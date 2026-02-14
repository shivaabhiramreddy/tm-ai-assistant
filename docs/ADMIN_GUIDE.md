# AskERP Frappe Plugin — Administrator Guide

Complete configuration and management guide for system administrators.

---

## Table of Contents

1. [Installation](#installation)
2. [Setup Wizard](#setup-wizard)
3. [AskERP Settings](#askerp-settings)
4. [AI Model Configuration](#ai-model-configuration)
5. [Business Profile](#business-profile)
6. [Prompt Templates](#prompt-templates)
7. [Custom Tools (No-Code Tool Builder)](#custom-tools)
8. [User Management](#user-management)
9. [Alert Rules](#alert-rules)
10. [Scheduled Reports](#scheduled-reports)
11. [Cost Management](#cost-management)
12. [Security](#security)
13. [Maintenance](#maintenance)

---

## 1. Installation

### Via Bench (self-hosted)

```bash
bench get-app https://github.com/shivaabhiramreddy/askerp-frappe
bench --site your-site.com install-app askerp
```

### Via Frappe Cloud

Go to your site's Apps page, search for "AskERP", and click Install.

### What Happens After Install

The post-install script automatically creates:

- 4 default AI model configurations (Claude Sonnet, GPT-4o, Gemini Pro, Claude Haiku)
- Default AskERP Settings with sensible defaults
- A starter Business Profile (edit this to match your company)
- 8 prompt templates covering common business questions
- 3 default custom tools (Customer Lookup, Item Search, Outstanding Summary)
- Custom fields on the User doctype (`allow_ai_chat`, `ai_preferences`)

---

## 2. Setup Wizard

On first visit after installation, administrators see a 5-step setup wizard:

1. **Welcome** — Overview of what the assistant does
2. **AI Provider** — Enter your API key and test the connection
3. **Business Profile** — Quick company context setup (industry, products, terminology)
4. **User Enablement** — Select which users should have AI chat access
5. **Completion** — Summary and redirect to start using the assistant

You can skip the wizard and configure everything manually via the doctypes described below.

---

## 3. AskERP Settings

**Navigation:** Search Bar → AskERP Settings

This is the central configuration doctype. Key fields:

### General

| Field | Description | Default |
|-------|-------------|---------|
| `setup_complete` | Whether setup wizard has been completed | 0 |
| `default_daily_limit` | Default queries per user per day | 50 |
| `monthly_budget` | Monthly spend cap in USD (0 = unlimited) | 0 |
| `demo_mode` | Force demo mode even with API keys configured | 0 |

### Model Tiers

The AI uses a tiered model system for cost optimization:

| Field | Purpose | Example |
|-------|---------|---------|
| `tier_1` | Flash/greeting queries (cheapest) | Claude Haiku |
| `tier_2` | Simple lookups | GPT-4o Mini |
| `tier_3` | Complex analysis (most capable) | Claude Sonnet |
| `utility_model` | Session titles, summaries (cheapest fast model) | Gemini Flash |
| `fallback_model` | Used when primary model fails | GPT-4o |

### Streaming

| Field | Description | Default |
|-------|-------------|---------|
| `enable_streaming` | Enable real-time token streaming | 1 |
| `stream_poll_interval` | Milliseconds between stream polls | 500 |

### Advanced

| Field | Description | Default |
|-------|-------------|---------|
| `max_tool_rounds` | Maximum tool call iterations per query | 8 |
| `max_context_messages` | Messages included in conversation context | 20 |
| `cache_ttl_minutes` | Query result cache duration | 15 |
| `precompute_enabled` | Enable hourly metric pre-computation | 1 |

---

## 4. AI Model Configuration

**Navigation:** Search Bar → AskERP Model

Each model record represents one AI provider/model combination.

### Creating a Model

| Field | Description | Example |
|-------|-------------|---------|
| `model_name` | Display name | "Claude Sonnet 4" |
| `provider` | AI provider | Anthropic / Google / OpenAI / Custom |
| `model_id` | Provider's model identifier | "claude-sonnet-4-20250514" |
| `api_key` | Your API key (stored encrypted) | sk-ant-... |
| `api_url` | API endpoint (auto-filled per provider) | https://api.anthropic.com/v1/messages |
| `enabled` | Whether this model is active | 1 |
| `max_output_tokens` | Maximum response length | 16384 |
| `supports_streaming` | Whether the model supports streaming | 1 |
| `supports_vision` | Whether the model accepts images | 1 |
| `cost_input_per_1m` | Cost per 1M input tokens (USD) | 3.00 |
| `cost_output_per_1m` | Cost per 1M output tokens (USD) | 15.00 |

### Rate Limits (Child Table)

Each model can have role-based rate limits via the **AskERP Model Limit** child table:

| Field | Description |
|-------|-------------|
| `role` | ERPNext role (e.g., "Sales User", "System Manager") |
| `daily_limit` | Maximum queries per day for users with this role |

If a user has multiple roles, the highest limit applies.

### Testing a Model

After entering the API key, use the **Test Connection** button (available in the AskERP Settings form) to verify the key works. The test sends a minimal request and reports success or failure.

---

## 5. Business Profile

**Navigation:** Search Bar → AskERP Business Profile

The business profile teaches the AI about your company. This is the most impactful configuration — a well-filled profile dramatically improves response quality.

### Sections

**Company Information:**
- Company name, industry, location, description
- Products and services (detailed descriptions help the AI)

**Financial Context:**
- Financial year start (e.g., April for Indian FY)
- Currency and number formatting preferences
- Key financial metrics your team tracks

**Terminology:**
- Business-specific terms the AI should understand
- Abbreviations and their meanings (e.g., "TMR = Total Mixed Ration")
- Custom product categories or classifications

**Operational Context:**
- Warehouse structure and naming conventions
- Territory/region definitions
- Customer segments and classifications
- Supplier categories

**Formatting Preferences:**
- Currency display format (₹, $, etc.)
- Number formatting (Indian: Lakhs/Crores, Western: Millions/Billions)
- Date format preferences
- Table style preferences

### Best Practices

1. Fill in as much detail as possible — the more context, the better the responses
2. Include your specific terminology and abbreviations
3. List your key products with descriptions
4. Describe your customer segments
5. Update the profile when business context changes (new products, new territories)

---

## 6. Prompt Templates

**Navigation:** Search Bar → AskERP Prompt Template

Prompt templates are pre-built question patterns that appear as suggestion chips in the chat interface.

### Template Fields

| Field | Description |
|-------|-------------|
| `template_name` | Display name (shown as chip text) |
| `category` | Grouping category (Financial, Sales, Inventory, etc.) |
| `prompt_text` | The actual question sent to the AI |
| `description` | Tooltip/description for the user |
| `roles` | Which roles see this template (blank = all) |
| `enabled` | Whether this template is active |

### Default Templates

The app installs 8 templates covering: daily sales summary, receivables aging, month-over-month comparison, inventory snapshot, top customers, pending approvals, purchase overview, and business health check.

### Creating Custom Templates

1. Go to AskERP Prompt Template → New
2. Enter a descriptive name (this appears as the chip text)
3. Write the prompt text — this is what the AI receives when the user taps the chip
4. Assign a category for grouping
5. Optionally restrict to specific roles
6. Save and enable

---

## 7. Custom Tools (No-Code Tool Builder) {#custom-tools}

**Navigation:** Search Bar → AskERP Custom Tool

Custom tools extend the AI's data-querying capabilities without writing Python code. Each tool becomes an additional function the AI can call when answering questions.

### How Custom Tools Work

1. You define a tool with a name, description, parameters, and a query
2. The AI sees the tool definition and decides when to use it
3. When used, the tool executes the query with the AI-provided parameters
4. Results are returned to the AI for interpretation

### Tool Types

| Type | Description | Use Case |
|------|-------------|----------|
| `ORM Query` | Uses Frappe's ORM (get_list) | Simple filtered lists |
| `Raw SQL` | Executes a parameterized SQL SELECT | Complex queries with JOINs |
| `API Method` | Calls a whitelisted Frappe method | Custom server-side logic |

### Creating a Custom Tool

**Example: "Get Customer Orders by Territory"**

1. **Tool Name:** get_territory_orders
2. **Display Name:** Territory Order Summary
3. **Description:** "Get sales order summary grouped by territory for a date range"
4. **Tool Type:** Raw SQL
5. **Parameters** (child table):
   - `from_date` (Date, required) — "Start date"
   - `to_date` (Date, required) — "End date"
   - `territory` (Data, optional) — "Filter by territory name"
6. **SQL Query:**
   ```sql
   SELECT territory, COUNT(*) as order_count, SUM(grand_total) as total_value
   FROM `tabSales Order`
   WHERE transaction_date BETWEEN %(from_date)s AND %(to_date)s
   {%- if territory %} AND territory = %(territory)s {%- endif %}
   GROUP BY territory
   ORDER BY total_value DESC
   LIMIT 50
   ```
7. **Allowed Roles:** Sales Manager, System Manager

### Security

- Custom tools can only execute SELECT queries (INSERT/UPDATE/DELETE are blocked)
- Sensitive tables (User, Auth, API Keys, etc.) are blocked
- Query execution has a 30-second timeout
- Results are limited to prevent overwhelming the AI context
- Role-based access controls which users can trigger which tools

---

## 8. User Management

### Enabling AI Chat for Users

1. Go to the User doctype → select a user
2. Check the **Allow AI Chat** checkbox
3. Save

Or use the setup wizard (Step 4) to bulk-enable users.

### Permissions Model

- Users can only query data they have ERPNext permission to see
- The AI enforces ERPNext's role-based access on every query
- Custom tool access is controlled via the tool's Allowed Roles field
- Usage logs are per-user and visible to System Manager

---

## 9. Alert Rules

**Navigation:** Search Bar → AI Alert Rule

### Alert Configuration

| Field | Description |
|-------|-------------|
| `alert_name` | Descriptive name |
| `query_doctype` | ERPNext doctype to query |
| `query_field` | Field to aggregate |
| `query_aggregation` | SUM, COUNT, AVG, MAX, or MIN |
| `query_filters` | JSON filters (same as ERPNext API filters) |
| `threshold_operator` | >, <, >=, <=, =, != |
| `threshold_value` | The value to compare against |
| `frequency` | hourly, daily, or weekly |
| `active` | Enable/disable the alert |

### Alert Notification Channels

When triggered, alerts send:

1. **ERPNext Notification** — appears in the bell icon (Notification Log)
2. **Email** — sent to the alert owner's email address

### Monitoring

Each alert tracks: `last_checked`, `last_triggered`, `last_value`, and `trigger_count`.

---

## 10. Scheduled Reports

**Navigation:** Search Bar → AI Scheduled Report

Set up recurring AI-generated reports delivered by email.

| Field | Description |
|-------|-------------|
| `report_name` | Display name |
| `prompt` | The question/prompt the AI answers |
| `frequency` | daily, weekly, monthly |
| `recipients` | Email addresses (comma-separated) |
| `format` | Response format (text, PDF, Excel) |
| `active` | Enable/disable |

### Morning Briefing

A special scheduled report type. When enabled, management users receive a daily business briefing at 7:00 AM with key metrics.

---

## 11. Cost Management

### Understanding Costs

The app itself is free/paid software. The AI provider costs are separate — you pay your chosen provider (Anthropic, Google, OpenAI) directly based on token usage.

### Cost Controls

1. **Daily query limits** — Cap queries per user per day
2. **Monthly budget** — Set a monthly spend cap in AskERP Settings
3. **Smart routing** — Simple questions use cheaper models automatically
4. **Query caching** — Identical questions within the TTL are served from cache (zero cost)
5. **Pre-computation** — Common metrics are pre-calculated hourly (reduces query complexity)
6. **Prompt caching** — System prompt is cached by the provider (90% token savings on Anthropic)

### Cost Analytics Dashboard

**Navigation:** Search Bar → AI Cost Analytics (Report)

The built-in report shows:

- Total cost by day/week/month
- Cost breakdown by user, model, and complexity tier
- Cache hit rate (higher = more savings)
- Average cost per query
- Token usage trends

### Typical Costs

| Provider | Model | Simple Query | Complex Query |
|----------|-------|-------------|---------------|
| Anthropic | Claude Haiku | $0.001 | $0.005 |
| Anthropic | Claude Sonnet | $0.01 | $0.05 |
| Google | Gemini Flash | $0.0005 | $0.003 |
| Google | Gemini Pro | $0.005 | $0.03 |
| OpenAI | GPT-4o Mini | $0.001 | $0.005 |
| OpenAI | GPT-4o | $0.01 | $0.05 |

*Costs are approximate and depend on query complexity, response length, and provider pricing.*

---

## 12. Security

### API Key Storage

API keys are stored using ERPNext's encrypted Password field type. They are never exposed in API responses, browser console, or error logs.

### SQL Safety

- All queries are read-only (SELECT only)
- Sensitive tables are blocked (User, Auth, API Keys, Sessions, etc.)
- Queries have a 30-second timeout
- Results are row-limited to prevent memory issues
- User-provided SQL in custom tools is validated before execution

### Data Access

- The AI respects ERPNext user permissions on every query
- Users can only access data their ERPNext role allows
- The AI cannot create, update, or delete any ERPNext records

### Rate Limiting

- Configurable daily query limits per user/role
- Monthly budget caps prevent runaway costs
- Priority queue prevents system overload from concurrent users

---

## 13. Maintenance

### Scheduler Jobs

The app runs these background jobs:

| Schedule | Job | Description |
|----------|-----|-------------|
| Every hour (:05) | Alert check (hourly) | Evaluates hourly alert rules |
| Every hour (:15) | Scheduled reports | Checks and sends due reports |
| Every hour (:30) | Pre-compute metrics | Refreshes cached business metrics |
| Daily at 7 AM IST | Morning briefing | Generates and emails daily briefings |
| Daily | Alert check (daily) | Evaluates daily alert rules |
| Weekly | Alert check (weekly) | Evaluates weekly alert rules |

### Logs

- **AI Usage Log** — Every query is logged with user, tokens, cost, model, complexity tier
- **AI Chat Session** — Full conversation history with messages
- **Error Log** — Standard ERPNext error log captures any AI engine errors

### Updating the App

```bash
# Self-hosted
bench update --apps askerp
bench --site your-site.com migrate

# Frappe Cloud
# Update from the Apps page on your site dashboard
```

### Cache Management

The query cache and pre-computed metrics are stored in Redis. They auto-expire based on TTL. To manually clear:

1. Query cache clears automatically when business data changes (Sales Invoice submitted, etc.)
2. Pre-computed metrics refresh every hour
3. Business profile and template caches clear when you save changes to those doctypes

### Uninstalling

```bash
bench --site your-site.com uninstall-app askerp
bench remove-app askerp
```

This removes all app doctypes and data. Chat sessions and usage logs will be deleted.
