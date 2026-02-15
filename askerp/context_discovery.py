"""
AskERP — Auto Business Context Discovery Engine
=================================================
Uses the most intelligent AI model to scan the ERPNext database schema and
auto-generate/update the AskERP Business Profile with comprehensive context.

Two modes:
1. **Post-Setup Discovery** — Runs after the setup wizard completes.
   Scans ERPNext schema, analyzes business data patterns, and populates
   the Business Profile fields automatically.

2. **Scheduled Refresh** — Monthly cron job that re-analyzes the database
   and updates context with latest business patterns (new doctypes, new
   custom fields, data volume changes, etc.).

The discovery engine gathers raw facts from ERPNext (schema, record counts,
custom fields, warehouses, items, territories, etc.) and sends them to the
tier_3 model to produce human-readable business context.

Usage:
    # Trigger manually:
    from askerp.context_discovery import run_context_discovery
    run_context_discovery()

    # Scheduled (via hooks.py):
    askerp.context_discovery.scheduled_context_refresh
"""

import json
import frappe
from frappe import _


# ─── Workflow & Approval Chain Scanner ────────────────────────────────────────

def _scan_workflow_details():
    """
    Deep-scan all active ERPNext workflows to understand approval chains.

    For each active workflow, captures:
    - Document type it applies to
    - All workflow states (with doc_status mapping: Draft/Submitted/Cancelled)
    - All transitions (from_state → to_state, allowed role, action label)
    - Approval chain reconstruction (ordered path from start → end states)
    - Which roles act as approvers at each stage

    Returns a list of workflow dicts with full introspection data.
    """
    workflows = []

    try:
        active_wfs = frappe.get_all(
            "Workflow",
            filters={"is_active": 1},
            fields=["name", "document_type", "workflow_state_field"],
            limit_page_length=30,
        )
    except Exception:
        return []

    for wf in active_wfs:
        wf_detail = {
            "name": wf["name"],
            "document_type": wf["document_type"],
            "state_field": wf.get("workflow_state_field") or "workflow_state",
            "states": [],
            "transitions": [],
            "approval_chain": [],
        }

        # --- Gather workflow states ---
        try:
            states = frappe.get_all(
                "Workflow Document State",
                filters={"parent": wf["name"]},
                fields=["state", "doc_status", "update_field", "update_value",
                         "is_optional_state", "allow_edit"],
                order_by="idx asc",
            )
            for s in states:
                state_info = {
                    "state": s["state"],
                    "doc_status": _map_doc_status(s.get("doc_status")),
                    "allow_edit": s.get("allow_edit") or "",
                }
                # If this state updates a field (like setting is_approved=1), note it
                if s.get("update_field") and s.get("update_value"):
                    state_info["side_effect"] = f"{s['update_field']}={s['update_value']}"
                wf_detail["states"].append(state_info)
        except Exception:
            pass

        # --- Gather workflow transitions ---
        try:
            transitions = frappe.get_all(
                "Workflow Transition",
                filters={"parent": wf["name"]},
                fields=["state", "action", "next_state", "allowed", "allow_self_approval",
                         "condition"],
                order_by="idx asc",
            )
            for t in transitions:
                trans_info = {
                    "from_state": t["state"],
                    "action": t["action"],
                    "to_state": t["next_state"],
                    "allowed_role": t.get("allowed") or "All",
                    "allow_self_approval": bool(t.get("allow_self_approval")),
                }
                # Only include condition if it exists (rare but important)
                if t.get("condition"):
                    trans_info["condition"] = t["condition"]
                wf_detail["transitions"].append(trans_info)
        except Exception:
            pass

        # --- Reconstruct approval chain ---
        wf_detail["approval_chain"] = _reconstruct_approval_chain(
            wf_detail["states"], wf_detail["transitions"]
        )

        workflows.append(wf_detail)

    return workflows


def _map_doc_status(doc_status):
    """Map ERPNext doc_status integer to human-readable label."""
    mapping = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
    try:
        return mapping.get(int(doc_status), f"Unknown({doc_status})")
    except (ValueError, TypeError):
        return "Draft"


def _reconstruct_approval_chain(states, transitions):
    """
    Reconstruct the approval chain — the primary path from initial state
    to a final submitted/approved state.

    Returns a list of steps like:
    [
        {"state": "Draft", "action": "Submit for Approval", "role": "Sales User"},
        {"state": "Pending", "action": "Approve", "role": "Sales Manager"},
        {"state": "Approved", "action": null, "role": null}
    ]
    """
    if not states or not transitions:
        return []

    # Build a transition graph: from_state → [(action, to_state, role), ...]
    trans_graph = {}
    for t in transitions:
        from_s = t["from_state"]
        if from_s not in trans_graph:
            trans_graph[from_s] = []
        trans_graph[from_s].append({
            "action": t["action"],
            "to_state": t["to_state"],
            "role": t["allowed_role"],
        })

    # State index for priority (earlier = more likely start)
    state_order = {s["state"]: i for i, s in enumerate(states)}

    # Find start state (first state in the list, typically Draft)
    start_state = states[0]["state"]

    # Walk the "happy path" — follow the most forward-progressing transition
    chain = []
    visited = set()
    current = start_state

    max_steps = len(states) + 1  # Safety guard
    step = 0
    while current and step < max_steps:
        step += 1
        if current in visited:
            break  # Avoid loops
        visited.add(current)

        outgoing = trans_graph.get(current, [])
        if not outgoing:
            # Terminal state — add it and stop
            chain.append({"state": current, "action": None, "role": None})
            break

        # Pick the transition that moves forward most (highest state index)
        # Prefer "Approve"-like actions over "Reject"/"Return"
        best = None
        for t in outgoing:
            target_idx = state_order.get(t["to_state"], -1)
            action_lower = (t["action"] or "").lower()
            # Skip reject/return/cancel — they're not the happy path
            if any(word in action_lower for word in ["reject", "return", "cancel"]):
                continue
            if best is None or target_idx > state_order.get(best["to_state"], -1):
                best = t

        if best is None:
            # All transitions are reject/return — just pick the first non-visited
            for t in outgoing:
                if t["to_state"] not in visited:
                    best = t
                    break

        if best is None:
            chain.append({"state": current, "action": None, "role": None})
            break

        chain.append({
            "state": current,
            "action": best["action"],
            "role": best["role"],
        })
        current = best["to_state"]

    # Add terminal state if not already added
    if chain and chain[-1]["action"] is not None:
        chain.append({"state": current, "action": None, "role": None})

    return chain


