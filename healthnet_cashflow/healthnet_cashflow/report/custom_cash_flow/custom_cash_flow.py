# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from datetime import timedelta

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import cstr, flt
from pypika import Order

from erpnext.accounts.report.financial_statements import (
    get_columns,
    get_cost_centers_with_children,
    get_data,
    get_filtered_list_for_consolidated_report,
    get_period_list,
    set_gl_entries_by_account,
)
from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
    get_net_profit_loss,
)
from erpnext.accounts.utils import get_fiscal_year
from healthnet_cashflow.api.profit_and_loss_report import get_profit_and_loss_report
from healthnet_cashflow.api.trial_balance_report import get_trial_balance_report


def build_cashflow_single_value_row(
    label,
    value,
    period_list,
    parent_section,
    currency,
    indent=1,
    include_in_op_total=True,
    include_in_net_cash=False,
):
    row = {
        "section_name": _(label),
        "section": _(label),
        "indent": indent,
        "parent_section": parent_section,
        "currency": currency,
        "include_in_op_total": include_in_op_total,
        "include_in_net_cash": include_in_net_cash,
        "total": value,
    }

    for period in period_list:
        row[period["key"]] = value

    return row



def get_tb_diff_by_label(label, filters):
    from erpnext.accounts.report.trial_balance import trial_balance
    from frappe.utils import flt
    import frappe

    tb_filters = frappe._dict({
        "company": filters.company,
        "fiscal_year": filters.from_fiscal_year,
        "from_date": filters.period_start_date,
        "to_date": filters.period_end_date,
        "show_net_values": 1,
        "with_period_closing_entry_for_opening": 1,
        "with_period_closing_entry_for_current_period": 1,
        "include_default_book_entries": 1,
    })

    columns, rows = trial_balance.execute(tb_filters)

    frappe.log_error(
        title="TB DEBUG ROW COUNT",
        message=f"Rows returned: {len(rows) if rows else 0}"
    )

    for row in rows or []:
        if not isinstance(row, dict):
            continue

        account_label = row.get("account_name", "")

        # LABEL MATCH (case-insensitive)
        if label.lower() in account_label.lower():
            opening_dr = flt(row.get("opening_debit", 0))
            closing_dr = flt(row.get("closing_debit", 0))
            opening_cr = flt(row.get("opening_credit", 0))
            closing_cr = flt(row.get("closing_credit", 0))

            difference = (((closing_dr - opening_dr) * -1) + (closing_cr - opening_cr))

            frappe.log_error(
                title="TB LABEL MATCH FOUND",
                message=f"{account_label} => Opening Dr = {opening_dr}, Closing Dr = {closing_dr}, Difference = {difference}"
            )

            return difference

    frappe.log_error(
        title="TB LABEL NOT FOUND",
        message=label
    )

    return 0


def get_withholding_tax_total(filters):
    from erpnext.accounts.report.trial_balance import trial_balance
    from frappe.utils import flt
    import frappe

    # Labels to match
    labels = ["WITHHOLDING TAX 7.5%", "WITHHOLDING TAX 3%"]

    tb_filters = frappe._dict({
        "company": filters.company,
        "fiscal_year": filters.from_fiscal_year,
        "from_date": filters.period_start_date,
        "to_date": filters.period_end_date,
        "show_zero_values": 1,
        "show_net_values": 1,
    })

    columns, rows = trial_balance.execute(tb_filters)

    frappe.log_error(
        title="TB DEBUG ROW COUNT",
        message=f"Rows returned: {len(rows) if rows else 0}"
    )

    total_difference = 0

    for label in labels:
        found = False
        for row in rows or []:
            if not isinstance(row, dict):
                continue

            account_label = row.get("account_name", "")

            # LABEL MATCH (case-insensitive)
            if label.lower() in account_label.lower():
                opening_cr = flt(row.get("opening_credit", 0))
                closing_cr = flt(row.get("closing_credit", 0))
                opening_dr = flt(row.get("opening_debit", 0))
                closing_dr = flt(row.get("closing_debit", 0))

                difference = (((closing_cr - opening_cr)) + (closing_dr - opening_dr) * -1)
                total_difference += difference
                found = True

                frappe.log_error(
                    title=f"TB WITHHOLDING TAX MATCH FOUND: {label}",
                    message=f"{account_label} => Opening Cr = {opening_cr}, Closing Cr = {closing_cr}, Difference = {difference}"
                )
                break  # stop searching for this label

        if not found:
            frappe.log_error(
                title=f"TB WITHHOLDING TAX NOT FOUND: {label}",
                message=f"{label} not found in Trial Balance"
            )

    frappe.log_error(
        title="TB WITHHOLDING TAX TOTAL",
        message=f"Total Difference (7.5% + 3%) = {total_difference}"
    )

    return total_difference



