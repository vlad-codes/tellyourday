import os
import json
import yaml
import streamlit as st
import ollama
import chromadb
from datetime import datetime

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MEMORY_FILE = "memory.json"   # JSON backup (kept for portability)
CHROMA_DIR  = "chroma_db"     # Vector database folder
COLLECTION  = "memory"        # ChromaDB collection name

# Below this threshold: linear fallback instead of vector search
VECTOR_MIN_ENTRIES = 15
# Number of semantically similar entries injected into the prompt
VECTOR_TOP_K = 5


def load_config() -> dict:
    """
    Loads model config from config.yaml.
    Falls back to defaults if the file doesn't exist.
    """
    defaults = {
        "chat_model": "gemma4:e2b",
        "embed_model": "nomic-embed-text"
    }
    if not os.path.exists("config.yaml"):
        return defaults
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return {**defaults, **config}
    except Exception:
        return defaults

config     = load_config()
CHAT_MODEL  = config["chat_model"]
EMBED_MODEL = config["embed_model"]


# ─────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    """
    Generates an embedding via Ollama (nomic-embed-text).
    Returns None on error — caller falls back to linear mode.
    """
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return resp["embedding"]
    except Exception as e:
        st.warning(f"Embedding error ({EMBED_MODEL}): {e}")
        return None


# ─────────────────────────────────────────────
# ChromaDB setup
# ─────────────────────────────────────────────

def get_collection() -> chromadb.Collection:
    """
    Returns the ChromaDB collection (cached in session_state).
    Creates the database and collection if they don't exist yet.
    PersistentClient stores everything locally in CHROMA_DIR —
    no server, no configuration needed.
    """
    if "chroma_collection" not in st.session_state:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"}  # cosine distance for similarity search
        )
        st.session_state.chroma_collection = collection
    return st.session_state.chroma_collection


def count_entries() -> int:
    """Returns the total number of stored memory entries."""
    return get_collection().count()


# ─────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────

def migrate_json_to_chroma(entries: list) -> None:
    """
    One-time migration: transfers existing memory.json entries into ChromaDB.
    Uses timestamp as unique ID — skips entries that already exist.
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
            # No embedding available: store text only, ChromaDB handles internally
            collection.add(
                ids=[entry_id],
                documents=[entry["summary"]],
                metadatas=[{"timestamp": entry["timestamp"]}]
            )
        migrated += 1

    if migrated:
        st.toast(f"{migrated} older entries migrated into vector database.")


# ─────────────────────────────────────────────
# Save entry
# ─────────────────────────────────────────────