# ─── Schema Scanner ──────────────────────────────────────────────────────────

def _scan_erpnext_schema():
    """
    Scan the ERPNext instance and gather raw facts about the database.
    Returns a dict of structured information the AI can analyze.
    """
    from askerp.schema_utils import resolve_financial_doctypes, get_table_name

    facts = {}
    _fin = resolve_financial_doctypes()

    # 1. Companies
    try:
        companies = frappe.get_all("Company", fields=["name", "country", "default_currency", "abbr"])
        facts["companies"] = companies
    except Exception:
        facts["companies"] = []

    # 2. Record counts for major doctypes
    major_doctypes = [
        "Customer", "Supplier", "Item", "Sales Order", "Sales Invoice",
        "Purchase Order", "Purchase Invoice", "Payment Entry",
        "Stock Entry", "Delivery Note", "Purchase Receipt",
        "Work Order", "Journal Entry", "Employee", "Warehouse",
        "BOM", "Batch", "Serial No", "Quality Inspection",
    ]
    counts = {}
    for dt in major_doctypes:
        try:
            counts[dt] = frappe.db.count(dt)
        except Exception:
            counts[dt] = 0
    facts["record_counts"] = counts

    # 3. Custom Doctypes (non-standard)
    try:
        custom_dts = frappe.get_all(
            "DocType",
            filters={"custom": 1, "istable": 0},
            fields=["name", "module"],
            limit_page_length=50,
        )
        facts["custom_doctypes"] = custom_dts
    except Exception:
        facts["custom_doctypes"] = []

    # 4. Custom Fields (count per doctype)
    try:
        cf_counts = frappe.db.sql("""
            SELECT dt, COUNT(*) as cnt
            FROM `tabCustom Field`
            GROUP BY dt
            ORDER BY cnt DESC
            LIMIT 30
        """, as_dict=True)
        facts["custom_fields_by_doctype"] = cf_counts
    except Exception:
        facts["custom_fields_by_doctype"] = []

    # 5. Item Groups
    try:
        item_groups = frappe.get_all("Item Group", filters={"is_group": 0}, fields=["name"], limit_page_length=30)
        facts["item_groups"] = [ig["name"] for ig in item_groups]
    except Exception:
        facts["item_groups"] = []

    # 6. Top Items by transaction volume (dynamically resolved)
    try:
        si_dt = _fin.get("sales_invoice")
        if si_dt and frappe.db.exists("DocType", si_dt):
            si_table = get_table_name(si_dt)
            si_item_table = get_table_name(si_dt + " Item")
            top_items = frappe.db.sql(f"""
                SELECT item_code, item_name, COUNT(*) as txn_count
                FROM {si_item_table}
                WHERE parent IN (SELECT name FROM {si_table} WHERE docstatus=1)
                GROUP BY item_code, item_name
                ORDER BY txn_count DESC
                LIMIT 15
            """, as_dict=True)
            facts["top_items"] = top_items
        else:
            facts["top_items"] = []
    except Exception:
        facts["top_items"] = []

    # 7. Customer Groups
    try:
        cg = frappe.get_all("Customer Group", filters={"is_group": 0}, fields=["name"], limit_page_length=20)
        facts["customer_groups"] = [c["name"] for c in cg]
    except Exception:
        facts["customer_groups"] = []

    # 8. Territories
    try:
        territories = frappe.get_all("Territory", filters={"is_group": 0}, fields=["name"], limit_page_length=30)
        facts["territories"] = [t["name"] for t in territories]
    except Exception:
        facts["territories"] = []

    # 9. Warehouses
    try:
        warehouses = frappe.get_all(
            "Warehouse",
            filters={"disabled": 0, "is_group": 0},
            fields=["name", "warehouse_name", "company"],
            limit_page_length=50,
        )
        facts["warehouses"] = warehouses
    except Exception:
        facts["warehouses"] = []

    # 10. POS Profiles (outlets)
    try:
        pos_profiles = frappe.get_all(
            "POS Profile",
            filters={"disabled": 0},
            fields=["name", "warehouse", "company"],
            limit_page_length=20,
        )
        facts["pos_profiles"] = pos_profiles
    except Exception:
        facts["pos_profiles"] = []

    # 11. Active Workflows (deep introspection with states, transitions, roles)
    facts["active_workflows"] = _scan_workflow_details()

    # 12. Installed Apps
    try:
        apps = frappe.get_installed_apps()
        facts["installed_apps"] = apps
    except Exception:
        facts["installed_apps"] = []

    # 13. Revenue summary (last 3 months — dynamically resolved)
    try:
        si_dt = _fin.get("sales_invoice")
        if si_dt and frappe.db.exists("DocType", si_dt):
            si_table = get_table_name(si_dt)
            revenue = frappe.db.sql(f"""
                SELECT
                    DATE_FORMAT(posting_date, '%%Y-%%m') as month,
                    company,
                    COUNT(*) as invoice_count,
                    SUM(grand_total) as total_revenue
                FROM {si_table}
                WHERE docstatus=1 AND is_return=0
                  AND posting_date >= DATE_SUB(CURDATE(), INTERVAL 3 MONTH)
                GROUP BY month, company
                ORDER BY month DESC
            """, as_dict=True)
            facts["recent_revenue"] = revenue
        else:
            facts["recent_revenue"] = []
    except Exception:
        facts["recent_revenue"] = []

    # 14. Supplier Groups
    try:
        sg = frappe.get_all("Supplier Group", fields=["name"], limit_page_length=20)
        facts["supplier_groups"] = [s["name"] for s in sg]
    except Exception:
        facts["supplier_groups"] = []

    # 15. Price Lists
    try:
        price_lists = frappe.get_all("Price List", fields=["name", "currency", "selling", "buying"], limit_page_length=10)
        facts["price_lists"] = price_lists
    except Exception:
        facts["price_lists"] = []

    # 16. UOM (Units of Measure) used
    try:
        uoms = frappe.db.sql("""
            SELECT DISTINCT stock_uom FROM `tabItem` WHERE disabled=0 LIMIT 10
        """, as_dict=True)
        facts["units_of_measure"] = [u["stock_uom"] for u in uoms]
    except Exception:
        facts["units_of_measure"] = []

    # 17. Financial Year
    try:
        fy = frappe.get_all(
            "Fiscal Year",
            filters={"disabled": 0},
            fields=["name", "year_start_date", "year_end_date"],
            order_by="year_start_date desc",
            limit_page_length=3,
        )
        facts["fiscal_years"] = fy
    except Exception:
        facts["fiscal_years"] = []

    # 18. Custom DocType details (fields for top 5 custom doctypes)
    custom_dt_details = []
    for dt_info in facts.get("custom_doctypes", [])[:5]:
        try:
            fields = frappe.get_all(
                "DocField",
                filters={"parent": dt_info["name"], "fieldtype": ["not in", ["Section Break", "Column Break", "Tab Break"]]},
                fields=["fieldname", "fieldtype", "label"],
                limit_page_length=20,
            )
            custom_dt_details.append({
                "doctype": dt_info["name"],
                "module": dt_info.get("module", ""),
                "fields": fields,
            })
        except Exception:
            pass
    facts["custom_doctype_details"] = custom_dt_details

    return facts


