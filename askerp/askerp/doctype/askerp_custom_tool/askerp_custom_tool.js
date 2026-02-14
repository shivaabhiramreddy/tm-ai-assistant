// AskERP Custom Tool — Client Script
// ===================================
// Features:
// 1. Test Panel: Run the tool with sample parameters and see results
// 2. Visual indicators for enabled/disabled state
// 3. Parameter validation hints
// 4. Query type visibility toggles

frappe.ui.form.on("AskERP Custom Tool", {
    refresh: function (frm) {
        // Show enabled/disabled indicator
        if (frm.doc.enabled) {
            frm.dashboard.set_headline(
                '<span style="color: #28a745; font-weight: 600;">' +
                '\u2705 This tool is ENABLED — the AI can use it</span>'
            );
        } else {
            frm.dashboard.set_headline(
                '<span style="color: #dc3545; font-weight: 600;">' +
                '\u274c This tool is DISABLED — the AI will not see it</span>'
            );
        }

        // Show usage stats
        if (frm.doc.usage_count > 0) {
            frm.dashboard.add_comment(
                __("Used {0} times | Last used: {1} | Avg response: {2}ms | Errors: {3}",
                    [frm.doc.usage_count,
                     frm.doc.last_used ? frappe.datetime.prettyDate(frm.doc.last_used) : "never",
                     frm.doc.avg_response_time_ms || 0,
                     frm.doc.error_count || 0]),
                "blue", true
            );
        }

        // Render the test panel
        _render_test_panel(frm);

        // Enable/Disable quick toggle button
        if (frm.doc.enabled) {
            frm.add_custom_button(__("Disable Tool"), function () {
                frm.set_value("enabled", 0);
                frm.save();
            }, __("Actions"));
        } else {
            frm.add_custom_button(__("Enable Tool"), function () {
                frm.set_value("enabled", 1);
                frm.save();
            }, __("Actions"));
        }

        // Duplicate tool button
        frm.add_custom_button(__("Duplicate Tool"), function () {
            frappe.prompt(
                { fieldname: "new_name", label: __("New Tool Name"), fieldtype: "Data", reqd: 1 },
                function (values) {
                    var new_doc = frappe.model.copy_doc(frm.doc);
                    new_doc.tool_name = values.new_name;
                    new_doc.display_name = values.new_name.replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); });
                    new_doc.usage_count = 0;
                    new_doc.error_count = 0;
                    new_doc.last_used = null;
                    new_doc.avg_response_time_ms = 0;
                    frappe.set_route("Form", "AskERP Custom Tool", new_doc.name);
                },
                __("Duplicate Tool"),
                __("Create")
            );
        }, __("Actions"));
    },

    tool_name: function (frm) {
        // Auto-generate display name from tool_name
        if (frm.doc.tool_name && !frm.doc.display_name) {
            var display = frm.doc.tool_name
                .replace(/_/g, " ")
                .replace(/\b\w/g, function (c) { return c.toUpperCase(); });
            frm.set_value("display_name", display);
        }
    },
});


// ─── Test Panel ──────────────────────────────────────────────────────────────

