"""
TM AI Assistant — Alert Engine
================================
Evaluates user-created alert rules on a schedule.
Called by Frappe's scheduler (hourly/daily/weekly hooks).

Each alert rule specifies:
  - A doctype + field + aggregation + filters → produces a single numeric value
  - An operator + threshold → compared against the computed value
  - If condition is met → alert triggers (updates last_triggered, increments trigger_count)

Future: Push notifications, email alerts, in-chat notifications.
Currently: Logs triggers and updates the alert rule record for the chat UI to query.
"""

import json
import frappe
from datetime import datetime


def check_alerts(frequency):
    """
    Evaluate all active alert rules for the given frequency.

    Args:
        frequency: "hourly", "daily", or "weekly"
    """
    alerts = frappe.get_all(
        "AI Alert Rule",
        filters={"active": 1, "frequency": frequency},
        fields=["name", "user", "alert_name", "description",
                "query_doctype", "query_field", "query_aggregation",
                "query_filters", "threshold_operator", "threshold_value"],
    )

    if not alerts:
        return

    triggered_count = 0
    for alert in alerts:
        try:
            triggered = _evaluate_alert(alert)
            if triggered:
                triggered_count += 1
        except Exception as e:
            frappe.log_error(
                title=f"Alert Evaluation Error: {alert.alert_name}",
                message=f"Alert: {alert.name}\nUser: {alert.user}\nError: {str(e)}"
            )

    if triggered_count > 0:
        frappe.db.commit()

    frappe.logger().info(
        f"Alert check ({frequency}): {len(alerts)} evaluated, {triggered_count} triggered"
    )


def _evaluate_alert(alert):
    """
    Evaluate a single alert rule. Returns True if triggered.

    Runs the query as the alert's user to respect permissions.
    """
    doctype = alert.query_doctype
    field = alert.query_field
    aggregation = alert.query_aggregation or "SUM"
    threshold_op = alert.threshold_operator
    threshold_val = float(alert.threshold_value)

    # Parse filters
    filters = {}
    if alert.query_filters:
        try:
            filters = json.loads(alert.query_filters) if isinstance(alert.query_filters, str) else alert.query_filters
        except (json.JSONDecodeError, TypeError):
            filters = {}

    # Ensure we only look at submitted documents
    if "docstatus" not in filters:
        filters["docstatus"] = 1

    # Execute query as the alert's user
    original_user = frappe.session.user
    try:
        frappe.set_user(alert.user)
        result = frappe.get_list(
            doctype,
            fields=[f"{aggregation}({field}) as value"],
            filters=filters,
            limit_page_length=1,
        )
    finally:
        frappe.set_user(original_user)

    if not result:
        current_value = 0.0
    else:
        current_value = float(result[0].get("value") or 0)

    # Update last_checked and last_value
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    frappe.db.set_value("AI Alert Rule", alert.name, {
        "last_checked": now,
        "last_value": current_value,
    }, update_modified=False)

    # Check threshold condition
    triggered = _check_condition(current_value, threshold_op, threshold_val)

    if triggered:
        # Update trigger info
        frappe.db.set_value("AI Alert Rule", alert.name, {
            "last_triggered": now,
            "trigger_count": (frappe.db.get_value("AI Alert Rule", alert.name, "trigger_count") or 0) + 1,
        }, update_modified=False)

        # Log the trigger event
        _log_trigger(alert, current_value, threshold_val)

    return triggered


def _check_condition(value, operator, threshold):
    """Compare value against threshold using the specified operator."""
    ops = {
        ">": lambda v, t: v > t,
        "<": lambda v, t: v < t,
        ">=": lambda v, t: v >= t,
        "<=": lambda v, t: v <= t,
        "=": lambda v, t: abs(v - t) < 0.01,
        "!=": lambda v, t: abs(v - t) >= 0.01,
    }
    check_fn = ops.get(operator)
    if not check_fn:
        return False
    return check_fn(value, threshold)


def _log_trigger(alert, current_value, threshold_value):
    """Log an alert trigger for audit and future notification."""
    try:
        frappe.get_doc({
            "doctype": "AI Usage Log",
            "user": alert.user,
            "session_id": f"alert-{alert.name}",
            "question": f"[ALERT TRIGGERED] {alert.alert_name}: {current_value} {alert.threshold_operator} {threshold_value}",
            "model": "alert-engine",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "tool_calls": 0,
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Alert Log Error", message=str(e))


# ─── Scheduler Entry Points ─────────────────────────────────────────────────

def check_hourly_alerts():
    """Called by Frappe scheduler every hour."""
    check_alerts("hourly")


def check_daily_alerts():
    """Called by Frappe scheduler once daily."""
    check_alerts("daily")


def check_weekly_alerts():
    """Called by Frappe scheduler once weekly."""
    check_alerts("weekly")
