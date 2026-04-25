import os
import json
import streamlit as st
import ollama
import chromadb
from datetime import datetime

# ─────────────────────────────────────────────
# Konfiguration
# ─────────────────────────────────────────────

MEMORY_FILE  = "memory.json"       # JSON-Backup (bleibt für Portabilität)
CHROMA_DIR   = "chroma_db"         # Vektordatenbank-Ordner
COLLECTION   = "memory"            # Name der chromadb-Collection

import yaml

def load_config() -> dict:
    if not os.path.exists("config.yaml"):
        return {
            "chat_model": "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b",
            "embed_model": "nomic-embed-text"
        }
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
CHAT_MODEL  = config["chat_model"]
EMBED_MODEL = config["embed_model"]

# Hybrid-Schwellwert: unter diesem Wert linearer Fallback statt Vektorsuche
VECTOR_MIN_ENTRIES = 15
# Anzahl semantisch ähnlicher Einträge die in den Prompt kommen
VECTOR_TOP_K = 5


# ─────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    """
    Generiert ein Embedding via Ollama (nomic-embed-text).
    Gibt None zurück bei Fehler – Aufrufer fällt dann auf linearen Modus zurück.
    """
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return resp["embedding"]
    except Exception as e:
        st.warning(f"Embedding-Fehler ({EMBED_MODEL}): {e}")
        return None


# ─────────────────────────────────────────────
# ChromaDB-Setup
# ─────────────────────────────────────────────

def get_collection() -> chromadb.Collection:
    """
    Gibt die ChromaDB-Collection zurück (gecacht in session_state).
    Legt Datenbank und Collection an falls noch nicht vorhanden.
    chromadb.PersistentClient speichert alles lokal in CHROMA_DIR –
    kein Server, keine Konfiguration nötig.
    """
    if "chroma_collection" not in st.session_state:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"}  # Kosinus-Distanz für Ähnlichkeitssuche
        )
        st.session_state.chroma_collection = collection
    return st.session_state.chroma_collection


def count_entries() -> int:
    """Gibt die Anzahl gespeicherter Einträge zurück."""
    return get_collection().count()


# ─────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────

def migrate_json_to_chroma(entries: list) -> None:
    """
    Einmalige Migration: Bestehende memory.json Einträge in ChromaDB übertragen.
    Verwendet timestamp als eindeutige ID – überspringt bereits vorhandene Einträge.
    """
    if not entries:
        return

    collection = get_collection()
    existing_ids = set(collection.get()["ids"])
    migrated = 0

    for entry in entries:
        entry_id = entry["timestamp"]
        if entry_id in existing_ids:
            continue

        embedding = get_embedding(entry["summary"])
        if embedding:
            collection.add(
                ids=[entry_id],
                embeddings=[embedding],
                documents=[entry["summary"]],
                metadatas=[{"timestamp": entry["timestamp"]}]
            )
        else:
            # Ohne Embedding: nur Text speichern, ChromaDB generiert intern einen Fallback
            collection.add(
                ids=[entry_id],
                documents=[entry["summary"]],
                metadatas=[{"timestamp": entry["timestamp"]}]
            )
        migrated += 1

    if migrated:
        st.toast(f"{migrated} ältere Einträge in Vektordatenbank migriert.")


# ─────────────────────────────────────────────
# Eintrag speichern
# ─────────────────────────────────────────────

def save_entry_to_chroma(timestamp: str, summary: str) -> bool:
    """
    Speichert einen neuen Eintrag mit Embedding in ChromaDB.
    Gibt True zurück bei Erfolg.
    """
    try:
        collection = get_collection()
        embedding = get_embedding(summary)
        if embedding:
            collection.add(
                ids=[timestamp],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[{"timestamp": timestamp}]
            )
        else:
            collection.add(
                ids=[timestamp],
                documents=[summary],
                metadatas=[{"timestamp": timestamp}]
            )
        return True
    except Exception as e:
        st.error(f"ChromaDB-Fehler beim Speichern: {e}")
        return False


# ─────────────────────────────────────────────
# Memory-Abruf
# ─────────────────────────────────────────────

def get_relevant_entries(query: str) -> list[dict]:
    """
    Hybrid-Strategie:
    - Unter VECTOR_MIN_ENTRIES: die letzten N Einträge chronologisch
      (zu wenig Daten für bedeutungsvolle Vektorsuche)
    - Ab VECTOR_MIN_ENTRIES: semantische Suche via Kosinus-Ähnlichkeit

    Gibt immer eine Liste von {"timestamp": ..., "summary": ...} zurück.
    """
    collection = get_collection()
    total = collection.count()

    if total == 0:
        return []

    # Linearer Fallback bei wenig Daten
    if total < VECTOR_MIN_ENTRIES:
        result = collection.get(include=["documents", "metadatas"])
        entries = [
            {"timestamp": m["timestamp"], "summary": d}
            for m, d in zip(result["metadatas"], result["documents"])
        ]
        # Chronologisch sortieren, neueste zuletzt
        entries.sort(key=lambda e: e["timestamp"])
        return entries[-VECTOR_TOP_K:]

    # Semantische Suche
    query_embedding = get_embedding(query)
    if query_embedding is None:
        # Embedding-Fehler → linearer Fallback
        result = collection.get(include=["documents", "metadatas"])
        entries = [
            {"timestamp": m["timestamp"], "summary": d}
            for m, d in zip(result["metadatas"], result["documents"])
        ]
        entries.sort(key=lambda e: e["timestamp"])
        return entries[-VECTOR_TOP_K:]

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(VECTOR_TOP_K, total),
        include=["documents", "metadatas", "distances"]
    )

    entries = [
        {"timestamp": m["timestamp"], "summary": d}
        for m, d in zip(result["metadatas"][0], result["documents"][0])
    ]
    return entries


# ─────────────────────────────────────────────
# JSON-Backup
# ─────────────────────────────────────────────

def load_memory_json() -> list:
    """
    Lädt Einträge aus memory.json.
    Wird nur für die einmalige Migration beim ersten Start benötigt.
    Unterstützt altes String-Format für Rückwärtskompatibilität.
    """
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "memory" in data and isinstance(data["memory"], str):
            if data["memory"].strip():
                return [{"timestamp": "Archiv (Alt)", "summary": data["memory"]}]
            return []
        return data.get("entries", [])
    except Exception as e:
        st.error(f"Fehler beim Laden der {MEMORY_FILE}: {e}")
        return []


def save_memory_json(entries: list) -> bool:
    """Schreibt alle Einträge als JSON-Backup (menschenlesbar, portabel)."""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern in {MEMORY_FILE}: {e}")
        return False


# ─────────────────────────────────────────────
# System-Prompt
# ─────────────────────────────────────────────

def build_system_prompt(relevant_entries: list[dict]) -> dict:
    """
    Baut den System-Prompt mit semantisch relevanten Erinnerungen.
    Explizite Verhaltensregeln statt vager Adjektive.
    """
    if relevant_entries:
        memory_text = "\n\n".join(
            [f"[{e['timestamp']}]\n{e['summary']}" for e in relevant_entries]
        )
    else:
        memory_text = "Keine früheren Gespräche vorhanden."

    return {
        "role": "system",
        "content": (
            "Du bist ein ruhiger, ehrlicher Reflexionsbegleiter. "
            "Du kennst den Nutzer aus vergangenen Gesprächen.\n\n"
            f"RELEVANTE ERINNERUNGEN (semantisch zum aktuellen Thema):\n{memory_text}\n\n"
            "VERHALTENSREGELN:\n"
            "1. Wenn der Nutzer einfach erzählt (kein explizites Fragezeichen): "
            "Validiere, spiegele, mach keinen Vorschlag und stelle KEINE Gegenfragen.\n"
            "2. Wenn der Nutzer explizit nach deiner Meinung fragt: "
            "Sei direkt, ungefiltert und konkret. Kein Herumreden.\n"
            "3. Wenn der Nutzer Hilfe oder Rat sucht: "
            "Ermutige konkret und handlungsorientiert.\n"
            "4. Beziehe dich auf die Erinnerungen NUR wenn es einen direkten, "
            "natürlichen Bezug zum aktuellen Thema gibt. Erzwinge keine Verbindungen.\n\n"
            "VERBOTEN:\n"
            "- 'Als KI habe ich keine Gefühle' oder ähnliche Distanzierungsfloskeln\n"
            "- Endlose Reflexionsfragen (maximal eine, wenn wirklich nötig)\n"
            "- Aufgesetzte Empathie-Phrasen wie 'Das klingt wirklich herausfordernd für dich'\n"
            "- Weitschweifige philosophische Schlüsse aus kleinen Alltagsdingen"
        )
    }


# ─────────────────────────────────────────────
# UI Setup
# ─────────────────────────────────────────────

st.set_page_config(page_title="Tell me your day", page_icon="📓")
st.title("Tell me your day 📓")

# Session State initialisieren
if "messages" not in st.session_state:
    st.session_state.messages = []
if "already_saved" not in st.session_state:
    st.session_state.already_saved = False
if "json_entries" not in st.session_state:
    st.session_state.json_entries = load_memory_json()

# ChromaDB initialisieren + einmalige Migration aus JSON
get_collection()
if not st.session_state.get("migration_done"):
    migrate_json_to_chroma(st.session_state.json_entries)
    st.session_state.migration_done = True

# Sidebar: Status
total = count_entries()
mode = "linear" if total < VECTOR_MIN_ENTRIES else "semantisch"
st.sidebar.caption(f"Gedächtnis: {total} Einträge · Modus: {mode}")
if total < VECTOR_MIN_ENTRIES:
    st.sidebar.caption(
        f"Vektorsuche aktiv ab {VECTOR_MIN_ENTRIES} Einträgen "
        f"({VECTOR_MIN_ENTRIES - total} fehlen noch)"
    )


# ─────────────────────────────────────────────
# Chat rendern
# ─────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Wie war dein Tag?"):

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Semantisch relevante Einträge abrufen
    relevant = get_relevant_entries(user_input)
    system_prompt = build_system_prompt(relevant)
    messages_for_llm = [system_prompt] + st.session_state.messages

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        try:
            for chunk in ollama.chat(model=CHAT_MODEL, messages=messages_for_llm, stream=True):
                if "message" in chunk and "content" in chunk["message"]:
                    full_response += chunk["message"]["content"]
                    response_placeholder.markdown(full_response + "▌")
            response_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})

        except Exception as e:
            response_placeholder.empty()
            st.error(
                f"Ollama nicht erreichbar. Läuft `ollama serve`?\n\n"
                f"Technischer Fehler: {e}"
            )


# ─────────────────────────────────────────────
# Gespräch beenden & Langzeitspeicherung
# ─────────────────────────────────────────────

st.divider()

if st.session_state.already_saved:
    st.success("Dieser Tag wurde bereits gespeichert. Starte die App neu für ein neues Gespräch.")

elif st.button("Gespräch beenden & Tag speichern"):
    if not st.session_state.messages:
        st.warning("Es gibt noch keinen Chatverlauf zum Speichern.")
    else:
        with st.spinner("Zusammenfassung wird generiert und gespeichert..."):
            history_text = "\n".join(
                [f"{m['role'].capitalize()}: {m['content']}" for m in st.session_state.messages]
            )
            summary_prompt = (
                f"Hier ist unser heutiges Gespräch:\n\n{history_text}\n\n"
                "Fasse DIESES Gespräch extrem kompakt in 3-4 Sätzen für die Langzeitspeicherung zusammen. "
                "Was war wichtig, wie war die Stimmung?\n\n"
                "ABSOLUTE REGELN:\n"
                "- Fasse ausschließlich die heutigen Inhalte zusammen.\n"
                "- Konstruiere KEINE Verbindungen zu Themen aus der Vergangenheit.\n"
                "- Bleib sachlich, direkt. Keine Poesie, keine Lebensweisheiten."
            )
            try:
                summary_response = ollama.chat(
                    model=CHAT_MODEL,
                    messages=[{"role": "user", "content": summary_prompt}],
                    options={"temperature": 0.1}
                )
                new_summary = summary_response["message"]["content"]
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # In ChromaDB speichern (mit Embedding)
                chroma_ok = save_entry_to_chroma(timestamp, new_summary)

                # JSON-Backup aktualisieren
                new_entry = {"timestamp": timestamp, "summary": new_summary}
                st.session_state.json_entries.append(new_entry)
                save_memory_json(st.session_state.json_entries)

                if chroma_ok:
                    st.session_state.already_saved = True
                    st.success("Erfolgreich gespeichert!")
                    st.info(f"**Neue Zusammenfassung:**\n{new_summary}")

            except Exception as e:
                st.error(f"Fehler bei der Zusammenfassung mit Ollama: {e}")