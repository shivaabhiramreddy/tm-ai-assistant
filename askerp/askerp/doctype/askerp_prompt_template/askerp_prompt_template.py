"""
AskERP Prompt Template — Editable System Prompts for AI
=======================================================
Allows admins to view and edit the prompts the AI uses, per role tier,
without any code changes. Supports {{variable}} placeholders that are
replaced at runtime with real data from Business Profile + context.

Key behaviors:
- Auto-extracts {{variables}} from prompt_content on save
- Enforces only one active template per tier
- Tracks last editor and prompt statistics
"""

import re
import frappe
from frappe.model.document import Document


# All available template variables with descriptions, grouped by category.
# This is the single source of truth for what variables are available.
AVAILABLE_VARIABLES = {
    "Company Identity": {
        "company_name": "Primary company name from Business Profile",
        "trading_name": "Trading/brand name (if different from company name)",
        "industry": "Industry type (e.g., Manufacturing, Trading, Services)",
        "industry_detail": "Detailed industry description",
        "location": "Company location (city, state, country)",
        "company_size": "Company size range (e.g., 51-200)",
        "currency": "Primary currency (e.g., INR, USD)",
        "multi_company_enabled": "Whether multi-company setup is active (1/0)",
        "companies_detail": "Description of all companies in the group",
    },
    "Time Context": {
        "today": "Today's date (YYYY-MM-DD)",
        "now_full_date": "Full date (e.g., Friday, 14 February 2026)",
        "current_month": "Current month name and year (e.g., February 2026)",
        "current_month_num": "Current month number zero-padded (e.g., 02)",
        "current_year": "Current year (e.g., 2026)",
        "month_start": "First day of current month (YYYY-MM-DD)",
        "month_end": "Today's date (used as month end for queries)",
        "last_month_label": "Last month name and year (e.g., January 2026)",
        "last_month_start": "First day of last month (YYYY-MM-DD)",
        "last_month_end": "Last day of last month (YYYY-MM-DD)",
        "fy_label": "Financial year label (e.g., FY 2025-26)",
        "fy_short": "Short FY code (e.g., 2526)",
        "fy_start": "Financial year start date (YYYY-MM-DD)",
        "fy_end": "Financial year end date (YYYY-MM-DD)",
        "prev_fy_label": "Previous financial year label",
        "prev_fy_start": "Previous FY start date (YYYY-MM-DD)",
        "fy_q": "Current FY quarter number (1-4)",
        "q_from": "Quarter start date (YYYY-MM-DD)",
        "q_to": "Quarter end date (YYYY-MM-DD)",
        "smly_start": "Same month last year start date",
        "smly_end": "Same month last year end date",
    },
    "User Context": {
        "user_name": "Current user's full name",
        "user_id": "Current user's login ID (email)",
        "user_roles": "Comma-separated list of user's roles",
        "prompt_tier": "User's prompt tier (executive/management/field)",
    },
    "Products & Operations": {
        "what_you_sell": "Products/services the company sells",
        "what_you_buy": "Raw materials/supplies the company buys",
        "unit_of_measure": "Primary unit of measure (e.g., Kg, Unit)",
        "pricing_model": "Pricing model (e.g., Per Unit, Per Kg)",
        "sales_channels": "Sales channels (Direct, Dealer, Institutional, etc.)",
        "customer_types": "Customer types served",
        "has_manufacturing": "Whether company has manufacturing (1/0)",
        "manufacturing_detail": "Manufacturing process details",
        "key_metrics_sales": "Key sales metrics the business tracks",
        "key_metrics_production": "Key production metrics the business tracks",
    },
    "Finance": {
        "number_format": "Number format preference (Indian/Western)",
        "accounting_focus": "Key accounting areas of focus",
        "payment_terms": "Standard payment terms",
        "financial_year_start": "FY start month-day (e.g., 04-01 for April)",
        "financial_analysis_depth": "Depth of financial analysis (Standard/Deep/Basic)",
    },
    "AI Behavior": {
        "ai_personality": "AI personality description",
        "example_voice": "Example of how the AI should speak",
        "communication_style": "Communication style (Professional/Casual/Formal)",
        "primary_language": "Primary language for responses",
        "response_length": "Preferred response length (Concise/Detailed/Brief)",
        "executive_focus": "Executive focus areas for insights",
        "restricted_data": "Data the AI should NOT expose",
    },
    "Custom Data": {
        "custom_terminology": "Company-specific terms and their meanings (JSON)",
        "custom_doctypes_info": "Custom ERPNext doctypes and their fields (JSON)",
        "industry_benchmarks": "Industry benchmark values (JSON)",
    },
    "Memory": {
        "memory_context": "Past session summaries and user preferences",
    },
}


