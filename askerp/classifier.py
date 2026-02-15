"""
AskERP — Hybrid Query Classifier
=================================
Two-stage classification: regex fast-path → LLM fallback.
Now with Stage 0: conversation-awareness for follow-up detection.

Stage 0 (Conversation check — free, instant):
    Detects short follow-up messages (e.g., "what about last month?", "and revenue?")
    that reference previous context. These MUST be routed to at least "simple" tier
    because they need tools + conversation history to answer correctly.

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

    # With conversation context (prevents follow-ups from going to flash tier):
    complexity, tier = classify_query("what about last month?", conversation_history=[...])
    # → ("simple", "tier_2")  # NOT flash, because this is a follow-up needing tools
"""

import re
import json
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

# ─── Custom patterns from AskERP Settings (loaded + cached at runtime) ────────

_custom_patterns_cache = {"loaded": False, "flash": [], "simple": [], "complex": []}


def _load_custom_patterns():
    """
    Load admin-defined classification patterns from AskERP Settings.
    Compiles them into regex objects and caches in module-level dict.
    Called once per worker process; cache cleared by Frappe on settings save.

    Expected JSON format in custom_classification_patterns field:
    {"flash": ["^shukriya", "dhanyawad"], "simple": ["kitna pending hai"], "complex": []}
    """
    global _custom_patterns_cache
    if _custom_patterns_cache["loaded"]:
        return _custom_patterns_cache

    try:
        settings = frappe.get_cached_doc("AskERP Settings")
        raw = settings.get("custom_classification_patterns") or ""
        if raw.strip():
            data = json.loads(raw)
            for tier in ("flash", "simple", "complex"):
                patterns = data.get(tier, [])
                if isinstance(patterns, list):
                    compiled = []
                    for p in patterns:
                        if isinstance(p, str) and p.strip():
                            try:
                                compiled.append(re.compile(p.strip(), re.IGNORECASE))
                            except re.error:
                                frappe.log_error(
                                    title="AskERP: Invalid classification pattern",
                                    message=f"Tier: {tier}, Pattern: {p}"
                                )
                    _custom_patterns_cache[tier] = compiled
    except Exception:
        pass  # Settings not available (fresh install, etc.)

    _custom_patterns_cache["loaded"] = True
    return _custom_patterns_cache


def _reset_custom_patterns_cache():
    """Called when AskERP Settings is saved to reload custom patterns."""
    global _custom_patterns_cache
    _custom_patterns_cache = {"loaded": False, "flash": [], "simple": [], "complex": []}


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
  "delete my alert", "show today's orders", "stock of item X", "ABC Corp ka outstanding",
  "this month's revenue", "list my alerts", "what's the price of product Y?"

complex — Multi-step analysis requiring deep reasoning across multiple data sources.
  ONLY use this when the query genuinely needs cross-referencing, comparisons across periods,
  strategic recommendations, or synthesizing 3+ data points.
  Examples: "compare Jan vs Feb revenue by customer group", "business pulse with all KPIs",
  "why did revenue drop this quarter?", "what should we do about aging receivables?",
  "forecast next month's sales based on trends"

IMPORTANT: When in doubt, choose "simple" over "complex". Most business queries are simple lookups.
Single actions (create, delete, update, show) are almost always "simple".

Reply with exactly one word: flash, simple, or complex."""


# ─── Follow-up detection patterns ─────────────────────────────────────────────

_FOLLOWUP_STARTERS = re.compile(
    r"^(what about|how about|and |also |show me |tell me |"
    r"what if|now |ok |okay |yes |yeah |yep |sure |"
    r"for |in |from |by |with |this |that |those |these |"
    r"same |similar|again |more |less |instead |rather )",
    re.IGNORECASE,
)

# Very short messages that are likely follow-ups referencing prior context
_MAX_FOLLOWUP_LEN = 40


def _is_followup_query(question, conversation_history):
    """
    Detect if a short query is a follow-up to a previous conversation turn.

    A follow-up is:
    - Short (< 40 chars) AND
    - Starts with a follow-up starter pattern (what about, and, also, etc.) AND
    - There's at least 1 prior assistant message with tool_use in the conversation

    Follow-ups MUST be routed to at least "simple" because they need the full
    system prompt + tools + conversation context to answer correctly.
    """
    if not conversation_history or not isinstance(conversation_history, list):
        return False

    q = question.strip()

    # Not short enough to be a follow-up
    if len(q) > _MAX_FOLLOWUP_LEN:
        return False

    # Check if it starts with a follow-up pattern
    if not _FOLLOWUP_STARTERS.search(q):
        return False

    # Check if there's meaningful prior conversation (at least 2 messages = 1 exchange)
    if len(conversation_history) < 2:
        return False

    # Look for any prior assistant message that used tools (indicates data context)
    for msg in conversation_history:
        if msg.get("role") == "assistant":
            content = msg.get("content")
            # If content is a list of blocks (tool_use, text, etc.)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        return True
            # If content is a string with substantial length (prior answer)
            elif isinstance(content, str) and len(content) > 50:
                return True

    return False


# ─── Stage 1: Regex Fast Path ───────────────────────────────────────────────

def _classify_via_regex(question):
    """
    Try to classify using regex patterns. Returns (complexity, tier) or None.
    Checks admin-defined custom patterns FIRST (higher priority), then built-in.
    Order: custom patterns → short-query optimization → complex → flash → simple → None.
    """
    q = question.strip()

    # ── Stage 1a: Custom patterns from AskERP Settings (admin-defined) ────
    custom = _load_custom_patterns()
    for pat in custom.get("complex", []):
        if pat.search(q):
            return "complex", "tier_3"
    for pat in custom.get("flash", []):
        if pat.search(q):
            return "flash", "tier_1"
    for pat in custom.get("simple", []):
        if pat.search(q):
            return "simple", "tier_2"

    # ── Stage 1b: Built-in patterns ──────────────────────────────────────
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

def classify_query(question, conversation_history=None):
    """
    Hybrid query classifier: follow-up check → regex fast-path → LLM fallback.

    Args:
        question: The user's query text.
        conversation_history: Optional list of prior messages [{role, content}, ...].
            Used to detect follow-up queries that need tool access.

    Returns: (complexity_str, tier_name)
      - ("flash", "tier_1")   — greetings, trivial (cheapest model)
      - ("simple", "tier_2")  — counts, simple lists (mid-range model)
      - ("complex", "tier_3") — analysis, comparisons, strategy (full-power model)

    The caller resolves tier_name → actual model doc via providers.get_model_for_tier().
    """
    q = (question or "").strip()
    if not q:
        return "flash", "tier_1"

    # Stage 0: Follow-up detection (free, instant)
    # Short follow-ups like "what about last month?" must get tools, not flash tier
    if _is_followup_query(q, conversation_history):
        # Run regex to see if it matches simple or complex
        result = _classify_via_regex(q)
        if result is not None:
            # Ensure minimum tier_2 for follow-ups (never flash)
            if result[1] == "tier_1":
                return "simple", "tier_2"
            return result
        # No regex match — default follow-ups to simple (not complex, to save cost)
        return "simple", "tier_2"

    # Stage 1: Regex (free, instant)
    result = _classify_via_regex(q)
    if result is not None:
        return result

    # Stage 2: LLM fallback (cheap, ~200-400ms)
    return _classify_via_llm(q)
