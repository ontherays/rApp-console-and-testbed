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

  document.addEventListener("DOMContentLoaded", function () { relabel(); });
  document.addEventListener("htmx:afterSwap", function (event) { relabel(event.target); });
  setInterval(function () { relabel(); }, 30000);
})();
