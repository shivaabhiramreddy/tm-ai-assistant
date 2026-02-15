"""
AskERP — Hybrid Query Classifier
=================================
Two-stage classification: regex fast-path → LLM fallback.

Stage 1 (Regex — free, instant):
    Tries to match the query against known patterns in classification_patterns.py.
    Handles ~70-80% of queries with zero cost and zero latency.

Stage 2 (LLM — cheap, ~200-400ms):
    If regex doesn't match, sends the query to the Tier 1 model (cheapest,
    e.g. Haiku) with a tiny classification prompt. The model returns one word
    (flash/simple/complex) and we route accordingly.

    Cost: ~$0.0001 per classification (negligible).
    Latency: ~200-400ms (acceptable for the accuracy gain).

Usage:
    from askerp.classifier import classify_query
    complexity, tier = classify_query("Good morning")
    # → ("flash", "tier_1")
"""

import re
import frappe

from askerp.classification_patterns import (
    FLASH_PATTERNS,
    SIMPLE_PATTERNS,
    COMPLEX_PATTERNS,
)


# ─── Compile regex patterns once at module load ──────────────────────────────

_flash_re = [re.compile(p, re.IGNORECASE) for p in FLASH_PATTERNS]
_simple_re = [re.compile(p, re.IGNORECASE) for p in SIMPLE_PATTERNS]
_complex_re = [re.compile(p, re.IGNORECASE) for p in COMPLEX_PATTERNS]


# ─── LLM Classification Prompt ──────────────────────────────────────────────

_LLM_CLASSIFIER_PROMPT = """You are a cost-optimizing query classifier for a business ERP system.
Your goal: assign the CHEAPEST tier that can handle the query well. Never over-classify.

Classify into exactly ONE category. Reply with ONLY the category name.

Categories (cheapest → most expensive):

flash — Greetings, yes/no, thank you, acknowledgements, small talk. No data needed.
  Examples: "hi", "good morning", "thanks", "ok", "namaskar", "bye"

simple — Single lookups, counts, CRUD operations, rankings, alert management, single-period data.
  A mid-range model with tool access can handle these easily.
  Examples: "how many customers?", "top 5 customers by revenue", "create alert for low sales",
  "delete my alert", "show today's orders", "stock of corn silage", "Malabar ka outstanding",
  "this month's revenue", "list my alerts", "what's the price of TMR?"

complex — Multi-step analysis requiring deep reasoning across multiple data sources.
  ONLY use this when the query genuinely needs cross-referencing, comparisons across periods,
  strategic recommendations, or synthesizing 3+ data points.
  Examples: "compare Jan vs Feb revenue by customer group", "business pulse with all KPIs",
  "why did revenue drop this quarter?", "what should we do about aging receivables?",
  "forecast next month's sales based on trends"

IMPORTANT: When in doubt, choose "simple" over "complex". Most business queries are simple lookups.
Single actions (create, delete, update, show) are almost always "simple".

Reply with exactly one word: flash, simple, or complex."""


# ─── Stage 1: Regex Fast Path ───────────────────────────────────────────────

def _classify_via_regex(question):
    """
    Try to classify using regex patterns. Returns (complexity, tier) or None.
    Order: short-query optimization → complex → flash → simple → None.
    """
    q = question.strip()

    # For very short queries (< 25 chars), check flash/simple first
    # Short queries are almost never complex
    if len(q) < 25:
        for pat in _flash_re:
            if pat.search(q):
                return "flash", "tier_1"
        for pat in _simple_re:
            if pat.search(q):
                return "simple", "tier_2"

    # Complex patterns take priority (longer queries)
    for pat in _complex_re:
        if pat.search(q):
            return "complex", "tier_3"

    # Then flash (might be a longer greeting like "thank you so much for the help")
    for pat in _flash_re:
        if pat.search(q):
            return "flash", "tier_1"

    # Then simple
    for pat in _simple_re:
        if pat.search(q):
            return "simple", "tier_2"

    # No regex match — needs LLM classification
    return None


# ─── Stage 2: LLM Fallback ──────────────────────────────────────────────────

def _classify_via_llm(question):
    """
    Use the Tier 1 model (cheapest) to classify an unmatched query.
    Returns (complexity, tier). Falls back to ("complex", "tier_3") on any error.
    """
    try:
        from askerp.providers import get_model_for_tier, call_model

        model_doc = get_model_for_tier("tier_1")
        if not model_doc:
            # No Tier 1 model configured — fall back to complex (safe default)
            return "complex", "tier_3"

        messages = [
            {"role": "user", "content": question}
        ]

        response = call_model(
            model_doc=model_doc,
            messages=messages,
            system_prompt=_LLM_CLASSIFIER_PROMPT,
            tools=None,
            stream=False,
        )

        if not response:
            return "complex", "tier_3"

        # Extract the classification from the response
        # The model should return exactly one word: flash, simple, or complex
        raw = ""
        for block in response.get("content", []):
            if block.get("type") == "text":
                raw = block.get("text", "").strip().lower()
                break

        # Parse the response — look for our keywords
        if "flash" in raw:
            return "flash", "tier_1"
        elif "simple" in raw:
            return "simple", "tier_2"
        elif "complex" in raw:
            return "complex", "tier_3"
        else:
            # Model returned something unexpected — log and default to complex
            frappe.log_error(
                title="AskERP Classifier: Unexpected LLM response",
                message=f"Query: {question[:200]}\nResponse: {raw[:200]}"
            )
            return "complex", "tier_3"

    except Exception as e:
        # Any error in LLM classification → default to complex (safe)
        frappe.log_error(
            title="AskERP Classifier: LLM fallback error",
            message=f"Query: {question[:200]}\nError: {str(e)[:300]}"
        )
        return "complex", "tier_3"


# ─── Public API ──────────────────────────────────────────────────────────────

def classify_query(question):
    """
    Hybrid query classifier: regex fast-path → LLM fallback.

    Returns: (complexity_str, tier_name)
      - ("flash", "tier_1")   — greetings, trivial (cheapest model)
      - ("simple", "tier_2")  — counts, simple lists (mid-range model)
      - ("complex", "tier_3") — analysis, comparisons, strategy (full-power model)

    The caller resolves tier_name → actual model doc via providers.get_model_for_tier().
    """
    q = (question or "").strip()
    if not q:
        return "flash", "tier_1"

    # Stage 1: Regex (free, instant)
    result = _classify_via_regex(q)
    if result is not None:
        return result

    # Stage 2: LLM fallback (cheap, ~200-400ms)
    return _classify_via_llm(q)
