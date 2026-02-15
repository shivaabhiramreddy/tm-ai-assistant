"""
AskERP — Setup Wizard Backend
========================================
API endpoints for the 5-step setup wizard that appears on first visit
after installation. Handles:
  1. Welcome (no backend needed)
  2. AI Provider configuration + API key validation
  3. Quick business profile setup
  4. User enablement (bulk toggle allow_ai_chat)
  5. Completion (mark setup_complete, redirect)

Also provides skip/resume logic and a boot hook for the notification bar.
"""

import frappe
from frappe import _


# ─── Setup Status ─────────────────────────────────────────────────────────

@frappe.whitelist()
def get_setup_status():
    """
    Check if setup wizard has been completed.
    Called on every page load via boot session hook.
    Returns: {setup_complete, current_step, show_wizard}
    """
    if frappe.session.user == "Guest":
        return {"setup_complete": True, "show_wizard": False}

    # Only System Manager / Administrator sees the wizard
    if not _is_admin():
        return {"setup_complete": True, "show_wizard": False}

    try:
        settings = frappe.get_single("AskERP Settings")
        setup_complete = bool(settings.setup_complete)
        current_step = settings.setup_current_step or 0
    except Exception:
        setup_complete = False
        current_step = 0

    return {
        "setup_complete": setup_complete,
        "current_step": current_step,
        "show_wizard": not setup_complete,
    }


# ─── Step 2: AI Provider / API Key ────────────────────────────────────────

@frappe.whitelist()
def test_api_key(provider, api_key):
    """
    Test an AI provider's API key by making a minimal API call.
    Returns: {success: bool, message: str, model_name: str}
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can configure AI settings."))

    provider = (provider or "").strip()
    api_key = (api_key or "").strip()

    if not provider or not api_key:
        return {"success": False, "message": "Provider and API key are required."}

    if provider == "Anthropic":
        return _test_anthropic_key(api_key)
    elif provider == "Google":
        return _test_google_key(api_key)
    elif provider == "OpenAI":
        return _test_openai_key(api_key)
    else:
        return {"success": False, "message": f"Unknown provider: {provider}"}


@frappe.whitelist()
def save_api_key(provider, api_key):
    """
    Save the validated API key to the appropriate AskERP Model records.
    Updates all models matching the provider.
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can configure AI settings."))

    provider = (provider or "").strip()
    api_key = (api_key or "").strip()

    if not provider or not api_key:
        frappe.throw(_("Provider and API key are required."))

    # Find all models for this provider
    models = frappe.get_all(
        "AskERP Model",
        filters={"provider": provider},
        fields=["name"],
    )

    if not models:
        frappe.throw(_(f"No AI models found for provider '{provider}'. Run after_install first."))

    updated = 0
    for m in models:
        doc = frappe.get_doc("AskERP Model", m["name"])
        doc.api_key = api_key
        doc.enabled = 1
        doc.save(ignore_permissions=True)
        updated += 1

    # Update setup progress
    _update_step(2)

    frappe.db.commit()
    return {"success": True, "models_updated": updated}


# ─── Step 3: Quick Business Profile ───────────────────────────────────────

@frappe.whitelist()
def save_quick_profile(company_name, industry, description):
    """
    Save the 3 essential business profile fields from the wizard.
    Admin can fill in the rest later from the full Business Profile form.
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can configure AI settings."))

    company_name = (company_name or "").strip()
    industry = (industry or "").strip()
    description = (description or "").strip()

    if not company_name:
        frappe.throw(_("Company name is required."))

    try:
        profile = frappe.get_single("AskERP Business Profile")
    except frappe.DoesNotExistError:
        profile = frappe.get_doc({"doctype": "AskERP Business Profile"})
        profile.insert(ignore_permissions=True)
        profile = frappe.get_single("AskERP Business Profile")

    profile.company_name = company_name
    if industry:
        profile.industry = industry
    if description:
        profile.industry_detail = description

    profile.save(ignore_permissions=True)

    # Update setup progress
    _update_step(3)

    frappe.db.commit()
    return {"success": True}


# ─── Step 4: User Enablement ──────────────────────────────────────────────

@frappe.whitelist()
def get_users_for_enablement():
    """
    Get list of active users with their current AI access status.
    Returns users suitable for the enablement checkboxes.
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can manage user access."))

    users = frappe.get_all(
        "User",
        filters={
            "enabled": 1,
            "user_type": "System User",
            "name": ["not in", ["Guest", "Administrator"]],
        },
        fields=["name", "full_name", "allow_ai_chat", "user_image"],
        order_by="full_name asc",
        limit_page_length=200,
    )

    return users


