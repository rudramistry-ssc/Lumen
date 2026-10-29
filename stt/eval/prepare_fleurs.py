"""Preparation only: pyarrow==26.0.0; bounded HTTP prefixes, not whole shards."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import wave
import struct

import pyarrow.parquet as pq
import pyarrow as pa
from array import array
import sys


class RemoteFile(io.RawIOBase):
    def __init__(self, url, size):
        self.url, self.size, self.pos, self.downloaded = url, size, 0, 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        return self.pos

    def read(self, size=-1):
        size = min(size if size >= 0 else self.size, self.size - self.pos)
        if size <= 0: return b""
        if size > 12 * 1024 * 1024: raise RuntimeError("Refusing a large dataset read")
        fetch = size
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{self.pos+fetch-1}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 206:
                raise RuntimeError("Server ignored byte range; refusing full dataset download")
            if not response.headers.get("Content-Range", "").startswith(f"bytes {self.pos}-"):
                raise RuntimeError("Unexpected HTTP range response")
            result = response.read(fetch + 1)
        if len(result) != fetch: raise RuntimeError("Unexpected byte range length")
        self.pos += size
        self.downloaded += len(result)
        return result


def dictionary_prefix(data, count=6, header_only=False):
    """Decode only first entries of a large Snappy PLAIN dictionary page.

    Compact Thrift PageHeader and raw Snappy are tiny wire formats. This avoids
    downloading the 400 MB audio dictionary merely to read six WAV entries.
    Fails closed if the pinned artifact changes format.
    """
    pos = 0
    def varint():
        nonlocal pos
        value = shift = 0
        while True:
            b = data[pos]; pos += 1
            value |= (b & 127) << shift
            if b < 128: return value
            shift += 7
    def structure():
        nonlocal pos
        fields, field = {}, 0
        while True:
            tag = data[pos]; pos += 1
            if tag == 0: return fields
            field = field + (tag >> 4) if tag >> 4 else (lambda n: (n >> 1) ^ -(n & 1))(varint())
            typ = tag & 15
            if typ in (4, 5, 6):
                n = varint(); value = (n >> 1) ^ -(n & 1)
            elif typ == 12: value = structure()
            elif typ in (1, 2): value = typ == 1
            elif typ == 8:
                length = varint(); value = data[pos:pos+length]; pos += length
            else: raise ValueError(f"Unexpected Thrift type {typ}")
            fields[field] = value
    header = structure()
    if header_only: return header, pos
    if header[1] != 2: raise ValueError("Expected dictionary page")
    varint()  # Snappy uncompressed length; intentionally do not expand entire page.
    decoded, entries, cursor = bytearray(), [], 0
    while len(entries) < count:
        tag = data[pos]; pos += 1
        kind = tag & 3
        if kind == 0:
            n = tag >> 2
            if n < 60: length = n + 1
            else:
                width = n - 59
                length = int.from_bytes(data[pos:pos+width], "little") + 1; pos += width
            if pos + length > len(data): raise ValueError("Dictionary prefix too short")
            decoded.extend(data[pos:pos+length]); pos += length
        else:
            if kind == 1:
                length = 4 + ((tag >> 2) & 7)
                offset = ((tag & 224) << 3) | data[pos]; pos += 1
            else:
                width = 2 if kind == 2 else 4
                length = 1 + (tag >> 2)
                offset = int.from_bytes(data[pos:pos+width], "little"); pos += width
            if not 0 < offset <= len(decoded): raise ValueError("Invalid Snappy copy")
            for _ in range(length): decoded.append(decoded[-offset])
        while cursor + 4 <= len(decoded) and len(entries) < count:
            length = struct.unpack_from("<I", decoded, cursor)[0]
            if cursor + 4 + length > len(decoded): break
            entries.append(bytes(decoded[cursor+4:cursor+4+length])); cursor += 4 + length
    return entries


def main():
    output = Path(__file__).parent / "data"
    output.mkdir(exist_ok=True)
    existing = output / "manifest.json"
    if existing.exists():
        manifest = json.loads(existing.read_text(encoding="utf-8"))
        if len(manifest["samples"]) == 12 and all(
            (output/x["file"]).is_file() and hashlib.sha256((output/x["file"]).read_bytes()).hexdigest() == x["sha256"]
            for x in manifest["samples"]):
            print("Reusing 12 verified local samples; no downloads")
            return
    revision = "168de341b3db6859a9bac1c50a2ef5e3b47647e0"
    manifest = {"dataset": "google/fleurs", "revision": revision, "split": "test",
                "license": "CC-BY-4.0", "attribution": "Google FLEURS contributors, Conneau et al. (2022)",
                "source": "https://huggingface.co/datasets/google/fleurs", "samples": [], "downloaded_bytes": {}}
    for lang in ["en_us", "fr_fr"]:
        path = f"{lang}/test/0000.parquet"
        metadata = json.load(urllib.request.urlopen(f"https://huggingface.co/api/datasets/google/fleurs/tree/{revision}/{lang}/test", timeout=30))[0]
        remote = RemoteFile(f"https://huggingface.co/datasets/google/fleurs/resolve/{revision}/{path}", metadata["size"])
        parquet = pq.ParquetFile(remote)
        print(lang, "row groups", parquet.num_row_groups, "first rows", parquet.metadata.row_group(0).num_rows, flush=True)
        columns = ["id", "path", "transcription", "raw_transcription"]
        rows = parquet.read_row_group(0, columns=columns).slice(0, 6).to_pylist()
        chunk = next(parquet.metadata.row_group(0).column(i) for i in range(parquet.metadata.row_group(0).num_columns)
                     if parquet.metadata.row_group(0).column(i).path_in_schema == "audio.bytes")
        remote.seek(chunk.dictionary_page_offset)
        audios = dictionary_prefix(remote.read(8 * 1024 * 1024))
        remote.seek(chunk.data_page_offset)
        encoded = remote.read(min(4096, chunk.total_compressed_size - (chunk.data_page_offset - chunk.dictionary_page_offset)))
        header, start = dictionary_prefix(encoded, header_only=True)
        page = bytes(pa.Codec("snappy").decompress(encoded[start:start+header[3]], header[2]))
        # All first six values must be non-null, dictionary IDs 0..5. Fail rather
        # than associating an unchecked dictionary entry with a reference.
        cursor = 4 + int.from_bytes(page[:4], "little")  # definition levels
        width = page[cursor]; cursor += 1
        run = page[cursor]; cursor += 1
        if not run & 1: raise ValueError("Unexpected dictionary index encoding")
        packed = int.from_bytes(page[cursor:cursor+((6*width+7)//8)], "little")
        ids = [(packed >> (i*width)) & ((1 << width)-1) for i in range(6)]
        if ids != list(range(6)): raise ValueError(f"Unexpected dictionary ordering: {ids}")
        for index, row in enumerate(rows):
            audio = audios[index]
            source_hash = hashlib.sha256(audio).hexdigest()
            # FLEURS stores float32 WAV. Convert explicitly to signed PCM16,
            # clipping [-1,1], retaining the original 16 kHz and sample count.
            if audio[:4] != b"RIFF": raise ValueError("Expected source WAV")
            offset, fmt, raw = 12, None, None
            while offset + 8 <= len(audio):
                name, size = audio[offset:offset+4], int.from_bytes(audio[offset+4:offset+8], "little")
                payload = audio[offset+8:offset+8+size]
                if name == b"fmt ": fmt = struct.unpack_from("<HHIIHH", payload)
                if name == b"data": raw = payload
                offset += 8 + size + size % 2
            if fmt[0:3] != (3, 1, 16000) or fmt[5] != 32: raise ValueError(f"Unexpected source format {fmt}")
            floats = array("f", raw)
            if sys.byteorder != "little": floats.byteswap()
            pcm = array("h", (max(-32768, min(32767, round(x*32768))) for x in floats))
            if sys.byteorder != "little": pcm.byteswap()
            output_audio = io.BytesIO()
            with wave.open(output_audio, "wb") as wav:
                wav.setparams((1, 2, 16000, 0, "NONE", "not compressed")); wav.writeframes(pcm.tobytes())
            audio = output_audio.getvalue()
            name = f"{lang}-{index}-{row['id']}.wav"
            with wave.open(io.BytesIO(audio), "rb") as wav:
                fmt = [wav.getframerate(), wav.getnchannels(), wav.getsampwidth()]
            if fmt != [16000, 1, 2]: raise ValueError(f"Unexpected source audio: {fmt}")
            (output / name).write_bytes(audio)
            manifest["samples"].append({"file": name, "id": row["id"], "row": index,
                 "config": lang, "language": lang[:2], "reference": row["raw_transcription"],
                 "normalized_reference": row["transcription"], "source_audio": row["path"],
                 "source_sha256": source_hash, "sha256": hashlib.sha256(audio).hexdigest(),
                 "conversion": "16 kHz mono float32 WAV to PCM16; round(x*32768), clip signed16; no resampling"})
        manifest["downloaded_bytes"][lang] = remote.downloaded
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(lang, "bytes fetched", remote.downloaded, flush=True)


if __name__ == "__main__": main()
