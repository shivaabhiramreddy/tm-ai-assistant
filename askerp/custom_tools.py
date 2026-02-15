"""
AskERP Custom Tools — Discovery + Execution Engine
====================================================
Phase 4 of commercialization: No-Code Tool Builder.

This module:
1. Discovers all enabled AskERP Custom Tools and converts them
   into Claude-compatible tool definitions.
2. Executes custom tool calls from the AI, mapping parameters
   to ORM queries, raw SQL, or API method calls.
3. Enforces SQL safety, role-based access, and query limits.

Called by ai_engine.py at runtime to dynamically extend
the AI's capabilities without code changes.
"""

import json
import re
import time
from datetime import datetime

import frappe


# ─── Sensitive tables that custom tools can NEVER query ──────────────────────

SENSITIVE_TABLES = [
    "tabUser", "tab__Auth", "tabUser Permission", "tabOAuth",
    "tabAPI Key", "tabToken", "tabSession", "tabOAuth Bearer Token",
    "tabOAuth Client", "tabOAuth Authorization Code",
    "tab__UserSettings", "tabUser Social Login",
]

# SQL keywords that are NEVER allowed in custom tool queries
DANGEROUS_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE",
    "BENCHMARK", "SLEEP",
]


# ─── Tool Discovery: Convert custom tools to AI tool definitions ─────────────

def get_custom_tool_definitions(user=None):
    """
    Fetch all enabled AskERP Custom Tools and convert them into
    the tool definition format expected by Claude's tool_use API.

    Args:
        user: The logged-in user (for role-based filtering)

    Returns:
        list: Tool definition dicts ready for Claude's tools parameter
    """
    cache_key = "askerp_custom_tools_defs"
    cached = frappe.cache().get_value(cache_key)

    if cached is not None:
        # Filter by role after cache retrieval (roles are per-user)
        return _filter_tools_by_role(cached, user)

    # Fetch all enabled tools with their child parameters
    tools = frappe.get_all(
        "AskERP Custom Tool",
        filters={"enabled": 1},
        fields=[
            "name", "tool_name", "display_name", "description",
            "category", "query_type", "is_read_only", "requires_approval",
            "allowed_roles",
        ],
        order_by="category asc, tool_name asc",
    )

    definitions = []
    for tool in tools:
        # Fetch parameters for this tool
        params = frappe.get_all(
            "AskERP Tool Parameter",
            filters={"parent": tool.name, "parenttype": "AskERP Custom Tool"},
            fields=[
                "param_name", "param_type", "param_description",
                "required", "default_value", "select_options",
            ],
            order_by="idx asc",
        )

        # Build the input_schema
        properties = {}
        required_params = []

        for p in params:
            prop = {
                "description": p.param_description or p.param_name,
            }
            # Map param_type to JSON Schema type
            if p.param_type == "Number":
                prop["type"] = "number"
            elif p.param_type == "Boolean":
                prop["type"] = "boolean"
            elif p.param_type == "Date":
                prop["type"] = "string"
                prop["description"] += " (YYYY-MM-DD format)"
            elif p.param_type == "Select" and p.select_options:
                prop["type"] = "string"
                prop["enum"] = [o.strip() for o in p.select_options.split(",")]
            else:
                prop["type"] = "string"

            properties[p.param_name] = prop

            if p.required:
                required_params.append(p.param_name)

        # Build the tool definition
        tool_def = {
            "name": tool.tool_name,
            "description": tool.description or tool.display_name,
            "input_schema": {
                "type": "object",
                "properties": properties,
            },
            # Store metadata for execution (not sent to Claude)
            "_custom_tool": True,
            "_tool_doc_name": tool.name,
            "_allowed_roles": tool.allowed_roles or "",
            "_requires_approval": tool.requires_approval,
        }

        if required_params:
            tool_def["input_schema"]["required"] = required_params

        definitions.append(tool_def)

    # Cache for 30 seconds (tools change rarely, cache short for responsiveness)
    frappe.cache().set_value(cache_key, definitions, expires_in_sec=30)

    return _filter_tools_by_role(definitions, user)


def _filter_tools_by_role(tool_defs, user=None):
    """Filter tool definitions based on the user's roles."""
    if not user:
        return tool_defs

    user_roles = frappe.get_roles(user)

    filtered = []
    for td in tool_defs:
        allowed_roles = td.get("_allowed_roles", "")
        if not allowed_roles:
            # No role restriction — everyone can use it
            filtered.append(td)
            continue

        # Parse comma-separated roles
        allowed = [r.strip() for r in allowed_roles.split(",") if r.strip()]
        if any(role in user_roles for role in allowed):
            filtered.append(td)

    return filtered


