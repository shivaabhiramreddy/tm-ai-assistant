"""
AskERP — Universal Formatting Engine
==========================================
Single source of truth for all number/currency formatting, FY calculations,
and branding across the entire AskERP codebase.

EVERY file that needs to format currency, numbers, dates, or company names
MUST import from here — never write inline formatters.

Reads configuration from:
  1. AskERP Business Profile (singleton) — currency, number_format, financial_year_start
  2. AskERP Settings (singleton) — executive_priority_roles, manager_priority_roles

Caching:
  - Profile cached 300 seconds (same as business_context.py)
  - Settings cached 300 seconds
  - Cache cleared on doctype save (see hooks.py)
"""

import frappe
from frappe.utils import flt, getdate, get_first_day, get_last_day, today, now_datetime


# ─── Currency Symbol Map ─────────────────────────────────────────────────────
# Common currencies. For unlisted currencies, falls back to Frappe Currency doctype.

_CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "د.إ",
    "SAR": "﷼",
    "JPY": "¥",
    "CNY": "¥",
    "AUD": "A$",
    "CAD": "C$",
    "SGD": "S$",
    "MYR": "RM",
    "THB": "฿",
    "KRW": "₩",
    "BRL": "R$",
    "ZAR": "R",
    "NGN": "₦",
    "KES": "KSh",
    "BDT": "৳",
    "PKR": "₨",
    "LKR": "Rs",
    "NPR": "Rs",
}


# ─── Profile & Settings Cache ────────────────────────────────────────────────

def get_cached_profile():
    """
    Get AskERP Business Profile as a dict. Cached 300 seconds.
    Returns sensible defaults if profile doesn't exist yet.
    """
    cache_key = "askerp_business_profile"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        profile_doc = frappe.get_single("AskERP Business Profile")
        data = profile_doc.as_dict()
        frappe.cache().set_value(cache_key, data, expires_in_sec=300)
        return data
    except Exception:
        return _get_default_profile()


def _get_cached_settings():
    """
    Get AskERP Settings as a dict. Cached 300 seconds.
    Returns sensible defaults if settings don't exist yet.
    """
    cache_key = "askerp_settings_cache"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    try:
        settings_doc = frappe.get_single("AskERP Settings")
        data = settings_doc.as_dict()
        frappe.cache().set_value(cache_key, data, expires_in_sec=300)
        return data
    except Exception:
        return {
            "executive_priority_roles": "System Manager,Accounts Manager",
            "manager_priority_roles": "Sales Manager,Purchase Manager,Stock Manager,Manufacturing Manager",
            "default_daily_limit": 50,
            "field_staff_daily_limit": 30,
        }


def _get_default_profile():
    """Sensible defaults when no profile exists yet."""
    return {
        "company_name": "Your Company",
        "trading_name": "Your Company",
        "industry": "General Business",
        "currency": "USD",
        "financial_year_start": "January",
        "number_format": "International (Millions, Billions)",
        "unit_of_measure": "Units",
        "location": "",
        "primary_language": "English",
    }


# ─── Currency Symbol ─────────────────────────────────────────────────────────

def get_currency_symbol(currency_code=None):
    """
    Get the currency symbol for a given currency code.

    Args:
        currency_code: ISO currency code (e.g. "INR", "USD"). If None, reads from profile.

    Returns:
        Currency symbol string (e.g. "₹", "$")
    """
    if not currency_code:
        profile = get_cached_profile()
        currency_code = profile.get("currency") or "USD"

    # Check our local map first (fast)
    symbol = _CURRENCY_SYMBOLS.get(currency_code)
    if symbol:
        return symbol

    # Fall back to Frappe's Currency doctype
    try:
        symbol = frappe.db.get_value("Currency", currency_code, "symbol")
        if symbol:
            return symbol
    except Exception:
        pass

    # Last resort: just use the code
    return currency_code


# ─── Number Formatting ────────────────────────────────────────────────────────

