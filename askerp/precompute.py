"""
AskERP — Pre-Computation Engine
==========================================
Refreshes commonly-needed business metrics on a schedule and stores
them in the AskERP Cached Metric doctype.  The AI engine reads these
cached values instead of running live SQL — making briefings and
dashboards 10x faster.

Scheduler entry (hooks.py):
  "30 * * * *": ["askerp.precompute.refresh_cached_metrics"]

Metric definition supports two query types:
  SQL          — raw SELECT that returns a single numeric value
  Aggregation  — doctype + field + function (SUM/COUNT/AVG/MAX/MIN)

Dynamic filter tokens in filters_json:
  {today}, {month_start}, {month_end}, {fy_start}, {fy_end},
  {last_month_start}, {last_month_end}
"""

import json
import time
import frappe
from frappe.utils import (
    now_datetime, today, get_first_day, get_last_day,
    getdate, flt, fmt_money,
)


# ─── Token Replacement ──────────────────────────────────────────────────────

def _get_dynamic_tokens():
    """
    Build a dict of dynamic date tokens for filter replacement.
    All dates use ERPNext's timezone-aware utilities.
    """
    now = now_datetime()
    today_date = getdate(today())
    month_start = get_first_day(today_date)
    month_end = get_last_day(today_date)

    # Indian financial year: Apr 1 – Mar 31
    if today_date.month >= 4:
        fy_start = getdate(f"{today_date.year}-04-01")
        fy_end = getdate(f"{today_date.year + 1}-03-31")
    else:
        fy_start = getdate(f"{today_date.year - 1}-04-01")
        fy_end = getdate(f"{today_date.year}-03-31")

    # Last month
    if today_date.month == 1:
        last_month_start = getdate(f"{today_date.year - 1}-12-01")
    else:
        last_month_start = getdate(f"{today_date.year}-{today_date.month - 1:02d}-01")
    last_month_end = get_last_day(last_month_start)

    return {
        "{today}": str(today_date),
        "{month_start}": str(month_start),
        "{month_end}": str(month_end),
        "{fy_start}": str(fy_start),
        "{fy_end}": str(fy_end),
        "{last_month_start}": str(last_month_start),
        "{last_month_end}": str(last_month_end),
    }


def _replace_tokens(text, tokens):
    """Replace all dynamic tokens in a string."""
    if not text:
        return text
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text


# ─── Indian Number Formatting ───────────────────────────────────────────────

def _format_indian(value):
    """
    Format a number in Indian notation with ₹ prefix.
    Examples: 45,23,000 → ₹45.23 L, 2,15,00,000 → ₹2.15 Cr
    """
    if value is None:
        return "₹0"
    val = flt(value)
    abs_val = abs(val)
    sign = "-" if val < 0 else ""

    if abs_val >= 1_00_00_000:  # 1 Crore
        return f"{sign}₹{abs_val / 1_00_00_000:.2f} Cr"
    elif abs_val >= 1_00_000:  # 1 Lakh
        return f"{sign}₹{abs_val / 1_00_000:.2f} L"
    elif abs_val >= 1_000:
        return f"{sign}₹{abs_val / 1_000:.2f} K"
    else:
        return f"{sign}₹{abs_val:.2f}"


# ─── Metric Computation ────────────────────────────────────────────────────

def _compute_sql_metric(metric, tokens):
    """Execute a raw SQL query that returns a single numeric value."""
    sql = _replace_tokens(metric.sql_query, tokens)
    if not sql or not sql.strip().upper().startswith("SELECT"):
        return None, "SQL query must be a SELECT statement"

    result = frappe.db.sql(sql, as_list=True)
    if result and result[0] and result[0][0] is not None:
        return flt(result[0][0]), None
    return 0.0, None


def _compute_aggregation_metric(metric, tokens):
    """Compute a metric using doctype + field + aggregation function."""
    if not metric.doctype_name or not metric.aggregation:
        return None, "Aggregation metric requires doctype and aggregation function"

    # Parse filters
    filters = {}
    if metric.filters_json:
        raw = _replace_tokens(metric.filters_json, tokens)
        try:
            filters = json.loads(raw)
        except json.JSONDecodeError as e:
            return None, f"Invalid filters JSON: {str(e)[:100]}"

    agg_func = metric.aggregation.upper()
    field = metric.field_name or "name"

    if agg_func == "COUNT":
        value = frappe.db.count(metric.doctype_name, filters=filters)
    elif agg_func in ("SUM", "AVG", "MAX", "MIN"):
        result = frappe.db.sql(
            f"SELECT {agg_func}(`{field}`) FROM `tab{metric.doctype_name}` WHERE {frappe.db.get_conditions(metric.doctype_name, filters)}",
            as_list=True,
        )
        value = flt(result[0][0]) if result and result[0] and result[0][0] is not None else 0.0
    else:
        return None, f"Unsupported aggregation: {agg_func}"

    return flt(value), None