def get_clean_tool_definitions(user=None):
    """
    Get tool definitions cleaned of internal metadata fields.
    This is what gets sent to Claude's API.
    """
    raw = get_custom_tool_definitions(user)
    clean = []
    for td in raw:
        clean_td = {
            "name": td["name"],
            "description": td["description"],
            "input_schema": td["input_schema"],
        }
        clean.append(clean_td)
    return clean


# ─── Tool Execution ──────────────────────────────────────────────────────────

def execute_custom_tool(tool_name, tool_input, user):
    """
    Execute a custom tool call from the AI.

    Args:
        tool_name: The tool_name (snake_case identifier)
        tool_input: Dict of parameter values from the AI
        user: The logged-in user (queries run as this user)

    Returns:
        dict: Result data or error message
    """
    start_time = time.time()
    error_occurred = False

    try:
        # Fetch the tool configuration
        tool_doc = _get_tool_doc(tool_name)
        if not tool_doc:
            return {"error": f"Custom tool '{tool_name}' not found or is disabled."}

        # Check role access
        if not _check_role_access(tool_doc, user):
            return {"error": "You don't have permission to use this tool."}

        # Check approval requirement
        if tool_doc.requires_approval:
            return {
                "requires_approval": True,
                "message": (
                    f"The tool '{tool_doc.display_name}' requires admin approval before execution. "
                    "Please ask your administrator to approve this action."
                ),
            }

        # Apply default values for missing optional params
        tool_input = _apply_defaults(tool_doc, tool_input)

        # Execute based on query type
        if tool_doc.query_type == "Frappe ORM":
            result = _execute_orm_query(tool_doc, tool_input, user)
        elif tool_doc.query_type == "Raw SQL":
            result = _execute_sql_query(tool_doc, tool_input, user)
        elif tool_doc.query_type == "API Method":
            result = _execute_api_method(tool_doc, tool_input, user)
        else:
            result = {"error": f"Unknown query type: {tool_doc.query_type}"}

        # Format output
        if "error" not in result:
            result = _format_output(tool_doc, result, tool_input)

        return result

    except frappe.PermissionError:
        error_occurred = True
        return {"error": "You don't have permission to access this data."}
    except Exception as e:
        error_occurred = True
        frappe.log_error(
            title=f"Custom Tool Error: {tool_name}",
            message=f"Input: {json.dumps(tool_input, default=str)[:500]}\nError: {str(e)}"
        )
        return {"error": f"Tool execution failed: {str(e)[:200]}"}
    finally:
        # Update usage stats
        elapsed_ms = int((time.time() - start_time) * 1000)
        _update_tool_stats(tool_name, elapsed_ms, error_occurred)


# ─── Internal Helpers ─────────────────────────────────────────────────────────

def _get_tool_doc(tool_name):
    """Fetch the tool document by tool_name. Returns None if not found/disabled."""
    cache_key = f"askerp_custom_tool_{tool_name}"
    cached = frappe.cache().get_value(cache_key)

    if cached == "__none__":
        return None
    if cached is not None:
        return cached

    try:
        doc = frappe.get_doc("AskERP Custom Tool", tool_name)
        if not doc.enabled:
            frappe.cache().set_value(cache_key, "__none__", expires_in_sec=30)
            return None
        frappe.cache().set_value(cache_key, doc, expires_in_sec=30)
        return doc
    except frappe.DoesNotExistError:
        frappe.cache().set_value(cache_key, "__none__", expires_in_sec=30)
        return None


def _check_role_access(tool_doc, user):
    """Check if the user has a role that's allowed to use this tool."""
    if not tool_doc.allowed_roles:
        return True  # No restriction

    allowed = [r.strip() for r in tool_doc.allowed_roles.split(",") if r.strip()]
    if not allowed:
        return True

    user_roles = frappe.get_roles(user)
    return any(role in user_roles for role in allowed)


def _apply_defaults(tool_doc, tool_input):
    """Apply default values for parameters not provided by the AI."""
    if not tool_doc.parameters:
        return tool_input

    result = dict(tool_input)
    for param in tool_doc.parameters:
        if param.param_name not in result and param.default_value:
            result[param.param_name] = param.default_value
    return result


# ─── Frappe ORM Execution ────────────────────────────────────────────────────

