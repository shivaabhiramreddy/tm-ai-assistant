# AskERP Cached Metric
# Stores pre-computed business metrics for fast AI responses.
# See precompute.py for the scheduler that refreshes these.

import frappe
from frappe.model.document import Document


class AskERPCachedMetric(Document):
    pass
