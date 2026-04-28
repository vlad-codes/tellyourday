# Tell Me Your Day 📓

Hi, this is my first GitHub project. It's vibe coded.

A local, private AI reflection companion. Runs entirely on your computer — no cloud, no API costs, no data sharing.

Built on **Gemma 4 E2B** — Google's most capable compact model. Multimodal, strong context handling, and fast enough for fluid conversation on consumer hardware.

## Requirements

- [Ollama](https://ollama.com) installed and running
- Python 3.10 or newer

## Setup

1. Pull the models:
```bash
ollama pull gemma4:e2b
ollama pull nomic-embed-text
```

2. Install dependencies:
```bash
pip3 install -r requirements.txt
```

3. Start the app:
```bash
python3 -m streamlit run tellyourday.py
```

> **macOS:** Always use `python3 -m streamlit run` instead of `streamlit run`

## How it works

Chat with Telmi — your personal reflection companion. Just type what's on your mind. No prompts needed.

When you're done, hit **End conversation & save**. Telmi summarizes your day and stores it locally. Over time, Telmi remembers past conversations and uses them to personalize responses.

Switch models anytime from the sidebar — any model you have installed in Ollama works.

## Privacy

Your conversations stay local. `memory.json` and `chroma_db/` are excluded from GitHub via `.gitignore`.