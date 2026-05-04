import os
import json
import ollama
import chromadb
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

_DATA_DIR          = os.environ.get("TELMI_DATA_DIR", ".")
MEMORY_FILE        = os.path.join(_DATA_DIR, "memory.json")
PROFILE_FILE       = os.path.join(_DATA_DIR, "profile.json")
CHROMA_DIR         = os.path.join(_DATA_DIR, "chroma_db")
COLLECTION         = "memory"
EMBED_MODEL        = "nomic-embed-text"
VECTOR_MIN_ENTRIES = 15
VECTOR_TOP_K       = 5
# Cosine distance threshold for /search (0 = identical, 1 = orthogonal, 2 = opposite).
# nomic-embed-text typically scores relevant hits below 0.50; raise to 0.65 for looser results.
SEARCH_DISTANCE_THRESHOLD = 0.50


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_collection()  # warm up ChromaDB on startup
    yield

app = FastAPI(title="Telmi API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    user_input: str
    mode: str           # "day" | "mind"
    history: list[ChatMessage]
    selected_model: str

class SaveRequest(BaseModel):
    mode: str
    history: list[ChatMessage]
    selected_model: str

class SaveResponse(BaseModel):
    title: str
    summary: str
    timestamp: str
    profile_update: str | None = None

class Entry(BaseModel):
    timestamp: str
    title: str
    summary: str
    has_chat: bool = False

class UpdateEntryRequest(BaseModel):
    title: str | None = None
    summary: str | None = None

class CalendarDay(BaseModel):
    date: str       # YYYY-MM-DD
    timestamp: str  # full "YYYY-MM-DD HH:MM:SS"
    title: str
    summary: str

class StatsResponse(BaseModel):
    streak: int
    total: int
    this_month: int
    avg_per_week: float
    achievements: list[str]


# ─────────────────────────────────────────────
# ChromaDB singleton
# ─────────────────────────────────────────────

_chroma_collection: chromadb.Collection | None = None

def get_collection() -> chromadb.Collection:
    global _chroma_collection
    if _chroma_collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        _chroma_collection = client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"}
        )
    return _chroma_collection


# ─────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return resp["embedding"]
    except Exception:
        return None


# ─────────────────────────────────────────────
# ChromaDB operations
# ─────────────────────────────────────────────

def get_all_entries() -> list[dict]:
    result = get_collection().get(include=["documents", "metadatas"])
    chroma_entries = {}
    for m, d in zip(result["metadatas"], result["documents"]):
        ts = m.get("timestamp", "")
        chroma_entries[ts] = {"timestamp": ts, "title": m.get("title", ""), "summary": d}

    # Merge has_chat flag from memory.json (ChromaDB doesn't store it)
    json_entries = {e["timestamp"]: e for e in load_memory_json()}
    entries = []
    for ts, entry in chroma_entries.items():
        has_chat = bool(json_entries.get(ts, {}).get("history"))
        entries.append({**entry, "has_chat": has_chat})
    entries.sort(key=lambda e: e["timestamp"])
    return entries


def get_relevant_entries(query: str) -> list[dict]:
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return []

    if total < VECTOR_MIN_ENTRIES:
        result = collection.get(include=["documents", "metadatas"])
        entries = [{"timestamp": m["timestamp"], "summary": d}
                   for m, d in zip(result["metadatas"], result["documents"])]
        entries.sort(key=lambda e: e["timestamp"])
        return entries[-VECTOR_TOP_K:]

    query_embedding = get_embedding(query)
    if query_embedding is None:
        result = collection.get(include=["documents", "metadatas"])
        entries = [{"timestamp": m["timestamp"], "summary": d}
                   for m, d in zip(result["metadatas"], result["documents"])]
        entries.sort(key=lambda e: e["timestamp"])
        return entries[-VECTOR_TOP_K:]

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(VECTOR_TOP_K, total),
        include=["documents", "metadatas", "distances"],
    )
    return [{"timestamp": m["timestamp"], "summary": d}
            for m, d in zip(result["metadatas"][0], result["documents"][0])]


