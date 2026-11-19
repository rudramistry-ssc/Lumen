# Lumen – offline demo (local GPU/CPU, Docker)

The finalized Lumen app – same frontend, same image-reading pipeline, same
confidence estimates and the same local Kokoro/Whisper speech – but the Qwen3-VL
vision model runs **on this computer** in Docker instead of on the HPC cluster.
It uses a GPU when one is usable (Intel Iris Xe / Arc, NVIDIA, AMD) and
otherwise falls back to the CPU. After the first setup it works with no network.

One photo → one Qwen3-VL request → extracted text, summary, detected language
and text/summary confidence estimates. Follow-up chat continues that same
conversation, so the model server reuses the image it already encoded. Read aloud (Kokoro) and the microphone (faster-whisper)
run locally in the app container. Vision output and answers are unverified;
check important information against the original image.

## Start it

### Windows (Docker Engine inside WSL2)

One-time: install Docker Engine in your WSL Ubuntu (Docker Desktop is not needed):

```powershell
wsl -d Ubuntu-24.04 -u root -- bash -c "curl -fsSL https://get.docker.com | sh && usermod -aG docker `$(id -nu 1000)"
```

On networks that inspect HTTPS (e.g. `GOC-GDC-ROOT-A`), that download fails until
WSL trusts the root certificate; see [Corporate networks](#corporate-networks).

Then, from this folder:

```powershell
.\start.ps1
```

### Linux

Install Docker Engine with the Compose plugin, then `./start.sh`.

Open **http://localhost:8000** when the script prints *Lumen is ready*, and
click **Open app**. The first run downloads about 2 GB of pinned models (plus
the runtime image for your GPU) and builds the app image; that takes a while on
a slow network. Later starts take seconds to a minute.

| Command | What it does |
|---|---|
| `.\start.ps1` / `./start.sh` | detect GPU, download/verify models, start |
| `... --offline` | restart with existing images/models, no network at all |
| `... --cpu` | skip GPU detection |
| `.\stop.ps1` | stop Lumen on Windows (models are kept) |
| `docker compose logs -f qwen` | watch the vision model (GPU offload, timings) |
| `docker compose down` | stop (models stay in the `models` volume) |

On Windows, `start.ps1` leaves one hidden `wsl.exe` process running. Without it,
WSL shuts the distribution down soon after the script ends and Lumen stops with
it. `stop.ps1` stops the containers and that process.

When the app starts, it sends the model one small image in each orientation in
the background, so the first real photo is not slowed by loading the vision
encoder or compiling GPU kernels (about 30–75 s after the model server is up).

Do **not** run `docker compose down -v` unless you want to delete the models.

## How the GPU is chosen

`start.sh` lists the GPUs that could work on this machine, then asks llama.cpp
itself, inside the exact Docker service that will run the model, which devices it
can use (`llama-server --list-devices`). The first GPU that llama.cpp actually
reports is used; if none works, the CPU is used. The choice is saved in `.env`
(`COMPOSE_FILE`), so plain `docker compose` commands keep using it.

| Machine | Compose files | llama.cpp v1.0.0 image |
|---|---|---|
| Windows + Intel GPU (WSL2) | `compose.yaml` + `compose.gpu-intel-wsl.yaml` | `server-intel` (SYCL) |
| Linux + Intel GPU | `compose.yaml` + `compose.gpu-intel.yaml` | `server-intel` (SYCL) |
| NVIDIA (Linux or WSL2) | `compose.yaml` + `compose.gpu-nvidia.yaml` | `server-cuda` |
| AMD / other on Linux | `compose.yaml` + `compose.gpu-vulkan.yaml` | `server-vulkan` |
| No usable GPU | `compose.yaml` | `server` (CPU) |

Every image is pinned by digest. NVIDIA additionally needs the NVIDIA Container
Toolkit on the host. Force a choice with `LUMEN_ACCELERATOR=cpu|intel-wsl|intel|nvidia|vulkan`.

## Settings

Set these in the shell before `start.ps1`/`start.sh` (they are remembered in `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `LUMEN_MODEL_SIZE` | `2B` | `8B` = Qwen3-VL-8B (closer to the HPC results; ~5.8 GB, slower, needs ~11 GB of memory) |
| `LUMEN_ACCELERATOR` | `auto` | see above |
| `LUMEN_CONTEXT` | `8192` | model context (tokens) for the image, history and answer |
| `LUMEN_IMAGE_PIXELS` | `500000` | image size sent to the model; larger reads small print better but is slower (~3 s per extra 100k pixels on Iris Xe) |
| `LUMEN_TIMEOUT_SECONDS` | `900` | longest wait for one model answer |
| `LUMEN_GPU_LAYERS` | all | lower it if the GPU runs out of memory |
| `APP_PORT` | `8000` | browser port (always bound to localhost only) |

