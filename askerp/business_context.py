"""
AskERP — Business Context v5.0 (Configurable via AskERP Business Profile)
===================================================================================

v5.0 Migration from Hardcoded to Configurable (Phase 5.2):
- All company-specific data moves to "AskERP Business Profile" singleton doctype
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
5. All hardcoded company strings replaced with profile.field_name references
6. Custom doctypes and industry benchmarks dynamically injected
7. Financial year start date now configurable

v5.1 Changes (Phase 1 Decoupling):
- Removed hardcoded _EXECUTIVE_ROLES, _MANAGEMENT_ROLES, _FIELD_ROLES constants
- _get_prompt_tier() now delegates to formatting.get_prompt_tier() which reads from AskERP Settings
- Role sets are admin-configurable via executive_priority_roles / manager_priority_roles

v5.2 Changes (Phase 2 Decoupling):
- _build_number_format_rules() now delegates to formatting.get_number_format_prompt()
  → Removed 47 lines of inline formatting rules and hardcoded 'currency == "INR"' fallback
- Time intelligence in get_system_prompt() now delegates to formatting.get_time_context()
  → Removed 110 lines of inline FY/quarter/month/SMLY calculations
- Time variables in get_template_variables() now delegates to formatting.get_time_context()
  → Removed 65 lines of duplicate FY/quarter/month/SMLY calculations
- Removed `from datetime import timedelta` import (no longer needed)
- All time logic is now centralized in formatting.py — single source of truth

v5.3 Changes (Phase 3 — Dynamic Schema Discovery):
- Replaced hardcoded ERPNEXT DATA MODEL section (~180 lines of doctypes, fields, reports, SQL)
  with _build_data_model_section(profile) that reads from discovered_data_model field
- context_discovery.py now scans live database schema (frappe.get_meta) and generates
  the data model text automatically — doctypes, fields, child tables, reports, SQL patterns
- discovered_data_model is stored in AskERP Business Profile and refreshed monthly
- Fallback: if discovered_data_model is empty (pre-discovery), provides minimal ERPNext
  reference with basic doctypes so the AI can still function
- Removed ~180 lines of hardcoded Sales/Purchase/Inventory/Finance/Masters doctypes
- Removed ~50 lines of hardcoded SQL query patterns (now generated from actual fields)
- Removed ~10 lines of hardcoded best practices (now included in generated data model)
- Removed dead code: _build_si_pos_fields(), _build_pos_section(), _has_pos_profiles()
  (POS detection is now automatic via _scan_active_doctypes in context_discovery)

Backward Compatibility:
- If profile doesn't exist or field is empty, sensible defaults are used
- All universal frameworks (CFO/CTO/CEO, query patterns, safety rules) unchanged
"""

import frappe
from typing import Dict, Optional, Any
from askerp.formatting import (
    get_role_sets,
    get_prompt_tier as _formatting_get_prompt_tier,
    get_number_format_prompt,
    get_time_context,
)
from askerp.schema_utils import (
    build_key_doctypes_text,
    build_fallback_schema_text,
    build_error_recovery_text,
    build_financial_metrics_text,
)


# ─── Role-Based Tier Classification (v5.1 — reads from AskERP Settings) ─────

def _get_role_sets_cached():
    """Get role sets from AskERP Settings (cached in formatting.py)."""
    return get_role_sets()


def _get_prompt_tier(user_roles):
    """
    Determine the prompt tier for a user based on their ERPNext roles.
    Reads executive/management role sets from AskERP Settings.
    Returns: 'executive', 'management', or 'field'
    """
    return _formatting_get_prompt_tier(set(user_roles))


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
    Delegates to formatting.get_number_format_prompt() — the central engine.

    Phase 2 Change: Removed 47 lines of inline formatting rules.
    Removed hardcoded 'currency == "INR"' fallback that forced Indian format.
    Now purely profile-driven — whatever the admin configures is what gets used.
    """
    rules = get_number_format_prompt(profile)
    return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{rules}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


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


def _build_approval_workflows_section(profile: Dict[str, Any]) -> str:
    """
    Build approval workflows quick-reference for executive/management prompts.

    Phase P2.1: This reads the AI-generated summary from the approval_workflows
    field on the Business Profile, populated by context_discovery.py.

    Complements the detailed workflow transition data already present in
    discovered_data_model (DATABASE SCHEMA section). This section provides a
    concise, business-oriented summary of approval chains.
    """
    workflows_text = (profile.get("approval_workflows") or "").strip()

    if not workflows_text:
        return ""

    return f"""