def execute(filters=None):
    if not filters:
        frappe.throw(_("Filters are required"))

    filters = frappe._dict(filters)

    validate_and_prepare_filters(filters)
    period_list = get_period_list(
        filters.from_fiscal_year,
        filters.to_fiscal_year,
        filters.period_start_date,
        filters.period_end_date,
        filters.filter_based_on,
        filters.periodicity,
        company=filters.company,
    )

    cash_flow_sections = get_cash_flow_accounts()

    # compute net profit / loss
    income = get_data(
        filters.company,
        "Income",
        "Credit",
        period_list,
        filters=filters,
        accumulated_values=filters.accumulated_values,
        ignore_closing_entries=True,
        ignore_accumulated_values_for_fy=True,
    )
    expense = get_data(
        filters.company,
        "Expense",
        "Debit",
        period_list,
        filters=filters,
        accumulated_values=filters.accumulated_values,
        ignore_closing_entries=True,
        ignore_accumulated_values_for_fy=True,
    )

    net_profit_loss = get_net_profit_loss(income, expense, period_list, filters.company)
    print(net_profit_loss)

    data = []
    summary_data = {}
    company_currency = frappe.get_cached_value("Company", filters.company, "default_currency")

    for cash_flow_section in cash_flow_sections:
        section_data = []
        header_row = {
            "section_name": "'" + cash_flow_section["section_header"] + "'",
            "parent_section": None,
            "indent": 0,
            "section": cash_flow_section["section_header"],
            "currency": None,
        }

        # Remove numeric values for all periods
        for period in period_list:
            header_row[period["key"]] = None

        header_row["total"] = None

        data.append(header_row)

        if len(data) == 1:
            # add first net income in operations section
            if net_profit_loss:
                net_profit_loss["account_name"] = "'Net Profit After Tax'"
                net_profit_loss["section"] = "Net Profit After Tax"

                net_profit_loss.update(
                    {
                        "indent": 1,
                        "parent_section": cash_flow_sections[0]["section_header"],
                    }
                )
            
                data.append(net_profit_loss)
                section_data.append(net_profit_loss)

        for row in cash_flow_section["account_types"]:
            # ---------------- PPE MOVEMENTS (TB BASED) ----------------
            if row["label"] == _("Purchase of PPE"):
                row_data = get_ppe_movement_from_tb(
                    period_list,
                    filters,
                    movement_type="purchase"
                )

            elif row["label"] == _("Proceeds from Asset Disposal"):
                row_data = get_ppe_movement_from_tb(
                    period_list,
                    filters,
                    movement_type="disposal"
                )

            # ---------------- INTEREST ----------------
            elif row["label"] == _("Interest Expense"):
                row_data = get_interest_expense_from_pl(period_list, filters)

            elif row["label"] == _("Interest Paid"):
                row_data = get_interest_expense_from_pl(period_list, filters)
                
            # ---------------- STATIC ZERO ----------------
            elif row["label"] == _("Borrowings/Equity Movements"):
                row_data = {p["key"]: 0 for p in period_list}
                row_data["total"] = 0    

            # ---------------- WORKING CAPITAL ----------------
            elif row["label"] == _("Change in Trade Receivables"):
                row_data = get_working_capital_change_from_tb(
                    "Accounts Receivable", period_list, filters
                )

            elif row["label"] == _("Change in Inventory"):
                row_data = get_working_capital_change_from_tb(
                    "INVENTORY", period_list, filters
                )

            elif row["label"] == _("Change in Trade Payables"):
                row_data = get_working_capital_change_from_tb(
                    "Accounts Payable", period_list, filters
                )

            elif row["label"] == _("Loans and Advances (Assets)"):
                loans_total = get_tb_diff_by_label("Loans and Advances (Assets)", filters) or 0
                row_data = build_cashflow_single_value_row(
                    label="Loans and Advances (Assets)",
                    value=loans_total,
                    period_list=period_list,
                    parent_section=cash_flow_sections[0]["section_header"],
                    currency=company_currency,
                    indent=1
                )

            elif row["label"] == _("Prepayment"):
                prepayment_total = get_tb_diff_by_label("PREPAYMENT", filters) or 0
                row_data = build_cashflow_single_value_row(
                    label="Prepayment",
                    value=prepayment_total,
                    period_list=period_list,
                    parent_section=cash_flow_sections[0]["section_header"],
                    currency=company_currency,
                    indent=1
                )

            elif row["label"] == _("Tax Assets"):
                tax_assets_total = get_tb_diff_by_label("Tax Assets", filters) or 0
                row_data = build_cashflow_single_value_row(
                    label="Tax Assets",
                    value=tax_assets_total,
                    period_list=period_list,
                    parent_section=cash_flow_sections[0]["section_header"],
                    currency=company_currency,
                    indent=1
                )

            elif row["label"] == _("Investment"):
                investment_total = get_tb_diff_by_label("Investment", filters) or 0
                row_data = build_cashflow_single_value_row(
                    label="Investment",
                    value=investment_total,
                    period_list=period_list,
                    parent_section=cash_flow_sections[0]["section_header"],
                    currency=company_currency,
                    indent=1
                )


            elif row["label"] == _("Withholding Tax"):
                row_data = build_cashflow_single_value_row(
                    label="Withholding Tax",
                    value=get_withholding_tax_total(filters),
                    period_list=period_list,
                    parent_section=cash_flow_sections[0]["section_header"],
                    currency=company_currency,
                    indent=1
                )
                


            # ---------------- DEFAULT (ACCOUNT TYPE BASED) ----------------
            else:
                row_data = get_account_type_based_data(
                    filters.company,
                    row["account_type"],
                    period_list,
                    filters.accumulated_values,
                    filters
                )


            accounts = frappe.get_all(
                "Account",
                filters={
                    "account_type": row["account_type"],
                    "is_group": 0,
                },
                pluck="name",
            )
            row_data.update(
                {
                    "section_name": row["label"],
                    "section": row["label"],
                    "indent": 1,
                    "accounts": accounts,
                    "parent_section": cash_flow_section["section_header"],
                    "currency": company_currency,
                    "include_in_op_total": row["label"] in (
                        _("Change in Trade Receivables"),
                        _("Change in Inventory"),
                        _("Change in Trade Payables"),
                        _("Loans and Advances (Assets)"),
                        _("Prepayment"),
                        _("Tax Assets"),
                        _("Investment"),
                        _("Withholding Tax"),
                    ),
                    "include_in_net_cash": row["label"] in (
                        _("Interest Paid"),
                        _("Borrowings/Equity Movements"),
                    ),
                }
            )
            data.append(row_data)
            section_data.append(row_data)

        
        if cash_flow_section["section_name"] == "Operations":
            op_profit = {
                "section_name": _("Operating Profit before Working Capital Changes"),
                "section": _("Operating Profit before Working Capital Changes"),
                "indent": 1,
                "parent_section": cash_flow_section["section_header"],
                "currency": company_currency,
                "total": 0,
                "include_in_op_total": True,
            }

            for period in period_list:
                key = period["key"]
                value = 0

                for row in section_data:
                    row_name = (row.get("section") or "").replace("'", "")

                    if row_name in (
                        "Net Profit After Tax",
                        "Depreciation & Amortisation",
                        "Interest Expense",
                    ):
                        value += row.get(key, 0)

                op_profit[key] = value
                op_profit["total"] += value

            # Insert AFTER Interest Expense
            insert_after_label = "Interest Expense"

            # Find index in section_data
            insert_index = None
            for idx, row in enumerate(section_data):
                if row.get("section", "").replace("'", "") == insert_after_label:
                    insert_index = idx + 1
                    break

            # Fallback (should not happen)
            if insert_index is None:
                insert_index = len(section_data)

            # Insert in section_data
            section_data.insert(insert_index, op_profit)

            # Insert in main data list (same relative position)
            data_index = None
            for idx, row in enumerate(data):
                if row.get("section", "").replace("'", "") == insert_after_label:
                    data_index = idx + 1
                    break

            if data_index is None:
                data.append(op_profit)
            else:
                data.insert(data_index, op_profit)


        add_total_row_account(
            data,
            section_data,
            cash_flow_section["section_footer"],
            period_list,
            company_currency,
            summary_data,
            filters,
        )
        

    net_cash_row = {
    "section_name": "'Net increase in cash and cash equivalents'",
    "section": "'Net increase in cash and cash equivalents'",
    "currency": company_currency,
    }

    for period in period_list:
        key = period["key"]
        value = 0

        for row in data:
            row_name = (row.get("section") or "").replace("'", "")

            if row_name in (
                "Net Cash from Operating Activities",
                "Net Cash used Investing Activities",
                "Net Cash from Financing Activities",
            ):
                value += row.get(key, 0)

        net_cash_row[key] = value
        summary_data["Net increase in cash and cash equivalents"] = (
            summary_data.get("Net increase in cash and cash equivalents", 0) + value
        )

    net_cash_row["total"] = sum(net_cash_row.get(p["key"], 0) for p in period_list)

    data.append(net_cash_row)
    data.append({})

    opening_row = get_cash_and_bank_balance(period_list, filters, "opening")
    opening_row.update({
        "section_name": "'Opening Cash and Bank Balance'",
        "section": "'Opening Cash and Bank Balance'",
        "currency": company_currency,
    })
    data.append(opening_row)
    data.append({})

    # --------------------------------
    # Closing Cash and Bank Balance
    # --------------------------------
    closing_row = {
    "section_name": "'Closing Cash and Bank Balance'",
    "section": "'Closing Cash and Bank Balance'",
    "currency": company_currency,
    }

    total = 0

    for period in period_list:
        key = period["key"]

        opening = opening_row.get(key, 0)
        net_change = net_cash_row.get(key, 0)

        value = opening + net_change
        closing_row[key] = value
        total += value

    closing_row["total"] = total

    data.append(closing_row)
    data.append({})

    
    columns = get_columns(
        filters.periodicity,
        period_list,
        filters.accumulated_values,
        filters.company,
        True,
    )

    chart = get_chart_data(columns, data, company_currency)

    report_summary = get_report_summary(summary_data, company_currency)

    return columns, data, None, chart, report_summary


