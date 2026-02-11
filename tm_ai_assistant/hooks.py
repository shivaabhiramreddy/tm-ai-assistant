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
        "filters": [["fieldname", "=", "allow_ai_chat"]],
    }
]

# Website
website_route_rules = []

# Whitelisted methods accessible via /api/method/
# These are the API endpoints the mobile app calls
override_whitelisted_methods = {}

# Doc Events
doc_events = {}

# Scheduled Tasks
scheduler_events = {}
