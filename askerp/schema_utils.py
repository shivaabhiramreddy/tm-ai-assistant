"""
AskERP — Schema Utilities (Dynamic Schema Resolution Layer)
============================================================
Central module that provides schema-aware helpers for ALL AskERP modules.

Instead of hardcoding doctype names, field references, SQL patterns, or workflow
states, every module calls functions in this file which resolve dynamically from:

  1. Live ERPNext metadata  → frappe.get_meta(), frappe.db.exists()
  2. Active workflows       → Workflow doctype transitions
  3. AskERP Settings        → Admin-configurable overrides
  4. Bootstrap-safe defaults → Sensible fallbacks for fresh installs

This is the "layer only" architecture: the codebase is a generic framework
that adapts to ANY ERPNext installation — not just one specific setup.

Usage from other modules:
    from askerp.schema_utils import (
        resolve_financial_doctypes,
        resolve_pending_workflow_states,
        build_financial_summary_sql,
        build_key_doctypes_text,
        ...
    )

Created: 2026-02-15 (Hardcoded Dependency Removal Sprint)
"""

import json
import re
import time

import frappe


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL CACHE
# ═══════════════════════════════════════════════════════════════════════════════
# All resolution functions are cached for 5 minutes (300s) to avoid
# repeated DB lookups on every chat message. Cache is cleared when:
#   - Context Discovery runs (calls clear_schema_cache())
#   - AskERP Settings is saved (calls clear_schema_cache())
#   - TTL expires naturally

_schema_cache = {}
_cache_ts = 0
_CACHE_TTL = 300  # seconds


def _get_cached(key, builder_fn):
    """Module-level cache with TTL. Thread-safe via GIL."""
    global _schema_cache, _cache_ts
    now = time.time()
    if now - _cache_ts > _CACHE_TTL:
        _schema_cache = {}
        _cache_ts = now
    if key not in _schema_cache:
        _schema_cache[key] = builder_fn()
    return _schema_cache[key]


def clear_schema_cache():
    """Force-clear the schema cache. Called after context discovery or settings save."""
    global _schema_cache, _cache_ts
    _schema_cache = {}
    _cache_ts = 0


# ═══════════════════════════════════════════════════════════════════════════════
# CORE RESOLUTION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def doctype_exists(doctype):
    """Check if a doctype exists in this ERPNext installation."""
    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def get_table_name(doctype):
    """Convert doctype name to SQL table name: 'Sales Invoice' → '`tabSales Invoice`'."""
    return f"`tab{doctype}`"


def resolve_financial_doctypes():
    """
    Returns a mapping of purpose → doctype name for all financial/transactional
    doctypes. Each entry is verified to exist in the current ERPNext installation.

    Returns dict like:
        {
            "sales_invoice": "Sales Invoice",
            "purchase_invoice": "Purchase Invoice",
            "payment_entry": "Payment Entry",
            "stock_bin": "Bin",
            ...
        }

    Modules call this instead of hardcoding doctype names.
    """
    def _build():
        # Standard ERPNext doctype mapping — covers all common modules
        candidates = {
            "sales_invoice": "Sales Invoice",
            "sales_invoice_item": "Sales Invoice Item",
            "purchase_invoice": "Purchase Invoice",
            "payment_entry": "Payment Entry",
            "stock_bin": "Bin",
            "stock_entry": "Stock Entry",
            "journal_entry": "Journal Entry",
            "sales_order": "Sales Order",
            "purchase_order": "Purchase Order",
            "delivery_note": "Delivery Note",
            "purchase_receipt": "Purchase Receipt",
            "customer": "Customer",
            "supplier": "Supplier",
            "item": "Item",
            "warehouse": "Warehouse",
            "employee": "Employee",
            "leave_allocation": "Leave Allocation",
            "leave_application": "Leave Application",
            "gl_entry": "GL Entry",
            "stock_ledger_entry": "Stock Ledger Entry",
            "work_order": "Work Order",
            "bom": "BOM",
        }
        # Only include doctypes that actually exist in this installation
        return {purpose: dt for purpose, dt in candidates.items() if doctype_exists(dt)}

    return _get_cached("financial_doctypes", _build)


def resolve_pending_workflow_states():
    """
    Dynamically discover ALL active workflows and their "pending" states.

    Returns: {doctype: [list of pending state names]}
    Example:
        {
            "Sales Order": ["Pending for Approval"],
            "Payment Proposal": ["Pending for Verification", "Pending for Approval"],
        }

    Used by briefing.py, default_tools.py, and plan cache instead of
    hardcoding "Pending for Approval" strings.
    """
    def _build():
        result = {}
        try:
            workflows = frappe.get_all(
                "Workflow",
                filters={"is_active": 1},
                fields=["name", "document_type"],
            )
            for wf in workflows:
                states = frappe.get_all(
                    "Workflow Document State",
                    filters={"parent": wf.name},
                    fields=["state", "doc_status"],
                )
                # Identify "pending" states: docstatus=0 states whose name
                # contains keywords indicating they're awaiting action
                _PENDING_KEYWORDS = ("pending", "waiting", "review", "verification", "submitted")
                pending = []
                for s in states:
                    state_lower = s.state.lower()
                    if int(s.doc_status or 0) == 0 and any(kw in state_lower for kw in _PENDING_KEYWORDS):
                        pending.append(s.state)
                if pending:
                    result[wf.document_type] = pending
        except Exception:
            pass
        return result

    return _get_cached("pending_workflow_states", _build)


