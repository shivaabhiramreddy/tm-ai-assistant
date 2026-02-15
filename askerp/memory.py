"""
AskERP — Session Memory System v3.0
=============================================
Persistent user-level memory across chat sessions.

v3.0 changes (P2.3):
- Cross-session insight extraction: entities, patterns, follow-ups
- Smart deduplication of insights across sessions
- Recency-weighted aggregation (newer sessions matter more)
- Structured JSON storage in session_insights field

v2.0 changes:
- Uses utility_model from AskERP Settings via providers layer
- No more hardcoded model strings or direct API calls

Memory layers:
1. Session summaries — auto-generated when a session has 4+ messages
2. Session insights  — structured extraction (entities, patterns, follow-ups)
3. User preferences  — explicit settings (e.g., "always show in lakhs")
4. Recurring topics   — tracks which business areas the user focuses on most
"""

import json
import frappe
from collections import Counter


# ─── Session Summary Generation ──────────────────────────────────────────────

def summarize_session(session_name):
    """
    Generate a 2-3 sentence summary of a chat session.
    Uses the utility model for speed and cost efficiency.
    Does NOT run if session has fewer than 2 user messages.
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

    # Use the utility model from AskERP Settings for fast, cheap summary
    try:
        from .providers import get_model_for_tier, call_model

        utility_model = get_model_for_tier("utility")
        if not utility_model:
            return None

        prompt = (
            f"Summarize this business chat session in 2-3 short sentences. "
            f"Focus on: what business area was discussed, key findings, any actions taken.\n\n"
            f"User messages: {combined}"
        )

        result = call_model(
            utility_model,
            messages=[{"role": "user", "content": prompt}],
            system_prompt="You are a session summarizer. Return ONLY a 2-3 sentence summary.",
            tools=None,
        )

        if result:
            summary = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    summary += block.get("text", "")
            summary = summary.strip()
            if summary:
                frappe.db.set_value("AI Chat Session", session_name,
                                    "session_summary", summary, update_modified=False)
                frappe.db.commit()
                return summary
    except Exception as e:
        frappe.log_error(title="Memory: Session Summary Error", message=str(e))

    return None


# ─── Cross-Session Insight Extraction (P2.3) ────────────────────────────────

# Maximum number of tokens to send for insight extraction
_MAX_INSIGHT_INPUT_CHARS = 3000

# Extraction prompt — instructs the utility model to return structured JSON
_INSIGHT_EXTRACTION_PROMPT = """Analyze this business chat session and extract structured insights.

Return ONLY valid JSON with exactly this schema (no markdown, no explanation):
{
  "entities": ["list of specific business entities mentioned: customer names, product names, supplier names, department names, account names"],
  "metrics_tracked": ["list of specific KPIs or metrics the user checked: revenue, DSO, outstanding, collections, etc."],
  "patterns": ["list of behavioral observations: e.g., 'checks revenue daily', 'monitors Malabar account closely', 'prefers data in table format'"],
  "follow_ups": ["list of any unresolved questions or things the user mentioned wanting to do next"]
}

