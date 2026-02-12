"""
TM AI Assistant — API Endpoints v5.0
======================================
Whitelisted API methods accessible from the mobile app.

Endpoints:
  POST /api/method/tm_ai_assistant.api.chat           — Send a chat message (sync)
  POST /api/method/tm_ai_assistant.api.chat_start     — Start streaming chat (returns stream_id)
  GET  /api/method/tm_ai_assistant.api.stream_poll     — Poll for streaming tokens
  GET  /api/method/tm_ai_assistant.api.chat_status     — Check if AI chat is enabled for user
  GET  /api/method/tm_ai_assistant.api.usage           — Get usage stats for current user
  GET  /api/method/tm_ai_assistant.api.alerts          — Get alert status for current user
  GET  /api/method/tm_ai_assistant.api.get_session     — Load a session's messages
  GET  /api/method/tm_ai_assistant.api.list_sessions   — List recent sessions
  POST /api/method/tm_ai_assistant.api.close_session   — Archive a session
  POST /api/method/tm_ai_assistant.api.upload_file     — Upload image for Vision (Phase 4.4)
  POST /api/method/tm_ai_assistant.api.transcribe_audio — Voice-to-text via Whisper (Phase 4.3)
  GET  /api/method/tm_ai_assistant.api.search_sessions — Search past conversations (Phase 5.3)

v5.0 changes (Phase 4+5):
- upload_file endpoint: multipart upload for Vision analysis
- transcribe_audio endpoint: OpenAI Whisper for voice input
- search_sessions endpoint: full-text search across conversations
- chat_start accepts file_url for multimodal streaming
- _run_stream_job passes image_data to process_chat_stream

v4.0 changes (Phase 3 — Response Streaming):
- New chat_start endpoint: enqueues background job, returns stream_id
- New stream_poll endpoint: frontend polls for new tokens from Redis

v3.0 changes (Phase 2):
- Server-side message storage, session management
"""

import json
import frappe
from frappe import _


# ─── Configuration ────────────────────────────────────────────────────────

# Sprint 6A: Role-based daily limits instead of flat 50
# Executive/Management get more queries; field staff get fewer (simpler queries)
ROLE_DAILY_LIMITS = {
    "System Manager": 200,      # Admin — unlimited-ish
    "Administrator": 200,
    "Accounts Manager": 100,    # Finance team — heavy analysis
    "Sales Manager": 80,        # Sales leadership
    "Purchase Manager": 80,     # Purchase leadership
    "Stock Manager": 60,        # Warehouse management
    "Manufacturing Manager": 60,
    "_default": 50,             # Default for all other roles
    "_field_staff": 30,         # Field operatives — quick lookups only
}
_FIELD_ROLES = {"Sales User", "Stock User", "Manufacturing User", "Purchase User"}

MAX_CONTEXT_MESSAGES = 20  # Max messages to send to Claude for context
MAX_STORED_MESSAGES = 100  # Sprint 6A: Max messages to store per session (pruning threshold)
SMART_TITLE_MODEL = "claude-haiku-4-5-20251001"  # Sprint 6A: Cheap model for title generation


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_daily_limit(user):
    """
    Sprint 6A: Get the daily query limit for a user based on their ERPNext roles.
    Higher roles get higher limits. Returns the highest limit among user's roles.
    """
    if user == "Administrator":
        return ROLE_DAILY_LIMITS["Administrator"]

    try:
        user_roles = frappe.get_roles(user)
    except Exception:
        return ROLE_DAILY_LIMITS["_default"]

    # Check if user is field staff (lower limit)
    if _FIELD_ROLES.intersection(set(user_roles)) and not {"System Manager", "Accounts Manager", "Sales Manager", "Purchase Manager"}.intersection(set(user_roles)):
        return ROLE_DAILY_LIMITS["_field_staff"]

    # Find the highest limit among user's roles
    max_limit = ROLE_DAILY_LIMITS["_default"]
    for role in user_roles:
        if role in ROLE_DAILY_LIMITS:
            max_limit = max(max_limit, ROLE_DAILY_LIMITS[role])

    return max_limit


def _check_ai_access(user=None):
    """Check if the current user has AI chat access."""
    user = user or frappe.session.user
    if user == "Administrator":
        return True

    allow = frappe.db.get_value("User", user, "allow_ai_chat")
    return bool(allow)


def _get_daily_usage(user):
    """Get today's query count for rate limiting."""
    today = frappe.utils.today()
    count = frappe.db.count("AI Usage Log", filters={
        "user": user,
        "creation": [">=", today],
    })
    return count