def resolve_draft_allowed_doctypes():
    """
    Get the set of doctypes that the AI can create as drafts.
    Reads from AskERP Settings JSON field if configured, else uses verified defaults.
    """
    def _build():
        # Check AskERP Settings for admin-configurable override
        try:
            from askerp.providers import get_settings
            settings = get_settings()
            if settings:
                custom = settings.get("draft_allowed_doctypes")
                if custom and isinstance(custom, str):
                    try:
                        parsed = json.loads(custom)
                        if isinstance(parsed, list) and parsed:
                            # Verify each configured doctype exists
                            return {dt for dt in parsed if doctype_exists(dt)}
                    except (json.JSONDecodeError, TypeError):
                        pass
        except Exception:
            pass

        # Bootstrap defaults — verified against live installation
        defaults = {
            "Sales Order", "Sales Invoice", "Purchase Order",
            "Payment Entry", "Stock Entry", "Journal Entry",
        }
        return {dt for dt in defaults if doctype_exists(dt)}

    return _get_cached("draft_allowed_doctypes", _build)


def resolve_mandatory_fields(doctype):
    """
    Get mandatory fields for a doctype from live ERPNext metadata.
    Returns list of mandatory fieldnames (excluding system fields like naming_series).
    """
    try:
        meta = frappe.get_meta(doctype)
        skip = {"naming_series", "amended_from", "name", "docstatus", "doctype"}
        return [
            f.fieldname for f in meta.fields
            if f.reqd and f.fieldname not in skip
        ]
    except Exception:
        return []


def resolve_core_doctypes():
    """
    Returns the set of core ERPNext transactional doctypes for cache invalidation.
    Only includes doctypes that exist in the current installation.
    """
    def _build():
        candidates = [
            "Sales Invoice", "Sales Order", "Purchase Invoice", "Purchase Order",
            "Payment Entry", "Stock Entry", "Delivery Note", "Purchase Receipt",
            "Customer", "Supplier", "Item", "Stock Ledger Entry", "GL Entry",
            "Journal Entry", "Work Order", "BOM",
        ]
        return {dt for dt in candidates if doctype_exists(dt)}

    return _get_cached("core_doctypes", _build)


def resolve_known_doctypes_map():
    """
    Returns {lowercase_name: canonical_name} for all doctypes the cache tracks.
    Used by query_cache.py to extract doctype references from tool inputs.
    """
    def _build():
        core = resolve_core_doctypes()
        return {dt.lower(): dt for dt in core}

    return _get_cached("known_doctypes_map", _build)


# ═══════════════════════════════════════════════════════════════════════════════
# SQL GENERATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_financial_summary_sql(company, from_date, to_date):
    """
    Build the 3 financial summary SQL queries dynamically.
    Returns dict with keys 'si', 'pi', 'pe' — each containing {sql, params}.
    Missing doctypes are omitted (caller handles gracefully).
    """
    fin = resolve_financial_doctypes()
    result = {}

    # BATCH 1: Sales Invoice metrics
    si_dt = fin.get("sales_invoice")
    if si_dt:
        table = get_table_name(si_dt)
        result["si"] = {
            "sql": f"""
                SELECT
                    COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN grand_total ELSE 0 END), 0) as total_revenue,
                    COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN net_total ELSE 0 END), 0) as net_revenue,
                    SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as invoice_count,
                    COALESCE(SUM(CASE WHEN is_return=1 AND posting_date BETWEEN %s AND %s THEN ABS(grand_total) ELSE 0 END), 0) as total_returns,
                    SUM(CASE WHEN is_return=1 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as return_count,
                    COALESCE(SUM(CASE WHEN outstanding_amount > 0 THEN outstanding_amount ELSE 0 END), 0) as total_receivable
                FROM {table}
                WHERE company=%s AND docstatus=1
            """,
            "params": (
                from_date, to_date, from_date, to_date, from_date, to_date,
                from_date, to_date, from_date, to_date, company,
            ),
        }

    # BATCH 2: Purchase Invoice metrics
    pi_dt = fin.get("purchase_invoice")
    if pi_dt:
        table = get_table_name(pi_dt)
        result["pi"] = {
            "sql": f"""
                SELECT
                    COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN grand_total ELSE 0 END), 0) as total_purchases,
                    SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as purchase_count,
                    COALESCE(SUM(CASE WHEN outstanding_amount > 0 THEN outstanding_amount ELSE 0 END), 0) as total_payable
                FROM {table}
                WHERE company=%s AND docstatus=1
            """,
            "params": (from_date, to_date, from_date, to_date, company),
        }

    # BATCH 3: Payment Entry metrics
    pe_dt = fin.get("payment_entry")
    if pe_dt:
        table = get_table_name(pe_dt)
        result["pe"] = {
            "sql": f"""
                SELECT
                    COALESCE(SUM(CASE WHEN payment_type='Receive' THEN paid_amount ELSE 0 END), 0) as total_collections,
                    SUM(CASE WHEN payment_type='Receive' THEN 1 ELSE 0 END) as collection_count,
                    COALESCE(SUM(CASE WHEN payment_type='Pay' THEN paid_amount ELSE 0 END), 0) as total_payments,
                    SUM(CASE WHEN payment_type='Pay' THEN 1 ELSE 0 END) as payment_count
                FROM {table}
                WHERE company=%s AND docstatus=1
                AND posting_date BETWEEN %s AND %s
            """,
            "params": (company, from_date, to_date),
        }

    return result


