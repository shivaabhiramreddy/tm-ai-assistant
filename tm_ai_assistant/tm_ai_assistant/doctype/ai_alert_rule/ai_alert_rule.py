"""AI Alert Rule — Controller for user-created business alerts."""

import frappe
from frappe.model.document import Document


class AIAlertRule(Document):
    def validate(self):
        """Validate alert rule before saving."""
        if not self.alert_name:
            frappe.throw("Alert name is required.")
        if not self.query_doctype:
            frappe.throw("A doctype to monitor is required.")
        if self.threshold_value is None:
            frappe.throw("Threshold value is required.")

        # Ensure frequency is valid
        if self.frequency not in ("hourly", "daily", "weekly"):
            self.frequency = "daily"

    def before_insert(self):
        """Set defaults on creation."""
        self.active = 1
        self.trigger_count = 0