def _execute_orm_query(tool_doc, params, user):
    """Execute a Frappe ORM query."""
    doctype = tool_doc.query_doctype
    limit = min(tool_doc.query_limit or 50, 500)

    # Parse fields
    fields = ["name"]
    if tool_doc.query_fields:
        raw_fields = [f.strip() for f in tool_doc.query_fields.split(",") if f.strip()]
        if raw_fields:
            fields = raw_fields

    # Build filters from template
    filters = {}
    if tool_doc.query_filters_template:
        try:
            template_str = tool_doc.query_filters_template
            # Replace {{param}} placeholders with actual values
            for key, value in params.items():
                template_str = template_str.replace("{{" + key + "}}", str(value))

            # Remove any unreplaced placeholders (set to empty string)
            template_str = re.sub(r"\{\{[^}]+\}\}", '""', template_str)

            filters = json.loads(template_str)
        except (json.JSONDecodeError, Exception) as e:
            return {"error": f"Filter template error: {str(e)[:200]}"}

    # Execute as the requesting user (respects permissions)
    original_user = frappe.session.user
    try:
        frappe.set_user(user)

        # Check if fields contain aggregations
        has_aggregation = any(
            agg in f.upper() for f in fields
            for agg in ["SUM(", "COUNT(", "AVG(", "MAX(", "MIN("]
        )

        if has_aggregation:
            # Use frappe.db.sql for aggregation queries
            field_str = ", ".join(fields)
            conditions = _build_where_clause(filters)
            sql = f"SELECT {field_str} FROM `tab{doctype}` WHERE {conditions} LIMIT {limit}"
            data = frappe.db.sql(sql, as_dict=True)
        else:
            data = frappe.get_all(
                doctype,
                filters=filters,
                fields=fields,
                limit_page_length=limit,
                order_by="modified desc",
            )

        return {"data": data, "count": len(data), "doctype": doctype}
    finally:
        frappe.set_user(original_user)


def _build_where_clause(filters):
    """Convert Frappe-style filters dict to SQL WHERE clause."""
    if not filters:
        return "1=1"

    conditions = []
    for key, value in filters.items():
        if isinstance(value, list) and len(value) == 2:
            operator, operand = value
            if operator.lower() == "between" and isinstance(operand, list):
                conditions.append(
                    f"`{key}` BETWEEN '{_sanitize_value(operand[0])}' AND '{_sanitize_value(operand[1])}'"
                )
            elif operator.lower() in ("in", "not in") and isinstance(operand, list):
                vals = ", ".join([f"'{_sanitize_value(v)}'" for v in operand])
                conditions.append(f"`{key}` {operator} ({vals})")
            else:
                conditions.append(f"`{key}` {operator} '{_sanitize_value(operand)}'")
        else:
            conditions.append(f"`{key}` = '{_sanitize_value(value)}'")

    return " AND ".join(conditions) if conditions else "1=1"


def _sanitize_value(value):
    """Sanitize a value for safe SQL interpolation."""
    if value is None:
        return ""
    s = str(value)
    # Remove SQL injection vectors
    s = s.replace("'", "''")  # Escape single quotes
    s = s.replace("\\", "\\\\")
    s = s.replace(";", "")
    s = s.replace("--", "")
    return s


# ─── Raw SQL Execution ───────────────────────────────────────────────────────

def _execute_sql_query(tool_doc, params, user):
    """Execute a raw SQL query with parameterized inputs."""
    sql = tool_doc.query_sql
    if not sql:
        return {"error": "No SQL query defined."}

    limit = min(tool_doc.query_limit or 50, 500)

    # ── Safety checks ──
    sql_upper = sql.upper().strip()

    # Must be SELECT only
    if not sql_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed."}

    # Check dangerous keywords
    for kw in DANGEROUS_SQL_KEYWORDS:
        pattern = rf"\b{kw}\b"
        if re.search(pattern, sql_upper):
            return {"error": f"Dangerous SQL keyword '{kw}' blocked."}

    # Check sensitive tables
    sql_lower = sql.lower()
    for tbl in SENSITIVE_TABLES:
        if tbl.lower() in sql_lower:
            return {"error": f"Access to '{tbl}' is restricted."}

    # Auto-append LIMIT if not present
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";") + f" LIMIT {limit}"

    # ── Parameterize ──
    # Convert params to the format frappe.db.sql expects: %(param_name)s
    safe_params = {}
    for key, value in params.items():
        # Type coercion based on parameter definition
        param_def = _get_param_def(tool_doc, key)
        if param_def and param_def.param_type == "Number":
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass
        safe_params[key] = value

    # Execute as the requesting user
    original_user = frappe.session.user
    try:
        frappe.set_user(user)

        # Set a 30-second timeout for safety
        frappe.db.sql("SET SESSION max_statement_time = 30")  # 30s timeout (MariaDB syntax)
        data = frappe.db.sql(sql, safe_params, as_dict=True)
        frappe.db.sql("SET SESSION max_statement_time = 0")  # Reset to default

        truncated = len(data) > limit
        data = data[:limit]

        return {"data": data, "count": len(data), "truncated": truncated}
    except Exception as e:
        try:
            frappe.db.sql("SET SESSION max_statement_time = 0")
        except Exception:
            pass
        raise
    finally:
        frappe.set_user(original_user)


