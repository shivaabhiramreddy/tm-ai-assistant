"""
AskERP — AI Engine v6.0
==================================
Core AI logic with dynamic multi-provider model selection.
Executes ERPNext data queries via tool_use and returns
executive-grade formatted responses.

v6.0 changes (Model Revamp):
- All model config from AskERP Model doctype (no hardcoded keys/URLs)
- Provider abstraction: Anthropic, Google, OpenAI, Custom via providers.py
- Dynamic tier routing: AskERP Settings tier_1/2/3 → model docs
- Cost tracking per query in AI Usage Log
- Fallback chain: primary model → fallback model → friendly message
- Token budgets from model doc (configurable per model in frontend)

v5.0: Smart routing, image/file support, chart tool
v4.0: Response streaming, Redis tokens
v3.4: Prompt caching (~90% savings)
v3.3: SQL safety, financial summary optimization
"""

import json
import re
import frappe


# ─── Configuration (Dynamic — from AskERP Settings + AskERP Model) ──────────
# All model selection, API keys, token budgets, and tool round limits
# are now read from the AskERP Model and AskERP Settings doctypes.
# No hardcoded model strings, API keys, or URLs remain in this file.

# Fallback defaults used ONLY if AskERP Settings is not yet configured
_FALLBACK_MAX_TOOL_ROUNDS = 8
_FALLBACK_TOKEN_BUDGETS = {
    "flash": 5_000,
    "simple": 15_000,
    "medium": 35_000,
    "complex": 60_000,
}


# ─── Smart Query Routing (Hybrid Classifier v2.0) ───────────────────────────
# Two-stage classification: regex fast-path → LLM fallback.
# Patterns live in classification_patterns.py (easy to extend).
# Hybrid logic lives in classifier.py (regex first, then Tier 1 LLM).
from askerp.classifier import classify_query  # noqa: F401 — re-exported for backward compat


# ─── Clarification Engine (Sprint 6B) ────────────────────────────────────────
# Classifies queries as CLEAR, LIKELY_CLEAR, or AMBIGUOUS.
# For ambiguous queries, returns clarification options as tappable chips.

# Patterns that indicate the query is AMBIGUOUS (needs clarification)
_AMBIGUOUS_PATTERNS = [
    (r"^(show|get|give|tell)\s+(me\s+)?(something|stuff|things|info|data|details)\b",
     "What specifically would you like to see?",
     ["Today's sales summary", "Outstanding receivables", "Inventory status", "Business pulse"]),
    (r"^(what|how)\s+(about|is)\s+(the\s+)?(business|company|status|situation)\b",
     "Which aspect of the business?",
     ["Revenue & sales today", "Cash flow & payments", "Inventory levels", "Full business dashboard"]),
    (r"^report\b",
     "What kind of report would you like?",
     ["Sales report this month", "Financial summary", "Inventory valuation", "Receivables aging"]),
    (r"^(compare|comparison)\b(?!.*\b(with|vs|to|and|between)\b)",
     "Compare what with what?",
     ["This month vs last month sales", "This quarter vs same quarter last year", "Territory-wise comparison"]),
    (r"^(update|status)\b$",
     "Status of what?",
     ["Pending approvals", "Today's orders", "Dispatch status", "Payment collections"]),
]

_ambiguous_re = [(re.compile(p, re.IGNORECASE), q, opts) for p, q, opts in _AMBIGUOUS_PATTERNS]


def classify_and_clarify(question):
    """
    Sprint 6B: Check if a query is ambiguous and needs clarification.

    Returns:
        dict with:
        - needs_clarification (bool): True if query is ambiguous
        - clarification_question (str): Question to ask the user
        - options (list): Tappable option labels
        - confidence (str): "clear", "likely_clear", or "ambiguous"
    """
    q = question.strip()

    # Very short queries (< 10 chars) that aren't greetings are likely ambiguous
    if len(q) < 10 and not re.match(r"^(hi|hello|hey|thanks|bye|ok|yes|no)\b", q, re.IGNORECASE):
        return {
            "needs_clarification": True,
            "clarification_question": "Could you be more specific?",
            "options": ["Today's business pulse", "Outstanding receivables", "Pending approvals", "Sales this month"],
            "confidence": "ambiguous",
        }

    # Check against known ambiguous patterns
    for pat, clarify_q, options in _ambiguous_re:
        if pat.search(q):
            return {
                "needs_clarification": True,
                "clarification_question": clarify_q,
                "options": options,
                "confidence": "ambiguous",
            }

    # Query has enough specificity — let it through
    return {
        "needs_clarification": False,
        "clarification_question": None,
        "options": [],
        "confidence": "clear",
    }


# ─── Plan Cache (Sprint 6B) ─────────────────────────────────────────────────
# Caches execution plans for common query patterns.
# If a query matches a cached pattern, skip the planning LLM call and reuse.

_PLAN_CACHE = {
    # Pattern → pre-built tool sequence (avoids an LLM round for common queries)
    r"(business\s+)?pulse|dashboard|overview|briefing": {
        "plan": "financial_summary",
        "tools": ["get_financial_summary"],
        "description": "Pre-cached: business pulse via financial summary tool",
    },
    r"(outstanding\s+)?receivables?\s*(aging)?": {
        "plan": "receivables_query",
        "tools": ["run_sql_query"],
        "query_hint": "SELECT customer, outstanding_amount FROM `tabSales Invoice` WHERE outstanding_amount > 0 AND docstatus=1 ORDER BY outstanding_amount DESC LIMIT 20",
    },
    r"(pending\s+)?approvals?": {
        "plan": "approvals_query",
        "tools": ["query_records"],
        "query_hint": "Check Sales Order, Sales Invoice, Purchase Receipt, Payment Proposal with workflow_state containing 'Pending'",
    },
    r"(today|yesterday)['s]*\s+sales(\s+summary)?": {
        "plan": "daily_sales",
        "tools": ["run_sql_query"],
        "query_hint": "SELECT SUM(grand_total) as total, COUNT(*) as count FROM `tabSales Invoice` WHERE posting_date='{date}' AND docstatus=1",
    },
    r"(dso|days?\s+sales?\s+outstanding)": {
        "plan": "dso_calculation",
        "tools": ["get_financial_summary"],
        "description": "DSO is included in the financial summary tool output",
    },
    r"(low\s+stock|reorder|stock\s+alert)": {
        "plan": "low_stock",
        "tools": ["run_sql_query"],
        "query_hint": "SELECT item_code, item_name, actual_qty, reorder_level FROM `tabBin` WHERE actual_qty < reorder_level AND reorder_level > 0",
    },
}

_plan_cache_re = [(re.compile(p, re.IGNORECASE), v) for p, v in _PLAN_CACHE.items()]


def get_cached_plan(question):
    """
    Sprint 6B: Check if a query matches a cached execution plan.
    Returns the cached plan dict if matched, None otherwise.

    The cached plan provides hints to Claude about which tools to use,
    reducing unnecessary planning tokens.
    """
    q = question.strip()
    for pat, plan in _plan_cache_re:
        if pat.search(q):
            return plan
    return None


def get_api_key():
    """
    DEPRECATED — Kept for backward compatibility with imports from other modules.
    New code should use providers.call_model() which reads keys from AskERP Model doc.
    Falls back to site_config for legacy use during migration.
    """
    # Try reading from the tier_3 model first
    try:
        from .providers import get_model_for_tier
        model_doc = get_model_for_tier("tier_3")
        if model_doc:
            key = model_doc.get_password("api_key")
            if key:
                return key
    except Exception:
        pass
    # Fallback to site_config
    key = frappe.conf.get("anthropic_api_key", "")
    if not key:
        frappe.throw("No AI model API key configured. Please set up models in AskERP Settings.")
    return key


def get_model():
    """
    DEPRECATED — Kept for backward compatibility.
    Returns the model_id of the tier_3 (Premium) model.
    New code should use providers.get_model_for_tier().
    """
    try:
        from .providers import get_model_for_tier
        model_doc = get_model_for_tier("tier_3")
        if model_doc:
            return model_doc.model_id
    except Exception:
        pass
    return frappe.conf.get("ai_model", "claude-opus-4-6")


# ─── Claude API Client (DEPRECATED — use providers.call_model) ────────────