def build_briefing_queries():
    """
    Build SQL queries for the morning briefing dynamically.
    Returns dict with keys: 'yesterday_sales', 'collections', 'receivables'.
    Each value is a SQL string (caller passes the date parameter).
    """
    fin = resolve_financial_doctypes()
    result = {}

    si_dt = fin.get("sales_invoice")
    if si_dt:
        table = get_table_name(si_dt)
        result["yesterday_sales"] = f"""
            SELECT
                COUNT(*) as invoice_count,
                COALESCE(SUM(grand_total), 0) as total_revenue,
                COALESCE(SUM(outstanding_amount), 0) as new_outstanding
            FROM {table}
            WHERE posting_date = %s AND docstatus = 1
        """
        result["receivables"] = f"""
            SELECT COALESCE(SUM(outstanding_amount), 0) as total
            FROM {table}
            WHERE outstanding_amount > 0 AND docstatus = 1
        """

    pe_dt = fin.get("payment_entry")
    if pe_dt:
        table = get_table_name(pe_dt)
        result["collections"] = f"""
            SELECT
                COUNT(*) as payment_count,
                COALESCE(SUM(paid_amount), 0) as total_collected
            FROM {table}
            WHERE posting_date = %s AND docstatus = 1
            AND payment_type = 'Receive'
        """

    return result


def build_pending_approval_counts():
    """
    Build pending approval counts dynamically from active workflows.
    Returns list of (doctype_label, count) tuples for display.
    """
    pending_states = resolve_pending_workflow_states()
    counts = []

    for dt, states in sorted(pending_states.items()):
        try:
            total = 0
            for state in states:
                total += frappe.db.count(dt, {"workflow_state": state, "docstatus": 0})
            if total > 0:
                # Pluralize doctype name for display
                label = dt + "s" if not dt.endswith("s") else dt
                counts.append((label, total))
        except Exception:
            continue

    return counts


