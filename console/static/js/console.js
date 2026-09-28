// Small helpers only. The pages are server-rendered; this file adds the toast
// region, the CSRF header on every non-GET, and the relative-time labels.

(function () {
  "use strict";

  function meta(name) {
    const el = document.querySelector('meta[name="' + name + '"]');
    return el ? el.getAttribute("content") : "";
  }

  // Every state-changing request carries the session's CSRF token (SE-08).
  document.addEventListener("htmx:configRequest", function (event) {
    const verb = (event.detail.verb || "get").toLowerCase();
    if (verb !== "get") {
      event.detail.headers["X-CSRF-Token"] = meta("csrf-token");
    }
  });

  // Toasts: success 4 s, warning 8 s, error stays until closed (GL-04).
  const LIFETIME = { success: 4000, warning: 8000, danger: 0, primary: 5000 };

  window.toast = function (message, variant, icon) {
    const region = document.querySelector(".toasts");
    if (!region) return;
    const alert = document.createElement("sl-alert");
    alert.variant = variant || "primary";
    alert.closable = true;
    alert.innerHTML =
      '<sl-icon slot="icon" name="' +
      (icon || "info-circle") +
      '"></sl-icon>' +
      "<span></span>";
    alert.querySelector("span").textContent = message;
    region.appendChild(alert);
    if (customElements.get("sl-alert")) {
      alert.toast ? alert.toast() : alert.show();
    } else {
      alert.setAttribute("open", "");
    }
    const life = LIFETIME[alert.variant];
    if (life) setTimeout(() => alert.hide && alert.hide(), life);
  };

  // The server announces an outcome with a response header, so a page does not
  // have to render its own message twice.
  document.addEventListener("htmx:afterRequest", function (event) {
    const xhr = event.detail.xhr;
    if (!xhr) return;
    const message = xhr.getResponseHeader("X-Console-Toast");
    if (message) {
      window.toast(
        message,
        xhr.getResponseHeader("X-Console-Toast-Variant") || "primary"
      );
    }
  });

  document.addEventListener("htmx:responseError", function (event) {
    const xhr = event.detail.xhr;
    if (xhr && xhr.status === 401) {
      window.location = "/login?next=" + encodeURIComponent(window.location.pathname);
      return;
    }
    window.toast(
      "The console could not complete that request (HTTP " +
        (xhr ? xhr.status : "?") +
        ").",
      "danger",
      "exclamation-octagon"
    );
  });

  document.addEventListener("htmx:sendError", function () {
    window.toast("The console itself is unreachable.", "danger", "exclamation-octagon");
  });

  // Times arrive as UTC and are displayed in the configured zone, with the raw
  // UTC value on hover (GL-06).
  function relabel(root) {
    (root || document).querySelectorAll("time[data-ago]").forEach(function (el) {
      const iso = el.getAttribute("datetime");
      if (!iso) return;
      const then = new Date(iso);
      if (isNaN(then)) return;
      const seconds = Math.round((Date.now() - then.getTime()) / 1000);
      el.textContent = human(seconds);
    });
  }

  function human(seconds) {
    if (seconds < 0) return "just now";
    if (seconds < 60) return seconds + " s ago";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return minutes + " min ago";
    const hours = Math.round(minutes / 60);
    if (hours < 48) return hours + " h ago";
    return Math.round(hours / 24) + " d ago";
  }

  // The topology drawer, and the presets inside it. Handlers live here rather
  // than inline because the Content-Security-Policy allows no inline script.
  document.addEventListener("click", function (event) {
    const opener = event.target.closest("[data-drawer-open]");
    if (opener) {
      const drawer = document.getElementById(opener.dataset.drawerOpen);
      if (drawer && drawer.show) drawer.show();
    }
    const closer = event.target.closest("[data-drawer-close]");
    if (closer) {
      const drawer = document.getElementById(closer.dataset.drawerClose);
      if (drawer && drawer.hide) drawer.hide();
    }
    const preset = event.target.closest("[data-preset]");
    if (preset) applyPreset(preset.dataset.preset);
  });

  // A preset sets the form's own fields and lets the form ask ETHOS, exactly as
  // picking each component by hand would. It decides nothing itself.
  function applyPreset(raw) {
    let wanted;
    try {
      wanted = JSON.parse(raw);
    } catch (error) {
      return;
    }
    const form = document.getElementById("plan-form");
    if (!form) return;

    const fields = {
      gnb_stack: wanted.gnb_stack,
      split_kind: wanted.gnb_split === "monolithic" ? "monolithic" : "CU+DU",
      ue: wanted.ue,
      ru: wanted.ru,
      l1_backend: wanted.l1_backend,
      core: wanted.core,
      server: wanted.server,
    };
    if (wanted.gnb_split === "OCUDU-CU+OAI-DU") {
      fields.cu_vendor = "OCUDU";
      fields.du_vendor = "OAI";
    } else if (wanted.gnb_split === "OAI-CU+OCUDU-DU") {
      fields.cu_vendor = "OAI";
      fields.du_vendor = "OCUDU";
    } else {
      fields.cu_vendor = wanted.gnb_stack;
      fields.du_vendor = wanted.gnb_stack;
    }

    Object.keys(fields).forEach(function (name) {
      const value = fields[name];
      if (value === undefined || value === null) return;
      const input = form.querySelector(
        'input[name="' + name + '"][value="' + value + '"]'
      );
      if (input && !input.disabled) input.checked = true;
    });
    form.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // "/" jumps to the search box, the way the rest of the industry does it.
  // Ignored while typing, so it never swallows a character in a form.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    const tag = active ? active.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" ||
        (active && active.isContentEditable)) {
      return;
    }
    const box = document.getElementById("console-search");
    if (box) {
      event.preventDefault();
      box.focus();
      box.select();
    }
  });

  document.addEventListener("DOMContentLoaded", function () { relabel(); });
  document.addEventListener("htmx:afterSwap", function (event) { relabel(event.target); });
  setInterval(function () { relabel(); }, 30000);

  // --- a job's live log ----------------------------------------------------
  //
  // `sse-swap="log"` on the log element is what subscribes it to ETHOS's log
  // events. The extension's default is to insert the event data as content, and
  // that data is ETHOS's own JSON, so the swap is cancelled here and the line
  // appended instead.
  //
  // The relay in console/sse.py stays a pass-through on purpose: reformatting
  // events there would mean teaching it every new event type before one could be
  // seen at all. Rendering is the page's job, and this is the page's script.
  //
  // It lives here rather than in a <script> on the job page because the console
  // serves a strict CSP (script-src 'self'), which blocks inline script.
  let pinnedToBottom = true;

  document.addEventListener("scroll", function (event) {
    const log = event.target;
    if (!log || log.id !== "job-log") return;
    pinnedToBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  }, true);

  document.addEventListener("htmx:sseBeforeMessage", function (event) {
    const log = event.target;
    if (!log || log.id !== "job-log") return;
    event.preventDefault();

    const message = event.detail || {};
    let line = message.data;
    try {
      const payload = JSON.parse(message.data);
      if (payload && payload.line !== undefined) line = payload.line;
    } catch (err) {
      // Not JSON. Show it as it came rather than dropping it.
    }
    if (line === undefined || line === null || line === "") return;
    // textContent, never innerHTML: these lines are a campaign's output.
    log.appendChild(document.createTextNode(line + "\n"));
    if (pinnedToBottom) log.scrollTop = log.scrollHeight;
  });

  document.addEventListener("htmx:sseError", function () {
    window.toast("The job event stream dropped; it is reconnecting.", "warning", "info");
  });
})();