def call_claude(messages, system_prompt, tools=None, model_override=None):
    """
    DEPRECATED — Kept for backward compatibility with any direct callers.
    New code should use providers.call_model(model_doc, ...) directly.

    Resolves model_override (string model_id or model doc) to a AskERP Model doc,
    then delegates to providers.call_model().
    """
    from .providers import get_model_for_tier, call_model as provider_call

    model_doc = None

    # model_override can be a model_id string, a AskERP Model doc name, or a doc object
    if model_override:
        if hasattr(model_override, "model_id"):
            # Already a model doc object
            model_doc = model_override
        else:
            try:
                model_doc = frappe.get_cached_doc("AskERP Model", model_override)
            except frappe.DoesNotExistError:
                # Try finding by model_id field
                name = frappe.db.get_value("AskERP Model", {"model_id": model_override, "enabled": 1})
                if name:
                    model_doc = frappe.get_cached_doc("AskERP Model", name)

    # Fall back to tier_3 (Premium) model
    if not model_doc:
        model_doc = get_model_for_tier("tier_3")

    if not model_doc:
        return {
            "content": [{"type": "text", "text": "No AI model is configured. Please ask your admin to set up AskERP Settings."}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
        }

    result = provider_call(model_doc, messages, system_prompt, tools)
    if result:
        return result

    # providers.call_model returned None — all retries exhausted
    return {
        "content": [{"type": "text", "text": "I'm temporarily unable to process your request. Please try again in a moment."}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
    }


# ─── ERPNext Tool Definitions ────────────────────────────────────────────────

ERPNEXT_TOOLS = [
    {
        "name": "query_records",
        "description": (
            "Query ERPNext records. Fetch lists of documents like Sales Invoices, "
            "Customers, Items, Stock Entries, etc. Supports filtering, field selection, "
            "ordering, grouping, and aggregation (SUM, COUNT, AVG). "
            "All queries respect the logged-in user's permissions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "ERPNext doctype (e.g. 'Sales Invoice', 'Customer', 'Item')"
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to return. Use field names or aggregations: "
                        "'SUM(grand_total) as total', 'COUNT(name) as count', 'AVG(grand_total) as avg'. "
                        "Use ['*'] for all fields."
                    )
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Filter criteria. Simple: {\"status\": \"Paid\"}. "
                        "With operators: {\"grand_total\": [\">\", 10000], "
                        "\"posting_date\": [\"between\", [\"2025-04-01\", \"2026-03-31\"]]}. "
                        "Operators: =, !=, >, <, >=, <=, like, not like, in, not in, between, is."
                    )
                },
                "order_by": {"type": "string", "description": "e.g. 'grand_total desc'"},
                "group_by": {"type": "string", "description": "e.g. 'customer_name' or 'territory'"},
                "limit": {"type": "integer", "description": "Max records (default 20, max 200)"},
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "count_records",
        "description": "Count total records matching criteria for any ERPNext doctype.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string", "description": "ERPNext doctype to count"},
                "filters": {"type": "object", "description": "Filter criteria"},
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "get_document",
        "description": "Get full details of a specific ERPNext document by its ID/name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string"},
                "name": {"type": "string", "description": "Document name/ID"},
                "fields": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Specific fields (optional, returns all if omitted)"
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "run_report",
        "description": (
            "Run a built-in ERPNext report. Key reports: "
            "'Accounts Receivable' (aging), 'Accounts Payable', 'General Ledger', "
            "'Stock Balance', 'Sales Analytics', 'Gross Profit', "
            "'Item-wise Sales Register', 'Purchase Analytics', "
            "'Customer Ledger Summary', 'Supplier Ledger Summary', "
            "'Balance Sheet', 'Profit and Loss Statement', 'Cash Flow'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_name": {"type": "string", "description": "Name of the ERPNext report"},
                "filters": {"type": "object", "description": "Report-specific filters"},
            },
            "required": ["report_name"],
        },
    },
    {
        "name": "run_sql_query",
        "description": (
            "Execute a READ-ONLY SQL query against the ERPNext database. "
            "Use this for complex analytics that need JOINs, subqueries, window functions, "
            "or calculations that can't be done with simple filters. "
            "ONLY SELECT statements are allowed. Table names use backtick-quoted "
            "format like `tabSales Invoice`, `tabCustomer`, `tabItem`. "
            "All tables are prefixed with 'tab'. Examples: "
            "`tabSales Invoice` for Sales Invoice, `tabPayment Entry` for Payment Entry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "SQL SELECT query. Table names use `tabDoctype` format. "
                        "Example: SELECT customer_name, SUM(grand_total) as total "
                        "FROM `tabSales Invoice` WHERE docstatus=1 GROUP BY customer_name"
                    )
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_financial_summary",
        "description": (
            "Get a pre-computed financial summary for a company and period. "
            "Returns: total revenue, total expenses, net profit, gross margin, "
            "total receivables, total payables, cash balance, key ratios. "
            "Use this for quick financial health checks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {
                    "type": "string",
                    "description": "Company name (e.g. 'Fertile Green Industries Private Limited')"
                },
                "from_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "to_date": {"type": "string", "description": "End date YYYY-MM-DD"},
            },
            "required": ["company"],
        },
    },
    {
        "name": "compare_periods",
        "description": (
            "Automatically compare two time periods for any metric. "
            "Returns absolute values, difference, and percentage change. "
            "Use for month-over-month, quarter-over-quarter, year-over-year comparisons."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string", "description": "Doctype to query"},
                "field": {"type": "string", "description": "Field to aggregate (e.g. 'grand_total')"},
                "aggregation": {
                    "type": "string", "enum": ["SUM", "COUNT", "AVG"],
                    "description": "Aggregation function"
                },
                "period1_from": {"type": "string", "description": "Period 1 start (YYYY-MM-DD)"},
                "period1_to": {"type": "string", "description": "Period 1 end (YYYY-MM-DD)"},
                "period2_from": {"type": "string", "description": "Period 2 start (YYYY-MM-DD)"},
                "period2_to": {"type": "string", "description": "Period 2 end (YYYY-MM-DD)"},
                "extra_filters": {"type": "object", "description": "Additional filters"},
                "group_by": {"type": "string", "description": "Optional grouping field"},
            },
            "required": ["doctype", "field", "aggregation", "period1_from", "period1_to", "period2_from", "period2_to"],
        },
    },
    {
        "name": "create_alert",
        "description": (
            "Create a business alert that monitors a condition and notifies the user. "
            "Example: 'Alert me when receivables exceed 50 lakhs' or "
            "'Notify me if daily sales drop below 1 lakh'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_name": {"type": "string", "description": "Short name for the alert"},
                "description": {"type": "string", "description": "What this alert monitors"},
                "doctype": {"type": "string", "description": "ERPNext doctype to monitor"},
                "field": {"type": "string", "description": "Field to check (e.g. 'grand_total')"},
                "aggregation": {"type": "string", "enum": ["SUM", "COUNT", "AVG", "MAX", "MIN"]},
                "filters": {"type": "object", "description": "Filters for the query"},
                "operator": {"type": "string", "enum": [">", "<", ">=", "<=", "=", "!="]},
                "threshold": {"type": "number", "description": "Trigger value"},
                "frequency": {"type": "string", "enum": ["hourly", "daily", "weekly"]},
            },
            "required": ["alert_name", "description", "doctype", "field", "aggregation", "operator", "threshold", "frequency"],
        },
    },
    {
        "name": "list_alerts",
        "description": "List all active alerts for the current user.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "delete_alert",
        "description": "Delete/deactivate an alert by its name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alert_name": {"type": "string", "description": "Name/ID of the alert to delete"},
            },
            "required": ["alert_name"],
        },
    },
    {
        "name": "export_pdf",
        "description": (
            "Generate a branded PDF report from your analysis. Use this when the user asks for "
            "a report, PDF, document, or anything they can download/share. "
            "Pass a clear title and the full content in markdown format "
            "(headers, tables, bold, bullet lists all work). Returns a download URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Report title (e.g. 'Receivables Aging Report — Feb 2026')"},
                "content": {
                    "type": "string",
                    "description": (
                        "Full report content in markdown. Include headers (##), tables (|col|col|), "
                        "bold (**text**), bullet lists (- item). This gets converted to a styled PDF."
                    )
                },
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "export_excel",
        "description": (
            "Generate a branded Excel spreadsheet from tabular data. Use this when the user asks for "
            "an Excel file, spreadsheet, or downloadable data table. "
            "Pass structured data as a list of row objects. Returns a download URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Sheet/report title"},
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of row objects. Each object is one row. "
                        "Example: [{\"customer\": \"ABC\", \"amount\": 50000}, {\"customer\": \"XYZ\", \"amount\": 30000}]"
                    )
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional column order. If omitted, auto-detected from data keys."
                },
            },
            "required": ["title", "data"],
        },
    },
    {
        "name": "generate_chart",
        "description": (
            "Generate a visual chart that will be rendered inline in the mobile app. "
            "Use this when the user asks to 'show me a chart', 'visualize', 'graph', or when "
            "presenting comparative data that benefits from visual representation. "
            "Supported types: bar (vertical), horizontal_bar, line. "
            "The chart is rendered natively in the app — no image generation needed. "
            "IMPORTANT: Include the chart JSON in your response wrapped in a ```chart code block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["bar", "horizontal_bar", "line"],
                    "description": "Chart type. Use horizontal_bar for many labels, bar for few, line for trends.",
                },
                "title": {"type": "string", "description": "Chart title (e.g. 'Monthly Sales Trend')"},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Category labels (x-axis for bar, y-axis for horizontal_bar)",
                },
                "datasets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "data": {"type": "array", "items": {"type": "number"}},
                            "color": {"type": "string", "description": "Hex color (optional, default green)"},
                        },
                        "required": ["label", "data"],
                    },
                    "description": "One or more data series",
                },
            },
            "required": ["type", "title", "labels", "datasets"],
        },
    },
    # ─── Write Action Tools (Sprint 8) ─────────────────────────────────────
    {
        "name": "create_draft_document",
        "description": (
            "Create a DRAFT document in ERPNext. The document will NOT be submitted — "
            "it will be saved as Draft (docstatus=0) for the user to review and submit manually. "
            "Supported doctypes: Sales Order, Sales Invoice, Purchase Order, Payment Entry, Stock Entry, Journal Entry. "
            "ALWAYS confirm with the user before creating any document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "The ERPNext doctype to create",
                    "enum": ["Sales Order", "Sales Invoice", "Purchase Order",
                             "Payment Entry", "Stock Entry", "Journal Entry"],
                },
                "values": {
                    "type": "object",
                    "description": "Field values for the document. Must include all mandatory fields for the doctype.",
                },
            },
            "required": ["doctype", "values"],
        },
    },
    {
        "name": "execute_workflow_action",
        "description": (
            "Execute a workflow action on a document (e.g., Approve, Reject, Submit for Approval). "
            "ALWAYS confirm with the user before executing any workflow action. "
            "Only works on documents that have ERPNext workflows configured."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {"type": "string", "description": "The ERPNext doctype"},
                "docname": {"type": "string", "description": "The document name/ID"},
                "action": {"type": "string", "description": "The workflow action to execute (e.g., 'Approve', 'Reject')"},
            },
            "required": ["doctype", "docname", "action"],
        },
    },
    {
        "name": "schedule_report",
        "description": (
            "Schedule a recurring report to be auto-generated and emailed. "
            "The user specifies what report they want, how often, and who should receive it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_name": {"type": "string", "description": "Human-friendly name for the report"},
                "report_query": {"type": "string", "description": "Natural language query that will be run to generate the report"},
                "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "How often to generate"},
                "export_format": {"type": "string", "enum": ["pdf", "excel"], "description": "Output format"},
                "email_recipients": {"type": "string", "description": "Comma-separated email addresses (optional, owner always included)"},
            },
            "required": ["report_name", "report_query", "frequency"],
        },
    },
    {
        "name": "save_user_preference",
        "description": (
            "Save a user preference that the AI will remember across sessions. "
            "Examples: preferred currency format, favorite metrics, default date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Preference key (e.g., 'currency_format', 'default_company')"},
                "value": {"type": "string", "description": "Preference value"},
            },
            "required": ["key", "value"],
        },
    },
]


# ─── Dynamic Tool Loading (Built-in + Custom Tools) ──────────────────────────

# Set of built-in tool names for fast dispatch lookup
_BUILTIN_TOOL_NAMES = {t["name"] for t in ERPNEXT_TOOLS}


