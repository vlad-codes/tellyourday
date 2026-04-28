import os
import json
import yaml
import calendar
import streamlit as st
import ollama
import chromadb
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────

MEMORY_FILE = "memory.json"
CHROMA_DIR  = "chroma_db"
COLLECTION  = "memory"

VECTOR_MIN_ENTRIES = 15
VECTOR_TOP_K       = 5


def load_config() -> dict:
    defaults = {"chat_model": "gemma4:e2b", "embed_model": "nomic-embed-text"}
    if not os.path.exists("config.yaml"):
        return defaults
    try:
        with open("config.yaml", "r") as f:
            return {**defaults, **yaml.safe_load(f)}
    except Exception:
        return defaults

config      = load_config()
CHAT_MODEL  = config["chat_model"]
EMBED_MODEL = config["embed_model"]


def get_available_models() -> list[str]:
    try:
        models = ollama.list()
        return [m["model"] for m in models["models"]]
    except Exception:
        return [CHAT_MODEL]


# ─────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────

def get_embedding(text: str) -> list[float] | None:
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return resp["embedding"]
    except Exception as e:
        st.warning(f"Embedding error ({EMBED_MODEL}): {e}")
        return None


# ─────────────────────────────────────────────
# ChromaDB
# ─────────────────────────────────────────────

def get_collection() -> chromadb.Collection:
    if "chroma_collection" not in st.session_state:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"}
        )
        st.session_state.chroma_collection = collection
    return st.session_state.chroma_collection


def count_entries() -> int:
    return get_collection().count()


def get_all_entries() -> list[dict]:
    result = get_collection().get(include=["documents", "metadatas"])
    entries = []
    for m, d in zip(result["metadatas"], result["documents"]):
        entries.append({
            "timestamp": m.get("timestamp", ""),
            "title":     m.get("title", ""),
            "summary":   d
        })
    entries.sort(key=lambda e: e["timestamp"])
    return entries


# ─────────────────────────────────────────────
# Streak
# ─────────────────────────────────────────────

def calculate_streaks(entries: list[dict]) -> tuple[int, int]:
    if not entries:
        return 0, 0

    days = sorted({
        datetime.strptime(e["timestamp"][:10], "%Y-%m-%d").date()
        for e in entries
        if len(e["timestamp"]) >= 10
    })

    if not days:
        return 0, 0

    today = date.today()

    current = 0
    check = today
    for d in reversed(days):
        if d == check:
            current += 1
            check -= timedelta(days=1)
        elif d < check:
            break

    longest = 1
    run = 1
    for i in range(1, len(days)):
        if days[i] == days[i - 1] + timedelta(days=1):
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    return current, max(longest, current)


# ─────────────────────────────────────────────
# Calendar (Plotly)
# ─────────────────────────────────────────────

