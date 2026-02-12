app_name = "tm_ai_assistant"
app_title = "TM AI Assistant"
app_publisher = "Fertile Green Industries Pvt Ltd"
app_description = "AI Business Assistant for Truemeal Feeds ERP"
app_email = "shivaabhiramreddy@gmail.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext"]

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

# Doc Events
doc_events = {}

# Scheduled Tasks — Alert engine + Proactive Intelligence (Sprint 7)
scheduler_events = {
    "cron": {
        # Check hourly alerts every hour at minute 5
        "5 * * * *": [
            "tm_ai_assistant.alerts.check_hourly_alerts",
        ],
        # Sprint 7: Morning briefing at 7:00 AM IST daily
        "0 7 * * *": [
            "tm_ai_assistant.briefing.generate_morning_briefing",
        ],
        # Sprint 7: Check scheduled reports every hour at minute 15
        "15 * * * *": [
            "tm_ai_assistant.scheduled_reports.check_scheduled_reports",
        ],
    },
    "daily": [
        "tm_ai_assistant.alerts.check_daily_alerts",
    ],
    "weekly": [
        "tm_ai_assistant.alerts.check_weekly_alerts",
    ],
}