# ─── Field-Level Schema Scanner ──────────────────────────────────────────────

def _scan_doctype_fields(doctype_name):
    """
    Scan a single doctype and return its fields + child table structure.
    Returns a dict with parent fields and child table details.
    """
    try:
        meta = frappe.get_meta(doctype_name)
    except Exception:
        return None

    # Get meaningful fields (skip layout elements)
    skip_types = {
        "Section Break", "Column Break", "Tab Break", "HTML",
        "Fold", "Heading", "HTML Editor",
    }

    parent_fields = []
    child_tables = []

    for df in meta.fields:
        if df.fieldtype in skip_types:
            continue

        field_info = {
            "name": df.fieldname,
            "type": df.fieldtype,
            "label": df.label or df.fieldname,
        }

        # Note link targets (critical for AI to understand relationships)
        if df.fieldtype == "Link" and df.options:
            field_info["links_to"] = df.options
        elif df.fieldtype == "Table" and df.options:
            # This is a child table — scan its fields too
            child_meta = _scan_child_table(df.options)
            if child_meta:
                child_tables.append({
                    "fieldname": df.fieldname,
                    "doctype": df.options,
                    "label": df.label or df.fieldname,
                    "fields": child_meta,
                })
            continue

        parent_fields.append(field_info)

    return {
        "fields": parent_fields,
        "child_tables": child_tables,
        "is_submittable": meta.is_submittable,
    }


def _scan_child_table(doctype_name):
    """Scan a child table doctype and return its key fields."""
    try:
        meta = frappe.get_meta(doctype_name)
    except Exception:
        return None

    skip_types = {
        "Section Break", "Column Break", "Tab Break", "HTML",
        "Fold", "Heading", "HTML Editor",
    }

    fields = []
    for df in meta.fields:
        if df.fieldtype in skip_types:
            continue
        # Skip internal frappe fields
        if df.fieldname in ("parent", "parenttype", "parentfield", "idx", "name"):
            continue

        field_info = {"name": df.fieldname, "type": df.fieldtype}
        if df.fieldtype == "Link" and df.options:
            field_info["links_to"] = df.options

        fields.append(field_info)

    return fields


