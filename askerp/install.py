"""
AskERP — Post-Install Setup
======================================
Creates default model configurations and settings after app installation.
Run automatically via hooks.py after_install, or manually via bench console:

    from askerp.install import after_install
    after_install()
"""

import frappe


def after_install():
    """Main entry point called by hooks.py after app install."""
    _create_custom_fields_on_user()
    _create_default_models()
    _create_default_settings()
    _create_default_business_profile()
    _create_default_prompt_templates()
    _create_default_custom_tools()
    frappe.db.commit()
    print("AskERP: Default models, settings, profile, templates, and custom tools created.")


def _create_custom_fields_on_user():
    """
    Create custom fields on the User doctype required by the AI assistant.
    These are also declared as fixtures in hooks.py for export, but they
    MUST be created here first — fixtures only export fields that already exist.

    Without these fields:
    - _check_ai_access() fails → all users denied AI access
    - memory.py get_user_preferences() crashes on missing field
    - briefing scheduler job crashes when querying allow_ai_chat
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    custom_fields = {
        "User": [
            {
                "fieldname": "allow_ai_chat",
                "label": "Allow AI Chat",
                "fieldtype": "Check",
                "insert_after": "enabled",
                "default": "0",
                "description": "Enable AI Chat assistant for this user",
            },
            {
                "fieldname": "custom_ai_preferences",
                "label": "AI Preferences",
                "fieldtype": "Small Text",
                "insert_after": "allow_ai_chat",
                "hidden": 1,
                "description": "JSON store for user-specific AI preferences (managed by AI assistant)",
            },
        ]
    }

    create_custom_fields(custom_fields, update=True)
    print("  Custom fields created on User doctype: allow_ai_chat, custom_ai_preferences")


def _create_default_models():
    """
    Create default AskERP Model records if they don't exist.
    Admin must still enter API keys — these are just the model configs.
    """
    models = [
        {
            "model_name": "Claude Haiku 4.5",
            "model_id": "claude-haiku-4-5-20251001",
            "provider": "Anthropic",
            "api_base_url": "https://api.anthropic.com/v1/messages",
            "api_version": "2023-06-01",
            "max_output_tokens": 4096,
            "supports_tools": 1,
            "supports_vision": 0,
            "supports_streaming": 1,
            "supports_thinking": 0,
            "input_cost_per_million": 0.80,
            "output_cost_per_million": 4.00,
            "cache_read_cost_per_million": 0.08,
            "cache_write_cost_per_million": 1.00,
            "token_budget_simple": 2048,
            "token_budget_medium": 3072,
            "token_budget_complex": 4096,
            "max_tool_rounds": 3,
            "enabled": 1,
            "rate_limits": [
                {"role": "System Manager", "daily_limit": 200},
                {"role": "Accounts Manager", "daily_limit": 100},
                {"role": "Sales Manager", "daily_limit": 80},
            ],
        },
        {
            "model_name": "Claude Sonnet 4.5",
            "model_id": "claude-sonnet-4-5-20250929",
            "provider": "Anthropic",
            "api_base_url": "https://api.anthropic.com/v1/messages",
            "api_version": "2023-06-01",
            "max_output_tokens": 8192,
            "supports_tools": 1,
            "supports_vision": 1,
            "supports_streaming": 1,
            "supports_thinking": 1,
            "input_cost_per_million": 3.00,
            "output_cost_per_million": 15.00,
            "cache_read_cost_per_million": 0.30,
            "cache_write_cost_per_million": 3.75,
            "token_budget_simple": 4096,
            "token_budget_medium": 6144,
            "token_budget_complex": 8192,
            "max_tool_rounds": 5,
            "enabled": 1,
            "rate_limits": [
                {"role": "System Manager", "daily_limit": 200},
                {"role": "Accounts Manager", "daily_limit": 80},
                {"role": "Sales Manager", "daily_limit": 60},
            ],
        },
        {
            "model_name": "Claude Opus 4.5",
            "model_id": "claude-opus-4-5-20251101",
            "provider": "Anthropic",
            "api_base_url": "https://api.anthropic.com/v1/messages",
            "api_version": "2023-06-01",
            "max_output_tokens": 16384,
            "supports_tools": 1,
            "supports_vision": 1,
            "supports_streaming": 1,
            "supports_thinking": 1,
            "input_cost_per_million": 15.00,
            "output_cost_per_million": 75.00,
            "cache_read_cost_per_million": 1.50,
            "cache_write_cost_per_million": 18.75,
            "token_budget_simple": 8192,
            "token_budget_medium": 12288,
            "token_budget_complex": 16384,
            "max_tool_rounds": 8,
            "enabled": 1,
            "rate_limits": [
                {"role": "System Manager", "daily_limit": 150},
                {"role": "Accounts Manager", "daily_limit": 50},
                {"role": "Sales Manager", "daily_limit": 30},
            ],
        },
        {
            "model_name": "Gemini 2.0 Flash",
            "model_id": "gemini-2.0-flash",
            "provider": "Google",
            "api_base_url": "https://generativelanguage.googleapis.com/v1beta/models",
            "max_output_tokens": 4096,
            "supports_tools": 1,
            "supports_vision": 0,
            "supports_streaming": 0,
            "supports_thinking": 0,
            "input_cost_per_million": 0.10,
            "output_cost_per_million": 0.40,
            "cache_read_cost_per_million": 0,
            "cache_write_cost_per_million": 0,
            "token_budget_simple": 2048,
            "token_budget_medium": 3072,
            "token_budget_complex": 4096,
            "max_tool_rounds": 3,
            "enabled": 0,  # Disabled by default — needs Google API key
            "rate_limits": [
                {"role": "System Manager", "daily_limit": 300},
            ],
        },
    ]

    for model_data in models:
        rate_limits = model_data.pop("rate_limits", [])

        # Skip if model already exists
        if frappe.db.exists("AskERP Model", {"model_id": model_data["model_id"]}):
            continue

        doc = frappe.get_doc({
            "doctype": "AskERP Model",
            **model_data,
        })

        for rl in rate_limits:
            doc.append("rate_limits", rl)

        doc.insert(ignore_permissions=True)
        print(f"  Created model: {model_data['model_name']}")


def _create_default_settings():
    """
    Create or update AskERP Settings with default tier assignments.
    Only sets values if they're empty — doesn't override admin changes.
    """
    try:
        settings = frappe.get_doc("AskERP Settings")
    except frappe.DoesNotExistError:
        settings = frappe.get_doc({"doctype": "AskERP Settings"})
        settings.insert(ignore_permissions=True)

    changed = False

    # Find model docs by model_id for tier assignment
    def _get_model_name(model_id):
        return frappe.db.get_value("AskERP Model", {"model_id": model_id, "enabled": 1}, "name")

    # Only set tier defaults if not already configured
    if not settings.tier_1_model:
        # Tier 1 (Economy): Gemini Flash or Haiku
        name = _get_model_name("gemini-2.0-flash") or _get_model_name("claude-haiku-4-5-20251001")
        if name:
            settings.tier_1_model = name
            changed = True

    if not settings.tier_2_model:
        name = _get_model_name("claude-sonnet-4-5-20250929")
        if name:
            settings.tier_2_model = name
            changed = True

    if not settings.tier_3_model:
        name = _get_model_name("claude-opus-4-5-20251101")
        if name:
            settings.tier_3_model = name
            changed = True

    if not settings.utility_model:
        name = _get_model_name("claude-haiku-4-5-20251001")
        if name:
            settings.utility_model = name
            changed = True

    if not settings.vision_model:
        name = _get_model_name("claude-sonnet-4-5-20250929") or _get_model_name("claude-opus-4-5-20251101")
        if name:
            settings.vision_model = name
            changed = True

    if not settings.fallback_model:
        name = _get_model_name("claude-haiku-4-5-20251001")
        if name:
            settings.fallback_model = name
            changed = True

    # Set default cost control if not configured
    if not settings.monthly_budget_limit:
        settings.monthly_budget_limit = 100  # $100/month default
        changed = True

    if not settings.enable_smart_routing:
        settings.enable_smart_routing = 1
        changed = True

    if changed:
        settings.save(ignore_permissions=True)
        print("  AskERP Settings defaults configured.")
    else:
        print("  AskERP Settings already configured — skipping.")


def _create_default_business_profile():
    """
    Create the AskERP Business Profile singleton with FGIPL's data pre-filled.

    This ensures Shiva's installation continues to work exactly as before
    after the genericization — all the previously hardcoded FGIPL business
    context is now stored in this configurable doctype.

    For new installations (non-FGIPL), this creates an empty profile that
    the admin fills in via the ERPNext UI.

    Only sets values if the profile is empty — doesn't override user changes.
    """
    import json

    try:
        profile = frappe.get_single("AskERP Business Profile")
    except frappe.DoesNotExistError:
        profile = frappe.get_doc({"doctype": "AskERP Business Profile"})
        profile.insert(ignore_permissions=True)
        profile = frappe.get_single("AskERP Business Profile")

    # Only pre-fill if the profile is essentially empty
    # (company_name not set = brand new installation)
    if profile.company_name and len(str(profile.company_name).strip()) >= 3:
        print("  AskERP Business Profile already configured — skipping.")
        return

    # ─── FGIPL Pre-Fill Data ─────────────────────────────────────────────
    # Source: docs/FGIPL-BUSINESS-PROFILE-DATA.md
    # This data was previously hardcoded in business_context.py v4.0

    # Section 1: Company Identity
    profile.company_name = "Fertile Green Industries Private Limited (FGIPL)"
    profile.trading_name = "Truemeal Feeds Private Limited (TMF)"
    profile.industry = "Manufacturing"
    profile.industry_detail = (
        "Animal Feed Manufacturing — Total Mixed Ration (TMR) for ruminants "
        "(cows, goats, sheep, buffaloes). We manufacture complete balanced feed "
        "using corn silage, sorghum silage, paddy straw, and other roughage "
        "ingredients at our state-of-the-art plant."
    )
    profile.location = "Nellore, Andhra Pradesh, India"
    profile.company_size = "51-200"
    profile.currency = "INR"
    profile.financial_year_start = "April"

    # Multi-company setup
    profile.multi_company_enabled = 1
    profile.companies_detail = (
        "1. Fertile Green Industries Private Limited (FGIPL) — Manufacturing, "
        "procurement, production, some direct sales\n"
        "2. Truemeal Feeds Private Limited (TMF) — Sales and distribution\n\n"
        "CRITICAL: When user asks about 'total sales' or 'the company', query "
        "BOTH companies and show combined + breakdown."
    )

    # Section 2: Products & Services
    profile.what_you_sell = (
        "- Corn Silage (fermented high-moisture stored fodder)\n"
        "- Sorghum Silage\n"
        "- Dehydrated Corn Silage\n"
        "- Paddy Straw (roughage)\n"
        "- Dry Fodder\n"
        "- TMR Mixes (complete balanced feed blends)\n"
        "- Concentrates (high-protein supplements)"
    )
    profile.what_you_buy = (
        "- Whole Crop Maize (for silage production)\n"
        "- Sorghum (for silage production)\n"
        "- Paddy Straw\n"
        "- Other roughage ingredients\n"
        "- Packaging materials\n"
        "- Transport services"
    )
    profile.unit_of_measure = "Kg (kilogram) — primary unit. Also uses Bag, Bale, Tonne."
    profile.pricing_model = (
        "Per Kg, ex-factory (transport extra) or delivered. "
        "Incoterms: EXW, EXS, DAP, DPU, DTF, DCL, DNF."
    )

    # Section 3: Sales & Customers
    profile.sales_channels = (
        "- Direct to dairy farms and cattle owners\n"
        "- Through Dealer/Sub-Dealer network\n"
        "- Institutional sales (Amul, Milma, other cooperative milk companies)\n"
        "- Own outlets"
    )
    profile.customer_types = (
        "- Dairy farmers and cattle owners\n"
        "- Dealer/Sub-Dealers (multi-level distribution)\n"
        "- Institutional buyers (milk cooperatives)\n"
        "- Consultants (hybrid model — facilitators who earn commission)"
    )
    profile.key_metrics_sales = (
        "Monthly revenue (combined both companies), Revenue by territory, "
        "Top 10 customer revenue, Daily sales and collections, "
        "Average order value, DSO, Collection efficiency rate"
    )

    # Section 4: Operations & Production
    profile.has_manufacturing = 1
    profile.manufacturing_detail = (
        "- State-of-the-art TMR manufacturing plant in Nellore\n"
        "- 30+ silage bunkers for raw material storage\n"
        "- Procurement through contract farming\n"
        "- Heavy field operations for procurement across farming regions\n"
        "- BOM-based production with batch tracking\n"
        "- Quality inspection at multiple stages"
    )
    profile.key_metrics_production = (
        "Work Order completion rate, Production yield, "
        "Bunker/silage inventory levels, Rejection/wastage rate, "
        "Capacity utilization"
    )

    # Section 5: Finance & Accounting
    profile.accounting_focus = (
        "- Outstanding receivables by customer\n"
        "- Monthly P&L comparison\n"
        "- Cash flow status\n"
        "- Vendor payment dues\n"
        "- Collections vs billing\n"
        "- DSO, DPO, DIO metrics\n"
        "- Working capital cycle\n"
        "- Aging analysis (0-30, 30-60, 60-90, 90+ days)\n"
        "- Revenue run-rate and annualized projections\n"
        "- Customer concentration risk"
    )
    profile.payment_terms = (
        "Standard credit terms for established customers, "
        "advance payment for new customers."
    )
    profile.financial_analysis_depth = (
        "CFO-level analysis: Revenue analysis (gross, net, by company/territory/"
        "customer/product/salesperson), Profitability analysis (gross margin, "
        "product-wise, territory-wise), Working capital intelligence (DSO, DPO, "
        "DIO, cash conversion cycle), Collection efficiency with aging, "
        "Cost analysis (purchase trends, per-unit production cost), "
        "Key ratios (current ratio, gross margin %, net profit margin %, "
        "ROA, D/E, revenue per employee)"
    )

    # Section 6: Terminology & Language
    profile.custom_terminology = (
        "TMR = Total Mixed Ration (complete balanced feed for ruminants)\n"
        "Silage = Fermented high-moisture stored fodder\n"
        "Bunker = Underground/above-ground storage for silage (mapped to Warehouse)\n"
        "Roughage = Fibrous feed ingredients (paddy straw, dry fodder)\n"
        "Concentrate = High-protein feed supplement\n"
        "FGIPL = Fertile Green Industries Private Limited (manufacturing entity)\n"
        "TMF = Truemeal Feeds Private Limited (sales entity)\n"
        "SO = Sales Order\n"
        "SI = Sales Invoice\n"
        "DN = Delivery Note\n"
        "PE = Payment Entry\n"
        "PO = Purchase Order\n"
        "PI = Purchase Invoice\n"
        "PR = Purchase Receipt\n"
        "WO = Work Order\n"
        "SE = Stock Entry\n"
        "GRN = Goods Receipt Note\n"
        "DSO = Days Sales Outstanding\n"
        "DPO = Days Payable Outstanding\n"
        "DIO = Days Inventory Outstanding\n"
        "SMLY = Same Month Last Year\n"
        "MTD = Month To Date\n"
        "YTD = Year To Date\n"
        "QTD = Quarter To Date"
    )
    profile.communication_style = "Professional"
    profile.primary_language = "English"

    # Section 7: AI Behavior Preferences
    profile.response_length = "Detailed"
    profile.number_format = "Indian (Lakhs, Crores)"
    profile.executive_focus = (
        "- Revenue vs target\n"
        "- Cash position and collections\n"
        "- Overdue receivables\n"
        "- Working capital cycle\n"
        "- Production output\n"
        "- Low stock items\n"
        "- Customer concentration risk\n"
        "- Growth metrics (YoY, MoM, SMLY)"
    )
    profile.restricted_data = (
        "- Individual employee salaries (unless user has HR Manager role)\n"
        "- Customer-specific pricing discounts\n"
        "- Internal margin percentages (unless user is Executive/System Manager)"
    )

    # AI Personality
    profile.ai_personality = (
        "Professional but warm. Trusted senior executive, not a cold database. "
        "Use 'we' and 'our'. Be decisive — don't hedge. Be proactive — if the "
        "data shows something important, say it. Be concise — business users want "
        "insights, not essays. Use industry language (TMR, silage, bunkers). "
        "Think ahead — anticipate what the user might ask next. Challenge "
        "assumptions — if data contradicts what the user assumes, respectfully "
        "point it out. Recommend actions — don't just report numbers."
    )
    profile.example_voice = (
        "Our collections this month are 38.4 L against 52.1 L in sales — "
        "that's a 73.7% collection rate, down from 81.2% last month. DSO has "
        "crept up to 47 days. I'd recommend focusing on the top 5 overdue "
        "accounts — they hold 18.2 L (47% of outstanding). Want me to pull "
        "up the aging breakdown?"
    )

    # Custom Doctypes
    profile.custom_doctypes_info = json.dumps({
        "Consultant": "consultant_name, mobile, territory, commission_rate. Creates Sales Partner + Supplier automatically (hybrid model).",
        "TM Gate Pass": "delivery_note, driver, vehicle, gross_weight, tare_weight, net_weight.",
        "TM Expense Entry": "expense_type, expense_date, amount, party_type, party, paid_from, journal_entry, payment_status, outstanding_amount.",
        "TM Incentive Scheme": "Incentive tracking for sales force.",
        "TM Incentive Ledger": "Incentive ledger entries.",
    })

    # Industry Benchmarks
    profile.industry_benchmarks = json.dumps({
        "Typical gross margin": "15-25% for TMR manufacturers",
        "Typical DSO": "30-45 days for feed industry",
        "Revenue growth": "8-15% YoY for mid-size manufacturers",
        "Working capital cycle": "45-75 days is normal",
    })

    profile.save(ignore_permissions=True)
    print("  AskERP Business Profile pre-filled with FGIPL data.")


def _create_default_prompt_templates():
    """
    Create default prompt templates for each tier (Executive, Management, Field).

    These templates use {{variable}} placeholders that are replaced at runtime
    by business_context.get_template_variables(). Admins can edit them in the
    ERPNext UI to customize AI behavior without code changes.

    Only creates templates if they don't already exist.
    Templates are created INACTIVE by default — the system falls back to the
    hardcoded prompts until an admin explicitly activates a template.
    """
    from askerp.default_templates import (
        EXECUTIVE_TEMPLATE,
        MANAGEMENT_TEMPLATE,
        FIELD_TEMPLATE,
    )

    templates = [
        {
            "template_name": "Executive System Prompt",
            "tier": "Executive",
            "is_active": 0,
            "description": (
                "Full CFO/CTO/CEO intelligence prompt for System Managers and Administrators. "
                "Includes financial analysis frameworks, strategic metrics, board-level reporting, "
                "and industry benchmarks."
            ),
            "prompt_content": EXECUTIVE_TEMPLATE,
        },
        {
            "template_name": "Management System Prompt",
            "tier": "Management",
            "is_active": 0,
            "description": (
                "Business analysis prompt for department managers. "
                "Includes financial metrics, operational insights, and departmental analysis. "
                "More focused than Executive, less detailed than full CFO framework."
            ),
            "prompt_content": MANAGEMENT_TEMPLATE,
        },
        {
            "template_name": "Field Staff System Prompt",
            "tier": "Field",
            "is_active": 0,
            "description": (
                "Lean, fast prompt for field staff (Sales Users, Stock Users, etc.). "
                "Focused on quick lookups: orders, inventory, customers, dispatch. "
                "Short responses, no deep financial analysis."
            ),
            "prompt_content": FIELD_TEMPLATE,
        },
    ]

    for tmpl in templates:
        # Skip if template already exists
        if frappe.db.exists("AskERP Prompt Template", tmpl["template_name"]):
            print(f"  Template '{tmpl['template_name']}' already exists — skipping.")
            continue

        doc = frappe.get_doc({
            "doctype": "AskERP Prompt Template",
            **tmpl,
        })
        doc.insert(ignore_permissions=True)
        print(f"  Created template: {tmpl['template_name']} ({tmpl['tier']} tier)")


def _create_default_custom_tools():
    """
    Create 8 pre-built AI custom tools that work out of the box.

    These tools demonstrate the No-Code Tool Builder and provide
    immediate value. Admins can customize or disable them.

    Only creates tools if they don't already exist.
    """
    from askerp.default_tools import DEFAULT_CUSTOM_TOOLS

    for tool_data in DEFAULT_CUSTOM_TOOLS:
        # Skip if tool already exists
        if frappe.db.exists("AskERP Custom Tool", tool_data["tool_name"]):
            print(f"  Custom tool '{tool_data['tool_name']}' already exists — skipping.")
            continue

        # Separate parameters from main doc fields
        parameters = tool_data.pop("parameters", [])

        doc = frappe.get_doc({
            "doctype": "AskERP Custom Tool",
            **tool_data,
        })

        for param in parameters:
            doc.append("parameters", param)

        doc.insert(ignore_permissions=True)
        print(f"  Created custom tool: {tool_data.get('display_name', tool_data.get('tool_name'))}")

        # Re-add parameters key for future iterations (pop mutates the dict)
        tool_data["parameters"] = parameters