def get_all_tools(user=None):
    """
    Get the combined list of built-in tools + enabled custom tools.
    Custom tools are fetched from AskERP Custom Tool doctype and
    filtered by the user's roles. This is what gets sent to Claude.
    """
    all_tools = list(ERPNEXT_TOOLS)  # Copy the built-in list

    try:
        from askerp.custom_tools import get_clean_tool_definitions
        custom_tools = get_clean_tool_definitions(user)
        if custom_tools:
            all_tools.extend(custom_tools)
    except Exception as e:
        # Custom tools are optional — don't break the AI if something fails
        frappe.logger("askerp").warning(
            f"Failed to load custom tools: {str(e)}"
        )

    return all_tools


# ─── Tool Execution ─────────────────────────────────────────────────────────

def execute_tool(tool_name, tool_input, user):
    """Execute an ERPNext tool call. All queries run as the specified user.
    Phase 6.1: Checks Redis cache first for read-only tools."""

    # Phase 6.1: Check cache before executing
    try:
        from .query_cache import get_cached_result, set_cached_result
        cached = get_cached_result(tool_name, tool_input)
        if cached is not None:
            return cached
    except Exception:
        pass  # Cache is optional — proceed without it

    original_user = frappe.session.user
    try:
        frappe.set_user(user)
        result = _dispatch_tool(tool_name, tool_input, user, original_user)

        # Phase 6.1: Cache the result for future identical queries
        try:
            from .query_cache import set_cached_result as _cache_set
            _cache_set(tool_name, tool_input, result)
        except Exception:
            pass  # Cache write is non-critical

        return result

    except frappe.PermissionError:
        return {"error": "You don't have permission to access this data."}
    except Exception as e:
        frappe.log_error(title=f"AI Tool Error: {tool_name}", message=str(e))
        return {"error": f"Query failed: {str(e)[:200]}"}
    finally:
        frappe.set_user(original_user)


def _try_precomputed_metrics(tool_input):
    """
    Phase 6.2: Try to assemble a financial summary from pre-computed metrics.
    Returns a result dict if enough metrics are cached, None otherwise.
    Falls back gracefully — if pre-computation isn't set up or metrics are
    stale (>2 hours old), returns None so the live query runs instead.
    """
    try:
        from .precompute import get_cached_metrics
        company = tool_input.get("company") if tool_input else None
        metrics = get_cached_metrics(company=company)
        if not metrics or len(metrics) < 3:
            return None  # Not enough cached data — fall through to live query

        # Check freshness — if oldest metric is >2 hours old, skip
        from frappe.utils import now_datetime, time_diff_in_seconds
        for m in metrics:
            if m.get("last_computed"):
                age = time_diff_in_seconds(now_datetime(), m["last_computed"])
                if age > 7200:  # 2 hours
                    return None

        # Build summary from cached metrics
        summary = {"_from_precompute": True, "metrics": {}}
        for m in metrics:
            if not m.get("error"):
                summary["metrics"][m["metric_name"]] = {
                    "label": m["label"],
                    "value": m["value"],
                    "formatted": m["formatted"],
                    "category": m["category"],
                }
        return summary
    except Exception:
        return None  # Pre-compute not available — proceed with live query


def _dispatch_tool(tool_name, tool_input, user, original_user):
    """Internal tool dispatcher. Separated from execute_tool for cache integration."""

    # Phase 6.2: Check pre-computed metrics first for financial_summary
    if tool_name == "get_financial_summary":
        precomputed = _try_precomputed_metrics(tool_input)
        if precomputed:
            return precomputed

    if tool_name == "query_records":
        return _exec_query_records(tool_input)
    elif tool_name == "count_records":
        return _exec_count_records(tool_input)
    elif tool_name == "get_document":
        return _exec_get_document(tool_input)
    elif tool_name == "run_report":
        return _exec_run_report(tool_input)
    elif tool_name == "run_sql_query":
        return _exec_sql_query(tool_input)
    elif tool_name == "get_financial_summary":
        return _exec_financial_summary(tool_input)
    elif tool_name == "compare_periods":
        return _exec_compare_periods(tool_input)
    elif tool_name == "create_alert":
        return _exec_create_alert(tool_input, user)
    elif tool_name == "list_alerts":
        return _exec_list_alerts(user)
    elif tool_name == "delete_alert":
        return _exec_delete_alert(tool_input, user)
    elif tool_name == "export_pdf":
        return _exec_export_pdf(tool_input)
    elif tool_name == "export_excel":
        return _exec_export_excel(tool_input)
    elif tool_name == "generate_chart":
        return _exec_generate_chart(tool_input)
    # Sprint 8: Write action tools
    elif tool_name == "create_draft_document":
        return _exec_create_draft(tool_input, user)
    elif tool_name == "execute_workflow_action":
        return _exec_workflow_action(tool_input, user)
    elif tool_name == "schedule_report":
        return _exec_schedule_report(tool_input, user)
    elif tool_name == "save_user_preference":
        return _exec_save_preference(tool_input, user)
    else:
        # Check if it's a custom tool (Phase 4: No-Code Tool Builder)
        if tool_name not in _BUILTIN_TOOL_NAMES:
            try:
                from askerp.custom_tools import execute_custom_tool
                # execute_custom_tool handles its own user context
                frappe.set_user(original_user)  # Reset before custom tool (it sets its own)
                return execute_custom_tool(tool_name, tool_input, user)
            except Exception as e:
                frappe.log_error(
                    title=f"Custom Tool Error: {tool_name}",
                    message=str(e)
                )
                return {"error": f"Custom tool error: {str(e)[:200]}"}

        return {"error": f"Unknown tool: {tool_name}"}


def _exec_query_records(params):
    doctype = params["doctype"]
    fields = params.get("fields", ["name"])
    filters = _parse_filters(params.get("filters", {}))
    order_by = params.get("order_by", "modified desc")
    group_by = params.get("group_by", "")
    limit = min(params.get("limit", 20), 200)

    result = frappe.get_list(
        doctype, fields=fields, filters=filters,
        order_by=order_by, group_by=group_by,
        limit_page_length=limit, ignore_ifnull=True,
    )
    return {"data": result, "count": len(result), "doctype": doctype}


def _exec_count_records(params):
    doctype = params["doctype"]
    filters = _parse_filters(params.get("filters", {}))
    count = frappe.db.count(doctype, filters=filters)
    return {"count": count, "doctype": doctype}


def _exec_get_document(params):
    doctype = params["doctype"]
    name = params["name"]
    fields = params.get("fields")

    doc = frappe.get_doc(doctype, name)
    if fields:
        result = {f: doc.get(f) for f in fields if doc.get(f) is not None}
    else:
        skip = {"docstatus", "idx", "owner", "modified_by", "creation",
                "modified", "doctype", "_user_tags", "_comments", "_assign", "_liked_by"}
        result = {k: v for k, v in doc.as_dict().items()
                  if k not in skip and v is not None and not k.startswith("_")}
    return {"document": result, "doctype": doctype, "name": name}


def _exec_run_report(params):
    report_name = params["report_name"]
    filters = params.get("filters", {})

    result = frappe.call(
        "frappe.desk.query_report.run",
        report_name=report_name, filters=filters,
        ignore_prepared_report=True,
    )
    columns = result.get("columns", [])
    data = result.get("result", [])[:100]
    return {
        "report": report_name, "columns": columns, "data": data,
        "total_rows": len(result.get("result", [])),
        "truncated": len(result.get("result", [])) > 100,
    }


def _exec_sql_query(params):
    """Execute a read-only SQL query with safety checks."""
    query = params["query"].strip()

    # Safety: only allow SELECT
    query_upper = query.upper().lstrip()
    if not query_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed. No INSERT, UPDATE, DELETE, DROP, ALTER, or CREATE."}

    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE", "EXEC"]
    for kw in dangerous:
        # Check for dangerous keywords that aren't inside quotes
        if f" {kw} " in f" {query_upper} " or query_upper.startswith(kw):
            return {"error": f"Dangerous keyword '{kw}' detected. Only read-only SELECT queries allowed."}

    # Block access to sensitive tables
    sensitive_tables = [
        "tabUser", "tab__Auth", "tabUser Permission", "tabOAuth",
        "tabAPI Key", "tabToken", "tabSession",
    ]
    for tbl in sensitive_tables:
        if tbl.lower() in query.lower():
            return {"error": f"Access to '{tbl}' is restricted for security reasons."}

    # Auto-append LIMIT if not present (prevent runaway queries)
    if "LIMIT" not in query_upper:
        query = query.rstrip(";") + " LIMIT 5000"

    try:
        # Execute with a 30-second timeout to prevent expensive queries
        # Frappe's db.sql runs in the current transaction context
        frappe.db.sql("SET SESSION MAX_EXECUTION_TIME = 30000")  # 30s in ms (MariaDB)
        result = frappe.db.sql(query, as_dict=True)
        frappe.db.sql("SET SESSION MAX_EXECUTION_TIME = 0")  # Reset to default

        # Return max 200 rows to the AI
        truncated = len(result) > 200
        data = result[:200]
        return {"data": data, "count": len(data), "total_rows": len(result), "truncated": truncated}
    except Exception as e:
        error_str = str(e)[:200]
        # Reset timeout on error too
        try:
            frappe.db.sql("SET SESSION MAX_EXECUTION_TIME = 0")
        except Exception:
            pass
        return {"error": f"SQL error: {error_str}"}


