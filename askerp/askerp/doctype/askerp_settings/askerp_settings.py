"""AskERP Settings — Single doctype for global AI assistant configuration."""

import frappe
from frappe.model.document import Document


class AskERPSettings(Document):
    def on_update(self):
        """Clear any cached setup status on save."""
        frappe.cache().delete_value("askerp_setup_complete")

    def validate(self):
        """Validate settings before saving."""
        # Ensure budget threshold is between 0 and 100
        if self.budget_warning_threshold:
            if self.budget_warning_threshold < 0 or self.budget_warning_threshold > 100:
                frappe.throw("Budget warning threshold must be between 0 and 100 percent.")

        # Validate email format if provided
        if self.budget_alert_email:
            import re
            if not re.match(r"[^@]+@[^@]+\.[^@]+", self.budget_alert_email):
                frappe.throw("Please enter a valid email address for budget alerts.")

        # Warn if smart routing is on but tiers are incomplete
        if self.enable_smart_routing:
            missing = []
            if not self.tier_1_model:
                missing.append("Tier 1 (Economy)")
            if not self.tier_2_model:
                missing.append("Tier 2 (Standard)")
            if not self.tier_3_model:
                missing.append("Tier 3 (Premium)")
            if missing:
                frappe.msgprint(
                    f"Smart routing is enabled but these tiers are not configured: {', '.join(missing)}. "
                    f"Queries will fall back to the highest available tier.",
                    indicator="orange",
                    title="Incomplete Tier Configuration",
                )
