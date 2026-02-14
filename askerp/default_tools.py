"""
AskERP Custom Tools — Pre-Built Tool Templates
===============================================
Phase 4, Task 4.5: Ship 8 ready-to-use tools that work out of the box.
Created during after_install and can be customized by admins.
"""

DEFAULT_CUSTOM_TOOLS = [
    # ─── 1. Check Customer Outstanding ────────────────────────────────
    {
        "tool_name": "check_customer_outstanding",
        "display_name": "Check Customer Outstanding",
        "description": (
            "Look up the total outstanding receivable amount for a specific customer. "
            "Returns the sum of unpaid and partially paid Sales Invoice balances. "
            "Use when the user asks about a customer's dues, outstanding, receivables, or balance."
        ),
        "category": "Sales",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  customer_name, "
            "  COUNT(name) as invoice_count, "
            "  SUM(grand_total) as total_invoiced, "
            "  SUM(outstanding_amount) as total_outstanding, "
            "  MIN(posting_date) as oldest_invoice_date, "
            "  DATEDIFF(CURDATE(), MIN(posting_date)) as max_aging_days "
            "FROM `tabSales Invoice` "
            "WHERE customer_name LIKE %(customer_name)s "
            "  AND docstatus = 1 "
            "  AND outstanding_amount > 0 "
            "GROUP BY customer_name"
        ),
        "query_limit": 10,
        "output_format": "Summary",
        "parameters": [
            {
                "param_name": "customer_name",
                "param_type": "String",
                "param_description": "Customer name (or partial name with % wildcards)",
                "required": 1,
            },
        ],
    },

    # ─── 2. Top Selling Items ─────────────────────────────────────────
    {
        "tool_name": "top_selling_items",
        "display_name": "Top Selling Items",
        "description": (
            "Get the best-selling items ranked by quantity or revenue for a given date range. "
            "Use when the user asks about top products, best sellers, most popular items, "
            "or sales rankings."
        ),
        "category": "Sales",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  sii.item_name, "
            "  sii.item_code, "
            "  SUM(sii.qty) as total_qty, "
            "  SUM(sii.amount) as total_revenue, "
            "  sii.uom, "
            "  COUNT(DISTINCT si.name) as invoice_count "
            "FROM `tabSales Invoice Item` sii "
            "JOIN `tabSales Invoice` si ON si.name = sii.parent "
            "WHERE si.docstatus = 1 "
            "  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s "
            "GROUP BY sii.item_code, sii.item_name, sii.uom "
            "ORDER BY total_revenue DESC "
            "LIMIT 20"
        ),
        "query_limit": 20,
        "output_format": "Table",
        "parameters": [
            {
                "param_name": "from_date",
                "param_type": "Date",
                "param_description": "Start date for the period (YYYY-MM-DD)",
                "required": 1,
            },
            {
                "param_name": "to_date",
                "param_type": "Date",
                "param_description": "End date for the period (YYYY-MM-DD)",
                "required": 1,
            },
        ],
    },

    # ─── 3. Stock Status ──────────────────────────────────────────────
    {
        "tool_name": "stock_status",
        "display_name": "Stock Status",
        "description": (
            "Check the current stock level for a specific item across all warehouses. "
            "Returns actual qty, reserved qty, and available qty per warehouse. "
            "Use when the user asks about stock levels, availability, inventory, or 'how much do we have'."
        ),
        "category": "Inventory",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  b.warehouse, "
            "  b.actual_qty, "
            "  b.reserved_qty, "
            "  (b.actual_qty - b.reserved_qty) as available_qty, "
            "  b.stock_uom, "
            "  b.valuation_rate, "
            "  ROUND(b.actual_qty * b.valuation_rate, 2) as stock_value "
            "FROM `tabBin` b "
            "WHERE b.item_code = %(item_code)s "
            "  AND b.actual_qty != 0 "
            "ORDER BY b.actual_qty DESC"
        ),
        "query_limit": 100,
        "output_format": "Table",
        "parameters": [
            {
                "param_name": "item_code",
                "param_type": "String",
                "param_description": "The item code to check stock for",
                "required": 1,
            },
        ],
    },

    # ─── 4. Pending Approvals Summary ─────────────────────────────────
    {
        "tool_name": "pending_approvals_summary",
        "display_name": "Pending Approvals Summary",
        "description": (
            "Get a count of all pending approval documents across Sales Orders, "
            "Sales Invoices, Purchase Receipts, and Payment Proposals. "
            "Use when the user asks about approvals, pending items, or 'what needs my attention'."
        ),
        "category": "Custom",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT 'Sales Order' as document_type, COUNT(*) as pending_count "
            "FROM `tabSales Order` WHERE workflow_state = 'Pending for Approval' AND docstatus = 0 "
            "UNION ALL "
            "SELECT 'Sales Invoice', COUNT(*) "
            "FROM `tabSales Invoice` WHERE workflow_state = 'Pending for Approval' AND docstatus = 0 "
            "UNION ALL "
            "SELECT 'Purchase Receipt', COUNT(*) "
            "FROM `tabPurchase Receipt` WHERE workflow_state = 'Pending for Approval' AND docstatus = 0 "
            "UNION ALL "
            "SELECT 'Payment Proposal', COUNT(*) "
            "FROM `tabPayment Proposal` WHERE workflow_state IN ('Pending for Verification', 'Pending for Approval') AND docstatus = 0"
        ),
        "query_limit": 10,
        "output_format": "Table",
        "parameters": [],
    },

    # ─── 5. Overdue Invoices ──────────────────────────────────────────
    {
        "tool_name": "overdue_invoices",
        "display_name": "Overdue Sales Invoices",
        "description": (
            "List all overdue (past due date) unpaid sales invoices with aging in days. "
            "Use when the user asks about overdue payments, aging receivables, "
            "late payments, or delinquent accounts."
        ),
        "category": "Finance",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  name, customer_name, posting_date, due_date, "
            "  grand_total, outstanding_amount, "
            "  DATEDIFF(CURDATE(), due_date) as days_overdue, "
            "  territory "
            "FROM `tabSales Invoice` "
            "WHERE docstatus = 1 "
            "  AND outstanding_amount > 0 "
            "  AND due_date < CURDATE() "
            "ORDER BY days_overdue DESC "
            "LIMIT %(max_results)s"
        ),
        "query_limit": 100,
        "output_format": "Table",
        "parameters": [
            {
                "param_name": "max_results",
                "param_type": "Number",
                "param_description": "Maximum number of results to return (default 50)",
                "required": 0,
                "default_value": "50",
            },
        ],
    },

    # ─── 6. Supplier Performance ──────────────────────────────────────
    {
        "tool_name": "supplier_performance",
        "display_name": "Supplier Performance",
        "description": (
            "Analyze a supplier's performance: total purchases, invoice count, "
            "average order value, and payment status. "
            "Use when the user asks about supplier evaluation, vendor performance, "
            "or purchase history with a supplier."
        ),
        "category": "Purchase",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  supplier_name, "
            "  COUNT(name) as total_invoices, "
            "  SUM(grand_total) as total_purchased, "
            "  ROUND(AVG(grand_total), 2) as avg_invoice_value, "
            "  SUM(outstanding_amount) as total_outstanding, "
            "  MIN(posting_date) as first_invoice_date, "
            "  MAX(posting_date) as latest_invoice_date "
            "FROM `tabPurchase Invoice` "
            "WHERE supplier_name LIKE %(supplier_name)s "
            "  AND docstatus = 1 "
            "GROUP BY supplier_name"
        ),
        "query_limit": 10,
        "output_format": "Summary",
        "parameters": [
            {
                "param_name": "supplier_name",
                "param_type": "String",
                "param_description": "Supplier name (or partial with % wildcards)",
                "required": 1,
            },
        ],
    },

    # ─── 7. Daily Sales Summary ───────────────────────────────────────
    {
        "tool_name": "daily_sales_summary",
        "display_name": "Daily Sales Summary",
        "description": (
            "Get a summary of sales activity for a specific date: revenue, order count, "
            "collections received, and new customers. "
            "Use when the user asks about daily sales, today's numbers, "
            "or 'how did we do on [date]'."
        ),
        "category": "Sales",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  'Revenue' as metric, "
            "  COALESCE(SUM(grand_total), 0) as value, "
            "  COUNT(name) as count "
            "FROM `tabSales Invoice` "
            "WHERE posting_date = %(target_date)s AND docstatus = 1 "
            "UNION ALL "
            "SELECT "
            "  'Orders', "
            "  COALESCE(SUM(grand_total), 0), "
            "  COUNT(name) "
            "FROM `tabSales Order` "
            "WHERE transaction_date = %(target_date)s AND docstatus = 1 "
            "UNION ALL "
            "SELECT "
            "  'Collections', "
            "  COALESCE(SUM(paid_amount), 0), "
            "  COUNT(name) "
            "FROM `tabPayment Entry` "
            "WHERE posting_date = %(target_date)s AND docstatus = 1 "
            "  AND payment_type = 'Receive'"
        ),
        "query_limit": 10,
        "output_format": "Table",
        "parameters": [
            {
                "param_name": "target_date",
                "param_type": "Date",
                "param_description": "The date to get the summary for (YYYY-MM-DD)",
                "required": 1,
            },
        ],
    },

    # ─── 8. Employee Leave Balance ────────────────────────────────────
    {
        "tool_name": "employee_leave_balance",
        "display_name": "Employee Leave Balance",
        "description": (
            "Check remaining leave balance for an employee across all leave types. "
            "Use when the user asks about leave balance, remaining holidays, "
            "or vacation days for an employee."
        ),
        "category": "HR",
        "enabled": 1,
        "is_read_only": 1,
        "requires_approval": 0,
        "query_type": "Raw SQL",
        "query_sql": (
            "SELECT "
            "  la.employee_name, "
            "  la.leave_type, "
            "  la.total_leaves_allocated, "
            "  COALESCE(("
            "    SELECT SUM(total_leave_days) FROM `tabLeave Application` "
            "    WHERE employee = la.employee AND leave_type = la.leave_type "
            "    AND docstatus = 1 AND status = 'Approved'"
            "  ), 0) as leaves_taken, "
            "  la.total_leaves_allocated - COALESCE(("
            "    SELECT SUM(total_leave_days) FROM `tabLeave Application` "
            "    WHERE employee = la.employee AND leave_type = la.leave_type "
            "    AND docstatus = 1 AND status = 'Approved'"
            "  ), 0) as balance "
            "FROM `tabLeave Allocation` la "
            "WHERE la.employee_name LIKE %(employee_name)s "
            "  AND la.docstatus = 1 "
            "  AND la.from_date <= CURDATE() "
            "  AND la.to_date >= CURDATE() "
            "ORDER BY la.leave_type"
        ),
        "query_limit": 20,
        "output_format": "Table",
        "parameters": [
            {
                "param_name": "employee_name",
                "param_type": "String",
                "param_description": "Employee name (or partial with % wildcards)",
                "required": 1,
            },
        ],
    },
]