def _exec_financial_summary(params):
    """
    Get a comprehensive financial summary for a company and period.
    Optimized: 8 sequential queries → 3 batched queries (SI + PI + PE combined).
    """
    company = params["company"]
    today = frappe.utils.today()
    from_date = params.get("from_date", frappe.utils.get_first_day(today).strftime("%Y-%m-%d"))
    to_date = params.get("to_date", today)

    summary = {}

    # BATCH 1: All Sales Invoice metrics in ONE query (revenue + returns + receivables)
    si_data = frappe.db.sql("""
        SELECT
            COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN grand_total ELSE 0 END), 0) as total_revenue,
            COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN net_total ELSE 0 END), 0) as net_revenue,
            SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as invoice_count,
            COALESCE(SUM(CASE WHEN is_return=1 AND posting_date BETWEEN %s AND %s THEN ABS(grand_total) ELSE 0 END), 0) as total_returns,
            SUM(CASE WHEN is_return=1 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as return_count,
            COALESCE(SUM(CASE WHEN outstanding_amount > 0 THEN outstanding_amount ELSE 0 END), 0) as total_receivable
        FROM `tabSales Invoice`
        WHERE company=%s AND docstatus=1
    """, (from_date, to_date, from_date, to_date, from_date, to_date,
          from_date, to_date, from_date, to_date, company), as_dict=True)

    si = si_data[0] if si_data else {}
    summary["revenue"] = {
        "total_revenue": si.get("total_revenue", 0),
        "net_revenue": si.get("net_revenue", 0),
        "invoice_count": si.get("invoice_count", 0),
    }
    summary["returns"] = {
        "total_returns": si.get("total_returns", 0),
        "return_count": si.get("return_count", 0),
    }
    summary["receivables"] = {"total_receivable": si.get("total_receivable", 0)}

    # BATCH 2: All Purchase Invoice metrics in ONE query (purchases + payables)
    pi_data = frappe.db.sql("""
        SELECT
            COALESCE(SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN grand_total ELSE 0 END), 0) as total_purchases,
            SUM(CASE WHEN is_return=0 AND posting_date BETWEEN %s AND %s THEN 1 ELSE 0 END) as purchase_count,
            COALESCE(SUM(CASE WHEN outstanding_amount > 0 THEN outstanding_amount ELSE 0 END), 0) as total_payable
        FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1
    """, (from_date, to_date, from_date, to_date, company), as_dict=True)

    pi = pi_data[0] if pi_data else {}
    summary["purchases"] = {
        "total_purchases": pi.get("total_purchases", 0),
        "purchase_count": pi.get("purchase_count", 0),
    }
    summary["payables"] = {"total_payable": pi.get("total_payable", 0)}

    # BATCH 3: All Payment Entry metrics in ONE query (collections + payments made)
    pe_data = frappe.db.sql("""
        SELECT
            COALESCE(SUM(CASE WHEN payment_type='Receive' THEN paid_amount ELSE 0 END), 0) as total_collections,
            SUM(CASE WHEN payment_type='Receive' THEN 1 ELSE 0 END) as collection_count,
            COALESCE(SUM(CASE WHEN payment_type='Pay' THEN paid_amount ELSE 0 END), 0) as total_payments,
            SUM(CASE WHEN payment_type='Pay' THEN 1 ELSE 0 END) as payment_count
        FROM `tabPayment Entry`
        WHERE company=%s AND docstatus=1
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)

    pe = pe_data[0] if pe_data else {}
    summary["collections"] = {
        "total_collections": pe.get("total_collections", 0),
        "collection_count": pe.get("collection_count", 0),
    }
    summary["payments_made"] = {
        "total_payments": pe.get("total_payments", 0),
        "payment_count": pe.get("payment_count", 0),
    }

    # Derived metrics
    total_rev = float(summary["revenue"].get("total_revenue", 0))
    total_pur = float(summary["purchases"].get("total_purchases", 0))

    summary["derived"] = {
        "gross_profit": total_rev - total_pur,
        "gross_margin_pct": round(((total_rev - total_pur) / total_rev * 100), 2) if total_rev > 0 else 0,
        "net_working_capital": float(summary["receivables"].get("total_receivable", 0)) - float(summary["payables"].get("total_payable", 0)),
        "collection_efficiency_pct": round(
            float(summary["collections"].get("total_collections", 0)) / total_rev * 100, 2
        ) if total_rev > 0 else 0,
    }

    summary["period"] = {"from_date": from_date, "to_date": to_date, "company": company}
    return summary


def _exec_compare_periods(params):
    """Compare a metric across two time periods with safety validation."""
    doctype = params["doctype"]
    field = params["field"]
    agg = params["aggregation"]
    p1_from = params["period1_from"]
    p1_to = params["period1_to"]
    p2_from = params["period2_from"]
    p2_to = params["period2_to"]
    extra = _parse_filters(params.get("extra_filters", {}))
    group_by = params.get("group_by", "")

    # Validate field names — only allow safe alphanumeric + underscore identifiers
    # This prevents SQL injection through field or group_by parameters
    _safe_field = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
    if not _safe_field.match(field):
        return {"error": f"Invalid field name: '{field}'. Only letters, numbers, and underscores allowed."}
    if group_by and not _safe_field.match(group_by):
        return {"error": f"Invalid group_by field: '{group_by}'. Only letters, numbers, and underscores allowed."}
    if agg not in ("SUM", "COUNT", "AVG"):
        return {"error": f"Invalid aggregation: '{agg}'. Must be SUM, COUNT, or AVG."}

    date_field = "posting_date"
    if doctype in ("Sales Order", "Purchase Order"):
        date_field = "transaction_date"

    def build_filters(from_d, to_d):
        f = {"docstatus": 1, date_field: ["between", [from_d, to_d]]}
        f.update(extra)
        return f

    if group_by:
        p1_data = frappe.get_list(doctype, fields=[group_by, f"{agg}({field}) as value"],
                                  filters=build_filters(p1_from, p1_to), group_by=group_by, limit_page_length=50)
        p2_data = frappe.get_list(doctype, fields=[group_by, f"{agg}({field}) as value"],
                                  filters=build_filters(p2_from, p2_to), group_by=group_by, limit_page_length=50)

        p1_map = {r[group_by]: float(r["value"] or 0) for r in p1_data}
        p2_map = {r[group_by]: float(r["value"] or 0) for r in p2_data}
        all_keys = sorted(set(list(p1_map.keys()) + list(p2_map.keys())))

        comparison = []
        for k in all_keys:
            v1 = p1_map.get(k, 0)
            v2 = p2_map.get(k, 0)
            change = v1 - v2
            pct = round((change / v2 * 100), 2) if v2 != 0 else (100.0 if v1 > 0 else 0.0)
            comparison.append({group_by: k, "period1": v1, "period2": v2, "change": change, "change_pct": pct})

        return {"grouped_comparison": comparison, "group_by": group_by}
    else:
        p1 = frappe.get_list(doctype, fields=[f"{agg}({field}) as value"],
                             filters=build_filters(p1_from, p1_to), limit_page_length=1)
        p2 = frappe.get_list(doctype, fields=[f"{agg}({field}) as value"],
                             filters=build_filters(p2_from, p2_to), limit_page_length=1)

        v1 = float(p1[0]["value"] or 0) if p1 else 0
        v2 = float(p2[0]["value"] or 0) if p2 else 0
        change = v1 - v2
        pct = round((change / v2 * 100), 2) if v2 != 0 else (100.0 if v1 > 0 else 0.0)

        return {
            "period1": {"from": p1_from, "to": p1_to, "value": v1},
            "period2": {"from": p2_from, "to": p2_to, "value": v2},
            "change": change, "change_pct": pct,
            "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
        }


def _exec_create_alert(params, user):
    """Create an AI alert rule."""
    try:
        doc = frappe.get_doc({
            "doctype": "AI Alert Rule",
            "user": user,
            "alert_name": params["alert_name"],
            "description": params["description"],
            "query_doctype": params["doctype"],
            "query_field": params["field"],
            "query_aggregation": params["aggregation"],
            "query_filters": json.dumps(params.get("filters", {})),
            "threshold_operator": params["operator"],
            "threshold_value": params["threshold"],
            "frequency": params["frequency"],
            "active": 1,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Sprint 7: Test-on-create — immediately show current value
        test_result = {}
        try:
            from .alerts import test_alert
            test_result = test_alert(doc.name)
        except Exception:
            pass

        result = {
            "success": True,
            "alert_id": doc.name,
            "message": f"Alert '{params['alert_name']}' created successfully.",
        }
        if test_result.get("success"):
            result["current_value"] = test_result.get("formatted_value", "")
            result["would_trigger_now"] = test_result.get("would_trigger", False)
            result["test_message"] = test_result.get("message", "")
        return result
    except Exception as e:
        return {"error": f"Failed to create alert: {str(e)[:200]}"}


def _exec_list_alerts(user):
    """List all active alerts for a user."""
    alerts = frappe.get_all(
        "AI Alert Rule",
        filters={"user": user, "active": 1},
        fields=["name", "alert_name", "description", "frequency",
                "threshold_operator", "threshold_value", "last_checked",
                "last_triggered", "last_value", "trigger_count"],
        order_by="creation desc",
    )
    return {"alerts": alerts, "count": len(alerts)}


def _exec_delete_alert(params, user):
    """Delete/deactivate an alert."""
    alert_name = params["alert_name"]
    # Try by name first, then by alert_name
    try:
        doc = frappe.get_doc("AI Alert Rule", alert_name)
    except frappe.DoesNotExistError:
        matches = frappe.get_all("AI Alert Rule",
                                 filters={"user": user, "alert_name": ["like", f"%{alert_name}%"]},
                                 fields=["name"], limit=1)
        if not matches:
            return {"error": f"Alert '{alert_name}' not found."}
        doc = frappe.get_doc("AI Alert Rule", matches[0]["name"])

    if doc.user != user:
        return {"error": "You can only delete your own alerts."}

    doc.active = 0
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "message": f"Alert '{doc.alert_name}' deactivated."}


def _exec_export_pdf(params):
    """Generate a branded PDF report from markdown content."""
    try:
        from .exports import export_pdf as _export_pdf
        result = _export_pdf(
            title=params["title"],
            content=params["content"],
        )
        return {
            "success": True,
            "file_name": result.get("file_name", ""),
            "download_url": result.get("download_url", ""),
            "file_url": result.get("file_url", ""),
            "message": f"PDF report '{params['title']}' generated successfully.",
        }
    except Exception as e:
        frappe.log_error(title="AI Export PDF Error", message=str(e))
        return {"error": f"Failed to generate PDF: {str(e)[:200]}"}


def _exec_export_excel(params):
    """Generate a branded Excel spreadsheet from tabular data."""
    try:
        from .exports import export_excel as _export_excel
        data = params["data"]
        columns = params.get("columns")
        # exports.py handles both list and JSON string — pass as JSON string for safety
        result = _export_excel(
            title=params["title"],
            data=json.dumps(data) if isinstance(data, list) else data,
            columns=json.dumps(columns) if isinstance(columns, list) else columns,
        )
        return {
            "success": True,
            "file_name": result.get("file_name", ""),
            "download_url": result.get("download_url", ""),
            "file_url": result.get("file_url", ""),
            "message": f"Excel report '{params['title']}' generated successfully.",
        }
    except Exception as e:
        frappe.log_error(title="AI Export Excel Error", message=str(e))
        return {"error": f"Failed to generate Excel: {str(e)[:200]}"}


def _exec_generate_chart(params):
    """
    Generate chart — returns the config back to Claude so it can embed it
    as a ```chart code block in its response text. The mobile app frontend
    parses these blocks and renders native charts.
    """
    return {
        "success": True,
        "chart_json": json.dumps({
            "type": params.get("type", "bar"),
            "title": params.get("title", ""),
            "labels": params.get("labels", []),
            "datasets": params.get("datasets", []),
        }),
        "instruction": (
            "Include this chart in your response by wrapping the chart_json "
            "value in a ```chart code block, like:\n"
            "```chart\n{...the chart JSON...}\n```\n"
            "The mobile app will render it as a native visual chart."
        ),
    }