def get_cash_flow_accounts():
    operation_accounts = {
        "section_name": "Operations",
        "section_footer": _("Net Cash from Operating Activities"),
        "section_header": _("Cash Flow from Operating Act"),
        "account_types": [
            {"account_type": "Depreciation", "label": _("Depreciation & Amortisation")},
            {"account_type": "Depreciation", "label": _("Interest Expense")},
            # {"account_type": "Depreciation", "label": _("Operating Profit before Working Capital Changes")},
            {"account_type": "Receivable", "label": _("Change in Trade Receivables")},
            {"account_type": "Stock", "label": _("Change in Inventory")},
            {"account_type": "Payable", "label": _("Change in Trade Payables")},

            {"account_type": "Other", "label": _("Loans and Advances (Assets)")},
            {"account_type": "Other", "label": _("Prepayment")},
            {"account_type": "Other", "label": _("Tax Assets")},
            {"account_type": "Other", "label": _("Investment")},
            {"account_type": "Other", "label": _("Withholding Tax")},
        ],
    }

    investing_accounts = {
        "section_name": "Investing",
        "section_footer": _("Net Cash used Investing Activities"),
        "section_header": _("Cash Flows From Investing Activities"),
        "account_types": [
            {"account_type": "Fixed Asset", "label": _("Purchase of PPE")},
            {"account_type": "Fixed Asset", "label": _("Proceeds from Asset Disposal")},
            
   ],
    }

    financing_accounts = {
        "section_name": "Financing",
        "section_footer": _("Net Cash from Financing Activities"),
        "section_header": _("Cash Flow from Financing Activities"),
        "account_types": [
              {"account_type": "Equity", "label": _("Interest Paid")},
            {"account_type": "Equity", "label": _("Borrowings/Equity Movements")},
         ],
    }

    # combine all cash flow accounts for iteration
    return [operation_accounts, investing_accounts, financing_accounts]


