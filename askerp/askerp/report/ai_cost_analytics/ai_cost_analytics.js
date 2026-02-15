// Copyright (c) 2026, Cogniverse and contributors
// License: MIT
//
// AI Cost Analytics — Client-side filters and configuration

frappe.query_reports["AI Cost Analytics"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: "Day\nWeek\nMonth\nUser\nModel\nComplexity",
			default: "Day",
		},
		{
			fieldname: "user",
			label: __("User"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "model",
			label: __("Model"),
			fieldtype: "Data",
		},
		{
			fieldname: "complexity",
			label: __("Complexity"),
			fieldtype: "Select",
			options: "\nflash\nsimple\nmedium\ncomplex",
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		// Highlight high costs in red
		if (column.fieldname === "total_cost" && data && data.total_cost > 1) {
			value = `<span style="color: #e74c3c; font-weight: bold;">${value}</span>`;
		}

		// Highlight good cache hit rates in green
		if (column.fieldname === "cache_hit_pct" && data && data.cache_hit_pct > 70) {
			value = `<span style="color: #047e38; font-weight: bold;">${value}</span>`;
		}

		return value;
	},
};
