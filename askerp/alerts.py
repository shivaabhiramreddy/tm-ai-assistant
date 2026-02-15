"""
AskERP — Alert Engine v2.0
=====================================
Evaluates user-created alert rules on a schedule.
Called by Frappe's scheduler (hourly/daily/weekly hooks).

Each alert rule specifies:
  - A doctype + field + aggregation + filters → produces a single numeric value
  - An operator + threshold → compared against the computed value
  - If condition is met → alert triggers:
    1. Updates last_triggered + increments trigger_count
    2. Creates Frappe System Notification (in-app bell icon)
    3. Sends email notification to the user
    4. Logs to AI Usage Log for chat UI to query

v2.0 changes:
- Added System Notification on trigger (shows in Frappe bell icon)
- Added email notification via frappe.sendmail

v2.1 changes (Decoupling):
- Removed hardcoded Indian number formatting — uses formatting.py
- Removed hardcoded "TM" branding — uses profile trading_name
"""

import json
import frappe
from askerp.formatting import format_currency, get_trading_name


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
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
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
    """
    Log an alert trigger AND notify the user via:
    1. AI Usage Log (for chat UI querying)
    2. Frappe System Notification (bell icon in ERPNext)
    3. Email notification
    """
    formatted_value = format_currency(current_value)
    formatted_threshold = format_currency(threshold_value)
    alert_msg = f"{alert.alert_name}: current value is {formatted_value} ({alert.threshold_operator} {formatted_threshold} threshold)"

    # 1. Log to AI Usage Log
    try:
        frappe.get_doc({
            "doctype": "AI Usage Log",
            "user": alert.user,
            "session_id": f"alert-{alert.name}",
            "question": f"[ALERT TRIGGERED] {alert_msg}",
            "model": "alert-engine",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "tool_calls": 0,
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Alert Log Error", message=str(e))

    # 2. Create Frappe System Notification (shows in bell icon)
    try:
        notification = frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": alert.user,
            "from_user": "Administrator",
            "type": "Alert",
            "subject": f"🚨 {get_trading_name()} Alert: {alert.alert_name}",
            "email_content": (
                f"<p><strong>{alert.alert_name}</strong></p>"
                f"<p>{alert.description or ''}</p>"
                f"<p>Current value: <strong>{formatted_value}</strong> "
                f"(threshold: {alert.threshold_operator} {formatted_threshold})</p>"
                f"<p>Frequency: {alert.frequency}</p>"
            ),
            "document_type": "AI Alert Rule",
            "document_name": alert.name,
        })
        notification.insert(ignore_permissions=True)
    except Exception as e:
        # Notification Log might not exist in all ERPNext versions — log but don't fail
        frappe.log_error(title="Alert Notification Error", message=str(e))

    # 3. Send email notification
    try:
        user_email = frappe.db.get_value("User", alert.user, "email")
        if user_email:
            frappe.sendmail(
                recipients=[user_email],
                subject=f"{get_trading_name()} Alert: {alert.alert_name}",
                message=(
                    f"<h3>🚨 {alert.alert_name}</h3>"
                    f"<p>{alert.description or ''}</p>"
                    f"<p><strong>Current value:</strong> {formatted_value}</p>"
                    f"<p><strong>Threshold:</strong> {alert.threshold_operator} {formatted_threshold}</p>"
                    f"<p><strong>Frequency:</strong> {alert.frequency}</p>"
                    f"<hr><p style='color:#888;font-size:12px'>This alert was set up through AskERP. "
                    f"Ask the assistant to modify or delete this alert.</p>"
                ),
                now=True,  # Send immediately (don't queue)
            )
    except Exception as e:
        # Email might fail (SMTP not configured) — log but don't fail the alert
        frappe.log_error(title="Alert Email Error", message=str(e))


# ─── Alert Test-on-Create (Sprint 7) ─────────────────────────────────────────

def test_alert(alert_name):
    """
    Sprint 7: Immediately evaluate an alert when created/updated.
    Returns the current value and whether the condition would trigger.
    Does NOT actually trigger notifications — just shows the result.

    Args:
        alert_name: The name (ID) of the AI Alert Rule to test

    Returns:
        dict: {current_value, formatted_value, threshold, would_trigger, message}
    """
    alert = frappe.get_doc("AI Alert Rule", alert_name)

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

    if "docstatus" not in filters:
        filters["docstatus"] = 1

    # Execute query as the alert's user
    try:
        result = frappe.get_list(
            doctype,
            fields=[f"{aggregation}({field}) as value"],
            filters=filters,
            limit_page_length=1,
        )
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Query failed: {str(e)[:200]}",
        }

    if not result:
        current_value = 0.0
    else:
        current_value = float(result[0].get("value") or 0)

    formatted_value = format_currency(current_value)
    formatted_threshold = format_currency(threshold_val)
    would_trigger = _check_condition(current_value, threshold_op, threshold_val)

    # Update last_checked and last_value
    now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
    frappe.db.set_value("AI Alert Rule", alert.name, {
        "last_checked": now,
        "last_value": current_value,
    }, update_modified=False)
    frappe.db.commit()

    trigger_word = "WOULD trigger" if would_trigger else "would NOT trigger"
    message = (
        f"Test result: {aggregation}({field}) on {doctype} = {formatted_value}. "
        f"Threshold: {threshold_op} {formatted_threshold}. "
        f"This alert {trigger_word} right now."
    )

    return {
        "success": True,
        "current_value": current_value,
        "formatted_value": formatted_value,
        "threshold_value": threshold_val,
        "formatted_threshold": formatted_threshold,
        "would_trigger": would_trigger,
        "message": message,
    }


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
