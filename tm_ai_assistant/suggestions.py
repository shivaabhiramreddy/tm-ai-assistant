"""
TM AI Assistant — Dynamic Contextual Suggestions (Sprint 6B)
==============================================================
Generates 3-4 context-aware suggestion chips for the chat UI.
No LLM calls — pure Python logic based on time, day, month, and recent activity.

The mobile app calls get_suggestions() on chat open and after each response.
Returns tappable chip labels that the user can tap to auto-fill a question.
"""

import frappe
from datetime import datetime


# ─── Suggestion Templates by Context ────────────────────────────────────────

# Time-of-day suggestions (IST)
_MORNING_SUGGESTIONS = [
    "Good morning! Give me today's business pulse",
    "What's my outstanding receivables?",
    "Any pending approvals for me?",
    "Show yesterday's sales summary",
]

_AFTERNOON_SUGGESTIONS = [
    "How are today's sales looking?",
    "Show me pending dispatch orders",
    "What's the inventory status at main warehouse?",
    "Compare this week vs last week sales",
]

_EVENING_SUGGESTIONS = [
    "Summarize today's business performance",
    "Show me today's collections",
    "Any low stock items I should worry about?",
    "What's our DSO this month?",
]

# Day-of-week suggestions
_MONDAY_SUGGESTIONS = [
    "Weekly business briefing please",
    "What happened over the weekend?",
    "Show me this week's pending targets",
]

_FRIDAY_SUGGESTIONS = [
    "Give me the weekly sales report",
    "How did we do this week vs last week?",
    "Outstanding payments due this week",
]

# Month-phase suggestions (beginning, mid, end)
_MONTH_START_SUGGESTIONS = [
    "Show me last month's P&L summary",
    "What's our monthly target progress?",
    "Receivables aging report",
]

_MONTH_END_SUGGESTIONS = [
    "Month-end closing status",
    "Revenue vs target for this month",
    "Top 10 customers by this month's revenue",
    "Outstanding payables due this month",
]

# Role-specific suggestions
_SALES_SUGGESTIONS = [
    "Top 5 customers by revenue this month",
    "Show me pending sales orders",
    "Which territory is performing best?",
    "Sales trend last 6 months",
]

_FINANCE_SUGGESTIONS = [
    "Cash flow summary this month",
    "Show me aging receivables over 90 days",
    "Bank balance across all accounts",
    "Revenue vs expenses trend",
]

_PURCHASE_SUGGESTIONS = [
    "Pending purchase orders",
    "Top suppliers by spend this month",
    "Show me GRN pending items",
    "Purchase cost trend last 3 months",
]

_INVENTORY_SUGGESTIONS = [
    "Low stock alert — items below reorder",
    "Show me stock value by warehouse",
    "Bunker occupancy status",
    "Top moving items this month",
]

_EXECUTIVE_SUGGESTIONS = [
    "Give me the complete business dashboard",
    "Compare this month vs same month last year",
    "Working capital analysis",
    "Customer acquisition trend",
    "Show me profitability by product",
]

# After specific query types (contextual follow-ups)
_FOLLOWUP_SUGGESTIONS = {
    "sales": [
        "Break this down by territory",
        "Show me the trend over last 6 months",
        "Who are the top 10 customers?",
        "Export this as PDF",
    ],
    "purchase": [
        "Show supplier-wise breakdown",
        "Compare with last month",
        "Any pending GRNs?",
        "Export this as Excel",
    ],
    "inventory": [
        "Show warehouse-wise stock",
        "What's the stock turnover ratio?",
        "Any slow-moving items?",
        "Bunker-wise breakdown",
    ],
    "finance": [
        "Show me the aging breakdown",
        "Compare with same period last year",
        "What's the collection efficiency?",
        "Export as PDF for review",
    ],
    "general": [
        "Tell me more about this",
        "Show me the trend",
        "Export this as PDF",
        "Compare with last month",
    ],
}


# ─── Main Suggestion Generator ──────────────────────────────────────────────

def get_suggestions(user, last_query=None, last_response=None, screen_context=None):
    """
    Generate 3-4 contextual suggestion chips.

    Args:
        user: ERPNext user ID
        last_query: The user's last message (for follow-up suggestions)
        last_response: The assistant's last response (for follow-up context)
        screen_context: Which app screen is active (e.g., "sales", "inventory")

    Returns:
        list of dicts: [{"label": "...", "query": "..."}]
    """
    suggestions = []

    # If there's a last query, prioritize follow-up suggestions
    if last_query and last_response:
        followups = _get_followup_suggestions(last_query, last_response)
        suggestions.extend(followups[:2])  # Max 2 follow-ups

    # Add time-based suggestions
    time_suggestions = _get_time_suggestions()
    suggestions.extend(time_suggestions)

    # Add role-based suggestions
    role_suggestions = _get_role_suggestions(user)
    suggestions.extend(role_suggestions)

    # Add screen-context suggestions
    if screen_context:
        screen_suggestions = _get_screen_suggestions(screen_context)
        suggestions.extend(screen_suggestions)

    # Deduplicate by label and limit to 4
    seen = set()
    unique = []
    for s in suggestions:
        if s["label"] not in seen:
            seen.add(s["label"])
            unique.append(s)
        if len(unique) >= 4:
            break

    return unique


