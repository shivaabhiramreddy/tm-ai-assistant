/**
 * AskERP — ERPNext Chat Widget
 * ======================================
 * Intercom + LinkedIn messaging style floating chat widget.
 * Injected on every ERPNext page via hooks.py app_include_js.
 *
 * Self-contained: creates its own DOM, manages its own state,
 * calls existing API endpoints, reads frappe.session for auth.
 */

(function () {
  "use strict";

  // ─── SVG Icons ──────────────────────────────────────────────────
  const ICONS = {
    sparkle: `<svg viewBox="0 0 24 24"><path d="M12 2L9.19 8.63L2 9.24l5.46 4.73L5.82 21L12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2z"/></svg>`,
    send: `<svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>`,
    close: `<svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`,
    minimize: `<svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14v2z"/></svg>`,
    maximize: `<svg viewBox="0 0 24 24"><path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>`,
    newchat: `<svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>`,
    gear: `<svg viewBox="0 0 24 24"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 00.12-.61l-1.92-3.32a.49.49 0 00-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.48.48 0 00-.48-.41h-3.84a.48.48 0 00-.48.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96a.49.49 0 00-.59.22L2.74 8.87a.48.48 0 00.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58a.49.49 0 00-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.26.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6A3.6 3.6 0 1115.6 12 3.611 3.611 0 0112 15.6z"/></svg>`,
    loading: `<svg viewBox="0 0 24 24"><path d="M12 4V2A10 10 0 0 0 2 12h2a8 8 0 0 1 8-8z"/></svg>`,
    copy: `<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>`,
    whatsapp: `<svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>`,
    email: `<svg viewBox="0 0 24 24"><path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>`,
    share: `<svg viewBox="0 0 24 24"><path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z"/></svg>`,
    check: `<svg viewBox="0 0 24 24"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`,
    trash: `<svg viewBox="0 0 24 24"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>`,
    back: `<svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>`,
  };

  // ─── State ──────────────────────────────────────────────────────
  const STATE_KEY = "askerp_widget_state";
  let state = {
    isOpen: false,
    isFullscreen: false,
    sessionId: null,
    messages: [],
    isStreaming: false,
    streamId: null,
    pollTimer: null,
    enabled: false,
    dailyLimit: 0,
    dailyUsed: 0,
  };

  // DOM references
  let $bubble, $badge, $panel, $messages, $input, $sendBtn,
      $suggestions, $headerContext, $typingIndicator, $errorBanner;

  // ─── Init ───────────────────────────────────────────────────────
  function init() {
    // Wait for frappe to be fully ready
    if (!window.frappe || !frappe.session || !frappe.session.user) {
      setTimeout(init, 500);
      return;
    }

    // Skip for Guest users
    if (frappe.session.user === "Guest") return;

    // Check if the user has AI access
    frappe.call({
      method: "askerp.api.chat_status",
      async: true,
      callback: function (r) {
        if (r && r.message && r.message.enabled) {
          state.enabled = true;
          state.dailyLimit = r.message.daily_limit || 50;
          state.dailyUsed = r.message.daily_used || 0;
          state.sessionId = r.message.active_session_id || null;
          buildWidget();
          restoreState();
          bindKeyboardShortcut();
          loadSuggestions();
          // Load existing session if any
          if (state.sessionId) {
            loadSession(state.sessionId);
          }
        }
        // If not enabled, don't build the widget — user won't see anything
      },
      error: function () {
        // Silently fail — AI assistant not available
      }
    });
  }

  // ─── Build DOM ──────────────────────────────────────────────────
  function buildWidget() {
    // Bubble
    $bubble = el("button", { class: "askerp-bubble askerp-pulse", title: __("AI Assistant") + " (Ctrl+Shift+A)" });
    $bubble.innerHTML = ICONS.sparkle;
    $bubble.onclick = togglePanel;

    $badge = el("span", { class: "askerp-badge askerp-hidden" });
    $bubble.appendChild($badge);

    // Panel
    $panel = el("div", { class: "askerp-panel" });

    // Header
    const header = el("div", { class: "askerp-header" });
    const headerLeft = el("div", { class: "askerp-header-left" });
    const avatar = el("div", { class: "askerp-header-avatar" });
    avatar.innerHTML = ICONS.sparkle;
    const headerInfo = el("div", { class: "askerp-header-info" });
    const headerTitle = el("span", { class: "askerp-header-title" });
    headerTitle.textContent = __("AI Assistant");
    $headerContext = el("span", { class: "askerp-header-context" });
    $headerContext.textContent = detectContext().label || __("Ask me anything");
    headerInfo.appendChild(headerTitle);
    headerInfo.appendChild($headerContext);
    headerLeft.appendChild(avatar);
    headerLeft.appendChild(headerInfo);

    const headerActions = el("div", { class: "askerp-header-actions" });

    const newChatBtn = el("button", { class: "askerp-header-btn", title: __("New Chat") });
    newChatBtn.innerHTML = ICONS.newchat;
    newChatBtn.onclick = startNewChat;

    const prefsBtn = el("button", { class: "askerp-header-btn", title: __("Preferences") });
    prefsBtn.innerHTML = ICONS.gear;
    prefsBtn.onclick = openPreferencesPanel;

    const maximizeBtn = el("button", { class: "askerp-header-btn", title: __("Fullscreen") });
    maximizeBtn.innerHTML = ICONS.maximize;
    maximizeBtn.onclick = toggleFullscreen;

    const minimizeBtn = el("button", { class: "askerp-header-btn", title: __("Minimize") });
    minimizeBtn.innerHTML = ICONS.minimize;
    minimizeBtn.onclick = togglePanel;

    const closeBtn = el("button", { class: "askerp-header-btn", title: __("Close") });
    closeBtn.innerHTML = ICONS.close;
    closeBtn.onclick = closePanel;

    headerActions.appendChild(newChatBtn);
    headerActions.appendChild(prefsBtn);
    headerActions.appendChild(maximizeBtn);
    headerActions.appendChild(minimizeBtn);
    headerActions.appendChild(closeBtn);

    header.appendChild(headerLeft);
    header.appendChild(headerActions);

    // Error banner (hidden by default)
    $errorBanner = el("div", { class: "askerp-error", style: "display:none" });

    // Messages container
    $messages = el("div", { class: "askerp-messages" });
    showWelcome();

    // Suggestions
    $suggestions = el("div", { class: "askerp-suggestions" });

    // Input area
    const inputArea = el("div", { class: "askerp-input-area" });
    $input = el("textarea", {
      class: "askerp-input",
      placeholder: __("Ask about your business data..."),
      rows: "1",
      maxlength: "2000",
    });
    $input.onkeydown = handleInputKey;
    $input.oninput = autoResize;

    $sendBtn = el("button", { class: "askerp-send-btn", title: __("Send") });
    $sendBtn.innerHTML = ICONS.send;
    $sendBtn.onclick = sendMessage;

    inputArea.appendChild($input);
    inputArea.appendChild($sendBtn);

    // Assemble panel
    $panel.appendChild(header);
    $panel.appendChild($errorBanner);
    $panel.appendChild($messages);
    $panel.appendChild($suggestions);
    $panel.appendChild(inputArea);

    // Add to page
    document.body.appendChild($bubble);
    document.body.appendChild($panel);

    // Update context on Frappe page change
    if (frappe.router && frappe.router.on) {
      frappe.router.on("change", updateContext);
    }
    // Fallback: listen to hashchange
    window.addEventListener("hashchange", updateContext);
  }

  // ─── Panel Toggle ───────────────────────────────────────────────
  function togglePanel() {
    if (state.isOpen) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function openPanel() {
    state.isOpen = true;
    $panel.classList.add("askerp-open");
    $bubble.classList.add("askerp-hidden");
    $bubble.classList.remove("askerp-pulse");
    $input.focus();
    updateContext();
    saveState();
    scrollToBottom();
  }

  function closePanel() {
    state.isOpen = false;
    state.isFullscreen = false;
    $panel.classList.remove("askerp-open", "askerp-fullscreen");
    $bubble.classList.remove("askerp-hidden");
    saveState();
  }

  function toggleFullscreen() {
    state.isFullscreen = !state.isFullscreen;
    $panel.classList.toggle("askerp-fullscreen", state.isFullscreen);
    saveState();
  }

  // ─── Context Detection ──────────────────────────────────────────
  function detectContext() {
    const route = frappe.get_route();
    if (!route || !route.length) return { doctype: null, name: null, label: __("Dashboard") };

    const view = route[0]; // "Form", "List", "Report", etc.
    const doctype = route[1] || null;
    const name = route[2] || null;

    if (view === "Form" && doctype && name) {
      return { doctype, name, label: __("{0}: {1}", [doctype, name]) };
    }
    if (view === "List" && doctype) {
      return { doctype, name: null, label: __("{0} List", [doctype]) };
    }
    if (view === "Report" && doctype) {
      return { doctype, name: null, label: __("Report: {0}", [doctype]) };
    }
    if (view === "modules") {
      return { doctype: null, name: null, label: __("Modules") };
    }
    return { doctype, name, label: doctype || __("Home") };
  }

  function updateContext() {
    if ($headerContext) {
      const ctx = detectContext();
      $headerContext.textContent = ctx.label || __("Ask me anything");
    }
    // Refresh suggestions on page change
    loadSuggestions();
  }

  // ─── Messages ───────────────────────────────────────────────────
  function addMessage(role, content) {
    // Remove welcome if first message
    const welcome = $messages.querySelector(".askerp-welcome");
    if (welcome) welcome.remove();

    const msg = el("div", { class: `askerp-msg askerp-${role}` });
    const bubble = el("div", { class: "askerp-msg-content" });

    if (role === "assistant") {
      bubble.innerHTML = renderMarkdown(content);
    } else {
      bubble.textContent = content;
    }

    msg.appendChild(bubble);

    // Add action bar for assistant messages (copy, share, WhatsApp, email)
    // Skip for empty content (streaming start — action bar added on stream complete)
    if (role === "assistant" && content) {
      msg.appendChild(buildMessageActions(content));
    }

    $messages.appendChild(msg);
    scrollToBottom();

    state.messages.push({ role, content });
    return bubble;
  }

  // ─── Message Action Bar ──────────────────────────────────────
  function buildMessageActions(rawText) {
    const bar = el("div", { class: "askerp-msg-actions" });

    // Copy button
    const copyBtn = el("button", { class: "askerp-action-btn", title: __("Copy") });
    copyBtn.innerHTML = ICONS.copy;
    copyBtn.onclick = function () { copyToClipboard(rawText, copyBtn); };
    bar.appendChild(copyBtn);

    // WhatsApp share button
    const waBtn = el("button", { class: "askerp-action-btn", title: __("Share via WhatsApp") });
    waBtn.innerHTML = ICONS.whatsapp;
    waBtn.onclick = function () { shareViaWhatsApp(rawText); };
    bar.appendChild(waBtn);

    // Email share button
    const emailBtn = el("button", { class: "askerp-action-btn", title: __("Share via Email") });
    emailBtn.innerHTML = ICONS.email;
    emailBtn.onclick = function () { shareViaEmail(rawText); };
    bar.appendChild(emailBtn);

    // Native Share API (if supported by the browser)
    if (navigator.share) {
      const shareBtn = el("button", { class: "askerp-action-btn", title: __("Share") });
      shareBtn.innerHTML = ICONS.share;
      shareBtn.onclick = function () { shareNative(rawText); };
      bar.appendChild(shareBtn);
    }

    return bar;
  }

  function copyToClipboard(text, btn) {
    if (!text) return;

    // Use modern Clipboard API with fallback
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showCopyFeedback(btn);
      }).catch(function () {
        fallbackCopy(text, btn);
      });
    } else {
      fallbackCopy(text, btn);
    }
  }

  function fallbackCopy(text, btn) {
    // Fallback for older browsers or non-HTTPS contexts
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.cssText = "position:fixed;left:-9999px;top:-9999px;opacity:0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      showCopyFeedback(btn);
    } catch (e) {
      // Silent fail
    }
    document.body.removeChild(textarea);
  }

  function showCopyFeedback(btn) {
    // Swap icon to checkmark briefly
    const originalHTML = btn.innerHTML;
    btn.innerHTML = ICONS.check;
    btn.classList.add("askerp-action-success");
    setTimeout(function () {
      btn.innerHTML = originalHTML;
      btn.classList.remove("askerp-action-success");
    }, 1500);
  }

  function shareViaWhatsApp(text) {
    if (!text) return;
    // Truncate to WhatsApp's practical URL limit (~2000 chars)
    const truncated = text.length > 1800
      ? text.substring(0, 1800) + "..."
      : text;
    const url = "https://wa.me/?text=" + encodeURIComponent(truncated);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function shareViaEmail(text) {
    if (!text) return;
    const subject = __("Business Insight from AskERP");
    // Truncate to stay within mailto URI limits
    const truncated = text.length > 1800
      ? text.substring(0, 1800) + "..."
      : text;
    const url = "mailto:?subject=" + encodeURIComponent(subject)
      + "&body=" + encodeURIComponent(truncated);
    window.location.href = url;
  }

  function shareNative(text) {
    if (!text || !navigator.share) return;
    navigator.share({
      title: __("AskERP Insight"),
      text: text,
    }).catch(function () {
      // User cancelled or share failed — silent
    });
  }

  function showTyping(statusText) {
    removeTyping();
    $typingIndicator = el("div", { class: "askerp-typing" });
    if (statusText) {
      $typingIndicator.innerHTML = `<span class="askerp-tool-status">${ICONS.loading} ${escapeHtml(statusText)}</span>`;
    } else {
      $typingIndicator.innerHTML = `<span class="askerp-typing-dots"><span></span><span></span><span></span></span><span>${__("Thinking...")}</span>`;
    }
    $messages.appendChild($typingIndicator);
    scrollToBottom();
  }

  function removeTyping() {
    if ($typingIndicator) {
      $typingIndicator.remove();
      $typingIndicator = null;
    }
  }

  function showWelcome() {
    const w = el("div", { class: "askerp-welcome" });
    const icon = el("div", { class: "askerp-welcome-icon" });
    icon.innerHTML = ICONS.sparkle;
    const h3 = el("h3");
    h3.textContent = __("AI Business Assistant");
    const p = el("p");
    p.textContent = __("Ask questions about your sales, inventory, finances, and more. I can analyze data, generate reports, and provide insights.");
    w.appendChild(icon);
    w.appendChild(h3);
    w.appendChild(p);
    $messages.appendChild(w);
  }

  function showError(msg) {
    $errorBanner.textContent = msg;
    $errorBanner.style.display = "block";
    setTimeout(() => { $errorBanner.style.display = "none"; }, 8000);
  }

  // ─── Send Message ───────────────────────────────────────────────
  function sendMessage() {
    const text = ($input.value || "").trim();
    if (!text || state.isStreaming) return;

    // Add user message
    addMessage("user", text);
    $input.value = "";
    autoResize();
    $sendBtn.disabled = true;

    // Show typing indicator
    showTyping();

    // Hide suggestions during streaming
    $suggestions.innerHTML = "";

    state.isStreaming = true;

    // Call chat_start for streaming
    frappe.call({
      method: "askerp.api.chat_start",
      args: {
        message: text,
        session_id: state.sessionId || undefined,
      },
      async: true,
      callback: function (r) {
        if (!r || !r.message) {
          finishStreaming(__("Something went wrong. Please try again."));
          return;
        }

        const data = r.message;

        // Handle clarification (Sprint 6B)
        if (data.needs_clarification) {
          removeTyping();
          state.isStreaming = false;
          $sendBtn.disabled = false;
          state.sessionId = data.session_id;
          addMessage("assistant", data.clarification_question);
          // Show clarification options as chips
          if (data.clarification_options) {
            showClarificationChips(data.clarification_options);
          }
          return;
        }

        // Handle budget exceeded
        if (data.budget_exceeded) {
          finishStreaming(data.error || __("Monthly budget exceeded."));
          return;
        }

        // Handle error
        if (data.error) {
          finishStreaming(data.error);
          return;
        }

        // Start polling for stream
        state.streamId = data.stream_id;
        state.sessionId = data.session_id;
        startPolling();
      },
      error: function (err) {
        const msg = (err && err.message) || __("Failed to connect to AI. Please try again.");
        finishStreaming(msg);
      }
    });
  }

  // ─── Streaming Poll ─────────────────────────────────────────────
  function startPolling() {
    let lastLength = 0;
    let assistantBubble = null;

    function poll() {
      if (!state.streamId) return;

      frappe.call({
        method: "askerp.api.stream_poll",
        args: {
          stream_id: state.streamId,
          last_length: lastLength,
        },
        async: true,
        callback: function (r) {
          if (!r || !r.message) {
            finishStreaming(__("Stream connection lost."));
            return;
          }

          const data = r.message;

          // Show tool status
          if (data.tool_status && !data.done) {
            showTyping(data.tool_status);
          }

          // Append new text
          if (data.delta) {
            removeTyping();
            if (!assistantBubble) {
              assistantBubble = addMessage("assistant", "");
            }
            // Update the full text (re-render markdown)
            assistantBubble.innerHTML = renderMarkdown(data.text);
            lastLength = data.text_length;
            scrollToBottom();
          }

          // Check if done
          if (data.done) {
            removeTyping();
            if (data.error) {
              if (!assistantBubble) {
                addMessage("assistant", data.error);
              }
            } else if (!assistantBubble && data.text) {
              // If we never got deltas but have final text
              addMessage("assistant", data.text);
            } else if (assistantBubble && data.text) {
              // Streaming complete — add action bar to the streamed message
              var msgEl = assistantBubble.closest(".askerp-msg");
              if (msgEl && !msgEl.querySelector(".askerp-msg-actions")) {
                msgEl.appendChild(buildMessageActions(data.text));
              }
            }
            state.isStreaming = false;
            state.streamId = null;
            $sendBtn.disabled = false;

            // Update session title from response
            if (data.session_title) {
              // Could update header, but keeping it simple
            }

            // Refresh suggestions
            const lastQ = state.messages.filter(m => m.role === "user").pop();
            const lastA = state.messages.filter(m => m.role === "assistant").pop();
            loadSuggestions(
              lastQ ? lastQ.content : null,
              lastA ? lastA.content : null
            );
            return;
          }

          // Continue polling (300ms interval for smooth streaming)
          state.pollTimer = setTimeout(poll, 300);
        },
        error: function () {
          finishStreaming(__("Connection error. Please try again."));
        }
      });
    }

    poll();
  }

  function finishStreaming(errorMsg) {
    removeTyping();
    state.isStreaming = false;
    state.streamId = null;
    $sendBtn.disabled = false;
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    if (errorMsg) {
      showError(errorMsg);
    }
    loadSuggestions();
  }

  // ─── Session Management ─────────────────────────────────────────
  function loadSession(sessionId) {
    frappe.call({
      method: "askerp.api.get_session",
      args: { session_id: sessionId },
      async: true,
      callback: function (r) {
        if (r && r.message && r.message.messages) {
          // Clear welcome
          $messages.innerHTML = "";
          const msgs = r.message.messages;
          msgs.forEach(function (m) {
            addMessage(m.role, m.content);
          });
          scrollToBottom();
        }
      }
    });
  }

  function startNewChat() {
    // Close current session
    if (state.sessionId) {
      frappe.call({
        method: "askerp.api.close_session",
        args: { session_id: state.sessionId },
        async: true,
      });
    }
    // Reset
    state.sessionId = null;
    state.messages = [];
    $messages.innerHTML = "";
    showWelcome();
    loadSuggestions();
    $input.focus();
  }

  // ─── Suggestions ────────────────────────────────────────────────
  function loadSuggestions(lastQuery, lastResponse) {
    const ctx = detectContext();
    const screenContext = ctx.doctype
      ? ctx.doctype.toLowerCase().replace(/\s+/g, "_")
      : "dashboard";

    frappe.call({
      method: "askerp.api.get_suggestions",
      args: {
        last_query: lastQuery || null,
        last_response: lastResponse ? lastResponse.substring(0, 300) : null,
        screen_context: screenContext,
      },
      async: true,
      callback: function (r) {
        if (r && r.message) {
          renderSuggestions(r.message);
        }
      }
    });
  }

  function renderSuggestions(suggestions) {
    $suggestions.innerHTML = "";
    if (!suggestions || !suggestions.length) return;

    suggestions.slice(0, 4).forEach(function (s) {
      const chip = el("button", { class: "askerp-chip" });
      chip.textContent = s.label;
      chip.title = s.query || s.label;
      chip.onclick = function () {
        $input.value = s.query || s.label;
        sendMessage();
      };
      $suggestions.appendChild(chip);
    });
  }

  function showClarificationChips(options) {
    $suggestions.innerHTML = "";
    options.forEach(function (opt) {
      const chip = el("button", { class: "askerp-chip" });
      chip.textContent = opt;
      chip.onclick = function () {
        $input.value = opt;
        sendMessage();
      };
      $suggestions.appendChild(chip);
    });
  }

  // ─── Markdown Renderer ──────────────────────────────────────────
  function renderMarkdown(text) {
    if (!text) return "";

    let html = escapeHtml(text);

    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      return `<pre><code>${code}</code></pre>`;
    });

    // Inline code (`...`)
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Tables (| col | col |)
    html = html.replace(/((?:\|[^\n]+\|\n?)+)/g, function (table) {
      const rows = table.trim().split("\n").filter(r => r.trim());
      if (rows.length < 2) return table;

      let tableHtml = "<table>";
      rows.forEach(function (row, i) {
        // Skip separator rows (|---|---|)
        if (/^\|[\s-:|]+\|$/.test(row)) return;
        const cells = row.split("|").filter(c => c.trim() !== "");
        const tag = i === 0 ? "th" : "td";
        tableHtml += "<tr>";
        cells.forEach(function (cell) {
          tableHtml += `<${tag}>${cell.trim()}</${tag}>`;
        });
        tableHtml += "</tr>";
      });
      tableHtml += "</table>";
      return tableHtml;
    });

    // Headers
    html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Unordered lists
    html = html.replace(/^[-•] (.+)$/gm, "<li>$1</li>");
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

    // Ordered lists
    html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");

    // Blockquotes
    html = html.replace(/^> (.+)$/gm, "<blockquote>$1</blockquote>");

    // Horizontal rules
    html = html.replace(/^---+$/gm, "<hr>");

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Line breaks (double newline → paragraph break, single → <br>)
    html = html.replace(/\n\n/g, "</p><p>");
    html = html.replace(/\n/g, "<br>");

    // Clean up empty paragraphs around block elements
    html = html.replace(/<p><(h[23]|table|ul|ol|pre|blockquote|hr)/g, "<$1");
    html = html.replace(/<\/(h[23]|table|ul|ol|pre|blockquote)><\/p>/g, "</$1>");

    return html;
  }

  // ─── Input Handling ─────────────────────────────────────────────
  function handleInputKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function autoResize() {
    $input.style.height = "auto";
    $input.style.height = Math.min($input.scrollHeight, 120) + "px";
  }

  // ─── Keyboard Shortcut ──────────────────────────────────────────
  function bindKeyboardShortcut() {
    document.addEventListener("keydown", function (e) {
      // Ctrl+Shift+A or Cmd+Shift+A
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "A") {
        e.preventDefault();
        if (state.enabled) togglePanel();
      }
    });
  }

  // ─── State Persistence ──────────────────────────────────────────
  function saveState() {
    try {
      localStorage.setItem(STATE_KEY, JSON.stringify({
        isOpen: state.isOpen,
        isFullscreen: state.isFullscreen,
        sessionId: state.sessionId,
      }));
    } catch (e) { /* localStorage may be blocked */ }
  }

  function restoreState() {
    try {
      const saved = JSON.parse(localStorage.getItem(STATE_KEY) || "{}");
      if (saved.isOpen) {
        openPanel();
        if (saved.isFullscreen) {
          state.isFullscreen = true;
          $panel.classList.add("askerp-fullscreen");
        }
      }
      if (saved.sessionId && !state.sessionId) {
        state.sessionId = saved.sessionId;
      }
    } catch (e) { /* ignore */ }
  }

  // ─── Utility ────────────────────────────────────────────────────
  function el(tag, attrs) {
    const elem = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        elem.setAttribute(k, attrs[k]);
      });
    }
    return elem;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function scrollToBottom() {
    if ($messages) {
      requestAnimationFrame(function () {
        $messages.scrollTop = $messages.scrollHeight;
      });
    }
  }

  // ─── Preferences Panel ─────────────────────────────────────────

  /** @type {HTMLElement|null} */
  var $prefsOverlay = null;

  /**
   * Opens the preferences panel (replaces the messages area in-place).
   * Fetches current prefs from the server and builds a form.
   */
  function openPreferencesPanel() {
    if ($prefsOverlay) return; // already open

    $prefsOverlay = el("div", { class: "askerp-prefs-overlay" });

    // Header
    var prefsHeader = el("div", { class: "askerp-prefs-header" });
    var backBtn = el("button", { class: "askerp-header-btn askerp-prefs-back", title: __("Back") });
    backBtn.innerHTML = ICONS.back;
    backBtn.onclick = closePreferencesPanel;

    var prefsTitle = el("span", { class: "askerp-prefs-title" });
    prefsTitle.textContent = __("Preferences");

    prefsHeader.appendChild(backBtn);
    prefsHeader.appendChild(prefsTitle);
    $prefsOverlay.appendChild(prefsHeader);

    // Loading
    var prefsBody = el("div", { class: "askerp-prefs-body" });
    prefsBody.innerHTML = '<div class="askerp-prefs-loading">' + ICONS.loading +
      " " + __("Loading preferences...") + "</div>";
    $prefsOverlay.appendChild(prefsBody);

    // Insert overlay after the header in the panel
    var panelHeader = $panel.querySelector(".askerp-header");
    if (panelHeader && panelHeader.nextSibling) {
      $panel.insertBefore($prefsOverlay, panelHeader.nextSibling);
    } else {
      $panel.appendChild($prefsOverlay);
    }

    // Fetch prefs from server
    frappe.call({
      method: "askerp.api.get_preferences",
      callback: function (r) {
        if (r && r.message) {
          renderPreferencesForm(prefsBody, r.message.quick_settings || {}, r.message.preferences || {});
        } else {
          prefsBody.innerHTML = '<div class="askerp-prefs-loading">' + __("Failed to load preferences.") + "</div>";
        }
      },
      error: function () {
        prefsBody.innerHTML = '<div class="askerp-prefs-loading">' + __("Failed to load preferences.") + "</div>";
      },
    });
  }

  function closePreferencesPanel() {
    if ($prefsOverlay) {
      $prefsOverlay.classList.add("askerp-prefs-closing");
      setTimeout(function () {
        if ($prefsOverlay && $prefsOverlay.parentNode) {
          $prefsOverlay.parentNode.removeChild($prefsOverlay);
        }
        $prefsOverlay = null;
      }, 200);
    }
  }

  /**
   * Renders the full preference form inside the given body element.
   * @param {HTMLElement} body - The prefs body container.
   * @param {Object} quickSettings - {response_language, number_format, response_style, default_company}.
   * @param {Object} customPrefs - Free-form key/value pairs learned by AI.
   */
  function renderPreferencesForm(body, quickSettings, customPrefs) {
    body.innerHTML = "";

    // ── Quick Settings Section ──
    var qsSection = el("div", { class: "askerp-prefs-section" });
    var qsHeading = el("div", { class: "askerp-prefs-section-title" });
    qsHeading.textContent = __("Quick Settings");
    qsSection.appendChild(qsHeading);

    // Response Language
    qsSection.appendChild(buildSelectRow(
      __("Response Language"),
      __("Language the AI responds in"),
      "response_language",
      [
        { value: "en", label: "English" },
        { value: "te", label: "Telugu" },
        { value: "hi", label: "Hindi" },
        { value: "ta", label: "Tamil" },
        { value: "kn", label: "Kannada" },
        { value: "ml", label: "Malayalam" },
        { value: "mr", label: "Marathi" },
        { value: "gu", label: "Gujarati" },
      ],
      quickSettings.response_language || "en"
    ));

    // Number Format
    qsSection.appendChild(buildSelectRow(
      __("Number Format"),
      __("How numbers and currency are displayed"),
      "number_format",
      [
        { value: "indian", label: __("Indian (12,34,567)") },
        { value: "international", label: __("International (1,234,567)") },
      ],
      quickSettings.number_format || "indian"
    ));

    // Response Style
    qsSection.appendChild(buildSelectRow(
      __("Response Style"),
      __("How detailed the AI responses are"),
      "response_style",
      [
        { value: "concise", label: __("Concise") },
        { value: "balanced", label: __("Balanced") },
        { value: "detailed", label: __("Detailed") },
      ],
      quickSettings.response_style || "balanced"
    ));

    // Default Company
    var companyOptions = [{ value: "", label: __("Auto-detect") }];
    if (quickSettings.available_companies && quickSettings.available_companies.length) {
      quickSettings.available_companies.forEach(function (c) {
        companyOptions.push({ value: c, label: c });
      });
    }
    qsSection.appendChild(buildSelectRow(
      __("Default Company"),
      __("Company context for queries"),
      "default_company",
      companyOptions,
      quickSettings.default_company || ""
    ));

    // Save Quick Settings button
    var saveRow = el("div", { class: "askerp-prefs-save-row" });
    var saveBtn = el("button", { class: "askerp-prefs-save-btn" });
    saveBtn.textContent = __("Save Settings");
    saveBtn.onclick = function () { saveQuickSettings(saveBtn); };
    saveRow.appendChild(saveBtn);
    qsSection.appendChild(saveRow);

    body.appendChild(qsSection);

    // ── AI-Learned Preferences Section ──
    var customKeys = Object.keys(customPrefs || {});
    var cpSection = el("div", { class: "askerp-prefs-section" });
    var cpHeading = el("div", { class: "askerp-prefs-section-title" });
    cpHeading.textContent = __("AI-Learned Preferences") + " (" + customKeys.length + ")";
    cpSection.appendChild(cpHeading);

    if (customKeys.length === 0) {
      var emptyMsg = el("div", { class: "askerp-prefs-empty" });
      emptyMsg.textContent = __("No custom preferences yet. As you chat, the AI will learn your preferences automatically.");
      cpSection.appendChild(emptyMsg);
    } else {
      customKeys.forEach(function (key) {
        var row = el("div", { class: "askerp-prefs-custom-row" });
        row.setAttribute("data-key", key);

        var keyLabel = el("div", { class: "askerp-prefs-custom-key" });
        keyLabel.textContent = key.replace(/_/g, " ");

        var valLabel = el("div", { class: "askerp-prefs-custom-val" });
        valLabel.textContent = String(customPrefs[key]);

        var delBtn = el("button", { class: "askerp-prefs-del-btn", title: __("Remove") });
        delBtn.innerHTML = ICONS.trash;
        delBtn.onclick = function () { deleteCustomPref(key, row); };

        row.appendChild(keyLabel);
        row.appendChild(valLabel);
        row.appendChild(delBtn);
        cpSection.appendChild(row);
      });

      // Clear All button
      var clearRow = el("div", { class: "askerp-prefs-save-row" });
      var clearBtn = el("button", { class: "askerp-prefs-clear-btn" });
      clearBtn.textContent = __("Clear All Preferences");
      clearBtn.onclick = function () { clearAllPreferences(clearBtn); };
      clearRow.appendChild(clearBtn);
      cpSection.appendChild(clearRow);
    }

    body.appendChild(cpSection);
  }

  /**
   * Builds a labeled select row for quick settings.
   */
  function buildSelectRow(label, description, fieldKey, options, currentValue) {
    var row = el("div", { class: "askerp-prefs-row" });

    var labelWrap = el("div", { class: "askerp-prefs-label-wrap" });
    var labelEl = el("div", { class: "askerp-prefs-label" });
    labelEl.textContent = label;
    var descEl = el("div", { class: "askerp-prefs-desc" });
    descEl.textContent = description;
    labelWrap.appendChild(labelEl);
    labelWrap.appendChild(descEl);

    var selectEl = el("select", { class: "askerp-prefs-select", "data-field": fieldKey });
    options.forEach(function (opt) {
      var optEl = el("option", { value: opt.value });
      optEl.textContent = opt.label;
      if (opt.value === currentValue) {
        optEl.setAttribute("selected", "selected");
      }
      selectEl.appendChild(optEl);
    });

    row.appendChild(labelWrap);
    row.appendChild(selectEl);
    return row;
  }

  /**
   * Saves quick settings to the server.
   */
  function saveQuickSettings(btn) {
    btn.disabled = true;
    btn.textContent = __("Saving...");

    var payload = {};
    var selects = $prefsOverlay.querySelectorAll(".askerp-prefs-select");
    selects.forEach(function (sel) {
      var key = sel.getAttribute("data-field");
      if (key) payload[key] = sel.value;
    });

    frappe.call({
      method: "askerp.api.save_preferences",
      args: { quick_settings: JSON.stringify(payload) },
      callback: function () {
        btn.textContent = __("Saved!");
        btn.style.background = "var(--askerp-primary)";
        btn.style.color = "#fff";
        setTimeout(function () {
          btn.disabled = false;
          btn.textContent = __("Save Settings");
          btn.style.background = "";
          btn.style.color = "";
        }, 1500);
      },
      error: function () {
        btn.disabled = false;
        btn.textContent = __("Save Settings");
        frappe.show_alert({ message: __("Failed to save preferences"), indicator: "red" }, 3);
      },
    });
  }

  /**
   * Deletes a single custom AI-learned preference.
   */
  function deleteCustomPref(key, rowEl) {
    rowEl.style.opacity = "0.4";
    rowEl.style.pointerEvents = "none";

    frappe.call({
      method: "askerp.api.delete_preference",
      args: { key: key },
      callback: function () {
        rowEl.style.transition = "max-height 0.25s ease, opacity 0.25s ease, padding 0.25s ease";
        rowEl.style.maxHeight = "0";
        rowEl.style.opacity = "0";
        rowEl.style.padding = "0";
        rowEl.style.overflow = "hidden";
        setTimeout(function () {
          if (rowEl.parentNode) rowEl.parentNode.removeChild(rowEl);
          // Update count in heading
          var heading = $prefsOverlay.querySelector(".askerp-prefs-section:last-child .askerp-prefs-section-title");
          if (heading) {
            var remaining = $prefsOverlay.querySelectorAll(".askerp-prefs-custom-row").length;
            heading.textContent = __("AI-Learned Preferences") + " (" + remaining + ")";
          }
        }, 260);
      },
      error: function () {
        rowEl.style.opacity = "1";
        rowEl.style.pointerEvents = "";
        frappe.show_alert({ message: __("Failed to delete preference"), indicator: "red" }, 3);
      },
    });
  }

  /**
   * Clears ALL custom AI-learned preferences.
   */
  function clearAllPreferences(btn) {
    if (!confirm(__("Clear all AI-learned preferences? This cannot be undone."))) return;

    btn.disabled = true;
    btn.textContent = __("Clearing...");

    frappe.call({
      method: "askerp.api.clear_preferences",
      callback: function () {
        // Re-fetch and re-render the panel
        closePreferencesPanel();
        setTimeout(openPreferencesPanel, 250);
      },
      error: function () {
        btn.disabled = false;
        btn.textContent = __("Clear All Preferences");
        frappe.show_alert({ message: __("Failed to clear preferences"), indicator: "red" }, 3);
      },
    });
  }

  // ─── Boot ───────────────────────────────────────────────────────
  // Wait for DOM + frappe ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      setTimeout(init, 800);
    });
  } else {
    setTimeout(init, 800);
  }

})();
