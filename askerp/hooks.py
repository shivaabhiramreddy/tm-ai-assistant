app_name = "askerp"
app_title = "AskERP"
app_publisher = "Fertile Green Industries Pvt Ltd"
app_description = "AI-powered business intelligence for ERPNext. Chat with your ERP data using Claude, Gemini, or GPT."
app_email = "shivaabhiramreddy@gmail.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]

# Include JS/CSS on every ERPNext page (Chat Widget + Setup Wizard)
# Chat widget checks allow_ai_chat permission via chat_status API before rendering
# Setup wizard checks boot session data for setup_complete flag
app_include_js = [
    "/assets/askerp/js/chat_widget.js",
    "/assets/askerp/js/setup_wizard.js",
]
app_include_css = "/assets/askerp/css/chat_widget.css"

# Post-install hook — creates default AI models and settings
after_install = "askerp.install.after_install"

# Boot session hook — injects setup_complete flag for wizard notification bar
boot_session = "askerp.setup_wizard.boot_session"

# Fixtures — export custom fields with the app
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [["fieldname", "in", ["allow_ai_chat", "custom_ai_preferences"]]],
    }
]

# Website
website_route_rules = []

# Whitelisted methods accessible via /api/method/
# These are the API endpoints the mobile app calls
override_whitelisted_methods = {}

# Doc Events — Clear caches when configuration doctypes are saved
# Phase 6.1: Also clear query cache when core business data changes
doc_events = {
    "AskERP Business Profile": {
        "after_save": "askerp.business_context.clear_profile_cache",
    },
    "AskERP Prompt Template": {
        "after_save": "askerp.business_context.clear_template_cache",
        "after_delete": "askerp.business_context.clear_template_cache",
    },
    "AskERP Custom Tool": {
        "after_save": "askerp.custom_tools.clear_custom_tool_cache",
        "after_delete": "askerp.custom_tools.clear_custom_tool_cache",
    },
    # Phase 6.1: Invalidate AI query cache when business data changes
    "Sales Invoice": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
    "Sales Order": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
    "Purchase Invoice": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
    "Payment Entry": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
    "Stock Entry": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
}

# Scheduled Tasks — Alert engine + Proactive Intelligence (Sprint 7)
# Phase 6.2: Pre-computation engine runs every hour at minute 30
scheduler_events = {
    "cron": {
        # Check hourly alerts every hour at minute 5
        "5 * * * *": [
            "askerp.alerts.check_hourly_alerts",
        ],
        # Sprint 7: Morning briefing at 7:00 AM IST daily
        # Frappe Cloud servers run in UTC; 1:30 AM UTC = 7:00 AM IST (UTC+5:30)
        "30 1 * * *": [
            "askerp.briefing.generate_morning_briefing",
        ],
        # Sprint 7: Check scheduled reports every hour at minute 15
        "15 * * * *": [
            "askerp.scheduled_reports.check_scheduled_reports",
        ],
        # Phase 6.2: Pre-compute common business metrics every hour at minute 30
        "30 * * * *": [
            "askerp.precompute.refresh_cached_metrics",
        ],
    },
    "daily": [
        "askerp.alerts.check_daily_alerts",
    ],
    "weekly": [
        "askerp.alerts.check_weekly_alerts",
    ],
}
