# Tell Me Your Day 📓

Ein lokaler, privater KI-Reflexionsbegleiter. Läuft vollständig auf deinem Computer – keine Cloud, keine API-Kosten, keine Datenweitergabe.

## Voraussetzungen

- [Ollama](https://ollama.com) installiert und gestartet
- Python 3.10 oder neuer

## Setup

1. Modelle laden:
```bash
ollama pull nomic-embed-text
ollama pull <dein-modell>
```

2. Dependencies installieren:
```bash
pip3 install -r requirements.txt
```

3. Modell in `config.yaml` eintragen:
```yaml
chat_model: "dein-modell-name"
embed_model: "nomic-embed-text"
```

4. App starten:
```bash
python3 -m streamlit run tellyourday.py
```

> **macOS:** Verwende immer `python3 -m streamlit run` statt `streamlit run`

## Datenschutz

Deine Gespräche bleiben lokal. `memory.json` und `chroma_db/` werden nicht auf GitHub hochgeladen.
