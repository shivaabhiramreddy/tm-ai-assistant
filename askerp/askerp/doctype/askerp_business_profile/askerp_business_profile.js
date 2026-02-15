// AskERP Business Profile — Client Script
// Shows a visual completeness guide with per-section progress indicators.
// Helps users understand what's filled and what's missing.

frappe.ui.form.on("AskERP Business Profile", {
    refresh: function (frm) {
        // Render the completeness guide in the HTML field
        _render_completeness_guide(frm);

        // Add a "Test AI Response" button for admins
        if (frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Test AI Response"), function () {
                _test_ai_response(frm);
            }, __("Actions"));
        }

        // Add "Clear Cache" button so profile changes take effect immediately
        frm.add_custom_button(__("Clear AI Cache"), function () {
            frappe.call({
                method: "frappe.client.clear_cache",
                callback: function () {
                    frappe.show_alert({
                        message: __("AI cache cleared. Changes will take effect on next chat."),
                        indicator: "green"
                    });
                }
            });
        }, __("Actions"));

        // Add "Refresh Business Context" button — triggers full schema discovery
        if (frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Refresh Business Context"), function () {
                frappe.confirm(
                    __("This will scan your entire ERPNext database and rebuild the AI's understanding of your business schema. It runs in the background and takes 1-2 minutes. Proceed?"),
                    function () {
                        frappe.show_alert({
                            message: __("Business context refresh queued. Check back in 1-2 minutes."),
                            indicator: "blue"
                        });
                        frappe.call({
                            method: "askerp.context_discovery.trigger_context_discovery",
                            args: { overwrite: "0" },
                            callback: function (r) {
                                if (r && r.message && r.message.status === "queued") {
                                    frappe.show_alert({
                                        message: __("Discovery running in background. Reload this page in 1-2 minutes to see updated schema."),
                                        indicator: "green"
                                    });
                                }
                            },
                            error: function () {
                                frappe.show_alert({
                                    message: __("Could not start context discovery. Check error log."),
                                    indicator: "red"
                                });
                            }
                        });
                    }
                );
            }, __("Actions"));
        }
    },

    after_save: function (frm) {
        // Re-render completeness guide after saving
        _render_completeness_guide(frm);

        // Clear the business profile cache so AI picks up changes
        frappe.call({
            method: "frappe.client.clear_cache",
            callback: function () {
                frappe.show_alert({
                    message: __("Profile saved. AI will use updated data on next chat."),
                    indicator: "green"
                });
            }
        });
    }
});


function _render_completeness_guide(frm) {
    // Call the server-side method to get per-section status
    frappe.call({
        method: "frappe.client.get",
        args: {
            doctype: "AskERP Business Profile",
            name: frm.doc.name
        },
        callback: function (r) {
            if (!r || !r.message) return;

            // Get section status from the server
            frappe.call({
                method: "frappe.handler.run_doc_method",
                args: {
                    docs: JSON.stringify(frm.doc),
                    method: "get_section_status"
                },
                callback: function (response) {
                    if (!response || !response.message) return;

                    var sections = response.message;
                    var html = _build_completeness_html(sections, frm.doc.profile_completeness || 0);

                    // Set the HTML in the completeness_guide field
                    var wrapper = frm.fields_dict.completeness_guide;
                    if (wrapper && wrapper.$wrapper) {
                        wrapper.$wrapper.html(html);
                    }
                }
            });
        }
    });
}


