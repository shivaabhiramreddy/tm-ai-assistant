# Frappe Marketplace Listing — AskERP Frappe Plugin

Use this content when submitting to the Frappe Marketplace.

---

## App Name

AskERP

## Tagline

AI-powered business intelligence for ERPNext

## Category

Tools

## Short Description (200 chars)

Chat widget for ERPNext that answers business questions using your live ERP data. Supports Claude, Gemini, and GPT. Smart routing, alerts, scheduled reports, and cost analytics built-in.

## Full Description

AskERP adds an AI-powered chat widget to every page in your ERPNext instance. Your team asks questions in plain English and gets instant, data-backed answers — no SQL, no report builder, no data exports needed.

### What It Does

- Floating chat bubble on every ERPNext page (desktop and mobile browser)
- Queries your live ERPNext data: sales, purchases, inventory, accounts, and more
- Multi-provider AI: works with Anthropic (Claude), Google (Gemini), and OpenAI (GPT-4o)
- Smart query routing: simple questions use cheaper models, complex analysis uses premium models
- Automated alerts: monitor thresholds and get notified by bell or email
- Scheduled reports: recurring AI-generated reports delivered by email
- Morning briefings: daily business overview for management
- PDF and Excel export: share AI responses as professional documents
- Cost analytics dashboard: track AI usage and spending
- Demo mode: explore the app without an API key using sample data

### How It Works

1. Install the app on your ERPNext site
2. Run the 5-step setup wizard (or configure manually)
3. Enter your AI provider API key (you bring your own key)
4. Enable AI chat for your users
5. Users start asking questions — the AI handles the rest

### Key Features

- **No-code tool builder**: Create custom data queries without writing Python
- **Business profile**: Teach the AI your terminology, products, and formatting preferences
- **Prompt templates**: Pre-built suggestion chips for common questions
- **Session persistence**: Conversations are saved and searchable
- **User permissions respected**: The AI only shows data each user has access to
- **Query caching**: Repeated questions served from cache (zero cost)
- **Pre-computed metrics**: Common business metrics refreshed hourly
- **Priority queue**: Executives served first during high-concurrency periods

### Requirements

- ERPNext v15+
- Frappe v15+
- Python 3.10+
- An API key from Anthropic, Google, or OpenAI (you pay your AI provider directly)

---

## Support URL

https://github.com/shivaabhiramreddy/askerp-frappe/issues

## Privacy Policy URL

https://your-site.com/privacy

(Replace with your actual site URL after deploying. The privacy policy page is included with the app at the `/privacy` route.)

## GitHub Repository

https://github.com/shivaabhiramreddy/askerp-frappe

## License

MIT

## Publisher

Fertile Green Industries Pvt Ltd

## Logo

(Pending — need a 200px+ square logo. Placeholder: use a chat-bubble-with-sparkles icon in the brand green #047e38.)

## Screenshots Needed

1. Chat widget on an ERPNext page (showing the floating bubble)
2. Chat conversation with a financial summary response (table formatting)
3. AskERP Settings page (tier configuration)
4. Business Profile setup
5. No-Code Tool Builder (AskERP Custom Tool)
6. AI Cost Analytics dashboard/report
7. Setup Wizard (step 2 — API key entry)
8. Demo mode conversation

---

## Submission Checklist

- [ ] GitHub repo is public (or authorized for Frappe Marketplace)
- [ ] README.md is comprehensive
- [ ] License file present (MIT)
- [ ] pyproject.toml has correct metadata
- [ ] MANIFEST.in includes all assets
- [ ] App installs cleanly on a fresh ERPNext v15 site
- [ ] Setup wizard runs without errors
- [ ] Demo mode works without API key
- [ ] Privacy policy accessible at /privacy
- [ ] All Python files compile clean (52/52 verified)
- [ ] No hardcoded company-specific data in user-facing text
- [ ] Logo uploaded (200px+ square)
- [ ] Screenshots captured (8 screenshots)
