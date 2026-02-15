"""
AskERP Business Profile — Configurable Business Context for AI
==============================================================
Singleton doctype that stores structured business information.
The AI reads this at runtime to understand the company's context.

Replaces the hardcoded business_context.py with a UI-configurable system.
"""

import frappe
from frappe.model.document import Document


# Fields that count toward completeness, grouped by section
_COMPLETENESS_FIELDS = {
    "Company Identity": ["company_name", "industry", "industry_detail", "location", "company_size", "currency", "financial_year_start"],
    "Products & Services": ["what_you_sell", "what_you_buy", "unit_of_measure"],
    "Sales & Customers": ["sales_channels", "customer_types", "key_metrics_sales"],
    "Operations": ["has_manufacturing"],
    "Finance": ["accounting_focus", "payment_terms"],
    "Terminology": ["custom_terminology", "communication_style"],
    "AI Behavior": ["response_length", "number_format", "executive_focus"],
}


class AskERPBusinessProfile(Document):
    def before_save(self):
        """Calculate profile completeness before every save."""
        self.profile_completeness = self._calculate_completeness()

    def _calculate_completeness(self):
        """
        Calculate how complete the profile is (0-100%).
        Each non-empty field counts equally toward the total.
        """
        total_fields = 0
        filled_fields = 0

        for section, fields in _COMPLETENESS_FIELDS.items():
            for field in fields:
                total_fields += 1
                value = self.get(field)
                if value and str(value).strip():
                    # Check fields have minimum meaningful content
                    if isinstance(value, str) and len(value.strip()) < 3:
                        continue  # Too short to be meaningful
                    filled_fields += 1

        if total_fields == 0:
            return 0

        return round((filled_fields / total_fields) * 100)

    @frappe.whitelist()
    def get_section_status(self):
        """
        Return per-section completeness for the UI indicator.
        Returns dict like: {"Company Identity": {"filled": 5, "total": 7, "pct": 71}, ...}
        """
        result = {}
        for section, fields in _COMPLETENESS_FIELDS.items():
            total = len(fields)
            filled = 0
            for field in fields:
                value = self.get(field)
                if value and str(value).strip() and len(str(value).strip()) >= 3:
                    filled += 1
            result[section] = {
                "filled": filled,
                "total": total,
                "pct": round((filled / total) * 100) if total > 0 else 0,
            }
        return result
