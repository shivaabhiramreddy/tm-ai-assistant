"""
AskERP — Demo Mode v1.0
==================================
Provides pre-recorded responses when no AI provider API key is configured.
Lets users explore the chat interface, understand response formatting, and
experience the product before entering a real API key.

Demo mode activates automatically when:
  1. No AskERP Model has an API key configured, OR
  2. The admin explicitly enables demo_mode in AskERP Settings

Demo responses cover common business questions and showcase features like:
  - Financial summaries with Indian formatting
  - Table formatting with multiple columns
  - Period comparisons with percentage changes
  - Alert suggestions
  - Export capability mentions
"""

import json
import re
import frappe
from frappe.utils import now_datetime


# ─── Demo Detection ────────────────────────────────────────────────────────

def is_demo_mode():
    """
    Check if the app should operate in demo mode.
    Returns True if no API keys are configured or demo_mode is explicitly on.
    """
    try:
        settings = frappe.get_single("AskERP Settings")
        # Explicit demo mode flag (if it exists on the doctype)
        if getattr(settings, "demo_mode", 0):
            return True
    except Exception:
        pass

    # Check if ANY model has an API key
    try:
        models_with_keys = frappe.db.count(
            "AskERP Model",
            filters={
                "enabled": 1,
                "api_key": ["is", "set"],
            },
        )
        return models_with_keys == 0
    except Exception:
        return True  # If we can't check, assume demo


# ─── Demo Response Engine ──────────────────────────────────────────────────