def _scan_active_doctypes():
    """
    Discover which doctypes have actual data and scan their field structure.
    Only scans doctypes with records (active in the business).
    Returns a list of doctype schemas with field details.
    """
    # Standard transactional doctypes to check (universal ERPNext)
    candidate_doctypes = [
        # Sales
        "Sales Order", "Sales Invoice", "Delivery Note", "Quotation",
        # Purchase
        "Purchase Order", "Purchase Invoice", "Purchase Receipt",
        # Inventory
        "Stock Entry", "Work Order", "BOM",
        # Finance
        "Payment Entry", "Journal Entry",
        # Masters
        "Customer", "Supplier", "Item", "Warehouse", "Employee",
        "Territory", "Price List", "POS Profile",
        # Quality / Other
        "Quality Inspection", "Batch", "Serial No",
        "Material Request", "Stock Reconciliation",
        "Asset", "Expense Claim", "Loan",
        "Timesheet", "Project", "Task",
    ]

    # Also add any custom doctypes
    try:
        custom_dts = frappe.get_all(
            "DocType",
            filters={"custom": 1, "istable": 0},
            fields=["name"],
            limit_page_length=50,
        )
        for dt in custom_dts:
            if dt["name"] not in candidate_doctypes:
                candidate_doctypes.append(dt["name"])
    except Exception:
        pass

    active_schemas = []
    for dt_name in candidate_doctypes:
        try:
            count = frappe.db.count(dt_name)
        except Exception:
            continue

        if count == 0:
            continue  # Skip doctypes with no data

        schema = _scan_doctype_fields(dt_name)
        if schema:
            active_schemas.append({
                "doctype": dt_name,
                "record_count": count,
                "is_submittable": schema["is_submittable"],
                "fields": schema["fields"],
                "child_tables": schema["child_tables"],
            })

    return active_schemas


def _generate_data_model_text(active_schemas, facts):
    """
    Generate the AI-ready data model text from discovered schemas.
    This replaces the hardcoded data model section in business_context.py.

    Produces a structured text that teaches the AI:
    - What doctypes exist and what they store
    - Key fields on each doctype (with types and link targets)
    - Child table structures
    - Record counts (so AI knows data volume)
    - SQL table naming convention
    - Key reports available
    - Example SQL patterns based on ACTUAL fields found
    """
    lines = []

    lines.append("## DATABASE SCHEMA — Auto-Discovered Reference")
    lines.append(f"_Last scanned: {frappe.utils.now_datetime().strftime('%Y-%m-%d %H:%M')}_")
    lines.append(f"_Active doctypes with data: {len(active_schemas)}_")
    lines.append("")
    lines.append("**SQL Table Convention:** ERPNext tables are named `tab<DocType>`. "
                  'Example: Sales Invoice → `tabSales Invoice`, Stock Entry → `tabStock Entry`.')
    lines.append("**Submitted documents:** Filter `docstatus=1` for submitted (confirmed) records. "
                  "`docstatus=0` = Draft, `docstatus=2` = Cancelled.")
    lines.append("")

    # Group doctypes by category
    categories = {
        "Sales": ["Sales Order", "Sales Invoice", "Delivery Note", "Quotation"],
        "Purchase": ["Purchase Order", "Purchase Invoice", "Purchase Receipt", "Material Request"],
        "Inventory": ["Stock Entry", "Stock Reconciliation", "Work Order", "BOM", "Batch", "Serial No"],
        "Finance": ["Payment Entry", "Journal Entry", "Expense Claim", "Asset", "Loan"],
        "Masters": ["Customer", "Supplier", "Item", "Warehouse", "Employee",
                     "Territory", "Price List", "POS Profile"],
        "Quality": ["Quality Inspection"],
        "Projects": ["Project", "Task", "Timesheet"],
    }

    # Build a lookup for quick access
    schema_lookup = {s["doctype"]: s for s in active_schemas}

    # Track which doctypes we've rendered
    rendered = set()

    for category, dt_names in categories.items():
        category_schemas = [schema_lookup[dt] for dt in dt_names if dt in schema_lookup]
        if not category_schemas:
            continue

        lines.append(f"### {category} Doctypes")
        for schema in category_schemas:
            _render_doctype(lines, schema)
            rendered.add(schema["doctype"])
        lines.append("")

    # Render any custom / uncategorized doctypes
    custom_schemas = [s for s in active_schemas if s["doctype"] not in rendered]
    if custom_schemas:
        lines.append("### Custom / Other Doctypes")
        for schema in custom_schemas:
            _render_doctype(lines, schema)
        lines.append("")

    # Workflow & Approval Chains section
    workflow_data = facts.get("active_workflows", [])
    if workflow_data:
        lines.append("### Workflows & Approval Chains")
        lines.append(_render_workflow_section(workflow_data))
        lines.append("")

    # Reports section — discover available reports
    lines.append("### Available Reports (use run_report tool)")
    lines.append(_discover_reports())
    lines.append("")

    # SQL pattern examples based on actual discovered fields
    lines.append("### SQL Query Patterns (based on your actual data)")
    lines.append(_generate_sql_examples(active_schemas))

    return "\n".join(lines)


def _render_doctype(lines, schema):
    """Render a single doctype's schema as human-readable text."""
    dt = schema["doctype"]
    count = schema["record_count"]
    submittable = " (submittable)" if schema["is_submittable"] else ""

    # Pick the most important fields (Currency, Link, Data, Int, Float, Select, Date, Check)
    important_types = {
        "Currency", "Link", "Data", "Int", "Float", "Select", "Date",
        "Datetime", "Check", "Small Text", "Long Text", "Text",
        "Percent", "Rating",
    }
    key_fields = [f for f in schema["fields"] if f["type"] in important_types]

    # Format field list — show name and link targets for Link fields
    field_strs = []
    for f in key_fields[:25]:  # Cap at 25 fields to keep prompt manageable
        if f.get("links_to"):
            field_strs.append(f'{f["name"]} (→{f["links_to"]})')
        elif f["type"] == "Currency":
            field_strs.append(f'{f["name"]} ($)')
        elif f["type"] in ("Date", "Datetime"):
            field_strs.append(f'{f["name"]} (date)')
        elif f["type"] == "Check":
            field_strs.append(f'{f["name"]} (0/1)')
        else:
            field_strs.append(f["name"])

    lines.append(f"- **{dt}**{submittable} [{count:,} records]: {', '.join(field_strs)}")

    # Render child tables
    for ct in schema["child_tables"]:
        child_fields = [f["name"] for f in ct["fields"][:15]]
        lines.append(f"  - Child: {ct['doctype']} → {', '.join(child_fields)}")