def save_entry_to_chroma(timestamp: str, summary: str, title: str) -> bool:
    try:
        collection = get_collection()
        embedding  = get_embedding(summary)
        metadata   = {"timestamp": timestamp, "title": title}
        if embedding:
            collection.add(ids=[timestamp], embeddings=[embedding],
                           documents=[summary], metadatas=[metadata])
        else:
            collection.add(ids=[timestamp], documents=[summary], metadatas=[metadata])
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# JSON I/O  — format must stay identical to telmi.py
# ─────────────────────────────────────────────

def load_memory_json() -> list:
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # legacy format: {"memory": "<plain text>"}
        if isinstance(data, dict) and "memory" in data and isinstance(data["memory"], str):
            if data["memory"].strip():
                return [{"timestamp": "Archive (legacy)", "title": "", "summary": data["memory"]}]
            return []
        return data.get("entries", [])
    except Exception:
        return []


def save_memory_json(entries: list) -> bool:
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


def load_profile() -> str:
    if not os.path.exists(PROFILE_FILE):
        return ""
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("notes", "")
    except Exception:
        return ""


def save_profile(notes: str) -> bool:
    try:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "notes": notes,
            }, f, ensure_ascii=False, indent=4)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────

def build_system_prompt(relevant_entries: list[dict], mode: str = "day") -> dict:
    if relevant_entries:
        memory_text = "\n\n".join(
            [f"[{e['timestamp']}]\n{e['summary']}" for e in relevant_entries]
        )
    else:
        memory_text = "No previous conversations on record."

    base = (
        "You are Telmi — a warm, calm presence who genuinely cares about this person.\n"
        "You have studied humans. Most people don't need much to live well — usually just clarity, "
        "or someone who truly listens. You are never alarmed. You always see a way forward.\n"
        "You are fully on this person's side. You believe in them even when they don't.\n\n"
        "Always respond in the same language the person is writing in.\n\n"
        "Rules:\n"
        "1. Be direct and natural. 2-3 sentences. No filler, no preamble.\n"
        "2. Never repeat back what the person said. Just respond to it.\n"
        "3. Maximum one question per response. Often zero.\n"
        "4. No clinical language. Never \"How does that make you feel?\"\n"
        "5. Never say \"That sounds really hard\" or \"I can imagine how difficult.\"\n"
        "6. Never mention being an AI.\n"
        "7. When someone shares good news: be genuinely interested. Reflect something back about them.\n"
        "8. When someone struggles: stay calm and steady. You are not worried — you know they can handle it.\n\n"
    )

    if mode == "day":
        memory_section = (
            f"PAST CONVERSATIONS:\n{memory_text}\n"
            "Only reference this if there is a direct echo in what they just said.\n\n"
        ) if relevant_entries else ""
        return {
            "role": "system",
            "content": base + memory_section,
        }
    else:  # mind
        profile_text = load_profile()
        profile_section = f"NOTES ON THIS PERSON:\n{profile_text}\n\n" if profile_text else ""
        memory_section = (
            f"PAST SESSIONS:\n{memory_text}\n"
            "Only reference this if there is a direct echo in what they just said.\n\n"
        ) if relevant_entries else ""
        return {
            "role": "system",
            "content": (
                base
                + "In this mode the person wants to think something through — a decision, a situation, "
                "something unresolved. Be a thinking partner. Help them get clearer, not just heard. "
                "Follow their thinking, ask the question that opens the next step, "
                "and when something useful comes into view, reflect it back gently. "
                "You are not challenging them — you are thinking alongside them.\n\n"
                + profile_section
                + memory_section
            ),
        }


# ─────────────────────────────────────────────
# Profile update (mind mode)
# ─────────────────────────────────────────────