def build_plan_cache_hints():
    """
    Build SQL hints for the plan cache dynamically from discovered schema.
    Returns dict of {regex_pattern: {plan, tools, query_hint/description}}.
    """
    fin = resolve_financial_doctypes()
    hints = {}

    # Business pulse — always available via financial summary tool
    hints[r"(business\s+)?pulse|dashboard|overview|briefing"] = {
        "plan": "financial_summary",
        "tools": ["get_financial_summary"],
        "description": "Pre-cached: business pulse via financial summary tool",
    }

    # Receivables — needs Sales Invoice
    si_dt = fin.get("sales_invoice")
    if si_dt:
        table = get_table_name(si_dt)
        hints[r"(outstanding\s+)?receivables?\s*(aging)?"] = {
            "plan": "receivables_query",
            "tools": ["run_sql_query"],
            "query_hint": (
                f"SELECT customer, outstanding_amount FROM {table} "
                "WHERE outstanding_amount > 0 AND docstatus=1 "
                "ORDER BY outstanding_amount DESC LIMIT 20"
            ),
        }
        hints[r"(today|yesterday)['s]*\s+sales(\s+summary)?"] = {
            "plan": "daily_sales",
            "tools": ["run_sql_query"],
            "query_hint": (
                f"SELECT SUM(grand_total) as total, COUNT(*) as count "
                f"FROM {table} WHERE posting_date='{{date}}' AND docstatus=1"
            ),
        }

    # Approvals — dynamic from workflows
    pending_states = resolve_pending_workflow_states()
    if pending_states:
        dt_list = ", ".join(sorted(pending_states.keys()))
        hints[r"(pending\s+)?approvals?"] = {
            "plan": "approvals_query",
            "tools": ["query_records"],
            "query_hint": f"Check {dt_list} with workflow_state containing 'Pending'",
        }

    # DSO — always available if financial summary tool exists
    hints[r"(dso|days?\s+sales?\s+outstanding)"] = {
        "plan": "dso_calculation",
        "tools": ["get_financial_summary"],
        "description": "DSO is included in the financial summary tool output",
    }

    # Low stock — needs Bin doctype
    bin_dt = fin.get("stock_bin")
    if bin_dt:
        table = get_table_name(bin_dt)
        hints[r"(low\s+stock|reorder|stock\s+alert)"] = {
            "plan": "low_stock",
            "tools": ["run_sql_query"],
            "query_hint": (
                f"SELECT item_code, item_name, actual_qty, reorder_level "
                f"FROM {table} WHERE actual_qty < reorder_level AND reorder_level > 0"
            ),
        }

    return hints


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT / PROMPT GENERATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_ambiguous_options():
    """
    Build clarification options for the ambiguity engine dynamically
    based on what modules/doctypes are actually available.
    Returns list of (regex_pattern, clarification_question, options_list) tuples.
    """
    fin = resolve_financial_doctypes()

    # Generic "show me something" options
    generic_options = []
    if "sales_invoice" in fin:
        generic_options.append("Today's sales summary")
    if "sales_invoice" in fin:
        generic_options.append("Outstanding receivables")
    if "stock_bin" in fin:
        generic_options.append("Inventory status")
    generic_options.append("Business pulse")

    # "How is the business" options
    business_options = []
    if "sales_invoice" in fin:
        business_options.append("Revenue & sales today")
    if "payment_entry" in fin:
        business_options.append("Cash flow & payments")
    if "stock_bin" in fin:
        business_options.append("Inventory levels")
    business_options.append("Full business dashboard")

    # "Report" options
    report_options = []
    if "sales_invoice" in fin:
        report_options.append("Sales report this month")
    report_options.append("Financial summary")
    if "stock_bin" in fin or "item" in fin:
        report_options.append("Inventory valuation")
    if "sales_invoice" in fin:
        report_options.append("Receivables aging")

    # "Compare" options
    compare_options = []
    if "sales_invoice" in fin:
        compare_options.append("This month vs last month sales")
        compare_options.append("This quarter vs same quarter last year")
    compare_options.append("Territory-wise comparison")

    # "Status/update" options
    status_options = []
    if resolve_pending_workflow_states():
        status_options.append("Pending approvals")
    if "sales_order" in fin:
        status_options.append("Today's orders")
    if "delivery_note" in fin:
        status_options.append("Dispatch status")
    if "payment_entry" in fin:
        status_options.append("Payment collections")
    if not status_options:
        status_options = ["Recent activity", "Document summary"]

    return [
        (r"^(show|get|give|tell)\s+(me\s+)?(something|stuff|things|info|data|details)\b",
         "What specifically would you like to see?",
         generic_options[:4]),
        (r"^(what|how)\s+(about|is)\s+(the\s+)?(business|company|status|situation)\b",
         "Which aspect of the business?",
         business_options[:4]),
        (r"^report\b",
         "What kind of report would you like?",
         report_options[:4]),
        (r"^(compare|comparison)\b(?!.*\b(with|vs|to|and|between)\b)",
         "Compare what with what?",
         compare_options[:3]),
        (r"^(update|status)\b$",
         "Status of what?",
         status_options[:4]),
    ]


def build_key_doctypes_text():
    """
    Generate the KEY DOCTYPES section for prompt templates dynamically.
    Returns formatted text block showing available doctypes and their key fields,
    verified against the live ERPNext metadata.
    """
    fin = resolve_financial_doctypes()
    lines = []

    # Define display order and candidate fields for each purpose
    doctype_display = [
        ("sales_order", "SO", ["customer", "grand_total", "transaction_date", "status", "territory"]),
        ("sales_invoice", "SI", ["customer", "grand_total", "outstanding_amount", "posting_date", "is_return"]),
        ("delivery_note", "DN", ["customer", "grand_total", "posting_date", "status", "total_net_weight"]),
        ("purchase_order", "PO", ["supplier", "grand_total", "transaction_date", "status"]),
        ("purchase_invoice", "PI", ["supplier", "grand_total", "outstanding_amount", "posting_date"]),
        ("customer", None, ["customer_name", "customer_group", "territory"]),
        ("item", None, ["item_code", "item_name", "item_group", "stock_uom", "standard_rate"]),
        ("stock_bin", "Bin", ["item_code", "warehouse", "actual_qty"]),
        ("payment_entry", "PE", ["party", "paid_amount", "posting_date", "payment_type"]),
    ]

    for purpose, abbr, candidate_fields in doctype_display:
        dt = fin.get(purpose)
        if not dt:
            continue
        # Verify which fields actually exist on this doctype
        try:
            meta = frappe.get_meta(dt)
            valid_fields = {f.fieldname for f in meta.fields}
            existing_fields = [f for f in candidate_fields if f in valid_fields]
            if not existing_fields:
                existing_fields = candidate_fields[:3]  # Show candidates as fallback
        except Exception:
            existing_fields = candidate_fields

        label = f"**{dt}" + (f" ({abbr})" if abbr else "") + ":**"
        extra = ""
        if purpose == "stock_bin":
            extra = " (real-time stock)"
        lines.append(f"- {label} {', '.join(existing_fields)}{extra}")

    if not lines:
        return "_No transactional doctypes discovered yet. Run Context Discovery to populate._"

    return "\n".join(lines)


