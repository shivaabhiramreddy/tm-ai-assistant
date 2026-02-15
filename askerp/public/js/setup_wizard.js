/**
 * AskERP — Setup Wizard
 * ================================
 * 5-step guided setup that appears on first visit after installation.
 * Fully self-contained: creates its own DOM, calls API endpoints.
 *
 * Steps:
 * 1. Welcome — intro + what to expect
 * 2. AI Provider — select provider, enter API key, test connection
 * 3. Business Profile — company name, industry, description
 * 4. Enable Users — checkbox list of users to give AI access
 * 5. Done — success message + open chat widget
 *
 * Resume: If dismissed, a notification bar appears. Clicking it re-opens
 * the wizard from the last completed step.
 */

(function () {
  "use strict";

  // ─── State ──────────────────────────────────────────────────────
  let currentStep = 1;
  let totalSteps = 5;
  let $overlay, $wizard;
  let selectedProvider = "";
  let validatedApiKey = "";
  let userList = [];
  let wizardActive = false;

  // ─── CSS ────────────────────────────────────────────────────────
  function injectStyles() {
    if (document.getElementById("askerp-wizard-styles")) return;

    const css = `
      .askerp-wizard-overlay {
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.5); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
        animation: askerp-wizard-fade-in 0.3s ease;
      }
      @keyframes askerp-wizard-fade-in {
        from { opacity: 0; } to { opacity: 1; }
      }
      .askerp-wizard {
        background: #fff; border-radius: 12px; width: 640px; max-width: 95vw;
        max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        animation: askerp-wizard-slide-up 0.3s ease;
      }
      @keyframes askerp-wizard-slide-up {
        from { transform: translateY(30px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
      }
      .askerp-wizard-header {
        padding: 24px 28px 16px; border-bottom: 1px solid #e9ecef;
      }
      .askerp-wizard-progress {
        display: flex; gap: 6px; margin-bottom: 16px;
      }
      .askerp-wizard-progress-dot {
        flex: 1; height: 4px; border-radius: 2px; background: #e9ecef;
        transition: background 0.3s ease;
      }
      .askerp-wizard-progress-dot.active { background: #1b8a2a; }
      .askerp-wizard-progress-dot.done { background: #28a745; }
      .askerp-wizard-step-label {
        font-size: 12px; color: #888; font-weight: 500; text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .askerp-wizard-title {
        font-size: 22px; font-weight: 700; color: #1a1a2e; margin: 8px 0 4px;
      }
      .askerp-wizard-subtitle {
        font-size: 14px; color: #666; line-height: 1.5;
      }
      .askerp-wizard-body {
        padding: 20px 28px;
      }
      .askerp-wizard-footer {
        padding: 16px 28px 24px; display: flex; justify-content: space-between;
        align-items: center; border-top: 1px solid #f0f0f0;
      }
      .askerp-wizard-btn {
        padding: 10px 24px; border-radius: 8px; font-size: 14px; font-weight: 600;
        cursor: pointer; border: none; transition: all 0.2s ease;
      }
      .askerp-wizard-btn-primary {
        background: #1b8a2a; color: #fff;
      }
      .askerp-wizard-btn-primary:hover { background: #157a22; }
      .askerp-wizard-btn-primary:disabled {
        background: #b8d4bc; cursor: not-allowed;
      }
      .askerp-wizard-btn-secondary {
        background: #f5f5f5; color: #555;
      }
      .askerp-wizard-btn-secondary:hover { background: #e8e8e8; }
      .askerp-wizard-btn-skip {
        background: none; color: #999; font-size: 13px; padding: 10px 12px;
      }
      .askerp-wizard-btn-skip:hover { color: #555; }

      /* Provider Cards */
      .askerp-wizard-providers {
        display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
        margin-bottom: 20px;
      }
      .askerp-wizard-provider-card {
        border: 2px solid #e9ecef; border-radius: 10px; padding: 16px 12px;
        text-align: center; cursor: pointer; transition: all 0.2s ease;
      }
      .askerp-wizard-provider-card:hover { border-color: #1b8a2a; background: #f8fff9; }
      .askerp-wizard-provider-card.selected {
        border-color: #1b8a2a; background: #f0faf1;
        box-shadow: 0 0 0 3px rgba(27,138,42,0.15);
      }
      .askerp-wizard-provider-name {
        font-size: 14px; font-weight: 600; color: #333; margin-top: 8px;
      }
      .askerp-wizard-provider-tag {
        font-size: 11px; color: #888; margin-top: 4px;
      }
      .askerp-wizard-provider-icon {
        font-size: 28px;
      }

      /* API Key Input */
      .askerp-wizard-api-section {
        margin-top: 16px; display: none;
      }
      .askerp-wizard-api-section.visible { display: block; }
      .askerp-wizard-input-group {
        display: flex; gap: 8px; align-items: stretch;
      }
      .askerp-wizard-input {
        flex: 1; padding: 10px 14px; border: 1px solid #d1d5db; border-radius: 8px;
        font-size: 14px; font-family: monospace; outline: none;
        transition: border-color 0.2s ease;
      }
      .askerp-wizard-input:focus { border-color: #1b8a2a; }
      .askerp-wizard-test-btn {
        padding: 10px 18px; background: #f0f0f0; border: 1px solid #d1d5db;
        border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
        white-space: nowrap; transition: all 0.2s;
      }
      .askerp-wizard-test-btn:hover { background: #e0e0e0; }
      .askerp-wizard-test-btn.testing {
        background: #fff3cd; border-color: #ffc107; cursor: wait;
      }
      .askerp-wizard-test-result {
        margin-top: 10px; padding: 10px 14px; border-radius: 8px;
        font-size: 13px; display: none;
      }
      .askerp-wizard-test-result.success {
        background: #d4edda; color: #155724; display: block;
      }
      .askerp-wizard-test-result.error {
        background: #f8d7da; color: #721c24; display: block;
      }

      /* Form Fields */
      .askerp-wizard-field {
        margin-bottom: 16px;
      }
      .askerp-wizard-label {
        font-size: 13px; font-weight: 600; color: #444; margin-bottom: 6px;
        display: block;
      }
      .askerp-wizard-label .required { color: #dc3545; }
      .askerp-wizard-select {
        width: 100%; padding: 10px 14px; border: 1px solid #d1d5db;
        border-radius: 8px; font-size: 14px; outline: none; background: #fff;
      }
      .askerp-wizard-textarea {
        width: 100%; padding: 10px 14px; border: 1px solid #d1d5db;
        border-radius: 8px; font-size: 14px; outline: none; resize: vertical;
        min-height: 80px; font-family: inherit;
      }
      .askerp-wizard-hint {
        font-size: 12px; color: #999; margin-top: 4px;
      }

      /* User List */
      .askerp-wizard-user-controls {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 12px;
      }
      .askerp-wizard-user-search {
        padding: 8px 12px; border: 1px solid #d1d5db; border-radius: 6px;
        font-size: 13px; width: 220px; outline: none;
      }
      .askerp-wizard-select-all {
        font-size: 13px; color: #1b8a2a; cursor: pointer; font-weight: 600;
        background: none; border: none; padding: 4px 8px;
      }
      .askerp-wizard-user-list {
        max-height: 280px; overflow-y: auto; border: 1px solid #e9ecef;
        border-radius: 8px;
      }
      .askerp-wizard-user-row {
        display: flex; align-items: center; gap: 12px; padding: 10px 14px;
        border-bottom: 1px solid #f5f5f5; cursor: pointer;
        transition: background 0.15s ease;
      }
      .askerp-wizard-user-row:hover { background: #f8f9fa; }
      .askerp-wizard-user-row:last-child { border-bottom: none; }
      .askerp-wizard-user-check {
        width: 18px; height: 18px; accent-color: #1b8a2a; cursor: pointer;
      }
      .askerp-wizard-user-avatar {
        width: 32px; height: 32px; border-radius: 50%; background: #e9ecef;
        display: flex; align-items: center; justify-content: center;
        font-size: 14px; font-weight: 600; color: #666; overflow: hidden;
      }
      .askerp-wizard-user-avatar img {
        width: 100%; height: 100%; object-fit: cover;
      }
      .askerp-wizard-user-info {
        flex: 1;
      }
      .askerp-wizard-user-name {
        font-size: 14px; font-weight: 500; color: #333;
      }
      .askerp-wizard-user-email {
        font-size: 12px; color: #999;
      }
      .askerp-wizard-user-count {
        font-size: 13px; color: #666;
      }

      /* Done Screen */
      .askerp-wizard-done {
        text-align: center; padding: 20px 0;
      }
      .askerp-wizard-done-icon {
        width: 72px; height: 72px; border-radius: 50%; background: #d4edda;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 20px; font-size: 36px;
      }
      .askerp-wizard-done h2 {
        font-size: 24px; font-weight: 700; color: #1a1a2e; margin-bottom: 8px;
      }
      .askerp-wizard-done p {
        font-size: 15px; color: #666; line-height: 1.6; max-width: 420px;
        margin: 0 auto;
      }
      .askerp-wizard-try-prompt {
        background: #f8f9fa; border-radius: 8px; padding: 12px 16px;
        margin-top: 20px; font-size: 14px; color: #333;
        border-left: 3px solid #1b8a2a;
      }

      /* Notification bar */
      .askerp-wizard-notification {
        position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
        background: linear-gradient(135deg, #1b8a2a, #28a745); color: #fff;
        padding: 10px 20px; display: flex; align-items: center;
        justify-content: center; gap: 12px; font-size: 14px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        animation: askerp-wizard-slide-down 0.3s ease;
      }
      @keyframes askerp-wizard-slide-down {
        from { transform: translateY(-100%); } to { transform: translateY(0); }
      }
      .askerp-wizard-notification-btn {
        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.4);
        color: #fff; padding: 5px 14px; border-radius: 6px; font-size: 13px;
        font-weight: 600; cursor: pointer;
      }
      .askerp-wizard-notification-btn:hover { background: rgba(255,255,255,0.3); }
      .askerp-wizard-notification-dismiss {
        background: none; border: none; color: rgba(255,255,255,0.7);
        cursor: pointer; font-size: 18px; padding: 0 4px; line-height: 1;
      }
    `;

    const style = document.createElement("style");
    style.id = "askerp-wizard-styles";
    style.textContent = css;
    document.head.appendChild(style);
  }


  // ─── Wizard Lifecycle ───────────────────────────────────────────

  function showWizard(startStep) {
    if (wizardActive) return;
    wizardActive = true;
    currentStep = startStep || 1;

    injectStyles();
    removeNotification();

    // Create overlay
    $overlay = document.createElement("div");
    $overlay.className = "askerp-wizard-overlay";

    $wizard = document.createElement("div");
    $wizard.className = "askerp-wizard";

    $overlay.appendChild($wizard);
    document.body.appendChild($overlay);

    renderStep();
  }

  function closeWizard() {
    if ($overlay) {
      $overlay.remove();
      $overlay = null;
      $wizard = null;
    }
    wizardActive = false;
  }

  function dismissWizard() {
    closeWizard();
    showNotification();
  }

  function renderStep() {
    if (!$wizard) return;

    let html = "";

    // Header with progress
    html += '<div class="askerp-wizard-header">';
    html += '<div class="askerp-wizard-progress">';
    for (let i = 1; i <= totalSteps; i++) {
      let cls = "askerp-wizard-progress-dot";
      if (i < currentStep) cls += " done";
      if (i === currentStep) cls += " active";
      html += '<div class="' + cls + '"></div>';
    }
    html += "</div>";

    // Step label and title
    const stepInfo = getStepInfo(currentStep);
    html += '<div class="askerp-wizard-step-label">' + __("Step {0} of {1}", [currentStep, totalSteps]) + "</div>";
    html += '<div class="askerp-wizard-title">' + stepInfo.title + "</div>";
    html += '<div class="askerp-wizard-subtitle">' + stepInfo.subtitle + "</div>";
    html += "</div>";

    // Body
    html += '<div class="askerp-wizard-body">';
    html += getStepContent(currentStep);
    html += "</div>";

    // Footer
    html += '<div class="askerp-wizard-footer">';
    html += getStepFooter(currentStep);
    html += "</div>";

    $wizard.innerHTML = html;

    // Bind events after render
    bindStepEvents(currentStep);
  }

  function getStepInfo(step) {
    switch (step) {
      case 1: return {
        title: __("Welcome to AI Assistant"),
        subtitle: __("In the next 5 minutes, you'll set up an AI that understands your business and can answer questions about your ERP data.")
      };
      case 2: return {
        title: __("Connect AI Provider"),
        subtitle: __("Choose your AI service and enter your API key. We'll test the connection in real-time.")
      };
      case 3: return {
        title: __("Tell Us About Your Business"),
        subtitle: __("Help the AI understand your company so it gives relevant, accurate answers.")
      };
      case 4: return {
        title: __("Enable Users"),
        subtitle: __("Select which users should have access to the AI chat assistant.")
      };
      case 5: return {
        title: __("You're All Set!"),
        subtitle: ""
      };
      default: return { title: "", subtitle: "" };
    }
  }


  // ─── Step Content ───────────────────────────────────────────────

  function getStepContent(step) {
    switch (step) {
      case 1: return getStep1Content();
      case 2: return getStep2Content();
      case 3: return getStep3Content();
      case 4: return getStep4Content();
      case 5: return getStep5Content();
      default: return "";
    }
  }

  function getStep1Content() {
    return '' +
      '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; margin: 10px 0;">' +
        '<div style="background: #f0faf1; border-radius: 10px; padding: 16px;">' +
          '<div style="font-size: 24px; margin-bottom: 8px;">💬</div>' +
          '<div style="font-weight: 600; color: #333; margin-bottom: 4px;">' + __("Chat with Your Data") + '</div>' +
          '<div style="font-size: 13px; color: #666;">' + __("Ask questions in plain English about sales, inventory, finances — any ERP data.") + '</div>' +
        '</div>' +
        '<div style="background: #f0f4ff; border-radius: 10px; padding: 16px;">' +
          '<div style="font-size: 24px; margin-bottom: 8px;">📊</div>' +
          '<div style="font-weight: 600; color: #333; margin-bottom: 4px;">' + __("Instant Analysis") + '</div>' +
          '<div style="font-size: 13px; color: #666;">' + __("Get financial summaries, trend comparisons, and export reports to PDF or Excel.") + '</div>' +
        '</div>' +
        '<div style="background: #fff8f0; border-radius: 10px; padding: 16px;">' +
          '<div style="font-size: 24px; margin-bottom: 8px;">🔔</div>' +
          '<div style="font-weight: 600; color: #333; margin-bottom: 4px;">' + __("Smart Alerts") + '</div>' +
          '<div style="font-size: 13px; color: #666;">' + __("Set alerts for business thresholds — get notified when metrics cross limits.") + '</div>' +
        '</div>' +
        '<div style="background: #f8f0ff; border-radius: 10px; padding: 16px;">' +
          '<div style="font-size: 24px; margin-bottom: 8px;">🛡️</div>' +
          '<div style="font-weight: 600; color: #333; margin-bottom: 4px;">' + __("Safe & Secure") + '</div>' +
          '<div style="font-size: 13px; color: #666;">' + __("Read-only by default. Role-based access. Your data stays in your ERPNext.") + '</div>' +
        '</div>' +
      '</div>';
  }

  function getStep2Content() {
    return '' +
      '<div class="askerp-wizard-providers">' +
        '<div class="askerp-wizard-provider-card' + (selectedProvider === "Anthropic" ? " selected" : "") + '" data-provider="Anthropic">' +
          '<div class="askerp-wizard-provider-icon">🟤</div>' +
          '<div class="askerp-wizard-provider-name">' + __("Anthropic (Claude)") + '</div>' +
          '<div class="askerp-wizard-provider-tag">' + __("Recommended") + '</div>' +
        '</div>' +
        '<div class="askerp-wizard-provider-card' + (selectedProvider === "Google" ? " selected" : "") + '" data-provider="Google">' +
          '<div class="askerp-wizard-provider-icon">🔵</div>' +
          '<div class="askerp-wizard-provider-name">' + __("Google (Gemini)") + '</div>' +
          '<div class="askerp-wizard-provider-tag">' + __("Budget-friendly") + '</div>' +
        '</div>' +
        '<div class="askerp-wizard-provider-card' + (selectedProvider === "OpenAI" ? " selected" : "") + '" data-provider="OpenAI">' +
          '<div class="askerp-wizard-provider-icon">🟢</div>' +
          '<div class="askerp-wizard-provider-name">' + __("OpenAI (GPT)") + '</div>' +
          '<div class="askerp-wizard-provider-tag">' + __("Popular") + '</div>' +
        '</div>' +
      '</div>' +
      '<div class="askerp-wizard-api-section' + (selectedProvider ? " visible" : "") + '" id="askerp-wizard-api-section">' +
        '<div class="askerp-wizard-label">' + __("API Key") + ' <span class="required">*</span></div>' +
        '<div class="askerp-wizard-input-group">' +
          '<input type="password" class="askerp-wizard-input" id="askerp-wizard-api-key" ' +
            'placeholder="' + __("Enter your {0} API key...", [selectedProvider || __("provider")]) + '" ' +
            'value="' + _escHtml(validatedApiKey) + '">' +
          '<button class="askerp-wizard-test-btn" id="askerp-wizard-test-btn">' + __("Test Connection") + '</button>' +
        '</div>' +
        '<div class="askerp-wizard-test-result" id="askerp-wizard-test-result"></div>' +
        '<div class="askerp-wizard-hint" style="margin-top: 8px;">' +
          __("Don't have an API key? Visit your provider's dashboard to create one.") +
        '</div>' +
      '</div>';
  }

  function getStep3Content() {
    // Try to get company name from ERPNext
    var defaultCompany = "";
    try {
      if (frappe.boot && frappe.boot.sysdefaults) {
        defaultCompany = frappe.boot.sysdefaults.company || "";
      }
    } catch (e) { /* ignore */ }

    return '' +
      '<div class="askerp-wizard-field">' +
        '<label class="askerp-wizard-label">' + __("Company Name") + ' <span class="required">*</span></label>' +
        '<input type="text" class="askerp-wizard-input" id="askerp-wizard-company" ' +
          'placeholder="' + __("Your company name") + '" value="' + _escHtml(defaultCompany) + '">' +
      '</div>' +
      '<div class="askerp-wizard-field">' +
        '<label class="askerp-wizard-label">' + __("Industry") + '</label>' +
        '<select class="askerp-wizard-select" id="askerp-wizard-industry">' +
          '<option value="">' + __("Select your industry...") + '</option>' +
          '<option value="Manufacturing">' + __("Manufacturing") + '</option>' +
          '<option value="Trading">' + __("Trading / Distribution") + '</option>' +
          '<option value="Retail">' + __("Retail") + '</option>' +
          '<option value="Services">' + __("Services") + '</option>' +
          '<option value="Healthcare">' + __("Healthcare") + '</option>' +
          '<option value="Education">' + __("Education") + '</option>' +
          '<option value="Agriculture">' + __("Agriculture") + '</option>' +
          '<option value="Construction">' + __("Construction / Real Estate") + '</option>' +
          '<option value="Technology">' + __("Technology / IT") + '</option>' +
          '<option value="Food & Beverage">' + __("Food & Beverage") + '</option>' +
          '<option value="Hospitality">' + __("Hospitality") + '</option>' +
          '<option value="Non-Profit">' + __("Non-Profit") + '</option>' +
          '<option value="Other">' + __("Other") + '</option>' +
        '</select>' +
      '</div>' +
      '<div class="askerp-wizard-field">' +
        '<label class="askerp-wizard-label">' + __("What does your company do?") + '</label>' +
        '<textarea class="askerp-wizard-textarea" id="askerp-wizard-description" ' +
          'placeholder="' + __("Describe your company in 1-2 sentences. For example: We manufacture electronic components and sell through a dealer network.") + '"></textarea>' +
        '<div class="askerp-wizard-hint">' + __("This helps the AI understand your business context. You can add more details later.") + '</div>' +
      '</div>';
  }

  function getStep4Content() {
    return '' +
      '<div class="askerp-wizard-user-controls">' +
        '<input type="text" class="askerp-wizard-user-search" id="askerp-wizard-user-search" placeholder="' + __("Search users...") + '">' +
        '<button class="askerp-wizard-select-all" id="askerp-wizard-select-all">' + __("Select All") + '</button>' +
      '</div>' +
      '<div class="askerp-wizard-user-list" id="askerp-wizard-user-list">' +
        '<div style="padding: 20px; text-align: center; color: #999;">' + __("Loading users...") + '</div>' +
      '</div>' +
      '<div class="askerp-wizard-user-count" id="askerp-wizard-user-count" style="margin-top: 8px;"></div>';
  }

  function getStep5Content() {
    return '' +
      '<div class="askerp-wizard-done">' +
        '<div class="askerp-wizard-done-icon">✅</div>' +
        '<h2>' + __("Your AI Assistant is Ready!") + '</h2>' +
        '<p>' + __("Look for the chat bubble in the bottom-right corner of any ERPNext page. Click it to start chatting with your data.") + '</p>' +
        '<div class="askerp-wizard-try-prompt">' +
          '💡 <strong>' + __("Try asking:") + '</strong> "' + __("What are my pending approvals?") + '" ' + __("or") + ' "' + __("Show me this month's revenue") + '"' +
        '</div>' +
      '</div>';
  }


  // ─── Step Footers ───────────────────────────────────────────────

  function getStepFooter(step) {
    switch (step) {
      case 1:
        return '' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-skip" onclick="window._askerpWizardDismiss()">' + __("Set up later") + '</button>' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-primary" onclick="window._askerpWizardNext()">' + __("Get Started") + ' →</button>';
      case 2:
        return '' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-secondary" onclick="window._askerpWizardPrev()">← ' + __("Back") + '</button>' +
          '<div>' +
            '<button class="askerp-wizard-btn askerp-wizard-btn-skip" onclick="window._askerpWizardSkipStep()">' + __("Skip for now") + '</button>' +
            '<button class="askerp-wizard-btn askerp-wizard-btn-primary" id="askerp-wizard-step2-next" ' +
              (validatedApiKey ? "" : "disabled") +
              ' onclick="window._askerpWizardSaveApiKey()">' + __("Save & Continue") + ' →</button>' +
          '</div>';
      case 3:
        return '' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-secondary" onclick="window._askerpWizardPrev()">← ' + __("Back") + '</button>' +
          '<div>' +
            '<button class="askerp-wizard-btn askerp-wizard-btn-skip" onclick="window._askerpWizardSkipStep()">' + __("Skip for now") + '</button>' +
            '<button class="askerp-wizard-btn askerp-wizard-btn-primary" onclick="window._askerpWizardSaveProfile()">' + __("Save & Continue") + ' →</button>' +
          '</div>';
      case 4:
        return '' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-secondary" onclick="window._askerpWizardPrev()">← ' + __("Back") + '</button>' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-primary" onclick="window._askerpWizardSaveUsers()">' + __("Enable & Continue") + ' →</button>';
      case 5:
        return '' +
          '<div></div>' +
          '<button class="askerp-wizard-btn askerp-wizard-btn-primary" onclick="window._askerpWizardFinish()" style="padding: 12px 32px; font-size: 15px;">' + __("Open AI Chat") + ' ✨</button>';
      default:
        return "";
    }
  }


  // ─── Event Binding ──────────────────────────────────────────────

  function bindStepEvents(step) {
    if (step === 2) {
      // Provider card selection
      var cards = $wizard.querySelectorAll(".askerp-wizard-provider-card");
      cards.forEach(function (card) {
        card.addEventListener("click", function () {
          cards.forEach(function (c) { c.classList.remove("selected"); });
          card.classList.add("selected");
          selectedProvider = card.getAttribute("data-provider");
          var apiSection = document.getElementById("askerp-wizard-api-section");
          if (apiSection) apiSection.classList.add("visible");
          var apiInput = document.getElementById("askerp-wizard-api-key");
          if (apiInput) {
            apiInput.placeholder = __("Enter your {0} API key...", [selectedProvider]);
            apiInput.focus();
          }
        });
      });

      // Test button
      var testBtn = document.getElementById("askerp-wizard-test-btn");
      if (testBtn) {
        testBtn.addEventListener("click", _testConnection);
      }
    }

    if (step === 4) {
      _loadUsers();

      // Search filter
      var searchInput = document.getElementById("askerp-wizard-user-search");
      if (searchInput) {
        searchInput.addEventListener("input", function () {
          _filterUsers(searchInput.value);
        });
      }

      // Select all
      var selectAllBtn = document.getElementById("askerp-wizard-select-all");
      if (selectAllBtn) {
        selectAllBtn.addEventListener("click", _toggleSelectAll);
      }
    }
  }


  // ─── Step 2: API Key Test ───────────────────────────────────────

  function _testConnection() {
    var apiKey = (document.getElementById("askerp-wizard-api-key") || {}).value || "";
    apiKey = apiKey.trim();
    if (!apiKey) {
      _showTestResult(false, __("Please enter an API key."));
      return;
    }
    if (!selectedProvider) {
      _showTestResult(false, __("Please select a provider first."));
      return;
    }

    var testBtn = document.getElementById("askerp-wizard-test-btn");
    if (testBtn) {
      testBtn.classList.add("testing");
      testBtn.textContent = __("Testing...");
      testBtn.disabled = true;
    }

    frappe.call({
      method: "askerp.setup_wizard.test_api_key",
      args: { provider: selectedProvider, api_key: apiKey },
      async: true,
      callback: function (r) {
        if (testBtn) {
          testBtn.classList.remove("testing");
          testBtn.textContent = __("Test Connection");
          testBtn.disabled = false;
        }

        if (r && r.message) {
          _showTestResult(r.message.success, r.message.message);
          if (r.message.success) {
            validatedApiKey = apiKey;
            var nextBtn = document.getElementById("askerp-wizard-step2-next");
            if (nextBtn) nextBtn.disabled = false;
          }
        } else {
          _showTestResult(false, __("No response from server."));
        }
      },
      error: function () {
        if (testBtn) {
          testBtn.classList.remove("testing");
          testBtn.textContent = __("Test Connection");
          testBtn.disabled = false;
        }
        _showTestResult(false, __("Server error. Please try again."));
      }
    });
  }

  function _showTestResult(success, message) {
    var resultDiv = document.getElementById("askerp-wizard-test-result");
    if (!resultDiv) return;
    resultDiv.className = "askerp-wizard-test-result " + (success ? "success" : "error");
    resultDiv.textContent = (success ? "✅ " : "❌ ") + message;
    resultDiv.style.display = "block";
  }


  // ─── Step 4: User Management ────────────────────────────────────

  function _loadUsers() {
    frappe.call({
      method: "askerp.setup_wizard.get_users_for_enablement",
      async: true,
      callback: function (r) {
        if (r && r.message) {
          userList = r.message;
          _renderUserList(userList);
        } else {
          var listDiv = document.getElementById("askerp-wizard-user-list");
          if (listDiv) listDiv.innerHTML = '<div style="padding:20px; text-align:center; color:#999;">' + __("No users found.") + '</div>';
        }
      },
      error: function () {
        var listDiv = document.getElementById("askerp-wizard-user-list");
        if (listDiv) listDiv.innerHTML = '<div style="padding:20px; text-align:center; color:#dc3545;">' + __("Failed to load users.") + '</div>';
      }
    });
  }

  function _renderUserList(users) {
    var listDiv = document.getElementById("askerp-wizard-user-list");
    if (!listDiv) return;

    if (!users || users.length === 0) {
      listDiv.innerHTML = '<div style="padding:20px; text-align:center; color:#999;">' + __("No users found.") + '</div>';
      return;
    }

    var html = "";
    users.forEach(function (u) {
      var checked = u.allow_ai_chat ? "checked" : "";
      var initials = (u.full_name || u.name || "?").split(" ").map(function (w) { return w[0] || ""; }).join("").substring(0, 2).toUpperCase();
      var avatarContent = u.user_image
        ? '<img src="' + _escHtml(u.user_image) + '" alt="">'
        : initials;

      html += '<div class="askerp-wizard-user-row" data-user="' + _escHtml(u.name) + '">';
      html += '<input type="checkbox" class="askerp-wizard-user-check" data-user="' + _escHtml(u.name) + '" ' + checked + '>';
      html += '<div class="askerp-wizard-user-avatar">' + avatarContent + '</div>';
      html += '<div class="askerp-wizard-user-info">';
      html += '<div class="askerp-wizard-user-name">' + _escHtml(u.full_name || u.name) + '</div>';
      html += '<div class="askerp-wizard-user-email">' + _escHtml(u.name) + '</div>';
      html += '</div>';
      html += '</div>';
    });

    listDiv.innerHTML = html;

    // Click on row toggles checkbox
    listDiv.querySelectorAll(".askerp-wizard-user-row").forEach(function (row) {
      row.addEventListener("click", function (e) {
        if (e.target.classList.contains("askerp-wizard-user-check")) return;
        var cb = row.querySelector(".askerp-wizard-user-check");
        if (cb) cb.checked = !cb.checked;
        _updateUserCount();
      });
    });

    listDiv.querySelectorAll(".askerp-wizard-user-check").forEach(function (cb) {
      cb.addEventListener("change", _updateUserCount);
    });

    _updateUserCount();
  }

  function _filterUsers(query) {
    query = (query || "").toLowerCase();
    var filtered = userList.filter(function (u) {
      return (u.full_name || "").toLowerCase().indexOf(query) >= 0 ||
             (u.name || "").toLowerCase().indexOf(query) >= 0;
    });
    _renderUserList(filtered);
  }

  function _toggleSelectAll() {
    var listDiv = document.getElementById("askerp-wizard-user-list");
    if (!listDiv) return;
    var checkboxes = listDiv.querySelectorAll(".askerp-wizard-user-check");
    var allChecked = Array.from(checkboxes).every(function (cb) { return cb.checked; });
    checkboxes.forEach(function (cb) { cb.checked = !allChecked; });
    var btn = document.getElementById("askerp-wizard-select-all");
    if (btn) btn.textContent = allChecked ? __("Select All") : __("Deselect All");
    _updateUserCount();
  }

  function _updateUserCount() {
    var listDiv = document.getElementById("askerp-wizard-user-list");
    var countDiv = document.getElementById("askerp-wizard-user-count");
    if (!listDiv || !countDiv) return;
    var checked = listDiv.querySelectorAll(".askerp-wizard-user-check:checked").length;
    var total = listDiv.querySelectorAll(".askerp-wizard-user-check").length;
    countDiv.textContent = __("{0} of {1} users selected for AI access", [checked, total]);
  }


  // ─── Navigation Actions (exposed globally) ─────────────────────

  window._askerpWizardNext = function () {
    currentStep++;
    if (currentStep > totalSteps) currentStep = totalSteps;
    renderStep();
  };

  window._askerpWizardPrev = function () {
    currentStep--;
    if (currentStep < 1) currentStep = 1;
    renderStep();
  };

  window._askerpWizardSkipStep = function () {
    currentStep++;
    if (currentStep > totalSteps) currentStep = totalSteps;
    renderStep();
  };

  window._askerpWizardDismiss = function () {
    dismissWizard();
  };

  window._askerpWizardSaveApiKey = function () {
    if (!selectedProvider || !validatedApiKey) {
      frappe.show_alert({ message: __("Please test your API key first."), indicator: "orange" });
      return;
    }

    frappe.call({
      method: "askerp.setup_wizard.save_api_key",
      args: { provider: selectedProvider, api_key: validatedApiKey },
      async: true,
      callback: function (r) {
        if (r && r.message && r.message.success) {
          frappe.show_alert({
            message: __("{0} model(s) configured!", [r.message.models_updated]),
            indicator: "green"
          });
          currentStep = 3;
          renderStep();
        } else {
          frappe.show_alert({ message: __("Failed to save API key."), indicator: "red" });
        }
      },
      error: function () {
        frappe.show_alert({ message: __("Server error. Please try again."), indicator: "red" });
      }
    });
  };

  window._askerpWizardSaveProfile = function () {
    var company = (document.getElementById("askerp-wizard-company") || {}).value || "";
    var industry = (document.getElementById("askerp-wizard-industry") || {}).value || "";
    var desc = (document.getElementById("askerp-wizard-description") || {}).value || "";

    if (!company.trim()) {
      frappe.show_alert({ message: __("Company name is required."), indicator: "orange" });
      return;
    }

    frappe.call({
      method: "askerp.setup_wizard.save_quick_profile",
      args: {
        company_name: company.trim(),
        industry: industry,
        description: desc.trim()
      },
      async: true,
      callback: function (r) {
        if (r && r.message && r.message.success) {
          frappe.show_alert({ message: __("Business profile saved!"), indicator: "green" });
          currentStep = 4;
          renderStep();
        }
      },
      error: function () {
        frappe.show_alert({ message: __("Failed to save profile."), indicator: "red" });
      }
    });
  };

  window._askerpWizardSaveUsers = function () {
    var listDiv = document.getElementById("askerp-wizard-user-list");
    if (!listDiv) { currentStep = 5; renderStep(); return; }

    var checkboxes = listDiv.querySelectorAll(".askerp-wizard-user-check");
    var updates = [];
    checkboxes.forEach(function (cb) {
      updates.push({
        user: cb.getAttribute("data-user"),
        enabled: cb.checked ? 1 : 0
      });
    });

    if (updates.length === 0) {
      currentStep = 5;
      renderStep();
      return;
    }

    frappe.call({
      method: "askerp.setup_wizard.bulk_enable_ai_chat",
      args: { user_list: JSON.stringify(updates) },
      async: true,
      callback: function (r) {
        if (r && r.message && r.message.success) {
          frappe.show_alert({
            message: __("{0} user(s) enabled for AI chat!", [r.message.enabled_count]),
            indicator: "green"
          });
          currentStep = 5;
          renderStep();
        }
      },
      error: function () {
        frappe.show_alert({ message: __("Failed to update users."), indicator: "red" });
      }
    });
  };

  window._askerpWizardFinish = function () {
    frappe.call({
      method: "askerp.setup_wizard.complete_setup",
      async: true,
      callback: function () {
        closeWizard();
        frappe.show_alert({
          message: __("AI Assistant is ready! Look for the chat bubble") + " →",
          indicator: "green"
        });
        // Trigger a page reload so chat widget initializes with the new state
        setTimeout(function () {
          window.location.reload();
        }, 1500);
      }
    });
  };


  // ─── Notification Bar ───────────────────────────────────────────

  function showNotification() {
    removeNotification();

    var bar = document.createElement("div");
    bar.className = "askerp-wizard-notification";
    bar.id = "askerp-wizard-notification";
    bar.innerHTML = '' +
      '<span>🤖 ' + __("AI Assistant setup is incomplete") + '</span>' +
      '<button class="askerp-wizard-notification-btn" id="askerp-wizard-notif-resume">' + __("Continue Setup") + '</button>' +
      '<button class="askerp-wizard-notification-dismiss" id="askerp-wizard-notif-dismiss">×</button>';

    document.body.appendChild(bar);

    document.getElementById("askerp-wizard-notif-resume").addEventListener("click", function () {
      removeNotification();
      // Get current step from boot data
      var startStep = 1;
      try {
        startStep = (frappe.boot.askerp_setup_step || 0) + 1;
        if (startStep < 1) startStep = 1;
        if (startStep > 5) startStep = 1;
      } catch (e) { /* ignore */ }
      showWizard(startStep);
    });

    document.getElementById("askerp-wizard-notif-dismiss").addEventListener("click", function () {
      removeNotification();
      // Remember dismissal for this session
      try { sessionStorage.setItem("askerp_wizard_dismissed", "1"); } catch (e) { /* ignore */ }
    });
  }

  function removeNotification() {
    var existing = document.getElementById("askerp-wizard-notification");
    if (existing) existing.remove();
  }


  // ─── Utility ────────────────────────────────────────────────────

  function _escHtml(str) {
    if (!str) return "";
    var div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }


  // ─── Boot ───────────────────────────────────────────────────────

  function init() {
    if (!window.frappe || !frappe.session || !frappe.session.user) {
      setTimeout(init, 500);
      return;
    }

    if (frappe.session.user === "Guest") return;

    // Check boot data for setup status
    var setupComplete = true;
    var setupStep = 0;
    try {
      setupComplete = frappe.boot.askerp_setup_complete;
      setupStep = frappe.boot.askerp_setup_step || 0;
    } catch (e) {
      // Boot data not available — check via API
      frappe.call({
        method: "askerp.setup_wizard.get_setup_status",
        async: true,
        callback: function (r) {
          if (r && r.message && r.message.show_wizard) {
            _handleSetupIncomplete(r.message.current_step);
          }
        }
      });
      return;
    }

    if (!setupComplete) {
      _handleSetupIncomplete(setupStep);
    }
  }

  function _handleSetupIncomplete(setupStep) {
    // Check if user is admin
    var roles = [];
    try { roles = frappe.user_roles || []; } catch (e) { /* ignore */ }
    if (roles.indexOf("System Manager") < 0 && roles.indexOf("Administrator") < 0) return;

    // Check if dismissed this session
    try {
      if (sessionStorage.getItem("askerp_wizard_dismissed") === "1") {
        showNotification();
        return;
      }
    } catch (e) { /* ignore */ }

    // Auto-show wizard on first visit
    var startStep = (setupStep || 0) + 1;
    if (startStep < 1) startStep = 1;
    if (startStep > 5) startStep = 1;

    // Small delay to let the page finish rendering
    setTimeout(function () {
      showWizard(startStep);
    }, 1500);
  }


  // ─── Expose for manual trigger ──────────────────────────────────
  window.askerpSetupWizard = {
    show: function (step) { showWizard(step || 1); },
    reset: function () {
      frappe.call({
        method: "askerp.setup_wizard.reset_setup",
        callback: function (r) {
          if (r && r.message) frappe.show_alert({ message: r.message.message, indicator: "green" });
        }
      });
    }
  };


  // ─── Auto-init ──────────────────────────────────────────────────
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(init, 1000);
    });
  } else {
    setTimeout(init, 1000);
  }

})();