# ─── API Method Execution ────────────────────────────────────────────────────

def _execute_api_method(tool_doc, params, user):
    """Execute a whitelisted Python method."""
    method_path = tool_doc.query_method
    if not method_path:
        return {"error": "No API method defined."}

    # Security: only allow methods from askerp module or whitelisted
    if not (
        method_path.startswith("askerp.")
        or method_path.startswith("frappe.client.")
        or _is_whitelisted_method(method_path)
    ):
        return {
            "error": (
                "API methods must be within askerp module or be "
                "whitelisted Frappe methods. Custom methods from other apps "
                "are not allowed for security reasons."
            )
        }

    # Execute as the requesting user
    original_user = frappe.session.user
    try:
        frappe.set_user(user)

        # Import and call the method
        module_path, method_name = method_path.rsplit(".", 1)
        module = frappe.get_module(module_path)
        method = getattr(module, method_name)

        result = method(**params)

        # Normalize result
        if isinstance(result, (list, tuple)):
            return {"data": list(result), "count": len(result)}
        elif isinstance(result, dict):
            return result
        else:
            return {"data": result}
    finally:
        frappe.set_user(original_user)


def _is_whitelisted_method(method_path):
    """Check if a method is whitelisted in ERPNext."""
    try:
        module_path, method_name = method_path.rsplit(".", 1)
        module = frappe.get_module(module_path)
        method = getattr(module, method_name, None)
        return method and getattr(method, "is_whitelisted", False)
    except Exception:
        return False


# ─── Output Formatting ───────────────────────────────────────────────────────

def _format_output(tool_doc, result, params):
    """Format tool output based on the configured output format."""
    fmt = tool_doc.output_format or "Table"

    if "error" in result:
        return result

    data = result.get("data", [])

    if fmt == "JSON":
        return result

    elif fmt == "Summary":
        # Convert to a summary string
        if isinstance(data, list) and len(data) > 0:
            if len(data) == 1:
                row = data[0]
                summary = ", ".join([f"{k}: {v}" for k, v in row.items()])
                result["summary"] = summary
            else:
                result["summary"] = f"{len(data)} records found."
        return result

    elif fmt == "Custom" and tool_doc.output_template:
        try:
            rendered = frappe.render_template(
                tool_doc.output_template,
                {"results": data, "count": len(data) if isinstance(data, list) else 0, "params": params},
            )
            result["formatted"] = rendered
        except Exception as e:
            result["format_error"] = str(e)[:200]
        return result

    else:
        # Default: Table format — return as-is (AI handles table presentation)
        return result


# ─── Stats Tracking ──────────────────────────────────────────────────────────

def _update_tool_stats(tool_name, elapsed_ms, error_occurred):
    """Update usage statistics on the tool document."""
    try:
        # Use set_value to avoid reloading the full document
        current = frappe.db.get_value(
            "AskERP Custom Tool", tool_name,
            ["usage_count", "avg_response_time_ms", "error_count"],
            as_dict=True,
        )
        if not current:
            return

        new_count = (current.usage_count or 0) + 1
        old_avg = current.avg_response_time_ms or 0
        # Running average
        new_avg = int(((old_avg * (new_count - 1)) + elapsed_ms) / new_count)
        new_errors = (current.error_count or 0) + (1 if error_occurred else 0)

        frappe.db.set_value(
            "AskERP Custom Tool", tool_name,
            {
                "usage_count": new_count,
                "avg_response_time_ms": new_avg,
                "error_count": new_errors,
                "last_used": frappe.utils.now_datetime(),
            },
            update_modified=False,
        )
    except Exception:
        pass  # Stats are nice-to-have, don't fail the tool execution


def _get_param_def(tool_doc, param_name):
    """Get the parameter definition for a given param name."""
    if not tool_doc.parameters:
        return None
    for p in tool_doc.parameters:
        if p.param_name == param_name:
            return p
    return None


# ─── Cache Invalidation ─────────────────────────────────────────────────────

def clear_custom_tool_cache(doc=None, method=None):
    """Clear cached tool definitions when a tool is saved/deleted."""
    frappe.cache().delete_value("askerp_custom_tools_defs")
    if doc and hasattr(doc, "tool_name"):
        frappe.cache().delete_value(f"askerp_custom_tool_{doc.tool_name}")