def get_account_type_based_data(company, account_type, period_list, accumulated_values, filters):
    data = {}
    total = 0
    for period in period_list:
        start_date = get_start_date(period, accumulated_values, company)
        filters.start_date = start_date
        filters.end_date = period["to_date"]
        filters.account_type = account_type

        amount = get_account_type_based_gl_data(company, filters)

        if amount and account_type == "Depreciation":
            amount *= -1

        total += amount
        data.setdefault(period["key"], amount)

    data["total"] = total
    return data


def get_account_type_based_gl_data(company, filters=None):
    cond = ""
    filters = frappe._dict(filters or {})

    if filters.include_default_book_entries:
        company_fb = frappe.get_cached_value("Company", company, "default_finance_book")
        cond = """ AND (finance_book in ({}, {}, '') OR finance_book IS NULL)
            """.format(
            frappe.db.escape(filters.finance_book),
            frappe.db.escape(company_fb),
        )
    else:
        cond = " AND (finance_book in (%s, '') OR finance_book IS NULL)" % (
            frappe.db.escape(cstr(filters.finance_book))
        )

    if filters.get("cost_center"):
        filters.cost_center = get_cost_centers_with_children(filters.cost_center)
        cond += " and cost_center in %(cost_center)s"

    gl_sum = frappe.db.sql_list(
        f"""
        select sum(credit) - sum(debit)
        from `tabGL Entry`
        where company=%(company)s and posting_date >= %(start_date)s and posting_date <= %(end_date)s
            and voucher_type != 'Period Closing Voucher'
            and account in ( SELECT name FROM tabAccount WHERE account_type = %(account_type)s) {cond}
    """,
        filters,
    )

    return gl_sum[0] if gl_sum and gl_sum[0] else 0


