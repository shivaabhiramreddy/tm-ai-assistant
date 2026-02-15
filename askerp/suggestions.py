"""
AskERP — Dynamic Contextual Suggestions v2.0 (Configurable)
=====================================================================
Generates 3-4 context-aware suggestion chips for the chat UI.
No LLM calls — pure Python logic based on time, day, month, roles, and business profile.

v2.0 Changes (Phase 2 — Commercialization):
- All company-specific suggestions removed
- Suggestions now generated dynamically from AskERP Business Profile
- Industry-aware: manufacturing gets production suggestions, trading gets margin suggestions
- Terminology-aware: uses company's own terms in suggestion text
- Metric-aware: reads key_metrics_sales, accounting_focus from profile
- Universal time/day/role/follow-up logic preserved

The chat widget calls get_suggestions() on open and after each response.
Returns tappable chip labels that the user can tap to auto-fill a question.
"""

import frappe
import random
import json
from askerp.formatting import get_role_sets


# ─── Universal Suggestion Templates (industry-agnostic) ─────────────────────

# Time-of-day templates
_MORNING_TEMPLATES = [
    "Good morning! Give me today's business pulse",
    "What's my outstanding receivables?",
    "Any pending approvals for me?",
    "Show yesterday's sales summary",
]

_AFTERNOON_TEMPLATES = [
    "How are today's sales looking?",
    "Show me pending orders",
    "What's the inventory status?",
    "Compare this week vs last week sales",
]

_EVENING_TEMPLATES = [
    "Summarize today's business performance",
    "Show me today's collections",
    "Any low stock items I should worry about?",
    "What's our collection rate this month?",
]

# Day-of-week templates
_MONDAY_TEMPLATES = [
    "Weekly business briefing please",
    "What happened over the weekend?",
    "Show me this week's pending targets",
]

_FRIDAY_TEMPLATES = [
    "Give me the weekly sales report",
    "How did we do this week vs last week?",
    "Outstanding payments due this week",
]

# Month-phase templates
_MONTH_START_TEMPLATES = [
    "Show me last month's P&L summary",
    "What's our monthly target progress?",
    "Receivables aging report",
]

_MONTH_END_TEMPLATES = [
    "Month-end closing status",
    "Revenue vs target for this month",
    "Top 10 customers by this month's revenue",
    "Outstanding payables due this month",
]

# Role-based templates (universal for any business)
_SALES_TEMPLATES = [
    "Top 5 customers by revenue this month",
    "Show me pending sales orders",
    "Which territory is performing best?",
    "Sales trend last 6 months",
]

_FINANCE_TEMPLATES = [
    "Cash flow summary this month",
    "Show me aging receivables over 90 days",
    "Bank balance across all accounts",
    "Revenue vs expenses trend",
]

_PURCHASE_TEMPLATES = [
    "Pending purchase orders",
    "Top suppliers by spend this month",
    "Show me pending receipts",
    "Purchase cost trend last 3 months",
]

_INVENTORY_TEMPLATES = [
    "Low stock alert — items below reorder",
    "Show me stock value by warehouse",
    "Top moving items this month",
    "Stock turnover analysis",
]

_EXECUTIVE_TEMPLATES = [
    "Give me the complete business dashboard",
    "Compare this month vs same month last year",
    "Working capital analysis",
    "Customer acquisition trend",
    "Show me profitability by product",
]

