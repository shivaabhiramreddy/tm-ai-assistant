"""
AskERP — Query Result Cache
======================================
Caches tool execution results in Redis to avoid redundant AI API calls
and expensive database queries for identical questions.

How it works:
  1. Before executing a tool, compute a cache key from (tool_name, tool_input)
  2. Check Redis — if cached result exists and TTL hasn't expired, return it
  3. If not cached, execute the tool, cache the result, return it

Cache invalidation:
  - TTL-based: entries auto-expire after cache_ttl_minutes
  - Manual: clear_all_cache() wipes everything (called on data-changing events)
  - Size-based: LRU eviction when cache_max_entries exceeded

Configuration (AskERP Settings):
  - enable_query_cache: master switch
  - cache_ttl_minutes: per-entry TTL (default 15)
  - cache_max_entries: max entries before eviction (default 500)
"""

import json
import hashlib
import frappe


# Redis key prefix for all AI query cache entries
_CACHE_PREFIX = "askerp_cache:"
# Redis key for the cache index (tracks all active keys for eviction)
_INDEX_KEY = "askerp_cache_index"


def _get_settings():
    """Get cache settings. Returns (enabled, ttl_seconds, max_entries)."""
    try:
        settings = frappe.get_cached_doc("AskERP Settings")
        enabled = bool(settings.enable_query_cache)
        ttl = max(0, int(settings.cache_ttl_minutes or 15)) * 60  # Convert to seconds
        max_entries = max(10, int(settings.cache_max_entries or 500))
        return enabled, ttl, max_entries
    except Exception:
        return False, 900, 500  # Disabled by default if settings unavailable


def _make_cache_key(tool_name, tool_input):
    """
    Generate a deterministic cache key from tool name + input.
    Uses SHA256 to keep keys short and avoid special characters.
    """
    # Normalize the input by sorting keys for deterministic hashing
    normalized = json.dumps({"tool": tool_name, "input": tool_input},
                            sort_keys=True, default=str)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{_CACHE_PREFIX}{tool_name}:{digest}"


# ─── Tools that should NEVER be cached ──────────────────────────────────────
# Write operations, user-specific state, and real-time tools
_UNCACHEABLE_TOOLS = {
    "create_alert", "delete_alert", "export_pdf", "export_excel",
    "create_draft_document", "execute_workflow_action",
    "schedule_report", "save_user_preference",
}

# Tools that are safe to cache (read-only data queries)
_CACHEABLE_TOOLS = {
    "query_records", "count_records", "get_document", "run_report",
    "run_sql_query", "get_financial_summary", "compare_periods",
    "list_alerts", "generate_chart",
}


def get_cached_result(tool_name, tool_input):
    """
    Check if a cached result exists for this tool call.
    Returns the cached result dict, or None if not cached.
    """
    if tool_name in _UNCACHEABLE_TOOLS:
        return None
    if tool_name not in _CACHEABLE_TOOLS:
        return None

    enabled, _ttl, _max = _get_settings()
    if not enabled:
        return None

    key = _make_cache_key(tool_name, tool_input)
    try:
        cached = frappe.cache.get_value(key)
        if cached:
            result = json.loads(cached) if isinstance(cached, str) else cached
            if isinstance(result, dict):
                result["_from_cache"] = True
                return result
    except Exception:
        pass  # Cache miss — proceed to execute

    return None


def set_cached_result(tool_name, tool_input, result):
    """
    Cache a tool result in Redis with the configured TTL.
    Manages the cache index for LRU eviction.
    """
    if tool_name in _UNCACHEABLE_TOOLS:
        return
    if tool_name not in _CACHEABLE_TOOLS:
        return
    if not isinstance(result, dict):
        return
    # Don't cache errors
    if result.get("error"):
        return

    enabled, ttl, max_entries = _get_settings()
    if not enabled or ttl <= 0:
        return

    key = _make_cache_key(tool_name, tool_input)
    try:
        # Store the result
        frappe.cache.set_value(key, json.dumps(result, default=str), expires_in_sec=ttl)

        # Update cache index (simple list of active keys)
        _update_index(key, max_entries)
    except Exception as e:
        # Cache write failure is non-critical
        frappe.logger("askerp").debug(f"Cache write failed: {e}")


def _update_index(new_key, max_entries):
    """
    Maintain a bounded index of cached keys.
    Evicts oldest entries when max_entries is exceeded.
    """
    try:
        raw = frappe.cache.get_value(_INDEX_KEY)
        index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

        # Remove this key if it already exists (move to end = most recent)
        if new_key in index:
            index.remove(new_key)
        index.append(new_key)

        # Evict oldest entries if over limit
        while len(index) > max_entries:
            old_key = index.pop(0)
            try:
                frappe.cache.delete_value(old_key)
            except Exception:
                pass

        # Save updated index (no TTL — lives as long as the cache has entries)
        frappe.cache.set_value(_INDEX_KEY, json.dumps(index))
    except Exception:
        pass  # Index maintenance is best-effort


def get_cache_stats():
    """
    Get cache statistics for the admin dashboard.
    Returns: {total_entries, estimated_memory_kb}
    """
    try:
        raw = frappe.cache.get_value(_INDEX_KEY)
        index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

        # Count how many are still alive
        alive = 0
        for key in index:
            if frappe.cache.get_value(key) is not None:
                alive += 1

        return {
            "total_entries": alive,
            "index_size": len(index),
        }
    except Exception:
        return {"total_entries": 0, "index_size": 0}


def clear_all_cache():
    """
    Clear all cached query results. Called when:
    - Admin explicitly clears cache
    - Data-changing doctypes are saved (configurable)
    """
    try:
        raw = frappe.cache.get_value(_INDEX_KEY)
        index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

        for key in index:
            try:
                frappe.cache.delete_value(key)
            except Exception:
                pass

        frappe.cache.delete_value(_INDEX_KEY)
        return {"success": True, "cleared": len(index)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def clear_cache_for_doctype(doc, method=None):
    """
    Clear cached results that reference a specific doctype.
    Called by doc_events hooks when data changes.
    Frappe passes (doc, method) — we extract the doctype from doc.
    """
    doctype = doc.doctype if hasattr(doc, "doctype") else str(doc)
    try:
        raw = frappe.cache.get_value(_INDEX_KEY)
        index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

        # The cache key contains the tool name, but we need to check
        # if any key references this doctype. Since keys are hashed,
        # we can only do a prefix-based clear for known tool patterns.
        # For efficiency, we clear all entries that start with query tools
        # when a core business doctype changes.
        core_doctypes = {
            "Sales Invoice", "Sales Order", "Purchase Invoice", "Purchase Order",
            "Payment Entry", "Stock Entry", "Delivery Note", "Customer", "Supplier",
            "Item", "Stock Ledger Entry", "GL Entry",
        }
        if doctype in core_doctypes:
            # Clear all query_records, run_sql_query, get_financial_summary, compare_periods caches
            cleared = 0
            remaining = []
            for key in index:
                # Check if key is from a data-query tool
                for tool_prefix in ("query_records:", "run_sql_query:", "get_financial_summary:", "compare_periods:", "count_records:"):
                    if f"{_CACHE_PREFIX}{tool_prefix}" in key:
                        try:
                            frappe.cache.delete_value(key)
                            cleared += 1
                        except Exception:
                            pass
                        break
                else:
                    remaining.append(key)

            frappe.cache.set_value(_INDEX_KEY, json.dumps(remaining))
            return {"cleared": cleared}

    except Exception:
        pass
    return {"cleared": 0}
