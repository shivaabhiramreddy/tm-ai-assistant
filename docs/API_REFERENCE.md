# AskERP Frappe Plugin — API Reference

Developer documentation for extending and integrating with the AI assistant.

---

## Authentication

All API endpoints require a valid Frappe session. Authenticate using one of:

- **Session cookie** — Standard Frappe web login
- **API key/secret** — `Authorization: token {api_key}:{api_secret}` header

---

## Endpoints

### Chat (Synchronous)

Send a message and receive the full response.

```
POST /api/method/askerp.api.chat
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | string | Yes | The user's question (max 5000 chars) |
| `session_id` | string | No | Existing session ID to continue a conversation |

**Response:**

```json
{
  "message": {
    "response": "**Today's Sales Summary**\n\n| Metric | Value |\n...",
    "session_id": "abc123-def456",
    "session_title": "Today's Sales Summary",
    "message_count": 4,
    "usage": {
      "input_tokens": 2450,
      "output_tokens": 680,
      "total_tokens": 3130,
      "cache_read_tokens": 7200,
      "cache_creation_tokens": 0
    },
    "cost": {
      "cost_input": 0.007,
      "cost_output": 0.010,
      "cost_total": 0.017
    },
    "tool_calls": 2,
    "model": "claude-sonnet-4-20250514",
    "tier": "tier_3",
    "daily_queries_remaining": 47,
    "is_demo": false
  }
}
```

### Chat Start (Streaming)

Start a streaming chat session. Returns a stream ID for polling.

```
POST /api/method/askerp.api.chat_start
```

**Parameters:** Same as `chat`.

**Response:**

```json
{
  "message": {
    "stream_id": "stream-xyz789",
    "session_id": "abc123-def456"
  }
}
```

### Stream Poll

Poll for streaming tokens from an active stream.

```
GET /api/method/askerp.api.stream_poll
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stream_id` | string | Yes | Stream ID from `chat_start` |

**Response:**

```json
{
  "message": {
    "tokens": [
      {"type": "text", "text": "**Today's Sales"},
      {"type": "text", "text": " Summary**\n\n"},
      {"type": "tool_start", "tool": "run_sql_query"},
      {"type": "tool_end", "tool": "run_sql_query"},
      {"type": "text", "text": "| Metric | Value |\n"}
    ],
    "done": false,
    "error": null
  }
}
```

When `done` is `true`, the final response includes full usage/cost data matching the synchronous `chat` response format.

### Chat Status

Check if the current user has AI chat access.

```
GET /api/method/askerp.api.chat_status
```

**Response:**

```json
{
  "message": {
    "enabled": true,
    "daily_limit": 50,
    "daily_used": 12,
    "demo_mode": false,
    "setup_complete": true
  }
}
```

### Usage

Get usage statistics for the current user.

```
GET /api/method/askerp.api.usage
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `period` | string | No | "today", "week", "month" (default: "today") |

**Response:**

```json
{
  "message": {
    "queries_today": 12,
    "queries_this_week": 45,
    "queries_this_month": 180,
    "cost_today": 0.42,
    "cost_this_week": 1.85,
    "cost_this_month": 7.20,
    "daily_limit": 50,
    "monthly_budget": 100.00,
    "monthly_budget_used": 7.20
  }
}
```

### Alerts

Get alert status for the current user.

```
GET /api/method/askerp.api.alerts
```

**Response:**

```json
{
  "message": {
    "active_alerts": 3,
    "triggered_today": 1,
    "alerts": [
      {
        "name": "ALR-001",
        "alert_name": "High Receivables",
        "threshold_value": 5000000,
        "last_value": 5234000,
        "last_triggered": "2026-02-14 09:05:00",
        "active": 1
      }
    ]
  }
}
```

### Get Session

Load messages from a specific chat session.

```
GET /api/method/askerp.api.get_session
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | The session ID to load |

**Response:**

```json
{
  "message": {
    "session_id": "abc123-def456",
    "title": "Revenue Analysis",
    "messages": [
      {
        "role": "user",
        "content": "What's our revenue this month?",
        "timestamp": "2026-02-14 10:30:00"
      },
      {
        "role": "assistant",
        "content": "**Monthly Revenue Summary**\n\n...",
        "timestamp": "2026-02-14 10:30:15"
      }
    ],
    "created": "2026-02-14 10:30:00",
    "message_count": 4
  }
}
```

### List Sessions

List recent chat sessions for the current user.

```
GET /api/method/askerp.api.list_sessions
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | int | No | Number of sessions (default: 20) |
| `offset` | int | No | Pagination offset (default: 0) |

**Response:**

```json
{
  "message": {
    "sessions": [
      {
        "session_id": "abc123-def456",
        "title": "Revenue Analysis",
        "message_count": 4,
        "created": "2026-02-14 10:30:00",
        "modified": "2026-02-14 10:35:00"
      }
    ],
    "total": 42
  }
}
```

### Close Session

Archive a chat session.

```
POST /api/method/askerp.api.close_session
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | Session to archive |

### Search Sessions

Search across past conversations.

```
GET /api/method/askerp.api.search_sessions
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search term |
| `limit` | int | No | Max results (default: 10) |

### Upload File

Upload an image for Claude Vision analysis.

```
POST /api/method/askerp.api.upload_file
```

**Parameters:** Multipart form data with `file` field.

**Response:**