### Approval Workflows (Quick Reference)
{workflows_text}

**Tip:** When users ask about pending approvals, use `run_sql_query` to check
the workflow_state field on the relevant doctype. The schema section above has
the exact state names and transitions for each workflow."""


def _build_data_model_section(profile: Dict[str, Any]) -> str:
    """
    Build the data model reference section for the system prompt.

    Phase 3 Change: Reads from discovered_data_model field (auto-generated
    by context_discovery.py) instead of hardcoded doctypes/fields/SQL.

    Priority:
    1. If discovered_data_model has content → use it (includes doctypes, fields,
       reports, SQL patterns, best practices — all from live database scan)
    2. If empty (before first discovery run) → return minimal fallback that
       teaches the AI basic ERPNext conventions so it can still function

    The discovered_data_model is refreshed monthly by scheduled_context_refresh().
    """
    discovered = (profile.get("discovered_data_model") or "").strip()

    if discovered:
        return discovered

    # ─── Fallback: minimal ERPNext reference for pre-discovery state ─────
    # Dynamically generated from live metadata via schema_utils
    return build_fallback_schema_text()


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

    # ─── Time Intelligence (Phase 2: delegates to formatting.get_time_context()) ───
    # All FY/quarter/month/SMLY calculations centralized in formatting.py.
    # Respects profile.financial_year_start setting.
    tc = get_time_context(profile)

    today = tc["today"]
    current_month = tc["current_month"]
    fy_label = tc["fy_label"]
    fy_start = tc["fy_start"]
    fy_end = tc["fy_end"]
    prev_fy_label = tc["prev_fy_label"]
    prev_fy_start = tc["prev_fy_start"]
    fy_q = tc["fy_q"]
    q_from = tc["q_from"]
    q_to = tc["q_to"]
    month_start = tc["month_start"]
    last_month_label = tc["last_month_label"]
    last_month_start = tc["last_month_start"]
    last_month_end = tc["last_month_end"]
    smly_start = tc["smly_start"]
    smly_end = tc["smly_end"]

    # ─── Build time context (shared across all tiers) ─────────────────────
    time_context = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🕐 TIME CONTEXT (Use for all date-relative queries)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- **Today:** {today} ({tc["now_full_date"]})
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
        approval_workflows = _build_approval_workflows_section(profile)

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
{industry_benchmarks}{approval_workflows}"""

    # ─── Build full prompt ───────────────────────────────────────────────
    company_identity = _build_company_identity(profile)
    number_format = _build_number_format_rules(profile)
    personality = _build_personality(profile)
    error_recovery_text = build_error_recovery_text()

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
- Gross Revenue (from submitted sales invoices, excluding returns)
- Net Revenue (gross minus return invoices)
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
## 📊 DATABASE SCHEMA REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{_build_data_model_section(profile)}

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
## 🔄 TOOL ERROR RECOVERY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{error_recovery_text}

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
    key_doctypes_text = build_key_doctypes_text()

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

{key_doctypes_text}

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

    # ─── Time variables (Phase 2: delegates to formatting.get_time_context()) ──
    tc = get_time_context(profile)
    today = tc["today"]
    current_year = str(tc["current_year"])
    current_month_num = tc["current_month_num"]
    month_start = tc["month_start"]
    fy_label = tc["fy_label"]
    fy_short = tc["fy_short"]
    fy_start = tc["fy_start"]
    fy_end = tc["fy_end"]
    prev_fy_label = tc["prev_fy_label"]
    prev_fy_start = tc["prev_fy_start"]
    fy_q = tc["fy_q"]
    q_from = tc["q_from"]
    q_to = tc["q_to"]
    last_month_label = tc["last_month_label"]
    last_month_start = tc["last_month_start"]
    last_month_end = tc["last_month_end"]
    smly_start = tc["smly_start"]
    smly_end = tc["smly_end"]

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
        "now_full_date": tc["now_full_date"],
        "current_month": tc["current_month"],
        "current_month_num": current_month_num,
        "current_year": current_year,
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
        "approval_workflows": str(profile.get("approval_workflows", "")),

        # Dynamic Schema (resolved at runtime from live ERPNext metadata)
        "key_doctypes": build_key_doctypes_text(),

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