def update_profile_from_session(history_text: str, summary: str, selected_model: str) -> str | None:
    existing = load_profile()
    profile_context = (
        f"EXISTING PROFILE NOTES:\n{existing}\n\n" if existing
        else "EXISTING PROFILE NOTES: None yet.\n\n"
    )
    prompt = (
        "You are keeping factual notes about a person based on their journal conversations. "
        "Your only job is to record what they explicitly said or directly demonstrated — nothing more.\n\n"
        f"{profile_context}"
        f"SESSION SUMMARY:\n{summary}\n\n"
        f"FULL SESSION TRANSCRIPT:\n{history_text}\n\n"
        "Write down observations from this session that are NOT already in the existing profile.\n\n"
        "STRICT EVIDENCE RULE:\n"
        "Every single observation you write must be directly traceable to something the user "
        "said or did in the transcript above. If you cannot point to a specific line or statement "
        "that supports it, do not write it. No exceptions.\n\n"
        "WHAT TO NOTE (only if the user explicitly expressed it):\n"
        "- Things the user stated as facts about their life, relationships, or situation\n"
        "- Emotions or reactions the user named themselves\n"
        "- Patterns or behaviors the user described themselves doing\n"
        "- Beliefs or values the user expressed in their own words\n"
        "- Conflicts or tensions the user explicitly mentioned\n\n"
        "STRICTLY FORBIDDEN:\n"
        "- Psychological interpretations not stated by the user ('You seem to fear...')\n"
        "- Inferences about underlying causes, motives, or subconscious patterns\n"
        "- Assumptions about what the user 'really' feels or believes\n"
        "- Filling gaps with plausible-sounding psychology\n"
        "- Anything the user did not say — even if it seems likely\n\n"
        "FORMAT:\n"
        "- Write in second person: 'You said...', 'You described...', 'You mentioned...'\n"
        "- Plain text paragraphs only — no bullet points, no headers\n"
        "- Only write what is genuinely new — do not repeat anything already in the profile\n"
        "- If the conversation is too short or too shallow to support any observation "
        "(e.g. only one or two messages, or only small talk), output exactly: NO_NEW_OBSERVATIONS\n"
        "- If there is nothing new to record, output exactly: NO_NEW_OBSERVATIONS\n"
        "- Output only the new notes, no preamble, no labels"
    )
    try:
        response = ollama.chat(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
        )
        raw = response["message"]["content"].strip()
        if not raw or raw == "NO_NEW_OBSERVATIONS":
            return None
        return raw
    except Exception:
        return None


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/status")
def get_status():
    try:
        result = ollama.list()
        models = [m["model"] for m in result["models"]]
        embedding_ok = any("nomic-embed-text" in m for m in models)
        return {"ollama_running": True, "models": models, "embedding_ok": embedding_ok}
    except Exception:
        return {"ollama_running": False, "models": [], "embedding_ok": False}


@app.get("/models", response_model=list[str])
def list_models():
    try:
        models = ollama.list()
        return [m["model"] for m in models["models"]]
    except Exception:
        return []


