/* Sanad widget — one script tag, zero dependencies, Shadow DOM isolated.
 * All dynamic content (model answers, document names, server errors) is
 * rendered with textContent/createElement only: no innerHTML anywhere, so a
 * malicious document cannot inject HTML/JS into the host page.
 *
 * <script src="http://localhost:8000/widget.js" data-site-key="pk-..." defer></script>
 * Optional: data-api-url, data-color, data-logo, data-welcome,
 *           data-lang="auto|ar|fr|en", data-theme="auto|light|dark"
 */
(function () {
  "use strict";
  if (window.__sanadWidgetLoaded) return;
  window.__sanadWidgetLoaded = true;

  var script = document.currentScript || document.querySelector("script[data-site-key]");
  if (!script) return;
  var siteKey = script.getAttribute("data-site-key") || "";
  if (!siteKey) {
    console.error("[Sanad] data-site-key is required on the widget script tag.");
    return;
  }
  var apiUrl = (
    script.getAttribute("data-api-url") || new URL(script.src, location.href).origin
  ).replace(/\/+$/, "");
  var accent = script.getAttribute("data-color") || "#2563eb";
  if (window.CSS && window.CSS.supports && !window.CSS.supports("color", accent)) {
    accent = "#2563eb";
  }
  var welcomeOverride = script.getAttribute("data-welcome") || "";
  var configuredLang = script.getAttribute("data-lang") || "auto";
  var configuredTheme = script.getAttribute("data-theme") || "auto";

  var STRINGS = {
    en: {
      title: "Sanad",
      placeholder: "Ask a question…",
      welcome: "Hello! Ask me anything about our policies and services.",
      error: "Cannot reach the assistant. Please try again.",
      rated: "Thanks for your feedback!",
      rateFailed: "Could not save your feedback.",
      open: "Open chat",
      close: "Close chat",
      send: "Send",
      good: "Good answer",
      bad: "Bad answer",
      page: "page",
      section: "section",
      auto: "Auto",
      handoff: "Talk to a human",
      handoffEmail: "Your email address",
      handoffMessage: "Your message",
      handoffNotice:
        "Your email address and message will be shared with this website's team so they can reply to you.",
      handoffSubmit: "Send request",
      handoffBack: "Back to chat",
      handoffSuccess: "Your request was sent. The team will contact you by email.",
      handoffError: "Could not send your request. Please try again.",
    },
    fr: {
      title: "Sanad",
      placeholder: "Posez une question…",
      welcome: "Bonjour ! Posez-moi vos questions sur nos politiques et services.",
      error: "Impossible de joindre l'assistant. Veuillez réessayer.",
      rated: "Merci pour votre retour !",
      rateFailed: "Impossible d'enregistrer votre retour.",
      open: "Ouvrir le chat",
      close: "Fermer le chat",
      send: "Envoyer",
      good: "Bonne réponse",
      bad: "Mauvaise réponse",
      page: "page",
      section: "section",
      auto: "Auto",
      handoff: "Parler à un humain",
      handoffEmail: "Votre adresse e-mail",
      handoffMessage: "Votre message",
      handoffNotice:
        "Votre adresse e-mail et votre message seront partagés avec l'équipe de ce site afin qu'elle puisse vous répondre.",
      handoffSubmit: "Envoyer la demande",
      handoffBack: "Retour au chat",
      handoffSuccess: "Votre demande a été envoyée. L'équipe vous contactera par e-mail.",
      handoffError: "Impossible d'envoyer votre demande. Veuillez réessayer.",
    },
    ar: {
      title: "سند",
      placeholder: "اطرح سؤالا…",
      welcome: "مرحبا! اسألني عن سياساتنا وخدماتنا.",
      error: "تعذر الوصول إلى المساعد. يرجى المحاولة مرة أخرى.",
      rated: "شكرا على ملاحظاتك!",
      rateFailed: "تعذر حفظ ملاحظاتك.",
      open: "فتح المحادثة",
      close: "إغلاق المحادثة",
      send: "إرسال",
      good: "إجابة جيدة",
      bad: "إجابة سيئة",
      page: "صفحة",
      section: "قسم",
      auto: "تلقائي",
      handoff: "التحدث إلى موظف",
      handoffEmail: "بريدك الإلكتروني",
      handoffMessage: "رسالتك",
      handoffNotice:
        "سيتم مشاركة بريدك الإلكتروني ورسالتك مع فريق هذا الموقع حتى يتمكنوا من الرد عليك.",
      handoffSubmit: "إرسال الطلب",
      handoffBack: "العودة إلى المحادثة",
      handoffSuccess: "تم إرسال طلبك. سيتواصل معك الفريق عبر البريد الإلكتروني.",
      handoffError: "تعذر إرسال طلبك. يرجى المحاولة مرة أخرى.",
    },
  };

  function browserLang() {
    var nav = (navigator.language || "en").slice(0, 2).toLowerCase();
    return STRINGS[nav] ? nav : "en";
  }

  var state = {
    open: false,
    busy: false,
    conversationId: null,
    manualLang: STRINGS[configuredLang] ? configuredLang : null,
    uiLang: STRINGS[configuredLang] ? configuredLang : browserLang(),
    welcomed: false,
    openedAt: 0,
  };

  /* ---------- DOM helpers (no innerHTML anywhere) ---------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  var SVG_NS = "http://www.w3.org/2000/svg";
  function icon(pathD, size) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size || 20));
    svg.setAttribute("height", String(size || 20));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    var path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", pathD);
    svg.appendChild(path);
    return svg;
  }

  var ICONS = {
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    close: "M18 6L6 18M6 6l12 12",
    send: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
    up: "M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3",
    down: "M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17",
  };

  function safeLogoUrl(raw) {
    if (!raw) return null;
    try {
      var url = new URL(raw, location.href);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch (err) {
      return null;
    }
  }

  /* ---------- styles ---------- */

  var STYLES = `
.sanad-root{--sanad-accent:#2563eb;--sanad-bg:#fff;--sanad-fg:#111827;--sanad-muted:#6b7280;
--sanad-border:#e5e7eb;--sanad-bot-bg:#f3f4f6;--sanad-err-bg:#fef2f2;--sanad-err-fg:#b91c1c;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Arabic","Noto Naskh Arabic",sans-serif;
font-size:14px;line-height:1.5;color:var(--sanad-fg);}
.sanad-root[data-theme="dark"]{--sanad-bg:#1f2937;--sanad-fg:#f9fafb;--sanad-muted:#9ca3af;
--sanad-border:#374151;--sanad-bot-bg:#374151;--sanad-err-bg:#451a1a;--sanad-err-fg:#fca5a5;}
.sanad-root *,.sanad-root *::before,.sanad-root *::after{box-sizing:border-box;}
.sanad-root [hidden]{display:none !important;}
.sanad-fab{position:fixed;bottom:20px;inset-inline-end:20px;width:56px;height:56px;border-radius:50%;
border:none;background:var(--sanad-accent);color:#fff;cursor:pointer;display:flex;align-items:center;
justify-content:center;box-shadow:0 4px 14px rgba(0,0,0,.25);z-index:2147483000;}
.sanad-fab:hover{filter:brightness(1.1);}
.sanad-panel{position:fixed;bottom:88px;inset-inline-end:20px;width:380px;max-width:calc(100vw - 40px);
height:560px;max-height:calc(100vh - 120px);display:flex;flex-direction:column;background:var(--sanad-bg);
border:1px solid var(--sanad-border);border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.25);
overflow:hidden;z-index:2147483000;}
.sanad-header{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--sanad-border);}
.sanad-logo{height:24px;width:auto;border-radius:4px;}
.sanad-title{font-weight:600;flex:1;}
.sanad-lang{font-size:12px;background:var(--sanad-bg);color:var(--sanad-fg);
border:1px solid var(--sanad-border);border-radius:6px;padding:2px 4px;max-width:90px;}
.sanad-close{background:none;border:none;color:var(--sanad-muted);cursor:pointer;padding:4px;display:flex;}
.sanad-messages{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px;}
.sanad-msg{max-width:85%;display:flex;flex-direction:column;}
.sanad-msg.sanad-user{align-self:flex-end;align-items:flex-end;}
.sanad-msg.sanad-bot{align-self:flex-start;align-items:flex-start;}
.sanad-bubble{padding:10px 12px;border-radius:14px;white-space:pre-wrap;overflow-wrap:anywhere;}
.sanad-user .sanad-bubble{background:var(--sanad-accent);color:#fff;border-end-end-radius:4px;}
.sanad-bot .sanad-bubble{background:var(--sanad-bot-bg);border-end-start-radius:4px;}
.sanad-bubble.sanad-error{background:var(--sanad-err-bg);color:var(--sanad-err-fg);}
.sanad-typing{display:inline-flex;gap:4px;padding:12px;}
.sanad-typing span{width:6px;height:6px;border-radius:50%;background:var(--sanad-muted);animation:sanad-bounce 1.2s infinite;}
.sanad-typing span:nth-child(2){animation-delay:.2s;}
.sanad-typing span:nth-child(3){animation-delay:.4s;}
@keyframes sanad-bounce{0%,60%,100%{transform:translateY(0);opacity:.5;}30%{transform:translateY(-4px);opacity:1;}}
.sanad-citations{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;}
.sanad-chip{font-size:12px;border:1px solid var(--sanad-border);background:var(--sanad-bg);
color:var(--sanad-muted);border-radius:999px;padding:2px 8px;cursor:pointer;font-family:inherit;}
.sanad-chip:hover{border-color:var(--sanad-accent);color:var(--sanad-accent);}
.sanad-source{font-size:12px;background:var(--sanad-bg);border:1px solid var(--sanad-border);
border-radius:8px;padding:8px;margin-top:4px;color:var(--sanad-fg);}
.sanad-feedback{display:flex;align-items:center;gap:4px;margin-top:6px;}
.sanad-rate{background:none;border:none;color:var(--sanad-muted);cursor:pointer;padding:2px;display:flex;}
.sanad-rate:hover{color:var(--sanad-accent);}
.sanad-rate.sanad-selected{color:var(--sanad-accent);}
.sanad-rate:disabled{cursor:default;opacity:.6;}
.sanad-rate-note{font-size:12px;color:var(--sanad-muted);}
.sanad-form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--sanad-border);}
.sanad-input{flex:1;min-width:0;border:1px solid var(--sanad-border);border-radius:999px;
padding:8px 12px;background:var(--sanad-bg);color:var(--sanad-fg);font:inherit;outline:none;}
.sanad-input:focus{border-color:var(--sanad-accent);}
.sanad-send{width:36px;height:36px;flex:none;border-radius:50%;border:none;background:var(--sanad-accent);
color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;}
.sanad-send:disabled{opacity:.5;cursor:default;}
.sanad-website{position:absolute;left:-9999px;width:1px;height:1px;opacity:0;}
.sanad-handoff{background:none;border:none;border-top:1px solid var(--sanad-border);
color:var(--sanad-muted);cursor:pointer;font:inherit;font-size:12px;padding:8px;text-align:center;}
.sanad-handoff:hover{color:var(--sanad-accent);}
.sanad-handoff-view{flex:1;display:flex;flex-direction:column;gap:10px;padding:14px;overflow-y:auto;}
.sanad-handoff-title{font-size:15px;font-weight:600;margin:0;}
.sanad-handoff-input{border:1px solid var(--sanad-border);border-radius:8px;padding:8px 10px;
background:var(--sanad-bg);color:var(--sanad-fg);font:inherit;outline:none;width:100%;}
.sanad-handoff-input:focus{border-color:var(--sanad-accent);}
.sanad-handoff-textarea{resize:vertical;min-height:80px;}
.sanad-handoff-notice{font-size:12px;color:var(--sanad-muted);margin:0;}
.sanad-handoff-note{font-size:12px;color:var(--sanad-err-fg);background:var(--sanad-err-bg);
border-radius:8px;padding:8px;margin:0;overflow-wrap:anywhere;}
.sanad-handoff-actions{display:flex;gap:8px;justify-content:flex-end;}
.sanad-handoff-back{background:none;border:1px solid var(--sanad-border);border-radius:999px;
color:var(--sanad-fg);cursor:pointer;font:inherit;padding:8px 14px;}
.sanad-handoff-submit{background:var(--sanad-accent);border:none;border-radius:999px;color:#fff;
cursor:pointer;font:inherit;padding:8px 14px;}
.sanad-handoff-submit:disabled,.sanad-handoff-back:disabled{opacity:.5;cursor:default;}
.sanad-root.sanad-mobile .sanad-panel{inset:0;width:100%;height:100%;max-width:none;max-height:none;border-radius:0;border:none;}
.sanad-root.sanad-mobile[data-open="true"] .sanad-fab{display:none;}
`;

  /* ---------- build UI ---------- */

  var host = el("div");
  host.id = "sanad-widget-host";
  var shadow = host.attachShadow({ mode: "open" });
  var style = el("style");
  style.textContent = STYLES;
  shadow.appendChild(style);

  var root = el("div", "sanad-root");
  root.style.setProperty("--sanad-accent", accent);
  root.setAttribute("data-open", "false");
  shadow.appendChild(root);

  var fab = el("button", "sanad-fab");
  fab.type = "button";
  fab.appendChild(icon(ICONS.chat, 24));
  root.appendChild(fab);

  var panel = el("section", "sanad-panel");
  panel.hidden = true;
  root.appendChild(panel);

  var header = el("header", "sanad-header");
  var logoUrl = safeLogoUrl(script.getAttribute("data-logo"));
  var logo = el("img", "sanad-logo");
  logo.alt = "";
  logo.hidden = true;
  if (logoUrl) {
    logo.addEventListener("load", function () { logo.hidden = false; });
    logo.addEventListener("error", function () { logo.hidden = true; });
    logo.src = logoUrl;
  }
  var title = el("span", "sanad-title");
  var langSelect = el("select", "sanad-lang");
  [["auto", "Auto"], ["en", "English"], ["fr", "Français"], ["ar", "العربية"]].forEach(function (pair) {
    var option = el("option", "", pair[1]);
    option.value = pair[0];
    langSelect.appendChild(option);
  });
  langSelect.value = state.manualLang || "auto";
  var closeBtn = el("button", "sanad-close");
  closeBtn.type = "button";
  closeBtn.appendChild(icon(ICONS.close, 18));
  header.appendChild(logo);
  header.appendChild(title);
  header.appendChild(langSelect);
  header.appendChild(closeBtn);
  panel.appendChild(header);

  var messages = el("div", "sanad-messages");
  messages.setAttribute("role", "log");
  messages.setAttribute("aria-live", "polite");
  panel.appendChild(messages);

  var form = el("form", "sanad-form");
  var input = el("input", "sanad-input");
  input.type = "text";
  input.maxLength = 4000;
  input.autocomplete = "off";
  var sendBtn = el("button", "sanad-send");
  sendBtn.type = "submit";
  sendBtn.appendChild(icon(ICONS.send, 18));
  form.appendChild(input);
  form.appendChild(sendBtn);
  // Honeypot: invisible to visitors, bots that auto-fill fields get rejected.
  var honeypot = el("input", "sanad-website");
  honeypot.type = "text";
  honeypot.name = "website";
  honeypot.tabIndex = -1;
  honeypot.autocomplete = "off";
  honeypot.setAttribute("aria-hidden", "true");
  form.appendChild(honeypot);
  panel.appendChild(form);

  /* ---------- human handoff ---------- */

  var handoffBtn = el("button", "sanad-handoff");
  handoffBtn.type = "button";
  panel.appendChild(handoffBtn);

  var handoffView = el("form", "sanad-handoff-view");
  handoffView.hidden = true;
  var handoffTitle = el("h2", "sanad-handoff-title");
  var handoffEmail = el("input", "sanad-handoff-input");
  handoffEmail.type = "email";
  handoffEmail.required = true;
  handoffEmail.maxLength = 320;
  handoffEmail.autocomplete = "email";
  var handoffMessage = el("textarea", "sanad-handoff-input sanad-handoff-textarea");
  handoffMessage.required = true;
  handoffMessage.maxLength = 4000;
  handoffMessage.rows = 4;
  var handoffNotice = el("p", "sanad-handoff-notice");
  var handoffNote = el("p", "sanad-handoff-note");
  handoffNote.hidden = true;
  var handoffActions = el("div", "sanad-handoff-actions");
  var handoffBack = el("button", "sanad-handoff-back");
  handoffBack.type = "button";
  var handoffSubmit = el("button", "sanad-handoff-submit");
  handoffSubmit.type = "submit";
  handoffActions.appendChild(handoffBack);
  handoffActions.appendChild(handoffSubmit);
  handoffView.appendChild(handoffTitle);
  handoffView.appendChild(handoffEmail);
  handoffView.appendChild(handoffMessage);
  handoffView.appendChild(handoffNotice);
  handoffView.appendChild(handoffNote);
  handoffView.appendChild(handoffActions);
  panel.appendChild(handoffView);

  function showHandoff(show) {
    handoffView.hidden = !show;
    messages.hidden = show;
    form.hidden = show;
    handoffBtn.hidden = show;
    if (show) {
      handoffNote.hidden = true;
      handoffEmail.focus();
    }
  }

  handoffBtn.addEventListener("click", function () { showHandoff(true); });
  handoffBack.addEventListener("click", function () {
    showHandoff(false);
    input.focus();
  });

  handoffView.addEventListener("submit", async function (event) {
    event.preventDefault();
    var email = handoffEmail.value.trim();
    var message = handoffMessage.value.trim();
    if (!email || !message) return;
    var strings = STRINGS[state.uiLang];
    handoffSubmit.disabled = true;
    handoffBack.disabled = true;
    var payload = {
      email: email,
      message: message,
      website: honeypot.value,
      opened_at: state.openedAt,
    };
    if (state.manualLang) payload.language = state.manualLang;
    try {
      var response = await fetch(apiUrl + "/api/v1/handoff", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Site-Key": siteKey },
        body: JSON.stringify(payload),
      });
      if (response.ok) {
        handoffEmail.value = "";
        handoffMessage.value = "";
        showHandoff(false);
        addMessage("bot", strings.handoffSuccess);
        input.focus();
      } else {
        var detail = strings.handoffError;
        try {
          var body = await response.json();
          if (body && body.detail) detail = String(body.detail);
        } catch (err) { /* keep default */ }
        handoffNote.textContent = detail;
        handoffNote.hidden = false;
      }
    } catch (err) {
      handoffNote.textContent = strings.handoffError;
      handoffNote.hidden = false;
    }
    handoffSubmit.disabled = false;
    handoffBack.disabled = false;
  });

  if (document.body) {
    document.body.appendChild(host);
  } else {
    document.addEventListener("DOMContentLoaded", function () {
      document.body.appendChild(host);
    });
  }

  /* ---------- theme ---------- */

  // screen.width, not just innerWidth: pages without a viewport meta tag keep
  // a 980px layout viewport on phones, which would defeat a CSS media query.
  function applyMobileClass() {
    var small = Math.min(screen.width || 9999, window.innerWidth) <= 480;
    root.classList.toggle("sanad-mobile", small);
  }
  applyMobileClass();
  window.addEventListener("resize", applyMobileClass);

  var darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  function applyTheme() {
    var dark = configuredTheme === "dark" || (configuredTheme === "auto" && darkQuery && darkQuery.matches);
    root.setAttribute("data-theme", dark ? "dark" : "light");
  }
  applyTheme();
  if (darkQuery && darkQuery.addEventListener && configuredTheme === "auto") {
    darkQuery.addEventListener("change", applyTheme);
  }

  /* ---------- language / RTL ---------- */

  function applyLanguage() {
    var strings = STRINGS[state.uiLang];
    root.dir = state.uiLang === "ar" ? "rtl" : "ltr";
    title.textContent = strings.title;
    input.placeholder = strings.placeholder;
    fab.setAttribute("aria-label", strings.open);
    closeBtn.setAttribute("aria-label", strings.close);
    sendBtn.setAttribute("aria-label", strings.send);
    langSelect.setAttribute("aria-label", strings.auto);
    langSelect.options[0].textContent = strings.auto;
    handoffBtn.textContent = strings.handoff;
    handoffTitle.textContent = strings.handoff;
    handoffEmail.placeholder = strings.handoffEmail;
    handoffEmail.setAttribute("aria-label", strings.handoffEmail);
    handoffMessage.placeholder = strings.handoffMessage;
    handoffMessage.setAttribute("aria-label", strings.handoffMessage);
    handoffNotice.textContent = strings.handoffNotice;
    handoffSubmit.textContent = strings.handoffSubmit;
    handoffBack.textContent = strings.handoffBack;
  }
  applyLanguage();

  langSelect.addEventListener("change", function () {
    var value = langSelect.value;
    state.manualLang = value === "auto" ? null : value;
    state.uiLang = value === "auto" ? browserLang() : value;
    applyLanguage();
  });

  /* ---------- messages ---------- */

  function scrollDown() {
    messages.scrollTop = messages.scrollHeight;
  }

  function addMessage(role, text, isError) {
    var wrap = el("div", "sanad-msg sanad-" + role);
    var bubble = el("div", "sanad-bubble" + (isError ? " sanad-error" : ""));
    bubble.dir = "auto";
    var content = el("div", "sanad-content", text);
    bubble.appendChild(content);
    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    scrollDown();
    return { wrap: wrap, content: content };
  }

  function showTyping() {
    var wrap = el("div", "sanad-msg sanad-bot");
    var bubble = el("div", "sanad-bubble");
    var typing = el("div", "sanad-typing");
    typing.setAttribute("aria-label", STRINGS[state.uiLang].title);
    typing.appendChild(el("span"));
    typing.appendChild(el("span"));
    typing.appendChild(el("span"));
    bubble.appendChild(typing);
    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    scrollDown();
    return wrap;
  }

  function closePopovers() {
    messages.querySelectorAll(".sanad-source").forEach(function (node) { node.remove(); });
  }

  function renderCitations(wrap, citations) {
    if (!citations || !citations.length) return;
    var strings = STRINGS[state.uiLang];
    var row = el("div", "sanad-citations");
    citations.forEach(function (citation) {
      var label = "[" + citation.index + "] " + citation.filename;
      if (citation.page_number != null) label += " · " + strings.page + " " + citation.page_number;
      var chip = el("button", "sanad-chip", label);
      chip.type = "button";
      chip.addEventListener("click", function () {
        var existing = wrap.querySelector(".sanad-source");
        var wasOpenForThis = existing && existing.dataset.index === String(citation.index);
        closePopovers();
        if (wasOpenForThis) return;
        var popover = el("div", "sanad-source");
        popover.dataset.index = String(citation.index);
        popover.appendChild(el("div", "", citation.filename));
        if (citation.page_number != null) {
          popover.appendChild(el("div", "", strings.page + " " + citation.page_number));
        }
        if (citation.heading) {
          popover.appendChild(el("div", "", strings.section + ": " + citation.heading));
        }
        wrap.appendChild(popover);
        scrollDown();
      });
      row.appendChild(chip);
    });
    wrap.appendChild(row);
  }

  function renderFeedback(wrap, messageId) {
    var strings = STRINGS[state.uiLang];
    var row = el("div", "sanad-feedback");
    var note = el("span", "sanad-rate-note");
    note.hidden = true;
    var buttons = [];
    [["up", ICONS.up, strings.good], ["down", ICONS.down, strings.bad]].forEach(function (spec) {
      var button = el("button", "sanad-rate");
      button.type = "button";
      button.setAttribute("aria-label", spec[2]);
      button.title = spec[2];
      button.appendChild(icon(spec[1], 15));
      button.addEventListener("click", function () {
        buttons.forEach(function (b) { b.disabled = true; });
        button.classList.add("sanad-selected");
        fetch(apiUrl + "/api/v1/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Site-Key": siteKey },
          body: JSON.stringify({ message_id: messageId, rating: spec[0] }),
        })
          .then(function (response) {
            note.hidden = false;
            note.textContent = response.ok ? strings.rated : strings.rateFailed;
          })
          .catch(function () {
            note.hidden = false;
            note.textContent = strings.rateFailed;
          });
      });
      buttons.push(button);
      row.appendChild(button);
    });
    row.appendChild(note);
    wrap.appendChild(row);
  }

  /* ---------- chat streaming ---------- */

  function setBusy(busy) {
    state.busy = busy;
    input.disabled = busy;
    sendBtn.disabled = busy;
  }

  function stripMarkers(text) {
    return text.replace(/\[\d+\]/g, "").replace(/[ \t]{2,}/g, " ").trim();
  }

  async function sendMessage(text) {
    setBusy(true);
    addMessage("user", text);
    var typing = showTyping();
    var bot = null;
    var full = "";
    var finished = false;

    function ensureBot() {
      if (!bot) {
        typing.remove();
        bot = addMessage("bot", "");
      }
      return bot;
    }

    function finish(errorText) {
      if (finished) return;
      finished = true;
      typing.remove();
      if (errorText) {
        if (bot) bot.content.textContent = errorText;
        else addMessage("bot", errorText, true);
        if (bot) bot.wrap.querySelector(".sanad-bubble").classList.add("sanad-error");
      }
      setBusy(false);
      input.focus();
    }

    var payload = { message: text, stream: true, website: honeypot.value, opened_at: state.openedAt };
    if (state.conversationId) payload.conversation_id = state.conversationId;
    if (state.manualLang) payload.language = state.manualLang;

    var response;
    try {
      response = await fetch(apiUrl + "/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Site-Key": siteKey },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      finish(STRINGS[state.uiLang].error);
      return;
    }
    if (!response.ok) {
      var detail = STRINGS[state.uiLang].error;
      try {
        var body = await response.json();
        if (body && body.detail) detail = String(body.detail);
      } catch (err) { /* keep default */ }
      finish(detail);
      return;
    }

    try {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      for (;;) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (var i = 0; i < parts.length; i++) {
          var lines = parts[i].split("\n");
          for (var j = 0; j < lines.length; j++) {
            if (lines[j].indexOf("data: ") !== 0) continue;
            var event = JSON.parse(lines[j].slice(6));
            if (event.type === "token") {
              full += event.content;
              ensureBot().content.textContent = full;
              scrollDown();
            } else if (event.type === "done") {
              state.conversationId = event.conversation_id;
              if (!state.manualLang && STRINGS[event.language]) {
                state.uiLang = event.language;
                applyLanguage();
              }
              var current = ensureBot();
              current.content.textContent = stripMarkers(full);
              renderCitations(current.wrap, event.citations);
              if (event.message_id) renderFeedback(current.wrap, event.message_id);
              finish(null);
            } else if (event.type === "error") {
              finish(String(event.detail || STRINGS[state.uiLang].error));
            }
          }
        }
      }
      finish(full ? null : STRINGS[state.uiLang].error);
    } catch (err) {
      finish(STRINGS[state.uiLang].error);
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var text = input.value.trim();
    if (!text || state.busy) return;
    input.value = "";
    sendMessage(text);
  });

  /* ---------- open / close ---------- */

  function setOpen(open) {
    state.open = open;
    panel.hidden = !open;
    root.setAttribute("data-open", open ? "true" : "false");
    if (open) {
      state.openedAt = Date.now();
      if (!state.welcomed) {
        state.welcomed = true;
        addMessage("bot", welcomeOverride || STRINGS[state.uiLang].welcome);
      }
      input.focus();
    } else {
      showHandoff(false);
      fab.focus();
    }
  }

  fab.addEventListener("click", function () { setOpen(!state.open); });
  closeBtn.addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.open) setOpen(false);
  });
})();