def _get_time_suggestions():
    """Get suggestions based on time of day and day of week (IST)."""
    now = frappe.utils.now_datetime()
    hour = now.hour
    day = now.weekday()  # 0=Monday
    day_of_month = now.day

    suggestions = []

    # Time of day
    if hour < 12:
        pool = _MORNING_SUGGESTIONS
    elif hour < 17:
        pool = _AFTERNOON_SUGGESTIONS
    else:
        pool = _EVENING_SUGGESTIONS

    # Pick 1-2 time-based suggestions
    import random
    random.seed(now.strftime("%Y%m%d%H"))  # Same suggestions within the hour
    suggestions.extend([{"label": s, "query": s} for s in random.sample(pool, min(2, len(pool)))])

    # Day of week specials
    if day == 0:  # Monday
        s = random.choice(_MONDAY_SUGGESTIONS)
        suggestions.insert(0, {"label": s, "query": s})
    elif day == 4:  # Friday
        s = random.choice(_FRIDAY_SUGGESTIONS)
        suggestions.insert(0, {"label": s, "query": s})

    # Month phase
    if day_of_month <= 5:
        s = random.choice(_MONTH_START_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})
    elif day_of_month >= 25:
        s = random.choice(_MONTH_END_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    return suggestions


def _get_role_suggestions(user):
    """Get suggestions based on user's ERPNext roles."""
    try:
        roles = set(frappe.get_roles(user))
    except Exception:
        return []

    suggestions = []
    import random
    random.seed(frappe.utils.today())  # Same role suggestions per day

    # Executive / System Manager
    if roles.intersection({"System Manager", "Administrator"}):
        s = random.choice(_EXECUTIVE_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    # Sales roles
    if roles.intersection({"Sales Manager", "Sales User", "Sales Master Manager"}):
        s = random.choice(_SALES_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    # Finance roles
    if roles.intersection({"Accounts Manager", "Accounts User"}):
        s = random.choice(_FINANCE_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    # Purchase roles
    if roles.intersection({"Purchase Manager", "Purchase User"}):
        s = random.choice(_PURCHASE_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    # Inventory roles
    if roles.intersection({"Stock Manager", "Stock User"}):
        s = random.choice(_INVENTORY_SUGGESTIONS)
        suggestions.append({"label": s, "query": s})

    return suggestions


def _get_screen_suggestions(screen_context):
    """Get suggestions based on which app screen is active."""
    screen_map = {
        "dashboard": _EXECUTIVE_SUGGESTIONS,
        "sales": _SALES_SUGGESTIONS,
        "purchase": _PURCHASE_SUGGESTIONS,
        "inventory": _INVENTORY_SUGGESTIONS,
        "accounts": _FINANCE_SUGGESTIONS,
        "finance": _FINANCE_SUGGESTIONS,
    }

    pool = screen_map.get(screen_context, [])
    if not pool:
        return []

    import random
    random.seed(frappe.utils.now_datetime().strftime("%Y%m%d%H"))
    return [{"label": s, "query": s} for s in random.sample(pool, min(1, len(pool)))]


def _get_followup_suggestions(last_query, last_response):
    """Get follow-up suggestions based on the last query/response."""
    q_lower = last_query.lower() if last_query else ""
    r_lower = (last_response[:300] if last_response else "").lower()

    # Detect the topic category
    category = "general"
    if any(kw in q_lower or kw in r_lower for kw in ["sales", "revenue", "invoice", "customer", "order"]):
        category = "sales"
    elif any(kw in q_lower or kw in r_lower for kw in ["purchase", "supplier", "vendor", "procurement"]):
        category = "purchase"
    elif any(kw in q_lower or kw in r_lower for kw in ["stock", "inventory", "warehouse", "bunker", "item"]):
        category = "inventory"
    elif any(kw in q_lower or kw in r_lower for kw in ["payment", "receivable", "payable", "cash", "bank", "dso", "collection"]):
        category = "finance"

    pool = _FOLLOWUP_SUGGESTIONS.get(category, _FOLLOWUP_SUGGESTIONS["general"])

    import random
    random.seed(last_query[:20] if last_query else "x")  # Deterministic per query
    selected = random.sample(pool, min(2, len(pool)))
    return [{"label": s, "query": s} for s in selected]
