"""
AskERP — Provider Abstraction Layer v1.0
===================================================
Unified interface for calling any AI model from any provider.
All model configuration comes from the AskERP Model doctype — no hardcoded keys or URLs.

Supported providers:
  - Anthropic (Claude Opus, Sonnet, Haiku)
  - Google (Gemini Flash, Pro)
  - OpenAI (GPT-4o, GPT-4o-mini)
  - Custom (any OpenAI-compatible endpoint)

Usage:
  from askerp.providers import call_model, call_model_stream, test_connection

  model_doc = frappe.get_doc("AskERP Model", "claude-opus-4-6")
  response = call_model(model_doc, messages, system_prompt, tools=TOOLS)
"""

import json
import frappe
import requests


# ─── Normalized Response Format ─────────────────────────────────────────────
# All providers return this structure, regardless of their native API format.
# {
#     "content": [{"type": "text", "text": "..."}],
#     "stop_reason": "end_turn" | "tool_use",
#     "usage": {"input_tokens": N, "output_tokens": N, "cache_read_tokens": 0, "cache_creation_tokens": 0},
#     "tool_calls": [{"id": "...", "name": "...", "input": {...}}]  # only if stop_reason == "tool_use"
# }


def call_model(model_doc, messages, system_prompt, tools=None, stream=False):
    """
    Unified model caller. Dispatches to the correct provider handler.

    Args:
        model_doc: Frappe document (AskERP Model) with all config
        messages: List of message dicts (role/content format)
        system_prompt: System prompt string
        tools: Optional list of tool definitions
        stream: If True, returns an iterator of SSE chunks (for streaming)

    Returns:
        Normalized response dict, or None on failure (caller handles fallback)
    """
    provider = (model_doc.provider or "").strip()

    handlers = {
        "Anthropic": _call_anthropic,
        "Google": _call_google,
        "OpenAI": _call_openai,
        "Custom": _call_openai,  # Custom uses OpenAI-compatible format
    }

    handler = handlers.get(provider)
    if not handler:
        frappe.log_error(
            title="AI Provider Error",
            message=f"Unknown provider '{provider}' for model {model_doc.model_id}"
        )
        return None

    try:
        if stream and model_doc.supports_streaming:
            return _call_anthropic_stream(model_doc, messages, system_prompt, tools) if provider == "Anthropic" else None
        return handler(model_doc, messages, system_prompt, tools)
    except Exception as e:
        frappe.log_error(
            title=f"AI Provider Error: {provider}",
            message=f"Model: {model_doc.model_id}\nError: {str(e)[:500]}"
        )
        return None


# ─── Anthropic (Claude) ─────────────────────────────────────────────────────

