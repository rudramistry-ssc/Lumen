# CanAI_Team_E

Lumen: point a camera at a sign or notice, get the text, hear it read aloud in English or French, and ask questions about it.

| folder       | what it is                                  | how to run                    |
|--------------|---------------------------------------------|-------------------------------|
| `frontend/`  | the web UI (plain HTML/CSS/JS)              | see [frontend/README.md](frontend/README.md) |
| `backend/`   | FastAPI API: sessions, uploads, chat        | see [backend/README.md](backend/README.md)   |

## Run the frontend

```bash
cd frontend
python3 -m http.server 5500
```

Open http://localhost:5500. It runs in **demo mode** with fake responses and is not connected to the backend yet. See [frontend/README.md](frontend/README.md#current-status-demo-mode) for what's needed to connect them.
