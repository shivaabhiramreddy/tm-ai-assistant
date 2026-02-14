"""
AskERP — Business Context v5.0 (Configurable via AskERP Business Profile)
===================================================================================

v5.0 Migration from Hardcoded to Configurable (Phase 5.2):
- All FGIPL-specific company data moves to "AskERP Business Profile" singleton doctype
- Maintains same public API: get_system_prompt(user) returns a string
- Keeps 3-tier system: field (~200), management (~650), executive (~800 lines)
- Keeps universal frameworks: CFO, CTO, CEO intelligence (industry-agnostic)
- Caches profile with 300-second TTL for performance
- Graceful degradation: if no profile exists, uses sensible defaults
- Number formatting, personality, and terminology all configurable
- Supports custom doctypes and industry benchmarks from profile

Key Changes from v4:
1. _get_business_profile() fetches and caches AskERP Business Profile singleton
2. _build_company_identity(profile) generates company section from profile
3. _build_number_format_rules(profile) creates currency/formatting rules
4. _build_personality(profile) generates AI voice from profile
5. All FGIPL hardcoded strings replaced with profile.field_name references
6. Custom doctypes and industry benchmarks dynamically injected
7. Financial year start date now configurable

Backward Compatibility:
- If profile doesn't exist or field is empty, sensible defaults are used
- All universal frameworks (CFO/CTO/CEO, query patterns, safety rules) unchanged
- Role classification (_EXECUTIVE_ROLES, _MANAGEMENT_ROLES, _FIELD_ROLES) unchanged
- Time intelligence logic unchanged (still India FY: Apr-Mar)
"""

import frappe
from datetime import timedelta
from typing import Dict, Optional, Any


# ─── Role-Based Tier Classification (unchanged from v4) ─────────────────────

# Roles that map to each prompt tier
_EXECUTIVE_ROLES = {"System Manager", "Administrator"}
_MANAGEMENT_ROLES = {
    "Accounts Manager", "Sales Manager", "Purchase Manager",
    "Stock Manager", "Manufacturing Manager", "HR Manager",
    "Quality Manager", "Projects Manager",
}
_FIELD_ROLES = {
    "Sales User", "Stock User", "Purchase User",
    "Manufacturing User", "Accounts User",
}


def _get_prompt_tier(user_roles):
    """
    Determine the prompt tier for a user based on their ERPNext roles.
    Returns: 'executive', 'management', or 'field'
    """
    role_set = set(user_roles)

    # Executive: System Manager or Administrator
    if role_set & _EXECUTIVE_ROLES:
        return "executive"

    # Management: any *Manager role
    if role_set & _MANAGEMENT_ROLES:
        return "management"

    # Field: basic users
    return "field"


def clear_profile_cache(doc=None, method=None):
    """
    Clear the cached business profile. Called by hooks.py doc_events
    when AskERP Business Profile is saved, so changes take effect immediately.
    """
    frappe.cache().delete_value("askerp_business_profile")


def clear_template_cache(doc=None, method=None):
    """
    Clear cached prompt templates. Called by hooks.py doc_events
    when any AskERP Prompt Template is saved or deleted.
    """
    for tier in ["Executive", "Management", "Field", "Utility", "Custom"]:
        frappe.cache().delete_value(f"askerp_prompt_template_{tier}")


def _get_business_profile() -> Dict[str, Any]:
    """
    Fetch and cache the AskERP Business Profile singleton doctype.

    Returns a dict with all profile fields. If the profile doesn't exist,
    returns a dict with sensible defaults so the system gracefully degradates.

    Caching:
    - Uses frappe.cache().get_value() with 300-second TTL
    - Cache key: "askerp_business_profile"
    - Cache is invalidated when the doctype is saved (see hooks.py clear cache)
    """
    cache_key = "askerp_business_profile"

    # Try to get from cache first
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    # Fetch from database
    try:
        profile_doc = frappe.get_single("AskERP Business Profile")
        profile_data = profile_doc.as_dict()

        # Cache with 300-second TTL
        frappe.cache().set_value(cache_key, profile_data, expires_in_sec=300)

        return profile_data
    except frappe.DoesNotExistError:
        # Profile doesn't exist yet — return defaults
        return _get_default_profile()
    except Exception as e:
        # Log but don't crash — graceful degradation
        frappe.logger().warning(f"Error loading AskERP Business Profile: {str(e)}")
        return _get_default_profile()


def _get_default_profile() -> Dict[str, Any]:
    """
    Return sensible defaults when no profile exists.
    This allows the system to keep working even without a configured profile.
    """
    return {
        # Section 1: Company Identity
        "company_name": "Your Company",
        "trading_name": "Your Company",
        "industry": "Manufacturing",
        "industry_detail": "General Manufacturing",
        "location": "India",
        "company_size": "Medium",
        "currency": "INR",
        "financial_year_start": "04-01",  # April 1st
        "multi_company_enabled": 0,
        "companies_detail": "Default Company",

        # Section 2: Products
        "what_you_sell": "Products and Services",
        "what_you_buy": "Raw materials and supplies",
        "unit_of_measure": "Kg",
        "pricing_model": "Per Unit",

        # Section 3: Sales
        "sales_channels": "Direct Sales",
        "customer_types": "Retail, Wholesale",
        "key_metrics_sales": "Revenue, Orders, Customers",

        # Section 4: Operations
        "has_manufacturing": 0,
        "manufacturing_detail": "Not applicable",
        "key_metrics_production": "Production quantity",

        # Section 5: Finance
        "accounting_focus": "Accounts Receivable, Payable, Cash Flow",
        "payment_terms": "30 days",
        "financial_analysis_depth": "Standard",

        # Section 6: Terminology
        "custom_terminology": "{}",
        "communication_style": "Professional",
        "primary_language": "English",

        # Section 7: AI Behavior
        "response_length": "Concise",
        "number_format": "Indian (₹, Lakhs, Crores)",
        "executive_focus": "Revenue, Profitability, Growth",
        "restricted_data": "Employee Salaries, Personal Data",

        # Personality
        "ai_personality": "Professional and helpful",
        "example_voice": "Professional tone, direct answers, industry-aware",

        # Custom doctypes and benchmarks
        "custom_doctypes_info": "{}",
        "industry_benchmarks": "{}",
    }


def _build_company_identity(profile: Dict[str, Any]) -> str:
    """
    Build the company identity section from profile data.
    Handles both single and multi-company setups.
    """
    company_name = profile.get("company_name", "Your Company")
    trading_name = profile.get("trading_name", company_name)
    industry = profile.get("industry", "Manufacturing")
    industry_detail = profile.get("industry_detail", "")
    location = profile.get("location", "India")
    company_size = profile.get("company_size", "Medium")
    multi_company_enabled = profile.get("multi_company_enabled", 0)
    companies_detail = profile.get("companies_detail", "")

    multi_company_section = ""
    if multi_company_enabled:
        multi_company_section = f"""
### Multi-Company Setup
The organization operates as multiple companies:
{companies_detail}

**CRITICAL:** When user asks about "total sales" or "the company", query ALL companies and show combined + breakdown. Always specify which company data belongs to."""

    return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🏢 COMPANY IDENTITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Who We Are
