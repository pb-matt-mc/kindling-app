// Orbit: shell, router and the shared state every screen reads.
import { $, ICON, api, esc, h, toast } from "./orbit/util.js";

// Installed-app detection lives in script, never in CSS: the display-mode media feature cannot be emulated in tests.
const standalone = () => (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
document.documentElement.dataset.display = standalone() ? "standalone" : "browser";

// Track the visual viewport so the app shrinks above an on-screen keyboard (iOS does not resize the layout viewport).
function trackViewport() {
  const vv = window.visualViewport;
  const set = () => document.documentElement.style.setProperty("--vvh", (vv ? vv.height : innerHeight) + "px");
  set();
  if (vv) { vv.addEventListener("resize", set); vv.addEventListener("scroll", set); }
  addEventListener("resize", set);
  addEventListener("orientationchange", () => setTimeout(set, 200));
}
trackViewport();

// Orientation of the SCREEN (not the viewport): a portrait phone with its keyboard up has a short, wide viewport.
function trackOrientation() {
  const set = () => {
    const t = (screen.orientation && screen.orientation.type) || (screen.width > screen.height ? "landscape" : "portrait");
    document.documentElement.dataset.orient = t.startsWith("landscape") ? "landscape" : "portrait";
  };
  set();
  addEventListener("resize", set);
  if (screen.orientation && screen.orientation.addEventListener) screen.orientation.addEventListener("change", set);
}
trackOrientation();

const app = $("#app");
const ctx = {
  state: null, onState: null, route: "place",
  async refresh() {
    ctx.state = await api("/o/state");
    ctx.onState && ctx.onState();
    return ctx.state;
  },
  afterBatch() { location.hash = "#recap"; },
};
window.__orbit = ctx;   // read by the browser tests

let view = null, mounted = null;
const NAV = [["place", "Place", ICON.sun], ["system", "System", ICON.planet], ["galaxy", "Galaxy", ICON.galaxy]];

function frame() {
  app.innerHTML = `<main class="main" id="main"></main>
    <nav class="nav" aria-label="Orbit">${NAV.map(([k, n, i]) => `<a href="#${k}" data-nav="${k}">${i}<span>${n}</span></a>`).join("")}
      <a href="/legacy#profile" data-nav="profile" aria-label="Profile and settings">${ICON.user}<span>Profile</span></a></nav>`;
}

function setNav(name) {
  $$nav().forEach((a) => (a.dataset.nav === name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
}
const $$nav = () => [...document.querySelectorAll(".nav a")];

async function route() {
  if (!ctx.state) return;
  try { await ctx.refresh(); } catch (_) { return; }     // every screen opens on fresh numbers
  const [name, arg] = (location.hash.replace(/^#/, "") || "place").split("/");
  const key = name + "/" + (arg || "");
  if (view && view.destroy) view.destroy();
  view = null; mounted = key;
  if (!$("#main")) frame();
  const main = $("#main");
  main.scrollTop = 0;
  setNav(["place", "move"].includes(name) ? "place" : ["system", "galaxy"].includes(name) ? name : name === "recap" ? "place" : "");
  document.getElementById("layer").innerHTML = "";
  try {
    if (name === "place" || name === "") view = (await import("./orbit/place.js")).mountPlace(main, ctx);
    else if (name === "move") view = (await import("./orbit/place.js")).mountPlace(main, ctx, { moveId: +arg });
    else if (name === "system") view = (await import("./orbit/system.js")).mountSystem(main, ctx);
    else if (name === "galaxy") view = (await import("./orbit/galaxy.js")).mountGalaxy(main, ctx);
    else if (name === "recap") view = (await import("./orbit/recap.js")).mountRecap(main, ctx, arg);
    else location.hash = "#place";
  } catch (e) {
    console.error(e);
    main.innerHTML = `<div class="page"><h1 class="h2">Something broke</h1><p class="p">${esc(e.message)}</p><a class="btn" href="#place">Back to Place</a></div>`;
  }
  maybeEvents();
}

// Events (black hole, new star, ...) wait for a batch to finish; they are shown one at a time from here.
async function maybeEvents() {
  if (!ctx.state || !ctx.state.events_ready) return;
  const name = (location.hash.replace(/^#/, "") || "place").split("/")[0];
  if (name === "move") return;
  try { (await import("./orbit/events.js")).showNextEvent(ctx); } catch (_) { /* events module is optional until it ships */ }
}

function signIn() {
  app.innerHTML = `<main class="main"><div class="page" style="justify-content:center">
    <img src="/static/icons/orbit-mark.svg" alt="" width="64" height="64">
    <h1 class="h1">Orbit</h1><p class="p">Enter the invite code you were given.</p>
    <div class="field-in"><label for="code">Invite code</label><input id="code" type="text" autocomplete="off" autocapitalize="characters" maxlength="12" placeholder="ABCD-EFGH"></div>
    <div class="field-in" id="namebox" hidden><label for="nm">Your name</label><input id="nm" type="text" maxlength="30" autocomplete="off"></div>
    <p class="sm" id="err" style="color:var(--alert)" hidden></p>
    <button class="btn primary" id="go">Continue</button></div></main>`;
  const m = location.hash.match(/join\/([A-Za-z0-9-]+)/);
  if (m) $("#code").value = m[1];
  $("#go").onclick = async () => {
    const err = $("#err"); err.hidden = true;
    try {
      const code = $("#code").value.trim();
      const info = await fetch("/api/auth/invite/" + encodeURIComponent(code)).then((r) => (r.ok ? r.json() : Promise.reject(new Error("That code doesn't work. Check it and try again."))));
      if (info.new_account && $("#namebox").hidden) { $("#namebox").hidden = false; $("#nm").focus(); return; }
      const res = await fetch("/api/auth/redeem", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ code, name: $("#nm").value.trim() || undefined }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "That didn't work");
      location.hash = "#place"; boot();
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  };
}

async function boot() {
  try { await ctx.refresh(); } catch (e) { return signIn(); }
  frame();
  route();
}
addEventListener("hashchange", () => { if (ctx.state) route(); });
addEventListener("orbit:signin", signIn);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
boot();
