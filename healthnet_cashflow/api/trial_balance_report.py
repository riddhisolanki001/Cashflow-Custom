import frappe
import json
from frappe.desk.query_report import run
from erpnext.accounts.utils import get_fiscal_year

# @frappe.whitelist()
# def get_trial_balance_report():
#     filters = {
#         "company": "HEALTHCARE NETWORKS LIMITED",
#         "fiscal_year": "2025",
#         "from_date": "2025-01-01",
#         "to_date": "2025-12-31",
#         "cost_center": [],
#         "project": [],
#         "with_period_closing_entry_for_opening": 1,
#         "with_period_closing_entry_for_current_period": 1,
#         "include_default_book_entries": 1,
#         "show_net_values": 1
#     }

#     result = run(
#         report_name="Trial Balance",
#         filters=json.dumps(filters),
#         ignore_prepared_report=False,
#         is_tree=True,
#         parent_field="parent_account",
#         are_default_filters=True
#     )

#     return result



@frappe.whitelist()
def get_trial_balance_report(filters):
    filters = frappe._dict(filters)

    if filters.filter_based_on == "Fiscal Year":
        fiscal_year = filters.from_fiscal_year

    else:  # Date Range
        fy = get_fiscal_year(
            filters.period_start_date,
            company=filters.company
        )
        fiscal_year = fy[0] if isinstance(fy, (list, tuple)) else fy.get("fiscal_year")

    if not fiscal_year:
        frappe.throw("Fiscal Year is required for Trial Balance")

    # --------------------------------------------------
    # TRIAL BALANCE FILTERS
    # --------------------------------------------------
    tb_filters = {
        "company": filters.company,
        "fiscal_year": fiscal_year,
        "from_date": (
            str(filters.period_start_date)
            if filters.period_start_date else None
        ),
        "to_date": (
            str(filters.period_end_date)
            if filters.period_end_date else None
        ),
        "cost_center": filters.get("cost_center") or [],
        "project": filters.get("project") or [],
        "with_period_closing_entry_for_opening": 1,
        "with_period_closing_entry_for_current_period": 1,
        "include_default_book_entries": 1,
        "show_net_values": 1,
    }


    return run(
        report_name="Trial Balance",
        filters=json.dumps(tb_filters),
        ignore_prepared_report=False,
        is_tree=True,
        parent_field="parent_account",
        are_default_filters=True
    )

