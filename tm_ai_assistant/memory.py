"""
TM AI Assistant — Session Memory System (Sprint 8)
====================================================
Persistent user-level memory across chat sessions.

When a session ends (or after every few messages), key facts are extracted
and stored. On the next session, the last 3 session summaries are loaded
into the system prompt so Claude "remembers" what the user has been working on.

Memory types:
1. Session summaries — auto-generated when a session has 4+ messages
2. User preferences — explicit preferences set by the user (e.g., "always show in lakhs")
3. Recurring topics — tracks which business areas the user focuses on most
"""

import json
import frappe


# ─── Session Summary Generation ──────────────────────────────────────────────

def summarize_session(session_name):
    """
    Generate a 2-3 sentence summary of a chat session.
    Uses Haiku for speed and cost efficiency.
    Does NOT run if session has fewer than 4 messages.
    """
    session = frappe.get_doc("AI Chat Session", session_name)
    messages_raw = session.get("messages_json")
    if not messages_raw:
        return None

    try:
        messages = json.loads(messages_raw) if isinstance(messages_raw, str) else messages_raw
    except (json.JSONDecodeError, TypeError):
        return None

    # Only summarize sessions with meaningful conversations
    user_messages = [m for m in messages if m.get("role") == "user"]
    if len(user_messages) < 2:
        return None

    # Extract key topics from user messages
    user_texts = [m.get("content", "")[:200] for m in user_messages if isinstance(m.get("content"), str)]
    combined = " | ".join(user_texts[:5])  # Max 5 messages for summary

    # Use Haiku for fast, cheap summary
    try:
        import requests

        from .ai_engine import get_api_key
        api_key = get_api_key()

        prompt = (
            f"Summarize this business chat session in 2-3 short sentences. "
            f"Focus on: what business area was discussed, key findings, any actions taken.\n\n"
            f"User messages: {combined}"
        )

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=8,
        )

        if resp.status_code == 200:
            data = resp.json()
            summary = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    summary += block["text"]
            summary = summary.strip()
            if summary:
                # Store summary on the session
                frappe.db.set_value("AI Chat Session", session_name,
                                    "session_summary", summary, update_modified=False)
                frappe.db.commit()
                return summary
    except Exception as e:
        frappe.log_error(title="Memory: Session Summary Error", message=str(e))

    return None


# ─── Memory Retrieval ────────────────────────────────────────────────────────

def get_memory_context(user):
    """
    Get the memory context to inject into the system prompt.
    Returns a string with recent session summaries and user preferences.
    """
    parts = []

    # 1. Recent session summaries (last 3 with summaries)
    recent_summaries = frappe.get_all(
        "AI Chat Session",
        filters={
            "user": user,
            "session_summary": ["is", "set"],
        },
        fields=["title", "session_summary", "modified"],
        order_by="modified desc",
        limit=3,
    )

    if recent_summaries:
        summary_lines = []
        for s in recent_summaries:
            date_str = frappe.utils.format_datetime(s.modified, "MMM d")
            summary_lines.append(f"- {date_str}: {s.session_summary}")
        parts.append("Recent conversation history:\n" + "\n".join(summary_lines))

    # 2. User preferences
    prefs = get_user_preferences(user)
    if prefs:
        pref_lines = [f"- {k}: {v}" for k, v in prefs.items()]
        parts.append("User preferences:\n" + "\n".join(pref_lines))

    # 3. Recurring topics (what the user asks about most)
    topics = _get_recurring_topics(user)
    if topics:
        parts.append(f"User frequently asks about: {', '.join(topics)}")

    if not parts:
        return ""

    return "\n\n".join(parts)


def get_user_preferences(user):
    """
    Get stored user preferences. These are explicit settings
    the user has communicated (e.g., "show amounts in lakhs").
    """
    try:
        prefs_json = frappe.db.get_value("User", user, "custom_ai_preferences")
        if prefs_json:
            return json.loads(prefs_json) if isinstance(prefs_json, str) else prefs_json
    except Exception:
        pass
    return {}


def save_user_preference(user, key, value):
    """Save a user preference for future sessions."""
    prefs = get_user_preferences(user)
    prefs[key] = value

    try:
        frappe.db.set_value("User", user, "custom_ai_preferences",
                            json.dumps(prefs, ensure_ascii=False), update_modified=False)
        frappe.db.commit()
        return True
    except Exception as e:
        frappe.log_error(title="Memory: Save Preference Error", message=str(e))
        return False


def _get_recurring_topics(user):
    """
    Analyze recent queries to find recurring business topics.
    Returns a list of top 3-5 topic keywords.
    """
    # Get last 50 queries
    recent = frappe.get_all(
        "AI Usage Log",
        filters={"user": user, "model": ["not in", ["alert-engine", "briefing-engine", "scheduled-report-engine"]]},
        fields=["question"],
        order_by="creation desc",
        limit=50,
    )

    if len(recent) < 5:
        return []

    # Count topic keywords
    topic_keywords = {
        "sales": ["sales", "revenue", "order", "invoice", "customer"],
        "collections": ["payment", "collection", "receivable", "outstanding", "dso"],
        "purchase": ["purchase", "supplier", "vendor", "procurement"],
        "inventory": ["stock", "inventory", "warehouse", "bunker", "item"],
        "finance": ["cash", "bank", "profit", "loss", "margin", "expense"],
        "production": ["production", "manufacturing", "batch", "work order"],
    }

    topic_counts = {topic: 0 for topic in topic_keywords}
    for log in recent:
        q = (log.question or "").lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in q for kw in keywords):
                topic_counts[topic] += 1

    # Return topics that appear in 20%+ of queries
    threshold = len(recent) * 0.2
    top_topics = sorted(
        [(topic, count) for topic, count in topic_counts.items() if count >= threshold],
        key=lambda x: x[1], reverse=True,
    )

    return [t[0] for t in top_topics[:5]]


# ─── Auto-Summary Trigger ────────────────────────────────────────────────────

def maybe_summarize_on_close(session_name):
    """
    Called when a session is archived/closed.
    Generates a summary if the session has enough messages.
    """
    try:
        session = frappe.get_doc("AI Chat Session", session_name)
        if session.get("session_summary"):
            return  # Already summarized

        return summarize_session(session_name)
    except Exception as e:
        frappe.log_error(title="Memory: Auto-Summary Error", message=str(e))
        return None
