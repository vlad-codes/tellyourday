# Telmi — Your Private AI Companion

*Tell your day. Work through your mind.*

| Setup | Onboarding | Your Day | Your Mind | Archive |
| :---: | :---: | :---: | :---: | :---: |
| <a href="./screenshots/ollama_onboarding.png"><img src="./screenshots/ollama_onboarding.png" width="160"></a> | <a href="./screenshots/model_onboarding.png"><img src="./screenshots/model_onboarding.png" width="160"></a> | <a href="./screenshots/yourday_chat.png"><img src="./screenshots/yourday_chat.png" width="160"></a> | <a href="./screenshots/yourmind_chat.png"><img src="./screenshots/yourmind_chat.png" width="160"></a> | <a href="./screenshots/archive_search.png"><img src="./screenshots/archive_search.png" width="160"></a> |

Your thoughts stay on your machine. No cloud. No subscription. No one reading your diary.

Telmi is a native macOS companion powered by local AI. Talk about your day, work through what's on your mind, tell it your secrets. Telmi listens, remembers, and gets better at knowing you — without sending a single word to a server.

---

## Two modes

**📓 Your Day** — tell Telmi what's been going on. Whatever's on your mind, big or small. Telmi listens and remembers.

**💭 Your Mind** — bring something you haven't quite worked out. A decision, a situation, something you keep circling. Telmi thinks alongside you.

---

## What makes it different

- **Fully local.** Everything runs on your Mac. Nothing is ever sent to a server.
- **No subscription.** No API key. No usage limits. You own the models, you own the data.
- **Runs on 8 GB RAM.** No GPU required. Works on everyday hardware.
- **Remembers you.** Past conversations are stored and retrieved — Telmi doesn't start from scratch every time.
- **Auto-saves.** No save button. Start a new conversation or close the app — Telmi remembers automatically.
- **Life Dashboard.** A calendar showing every day you've talked, streaks, and monthly stats — built into the sidebar.
- **Open models.** Switch between any model you have installed in Ollama. Upgrade when you want.

---

## Download

**→ [Latest release](../../releases/latest)** — download the `.dmg`, open it, drag Telmi to Applications.

> macOS only. Apple Silicon (M1 and later).

> **"Telmi is damaged and can't be opened"** — this is a Gatekeeper warning because the app isn't signed with an Apple certificate. Run this once in Terminal, then open normally:
> ```bash
> xattr -cr /Applications/Telmi.app
> ```

---

## Setup

Telmi guides you through setup on first launch. The only prerequisite is Ollama.

**1. Install [Ollama](https://ollama.com)**

Download the Ollama desktop app — it starts automatically in the background.

**2. Open Telmi**

The app detects whether Ollama is running and whether any models are installed. If something is missing, it tells you exactly what to do.

**Recommended models by RAM:**

| RAM    | Model            | Size   | Notes |
|--------|------------------|--------|-------|
| 8 GB   | `llama3.2:3b`    | 2.0 GB | Good starting point |
| 16 GB  | `llama3.1:8b`    | 4.7 GB | Noticeably better responses |
| 32 GB+ | `qwen2.5:32b`    | 20 GB  | Best experience |

**Optional — semantic search** (activates automatically once you have 15+ entries):
```bash
ollama pull nomic-embed-text
```

---

## Build from source

Requirements: [Node.js](https://nodejs.org), [Rust](https://rustup.rs), [Python 3.11+](https://python.org), [Ollama](https://ollama.com)

```bash
# 1. Clone
git clone https://github.com/vlad-codes/telmi-journal.git
cd telmi-journal

# 2. Python dependencies
pip3 install -r requirements.txt

# 3. Build the backend binary
pyinstaller telmi-backend.spec --distpath frontend/src-tauri/binaries --noconfirm

# 4. Dev mode (two terminals)
uvicorn api:app --reload          # terminal 1 — backend
cd frontend && npm run tauri dev  # terminal 2 — app

# 5. Release build
cd frontend && npm run tauri build
# DMG output: frontend/src-tauri/target/release/bundle/dmg/
```

---

## Privacy

All data lives exclusively on your machine:

| File | Contents |
|------|----------|
| `memory.json` | Conversations + chat history |
| `profile.json` | Notes Telmi builds about you over time |
| `chroma_db/` | Vector embeddings for semantic search |

None of these are included in this repository. Telmi never phones home.

---

## License

MIT — see [LICENSE](LICENSE).
