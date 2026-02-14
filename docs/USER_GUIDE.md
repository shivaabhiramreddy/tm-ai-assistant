# AskERP Frappe Plugin — User Guide

A practical guide for everyday users of the AI chat assistant in ERPNext.

---

## Getting Started

Once your administrator enables AI chat for your account, a small green chat bubble appears in the bottom-right corner of every ERPNext page. Tap it to open the AI assistant.

### First Conversation

Type a business question in plain language. The AI understands your company context, products, customers, and financial data. You don't need SQL or report names — just ask naturally.

**Examples of what you can ask:**

- "What are today's sales?"
- "Show outstanding receivables over 60 days"
- "Compare this month's revenue to last month"
- "Who are our top 10 customers by revenue?"
- "What's our DSO right now?"
- "How much inventory do we have of [item name]?"

### Chat Modes

The chat panel opens in **half-screen mode** by default. You can:

- **Expand to full screen** — tap the expand icon in the header
- **Collapse back** — tap the collapse icon
- **Close** — tap the X button or the chat bubble again

---

## Asking Questions

### Financial Questions

The AI can pull live data from your ERPNext and present it with formatting, tables, and analysis.

- "What's our revenue this month?"
- "Show purchase summary for last quarter"
- "What are our payables outstanding?"
- "Calculate DSO and DPO for this financial year"
- "How are collections trending week over week?"

### Comparisons

Ask the AI to compare any two time periods:

- "Compare January vs February sales"
- "How did Q3 compare to Q2?"
- "Show this month vs same month last year"

The AI returns a formatted table with amounts and percentage changes.

### Document Lookups

Find specific documents quickly:

- "Show me Sales Order SO-00542"
- "What's the status of Purchase Invoice PI-2025-03-0012?"
- "List all pending Sales Orders"

### Customer & Supplier Analysis

- "Who are our top 5 customers by outstanding?"
- "Show supplier payment history for [supplier name]"
- "Which customers haven't ordered in 90 days?"

### Inventory

- "What's the stock level of Corn Silage?"
- "Show items below reorder level"
- "Warehouse-wise stock of TMR Premium Mix"

---

## Understanding Responses

### Tables

When the AI returns data, it formats it as a readable table with columns aligned. Currency values use Indian formatting (Lakhs, Crores with the ₹ symbol).

### Analysis

For complex questions, the AI provides not just data but also interpretation — trends, recommendations, and observations based on your business context.

### Tool Calls

Sometimes the AI needs multiple steps to answer your question. You may see brief indicators like "Querying sales data..." or "Calculating metrics..." as the AI works through the steps. This is normal for complex analysis.

---

## Exporting Responses

Any AI response can be exported for sharing or record-keeping.

### Export to PDF

After receiving a response, use the export option to generate a professionally formatted PDF. The PDF includes your company branding and the full AI response with tables and formatting preserved.

### Export to Excel

Tabular data can be exported to Excel (.xlsx) with proper column formatting and company headers. Useful for further analysis in spreadsheets.

---

## Alerts

You can ask the AI to set up automated alerts that monitor your business data.

### Creating Alerts

Simply ask:

- "Alert me when outstanding receivables exceed ₹50 lakhs"
- "Notify me when daily sales drop below ₹1 lakh"
- "Watch for inventory items below reorder level"

The AI creates the alert rule for you. You can choose monitoring frequency: hourly, daily, or weekly.

### How Alerts Work

When an alert condition is met:

1. You receive a **bell notification** in ERPNext (top-right notification area)
2. You receive an **email notification** with the alert details and current value

### Managing Alerts

- "Show my active alerts" — lists all your alert rules
- "Delete the receivables alert" — removes a specific alert
- You can also manage alerts directly in the **AI Alert Rule** doctype in ERPNext

---

## Scheduled Reports

Set up recurring AI-generated reports delivered to your email.

### Creating a Report

- "Send me a daily sales summary at 8 AM"
- "Email me a weekly receivables aging report every Monday"
- "Schedule a monthly revenue comparison report"

### Morning Briefing

Management users can receive an automatic morning briefing at 7:00 AM with key metrics: yesterday's sales, collections, outstanding changes, inventory alerts, and pending approvals.

---

## Sessions & History

### Session Persistence

Your conversations are saved automatically. If you close the chat and reopen it, your recent conversation is still there.

### Starting a New Conversation

Click the "New Chat" option in the chat header to start a fresh session. Your previous session is archived and can be accessed later.

### Browsing Past Sessions

You can view your chat history — past sessions are listed with their title and date. Tap any session to reload the conversation.

### Searching Conversations

Use the search feature to find past conversations by keyword. The AI searches across all your session history.

---

## Tips for Better Results

1. **Be specific** — "Show revenue for March 2026" works better than "show me some numbers"
2. **Use business terms** — The AI understands your company's terminology, product names, and customer names
3. **Ask follow-ups** — The AI remembers context within a session, so you can ask "break that down by territory" after getting a revenue summary
4. **Use natural dates** — "last month", "this quarter", "past 7 days", "yesterday" all work
5. **Request formats** — "Show as a table", "give me percentages", "include totals" help the AI format responses the way you want

---

## Troubleshooting

### "AI chat is not enabled for your account"

Your administrator needs to enable the **Allow AI Chat** checkbox on your User record in ERPNext. Contact your system administrator.

### Slow responses

Complex analysis (comparisons, multi-step queries) may take 10-20 seconds. Simple lookups are typically under 5 seconds. If responses are consistently slow, check with your administrator about the AI model configuration.

### "Daily query limit reached"

Each user has a configurable daily query limit to manage API costs. The limit resets at midnight. Contact your administrator to increase your limit if needed.

### Incorrect data

The AI queries your live ERPNext data. If numbers seem wrong, verify the source data in ERPNext first. The AI respects your user permissions — you only see data you have access to in ERPNext.

---

## Demo Mode

If your administrator hasn't configured an AI provider yet, the assistant runs in **demo mode** with sample data. Demo responses are clearly marked with a disclaimer. No API costs are incurred in demo mode.

To switch to live data, your administrator needs to enter an AI provider API key in **AskERP Settings**.