@frappe.whitelist()
def bulk_enable_ai_chat(user_list):
    """
    Bulk enable/disable AI chat for selected users.
    user_list: JSON string of [{user: "user@example.com", enabled: 1/0}, ...]
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can manage user access."))

    import json as json_module

    if isinstance(user_list, str):
        try:
            user_list = json_module.loads(user_list)
        except Exception:
            frappe.throw(_("Invalid user list format."))

    if not isinstance(user_list, list):
        frappe.throw(_("User list must be an array."))

    enabled_count = 0
    disabled_count = 0

    for item in user_list:
        user = item.get("user")
        enabled = int(item.get("enabled", 0))

        if not user or user in ("Guest", "Administrator"):
            continue

        if not frappe.db.exists("User", user):
            continue

        frappe.db.set_value("User", user, "allow_ai_chat", enabled, update_modified=False)

        if enabled:
            enabled_count += 1
        else:
            disabled_count += 1

    # Update setup progress
    _update_step(4)

    frappe.db.commit()
    return {
        "success": True,
        "enabled_count": enabled_count,
        "disabled_count": disabled_count,
    }


# ─── Step 5: Complete Setup ───────────────────────────────────────────────

@frappe.whitelist()
def complete_setup():
    """
    Mark the setup wizard as complete.
    Sets setup_complete=1, records who completed it and when.
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can complete setup."))

    settings = frappe.get_single("AskERP Settings")
    settings.setup_complete = 1
    settings.setup_completed_by = frappe.session.user
    settings.setup_completed_on = frappe.utils.now_datetime()
    settings.setup_current_step = 5
    settings.save(ignore_permissions=True)

    # Also enable AI for the admin who completed setup
    frappe.db.set_value("User", frappe.session.user, "allow_ai_chat", 1, update_modified=False)

    frappe.db.commit()

    # Trigger auto business context discovery in background
    # This scans ERPNext schema and populates the Business Profile with
    # intelligent context (industry details, products, sales channels, etc.)
    try:
        frappe.enqueue(
            "askerp.context_discovery.run_context_discovery",
            overwrite=False,  # Don't overwrite fields the admin already filled in wizard
            queue="long",
            timeout=300,  # 5 minutes max
            now=False,
        )
        frappe.logger("askerp").info("Auto context discovery enqueued after setup completion")
    except Exception:
        # Non-critical — setup still succeeds even if discovery fails to enqueue
        frappe.log_error(title="AskERP: Context discovery enqueue failed")

    return {"success": True}


@frappe.whitelist()
def reset_setup():
    """
    Reset setup wizard so it can be re-run.
    Accessible from AskERP Settings form.
    """
    if not _is_admin():
        frappe.throw(_("Only System Manager can reset setup."))

    settings = frappe.get_single("AskERP Settings")
    settings.setup_complete = 0
    settings.setup_completed_by = None
    settings.setup_completed_on = None
    settings.setup_current_step = 0
    settings.save(ignore_permissions=True)

    frappe.db.commit()
    return {"success": True, "message": "Setup wizard reset. Refresh the page to start again."}


# ─── Boot Session Hook ────────────────────────────────────────────────────