def _parse_filters(filters):
    if not filters:
        return {}
    parsed = {}
    for key, value in filters.items():
        parsed[key] = value
    return parsed


# ─── Write Action Executors (Sprint 8) ──────────────────────────────────────

# Doctypes that can be created as drafts via the AI
_DRAFT_ALLOWED_DOCTYPES = {
    "Sales Order", "Sales Invoice", "Purchase Order",
    "Payment Entry", "Stock Entry", "Journal Entry",
}

# Mandatory fields per doctype that must be present in values
_DRAFT_MANDATORY = {
    "Sales Order": ["customer", "company", "delivery_date"],
    "Sales Invoice": ["customer", "company"],
    "Purchase Order": ["supplier", "company"],
    "Payment Entry": ["payment_type", "party_type", "party", "company", "paid_amount"],
    "Stock Entry": ["stock_entry_type", "company"],
    "Journal Entry": ["company"],
}


def _exec_create_draft(params, user):
    """
    Create a DRAFT document (docstatus=0) in ERPNext.
    The document is saved but NOT submitted — the user must review and submit manually.
    """
    doctype = params.get("doctype")
    values = params.get("values", {})

    if doctype not in _DRAFT_ALLOWED_DOCTYPES:
        return {"error": f"Cannot create drafts for '{doctype}'. Allowed: {', '.join(sorted(_DRAFT_ALLOWED_DOCTYPES))}"}

    # Check mandatory fields
    missing = []
    for field in _DRAFT_MANDATORY.get(doctype, []):
        if field not in values or not values[field]:
            missing.append(field)
    if missing:
        return {"error": f"Missing mandatory fields for {doctype}: {', '.join(missing)}"}

    try:
        doc = frappe.new_doc(doctype)
        for field, value in values.items():
            if field == "docstatus":
                continue  # Never allow setting docstatus via this tool
            if field == "items" and isinstance(value, list):
                # Handle child table items
                for item_row in value:
                    row = doc.append("items", {})
                    for k, v in item_row.items():
                        row.set(k, v)
            elif field == "accounts" and isinstance(value, list):
                # Journal Entry accounts child table
                for acct_row in value:
                    row = doc.append("accounts", {})
                    for k, v in acct_row.items():
                        row.set(k, v)
            else:
                doc.set(field, value)

        doc.docstatus = 0  # Force draft
        doc.insert(ignore_permissions=False)  # Respect user permissions
        frappe.db.commit()

        return {
            "success": True,
            "doctype": doctype,
            "name": doc.name,
            "message": f"Draft {doctype} '{doc.name}' created successfully. The user can review and submit it from ERPNext.",
        }
    except frappe.ValidationError as e:
        return {"error": f"Validation error: {str(e)[:300]}"}
    except frappe.PermissionError:
        return {"error": f"You don't have permission to create {doctype} documents."}
    except Exception as e:
        frappe.log_error(title=f"AI Draft Creation Error: {doctype}", message=str(e))
        return {"error": f"Failed to create draft: {str(e)[:200]}"}


def _exec_workflow_action(params, user):
    """
    Execute a workflow action on a document (e.g., Approve, Reject).
    Uses ERPNext's native workflow system.
    """
    doctype = params.get("doctype")
    docname = params.get("docname")
    action = params.get("action")

    if not all([doctype, docname, action]):
        return {"error": "Missing required fields: doctype, docname, action"}

    try:
        doc = frappe.get_doc(doctype, docname)

        # Check if the document has a workflow
        workflow_name = frappe.get_value("Workflow", {"document_type": doctype, "is_active": 1}, "name")
        if not workflow_name:
            return {"error": f"No active workflow found for {doctype}."}

        # Get available transitions for current state
        from frappe.model.workflow import get_transitions
        transitions = get_transitions(doc)
        available_actions = [t.get("action") for t in transitions]

        if action not in available_actions:
            return {
                "error": f"Action '{action}' not available. Current state: '{doc.workflow_state}'. Available actions: {', '.join(available_actions)}",
            }

        # Apply the workflow action
        from frappe.model.workflow import apply_workflow
        apply_workflow(doc, action)
        frappe.db.commit()

        return {
            "success": True,
            "doctype": doctype,
            "name": docname,
            "action": action,
            "new_state": doc.workflow_state,
            "message": f"{action} applied to {doctype} '{docname}'. New state: {doc.workflow_state}.",
        }
    except frappe.PermissionError:
        return {"error": f"You don't have permission to perform '{action}' on this document."}
    except Exception as e:
        frappe.log_error(title=f"AI Workflow Action Error: {doctype}/{docname}", message=str(e))
        return {"error": f"Failed to execute workflow action: {str(e)[:200]}"}


def _exec_schedule_report(params, user):
    """Create a scheduled report that auto-generates and emails on a recurring basis."""
    report_name = params.get("report_name")
    report_query = params.get("report_query")
    frequency = params.get("frequency", "daily")
    export_format = params.get("export_format", "pdf")
    email_recipients = params.get("email_recipients", "")

    if not report_name or not report_query:
        return {"error": "Missing required fields: report_name, report_query"}

    if frequency not in ("daily", "weekly", "monthly", "hourly"):
        return {"error": f"Invalid frequency '{frequency}'. Use: daily, weekly, monthly, hourly."}

    try:
        doc = frappe.new_doc("AI Scheduled Report")
        doc.user = user
        doc.report_name = report_name
        doc.report_query = report_query
        doc.frequency = frequency
        doc.export_format = export_format
        doc.email_recipients = email_recipients
        doc.active = 1
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "name": doc.name,
            "message": f"Scheduled report '{report_name}' created. It will run {frequency} and be emailed to {email_recipients or user}.",
        }
    except Exception as e:
        frappe.log_error(title="AI Schedule Report Error", message=str(e))
        return {"error": f"Failed to schedule report: {str(e)[:200]}"}


def _exec_save_preference(params, user):
    """Save a user preference that persists across sessions."""
    key = params.get("key")
    value = params.get("value")

    if not key:
        return {"error": "Missing required field: key"}

    try:
        from .memory import save_user_preference
        success = save_user_preference(user, key, value)
        if success:
            return {
                "success": True,
                "message": f"Preference saved: {key} = {value}. I'll remember this in future sessions.",
            }
        else:
            return {"error": "Failed to save preference."}
    except Exception as e:
        frappe.log_error(title="AI Save Preference Error", message=str(e))
        return {"error": f"Failed to save preference: {str(e)[:200]}"}


# ─── Response Distillation (Sprint 6A) ──────────────────────────────────────
# Strips irrelevant fields from tool results before feeding back to Claude.
# This saves 15-30% of tokens per tool round by removing internal metadata.

# Fields that are ALWAYS useful regardless of tool
_ALWAYS_KEEP = {"name", "title", "status", "docstatus", "grand_total", "total",
                "outstanding_amount", "customer", "supplier", "item_code", "item_name",
                "qty", "rate", "amount", "posting_date", "transaction_date",
                "workflow_state", "company", "warehouse", "territory"}

# Fields to ALWAYS strip (internal metadata, never useful for analysis)
_ALWAYS_STRIP = {"_user_tags", "_comments", "_assign", "_liked_by", "modified_by",
                 "creation", "modified", "owner", "idx", "parent", "parentfield",
                 "parenttype", "doctype", "_seen"}

# Phase 6.4: Additional low-value fields to strip for extra token savings
_EXTRA_STRIP = {"naming_series", "amended_from", "letter_head", "select_print_heading",
                "language", "represents_company", "is_internal_customer",
                "is_internal_supplier", "inter_company_order_reference",
                "po_no", "po_date", "tax_id", "remarks"}

# Max records to send back to Claude (prevents huge tool results)
_MAX_DISTILL_RECORDS = 100

# Phase 6.4: Threshold above which we auto-summarize instead of sending raw records
_AUTO_SUMMARIZE_THRESHOLD = 50


def _auto_summarize_records(records, tool_input):
    """
    Phase 6.4: When a query returns many records (>50), generate a compact
    statistical summary instead of sending all rows to the AI.
    Saves 40-60% tokens on large result sets.

    Returns a dict with summary statistics and a sample of top records.
    """
    if not records or not isinstance(records[0], dict):
        return None

    summary = {
        "_auto_summarized": True,
        "total_records": len(records),
        "sample_records": records[:10],  # Keep first 10 as representative sample
    }

    # Find numeric and categorical columns
    numeric_cols = {}
    categorical_cols = {}

    for key in records[0].keys():
        if key in _ALWAYS_STRIP or key in _EXTRA_STRIP:
            continue
        # Sample values to determine type
        values = [r.get(key) for r in records if r.get(key) is not None and r.get(key) != ""]
        if not values:
            continue

        # Check if numeric
        if all(isinstance(v, (int, float)) for v in values[:20]):
            numeric_vals = [float(v) for v in values if isinstance(v, (int, float))]
            if numeric_vals:
                numeric_cols[key] = {
                    "sum": round(sum(numeric_vals), 2),
                    "avg": round(sum(numeric_vals) / len(numeric_vals), 2),
                    "min": round(min(numeric_vals), 2),
                    "max": round(max(numeric_vals), 2),
                    "count": len(numeric_vals),
                }
        elif all(isinstance(v, str) for v in values[:20]):
            # Categorical — show top 5 value counts
            from collections import Counter
            counts = Counter(values)
            top5 = counts.most_common(5)
            categorical_cols[key] = {v: c for v, c in top5}

    if numeric_cols:
        summary["numeric_stats"] = numeric_cols
    if categorical_cols:
        summary["top_values"] = categorical_cols

    return summary