def format_currency(value, profile=None, currency_code=None):
    """
    Format a number as currency based on profile settings.

    Reads profile.number_format to determine style:
      - "Indian (Lakhs, Crores)" → ₹45.23 L, ₹2.15 Cr
      - "International (Millions, Billions)" → $4.52M, $21.5M
      - "Plain numbers" → 4,523,000

    Args:
        value: The number to format
        profile: Optional pre-fetched profile dict. If None, fetches from cache.
        currency_code: Optional override. If None, reads from profile.

    Returns:
        Formatted currency string
    """
    if profile is None:
        profile = get_cached_profile()

    number_format = profile.get("number_format") or "International (Millions, Billions)"

    if not currency_code:
        currency_code = profile.get("currency") or "USD"
    symbol = get_currency_symbol(currency_code)

    val = flt(value)

    if "Indian" in number_format:
        return _format_indian(val, symbol)
    elif "International" in number_format:
        return _format_international(val, symbol)
    else:
        return _format_plain(val, symbol)


def format_number(value, profile=None):
    """
    Format a number WITHOUT currency symbol.
    Uses the same grouping convention (Indian or International) but no symbol.

    Args:
        value: The number to format
        profile: Optional pre-fetched profile dict

    Returns:
        Formatted number string
    """
    if profile is None:
        profile = get_cached_profile()

    number_format = profile.get("number_format") or "International (Millions, Billions)"
    val = flt(value)

    if "Indian" in number_format:
        return _format_indian(val, "")
    elif "International" in number_format:
        return _format_international(val, "")
    else:
        return _format_plain(val, "")


# ─── Internal Formatters ─────────────────────────────────────────────────────

def _format_indian(value, symbol="₹"):
    """
    Format a number in Indian notation (Lakhs / Crores).
    Examples: ₹45.23 L, ₹2.15 Cr, ₹45,230
    """
    if value is None:
        return f"{symbol}0"
    val = flt(value)
    abs_val = abs(val)
    sign = "-" if val < 0 else ""

    if abs_val >= 1_00_00_000:  # 1 Crore = 10 million
        return f"{sign}{symbol}{abs_val / 1_00_00_000:.2f} Cr"
    elif abs_val >= 1_00_000:  # 1 Lakh = 100 thousand
        return f"{sign}{symbol}{abs_val / 1_00_000:.2f} L"
    elif abs_val >= 1_000:
        return f"{sign}{symbol}{abs_val:,.0f}"
    else:
        return f"{sign}{symbol}{abs_val:.2f}"


def _format_international(value, symbol="$"):
    """
    Format a number in International notation (K / M / B).
    Examples: $4.52M, $21.5B, $45.23K
    """
    if value is None:
        return f"{symbol}0"
    val = flt(value)
    abs_val = abs(val)
    sign = "-" if val < 0 else ""

    if abs_val >= 1_000_000_000:  # 1 Billion
        return f"{sign}{symbol}{abs_val / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000:  # 1 Million
        return f"{sign}{symbol}{abs_val / 1_000_000:.2f}M"
    elif abs_val >= 1_000:  # 1 Thousand
        return f"{sign}{symbol}{abs_val / 1_000:.2f}K"
    else:
        return f"{sign}{symbol}{abs_val:.2f}"


def _format_plain(value, symbol=""):
    """
    Format a number with standard comma grouping, no abbreviation.
    Examples: $4,523,000.00, 1,234,567
    """
    if value is None:
        return f"{symbol}0"
    val = flt(value)
    abs_val = abs(val)
    sign = "-" if val < 0 else ""

    if abs_val >= 1:
        return f"{sign}{symbol}{abs_val:,.2f}"
    else:
        return f"{sign}{symbol}{abs_val:.2f}"


# ─── Financial Year ──────────────────────────────────────────────────────────

