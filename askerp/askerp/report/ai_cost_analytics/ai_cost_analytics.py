# Copyright (c) 2026, Fertile Green Industries Pvt Ltd and contributors
# License: MIT
#
# AI Cost Analytics — Script Report
# Shows AI API spend, token usage, cache hit rates, and per-user breakdown.

import frappe
from frappe.utils import flt, getdate, add_days, today, get_first_day, get_last_day


def execute(filters=None):
    filters = filters or {}
    columns = get_columns(filters)
    data = get_data(filters)
    chart = get_chart(filters)
    report_summary = get_report_summary(filters)
    return columns, data, None, chart, report_summary


def get_columns(filters):
    """Define report columns based on grouping."""
    group_by = filters.get("group_by", "Day")

    columns = [
        {
            "fieldname": "period",
            "label": "Period" if group_by == "Day" else group_by,
            "fieldtype": "Data",
            "width": 140,
        },
        {
            "fieldname": "total_queries",
            "label": "Queries",
            "fieldtype": "Int",
            "width": 90,
        },
        {
            "fieldname": "total_cost",
            "label": "Total Cost ($)",
            "fieldtype": "Float",
            "precision": 4,
            "width": 120,
        },
        {
            "fieldname": "avg_cost_per_query",
            "label": "Avg $/Query",
            "fieldtype": "Float",
            "precision": 4,
            "width": 110,
        },
        {
            "fieldname": "input_tokens",
            "label": "Input Tokens",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "fieldname": "output_tokens",
            "label": "Output Tokens",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "fieldname": "cache_read_tokens",
            "label": "Cache Tokens",
            "fieldtype": "Int",
            "width": 110,
        },
        {
            "fieldname": "cache_hit_pct",
            "label": "Cache Hit %",
            "fieldtype": "Percent",
            "width": 100,
        },
        {
            "fieldname": "tool_calls",
            "label": "Tool Calls",
            "fieldtype": "Int",
            "width": 100,
        },
    ]

    # Add user column if grouping by user
    if group_by == "User":
        columns.insert(0, {
            "fieldname": "user",
            "label": "User",
            "fieldtype": "Link",
            "options": "User",
            "width": 180,
        })

    if group_by == "Model":
        columns.insert(0, {
            "fieldname": "model",
            "label": "Model",
            "fieldtype": "Data",
            "width": 200,
        })

    if group_by == "Complexity":
        columns.insert(0, {
            "fieldname": "complexity",
            "label": "Complexity",
            "fieldtype": "Data",
            "width": 120,
        })

    return columns


def get_data(filters):
    """Fetch and aggregate data from AI Usage Log."""
    conditions = _build_conditions(filters)
    group_by = filters.get("group_by", "Day")

    if group_by == "Day":
        group_field = "DATE(creation)"
        order_field = "DATE(creation)"
    elif group_by == "Week":
        group_field = "YEARWEEK(creation, 1)"
        order_field = "YEARWEEK(creation, 1)"
    elif group_by == "Month":
        group_field = "DATE_FORMAT(creation, '%Y-%m')"
        order_field = "DATE_FORMAT(creation, '%Y-%m')"
    elif group_by == "User":
        group_field = "user"
        order_field = "SUM(cost_total) DESC"
    elif group_by == "Model":
        group_field = "model"
        order_field = "SUM(cost_total) DESC"
    elif group_by == "Complexity":
        group_field = "complexity"
        order_field = "SUM(cost_total) DESC"
    else:
        group_field = "DATE(creation)"
        order_field = "DATE(creation)"

    sql = f"""
        SELECT
            {group_field} as period_key,
            COUNT(*) as total_queries,
            SUM(cost_total) as total_cost,
            SUM(cost_total) / NULLIF(COUNT(*), 0) as avg_cost_per_query,
            SUM(input_tokens) as input_tokens,
            SUM(output_tokens) as output_tokens,
            SUM(cache_read_tokens) as cache_read_tokens,
            SUM(tool_calls) as tool_calls
            {"," if group_by in ("User", "Model", "Complexity") else ""}
            {"user" if group_by == "User" else ""}
            {"model" if group_by == "Model" else ""}
            {"complexity" if group_by == "Complexity" else ""}
        FROM `tabAI Usage Log`
        WHERE 1=1 {conditions}
        GROUP BY {group_field}
        ORDER BY {order_field}
    """

    raw = frappe.db.sql(sql, as_dict=True)

    data = []
    for row in raw:
        total_input = flt(row.get("input_tokens", 0))
        cache_read = flt(row.get("cache_read_tokens", 0))
        # Cache hit % = cache_read_tokens / total_input_tokens (prompt caching savings)
        cache_pct = (cache_read / total_input * 100) if total_input > 0 else 0

        record = {
            "period": str(row.get("period_key", "")),
            "total_queries": row.get("total_queries", 0),
            "total_cost": flt(row.get("total_cost", 0), 4),
            "avg_cost_per_query": flt(row.get("avg_cost_per_query", 0), 4),
            "input_tokens": int(total_input),
            "output_tokens": int(flt(row.get("output_tokens", 0))),
            "cache_read_tokens": int(cache_read),
            "cache_hit_pct": flt(cache_pct, 1),
            "tool_calls": int(flt(row.get("tool_calls", 0))),
        }

        if group_by == "User":
            record["user"] = row.get("user", "")
        elif group_by == "Model":
            record["model"] = row.get("model", "")
        elif group_by == "Complexity":
            record["complexity"] = row.get("complexity", "")

        data.append(record)

    return data


