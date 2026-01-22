import frappe
import json
from frappe.desk.query_report import run

# @frappe.whitelist()
# def get_profit_and_loss_report():
#     filters = {
#         "company": "HEALTHCARE NETWORKS LIMITED",
#         "filter_based_on": "Fiscal Year",
#         "period_start_date": "2025-01-01",
#         "period_end_date": "2026-12-31",
#         "from_fiscal_year": "2025",
#         "to_fiscal_year": "2026",
#         "periodicity": "Yearly",
#         "cost_center": [],
#         "project": [],
#         "selected_view": "Report",
#         "include_default_book_entries": 1,
        
#     }

#     result = run(
#         report_name="Profit and Loss Statement",
#         filters=json.dumps(filters),
#         ignore_prepared_report=False,
#         is_tree=True,
#         parent_field="parent_account",
#         are_default_filters=False
#     )

#     return result


@frappe.whitelist()
def get_profit_and_loss_report(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)

    result = run(
    report_name="Profit and Loss Statement",
    filters=filters,   # ← PASS DICT DIRECTLY
    ignore_prepared_report=False,
    is_tree=True,
    parent_field="parent_account",
    are_default_filters=False
    )


    return result