def _render_workflow_section(workflow_data):
    """
    Render discovered workflows as AI-readable text with approval chains.

    Produces output like:
      **Sales Order** — Workflow: "SO Approval"
      State field: `workflow_state`
      Approval chain: Draft → [Submit for Approval | Sales User] → Pending for Approval → [Approve | Sales Manager] → Approved
      Alternative actions:
        - Pending for Approval → [Reject | Sales Manager] → Rejected
        - Pending for Approval → [Return | Sales Manager] → Draft

      Tips for AI:
      - To find pending approvals: SELECT * FROM `tabSales Order` WHERE workflow_state='Pending for Approval'
      - The allowed role for each transition determines WHO can perform the action
    """
    lines = []

    lines.append("_Active workflows define the approval process for key business documents._")
    lines.append("_When users ask about 'pending approvals' or 'what needs my attention', check the workflow state field._")
    lines.append("")

    for wf in workflow_data:
        dt = wf["document_type"]
        wf_name = wf["name"]
        state_field = wf.get("state_field", "workflow_state")

        lines.append(f"**{dt}** — Workflow: \"{wf_name}\"")
        lines.append(f"  State field: `{state_field}`")

        # Render the approval chain (happy path)
        chain = wf.get("approval_chain", [])
        if chain:
            chain_parts = []
            for step in chain:
                if step["action"]:
                    chain_parts.append(f"{step['state']} → [{step['action']} | {step['role']}]")
                else:
                    chain_parts.append(step["state"])
            lines.append(f"  Approval chain: {' → '.join(chain_parts)}")

        # Render alternative transitions (reject, return, cancel) — important for completeness
        all_transitions = wf.get("transitions", [])
        chain_actions = {(s["state"], s["action"]) for s in chain if s["action"]}
        alt_transitions = [
            t for t in all_transitions
            if (t["from_state"], t["action"]) not in chain_actions
        ]
        if alt_transitions:
            lines.append("  Alternative actions:")
            for t in alt_transitions:
                cond = f" (if {t['condition']})" if t.get("condition") else ""
                lines.append(
                    f"    - {t['from_state']} → [{t['action']} | {t['allowed_role']}] → {t['to_state']}{cond}"
                )

        # Render all possible states with doc_status
        states = wf.get("states", [])
        if states:
            state_strs = [f"{s['state']} ({s['doc_status']})" for s in states]
            lines.append(f"  All states: {', '.join(state_strs)}")

        lines.append("")

    # Add universal tips for the AI
    lines.append("**Workflow Query Tips:**")
    lines.append("- Pending approvals: `SELECT * FROM \\`tab<DocType>\\` WHERE <state_field>='<pending_state>'`")
    lines.append("- The `allowed` role on each transition determines WHO can approve/reject")
    lines.append("- `allow_self_approval=False` means the submitter cannot also be the approver")
    lines.append("- Documents in 'Draft' state (docstatus=0) are editable; 'Submitted' (docstatus=1) are locked")

    return "\n".join(lines)


def _discover_reports():
    """Discover which standard reports are available."""
    # These are universal ERPNext reports — check if the underlying doctypes exist
    report_map = {
        "Accounts Receivable": ("Sales Invoice", "Aging, who owes us", "company, ageing_based_on"),
        "Accounts Payable": ("Purchase Invoice", "What we owe suppliers", "company, ageing_based_on"),
        "General Ledger": ("Journal Entry", "Transaction detail", "company, account, from_date, to_date"),
        "Trial Balance": ("Journal Entry", "Account balances", "company, from_date, to_date"),
        "Balance Sheet": ("Journal Entry", "Financial position", "company, period_start_date"),
        "Profit and Loss Statement": ("Journal Entry", "P&L statement", "company, from_date, to_date"),
        "Stock Balance": ("Bin", "Inventory levels", "company, warehouse, item_code"),
        "Stock Ledger": ("Stock Entry", "Stock movements", "item_code, warehouse, from_date"),
        "Gross Profit": ("Sales Invoice", "Margin analysis", "company, from_date, to_date"),
        "Sales Analytics": ("Sales Invoice", "Sales trends", "company, from_date, to_date"),
        "Purchase Analytics": ("Purchase Invoice", "Purchase trends", "company, from_date, to_date"),
    }

    lines = []
    lines.append("| Report | Best For | Key Filters |")
    lines.append("|--------|----------|-------------|")

    for report_name, (check_dt, description, filters) in report_map.items():
        try:
            if frappe.db.count(check_dt) > 0:
                lines.append(f"| **{report_name}** | {description} | {filters} |")
        except Exception:
            pass

    return "\n".join(lines)