```json
{
  "message": {
    "file_url": "/files/upload-abc123.png",
    "file_name": "warehouse-photo.png",
    "content_type": "image/png"
  }
}
```

### Transcribe Audio

Convert voice recording to text using Whisper.

```
POST /api/method/askerp.api.transcribe_audio
```

**Parameters:** Multipart form data with `audio` field.

**Response:**

```json
{
  "message": {
    "text": "What are today's sales?",
    "language": "en",
    "duration": 2.5
  }
}
```

### Test Connection

Test an AI model's API connectivity.

```
POST /api/method/askerp.api.test_connection
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model_name` | string | Yes | Name of the AskERP Model to test |

**Response:**

```json
{
  "message": {
    "success": true,
    "message": "Connection successful. Model responded in 1.2s.",
    "model_id": "claude-sonnet-4-20250514",
    "provider": "Anthropic"
  }
}
```

---

## Setup Wizard Endpoints

These endpoints power the 5-step setup wizard.

```
GET  /api/method/askerp.setup_wizard.get_setup_status
POST /api/method/askerp.setup_wizard.test_api_key
POST /api/method/askerp.setup_wizard.save_provider
POST /api/method/askerp.setup_wizard.save_business_profile
POST /api/method/askerp.setup_wizard.get_users_for_enablement
POST /api/method/askerp.setup_wizard.save_user_enablement
POST /api/method/askerp.setup_wizard.complete_setup
POST /api/method/askerp.setup_wizard.skip_setup
```

---

## Custom Doctypes

| Doctype | Purpose | Key Fields |
|---------|---------|------------|
| **AskERP Settings** | Global configuration (singleton) | tiers, limits, budgets, streaming, caching |
| **AskERP Model** | AI provider/model configuration | provider, model_id, api_key, costs, capabilities |
| **AskERP Model Limit** | Role-based rate limits (child of Model) | role, daily_limit |
| **AskERP Business Profile** | Company context for AI (singleton) | industry, products, terminology, formatting |
| **AskERP Prompt Template** | Suggestion chip templates | prompt_text, category, roles |
| **AskERP Custom Tool** | No-code tool definitions | tool_type, query, parameters, allowed_roles |
| **AskERP Tool Parameter** | Tool parameter definitions (child) | param_name, param_type, required, description |
| **AI Chat Session** | Conversation storage | session_id, user, title, messages (JSON) |
| **AI Usage Log** | Per-query cost/token tracking | user, model, tokens, cost, tier, complexity |
| **AI Alert Rule** | Automated monitoring rules | query, threshold, frequency, notification |
| **AI Scheduled Report** | Recurring AI report definitions | prompt, frequency, recipients, format |
| **AskERP Cached Metric** | Pre-computed metric cache | metric_key, value, last_refreshed |

---

## Extending the AI

### Adding a New Built-in Tool

Edit `ai_engine.py` to add a new tool definition in the tools list and a corresponding `_exec_` function:

```python
# 1. Add tool definition (Claude tool_use format)
{
    "name": "my_new_tool",
    "description": "What this tool does — be specific for the AI",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"]
    }
}

# 2. Add execution function
def _exec_my_new_tool(params, user):
    """Execute the tool and return results."""
    # Query ERPNext data...
    return {"data": results}

# 3. Register in the tool dispatch map
```

### Adding a Custom Tool (No-Code)

Use the AskERP Custom Tool doctype instead of writing code. See the Admin Guide for details.

### Adding a New Provider

Edit `providers.py` to add support for a new AI provider:

1. Add the provider name to the `provider` Select field options in `askerp_model.json`
2. Implement the provider's API call pattern in `providers.py` → `call_model()`
3. Add default API URL and any provider-specific headers
4. Test with a minimal query

### Hooking into Doc Events

The app clears query caches when business data changes. To add cache invalidation for additional doctypes, edit `hooks.py`:

```python
doc_events = {
    "Your Custom Doctype": {
        "on_submit": "askerp.query_cache.clear_cache_for_doctype",
        "on_cancel": "askerp.query_cache.clear_cache_for_doctype",
    },
}
```

---

## Error Handling

All endpoints return standard Frappe error responses:

```json
{
  "exc_type": "ValidationError",
  "exception": "askerp.api.chat: Daily query limit reached",
  "_server_messages": "[\"Daily query limit reached. You have used 50/50 queries today.\"]"
}
```

Common error scenarios:

| HTTP Status | Cause | Resolution |
|-------------|-------|------------|
| 403 | User doesn't have `allow_ai_chat` enabled | Enable on User doctype |
| 429 | Daily query limit reached | Wait for reset or increase limit |
| 500 | AI provider API error | Check API key, provider status |
| 500 | Query timeout (30s) | Simplify the question or check ERPNext performance |

---

## Rate Limiting

Rate limits are checked in this order:

1. **Role-based limit** from AskERP Model Limit child table (highest role wins)
2. **Default daily limit** from AskERP Settings
3. **Hardcoded fallback** of 50 queries/day

The `daily_queries_remaining` field in chat responses tells the client how many queries are left.

---

## Demo Mode

When no AI models have API keys configured (or `demo_mode` is explicitly enabled in AskERP Settings), the chat endpoint returns pre-recorded responses for common business questions. The response includes `"is_demo": true` so the client can display appropriate disclaimers.

Demo mode incurs zero API costs and zero token usage.
