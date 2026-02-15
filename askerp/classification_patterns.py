"""
AskERP — Query Classification Patterns
=======================================
Regex patterns for the fast-path query classifier. These handle ~70-80% of
queries instantly and for free. Anything that doesn't match falls through to
the LLM classifier (Tier 1 model, typically Haiku — cheap and accurate).

HOW TO ADD PATTERNS:
  1. Add your regex string to the correct list below
  2. All patterns are compiled with re.IGNORECASE (case doesn't matter)
  3. Use ^ to anchor at the start of the query
  4. Use \\b for word boundaries
  5. Test your pattern: python3 -c "import re; print(bool(re.search(r'your_pattern', 'test input', re.I)))"
  6. Deploy and the new pattern takes effect immediately

TIER DEFINITIONS:
  - FLASH (tier_1): Greetings, acknowledgements, yes/no, trivial non-data queries
                     → Cheapest model (e.g., Haiku). No tools needed.
  - SIMPLE (tier_2): Single-fact lookups, counts, simple lists, today/recent data
                     → Mid-range model (e.g., Sonnet). May use 1-2 tools.
  - COMPLEX (tier_3): Analysis, comparisons, trends, strategy, multi-step reasoning
                     → Full-power model (e.g., Opus). May use 3-8 tools.
"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FLASH PATTERNS — Greetings, pleasantries, acknowledgements
# These queries need NO data lookup — just a friendly response.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FLASH_PATTERNS = [
    # English greetings
    r"^(hi|hello|hey|hola|howdy|sup|yo)\b",
    r"^good\s*(morning|afternoon|evening|night|day)\b",
    r"^(how are you|what'?s up|how'?s it going|how do you do)\b",

    # Indian language greetings (transliterated)
    r"^(namaste|namaskar|vanakkam|namaskara|namaskaram)\b",
    r"^(jai\s*shri\s*ram|jai\s*hind|radhe\s*radhe)\b",
    r"^(salam|salaam|as\-?salaam)\b",
    r"^(sat\s*sri\s*akal)\b",

    # Acknowledgements & closings
    r"^(thanks|thank\s*you|thx|ty|cheers|great|awesome|perfect|cool|nice)\b",
    r"^(ok|okay|k|got\s*it|understood|noted|sure|alright|fine)\b",
    r"^(yes|no|yep|nope|yeah|nah|yea|ya)\b",
    r"^(bye|goodbye|see\s*you|good\s*bye|later|cya)\b",

    # Simple identity questions
    r"^who\s+(is|are)\b",
    r"^what\s+can\s+you\s+do\b",
    r"^(help|menu)\b",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SIMPLE PATTERNS — Single-fact lookups, counts, straightforward lists
# These queries need 1-2 simple data lookups.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SIMPLE_PATTERNS = [
    # Counts and totals
    r"^how\s+many\b",
    r"^what\s+(is|are)\s+(the\s+)?(total|count|number)\b",
    r"^(total|count)\s+(of\s+)?\w+",

    # Recent / today data
    r"^show\s+me\s+(today|yesterday|recent|latest|last)\b",
    r"^(today'?s|yesterday'?s)\s+\w+",
    r"^what\s+(happened|was)\s+(today|yesterday)\b",

    # Simple lookups
    r"^(what|which)\s+(is|are)\s+(the\s+)?(status|price|balance|amount|address|phone|email)\b",
    r"^(show|get|find|look\s*up)\s+(me\s+)?(the\s+)?(details|info|status)\s+(of|for)\b",

    # List operations (alerts, sessions, items)
    r"^(list|show|get)\b.{0,25}\b(alerts|sessions|items|products|warehouses)\b",

    # Simple when/where questions
    r"^(when|where)\s+(is|was|did|will)\b",

    # Stock checks
    r"^(stock|inventory)\s+(of|for|check|level)\b",
    r"^(is|are)\s+.{0,30}\s+(in\s+stock|available)\b",

    # Price checks
    r"^(price|rate|cost)\s+(of|for)\b",
    r"^how\s+much\s+(is|does|for)\b",

    # Alert CRUD operations (create/delete/list — single tool call, Sonnet handles fine)
    r"(alert|notify|watch|monitor)\s+(me|us|when|if)\b",
    r"(set\s+up|create|add)\s+.{0,15}\b(alert|monitor|watch)\b",
    r"(delete|remove|cancel|disable|deactivate|turn\s+off)\s+.{0,40}\b(alert|monitor|watch|notification)\b",

    # Rankings — single sorted query (Sonnet composes ORDER BY easily)
    r"(top\s+\d+|bottom\s+\d+|highest|lowest)\b",
    r"^(best|worst)\s+(selling|performing|paying|buying)\b",

    # Receivables / payables / outstanding lookups (single-entity)
    r"(kitna|kitne|kitni)\s+(baki|baaki|pending|due)\b",
    r"\b(outstanding|receivable|payable|due|baki|balance)\b.{0,20}\b(of|for|from|hai|h)\b",

    # Single-period revenue/sales/collection (no comparison)
    r"^(this|last|current)\s+(month|week|quarter|year)('?s)?\s+(revenue|sales|collection|purchase|payment|invoice)s?\b",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMPLEX PATTERNS — Analysis, comparisons, strategy, multi-step reasoning
# These queries need deep analysis with multiple tool calls.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COMPLEX_PATTERNS = [
    # Comparisons
    r"(compare|comparison|versus|vs\.?)\b",
    r"(between\s+.+\s+and\s+)\b",
    r"(differ|difference)\b.{0,20}\b(between|from)\b",

    # Trends and forecasts
    r"(trend|forecast|predict|project|growth)\b",
    r"(month[\s\-]over[\s\-]month|year[\s\-]over[\s\-]year|quarter[\s\-]over[\s\-]quarter)\b",
    r"\b(YoY|MoM|QoQ|CAGR)\b",

    # Analysis keywords
    r"(why|explain|analy[sz]e|analysis|insight|deep\s*dive)\b",
    r"(breakdown|break\s*down|decompos|dissect)\b",

    # Strategy and recommendations
    r"(strateg|optimi[sz]|improv|suggest|recommend|advic?e)\b",
    r"(should\s+(we|i)|what\s+would|action\s+plan)\b",

    # Visualizations and exports
    r"(chart|graph|visual|dashboard|report|pdf|excel|export)\b",

    # Financial metrics
    r"\b(dso|dpo|dio|working\s*capital|cash\s*flow|margin|ratio|profitab)\b",
    r"(receivab|payab|outstand|overdue|aging)\b.{0,20}\b(analysis|report|summary|trend)\b",

    # Hypotheticals and scenarios
    r"(if\s+we|what\s+if|what\s+would|scenario|simulat)\b",

    # Multi-period analysis (comparison across periods — NOT single-period lookups)
    r"(this|last|previous|current)\s+(month|quarter|year|week|fy|financial\s*year)\b.{5,}\b(compar|vs|versus|against|differ|change)\b",
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(vs|versus|against|compared?\s+to)\b",

    # Business pulse / dashboard requests (multi-metric deep analysis)
    r"(business\s+pulse|full\s+overview|executive\s+summary|business\s+health)\b",
    r"(pulse|snapshot|overview|summary)\s+(of|for)\s+(the\s+)?(business|company)\b",
]
