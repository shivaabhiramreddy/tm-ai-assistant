"""
TM AI Assistant — API Endpoints v2.1
======================================
Whitelisted API methods accessible from the mobile app.

Endpoints:
  POST /api/method/tm_ai_assistant.api.chat         — Send a chat message
  GET  /api/method/tm_ai_assistant.api.chat_status   — Check if AI chat is enabled for user
  GET  /api/method/tm_ai_assistant.api.usage         — Get usage stats for current user
  GET  /api/method/tm_ai_assistant.api.alerts        — Get alert status for current user

v2.1 changes:
- Model upgraded to Opus 4.6 ($5/M input, $25/M output — 3x cheaper than 4.5)
- Adaptive thinking (Claude decides when/how much to think)

v2 changes:
- Added alerts endpoint
- Added thinking token tracking
"""

import json
import frappe
from frappe import _
from datetime import datetime


# ─── Helpers ─────────────────────────────────────────────────────────────────

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


DAILY_LIMIT = 50  # Queries per user per day


# ─── Chat Endpoint ──────────────────────────────────────────────────────────

@frappe.whitelist()
def chat(message, session_id=None, conversation_history=None):
    """
    Main chat endpoint. Receives a user message and returns an AI response.

    Args:
        message (str): The user's question
        session_id (str, optional): Existing chat session ID for conversation continuity
        conversation_history (str, optional): JSON-encoded previous messages

    Returns:
        dict: {response, session_id, usage, daily_queries_remaining}
    """
    user = frappe.session.user

    # 1. Check AI access
    if not _check_ai_access(user):
        frappe.throw(_("AI Chat is not enabled for your account. Contact your administrator."), frappe.PermissionError)

    # 2. Check rate limit
    daily_count = _get_daily_usage(user)
    if daily_count >= DAILY_LIMIT:
        frappe.throw(_(f"Daily query limit ({DAILY_LIMIT}) reached. Limit resets tomorrow."), frappe.ValidationError)

    # 3. Parse conversation history
    history = None
    if conversation_history:
        try:
            history = json.loads(conversation_history) if isinstance(conversation_history, str) else conversation_history
        except json.JSONDecodeError:
            history = None

    # 4. Process through AI engine
    from .ai_engine import process_chat

    result = process_chat(
        user=user,
        question=message,
        conversation_history=history,
    )

    # 5. Create/update session
    if not session_id:
        session_id = frappe.generate_hash(length=16)

    # 6. Log usage
    try:
        model = result.get("model", "claude-opus-4-6")
        usage_log = frappe.get_doc({
            "doctype": "AI Usage Log",
            "user": user,
            "session_id": session_id,
            "question": message[:500],  # Truncate for storage
            "input_tokens": result["usage"]["input_tokens"],
            "output_tokens": result["usage"]["output_tokens"],
            "total_tokens": result["usage"]["total_tokens"],
            "tool_calls": result.get("tool_calls", 0),
            "model": model,
        })
        usage_log.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="AI Usage Log Error", message=str(e))

    # 7. Return response
    return {
        "response": result["response"],
        "session_id": session_id,
        "usage": result["usage"],
        "tool_calls": result.get("tool_calls", 0),
        "daily_queries_remaining": max(0, DAILY_LIMIT - daily_count - 1),
    }


# ─── Status Endpoint ────────────────────────────────────────────────────────

@frappe.whitelist()
def chat_status():
    """Check if AI chat is enabled for the current user and return config."""
    user = frappe.session.user

    enabled = _check_ai_access(user)
    daily_count = _get_daily_usage(user) if enabled else 0

    return {
        "enabled": enabled,
        "daily_limit": DAILY_LIMIT,
        "daily_used": daily_count,
        "daily_remaining": max(0, DAILY_LIMIT - daily_count) if enabled else 0,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
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