def get_start_date(period, accumulated_values, company):
    if not accumulated_values and period.get("from_date"):
        return period["from_date"]

    start_date = period["year_start_date"]
    if accumulated_values:
        start_date = get_fiscal_year(period.to_date, company=company)[1]

    return start_date


def add_total_row_account(out, data, label, period_list, currency, summary_data, filters, consolidated=False):
    total_row = {
        "section_name": "'" + _("{0}").format(label) + "'",
        "section": "'" + _("{0}").format(label) + "'",
        "currency": currency,
        "is_section_total": True,
    }

    summary_data[label] = 0

    # from consolidated financial statement
    if filters.get("accumulated_in_group_company"):
        period_list = get_filtered_list_for_consolidated_report(filters, period_list)

    for row in data:
        if label == _("Net Cash from Operating Activities"):
            if not row.get("include_in_op_total"):
                continue
        else:
            if not row.get("parent_section"):
                continue
        if row.get("parent_section"):
            for period in period_list:
                key = period if consolidated else period["key"]
                total_row.setdefault(key, 0.0)
                total_row[key] += row.get(key, 0.0)
                summary_data[label] += row.get(key)

            total_row.setdefault("total", 0.0)
            total_row["total"] += row["total"]

    out.append(total_row)
    out.append({})

    return total_row