def build_calendar(entries: list[dict], year: int, month: int):
    entry_map = {}
    for e in entries:
        d = e["timestamp"][:10]
        if d not in entry_map:
            entry_map[d] = {"title": e["title"], "summary": e["summary"]}

    today = date.today()
    cal = calendar.monthcalendar(year, month)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    x_vals, y_vals, colors, hover_texts, custom_dates, day_numbers = [], [], [], [], [], []
    num_weeks = len(cal)

    for week_idx, week in enumerate(cal):
        for day_idx, day in enumerate(week):
            x = day_idx
            y = num_weeks - 1 - week_idx

            if day == 0:
                x_vals.append(x)
                y_vals.append(y)
                colors.append("rgba(0,0,0,0)")
                hover_texts.append("")
                custom_dates.append("")
                day_numbers.append("")
                continue

            ds = f"{year:04d}-{month:02d}-{day:02d}"
            is_today = (date(year, month, day) == today)
            has_entry = ds in entry_map

            if has_entry:
                color = "#a78bfa"
            elif is_today:
                color = "#374151"
            else:
                color = "#1e1e1e"

            title = entry_map[ds]["title"] if has_entry else ""
            hover = f"{ds}<br>{title}" if title else ds

            x_vals.append(x)
            y_vals.append(y)
            colors.append(color)
            hover_texts.append(hover)
            custom_dates.append(ds)
            day_numbers.append(str(day))

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        mode="markers+text",
        marker=dict(
            symbol="square",
            size=38,
            color=colors,
            line=dict(width=0),
        ),
        text=day_numbers,
        textposition="middle center",
        textfont=dict(size=13, color="#e5e7eb"),
        hovertext=hover_texts,
        hovertemplate="%{hovertext}<extra></extra>",
        customdata=custom_dates,
    ))

    fig.add_trace(go.Scatter(
        x=list(range(7)),
        y=[num_weeks] * 7,
        mode="text",
        text=day_names,
        textfont=dict(size=11, color="#6b7280"),
        hoverinfo="skip",
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        height=300,
        showlegend=False,
        xaxis=dict(visible=False, range=[-0.6, 6.6], fixedrange=True),
        yaxis=dict(visible=False, range=[-0.6, num_weeks + 0.6], fixedrange=True),
    )

    return fig, entry_map


# ─────────────────────────────────────────────
# Migration
# ─────────────────────────────────────────────

def migrate_json_to_chroma(entries: list) -> None:
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
        metadata = {
            "timestamp": entry["timestamp"],
            "title":     entry.get("title", "")
        }
        if embedding:
            collection.add(ids=[entry_id], embeddings=[embedding],
                           documents=[entry["summary"]], metadatas=[metadata])
        else:
            collection.add(ids=[entry_id], documents=[entry["summary"]],
                           metadatas=[metadata])
        migrated += 1
    if migrated:
        st.toast(f"{migrated} older entries migrated into vector database.")


# ─────────────────────────────────────────────
# Save entry
# ─────────────────────────────────────────────

def save_entry_to_chroma(timestamp: str, summary: str, title: str) -> bool:
    try:
        collection = get_collection()
        embedding = get_embedding(summary)
        metadata = {"timestamp": timestamp, "title": title}
        if embedding:
            collection.add(ids=[timestamp], embeddings=[embedding],
                           documents=[summary], metadatas=[metadata])
        else:
            collection.add(ids=[timestamp], documents=[summary],
                           metadatas=[metadata])
        return True
    except Exception as e:
        st.error(f"ChromaDB error while saving: {e}")
        return False


# ─────────────────────────────────────────────
# Memory retrieval
# ─────────────────────────────────────────────

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
        include=["documents", "metadatas", "distances"]
    )
    return [{"timestamp": m["timestamp"], "summary": d}
            for m, d in zip(result["metadatas"][0], result["documents"][0])]


# ─────────────────────────────────────────────
# JSON backup
# ─────────────────────────────────────────────

def load_memory_json() -> list:
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "memory" in data and isinstance(data["memory"], str):
            if data["memory"].strip():
                return [{"timestamp": "Archive (legacy)", "title": "", "summary": data["memory"]}]
            return []
        return data.get("entries", [])
    except Exception as e:
        st.error(f"Error loading {MEMORY_FILE}: {e}")
        return []


def save_memory_json(entries: list) -> bool:
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
# Save logic (called from sidebar button)
# ─────────────────────────────────────────────

def run_save_flow():
    has_user_messages = any(m["role"] == "user" for m in st.session_state.messages)
    if not has_user_messages:
        st.session_state.save_warning = "No conversation to save yet."
        return

    history_text = "\n".join(
        [f"{m['role'].capitalize()}: {m['content']}" for m in st.session_state.messages]
    )
    summary_prompt = (
        f"Here is today's conversation:\n\n{history_text}\n\n"
        "Return exactly two things, nothing else:\n\n"
        "TITLE: a single line, max 8 words, capturing what was on the user's mind today\n"
        "SUMMARY: 3-4 sentences written from Telmi's perspective about the USER — "
        "what they shared, how they felt, what mattered to them. "
        "Write 'You' when referring to the user. Never describe the conversation itself. "
        "Never mention Telmi. Only what the user brought up and their mood.\n\n"
        "RULES:\n"
        "- Focus entirely on the user, not the exchange\n"
        "- No meta-commentary like 'the conversation was about'\n"
        "- No poetry, no life lessons\n"
        "- Output only TITLE: and SUMMARY: labels, nothing else"
    )
    try:
        summary_response = ollama.chat(
            model=st.session_state.selected_model,
            messages=[{"role": "user", "content": summary_prompt}],
            options={"temperature": 0.1}
        )
        raw = summary_response["message"]["content"]

        title = ""
        summary_lines = []
        in_summary = False
        for line in raw.splitlines():
            if line.startswith("TITLE:"):
                title = line.replace("TITLE:", "").strip()
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
        chroma_ok = save_entry_to_chroma(timestamp, summary, title)

        new_entry = {"timestamp": timestamp, "title": title, "summary": summary}
        st.session_state.json_entries.append(new_entry)
        save_memory_json(st.session_state.json_entries)
        st.session_state.all_entries = get_all_entries()

        if chroma_ok:
            st.session_state.already_saved = True
            st.session_state.model_changed = False
            st.session_state.last_saved = {"title": title, "summary": summary}

    except Exception as e:
        st.session_state.save_error = f"Error generating summary: {e}"


