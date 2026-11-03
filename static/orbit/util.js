// Shared helpers: DOM, API, inline icons (the handoff's line icons), haptics with visual twins, toasts.
export const M = window.OrbitMath;

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export async function api(path, { method, body } = {}) {
  const res = await fetch("/api" + path, {
    method: method || (body !== undefined ? "POST" : "GET"),
    headers: body !== undefined ? { "content-type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  if (res.status === 401) { window.dispatchEvent(new Event("orbit:signin")); throw new Error("Sign in to continue"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : "That didn't work") : "That didn't work");
  return data;
}

const P = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
export const ICON = {
  price: P('<path d="M3.5 12.5 12 4h8v8l-8.5 8.5a1.5 1.5 0 0 1-2.1 0l-6.4-6.4a1.5 1.5 0 0 1 0-2.1Z"/><circle cx="16.2" cy="7.8" r="1.4"/>'),
  right: P('<path d="M4 9h16M4 15h16M16.5 4 7.5 20"/>'),
  wrong: P('<path d="M2.5 12c2.2-5.5 4.3-5.5 6.4 0s4.1 5.5 6.2 0 4.2-5.5 6.4 0"/>'),
  guess: P('<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2.2"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/>'),
  sun: P('<circle cx="12" cy="12" r="5"/><path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3M4.6 4.6l2.1 2.1M17.3 17.3l2.1 2.1M4.6 19.4l2.1-2.1M17.3 6.7l2.1-2.1"/>'),
  planet: P('<circle cx="12" cy="12" r="5.5"/><path d="M7.2 9.8C3.9 11.6 2 13.7 2.6 14.9c.8 1.5 5.5.5 10.5-2.1s8.5-5.9 7.7-7.4c-.5-1-2.7-.9-5.6.1"/>'),
  comet: P('<circle cx="8" cy="16" r="4"/><path d="M11 12.5 20.5 3M12.5 15 21 9M8.5 11 14 3"/>'),
  belt: P('<circle cx="5" cy="15" r="2"/><circle cx="12" cy="9" r="2.6"/><circle cx="19" cy="14" r="1.7"/><circle cx="14.5" cy="18.5" r="1"/><circle cx="6.5" cy="7" r="1"/>'),
  blackhole: P('<path d="M12 12c0-1.4 1.8-2 3-1 1.8 1.5 1 4.6-1.5 5.4-3.5 1.1-6.8-2.1-6-5.9.9-4.4 6.2-6.3 10.1-3.7 4.8 3.2 4.9 10.4.5 14"/>'),
  undo: P('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>'),
  close: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  plus: P('<path d="M12 5v14M5 12h14"/>'),
  galaxy: P('<ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-24 12 12)"/><circle cx="12" cy="12" r="1.8"/>'),
  user: P('<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20c1-4 4-5.5 7.500-5.500S18.500 16 19.500 20"/>'),
  rocket: `<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M16 3c4 3 6 7.500 6 12.500V21H10v-5.500C10 10.500 12 6 16 3Z"/><circle cx="16" cy="12" r="2"/><path d="M10 17l-4 4v3l4-2M22 17l4 4v3l-4-2"/>
    <path class="flame" d="M13.500 24.500c0 2 1 3.500 2.500 4.500 1.500-1 2.500-2.500 2.500-4.500" stroke="#FFC933"/></svg>`,
};
export const AXIS_LABEL = { price: "Price", right: "Right vibe", guess: "Claude's guess", wrong: "Wrong vibe" };
export const AXIS_COLOR = { price: "var(--dir-price)", right: "var(--dir-right)", guess: "var(--dir-guess)", wrong: "var(--dir-wrong)" };

export const money = (l) => l.price_text || (l.price != null ? "$" + Math.round(l.price).toLocaleString() : "No price");

// Haptics only where the device has them; every cue also gets a visual twin (a pulse on the element, or a toast).
export function haptic(pattern, el) {
  if (el) { el.classList.remove("pulse"); void el.offsetWidth; el.classList.add("pulse"); }
  try { if ("vibrate" in navigator) navigator.vibrate(pattern); } catch (_) { /* unsupported or blocked */ }
}

let toastTimer;
export function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

// Bottom sheet that follows the overlay contract: capped to the visual viewport, pinned head and foot, scrolling body.
export function sheet({ title, body, foot, onClose, label }) {
  const root = document.getElementById("layer");
  const dim = h('<div class="dim"></div>');
  const sh = h(`<section class="sheet" role="dialog" aria-modal="true" aria-label="${esc(label || title || "Dialog")}">
    <div class="sh-head"><h2 class="h2 grow ellip">${esc(title || "")}</h2><button class="btn ghost small" data-x aria-label="Close">${ICON.close}</button></div>
    <div class="sh-body"></div><div class="sh-foot"></div></section>`);
  const bodyEl = $(".sh-body", sh), footEl = $(".sh-foot", sh);
  if (typeof body === "string") bodyEl.innerHTML = body; else if (body) bodyEl.append(body);
  if (typeof foot === "string") footEl.innerHTML = foot; else if (foot) footEl.append(foot);
  if (!foot) footEl.hidden = true;
  const close = (reason) => { dim.remove(); sh.remove(); document.removeEventListener("keydown", key); onClose && onClose(reason); };
  const key = (e) => { if (e.key === "Escape") close("esc"); };
  dim.onclick = () => close("dim");
  $("[data-x]", sh).onclick = () => close("x");
  document.addEventListener("keydown", key);
  root.append(dim, sh);
  sh.addEventListener("focusin", (e) => { if (e.target.matches("input,textarea")) setTimeout(() => e.target.scrollIntoView({ block: "center" }), 250); });
  (sh.querySelector("input,textarea,button:not([data-x])") || $("[data-x]", sh)).focus({ preventScroll: true });
  return { el: sh, body: bodyEl, foot: footEl, close };
}

export function zoneText(r) { return M.zone(r); }
export function splitText(percents) {
  if (!percents) return "no complaints";
  return M.AXIS_NAMES.filter((k) => percents[k] > 0).sort((a, b) => percents[b] - percents[a]).map((k) => `${percents[k]}% ${AXIS_LABEL[k]}`).join(" · ");
}
export function topReason(percents, guessText) {
  if (!percents) return "";
  const k = M.AXIS_NAMES.reduce((a, b) => (percents[b] > percents[a] ? b : a));
  return k === "guess" ? guessText : AXIS_LABEL[k];
}
export function confText(c) {
  if (!c || c.state !== "ready") return "Still learning";
  return "Claude " + Math.round(c.value * 100) + "%";
}