def _compute_single_metric(metric, tokens):
    """
    Compute one metric. Returns (value, error_string).
    Catches all exceptions so one failure doesn't stop others.
    """
    try:
        if metric.query_type == "SQL":
            return _compute_sql_metric(metric, tokens)
        else:
            return _compute_aggregation_metric(metric, tokens)
    except Exception as e:
        return None, str(e)[:500]


# ─── Public API: Refresh All Metrics (Scheduler) ───────────────────────────

def refresh_cached_metrics():
    """
    Scheduled task: refreshes all enabled AskERP Cached Metric records.
    Called every hour at minute 30 via hooks.py scheduler.

    Runs as Administrator to bypass permissions on all doctypes.
    Each metric is computed independently — one failure won't stop others.
    """
    try:
        metrics = frappe.get_all(
            "AskERP Cached Metric",
            filters={"enabled": 1},
            fields=["name"],
        )
    except Exception:
        # Doctype may not exist yet (fresh install, migration pending)
        return

    if not metrics:
        return

    tokens = _get_dynamic_tokens()
    computed = 0
    errors = 0

    for m in metrics:
        try:
            metric = frappe.get_doc("AskERP Cached Metric", m.name)
            start_ms = time.time()

            value, error = _compute_single_metric(metric, tokens)

            elapsed_ms = int((time.time() - start_ms) * 1000)

            # Update the metric doc directly (bypass ORM for speed)
            updates = {
                "last_computed": now_datetime(),
                "computation_time_ms": elapsed_ms,
            }

            if error:
                updates["error_message"] = error[:500]
                errors += 1
            else:
                updates["cached_value"] = flt(value, 2)
                updates["cached_value_formatted"] = _format_indian(value)
                updates["error_message"] = ""
                computed += 1

            frappe.db.set_value("AskERP Cached Metric", m.name, updates, update_modified=False)

        except Exception as e:
            errors += 1
            frappe.log_error(
                title=f"Pre-compute Error: {m.name}",
                message=str(e),
            )

    frappe.db.commit()

    if computed or errors:
        frappe.logger("askerp").info(
            f"Pre-compute: {computed} metrics refreshed, {errors} errors"
        )


# ─── Public API: Read Cached Metrics ───────────────────────────────────────

def get_cached_metrics(category=None, company=None):
    """
    Read pre-computed metrics for use by the AI engine.

    Returns a list of dicts:
      [{"metric_name": "...", "label": "...", "value": 123.45,
        "formatted": "₹1.23 L", "category": "Revenue",
        "last_computed": "2026-02-14 07:30:00"}]

    If category is provided, filters to that category only.
    If company is provided, filters to that company (or metrics with no company set).
    """
    filters = {"enabled": 1}
    if category:
        filters["category"] = category
    if company:
        filters["company"] = ["in", [company, "", None]]

    try:
        metrics = frappe.get_all(
            "AskERP Cached Metric",
            filters=filters,
            fields=[
                "metric_name", "metric_label", "category", "company",
                "cached_value", "cached_value_formatted",
                "last_computed", "error_message",
            ],
            order_by="category asc, metric_label asc",
        )
    except Exception:
        return []

    result = []
    for m in metrics:
        result.append({
            "metric_name": m.metric_name,
            "label": m.metric_label,
            "value": flt(m.cached_value),
            "formatted": m.cached_value_formatted or _format_indian(m.cached_value),
            "category": m.category,
            "company": m.company,
            "last_computed": str(m.last_computed) if m.last_computed else None,
            "error": m.error_message or None,
        })

    return result


def get_metrics_for_prompt(company=None):
    """
    Format cached metrics as a compact text block for the AI system prompt.
    Used by business_context.py to inject pre-computed data.

    Returns a string like:
      Revenue | Today's Revenue: ₹45.23 L | Monthly Revenue: ₹3.15 Cr
      Receivables | Outstanding: ₹1.23 Cr | Overdue >90 days: ₹45.00 L
    """
    metrics = get_cached_metrics(company=company)
    if not metrics:
        return ""

    # Group by category
    by_category = {}
    for m in metrics:
        cat = m["category"] or "Custom"
        if cat not in by_category:
            by_category[cat] = []
        if not m.get("error"):
            by_category[cat].append(f"{m['label']}: {m['formatted']}")

    lines = []
    for cat, items in sorted(by_category.items()):
        if items:
            lines.append(f"{cat} | {' | '.join(items)}")

    return "\n".join(lines)
