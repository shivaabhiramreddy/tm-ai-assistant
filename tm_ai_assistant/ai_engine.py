"""
TM AI Assistant — AI Engine v3.0
==================================
Core AI logic with Claude Opus 4.5 + Extended Thinking.
Executes ERPNext data queries via tool_use and returns
executive-grade formatted responses.

v3 changes:
- Upgraded to Claude Opus 4.5 with extended thinking (budget 8K tokens)
- Added run_sql_query tool for complex analytical JOINs
- Added get_financial_summary tool for pre-built financial dashboards
- Added compare_periods tool for automatic period-over-period analysis
- Added create_alert / list_alerts / delete_alert tools for alert management
- Thinking blocks filtered from user-facing responses
- Configurable model and thinking budget via site_config
"""

import json
import frappe
import requests
from datetime import datetime


# ─── Configuration ───────────────────────────────────────────────────────────

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-4-5-20251101"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 16384
THINKING_BUDGET = 8192
MAX_TOOL_ROUNDS = 8  # Opus can handle deeper multi-step analysis


def get_api_key():
    """Get Anthropic API key from site config."""
    key = frappe.conf.get("anthropic_api_key", "")
    if not key:
        frappe.throw("Anthropic API key not configured. Set 'anthropic_api_key' in site_config.json.")
    return key


def get_model():
    """Get model from site config, default to Opus 4.5."""
    return frappe.conf.get("ai_model", DEFAULT_MODEL)


def get_thinking_budget():
    """Get thinking token budget from site config."""
    return int(frappe.conf.get("ai_thinking_budget", THINKING_BUDGET))


# ─── Claude API Client ──────────────────────────────────────────────────────

def call_claude(messages, system_prompt, tools=None):
    """Make a single call to Claude API with extended thinking. Returns the full response dict."""
    api_key = get_api_key()
    model = get_model()
    thinking_budget = get_thinking_budget()

    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": messages,
        "thinking": {
            "type": "enabled",
            "budget_tokens": thinking_budget,
        },
    }
    if tools:
        payload["tools"] = tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    resp = requests.post(ANTHROPIC_API_URL, json=payload, headers=headers, timeout=180)

    if resp.status_code != 200:
        error_detail = resp.text[:500]
        frappe.log_error(
            title="Claude API Error",
            message=f"Status {resp.status_code}: {error_detail}"
        )
        frappe.throw(f"AI service error (HTTP {resp.status_code}). Please try again.")

    return resp.json()


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
]


# ─── Tool Execution ─────────────────────────────────────────────────────────

def execute_tool(tool_name, tool_input, user):
    """Execute an ERPNext tool call. All queries run as the specified user."""
    original_user = frappe.session.user
    try:
        frappe.set_user(user)

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
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except frappe.PermissionError:
        return {"error": "You don't have permission to access this data."}
    except Exception as e:
        frappe.log_error(title=f"AI Tool Error: {tool_name}", message=str(e))
        return {"error": f"Query failed: {str(e)[:200]}"}
    finally:
        frappe.set_user(original_user)


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

    try:
        result = frappe.db.sql(query, as_dict=True)
        # Limit to 100 rows
        truncated = len(result) > 100
        data = result[:100]
        return {"data": data, "count": len(data), "total_rows": len(result), "truncated": truncated}
    except Exception as e:
        return {"error": f"SQL error: {str(e)[:200]}"}


