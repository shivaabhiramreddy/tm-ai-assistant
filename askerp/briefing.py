"""
AskERP — Morning Briefing Generator (Sprint 7)
========================================================
Generates a daily business briefing for executive/management users.
Called by Frappe scheduler each morning (7 AM IST via cron).

The briefing includes:
- Yesterday's sales & collections
- Outstanding receivables status
- Pending approvals count
- Any alerts that triggered overnight
- Top priority items for the day

Delivered via:
1. Frappe Notification Log (bell icon in ERPNext)
2. Email notification
3. Logged to AI Usage Log for chat UI to show
"""

import json
import frappe


def generate_morning_briefing():
    """
    Main entry point called by scheduler.
    Generates briefings for all users with AI access + management roles.
    """
    # Find users who should receive briefings
    briefing_users = _get_briefing_users()

    if not briefing_users:
        return

    generated = 0
    for user in briefing_users:
        try:
            briefing = _build_briefing(user)
            if briefing:
                _deliver_briefing(user, briefing)
                generated += 1
        except Exception as e:
            frappe.log_error(
                title=f"Morning Briefing Error: {user}",
                message=str(e)
            )

    if generated > 0:
        frappe.db.commit()

    frappe.logger().info(
        f"Morning briefing: {generated}/{len(briefing_users)} generated"
    )


def _get_briefing_users():
    """
    Get list of users who should receive morning briefings.

    Bootstrap-safe: checks if allow_ai_chat field exists before querying.
    On fresh install, the field may not exist yet (created by after_install hook).
    """
    # Users with AI access AND management+ roles
    management_roles = {"System Manager", "Accounts Manager", "Sales Manager",
                        "Purchase Manager", "Stock Manager", "Manufacturing Manager"}

    # Bootstrap protection: skip if custom field doesn't exist yet
    if not frappe.db.has_column("User", "allow_ai_chat"):
        return []

    ai_users = frappe.get_all(
        "User",
        filters={"allow_ai_chat": 1, "enabled": 1},
        fields=["name"],
    )

    briefing_users = []
    for u in ai_users:
        try:
            user_roles = set(frappe.get_roles(u.name))
            if user_roles.intersection(management_roles):
                briefing_users.append(u.name)
        except Exception:
            continue

    return briefing_users


def _build_briefing(user):
    """
    Build the briefing content for a specific user.
    Uses direct SQL for speed — no LLM calls needed.
    """
    now = frappe.utils.now_datetime()
    yesterday = frappe.utils.add_days(frappe.utils.today(), -1)
    today = frappe.utils.today()

    sections = []

    # 1. Yesterday's Sales
    try:
        sales_data = frappe.db.sql("""
            SELECT
                COUNT(*) as invoice_count,
                COALESCE(SUM(grand_total), 0) as total_revenue,
                COALESCE(SUM(outstanding_amount), 0) as new_outstanding
            FROM `tabSales Invoice`
            WHERE posting_date = %s AND docstatus = 1
        """, yesterday, as_dict=True)[0]

        revenue = _format_inr(sales_data.total_revenue)
        sections.append(
            f"**Yesterday's Sales:** {sales_data.invoice_count} invoices totaling {revenue}"
        )
    except Exception:
        pass

    # 2. Collections Yesterday
    try:
        collections = frappe.db.sql("""
            SELECT
                COUNT(*) as payment_count,
                COALESCE(SUM(paid_amount), 0) as total_collected
            FROM `tabPayment Entry`
            WHERE posting_date = %s AND docstatus = 1
            AND payment_type = 'Receive'
        """, yesterday, as_dict=True)[0]

        collected = _format_inr(collections.total_collected)
        sections.append(
            f"**Collections:** {collections.payment_count} payments, {collected} received"
        )
    except Exception:
        pass

    # 3. Outstanding Receivables
    try:
        receivables = frappe.db.sql("""
            SELECT COALESCE(SUM(outstanding_amount), 0) as total
            FROM `tabSales Invoice`
            WHERE outstanding_amount > 0 AND docstatus = 1
        """, as_dict=True)[0]

        outstanding = _format_inr(receivables.total)
        sections.append(f"**Total Outstanding Receivables:** {outstanding}")
    except Exception:
        pass

    # 4. Pending Approvals
    try:
        pending_so = frappe.db.count("Sales Order", {
            "workflow_state": "Pending for Approval", "docstatus": 0
        })
        pending_si = frappe.db.count("Sales Invoice", {
            "workflow_state": "Pending for Approval", "docstatus": 0
        })
        pending_pr = frappe.db.count("Purchase Receipt", {
            "workflow_state": "Pending for Approval", "docstatus": 0
        })
        total_pending = pending_so + pending_si + pending_pr

        if total_pending > 0:
            parts = []
            if pending_so: parts.append(f"{pending_so} Sales Orders")
            if pending_si: parts.append(f"{pending_si} Sales Invoices")
            if pending_pr: parts.append(f"{pending_pr} Purchase Receipts")
            sections.append(f"**Pending Approvals:** {total_pending} ({', '.join(parts)})")
    except Exception:
        pass

    # 5. Alerts triggered overnight
    try:
        overnight_alerts = frappe.get_all(
            "AI Usage Log",
            filters={
                "model": "alert-engine",
                "creation": [">=", yesterday],
            },
            fields=["question"],
            limit=5,
        )
        if overnight_alerts:
            alert_lines = [a.question.replace("[ALERT TRIGGERED] ", "• ") for a in overnight_alerts]
            sections.append(f"**Alerts Triggered:**\n" + "\n".join(alert_lines))
    except Exception:
        pass

    if not sections:
        return None

    # Build final briefing
    greeting = "Good morning"
    full_name = frappe.db.get_value("User", user, "full_name") or user
    first_name = full_name.split()[0] if full_name else "there"

    briefing_text = f"🌅 {greeting}, {first_name}! Here's your business briefing for {now.strftime('%A, %B %d')}:\n\n"
    briefing_text += "\n\n".join(sections)
    briefing_text += "\n\n💡 *Ask me anything for deeper analysis on any of these metrics.*"

    return briefing_text