def show_opening_and_closing_balance(out, period_list, currency, net_change_in_cash, filters):
    opening_balance = {
        "section_name": "Opening",
        "section": "Opening",
        "currency": currency,
    }
    closing_balance = {
        "section_name": "Closing (Opening + Total)",
        "section": "Closing (Opening + Total)",
        "currency": currency,
    }

    opening_amount = get_opening_balance(filters.company, period_list, filters) or 0.0
    running_total = opening_amount

    for i, period in enumerate(period_list):
        key = period["key"]
        change = net_change_in_cash.get(key, 0.0)

        opening_balance[key] = opening_amount if i == 0 else running_total
        running_total += change
        closing_balance[key] = running_total

    opening_balance["total"] = opening_balance[period_list[0]["key"]]
    closing_balance["total"] = closing_balance[period_list[-1]["key"]]

    out.extend([opening_balance, net_change_in_cash, closing_balance, {}])


def get_opening_balance(company, period_list, filters):
    from copy import deepcopy

    cash_value = {}
    account_types = get_cash_flow_accounts()
    net_profit_loss = 0.0

    local_filters = deepcopy(filters)
    local_filters.start_date, local_filters.end_date = get_opening_range_using_fiscal_year(
        company, period_list
    )

    for section in account_types:
        section_name = section.get("section_name")
        cash_value.setdefault(section_name, 0.0)

        if section_name == "Operations":
            net_profit_loss += get_net_income(company, period_list, local_filters)

        for account in section.get("account_types", []):
            account_type = account.get("account_type")
            local_filters.account_type = account_type

            amount = get_account_type_based_gl_data(company, local_filters) or 0.0

            if account_type == "Depreciation":
                cash_value[section_name] += amount * -1
            else:
                cash_value[section_name] += amount

    return sum(cash_value.values()) + net_profit_loss


def get_net_income(company, period_list, filters):
    gl_entries_by_account_for_income, gl_entries_by_account_for_expense = {}, {}
    income, expense = 0.0, 0.0
    from_date, to_date = get_opening_range_using_fiscal_year(company, period_list)

    for root_type in ["Income", "Expense"]:
        for root in frappe.db.sql(
            """select lft, rgt from tabAccount
                where root_type=%s and ifnull(parent_account, '') = ''""",
            root_type,
            as_dict=1,
        ):
            set_gl_entries_by_account(
                company,
                from_date,
                to_date,
                filters,
                gl_entries_by_account_for_income
                if root_type == "Income"
                else gl_entries_by_account_for_expense,
                root.lft,
                root.rgt,
                root_type=root_type,
                ignore_closing_entries=True,
            )

    for entries in gl_entries_by_account_for_income.values():
        for entry in entries:
            if entry.posting_date <= to_date:
                amount = (entry.debit - entry.credit) * -1
                income = flt((income + amount), 2)

    for entries in gl_entries_by_account_for_expense.values():
        for entry in entries:
            if entry.posting_date <= to_date:
                amount = entry.debit - entry.credit
                expense = flt((expense + amount), 2)

    return income - expense


def get_opening_range_using_fiscal_year(company, period_list):
    first_from_date = period_list[0]["from_date"]
    previous_day = first_from_date - timedelta(days=1)

    # Get the earliest fiscal year for the company

    FiscalYear = DocType("Fiscal Year")
    FiscalYearCompany = DocType("Fiscal Year Company")

    earliest_fy = (
        frappe.qb.from_(FiscalYear)
        .join(FiscalYearCompany)
        .on(FiscalYearCompany.parent == FiscalYear.name)
        .select(FiscalYear.year_start_date)
        .where(FiscalYearCompany.company == company)
        .orderby(FiscalYear.year_start_date, order=Order.asc)
        .limit(1)
    ).run(as_dict=True)

    if not earliest_fy:
        frappe.throw(_("Not able to find the earliest Fiscal Year for the given company."))

    company_start_date = earliest_fy[0]["year_start_date"]
    return company_start_date, previous_day


def get_report_summary(summary_data, currency):
    report_summary = []

    for label, value in summary_data.items():
        report_summary.append({"value": value, "label": label, "datatype": "Currency", "currency": currency})

    return report_summary


def get_chart_data(columns, data, currency):
    labels = [d.get("label") for d in columns[2:]]
    print(data)
    datasets = [
        {
            "name": section.get("section").replace("'", ""),
            "values": [section.get(d.get("fieldname")) for d in columns[2:]],
        }
        for section in data
        if section.get("parent_section") is None and section.get("currency")
    ]
    datasets = datasets[:-2]

    chart = {"data": {"labels": labels, "datasets": datasets}, "type": "bar"}

    chart["fieldtype"] = "Currency"
    chart["options"] = "currency"
    chart["currency"] = currency

    return chart