def _exec_financial_summary(params):
    """Get a comprehensive financial summary for a company and period."""
    company = params["company"]
    today = frappe.utils.today()
    from_date = params.get("from_date", frappe.utils.get_first_day(today).strftime("%Y-%m-%d"))
    to_date = params.get("to_date", today)

    summary = {}

    # Revenue (Sales Invoices)
    rev = frappe.db.sql("""
        SELECT COALESCE(SUM(grand_total), 0) as total_revenue,
               COALESCE(SUM(net_total), 0) as net_revenue,
               COUNT(name) as invoice_count
        FROM `tabSales Invoice`
        WHERE company=%s AND docstatus=1 AND is_return=0
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)
    summary["revenue"] = rev[0] if rev else {}

    # Returns
    ret = frappe.db.sql("""
        SELECT COALESCE(SUM(ABS(grand_total)), 0) as total_returns,
               COUNT(name) as return_count
        FROM `tabSales Invoice`
        WHERE company=%s AND docstatus=1 AND is_return=1
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)
    summary["returns"] = ret[0] if ret else {}

    # Purchases
    pur = frappe.db.sql("""
        SELECT COALESCE(SUM(grand_total), 0) as total_purchases,
               COUNT(name) as purchase_count
        FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1 AND is_return=0
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)
    summary["purchases"] = pur[0] if pur else {}

    # Collections (Payments Received)
    coll = frappe.db.sql("""
        SELECT COALESCE(SUM(paid_amount), 0) as total_collections,
               COUNT(name) as collection_count
        FROM `tabPayment Entry`
        WHERE company=%s AND docstatus=1 AND payment_type='Receive'
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)
    summary["collections"] = coll[0] if coll else {}

    # Payments Made
    paid = frappe.db.sql("""
        SELECT COALESCE(SUM(paid_amount), 0) as total_payments,
               COUNT(name) as payment_count
        FROM `tabPayment Entry`
        WHERE company=%s AND docstatus=1 AND payment_type='Pay'
        AND posting_date BETWEEN %s AND %s
    """, (company, from_date, to_date), as_dict=True)
    summary["payments_made"] = paid[0] if paid else {}

    # Outstanding Receivables (all time, current balance)
    recv = frappe.db.sql("""
        SELECT COALESCE(SUM(outstanding_amount), 0) as total_receivable
        FROM `tabSales Invoice`
        WHERE company=%s AND docstatus=1 AND outstanding_amount > 0
    """, (company,), as_dict=True)
    summary["receivables"] = recv[0] if recv else {}

    # Outstanding Payables
    payb = frappe.db.sql("""
        SELECT COALESCE(SUM(outstanding_amount), 0) as total_payable
        FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1 AND outstanding_amount > 0
    """, (company,), as_dict=True)
    summary["payables"] = payb[0] if payb else {}

    # Derived metrics
    total_rev = float(summary["revenue"].get("total_revenue", 0))
    net_rev = float(summary["revenue"].get("net_revenue", 0))
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
    """Compare a metric across two time periods."""
    doctype = params["doctype"]
    field = params["field"]
    agg = params["aggregation"]
    p1_from = params["period1_from"]
    p1_to = params["period1_to"]
    p2_from = params["period2_from"]
    p2_to = params["period2_to"]
    extra = _parse_filters(params.get("extra_filters", {}))
    group_by = params.get("group_by", "")

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
        return {"success": True, "alert_id": doc.name, "message": f"Alert '{params['alert_name']}' created successfully."}
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


def _parse_filters(filters):
    if not filters:
        return {}
    parsed = {}
    for key, value in filters.items():
        parsed[key] = value
    return parsed


# ─── Main Chat Handler ──────────────────────────────────────────────────────

def process_chat(user, question, conversation_history=None):
    """
    Process a user's chat question through the full AI pipeline.
    Uses Claude Opus 4.5 with extended thinking for deep analytical reasoning.
    """
    from .business_context import get_system_prompt

    system_prompt = get_system_prompt(user)
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": question})

    total_input_tokens = 0
    total_output_tokens = 0
    tool_calls_made = 0

    for round_num in range(MAX_TOOL_ROUNDS):
        response = call_claude(messages, system_prompt, tools=ERPNEXT_TOOLS)

        usage = response.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)

        stop_reason = response.get("stop_reason", "")
        content_blocks = response.get("content", [])

        if stop_reason == "tool_use":
            # Claude wants to query data — pass ALL content blocks (including thinking)
            messages.append({"role": "assistant", "content": content_blocks})

            tool_results = []
            for block in content_blocks:
                if block.get("type") == "tool_use":
                    tool_calls_made += 1
                    tool_result = execute_tool(block["name"], block["input"], user)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(tool_result, default=str),
                    })

            messages.append({"role": "user", "content": tool_results})

        elif stop_reason == "end_turn":
            # Extract only text blocks (skip thinking blocks)
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]

            return {
                "response": text_response,
                "tool_calls": tool_calls_made,
                "model": get_model(),
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
            }
        else:
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]
            return {
                "response": text_response or "I wasn't able to complete that request. Please try again.",
                "tool_calls": tool_calls_made,
                "model": get_model(),
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
            }

    return {
        "response": "This query required too many data lookups. Try asking a simpler question.",
        "tool_calls": tool_calls_made,
        "model": get_model(),
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
        },
    }
