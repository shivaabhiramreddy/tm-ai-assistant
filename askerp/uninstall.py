"""
AskERP — Clean Uninstall Handler
======================================
Removes AskERP's footprint from the ERPNext site when the app is uninstalled.

Called automatically via hooks.py after_uninstall, or manually via bench console:

    from askerp.uninstall import after_uninstall
    after_uninstall()

What this script does:
  1. Removes custom fields added to the User doctype (allow_ai_chat, custom_ai_preferences)
  2. Removes Custom Field records created via fixtures
  3. Clears all AskERP Redis cache entries
  4. Clears all AskERP Notification Logs

What Frappe handles automatically (we do NOT need to do):
  - Dropping AskERP's own doctype tables (AI Chat Session, AI Usage Log, etc.)
  - Removing AskERP module entry
  - Removing scheduled job entries
  - Removing app_include_js/css (hooks are gone after uninstall)

Note: AskERP's own doctypes (AskERP Settings, AskERP Business Profile, AI Usage Log,
AI Chat Session, AI Alert Rule, AI Scheduled Report, etc.) are automatically deleted
by Frappe's `bench uninstall-app` command — it drops the corresponding database tables.
We only need to clean up things that live OUTSIDE our own tables.
"""

import frappe


def after_uninstall():
    """Main entry point called by hooks.py after app uninstall."""
    _remove_custom_fields_from_user()
    _clear_all_caches()
    _clear_notification_logs()
    frappe.db.commit()
    print("AskERP: Cleanup complete. All custom fields, caches, and notifications removed.")


def _remove_custom_fields_from_user():
    """
    Remove the custom fields AskERP added to the User doctype.

    These fields are:
      - allow_ai_chat: Check field that gates AI access per user
      - custom_ai_preferences: JSON store for user-specific AI preferences

    Without removing these, the User form would show orphan fields after uninstall.
    """
    fields_to_remove = ["allow_ai_chat", "custom_ai_preferences"]

    for fieldname in fields_to_remove:
        # Custom Field naming convention in Frappe: "{doctype}-{fieldname}"
        cf_name = f"User-{fieldname}"
        if frappe.db.exists("Custom Field", cf_name):
            frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
            print(f"  Removed Custom Field: {cf_name}")
        else:
            print(f"  Custom Field {cf_name} not found — skipping.")

    # Also clear any Custom Field records that might have different naming
    # (e.g., if created via API with auto-name instead of standard naming)
    orphan_fields = frappe.get_all(
        "Custom Field",
        filters={
            "dt": "User",
            "fieldname": ["in", fields_to_remove],
        },
        pluck="name",
    )
    for cf_name in orphan_fields:
        frappe.delete_doc("Custom Field", cf_name, force=True, ignore_permissions=True)
        print(f"  Removed orphan Custom Field: {cf_name}")


def _clear_all_caches():
    """
    Clear all Redis cache entries created by AskERP.

    AskERP uses these cache key patterns:
      - askerp_business_profile     — Business profile singleton cache
      - askerp_setup_complete       — Setup wizard completion flag
      - askerp_custom_tools_defs    — All custom tool definitions
      - askerp_custom_tool_{name}   — Individual custom tool cache
      - askerp_prompt_template_{t}  — Prompt templates per tier
      - askerp_settings_cache       — Settings cache
      - askerp:credit_exhausted:*   — Credit exhaustion status per provider
      - askerp:credit_notified:*    — Credit notification dedup
      - askerp_stream:*             — Streaming response data
      - askerp_cache:*              — Query cache entries (query_cache.py)
      - askerp_cache_index          — Query cache index
    """
    # Known fixed cache keys
    fixed_keys = [
        "askerp_business_profile",
        "askerp_setup_complete",
        "askerp_custom_tools_defs",
        "askerp_settings_cache",
        "askerp_cache_index",
    ]

    for key in fixed_keys:
        try:
            frappe.cache().delete_value(key)
        except Exception:
            pass

    # Dynamic cache keys — clear by pattern using Redis SCAN
    # This catches all askerp_custom_tool_*, askerp_prompt_template_*,
    # askerp:credit_*, askerp_stream:*, askerp_cache:* keys
    _clear_cache_by_pattern("askerp_custom_tool_*")
    _clear_cache_by_pattern("askerp_prompt_template_*")
    _clear_cache_by_pattern("askerp:credit_*")
    _clear_cache_by_pattern("askerp_stream:*")
    _clear_cache_by_pattern("askerp_cache:*")

    print("  All AskERP cache entries cleared.")


def _clear_cache_by_pattern(pattern):
    """
    Delete all Redis keys matching a glob pattern.

    Uses Redis SCAN (cursor-based iteration) instead of KEYS to avoid
    blocking the Redis server on large datasets.
    """
    try:
        redis_client = frappe.cache().get_client()
        if not redis_client:
            return

        # Frappe prefixes all cache keys with the site name
        # e.g., "mysite.com|askerp_business_profile"
        site = frappe.local.site
        full_pattern = f"{site}|{pattern}"

        cursor = 0
        deleted = 0
        while True:
            cursor, keys = redis_client.scan(cursor=cursor, match=full_pattern, count=100)
            if keys:
                redis_client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break

        if deleted:
            print(f"  Cleared {deleted} cache keys matching '{pattern}'")
    except Exception:
        # Redis might not be available in test environments
        pass


def _clear_notification_logs():
    """
    Remove Notification Log entries created by AskERP's alert system.

    AskERP creates notification logs with subject containing 'AskERP'
    when alerts trigger or when credit exhaustion is detected.
    These become orphaned after uninstall.
    """
    try:
        count = frappe.db.count(
            "Notification Log",
            filters={"subject": ["like", "%AskERP%"]},
        )
        if count:
            frappe.db.delete(
                "Notification Log",
                filters={"subject": ["like", "%AskERP%"]},
            )
            print(f"  Removed {count} AskERP notification log entries.")
        else:
            print("  No AskERP notification logs found.")
    except Exception:
        # Notification Log might not exist in some Frappe versions
        print("  Could not clean notification logs — skipping.")