def get_fy_dates(profile=None):
    """
    Calculate financial year dates based on profile.financial_year_start.

    Supports: "January" (Jan-Dec), "April" (Apr-Mar), "July" (Jul-Jun), "October" (Oct-Sep)

    Returns:
        dict with keys:
            fy_start (date): First day of current FY
            fy_end (date): Last day of current FY
            fy_label (str): e.g. "FY 2025-26" or "FY 2026"
            last_fy_start (date): First day of previous FY
            last_fy_end (date): Last day of previous FY
    """
    if profile is None:
        profile = get_cached_profile()

    fy_start_month_name = profile.get("financial_year_start") or "January"

    # Map month name to month number
    month_map = {
        "January": 1, "February": 2, "March": 3, "April": 4,
        "May": 5, "June": 6, "July": 7, "August": 8,
        "September": 9, "October": 10, "November": 11, "December": 12,
    }
    fy_start_month = month_map.get(fy_start_month_name, 1)

    today_date = getdate(today())

    # Determine which FY we're currently in
    if today_date.month >= fy_start_month:
        fy_start_year = today_date.year
    else:
        fy_start_year = today_date.year - 1

    fy_start = getdate(f"{fy_start_year}-{fy_start_month:02d}-01")

    # FY end = day before next FY start
    if fy_start_month == 1:
        fy_end = getdate(f"{fy_start_year}-12-31")
    else:
        fy_end_year = fy_start_year + 1
        fy_end_month = fy_start_month - 1
        fy_end = get_last_day(getdate(f"{fy_end_year}-{fy_end_month:02d}-01"))

    # Previous FY
    last_fy_start = getdate(f"{fy_start_year - 1}-{fy_start_month:02d}-01")
    if fy_start_month == 1:
        last_fy_end = getdate(f"{fy_start_year - 1}-12-31")
    else:
        last_fy_end_year = fy_start_year
        last_fy_end_month = fy_start_month - 1
        last_fy_end = get_last_day(getdate(f"{last_fy_end_year}-{last_fy_end_month:02d}-01"))

    # FY label
    if fy_start_month == 1:
        fy_label = f"FY {fy_start_year}"
    else:
        fy_label = f"FY {fy_start_year}-{(fy_start_year + 1) % 100:02d}"

    return {
        "fy_start": fy_start,
        "fy_end": fy_end,
        "fy_label": fy_label,
        "last_fy_start": last_fy_start,
        "last_fy_end": last_fy_end,
    }


# ─── Branding ────────────────────────────────────────────────────────────────

def get_trading_name(profile=None):
    """
    Get the company's trading/brand name for use in emails, alerts, reports.
    Falls back to "AskERP" if nothing configured.

    Returns:
        str: Company trading name
    """
    if profile is None:
        profile = get_cached_profile()

    return (
        profile.get("trading_name")
        or profile.get("company_name")
        or "AskERP"
    )


def get_report_filename_prefix(profile=None):
    """
    Get a filesystem-safe prefix for report filenames.
    Example: "My_Company" or "AskERP"
    """
    name = get_trading_name(profile)
    # Replace spaces and special chars with underscore
    safe_name = "".join(c if c.isalnum() else "_" for c in name)
    # Collapse multiple underscores
    while "__" in safe_name:
        safe_name = safe_name.replace("__", "_")
    return safe_name.strip("_")


# ─── Role Sets (from Settings) ───────────────────────────────────────────────

def get_role_sets():
    """
    Get executive, management role sets from AskERP Settings.
    These are configurable by the admin — not hardcoded.

    Always includes "System Manager" and "Administrator" in executive set
    (these are Frappe universals that exist on every installation).

    Returns:
        dict with keys:
            executive (set): Roles that get executive-tier treatment
            management (set): Roles that get management-tier treatment
    """
    settings = _get_cached_settings()

    exec_str = settings.get("executive_priority_roles") or "System Manager,Accounts Manager"
    mgr_str = settings.get("manager_priority_roles") or "Sales Manager,Purchase Manager,Stock Manager,Manufacturing Manager"

    exec_roles = {r.strip() for r in exec_str.split(",") if r.strip()}
    mgr_roles = {r.strip() for r in mgr_str.split(",") if r.strip()}

    # Frappe universals — always executive tier
    exec_roles.add("System Manager")
    exec_roles.add("Administrator")

    return {
        "executive": exec_roles,
        "management": mgr_roles,
    }