def _call_anthropic(model_doc, messages, system_prompt, tools=None):
    """Call Anthropic Claude API with prompt caching and adaptive thinking."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        frappe.log_error(title="Anthropic API Error", message=f"No API key for model {model_doc.model_id}")
        return None

    base_url = model_doc.api_base_url or "https://api.anthropic.com/v1/messages"
    api_version = model_doc.api_version or "2023-06-01"
    max_tokens = model_doc.max_output_tokens or 4096

    # Build payload
    payload = {
        "model": model_doc.model_id,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
    }

    # Extended thinking for models that support it
    # Note: Opus 4.5 / Sonnet 4.5 require "type": "enabled" with budget_tokens.
    # "type": "adaptive" is only supported on Opus 4.6+.
    if model_doc.supports_thinking:
        thinking_budget = min(max_tokens // 2, 8192)
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    # Tool definitions with cache control on last tool
    if tools:
        cached_tools = [t.copy() for t in tools]
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}
        payload["tools"] = cached_tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": api_version,
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
    }

    # Retry logic
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(base_url, json=payload, headers=headers, timeout=180)

            if resp.status_code == 200:
                data = resp.json()
                return _normalize_anthropic_response(data)

            # If thinking caused a 400 error, retry without it
            if resp.status_code == 400 and "thinking" in payload:
                error_text = resp.text[:500].lower()
                if "thinking" in error_text or "adaptive" in error_text:
                    frappe.log_error(
                        title="Anthropic Thinking Fallback",
                        message=f"Model {model_doc.model_id} doesn't support thinking. Retrying without it."
                    )
                    del payload["thinking"]
                    resp = requests.post(base_url, json=payload, headers=headers, timeout=180)
                    if resp.status_code == 200:
                        data = resp.json()
                        return _normalize_anthropic_response(data)

            _log_api_error("Anthropic", model_doc.model_id, resp.status_code, resp.text[:500], attempt)

            if resp.status_code in (429, 500, 502, 503, 529) and attempt < max_retries:
                import time
                time.sleep((attempt + 1) * 3)
                continue

            return _make_error_response(resp.status_code)

        except requests.exceptions.Timeout:
            _log_api_error("Anthropic", model_doc.model_id, 0, "180s timeout exceeded", attempt)
            if attempt < max_retries:
                import time
                time.sleep(3)
                continue

        except requests.exceptions.ConnectionError as e:
            _log_api_error("Anthropic", model_doc.model_id, 0, str(e)[:200], attempt)
            if attempt < max_retries:
                import time
                time.sleep(3)
                continue

        except Exception as e:
            _log_api_error("Anthropic", model_doc.model_id, 0, str(e)[:200], attempt)
            break

    return None


def _call_anthropic_stream(model_doc, messages, system_prompt, tools=None):
    """
    Streaming call to Anthropic. Returns the raw requests.Response with stream=True.
    The caller (process_chat_stream) parses SSE events from this.
    """
    api_key = model_doc.get_password("api_key")
    if not api_key:
        return None

    base_url = model_doc.api_base_url or "https://api.anthropic.com/v1/messages"
    api_version = model_doc.api_version or "2023-06-01"
    max_tokens = model_doc.max_output_tokens or 4096

    payload = {
        "model": model_doc.model_id,
        "max_tokens": max_tokens,
        "stream": True,
        "system": [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
    }

    # Extended thinking: use "enabled" with budget_tokens (not "adaptive")
    if model_doc.supports_thinking:
        thinking_budget = min(max_tokens // 2, 8192)
        payload["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

    if tools:
        cached_tools = [t.copy() for t in tools]
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}
        payload["tools"] = cached_tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": api_version,
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
    }

    try:
        resp = requests.post(base_url, json=payload, headers=headers, timeout=180, stream=True)
        if resp.status_code == 200:
            return resp  # Return raw response for SSE parsing

        # If thinking caused a 400 error, retry without it
        if resp.status_code == 400 and "thinking" in payload:
            error_text = resp.text[:500].lower()
            if "thinking" in error_text or "adaptive" in error_text:
                frappe.log_error(
                    title="Anthropic Stream Thinking Fallback",
                    message=f"Model {model_doc.model_id} doesn't support thinking. Retrying without it."
                )
                del payload["thinking"]
                resp = requests.post(base_url, json=payload, headers=headers, timeout=180, stream=True)
                if resp.status_code == 200:
                    return resp

        _log_api_error("Anthropic Stream", model_doc.model_id, resp.status_code, resp.text[:500], 0)
        return None
    except Exception as e:
        _log_api_error("Anthropic Stream", model_doc.model_id, 0, str(e)[:200], 0)
        return None


def _normalize_anthropic_response(data):
    """Normalize Anthropic response to common format."""
    return {
        "content": data.get("content", []),
        "stop_reason": data.get("stop_reason", "end_turn"),
        "usage": {
            "input_tokens": data.get("usage", {}).get("input_tokens", 0),
            "output_tokens": data.get("usage", {}).get("output_tokens", 0),
            "cache_read_tokens": data.get("usage", {}).get("cache_read_input_tokens", 0),
            "cache_creation_tokens": data.get("usage", {}).get("cache_creation_input_tokens", 0),
        },
    }


# ─── Google (Gemini) ────────────────────────────────────────────────────────

def _call_google(model_doc, messages, system_prompt, tools=None):
    """Call Google Gemini API."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        frappe.log_error(title="Google API Error", message=f"No API key for model {model_doc.model_id}")
        return None

    # Gemini uses a different URL format: base_url/{model_id}:generateContent?key=KEY
    base_url = model_doc.api_base_url or "https://generativelanguage.googleapis.com/v1beta/models"
    url = f"{base_url}/{model_doc.model_id}:generateContent?key={api_key}"

    # Convert messages to Gemini format
    # Gemini uses: {"contents": [{"role": "user/model", "parts": [{"text": "..."}]}]}
    gemini_contents = []
    for msg in messages:
        role = "model" if msg.get("role") == "assistant" else "user"
        content = msg.get("content", "")
        if isinstance(content, str):
            gemini_contents.append({"role": role, "parts": [{"text": content}]})
        elif isinstance(content, list):
            # Handle multimodal content
            parts = []
            for block in content:
                if block.get("type") == "text":
                    parts.append({"text": block["text"]})
            if parts:
                gemini_contents.append({"role": role, "parts": parts})

    # Add system prompt as first user message if not in contents
    if system_prompt and gemini_contents:
        gemini_contents[0]["parts"].insert(0, {"text": f"[System instructions]: {system_prompt}\n\n"})

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": model_doc.max_output_tokens or 2048,
        },
    }

    # Add tool definitions if supported
    if tools and model_doc.supports_tools:
        gemini_tools = _convert_tools_to_gemini(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

    try:
        resp = requests.post(url, json=payload, timeout=60)

        if resp.status_code != 200:
            _log_api_error("Google", model_doc.model_id, resp.status_code, resp.text[:500], 0)
            return _make_error_response(resp.status_code)

        data = resp.json()
        return _normalize_google_response(data)

    except Exception as e:
        _log_api_error("Google", model_doc.model_id, 0, _sanitize_google_error(str(e), api_key), 0)
        return None


def _normalize_google_response(data):
    """Normalize Google Gemini response to common format."""
    text = ""
    tool_calls = []

    if "candidates" in data and data["candidates"]:
        candidate = data["candidates"][0]
        if "content" in candidate and "parts" in candidate["content"]:
            for part in candidate["content"]["parts"]:
                if "text" in part:
                    text += part["text"]
                elif "functionCall" in part:
                    tool_calls.append({
                        "id": f"gemini_{len(tool_calls)}",
                        "name": part["functionCall"]["name"],
                        "input": part["functionCall"].get("args", {}),
                    })

    # Gemini doesn't provide token counts in the standard response, estimate
    usage_meta = data.get("usageMetadata", {})

    content = [{"type": "text", "text": text}] if text else []
    stop_reason = "tool_use" if tool_calls else "end_turn"

    if tool_calls:
        for tc in tool_calls:
            content.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})

    return {
        "content": content,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": usage_meta.get("promptTokenCount", 0),
            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
    }