@app.get("/pull-model")
def pull_model(model: str = Query(...)):
    def generate():
        try:
            for progress in ollama.pull(model, stream=True):
                data = json.dumps({
                    "status": progress.get("status", ""),
                    "completed": progress.get("completed", 0),
                    "total": progress.get("total", 0),
                })
                yield f"data: {data}\n\n"
            yield 'data: {"status":"done"}\n\n'
        except Exception as e:
            yield f'data: {{"status":"error","error":{json.dumps(str(e))}}}\n\n'
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat")
def chat(request: ChatRequest):
    relevant         = get_relevant_entries(request.user_input)
    system_prompt    = build_system_prompt(relevant, request.mode)
    messages_for_llm = [system_prompt] + [m.model_dump() for m in request.history]

    def generate():
        for chunk in ollama.chat(
            model=request.selected_model,
            messages=messages_for_llm,
            stream=True,
        ):
            if "message" in chunk and "content" in chunk["message"]:
                yield chunk["message"]["content"]

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/save", response_model=SaveResponse)
def save_session(request: SaveRequest):
    user_messages = [m for m in request.history if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No conversation to save yet.")

    # Skip the opening assistant intro message when building the transcript
    convo = (request.history[1:]
             if request.history and request.history[0].role == "assistant"
             else request.history)
    history_text = "\n".join(
        [f"{m.role.capitalize()}: {m.content}" for m in convo]
    )

    summary_prompt = (
        f"Here is the conversation to summarize:\n\n{history_text}\n\n"
        "Return exactly two things, in this format, nothing else:\n\n"
        "TITLE: one line, maximum 8 words, capturing the central thing on the user's mind\n"
        "SUMMARY: 2–4 sentences, written in second person (\"You\"). Focus entirely on the user — "
        "what they brought up, what they seemed to be feeling or working through, what shifted or didn't. "
        "This text will be used for semantic search to surface relevant past sessions, so be specific and concrete: "
        "name topics, emotions, situations, and relationships that were actually mentioned. "
        "Do not describe the conversation itself. Do not mention Telmi. "
        "Do not interpret beyond what the user actually expressed.\n\n"
        "RULES:\n"
        "- Write \"You\" when referring to the user\n"
        "- No meta-commentary (\"the conversation touched on...\", \"the user discussed...\")\n"
        "- No poetry, no life lessons, no conclusions the user didn't reach themselves\n"
        "- If the conversation was very short or only a greeting: write a minimal honest summary "
        "of what was literally there — do not fill in emotions or context that weren't present\n"
        "- Output only the TITLE: and SUMMARY: lines, nothing else"
    )

    try:
        summary_response = ollama.chat(
            model=request.selected_model,
            messages=[{"role": "user", "content": summary_prompt}],
            options={"temperature": 0.1},
        )
        raw = summary_response["message"]["content"]

        title         = ""
        summary_lines = []
        in_summary    = False
        for line in raw.splitlines():
            if line.startswith("TITLE:"):
                title      = line.replace("TITLE:", "").strip()
                in_summary = False
            elif line.startswith("SUMMARY:"):
                summary_lines.append(line.replace("SUMMARY:", "").strip())
                in_summary = True
            elif in_summary and line.strip():
                summary_lines.append(line.strip())
        summary = " ".join(summary_lines)
        if not summary:
            summary = raw.strip()
        if not title:
            title = summary[:60]

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_entry_to_chroma(timestamp, summary, title)

        entries = load_memory_json()
        entries.append({
            "timestamp": timestamp,
            "title": title,
            "summary": summary,
            "history": [m.model_dump() for m in request.history],
        })
        save_memory_json(entries)

        profile_update = None
        if request.mode == "mind":
            new_observations = update_profile_from_session(
                history_text, summary, request.selected_model
            )
            if new_observations:
                existing = load_profile()
                ts       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                updated  = (existing + f"\n\n[{ts}]\n" + new_observations
                            if existing else new_observations)
                save_profile(updated)
                profile_update = new_observations

        return SaveResponse(
            title=title,
            summary=summary,
            timestamp=timestamp,
            profile_update=profile_update,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summary: {e}")


@app.get("/calendar-data", response_model=list[CalendarDay])
def get_calendar_data():
    entries = load_memory_json()
    result = []
    for e in entries:
        ts = e.get("timestamp", "")
        if not ts or ts == "Archive (legacy)":
            continue
        result.append(CalendarDay(
            date=ts[:10],
            timestamp=ts,
            title=e.get("title", ""),
            summary=e.get("summary", "")[:200],
        ))
    return result


@app.get("/telmi-stats")
def get_stats():
    entries = load_memory_json()
    valid = [e for e in entries if e.get("timestamp") and e["timestamp"] != "Archive (legacy)"]

    total = len(valid)

    today = date.today()
    this_month_prefix = today.strftime("%Y-%m")
    this_month = sum(1 for e in valid if e["timestamp"].startswith(this_month_prefix))

    dates = {e["timestamp"][:10] for e in valid}
    streak = 0
    cursor = today
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= timedelta(days=1)

    if total == 0:
        avg_per_week = 0.0
    else:
        first_date = date.fromisoformat(min(dates))
        weeks = max((today - first_date).days / 7, 1)
        avg_per_week = round(total / weeks, 1)

    achievements: list[str] = []
    if total >= 1:
        achievements.append("first_entry")
    if streak >= 7:
        achievements.append("week_streak")
    if streak >= 30:
        achievements.append("month_streak")
    if total >= 50:
        achievements.append("bookworm")
    if total >= 100:
        achievements.append("century")

    return StatsResponse(
        streak=streak,
        total=total,
        this_month=this_month,
        avg_per_week=avg_per_week,
        achievements=achievements,
    )


@app.get("/entries", response_model=list[Entry])
def list_entries():
    return get_all_entries()


@app.get("/search", response_model=list[Entry])
def search_entries(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
):
    collection = get_collection()
    total = collection.count()
    if total == 0:
        return []

    query_embedding = get_embedding(q)
    if query_embedding is None:
        raise HTTPException(
            status_code=503,
            detail="Embedding model not available. Make sure Ollama is running.",
        )

    n_results = min(limit, total)
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    entries = []
    for m, d, dist in zip(result["metadatas"][0], result["documents"][0], result["distances"][0]):
        if dist <= SEARCH_DISTANCE_THRESHOLD:
            entries.append(Entry(
                timestamp=m.get("timestamp", ""),
                title=m.get("title", ""),
                summary=d,
            ))
    return entries


@app.put("/entries/{timestamp}", response_model=Entry)
def update_entry(timestamp: str, request: UpdateEntryRequest):
    collection = get_collection()
    existing   = collection.get(ids=[timestamp], include=["documents", "metadatas"])

    if not existing["ids"]:
        raise HTTPException(status_code=404, detail="Entry not found")

    current_summary  = existing["documents"][0]
    current_metadata = existing["metadatas"][0]

    new_summary  = request.summary if request.summary is not None else current_summary
    new_title    = request.title   if request.title   is not None else current_metadata.get("title", "")
    new_metadata = {"timestamp": timestamp, "title": new_title}

    if request.summary is not None:
        new_embedding = get_embedding(new_summary)
        if new_embedding:
            collection.update(ids=[timestamp], embeddings=[new_embedding],
                              documents=[new_summary], metadatas=[new_metadata])
        else:
            collection.update(ids=[timestamp],
                              documents=[new_summary], metadatas=[new_metadata])
    else:
        collection.update(ids=[timestamp], metadatas=[new_metadata])

    entries = load_memory_json()
    for entry in entries:
        if entry["timestamp"] == timestamp:
            entry["title"]   = new_title
            entry["summary"] = new_summary
            break
    save_memory_json(entries)

    return Entry(timestamp=timestamp, title=new_title, summary=new_summary)


@app.get("/entries/{timestamp}/chat", response_model=list[ChatMessage])
def get_entry_chat(timestamp: str):
    entries = load_memory_json()
    for entry in entries:
        if entry["timestamp"] == timestamp:
            history = entry.get("history")
            if not history:
                raise HTTPException(status_code=404, detail="No chat history stored for this entry.")
            return [ChatMessage(**m) for m in history]
    raise HTTPException(status_code=404, detail="Entry not found.")


@app.delete("/entries/{timestamp}")
def delete_entry(timestamp: str):
    collection = get_collection()
    existing   = collection.get(ids=[timestamp])

    if not existing["ids"]:
        raise HTTPException(status_code=404, detail="Entry not found")

    collection.delete(ids=[timestamp])

    entries = load_memory_json()
    entries = [e for e in entries if e["timestamp"] != timestamp]
    save_memory_json(entries)

    return {"deleted": timestamp}


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import multiprocessing
    import uvicorn
    multiprocessing.freeze_support()
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