def get_prompt_tier(user_roles):
    """
    Determine the prompt tier for a user based on their roles.
    Reads role configuration from AskERP Settings (not hardcoded).

    Args:
        user_roles: list or set of role names

    Returns:
        str: "executive", "management", or "field"
    """
    role_set = set(user_roles)
    role_config = get_role_sets()

    if role_set & role_config["executive"]:
        return "executive"
    if role_set & role_config["management"]:
        return "management"
    return "field"


# ─── Number Format Rules for System Prompt ───────────────────────────────────

def get_time_context(profile=None):
    """
    Build comprehensive time context for the AI system prompt.
    Centralizes ALL date/FY/quarter/month logic so business_context.py
    doesn't need its own inline calculations.

    Uses profile.financial_year_start to determine FY boundaries.

    Returns:
        dict with keys:
            today (str): YYYY-MM-DD
            now_full_date (str): "Monday, 15 February 2026"
            current_month (str): "February 2026"
            current_month_num (str): "02"
            current_year (int): 2026
            month_start (str): YYYY-MM-DD
            last_month_label (str): "January 2026"
            last_month_start (str): YYYY-MM-DD
            last_month_end (str): YYYY-MM-DD
            fy_label (str): "FY 2025-26"
            fy_short (str): "2526"
            fy_start (str): YYYY-MM-DD
            fy_end (str): YYYY-MM-DD
            prev_fy_label (str): "FY 2024-25"
            prev_fy_start (str): YYYY-MM-DD
            fy_q (int): Quarter number (1-4)
            q_from (str): YYYY-MM-DD (quarter start)
            q_to (str): YYYY-MM-DD (quarter end)
            smly_start (str): YYYY-MM-DD (same month last year start)
            smly_end (str): YYYY-MM-DD (same month last year end)
    """
    from datetime import timedelta

    if profile is None:
        profile = get_cached_profile()

    now = now_datetime()
    today_str = today()
    today_date = getdate(today_str)

    # ─── Financial Year (from profile) ────────────────────────────────
    fy_data = get_fy_dates(profile)
    fy_start = fy_data["fy_start"]
    fy_end = fy_data["fy_end"]
    fy_label = fy_data["fy_label"]

    # Derive FY years for short label
    fy_start_year = fy_start.year
    fy_end_year = fy_end.year
    if fy_start.month == 1:
        fy_short = str(fy_start_year)[-2:] * 2  # "2626" for calendar year
    else:
        fy_short = f"{str(fy_start_year)[-2:]}{str(fy_end_year)[-2:]}"

    # Previous FY
    prev_fy_start = fy_data["last_fy_start"]
    prev_fy_label_parts = fy_label.replace("FY ", "").split("-")
    if len(prev_fy_label_parts) == 2:
        prev_fy_label = f"FY {fy_start_year - 1}-{str(fy_start_year)[-2:]}"
    else:
        prev_fy_label = f"FY {fy_start_year - 1}"

    # ─── Quarter Calculation (relative to FY start) ───────────────────
    fy_start_month = fy_start.month
    months_into_fy = (now.month - fy_start_month) % 12
    fy_q = (months_into_fy // 3) + 1

    # Quarter date ranges
    q_offset = (fy_q - 1) * 3
    q_start_m = ((fy_start_month - 1 + q_offset) % 12) + 1
    q_end_m = ((fy_start_month - 1 + q_offset + 2) % 12) + 1
    q_start_y = fy_start_year if q_start_m >= fy_start_month else fy_start_year + 1
    q_end_y = fy_start_year if q_end_m >= fy_start_month else fy_start_year + 1
    q_from = f"{q_start_y}-{q_start_m:02d}-01"
    q_to_date = get_last_day(getdate(f"{q_end_y}-{q_end_m:02d}-01"))
    q_to = str(q_to_date)

    # ─── Current Month ────────────────────────────────────────────────
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    current_month = now.strftime("%B %Y")
    current_month_num = now.strftime("%m")

    # ─── Last Month ──────────────────────────────────────────────────
    first_of_this_month = now.replace(day=1)
    last_day_prev = first_of_this_month - timedelta(days=1)
    first_of_prev = last_day_prev.replace(day=1)
    last_month_start = first_of_prev.strftime("%Y-%m-%d")
    last_month_end = last_day_prev.strftime("%Y-%m-%d")
    last_month_label = first_of_prev.strftime("%B %Y")

    # ─── Same Month Last Year (SMLY) ─────────────────────────────────
    smly_start = f"{now.year - 1}-{current_month_num}-01"
    try:
        smly_end = now.replace(year=now.year - 1).strftime("%Y-%m-%d")
    except ValueError:
        # Handle leap year edge case (Feb 29 → Feb 28)
        smly_end = f"{now.year - 1}-{current_month_num}-28"

    return {
        "today": today_str,
        "now_full_date": now.strftime("%A, %d %B %Y"),
        "current_month": current_month,
        "current_month_num": current_month_num,
        "current_year": now.year,
        "month_start": month_start,
        "last_month_label": last_month_label,
        "last_month_start": last_month_start,
        "last_month_end": last_month_end,
        "fy_label": fy_label,
        "fy_short": fy_short,
        "fy_start": str(fy_start),
        "fy_end": str(fy_end),
        "prev_fy_label": prev_fy_label,
        "prev_fy_start": str(prev_fy_start),
        "fy_q": fy_q,
        "q_from": q_from,
        "q_to": q_to,
        "smly_start": smly_start,
        "smly_end": smly_end,
    }


def get_number_format_prompt(profile=None):
    """
    Generate the number formatting instructions for the AI system prompt.
    Reads from profile instead of hardcoding Indian format.

    Returns:
        str: Formatting rules block for inclusion in system prompt
    """
    if profile is None:
        profile = get_cached_profile()

    number_format = profile.get("number_format") or "International (Millions, Billions)"
    currency_code = profile.get("currency") or "USD"
    symbol = get_currency_symbol(currency_code)
    uom = profile.get("unit_of_measure") or "Units"

    if "Indian" in number_format:
        return f"""## CURRENCY & NUMBER FORMATTING — MANDATORY

**ALL numbers MUST use Indian format. NEVER use Western notation.**

### Absolute Rules
1. **{symbol} symbol** for all currency
2. **Indian comma grouping:** last 3 digits, then groups of 2
   - ✅ {symbol}12,34,567 | ❌ {symbol}1,234,567
3. **Lakhs (L) and Crores (Cr)** for large numbers:
   - {symbol}1 Lakh = {symbol}1,00,000
   - {symbol}1 Crore = {symbol}1,00,00,000
4. **NEVER use Million, Billion, K, M, B** — always Lakhs and Crores
5. **Smart rounding:**
   - < {symbol}1 L → show full: {symbol}45,230
   - {symbol}1 L to {symbol}99 L → {symbol}X.XX L (2 decimals)
   - {symbol}1 Cr+ → {symbol}X.XX Cr
6. **Weights:** {uom}
7. **Percentages:** Always show 1-2 decimal places: 23.5%, 12.05%"""

    elif "International" in number_format:
        return f"""## CURRENCY & NUMBER FORMATTING — MANDATORY

### Formatting Rules
1. **{symbol} symbol** for all currency ({currency_code})
2. **Standard comma grouping:** thousands separator every 3 digits
   - ✅ {symbol}1,234,567 | ❌ {symbol}12,34,567
3. **For large numbers:** use K (thousands), M (millions), B (billions)
   - {symbol}45.23K, {symbol}2.15M, {symbol}1.05B
4. **Smart rounding:** round to appropriate precision for the context
5. **Units:** {uom}
6. **Percentages:** Always show 1-2 decimal places: 23.5%, 12.05%"""

    else:
        return f"""## CURRENCY & NUMBER FORMATTING — MANDATORY

### Formatting Rules
1. **{symbol} symbol** for all currency ({currency_code})
2. **Standard comma grouping:** thousands separator every 3 digits
3. **Show full numbers** — no abbreviation (K, M, B, Lakhs, Crores)
4. **Units:** {uom}
5. **Percentages:** Always show 1-2 decimal places"""