# ─────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────

st.set_page_config(page_title="Tell me your day", page_icon="📓", layout="centered")

# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = [{
        "role": "assistant",
        "content": "Hey, I'm Telmi — your personal reflection companion.\n\nI'm here to listen. Just tell me what's been on your mind today — big or small, good or bad.\n\nI remember our past conversations and I'm curious how you're doing."    }]
if "already_saved" not in st.session_state:
    st.session_state.already_saved = False
if "json_entries" not in st.session_state:
    st.session_state.json_entries = load_memory_json()
if "cal_year" not in st.session_state:
    st.session_state.cal_year = date.today().year
if "cal_month" not in st.session_state:
    st.session_state.cal_month = date.today().month
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None
if "selected_model" not in st.session_state:
    st.session_state.selected_model = CHAT_MODEL
if "model_changed" not in st.session_state:
    st.session_state.model_changed = False
if "trigger_save" not in st.session_state:
    st.session_state.trigger_save = False
if "save_warning" not in st.session_state:
    st.session_state.save_warning = None
if "save_error" not in st.session_state:
    st.session_state.save_error = None
if "last_saved" not in st.session_state:
    st.session_state.last_saved = None

get_collection()
if not st.session_state.get("migration_done"):
    migrate_json_to_chroma(st.session_state.json_entries)
    st.session_state.migration_done = True

if "all_entries" not in st.session_state:
    st.session_state.all_entries = get_all_entries()

# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────

total = count_entries()
mode = "linear mode" if total < VECTOR_MIN_ENTRIES else "semantic mode"

with st.sidebar:
    # Model selector
    available_models = get_available_models()
    current_index = available_models.index(st.session_state.selected_model) \
        if st.session_state.selected_model in available_models else 0

    new_model = st.selectbox("Model", available_models, index=current_index)

    if new_model != st.session_state.selected_model:
        has_user_messages = any(m["role"] == "user" for m in st.session_state.messages)
        if has_user_messages and not st.session_state.already_saved:
            st.session_state.model_changed = True
        st.session_state.selected_model = new_model

    if st.session_state.model_changed:
        st.warning("Save your conversation before the new model takes effect.")

    st.divider()


    if st.session_state.already_saved:
        st.success("Session saved.")
        if st.button("New Session", use_container_width=True):
            st.session_state.messages = [{
                "role": "assistant",
                "content": "Hey, I'm Telmi — your personal reflection companion.\n\nI'm here to listen, not to judge. Just tell me what's been on your mind today — big or small, good or bad.\n\nI remember our past conversations and I'm curious how you're doing."
            }]
            st.session_state.already_saved = False
            st.session_state.last_saved = None
            st.session_state.model_changed = False
            st.rerun()
    else:
        if st.button("End conversation & save", use_container_width=True):
            st.session_state.trigger_save = True
            st.rerun()
    st.divider()
    st.caption("""
**How it works**

Type freely — there's no right or wrong way to start. Just write what's on your mind.

When you're done, hit **End conversation & save**. Your session gets summarized and stored locally — no cloud, no data sharing.

To switch models, use the dropdown above. Start a **New Session** afterwards so the new model takes effect cleanly.

Your conversation history is used to personalize responses over time.
""")
    
    st.divider()
    st.caption(f"{total} memories stored")
    if total < VECTOR_MIN_ENTRIES:
        st.caption(f"Smart search activates at {VECTOR_MIN_ENTRIES} memories — {VECTOR_MIN_ENTRIES - total} to go.")