def _generate_sql_examples(active_schemas):
    """Generate SQL examples based on actual discovered fields."""
    schema_lookup = {s["doctype"]: s for s in active_schemas}
    examples = []

    # Revenue query (if Sales Invoice exists)
    if "Sales Invoice" in schema_lookup:
        si = schema_lookup["Sales Invoice"]
        si_fields = {f["name"] for f in si["fields"]}
        amount_field = "grand_total" if "grand_total" in si_fields else "total" if "total" in si_fields else "amount"
        examples.append(f"""```sql
-- Revenue by month
SELECT DATE_FORMAT(posting_date, '%Y-%m') as month, SUM({amount_field}) as revenue
FROM `tabSales Invoice`
WHERE docstatus=1 AND is_return=0 AND posting_date BETWEEN '{{start}}' AND '{{end}}'
GROUP BY month ORDER BY month
```""")

    # Outstanding query
    if "Sales Invoice" in schema_lookup:
        examples.append("""```sql
-- Customer outstanding
SELECT customer_name, SUM(outstanding_amount) as outstanding
FROM `tabSales Invoice`
WHERE docstatus=1 AND outstanding_amount > 0
GROUP BY customer_name ORDER BY outstanding DESC
```""")

    # Stock query (if Bin exists)
    if "Bin" in schema_lookup:
        examples.append("""```sql
-- Stock value by warehouse
SELECT warehouse, SUM(actual_qty * valuation_rate) as stock_value
FROM `tabBin` WHERE actual_qty > 0
GROUP BY warehouse ORDER BY stock_value DESC
```""")

    # Payment collections (if Payment Entry exists)
    if "Payment Entry" in schema_lookup:
        examples.append("""```sql
-- Collections this month
SELECT party_name, SUM(paid_amount) as collected
FROM `tabPayment Entry`
WHERE docstatus=1 AND payment_type='Receive' AND posting_date BETWEEN '{start}' AND '{end}'
GROUP BY party_name ORDER BY collected DESC
```""")

    # Inventory movement (if Stock Entry exists)
    if "Stock Entry" in schema_lookup:
        examples.append("""```sql
-- Stock movements by type
SELECT stock_entry_type, COUNT(*) as count, SUM(total_amount) as value
FROM `tabStock Entry`
WHERE docstatus=1 AND posting_date BETWEEN '{start}' AND '{end}'
GROUP BY stock_entry_type
```""")

    if not examples:
        return "_No transactional data found yet. SQL examples will appear after first transactions._"

    result = "\n\n".join(examples)

    # Append universal best practices
    result += """

### Best Practices for Queries
- **Always filter docstatus=1** for submitted (confirmed) documents
- **Always exclude returns** for revenue queries: `is_return=0`
- **Use company filter** when showing company-specific data
- **Default date range**: If no date specified, use current financial year
- **For "sales"**: query Sales Invoice (not Sales Order) unless user says "orders"
- **For "outstanding"**: query `outstanding_amount` field on SI/PI
- **For "stock"**: use `tabBin` for real-time quantities, Stock Balance report for detailed view
- **For "collections"**: Payment Entry with `payment_type='Receive'`
- **For child table JOINs**: use `tabChild Table`.parent = `tabParent`.name pattern"""

    return result


# ─── AI Analysis ─────────────────────────────────────────────────────────────

_DISCOVERY_PROMPT = """You are analyzing an ERPNext database to generate a comprehensive business profile.
Based on the raw database facts provided, generate a detailed business context that will help an AI assistant
understand this business deeply.

You must return a valid JSON object with EXACTLY these keys (all values are strings):

{{
  "industry_detail": "2-3 sentence description of what this company does, based on items, customers, and transaction patterns",
  "what_you_sell": "List of main products/services, one per line, based on top-selling items",
  "what_you_buy": "List of main raw materials/inputs, one per line, based on supplier data and stock entries",
  "sales_channels": "How they sell — based on customer groups, territories, POS profiles, sales partners",
  "customer_types": "Types of customers based on customer groups",
  "key_metrics_sales": "Recommended key sales metrics based on the data patterns observed",
  "manufacturing_detail": "Description of manufacturing if applicable (based on work orders, BOMs, stock entries)",
  "key_metrics_production": "Recommended production metrics if manufacturing exists",
  "accounting_focus": "Key financial questions this business should track, based on transaction patterns",
  "custom_terminology": "Any custom terms detected from custom doctypes and fields, format: TERM = Meaning",
  "custom_doctypes_info": "Description of each custom doctype and its purpose, one per line",
  "executive_focus": "Top 5-7 executive focus areas based on the business data patterns",
  "industry_benchmarks": "Relevant industry benchmarks based on the detected industry",
  "approval_workflows": "Summary of active workflows and approval chains. For each: which document, who approves, what states exist. Example: Sales Orders require Sales Manager approval before dispatch."
}}

Be specific and data-driven. Reference actual item names, customer groups, and territories you see in the data.
If a field is not applicable (e.g., no manufacturing), set the value to an empty string "".
Return ONLY the JSON object, no markdown, no explanation."""