def get_chart(filters):
    """Generate chart data for the report."""
    group_by = filters.get("group_by", "Day")
    conditions = _build_conditions(filters)

    if group_by in ("User", "Model", "Complexity"):
        # Pie/donut chart for categorical grouping
        group_field = {"User": "user", "Model": "model", "Complexity": "complexity"}[group_by]
        sql = f"""
            SELECT {group_field} as label, SUM(cost_total) as value
            FROM `tabAI Usage Log`
            WHERE 1=1 {conditions}
            GROUP BY {group_field}
            ORDER BY value DESC
            LIMIT 10
        """
        raw = frappe.db.sql(sql, as_dict=True)
        return {
            "data": {
                "labels": [r["label"] or "Unknown" for r in raw],
                "datasets": [{"values": [flt(r["value"], 4) for r in raw]}],
            },
            "type": "donut",
            "colors": ["#047e38", "#fac421", "#056839", "#ee4919", "#143121",
                       "#e1d790", "#2196F3", "#9C27B0", "#FF9800", "#607D8B"],
        }

    # Time-series: line chart for cost + bar chart for queries
    if group_by == "Week":
        group_field = "YEARWEEK(creation, 1)"
    elif group_by == "Month":
        group_field = "DATE_FORMAT(creation, '%Y-%m')"
    else:
        group_field = "DATE(creation)"

    sql = f"""
        SELECT
            {group_field} as period,
            SUM(cost_total) as total_cost,
            COUNT(*) as total_queries
        FROM `tabAI Usage Log`
        WHERE 1=1 {conditions}
        GROUP BY {group_field}
        ORDER BY {group_field}
    """
    raw = frappe.db.sql(sql, as_dict=True)

    return {
        "data": {
            "labels": [str(r["period"]) for r in raw],
            "datasets": [
                {"name": "Cost ($)", "values": [flt(r["total_cost"], 4) for r in raw]},
                {"name": "Queries", "values": [r["total_queries"] for r in raw]},
            ],
        },
        "type": "bar",
        "colors": ["#047e38", "#fac421"],
    }


def get_report_summary(filters):
    """Generate summary cards shown above the report."""
    conditions = _build_conditions(filters)

    sql = f"""
        SELECT
            COUNT(*) as total_queries,
            SUM(cost_total) as total_cost,
            SUM(input_tokens) as total_input,
            SUM(output_tokens) as total_output,
            SUM(cache_read_tokens) as total_cache_read,
            AVG(cost_total) as avg_cost
        FROM `tabAI Usage Log`
        WHERE 1=1 {conditions}
    """
    result = frappe.db.sql(sql, as_dict=True)
    if not result:
        return []

    r = result[0]
    total_input = flt(r.get("total_input", 0))
    cache_read = flt(r.get("total_cache_read", 0))
    cache_pct = (cache_read / total_input * 100) if total_input > 0 else 0

    # Estimate savings from caching (cache_read charged at 10% of regular input rate)
    cache_savings_tokens = cache_read * 0.9  # 90% of cache tokens are savings
    # Rough estimate: $15/MTok input → savings in dollars
    cache_savings_usd = (cache_savings_tokens / 1_000_000) * 15

    return [
        {
            "value": flt(r.get("total_cost", 0), 4),
            "label": "Total Cost ($)",
            "datatype": "Float",
            "indicator": "Red" if flt(r.get("total_cost", 0)) > 50 else "Green",
        },
        {
            "value": r.get("total_queries", 0),
            "label": "Total Queries",
            "datatype": "Int",
            "indicator": "Blue",
        },
        {
            "value": flt(r.get("avg_cost", 0), 4),
            "label": "Avg Cost/Query ($)",
            "datatype": "Float",
            "indicator": "Green" if flt(r.get("avg_cost", 0)) < 0.05 else "Orange",
        },
        {
            "value": flt(cache_pct, 1),
            "label": "Cache Hit Rate (%)",
            "datatype": "Percent",
            "indicator": "Green" if cache_pct > 50 else "Orange",
        },
        {
            "value": flt(cache_savings_usd, 2),
            "label": "Est. Cache Savings ($)",
            "datatype": "Float",
            "indicator": "Green",
        },
    ]


def _build_conditions(filters):
    """Build SQL WHERE conditions from report filters."""
    conditions = ""

    if filters.get("from_date"):
        conditions += f" AND DATE(creation) >= '{getdate(filters['from_date'])}'"
    if filters.get("to_date"):
        conditions += f" AND DATE(creation) <= '{getdate(filters['to_date'])}'"
    if filters.get("user"):
        conditions += f" AND user = '{frappe.db.escape(filters['user'])}'"
    if filters.get("model"):
        conditions += f" AND model = '{frappe.db.escape(filters['model'])}'"
    if filters.get("complexity"):
        conditions += f" AND complexity = '{frappe.db.escape(filters['complexity'])}'"

    return conditions
