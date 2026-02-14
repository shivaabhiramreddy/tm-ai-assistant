// AskERP Prompt Template — Client Script
// ========================================
// Features:
// 1. Preview: Shows the rendered prompt with all {{variables}} replaced
// 2. Test: Sends a sample query using this template and shows the AI response
// 3. Variable Reference: Interactive panel listing all available {{variables}}
//    with click-to-insert functionality
// 4. Active indicator: Shows which tier this template serves

frappe.ui.form.on("AskERP Prompt Template", {
    refresh: function (frm) {
        // Render the variable reference panel
        _render_variable_reference(frm);

        // Show active status indicator
        if (frm.doc.is_active) {
            frm.dashboard.set_headline(
                '<span style="color: #28a745; font-weight: 600;">' +
                '✅ This is the ACTIVE template for the "' + frm.doc.tier + '" tier</span>'
            );
        }

        // Show prompt stats in a subtle way
        if (frm.doc.prompt_char_count) {
            var est_tokens = Math.round(frm.doc.prompt_char_count / 4);
            frm.dashboard.add_comment(
                __("Prompt: {0} chars ≈ {1} tokens | {2} variables",
                    [frm.doc.prompt_char_count, est_tokens, frm.doc.variable_count || 0]),
                "blue",
                true
            );
        }

        // ─── Preview Button ───
        frm.add_custom_button(__("Preview Rendered Prompt"), function () {
            _preview_prompt(frm);
        }, __("Actions"));

        // ─── Test AI Response Button (System Manager only) ───
        if (frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Test AI Response"), function () {
                _test_ai_response(frm);
            }, __("Actions"));
        }

        // ─── Activate / Deactivate Button ───
        if (!frm.doc.is_active) {
            frm.add_custom_button(__("Activate This Template"), function () {
                frm.set_value("is_active", 1);
                frm.save();
            }, __("Actions"));
        }
    },

    prompt_content: function (frm) {
        // Live update character count as user types
        var content = frm.doc.prompt_content || "";
        frm.set_value("prompt_char_count", content.length);
    }
});


// ─── Preview: Render the prompt with real variable values ────────────────────

function _preview_prompt(frm) {
    if (!frm.doc.prompt_content) {
        frappe.msgprint(__("No prompt content to preview."));
        return;
    }

    frappe.show_alert({
        message: __("Rendering preview with live data..."),
        indicator: "blue"
    });

    frappe.call({
        method: "frappe.handler.run_doc_method",
        args: {
            docs: JSON.stringify(frm.doc),
            method: "get_rendered_preview"
        },
        callback: function (r) {
            if (!r || !r.message) {
                frappe.msgprint(__("Could not render preview. Save the template first."));
                return;
            }

            var rendered = r.message;
            var char_count = rendered.length;
            var token_est = Math.round(char_count / 4);

            // Build a styled preview dialog
            var html = '<div style="max-height: 500px; overflow-y: auto;">';

            // Stats bar
            html += '<div style="background: #f0f4f7; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; font-size: 12px; color: #666;">';
            html += '<strong>' + char_count + '</strong> characters ≈ <strong>' + token_est + '</strong> tokens';
            html += ' | Variables: <strong>' + (frm.doc.variable_count || 0) + '</strong>';
            html += '</div>';

            // Rendered prompt (pre-formatted)
            html += '<pre style="background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px; '
                + 'font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-wrap: break-word; '
                + 'max-height: 400px; overflow-y: auto;">';
            html += _escape_html(rendered);
            html += '</pre>';
            html += '</div>';

            var d = new frappe.ui.Dialog({
                title: __("Rendered Prompt Preview"),
                size: "extra-large",
                fields: [
                    {
                        fieldtype: "HTML",
                        fieldname: "preview_html",
                        options: html
                    }
                ],
                primary_action_label: __("Copy to Clipboard"),
                primary_action: function () {
                    navigator.clipboard.writeText(rendered).then(function () {
                        frappe.show_alert({
                            message: __("Copied to clipboard!"),
                            indicator: "green"
                        });
                    });
                }
            });
            d.show();
        },
        error: function () {
            frappe.msgprint(__("Error rendering preview. Make sure the template is saved."));
        }
    });
}


// ─── Test: Send a query using this template ──────────────────────────────────

