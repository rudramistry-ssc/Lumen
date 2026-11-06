# Lumen - CanAI Team E

Lumen is an offline accessibility proof of concept for reading signs and
notices aloud and answering questions in English and French.

## Hackathon Demo

The integrated hackathon implementation currently lives on
[`integration/offline-poc`](https://github.com/rudramistry-ssc/CanAI_Team_E/tree/integration/offline-poc),
not on `main`.

It has not yet been merged while we complete more thorough testing,
develop additional features, and review the project's organization.
Treat it as an experimental local demo, not a production-ready application.

## Setup

Install Git and Docker with Docker Compose, then run:

```bash
git clone --branch integration/offline-poc https://github.com/rudramistry-ssc/CanAI_Team_E.git
cd CanAI_Team_E
docker compose up --build
```

Open http://localhost:8000 once the API is healthy.

First setup requires internet to build dependencies and download about
1.9 GB of models. Allocate at least 8 GB RAM to Docker (12 GB recommended)
and roughly 10 GB of free disk space. CPU processing can take minutes per photo.

For complete setup instructions, offline restart commands, troubleshooting,
and known limitations, see the
[PoC README](https://github.com/rudramistry-ssc/CanAI_Team_E/blob/integration/offline-poc/README.md).
