"""WHAT THIS FILE DOES
This is the chat web page where people talk to Navi.

The page shows the logo and title, a short introduction to Navi, a greeting, and four sample questions to click. Below
that is the chat itself: the user types a question, and Navi's answer appears as it's being written, sometimes with a
diagram of the steps and their order.

The sidebar on the left works like the one in Claude: a "New chat" button, a list of past chats grouped by date (click
one to reopen it), the user's saved checklist and reminders, and a folded-away "Developer settings" section for testing.

The page doesn't contain Navi itself; it sends every message to the web server (server.py) and shows what comes back.

HOW TO RUN IT (with the server already running)
    streamlit run ui/streamlit_app.py
"""

import base64
import json
import os
import textwrap
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import streamlit as st

# The app only ever talks to Navi through the HTTP API; it never imports the agent code directly. That makes
# it a "thin client": scripts, the evaluation and this page all use the same API, and the page could be
# replaced without touching the agent at all.
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# This has to be the first Streamlit call on the page. The wide layout leaves room for the sidebar and the diagrams.
st.set_page_config(page_title="License Navigator", page_icon="🧭", layout="wide")

# A little CSS to tidy up the look. In the sidebar, chat titles are left-aligned and kept to one line, like a
# chat app; Streamlit centres button text by default, which looks odd for a list of titles. The header puts
# the logo and title side by side. The sample-question buttons show the whole question instead of cutting it
# off. And the chat avatars are green to match the logo, instead of Streamlit's orange and red. If a future
# Streamlit version renames any of these elements, the styling simply stops applying; nothing breaks.
st.markdown(
    """<style>
    [data-testid="stSidebar"] .stButton button { justify-content: flex-start; text-align: left; }
    [data-testid="stSidebar"] .stButton button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nav-header { display: flex; align-items: center; gap: 14px; margin-bottom: 0.4rem; }
    .nav-header img { width: 56px; height: 56px; flex-shrink: 0; }
    .nav-header h1 { margin: 0; padding: 0; font-size: 2rem; line-height: 1.2; }
    .nav-intro { color: rgba(128, 128, 128, 0.95); margin-bottom: 1.2rem; }
    /* Sample-question buttons: show the whole question (wrapped, left-aligned) instead of cutting it off. */
    [data-testid="stMainBlockContainer"] .stButton button { justify-content: flex-start; text-align: left; height: 100%; }
    [data-testid="stMainBlockContainer"] .stButton button div,
    [data-testid="stMainBlockContainer"] .stButton button p { white-space: normal; overflow: visible; text-overflow: clip; }
    /* Chat avatars in brand green instead of Streamlit's orange (Navi) and red (user): Navi in the logo
       green, the user in a lighter green so the two are still easy to tell apart. */
    [data-testid="stChatMessageAvatarAssistant"] { background-color: #0B7A4B; color: #FFFFFF; }
    [data-testid="stChatMessageAvatarUser"] { background-color: #3FAE74; color: #FFFFFF; }
    </style>""",
    unsafe_allow_html=True,
)

# The logo is an SVG file sitting next to this script. We embed it directly in the page, which lets it sit on
# the same line as the title (st.image would put it on a line of its own). If the file is missing, the header
# just shows the title without a logo.
LOGO_PATH = Path(__file__).parent / "assets" / "logo.svg"
LOGO_URI = (f"data:image/svg+xml;base64,{base64.b64encode(LOGO_PATH.read_bytes()).decode()}"
            if LOGO_PATH.exists() else "")

# These sample questions appear on every new chat, so a first-time user knows what they can ask. Each one
# shows off a different skill: the ordered checklist, a fee lookup with its source, explaining why one step
# comes first, and Pidgin.
SAMPLE_QUESTIONS = [
    "I want to start selling packaged zobo drinks in Ibadan. What do I need, and in what order?",
    "How much is the CAC business name registration fee, and how long does it take?",
    "Why do I need the NAFDAC facility inspection before product registration?",
    "Abeg, wetin I need to open pharmacy for Lagos?",
]

# Navi's greeting at the top of every chat.
GREETING = (
    "Hello! 👋 I'm **Navi**. Tell me about the business you want to start, or pick one of the "
    "questions below to see how I can help."
)


# Streamlit runs this whole script again from the top every time the user clicks or types anything. So
# anything we need to keep between those runs, like the conversation so far, lives in st.session_state.

def _new_session_id() -> str:
    """Make a new random chat ID."""
    return f"s-{uuid.uuid4().hex[:12]}"