def _generate_smart_title(message, response_text):
    """
    Sprint 6A: Generate a concise 5-word session title using Haiku.
    Falls back to truncation if the API call fails.
    """
    try:
        import requests as req

        api_key = frappe.conf.get("anthropic_api_key")
        if not api_key:
            from .ai_engine import get_api_key
            api_key = get_api_key()

        prompt = (
            f"Generate a very short title (max 5 words) for this conversation. "
            f"No quotes, no punctuation at the end. Just the title.\n\n"
            f"User asked: {message[:200]}\n"
            f"Assistant replied about: {response_text[:200]}"
        )

        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": SMART_TITLE_MODEL,
                "max_tokens": 30,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=5,  # Fast timeout — titles are non-critical
        )

        if resp.status_code == 200:
            data = resp.json()
            title = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    title += block["text"]
            title = title.strip().strip('"').strip("'")
            if title and len(title) < 80:
                return title

    except Exception:
        pass  # Non-critical — fall back to truncation

    # Fallback: smart truncation
    title = message[:80].strip()
    if len(message) > 80:
        title += "..."
    return title


def _prune_messages(messages):
    """
    Sprint 6A: Prune old messages if session exceeds MAX_STORED_MESSAGES.
    Keeps the first 2 messages (establishes context) and the most recent messages.
    Returns the pruned list.
    """
    if len(messages) <= MAX_STORED_MESSAGES:
        return messages

    # Keep first 2 (session opener) + last (MAX_STORED_MESSAGES - 4) + pruning marker
    first_messages = messages[:2]
    keep_count = MAX_STORED_MESSAGES - 3  # 2 first + 1 marker
    recent_messages = messages[-keep_count:]
    pruned_count = len(messages) - 2 - keep_count

    pruning_marker = {
        "role": "system",
        "content": f"[{pruned_count} older messages pruned to save space]",
        "timestamp": frappe.utils.now_datetime().strftime("%Y-%m-%dT%H:%M:%S"),
        "pruned": True,
    }

    return first_messages + [pruning_marker] + recent_messages


# ─── Session Management ──────────────────────────────────────────────────