def build_financial_metrics_text():
    """
    Generate financial metric hints for prompt templates dynamically.
    Replaces hardcoded references like 'Sales Invoice grand_total' with
    doctype names resolved from the current installation.
    """
    fin = resolve_financial_doctypes()
    lines = []

    si = fin.get("sales_invoice")
    if si:
        lines.append(f"- Revenue: {si} grand_total (docstatus=1, is_return=0)")
    if si or fin.get("purchase_invoice"):
        si_label = si or "Sales Invoice"
        pi_label = fin.get("purchase_invoice", "Purchase Invoice")
        lines.append(f"- Outstanding: Sum of outstanding_amount from {si_label}/{pi_label}")
    pe = fin.get("payment_entry")
    if pe:
        lines.append(f"- Collections: {pe} paid_amount (payment_type=Receive)")
    lines.append("- DSO = Outstanding Receivables ÷ (Revenue ÷ 365)")
    lines.append("- Collection Rate = Collections ÷ Revenue × 100")
    lines.append("- Aging: 0-30 / 30-60 / 60-90 / 90+ days")

    return "\n".join(lines) if lines else "- Financial metrics will be available after Context Discovery"


def build_fallback_schema_text():
    """
    Generate the fallback schema text for when context discovery hasn't run yet.
    Uses live ERPNext metadata instead of hardcoded doctype/field references.
    """
    fin = resolve_financial_doctypes()

    lines = [
        "## DATABASE SCHEMA — Not Yet Discovered",
        "_Run context discovery to auto-detect your database schema. "
        "Until then, using basic ERPNext conventions._",
        "",
        "**SQL Table Convention:** ERPNext tables are named `tab<DocType>`.",
    ]

    # Build examples from what actually exists
    examples = []
    for purpose in ["sales_invoice", "payment_entry", "purchase_invoice"]:
        dt = fin.get(purpose)
        if dt:
            examples.append(f"{dt} → `tab{dt}`")
    if examples:
        lines.append(f"Example: {', '.join(examples[:2])}.")

    lines.extend([
        "",
        "**Submitted documents:** Filter `docstatus=1` for submitted (confirmed) records.",
        "`docstatus=0` = Draft, `docstatus=2` = Cancelled.",
        "",
        "### Available Doctypes (use run_sql_query to discover actual fields)",
    ])

    # Dynamic doctype listing — only show what exists
    doctype_info = [
        ("sales_invoice", "SI", "customer, grand_total, outstanding_amount, posting_date, status, company"),
        ("purchase_invoice", "PI", "supplier, grand_total, outstanding_amount, posting_date, status, company"),
        ("payment_entry", "PE", "party_type, party, paid_amount, posting_date, payment_type, company"),
        ("stock_entry", "SE", "stock_entry_type, posting_date, company, total_amount"),
        ("journal_entry", "JE", "posting_date, total_debit, total_credit, company"),
        ("customer", None, "customer_name, customer_group, territory"),
        ("supplier", None, "supplier_name, supplier_group"),
        ("item", None, "item_code, item_name, item_group, stock_uom"),
        ("warehouse", None, "name, warehouse_name, company"),
        ("stock_bin", "Bin", "item_code, warehouse, actual_qty — real-time stock levels"),
    ]
    for purpose, abbr, fields in doctype_info:
        dt = fin.get(purpose)
        if dt:
            label = f"**{dt}" + (f" ({abbr})" if abbr else "") + ":**"
            lines.append(f"- {label} {fields}")

    lines.extend([
        "",
        "### Best Practices for Queries",
        "- Always filter `docstatus=1` for submitted documents",
        "- Always exclude returns for revenue: `is_return=0`",
        "- Use company filter when showing company-specific data",
    ])

    # Dynamic best practices based on what exists
    if "sales_invoice" in fin:
        si = fin["sales_invoice"]
        lines.append(f'- For "sales": query {si} (not Sales Order) unless user says "orders"')
        lines.append(f'- For "outstanding": query `outstanding_amount` field on {si}')
    if "stock_bin" in fin:
        bin_dt = fin["stock_bin"]
        lines.append(f'- For "stock": use `tab{bin_dt}` for real-time quantities')
    if "payment_entry" in fin:
        pe = fin["payment_entry"]
        lines.append(f'- For "collections": {pe} with `payment_type=\'Receive\'`')

    lines.extend([
        "",
        "_Note: Run the context discovery engine to auto-populate the full schema "
        "with all your doctypes, fields, reports, and SQL patterns._",
    ])

    return "\n".join(lines)