def get_interest_expense_from_pl(period_list, filters):
    pl_filters = {
        "company": filters.company,
        "filter_based_on": "Fiscal Year",
        "period_start_date": filters.period_start_date,
        "period_end_date": filters.period_end_date,
        "from_fiscal_year": filters.from_fiscal_year,
        "to_fiscal_year": filters.to_fiscal_year,
        "periodicity": filters.periodicity,
        "cost_center": filters.cost_center or [],
        "project": filters.project or [],
        "include_default_book_entries": 1,
        "accumulated_values": 1
    }

    pl_result = get_profit_and_loss_report(pl_filters)

    rows = pl_result.get("result", [])

    interest_data = {}
    total = 0

    for period in period_list:
        interest_data[period["key"]] = 0

    for row in rows:
        parent = (row.get("parent_account") or "").upper()
        name = (row.get("account_name") or "").upper()

        if "FINANCE COST" in parent and "INTEREST" in name:
            for period in period_list:
                key = period["key"]
                value = row.get(key, 0) or 0
                interest_data[key] += value
                total += value

    interest_data["total"] = total
    return interest_data

def get_working_capital_change_from_tb(account_name, period_list, filters):

    tb_filters = {
        "company": filters.company,
        "from_date": filters.period_start_date,
        "to_date": filters.period_end_date,
        "fiscal_year": filters.from_fiscal_year,
        "cost_center": filters.cost_center or [],
        "project": filters.project or [],
        "include_default_book_entries": 1,
        "show_net_values": 1,
        "with_period_closing_entry_for_opening": 1,
        "with_period_closing_entry_for_current_period": 1,
    }

    tb_filters.update({
        "filter_based_on": filters.filter_based_on,
        "from_fiscal_year": filters.get("from_fiscal_year"),
        "to_fiscal_year": filters.get("to_fiscal_year"),
        "period_start_date": filters.get("period_start_date"),
        "period_end_date": filters.get("period_end_date"),
    })

    tb_result = get_trial_balance_report(tb_filters)
    rows = tb_result.get("result", [])

    data = {}
    total = 0

    for period in period_list:
        data[period["key"]] = 0

    for row in rows:
        if row.get("account_name") != account_name:
            continue

        opening = 0
        closing = 0

        # ASSETS → debit
        if account_name in ["Accounts Receivable", "INVENTORY"]:
            opening = row.get("opening_debit", 0)
            closing = row.get("closing_debit", 0)
            value = opening - closing

        # # LIABILITIES → credit
        elif account_name == "Accounts Payable":
            opening = row.get("opening_credit", 0)
            closing = row.get("closing_credit", 0)
            value = (opening - closing) * -1

        for period in period_list:
            key = period["key"]
            data[key] = value
            total += value

    data["total"] = total
    return data


def validate_and_prepare_filters(filters):
    if not filters.filter_based_on:
        frappe.throw(_("Please select Filter Based On"))

    # --------------------------------
    # FILTER BASED ON → FISCAL YEAR
    # --------------------------------
    if filters.filter_based_on == "Fiscal Year":
        if not filters.from_fiscal_year or not filters.to_fiscal_year:
            frappe.throw(_("Please select From Fiscal Year and To Fiscal Year"))

        if filters.from_fiscal_year != filters.to_fiscal_year:
            frappe.throw(_("From Fiscal Year and To Fiscal Year must be the same"))

        fy_name, fy_start, fy_end = get_fiscal_year(
            filters.from_fiscal_year,
            company=filters.company
        )

        filters.period_start_date = fy_start
        filters.period_end_date = fy_end

    # --------------------------------
    # FILTER BASED ON → DATE RANGE
    # --------------------------------
    elif filters.filter_based_on == "Date Range":
        if not filters.period_start_date or not filters.period_end_date:
            frappe.throw(_("Please select Start Date and End Date"))

        if filters.period_start_date > filters.period_end_date:
            frappe.throw(_("Start Date cannot be greater than End Date"))

        fy1_name, fy1_start, fy1_end = get_fiscal_year(
            filters.period_start_date,
            company=filters.company
        )

        fy2_name, fy2_start, fy2_end = get_fiscal_year(
            filters.period_end_date,
            company=filters.company
        )

        if fy1_name != fy2_name:
            frappe.throw(
                _("Start Date and End Date must belong to the same Fiscal Year")
            )

        # Auto-assign fiscal year
        filters.from_fiscal_year = fy1_name
        filters.to_fiscal_year = fy1_name

    else:
        frappe.throw(_("Invalid Filter Based On selection"))