function _test_ai_response(frm) {
    if (!frm.doc.prompt_content) {
        frappe.msgprint(__("No prompt content to test with. Write a prompt first."));
        return;
    }

    frappe.prompt(
        {
            fieldname: "test_query",
            label: __("Test Query"),
            fieldtype: "Small Text",
            default: "Give me today's business pulse",
            description: "Send a test query using THIS template (not the active one)."
        },
        function (values) {
            frappe.show_alert({
                message: __("Sending test query to AI..."),
                indicator: "blue"
            });

            frappe.call({
                method: "frappe.handler.run_doc_method",
                args: {
                    docs: JSON.stringify(frm.doc),
                    method: "test_with_query",
                    args: JSON.stringify({ test_query: values.test_query })
                },
                callback: function (r) {
                    if (r && r.message && r.message.response) {
                        var html = '<div style="max-height: 400px; overflow-y: auto;">';
                        html += '<div style="background: #f0f4f7; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; font-size: 12px; color: #666;">';
                        html += 'Template: <strong>' + frm.doc.template_name + '</strong>';
                        html += ' | Tier: <strong>' + frm.doc.tier + '</strong>';
                        if (r.message.tokens_used) {
                            html += ' | Tokens: <strong>' + r.message.tokens_used + '</strong>';
                        }
                        html += '</div>';
                        html += '<div style="padding: 12px; background: #fff; border: 1px solid #e9ecef; border-radius: 8px; line-height: 1.7;">';
                        html += _format_ai_response(r.message.response);
                        html += '</div>';
                        html += '</div>';

                        frappe.msgprint({
                            title: __("AI Test Response"),
                            message: html,
                            wide: true,
                            indicator: "green"
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


// ─── Variable Reference Panel ────────────────────────────────────────────────

function _render_variable_reference(frm) {
    var wrapper = frm.fields_dict.variable_reference_html;
    if (!wrapper || !wrapper.$wrapper) return;

    // Variable definitions grouped by category
    var categories = {
        "Company Identity": {
            "company_name": "Primary company name",
            "trading_name": "Trading/brand name",
            "industry": "Industry type",
            "industry_detail": "Industry details",
            "location": "Company location",
            "company_size": "Size range (e.g., 51-200)",
            "currency": "Currency code (e.g., INR)",
            "multi_company_enabled": "Multi-company flag (1/0)",
            "companies_detail": "Multi-company descriptions"
        },
        "Time Context": {
            "today": "Today (YYYY-MM-DD)",
            "now_full_date": "Full date (Friday, 14 Feb 2026)",
            "current_month": "Month + Year (February 2026)",
            "current_year": "Year (2026)",
            "month_start": "1st of current month",
            "month_end": "Today's date",
            "last_month_label": "Last month name + year",
            "last_month_start": "1st of last month",
            "last_month_end": "Last day of last month",
            "fy_label": "FY label (FY 2025-26)",
            "fy_short": "Short FY (2526)",
            "fy_start": "FY start date",
            "fy_end": "FY end date",
            "prev_fy_label": "Previous FY label",
            "prev_fy_start": "Previous FY start",
            "fy_q": "Current quarter (1-4)",
            "q_from": "Quarter start date",
            "q_to": "Quarter end date",
            "smly_start": "Same month last year start",
            "smly_end": "Same month last year end"
        },
        "User Context": {
            "user_name": "User's full name",
            "user_id": "User login (email)",
            "user_roles": "Comma-separated roles",
            "prompt_tier": "Tier (executive/management/field)"
        },
        "Products & Operations": {
            "what_you_sell": "Products/services sold",
            "what_you_buy": "Raw materials/supplies bought",
            "unit_of_measure": "Primary UoM",
            "pricing_model": "Pricing model",
            "sales_channels": "Sales channels",
            "customer_types": "Customer types",
            "has_manufacturing": "Has manufacturing (1/0)",
            "manufacturing_detail": "Manufacturing details",
            "key_metrics_sales": "Key sales metrics",
            "key_metrics_production": "Key production metrics"
        },
        "Finance": {
            "number_format": "Number format (Indian/Western)",
            "accounting_focus": "Accounting focus areas",
            "payment_terms": "Payment terms",
            "financial_year_start": "FY start (MM-DD)",
            "financial_analysis_depth": "Analysis depth"
        },
        "AI Behavior": {
            "ai_personality": "AI personality description",
            "example_voice": "Voice/tone examples",
            "communication_style": "Communication style",
            "primary_language": "Primary language",
            "response_length": "Response length preference",
            "executive_focus": "Executive focus areas",
            "restricted_data": "Restricted data rules"
        },
        "Custom Data": {
            "custom_terminology": "Company terminology (JSON)",
            "custom_doctypes_info": "Custom doctypes (JSON)",
            "industry_benchmarks": "Industry benchmarks (JSON)"
        },
        "Memory": {
            "memory_context": "Session summaries & preferences"
        }
    };

    var html = '<div style="padding: 10px 0;">';

    // Instructions
    html += '<div style="background: #e8f4fd; padding: 10px 14px; border-radius: 6px; margin-bottom: 16px; font-size: 12px; color: #31708f;">';
    html += '<strong>💡 How to use:</strong> Click any variable below to copy <code>{{variable}}</code> to your clipboard, ';
    html += 'then paste it into the Prompt Content above. Variables are replaced with real data at runtime.';
    html += '</div>';

    // Search box
    html += '<div style="margin-bottom: 12px;">';
    html += '<input type="text" id="askerp-var-search" placeholder="Search variables..." ';
    html += 'style="width: 100%; padding: 8px 12px; border: 1px solid #d1d8dd; border-radius: 6px; font-size: 13px;" />';
    html += '</div>';

    // Variable grid
    for (var cat in categories) {
        html += '<div class="askerp-var-category" style="margin-bottom: 14px;">';
        html += '<div style="font-size: 13px; font-weight: 600; color: #333; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid #eee;">';
        html += _get_category_icon(cat) + ' ' + cat;
        html += '</div>';
        html += '<div style="display: flex; flex-wrap: wrap; gap: 6px;">';

        var vars = categories[cat];
        for (var vname in vars) {
            var vdesc = vars[vname];
            html += '<span class="askerp-var-chip" data-var="' + vname + '" ';
            html += 'title="' + _escape_html(vdesc) + '" ';
            html += 'style="display: inline-block; padding: 4px 10px; background: #f4f5f6; ';
            html += 'border: 1px solid #d1d8dd; border-radius: 12px; font-size: 11px; ';
            html += 'color: #36414C; cursor: pointer; transition: all 0.15s ease; ';
            html += 'font-family: monospace;" ';
            html += 'onmouseover="this.style.background=\'#e8f4fd\';this.style.borderColor=\'#80bdff\';" ';
            html += 'onmouseout="this.style.background=\'#f4f5f6\';this.style.borderColor=\'#d1d8dd\';">';
            html += '{{' + vname + '}}';
            html += '</span>';
        }

        html += '</div>';
        html += '</div>';
    }

    html += '</div>';

    wrapper.$wrapper.html(html);

    // Click handler — copy variable to clipboard
    wrapper.$wrapper.find(".askerp-var-chip").on("click", function () {
        var varName = $(this).data("var");
        var varText = "{{" + varName + "}}";

        navigator.clipboard.writeText(varText).then(function () {
            frappe.show_alert({
                message: __("Copied: " + varText),
                indicator: "green"
            });
        }).catch(function () {
            // Fallback for older browsers
            var temp = document.createElement("textarea");
            temp.value = varText;
            document.body.appendChild(temp);
            temp.select();
            document.execCommand("copy");
            document.body.removeChild(temp);
            frappe.show_alert({
                message: __("Copied: " + varText),
                indicator: "green"
            });
        });
    });

    // Search filter
    wrapper.$wrapper.find("#askerp-var-search").on("input", function () {
        var query = $(this).val().toLowerCase();
        wrapper.$wrapper.find(".askerp-var-chip").each(function () {
            var varName = $(this).data("var").toLowerCase();
            var varTitle = ($(this).attr("title") || "").toLowerCase();
            if (varName.indexOf(query) !== -1 || varTitle.indexOf(query) !== -1) {
                $(this).show();
            } else {
                $(this).hide();
            }
        });
        // Hide empty categories
        wrapper.$wrapper.find(".askerp-var-category").each(function () {
            var visibleChips = $(this).find(".askerp-var-chip:visible").length;
            if (visibleChips === 0) {
                $(this).hide();
            } else {
                $(this).show();
            }
        });
    });
}


// ─── Helper Functions ────────────────────────────────────────────────────────

function _get_category_icon(category) {
    var icons = {
        "Company Identity": "🏢",
        "Time Context": "🕐",
        "User Context": "👤",
        "Products & Operations": "📦",
        "Finance": "📊",
        "AI Behavior": "🤖",
        "Custom Data": "⚙️",
        "Memory": "🧠"
    };
    return icons[category] || "📋";
}

function _escape_html(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function _format_ai_response(text) {
    if (!text) return "";
    // Basic formatting: bold, code, newlines
    return text
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/`(.*?)`/g, "<code style='background:#f0f0f0;padding:1px 4px;border-radius:3px;'>$1</code>")
        .replace(/\n/g, "<br>");
}