def build_sql_tool_description():
    """
    Build the description for the run_sql_query tool dynamically.
    Includes table name examples from doctypes that actually exist.
    """
    fin = resolve_financial_doctypes()

    base = (
        "Execute a READ-ONLY SQL query against the ERPNext database. "
        "Use this for complex analytics that need JOINs, subqueries, window functions, "
        "or calculations that can't be done with simple filters. "
        "ONLY SELECT statements are allowed. Table names use backtick-quoted "
        "format like `tab<DocType Name>`. All tables are prefixed with 'tab'. "
    )

    # Build examples from actual doctypes
    examples = []
    for purpose in ["sales_invoice", "payment_entry", "customer", "item"]:
        dt = fin.get(purpose)
        if dt:
            examples.append(f"`tab{dt}` for {dt}")
    if examples:
        base += "Examples: " + ", ".join(examples[:3]) + "."

    return base


def build_sql_tool_input_description():
    """Build the input field description for run_sql_query with dynamic examples."""
    fin = resolve_financial_doctypes()

    desc = "SQL SELECT query. Table names use `tabDoctype` format. "
    si_dt = fin.get("sales_invoice")
    if si_dt:
        table = get_table_name(si_dt)
        desc += (
            f"Example: SELECT customer_name, SUM(grand_total) as total "
            f"FROM {table} WHERE docstatus=1 GROUP BY customer_name"
        )
    return desc


def build_error_recovery_text():
    """
    Build the TOOL ERROR RECOVERY section for the system prompt.
    Uses dynamic table name examples instead of hardcoded ones.
    """
    fin = resolve_financial_doctypes()

    # Build a representative table example
    table_example = "`tabSales Invoice`"  # safe default
    si_dt = fin.get("sales_invoice")
    if si_dt:
        table_example = get_table_name(si_dt)

    return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 🔄 TOOL ERROR RECOVERY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If a tool call returns an error, DO NOT give up. Follow this recovery protocol:

1. **Field not found / column error**: The field name may be wrong. Try using `run_sql_query` with `SELECT *` on a small sample (LIMIT 3) to discover actual column names.
2. **No data returned**: Try broadening the date range, removing filters, or checking if the doctype name is correct (remember: use backtick-quoted table names like {table_example}).
3. **Permission denied**: Tell the user you don't have access to that data. Do NOT retry with different params.
4. **SQL syntax error**: Fix the SQL and retry. Common mistakes: missing backticks on table names, wrong date format (use YYYY-MM-DD), forgetting `docstatus=1`.
5. **Timeout error**: The query is too heavy. Simplify it — add stricter date filters, reduce JOINs, add LIMIT.
6. **Filter parsing error**: If `query_records` fails on filters, switch to `run_sql_query` with explicit SQL WHERE clause instead.