# Follow-up templates by topic
_FOLLOWUP_TEMPLATES = {
    "sales": [
        "Break this down by territory",
        "Show me the trend over last 6 months",
        "Who are the top 10 customers?",
        "Export this as PDF",
    ],
    "purchase": [
        "Show supplier-wise breakdown",
        "Compare with last month",
        "Any pending receipts?",
        "Export this as Excel",
    ],
    "inventory": [
        "Show warehouse-wise stock",
        "What's the stock turnover ratio?",
        "Any slow-moving items?",
        "Export this data",
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


# ─── Profile-Aware Suggestion Builders ───────────────────────────────────────

def _get_business_profile():
    """
    Fetch the AskERP Business Profile. Returns a dict.
    Uses the same cache key as business_context.py for consistency.
    """
    cache_key = "askerp_business_profile"

    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        profile_doc = frappe.get_single("AskERP Business Profile")
        profile_data = profile_doc.as_dict()
        frappe.cache().set_value(cache_key, profile_data, expires_in_sec=300)
        return profile_data
    except Exception:
        return {}


def _build_industry_suggestions(profile):
    """
    Build industry-specific suggestions from the business profile.
    A manufacturing company gets production suggestions.
    A trading company gets margin/supply chain suggestions.
    A services company gets project/billing suggestions.
    """
    suggestions = []
    industry = (profile.get("industry") or "").lower()
    has_manufacturing = profile.get("has_manufacturing", 0)

    # Manufacturing-specific
    if has_manufacturing or "manufactur" in industry:
        suggestions.extend([
            "What's our production output this month?",
            "Show me work order completion rate",
            "Raw material stock levels",
            "Production vs capacity utilization",
        ])

    # Trading-specific
    if "trading" in industry or "retail" in industry:
        suggestions.extend([
            "Show me product-wise margins",
            "Best selling items this month",
            "Slow-moving inventory report",
            "Purchase price trends",
        ])

    # Services-specific
    if "service" in industry or "consulting" in industry:
        suggestions.extend([
            "Show me project-wise revenue",
            "Outstanding invoices by project",
            "Resource utilization this month",
            "Pending timesheet billing",
        ])

    # Agriculture-specific
    if "agri" in industry or "farm" in industry:
        suggestions.extend([
            "Seasonal inventory status",
            "Procurement vs budget",
            "Warehouse capacity status",
            "Product-wise volume report",
        ])

    # Healthcare / Pharma
    if "health" in industry or "pharma" in industry:
        suggestions.extend([
            "Batch-wise inventory status",
            "Near-expiry stock report",
            "Product-wise sales volume",
            "Quality inspection pass rate",
        ])

    return suggestions


def _build_metric_suggestions(profile):
    """
    Build suggestions from the key metrics the user cares about.
    Reads key_metrics_sales, accounting_focus, executive_focus from profile.
    """
    suggestions = []

    # Parse key_metrics_sales (comma or newline separated)
    metrics_text = profile.get("key_metrics_sales", "")
    if metrics_text:
        metrics = [m.strip().lstrip("- ") for m in metrics_text.replace("\n", ",").split(",") if m.strip()]
        for metric in metrics[:3]:
            if len(metric) > 3 and len(metric) < 60:
                suggestions.append(f"Show me {metric.lower()}")

    # Parse accounting_focus (newline separated questions/topics)
    focus_text = profile.get("accounting_focus", "")
    if focus_text:
        lines = [l.strip().lstrip("- ") for l in focus_text.split("\n") if l.strip()]
        for line in lines[:2]:
            if len(line) > 5 and len(line) < 80:
                suggestions.append(line)

    return suggestions


def _build_terminology_suggestions(profile):
    """
    Build suggestions using company-specific terminology.
    E.g., if a company has custom warehouse types, show related suggestions.
    """
    suggestions = []
    terms_text = profile.get("custom_terminology", "")

    if not terms_text or terms_text.strip() in ("{}", ""):
        return suggestions

    # Try to parse as JSON first (new format)
    try:
        terms = json.loads(terms_text)
        if isinstance(terms, dict):
            for term in list(terms.keys())[:3]:
                if len(term) > 1 and len(term) < 30:
                    suggestions.append(f"Show me {term} status")
            return suggestions
    except (json.JSONDecodeError, TypeError):
        pass

    # Parse as "term = meaning" lines (legacy format)
    lines = [l.strip() for l in terms_text.split("\n") if "=" in l]
    for line in lines[:3]:
        term = line.split("=")[0].strip().lstrip("- ").strip()
        if term and len(term) > 1 and len(term) < 30:
            suggestions.append(f"Show me {term} status")

    return suggestions


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

    # Load business profile (cached, fast)
    profile = _get_business_profile()

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

    # Add industry-specific suggestions from profile
    if profile:
        industry_suggestions = _build_industry_suggestions(profile)
        if industry_suggestions:
            random.seed(frappe.utils.today())
            selected = random.sample(industry_suggestions, min(1, len(industry_suggestions)))
            suggestions.extend([{"label": s, "query": s} for s in selected])

        # Add metric-based suggestions (from what the user told us matters)
        metric_suggestions = _build_metric_suggestions(profile)
        if metric_suggestions:
            random.seed(frappe.utils.now_datetime().strftime("%Y%m%d%H"))
            selected = random.sample(metric_suggestions, min(1, len(metric_suggestions)))
            suggestions.extend([{"label": s, "query": s} for s in selected])

    # Add screen-context suggestions
    if screen_context:
        screen_suggestions = _get_screen_suggestions(screen_context)
        suggestions.extend(screen_suggestions)

    # Deduplicate by label and limit to 4
    seen = set()
    unique = []
    for s in suggestions:
        label = s.get("label", "")
        if label and label not in seen:
            seen.add(label)
            unique.append(s)
        if len(unique) >= 4:
            break

    return unique


def _get_time_suggestions():
    """Get suggestions based on time of day and day of week."""
    now = frappe.utils.now_datetime()
    hour = now.hour
    day = now.weekday()  # 0=Monday
    day_of_month = now.day

    suggestions = []

    # Time of day
    if hour < 12:
        pool = _MORNING_TEMPLATES
    elif hour < 17:
        pool = _AFTERNOON_TEMPLATES
    else:
        pool = _EVENING_TEMPLATES

    # Pick 1-2 time-based suggestions
    random.seed(now.strftime("%Y%m%d%H"))  # Same suggestions within the hour
    suggestions.extend([{"label": s, "query": s} for s in random.sample(pool, min(2, len(pool)))])

    # Day of week specials
    if day == 0:  # Monday
        s = random.choice(_MONDAY_TEMPLATES)
        suggestions.insert(0, {"label": s, "query": s})
    elif day == 4:  # Friday
        s = random.choice(_FRIDAY_TEMPLATES)
        suggestions.insert(0, {"label": s, "query": s})

    # Month phase
    if day_of_month <= 5:
        s = random.choice(_MONTH_START_TEMPLATES)
        suggestions.append({"label": s, "query": s})
    elif day_of_month >= 25:
        s = random.choice(_MONTH_END_TEMPLATES)
        suggestions.append({"label": s, "query": s})

    return suggestions


def _get_role_suggestions(user):
    """Get suggestions based on user's ERPNext roles."""
    try:
        roles = set(frappe.get_roles(user))
    except Exception:
        return []

    suggestions = []
    random.seed(frappe.utils.today())  # Same role suggestions per day

    # Get dynamic role sets from AskERP Settings
    role_sets = get_role_sets()
    exec_roles = role_sets["executive"]
    mgmt_roles = role_sets["management"]

    # Executive / System Manager (from Settings)
    if roles.intersection(exec_roles):
        s = random.choice(_EXECUTIVE_TEMPLATES)
        suggestions.append({"label": s, "query": s})

    # Sales roles (always includes standard ERPNext sales roles)
    if roles.intersection({"Sales Manager", "Sales User", "Sales Master Manager"} | mgmt_roles):
        if roles.intersection({"Sales Manager", "Sales User", "Sales Master Manager"}):
            s = random.choice(_SALES_TEMPLATES)
            suggestions.append({"label": s, "query": s})

    # Finance roles (always includes standard ERPNext accounts roles)
    if roles.intersection({"Accounts Manager", "Accounts User"}):
        s = random.choice(_FINANCE_TEMPLATES)
        suggestions.append({"label": s, "query": s})

    # Purchase roles
    if roles.intersection({"Purchase Manager", "Purchase User"}):
        s = random.choice(_PURCHASE_TEMPLATES)
        suggestions.append({"label": s, "query": s})

    # Inventory roles
    if roles.intersection({"Stock Manager", "Stock User"}):
        s = random.choice(_INVENTORY_TEMPLATES)
        suggestions.append({"label": s, "query": s})

    return suggestions


def _get_screen_suggestions(screen_context):
    """Get suggestions based on which app screen is active."""
    screen_map = {
        "dashboard": _EXECUTIVE_TEMPLATES,
        "sales": _SALES_TEMPLATES,
        "purchase": _PURCHASE_TEMPLATES,
        "inventory": _INVENTORY_TEMPLATES,
        "accounts": _FINANCE_TEMPLATES,
        "finance": _FINANCE_TEMPLATES,
    }

    pool = screen_map.get(screen_context, [])
    if not pool:
        return []

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
    elif any(kw in q_lower or kw in r_lower for kw in ["stock", "inventory", "warehouse", "item"]):
        category = "inventory"
    elif any(kw in q_lower or kw in r_lower for kw in ["payment", "receivable", "payable", "cash", "bank", "collection"]):
        category = "finance"

    pool = _FOLLOWUP_TEMPLATES.get(category, _FOLLOWUP_TEMPLATES["general"])

    random.seed(last_query[:20] if last_query else "x")  # Deterministic per query
    selected = random.sample(pool, min(2, len(pool)))
    return [{"label": s, "query": s} for s in selected]