def _deliver_briefing(user, briefing_text):
    """
    Deliver the briefing via multiple channels:
    1. AI Usage Log (so chat UI can show it)
    2. Frappe Notification Log (bell icon)
    3. Email
    """
    now_str = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Log to AI Usage Log
    try:
        frappe.get_doc({
            "doctype": "AI Usage Log",
            "user": user,
            "session_id": f"briefing-{frappe.utils.today()}",
            "question": f"[MORNING BRIEFING] {briefing_text[:500]}",
            "model": "briefing-engine",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "tool_calls": 0,
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Briefing Log Error", message=str(e))

    # 2. Frappe Notification Log
    try:
        notification = frappe.get_doc({
            "doctype": "Notification Log",
            "for_user": user,
            "from_user": "Administrator",
            "type": "Alert",
            "subject": f"🌅 Morning Business Briefing",
            "email_content": briefing_text.replace("\n", "<br>").replace("**", "<strong>").replace("*", "<em>"),
        })
        notification.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(title="Briefing Notification Error", message=str(e))

    # 3. Email
    try:
        user_email = frappe.db.get_value("User", user, "email")
        if user_email:
            html_content = briefing_text.replace("\n", "<br>").replace("**", "<strong>").replace("*", "<em>")
            frappe.sendmail(
                recipients=[user_email],
                subject=f"TM Morning Briefing — {frappe.utils.now_datetime().strftime('%B %d, %Y')}",
                message=(
                    f"<div style='font-family: Arial, sans-serif; max-width: 600px;'>"
                    f"{html_content}"
                    f"<hr><p style='color:#888;font-size:12px'>"
                    f"Generated by AskERP. Open the app to ask follow-up questions.</p>"
                    f"</div>"
                ),
                now=True,
            )
    except Exception as e:
        frappe.log_error(title="Briefing Email Error", message=str(e))


def _format_inr(value):
    """Format number in Indian notation."""
    value = float(value or 0)
    if abs(value) >= 1_00_00_000:
        return f"₹{value / 1_00_00_000:.2f} Cr"
    elif abs(value) >= 1_00_000:
        return f"₹{value / 1_00_000:.2f} L"
    elif abs(value) >= 1000:
        return f"₹{value:,.0f}"
    else:
        return f"₹{value:.2f}"