WSL2 gives Docker half of the computer's memory by default. For the 8B model on a
16 GB laptop, raise it in `%UserProfile%\.wslconfig` (`[wsl2]` / `memory=12GB`),
run `wsl --shutdown`, then start again.

## What is the same as the HPC version, and what differs

Unchanged: the frontend (only the landing-page lines that named vLLM/the HPC GPU
node now say llama.cpp/local GPU), the confidence estimates, session limits,
the API seen by the browser, the Kokoro voice
(70/30 `af_heart`/`af_bella` blend, `ff_siwis` for French, Misaki pronunciation,
OpenVINO FP32 acceleration, clip caching) and faster-whisper speech input.

Different: the model is a 4-bit GGUF of Qwen3-VL (2B by default, 8B optional)
with an F16 vision projector, served by llama.cpp, instead of the full-precision
8B on vLLM. The 2B model is much faster but reads small or messy text less
reliably and its confidence estimates are less meaningful. To make it fast enough
locally, the image request uses a shorter prompt and a small flat JSON answer
(the unused uncertainty notes were dropped), photos are scaled to 0.5 MP, and
llama.cpp's DRY sampler stops the repetition loops a small model can fall into.
Chat questions continue the image conversation with one shared system prompt, so
the cached image is reused instead of being sent through the model again.

## Performance on the development laptop

Measured end to end through the app API on an Intel Core i7-1265U (Iris Xe,
16 GB RAM, on battery) with Qwen3-VL-2B on the Iris Xe GPU, nine demo photos,
after the startup warm-up:

| Step | Before | Now |
|---|---|---|
| Photo -> extracted text + summary | ~4 min (CPU) | 19-40 s, median 31 s |
| Follow-up chat answer | 1-2 min | 2-14 s, mostly 2-8 s |
| Model server start (GPU kernel compilation) | 1.5-4 min | ~2 min, then ~30-75 s background warm-up |

Where the time goes for a photo: reading the image is now ~10 s (about 500
image tokens); generating the transcription and summary at ~10 tokens/s is the
rest, so long notices take longest. On mains power the CPU and GPU run faster.

The Iris Xe through WSL2 can still hit a driver error (`DEVICE_LOST`) after many
requests; the `qwen` container then restarts the model and, after a second crash,
keeps serving on the CPU (several times slower), while the app repeats the
interrupted request. Restart the app (`.\stop.ps1`, then `.\start.ps1 --offline`)
to go back to the GPU.

Known limits of the 2B model: weaker reading of small, handwritten or messy text
(e.g. it misreads the corrected delivery note), and its confidence estimates
(e.g. 100/100) are not meaningful. The app retries once when the model's answer
breaks the strict JSON contract. Use `LUMEN_MODEL_SIZE=8B` on machines with more
memory for results closer to the HPC version.

## Corporate networks

Networks that inspect HTTPS (for example `GOC-GDC-ROOT-A`) make downloads fail
with `CERTIFICATE_VERIFY_FAILED` / `self-signed certificate in certificate chain`.
Put the PEM root certificate in `certs/` as a `.crt` file; the Docker build trusts
it automatically (verification stays on). `start.ps1` exports `GOC-GDC-ROOT-A`
from the Windows certificate store into `certs/` for you. For the one-time Docker
Engine install, WSL itself must trust it too:

```bash
sudo cp certs/*.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates
```

## What Docker runs

```text
Browser ─► api :8000 (localhost only)   FastAPI + frontend + Kokoro + faster-whisper
             └─► qwen :8091 (internal)    llama.cpp server, Qwen3-VL GGUF, GPU or CPU
models  (one-time setup)                  downloads + SHA256-verifies pinned files
volume  models                            read-only for api and qwen
```

Images, conversations and audio stay in memory and are never written to disk;
restarting the app clears them. Sessions expire after one idle hour. There is no
authentication: the port is bound to localhost for a local demo.

## Tests

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest ocr/tests -q          # simulated model server, no weights needed
node tests/frontend.test.cjs
node tests/speech.test.cjs
python tests/live_pipeline.py          # real end-to-end check against the running app
```

## Files

- `start.ps1`, `start.sh` – launchers with GPU detection and CPU fallback; `stop.ps1` stops Lumen on Windows.
- `compose.yaml`, `compose.gpu-*.yaml` – Docker services; one override per GPU type.
- `backend/` – FastAPI app, sessions, local speech, `provision.py` (model setup), `Dockerfile`.
- `frontend/` – the finalized UI.
- `ocr/` – image ingestion, Qwen prompt and response validation, chat.
- `certs/` – optional extra root certificates (ignored by Git).
- `demo images/`, `ocr/test images/` – photos for trying the app.