Rules:
- entities: Only include SPECIFIC names (e.g., "Malabar Rural Dev Foundation"), not generic terms
- metrics_tracked: Include the specific metric, not the question (e.g., "monthly revenue" not "what is revenue")
- patterns: Infer behavioral patterns from the conversation flow, not just restate what was asked
- follow_ups: Only include if the user explicitly mentioned wanting to do something later
- Return empty arrays [] for any category with no relevant items
- Maximum 5 items per category"""


def extract_session_insights(session_name):
    """
    Extract structured insights from a completed chat session.
    Called automatically after session summarization.

    Stores a JSON object on the session with:
    - entities: specific business entities the user discussed
    - metrics_tracked: KPIs and metrics the user checked
    - patterns: behavioral observations
    - follow_ups: unresolved items

    Returns the insights dict or None on failure.
    """
    session = frappe.get_doc("AI Chat Session", session_name)

    # Skip if already extracted
    existing = session.get("session_insights")
    if existing:
        try:
            parsed = json.loads(existing) if isinstance(existing, str) else existing
            if parsed and any(parsed.get(k) for k in ("entities", "metrics_tracked", "patterns", "follow_ups")):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    messages_raw = session.get("messages_json")
    if not messages_raw:
        return None

    try:
        messages = json.loads(messages_raw) if isinstance(messages_raw, str) else messages_raw
    except (json.JSONDecodeError, TypeError):
        return None

    # Need at least 2 user messages for meaningful insights
    user_messages = [m for m in messages if m.get("role") == "user"]
    if len(user_messages) < 2:
        return None

    # Build a condensed conversation transcript for the LLM
    transcript_parts = []
    char_count = 0
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        # Truncate individual messages
        truncated = content[:400]
        line = f"{role.upper()}: {truncated}"
        if char_count + len(line) > _MAX_INSIGHT_INPUT_CHARS:
            break
        transcript_parts.append(line)
        char_count += len(line)

    if not transcript_parts:
        return None

    transcript = "\n".join(transcript_parts)

    try:
        from .providers import get_model_for_tier, call_model

        utility_model = get_model_for_tier("utility")
        if not utility_model:
            return None

        result = call_model(
            utility_model,
            messages=[{"role": "user", "content": f"Session transcript:\n\n{transcript}"}],
            system_prompt=_INSIGHT_EXTRACTION_PROMPT,
            tools=None,
        )

        if not result:
            return None

        # Extract text from response
        response_text = ""
        for block in result.get("content", []):
            if block.get("type") == "text":
                response_text += block.get("text", "")
        response_text = response_text.strip()

        if not response_text:
            return None

        # Parse JSON — handle cases where model wraps in ```json ... ```
        clean_text = response_text
        if clean_text.startswith("```"):
            # Strip markdown code fences
            lines = clean_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            clean_text = "\n".join(lines)

        insights = json.loads(clean_text)

        # Validate structure — ensure all expected keys exist with lists
        validated = {
            "entities": _clean_list(insights.get("entities", []), max_items=5),
            "metrics_tracked": _clean_list(insights.get("metrics_tracked", []), max_items=5),
            "patterns": _clean_list(insights.get("patterns", []), max_items=5),
            "follow_ups": _clean_list(insights.get("follow_ups", []), max_items=5),
        }

        # Store on the session record
        insights_json = json.dumps(validated, ensure_ascii=False)
        frappe.db.set_value("AI Chat Session", session_name,
                            "session_insights", insights_json, update_modified=False)
        frappe.db.commit()
        return validated

    except json.JSONDecodeError:
        frappe.log_error(
            title="Memory: Insight JSON Parse Error",
            message=f"Session: {session_name}\nResponse: {response_text[:500]}"
        )
    except Exception as e:
        frappe.log_error(title="Memory: Insight Extraction Error", message=str(e))

    return None


def _clean_list(items, max_items=5):
    """Ensure items is a list of non-empty strings, capped at max_items."""
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items:
        if isinstance(item, str) and item.strip():
            cleaned.append(item.strip()[:200])  # Cap individual item length
    return cleaned[:max_items]


# ─── Cross-Session Insight Aggregation ───────────────────────────────────────

def get_cross_session_insights(user, max_sessions=10):
    """
    Aggregate insights from the user's recent sessions.
    Returns a formatted string suitable for injection into the system prompt.

    Uses recency-weighted deduplication:
    - Recent sessions (last 3): weight 3x
    - Middle sessions (4-7): weight 2x
    - Older sessions (8-10): weight 1x

    Deduplicates entities and metrics using normalized matching.
    """
    sessions = frappe.get_all(
        "AI Chat Session",
        filters={
            "user": user,
            "session_insights": ["is", "set"],
        },
        fields=["session_insights", "modified"],
        order_by="modified desc",
        limit=max_sessions,
    )

    if not sessions:
        return ""

    # Aggregate with recency weighting
    entity_counter = Counter()
    metric_counter = Counter()
    all_patterns = []
    all_follow_ups = []

    for idx, s in enumerate(sessions):
        try:
            insights = json.loads(s.session_insights) if isinstance(s.session_insights, str) else s.session_insights
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(insights, dict):
            continue

        # Recency weight: first 3 sessions get 3x, next 4 get 2x, rest get 1x
        weight = 3 if idx < 3 else (2 if idx < 7 else 1)

        for entity in insights.get("entities", []):
            entity_counter[_normalize_key(entity)] += weight

        for metric in insights.get("metrics_tracked", []):
            metric_counter[_normalize_key(metric)] += weight

        for pattern in insights.get("patterns", []):
            all_patterns.append(pattern)

        for follow_up in insights.get("follow_ups", []):
            all_follow_ups.append(follow_up)

    # Build the output sections
    parts = []

    # Top entities (by weighted frequency)
    top_entities = [name for name, _ in entity_counter.most_common(8)]
    if top_entities:
        parts.append(f"Key entities this user tracks: {', '.join(top_entities)}")

    # Top metrics
    top_metrics = [name for name, _ in metric_counter.most_common(6)]
    if top_metrics:
        parts.append(f"Metrics this user monitors: {', '.join(top_metrics)}")

    # Deduplicate patterns (simple substring dedup)
    unique_patterns = _deduplicate_strings(all_patterns, max_items=5)
    if unique_patterns:
        pattern_lines = [f"- {p}" for p in unique_patterns]
        parts.append("Behavioral patterns observed:\n" + "\n".join(pattern_lines))

    # Recent follow-ups (only from last 3 sessions — older ones are stale)
    recent_follow_ups = []
    for idx, s in enumerate(sessions[:3]):
        try:
            insights = json.loads(s.session_insights) if isinstance(s.session_insights, str) else s.session_insights
            for fu in insights.get("follow_ups", []):
                recent_follow_ups.append(fu)
        except (json.JSONDecodeError, TypeError):
            continue

    unique_follow_ups = _deduplicate_strings(recent_follow_ups, max_items=3)
    if unique_follow_ups:
        fu_lines = [f"- {f}" for f in unique_follow_ups]
        parts.append("Open follow-ups from recent sessions:\n" + "\n".join(fu_lines))

    if not parts:
        return ""

    return "\n".join(parts)


def _normalize_key(text):
    """Normalize a string for deduplication (lowercase, strip whitespace)."""
    return text.strip().lower() if isinstance(text, str) else ""


def _deduplicate_strings(strings, max_items=5):
    """
    Deduplicate a list of strings by checking if one is a substring of another.
    Keeps the longer/more detailed version. Returns at most max_items.
    """
    if not strings:
        return []

    # Sort by length descending so longer strings are preferred
    sorted_strings = sorted(set(strings), key=len, reverse=True)
    unique = []

    for s in sorted_strings:
        s_lower = s.lower().strip()
        if not s_lower:
            continue
        # Check if this is a substring of any already-kept string
        is_duplicate = False
        for kept in unique:
            if s_lower in kept.lower() or kept.lower() in s_lower:
                is_duplicate = True
                break
        if not is_duplicate:
            unique.append(s)
        if len(unique) >= max_items:
            break

    return unique


# ─── Memory Retrieval ────────────────────────────────────────────────────────

def get_memory_context(user):
    """
    Get the full memory context to inject into the system prompt.
    Returns a string combining all memory layers:
    1. Recent session summaries
    2. Cross-session insights (entities, metrics, patterns, follow-ups)
    3. User preferences
    4. Recurring topics
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

    # 2. Cross-session insights (NEW in v3.0)
    insights_text = get_cross_session_insights(user)
    if insights_text:
        parts.append("Cross-session intelligence:\n" + insights_text)

    # 3. User preferences
    prefs = get_user_preferences(user)
    if prefs:
        pref_lines = [f"- {k}: {v}" for k, v in prefs.items()]
        parts.append("User preferences:\n" + "\n".join(pref_lines))

    # 4. Recurring topics (what the user asks about most)
    topics = _get_recurring_topics(user)
    if topics:
        parts.append(f"User frequently asks about: {', '.join(topics)}")

    if not parts:
        return ""

    return "\n\n".join(parts)