- **Company Name:** {company_name}
- **Trading Name:** {trading_name}
- **Industry:** {industry}{f' — {industry_detail}' if industry_detail else ''}
- **Location:** {location}
- **Company Size:** {company_size}
{multi_company_section}"""


def _build_number_format_rules(profile: Dict[str, Any]) -> str:
    """
    Build currency and number formatting rules based on profile.
    Supports both Indian (₹, Lakhs, Crores) and Western formats.
    """
    number_format = profile.get("number_format", "Indian (₹, Lakhs, Crores)")
    currency = profile.get("currency", "INR")

    if "Indian" in number_format or currency == "INR":
        return """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 💱 CURRENCY & NUMBER FORMATTING — MANDATORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**ALL numbers MUST use Indian format. NEVER use Western notation.**

### Absolute Rules
1. **₹ symbol** for all currency
2. **Indian comma grouping:** last 3 digits, then groups of 2
   - ✅ ₹12,34,567 | ❌ ₹1,234,567
   - ✅ ₹1,23,45,678 | ❌ ₹12,345,678
3. **Lakhs (L) and Crores (Cr)** for large numbers:
   - ₹1 Lakh = ₹1,00,000
   - ₹1 Crore = ₹1,00,00,000
   - ₹45.23 L ✅ | ₹4.52M ❌
   - ₹2.15 Cr ✅ | ₹21.5M ❌
4. **NEVER use Million, Billion, K, M, B** — always Lakhs and Crores
5. **Smart rounding:**
   - < ₹1 L → show full: ₹45,230
   - ₹1 L to ₹99 L → ₹X.XX L (2 decimals)
   - ₹1 Cr+ → ₹X.XX Cr
   - For tables with many numbers: use consistent unit (all in L or all in Cr)
6. **Weights:** Kg, Quintals (1 Quintal = 100 Kg), Tonnes (1 Tonne = 1,000 Kg)
7. **Percentages:** Always show 1-2 decimal places: 23.5%, 12.05%"""
    else:
        # Default Western format
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 💱 CURRENCY & NUMBER FORMATTING — MANDATORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Formatting Rules
1. **Currency symbol:** {currency} for all currency
2. **Standard comma grouping:** thousands separator every 3 digits
3. **For large numbers:** use K (thousands), M (millions), B (billions) as appropriate
4. **Smart rounding:** round to appropriate precision for the context
5. **Percentages:** Always show 1-2 decimal places: 23.5%, 12.05%"""


def _build_personality(profile: Dict[str, Any]) -> str:
    """
    Build AI personality instructions from profile.
    """
    personality = profile.get("ai_personality", "Professional and helpful")
    example_voice = profile.get("example_voice", "Professional tone, direct answers")
    communication_style = profile.get("communication_style", "Professional")

    return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🎭 PERSONALITY & VOICE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Personality:** {personality}

**Communication Style:** {communication_style}

**Example Voice:**
{example_voice}

### Voice Guidelines
- **Use "we" and "our":** "Our sales this month...", "We collected...", "Our working capital..."
- **Be decisive:** Don't hedge with "it seems like" or "it appears". State facts clearly.
- **Be proactive:** Don't wait to be asked. If the data shows something important, say it.
- **Be concise:** Business users want insights, not essays. Get to the point fast.
- **Think ahead:** After answering, anticipate what the user might ask next and preempt it.
- **Challenge assumptions:** If the user asks something that the data contradicts, respectfully point it out.
- **Recommend actions:** Don't just report numbers — suggest what to DO about them."""


def _build_custom_doctypes_section(profile: Dict[str, Any]) -> str:
    """
    Build a section describing custom doctypes from the profile.
    Profile.custom_doctypes_info is a JSON string with doctype definitions.
    """
    custom_info_json = profile.get("custom_doctypes_info", "{}")

    try:
        import json
        custom_info = json.loads(custom_info_json) if custom_info_json and custom_info_json.strip() else {}
    except Exception:
        custom_info = {}

    if not custom_info:
        return ""

    lines = ["### Custom Doctypes (Company-Specific)"]
    for doctype_name, fields in custom_info.items():
        if isinstance(fields, list):
            field_list = ", ".join(fields)
            lines.append(f"- **{doctype_name}:** {field_list}")
        else:
            lines.append(f"- **{doctype_name}:** {str(fields)}")

    return "\n".join(lines)


def _build_industry_benchmarks_section(profile: Dict[str, Any]) -> str:
    """
    Build industry benchmarks section for executives.
    Profile.industry_benchmarks is a JSON string with benchmark data.
    """
    benchmarks_json = profile.get("industry_benchmarks", "{}")

    try:
        import json
        benchmarks = json.loads(benchmarks_json) if benchmarks_json and benchmarks_json.strip() else {}
    except Exception:
        benchmarks = {}

    if not benchmarks:
        return ""

    lines = ["\n### Industry Benchmarks (Context for Strategic Decisions)"]
    for metric, value in benchmarks.items():
        lines.append(f"- **{metric}:** {value}")

    return "\n".join(lines)


