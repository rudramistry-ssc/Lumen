# Runtime and voice provenance

- Runtime: [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl),
  `piper-tts==1.8.0`, GPL-3.0-or-later per its release metadata and
  [COPYING](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING).
  The installed Windows wheel is `piper_tts-1.8.0-cp39-abi3-win_amd64.whl`, SHA256
  `5da9bfdb05dfe15da3536859d422e605483ffa6d2b3ec2c5b9593bae6b5aa6a4`.
- Voice repository: [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices),
  repository metadata declares MIT. Both selected artifacts are pinned to
  `5041a7a49ae5b3a0f30e6837769eb03fdbb231bd`. Specific model cards additionally
  describe dataset licensing and training provenance; these distinctions are
  retained rather than treating every upstream component as MIT.
- English [LJSpeech high model card](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/en/en_US/ljspeech/high/MODEL_CARD):
  LJ Speech dataset, public domain; trained from scratch, trainer reference
  Bryce Beattie. [LJ Speech](https://keithito.com/LJ-Speech-Dataset/) credits
  Keith Ito and Linda Johnson, with recordings from LibriVox. The card labels
  the artifact high quality but mentions medium-quality training settings;
  no independent quality rating is claimed here.
- French [SIWIS medium model card](https://huggingface.co/rhasspy/piper-voices/blob/5041a7a49ae5b3a0f30e6837769eb03fdbb231bd/fr/fr_FR/siwis/medium/MODEL_CARD):
  SIWIS dataset CC-BY 4.0; fine-tuned from the U.S. English Lessac medium voice.
  This documented training provenance is not omitted or recast as training
  from scratch. Dataset citation: Junichi Yamagishi, Pierre-Edouard Honnet,
  Philip Garner and Alexandros Lazaridis (2017), *The SIWIS French Speech
  Synthesis Database, 2016*, University of Edinburgh,
  [doi:10.7488/ds/1705](https://doi.org/10.7488/ds/1705).

The required model cards are downloaded and checksum-verified alongside the
voices. Preserve these upstream notices and dataset attribution with deployment
artifacts. These notes record upstream statements; they do not relicense the
engine, voices, datasets or their dependencies. No training datasets were downloaded.