def boot_session(bootinfo):
    """
    Called on every page load via hooks.py boot_session.
    Injects setup_complete flag into the boot payload so the
    chat widget can show the notification bar.
    """
    if frappe.session.user == "Guest":
        return

    try:
        settings = frappe.get_single("AskERP Settings")
        bootinfo["askerp_setup_complete"] = bool(settings.setup_complete)
        bootinfo["askerp_setup_step"] = settings.setup_current_step or 0
    except Exception:
        bootinfo["askerp_setup_complete"] = False
        bootinfo["askerp_setup_step"] = 0


# ─── Helpers ──────────────────────────────────────────────────────────────

def _is_admin():
    """Check if current user has System Manager or Administrator role."""
    return (
        frappe.session.user == "Administrator"
        or "System Manager" in frappe.get_roles(frappe.session.user)
    )


def _update_step(step_number):
    """Update the current step in AskERP Settings."""
    try:
        settings = frappe.get_single("AskERP Settings")
        if (settings.setup_current_step or 0) < step_number:
            settings.setup_current_step = step_number
            settings.save(ignore_permissions=True)
    except Exception:
        pass


def _test_anthropic_key(api_key):
    """Test Anthropic API key with a minimal request."""
    import requests

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Hi"}],
            },
            timeout=15,
        )

        if resp.status_code == 200:
            return {
                "success": True,
                "message": "Anthropic API key is valid! Connection successful.",
                "provider": "Anthropic",
            }
        elif resp.status_code == 401:
            return {
                "success": False,
                "message": "Invalid API key. Please check your Anthropic API key and try again.",
            }
        elif resp.status_code == 429:
            # Rate limited but key is valid
            return {
                "success": True,
                "message": "API key is valid (rate limited — this is normal for testing).",
                "provider": "Anthropic",
            }
        else:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = body.get("error", {}).get("message", resp.text[:200])
            return {
                "success": False,
                "message": f"Anthropic API returned status {resp.status_code}: {error_msg}",
            }
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timed out. Check your network and try again."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "Could not connect to Anthropic. Check your network."}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)[:200]}"}


def _test_google_key(api_key):
    """Test Google Gemini API key with a minimal request."""
    import requests

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"content-type": "application/json"},
            json={
                "contents": [{"parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 10},
            },
            timeout=15,
        )

        if resp.status_code == 200:
            return {
                "success": True,
                "message": "Google Gemini API key is valid! Connection successful.",
                "provider": "Google",
            }
        elif resp.status_code == 400:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = body.get("error", {}).get("message", "Invalid request")
            if "API_KEY_INVALID" in str(error_msg).upper() or "API key" in str(error_msg):
                return {"success": False, "message": "Invalid Google API key. Please check and try again."}
            return {"success": False, "message": f"Google API error: {error_msg[:200]}"}
        elif resp.status_code == 403:
            return {"success": False, "message": "API key doesn't have access to Gemini. Enable the Generative Language API in Google Cloud Console."}
        else:
            return {"success": False, "message": f"Google API returned status {resp.status_code}."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timed out. Check your network and try again."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "Could not connect to Google. Check your network."}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)[:200]}"}


def _test_openai_key(api_key):
    """Test OpenAI API key with a minimal request."""
    import requests

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 10,
            },
            timeout=15,
        )

        if resp.status_code == 200:
            return {
                "success": True,
                "message": "OpenAI API key is valid! Connection successful.",
                "provider": "OpenAI",
            }
        elif resp.status_code == 401:
            return {"success": False, "message": "Invalid OpenAI API key. Please check and try again."}
        elif resp.status_code == 429:
            return {
                "success": True,
                "message": "API key is valid (rate limited — this is normal for testing).",
                "provider": "OpenAI",
            }
        else:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = body.get("error", {}).get("message", resp.text[:200])
            return {"success": False, "message": f"OpenAI API error: {error_msg[:200]}"}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Connection timed out. Check your network and try again."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "Could not connect to OpenAI. Check your network."}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)[:200]}"}