# ─────────────────────────────────────────────
# Handle save trigger (runs once after sidebar click)
# ─────────────────────────────────────────────

if st.session_state.trigger_save:
    st.session_state.trigger_save = False
    with st.spinner("Generating summary and saving..."):
        run_save_flow()
    st.rerun()

# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

st.title("Tell me your day 📓")

tab_chat, tab_stats = st.tabs(["Chat", "Statistics"])

# ── Chat Tab ────────────────────────────────
with tab_chat:
    
    # Scrollable message container — chat_input stays below it, fixed in tab
    chat_container = st.container(height=500)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Chat input — inside tab, renders below container, not floating
    if user_input := st.chat_input("How was your day?"):
        st.session_state.messages.append({"role": "user", "content": user_input})

        with chat_container:
            with st.chat_message("user"):
                st.markdown(user_input)

        relevant = get_relevant_entries(user_input)
        system_prompt = build_system_prompt(relevant)
        messages_for_llm = [system_prompt] + st.session_state.messages

        with chat_container:
            with st.chat_message("assistant"):
                response_placeholder = st.empty()
                full_response = ""
                try:
                    for chunk in ollama.chat(model=st.session_state.selected_model, messages=messages_for_llm, stream=True):
                        if "message" in chunk and "content" in chunk["message"]:
                            full_response += chunk["message"]["content"]
                            response_placeholder.markdown(full_response + "▌")
                    response_placeholder.markdown(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                except Exception as e:
                    response_placeholder.empty()
                    st.error(f"Cannot reach Ollama. Is `ollama serve` running?\n\nError: {e}")

    # Feedback messages from save flow
    if st.session_state.save_warning:
        st.warning(st.session_state.save_warning)
        st.session_state.save_warning = None
    if st.session_state.save_error:
        st.error(st.session_state.save_error)
        st.session_state.save_error = None
    if st.session_state.already_saved and st.session_state.last_saved:
        ls = st.session_state.last_saved
        st.success("Saved successfully!")
        st.info(f"**{ls['title']}**\n\n{ls['summary']}")

# ── Statistics Tab ───────────────────────────
with tab_stats:
    all_entries = st.session_state.all_entries
    current_streak, longest_streak = calculate_streaks(all_entries)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("current streak", f"{current_streak} days")
    with col2:
        st.metric("longest streak", f"{longest_streak} days")

    st.divider()

    # Month navigation
    nav_col1, nav_col2, nav_col3 = st.columns([1, 3, 1])
    with nav_col1:
        if st.button("←", use_container_width=True):
            if st.session_state.cal_month == 1:
                st.session_state.cal_month = 12
                st.session_state.cal_year -= 1
            else:
                st.session_state.cal_month -= 1
            st.session_state.selected_date = None
            st.rerun()
    with nav_col2:
        month_name = date(st.session_state.cal_year, st.session_state.cal_month, 1).strftime("%B %Y")
        st.markdown(
            f"<p style='text-align:center;margin:0;padding:6px 0;font-size:16px;'>{month_name}</p>",
            unsafe_allow_html=True
        )
    with nav_col3:
        if st.button("→", use_container_width=True):
            if st.session_state.cal_month == 12:
                st.session_state.cal_month = 1
                st.session_state.cal_year += 1
            else:
                st.session_state.cal_month += 1
            st.session_state.selected_date = None
            st.rerun()

    fig, entry_map = build_calendar(
        all_entries,
        st.session_state.cal_year,
        st.session_state.cal_month
    )

    click_data = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        key="calendar"
    )

    if click_data and click_data.get("selection", {}).get("points"):
        point = click_data["selection"]["points"][0]
        clicked = point.get("customdata", "")
        if clicked and clicked in entry_map:
            st.session_state.selected_date = clicked

    if st.session_state.selected_date:
        sd = st.session_state.selected_date
        if sd in entry_map:
            st.divider()
            st.caption(sd)
            if entry_map[sd]["title"]:
                st.markdown(f"**{entry_map[sd]['title']}**")
            st.write(entry_map[sd]["summary"])