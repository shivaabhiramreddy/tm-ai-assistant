"""AskERP Model — Controller for the AI model registry."""

import frappe
from frappe.model.document import Document


class AskERPModel(Document):
    def validate(self):
        """Validate model configuration before saving."""
        if not self.model_name:
            frappe.throw("Model Name is required.")
        if not self.model_id:
            frappe.throw("Model ID is required (the API model string).")
        if not self.provider:
            frappe.throw("Provider is required.")
        if not self.tier:
            frappe.throw("Tier is required.")

        # Auto-fill API base URL based on provider if not set
        if not self.api_base_url:
            provider_urls = {
                "Anthropic": "https://api.anthropic.com/v1/messages",
                "Google": "https://generativelanguage.googleapis.com/v1beta/models",
                "OpenAI": "https://api.openai.com/v1/chat/completions",
            }
            self.api_base_url = provider_urls.get(self.provider, "")

        # Auto-fill API version for Anthropic
        if self.provider == "Anthropic" and not self.api_version:
            self.api_version = "2023-06-01"

        # Validate rate limits — no duplicate roles
        seen_roles = set()
        for row in self.rate_limits or []:
            if row.role in seen_roles:
                frappe.throw(f"Duplicate role '{row.role}' in rate limits. Each role should appear only once.")
            seen_roles.add(row.role)

    def before_insert(self):
        """Set defaults on creation."""
        if not self.test_status:
            self.test_status = "Not Tested"