def save_entry_to_chroma(timestamp: str, summary: str) -> bool:
    """
    Saves a new entry with embedding into ChromaDB.
    Returns True on success.
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
        st.error(f"ChromaDB error while saving: {e}")
        return False


# ─────────────────────────────────────────────
# Memory retrieval
# ─────────────────────────────────────────────

def get_relevant_entries(query: str) -> list[dict]:
    """
    Hybrid strategy:
    - Below VECTOR_MIN_ENTRIES: returns the last N entries chronologically
      (not enough data for meaningful vector search)
    - At or above VECTOR_MIN_ENTRIES: semantic search via cosine similarity

    Always returns a list of {"timestamp": ..., "summary": ...}
    """
    collection = get_collection()
    total = collection.count()

    if total == 0:
        return []

    # Linear fallback for small datasets
    if total < VECTOR_MIN_ENTRIES:
        result = collection.get(include=["documents", "metadatas"])
        entries = [
            {"timestamp": m["timestamp"], "summary": d}
            for m, d in zip(result["metadatas"], result["documents"])
        ]
        entries.sort(key=lambda e: e["timestamp"])
        return entries[-VECTOR_TOP_K:]

    # Semantic search
    query_embedding = get_embedding(query)
    if query_embedding is None:
        # Embedding error → linear fallback
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
# JSON backup
# ─────────────────────────────────────────────

def load_memory_json() -> list:
    """
    Loads entries from memory.json.
    Only used for the one-time migration on first launch.
    Supports legacy string format for backwards compatibility.
    """
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "memory" in data and isinstance(data["memory"], str):
            if data["memory"].strip():
                return [{"timestamp": "Archive (legacy)", "summary": data["memory"]}]
            return []
        return data.get("entries", [])
    except Exception as e:
        st.error(f"Error loading {MEMORY_FILE}: {e}")
        return []


def save_memory_json(entries: list) -> bool:
    """Writes all entries as a human-readable JSON backup."""
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"Error saving {MEMORY_FILE}: {e}")
        return False


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

def build_system_prompt(relevant_entries: list[dict]) -> dict:
    """
    Builds the system prompt with semantically relevant memories.
    Uses explicit behavioral rules instead of vague adjectives.
    """
    if relevant_entries:
        memory_text = "\n\n".join(
            [f"[{e['timestamp']}]\n{e['summary']}" for e in relevant_entries]
        )
    else:
        memory_text = "No previous conversations on record."

    return {
        "role": "system",
        "content": (
            "You are a calm, honest reflection companion. "
            "You know the user from past conversations.\n\n"
            f"RELEVANT MEMORIES (semantically matched to current topic):\n{memory_text}\n\n"
            "BEHAVIORAL RULES:\n"
            "1. If the user is simply sharing (no explicit question mark): "
            "validate and mirror what they said. Make no suggestions and ask NO follow-up questions.\n"
            "2. If the user explicitly asks for your opinion: "
            "be direct, unfiltered, and concrete. No beating around the bush.\n"
            "3. If the user is looking for help or advice: "
            "encourage them concretely and action-oriented.\n"
            "4. Only reference memories when there is a direct, natural connection "
            "to the current topic. Never force connections.\n\n"
            "FORBIDDEN:\n"
            "- 'As an AI I have no feelings' or similar distancing phrases\n"
            "- Endless follow-up questions (one maximum, only if truly necessary)\n"
            "- Hollow empathy phrases like 'That sounds really challenging for you'\n"
            "- Sweeping philosophical conclusions drawn from small everyday things"
        )
    }


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────

st.set_page_config(page_title="Tell me your day", page_icon="📓")
st.title("Tell me your day 📓")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "already_saved" not in st.session_state:
    st.session_state.already_saved = False
if "json_entries" not in st.session_state:
    st.session_state.json_entries = load_memory_json()

# Initialize ChromaDB + one-time migration from JSON
get_collection()
if not st.session_state.get("migration_done"):
    migrate_json_to_chroma(st.session_state.json_entries)
    st.session_state.migration_done = True

# Sidebar status
total = count_entries()
mode = "linear" if total < VECTOR_MIN_ENTRIES else "semantic"
st.sidebar.caption(f"Memory: {total} entries · Mode: {mode}")
if total < VECTOR_MIN_ENTRIES:
    st.sidebar.caption(
        f"Vector search active from {VECTOR_MIN_ENTRIES} entries "
        f"({VECTOR_MIN_ENTRIES - total} to go)"
    )


# ─────────────────────────────────────────────
# Render chat
# ─────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("How was your day?"):

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Retrieve semantically relevant entries
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
                f"Cannot reach Ollama. Is `ollama serve` running?\n\n"
                f"Error: {e}"
            )


# ─────────────────────────────────────────────
# End session & save
# ─────────────────────────────────────────────

st.divider()

if st.session_state.already_saved:
    st.success("Today's session has already been saved. Restart the app to begin a new conversation.")

elif st.button("End conversation & save today"):
    if not st.session_state.messages:
        st.warning("No conversation to save yet.")
    else:
        with st.spinner("Generating summary and saving..."):
            history_text = "\n".join(
                [f"{m['role'].capitalize()}: {m['content']}" for m in st.session_state.messages]
            )
            summary_prompt = (
                f"Here is our conversation from today:\n\n{history_text}\n\n"
                "Summarize THIS conversation in 3-4 sentences for long-term storage. "
                "What was important, what was the mood?\n\n"
                "ABSOLUTE RULES:\n"
                "- Summarize only today's content.\n"
                "- Do NOT construct connections to past topics.\n"
                "- Stay factual and direct. No poetry, no life lessons."
            )
            try:
                summary_response = ollama.chat(
                    model=CHAT_MODEL,
                    messages=[{"role": "user", "content": summary_prompt}],
                    options={"temperature": 0.1}
                )
                new_summary = summary_response["message"]["content"]
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Save to ChromaDB (with embedding)
                chroma_ok = save_entry_to_chroma(timestamp, new_summary)

                # Update JSON backup
                new_entry = {"timestamp": timestamp, "summary": new_summary}
                st.session_state.json_entries.append(new_entry)
                save_memory_json(st.session_state.json_entries)

                if chroma_ok:
                    st.session_state.already_saved = True
                    st.success("Saved successfully!")
                    st.info(f"**Summary:**\n{new_summary}")

            except Exception as e:
                st.error(f"Error generating summary: {e}")