function _build_completeness_html(sections, overall_pct) {
    // Overall progress bar color
    var overall_color = overall_pct >= 80 ? "#28a745" : overall_pct >= 50 ? "#ffc107" : "#dc3545";
    var overall_label = overall_pct >= 80
        ? "Excellent! Your AI has great context."
        : overall_pct >= 50
            ? "Good progress. Fill more sections for better AI responses."
            : "Getting started. The more you fill, the smarter the AI gets.";

    var html = '<div style="padding: 15px 0;">';

    // Overall progress
    html += '<div style="margin-bottom: 20px;">';
    html += '<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">';
    html += '<span style="font-size: 15px; font-weight: 600; color: #333;">Overall Profile Completeness</span>';
    html += '<span style="font-size: 20px; font-weight: 700; color: ' + overall_color + ';">' + overall_pct + '%</span>';
    html += '</div>';
    html += '<div style="background: #e9ecef; border-radius: 8px; height: 12px; overflow: hidden;">';
    html += '<div style="background: ' + overall_color + '; height: 100%; width: ' + overall_pct + '%; border-radius: 8px; transition: width 0.5s ease;"></div>';
    html += '</div>';
    html += '<p style="margin-top: 6px; font-size: 12px; color: #666;">' + overall_label + '</p>';
    html += '</div>';

    // Per-section breakdown
    html += '<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">';

    var section_icons = {
        "Company Identity": "🏢",
        "Products & Services": "📦",
        "Sales & Customers": "💰",
        "Operations": "⚙️",
        "Finance": "📊",
        "Terminology": "📝",
        "AI Behavior": "🤖"
    };

    for (var section_name in sections) {
        var s = sections[section_name];
        var pct = s.pct || 0;
        var filled = s.filled || 0;
        var total = s.total || 0;
        var icon = section_icons[section_name] || "📋";
        var bar_color = pct >= 80 ? "#28a745" : pct >= 50 ? "#ffc107" : "#dc3545";
        var status_text = pct === 100 ? "✅ Complete" : filled + "/" + total + " fields";

        html += '<div style="background: #f8f9fa; border-radius: 8px; padding: 12px; border: 1px solid #e9ecef;">';
        html += '<div style="display: flex; align-items: center; gap: 6px; margin-bottom: 6px;">';
        html += '<span style="font-size: 16px;">' + icon + '</span>';
        html += '<span style="font-size: 13px; font-weight: 600; color: #333;">' + section_name + '</span>';
        html += '</div>';
        html += '<div style="background: #dee2e6; border-radius: 4px; height: 6px; overflow: hidden; margin-bottom: 4px;">';
        html += '<div style="background: ' + bar_color + '; height: 100%; width: ' + pct + '%; border-radius: 4px;"></div>';
        html += '</div>';
        html += '<span style="font-size: 11px; color: #888;">' + status_text + '</span>';
        html += '</div>';
    }

    html += '</div>';

    // Tip section
    if (overall_pct < 80) {
        html += '<div style="margin-top: 16px; padding: 12px; background: #fff3cd; border-radius: 8px; border: 1px solid #ffc107;">';
        html += '<p style="margin: 0; font-size: 12px; color: #856404;">';
        html += '<strong>💡 Tip:</strong> The AI generates better, more relevant responses when it knows more about your business. ';
        html += 'Fill in the sections above — especially <strong>Company Identity</strong>, <strong>Products</strong>, and <strong>Finance</strong> — for the best results.';
        html += '</p>';
        html += '</div>';
    }

    html += '</div>';
    return html;
}


function _test_ai_response(frm) {
    // Quick test: send a simple query to the AI and show the response
    frappe.prompt(
        {
            fieldname: "test_query",
            label: __("Test Query"),
            fieldtype: "Small Text",
            default: "Give me today's business pulse",
            description: "Send a test query to see how the AI responds with the current profile."
        },
        function (values) {
            frappe.show_alert({
                message: __("Sending test query to AI..."),
                indicator: "blue"
            });

            frappe.call({
                method: "askerp.api.chat",
                args: {
                    message: values.test_query
                },
                callback: function (r) {
                    if (r && r.message && r.message.response) {
                        frappe.msgprint({
                            title: __("AI Test Response"),
                            message: r.message.response,
                            wide: true
                        });
                    } else {
                        frappe.msgprint(__("No response received. Check AI settings and API key."));
                    }
                },
                error: function (err) {
                    frappe.msgprint(__("Error: " + (err.message || "Could not reach AI. Check settings.")));
                }
            });
        },
        __("Test AI Response"),
        __("Send")
    );
}
