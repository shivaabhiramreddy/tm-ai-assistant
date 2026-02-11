# TM AI Assistant

AI Business Assistant for Truemeal Feeds ERP (ERPNext).

A custom Frappe app that provides a natural language interface to query ERPNext business data using Claude AI.

## Features

- **Natural language queries** — Ask business questions in plain English
- **Live ERP data** — Queries run against real-time ERPNext data
- **Permission-safe** — Every query respects the logged-in user's ERPNext permissions
- **Usage tracking** — Token usage and cost tracking per user
- **Rate limiting** — Configurable daily query limits per user

## API Endpoints

- `POST /api/method/tm_ai_assistant.api.chat` — Send a chat message
- `GET /api/method/tm_ai_assistant.api.chat_status` — Check AI access status
- `GET /api/method/tm_ai_assistant.api.usage` — Get usage statistics

## Setup

1. Install the app on your ERPNext instance
2. Set `anthropic_api_key` in your site config
3. Enable `allow_ai_chat` checkbox on User records for authorized users

## License

MIT
