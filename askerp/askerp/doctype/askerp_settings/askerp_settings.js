// AskERP Settings — Client Script
// =================================
// Adds "Re-run Setup Wizard" button and setup status indicators.

frappe.ui.form.on("AskERP Settings", {
    refresh: function (frm) {
        // Show setup status indicator
        if (frm.doc.setup_complete) {
            frm.dashboard.set_headline(
                '<span style="color: #28a745; font-weight: 600;">' +
                '\u2705 Setup Complete' +
                (frm.doc.setup_completed_on
                    ? ' — ' + frappe.datetime.prettyDate(frm.doc.setup_completed_on)
                    : '') +
                '</span>'
            );
        } else {
            frm.dashboard.set_headline(
                '<span style="color: #dc3545; font-weight: 600;">' +
                '\u26a0\ufe0f Setup Incomplete — Step ' + (frm.doc.setup_current_step || 0) + ' of 5' +
                '</span>'
            );
        }

        // Re-run Setup Wizard button
        frm.add_custom_button(__("Re-run Setup Wizard"), function () {
            frappe.confirm(
                __("This will reset the setup wizard so it appears again on page load. Continue?"),
                function () {
                    frappe.call({
                        method: "askerp.setup_wizard.reset_setup",
                        callback: function (r) {
                            if (r && r.message && r.message.success) {
                                frappe.show_alert({
                                    message: __("Setup wizard reset! Reloading page..."),
                                    indicator: "green"
                                });
                                setTimeout(function () {
                                    window.location.reload();
                                }, 1000);
                            }
                        }
                    });
                }
            );
        }, __("Actions"));

        // Open Setup Wizard Now button (if incomplete)
        if (!frm.doc.setup_complete) {
            frm.add_custom_button(__("Open Setup Wizard"), function () {
                if (window.askerpSetupWizard) {
                    window.askerpSetupWizard.show((frm.doc.setup_current_step || 0) + 1);
                } else {
                    frappe.show_alert({
                        message: __("Setup wizard script not loaded. Refresh the page."),
                        indicator: "orange"
                    });
                }
            }).addClass("btn-primary-dark");
        }
    }
});