def get_available_variables_flat():
    """Return a flat dict of all available variables with descriptions."""
    flat = {}
    for category, variables in AVAILABLE_VARIABLES.items():
        for var_name, var_desc in variables.items():
            flat[var_name] = {"description": var_desc, "category": category}
    return flat


class AskERPPromptTemplate(Document):
    def before_save(self):
        """Extract variables, update stats, track editor."""
        self._extract_variables()
        self._update_stats()
        self.last_edited_by = frappe.session.user
        self.last_edited_on = frappe.utils.now_datetime()

    def validate(self):
        """Enforce one active template per tier."""
        if self.is_active and self.tier:
            self._deactivate_other_templates()
        self._validate_variables()

    def _extract_variables(self):
        """
        Find all {{variable}} placeholders in the prompt content.
        Sets variables_used (newline-separated) and variable_count.
        """
        if not self.prompt_content:
            self.variables_used = ""
            self.variable_count = 0
            return

        # Find all {{variable_name}} patterns (supports dots for profile.field_name)
        pattern = r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\}"
        matches = re.findall(pattern, self.prompt_content)

        # Deduplicate while preserving order
        seen = set()
        unique_vars = []
        for var in matches:
            if var not in seen:
                seen.add(var)
                unique_vars.append(var)

        self.variables_used = "\n".join(unique_vars)
        self.variable_count = len(unique_vars)

    def _update_stats(self):
        """Update prompt length statistics."""
        if self.prompt_content:
            self.prompt_char_count = len(self.prompt_content)
        else:
            self.prompt_char_count = 0

    def _deactivate_other_templates(self):
        """
        When this template is activated, deactivate all other templates
        in the same tier. Only one active template per tier.
        """
        other_active = frappe.get_all(
            "AskERP Prompt Template",
            filters={
                "tier": self.tier,
                "is_active": 1,
                "name": ["!=", self.name],
            },
            pluck="name",
        )

        for name in other_active:
            frappe.db.set_value(
                "AskERP Prompt Template", name, "is_active", 0, update_modified=False
            )

        if other_active:
            frappe.msgprint(
                f"Deactivated {len(other_active)} other template(s) in the '{self.tier}' tier.",
                indicator="orange",
                alert=True,
            )

    def _validate_variables(self):
        """
        Check if any variables in the prompt are not in the known list.
        Warns (doesn't block) — custom variables are allowed.
        """
        if not self.variables_used:
            return

        known = get_available_variables_flat()
        used_vars = [v.strip() for v in self.variables_used.split("\n") if v.strip()]
        unknown = [v for v in used_vars if v not in known]

        if unknown:
            frappe.msgprint(
                f"Unknown variables detected: {', '.join(unknown)}. "
                "These will be replaced with empty strings at runtime unless "
                "you add custom variable handling.",
                indicator="yellow",
                alert=True,
            )

    @frappe.whitelist()
    def get_rendered_preview(self):
        """
        Render the prompt with all variables replaced using current data.
        Used by the Preview button in the client script.
        """
        from askerp.business_context import get_template_variables

        variables = get_template_variables(frappe.session.user)
        rendered = self._render_template(self.prompt_content, variables)
        return rendered

    @frappe.whitelist()
    def test_with_query(self, test_query):
        """
        Send a test query using this template and return the AI response.
        Used by the Test button in the client script.
        """
        from askerp.business_context import get_template_variables

        variables = get_template_variables(frappe.session.user)
        rendered_prompt = self._render_template(self.prompt_content, variables)

        # Use the AI engine with the rendered prompt
        from askerp.ai_engine import get_ai_response

        response = get_ai_response(
            user=frappe.session.user,
            message=test_query,
            system_prompt_override=rendered_prompt,
        )
        return response

    @staticmethod
    def _render_template(template_text, variables):
        """
        Replace all {{variable}} placeholders with values from the variables dict.
        Unknown variables are replaced with empty string.
        """
        if not template_text:
            return ""

        def replace_var(match):
            var_name = match.group(1)
            value = variables.get(var_name, "")
            if value is None:
                return ""
            return str(value)

        pattern = r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)\}\}"
        return re.sub(pattern, replace_var, template_text)
