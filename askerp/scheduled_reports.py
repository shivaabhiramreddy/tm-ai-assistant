"""
AskERP — Scheduled Reports Engine (Sprint 7)
======================================================
Allows users to schedule recurring reports that are auto-generated
and emailed as PDF/Excel attachments.

Reports are stored as "AI Scheduled Report" doctype records.
The scheduler checks hourly which reports are due and generates them.
"""

import json
import frappe
from datetime import datetime
from askerp.formatting import get_trading_name


def check_scheduled_reports():
    """
    Called by Frappe scheduler (hourly).
    Checks which scheduled reports are due and generates them.
    """
    now = frappe.utils.now_datetime()

    # Get all active scheduled reports
    reports = frappe.get_all(
        "AI Scheduled Report",
        filters={"active": 1},
        fields=["name", "user", "report_name", "report_query",
                "frequency", "export_format", "last_generated",
                "email_recipients", "description"],
    )

    if not reports:
        return

    generated = 0
    for report in reports:
        try:
            if _is_due(report, now):
                _generate_and_deliver(report)
                generated += 1
        except Exception as e:
            frappe.log_error(
                title=f"Scheduled Report Error: {report.report_name}",
                message=f"Report: {report.name}\nUser: {report.user}\nError: {str(e)}"
            )

    if generated > 0:
        frappe.db.commit()

    frappe.logger().info(
        f"Scheduled reports check: {len(reports)} active, {generated} generated"
    )


def _is_due(report, now):
    """Check if a report is due for generation based on frequency and last_generated."""
    last = report.last_generated
    frequency = report.frequency

    if not last:
        return True  # Never generated — run now

    # Parse last_generated
    if isinstance(last, str):
        try:
            last = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True

    if frequency == "daily":
        return (now - last).total_seconds() >= 86400  # 24 hours
    elif frequency == "weekly":
        return (now - last).total_seconds() >= 604800  # 7 days
    elif frequency == "monthly":
        return (now - last).days >= 28  # ~monthly
    elif frequency == "hourly":
        return (now - last).total_seconds() >= 3600  # 1 hour

    return False


def _generate_and_deliver(report):
    """
    Generate the report by running the stored query through the AI engine,
    then export to the requested format and email it.
    """
    from .ai_engine import process_chat

    user = report.user
    query = report.report_query
    export_format = (report.export_format or "pdf").lower()

    # Run the query through the AI engine as the report's user
    # Save and restore original user context to prevent contamination across reports
    original_user = frappe.session.user
    frappe.set_user(user)

    try:
        result = process_chat(
            user=user,
            question=f"{query}\n\n[Auto-generate this as a scheduled report. Include key metrics and trends.]",
        )
    except Exception as e:
        frappe.log_error(title="Scheduled Report AI Error", message=str(e))
        frappe.set_user(original_user)
        return

    response_text = result.get("response", "")
    if not response_text:
        frappe.set_user(original_user)
        return

    try:
        # Export to the requested format
        file_info = None
        session_id = f"scheduled-report-{report.name}"

        if export_format == "pdf":
            from .exports import export_pdf
            try:
                file_info = export_pdf(
                    title=report.report_name,
                    content=response_text,
                    session_id=session_id,
                )
            except Exception as e:
                frappe.log_error(title="Scheduled Report PDF Error", message=str(e))
        elif export_format == "excel":
            # For Excel, try to extract tabular data from the response
            from .exports import export_excel
            try:
                # Simple extraction: look for table-like data in the response
                lines = response_text.strip().split("\n")
                data = []
                columns = []
                for line in lines:
                    if "|" in line and "---" not in line:
                        cells = [c.strip() for c in line.split("|") if c.strip()]
                        if not columns:
                            columns = cells
                        else:
                            data.append(cells)

                if data:
                    file_info = export_excel(
                        title=report.report_name,
                        data=data,
                        columns=columns,
                        session_id=session_id,
                    )
                else:
                    # Fallback: export as PDF if no tabular data found
                    from .exports import export_pdf
                    file_info = export_pdf(
                        title=report.report_name,
                        content=response_text,
                        session_id=session_id,
                    )
            except Exception as e:
                frappe.log_error(title="Scheduled Report Excel Error", message=str(e))

        # Update last_generated timestamp
        now_str = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        frappe.db.set_value("AI Scheduled Report", report.name, {
            "last_generated": now_str,
        }, update_modified=False)

        # Email the report
        if file_info:
            _email_report(report, file_info, response_text)

        # Log to AI Usage Log
        try:
            frappe.get_doc({
                "doctype": "AI Usage Log",
                "user": user,
                "session_id": session_id,
                "question": f"[SCHEDULED REPORT] {report.report_name}",
                "model": "scheduled-report-engine",
                "input_tokens": result.get("usage", {}).get("input_tokens", 0),
                "output_tokens": result.get("usage", {}).get("output_tokens", 0),
                "total_tokens": result.get("usage", {}).get("total_tokens", 0),
                "tool_calls": result.get("tool_calls", 0),
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(title="Scheduled Report Log Error", message=str(e))
    finally:
        # Always restore original user context to prevent contamination
        frappe.set_user(original_user)


def _email_report(report, file_info, summary_text):
    """Email the generated report to configured recipients."""
    recipients = []

    # Parse recipients (comma-separated emails)
    if report.email_recipients:
        recipients = [e.strip() for e in report.email_recipients.split(",") if e.strip()]

    # Always include the report owner
    user_email = frappe.db.get_value("User", report.user, "email")
    if user_email and user_email not in recipients:
        recipients.insert(0, user_email)

    if not recipients:
        return

    # Build email
    file_url = file_info.get("file_url", "")
    file_name = file_info.get("file_name", "report")
    download_url = file_info.get("download_url", file_url)

    site_url = frappe.utils.get_url()
    full_download_url = f"{site_url}{download_url}" if download_url.startswith("/") else download_url

    try:
        frappe.sendmail(
            recipients=recipients,
            subject=f"{get_trading_name()} Report: {report.report_name}",
            message=(
                f"<div style='font-family: Arial, sans-serif; max-width: 600px;'>"
                f"<h3>📊 {report.report_name}</h3>"
                f"<p>{report.description or ''}</p>"
                f"<p><strong>Summary:</strong></p>"
                f"<p>{summary_text[:500]}{'...' if len(summary_text) > 500 else ''}</p>"
                f"<p><a href='{full_download_url}' style='display: inline-block; "
                f"padding: 10px 20px; background: #056839; color: white; "
                f"text-decoration: none; border-radius: 5px;'>Download {file_name}</a></p>"
                f"<hr><p style='color:#888;font-size:12px'>"
                f"This is an auto-generated scheduled report from AskERP. "
                f"Frequency: {report.frequency}. Ask the assistant to modify or cancel this report.</p>"
                f"</div>"
            ),
            now=True,
        )
    except Exception as e:
        frappe.log_error(title="Scheduled Report Email Error", message=str(e))
