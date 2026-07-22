# Mission Operations Center — Setup Guide

A satellite Mission Operations Center dashboard.
**Backend:** Python + Flask (serves the data API).
**Frontend:** React + Vite (the dashboard UI).

You run **two things at once**: the backend API and the frontend UI.

---

## 1. Prerequisites (install these first)

| Tool | Check it's installed | Get it |
|------|----------------------|--------|
| **Python 3.10+** | `python3 --version` | https://www.python.org/downloads/ |
| **Node.js 18+** | `node --version` | https://nodejs.org (LTS) |

> If a command says "command not found", that tool isn't installed yet.

---

## 2. First-time setup

Unzip the project, then open a terminal **inside the project folder**:

```bash
cd "Vajeed Project"     # the folder you unzipped
```

> ⚠️ Ignore any `.venv` and `node_modules` folders that came in the zip —
> they only work on the original computer. The steps below rebuild them.

### a) Backend (Python)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### b) Frontend (Node)

```bash
npm install
```

---

## 3. Run the app (every time)

Open **two terminal windows/tabs**, both in the project folder.

**Terminal 1 — backend API:**
```bash
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python api.py
```
Leave it running. It serves data at http://127.0.0.1:5001

**Terminal 2 — frontend UI:**
```bash
npm run dev
```

Then open the URL it prints (usually **http://127.0.0.1:5173**) in a browser.

---

## 4. Stopping

Press `Ctrl + C` in each terminal.

---

## Troubleshooting

- **UI loads but says "Failed to load dashboard"** → the backend (Terminal 1) isn't
  running, or crashed. Make sure `python api.py` is still running.
- **`pip install` fails** → make sure the venv is activated first (you should see
  `(.venv)` at the start of your terminal line).
- **Port already in use** → close any old copies, or Vite will pick the next free
  port and print the new URL.
- **`python` not found on Windows** → try `py` instead of `python3`.
