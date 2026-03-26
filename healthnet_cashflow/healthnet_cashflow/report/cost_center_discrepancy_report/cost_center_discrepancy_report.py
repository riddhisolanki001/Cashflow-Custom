# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	report_summary = get_report_summary(filters)
	return columns, data, None, None, report_summary


def get_columns():
	return [
		{
			"label": _("Journal Entry"),
			"fieldname": "journal_entry",
			"fieldtype": "Link",
			"options": "Journal Entry",
			"width": 200,
		},
		{
			"label": _("Posting Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 300,
		},
		{
			"label": _("Entry Type"),
			"fieldname": "entry_type",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Cost Centers Found"),
			"fieldname": "cost_centers_found",
			"fieldtype": "Data",
			"width": 300,
		},
		{
			"label": _("No. of Cost Centers"),
			"fieldname": "cost_center_count",
			"fieldtype": "Int",
			"width": 200,
		},
		{
			"label": _("User Remark"),
			"fieldname": "user_remark",
			"fieldtype": "Data",
			"width": 300,
		},
		{
			"label": _("Owner"),
			"fieldname": "owner",
			"fieldtype": "Link",
			"options": "User",
			"width": 250,
		},
	]


def get_data(filters):
	conditions = get_conditions(filters)
	cost_center_condition = ""

	if filters.get("cost_center"):
		cost_center_condition = """
			AND je.name IN (
				SELECT parent FROM `tabJournal Entry Account`
				WHERE cost_center = %(cost_center)s
			)
		"""

	data = frappe.db.sql(
		"""
		SELECT
			je.name AS journal_entry,
			je.posting_date,
			je.company,
			je.voucher_type AS entry_type,
			GROUP_CONCAT(DISTINCT jea.cost_center ORDER BY jea.cost_center SEPARATOR ', ') AS cost_centers_found,
			COUNT(DISTINCT jea.cost_center) AS cost_center_count,
			je.user_remark,
			je.owner
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE je.docstatus = 1
			AND IFNULL(jea.cost_center, '') != ''
			{conditions}
			{cost_center_condition}
		GROUP BY je.name
		HAVING COUNT(DISTINCT jea.cost_center) > 1
		ORDER BY je.posting_date DESC
	""".format(conditions=conditions, cost_center_condition=cost_center_condition),
		filters,
		as_dict=True,
	)

	return data


def get_report_summary(filters):
	conditions = get_conditions(filters)

	# Get total submitted JEs and their cost center status
	summary_data = frappe.db.sql(
		"""
		SELECT
			je.name,
			COUNT(DISTINCT jea.cost_center) AS cc_count
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE je.docstatus = 1
			AND IFNULL(jea.cost_center, '') != ''
			{conditions}
		GROUP BY je.name
	""".format(conditions=conditions),
		filters,
		as_dict=True,
	)

	total = len(summary_data)
	mismatch = sum(1 for row in summary_data if row.cc_count > 1)
	match = total - mismatch

	return [
		{
			"value": total,
			"indicator": "Blue",
			"label": _("Total Journal Entries"),
			"datatype": "Int",
		},
		{
			"value": match,
			"indicator": "Green",
			"label": _("Matched Cost Center"),
			"datatype": "Int",
		},
		{
			"value": mismatch,
			"indicator": "Red",
			"label": _("Mismatched Cost Center"),
			"datatype": "Int",
		},
	]


def get_conditions(filters):
	conditions = ""

	if filters.get("company"):
		conditions += " AND je.company = %(company)s"

	if filters.get("from_date"):
		conditions += " AND je.posting_date >= %(from_date)s"

	if filters.get("to_date"):
		conditions += " AND je.posting_date <= %(to_date)s"

	if filters.get("entry_type"):
		conditions += " AND je.voucher_type = %(entry_type)s"

	return conditions