def get_cash_and_bank_balance(period_list, filters, balance_type):
    """
    balance_type: 'opening' or 'closing'
    """    
    tb_filters = {
        "company": filters.company,
        "from_date": filters.period_start_date,
        "to_date": filters.period_end_date,
        "fiscal_year": filters.from_fiscal_year,
        "cost_center": filters.cost_center or [],
        "project": filters.project or [],
        "include_default_book_entries": 1,
        "show_net_values": 1,
        "with_period_closing_entry_for_opening": 1,
        "with_period_closing_entry_for_current_period": 1,
    }

    tb_filters.update({
        "filter_based_on": filters.filter_based_on,
        "from_fiscal_year": filters.get("from_fiscal_year"),
        "to_fiscal_year": filters.get("to_fiscal_year"),
        "period_start_date": filters.get("period_start_date"),
        "period_end_date": filters.get("period_end_date"),
    })
    tb_result = get_trial_balance_report(tb_filters)
    rows = tb_result.get("result", [])

    data = {}
    total = 0

    for period in period_list:
        data[period["key"]] = 0

    for row in rows:
        if row.get("account_name") not in ("Bank Accounts", "Cash In Hand"):
            continue

        if balance_type == "opening":
            value = row.get("opening_debit", 0)

        else:
            value = row.get("closing_credit", 0)

        for period in period_list:
            data[period["key"]] += value
            total += value
            
    data["total"] = total
    return data


def get_ppe_movement_from_tb(period_list, filters, movement_type):
    """
    movement_type:
        - 'purchase'  → debit based
        - 'disposal'  → credit based
    """

    tb_filters = {
        "company": filters.company,
        "from_date": filters.period_start_date,
        "to_date": filters.period_end_date,
        "fiscal_year": filters.from_fiscal_year,
        "cost_center": filters.cost_center or [],
        "project": filters.project or [],
        "include_default_book_entries": 1,
        "show_net_values": 0,
        "with_period_closing_entry_for_opening": 1,
        "with_period_closing_entry_for_current_period": 1,
    }

    tb_filters.update({
        "filter_based_on": filters.filter_based_on,
        "from_fiscal_year": filters.from_fiscal_year,
        "to_fiscal_year": filters.to_fiscal_year,
        "period_start_date": filters.period_start_date,
        "period_end_date": filters.period_end_date,
    })

    tb_result = get_trial_balance_report(tb_filters)
    rows = tb_result.get("result", [])

    data = {p["key"]: 0 for p in period_list}
    total = 0

    ppe_row = None
    dep_row = None

    for row in rows:
        if row.get("account_name") == "PROPERTY, PLANT & EQUIPMENT AIRPORT":
            ppe_row = row
        elif row.get("account_name") == "ACCUMULATED DEPRECIATION":
            dep_row = row

    if not ppe_row:
        return {"total": 0, **data}

    for period in period_list:
        key = period["key"]

        if movement_type == "purchase":
            ppe_value = ppe_row.get("debit", 0)
            dep_value = dep_row.get("debit", 0) if dep_row else 0
            value = -abs(ppe_value - dep_value)

        else:  # disposal
            ppe_value = ppe_row.get("credit", 0)
            dep_value = dep_row.get("credit", 0) if dep_row else 0
            value = ppe_value - dep_value

        data[key] = value
        total += value

    data["total"] = total
    return data