def _get_or_create_session(session_id, user):
    """
    Get an existing session by session_id, or create a new one.
    Returns the AI Chat Session doc.
    """
    if session_id:
        # Try to find existing session
        exists = frappe.db.exists("AI Chat Session", {
            "session_id": session_id,
            "user": user,
        })
        if exists:
            doc_name = frappe.db.get_value("AI Chat Session", {
                "session_id": session_id,
                "user": user,
            }, "name")
            return frappe.get_doc("AI Chat Session", doc_name)

    # Create new session
    new_session_id = session_id or frappe.generate_hash(length=16)
    doc = frappe.get_doc({
        "doctype": "AI Chat Session",
        "user": user,
        "session_id": new_session_id,
        "status": "Active",
        "started_at": frappe.utils.now_datetime(),
        "total_tokens": 0,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc


def _load_messages(session):
    """
    Load messages from session's messages_json field.
    Returns list of {role, content} dicts for Claude API.
    """
    raw = session.get("messages_json")
    if not raw:
        return []

    try:
        messages = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(messages, list):
            return []
        return messages
    except (json.JSONDecodeError, TypeError):
        return []


def _save_message_pair(session, user_message, assistant_response, usage):
    """
    Append user message + assistant response to session's messages_json.
    Also updates total_tokens.
    """
    messages = _load_messages(session)

    now_str = frappe.utils.now_datetime().strftime("%Y-%m-%dT%H:%M:%S")

    # Append user message
    messages.append({
        "role": "user",
        "content": user_message,
        "timestamp": now_str,
    })

    # Append assistant response
    messages.append({
        "role": "assistant",
        "content": assistant_response,
        "timestamp": now_str,
        "tokens": usage.get("total_tokens", 0),
        "tool_calls": usage.get("tool_calls", 0),
    })

    # Sprint 6A: Prune old messages if session is getting too long
    messages = _prune_messages(messages)

    # Update session
    new_total = (session.total_tokens or 0) + usage.get("total_tokens", 0)
    frappe.db.set_value("AI Chat Session", session.name, {
        "messages_json": json.dumps(messages, ensure_ascii=False),
        "total_tokens": new_total,
    }, update_modified=True)


def _get_context_messages(messages):
    """
    Get the last N messages formatted for Claude API.
    Only sends role + content (strips metadata like timestamps).
    """
    # Take last MAX_CONTEXT_MESSAGES messages
    recent = messages[-MAX_CONTEXT_MESSAGES:] if len(messages) > MAX_CONTEXT_MESSAGES else messages

    return [
        {"role": m["role"], "content": m["content"]}
        for m in recent
        if m.get("role") and m.get("content")
    ]


# ─── Chat Endpoint ──────────────────────────────────────────────────────────

@frappe.whitelist()
def chat(message, session_id=None):
    """
    Main chat endpoint. Receives a user message and returns an AI response.

    Phase 2: Server manages conversation history. Client only sends the new
    message + session_id. Server loads prior messages from DB, sends context
    to Claude, saves the response, and returns it.

    Args:
        message (str): The user's question
        session_id (str, optional): Existing session ID to resume

    Returns:
        dict: {response, session_id, session_title, message_count, usage, daily_queries_remaining}
    """
    user = frappe.session.user

    # 1. Check AI access
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled for your account. Contact your administrator."), frappe.PermissionError)

    # 2. Check rate limit (Sprint 6A: role-based limits)
    daily_count = _get_daily_usage(user)
    user_limit = _get_daily_limit(user)
    if daily_count >= user_limit:
        frappe.throw(_(f"Daily query limit ({user_limit}) reached. Limit resets tomorrow."), frappe.ValidationError)

    # 3. Get or create session
    session = _get_or_create_session(session_id, user)

    # 4. Load conversation history from server (NOT from client)
    all_messages = _load_messages(session)
    context_messages = _get_context_messages(all_messages)

    # 5a. Sprint 6B: Check if query needs clarification
    from .ai_engine import process_chat, get_model, classify_and_clarify, get_cached_plan

    clarification = classify_and_clarify(message)
    if clarification["needs_clarification"] and not context_messages:
        # First message in session and it's ambiguous — ask for clarification
        # Don't clarify mid-conversation (user has context)
        return {
            "response": clarification["clarification_question"],
            "needs_clarification": True,
            "clarification_options": clarification["options"],
            "session_id": session.session_id,
            "session_title": session.title or "",
            "message_count": len(all_messages),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "tool_calls": 0,
            "daily_queries_remaining": max(0, user_limit - daily_count),
        }

    # 5b. Sprint 6B: Check plan cache for common queries
    cached_plan = get_cached_plan(message)
    plan_hint = ""
    if cached_plan:
        # Inject plan hint into the message so Claude uses the right tools immediately
        plan_hint = f"\n[System hint: Use {', '.join(cached_plan.get('tools', []))} tool(s). {cached_plan.get('description', cached_plan.get('query_hint', ''))}]"

    # 5c. Process through AI engine
    try:
        result = process_chat(
            user=user,
            question=message + plan_hint if plan_hint else message,
            conversation_history=context_messages if context_messages else None,
        )
    except Exception as e:
        frappe.log_error(title="AI Chat Processing Error", message=str(e))
        result = {
            "response": "I ran into a temporary issue processing your request. Please try again.",
            "tool_calls": 0,
            "model": get_model(),
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }

    # 6. Save message pair to session
    _save_message_pair(session, message, result["response"], {
        "total_tokens": result["usage"].get("total_tokens", 0),
        "tool_calls": result.get("tool_calls", 0),
    })

    # 7. Auto-title: Sprint 6A — smart title via Haiku instead of dumb truncation
    session_title = session.title
    if not session_title:
        session_title = _generate_smart_title(message, result["response"])
        frappe.db.set_value("AI Chat Session", session.name, "title", session_title)

    # 8. Log usage
    try:
        model = result.get("model", get_model())
        frappe.get_doc({
            "doctype": "AI Usage Log",
            "user": user,
            "session_id": session.session_id,
            "question": message[:500],
            "input_tokens": result["usage"]["input_tokens"],
            "output_tokens": result["usage"]["output_tokens"],
            "total_tokens": result["usage"]["total_tokens"],
            "tool_calls": result.get("tool_calls", 0),
            "model": model,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="AI Usage Log Error", message=str(e))

    # 9. Count messages for response
    updated_messages = _load_messages(session)

    # 10. Return response
    return {
        "response": result["response"],
        "session_id": session.session_id,
        "session_title": session_title,
        "message_count": len(updated_messages),
        "usage": result["usage"],
        "tool_calls": result.get("tool_calls", 0),
        "daily_queries_remaining": max(0, user_limit - daily_count - 1),
    }


# ─── Session Endpoints ──────────────────────────────────────────────────────

@frappe.whitelist()
def get_session(session_id):
    """
    Load a session's full message history.

    Args:
        session_id (str): The session ID

    Returns:
        dict: {session_id, title, status, messages, total_tokens, started_at}
    """
    user = frappe.session.user

    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled."), frappe.PermissionError)

    doc_name = frappe.db.get_value("AI Chat Session", {
        "session_id": session_id,
        "user": user,
    }, "name")

    if not doc_name:
        frappe.throw(_("Session not found."), frappe.DoesNotExistError)

    session = frappe.get_doc("AI Chat Session", doc_name)
    messages = _load_messages(session)

    return {
        "session_id": session.session_id,
        "title": session.title or "Untitled",
        "status": session.status,
        "messages": messages,
        "message_count": len(messages),
        "total_tokens": session.total_tokens or 0,
        "started_at": str(session.started_at) if session.started_at else None,
    }


@frappe.whitelist()
def list_sessions(limit=20):
    """
    List recent chat sessions for the current user.

    Args:
        limit (int): Max sessions to return (default 20)

    Returns:
        dict: {sessions: [{session_id, title, status, message_count, total_tokens, started_at, last_message}]}
    """
    user = frappe.session.user

    if not _check_ai_access(user):
        return {"sessions": []}

    limit = min(int(limit), 50)

    sessions = frappe.get_all(
        "AI Chat Session",
        filters={"user": user},
        fields=["session_id", "title", "status", "total_tokens",
                "started_at", "messages_json", "modified"],
        order_by="modified desc",
        limit_page_length=limit,
    )

    result = []
    for s in sessions:
        # Extract message count and last message preview
        messages = []
        try:
            if s.messages_json:
                messages = json.loads(s.messages_json) if isinstance(s.messages_json, str) else s.messages_json
        except (json.JSONDecodeError, TypeError):
            messages = []

        last_message = ""
        if messages:
            last_msg = messages[-1]
            last_message = (last_msg.get("content", ""))[:100]

        result.append({
            "session_id": s.session_id,
            "title": s.title or "Untitled",
            "status": s.status,
            "message_count": len(messages),
            "total_tokens": s.total_tokens or 0,
            "started_at": str(s.started_at) if s.started_at else None,
            "last_modified": str(s.modified) if s.modified else None,
            "last_message": last_message,
        })

    return {"sessions": result}


@frappe.whitelist()
def close_session(session_id):
    """
    Close/archive a chat session.

    Args:
        session_id (str): The session ID to close

    Returns:
        dict: {success: True}
    """
    user = frappe.session.user

    doc_name = frappe.db.get_value("AI Chat Session", {
        "session_id": session_id,
        "user": user,
    }, "name")

    if not doc_name:
        frappe.throw(_("Session not found."), frappe.DoesNotExistError)

    frappe.db.set_value("AI Chat Session", doc_name, {
        "status": "Closed",
        "ended_at": frappe.utils.now_datetime(),
    })
    frappe.db.commit()

    # Sprint 8: Auto-summarize session for memory across sessions
    try:
        from .memory import maybe_summarize_on_close
        maybe_summarize_on_close(doc_name)
    except Exception:
        pass  # Memory is non-critical — never block session close

    return {"success": True}


# ─── Streaming Endpoints (Phase 3) ───────────────────────────────────────────

@frappe.whitelist()
def chat_start(message, session_id=None, file_url=None):
    """
    Start a streaming chat. Enqueues a background job that streams Claude's
    response, writing tokens to Redis in real-time. Returns a stream_id
    that the frontend polls via stream_poll().

    Args:
        message (str): The user's question
        session_id (str, optional): Existing session ID to resume
        file_url (str, optional): URL of an uploaded image/file for Vision analysis

    Returns:
        dict: {stream_id, session_id}
    """
    user = frappe.session.user

    # 1. Check AI access
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled for your account."), frappe.PermissionError)

    # 2. Check rate limit (Sprint 6A: role-based limits)
    daily_count = _get_daily_usage(user)
    user_limit = _get_daily_limit(user)
    if daily_count >= user_limit:
        frappe.throw(_(f"Daily query limit ({user_limit}) reached."), frappe.ValidationError)

    # 3. Get or create session
    session = _get_or_create_session(session_id, user)

    # 4. Load context messages from server
    all_messages = _load_messages(session)
    context_messages = _get_context_messages(all_messages)

    # 4b. Sprint 6B: Check clarification for ambiguous first messages
    from .ai_engine import classify_and_clarify, get_cached_plan

    clarification = classify_and_clarify(message)
    if clarification["needs_clarification"] and not context_messages:
        return {
            "needs_clarification": True,
            "clarification_question": clarification["clarification_question"],
            "clarification_options": clarification["options"],
            "session_id": session.session_id,
            "stream_id": None,
        }

    # 4c. Sprint 6B: Inject plan cache hint if available
    cached_plan = get_cached_plan(message)
    actual_message = message
    if cached_plan:
        plan_hint = f"\n[System hint: Use {', '.join(cached_plan.get('tools', []))} tool(s). {cached_plan.get('description', cached_plan.get('query_hint', ''))}]"
        actual_message = message + plan_hint

    # 5. Generate stream ID and initialize Redis
    stream_id = frappe.generate_hash(length=16)
    cache_key = f"tm_ai_stream:{stream_id}"
    frappe.cache.set_value(cache_key, json.dumps({
        "status": "starting",
        "text": "",
        "tool_status": None,
        "done": False,
        "error": None,
        "usage": {},
        "tool_calls": 0,
        "session_id": session.session_id,
        "session_title": session.title or "",
        "message_count": 0,
        "daily_remaining": max(0, user_limit - daily_count - 1),
    }), expires_in_sec=300)

    # 6. Enqueue background job (use actual_message with plan hint if any)
    frappe.enqueue(
        "tm_ai_assistant.api._run_stream_job",
        queue="long",
        timeout=300,
        stream_id=stream_id,
        user=user,
        message=actual_message,
        session_name=session.name,
        session_id_str=session.session_id,
        context_messages=context_messages if context_messages else None,
        daily_count=daily_count,
        file_url=file_url,
    )

    return {
        "stream_id": stream_id,
        "session_id": session.session_id,
    }


def _run_stream_job(stream_id, user, message, session_name, session_id_str,
                    context_messages=None, daily_count=0, file_url=None):
    """
    Background job: runs streaming chat, saves results to session, logs usage.
    Called via frappe.enqueue() from chat_start().
    file_url: if provided, downloads and converts to base64 image_data for Vision.
    """
    from .ai_engine import process_chat_stream, get_model

    cache_key = f"tm_ai_stream:{stream_id}"

    try:
        # Phase 4.4: Convert file_url to image_data for Claude Vision
        image_data = None
        if file_url:
            try:
                image_data = _download_file_as_image_data(file_url)
            except Exception as img_err:
                frappe.log_error(title="AI Image Download Error", message=str(img_err))
                # Continue without image — don't fail the whole request

        # Run the streaming chat (tokens pushed to Redis in real-time)
        result = process_chat_stream(
            user=user,
            question=message,
            conversation_history=context_messages,
            stream_id=stream_id,
            image_data=image_data,
        )

        # Save message pair to session
        frappe.set_user(user)
        session = frappe.get_doc("AI Chat Session", session_name)
        _save_message_pair(session, message, result["response"], {
            "total_tokens": result["usage"].get("total_tokens", 0),
            "tool_calls": result.get("tool_calls", 0),
        })

        # Auto-title (Sprint 6A: smart title via Haiku)
        session_title = session.title
        if not session_title:
            session_title = _generate_smart_title(message, result["response"])
            frappe.db.set_value("AI Chat Session", session.name, "title", session_title)

        # Log usage
        model = result.get("model", get_model())
        try:
            frappe.get_doc({
                "doctype": "AI Usage Log",
                "user": user,
                "session_id": session_id_str,
                "question": message[:500],
                "input_tokens": result["usage"]["input_tokens"],
                "output_tokens": result["usage"]["output_tokens"],
                "total_tokens": result["usage"]["total_tokens"],
                "tool_calls": result.get("tool_calls", 0),
                "model": model,
            }).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(title="AI Stream Usage Log Error", message=str(e))

        # Get updated counts
        updated_messages = _load_messages(session)
        updated_daily = _get_daily_usage(user)

        # Final Redis update — marks stream as done
        frappe.cache.set_value(cache_key, json.dumps({
            "status": "done",
            "text": result["response"],
            "tool_status": None,
            "done": True,
            "error": None,
            "usage": result["usage"],
            "tool_calls": result.get("tool_calls", 0),
            "session_id": session_id_str,
            "session_title": session_title or "",
            "message_count": len(updated_messages),
            "daily_remaining": max(0, _get_daily_limit(user) - updated_daily),
        }), expires_in_sec=300)

    except Exception as e:
        frappe.log_error(title="AI Stream Job Error", message=str(e))
        frappe.cache.set_value(cache_key, json.dumps({
            "status": "error",
            "text": "",
            "tool_status": None,
            "done": True,
            "error": str(e)[:200],
            "usage": {},
            "tool_calls": 0,
            "session_id": session_id_str or "",
            "session_title": "",
            "message_count": 0,
            "daily_remaining": 0,
        }), expires_in_sec=300)


@frappe.whitelist()
def stream_poll(stream_id, last_length=0):
    """
    Poll for streaming chat updates. Returns new text since last_length.

    Args:
        stream_id (str): Stream ID from chat_start()
        last_length (int): Length of text the client already has

    Returns:
        dict: {status, text, delta, text_length, tool_status, done, error, ...}
    """
    cache_key = f"tm_ai_stream:{stream_id}"
    raw = frappe.cache.get_value(cache_key)

    if not raw:
        return {
            "status": "error",
            "text": "",
            "delta": "",
            "text_length": 0,
            "tool_status": None,
            "done": True,
            "error": "Stream not found or expired.",
        }

    data = json.loads(raw) if isinstance(raw, str) else raw

    text = data.get("text", "")
    last_length = int(last_length)
    delta = text[last_length:] if last_length < len(text) else ""
    is_done = data.get("done", False)

    result = {
        "status": data.get("status", "streaming"),
        "text": text,
        "delta": delta,
        "text_length": len(text),
        "tool_status": data.get("tool_status"),
        "done": is_done,
        "error": data.get("error"),
    }

    # Include final metadata only when done
    if is_done:
        result["usage"] = data.get("usage", {})
        result["tool_calls"] = data.get("tool_calls", 0)
        result["session_id"] = data.get("session_id", "")
        result["session_title"] = data.get("session_title", "")
        result["message_count"] = data.get("message_count", 0)
        result["daily_remaining"] = data.get("daily_remaining", 0)

    return result


# ─── Status Endpoint ────────────────────────────────────────────────────────

@frappe.whitelist()
def chat_status():
    """
    Check if AI chat is enabled for the current user and return config.
    Also returns active session ID if one exists (for resumption).
    """
    user = frappe.session.user

    enabled = _check_ai_access(user)
    daily_count = _get_daily_usage(user) if enabled else 0

    # Find most recent active session for resumption
    active_session_id = None
    if enabled:
        active = frappe.db.get_value("AI Chat Session", {
            "user": user,
            "status": "Active",
        }, ["session_id", "title"], order_by="modified desc")
        if active:
            active_session_id = active[0] if isinstance(active, (list, tuple)) else active

    user_limit = _get_daily_limit(user)
    return {
        "enabled": enabled,
        "daily_limit": user_limit,
        "daily_used": daily_count,
        "daily_remaining": max(0, user_limit - daily_count) if enabled else 0,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
        "active_session_id": active_session_id,
    }


# ─── Usage Stats Endpoint ───────────────────────────────────────────────────

@frappe.whitelist()
def usage(period="today"):
    """Get usage statistics. Admins see all users, others see only their own."""
    user = frappe.session.user
    is_admin = "System Manager" in frappe.get_roles(user)

    filters = {}
    if period == "today":
        filters["creation"] = [">=", frappe.utils.today()]
    elif period == "week":
        filters["creation"] = [">=", frappe.utils.add_days(frappe.utils.today(), -7)]
    elif period == "month":
        filters["creation"] = [">=", frappe.utils.add_days(frappe.utils.today(), -30)]

    if not is_admin:
        filters["user"] = user

    logs = frappe.get_all(
        "AI Usage Log",
        filters=filters,
        fields=["user", "SUM(input_tokens) as input_tokens",
                "SUM(output_tokens) as output_tokens",
                "SUM(total_tokens) as total_tokens",
                "COUNT(name) as query_count"],
        group_by="user",
        order_by="total_tokens desc",
    )

    # Estimate cost — Claude Opus 4.6 pricing: $5/M input, $25/M output
    total_input = sum(l.get("input_tokens", 0) or 0 for l in logs)
    total_output = sum(l.get("output_tokens", 0) or 0 for l in logs)
    estimated_cost_usd = (total_input * 5 / 1_000_000) + (total_output * 25 / 1_000_000)
    estimated_cost_inr = estimated_cost_usd * 85  # Approximate USD to INR

    return {
        "period": period,
        "users": logs,
        "totals": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_queries": sum(l.get("query_count", 0) or 0 for l in logs),
            "estimated_cost_usd": round(estimated_cost_usd, 2),
            "estimated_cost_inr": round(estimated_cost_inr, 2),
        },
    }


# ─── Alerts Endpoint ────────────────────────────────────────────────────────

@frappe.whitelist()
def alerts():
    """Get alert status for the current user."""
    user = frappe.session.user

    if not _check_ai_access(user):
        return {"alerts": [], "triggered_today": []}

    # Active alerts
    active_alerts = frappe.get_all(
        "AI Alert Rule",
        filters={"user": user, "active": 1},
        fields=["name", "alert_name", "description", "frequency",
                "threshold_operator", "threshold_value", "last_checked",
                "last_triggered", "last_value", "trigger_count"],
        order_by="creation desc",
    )

    # Today's triggers (from usage log)
    today = frappe.utils.today()
    triggered_today = frappe.get_all(
        "AI Usage Log",
        filters={
            "user": user,
            "model": "alert-engine",
            "creation": [">=", today],
        },
        fields=["question", "creation"],
        order_by="creation desc",
    )

    return {
        "alerts": active_alerts,
        "alert_count": len(active_alerts),
        "triggered_today": triggered_today,
    }


# ─── Alert Test Endpoint (Sprint 7) ──────────────────────────────────────────

@frappe.whitelist()
def test_alert(alert_name):
    """
    Sprint 7: Test an alert immediately — shows current value and whether
    it would trigger, without actually sending notifications.
    """
    user = frappe.session.user
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled."), frappe.PermissionError)

    from .alerts import test_alert as _test_alert
    return _test_alert(alert_name)


# ─── Scheduled Reports Endpoints (Sprint 7) ──────────────────────────────────

@frappe.whitelist()
def create_scheduled_report(report_name, report_query, frequency="daily",
                           export_format="pdf", email_recipients=None, description=None):
    """
    Sprint 7: Create a new scheduled report.
    The report will be auto-generated and emailed at the specified frequency.
    """
    user = frappe.session.user
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled."), frappe.PermissionError)

    # Validate frequency
    if frequency not in ("hourly", "daily", "weekly", "monthly"):
        frappe.throw(_("Frequency must be one of: hourly, daily, weekly, monthly"))

    doc = frappe.get_doc({
        "doctype": "AI Scheduled Report",
        "user": user,
        "report_name": report_name,
        "report_query": report_query,
        "frequency": frequency,
        "export_format": export_format or "pdf",
        "email_recipients": email_recipients or "",
        "description": description or "",
        "active": 1,
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True,
        "report_id": doc.name,
        "message": f"Scheduled report '{report_name}' created. It will run {frequency}.",
    }


@frappe.whitelist()
def list_scheduled_reports():
    """Sprint 7: List the current user's scheduled reports."""
    user = frappe.session.user
    if not _check_ai_access(user):
        return {"reports": []}

    reports = frappe.get_all(
        "AI Scheduled Report",
        filters={"user": user},
        fields=["name", "report_name", "description", "frequency",
                "export_format", "active", "last_generated", "creation"],
        order_by="creation desc",
    )

    return {"reports": reports, "count": len(reports)}


@frappe.whitelist()
def delete_scheduled_report(report_name):
    """Sprint 7: Delete a scheduled report."""
    user = frappe.session.user
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled."), frappe.PermissionError)

    # Verify ownership
    owner = frappe.db.get_value("AI Scheduled Report", report_name, "user")
    if owner != user and "System Manager" not in frappe.get_roles(user):
        frappe.throw(_("You can only delete your own reports."), frappe.PermissionError)

    frappe.delete_doc("AI Scheduled Report", report_name, ignore_permissions=True)
    frappe.db.commit()

    return {"success": True, "message": "Report deleted."}


# ─── Dynamic Suggestions Endpoint (Sprint 6B) ────────────────────────────────

@frappe.whitelist()
def get_suggestions(last_query=None, last_response=None, screen_context=None):
    """
    Sprint 6B: Get contextual suggestion chips for the chat UI.
    No LLM calls — pure Python logic based on time, roles, and recent activity.

    Args:
        last_query (str, optional): User's last message for follow-up suggestions
        last_response (str, optional): Assistant's last response for context
        screen_context (str, optional): Active app screen ("sales", "inventory", etc.)

    Returns:
        dict: {suggestions: [{label, query}]}
    """
    user = frappe.session.user

    if not _check_ai_access(user):
        return {"suggestions": []}

    from .suggestions import get_suggestions as _gen_suggestions

    suggestions = _gen_suggestions(
        user=user,
        last_query=last_query,
        last_response=last_response[:300] if last_response else None,
        screen_context=screen_context,
    )

    return {"suggestions": suggestions}


# ─── File/Image Helpers (Phase 4.4) ──────────────────────────────────────────

def _download_file_as_image_data(file_url):
    """
    Download a Frappe file URL and convert to base64 image_data dict
    suitable for Claude Vision API.

    Args:
        file_url (str): Frappe file URL (e.g., /files/photo.jpg)

    Returns:
        dict: {"data": base64_string, "media_type": "image/jpeg"}
    """
    import base64
    import mimetypes

    # Get the actual file path on disk
    if file_url.startswith("/files/"):
        file_path = frappe.get_site_path("public", file_url.lstrip("/"))
    elif file_url.startswith("/private/files/"):
        file_path = frappe.get_site_path(file_url.lstrip("/"))
    else:
        # Try to find the file doc
        file_doc = frappe.get_all("File", filters={"file_url": file_url}, fields=["file_url", "is_private"], limit=1)
        if not file_doc:
            raise ValueError(f"File not found: {file_url}")
        actual_url = file_doc[0].file_url
        if file_doc[0].is_private:
            file_path = frappe.get_site_path(actual_url.lstrip("/"))
        else:
            file_path = frappe.get_site_path("public", actual_url.lstrip("/"))

    import os
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found on disk: {file_path}")

    # Read file and base64 encode
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    # Detect media type
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/jpeg"  # Default assumption

    # Validate it's an image type Claude can handle
    supported = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if mime_type not in supported:
        raise ValueError(f"Unsupported image type: {mime_type}. Supported: {', '.join(supported)}")

    # Check file size (Claude limit: ~20MB for images, we'll be conservative)
    if len(file_bytes) > 10 * 1024 * 1024:  # 10MB
        raise ValueError("Image file too large. Maximum 10MB.")

    return {
        "data": base64.b64encode(file_bytes).decode("utf-8"),
        "media_type": mime_type,
    }


# ─── File Upload Endpoint (Phase 4.4) ──────────────────────────────────────

@frappe.whitelist()
def upload_file():
    """
    Upload a file for AI Vision analysis. Accepts multipart form upload.
    Returns the file_url that can be passed to chat_start(file_url=...).

    Returns:
        dict: {file_url, file_name, file_type}
    """
    user = frappe.session.user

    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled for your account."), frappe.PermissionError)

    # Get uploaded file from request
    uploaded_file = frappe.request.files.get("file")
    if not uploaded_file:
        frappe.throw(_("No file uploaded."), frappe.ValidationError)

    # Validate file type
    import mimetypes
    mime_type, _ = mimetypes.guess_type(uploaded_file.filename)
    supported_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    if mime_type not in supported_types:
        frappe.throw(_(f"Unsupported file type: {mime_type}. Supported: JPEG, PNG, GIF, WebP"), frappe.ValidationError)

    # Save via Frappe's file manager (private file)
    # NOTE: Do NOT set attached_to_doctype without attached_to_name — Frappe
    # validates this and may reject the file or cause errors.
    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": uploaded_file.filename,
        "content": uploaded_file.read(),
        "is_private": 1,
        "folder": "Home",
    })
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "file_url": file_doc.file_url,
        "file_name": file_doc.file_name,
        "file_type": mime_type,
    }


