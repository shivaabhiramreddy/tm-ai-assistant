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
from askerp.schema_utils import (
    resolve_known_doctypes_map,
    resolve_financial_doctypes,
    resolve_core_doctypes,
)


# Redis key prefix for all AI query cache entries
_CACHE_PREFIX = "askerp_cache:"
# Redis key for the cache index (tracks all active keys for eviction)
_INDEX_KEY = "askerp_cache_index"
# Redis keys for hit/miss counters (reset daily)
_STATS_PREFIX = "askerp_cache_stats:"
_STATS_TTL = 86400 * 7  # 7 days of stats retention
# Reverse index: doctype → set of cache keys for granular invalidation
_DOCTYPE_INDEX_PREFIX = "askerp_cache_dt:"


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


def _record_stat(stat_type, tool_name="global"):
    """
    Increment a cache stat counter in Redis.
    Tracks per-day and per-tool stats for dashboard reporting.
    stat_type: "hit" or "miss"
    """
    try:
        from frappe.utils import today
        day = today()
        # Global daily counter
        global_key = f"{_STATS_PREFIX}{stat_type}:{day}"
        val = frappe.cache.get_value(global_key)
        frappe.cache.set_value(global_key, int(val or 0) + 1, expires_in_sec=_STATS_TTL)

        # Per-tool daily counter
        tool_key = f"{_STATS_PREFIX}{stat_type}:{day}:{tool_name}"
        tval = frappe.cache.get_value(tool_key)
        frappe.cache.set_value(tool_key, int(tval or 0) + 1, expires_in_sec=_STATS_TTL)
    except Exception:
        pass  # Stats recording is best-effort


def _get_daily_stat(stat_type, day, tool_name=None):
    """Read a single stat counter."""
    try:
        if tool_name:
            key = f"{_STATS_PREFIX}{stat_type}:{day}:{tool_name}"
        else:
            key = f"{_STATS_PREFIX}{stat_type}:{day}"
        val = frappe.cache.get_value(key)
        return int(val) if val else 0
    except Exception:
        return 0


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
                _record_stat("hit", tool_name)
                return result
    except Exception:
        pass  # Cache miss — proceed to execute

    _record_stat("miss", tool_name)
    return None


def _extract_doctypes_from_input(tool_name, tool_input):
    """
    Detect which ERPNext doctypes a tool call references.
    Used for granular cache invalidation: when a Sales Invoice is submitted,
    only cache entries that referenced Sales Invoice are invalidated.
    """
    doctypes = set()
    if not tool_input:
        return doctypes

    input_str = json.dumps(tool_input, default=str).lower() if isinstance(tool_input, dict) else str(tool_input).lower()

    # Dynamic doctype map — resolved at runtime from live ERPNext metadata
    _KNOWN_DOCTYPES = resolve_known_doctypes_map()

    for lower_name, canonical in _KNOWN_DOCTYPES.items():
        # Check in both tool_input text and SQL table references (tab prefix)
        if lower_name in input_str or f"tab{canonical}".lower().replace(" ", "") in input_str.replace(" ", ""):
            doctypes.add(canonical)

    # For SQL queries, also check `tabXxx` patterns
    if tool_name == "run_sql_query" and isinstance(tool_input, dict):
        sql = (tool_input.get("query") or tool_input.get("sql") or "").lower()
        for lower_name, canonical in _KNOWN_DOCTYPES.items():
            tab_name = f"`tab{canonical}`".lower()
            if tab_name in sql:
                doctypes.add(canonical)

    # Financial summary / compare_periods reference dynamic doctype sets
    fin = resolve_financial_doctypes()
    if tool_name == "get_financial_summary":
        for key in ("sales_invoice", "purchase_invoice", "payment_entry"):
            dt = fin.get(key)
            if dt:
                doctypes.add(dt)
    elif tool_name == "compare_periods":
        for key in ("sales_invoice", "purchase_invoice"):
            dt = fin.get(key)
            if dt:
                doctypes.add(dt)

    return doctypes


def _update_doctype_index(cache_key, doctypes, ttl):
    """
    Maintain reverse index: for each doctype, store the set of cache keys
    that reference it. This enables granular invalidation.
    """
    for dt in doctypes:
        dt_key = f"{_DOCTYPE_INDEX_PREFIX}{dt}"
        try:
            raw = frappe.cache.get_value(dt_key)
            keys = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])
            if cache_key not in keys:
                keys.append(cache_key)
            frappe.cache.set_value(dt_key, json.dumps(keys), expires_in_sec=ttl + 60)
        except Exception:
            pass


def set_cached_result(tool_name, tool_input, result):
    """
    Cache a tool result in Redis with the configured TTL.
    Manages the cache index for LRU eviction and doctype reverse index
    for granular invalidation.
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

        # Update doctype reverse index for granular invalidation
        doctypes = _extract_doctypes_from_input(tool_name, tool_input)
        if doctypes:
            _update_doctype_index(key, doctypes, ttl)
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
    Get basic cache statistics. Lightweight call for quick checks.
    Returns: {total_entries, index_size}
    """
    try:
        raw = frappe.cache.get_value(_INDEX_KEY)
        index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

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