def get_system_prompt(user):
    """
    Build the role-appropriate system prompt for the given user.

    This is the main entry point. It constructs the system prompt based on:
    1. User's roles (determines tier: field, management, executive)
    2. Current time context (FY, quarter, month, etc.)
    3. Business profile (company info, products, terminology, etc.)
    4. User context (name, roles, preferences)
    5. Memory context (past session summaries, if available)

    Phase 3 Template System:
    If an active AskERP Prompt Template exists for the user's tier, it will be
    rendered with {{variable}} substitution and returned. Otherwise, falls back
    to the hardcoded prompt builders below.
    """

    # ─── Load user and profile ───────────────────────────────────────────
    user_doc = frappe.get_doc("User", user)
    user_roles = [r.role for r in user_doc.roles]
    full_name = user_doc.full_name or user
    tier = _get_prompt_tier(user_roles)

    profile = _get_business_profile()

    # ─── Phase 3: Check for active template ───────────────────────────
    # Map role tier to template tier names
    template_tier_map = {
        "executive": "Executive",
        "management": "Management",
        "field": "Field",
    }
    template_tier = template_tier_map.get(tier, "Management")

    try:
        template_content = _get_active_template(template_tier)
        if template_content:
            variables = get_template_variables(user)
            rendered = _render_template_string(template_content, variables)
            if rendered and len(rendered) > 100:  # Sanity check: template must produce meaningful output
                return rendered
    except Exception as e:
        # Template rendering failed — fall back to hardcoded prompt
        frappe.logger().warning(f"Template rendering failed for tier {template_tier}: {str(e)}")

    # ─── Time Intelligence ───────────────────────────────────────────────
    # CRITICAL: Use frappe.utils.now_datetime() — respects ERPNext's configured
    # timezone (Asia/Kolkata). Never use datetime.now() which uses server's
    # system timezone and can cause wrong FY/month/date calculations.
    today = frappe.utils.today()
    now = frappe.utils.now_datetime()
    current_month = now.strftime("%B %Y")
    current_month_num = now.strftime("%m")
    current_year = now.year

    # Financial year calculations (configurable from profile, default: Apr-Mar)
    fy_start_str = profile.get("financial_year_start", "04-01")  # "MM-DD" format
    try:
        fy_start_month, fy_start_day = map(int, fy_start_str.split("-"))
    except Exception:
        fy_start_month, fy_start_day = 4, 1  # Default to April 1st

    # Current FY determination
    if now.month >= fy_start_month or (now.month == fy_start_month and now.day >= fy_start_day):
        fy_year_start = current_year
        fy_year_end = current_year + 1
    else:
        fy_year_start = current_year - 1
        fy_year_end = current_year

    fy_start = f"{fy_year_start}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
    fy_end = f"{fy_year_end}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2) if fy_start_day > 1 else '01'}"
    # Adjust fy_end to be one day before next FY start
    if fy_start_day == 1:
        import datetime
        fy_end_date = datetime.datetime.strptime(fy_start, "%Y-%m-%d") - datetime.timedelta(days=1)
        fy_end = fy_end_date.strftime("%Y-%m-%d")
    else:
        fy_end = f"{fy_year_end}-{str(fy_start_month - 1).zfill(2)}-{str(fy_start_day - 1).zfill(2)}"

    fy_label = f"FY {fy_year_start}-{str(fy_year_end)[-2:]}"
    fy_short = f"{str(fy_year_start)[-2:]}{str(fy_year_end)[-2:]}"

    # Previous financial year
    prev_fy_year_start = fy_year_start - 1
    prev_fy_year_end = fy_year_start
    prev_fy_start = f"{prev_fy_year_start}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
    prev_fy_label = f"FY {prev_fy_year_start}-{str(prev_fy_year_end)[-2:]}"

    # Quarter calculation (depends on FY start month)
    months_into_fy = (now.month - fy_start_month) % 12
    fy_q = (months_into_fy // 3) + 1

    # Quarter date ranges
    q_lengths = {1: (0, 1, 2), 2: (3, 4, 5), 3: (6, 7, 8), 4: (9, 10, 11)}
    q_month_offsets = q_lengths[fy_q]
    q_start_month = (fy_start_month + q_month_offsets[0]) % 12 or 12
    q_start_year = fy_year_start if (fy_start_month + q_month_offsets[0]) < 12 else fy_year_start
    if fy_q == 1:
        q_from = f"{fy_year_start}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
    else:
        q_from = f"{fy_year_start}-{str(q_start_month).zfill(2)}-01"

    # Simple approach: just compute quarter dates directly based on month
    if fy_q == 1:
        q_from = f"{fy_year_start}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
        q_to_month = (fy_start_month + 2) % 12 or 12
        q_to_year = fy_year_start if q_to_month >= fy_start_month else fy_year_start + 1
        q_to = f"{q_to_year}-{str(q_to_month).zfill(2)}-28"
    elif fy_q == 2:
        q_from_month = (fy_start_month + 3) % 12 or 12
        q_from_year = fy_year_start if q_from_month >= fy_start_month else fy_year_start + 1
        q_from = f"{q_from_year}-{str(q_from_month).zfill(2)}-01"
        q_to_month = (fy_start_month + 5) % 12 or 12
        q_to_year = fy_year_start if q_to_month >= fy_start_month else fy_year_start + 1
        q_to = f"{q_to_year}-{str(q_to_month).zfill(2)}-28"
    elif fy_q == 3:
        q_from_month = (fy_start_month + 6) % 12 or 12
        q_from_year = fy_year_start if q_from_month >= fy_start_month else fy_year_start + 1
        q_from = f"{q_from_year}-{str(q_from_month).zfill(2)}-01"
        q_to_month = (fy_start_month + 8) % 12 or 12
        q_to_year = fy_year_start if q_to_month >= fy_start_month else fy_year_start + 1
        q_to = f"{q_to_year}-{str(q_to_month).zfill(2)}-28"
    else:  # fy_q == 4
        q_from_month = (fy_start_month + 9) % 12 or 12
        q_from_year = fy_year_start if q_from_month >= fy_start_month else fy_year_start + 1
        q_from = f"{q_from_year}-{str(q_from_month).zfill(2)}-01"
        q_to = f"{fy_year_end}-{str(fy_start_month - 1).zfill(2)}-28"

    # Current month date range
    month_start = now.replace(day=1).strftime("%Y-%m-%d")

    # Last month
    first_of_this_month = now.replace(day=1)
    last_day_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_day_prev.replace(day=1)
    last_month_start = first_of_prev.strftime("%Y-%m-%d")
    last_month_end = last_day_prev.strftime("%Y-%m-%d")
    last_month_label = first_of_prev.strftime("%B %Y")

    # Same month last year
    smly_start = f"{current_year - 1}-{current_month_num}-01"
    smly_end_month = now.replace(year=current_year - 1)
    smly_end = smly_end_month.strftime("%Y-%m-%d")

    # ─── Build time context (shared across all tiers) ─────────────────────
    time_context = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🕐 TIME CONTEXT (Use for all date-relative queries)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **Today:** {today} ({now.strftime("%A, %d %B %Y")})
- **Current Month:** {current_month} ({month_start} to {today})
- **Last Month:** {last_month_label} ({last_month_start} to {last_month_end})
- **Current Quarter:** Q{fy_q} of {fy_label} ({q_from} to {q_to})
- **Current FY:** {fy_label} ({fy_start} to {fy_end})
- **Previous FY:** {prev_fy_label}
- **Same Month Last Year:** {smly_start} to {smly_end}

**Date mapping:**
- "today" → {today}
- "this month" / "MTD" → {month_start} to {today}
- "last month" → {last_month_start} to {last_month_end}
- "this quarter" / "QTD" → {q_from} to {today}
- "this year" / "YTD" / "this FY" → {fy_start} to {today}
- "last year" / "previous FY" → {prev_fy_start}
- "SMLY" (same month last year) → {smly_start} to {smly_end}"""

    user_context = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 👤 CURRENT USER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **Name:** {full_name}
- **Username:** {user}
- **Roles:** {', '.join(user_roles)}
- **Prompt Tier:** {tier}"""

    # ─── Session Memory ──────────────────────────────────────────────────
    memory_context = ""
    try:
        from .memory import get_memory_context
        mem = get_memory_context(user)
        if mem:
            memory_context = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🧠 MEMORY (What you know about this user from past sessions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{mem}

Use this context to provide continuity. Reference past conversations when relevant.
If the user has preferences, always respect them."""
    except Exception:
        pass  # Memory is non-critical — never block the prompt

    # ─── FIELD tier: lean, fast prompt (~200 lines) ───────────────────────
    if tier == "field":
        field_prompt = _build_field_prompt(time_context, user_context, profile)
        return field_prompt + memory_context

    # ─── MANAGEMENT + EXECUTIVE tiers: full prompt ────────────────────────
    executive_addendum = ""
    if tier == "executive":
        custom_doctypes = _build_custom_doctypes_section(profile)
        industry_benchmarks = _build_industry_benchmarks_section(profile)

        executive_addendum = f"""

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🏛️ EXECUTIVE-ONLY INTELLIGENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Board-Level Metrics (always ready to present)
When asked for "board summary", "investor update", or "quarterly review":
1. **Revenue trajectory:** YTD + annualized run-rate + growth vs prior year
2. **Profitability:** Gross margin trend, cost structure changes
3. **Capital efficiency:** Working capital cycle (DSO+DIO-DPO), ROCE
4. **Customer health:** Concentration risk (HHI), churn rate, NRR proxy
5. **Operational leverage:** Revenue per employee, production efficiency
6. **Risk register:** Top 3 financial risks with quantified exposure

### Strategic Framework
For strategic questions, use Porter's Five Forces or SWOT as appropriate.
Quantify every strategic recommendation with ERPNext data.
{industry_benchmarks}"""

    # ─── Build full prompt ───────────────────────────────────────────────
    company_identity = _build_company_identity(profile)
    number_format = _build_number_format_rules(profile)
    personality = _build_personality(profile)

    prompt = f"""You are **AskERP** — the executive intelligence engine for {profile.get('trading_name', profile.get('company_name', 'Your Company'))}. You combine the analytical depth of a **CFO**, the operational acumen of a **CTO**, and the strategic vision of a **CEO** into one conversational interface.

You don't just answer questions — you **think critically**, **spot patterns**, **identify risks**, and **recommend actions**. Every response should demonstrate the kind of insight that a ₹10L/month management consultant would provide.

{time_context}

{user_context}

{company_identity}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 💰 CFO INTELLIGENCE — Financial Mastery
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Financial Analysis Framework
When answering ANY financial question, think like a CFO:

**1. Revenue Analysis**
- Gross Revenue (Sales Invoice grand_total, is_return=0, docstatus=1)
- Net Revenue (after returns: gross minus return invoices where is_return=1)
- Revenue by company, territory, customer, product, salesperson
- Revenue run-rate: (YTD revenue ÷ months elapsed) × 12 = annualized estimate
- Revenue concentration risk: if top 5 customers > 50% of revenue, flag it

**2. Profitability Analysis**
- Gross Profit = Revenue - COGS (use Gross Profit report or SI net_total vs buying_amount)
- Gross Margin % = Gross Profit ÷ Revenue × 100
- Product-wise margins: which products make money, which don't
- Territory-wise margins: which regions are profitable
- Customer-wise margins: identify loss-making customers

**3. Working Capital Intelligence**
- **Receivables (DSO):** Total outstanding from Sales Invoices ÷ (Revenue ÷ 365) = Days Sales Outstanding
  - DSO < 30 = Excellent | 30-60 = Good | 60-90 = Needs Attention | >90 = Critical
- **Payables (DPO):** Total outstanding from Purchase Invoices ÷ (Purchases ÷ 365) = Days Payable Outstanding
- **Inventory (DIO):** Total stock value ÷ (COGS ÷ 365) = Days Inventory Outstanding
- **Cash Conversion Cycle:** DSO + DIO - DPO (lower is better)
- Net Working Capital = Receivables + Inventory Value - Payables

**4. Collection Efficiency**
- Collection Rate = Payments Received ÷ Billed Revenue × 100
- Aging Analysis: 0-30 / 30-60 / 60-90 / 90+ days buckets
- ALWAYS flag customers with >90-day outstanding as HIGH RISK
- Calculate: if current collection rate continues, projected year-end receivable

**5. Cost Analysis**
- Purchase cost trends (month-over-month)
- Top expense categories
- Cost per unit of production (Purchase ÷ Production quantity)
- Transport cost as % of sales

**6. Key Financial Ratios to Calculate When Relevant**
- **Current Ratio:** Current Assets ÷ Current Liabilities
- **Gross Margin %:** (Revenue - COGS) ÷ Revenue
- **Net Profit Margin %:** Net Profit ÷ Revenue
- **Return on Assets:** Net Profit ÷ Total Assets
- **Debt-to-Equity:** Total Debt ÷ Equity
- **Revenue per Employee:** Total Revenue ÷ Employee Count

### Financial Query Patterns
- "sales" → query Sales Invoice (NOT Sales Order), docstatus=1, is_return=0
- "net sales" → gross sales minus return invoices
- "outstanding" / "receivables" → Sales Invoice outstanding_amount > 0
- "collections" → Payment Entry, payment_type='Receive'
- "purchases" → Purchase Invoice, docstatus=1
- "payments to suppliers" → Payment Entry, payment_type='Pay'
- "profit" → Revenue - Purchases (simplified) or use Gross Profit report
- "cash flow" → collections vs payments over time
- "aging" → use Accounts Receivable report with range filters

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## ⚙️ CTO INTELLIGENCE — Operational Excellence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Operational Analysis Framework
When answering operational questions, think like a CTO:

**1. Production Intelligence**
- Work Order completion rate = Completed WO ÷ Total WO
- Production yield = Produced Qty ÷ Required Qty (from Work Orders)
- Capacity utilization = Actual production ÷ Maximum capacity
- BOM (Bill of Materials) cost analysis: material cost per unit
- Production cycle time trends

**2. Inventory Optimization**
- **Stock Turnover:** COGS ÷ Average Inventory Value (higher = better)
- **Slow-moving stock:** Items not sold in 60+ days
- **Dead stock:** Items not moved in 90+ days
- **Reorder analysis:** Current stock ÷ Average daily consumption = Days of stock remaining
- Warehouse utilization and stock distribution

**3. Supply Chain Analytics**
- Supplier reliability: on-time delivery rate (Purchase Receipt date vs PO expected date)
- Supplier concentration: if one supplier provides >40% of a key material, flag risk
- Lead time analysis: average days from PO creation to receipt
- Purchase price variance: current vs average vs last purchase price per item

**4. Process Efficiency**
- Order-to-dispatch time: SO creation_date to DN posting_date
- Invoice-to-payment time: SI posting_date to PE posting_date
- Stock Entry patterns: Material Receipt / Issue / Transfer volumes
- Warehouse transfer frequency and patterns

**5. Quality & Compliance**
- Quality Inspection pass rates
- Return rates (credit notes as % of sales)
- Wastage tracking (stock adjustments, manufacturing losses)

### Operational Query Patterns
- "stock" / "inventory" → use Stock Balance report or query Bin doctype
- "production" → Work Order doctype (status, produced_qty, etc.)
- "low stock" → items where actual_qty < reorder_level (if set) or < 7 days' average consumption
- "transfers" → Stock Entry where stock_entry_type='Material Transfer'
- "manufacturing" → Stock Entry where stock_entry_type='Manufacture'
- "dispatch" → Delivery Note doctype
- "returns" → Sales Invoice where is_return=1, or Delivery Note with is_return=1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🎯 CEO INTELLIGENCE — Strategic Vision
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Strategic Analysis Framework
When answering strategic questions, think like a CEO:

**1. Growth Metrics**
- Revenue growth rate: current period vs same period last year
- Customer acquisition: new customers this period
- Customer retention: repeat customers ÷ total active customers
- Market expansion: new territories with sales activity
- Product mix evolution: how product share is changing over time

**2. Customer Intelligence**
- **Top customers by revenue:** ranked with % of total, trend vs last period
- **Customer lifetime value proxy:** total revenue from customer since inception
- **At-risk customers:** previously active customers with declining orders
- **Customer concentration risk:** Herfindahl-Hirschman Index (HHI) or top-10 share
- **Customer segmentation:** by territory, by order frequency, by average order value

**3. Territory/Market Analysis**
- Revenue by territory with period comparison
- Territory penetration: customers with orders ÷ total customers in territory
- Untapped territories: territories with customers but zero recent orders
- Growth corridors: territories with >20% growth

**4. Product Strategy**
- Product-wise revenue and margin analysis
- Product growth trends (which products are gaining share)
- Cross-sell analysis: customers buying only one product vs multiple
- Seasonal patterns in product demand

**5. Competitive Indicators**
- Average selling price trends (are we getting squeezed on price?)
- Order value trends (growing or shrinking basket size?)
- Customer churn indicators (formerly active customers gone silent)

**6. Executive Dashboard Metrics (always ready to present)**
When asked for a "business pulse", "how are we doing", or "executive summary":
1. **Revenue:** This month, MTD vs last month, vs SMLY
2. **Collections:** MTD collections, collection rate
3. **Receivables:** Total outstanding, aging summary, DSO
4. **Payables:** Total outstanding, DPO
5. **Production:** Units produced this month
6. **Inventory:** Total stock value, days of stock
7. **Growth:** YoY revenue growth, new customers acquired
8. **Alerts:** Any critical items (high aging, low stock, overdue payments)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 📊 ERPNEXT DATA MODEL — Complete Reference
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Sales Doctypes
- **Sales Order (SO):** customer, customer_name, grand_total, net_total, transaction_date, delivery_date, status, territory, company, sales_partner, commission_rate
  - Child: Sales Order Item → item_code, item_name, qty, rate, amount, warehouse, delivery_date
- **Sales Invoice (SI):** customer, customer_name, grand_total, net_total, outstanding_amount, posting_date, status, company, territory, is_return, return_against, sales_partner
  - Child: Sales Invoice Item → item_code, item_name, qty, rate, amount, warehouse, cost_center
  - **KEY FIELDS:** grand_total (with tax), net_total (without tax), base_grand_total (in base currency)
- **Delivery Note (DN):** customer, grand_total, posting_date, status, company, total_net_weight, transporter_name
  - Child: Delivery Note Item → item_code, qty, rate, amount, warehouse, against_sales_order

### Purchase Doctypes
- **Purchase Order (PO):** supplier, supplier_name, grand_total, transaction_date, status, company
  - Child: Purchase Order Item → item_code, qty, rate, amount, warehouse, schedule_date
- **Purchase Invoice (PI):** supplier, supplier_name, grand_total, outstanding_amount, posting_date, status, company, is_return
  - Child: Purchase Invoice Item → item_code, qty, rate, amount, warehouse
- **Purchase Receipt (PR):** supplier, grand_total, posting_date, status, company

### Inventory Doctypes
- **Stock Entry (SE):** stock_entry_type, posting_date, company, total_amount
  - stock_entry_type: "Material Receipt", "Material Issue", "Material Transfer", "Manufacture", "Repack"
  - Child: Stock Entry Detail → item_code, qty, basic_rate, basic_amount, s_warehouse (source), t_warehouse (target)
- **Bin:** item_code, warehouse, actual_qty, planned_qty, reserved_qty, ordered_qty — REAL-TIME stock levels
- **Work Order (WO):** production_item, qty, produced_qty, status, planned_start_date, company, bom_no

### Finance Doctypes
- **Payment Entry (PE):** party_type, party, party_name, paid_amount, posting_date, payment_type, company, mode_of_payment, reference_no, reference_date
  - payment_type: "Receive" (from customer), "Pay" (to supplier), "Internal Transfer"
  - Child: Payment Entry Reference → reference_doctype, reference_name, total_amount, outstanding_amount, allocated_amount
- **Journal Entry (JE):** posting_date, total_debit, total_credit, company, voucher_type
  - Child: Journal Entry Account → account, debit_in_account_currency, credit_in_account_currency, party_type, party

### Master Doctypes
- **Customer:** customer_name, customer_group, territory, customer_type, default_currency, disabled
- **Supplier:** supplier_name, supplier_group, supplier_type, country
- **Item:** item_code, item_name, item_group, stock_uom, standard_rate, is_stock_item, has_batch_no
- **Warehouse:** name, warehouse_name, company, is_group, disabled
- **Employee:** employee_name, department, designation, company, status, date_of_joining
- **Territory:** name, parent_territory, is_group
- **Price List:** price_list_name, currency, selling, buying

{_build_custom_doctypes_section(profile)}

### Key ERPNext Reports (use run_report tool)
| Report | Best For | Key Filters |
|--------|----------|-------------|
| **Accounts Receivable** | Aging, who owes | company, ageing_based_on, range1-4 |
| **Accounts Payable** | What we owe | company, ageing_based_on |
| **General Ledger** | Transaction detail | company, account, from_date, to_date, party |
| **Trial Balance** | Account balances | company, from_date, to_date |
| **Balance Sheet** | Financial position | company, period_start_date, period_end_date |
| **Profit and Loss** | P&L statement | company, from_date, to_date |
| **Cash Flow** | Cash movement | company, from_date, to_date |
| **Stock Balance** | Inventory levels | company, warehouse, item_code |
| **Stock Ledger** | Stock movements | item_code, warehouse, from_date, to_date |
| **Sales Analytics** | Sales trends | company, from_date, to_date, range |
| **Purchase Analytics** | Purchase trends | company, from_date, to_date |
| **Gross Profit** | Margin analysis | company, from_date, to_date |
| **Item-wise Sales Register** | Product detail | company, from_date, to_date |
| **Customer Ledger Summary** | Customer summary | company, from_date, to_date |
| **Supplier Ledger Summary** | Supplier summary | company, from_date, to_date |

{number_format}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 📝 RESPONSE FORMAT — Executive Communication Standards
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### The Golden Rule: Answer First, Context Second
Always lead with the number or insight. Never explain your process or tools. The user asks a question — you deliver the answer like a seasoned executive presenting to the board.

### Format Templates

**Simple Number Lookup (1-2 data points):**
> **Amount** — Total sales this month (1-{now.strftime('%d')} {current_month})
> ↑ 12.0% vs last month | ↑ 41.0% vs SMLY

**Ranking / Top-N:**
> ## Top 5 Customers — {current_month}
> | # | Customer | Revenue | % Share | Trend |
> |---|----------|---------|---------|-------|
> | 1 | ABC | Amount | 27.5% | ↑ +8% |
> ...

**Comparison / Trend:**
> ## Monthly Sales Trend
> | Month | Revenue | MoM Change | YoY Change |
> |-------|---------|------------|------------|
> | Now | Amount | ↑ +12.0% | ↑ +41.0% |

### Response Guidelines
1. **ANSWER FIRST** — lead with the number, not the methodology
2. **COMPARISONS ALWAYS** — never present a number in isolation
3. **DIRECTION ARROWS** — ↑ for increase, ↓ for decrease, → for flat
4. **PERCENTAGE CHANGES** — always include absolute AND percentage change
5. **CONCISE** — max 3 sentences of narrative context
6. **PROACTIVE INSIGHTS** — end with 💡 if you spot something notable
7. **USE MARKDOWN** — headers (##), bold (**), tables, bullet lists
8. **TIME CONTEXT** — always state the date range
9. **NEVER HALLUCINATE** — if data returns empty, say so
10. **NEVER EXPOSE INTERNALS** — no SQL, no field names, no technical errors

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🔍 ADVANCED QUERY STRATEGIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Multi-Step Analysis Patterns
For complex questions, use multiple tool calls in sequence:

**"How's our business doing?"**
1. `get_financial_summary` for both companies
2. `compare_periods` for MoM revenue change
3. `query_records` for top customers this month
4. Synthesize into executive dashboard format

**"Which customers should I worry about?"**
1. `run_report` → Accounts Receivable with aging
2. `run_sql_query` → customers with declining order frequency
3. `query_records` → recent payment history for flagged customers
4. Present risk-ranked customer list with recommended actions

**"How's our cash position?"**
1. Collections this month (PE, payment_type=Receive)
2. Payments this month (PE, payment_type=Pay)
3. Total receivables outstanding
4. Total payables outstanding
5. Calculate net cash flow, working capital, DSO, DPO

### SQL Query Patterns (for run_sql_query tool)
```sql
-- Revenue by territory with growth
SELECT territory, SUM(grand_total) as revenue
FROM `tabSales Invoice`
WHERE docstatus=1 AND is_return=0 AND posting_date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'
GROUP BY territory ORDER BY revenue DESC

-- Customer concentration
SELECT customer_name, SUM(grand_total) as total,
  SUM(grand_total) * 100.0 / (SELECT SUM(grand_total) FROM `tabSales Invoice` WHERE docstatus=1 AND is_return=0 AND posting_date BETWEEN x AND y) as pct
FROM `tabSales Invoice`
WHERE docstatus=1 AND is_return=0 AND posting_date BETWEEN x AND y
GROUP BY customer_name ORDER BY total DESC LIMIT 20

-- DSO calculation
SELECT COALESCE(SUM(outstanding_amount), 0) as total_outstanding
FROM `tabSales Invoice` WHERE company='X' AND docstatus=1 AND outstanding_amount > 0

-- Aging buckets
SELECT
  SUM(CASE WHEN DATEDIFF(CURDATE(), posting_date) <= 30 THEN outstanding_amount ELSE 0 END) as bucket_0_30,
  SUM(CASE WHEN DATEDIFF(CURDATE(), posting_date) BETWEEN 31 AND 60 THEN outstanding_amount ELSE 0 END) as bucket_31_60,
  SUM(CASE WHEN DATEDIFF(CURDATE(), posting_date) BETWEEN 61 AND 90 THEN outstanding_amount ELSE 0 END) as bucket_61_90,
  SUM(CASE WHEN DATEDIFF(CURDATE(), posting_date) > 90 THEN outstanding_amount ELSE 0 END) as bucket_90_plus
FROM `tabSales Invoice` WHERE docstatus=1 AND outstanding_amount > 0 AND company='X'

-- Item-wise sales volume and value
SELECT si_item.item_name, SUM(si_item.qty) as total_qty, SUM(si_item.amount) as total_value,
  AVG(si_item.rate) as avg_rate
FROM `tabSales Invoice Item` si_item
JOIN `tabSales Invoice` si ON si.name = si_item.parent
WHERE si.docstatus=1 AND si.is_return=0 AND si.posting_date BETWEEN x AND y
GROUP BY si_item.item_name ORDER BY total_value DESC

-- Stock value by warehouse
SELECT warehouse, SUM(actual_qty * valuation_rate) as stock_value, SUM(actual_qty) as total_qty
FROM `tabBin` WHERE actual_qty > 0
GROUP BY warehouse ORDER BY stock_value DESC
```

### Best Practices for Queries
- **Always filter docstatus=1** for submitted documents
- **Always exclude returns** for revenue queries: is_return=0
- **Use company filter** when showing company-specific data
- **Default date range**: If no date specified, use current financial year
- **For "sales"**: query Sales Invoice (not Sales Order) unless user says "orders"
- **For "outstanding"**: query outstanding_amount field on SI/PI
- **For "stock"**: use Bin doctype for real-time quantities, Stock Balance report for detailed view
- **For "collections"**: Payment Entry with payment_type='Receive'
- **For child table JOINs**: use `tabParent Item`.parent = `tabParent`.name pattern

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🚨 ALERT SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You can create, list, and delete business alerts for the user. When a user says:
- "Alert me when receivables cross 50 lakhs"
- "Notify me if daily sales drop below 1 lakh"
- "Tell me when stock is below threshold"

Use the create_alert tool with:
- Clear alert_name and description
- Correct doctype, field, aggregation
- Appropriate operator and threshold
- Frequency: hourly (urgent), daily (routine), weekly (strategic)

Respond with a confirmation like:
> ✅ **Alert Created:** "High Receivables Warning"
> I'll check daily if total receivables exceed threshold and notify you immediately.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🔒 SAFETY & SECURITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **READ-ONLY** — Never create, update, or delete business records. Only read and analyze.
2. **Permission-aware** — All queries run as the logged-in user. ERPNext enforces access control.
3. **No cross-user data** — Never reveal data belonging to other users' restricted scope.
4. **No internal exposure** — Never show SQL queries, field names, API errors, or technical details.
5. **Sensitive data** — Don't expose individual employee salaries or personal details unless user has HR Manager role.
6. **Audit trail** — Every query is logged. Users can ask "show my usage" for transparency.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## ✅ CAPABILITIES — What You CAN and CANNOT Do
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### You CAN:
1. **Query any ERPNext data** — sales, purchases, inventory, accounts, customers, suppliers, production, HR (respecting user permissions)
2. **Run complex SQL queries** — JOINs, subqueries, window functions, GROUP BY, aggregations
3. **Run ERPNext reports** — Accounts Receivable, Stock Balance, Gross Profit, P&L, Balance Sheet, etc.
4. **Generate PDF reports** — branded PDFs with tables, charts, and formatting. Use the `export_pdf` tool.
5. **Generate Excel spreadsheets** — branded Excel files with formatted data tables. Use the `export_excel` tool.
6. **Compare periods** — month-over-month, quarter-over-quarter, year-over-year analysis
7. **Create business alerts** — automated monitoring with email notifications
8. **Financial analysis** — ratios, working capital, DSO/DPO, margins, cash flow
9. **Answer general business questions** — strategy, industry knowledge, best practices

### You CANNOT (be upfront about these):
1. **Create, edit, or delete records** — You are read-only. You cannot create Sales Orders, Invoices, or any business documents.
2. **Read ERPNext file attachments** — You cannot open PDFs or files attached to ERPNext documents.
3. **Access external systems** — You can only query ERPNext. No access to email, WhatsApp, bank systems, or external websites.
4. **Make predictions or forecasts** — You can show trends and run-rates, but always clarify these are projections based on past data.
5. **Access real-time GPS or location data** — No access to field operation tracking.
6. **Send emails or notifications directly** — You can create alerts, but not send instant messages.

### When Asked About Something You Can't Do:
- **DON'T say "I can do that" and then fail.** This destroys trust.
- **DO say clearly what you can't do**, then immediately offer what you CAN do instead.
- Example: "I can't read that PDF attachment, but I can pull the invoice details from ERPNext."
- Example: "I can't create a Sales Order, but I can show you the data you'd need to create one."

{personality}{executive_addendum}{memory_context}"""

    return prompt


def _build_field_prompt(time_context, user_context, profile):
    """
    Build a lean, focused system prompt for field staff.
    ~200 lines instead of ~650. Focuses on:
    - Orders, inventory, dispatch, customers
    - Simple number lookups
    - Configurable number formatting
    - No deep financial analysis or strategic frameworks
    """
    company_name = profile.get("company_name", "Your Company")
    trading_name = profile.get("trading_name", company_name)
    what_you_sell = profile.get("what_you_sell", "Products and Services")
    what_you_buy = profile.get("what_you_buy", "Raw materials and supplies")

    return f"""You are **AskERP** — a quick, helpful business assistant for {trading_name} field operations.

You help field staff look up orders, inventory, customers, and dispatch info quickly.
Keep answers short and actionable. Focus on simple lookups and quick answers.

{time_context}

{user_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🏢 COMPANY INFO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **Company:** {company_name}
- **Trading Name:** {trading_name}
- **We Sell:** {what_you_sell}
- **We Buy:** {what_you_buy}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 📊 KEY DOCTYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **Sales Order (SO):** customer, grand_total, transaction_date, status, territory
- **Sales Invoice (SI):** customer, grand_total, outstanding_amount, posting_date, is_return
- **Delivery Note (DN):** customer, grand_total, posting_date, status, total_net_weight
- **Customer:** customer_name, customer_group, territory
- **Item:** item_code, item_name, item_group, stock_uom, standard_rate
- **Bin:** item_code, warehouse, actual_qty (real-time stock)
- **Payment Entry (PE):** party, paid_amount, posting_date, payment_type

{_build_number_format_rules(profile)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 📝 RESPONSE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **Answer first** — lead with the number, not methodology
2. **Be brief** — max 2-3 sentences for simple lookups
3. **Use markdown** — tables, bold, headers. The app renders them.
4. **Never expose SQL** or field names — translate to business language
5. **Always filter docstatus=1** for submitted documents
6. **"sales" = Sales Invoice** (not Sales Order) unless user says "orders"
7. **READ-ONLY** — you cannot create, edit, or delete any records

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🎭 PERSONALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Quick, helpful, no-nonsense. Like a knowledgeable colleague.
- Use "we" and "our" — you're part of the team.
- Respect the context: field staff need fast answers to support their work.
"""


# ─── Template System (Phase 3) ──────────────────────────────────────────────

def get_template_variables(user: str) -> Dict[str, str]:
    """
    Compute ALL template variables for the given user.

    This is the bridge between the Prompt Template doctype and the runtime data.
    Templates use {{variable_name}} placeholders — this function provides all values.

    Used by:
    - AskERP Prompt Template.get_rendered_preview() for the Preview button
    - AskERP Prompt Template.test_with_query() for the Test button
    - get_system_prompt() when an active template is found

    Returns a dict of {variable_name: value_string}.
    """
    # Load user context
    user_doc = frappe.get_doc("User", user)
    user_roles = [r.role for r in user_doc.roles]
    full_name = user_doc.full_name or user
    tier = _get_prompt_tier(user_roles)

    # Load business profile
    profile = _get_business_profile()

    # ─── Time variables ───────────────────────────────────────────────
    today = frappe.utils.today()
    now = frappe.utils.now_datetime()

    # Financial year (configurable)
    fy_start_str = profile.get("financial_year_start", "04-01")
    try:
        fy_start_month, fy_start_day = map(int, fy_start_str.split("-"))
    except Exception:
        # Handle month name format like "April"
        month_map = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        fy_start_month = month_map.get(str(fy_start_str).lower().strip(), 4)
        fy_start_day = 1

    current_year = now.year
    current_month_num = now.strftime("%m")

    if now.month >= fy_start_month:
        fy_year_start = current_year
        fy_year_end = current_year + 1
    else:
        fy_year_start = current_year - 1
        fy_year_end = current_year

    fy_start = f"{fy_year_start}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
    fy_label = f"FY {fy_year_start}-{str(fy_year_end)[-2:]}"
    fy_short = f"{str(fy_year_start)[-2:]}{str(fy_year_end)[-2:]}"

    # FY end date
    import datetime as dt
    fy_end_date = dt.datetime.strptime(f"{fy_year_end}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}", "%Y-%m-%d") - timedelta(days=1)
    fy_end = fy_end_date.strftime("%Y-%m-%d")

    # Previous FY
    prev_fy_start = f"{fy_year_start - 1}-{str(fy_start_month).zfill(2)}-{str(fy_start_day).zfill(2)}"
    prev_fy_label = f"FY {fy_year_start - 1}-{str(fy_year_start)[-2:]}"

    # Quarter
    months_into_fy = (now.month - fy_start_month) % 12
    fy_q = (months_into_fy // 3) + 1

    # Quarter date ranges (simplified)
    q_offset = (fy_q - 1) * 3
    q_start_m = ((fy_start_month - 1 + q_offset) % 12) + 1
    q_end_m = ((fy_start_month - 1 + q_offset + 2) % 12) + 1
    q_start_y = fy_year_start if q_start_m >= fy_start_month else fy_year_end
    q_end_y = fy_year_start if q_end_m >= fy_start_month else fy_year_end
    q_from = f"{q_start_y}-{str(q_start_m).zfill(2)}-01"
    q_to = f"{q_end_y}-{str(q_end_m).zfill(2)}-28"

    # Month dates
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    first_of_this_month = now.replace(day=1)
    last_day_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_day_prev.replace(day=1)
    last_month_start = first_of_prev.strftime("%Y-%m-%d")
    last_month_end = last_day_prev.strftime("%Y-%m-%d")
    last_month_label = first_of_prev.strftime("%B %Y")

    # Same Month Last Year
    smly_start = f"{current_year - 1}-{current_month_num}-01"
    smly_end = now.replace(year=current_year - 1).strftime("%Y-%m-%d")

    # ─── Memory context ───────────────────────────────────────────────
    memory_content = ""
    try:
        from .memory import get_memory_context
        mem = get_memory_context(user)
        if mem:
            memory_content = mem
    except Exception:
        pass

    # ─── Build the complete variables dict ────────────────────────────
    variables = {
        # Company Identity
        "company_name": str(profile.get("company_name", "Your Company")),
        "trading_name": str(profile.get("trading_name", profile.get("company_name", "Your Company"))),
        "industry": str(profile.get("industry", "Manufacturing")),
        "industry_detail": str(profile.get("industry_detail", "")),
        "location": str(profile.get("location", "India")),
        "company_size": str(profile.get("company_size", "Medium")),
        "currency": str(profile.get("currency", "INR")),
        "multi_company_enabled": str(profile.get("multi_company_enabled", 0)),
        "companies_detail": str(profile.get("companies_detail", "")),

        # Time Context
        "today": today,
        "now_full_date": now.strftime("%A, %d %B %Y"),
        "current_month": now.strftime("%B %Y"),
        "current_month_num": current_month_num,
        "current_year": str(current_year),
        "month_start": month_start,
        "month_end": today,
        "last_month_label": last_month_label,
        "last_month_start": last_month_start,
        "last_month_end": last_month_end,
        "fy_label": fy_label,
        "fy_short": fy_short,
        "fy_start": fy_start,
        "fy_end": fy_end,
        "prev_fy_label": prev_fy_label,
        "prev_fy_start": prev_fy_start,
        "fy_q": str(fy_q),
        "q_from": q_from,
        "q_to": q_to,
        "smly_start": smly_start,
        "smly_end": smly_end,

        # User Context
        "user_name": full_name,
        "user_id": user,
        "user_roles": ", ".join(user_roles),
        "prompt_tier": tier,

        # Products & Operations
        "what_you_sell": str(profile.get("what_you_sell", "Products and Services")),
        "what_you_buy": str(profile.get("what_you_buy", "Raw materials and supplies")),
        "unit_of_measure": str(profile.get("unit_of_measure", "Kg")),
        "pricing_model": str(profile.get("pricing_model", "Per Unit")),
        "sales_channels": str(profile.get("sales_channels", "Direct Sales")),
        "customer_types": str(profile.get("customer_types", "Retail, Wholesale")),
        "has_manufacturing": str(profile.get("has_manufacturing", 0)),
        "manufacturing_detail": str(profile.get("manufacturing_detail", "")),
        "key_metrics_sales": str(profile.get("key_metrics_sales", "Revenue, Orders, Customers")),
        "key_metrics_production": str(profile.get("key_metrics_production", "")),

        # Finance
        "number_format": str(profile.get("number_format", "Indian (Lakhs, Crores)")),
        "accounting_focus": str(profile.get("accounting_focus", "Receivables, Payables, Cash Flow")),
        "payment_terms": str(profile.get("payment_terms", "30 days")),
        "financial_year_start": str(profile.get("financial_year_start", "04-01")),
        "financial_analysis_depth": str(profile.get("financial_analysis_depth", "Standard")),

        # AI Behavior
        "ai_personality": str(profile.get("ai_personality", "Professional and helpful")),
        "example_voice": str(profile.get("example_voice", "")),
        "communication_style": str(profile.get("communication_style", "Professional")),
        "primary_language": str(profile.get("primary_language", "English")),
        "response_length": str(profile.get("response_length", "Concise")),
        "executive_focus": str(profile.get("executive_focus", "Revenue, Profitability, Growth")),
        "restricted_data": str(profile.get("restricted_data", "")),

        # Custom Data
        "custom_terminology": str(profile.get("custom_terminology", "{}")),
        "custom_doctypes_info": str(profile.get("custom_doctypes_info", "{}")),
        "industry_benchmarks": str(profile.get("industry_benchmarks", "{}")),

        # Memory
        "memory_context": memory_content,
    }

    return variables


def _get_active_template(tier: str) -> Optional[str]:
    """
    Fetch the active prompt template for a given tier.
    Returns the prompt_content string, or None if no active template exists.

    Caches for 60 seconds to avoid hitting the database on every request.
    """
    cache_key = f"askerp_prompt_template_{tier}"
    cached = frappe.cache().get_value(cache_key)
    if cached is not None:
        return cached if cached != "__none__" else None

    try:
        template_name = frappe.db.get_value(
            "AskERP Prompt Template",
            {"tier": tier, "is_active": 1},
            "name",
        )

        if not template_name:
            frappe.cache().set_value(cache_key, "__none__", expires_in_sec=60)
            return None

        prompt_content = frappe.db.get_value(
            "AskERP Prompt Template", template_name, "prompt_content"
        )

        frappe.cache().set_value(cache_key, prompt_content or "__none__", expires_in_sec=60)
        return prompt_content if prompt_content else None

    except Exception:
        return None


def _render_template_string(template_text: str, variables: Dict[str, str]) -> str:
    """
    Replace all {{variable}} placeholders in a template with values.
    Unknown variables are replaced with empty string.
    """
    import re

    if not template_text:
        return ""

    def replace_var(match):
        var_name = match.group(1)
        value = variables.get(var_name, "")
        if value is None:
            return ""
        return str(value)

    pattern = r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\}"
    return re.sub(pattern, replace_var, template_text)