def _distill_tool_result(tool_name, tool_input, raw_result):
    """
    Distill a tool result to only the fields Claude needs for analysis.
    Phase 6.4 enhanced: 40-60% token reduction via smart summarization.

    Strategy:
    - query_records/run_sql_query: Strip internal fields, auto-summarize large sets
    - get_document: Strip metadata + extra low-value fields
    - count_records/run_report: Return as-is (already compact)
    - financial_summary/compare_periods: Return as-is (pre-formatted)
    - create_alert/list_alerts/delete_alert: Return as-is (small payloads)
    - export_pdf/export_excel/generate_chart: Return as-is (contains URLs)
    """
    if not isinstance(raw_result, dict):
        return raw_result

    # Tools that produce compact results — return unchanged
    compact_tools = {"count_records", "create_alert", "list_alerts", "delete_alert",
                     "export_pdf", "export_excel", "generate_chart",
                     "get_financial_summary", "compare_periods", "run_report"}
    if tool_name in compact_tools:
        return raw_result

    # query_records / run_sql_query — strip fields + cap records + auto-summarize
    if tool_name in ("query_records", "run_sql_query"):
        records = raw_result.get("data") or raw_result.get("records") or raw_result.get("result")
        if isinstance(records, list) and len(records) > 0:
            # Determine which fields were explicitly requested
            requested_fields = set()
            if tool_input:
                fields_str = tool_input.get("fields", "")
                if isinstance(fields_str, str) and fields_str:
                    requested_fields = {f.strip().split(" as ")[-1].strip().split(".")[-1]
                                        for f in fields_str.split(",") if f.strip() != "*"}
                elif isinstance(fields_str, list):
                    requested_fields = {f.strip().split(" as ")[-1].strip().split(".")[-1]
                                        for f in fields_str if isinstance(f, str)}

            # If specific fields were requested, keep only those + always-keep
            keep_fields = _ALWAYS_KEEP | requested_fields if requested_fields else None
            strip_fields = _ALWAYS_STRIP | _EXTRA_STRIP  # Phase 6.4: strip more

            distilled = []
            for record in records[:_MAX_DISTILL_RECORDS]:
                if isinstance(record, dict):
                    clean = {}
                    for k, v in record.items():
                        if k in strip_fields:
                            continue
                        if keep_fields and k not in keep_fields and k != "name":
                            continue
                        # Skip empty/null values to save tokens
                        if v is None or v == "" or v == 0.0:
                            continue
                        clean[k] = v
                    if clean:
                        distilled.append(clean)
                else:
                    distilled.append(record)

            # Phase 6.4: Auto-summarize large result sets
            result_key = "data" if "data" in raw_result else ("records" if "records" in raw_result else "result")
            if len(distilled) > _AUTO_SUMMARIZE_THRESHOLD:
                summary = _auto_summarize_records(distilled, tool_input)
                if summary:
                    # Clean the sample records too
                    summary["sample_records"] = summary["sample_records"][:10]
                    return summary

            # Build distilled result
            distilled_result = dict(raw_result)
            distilled_result[result_key] = distilled
            if len(records) > _MAX_DISTILL_RECORDS:
                distilled_result["_truncated"] = True
                distilled_result["_total_available"] = len(records)
                distilled_result["_showing"] = _MAX_DISTILL_RECORDS
            return distilled_result

    # get_document — strip metadata + extra fields
    if tool_name == "get_document":
        doc = raw_result.get("data") or raw_result
        strip_all = _ALWAYS_STRIP | _EXTRA_STRIP
        if isinstance(doc, dict):
            clean = {k: v for k, v in doc.items()
                     if k not in strip_all and v is not None and v != ""}
            if "data" in raw_result:
                return {"data": clean, "success": raw_result.get("success", True)}
            return clean

    return raw_result


def _get_token_budget(question, model_doc=None):
    """
    Determine the token budget for a query based on its complexity class.
    Reads configurable budgets from model_doc if available.
    Falls back to _FALLBACK_TOKEN_BUDGETS.
    """
    complexity, _ = classify_query(question)

    # Build budget map — model doc overrides defaults if configured
    budgets = _FALLBACK_TOKEN_BUDGETS.copy()
    if model_doc:
        if getattr(model_doc, "token_budget_simple", 0) and model_doc.token_budget_simple > 0:
            budgets["simple"] = model_doc.token_budget_simple
        if getattr(model_doc, "token_budget_medium", 0) and model_doc.token_budget_medium > 0:
            budgets["medium"] = model_doc.token_budget_medium
        if getattr(model_doc, "token_budget_complex", 0) and model_doc.token_budget_complex > 0:
            budgets["complex"] = model_doc.token_budget_complex

    if complexity == "flash":
        return budgets.get("flash", budgets["simple"])
    if complexity == "simple":
        return budgets["simple"]

    # Check for multi-part/dashboard queries → use complex budget
    dashboard_keywords = ["pulse", "dashboard", "overview", "everything", "full report",
                          "all metrics", "complete analysis", "briefing"]
    q_lower = question.lower()
    if any(kw in q_lower for kw in dashboard_keywords):
        return budgets["complex"]
    return budgets["medium"]



# ─── Main Chat Handler ──────────────────────────────────────────────────────

def process_chat(user, question, conversation_history=None, image_data=None):
    """
    Process a user's chat question through the full AI pipeline.

    Dynamic model selection:
      1. Classify query complexity → tier name
      2. Resolve tier → model doc via AskERP Settings
      3. Check user restrictions, monthly budget
      4. Call model via providers.call_model()
      5. Handle tool use rounds with token budget enforcement
      6. Fallback chain: primary → fallback model → friendly message
      7. Calculate and return cost

    image_data: optional dict with {"data": base64_str, "media_type": "image/jpeg"}
    """
    from .business_context import get_system_prompt
    from .providers import (
        get_model_for_tier, get_settings, get_user_restricted_model,
        check_monthly_budget, call_model as provider_call, calculate_cost,
        is_provider_credit_exhausted,
    )

    settings = get_settings()
    fallback_message = (settings.fallback_message if settings else None) or \
        "I'm temporarily unable to help right now. Please try again in a few minutes."

    # ── Step 1: Model Selection ───────────────────────────────────────────
    model_doc = None
    tier_used = "tier_3"

    # Check for user-specific model restriction
    restricted_model = get_user_restricted_model(user)
    if restricted_model:
        model_doc = restricted_model
        tier_used = "restricted"
    elif image_data:
        # Vision queries → vision model or tier_3
        model_doc = get_model_for_tier("vision") or get_model_for_tier("tier_3")
        tier_used = "vision"
    else:
        # Smart routing: classify query → tier → model
        if settings and settings.enable_smart_routing:
            _complexity, tier_name = classify_query(question)
            tier_used = tier_name
            model_doc = get_model_for_tier(tier_name)
            # If requested tier not configured, escalate to next tier
            if not model_doc and tier_name == "tier_1":
                model_doc = get_model_for_tier("tier_2")
                tier_used = "tier_2"
            if not model_doc and tier_used in ("tier_1", "tier_2"):
                model_doc = get_model_for_tier("tier_3")
                tier_used = "tier_3"
        else:
            # Smart routing disabled → always tier_3
            model_doc = get_model_for_tier("tier_3")

    if not model_doc:
        return {
            "response": fallback_message,
            "tool_calls": 0,
            "model": "none",
            "tier": "unknown",
            "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
        }

    # ── Step 2: Budget Check ─────────────────────────────────────────────
    exceeded, _current_spend, _limit = check_monthly_budget()
    if exceeded:
        return {
            "response": "The monthly AI budget has been reached. Please contact your admin.",
            "tool_calls": 0,
            "model": model_doc.model_id,
            "tier": tier_used,
            "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
        }

    # ── Step 3: Build Messages ───────────────────────────────────────────
    # Flash tier: use a minimal system prompt (saves ~4K input tokens)
    if tier_used == "tier_1":
        user_doc = frappe.get_doc("User", user)
        system_prompt = (
            f"You are AskERP, a friendly business assistant. "
            f"You're chatting with {user_doc.full_name or user}. "
            f"Keep responses brief and warm. Today is {frappe.utils.today()}."
        )
    else:
        system_prompt = get_system_prompt(user)
    messages = []
    if conversation_history:
        messages.extend(conversation_history)

    if image_data:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_data.get("media_type", "image/jpeg"),
                        "data": image_data["data"],
                    },
                },
                {"type": "text", "text": question},
            ],
        })
    else:
        messages.append({"role": "user", "content": question})

    # ── Step 4: Tier-Aware Optimization ──────────────────────────────────
    #
    # Cost optimization: different tiers get different capabilities.
    # Flash (greetings): no tools, no thinking, low max_tokens → ~90% cheaper
    # Simple (lookups):  tools yes, no thinking, medium max_tokens → ~50% cheaper
    # Complex (analysis): full tools, thinking if supported, full max_tokens
    #
    # Override max_tokens based on tier (saves output token cost)
    _TIER_MAX_TOKENS = {
        "tier_1": 1024,    # Flash: greetings, single-line answers
        "tier_2": 4096,    # Simple: lookups, short tables, counts
        "tier_3": None,    # Complex: use model default (8192-16384)
        "vision": None,    # Vision: use model default
    }
    tier_max = _TIER_MAX_TOKENS.get(tier_used)
    if tier_max and tier_max < (model_doc.max_output_tokens or 99999):
        # Temporarily override the model's max_output_tokens for this request
        model_doc._original_max_tokens = model_doc.max_output_tokens
        model_doc.max_output_tokens = tier_max

    # Disable extended thinking for flash/simple tiers (saves 2x output tokens)
    if tier_used in ("tier_1", "tier_2"):
        model_doc._original_thinking = getattr(model_doc, "supports_thinking", 0)
        model_doc.supports_thinking = 0

    total_input_tokens = 0
    total_output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    tool_calls_made = 0

    token_budget = _get_token_budget(question, model_doc)
    budget_exceeded = False

    max_rounds = model_doc.max_tool_rounds if (model_doc.max_tool_rounds and model_doc.max_tool_rounds > 0) else _FALLBACK_MAX_TOOL_ROUNDS

    # Flash tier: skip tools entirely (saves ~2K input tokens per call)
    if tier_used == "tier_1":
        tools = None
        max_rounds = 1  # No tool use rounds needed
    else:
        tools = get_all_tools(user) if model_doc.supports_tools else None

    for _round_num in range(max_rounds):
        response = provider_call(model_doc, messages, system_prompt, tools)

        # If provider call failed, try tier downgrade → fallback → graceful message
        if response is None:
            # Step A: Try downgrading tiers (tier_3 → tier_2 → tier_1)
            downgrade_chain = []
            if tier_used == "tier_3":
                downgrade_chain = ["tier_2", "tier_1"]
            elif tier_used == "tier_2":
                downgrade_chain = ["tier_1"]

            for dg_tier in downgrade_chain:
                dg_doc = get_model_for_tier(dg_tier)
                if dg_doc and dg_doc.name != model_doc.name:
                    dg_provider = (dg_doc.provider or "").strip()
                    if is_provider_credit_exhausted(dg_provider):
                        continue  # Same provider, same credit issue — skip
                    frappe.logger("askerp").warning(
                        f"Downgrading from {model_doc.model_id} to {dg_doc.model_id} ({dg_tier})"
                    )
                    model_doc = dg_doc
                    tier_used = dg_tier
                    tools = get_all_tools(user) if model_doc.supports_tools else None
                    response = provider_call(model_doc, messages, system_prompt, tools)
                    if response is not None:
                        break

            # Step B: Try configured fallback model
            if response is None:
                fb_doc = get_model_for_tier("fallback")
                if fb_doc and fb_doc.name != model_doc.name:
                    fb_provider = (fb_doc.provider or "").strip()
                    if not is_provider_credit_exhausted(fb_provider):
                        frappe.logger("askerp").warning(
                            f"Trying fallback model {fb_doc.model_id}"
                        )
                        model_doc = fb_doc
                        tools = get_all_tools(user) if model_doc.supports_tools else None
                        response = provider_call(model_doc, messages, system_prompt, tools)

            # Step C: All options exhausted — graceful message
            if response is None:
                any_credit_issue = any(
                    is_provider_credit_exhausted(p)
                    for p in ("Anthropic", "Google", "OpenAI", "Custom")
                )
                graceful_msg = (
                    "I'm taking a short break to recharge. "
                    "Your admin has been notified and I'll be back shortly."
                ) if any_credit_issue else fallback_message

                return {
                    "response": graceful_msg,
                    "tool_calls": tool_calls_made,
                    "model": model_doc.model_id,
                    "tier": tier_used,
                    "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
                }

        usage = response.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)
        cache_read_tokens += usage.get("cache_read_tokens", 0)
        cache_creation_tokens += usage.get("cache_creation_tokens", 0)

        stop_reason = response.get("stop_reason", "")
        content_blocks = response.get("content", [])

        if stop_reason == "tool_use":
            # Token budget check
            total_tokens_so_far = total_input_tokens + total_output_tokens
            if total_tokens_so_far > token_budget:
                budget_exceeded = True
                messages.append({"role": "assistant", "content": content_blocks})
                messages.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": block["id"],
                     "content": json.dumps({"note": "Token budget reached. Please synthesize your answer from the data already gathered."})}
                    for block in content_blocks if block.get("type") == "tool_use"
                ]})
                continue

            messages.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_calls_made += 1
                    tool_result = execute_tool(block["name"], block["input"], user)
                    distilled = _distill_tool_result(block["name"], block.get("input", {}), tool_result)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(distilled, default=str),
                    })
            messages.append({"role": "user", "content": tool_results})

        elif stop_reason == "end_turn":
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]

            # ── Step 5: Cost Calculation ─────────────────────────────────
            cost = calculate_cost(model_doc, {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
            })

            return {
                "response": text_response,
                "tool_calls": tool_calls_made,
                "model": model_doc.model_id,
                "tier": tier_used,
                "budget_exceeded": budget_exceeded,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                },
                "cost": cost,
            }
        else:
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]
            cost = calculate_cost(model_doc, {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
            })
            return {
                "response": text_response or "I wasn't able to complete that request. Please try again.",
                "tool_calls": tool_calls_made,
                "model": model_doc.model_id,
                "tier": tier_used,
                "budget_exceeded": budget_exceeded,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                },
                "cost": cost,
            }

    # Max tool rounds exhausted
    cost = calculate_cost(model_doc, {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    })
    return {
        "response": "This query required too many data lookups. Try asking a simpler question.",
        "tool_calls": tool_calls_made,
        "model": model_doc.model_id,
        "tier": tier_used,
        "budget_exceeded": budget_exceeded,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
        },
        "cost": cost,
    }


