"""
AskERP Custom Tools — Pre-Built Tool Templates
===============================================
Phase 4, Task 4.5: Ship 8 ready-to-use tools that work out of the box.
Created during after_install and can be customized by admins.

v2.0 Changes (Hardcoded Dependency Removal):
- Replaced 340 lines of hardcoded SQL with dynamic generation via schema_utils.
- All SQL table names, workflow states, and field references are now resolved
  at runtime from live ERPNext metadata.
- Tools whose target doctypes don't exist are automatically excluded.
- Pending approvals tool uses dynamically discovered workflow states.
"""

from askerp.schema_utils import build_default_tools


def get_default_tools():
    """
    Return the list of default tool definitions with dynamically generated SQL.

    Called by:
    - install.py (after_install) to seed AskERP Custom Tool records
    - Any module that needs the default tool definitions

    Each tool dict contains: tool_name, display_name, description, category,
    enabled, is_read_only, requires_approval, query_type, query_sql,
    query_limit, output_format, parameters.
    """
    return build_default_tools()


# For backward compatibility — install.py imports DEFAULT_CUSTOM_TOOLS directly
DEFAULT_CUSTOM_TOOLS = build_default_tools()
