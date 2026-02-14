"""
AskERP Custom Tool — No-Code Tool Builder for AI Assistant
==========================================================
Allows admins to create new AI capabilities from the ERPNext UI.
The AI auto-discovers enabled tools and uses them when relevant.
"""

import json
import re
import time

import frappe
from frappe.model.document import Document


# SQL keywords that are never allowed in custom tool queries
DANGEROUS_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "INTO OUTFILE", "INTO DUMPFILE", "LOAD_FILE",
]

# Tables that must never be queried by custom tools
SENSITIVE_TABLES = [
    "tabUser", "tab__Auth", "tabUser Permission", "tabOAuth",
    "tabAPI Key", "tabToken", "tabSession", "tabOAuth Bearer Token",
    "tabOAuth Client", "tabOAuth Authorization Code",
]


class AskERPCustomTool(Document):
    """Custom Tool doctype for no-code AI tool building."""

    def validate(self):
        self._validate_tool_name()
        self._validate_parameters()
        self._validate_query_config()
        self._validate_sql_safety()

    def _validate_tool_name(self):
        """Enforce snake_case naming for tool_name."""
        if not self.tool_name:
            return
        if not re.match(r"^[a-z][a-z0-9_]*$", self.tool_name):
            frappe.throw(
                "Tool Name must be snake_case (lowercase letters, numbers, underscores). "
                "Example: check_customer_credit"
            )
        # Block names that conflict with built-in tools
        builtin_names = [
            "query_records", "count_records", "get_document", "run_report",
            "run_sql_query", "get_financial_summary", "compare_periods",
            "create_alert", "list_alerts", "delete_alert",
            "export_pdf", "export_excel", "generate_chart",
            "create_draft_document", "execute_workflow_action",
            "schedule_report", "save_user_preference",
        ]
        if self.tool_name in builtin_names:
            frappe.throw(f"Tool name '{self.tool_name}' conflicts with a built-in tool. Choose a different name.")

    def _validate_parameters(self):
        """Validate parameter definitions."""
        if not self.parameters:
            return
        seen_names = set()
        for param in self.parameters:
            if not param.param_name:
                continue
            # Enforce snake_case
            if not re.match(r"^[a-z][a-z0-9_]*$", param.param_name):
                frappe.throw(
                    f"Parameter '{param.param_name}' must be snake_case. "
                    "Example: customer_name"
                )
            # Check for duplicates
            if param.param_name in seen_names:
                frappe.throw(f"Duplicate parameter name: {param.param_name}")
            seen_names.add(param.param_name)
            # Validate select options
            if param.param_type == "Select" and not param.select_options:
                frappe.throw(
                    f"Parameter '{param.param_name}' is a Select type but has no options defined."
                )

    def _validate_query_config(self):
        """Validate query configuration based on query type."""
        if self.query_type == "Frappe ORM":
            if not self.query_doctype:
                frappe.throw("Doctype is required for Frappe ORM query type.")
            # Verify doctype exists
            if not frappe.db.exists("DocType", self.query_doctype):
                frappe.throw(f"Doctype '{self.query_doctype}' does not exist in ERPNext.")
            # Validate filters template JSON
            if self.query_filters_template:
                try:
                    json.loads(self.query_filters_template)
                except json.JSONDecodeError as e:
                    frappe.throw(f"Filters Template is not valid JSON: {str(e)}")

        elif self.query_type == "Raw SQL":
            if not self.query_sql:
                frappe.throw("SQL Query is required for Raw SQL query type.")

        elif self.query_type == "API Method":
            if not self.query_method:
                frappe.throw("API Method path is required for API Method query type.")
            # Basic dotted path validation
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]+$", self.query_method):
                frappe.throw("API Method must be a valid dotted Python path.")

    def _validate_sql_safety(self):
        """Enforce SQL safety for Raw SQL queries."""
        if self.query_type != "Raw SQL" or not self.query_sql:
            return

        sql_upper = self.query_sql.upper().strip()

        # Must start with SELECT
        if not sql_upper.startswith("SELECT"):
            frappe.throw("Only SELECT queries are allowed. No INSERT, UPDATE, DELETE, etc.")

        # Check for dangerous keywords
        for kw in DANGEROUS_SQL_KEYWORDS:
            pattern = rf"\b{kw}\b"
            if re.search(pattern, sql_upper):
                frappe.throw(f"Dangerous SQL keyword '{kw}' detected. Only read-only SELECT queries are allowed.")

        # Check for sensitive tables
        sql_lower = self.query_sql.lower()
        for tbl in SENSITIVE_TABLES:
            if tbl.lower() in sql_lower:
                frappe.throw(f"Access to '{tbl}' is restricted for security reasons.")

        # If is_read_only is set, enforce it
        if self.is_read_only:
            # Already checked above, but belt-and-suspenders
            pass

    # ─── Test Method (whitelisted for client script) ──────────────────

    @frappe.whitelist()
    def test_tool(self, test_params=None):
        """
        Test this tool with sample parameters. Called from the Test Panel.
        Returns the raw query output + timing info.
        """
        if not test_params:
            test_params = {}

        if isinstance(test_params, str):
            try:
                test_params = json.loads(test_params)
            except json.JSONDecodeError:
                return {"error": "Invalid test parameters JSON."}

        # Import the executor
        from askerp.custom_tools import execute_custom_tool

        start_time = time.time()
        try:
            result = execute_custom_tool(self.tool_name, test_params, frappe.session.user)
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "success": True,
                "result": result,
                "elapsed_ms": elapsed_ms,
                "query_type": self.query_type,
            }
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "error": str(e)[:500],
                "elapsed_ms": elapsed_ms,
            }