# ─── Audio Transcription Endpoint (Phase 4.3) ───────────────────────────────

@frappe.whitelist()
def transcribe_audio():
    """
    Transcribe an audio file using OpenAI Whisper API.
    Accepts multipart form upload of audio file.

    Returns:
        dict: {text, language, duration}
    """
    import requests as http_requests

    user = frappe.session.user

    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled for your account."), frappe.PermissionError)

    # Get OpenAI API key from site config
    openai_key = frappe.conf.get("openai_api_key", "")
    if not openai_key:
        frappe.throw(_("Voice input is not configured. OpenAI API key required."), frappe.ValidationError)

    # Get uploaded audio file
    audio_file = frappe.request.files.get("file")
    if not audio_file:
        frappe.throw(_("No audio file uploaded."), frappe.ValidationError)

    try:
        # Call OpenAI Whisper API
        resp = http_requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {openai_key}"},
            files={"file": (audio_file.filename or "audio.m4a", audio_file.read(), "audio/m4a")},
            data={"model": "whisper-1", "language": "en"},
            timeout=30,
        )

        if resp.status_code != 200:
            error_detail = resp.text[:200]
            frappe.log_error(title="Whisper API Error", message=f"Status {resp.status_code}: {error_detail}")
            frappe.throw(_("Failed to transcribe audio. Please try again."), frappe.ValidationError)

        result = resp.json()
        return {
            "text": result.get("text", ""),
            "language": result.get("language", "en"),
        }

    except http_requests.exceptions.Timeout:
        frappe.throw(_("Audio transcription timed out. Please try again."), frappe.ValidationError)
    except Exception as e:
        frappe.log_error(title="Whisper API Error", message=str(e))
        frappe.throw(_("Failed to transcribe audio."), frappe.ValidationError)