# ─── Streaming Chat Handler (Phase 3) ────────────────────────────────────────

def _update_stream_cache(cache_key, **kwargs):
    """Write current stream state to Redis cache for frontend polling."""
    data = {
        "status": kwargs.get("status", "streaming"),
        "text": kwargs.get("text", ""),
        "tool_status": kwargs.get("tool_status"),
        "done": kwargs.get("done", False),
        "error": kwargs.get("error"),
        "usage": kwargs.get("usage", {}),
        "tool_calls": kwargs.get("tool_calls", 0),
        "session_id": kwargs.get("session_id", ""),
        "session_title": kwargs.get("session_title", ""),
        "message_count": kwargs.get("message_count", 0),
        "daily_remaining": kwargs.get("daily_remaining", 0),
    }
    frappe.cache.set_value(cache_key, json.dumps(data), expires_in_sec=600)


def _get_tool_label(tool_name, tool_input):
    """Get a user-friendly label for a tool being executed."""
    labels = {
        "query_records": "Looking up {doctype}...",
        "count_records": "Counting {doctype}...",
        "get_document": "Fetching details...",
        "run_report": "Running {report_name} report...",
        "run_sql_query": "Analyzing data...",
        "get_financial_summary": "Computing financial summary...",
        "compare_periods": "Comparing periods...",
        "create_alert": "Setting up alert...",
        "list_alerts": "Checking alerts...",
        "delete_alert": "Removing alert...",
        "export_pdf": "Generating PDF...",
        "export_excel": "Creating spreadsheet...",
        "generate_chart": "Creating chart...",
    }
    template = labels.get(tool_name, "Processing...")
    try:
        return template.format(**tool_input)
    except (KeyError, IndexError):
        return template.split("{")[0].strip() + "..."


def _stream_claude_response(messages, system_prompt, tools, cache_key, text_so_far, model_doc=None):
    """
    Stream an AI response via Anthropic SSE.
    Uses model_doc from providers for connection setup.
    Parses SSE events, writes text tokens to Redis in real-time.
    Returns result dict with accumulated text, content blocks, and usage.
    """
    from .providers import _call_anthropic_stream as get_stream_response

    if not model_doc:
        error_msg = "No model configured for streaming."
        return {
            "stop_reason": "end_turn",
            "accumulated_text": (text_so_far + "\n\n" + error_msg) if text_so_far else error_msg,
            "content_blocks": [{"type": "text", "text": error_msg}],
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }

    # Get raw streaming response from provider
    resp = get_stream_response(model_doc, messages, system_prompt, tools)
    if resp is None:
        error_msg = "I'm having trouble connecting right now. Please try again."
        return {
            "stop_reason": "end_turn",
            "accumulated_text": (text_so_far + "\n\n" + error_msg) if text_so_far else error_msg,
            "content_blocks": [{"type": "text", "text": error_msg}],
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }

    # Parse SSE events from streaming response
    accumulated_text = text_so_far
    content_blocks = []
    current_block = None
    tool_input_json = ""
    stop_reason = "end_turn"
    input_tokens = 0
    output_tokens = 0
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0
    last_update_len = len(accumulated_text)

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue

        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break

        try:
            event = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        if event_type == "message_start":
            msg = event.get("message", {})
            u = msg.get("usage", {})
            input_tokens = u.get("input_tokens", 0)
            cache_read_input_tokens = u.get("cache_read_input_tokens", 0)
            cache_creation_input_tokens = u.get("cache_creation_input_tokens", 0)

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            block_type = block.get("type", "")
            if block_type == "text":
                current_block = {"type": "text", "text": ""}
            elif block_type == "tool_use":
                current_block = {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": {},
                }
                tool_input_json = ""
            elif block_type == "thinking":
                current_block = {"type": "thinking", "thinking": ""}
                _update_stream_cache(cache_key, status="thinking", text=accumulated_text)

        elif event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta" and current_block and current_block["type"] == "text":
                new_text = delta.get("text", "")
                current_block["text"] += new_text
                accumulated_text += new_text
                # Update Redis every ~30 chars for smooth streaming
                if len(accumulated_text) - last_update_len >= 30:
                    _update_stream_cache(cache_key, status="streaming", text=accumulated_text)
                    last_update_len = len(accumulated_text)

            elif delta_type == "input_json_delta" and current_block and current_block["type"] == "tool_use":
                tool_input_json += delta.get("partial_json", "")

            elif delta_type == "thinking_delta" and current_block and current_block.get("type") == "thinking":
                current_block["thinking"] += delta.get("thinking", "")

        elif event_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try:
                        current_block["input"] = json.loads(tool_input_json) if tool_input_json else {}
                    except json.JSONDecodeError:
                        current_block["input"] = {}
                content_blocks.append(current_block)
                current_block = None

        elif event_type == "message_delta":
            delta = event.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            u = event.get("usage", {})
            output_tokens = u.get("output_tokens", output_tokens)

        elif event_type == "message_stop":
            break

    # Final update with complete text for this round
    _update_stream_cache(cache_key, status="streaming", text=accumulated_text)

    return {
        "stop_reason": stop_reason,
        "accumulated_text": accumulated_text,
        "content_blocks": content_blocks,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_input_tokens,
        "cache_creation_tokens": cache_creation_input_tokens,
    }