def _init_state() -> None:
    """Set up the page's memory the first time it loads."""
    # st.session_state survives each rerun, and setdefault only fills in a value the first time, so the
    # conversation isn't wiped every time the user clicks something. The history holds each message with its
    # diagram, warning and debug line. show_debug controls the tools, timing and token line under each reply,
    # which you switch on in Developer settings.
    defaults = {
        "user_id": "ada-ibadan",
        "session_id": _new_session_id(),
        "mode": "graphrag",
        "history": [],
        "show_debug": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _end_current_session() -> None:
    """Tell the API the current chat is over, so its long-term summary gets written now.

    We skip this for an empty chat, because there's nothing to summarise and it would create an empty chat
    on the server. If the call fails, we ignore it: the user must always be able to move on.
    """
    if not st.session_state.history:
        return
    try:
        requests.post(f"{API_URL}/sessions/{st.session_state.session_id}/end",
                      params={"user_id": st.session_state.user_id, "mode": st.session_state.mode}, timeout=30)
    except requests.RequestException:
        pass


def _new_session() -> None:
    """Start a new chat: end the current one and begin an empty one.

    Long-term memory carries over, so Navi still knows the user. Only the conversation starts fresh.
    """
    _end_current_session()
    st.session_state.session_id = _new_session_id()
    st.session_state.history = []


def _open_session(session_id: str) -> None:
    """Reopen a chat from the sidebar: load its messages from the API and carry on in it.

    This runs when the chat's button is clicked, before the page redraws, so the chat area shows the
    reopened conversation straight away.
    """
    if session_id == st.session_state.session_id:
        return
    _end_current_session()
    try:
        response = requests.get(f"{API_URL}/sessions/{session_id}/messages",
                                params={"user_id": st.session_state.user_id}, timeout=30)
        response.raise_for_status()
        messages = response.json()["messages"]
    except requests.RequestException as exc:
        st.session_state.load_error = f"Could not open that chat: {exc}"
        return
    st.session_state.session_id = session_id
    # Reopened messages come back as text only. Their diagrams and notices weren't saved, so they aren't drawn again.
    st.session_state.history = [{"role": m["role"], "content": m["content"]} for m in messages]


# The colour for each kind of step in the diagram: green for done, blue for ready now, and orange for
# waiting on an earlier step.
GROUP_COLOURS = {"done": "#b2f2bb", "todo": "#a5d8ff", "waiting": "#ffd8a8"}


def to_dot(graph: dict) -> str:
    """Turn the steps and links from a tool into a Graphviz diagram description.

    Streamlit draws Graphviz diagrams right in the browser, so nothing extra needs installing. The diagram
    runs left to right, which reads like a timeline.
    """
    lines = ["digraph G {", "rankdir=LR;", 'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];']
    for node in graph.get("nodes", []):
        # Each box shows only the step's name. The step's code is still used behind the scenes to connect the
        # arrows, but codes are internal and never shown to the user. Long names wrap onto at most two lines of
        # about 30 characters, and double quotes are swapped for single ones because they'd break the description.
        lines_of_name = textwrap.wrap(node["name"].replace('"', "'"), width=30)
        label = "\\n".join(lines_of_name[:2]) + ("…" if len(lines_of_name) > 2 else "")
        colour = GROUP_COLOURS.get(node.get("group"), "#e5dbff")
        lines.append(f'"{node["id"]}" [label="{label}", fillcolor="{colour}"];')
    for edge in graph.get("edges", []):
        lines.append(f'"{edge["from"]}" -> "{edge["to"]}";')
    lines.append("}")
    return "\n".join(lines)


def _render_extras(item: dict) -> None:
    """Show the extras under a reply: the diagram, any warning, a hand-off notice, and the debug line."""
    # The diagram starts folded away, so it doesn't push the answer off the screen.
    if item.get("graph") and item["graph"].get("nodes"):
        with st.expander("Show the dependency graph", expanded=False):
            st.graphviz_chart(to_dot(item["graph"]))
            st.caption("Green = done · Blue = ready now · Orange = waiting on an earlier step")
    if item.get("warning"):
        st.warning(item["warning"])
    if item.get("handoff"):
        st.info(f"👩🏾‍💼 Passed to a human adviser — ticket #{item['handoff']}")
    # The debug line only shows if it's switched on in Developer settings.
    if st.session_state.show_debug and item.get("debug"):
        st.caption(item["debug"])


def _date_group(iso_timestamp: str) -> str:
    """Decide which date heading a chat goes under, like Claude's sidebar: Today, Yesterday, and so on.

    Times are stored in UTC, so we convert to this computer's local time first. Otherwise a chat from 11pm
    might be filed under "Yesterday" just because it's already the next day in UTC.
    """
    try:
        day = datetime.fromisoformat(iso_timestamp).astimezone().date()
    except ValueError:
        return "Older"
    today = date.today()
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    if day > today - timedelta(days=7):
        return "Previous 7 days"
    if day > today - timedelta(days=30):
        return "Previous 30 days"
    return "Older"


def _chat_list() -> None:
    """Show the user's chats in the sidebar, newest first and grouped by date, with the open one highlighted."""
    try:
        sessions = requests.get(f"{API_URL}/users/{st.session_state.user_id}/sessions",
                                params={"mode": st.session_state.mode}, timeout=10).json()["sessions"]
    except requests.RequestException:
        st.error(f"API not reachable at {API_URL}. Start it with: uvicorn server:app --port 8000")
        return

    # The server only records a new chat once its first message is sent. Until then, we show it here at the
    # top of the list as a highlighted "New chat".
    if st.session_state.session_id not in {s["session_id"] for s in sessions}:
        st.caption("Today")
        st.button("💬 New chat", key="chat-current-new", type="primary", use_container_width=True, disabled=True)

    shown_group = None
    for s in sessions:
        # Print each date heading once, just above the first chat in that group.
        group = _date_group(s["updated_at"])
        if group != shown_group:
            st.caption(group)
            shown_group = group
        is_open = s["session_id"] == st.session_state.session_id
        # Each chat is a button. Hovering shows the full title in case it's been cut off, and clicking reopens the chat.
        st.button(
            s["title"],
            key=f"chat-{s['session_id']}",
            type="primary" if is_open else "secondary",
            use_container_width=True,
            help=s["title"],
            on_click=_open_session,
            args=(s["session_id"],),
        )


def _checklist() -> None:
    """Show the user's saved checklist and reminders in the sidebar, by step name rather than by code."""
    try:
        data = requests.get(f"{API_URL}/users/{st.session_state.user_id}/checklist", timeout=10).json()
    except requests.RequestException:
        return
    checklist = data.get("checklist")
    if not checklist and not data.get("reminders"):
        return
    steps = (checklist or {}).get("steps", [])
    # Reminders are saved against a step's code, so we use the checklist to look up the name to show instead.
    names = {step["id"]: step["name"] for step in steps}
    with st.expander(f"📋 Your checklist ({len(steps)} steps)", expanded=False):
        for i, step in enumerate(steps, 1):
            st.markdown(f"{i}. {step['name']}")
        for reminder in data.get("reminders", []):
            what = names.get(reminder["requirement_id"], "a step on your checklist")
            st.info(f"⏰ {reminder['remind_on']}: {what}" + (f" — {reminder['note']}" if reminder.get("note") else ""))


def _developer_settings() -> None:
    """Show the testing controls, folded away so a normal user never has to see them.

    Changing the user ID is how you test long-term memory with a different user, or a returning one. The
    mode switches between GraphRAG and the vector-only baseline for the key experiment, and each mode has
    its own list of chats. The debug switch shows which tools ran, how long the turn took and how many
    tokens it used, under each reply.
    """
    with st.expander("⚙️ Developer settings", expanded=False):
        user_id = st.text_input("User ID (long-term memory key)", st.session_state.user_id)
        mode = st.radio("Mode", ["graphrag", "baseline"], horizontal=True,
                        index=["graphrag", "baseline"].index(st.session_state.mode),
                        help="baseline = vector-only RAG, for the key experiment")
        st.session_state.show_debug = st.toggle("Show tools, latency and tokens", value=st.session_state.show_debug)
        st.caption(f"Session ID: `{st.session_state.session_id}`")
        # A different user or mode means a different list of chats, so start a fresh chat for it.
        if user_id != st.session_state.user_id or mode != st.session_state.mode:
            _end_current_session()
            st.session_state.user_id, st.session_state.mode = user_id, mode
            st.session_state.session_id, st.session_state.history = _new_session_id(), []
            st.rerun()


def sidebar() -> None:
    """Draw the whole sidebar: the logo, the New chat button, the chat list, the checklist and the settings."""
    with st.sidebar:
        # The same logo as the main header, just smaller, so the sidebar matches the page.
        logo = f'<img src="{LOGO_URI}" alt="" style="width:32px;height:32px">' if LOGO_URI else ""
        st.markdown(f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:0.8rem">{logo}'
                    '<span style="font-size:1.25rem;font-weight:600">License Navigator</span></div>',
                    unsafe_allow_html=True)
        # The plus is a Material icon rather than the ➕ emoji, so it turns white like the button's text.
        if st.button("New chat", icon=":material/add:", type="primary", use_container_width=True, key="new-chat"):
            _new_session()
            st.rerun()
        st.markdown("**Chats**")
        _chat_list()
        st.divider()
        _checklist()
        _developer_settings()


def stream_reply(message: str, extras: dict):
    """Send a message to the API and hand back Navi's reply a piece at a time, for st.write_stream.

    Text is passed straight on, so it appears as it's written. Everything else (the diagram, a warning, a
    hand-off, the token counts) is collected in `extras` and shown once the reply is finished.
    """
    payload = {"user_id": st.session_state.user_id, "session_id": st.session_state.session_id,
               "message": message, "mode": st.session_state.mode}
    # stream=True makes requests hand us the reply line by line as it arrives, instead of waiting for the end.
    # The long timeout allows for turns that call several tools.
    with requests.post(f"{API_URL}/chat", json=payload, stream=True, timeout=180) as response:
        response.raise_for_status()
        # Each event arrives as a line starting "data: ". Blank lines in between are just keep-alives, so we skip them.
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            kind = event["type"]
            if kind == "text":
                yield event["text"]
            elif kind == "tool":
                extras.setdefault("tools", []).append(event["name"])
            elif kind == "graph":
                extras["graph"] = event["graph"]
            elif kind == "warning":
                extras["warning"] = event["text"]
            elif kind == "handoff":
                extras["handoff"] = event["ticket"]
            elif kind == "error":
                yield f"\n\n⚠️ {event['text']}"
            elif kind == "done":
                extras["usage"] = event["usage"]
                extras["latency_ms"] = event["latency_ms"]


def _header() -> None:
    """Show the logo and title on one line, with a short description of Navi underneath."""
    logo = f'<img src="{LOGO_URI}" alt="">' if LOGO_URI else ""
    st.markdown(
        f'<div class="nav-header">{logo}<h1>Business Licensing Navigator</h1></div>'
        '<div class="nav-intro">Meet <b>Navi</b>, your guide to the registrations, licences and permits a '
        "Nigerian business needs. Tell Navi what you sell and where, and it builds your checklist in the "
        "right order, explains why each step comes first, answers fee and document questions with the "
        "official source, and keeps track of your progress. Ask in English or Pidgin.</div>",
        unsafe_allow_html=True,
    )


def _ask(question: str) -> None:
    """Runs when a sample question is clicked. It queues the question, so main() sends it just like a typed message."""
    st.session_state.pending_prompt = question


def _welcome() -> None:
    """Show Navi's greeting, and the sample questions while the chat is still empty.

    The greeting only exists on the page. It isn't sent to the agent or saved in the conversation, so it costs
    no tokens and doesn't change anything the agent sees.
    """
    with st.chat_message("assistant"):
        st.markdown(GREETING)
    if st.session_state.history:
        return
    st.caption("Try asking")
    # Lay the sample questions out as buttons in two columns. Clicking one sends that question straight away.
    columns = st.columns(2)
    for i, question in enumerate(SAMPLE_QUESTIONS):
        columns[i % 2].button(question, key=f"sample-{i}", use_container_width=True,
                              on_click=_ask, args=(question,))


def main() -> None:
    """Draw the page and handle the user's next message."""
    _init_state()
    sidebar()
    _header()

    # If reopening a chat from the sidebar failed, show the error here, once.
    if st.session_state.get("load_error"):
        st.error(st.session_state.pop("load_error"))

    _welcome()

    # Show the conversation so far. Streamlit redraws the whole page on every interaction, so earlier messages
    # (and their diagrams) have to be drawn again from session_state each time.
    for item in st.session_state.history:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            _render_extras(item)

    # Take either a typed message or a sample question that was just clicked. If there's neither, there's
    # nothing more to do on this run.
    typed = st.chat_input("Ask Navi about registering, licensing or running your business...")
    prompt = typed or st.session_state.pop("pending_prompt", None)
    if not prompt:
        return

    # Show the user's message straight away.
    is_first_message = not st.session_state.history
    st.session_state.history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Stream Navi's reply into a new message, then add the extras underneath it.
    with st.chat_message("assistant"):
        extras: dict = {}
        try:
            reply = st.write_stream(stream_reply(prompt, extras))
        except requests.RequestException as exc:
            reply = f"⚠️ Could not reach the API: {exc}"
            st.error(reply)
        # Build the debug line (which tools ran, how long it took, how many tokens) and keep it with the
        # reply, so it can be switched on and off later.
        debug = None
        if extras.get("usage"):
            u = extras["usage"]
            debug = (f"{', '.join(extras.get('tools', [])) or 'no tools'} · {extras['latency_ms']} ms · "
                     f"in {u['inputTokens']} / out {u['outputTokens']} / cache read {u['cacheReadInputTokens']}")
        item = {"role": "assistant", "content": reply if isinstance(reply, str) else "".join(reply),
                "graph": extras.get("graph"), "warning": extras.get("warning"),
                "handoff": extras.get("handoff"), "debug": debug}
        _render_extras(item)
        st.session_state.history.append(item)

    # The sidebar was drawn before this message was sent. After the first message of a new chat, we redraw the
    # page once, so the chat shows up in the list with its title (as Claude does) instead of on the next click.
    if is_first_message:
        st.rerun()


main()