IMPORTANT: You have up to 8 tool rounds. If the first attempt fails, you MUST try a different approach. Never tell the user "I encountered an error" without first attempting recovery. Users should see answers, not error messages."""


def build_pending_approvals_sql():
    """
    Build a UNION ALL SQL query for the pending_approvals_summary default tool.
    Dynamically includes only doctypes that have active workflows with pending states.
    Returns the SQL string, or None if no workflows exist.
    """
    pending_states = resolve_pending_workflow_states()
    if not pending_states:
        return None

    parts = []
    for dt, states in sorted(pending_states.items()):
        table = get_table_name(dt)
        state_list = ", ".join(f"'{s}'" for s in states)
        parts.append(
            f"SELECT '{dt}' as document_type, COUNT(*) as pending_count "
            f"FROM {table} WHERE workflow_state IN ({state_list}) AND docstatus = 0"
        )

    return " UNION ALL ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULT TOOLS GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

def build_default_tools():
    """
    Generate default tool definitions dynamically based on the available schema.
    Only includes tools whose target doctypes exist in this installation.

    Returns list of tool definition dicts (same format as DEFAULT_CUSTOM_TOOLS).
    Called by install.py during after_install and by regenerate functions.
    """
    fin = resolve_financial_doctypes()
    tools = []

    # ─── 1. Check Customer Outstanding ────────────────────────────────
    si_dt = fin.get("sales_invoice")
    if si_dt:
        table = get_table_name(si_dt)
        tools.append({
            "tool_name": "check_customer_outstanding",
            "display_name": "Check Customer Outstanding",
            "description": (
                "Look up the total outstanding receivable amount for a specific customer. "
                "Returns the sum of unpaid and partially paid invoice balances. "
                "Use when the user asks about a customer's dues, outstanding, receivables, or balance."
            ),
            "category": "Sales",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  customer_name, "
                "  COUNT(name) as invoice_count, "
                "  SUM(grand_total) as total_invoiced, "
                "  SUM(outstanding_amount) as total_outstanding, "
                "  MIN(posting_date) as oldest_invoice_date, "
                "  DATEDIFF(CURDATE(), MIN(posting_date)) as max_aging_days "
                f"FROM {table} "
                "WHERE customer_name LIKE %(customer_name)s "
                "  AND docstatus = 1 "
                "  AND outstanding_amount > 0 "
                "GROUP BY customer_name"
            ),
            "query_limit": 10,
            "output_format": "Summary",
            "parameters": [
                {
                    "param_name": "customer_name",
                    "param_type": "String",
                    "param_description": "Customer name (or partial name with % wildcards)",
                    "required": 1,
                },
            ],
        })

    # ─── 2. Top Selling Items ─────────────────────────────────────────
    si_item_dt = fin.get("sales_invoice_item")
    if si_dt and si_item_dt:
        si_table = get_table_name(si_dt)
        sii_table = get_table_name(si_item_dt)
        tools.append({
            "tool_name": "top_selling_items",
            "display_name": "Top Selling Items",
            "description": (
                "Get the best-selling items ranked by quantity or revenue for a given date range. "
                "Use when the user asks about top products, best sellers, most popular items, "
                "or sales rankings."
            ),
            "category": "Sales",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  sii.item_name, "
                "  sii.item_code, "
                "  SUM(sii.qty) as total_qty, "
                "  SUM(sii.amount) as total_revenue, "
                "  sii.uom, "
                "  COUNT(DISTINCT si.name) as invoice_count "
                f"FROM {sii_table} sii "
                f"JOIN {si_table} si ON si.name = sii.parent "
                "WHERE si.docstatus = 1 "
                "  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s "
                "GROUP BY sii.item_code, sii.item_name, sii.uom "
                "ORDER BY total_revenue DESC "
                "LIMIT 20"
            ),
            "query_limit": 20,
            "output_format": "Table",
            "parameters": [
                {
                    "param_name": "from_date",
                    "param_type": "Date",
                    "param_description": "Start date for the period (YYYY-MM-DD)",
                    "required": 1,
                },
                {
                    "param_name": "to_date",
                    "param_type": "Date",
                    "param_description": "End date for the period (YYYY-MM-DD)",
                    "required": 1,
                },
            ],
        })

    # ─── 3. Stock Status ──────────────────────────────────────────────
    bin_dt = fin.get("stock_bin")
    if bin_dt:
        table = get_table_name(bin_dt)
        tools.append({
            "tool_name": "stock_status",
            "display_name": "Stock Status",
            "description": (
                "Check the current stock level for a specific item across all warehouses. "
                "Returns actual qty, reserved qty, and available qty per warehouse. "
                "Use when the user asks about stock levels, availability, inventory, "
                "or 'how much do we have'."
            ),
            "category": "Inventory",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  b.warehouse, "
                "  b.actual_qty, "
                "  b.reserved_qty, "
                "  (b.actual_qty - b.reserved_qty) as available_qty, "
                "  b.stock_uom, "
                "  b.valuation_rate, "
                "  ROUND(b.actual_qty * b.valuation_rate, 2) as stock_value "
                f"FROM {table} b "
                "WHERE b.item_code = %(item_code)s "
                "  AND b.actual_qty != 0 "
                "ORDER BY b.actual_qty DESC"
            ),
            "query_limit": 100,
            "output_format": "Table",
            "parameters": [
                {
                    "param_name": "item_code",
                    "param_type": "String",
                    "param_description": "The item code to check stock for",
                    "required": 1,
                },
            ],
        })

    # ─── 4. Pending Approvals Summary ─────────────────────────────────
    approvals_sql = build_pending_approvals_sql()
    if approvals_sql:
        tools.append({
            "tool_name": "pending_approvals_summary",
            "display_name": "Pending Approvals Summary",
            "description": (
                "Get a count of all pending approval documents across all workflow-enabled doctypes. "
                "Use when the user asks about approvals, pending items, or 'what needs my attention'."
            ),
            "category": "Custom",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": approvals_sql,
            "query_limit": 10,
            "output_format": "Table",
            "parameters": [],
        })

    # ─── 5. Overdue Invoices ──────────────────────────────────────────
    if si_dt:
        table = get_table_name(si_dt)
        tools.append({
            "tool_name": "overdue_invoices",
            "display_name": "Overdue Sales Invoices",
            "description": (
                "List all overdue (past due date) unpaid sales invoices with aging in days. "
                "Use when the user asks about overdue payments, aging receivables, "
                "late payments, or delinquent accounts."
            ),
            "category": "Finance",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  name, customer_name, posting_date, due_date, "
                "  grand_total, outstanding_amount, "
                "  DATEDIFF(CURDATE(), due_date) as days_overdue, "
                "  territory "
                f"FROM {table} "
                "WHERE docstatus = 1 "
                "  AND outstanding_amount > 0 "
                "  AND due_date < CURDATE() "
                "ORDER BY days_overdue DESC "
                "LIMIT %(max_results)s"
            ),
            "query_limit": 100,
            "output_format": "Table",
            "parameters": [
                {
                    "param_name": "max_results",
                    "param_type": "Number",
                    "param_description": "Maximum number of results to return (default 50)",
                    "required": 0,
                    "default_value": "50",
                },
            ],
        })

    # ─── 6. Supplier Performance ──────────────────────────────────────
    pi_dt = fin.get("purchase_invoice")
    if pi_dt:
        table = get_table_name(pi_dt)
        tools.append({
            "tool_name": "supplier_performance",
            "display_name": "Supplier Performance",
            "description": (
                "Analyze a supplier's performance: total purchases, invoice count, "
                "average order value, and payment status. "
                "Use when the user asks about supplier evaluation, vendor performance, "
                "or purchase history with a supplier."
            ),
            "category": "Purchase",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  supplier_name, "
                "  COUNT(name) as total_invoices, "
                "  SUM(grand_total) as total_purchased, "
                "  ROUND(AVG(grand_total), 2) as avg_invoice_value, "
                "  SUM(outstanding_amount) as total_outstanding, "
                "  MIN(posting_date) as first_invoice_date, "
                "  MAX(posting_date) as latest_invoice_date "
                f"FROM {table} "
                "WHERE supplier_name LIKE %(supplier_name)s "
                "  AND docstatus = 1 "
                "GROUP BY supplier_name"
            ),
            "query_limit": 10,
            "output_format": "Summary",
            "parameters": [
                {
                    "param_name": "supplier_name",
                    "param_type": "String",
                    "param_description": "Supplier name (or partial with % wildcards)",
                    "required": 1,
                },
            ],
        })

    # ─── 7. Daily Sales Summary ───────────────────────────────────────
    pe_dt = fin.get("payment_entry")
    so_dt = fin.get("sales_order")
    if si_dt:
        si_table = get_table_name(si_dt)
        parts = [
            (
                "SELECT "
                "  'Revenue' as metric, "
                "  COALESCE(SUM(grand_total), 0) as value, "
                "  COUNT(name) as count "
                f"FROM {si_table} "
                "WHERE posting_date = %(target_date)s AND docstatus = 1"
            ),
        ]
        if so_dt:
            so_table = get_table_name(so_dt)
            parts.append(
                "SELECT "
                "  'Orders', "
                "  COALESCE(SUM(grand_total), 0), "
                "  COUNT(name) "
                f"FROM {so_table} "
                "WHERE transaction_date = %(target_date)s AND docstatus = 1"
            )
        if pe_dt:
            pe_table = get_table_name(pe_dt)
            parts.append(
                "SELECT "
                "  'Collections', "
                "  COALESCE(SUM(paid_amount), 0), "
                "  COUNT(name) "
                f"FROM {pe_table} "
                "WHERE posting_date = %(target_date)s AND docstatus = 1 "
                "  AND payment_type = 'Receive'"
            )

        tools.append({
            "tool_name": "daily_sales_summary",
            "display_name": "Daily Sales Summary",
            "description": (
                "Get a summary of sales activity for a specific date: revenue, order count, "
                "collections received, and new customers. "
                "Use when the user asks about daily sales, today's numbers, "
                "or 'how did we do on [date]'."
            ),
            "category": "Sales",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": " UNION ALL ".join(parts),
            "query_limit": 10,
            "output_format": "Table",
            "parameters": [
                {
                    "param_name": "target_date",
                    "param_type": "Date",
                    "param_description": "The date to get the summary for (YYYY-MM-DD)",
                    "required": 1,
                },
            ],
        })

    # ─── 8. Employee Leave Balance ────────────────────────────────────
    la_dt = fin.get("leave_allocation")
    lapp_dt = fin.get("leave_application")
    if la_dt and lapp_dt:
        la_table = get_table_name(la_dt)
        lapp_table = get_table_name(lapp_dt)
        tools.append({
            "tool_name": "employee_leave_balance",
            "display_name": "Employee Leave Balance",
            "description": (
                "Check remaining leave balance for an employee across all leave types. "
                "Use when the user asks about leave balance, remaining holidays, "
                "or vacation days for an employee."
            ),
            "category": "HR",
            "enabled": 1,
            "is_read_only": 1,
            "requires_approval": 0,
            "query_type": "Raw SQL",
            "query_sql": (
                "SELECT "
                "  la.employee_name, "
                "  la.leave_type, "
                "  la.total_leaves_allocated, "
                "  COALESCE(("
                f"    SELECT SUM(total_leave_days) FROM {lapp_table} "
                "    WHERE employee = la.employee AND leave_type = la.leave_type "
                "    AND docstatus = 1 AND status = 'Approved'"
                "  ), 0) as leaves_taken, "
                "  la.total_leaves_allocated - COALESCE(("
                f"    SELECT SUM(total_leave_days) FROM {lapp_table} "
                "    WHERE employee = la.employee AND leave_type = la.leave_type "
                "    AND docstatus = 1 AND status = 'Approved'"
                "  ), 0) as balance "
                f"FROM {la_table} la "
                "WHERE la.employee_name LIKE %(employee_name)s "
                "  AND la.docstatus = 1 "
                "  AND la.from_date <= CURDATE() "
                "  AND la.to_date >= CURDATE() "
                "ORDER BY la.leave_type"
            ),
            "query_limit": 20,
            "output_format": "Table",
            "parameters": [
                {
                    "param_name": "employee_name",
                    "param_type": "String",
                    "param_description": "Employee name (or partial with % wildcards)",
                    "required": 1,
                },
            ],
        })

    return tools