# Each demo response has a list of trigger patterns and a response template.
# The first matching pattern wins.
_DEMO_RESPONSES = [
    {
        "patterns": [
            r"revenue|sales.*today|today.*sales|how.*much.*sell",
            r"daily.*sales|sales.*daily",
        ],
        "response": (
            "**Today's Sales Summary** (Demo Data)\n\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            "| Gross Sales | ₹8.45 L |\n"
            "| Returns | ₹0.12 L |\n"
            "| Net Sales | ₹8.33 L |\n"
            "| Orders | 23 |\n"
            "| Avg Order Value | ₹3,622 |\n\n"
            "Sales are tracking 12% above yesterday (₹7.44 L). "
            "Top performers: Nellore region (₹3.2 L) and Ongole territory (₹2.1 L).\n\n"
            "💡 *This is demo data. Connect an AI provider in AskERP Settings to query your real ERP data.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"outstanding|receivable|overdue|owed|pending.*payment",
            r"dso|days.*sales.*outstanding",
        ],
        "response": (
            "**Outstanding Receivables** (Demo Data)\n\n"
            "| Aging Bucket | Amount | % of Total |\n"
            "|-------------|--------|------------|\n"
            "| 0-30 days | ₹18.50 L | 42% |\n"
            "| 31-60 days | ₹12.30 L | 28% |\n"
            "| 61-90 days | ₹8.20 L | 19% |\n"
            "| 90+ days | ₹4.80 L | 11% |\n"
            "| **Total** | **₹43.80 L** | **100%** |\n\n"
            "**DSO: 47 days** (up from 43 days last month)\n\n"
            "Top 5 overdue accounts hold ₹18.2 L (42% of outstanding). "
            "I'd recommend prioritizing collections on accounts over 60 days.\n\n"
            "💡 *This is demo data. Connect an AI provider to analyze your real receivables.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"compare|comparison|vs|versus|month.*over.*month|MoM|YoY",
            r"last.*month|previous.*month|this.*month.*vs",
        ],
        "response": (
            "**Month-over-Month Comparison** (Demo Data)\n\n"
            "| Metric | This Month | Last Month | Change |\n"
            "|--------|-----------|------------|--------|\n"
            "| Revenue | ₹1.85 Cr | ₹1.62 Cr | +14.2% |\n"
            "| Collections | ₹1.52 Cr | ₹1.31 Cr | +16.0% |\n"
            "| New Customers | 28 | 22 | +27.3% |\n"
            "| Avg Order Value | ₹4,250 | ₹3,980 | +6.8% |\n"
            "| Outstanding | ₹43.8 L | ₹38.2 L | +14.7% |\n\n"
            "Strong growth across all metrics this month. Collections are outpacing revenue growth, "
            "which is improving our cash position. Worth monitoring the outstanding increase — it's "
            "growing at the same rate as revenue, so DSO is stable.\n\n"
            "💡 *This is demo data. Connect an AI provider to compare your real periods.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"inventory|stock|warehouse|bunker|silage",
            r"low.*stock|out.*of.*stock|stock.*level",
        ],
        "response": (
            "**Inventory Snapshot** (Demo Data)\n\n"
            "| Item | Warehouse | Qty (Kg) | Reorder Level |\n"
            "|------|-----------|----------|---------------|\n"
            "| Corn Silage | Bunker A | 45,000 | 20,000 |\n"
            "| Sorghum Silage | Bunker B | 12,500 | 15,000 ⚠️ |\n"
            "| TMR Premium Mix | Main Store | 8,200 | 5,000 |\n"
            "| Paddy Straw | Dry Store | 3,800 | 10,000 ⚠️ |\n"
            "| Concentrate | Main Store | 15,600 | 8,000 |\n\n"
            "⚠️ **2 items below reorder level:** Sorghum Silage and Paddy Straw. "
            "Sorghum Silage is at 83% of reorder — procurement should be initiated this week.\n\n"
            "💡 *This is demo data. Connect an AI provider to check your real inventory.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"top.*customer|best.*customer|biggest.*customer",
            r"customer.*rank|customer.*revenue",
        ],
        "response": (
            "**Top 10 Customers by Revenue — This Month** (Demo Data)\n\n"
            "| # | Customer | Revenue | Orders | Outstanding |\n"
            "|---|----------|---------|--------|-------------|\n"
            "| 1 | Amul Dairy Coop | ₹18.5 L | 12 | ₹4.2 L |\n"
            "| 2 | Milma Federation | ₹15.2 L | 8 | ₹6.8 L |\n"
            "| 3 | Krishna Dairy Farm | ₹12.8 L | 15 | ₹1.5 L |\n"
            "| 4 | Nellore Cattle Assn | ₹9.4 L | 6 | ₹3.2 L |\n"
            "| 5 | Ongole Feed Depot | ₹8.7 L | 9 | ₹0.8 L |\n"
            "| 6 | Kavali Dairy | ₹7.1 L | 5 | ₹2.1 L |\n"
            "| 7 | Gudur Feed Center | ₹6.3 L | 7 | ₹0.5 L |\n"
            "| 8 | Prakasam Coop | ₹5.8 L | 4 | ₹4.5 L |\n"
            "| 9 | AP Milk Union | ₹5.2 L | 3 | ₹1.8 L |\n"
            "| 10 | Tirupati Feeds | ₹4.5 L | 6 | ₹0.3 L |\n\n"
            "Top 3 customers account for 51% of monthly revenue. Customer concentration risk is moderate.\n\n"
            "💡 *This is demo data. Connect an AI provider to see your real customer rankings.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"pending.*approv|approval|waiting.*approv|needs.*approv",
        ],
        "response": (
            "**Pending Approvals** (Demo Data)\n\n"
            "| Document Type | Count | Oldest |\n"
            "|--------------|-------|--------|\n"
            "| Sales Orders | 5 | 2 days ago |\n"
            "| Sales Invoices | 3 | 1 day ago |\n"
            "| Purchase Receipts | 2 | Today |\n"
            "| Payment Proposals | 1 | 3 days ago |\n"
            "| **Total** | **11** | |\n\n"
            "The Payment Proposal has been pending for 3 days — you may want to review that first.\n\n"
            "💡 *This is demo data. Connect an AI provider to see your real pending approvals.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"purchase|vendor|supplier|procurement|buying",
        ],
        "response": (
            "**Purchase Summary — This Month** (Demo Data)\n\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            "| Total Purchases | ₹1.12 Cr |\n"
            "| Payments Made | ₹95.8 L |\n"
            "| Payables Outstanding | ₹62.3 L |\n"
            "| DPO | 38 days |\n"
            "| Active Suppliers | 45 |\n\n"
            "Top 3 suppliers by spend: Maize Procurement (₹42 L), "
            "Transport Services (₹18 L), Packaging Materials (₹12 L).\n\n"
            "💡 *This is demo data. Connect an AI provider to analyze your real purchase data.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"alert|notify|watch|monitor|threshold",
        ],
        "response": (
            "**Alert System** (Demo Mode)\n\n"
            "You can set up automated alerts that monitor your business data. For example:\n\n"
            "- \"Alert me when outstanding receivables exceed ₹50 lakhs\"\n"
            "- \"Notify me when daily sales drop below ₹1 lakh\"\n"
            "- \"Watch for inventory items below reorder level\"\n\n"
            "Alerts can check hourly, daily, or weekly, and notify you via:\n"
            "- ERPNext bell notifications\n"
            "- Email\n\n"
            "To set up alerts, configure them in **AI Alert Rule** doctype, "
            "or simply ask me to create one when connected to a real AI provider.\n\n"
            "💡 *Connect an AI provider in AskERP Settings to start using alerts with your real data.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"export|pdf|excel|download|report",
        ],
        "response": (
            "**Export & Report Features** (Demo Mode)\n\n"
            "When connected to an AI provider, you can:\n\n"
            "- **Export to PDF** — Any AI response can be exported as a professionally formatted PDF\n"
            "- **Export to Excel** — Tabular data exports with company branding and formatting\n"
            "- **Scheduled Reports** — Set up recurring AI-generated reports (daily/weekly/monthly) delivered by email\n"
            "- **Morning Briefings** — Automatic daily business briefings at 7 AM for management users\n\n"
            "Reports include narrative analysis, not just raw numbers. "
            "The AI writes executive-quality commentary on your business data.\n\n"
            "💡 *Connect an AI provider in AskERP Settings to start generating reports from your real data.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
    {
        "patterns": [
            r"^(hi|hello|hey|good morning|good afternoon|good evening)",
        ],
        "response": (
            "Hello! 👋 Welcome to AskERP — your AI-powered business intelligence layer for ERPNext.\n\n"
            "I'm currently running in **demo mode** with sample data. Here's what you can try:\n\n"
            "- \"What's our revenue today?\" — Financial summaries\n"
            "- \"Show outstanding receivables\" — Aging analysis\n"
            "- \"Compare this month vs last month\" — Period comparisons\n"
            "- \"Top 10 customers by revenue\" — Rankings and lists\n"
            "- \"Check inventory levels\" — Stock snapshots\n"
            "- \"Pending approvals\" — Workflow status\n\n"
            "To connect to your real ERP data, go to **AskERP Settings** and enter your AI provider API key.\n\n"
            "💡 *Demo mode uses sample data. Your real business data is never shown until you connect an AI provider.*"
        ),
        "model": "demo-mode",
        "tokens": 0,
    },
]

# Compile patterns once at module load
for entry in _DEMO_RESPONSES:
    entry["_compiled"] = [re.compile(p, re.IGNORECASE) for p in entry["patterns"]]


def get_demo_response(message):
    """
    Match a user message against demo patterns and return a pre-recorded response.

    Args:
        message: The user's question string

    Returns:
        dict with keys: response, model, tokens_used, cost, is_demo
        or None if no pattern matches (falls through to default response)
    """
    q = message.strip()

    for entry in _DEMO_RESPONSES:
        for pat in entry["_compiled"]:
            if pat.search(q):
                return {
                    "response": entry["response"],
                    "model": "demo-mode",
                    "tokens_used": 0,
                    "cost": 0,
                    "is_demo": True,
                }

    # Default response for unmatched queries
    return {
        "response": (
            "I'm currently running in **demo mode** and can only respond to a few sample questions.\n\n"
            "**Try asking:**\n"
            "- \"What's our revenue today?\"\n"
            "- \"Show outstanding receivables\"\n"
            "- \"Compare this month vs last month\"\n"
            "- \"Top 10 customers\"\n"
            "- \"Check inventory levels\"\n"
            "- \"Pending approvals\"\n\n"
            "To get answers about **your real business data**, connect an AI provider:\n\n"
            "1. Go to **AskERP Settings** in ERPNext\n"
            "2. Enter your Anthropic, Google, or OpenAI API key\n"
            "3. The AI will start querying your live ERP data immediately\n\n"
            "💡 *Demo mode is free — no API costs are incurred.*"
        ),
        "model": "demo-mode",
        "tokens_used": 0,
        "cost": 0,
        "is_demo": True,
    }
