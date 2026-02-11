"""
TM AI Assistant — AI Engine
============================
Core AI logic: sends user questions to Claude API with ERPNext tool definitions,
executes data queries, and returns formatted responses.

Architecture:
  User Question → Claude (with tools) → Tool calls → ERPNext queries → Claude (format) → Response
"""

import json
import frappe
import requests
from datetime import datetime


# ─── Configuration ───────────────────────────────────────────────────────────

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 5  # Max back-and-forth tool calls per question


def get_api_key():
    """Get Anthropic API key from site config."""
    key = frappe.conf.get("anthropic_api_key", "")
    if not key:
        frappe.throw("Anthropic API key not configured. Set 'anthropic_api_key' in site_config.json.")
    return key


# ─── Claude API Client ──────────────────────────────────────────────────────

def call_claude(messages, system_prompt, tools=None):
    """Make a single call to Claude API. Returns the full response dict."""
    api_key = get_api_key()

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    resp = requests.post(ANTHROPIC_API_URL, json=payload, headers=headers, timeout=120)

    if resp.status_code != 200:
        error_detail = resp.text[:500]
        frappe.log_error(
            title="Claude API Error",
            message=f"Status {resp.status_code}: {error_detail}"
        )
        frappe.throw(f"AI service error (HTTP {resp.status_code}). Please try again.")

    return resp.json()


# ─── ERPNext Tool Definitions (for Claude tool_use) ─────────────────────────

ERPNEXT_TOOLS = [
    {
        "name": "query_records",
        "description": (
            "Query ERPNext records. Use this to fetch lists of documents like Sales Invoices, "
            "Customers, Items, Stock Entries, etc. Supports filtering, field selection, ordering, "
            "and aggregation. All queries respect the logged-in user's permissions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "ERPNext doctype to query (e.g. 'Sales Invoice', 'Customer', 'Item')"
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to return. Use field names like 'name', 'customer_name', 'grand_total'. "
                        "For aggregation use 'SUM(grand_total) as total', 'COUNT(name) as count'. "
                        "Use ['*'] for all fields."
                    )
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Filter criteria as key-value pairs. Simple: {\"status\": \"Paid\"}. "
                        "With operators: {\"grand_total\": [\">\", 10000], \"posting_date\": [\"between\", [\"2025-01-01\", \"2025-12-31\"]]}. "
                        "Supported operators: =, !=, >, <, >=, <=, like, not like, in, not in, between, is (for null checks)."
                    )
                },
                "order_by": {
                    "type": "string",
                    "description": "Sort order, e.g. 'grand_total desc' or 'posting_date asc'"
                },
                "group_by": {
                    "type": "string",
                    "description": "Group by field for aggregation, e.g. 'customer_name' or 'territory'"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records to return (default 20, max 100)"
                },
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
                "doctype": {
                    "type": "string",
                    "description": "ERPNext doctype to count"
                },
                "filters": {
                    "type": "object",
                    "description": "Filter criteria (same format as query_records)"
                },
            },
            "required": ["doctype"],
        },
    },
    {
        "name": "get_document",
        "description": (
            "Get full details of a specific ERPNext document by its ID/name. "
            "Use this when you know the exact document name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "ERPNext doctype"
                },
                "name": {
                    "type": "string",
                    "description": "Document name/ID"
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific fields to return (optional, returns all if omitted)"
                },
            },
            "required": ["doctype", "name"],
        },
    },
    {
        "name": "run_report",
        "description": (
            "Run a built-in ERPNext report. Common reports: 'Accounts Receivable', "
            "'Accounts Payable', 'General Ledger', 'Stock Balance', 'Sales Analytics', "
            "'Purchase Analytics', 'Gross Profit', 'Item-wise Sales Register'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "report_name": {
                    "type": "string",
                    "description": "Name of the ERPNext report"
                },
                "filters": {
                    "type": "object",
                    "description": "Report-specific filters (e.g. {\"company\": \"...\", \"from_date\": \"...\"})"
                },
            },
            "required": ["report_name"],
        },
    },
]


# ─── Tool Execution ─────────────────────────────────────────────────────────

def execute_tool(tool_name, tool_input, user):
    """Execute an ERPNext tool call and return the result.
    All queries run as the specified user to enforce permissions."""

    # Set the user context for permission enforcement
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
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    except frappe.PermissionError:
        return {"error": "You don't have permission to access this data."}
    except Exception as e:
        frappe.log_error(title=f"AI Tool Error: {tool_name}", message=str(e))
        return {"error": f"Query failed: {str(e)}"}
    finally:
        frappe.set_user(original_user)