def _analyze_with_ai(facts):
    """
    Send the gathered facts to the most intelligent model for analysis.
    Returns a dict of field values to update on the Business Profile.
    """
    from askerp.providers import get_model_for_tier, call_model

    # Use tier_3 (most intelligent) for schema analysis
    model_doc = get_model_for_tier("tier_3")
    if not model_doc:
        # Fall back to tier_2
        model_doc = get_model_for_tier("tier_2")
    if not model_doc:
        frappe.log_error(
            title="AskERP Context Discovery",
            message="No AI model configured for context discovery. Please set up at least a tier_2 or tier_3 model."
        )
        return None

    # Prepare the facts as a clean text summary
    facts_text = json.dumps(facts, indent=2, default=str)

    # Truncate if too long (stay within token limits)
    if len(facts_text) > 30000:
        facts_text = facts_text[:30000] + "\n... (truncated)"

    messages = [
        {"role": "user", "content": f"Here are the raw database facts:\n\n{facts_text}"}
    ]

    try:
        response = call_model(
            model_doc=model_doc,
            messages=messages,
            system_prompt=_DISCOVERY_PROMPT,
            tools=None,
            stream=False,
        )

        if not response:
            frappe.log_error(
                title="AskERP Context Discovery",
                message="AI model returned empty response during context discovery."
            )
            return None

        # Extract text from response
        raw_text = ""
        for block in response.get("content", []):
            if block.get("type") == "text":
                raw_text += block.get("text", "")

        # Parse JSON from the response
        raw_text = raw_text.strip()
        # Remove any markdown code fence if the model wraps it
        if raw_text.startswith("```"):
            # Strip opening ```json or ```
            first_newline = raw_text.index("\n")
            raw_text = raw_text[first_newline + 1:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        result = json.loads(raw_text)
        return result

    except json.JSONDecodeError as e:
        frappe.log_error(
            title="AskERP Context Discovery: JSON parse error",
            message=f"Could not parse AI response as JSON.\nError: {str(e)}\nResponse: {raw_text[:1000]}"
        )
        return None
    except Exception as e:
        frappe.log_error(
            title="AskERP Context Discovery: AI call error",
            message=f"Error calling AI model: {str(e)[:500]}"
        )
        return None


# ─── Profile Updater ─────────────────────────────────────────────────────────

# Map of AI response keys → AskERP Business Profile field names
_FIELD_MAP = {
    "industry_detail": "industry_detail",
    "what_you_sell": "what_you_sell",
    "what_you_buy": "what_you_buy",
    "sales_channels": "sales_channels",
    "customer_types": "customer_types",
    "key_metrics_sales": "key_metrics_sales",
    "manufacturing_detail": "manufacturing_detail",
    "key_metrics_production": "key_metrics_production",
    "accounting_focus": "accounting_focus",
    "custom_terminology": "custom_terminology",
    "custom_doctypes_info": "custom_doctypes_info",
    "executive_focus": "executive_focus",
    "industry_benchmarks": "industry_benchmarks",
    "approval_workflows": "approval_workflows",
}


def _update_business_profile(ai_result, overwrite=False):
    """
    Update AskERP Business Profile singleton with AI-generated context.

    Args:
        ai_result: Dict from _analyze_with_ai()
        overwrite: If False, only fill empty fields. If True, overwrite all.
    """
    if not ai_result:
        return False

    try:
        profile = frappe.get_single("AskERP Business Profile")
    except Exception:
        frappe.log_error(
            title="AskERP Context Discovery",
            message="AskERP Business Profile doctype not found. Run the setup wizard first."
        )
        return False

    fields_updated = 0
    for ai_key, profile_field in _FIELD_MAP.items():
        value = ai_result.get(ai_key, "")
        if not value:
            continue

        current_value = getattr(profile, profile_field, "") or ""

        if overwrite or not current_value.strip():
            setattr(profile, profile_field, value)
            fields_updated += 1

    # Special handling: if manufacturing_detail was populated, enable the check
    if ai_result.get("manufacturing_detail"):
        if not profile.has_manufacturing:
            profile.has_manufacturing = 1
            fields_updated += 1

    # Special handling: detect multi-company from facts
    if len(ai_result.get("companies_detail", "")) > 0:
        if not profile.multi_company_enabled:
            profile.multi_company_enabled = 1
            profile.companies_detail = ai_result["companies_detail"]
            fields_updated += 1

    if fields_updated > 0:
        profile.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.logger("askerp").info(
            f"Context Discovery: Updated {fields_updated} fields in Business Profile"
        )

    return fields_updated > 0


# ─── Data Model Updater ──────────────────────────────────────────────────────

def _update_discovered_data_model(data_model_text):
    """
    Store the auto-generated data model text in the Business Profile.

    This is ALWAYS written on every discovery run because it's machine-generated
    (not user content). The `discovered_data_model` field is a Long Text that the
    AI reads at prompt-build time instead of a hardcoded data model.

    Also updates `last_schema_discovery` timestamp.
    """
    try:
        profile = frappe.get_single("AskERP Business Profile")
    except Exception:
        frappe.log_error(
            title="AskERP Context Discovery",
            message="Cannot update discovered_data_model: AskERP Business Profile not found."
        )
        return False

    profile.discovered_data_model = data_model_text
    profile.last_schema_discovery = frappe.utils.now_datetime()
    profile.save(ignore_permissions=True)
    frappe.db.commit()

    # Clear the cached profile so next prompt-build picks up the new data model
    frappe.cache().delete_value("askerp_business_profile")

    frappe.logger("askerp").info(
        f"Discovered data model stored ({len(data_model_text)} chars, "
        f"{data_model_text.count(chr(10))} lines)"
    )
    return True


# ─── Public API ──────────────────────────────────────────────────────────────

def run_context_discovery(overwrite=False):
    """
    Run the full context discovery pipeline:
    1. Scan ERPNext schema and data patterns
    2. Scan field-level structure of active doctypes
    3. Generate AI-ready data model text from live schema
    4. Analyze business context with AI model
    5. Update Business Profile with generated context + data model

    The discovered_data_model field is ALWAYS refreshed (it's auto-generated).
    User-provided fields (industry_detail, what_you_sell, etc.) respect overwrite flag.

    Args:
        overwrite: If True, overwrite existing user-provided fields.
                   If False (default), only fill empty user fields.
                   NOTE: discovered_data_model is always refreshed regardless.

    Returns: dict with status info
    """
    frappe.logger("askerp").info("Starting Auto Business Context Discovery...")

    # Step 1: Scan basic facts (record counts, companies, etc.)
    facts = _scan_erpnext_schema()
    fact_summary = {
        "companies": len(facts.get("companies", [])),
        "total_records": sum(facts.get("record_counts", {}).values()),
        "custom_doctypes": len(facts.get("custom_doctypes", [])),
        "warehouses": len(facts.get("warehouses", [])),
        "pos_profiles": len(facts.get("pos_profiles", [])),
    }
    frappe.logger("askerp").info(f"Schema scan complete: {json.dumps(fact_summary)}")

    # Step 2: Scan field-level structure of all active doctypes
    active_schemas = _scan_active_doctypes()
    fact_summary["active_doctypes_scanned"] = len(active_schemas)
    frappe.logger("askerp").info(f"Field-level scan: {len(active_schemas)} active doctypes discovered")

    # Step 3: Generate AI-ready data model text (NO AI call needed — pure schema)
    data_model_text = _generate_data_model_text(active_schemas, facts)

    # Step 4: Store the discovered data model in Business Profile
    # This is ALWAYS written (it's machine-generated, not user content)
    _update_discovered_data_model(data_model_text)

    # Step 5: Analyze business context with AI (fills user-facing fields)
    ai_result = _analyze_with_ai(facts)
    if not ai_result:
        return {
            "status": "partial",
            "message": "Data model updated, but AI analysis failed. Check Error Log.",
            "facts_scanned": fact_summary,
            "data_model_generated": True,
        }

    # Step 6: Update user-facing Business Profile fields
    updated = _update_business_profile(ai_result, overwrite=overwrite)

    status = "updated" if updated else "data_model_only"
    msg = (f"Data model refreshed ({len(active_schemas)} doctypes). "
           f"Business Profile {'updated' if updated else 'unchanged (user fields already filled)'}.")

    frappe.logger("askerp").info(f"Context Discovery complete: {status}")

    return {
        "status": status,
        "message": msg,
        "facts_scanned": fact_summary,
        "data_model_generated": True,
        "fields_generated": list(ai_result.keys()) if ai_result else [],
    }


# ─── Scheduled Task ──────────────────────────────────────────────────────────

def scheduled_context_refresh():
    """
    Monthly scheduled task: re-scans ERPNext and refreshes business context.
    Only fills in empty fields by default (doesn't overwrite user's manual edits).

    Called by hooks.py scheduler_events → monthly.
    """
    try:
        # Only run if AskERP is set up (Business Profile exists and has a company name)
        profile = frappe.get_single("AskERP Business Profile")
        if not profile.company_name:
            return  # Not set up yet — skip

        result = run_context_discovery(overwrite=False)
        frappe.logger("askerp").info(
            f"Scheduled context refresh: {result.get('status')} — {result.get('message')}"
        )
    except Exception as e:
        frappe.log_error(
            title="AskERP Scheduled Context Refresh Error",
            message=str(e)[:500]
        )


# ─── Whitelisted API for manual trigger ───────────────────────────────────

@frappe.whitelist()
def trigger_context_discovery(overwrite="0"):
    """
    Manually trigger context discovery from the UI or API.
    Requires System Manager role.

    POST /api/method/askerp.context_discovery.trigger_context_discovery
    Body: {"overwrite": "1"}  (optional, default "0")
    """
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only System Managers can run context discovery."), frappe.PermissionError)

    ow = overwrite in ("1", "true", True, 1)

    # Run async to avoid timeout on large instances
    frappe.enqueue(
        "askerp.context_discovery.run_context_discovery",
        queue="long",
        timeout=300,
        overwrite=ow,
    )

    return {
        "status": "queued",
        "message": "Context discovery has been queued. Check the Business Profile in a few minutes.",
    }


# ─── Schema Change Auto-Trigger ──────────────────────────────────────────

# Debounce key: prevents multiple rapid discoveries when
# a bench migrate adds 20+ custom fields in quick succession.
_SCHEMA_CHANGE_DEBOUNCE_KEY = "askerp_schema_change_pending"
_SCHEMA_CHANGE_COOLDOWN = 300  # 5 minutes between auto-refreshes

def on_schema_change(doc, method=None):
    """
    Doc event handler: fires when Custom Field, DocType, or Property Setter
    is created/updated/deleted.  Queues a context discovery refresh
    with debounce — multiple rapid changes are collapsed into one refresh.

    Registered in hooks.py doc_events.
    """
    try:
        # Only run if AskERP is fully set up
        profile = frappe.get_single("AskERP Business Profile")
        if not profile.company_name:
            return

        # Check debounce — is a refresh already pending?
        pending = frappe.cache.get_value(_SCHEMA_CHANGE_DEBOUNCE_KEY)
        if pending:
            return  # Another trigger already queued a refresh recently

        # Set debounce flag (5-minute cooldown)
        frappe.cache.set_value(
            _SCHEMA_CHANGE_DEBOUNCE_KEY, "1",
            expires_in_sec=_SCHEMA_CHANGE_COOLDOWN
        )

        # Queue discovery (non-overwrite — preserves admin edits)
        frappe.enqueue(
            "askerp.context_discovery.run_context_discovery",
            queue="long",
            timeout=300,
            overwrite=False,
            # Delay 60 seconds to let batch operations finish
            # (e.g., bench migrate adds many fields rapidly)
            at_front=False,
        )

        frappe.logger("askerp").info(
            f"Schema change detected ({doc.doctype}: {doc.name}). "
            f"Context discovery queued."
        )
    except Exception:
        pass  # Schema change trigger is best-effort, never block user operations