function _render_test_panel(frm) {
    var wrapper = frm.fields_dict.test_panel_html;
    if (!wrapper || !wrapper.$wrapper) return;

    if (frm.is_new()) {
        wrapper.$wrapper.html(
            '<p class="text-muted">Save the tool first to use the Test Panel.</p>'
        );
        return;
    }

    var html = '<div style="padding: 10px 0;">';

    // Instructions
    html += '<div style="background: #e8f4fd; padding: 10px 14px; border-radius: 6px; margin-bottom: 16px; font-size: 12px; color: #31708f;">';
    html += '<strong>\ud83e\uddea Test Panel:</strong> Enter sample parameter values below and click "Run Test" to see the tool\'s output. ';
    html += 'This runs the actual query against your ERPNext data.';
    html += '</div>';

    // Parameter input fields
    var params = frm.doc.parameters || [];
    if (params.length > 0) {
        html += '<div style="margin-bottom: 16px;">';
        for (var i = 0; i < params.length; i++) {
            var p = params[i];
            var input_type = "text";
            var placeholder = p.param_description || p.param_name;
            if (p.param_type === "Number") input_type = "number";
            if (p.param_type === "Date") input_type = "date";

            html += '<div style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">';
            html += '<label style="min-width: 140px; font-weight: 600; font-size: 12px; color: #36414C;">';
            html += _escape_html(p.param_name);
            if (p.required) html += ' <span style="color: red;">*</span>';
            html += '</label>';

            if (p.param_type === "Select" && p.select_options) {
                html += '<select class="askerp-test-param form-control" data-param="' + _escape_html(p.param_name) + '" ';
                html += 'style="flex: 1; max-width: 300px; font-size: 13px;">';
                html += '<option value="">Select...</option>';
                var opts = p.select_options.split(",");
                for (var j = 0; j < opts.length; j++) {
                    var opt = opts[j].trim();
                    html += '<option value="' + _escape_html(opt) + '">' + _escape_html(opt) + '</option>';
                }
                html += '</select>';
            } else if (p.param_type === "Boolean") {
                html += '<select class="askerp-test-param form-control" data-param="' + _escape_html(p.param_name) + '" ';
                html += 'style="flex: 1; max-width: 300px; font-size: 13px;">';
                html += '<option value="">Select...</option>';
                html += '<option value="1">Yes / True</option>';
                html += '<option value="0">No / False</option>';
                html += '</select>';
            } else {
                html += '<input type="' + input_type + '" class="askerp-test-param form-control" ';
                html += 'data-param="' + _escape_html(p.param_name) + '" ';
                html += 'placeholder="' + _escape_html(placeholder) + '" ';
                if (p.default_value) html += 'value="' + _escape_html(p.default_value) + '" ';
                html += 'style="flex: 1; max-width: 300px; font-size: 13px;" />';
            }

            html += '<span style="font-size: 11px; color: #888;">(' + (p.param_type || "String") + ')</span>';
            html += '</div>';
        }
        html += '</div>';
    } else {
        html += '<p class="text-muted" style="font-size: 12px;">No parameters defined. The tool will run without inputs.</p>';
    }

    // Run Test button
    html += '<button class="btn btn-primary btn-sm askerp-run-test" style="margin-bottom: 16px;">Run Test</button>';
    html += ' <button class="btn btn-default btn-sm askerp-clear-results" style="margin-bottom: 16px;">Clear Results</button>';

    // Results area
    html += '<div id="askerp-test-results" style="display: none;">';
    html += '<div style="font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #333;">Results:</div>';
    html += '<div id="askerp-test-meta" style="background: #f0f4f7; padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 12px; color: #666;"></div>';
    html += '<pre id="askerp-test-output" style="background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px; ';
    html += 'font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; ';
    html += 'max-height: 400px; overflow-y: auto;"></pre>';
    html += '</div>';

    html += '</div>';

    wrapper.$wrapper.html(html);

    // Run Test click handler
    wrapper.$wrapper.find(".askerp-run-test").on("click", function () {
        _run_tool_test(frm, wrapper);
    });

    // Clear results
    wrapper.$wrapper.find(".askerp-clear-results").on("click", function () {
        wrapper.$wrapper.find("#askerp-test-results").hide();
    });
}


function _run_tool_test(frm, wrapper) {
    // Collect parameter values
    var test_params = {};
    wrapper.$wrapper.find(".askerp-test-param").each(function () {
        var pname = $(this).data("param");
        var val = $(this).val();
        if (val !== "" && val !== null && val !== undefined) {
            test_params[pname] = val;
        }
    });

    // Validate required params
    var params = frm.doc.parameters || [];
    for (var i = 0; i < params.length; i++) {
        if (params[i].required && !test_params[params[i].param_name]) {
            frappe.msgprint(__("Required parameter missing: " + params[i].param_name));
            return;
        }
    }

    frappe.show_alert({ message: __("Running tool test..."), indicator: "blue" });

    frappe.call({
        method: "frappe.handler.run_doc_method",
        args: {
            docs: JSON.stringify(frm.doc),
            method: "test_tool",
            args: JSON.stringify({ test_params: JSON.stringify(test_params) })
        },
        callback: function (r) {
            if (!r || !r.message) {
                frappe.msgprint(__("No response. Save the tool first."));
                return;
            }

            var res = r.message;
            var results_div = wrapper.$wrapper.find("#askerp-test-results");
            var meta_div = wrapper.$wrapper.find("#askerp-test-meta");
            var output_div = wrapper.$wrapper.find("#askerp-test-output");

            results_div.show();

            if (res.success) {
                meta_div.html(
                    '<span style="color: #28a745;">\u2705 Success</span>' +
                    ' | Query type: <strong>' + (res.query_type || "?") + '</strong>' +
                    ' | Time: <strong>' + (res.elapsed_ms || 0) + 'ms</strong>' +
                    (res.result && res.result.count !== undefined ? ' | Rows: <strong>' + res.result.count + '</strong>' : '')
                );
                output_div.text(JSON.stringify(res.result, null, 2));
            } else {
                meta_div.html(
                    '<span style="color: #dc3545;">\u274c Error</span>' +
                    ' | Time: <strong>' + (res.elapsed_ms || 0) + 'ms</strong>'
                );
                output_div.text(res.error || "Unknown error");
            }
        },
        error: function (err) {
            frappe.msgprint(__("Test failed: " + (err.message || "Unknown error")));
        }
    });
}


function _escape_html(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