# ─── Conversation Search Endpoint (Phase 5.3) ────────────────────────────────

@frappe.whitelist()
def search_sessions(query, limit=20):
    """
    Search across all past conversations for the current user.
    Full-text search on session titles and message content.

    Args:
        query (str): Search text
        limit (int): Max results to return (default 20)

    Returns:
        dict: {results: [{session_id, title, match_preview, started_at, message_count}]}
    """
    user = frappe.session.user

    if not _check_ai_access(user):
        return {"results": []}

    if not query or len(query.strip()) < 2:
        return {"results": []}

    query = query.strip()
    limit = min(int(limit), 50)

    # Search in session titles and messages_json
    # Using LIKE for compatibility (Frappe Cloud MariaDB)
    search_pattern = f"%{query}%"

    sessions = frappe.db.sql("""
        SELECT session_id, title, status, total_tokens,
               started_at, messages_json, modified
        FROM `tabAI Chat Session`
        WHERE user = %(user)s
          AND (title LIKE %(pattern)s OR messages_json LIKE %(pattern)s)
        ORDER BY modified DESC
        LIMIT %(limit)s
    """, {"user": user, "pattern": search_pattern, "limit": limit}, as_dict=True)

    results = []
    for s in sessions:
        # Find the matching message snippet
        match_preview = ""
        message_count = 0
        try:
            if s.messages_json:
                messages = json.loads(s.messages_json) if isinstance(s.messages_json, str) else s.messages_json
                message_count = len(messages)
                # Find first message containing the query
                for m in messages:
                    content = m.get("content", "")
                    if isinstance(content, str) and query.lower() in content.lower():
                        # Extract snippet around the match
                        idx = content.lower().index(query.lower())
                        start = max(0, idx - 40)
                        end = min(len(content), idx + len(query) + 40)
                        snippet = content[start:end]
                        if start > 0:
                            snippet = "..." + snippet
                        if end < len(content):
                            snippet = snippet + "..."
                        match_preview = snippet
                        break
        except (json.JSONDecodeError, TypeError):
            pass

        if not match_preview and s.title and query.lower() in s.title.lower():
            match_preview = s.title

        results.append({
            "session_id": s.session_id,
            "title": s.title or "Untitled",
            "match_preview": match_preview,
            "message_count": message_count,
            "started_at": str(s.started_at) if s.started_at else None,
            "last_modified": str(s.modified) if s.modified else None,
        })

    return {"results": results}