def _convert_tools_to_gemini(tools):
    """Convert Anthropic-format tool definitions to Gemini format."""
    gemini_functions = []
    for tool in tools:
        if tool.get("name") and tool.get("input_schema"):
            gemini_functions.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
            })
    if gemini_functions:
        return [{"functionDeclarations": gemini_functions}]
    return None


# ─── OpenAI + Custom (OpenAI-compatible) ────────────────────────────────────

def _call_openai(model_doc, messages, system_prompt, tools=None):
    """Call OpenAI or any OpenAI-compatible API."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        frappe.log_error(title="OpenAI API Error", message=f"No API key for model {model_doc.model_id}")
        return None

    base_url = model_doc.api_base_url or "https://api.openai.com/v1/chat/completions"

    # Build OpenAI-format messages (system message first)
    oai_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str):
            oai_messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Handle tool results and multimodal
            parts = []
            for block in content:
                if block.get("type") == "text":
                    parts.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "tool_result":
                    # Convert tool_result to OpenAI format
                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    })
                    continue
            if parts:
                oai_messages.append({"role": role, "content": parts})

    payload = {
        "model": model_doc.model_id,
        "messages": oai_messages,
        "max_tokens": model_doc.max_output_tokens or 4096,
        "temperature": 0.7,
    }

    # Convert tools to OpenAI format
    if tools and model_doc.supports_tools:
        oai_tools = _convert_tools_to_openai(tools)
        if oai_tools:
            payload["tools"] = oai_tools

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Add org header if api_secret contains org ID
    api_secret = model_doc.get_password("api_secret")
    if api_secret:
        headers["OpenAI-Organization"] = api_secret

    try:
        resp = requests.post(base_url, json=payload, headers=headers, timeout=120)

        if resp.status_code != 200:
            _log_api_error("OpenAI", model_doc.model_id, resp.status_code, resp.text[:500], 0)
            return _make_error_response(resp.status_code)

        data = resp.json()
        return _normalize_openai_response(data)

    except Exception as e:
        _log_api_error("OpenAI", model_doc.model_id, 0, str(e)[:200], 0)
        return None


def _normalize_openai_response(data):
    """Normalize OpenAI response to common format."""
    content = []
    choices = data.get("choices", [])

    if choices:
        choice = choices[0]
        message = choice.get("message", {})

        # Text content
        if message.get("content"):
            content.append({"type": "text", "text": message["content"]})

        # Tool calls
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                except (json.JSONDecodeError, KeyError):
                    args = {}
                content.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "input": args,
                })

    # Determine stop reason
    finish_reason = choices[0].get("finish_reason", "stop") if choices else "stop"
    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

    usage = data.get("usage", {})

    return {
        "content": content,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        },
    }


def _convert_tools_to_openai(tools):
    """Convert Anthropic-format tool definitions to OpenAI format."""
    oai_tools = []
    for tool in tools:
        if tool.get("name") and tool.get("input_schema"):
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
    return oai_tools


# ─── Connection Testing ─────────────────────────────────────────────────────

def test_connection(model_doc):
    """
    Test connectivity to an AI model. Sends a minimal request.
    Updates the model doc with test results.

    Returns:
        dict: {success: bool, message: str, latency_ms: float}
    """
    import time

    provider = (model_doc.provider or "").strip()
    start = time.time()

    testers = {
        "Anthropic": _test_anthropic,
        "Google": _test_google,
        "OpenAI": _test_openai,
        "Custom": _test_openai,
    }

    tester = testers.get(provider)
    if not tester:
        return {"success": False, "message": f"Unknown provider: {provider}", "latency_ms": 0}

    try:
        result = tester(model_doc)
        latency = round((time.time() - start) * 1000, 1)
        result["latency_ms"] = latency

        # Update model doc with test results
        now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        status = "Pass" if result["success"] else "Fail"
        message = result["message"]
        if result["success"]:
            message = f"Connected successfully in {latency}ms. {message}"

        frappe.db.set_value("AskERP Model", model_doc.name, {
            "last_tested": now,
            "test_status": status,
            "test_message": message[:500],
        }, update_modified=False)
        frappe.db.commit()

        return result

    except Exception as e:
        now = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        frappe.db.set_value("AskERP Model", model_doc.name, {
            "last_tested": now,
            "test_status": "Fail",
            "test_message": f"Unexpected error: {str(e)[:400]}",
        }, update_modified=False)
        frappe.db.commit()
        return {"success": False, "message": str(e)[:500], "latency_ms": 0}


def _test_anthropic(model_doc):
    """Send minimal test request to Anthropic."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        return {"success": False, "message": "API key is empty"}

    base_url = model_doc.api_base_url or "https://api.anthropic.com/v1/messages"
    api_version = model_doc.api_version or "2023-06-01"

    resp = requests.post(
        base_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": api_version,
            "content-type": "application/json",
        },
        json={
            "model": model_doc.model_id,
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Say OK"}],
        },
        timeout=15,
    )

    if resp.status_code == 200:
        return {"success": True, "message": f"Model {model_doc.model_id} responded."}
    else:
        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}