def get_cache_dashboard(days=7):
    """
    Comprehensive cache metrics dashboard for admin UI.

    Returns:
    {
        "overview": {total_entries, index_size, enabled, ttl_minutes, max_entries},
        "today": {hits, misses, total, hit_rate_pct},
        "daily_trend": [{date, hits, misses, total, hit_rate_pct}, ...],
        "by_tool": [{tool, hits, misses, total, hit_rate_pct}, ...],
        "precomputed_metrics": {total, healthy, errored, stale, last_refresh},
    }
    """
    from frappe.utils import today as today_str, add_days, getdate, now_datetime

    enabled, ttl, max_entries = _get_settings()
    basic = get_cache_stats()

    # ── Today's stats ────────────────────────────────────────────────────
    today_date = today_str()
    today_hits = _get_daily_stat("hit", today_date)
    today_misses = _get_daily_stat("miss", today_date)
    today_total = today_hits + today_misses
    today_rate = round((today_hits / today_total * 100), 1) if today_total > 0 else 0.0

    # ── Daily trend (last N days) ────────────────────────────────────────
    daily_trend = []
    for i in range(days - 1, -1, -1):
        day = str(add_days(getdate(today_date), -i))
        h = _get_daily_stat("hit", day)
        m = _get_daily_stat("miss", day)
        t = h + m
        rate = round((h / t * 100), 1) if t > 0 else 0.0
        daily_trend.append({
            "date": day,
            "hits": h,
            "misses": m,
            "total": t,
            "hit_rate_pct": rate,
        })

    # ── Per-tool breakdown (today only) ──────────────────────────────────
    by_tool = []
    for tool in sorted(_CACHEABLE_TOOLS):
        h = _get_daily_stat("hit", today_date, tool)
        m = _get_daily_stat("miss", today_date, tool)
        t = h + m
        if t > 0:
            rate = round((h / t * 100), 1)
            by_tool.append({
                "tool": tool,
                "hits": h,
                "misses": m,
                "total": t,
                "hit_rate_pct": rate,
            })

    # Sort by total descending (most active tools first)
    by_tool.sort(key=lambda x: x["total"], reverse=True)

    # ── Pre-computed metrics health ──────────────────────────────────────
    precomputed = {"total": 0, "healthy": 0, "errored": 0, "stale": 0, "last_refresh": None}
    try:
        metrics = frappe.get_all(
            "AskERP Cached Metric",
            filters={"enabled": 1},
            fields=["last_computed", "error_message"],
        )
        precomputed["total"] = len(metrics)
        now = now_datetime()
        for m in metrics:
            if m.error_message:
                precomputed["errored"] += 1
            elif m.last_computed:
                age_hours = (now - m.last_computed).total_seconds() / 3600
                if age_hours > 2:
                    precomputed["stale"] += 1
                else:
                    precomputed["healthy"] += 1
                # Track most recent refresh
                if not precomputed["last_refresh"] or m.last_computed > getdate(precomputed["last_refresh"]):
                    precomputed["last_refresh"] = str(m.last_computed)
            else:
                precomputed["stale"] += 1  # Never computed
    except Exception:
        pass  # Doctype might not exist

    return {
        "overview": {
            "total_entries": basic["total_entries"],
            "index_size": basic["index_size"],
            "enabled": enabled,
            "ttl_minutes": ttl // 60 if ttl else 0,
            "max_entries": max_entries,
        },
        "today": {
            "hits": today_hits,
            "misses": today_misses,
            "total": today_total,
            "hit_rate_pct": today_rate,
        },
        "daily_trend": daily_trend,
        "by_tool": by_tool,
        "precomputed_metrics": precomputed,
    }


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

    Uses a two-layer strategy:
      Layer 1 (precise): Check the reverse index (doctype → cache keys).
        Only deletes cache entries that actually referenced this doctype.
      Layer 2 (fallback): If no reverse index exists (entries cached before
        P3.6 was deployed), falls back to the old coarse prefix-matching
        approach for core business doctypes.
    """
    doctype = doc.doctype if hasattr(doc, "doctype") else str(doc)
    try:
        cleared = 0

        # ── Layer 1: Reverse index lookup (precise) ──────────────────────
        dt_key = f"{_DOCTYPE_INDEX_PREFIX}{doctype}"
        dt_raw = frappe.cache.get_value(dt_key)
        dt_keys = json.loads(dt_raw) if dt_raw and isinstance(dt_raw, str) else (dt_raw if isinstance(dt_raw, list) else [])

        if dt_keys:
            # Delete only cache entries that referenced this doctype
            for cache_key in dt_keys:
                try:
                    frappe.cache.delete_value(cache_key)
                    cleared += 1
                except Exception:
                    pass

            # Remove cleared keys from the main index
            raw = frappe.cache.get_value(_INDEX_KEY)
            index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])
            dt_keys_set = set(dt_keys)
            updated_index = [k for k in index if k not in dt_keys_set]
            frappe.cache.set_value(_INDEX_KEY, json.dumps(updated_index))

            # Clear the reverse index entry itself
            frappe.cache.delete_value(dt_key)

            return {"cleared": cleared}

        # ── Layer 2: Fallback — coarse prefix-matching ────────────────────
        # For cache entries created before the reverse index was deployed,
        # fall back to clearing all query-tool entries for core doctypes.
        core_doctypes = resolve_core_doctypes()
        if doctype in core_doctypes:
            raw = frappe.cache.get_value(_INDEX_KEY)
            index = json.loads(raw) if raw and isinstance(raw, str) else (raw if isinstance(raw, list) else [])

            remaining = []
            for key in index:
                matched = False
                for tool_prefix in ("query_records:", "run_sql_query:", "get_financial_summary:", "compare_periods:", "count_records:"):
                    if f"{_CACHE_PREFIX}{tool_prefix}" in key:
                        try:
                            frappe.cache.delete_value(key)
                            cleared += 1
                        except Exception:
                            pass
                        matched = True
                        break
                if not matched:
                    remaining.append(key)

            frappe.cache.set_value(_INDEX_KEY, json.dumps(remaining))
            return {"cleared": cleared}

    except Exception:
        pass
    return {"cleared": 0}
