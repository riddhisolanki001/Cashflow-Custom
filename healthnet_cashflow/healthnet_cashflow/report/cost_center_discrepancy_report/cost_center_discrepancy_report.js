// Copyright (c) 2026, Your Company and contributors
// For license information, please see license.txt

frappe.query_reports["Cost Center Discrepancy Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: function () {
				var company = frappe.query_report.get_filter_value("company");
				return {
					filters: { company: company },
				};
			},
		},
		{
			fieldname: "entry_type",
			label: __("Entry Type"),
			fieldtype: "Select",
			options: [
				"",
				"Journal Entry",
				"Inter Company Journal Entry",
				"Bank Entry",
				"Cash Entry",
				"Credit Card Entry",
				"Debit Note",
				"Credit Note",
				"Contra Entry",
				"Excise Entry",
				"Write Off Entry",
				"Opening Entry",
				"Depreciation Entry",
				"Exchange Rate Revaluation",
				"Exchange Gain Or Loss",
			],
		},
	],
};