# ─── User Preferences ───────────────────────────────────────────────────────

def get_user_preferences(user):
    """
    Get stored user preferences. These are explicit settings
    the user has communicated (e.g., "show amounts in lakhs").

    Bootstrap-safe: checks if custom_ai_preferences field exists before querying.
    On fresh install, the field may not exist yet (created by after_install hook).
    """
    try:
        if not frappe.db.has_column("User", "custom_ai_preferences"):
            return {}
        prefs_json = frappe.db.get_value("User", user, "custom_ai_preferences")
        if prefs_json:
            return json.loads(prefs_json) if isinstance(prefs_json, str) else prefs_json
    except Exception:
        pass
    return {}


def save_user_preference(user, key, value):
    """Save a user preference for future sessions."""
    try:
        if not frappe.db.has_column("User", "custom_ai_preferences"):
            return False

        prefs = get_user_preferences(user)
        prefs[key] = value

        frappe.db.set_value("User", user, "custom_ai_preferences",
                            json.dumps(prefs, ensure_ascii=False), update_modified=False)
        frappe.db.commit()
        return True
    except Exception as e:
        frappe.log_error(title="Memory: Save Preference Error", message=str(e))
        return False


# ─── Recurring Topics ────────────────────────────────────────────────────────

def _get_recurring_topics(user):
    """
    Analyze recent queries to find recurring business topics with temporal decay.

    Recent queries carry more weight than older ones:
      - Last 7 days:   weight 3.0  (strong signal — current focus)
      - 8-30 days:     weight 1.5  (moderate signal — recent interest)
      - 31+ days:      weight 0.5  (weak signal — historical context)

    Returns a list of top 3-5 topic keywords sorted by weighted score.
    """
    from frappe.utils import now_datetime

    recent = frappe.get_all(
        "AI Usage Log",
        filters={"user": user, "model": ["not in", ["alert-engine", "briefing-engine", "scheduled-report-engine"]]},
        fields=["question", "creation"],
        order_by="creation desc",
        limit=80,
    )

    if len(recent) < 5:
        return []

    now = now_datetime()

    topic_keywords = {
        "sales": ["sales", "revenue", "order", "invoice", "customer"],
        "collections": ["payment", "collection", "receivable", "outstanding", "dso"],
        "purchase": ["purchase", "supplier", "vendor", "procurement"],
        "inventory": ["stock", "inventory", "warehouse", "item", "bin"],
        "finance": ["cash", "bank", "profit", "loss", "margin", "expense"],
        "production": ["production", "manufacturing", "batch", "work order"],
        "hr": ["employee", "attendance", "leave", "salary", "payroll"],
    }

    topic_scores = {topic: 0.0 for topic in topic_keywords}
    total_weight = 0.0

    for log in recent:
        q = (log.question or "").lower()
        if not q:
            continue

        # Calculate temporal decay weight
        age_days = (now - log.creation).total_seconds() / 86400
        if age_days <= 7:
            weight = 3.0
        elif age_days <= 30:
            weight = 1.5
        else:
            weight = 0.5

        total_weight += weight

        for topic, keywords in topic_keywords.items():
            if any(kw in q for kw in keywords):
                topic_scores[topic] += weight

    if total_weight == 0:
        return []

    # Normalize: topic score as % of total weighted queries
    # Threshold: topic must represent 15%+ of weighted activity
    threshold = total_weight * 0.15
    top_topics = sorted(
        [(topic, score) for topic, score in topic_scores.items() if score >= threshold],
        key=lambda x: x[1], reverse=True,
    )

    return [t[0] for t in top_topics[:5]]


# ─── Auto-Summary & Insight Trigger ─────────────────────────────────────────

def maybe_summarize_on_close(session_name):
    """
    Called when a session is archived/closed.
    Generates a summary AND extracts insights if the session has enough messages.
    """
    try:
        session = frappe.get_doc("AI Chat Session", session_name)

        # Generate summary if not already done
        if not session.get("session_summary"):
            summarize_session(session_name)

        # Extract insights if not already done (P2.3)
        if not session.get("session_insights"):
            extract_session_insights(session_name)

    except Exception as e:
        frappe.log_error(title="Memory: Auto-Summary Error", message=str(e))
        return None
