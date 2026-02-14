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
    gear: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.5"/><path d="M12 2L9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61z" fill="none" stroke="currentColor" stroke-width="1"/></svg>`,
    loading: `<svg viewBox="0 0 24 24"><path d="M12 4V2A10 10 0 0 0 2 12h2a8 8 0 0 1 8-8z"/></svg>`,
    copy: `<svg viewBox="0 0 24 24"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>`,
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
    $bubble = el("button", { class: "askerp-bubble askerp-pulse", title: "AI Assistant (Ctrl+Shift+A)" });
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
    headerTitle.textContent = "AI Assistant";
    $headerContext = el("span", { class: "askerp-header-context" });
    $headerContext.textContent = detectContext().label || "Ask me anything";
    headerInfo.appendChild(headerTitle);
    headerInfo.appendChild($headerContext);
    headerLeft.appendChild(avatar);
    headerLeft.appendChild(headerInfo);

    const headerActions = el("div", { class: "askerp-header-actions" });

    const newChatBtn = el("button", { class: "askerp-header-btn", title: "New Chat" });
    newChatBtn.innerHTML = ICONS.newchat;
    newChatBtn.onclick = startNewChat;

    const maximizeBtn = el("button", { class: "askerp-header-btn", title: "Fullscreen" });
    maximizeBtn.innerHTML = ICONS.maximize;
    maximizeBtn.onclick = toggleFullscreen;

    const minimizeBtn = el("button", { class: "askerp-header-btn", title: "Minimize" });
    minimizeBtn.innerHTML = ICONS.minimize;
    minimizeBtn.onclick = togglePanel;

    const closeBtn = el("button", { class: "askerp-header-btn", title: "Close" });
    closeBtn.innerHTML = ICONS.close;
    closeBtn.onclick = closePanel;

    headerActions.appendChild(newChatBtn);
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
      placeholder: "Ask about your business data...",
      rows: "1",
      maxlength: "2000",
    });
    $input.onkeydown = handleInputKey;
    $input.oninput = autoResize;

    $sendBtn = el("button", { class: "askerp-send-btn", title: "Send" });
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
    if (!route || !route.length) return { doctype: null, name: null, label: "Dashboard" };

    const view = route[0]; // "Form", "List", "Report", etc.
    const doctype = route[1] || null;
    const name = route[2] || null;

    if (view === "Form" && doctype && name) {
      return { doctype, name, label: `${doctype}: ${name}` };
    }
    if (view === "List" && doctype) {
      return { doctype, name: null, label: `${doctype} List` };
    }
    if (view === "Report" && doctype) {
      return { doctype, name: null, label: `Report: ${doctype}` };
    }
    if (view === "modules") {
      return { doctype: null, name: null, label: "Modules" };
    }
    return { doctype, name, label: doctype || "Home" };
  }

  function updateContext() {
    if ($headerContext) {
      const ctx = detectContext();
      $headerContext.textContent = ctx.label || "Ask me anything";
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
    $messages.appendChild(msg);
    scrollToBottom();

    state.messages.push({ role, content });
    return bubble;
  }

  function showTyping(statusText) {
    removeTyping();
    $typingIndicator = el("div", { class: "askerp-typing" });
    if (statusText) {
      $typingIndicator.innerHTML = `<span class="askerp-tool-status">${ICONS.loading} ${escapeHtml(statusText)}</span>`;
    } else {
      $typingIndicator.innerHTML = `<span class="askerp-typing-dots"><span></span><span></span><span></span></span><span>Thinking...</span>`;
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
    h3.textContent = "AI Business Assistant";
    const p = el("p");
    p.textContent = "Ask questions about your sales, inventory, finances, and more. I can analyze data, generate reports, and provide insights.";
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
          finishStreaming("Something went wrong. Please try again.");
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
          finishStreaming(data.error || "Monthly budget exceeded.");
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
        const msg = (err && err.message) || "Failed to connect to AI. Please try again.";
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
            finishStreaming("Stream connection lost.");
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
          finishStreaming("Connection error. Please try again.");
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