def _test_google(model_doc):
    """Send minimal test request to Google Gemini."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        return {"success": False, "message": "API key is empty"}

    base_url = model_doc.api_base_url or "https://generativelanguage.googleapis.com/v1beta/models"
    url = f"{base_url}/{model_doc.model_id}:generateContent?key={api_key}"

    resp = requests.post(
        url,
        json={
            "contents": [{"parts": [{"text": "Say OK"}]}],
            "generationConfig": {"maxOutputTokens": 10},
        },
        timeout=15,
    )

    if resp.status_code == 200:
        return {"success": True, "message": f"Model {model_doc.model_id} responded."}
    else:
        # Sanitize response text in case it echoes the key back
        safe_text = _sanitize_google_error(resp.text[:300], api_key)
        return {"success": False, "message": f"HTTP {resp.status_code}: {safe_text}"}


def _test_openai(model_doc):
    """Send minimal test request to OpenAI or compatible API."""
    api_key = model_doc.get_password("api_key")
    if not api_key:
        return {"success": False, "message": "API key is empty"}

    base_url = model_doc.api_base_url or "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    api_secret = model_doc.get_password("api_secret")
    if api_secret:
        headers["OpenAI-Organization"] = api_secret

    resp = requests.post(
        base_url,
        headers=headers,
        json={
            "model": model_doc.model_id,
            "messages": [{"role": "user", "content": "Say OK"}],
            "max_tokens": 10,
        },
        timeout=15,
    )

    if resp.status_code == 200:
        return {"success": True, "message": f"Model {model_doc.model_id} responded."}
    else:
        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}


# ─── Cost Calculator ────────────────────────────────────────────────────────

def calculate_cost(model_doc, usage):
    """
    Calculate the cost of a query based on the model's pricing.

    Args:
        model_doc: AskERP Model document
        usage: dict with input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens

    Returns:
        dict: {cost_input, cost_output, cost_total}
    """
    input_tokens = max(0, usage.get("input_tokens", 0) or 0)
    output_tokens = max(0, usage.get("output_tokens", 0) or 0)
    cache_read_tokens = max(0, usage.get("cache_read_tokens", 0) or 0)
    cache_creation_tokens = max(0, usage.get("cache_creation_tokens", 0) or 0)

    # Anthropic breaks input into: regular + cache_read + cache_creation
    # Each has different pricing:
    #   regular_input = input_tokens - cache_read - cache_creation (standard rate)
    #   cache_read = discounted rate (typically 10% of input)
    #   cache_creation = premium rate (typically 125% of input)
    regular_input_tokens = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)

    input_rate = float(model_doc.input_cost_per_million or 0)
    output_rate = float(model_doc.output_cost_per_million or 0)
    cache_read_rate = float(model_doc.cache_read_cost_per_million or 0)
    cache_write_rate = float(getattr(model_doc, "cache_write_cost_per_million", 0) or 0)

    cost_input = (
        (regular_input_tokens / 1_000_000) * input_rate
        + (cache_read_tokens / 1_000_000) * cache_read_rate
        + (cache_creation_tokens / 1_000_000) * cache_write_rate
    )
    cost_output = (output_tokens / 1_000_000) * output_rate
    cost_total = cost_input + cost_output

    return {
        "cost_input": round(cost_input, 6),
        "cost_output": round(cost_output, 6),
        "cost_total": round(cost_total, 6),
    }


# ─── Model Resolution Helpers ───────────────────────────────────────────────

def get_settings():
    """Get the AskERP Settings singleton. Cached per request."""
    try:
        return frappe.get_cached_doc("AskERP Settings")
    except frappe.DoesNotExistError:
        return None


def get_model_for_tier(tier_name):
    """
    Get the model document for a given tier.

    Args:
        tier_name: "tier_1", "tier_2", "tier_3", "utility", "vision", "fallback"

    Returns:
        AskERP Model doc or None
    """
    settings = get_settings()
    if not settings:
        return None

    field_map = {
        "tier_1": "tier_1_model",
        "tier_2": "tier_2_model",
        "tier_3": "tier_3_model",
        "utility": "utility_model",
        "vision": "vision_model",
        "fallback": "fallback_model",
    }

    field = field_map.get(tier_name)
    if not field:
        return None

    model_id = settings.get(field)
    if not model_id:
        return None

    try:
        model_doc = frappe.get_cached_doc("AskERP Model", model_id)
        if model_doc.enabled:
            return model_doc
        return None
    except frappe.DoesNotExistError:
        return None


def get_user_restricted_model(user):
    """
    Check if a user has a User Permission restricting them to a specific model.

    Returns:
        AskERP Model doc if restricted, None if user can use any model
    """
    perms = frappe.get_all(
        "User Permission",
        filters={
            "user": user,
            "allow": "AskERP Model",
            "is_default": 0,
        },
        fields=["for_value"],
        limit=1,
    )

    if perms:
        model_id = perms[0].get("for_value")
        if model_id:
            try:
                model_doc = frappe.get_doc("AskERP Model", model_id)
                if model_doc.enabled:
                    return model_doc
            except frappe.DoesNotExistError:
                pass

    return None


def get_daily_limit_for_user(user, model_doc):
    """
    Get the daily query limit for a user on a specific model.
    Checks the model's rate_limits child table first, then falls back to global defaults.

    Returns:
        int: daily limit
    """
    if user == "Administrator":
        return 999

    # Check model's rate_limits child table
    user_roles = set(frappe.get_roles(user))
    max_limit = 0

    for row in (model_doc.rate_limits or []):
        if row.role in user_roles:
            max_limit = max(max_limit, row.daily_limit or 0)

    if max_limit > 0:
        return max_limit

    # Fall back to AskERP Settings defaults
    settings = get_settings()
    if not settings:
        return 50  # Hardcoded absolute fallback

    # Check if field staff
    field_roles = {"Sales User", "Stock User", "Manufacturing User", "Purchase User"}
    mgmt_roles = {"System Manager", "Accounts Manager", "Sales Manager", "Purchase Manager", "Stock Manager"}

    if field_roles.intersection(user_roles) and not mgmt_roles.intersection(user_roles):
        return settings.field_staff_daily_limit or 30

    return settings.default_daily_limit or 50


def check_monthly_budget():
    """
    Check if the monthly budget limit has been exceeded.

    Returns:
        tuple: (exceeded: bool, current_spend: float, limit: float)
    """
    settings = get_settings()
    if not settings or not settings.monthly_budget_limit or float(settings.monthly_budget_limit) <= 0:
        return False, 0, 0

    limit = float(settings.monthly_budget_limit)

    # Sum cost_total for current month
    from frappe.utils import get_first_day, get_last_day, today
    first_day = get_first_day(today())

    result = frappe.db.sql("""
        SELECT COALESCE(SUM(cost_total), 0) as total_spend
        FROM `tabAI Usage Log`
        WHERE creation >= %s
    """, first_day, as_dict=True)

    current_spend = float(result[0].total_spend) if result else 0

    return current_spend >= limit, current_spend, limit


# ─── Internal Helpers ────────────────────────────────────────────────────────

def _make_error_response(status_code):
    """Create a friendly error response instead of throwing."""
    messages = {
        429: "I'm getting a lot of requests right now. Please wait a moment and try again.",
        401: "There's an issue with the AI service configuration. Please contact your admin.",
        403: "Access to the AI service was denied. Please contact your admin.",
        400: "There was an issue with this request. Try asking a shorter question.",
    }
    error_msg = messages.get(status_code, "I'm having trouble connecting to my AI service right now. Please try again shortly.")

    return {
        "content": [{"type": "text", "text": error_msg}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0},
    }


def _sanitize_google_error(error_str, api_key):
    """Strip Google API key from error messages to prevent key leakage into logs."""
    if api_key and api_key in error_str:
        return error_str.replace(api_key, "***REDACTED***")
    # Also strip any ?key= parameter pattern
    import re
    return re.sub(r'\?key=[A-Za-z0-9_-]+', '?key=***REDACTED***', error_str)


def _log_api_error(provider, model_id, status_code, message, attempt):
    """Log an API error to Frappe Error Log."""
    frappe.log_error(
        title=f"{provider} API Error (attempt {attempt + 1})",
        message=f"Model: {model_id}\nStatus: {status_code}\nDetails: {message}"
    )