def _exec_query_records(params):
    """Execute query_records tool."""
    doctype = params["doctype"]
    fields = params.get("fields", ["name"])
    filters = params.get("filters", {})
    order_by = params.get("order_by", "modified desc")
    group_by = params.get("group_by", "")
    limit = min(params.get("limit", 20), 100)

    # Convert filter format if needed
    parsed_filters = _parse_filters(filters)

    result = frappe.get_list(
        doctype,
        fields=fields,
        filters=parsed_filters,
        order_by=order_by,
        group_by=group_by,
        limit_page_length=limit,
        ignore_ifnull=True,
    )

    return {"data": result, "count": len(result), "doctype": doctype}


def _exec_count_records(params):
    """Execute count_records tool."""
    doctype = params["doctype"]
    filters = _parse_filters(params.get("filters", {}))

    count = frappe.db.count(doctype, filters=filters)
    return {"count": count, "doctype": doctype}


def _exec_get_document(params):
    """Execute get_document tool."""
    doctype = params["doctype"]
    name = params["name"]
    fields = params.get("fields")

    doc = frappe.get_doc(doctype, name)

    if fields:
        result = {f: doc.get(f) for f in fields if doc.get(f) is not None}
    else:
        # Return key fields, skip internal/meta fields
        skip_fields = {"docstatus", "idx", "owner", "modified_by", "creation",
                       "modified", "doctype", "_user_tags", "_comments", "_assign", "_liked_by"}
        result = {k: v for k, v in doc.as_dict().items()
                  if k not in skip_fields and v is not None and not k.startswith("_")}

    return {"document": result, "doctype": doctype, "name": name}


def _exec_run_report(params):
    """Execute run_report tool."""
    report_name = params["report_name"]
    filters = params.get("filters", {})

    result = frappe.call(
        "frappe.desk.query_report.run",
        report_name=report_name,
        filters=filters,
        ignore_prepared_report=True,
    )

    # Trim large results
    columns = result.get("columns", [])
    data = result.get("result", [])[:50]  # Max 50 rows

    return {
        "report": report_name,
        "columns": columns,
        "data": data,
        "total_rows": len(result.get("result", [])),
        "truncated": len(result.get("result", [])) > 50,
    }


def _parse_filters(filters):
    """Parse filter dict into Frappe-compatible format."""
    if not filters:
        return {}

    parsed = {}
    for key, value in filters.items():
        if isinstance(value, list) and len(value) == 2:
            # Operator format: [">=", 1000] or ["between", ["2025-01-01", "2025-12-31"]]
            parsed[key] = value
        else:
            parsed[key] = value

    return parsed


# ─── Main Chat Handler ──────────────────────────────────────────────────────

def process_chat(user, question, conversation_history=None):
    """
    Process a user's chat question through the full AI pipeline.

    Args:
        user: ERPNext username (email)
        question: The user's natural language question
        conversation_history: Previous messages in the conversation (optional)

    Returns:
        dict with 'response' (text), 'data' (structured data if any), 'usage' (token counts)
    """
    from .business_context import get_system_prompt

    system_prompt = get_system_prompt(user)

    # Build messages array
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": question})

    # Tool use loop — Claude may request multiple data queries
    total_input_tokens = 0
    total_output_tokens = 0
    tool_calls_made = 0

    for round_num in range(MAX_TOOL_ROUNDS):
        response = call_claude(messages, system_prompt, tools=ERPNEXT_TOOLS)

        # Track usage
        usage = response.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)

        stop_reason = response.get("stop_reason", "")
        content_blocks = response.get("content", [])

        if stop_reason == "tool_use":
            # Claude wants to query data — execute each tool call
            assistant_content = content_blocks
            messages.append({"role": "assistant", "content": assistant_content})

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
            # Claude has the final answer
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]

            return {
                "response": text_response,
                "tool_calls": tool_calls_made,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
            }

        else:
            # Unexpected stop reason
            text_response = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text_response += block["text"]

            return {
                "response": text_response or "I wasn't able to complete that request. Please try again.",
                "tool_calls": tool_calls_made,
                "usage": {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                },
            }

    # Max rounds exceeded
    return {
        "response": "This query required too many data lookups. Try asking a simpler question.",
        "tool_calls": tool_calls_made,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
        },
    }