def process_chat_stream(user, question, conversation_history=None, stream_id=None, image_data=None):
    """
    Streaming version of process_chat. Runs as a background job (RQ worker).
    Streams tokens to Redis so frontend can poll for real-time updates.
    Returns final result dict on completion.

    Dynamic model selection mirrors process_chat:
      - Smart routing, user restrictions, budget checks
      - Anthropic models use SSE streaming, others fall back to sync call
      - Fallback chain on failure (tier downgrade → fallback → graceful message)
      - Cost tracking
    """
    from .business_context import get_system_prompt
    from .providers import (
        get_model_for_tier, get_settings, get_user_restricted_model,
        check_monthly_budget, call_model as provider_call, calculate_cost,
        is_provider_credit_exhausted,
    )

    cache_key = f"askerp_stream:{stream_id}"
    full_text = ""

    try:
        frappe.set_user(user)

        settings = get_settings()
        fallback_message = (settings.fallback_message if settings else None) or \
            "I'm temporarily unable to help right now. Please try again in a few minutes."

        # ── Model Selection ───────────────────────────────────────────
        model_doc = None
        tier_used = "tier_3"

        restricted_model = get_user_restricted_model(user)
        if restricted_model:
            model_doc = restricted_model
            tier_used = "restricted"
        elif image_data:
            model_doc = get_model_for_tier("vision") or get_model_for_tier("tier_3")
            tier_used = "vision"
        else:
            if settings and settings.enable_smart_routing:
                _complexity, tier_name = classify_query(question)
                tier_used = tier_name
                model_doc = get_model_for_tier(tier_name)
                if not model_doc and tier_name == "tier_1":
                    model_doc = get_model_for_tier("tier_2")
                    tier_used = "tier_2"
                if not model_doc and tier_used in ("tier_1", "tier_2"):
                    model_doc = get_model_for_tier("tier_3")
                    tier_used = "tier_3"
            else:
                model_doc = get_model_for_tier("tier_3")

        if not model_doc:
            _update_stream_cache(cache_key, status="error", text=fallback_message, done=True)
            return {"response": fallback_message, "tool_calls": 0, "model": "none",
                    "tier": "unknown", "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}}

        # ── Budget Check ─────────────────────────────────────────────
        exceeded, _, _ = check_monthly_budget()
        if exceeded:
            msg = "The monthly AI budget has been reached. Please contact your admin."
            _update_stream_cache(cache_key, status="done", text=msg, done=True)
            return {"response": msg, "tool_calls": 0, "model": model_doc.model_id,
                    "tier": tier_used, "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0}}

        # ── Build Messages ───────────────────────────────────────────
        if tier_used == "tier_1":
            user_doc_s = frappe.get_doc("User", user)
            system_prompt = (
                f"You are AskERP, a friendly business assistant. "
                f"You're chatting with {user_doc_s.full_name or user}. "
                f"Keep responses brief and warm. Today is {frappe.utils.today()}."
            )
        else:
            system_prompt = get_system_prompt(user)
        messages = []
        if conversation_history:
            messages.extend(conversation_history)

        if image_data:
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_data.get("media_type", "image/jpeg"),
                            "data": image_data["data"],
                        },
                    },
                    {"type": "text", "text": question},
                ],
            })
        else:
            messages.append({"role": "user", "content": question})

        # ── Tier-Aware Optimization (same as process_chat) ────────────
        _TIER_MAX_TOKENS_S = {
            "tier_1": 1024,
            "tier_2": 4096,
            "tier_3": None,
            "vision": None,
        }
        tier_max_s = _TIER_MAX_TOKENS_S.get(tier_used)
        if tier_max_s and tier_max_s < (model_doc.max_output_tokens or 99999):
            model_doc.max_output_tokens = tier_max_s

        if tier_used in ("tier_1", "tier_2"):
            model_doc.supports_thinking = 0

        total_input_tokens = 0
        total_output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        tool_calls_made = 0

        token_budget = _get_token_budget(question, model_doc)
        budget_exceeded = False

        max_rounds = model_doc.max_tool_rounds if (model_doc.max_tool_rounds and model_doc.max_tool_rounds > 0) else _FALLBACK_MAX_TOOL_ROUNDS

        if tier_used == "tier_1":
            tools = None
            max_rounds = 1
        else:
            tools = get_all_tools(user) if model_doc.supports_tools else None

        _update_stream_cache(cache_key, status="thinking", text="")

        # Only Anthropic models support SSE streaming; others use sync call
        use_streaming = (model_doc.provider == "Anthropic" and model_doc.supports_streaming)

        for _round_num in range(max_rounds):
            if use_streaming:
                result = _stream_claude_response(
                    messages, system_prompt, tools, cache_key, full_text,
                    model_doc=model_doc,
                )

                if result is None:
                    # Streaming failed — try tier downgrade → fallback → graceful
                    recovered = False
                    downgrade_chain = []
                    if tier_used == "tier_3":
                        downgrade_chain = ["tier_2", "tier_1"]
                    elif tier_used == "tier_2":
                        downgrade_chain = ["tier_1"]
                    for dg_tier in downgrade_chain:
                        dg_doc = get_model_for_tier(dg_tier)
                        if dg_doc and dg_doc.name != model_doc.name:
                            dg_provider = (dg_doc.provider or "").strip()
                            if is_provider_credit_exhausted(dg_provider):
                                continue
                            model_doc = dg_doc
                            tier_used = dg_tier
                            use_streaming = (model_doc.provider == "Anthropic" and model_doc.supports_streaming)
                            tools = get_all_tools(user) if model_doc.supports_tools else None
                            recovered = True
                            break
                    if not recovered:
                        fb_doc = get_model_for_tier("fallback")
                        if fb_doc and fb_doc.name != model_doc.name:
                            fb_prov = (fb_doc.provider or "").strip()
                            if not is_provider_credit_exhausted(fb_prov):
                                model_doc = fb_doc
                                use_streaming = (model_doc.provider == "Anthropic" and model_doc.supports_streaming)
                                tools = get_all_tools(user) if model_doc.supports_tools else None
                                recovered = True
                    if recovered:
                        continue
                    # All options exhausted
                    any_credit = any(is_provider_credit_exhausted(p) for p in ("Anthropic", "Google", "OpenAI", "Custom"))
                    msg = ("I'm taking a short break to recharge. "
                           "Your admin has been notified and I'll be back shortly.") if any_credit else fallback_message
                    _update_stream_cache(cache_key, status="error", text=msg, done=True)
                    return {"response": msg, "tool_calls": tool_calls_made,
                            "model": model_doc.model_id, "tier": tier_used,
                            "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
                            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                                      "cache_read_tokens": 0, "cache_creation_tokens": 0}}

                total_input_tokens += result.get("input_tokens", 0)
                total_output_tokens += result.get("output_tokens", 0)
                cache_read_tokens += result.get("cache_read_tokens", 0)
                cache_creation_tokens += result.get("cache_creation_tokens", 0)
                full_text = result.get("accumulated_text", full_text)
                stop_reason = result.get("stop_reason", "end_turn")
                content_blocks = result.get("content_blocks", [])

            else:
                # Non-streaming: synchronous call via providers
                _update_stream_cache(cache_key, status="thinking", text=full_text)
                response = provider_call(model_doc, messages, system_prompt, tools)

                if response is None:
                    # Non-streaming failed — try tier downgrade → fallback
                    recovered = False
                    dg_chain = []
                    if tier_used == "tier_3":
                        dg_chain = ["tier_2", "tier_1"]
                    elif tier_used == "tier_2":
                        dg_chain = ["tier_1"]
                    for dg_tier in dg_chain:
                        dg_doc = get_model_for_tier(dg_tier)
                        if dg_doc and dg_doc.name != model_doc.name:
                            dg_prov = (dg_doc.provider or "").strip()
                            if is_provider_credit_exhausted(dg_prov):
                                continue
                            model_doc = dg_doc
                            tools = get_all_tools(user) if model_doc.supports_tools else None
                            recovered = True
                            break
                    if not recovered:
                        fb_doc = get_model_for_tier("fallback")
                        if fb_doc and fb_doc.name != model_doc.name:
                            fb_prov = (fb_doc.provider or "").strip()
                            if not is_provider_credit_exhausted(fb_prov):
                                model_doc = fb_doc
                                tools = get_all_tools(user) if model_doc.supports_tools else None
                                recovered = True
                    if recovered:
                        continue
                    any_credit = any(is_provider_credit_exhausted(p) for p in ("Anthropic", "Google", "OpenAI", "Custom"))
                    msg = ("I'm taking a short break to recharge. "
                           "Your admin has been notified and I'll be back shortly.") if any_credit else fallback_message
                    _update_stream_cache(cache_key, status="error", text=msg, done=True)
                    return {"response": msg, "tool_calls": tool_calls_made,
                            "model": model_doc.model_id, "tier": tier_used,
                            "cost": {"cost_input": 0, "cost_output": 0, "cost_total": 0},
                            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                                      "cache_read_tokens": 0, "cache_creation_tokens": 0}}

                usage = response.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                cache_read_tokens += usage.get("cache_read_tokens", 0)
                cache_creation_tokens += usage.get("cache_creation_tokens", 0)

                stop_reason = response.get("stop_reason", "")
                content_blocks = response.get("content", [])

                # Extract text for cache update
                for block in content_blocks:
                    if block.get("type") == "text":
                        full_text += block["text"]
                _update_stream_cache(cache_key, status="streaming", text=full_text)

            if stop_reason == "tool_use":
                # Token budget check
                total_tokens_so_far = total_input_tokens + total_output_tokens
                if total_tokens_so_far > token_budget:
                    budget_exceeded = True
                    messages.append({"role": "assistant", "content": content_blocks})
                    messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": block["id"],
                         "content": json.dumps({"note": "Token budget reached. Please synthesize your answer from the data already gathered."})}
                        for block in content_blocks if block.get("type") == "tool_use"
                    ]})
                    continue

                messages.append({"role": "assistant", "content": content_blocks})
                tool_results = []
                for block in content_blocks:
                    if block.get("type") == "tool_use":
                        tool_calls_made += 1
                        tool_label = _get_tool_label(block["name"], block.get("input", {}))
                        _update_stream_cache(
                            cache_key, status="tool_use",
                            text=full_text, tool_status=tool_label,
                            tool_calls=tool_calls_made,
                        )
                        tool_result = execute_tool(block["name"], block["input"], user)
                        distilled = _distill_tool_result(block["name"], block.get("input", {}), tool_result)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": json.dumps(distilled, default=str),
                        })
                messages.append({"role": "user", "content": tool_results})

            elif stop_reason == "end_turn":
                cost = calculate_cost(model_doc, {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                })
                return {
                    "response": full_text,
                    "tool_calls": tool_calls_made,
                    "model": model_doc.model_id,
                    "tier": tier_used,
                    "usage": {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                        "cache_read_tokens": cache_read_tokens,
                        "cache_creation_tokens": cache_creation_tokens,
                    },
                    "cost": cost,
                }
            else:
                cost = calculate_cost(model_doc, {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                })
                return {
                    "response": full_text or "I wasn't able to complete that request.",
                    "tool_calls": tool_calls_made,
                    "model": model_doc.model_id,
                    "tier": tier_used,
                    "usage": {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                        "cache_read_tokens": cache_read_tokens,
                        "cache_creation_tokens": cache_creation_tokens,
                    },
                    "cost": cost,
                }

        # Max tool rounds exhausted
        cost = calculate_cost(model_doc, {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": cache_creation_tokens,
        })
        return {
            "response": full_text or "This query required too many data lookups.",
            "tool_calls": tool_calls_made,
            "model": model_doc.model_id,
            "tier": tier_used,
            "usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
            },
            "cost": cost,
        }

    except Exception as e:
        frappe.log_error(title="AI Stream Error", message=str(e))
        _update_stream_cache(cache_key, status="error", text=full_text,
                             error=str(e)[:200], done=True)
        raise
