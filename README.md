# AskERP Frappe Plugin

> The ERPNext/Frappe connector for AskERP — Cogniverse's AI-powered business intelligence product. Adds an AI chat widget to your ERPNext instance. Ask questions in plain English, get instant answers from your live ERP data.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](license.txt)
[![Frappe Framework](https://img.shields.io/badge/Frappe-v15+-blue.svg)](https://frappeframework.com)
[![ERPNext](https://img.shields.io/badge/ERPNext-v15+-blue.svg)](https://erpnext.com)

## What Is This?

The AskERP Frappe Plugin is a Frappe custom app that adds an **AI chat widget** to every page in your ERPNext instance. Your team can ask business questions in natural language and get answers backed by real-time ERP data — no SQL, no report builder, no exports.

This plugin is part of the **AskERP** product by [Cogniverse](https://cogniverse.ai). AskERP supports multiple ERPs through separate plugins — this is the ERPNext/Frappe connector.

**Example questions your team can ask:**

- "What's our revenue this month vs last month?"
- "Show me the top 10 customers by outstanding amount"
- "How many sales orders are pending approval?"
- "Compare this quarter's purchases with the same quarter last year"
- "What's our DSO trend over the last 6 months?"

The AI queries your live ERPNext data, respects user permissions, and returns formatted answers with tables, charts, and actionable insights.

## Key Features

### Chat Widget
A floating chat bubble on every ERPNext page. Click to open a half-screen or full-screen chat panel. Works on desktop and mobile browsers.

### Multi-Provider AI Support
Works with **Anthropic (Claude)**, **Google (Gemini)**, and **OpenAI (GPT-4o)**. Bring your own API key — your data never leaves your control.

### Smart Query Routing
Simple questions use a lightweight model (fast and cheap). Complex analysis uses a powerful model (thorough and accurate). You configure which model handles which tier.

### Business Profile
Tell the AI about your company — industry, products, terminology, financial year, reporting preferences. The AI uses this context to give relevant, industry-aware answers instead of generic responses.

### Configurable Prompt Templates
Three tiers of system prompts (Executive, Management, Field Staff) that control the depth and style of AI responses. Edit them from the ERPNext UI — no code changes needed.

### No-Code Tool Builder
Create custom AI tools from the ERPNext interface. Define a tool name, description, parameters, and a SQL or Python query. The AI automatically uses your custom tools when relevant.

### Alert System
Set up threshold-based alerts: "Notify me when outstanding receivables exceed ₹50 lakhs" or "Alert me when daily sales drop below ₹1 lakh." Alerts check hourly, daily, or weekly and deliver via ERPNext notifications and email.

### Morning Briefings
Automated daily business briefings delivered at 7 AM to management users. Covers yesterday's sales, collections, pending approvals, and priority items.

### Scheduled Reports
Configure recurring AI-generated reports (daily, weekly, monthly) delivered by email. The AI analyzes your data and writes a narrative report — not just numbers.

### Session Persistence
Conversations are saved server-side. Resume where you left off, search past conversations, and reference insights from previous sessions.

### Response Streaming
See the AI's response appear in real-time as it generates, instead of waiting for the full response.

### PDF & Excel Export
Export any AI response to PDF or Excel with one click. Professional formatting with your company branding.

### Cost Analytics Dashboard
Built-in Script Report showing AI usage costs by day, user, model, and query complexity. Monitor spending and optimize model allocation.

### Pre-Computation Engine
Frequently-needed business metrics are pre-computed hourly and cached. The AI reads cached values instead of running live SQL — making responses up to 10x faster.

### Query Result Cache
Identical queries within a configurable TTL return cached results instantly, reducing API costs and database load.

### Permission-Safe
Every data query respects the logged-in user's ERPNext permissions. A Sales Manager sees only their territory's data. An accountant sees financial data but not HR records.

### Setup Wizard
A 5-step guided setup that walks you through: API key configuration, business profile, user enablement, and completion — all from the browser.

## Installation

### Prerequisites

- ERPNext v15 or later on Frappe Cloud or self-hosted
- An API key from at least one AI provider:
  - [Anthropic](https://console.anthropic.com/) (recommended)
  - [Google AI Studio](https://aistudio.google.com/)
  - [OpenAI](https://platform.openai.com/)

### Install via Bench

```bash
# Get the app
bench get-app https://github.com/shivaabhiramreddy/askerp-frappe

# Install on your site
bench --site your-site.localhost install-app askerp

# Run migrations
bench --site your-site.localhost migrate
```

### Install on Frappe Cloud

1. Go to your site's **Apps** page on Frappe Cloud
2. Click **Add App** → enter the GitHub URL
3. Click **Install** and wait for the deploy

### Post-Install Setup

After installation, a **setup wizard** appears automatically for System Managers:

1. **Welcome** — Overview of what the app does
2. **AI Provider** — Enter your API key (tested immediately)
3. **Business Profile** — Company name, industry, and description
4. **User Access** — Select which users can access the AI chat
5. **Done** — Start chatting!

You can also configure everything manually from `AskERP Settings` in the ERPNext sidebar.

## Configuration

### AskERP Settings (Single DocType)

The central configuration hub. Access via the ERPNext search bar → "AskERP Settings".

| Setting | Description |
|---------|-------------|
| **Tier 1 Model** | Economy model for simple queries (e.g., Gemini Flash) |
| **Tier 2 Model** | Standard model for most queries (e.g., Claude Sonnet) |
| **Tier 3 Model** | Premium model for complex analysis (e.g., Claude Opus) |
| **Utility Model** | Used for internal tasks (titles, summaries) |
| **Fallback Model** | Used when the primary model fails |
| **Smart Routing** | Auto-select model based on query complexity |
| **Monthly Budget** | Maximum AI spend per month (in USD) |
| **Cache TTL** | How long to cache query results (minutes) |

### AskERP Model (DocType)

Configure each AI model individually:

- Model name and ID (e.g., `claude-sonnet-4-5-20250929`)
- Provider (Anthropic / Google / OpenAI / Custom)
- API key and base URL
- Token budgets per complexity tier
- Cost per million tokens (input/output/cache)
- Rate limits per role

### AskERP Business Profile (Single DocType)

Tell the AI about your business:

- Company identity (name, industry, location, size)
- Products and services (what you sell, what you buy)
- Sales channels and customer types
- Manufacturing and operations details
- Financial focus areas and accounting preferences
- Custom terminology and abbreviations
- AI personality and communication style

### AskERP Prompt Template (DocType)

Customize the system prompt for each user tier:

- **Executive** — Full CFO/CTO/CEO intelligence
- **Management** — Department-level analysis
- **Field Staff** — Quick lookups, minimal analysis

Templates support `{{variable}}` placeholders replaced at runtime with live business context.

### AskERP Custom Tool (DocType)

Build custom AI tools without code:

- Tool name and description (the AI reads this to decide when to use the tool)
- Parameters with types and descriptions
- Query type: SQL or Python
- Query template with `{{parameter}}` placeholders

## API Reference

All endpoints require authentication via Frappe session or API key.

### Chat

```
POST /api/method/askerp.api.chat
```

Send a message and get an AI response.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | Yes | The user's question |
| `session_id` | string | No | Resume an existing session |

**Response:**
```json
{
  "message": {
    "response": "Your revenue this month is ₹45.23 L...",
    "session_id": "abc123def456",
    "tokens_used": 1250,
    "model": "claude-sonnet-4-5-20250929",
    "cost": 0.0045
  }
}
```

### Streaming Chat

```
POST /api/method/askerp.api.chat_start
GET  /api/method/askerp.api.stream_poll?stream_id=xxx
```

Start a streaming chat and poll for tokens as they arrive.

### Chat Status

```
GET /api/method/askerp.api.chat_status
```

Check if the current user has AI chat access.

### Usage Statistics

```
GET /api/method/askerp.api.usage
```

Get the current user's query count, remaining quota, and cost summary.

### Session Management

```
GET  /api/method/askerp.api.list_sessions
GET  /api/method/askerp.api.get_session?session_id=xxx
POST /api/method/askerp.api.close_session
GET  /api/method/askerp.api.search_sessions?q=revenue
```

### Alerts

```
GET /api/method/askerp.api.alerts
```

Get alert status and recent triggers for the current user.

### File Upload (Vision)

```
POST /api/method/askerp.api.upload_file
```

Upload an image for AI analysis (requires a vision-capable model).

### Voice Transcription

```
POST /api/method/askerp.api.transcribe_audio
```

Upload audio for speech-to-text transcription.

### Connection Test

```
POST /api/method/askerp.api.test_connection
```

Test if a specific AI model's API key and endpoint are working.

## Custom Doctypes

| DocType | Purpose |
|---------|---------|
| **AskERP Settings** | Central configuration (singleton) |
| **AskERP Model** | AI model configs with API keys and pricing |
| **AskERP Business Profile** | Company context for the AI (singleton) |
| **AskERP Prompt Template** | Customizable system prompts per tier |
| **AskERP Custom Tool** | No-code tool definitions |
| **AskERP Tool Parameter** | Parameters for custom tools (child table) |
| **AskERP Model Limit** | Rate limits per role (child table) |
| **AI Chat Session** | Conversation storage |
| **AI Usage Log** | Per-query cost and usage tracking |
| **AI Alert Rule** | Threshold-based business alerts |
| **AI Scheduled Report** | Recurring AI-generated reports |
| **AskERP Cached Metric** | Pre-computed business metrics |

## Security

- **No data leaves your server** — AI queries are constructed server-side and only the question + relevant data goes to the AI provider
- **Permission enforcement** — Every query runs as the logged-in user with their ERPNext permissions
- **SQL safety** — All queries are SELECT-only with sensitive table blocklists, auto-LIMIT, and query timeout protection
- **Rate limiting** — Configurable daily query limits per user role
- **Budget limits** — Monthly spend caps prevent runaway costs
- **API key storage** — Keys stored in ERPNext's encrypted Password field type
- **No admin access** — The AI cannot create, update, or delete any ERPNext records

## Cost Management

You bring your own AI API key, so costs depend on your usage and model selection. Typical costs:

| Model | Simple Query | Complex Analysis |
|-------|-------------|-----------------|
| Gemini 2.0 Flash | ~$0.001 | ~$0.005 |
| Claude Haiku 4.5 | ~$0.003 | ~$0.015 |
| Claude Sonnet 4.5 | ~$0.01 | ~$0.05 |
| Claude Opus 4.5 | ~$0.05 | ~$0.25 |

The built-in **Cost Analytics Dashboard** (Script Report) shows your actual spending by day, user, model, and complexity.

**Cost optimization features:**
- Smart routing sends simple questions to cheap models
- Query result caching avoids redundant API calls
- Pre-computed metrics skip expensive SQL for common questions
- Token optimization summarizes large result sets before sending to the AI

## Demo Mode

Install the app without an API key to explore features in demo mode. Demo mode uses pre-recorded responses for common business questions so you can experience the interface before committing to an AI provider.

To activate demo mode, simply skip the API key step in the setup wizard — or leave all AskERP Model records without API keys.

## Scheduled Jobs

| Schedule | Job | Purpose |
|----------|-----|---------|
| Every hour (:05) | `alerts.check_hourly_alerts` | Evaluate hourly alert rules |
| Every hour (:15) | `scheduled_reports.check_scheduled_reports` | Generate due reports |
| Every hour (:30) | `precompute.refresh_cached_metrics` | Refresh pre-computed metrics |
| Daily (7 AM IST) | `briefing.generate_morning_briefing` | Morning business briefing |
| Daily | `alerts.check_daily_alerts` | Evaluate daily alert rules |
| Weekly | `alerts.check_weekly_alerts` | Evaluate weekly alert rules |

## Extending the App

### Adding Custom Tools via UI

1. Go to **AskERP Custom Tool** → New
2. Set a tool name (e.g., `check_delivery_status`)
3. Write a description the AI can understand
4. Add parameters (e.g., `sales_order` of type `string`)
5. Write the SQL or Python query template
6. Save and the AI will start using it automatically

### Adding Custom Tools via Code

Register tools in `default_tools.py` following the existing pattern. Each tool needs:
- A function in `ai_engine.py` that executes the tool logic
- A tool definition dict with name, description, and input schema

## Troubleshooting

**"AI Chat is not enabled for your account"**
→ Ask your System Manager to check the `Allow AI Chat` checkbox on your User record.

**"Daily query limit reached"**
→ Your admin has set a daily limit. Wait until tomorrow or ask them to increase your limit in AskERP Model rate limits.

**"No AI models configured"**
→ Go to AskERP Settings and configure at least one model with a valid API key.

**Chat widget not appearing**
→ Clear browser cache and reload. Check the browser console for JavaScript errors.

**Slow responses**
→ Check AskERP Settings → enable Smart Routing to use faster models for simple queries. Pre-compute common metrics via AskERP Cached Metric.

## License

MIT — see [license.txt](license.txt)
