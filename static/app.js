import { createWeb } from "/static/web.js";

// ------------------------------------------------------------------ utilities
const $ = (sel, el = document) => el.querySelector(sel);
const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ago = (t) => {
  const m = Math.max(0, Math.round((Date.now() / 1000 - t) / 60));
  return m < 1 ? "just now" : m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago";
};
const money = (l) => l.price_text || (l.price != null ? "$" + Math.round(l.price) : "");
const pct = (x) => Math.round((x ?? 0) * 100) + "%";

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: opts.body ? { "content-type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    const err = new Error(msg);
    err.status = res.status;
    if (res.status === 401 && !path.startsWith("/auth/")) { renderJoin(); err.handled = true; }
    throw err;
  }
  return res.json();
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
}

const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

const I = {
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  heart: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.8 4.5c2.1 0 3.6 1.1 5.2 3 1.6-1.9 3.1-3 5.2-3 3.8 0 5.9 3.9 4.4 7.3C19.5 16.4 12 21 12 21z"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  undo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 010 12h-3"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/></svg>',
  web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="2.5"/><circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/><path d="M12 3v6M21 12h-6M12 21v-6M3 12h6"/></svg>',
  flame: '<svg viewBox="0 0 64 80"><defs><linearGradient id="fl" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#e5531f"/><stop offset=".6" stop-color="#ff7a3d"/><stop offset="1" stop-color="#ffd27a"/></linearGradient></defs><path d="M32 4c4 12 18 19 18 37a18 18 0 0 1-36 0c0-8 4-14 8-18 0 7 3 11 7 12-3-11 0-22 3-31z" fill="url(#fl)"/><path d="M32 40c3 5 8 8 8 15a8 8 0 0 1-16 0c0-4 3-7 4-8 0 3 1 4 3 5 0-4 0-8 1-12z" fill="#ffe7b0"/></svg>',
  gem: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M6 3h12l4 6-10 12L2 9z"/><path d="M2 9h20M9 3l3 18M15 3l-3 18M6 3l3 6M18 3l-3 6"/></svg>',
  mark: '<svg class="mark" viewBox="0 0 64 64"><path d="M32 6c3 9 13 14 13 27a13 13 0 0 1-26 0c0-6 3-10 6-13 0 5 2 8 5 9-2-8 0-16 2-23z" fill="#ff7a3d"/><path d="M32 30c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-6 0 2 1 3 2 4 0-3 0-6 1-9z" fill="#ffd27a"/></svg>',
};

// ------------------------------------------------------------------ app state & routing
const S = { state: null, poll: null, web: null, undo: [] };
const app = $("#app");

async function loadState() {
  S.state = await api("/state");
  return S.state;
}

function go(route) { location.hash = route; }

window.addEventListener("hashchange", route);
async function route() {
  clearInterval(S.poll); S.poll = null;
  S.web?.destroy(); S.web = null;
  closeSheet();
  const r = (location.hash || "#home").slice(1);
  if (r.startsWith("join")) return renderJoin(decodeURIComponent(r.split("/")[1] || ""));
  try { await loadState(); } catch (e) { if (e.status === 401) return renderJoin(); app.innerHTML = `<div class="screen"><div class="center-state"><h2>Can't reach Kindling</h2><p>${esc(e.message)}</p><button class="btn" onclick="location.reload()">Retry</button></div></div>`; return; }
  ({ home: renderHome, swipe: renderSwipe, likes: renderLikes, profile: renderProfile, vibe: renderVibe }[r] || renderHome)();
}

function modeBadge() {
  const m = S.state.mode;
  const parts = [];
  if (m.source === "mock") parts.push("fake listings");
  if (m.brain === "mock") parts.push("no Claude key");
  return parts.length ? `<span class="pill warn" title="Set API keys in .env">Demo: ${parts.join(", ")}</span>` : "";
}

// ------------------------------------------------------------------ join (invite codes)
function renderJoin(prefill = "") {
  clearInterval(S.poll); S.poll = null;
  S.web?.destroy(); S.web = null;
  document.querySelectorAll(".modal, .viewer, .dialog, .backdrop").forEach((x) => x.remove());
  closeSheet();
  const el = h(`<div class="screen join">
    <div class="center-state">
      <div class="flame">${I.flame}</div>
      <h2>Kindling</h2>
      <p>Swipe through Marketplace finds that learn your taste. You'll need an invite code to get in.</p>
      <form id="jf" class="join-form" autocomplete="off">
        <input id="jcode" placeholder="Invite code (e.g. ABCD-2345)" autocapitalize="characters" spellcheck="false" value="${esc(prefill)}">
        <input id="jname" placeholder="Your name" maxlength="40" hidden>
        <button class="big-btn" id="jgo" type="submit">Join</button>
        <p class="mode-note" id="jmsg"></p>
      </form>
    </div></div>`);
  app.replaceChildren(el);
  const code = $("#jcode", el), name = $("#jname", el), msg = $("#jmsg", el), go_ = $("#jgo", el);
  let info = null;
  const check = async () => {
    const c = code.value.replace(/[^a-z0-9]/gi, "");
    info = null; name.hidden = true; msg.textContent = "";
    if (c.length < 8) return;
    try {
      info = await api("/auth/invite/" + encodeURIComponent(c));
      if (info.new_account) { name.hidden = false; name.focus(); msg.textContent = "Welcome! Add your name and you're in."; }
      else msg.textContent = `Signs this device in as ${info.name}.`;
    } catch (e) { msg.textContent = e.message; }
  };
  code.addEventListener("input", check);
  if (prefill) check();
  $("#jf", el).onsubmit = async (e) => {
    e.preventDefault();
    go_.disabled = true;
    try {
      await api("/auth/redeem", { body: { code: code.value, name: name.value } });
      history.replaceState(null, "", location.pathname + "#home");
      route();
    } catch (err) { msg.textContent = err.message; go_.disabled = false; if (!info) check(); }
  };
}

// ------------------------------------------------------------------ home
function renderHome() {
  const st = S.state, cur = st.current;
  let sub = "Start your first batch";
  if (cur) {
    const left = cur.listings.length - cur.swiped;
    if (cur.status === "ready") sub = left ? `${left} waiting for you` : "Batch done. See your recap";
    else if (cur.status === "error") sub = "Last batch hit a snag";
    else sub = "Next batch is brewing…";
  } else if (st.web.locked) sub = "Web's full. Crystallize it in Your likes";
  else if (st.batches_done) sub = `Batch ${st.batches_done + 1} is one tap away`;

  const el = h(`<div class="screen home">
    <div class="brand">${I.mark}<span class="word">Kindling</span><span class="spacer"></span>
      <button class="profile-chip" id="pchip"><i></i><span>${esc(st.profile.name)}</span></button></div>
    <div style="display:flex;justify-content:center;margin-top:6px">${modeBadge()}</div>
    <div class="swipe-hero">
      <div class="hero-stack">
        <div class="hero-card"></div><div class="hero-card"></div>
        <button class="hero-card main" id="go-swipe"><div><div class="big">SWIPE</div><div class="sub">${esc(sub)}</div></div></button>
      </div>
    </div>
    <div class="home-nav">
      <button class="nav-card likes ${st.web.locked ? "wiggle" : ""}" id="go-likes">${I.heart}
        ${st.web.locked ? `<span class="gem-badge">${I.gem}</span>` : ""}
        <div><div class="label">Your likes</div>
        <div class="meta"><span id="like-count">${st.totals.likes}</span> liked · ${st.web.count}/${st.web.limit} in web</div></div></button>
      <button class="nav-card" id="go-profile">${I.user}<div><div class="label">Your profile</div>
        <div class="meta">${st.batches_done} batch${st.batches_done === 1 ? "" : "es"} so far</div></div></button>
    </div>
  </div>`);
  app.replaceChildren(el);
  const cards = el.querySelectorAll(".hero-card:not(.main)");
  st.recent_likes.slice(0, 2).forEach((l, i) => l.thumb && (cards[i].style.backgroundImage = `url(${l.thumb})`));
  const hero = $(".swipe-hero", el);
  for (let i = 0; i < 7; i++) {
    const d = h(`<i class="ember-dot"></i>`);
    d.style.left = 30 + Math.random() * 40 + "%"; d.style.top = 55 + Math.random() * 20 + "%";
    d.style.animationDelay = Math.random() * 3.4 + "s";
    hero.appendChild(d);
  }
  const flingMsg = !cur ? "No batch yet. Tap to start one" : cur.status === "error" ? "That batch hit a snag. Tap to retry" : "Still brewing…";
  // a fling while it looks like nothing's ready re-checks, so a batch that finished since this screen drew still opens
  const recheck = !cur || cur.status === "error" ? null : async () => {
    try {
      const s = await loadState();
      if (s.current?.status !== "ready") return false;
      const left = s.current.listings.length - s.current.swiped;
      $("#go-swipe .sub", el).textContent = left ? `${left} waiting for you` : "Batch done. See your recap";
      return true;
    } catch { return false; }
  };
  heroFling($("#go-swipe", el), cards[1], !!cur && cur.status === "ready", flingMsg, recheck);
  $("#go-likes", el).onclick = () => go("likes");
  $("#go-profile", el).onclick = () => go("profile");
  $("#pchip", el).onclick = () => go("profile");
  flyNewLikes(el);
}

// The SWIPE card moves like a listing card: drag it, fling it past the same line in any direction
// (left, right or up) and it flies off the same way a swiped listing does, then the batch opens.
// Short drags spring back with the same bounce. A plain tap always opens the swipe screen (the
// batch, the brewing view, the new-batch form or retry). A fling only succeeds when a batch is
// ready to swipe through; otherwise the card springs back, wiggles and says why.
function heroFling(card, next, hasBatch, blockedMsg, recheck) {
  let sx = 0, sy = 0, dx = 0, dy = 0, dragging = false, moved = false, gone = false;
  const open = () => { if (!gone) { gone = true; go("swipe"); } };
  card.onclick = (e) => { if (moved) { e.preventDefault(); return; } open(); };  // taps and keyboard
  card.addEventListener("pointerdown", (e) => {
    if (gone) return;
    card.classList.remove("shake");
    dragging = true; moved = false; sx = e.clientX; sy = e.clientY; dx = dy = 0;
    card.setPointerCapture(e.pointerId); card.style.transition = "none";
  });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - sx; dy = e.clientY - sy;
    if (Math.hypot(dx, dy) > 6) moved = true;
    if (!moved) return;
    card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
    if (next) {  // the card underneath straightens up as this one leaves, like the deck's next card
      const k = Math.min(1, Math.max(Math.abs(dx), -dy) / 110);
      next.style.transition = "none";
      next.style.transform = `rotate(${6 * (1 - k)}deg) translate(${12 * (1 - k)}px, ${4 * (1 - k)}px) scale(${0.96 + 0.04 * k})`;
      next.style.opacity = 0.75 + 0.25 * k;
    }
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    if (!moved) return;  // a tap: the click handler opens it
    const side = dx > 110 ? 1 : dx < -110 ? -1 : 0;
    const up = !side && dy < -100 && Math.abs(dx) < 70;
    const flyOut = () => {
      card.style.transition = "transform .32s ease-in, opacity .32s";
      card.style.transform = side
        ? `translate(${side * window.innerWidth * 1.2}px, -40px) rotate(${side * 24}deg)`
        : `translate(${dx}px, ${-window.innerHeight}px) rotate(${dx / 18}deg)`;
      card.style.opacity = 0;
      setTimeout(open, 260);
    };
    if ((side || up) && !hasBatch) {
      card.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2)";
      card.style.transform = "";
      card.classList.remove("shake"); void card.offsetWidth;
      if (next) { next.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2), opacity .3s"; next.style.transform = ""; next.style.opacity = ""; }
      setTimeout(() => { moved = false; }, 0);
      // the fling is the check: the screen may be out of date, so ask whether the batch has finished since
      Promise.resolve(recheck ? recheck() : false).then((ready) => {
        if (gone) return;
        if (ready) { hasBatch = true; flyOut(); return; }
        card.classList.add("shake");
        toast(blockedMsg);
      });
      return;
    }
    if (side || up) { flyOut(); return; }
    card.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2)";
    card.style.transform = "";
    if (next) { next.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2), opacity .3s"; next.style.transform = ""; next.style.opacity = ""; }
    setTimeout(() => { moved = false; }, 0);  // let the click that follows a drag be ignored, then reset
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

// little animation: fresh likes fly from the swipe stack into the Likes card
function flyNewLikes(el) {
  const shown = new Set(store.get("flown", []));
  const fresh = S.state.recent_likes.filter((l) => l.thumb && !shown.has(l.id)).slice(0, 6);
  if (!fresh.length) return;
  const from = $("#go-swipe", el).getBoundingClientRect();
  const target = $("#go-likes", el);
  const to = target.getBoundingClientRect();
  const countEl = $("#like-count", el);
  const total = S.state.totals.likes;
  countEl.textContent = Math.max(0, total - fresh.length);
  fresh.forEach((l, i) => {
    const f = h(`<div class="flyer"></div>`);
    f.style.backgroundImage = `url(${l.thumb})`;
    const sx = from.left + from.width / 2 - 28 + (Math.random() - 0.5) * 60, sy = from.top + from.height / 2 - 28;
    const ex = to.left + 30, ey = to.top + 20;
    f.style.left = sx + "px"; f.style.top = sy + "px"; f.style.opacity = 0;
    document.body.appendChild(f);
    const mx = (sx + ex) / 2 - 80 + Math.random() * 40, my = Math.min(sy, ey) - 120;
    const anim = f.animate([
      { transform: "translate(0,0) scale(.4) rotate(0deg)", opacity: 0 },
      { transform: "translate(0,-20px) scale(1.05) rotate(-6deg)", opacity: 1, offset: 0.2 },
      { transform: `translate(${mx - sx}px,${my - sy}px) scale(.9) rotate(8deg)`, opacity: 1, offset: 0.6 },
      { transform: `translate(${ex - sx}px,${ey - sy}px) scale(.25) rotate(0deg)`, opacity: 0.2 },
    ], { duration: 1100, delay: 350 + i * 220, easing: "cubic-bezier(.45,.05,.4,1)", fill: "forwards" });
    anim.onfinish = () => {
      f.remove();
      countEl.textContent = Math.min(total, Number(countEl.textContent) + 1);
      target.classList.remove("bump"); void target.offsetWidth; target.classList.add("bump");
    };
  });
  store.set("flown", [...shown, ...fresh.map((l) => l.id)].slice(-400));
}

// ------------------------------------------------------------------ swipe
function renderSwipe() {
  const cur = S.state.current;
  const el = h(`<div class="screen">
    <div class="topbar"><button class="icon-btn" id="back">${I.back}</button>
      <h1>${cur ? "Batch " + cur.number : "Swipe"}</h1><span class="pill" id="counter"></span></div>
    <div id="swipe-body" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>
  </div>`);
  app.replaceChildren(el);
  $("#back", el).onclick = () => go("home");
  swipeBody();
}

function swipeBody() {
  const body = $("#swipe-body");
  const cur = S.state.current;
  const counter = $("#counter");
  $(".topbar h1").textContent = cur ? "Batch " + cur.number : "Swipe";
  if (!cur) return renderNewBatch(body);
  if (cur.status === "error") {
    counter.textContent = "";
    body.replaceChildren(h(`<div class="center-state"><div class="flame" style="opacity:.4">${I.flame}</div>
      <h2>That batch fizzled</h2><p>${esc(cur.error || "Something went wrong.")}</p>
      <button class="btn primary" id="retry">Try a new batch</button>
      <button class="btn ghost" id="edit">Adjust what I'm hunting for</button></div>`));
    $("#retry").onclick = () => startBatch();
    $("#edit").onclick = () => go("profile");
    return;
  }
  if (cur.status !== "ready") return renderBrewing(body, cur);
  const queue = cur.listings.filter((l) => !l.verdict);
  counter.textContent = `${cur.swiped} / ${cur.listings.length}`;
  if (!queue.length) {
    body.replaceChildren(h(`<div class="center-state"><h2>All swiped</h2><p>Opening your recap…</p></div>`));
    openDashboard(cur);
    return;
  }
  renderDeck(body, cur, queue);
}

const WEIRD_LEVELS = [
  [15, "On the nose", "Sticks to what you've liked and the searches that worked."],
  [40, "A little adventurous", "Mostly your taste, with a few new angles mixed in."],
  [65, "Off the beaten path", "Neighboring styles, materials and search terms you haven't tried."],
  [85, "Wildcard city", "Things you'd never search for that could still do the job."],
  [101, "Full chaos", "Ignores your taste so far. Only price and distance still apply."],
];
const weirdLevel = (w) => WEIRD_LEVELS.find(([max]) => w < max);

// "This batch only" prefixes: -word (not mentioned), !word (isn't that), $750 (under), +$100 (over)
function modInfo(m) {
  const money = /^(\+?)\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k)?$/i.exec(m);
  if (money) {
    const v = parseFloat(money[2].replace(/,/g, "")) * (money[3] ? 1000 : 1);
    const amt = "$" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
    return money[1] ? { cls: "rule", label: "over " + amt, kind: "over", v } : { cls: "rule", label: "under " + amt, kind: "under", v };
  }
  if (m.length > 1 && m[0] === "-") return { cls: "rule no", label: "never says “" + m.slice(1).trim() + "”", kind: "exclude" };
  if (m.length > 1 && m[0] === "!") return { cls: "rule no", label: "not " + m.slice(1).trim(), kind: "not" };
  return { cls: "", label: m, kind: "soft" };
}
const modChip = (m, x = "") => { const i = modInfo(m); return `<span class="chip mod ${i.cls}">${i.kind === "soft" ? "+ " : ""}${esc(i.label)}${x}</span>`; };

function renderNewBatch(body) {
  $("#counter").textContent = "";
  const p = S.state.profile;
  const bud = S.state.me.budget;
  if (S.state.mode.brain === "claude" && bud.over) {
    body.replaceChildren(h(`<div class="center-state">
      <div class="flame" style="opacity:.4">${I.flame}</div>
      <h2>Out of Claude for the week</h2>
      <p>You've used this week's $${bud.cap.toFixed(2)}. New batches open again ${esc(bud.resets_label)}. Your web, likes and keepers are all still here.</p>
      <button class="btn" id="go-likes2">Browse your likes</button>
    </div>`));
    $("#go-likes2").onclick = () => go("likes");
    return;
  }
  if (S.state.web.locked) {
    body.replaceChildren(h(`<div class="center-state">
      <div class="gem-big">${gemSvg(S.state.crystals + 1, true)}</div>
      <h2>Your web is full</h2>
      <p>${S.state.web.count} of ${S.state.web.limit}. Crystallize it to lock in what it learned and start a fresh web. Then the next batch is yours.</p>
      <button class="big-btn" disabled style="opacity:.35;filter:grayscale(1)">New batch<small>locked until you crystallize</small></button>
      <button class="btn primary" id="go-crys">◆ Go crystallize</button>
    </div>`));
    $("#go-crys").onclick = () => { location.hash = "likes"; setTimeout(openCrystallize, 350); };
    return;
  }
  let size = p.batch_size;
  let weird = p.weirdness ?? 25;
  const hasHunt = (p.hunt || "").trim().length > 3;
  const credits = () => (S.state.mode.source === "scrapecreators" ? ` · ~${size + 3} credits` : "");
  body.replaceChildren(h(`<div class="center-state scroll" style="justify-content:flex-start;padding-top:8px;overflow-y:auto">
    <div class="flame" style="width:64px;height:78px;flex:none">${I.flame}</div>
    <h2>${S.state.batches_done ? "Ready for more?" : (/^my /i.test(p.name) ? "Let's start the hunt" : "Let's find your " + esc(p.name.toLowerCase()))}</h2>
    <p>${hasHunt ? "Each batch learns from every swipe before it." : "Tell it what you're hunting for first, so the first batch isn't a shot in the dark."}</p>
    <div class="stepper"><button id="minus">−</button><b id="sz">${size} listings</b><button id="plus">+</button></div>
    <div class="weird">
      <div class="top"><b>Weirdness</b><span class="lvl" id="wl"></span></div>
      <input type="range" id="weird" min="0" max="100" step="5" value="${weird}">
      <div class="ends"><span>Safe</span><span>Wild</span></div>
      <p id="wd"></p>
    </div>
    <div class="weird mods">
      <div class="top"><b>Batch extras</b><span class="lvl" id="modcount"></span><button type="button" class="mod-clear" id="modclear" hidden>Clear</button></div>
      <form id="modform" class="mod-field" autocomplete="off">
        <span id="modchips"></span>
        <input id="modin" enterkeyhint="enter" maxlength="60" placeholder="Add a twist, then Enter">
      </form>
      <p class="mod-help"><b>-used</b> never mentions · <b>!leather</b> isn't · <b>$750</b> under · <b>+$100</b> over · anything else is a nudge. They carry over to the next batch until you remove them. Your saved hunt stays as is.</p>
    </div>
    <button class="big-btn" id="new" style="flex:none">New batch<small id="newsub"></small></button>
    ${hasHunt ? "" : '<button class="btn" id="setup">Set up the hunt</button>'}
    ${bud.cap != null && S.state.mode.brain === "claude" ? budgetMeter(bud) : ""}
  </div>`));
  const upd = () => {
    const [, name, desc] = weirdLevel(weird);
    $("#sz").textContent = size + " listings";
    $("#wl").textContent = `${weird} · ${name}`;
    $("#wd").textContent = desc;
    $("#newsub").textContent = `${size} listings${credits()}${weird >= 40 ? " · " + name.toLowerCase() : ""}`;
  };
  upd();
  $("#minus").onclick = () => { size = Math.max(3, size - 1); upd(); };
  $("#plus").onclick = () => { size = Math.min(40, size + 1); upd(); };
  $("#weird").oninput = (e) => { weird = +e.target.value; upd(); };

  // one field: type a topic, Enter turns it into a tile, keep typing the next one
  const mods = [...(S.state.last_modifiers || [])].slice(0, 8);
  const carried = mods.length;
  const modIn = $("#modin");
  const paintMods = () => {
    $("#modchips").innerHTML = mods.map((m, i) =>
      modChip(m, `<button type="button" data-i="${i}" aria-label="Remove ${esc(m)}">✕</button>`)).join("");
    const unders = mods.map(modInfo).filter((x) => x.kind === "under").map((x) => x.v);
    const overs = mods.map(modInfo).filter((x) => x.kind === "over").map((x) => x.v);
    if (unders.length && overs.length && Math.max(...overs) >= Math.min(...unders)) toast("Those price rules can't both be true.");
    $("#modchips").querySelectorAll("button").forEach((b) => (b.onclick = () => { mods.splice(+b.dataset.i, 1); paintMods(); modIn.focus(); }));
    const same = carried && mods.length === carried && mods.every((m, i) => m === S.state.last_modifiers[i]);
    $("#modcount").textContent = !mods.length ? "" : same ? "from last batch" : `${mods.length} extra${mods.length > 1 ? "s" : ""}`;
    $("#modclear").hidden = !mods.length;
  };
  $("#modclear").onclick = () => { mods.length = 0; paintMods(); };
  const addMod = () => {
    const parts = modIn.value.split(",").map((v) => v.trim()).filter(Boolean);
    for (const v of parts) if (mods.length < 8 && !mods.some((m) => m.toLowerCase() === v.toLowerCase())) mods.push(v);
    modIn.value = "";
    paintMods();
  };
  $("#modform").onsubmit = (e) => { e.preventDefault(); addMod(); modIn.focus(); };
  modIn.addEventListener("input", () => { if (modIn.value.includes(",")) addMod(); });
  modIn.addEventListener("keydown", (e) => {
    if (e.key === "Backspace" && !modIn.value && mods.length) { mods.pop(); paintMods(); }
  });
  $(".mod-field").addEventListener("click", (e) => { if (e.target.classList.contains("mod-field")) modIn.focus(); });
  paintMods();

  $("#new").onclick = () => { if (modIn.value.trim()) addMod(); startBatch(size, weird, mods); };
  $("#setup") && ($("#setup").onclick = () => go("profile"));
}

async function startBatch(size, weirdness, modifiers = []) {
  try {
    await api("/batches", { body: { size, weirdness, modifiers } });
  } catch (e) { toast(e.message); }
  await loadState();
  swipeBody();
}

const STAGES = { queued: 0.05, searching: 0.2, screening: 0.45, scoring: 0.7 };
function renderBrewing(body, cur) {
  $("#counter").textContent = "";
  body.replaceChildren(h(`<div class="center-state">
    <div class="flame">${I.flame}</div>
    <h2>Brewing batch ${cur.number}</h2>
    <p id="prog">${esc(cur.progress || "Getting started")}</p>
    <div class="progress"><i id="bar" style="width:${(STAGES[cur.status] || 0.1) * 100}%"></i></div>
    <div class="chips" id="qs"></div>
    <p style="font-size:13px">Usually a minute or two. You can leave, it keeps going.</p>
  </div>`));
  const paint = (c) => {
    $("#prog").textContent = c.progress || "";
    let frac = STAGES[c.status] || 0.1;
    const m = /Looked at (\d+) of (\d+)/.exec(c.progress || "");
    if (m) frac = 0.7 + 0.28 * (Number(m[1]) / Number(m[2]));
    $("#bar").style.width = frac * 100 + "%";
    $("#qs").innerHTML = (c.weirdness != null ? `<span class="chip">weirdness ${c.weirdness}</span>` : "")
      + (c.modifiers || []).map((m) => modChip(m)).join("")
      + (c.queries || []).map((q) => `<span class="chip">${esc(q)}</span>`).join("");
  };
  paint(cur);
  S.poll = setInterval(async () => {
    try {
      const st = await loadState();
      if (!st.current || st.current.status === "ready" || st.current.status === "error") {
        clearInterval(S.poll); S.poll = null;
        renderSwipe();
      } else paint(st.current);
    } catch {}
  }, 2000);
}

function cardEl(l) {
  const photos = l.photos?.length ? l.photos : [""];
  const el = h(`<div class="card">
    <div class="photo"></div>
    <div class="dots">${photos.length > 1 ? photos.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("") : ""}</div>
    ${l.explore ? '<div class="wildcard">Wildcard</div>' : ""}
    <div class="match">${pct(l.predicted)} match</div>
    <div class="tap-zone l"></div><div class="tap-zone r"></div>
    <div class="stamp like">LIKE</div><div class="stamp nope">NOPE</div><div class="stamp more">WHY?</div>
    <div class="shade"></div>
    <div class="info"><div class="title">${esc(l.title)}</div>
      <div class="row"><span class="price">${esc(money(l))}</span><span class="loc">${esc(l.location_text || "")}</span></div>
      <div class="hint">Swipe up for why it was picked</div></div>
  </div>`);
  let idx = 0;
  const photo = $(".photo", el);
  const show = () => {
    photo.style.backgroundImage = photos[idx] ? `url(${photos[idx]})` : "none";
    el.querySelectorAll(".dots i").forEach((d, i) => d.classList.toggle("on", i === idx));
  };
  show();
  el._step = (dir) => { idx = (idx + dir + photos.length) % photos.length; show(); };
  el._open = () => photos[idx] && openViewer(photos, idx);
  // top of the card: edges flip photos, the middle opens full screen
  el._tapPhoto = (xr) => (xr < 0.3 ? el._step(-1) : xr > 0.7 ? el._step(1) : el._open());
  return el;
}

function renderDeck(body, cur, queue) {
  body.replaceChildren(h(`<div style="flex:1;display:flex;flex-direction:column;min-height:0">
    <div class="deck-wrap" id="deck"></div>
    <div class="actions">
      <button class="act small" id="undo" title="Undo">${I.undo}</button>
      <button class="act nope" id="nope">${I.x}</button>
      <button class="act small info" id="why">${I.info}</button>
      <button class="act like" id="like">${I.heart}</button>
    </div></div>`));
  const deck = $("#deck");
  let top, next;

  const mount = () => {
    deck.innerHTML = "";
    const pending = cur.listings.filter((l) => !l.verdict);
    if (!pending.length) { swipeBody(); return; }
    $("#counter").textContent = `${cur.swiped} / ${cur.listings.length}`;
    if (pending[1]) { next = cardEl(pending[1]); next.classList.add("behind"); deck.appendChild(next); }
    top = cardEl(pending[0]); top._l = pending[0];
    deck.appendChild(top);
    bindGestures(top);
    pending.slice(2, 4).forEach((l) => l.photos?.[0] && (new Image().src = l.photos[0]));
  };

  const decide = async (verdict, card) => {
    if (recentlyClosed() || $("#sheet-root").childElementCount || card._deciding) return;
    card._deciding = true;  // the card stays mounted for 260ms; a second tap must not re-decide it
    const l = card._l;
    const dir = verdict === "like" ? 1 : -1;
    card.style.transition = "transform .32s ease-in, opacity .32s";
    card.style.transform = `translate(${dir * window.innerWidth * 1.2}px, -40px) rotate(${dir * 24}deg)`;
    card.style.opacity = 0;
    l.verdict = verdict; cur.swiped++;
    S.undo.push(l);
    setTimeout(mount, 260);
    try { await api("/swipe", { body: { listing_id: l.id, verdict } }); }
    catch (e) { toast("Didn't save that swipe: " + e.message); l.verdict = null; cur.swiped--; mount(); }
  };

  function bindGestures(card) {
    let sx = 0, sy = 0, dx = 0, dy = 0, dragging = false, moved = false;
    const like = $(".stamp.like", card), nope = $(".stamp.nope", card), more = $(".stamp.more", card);
    card.addEventListener("pointerdown", (e) => {
      if (recentlyClosed()) return;
      dragging = true; moved = false; sx = e.clientX; sy = e.clientY; dx = dy = 0;
      card.setPointerCapture(e.pointerId); card.style.transition = "none";
    });
    card.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dx = e.clientX - sx; dy = e.clientY - sy;
      if (Math.hypot(dx, dy) > 6) moved = true;
      card.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 18}deg)`;
      like.style.opacity = Math.max(0, Math.min(1, dx / 110));
      nope.style.opacity = Math.max(0, Math.min(1, -dx / 110));
      more.style.opacity = Math.abs(dx) < 60 ? Math.max(0, Math.min(1, -dy / 110)) : 0;
      if (next) next.style.transform = `scale(${0.94 + Math.min(0.06, Math.abs(dx) / 2500)}) translateY(${14 - Math.min(14, Math.abs(dx) / 20)}px)`;
    });
    const end = (e) => {
      if (!dragging) return;
      dragging = false;
      if (dx > 110) return decide("like", card);
      if (dx < -110) return decide("dislike", card);
      card.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2)";
      card.style.transform = "";
      like.style.opacity = nope.style.opacity = more.style.opacity = 0;
      if (next) next.style.transform = "";
      if (dy < -100 && Math.abs(dx) < 70) return openListing(card._l.id, { why: true });
      if (!moved && e.type === "pointerup") {
        const r = card.getBoundingClientRect();
        const xr = (e.clientX - r.left) / r.width, yr = (e.clientY - r.top) / r.height;
        if (yr < 0.6) card._tapPhoto(xr);
        else openListing(card._l.id, { why: true });
      }
    };
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
  }

  $("#like").onclick = () => top && decide("like", top);
  $("#nope").onclick = () => top && decide("dislike", top);
  $("#why").onclick = () => top && openListing(top._l.id, { why: true });
  $("#undo").onclick = async () => {
    const l = S.undo.pop();
    if (!l || !cur.listings.includes(l)) return toast("Nothing to undo");
    await api("/swipe/" + l.id, { method: "DELETE" });
    l.verdict = null; cur.swiped--;
    const i = cur.listings.indexOf(l);
    cur.listings.splice(i, 1);
    const firstPending = cur.listings.findIndex((x) => !x.verdict);
    cur.listings.splice(firstPending < 0 ? cur.listings.length : firstPending, 0, l);
    mount();
  };
  mount();
}

// ------------------------------------------------------------------ full-screen photo viewer
// Pinch or double-tap to zoom, drag to pan, swipe sideways between photos, swipe down or ✕ to close.
function openViewer(photos, start = 0) {
  photos = (photos || []).filter(Boolean);
  if (!photos.length) return;
  let i = Math.max(0, Math.min(start, photos.length - 1));
  const v = h(`<div class="viewer" role="dialog" aria-label="Photo viewer">
    <div class="vstage"><img class="vimg" alt=""></div>
    <div class="vbar"><span class="vcount"></span><button class="vx" aria-label="Close">${I.x}</button></div>
    <div class="vdots"></div>
    ${photos.length > 1 ? '<button class="vnav prev" aria-label="Previous">‹</button><button class="vnav next" aria-label="Next">›</button>' : ""}
  </div>`);
  document.body.appendChild(v);
  const stage = $(".vstage", v), img = $(".vimg", v);
  let s = 1, tx = 0, ty = 0;               // current zoom and pan
  const pts = new Map();                   // active pointers
  let g = null;                            // gesture in progress
  let lastTap = { t: 0, x: 0, y: 0 };

  const apply = (anim) => {
    img.style.transition = anim ? "transform .22s ease" : "none";
    img.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
  };
  const fitted = () => {  // on-screen size of the photo at zoom 1 (object-fit: contain)
    const W = stage.clientWidth, H = stage.clientHeight;
    const r = (img.naturalWidth || W) / (img.naturalHeight || H);
    return W / H > r ? { w: H * r, h: H, W, H } : { w: W, h: W / r, W, H };
  };
  const clamp = () => {
    const f = fitted();
    const mx = Math.max(0, (f.w * s - f.W) / 2), my = Math.max(0, (f.h * s - f.H) / 2);
    tx = Math.max(-mx, Math.min(mx, tx));
    ty = Math.max(-my, Math.min(my, ty));
  };
  const zoomAt = (ns, cx, cy) => {  // keep the point under the fingers still while zooming
    ns = Math.max(1, Math.min(6, ns));
    const r = stage.getBoundingClientRect();
    const px = cx - r.left - r.width / 2, py = cy - r.top - r.height / 2;
    tx = px - (px - tx) * (ns / s);
    ty = py - (py - ty) * (ns / s);
    s = ns;
    if (s === 1) { tx = 0; ty = 0; }
    clamp();
  };
  const show = (dir = 0) => {
    s = 1; tx = 0; ty = 0; apply(false);
    img.src = photos[i];
    $(".vcount", v).textContent = photos.length > 1 ? `${i + 1} / ${photos.length}` : "";
    $(".vdots", v).innerHTML = photos.length > 1 ? photos.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("") : "";
    if (dir) img.animate([{ transform: `translateX(${dir * 40}px)`, opacity: 0.3 }, { transform: "none", opacity: 1 }], { duration: 180 });
  };
  const go = (d) => { if (photos.length > 1) { i = (i + d + photos.length) % photos.length; show(d); } };
  const close = () => {
    v.classList.add("closing");
    setTimeout(() => v.remove(), 180);
    document.removeEventListener("keydown", onKey);
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "ArrowRight") go(1);
    if (e.key === "ArrowLeft") go(-1);
  };
  document.addEventListener("keydown", onKey);
  $(".vx", v).onclick = close;
  $(".prev", v) && ($(".prev", v).onclick = () => go(-1));
  $(".next", v) && ($(".next", v).onclick = () => go(1));

  stage.addEventListener("pointerdown", (e) => {
    stage.setPointerCapture(e.pointerId);
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      g = { type: "pinch", d0: Math.hypot(a.x - b.x, a.y - b.y), s0: s };
    } else if (pts.size === 1) {
      g = { type: "one", x0: e.clientX, y0: e.clientY, tx0: tx, ty0: ty, moved: 0, t0: Date.now() };
    }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId) || !g) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (g.type === "pinch" && pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      zoomAt(g.s0 * (d / g.d0), (a.x + b.x) / 2, (a.y + b.y) / 2);
      apply(false);
    } else if (g.type === "one") {
      const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
      g.moved = Math.max(g.moved, Math.hypot(dx, dy));
      if (s > 1) {                       // zoomed: pan around
        tx = g.tx0 + dx; ty = g.ty0 + dy; clamp(); apply(false);
      } else if (Math.abs(dy) > Math.abs(dx) && dy > 0) {   // pull down to close
        img.style.transition = "none";
        img.style.transform = `translateY(${dy}px) scale(${Math.max(0.8, 1 - dy / 1500)})`;
        v.style.backgroundColor = `rgba(0,0,0,${Math.max(0.3, 0.96 - dy / 500)})`;
      } else {                           // drag sideways to the next photo
        img.style.transition = "none";
        img.style.transform = `translateX(${dx}px)`;
      }
    }
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (g?.type === "pinch") {
      if (pts.size === 1) {              // one finger left: carry on as a pan from here
        const [p] = [...pts.values()];
        g = { type: "one", x0: p.x, y0: p.y, tx0: tx, ty0: ty, moved: 99, t0: 0 };
      } else { g = null; if (s < 1.05) { s = 1; tx = 0; ty = 0; } apply(true); }
      return;
    }
    if (!g || g.type !== "one") return;
    const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
    const moved = g.moved;
    g = null;
    if (moved < 8) {                     // a tap: double-tap toggles zoom
      const now = Date.now();
      if (now - lastTap.t < 300 && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 30) {
        if (s > 1) { s = 1; tx = 0; ty = 0; } else zoomAt(2.5, e.clientX, e.clientY);
        apply(true);
        lastTap = { t: 0, x: 0, y: 0 };
      } else lastTap = { t: now, x: e.clientX, y: e.clientY };
      return;
    }
    if (s > 1) return;
    v.style.backgroundColor = "";
    if (dy > 110 && Math.abs(dy) > Math.abs(dx)) return close();
    if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy)) return go(dx < 0 ? 1 : -1);
    apply(true);                          // snap back
  };
  stage.addEventListener("pointerup", up);
  stage.addEventListener("pointercancel", up);
  stage.addEventListener("wheel", (e) => {  // trackpad / mouse wheel zoom on desktop
    e.preventDefault();
    zoomAt(s * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX, e.clientY);
    apply(false);
  }, { passive: false });
  show();
}

// ------------------------------------------------------------------ listing sheet
let sheetOnClose = null, sheetClosedAt = 0;
// taps that land right after a sheet closes are ghosts, never swipes
const recentlyClosed = () => Date.now() - sheetClosedAt < 400;
function closeSheet() {
  const root = $("#sheet-root");
  if (root.childElementCount) {
    root.innerHTML = "";
    sheetClosedAt = Date.now();
    const f = sheetOnClose; sheetOnClose = null; f?.();
  }
}
function openSheet(content, onClose) {
  closeSheet();
  const root = $("#sheet-root");
  const back = h(`<div class="backdrop"></div>`);
  const sheet = h(`<div class="sheet"><div class="sheet-head"><div class="grab"></div>
    <button class="sheet-x" aria-label="Close">${I.x}</button></div><div class="body"></div></div>`);
  const body = $(".body", sheet), head = $(".sheet-head", sheet);
  body.appendChild(content);

  const animateClose = () => {
    sheet.classList.add("settle");
    sheet.style.transform = "translateY(105%)";
    back.style.transition = "opacity .2s"; back.style.opacity = 0;
    setTimeout(closeSheet, 200);
  };
  back.addEventListener("click", animateClose);
  $(".sheet-x", sheet).addEventListener("click", (e) => { e.stopPropagation(); animateClose(); });

  // drag the sheet down to dismiss: from the handle anytime, from the content when it's scrolled to the top
  let sx = 0, sy = null, dy = 0, decided = false;
  const begin = (x, y, inBody) => {
    if (inBody && body.scrollTop > 2) return;
    sx = x; sy = y; dy = 0; decided = !inBody;
  };
  const move = (x, y, e) => {
    if (sy == null) return;
    const ddx = x - sx, ddy = y - sy;
    if (!decided) {
      if (Math.abs(ddx) < 6 && Math.abs(ddy) < 6) return;
      if (Math.abs(ddx) > Math.abs(ddy) || ddy < 0) { sy = null; return; }  // sideways (photos) or scrolling up
      decided = true;
    }
    dy = Math.max(0, ddy);
    if (e.cancelable) e.preventDefault();
    sheet.classList.remove("settle");
    sheet.style.transform = `translateY(${dy}px)`;
    back.style.opacity = Math.max(0.15, 1 - dy / 450);
  };
  const end = () => {
    if (sy == null) return;
    sy = null;
    if (dy > 90) return animateClose();
    sheet.classList.add("settle");
    sheet.style.transform = ""; back.style.opacity = "";
  };
  head.addEventListener("touchstart", (e) => begin(e.touches[0].clientX, e.touches[0].clientY, false), { passive: true });
  body.addEventListener("touchstart", (e) => begin(e.touches[0].clientX, e.touches[0].clientY, true), { passive: true });
  sheet.addEventListener("touchmove", (e) => move(e.touches[0].clientX, e.touches[0].clientY, e), { passive: false });
  sheet.addEventListener("touchend", end);
  sheet.addEventListener("touchcancel", end);
  head.addEventListener("mousedown", (e) => {
    begin(e.clientX, e.clientY, false);
    const mm = (ev) => move(ev.clientX, ev.clientY, ev);
    const mu = () => { end(); removeEventListener("mousemove", mm); removeEventListener("mouseup", mu); };
    addEventListener("mousemove", mm); addEventListener("mouseup", mu);
  });

  root.append(back, sheet);
  sheetOnClose = onClose;
}

function checklistHtml(items) {
  if (!items?.length) return '<p class="empty">No checklist yet. Add one on your profile.</p>';
  const ic = { yes: "✓", no: "✕", unsure: "?" };
  return items.map((c) => `<div class="check"><div class="ic ${c.status}">${ic[c.status] || "?"}</div>
    <div><b>${esc(c.item)}</b><span>${esc(c.note || "")}</span></div></div>`).join("");
}

async function openListing(id, { why = false, onChange } = {}) {
  let l;
  try { l = await api("/listing/" + id); } catch (e) { return toast(e.message); }
  const color = d3.interpolateRgbBasis(["#ff5a5f", "#f1b24a", "#4cc38a"]);
  const c = h(`<div>
    <div class="gallery">${(l.photos || []).map((p, i) => `<img src="${p}" data-i="${i}" loading="lazy" alt="Photo ${i + 1}">`).join("")}</div>
    <h2>${esc(l.title)}</h2>
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <span style="font-family:var(--display);font-weight:800;font-size:22px;color:var(--gold)">${esc(money(l))}</span>
      <span class="pill">${esc(l.location_text || "")}</span>
      ${l.explore ? '<span class="pill warn">Wildcard pick</span>' : ""}</div>
    <div class="section"><h4>Why it was picked</h4>
      <div style="display:flex;justify-content:space-between;font-size:14px"><span>Predicted match</span><b>${pct(l.predicted)}</b></div>
      <div class="meter"><i style="width:${pct(l.predicted)};background:${color(l.predicted ?? 0.5)}"></i></div>
      <div style="display:flex;gap:14px;font-size:12px;color:var(--muted);margin-top:6px">
        <span>Claude: ${Math.round(l.claude_score ?? 50)}%</span><span>Your swipe history: ${pct(l.model_score)}</span></div>
      ${l.take ? `<div class="take" style="margin-top:12px">${esc(l.take)}</div>` : ""}</div>
    <div class="section"><h4>Checklist</h4>${checklistHtml(l.checklist)}</div>
    ${l.verdict ? `<div class="section"><h4>Your call</h4><div class="verdict-toggle">
      <button data-v="dislike" class="${l.verdict === "dislike" ? "on dislike" : ""}">Pass</button>
      <button data-v="like" class="${l.verdict === "like" ? "on like" : ""}">Like</button></div></div>` : ""}
    ${l.groups?.length ? `<div class="section"><h4>In your categories</h4><div class="chips" style="justify-content:flex-start">
      ${l.groups.map((g) => `<span class="chip">${esc(g.label)}<button data-g="${g.id}" aria-label="Remove">✕</button></span>`).join("")}</div></div>` : ""}
    <div class="section"><h4>Traits</h4><div class="chips" style="justify-content:flex-start">
      ${(l.tags || []).map((t) => `<span class="chip">${esc(t.split(":").slice(1).join(":"))}</span>`).join("") || '<span class="empty">None yet</span>'}</div></div>
    <div class="section"><h4>Details</h4><dl class="kv">
      <dt>Condition</dt><dd>${esc(l.condition || "Not listed")}</dd>
      ${l.features?.width_in ? `<dt>Width</dt><dd>${esc(l.features.width_in)}"</dd>` : ""}
      <dt>Found by</dt><dd>"${esc(l.query || "")}"</dd>
      ${(l.fb_attributes || []).filter((a) => a.name !== "Condition").map((a) => `<dt>${esc(a.name)}</dt><dd>${esc(a.value)}</dd>`).join("")}
    </dl></div>
    ${l.description ? `<div class="section"><h4>Seller says</h4><div class="desc">${esc(l.description)}</div></div>` : ""}
    <div class="section">
      <a class="btn primary" style="display:block;text-align:center;text-decoration:none" href="${esc(l.url)}" target="_blank" rel="noopener">Open on Facebook</a></div>
  </div>`);
  if (!why) c.querySelector(".section h4").textContent = "How it scored";
  c.querySelectorAll(".gallery img").forEach((img) => (img.onclick = () => openViewer(l.photos, +img.dataset.i)));
  c.querySelectorAll(".verdict-toggle button").forEach((b) => (b.onclick = async () => {
    const v = b.dataset.v;
    await api("/rank", { body: { listing_id: l.id, rank: v === "like" ? 0.75 : 0.25 } });
    c.querySelectorAll(".verdict-toggle button").forEach((x) => (x.className = x.dataset.v === v ? "on " + v : ""));
    onChange?.();
  }));
  c.querySelectorAll("[data-g]").forEach((b) => (b.onclick = async () => {
    await api(`/groups/${b.dataset.g}/members/${l.id}`, { method: "DELETE" });
    b.parentElement.remove();
    onChange?.();
  }));
  openSheet(c);
}

// ------------------------------------------------------------------ grouping dialog
function groupDialog(a, b) {
  return new Promise(async (resolve) => {
    const existing = await api("/groups").catch(() => []);
    const shared = existing.filter((g) => g.members.includes(b.id) || g.members.includes(a.id));
    const back = h(`<div class="backdrop" style="z-index:74"></div>`);
    const dlg = h(`<div class="dialog">
      <h3>Group these two?</h3>
      <p>${esc(a.title)} + ${esc(b.title)}</p>
      ${shared.length ? `<div class="chips" style="justify-content:flex-start;margin-bottom:10px">
        ${shared.map((g) => `<button class="chip" data-g="${g.id}">Add to "${esc(g.label)}"</button>`).join("")}</div>` : ""}
      <div class="field" style="margin:0"><label>New category name</label>
        <input id="glabel" placeholder="e.g. cozy greens, too formal, apartment-sized" maxlength="60"></div>
      <div class="row"><button class="btn ghost" id="gc">Cancel</button><button class="btn primary" id="gok">Group</button></div>
    </div>`);
    const done = (v) => { back.remove(); dlg.remove(); resolve(v); };
    document.body.append(back, dlg);
    setTimeout(() => $("#glabel", dlg).focus(), 50);
    back.onclick = () => done(false);
    $("#gc", dlg).onclick = () => done(false);
    dlg.querySelectorAll("[data-g]").forEach((btn) => (btn.onclick = async () => {
      await api(`/groups/${btn.dataset.g}/members`, { body: { listing_ids: [a.id, b.id] } });
      toast("Added"); done(true);
    }));
    $("#gok", dlg).onclick = async () => {
      const label = $("#glabel", dlg).value.trim();
      if (!label) return $("#glabel", dlg).focus();
      await api("/groups", { body: { label, listing_ids: [a.id, b.id] } });
      toast(`Grouped as "${label}"`); done(true);
    };
  });
}

function mountWeb(container, batchId) {
  return createWeb(container, {
    load: () => api("/graph" + (batchId ? "?batch_id=" + batchId : "")),
    onSelect: (id) => openListing(id, { onChange: () => S.web?.refresh() }),
    onRank: async (id, rank) => {
      try { await api("/rank", { body: { listing_id: id, rank } }); }
      catch (e) { toast(e.message); }
    },
    onGroup: groupDialog,
    onLinkTap: (msg) => toast(msg),
    onExport: () => exportDialog(batchId),
    emptyText: batchId ? "Nothing swiped in this batch yet." : "Swipe a batch and your web shows up here.",
  });
}

function budgetMeter(b) {
  const frac = b.cap ? Math.min(1, b.spent / b.cap) : 0;
  return `<div class="budget"><div class="brow"><span>Claude this week</span><b>$${b.spent.toFixed(2)} of $${b.cap.toFixed(2)}</b></div>
    <div class="meter"><i style="width:${frac * 100}%;background:${frac > 0.85 ? "var(--nope)" : frac > 0.6 ? "var(--maybe)" : "var(--like)"}"></i></div>
    <div class="mode-note">Resets ${esc(b.resets_label)}. A batch usually runs about $0.20.</div></div>`;
}

// ------------------------------------------------------------------ export
// Names to leave out, from a CSV/text file: one per row, or the "Name" column if there's a header.
function parseNameList(text, sep = ",") {
  const rows = [];
  let row = [], cell = "", q = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === sep) { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  row.push(cell); rows.push(row);
  const full = rows.filter((r) => r.some((x) => x.trim()));
  let col = 0;
  const hi = full.length ? full[0].findIndex((x) => /^(name|title|listing( name)?)$/i.test(x.trim())) : -1;
  if (hi >= 0) { col = hi; full.shift(); }
  return [...new Set(full.map((r) => (r[col] || "").trim()).filter(Boolean))];
}

function exportDialog(batchId, keepers = false) {
  const q = keepers ? "keepers=true&" : batchId ? `batch_id=${batchId}&` : "";
  const back = h(`<div class="backdrop" style="z-index:74"></div>`);
  const dlg = h(`<div class="dialog">
    <div class="dlg-head">
      <h3>Export ${keepers ? "your keepers" : batchId ? "this batch" : "your web"}</h3>
      <div class="tabs" style="margin:0"><button class="on" data-t="new">New</button><button data-t="upd">Update</button><button data-t="avail">Availability</button></div>
      <div id="ex-status" class="ex-status" hidden></div>
    </div>
    <div id="ex-new">
      <details><summary>What's included</summary>
        <p class="mode-note">Name, link, price, top 5 qualities, your ranking, your call, and Claude's expected approval, best-ranked first. The Excel file also has each listing's area and drive distance and time from your profile address, and is the only one with photos. Copy, then paste into cell A1 of a sheet.</p></details>
      <div class="stack">
        <button class="btn primary xact" id="ex-copy">Copy for Google Sheets</button>
        <a class="btn xact btn-link" id="ex-xlsx" href="/api/export?${q}fmt=xlsx" download>Download Excel, with photos</a>
        <a class="btn xact btn-link" id="ex-csv" href="/api/export?${q}fmt=csv" download>Download CSV</a>
      </div>
      <div class="field-group"><textarea id="ex-skiptext" rows="2" placeholder="Leave some out: paste names here, one per line"></textarea>
        <div class="field-foot"><label class="btn ghost">Or upload a file<input type="file" id="ex-skipfile" accept=".csv,.txt,text/csv,text/plain" hidden></label>
        <span class="mode-note" id="ex-skipnote">Those listings are left out; everything else is exported.</span></div></div>
    </div>
    <div id="ex-upd" hidden>
      <p>Get only the listings that aren't in an earlier export, so you can add them to the same sheet.</p>
      <label class="mode-note" for="ex-type" style="display:block;margin:0 0 4px">Your original export was</label>
      <select id="ex-type"><option value="sheets">Copy for Google Sheets</option><option value="xlsx">Excel, with photos</option><option value="csv">CSV</option></select>
      <div class="stack two">
        <button class="btn primary xact" id="up-copy">Copy to update</button>
        <a class="btn xact btn-link" id="up-dl" href="#" download>Download to update</a>
      </div>
      <div class="field-group"><textarea id="up-text" rows="3"></textarea>
        <div class="field-foot"><label class="btn ghost">Or upload the original<input type="file" id="up-file" hidden></label>
        <span class="mode-note" id="up-note"></span></div></div>
    </div>
    <div id="ex-av" hidden>
      <p>Paste an exported column of listing links (best) or names, in your sheet's order. You get one answer per row, same order: Available, Unavailable or Failed to find. Paste it into a new column.</p>
      <textarea id="av-text" rows="4" placeholder="Paste the Link column (or the Name column) here, one per line"></textarea>
      <span class="mode-note" id="av-note" style="display:block;margin:6px 0 10px"></span>
      <button class="btn primary xact" id="av-copy" style="width:100%">Copy availability</button>
      <details style="margin-top:10px"><summary>How it works</summary>
        <p class="mode-note">Links are safest: they identify the exact listing. Names only work for listings your app has seen. This asks Facebook for each listing, so it uses a few credits (shown when done). A listing that's been removed may show as Failed to find.</p></details>
    </div>
    <div class="row"><button class="btn ghost" id="ex-x">Close</button></div></div>`);
  const done = () => { back.remove(); dlg.remove(); };
  document.body.append(back, dlg);
  back.onclick = done;
  $("#ex-x", dlg).onclick = done;

  // New: names to leave out. Update: names found in the original export. Each tab keeps its own.
  let tab = "new", skipNew = [], skipOld = [];
  const exclude = () => (tab === "new" ? skipNew : skipOld);
  const doFetch = (url, ex = exclude()) => ex.length
    ? fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ exclude: ex }) })
    : fetch(url);
  dlg.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    tab = b.dataset.t;
    dlg.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $("#ex-new", dlg).hidden = tab !== "new";
    $("#ex-upd", dlg).hidden = tab !== "upd";
    $("#ex-av", dlg).hidden = tab !== "avail";
  }));
  // Availability tab: lines stay in place (blank rows too) so the answers line up with the sheet
  const avLines = () => $("#av-text", dlg).value.replace(/\s+$/, "").split(/\r?\n/).map((s) => s.trim());
  $("#av-text", dlg).oninput = () => {
    const n = avLines().filter(Boolean).length;
    $("#av-note", dlg).textContent = n ? `${n} listing${n === 1 ? "" : "s"} to check.` : "";
  };

  // New tab: the box is line-based, each line one whole name (commas stay part of the name)
  const setSkip = (text) => {
    skipNew = [...new Set(text.split(/\r?\n/).map((s) => s.trim().replace(/^"(.*)"$/, "$1").trim()).filter(Boolean))];
    $("#ex-skipnote", dlg).textContent = skipNew.length ? `Leaving out ${skipNew.length} name${skipNew.length === 1 ? "" : "s"}.` : "Those listings are left out; everything else is exported.";
  };
  $("#ex-skiptext", dlg).oninput = (e) => setSkip(e.target.value);
  $("#ex-skipfile", dlg).onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    // a CSV file is read by column, then shown in the box one name per line
    const text = parseNameList(await f.text()).join("\n");
    $("#ex-skiptext", dlg).value = text;
    setSkip(text);
  };

  // Update tab: read the original export in whatever form it was made
  const type = () => $("#ex-type", dlg).value;
  const upNote = () => ($("#up-note", dlg).textContent = skipOld.length ? `${skipOld.length} original listing${skipOld.length === 1 ? "" : "s"} found.` : "");
  const readPasted = () => {
    const t = $("#up-text", dlg).value;
    skipOld = type() === "csv" ? parseNameList(t) : parseNameList(t, "\t");  // cells copied from Sheets or Excel paste tab-separated
    upNote();
  };
  const setType = () => {
    const t = type();
    $("#up-text", dlg).placeholder = t === "sheets" ? "Paste the sheet here (select all in Google Sheets, copy, paste). The Name column is read."
      : t === "csv" ? "Paste the CSV text here, or upload the file. The Name column is read."
      : "Paste the cells copied from Excel here (select all, copy, paste), or upload the .xlsx file. The Name column is read.";
    $("#up-file", dlg).accept = t === "xlsx" ? ".xlsx" : ".csv,.tsv,.txt,text/csv,text/plain";
    $("#up-dl", dlg).href = `/api/export?${q}fmt=${t === "xlsx" ? "xlsx" : "csv"}`;
    $("#up-text", dlg).value = ""; skipOld = []; upNote();
  };
  $("#ex-type", dlg).onchange = setType;
  $("#up-text", dlg).oninput = readPasted;
  $("#up-file", dlg).onchange = async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      if (type() === "xlsx") {
        const res = await fetch("/api/export/names", { method: "POST", body: await f.arrayBuffer() });
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "couldn't read it");
        skipOld = (await res.json()).names;
      } else {
        const text = await f.text();
        $("#up-text", dlg).value = text;
        skipOld = parseNameList(text, /\t/.test(text.split("\n")[0]) ? "\t" : ",");
      }
      upNote();
    } catch (err) { toast("Couldn't read that file: " + err.message); }
  };
  setType();
  const needOriginal = () => {
    if (tab === "upd" && !skipOld.length) { toast("Paste or upload your original export first."); return true; }
    return false;
  };

  // One export at a time, but the rest of the dialog stays usable while it's prepared.
  // Status line at the top shows what's running; settings are read when the button is tapped.
  const status = (msg, working) => {
    const el = $("#ex-status", dlg);
    el.hidden = !msg;
    el.textContent = msg || "";
    el.classList.toggle("working", !!working);
  };
  const run = async (el, msg, job) => {
    if (dlg.classList.contains("busy") || needOriginal()) return;
    const label = el.textContent;
    dlg.classList.add("busy"); el.classList.add("working");
    el.textContent = "Preparing…";
    status(msg, true);
    try { status(await job() || "", false); }
    catch (err) { status("", false); toast("Export failed: " + err.message); }
    dlg.classList.remove("busy"); el.classList.remove("working"); el.textContent = label;
  };
  // fetch first, so a server error shows as a message instead of being saved as the file
  const download = (el) => el.addEventListener("click", (e) => {
    e.preventDefault();
    const isX = el.id === "ex-xlsx" || (el.id === "up-dl" && type() === "xlsx");
    const ex = exclude().slice();
    run(el, isX ? "Building your Excel file with photos… this can take a minute. You can keep editing." : "Building your file…", async () => {
      const res = await doFetch(el.getAttribute("href"), ex);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "export failed");
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "")?.[1] || "kindling-export";
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await res.blob()), download: name });
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      return `Done: ${name} downloaded${ex.length ? `, ${res.headers.get("X-Excluded") || 0} left out` : ""}.`;
    });
  });
  download($("#ex-csv", dlg));
  download($("#ex-xlsx", dlg));
  download($("#up-dl", dlg));
  const copy = (e) => {
    const upd = tab === "upd", like = upd && type() === "xlsx", ex = exclude().slice();
    run(e.currentTarget, "Preparing your copy…" + (like ? " This can take a minute." : ""), async () => {
      const res = await doFetch(`/api/export?${q}fmt=tsv${upd ? "&bare=1" + (like ? "&like=xlsx" : "") : ""}`, ex);
      if (!res.ok) throw new Error("export failed");
      const text = await res.text();
      if (upd && !text.trim()) return "Nothing new: every listing is already in your original.";
      try { await navigator.clipboard.writeText(text); }
      catch { throw new Error("couldn't copy here. Use Download instead."); }
      const n = text.split("\n").length - (upd ? 0 : 1);
      return `Copied ${n} row${n === 1 ? "" : "s"}${ex.length ? `, ${res.headers.get("X-Excluded") || 0} left out` : ""}. ${upd ? "Paste in the first empty row, column A." : "Paste into A1."}`;
    });
  };
  $("#av-copy", dlg).onclick = (e) => {
    const lines = avLines();
    if (!lines.some(Boolean)) { toast("Paste your listing links or names first."); return; }
    run(e.currentTarget, `Checking ${lines.filter(Boolean).length} listings… this can take a minute. You can keep editing.`, async () => {
      const res = await fetch("/api/export/availability", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lines }) });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "check failed");
      const { results, credits } = await res.json();
      try { await navigator.clipboard.writeText(results.join("\n")); }
      catch { throw new Error("couldn't copy here."); }
      const c = (w) => results.filter((x) => x === w).length;
      return `Copied ${results.length} answers: ${c("Available")} available, ${c("Unavailable")} unavailable, ${c("Failed to find")} not found. Used ${credits} credit${credits === 1 ? "" : "s"}. Paste into a new column.`;
    });
  };
  $("#ex-copy", dlg).onclick = copy;
  $("#up-copy", dlg).onclick = copy;
}

// ------------------------------------------------------------------ batch dashboard
async function openDashboard(cur) {
  if ($(".modal")) return;
  closeSheet();
  const listings = cur.listings;
  const likes = listings.filter((l) => l.verdict === "like").length;
  const hits = listings.filter((l) => ((l.predicted ?? 0.5) >= 0.5) === (l.verdict === "like")).length;
  const insights = await api("/insights").catch(() => ({ accuracy: [] }));
  const m = h(`<div class="modal dash">
    <div class="dash-head"><h1>Batch ${cur.number} recap</h1><button class="btn primary" id="done">Done</button></div>
    <div class="stats">
      <div class="stat"><b style="color:var(--like)">${likes}</b><span>liked</span></div>
      <div class="stat"><b style="color:var(--nope)">${listings.length - likes}</b><span>passed</span></div>
      <div class="stat"><b style="color:var(--gold)">${listings.length ? Math.round((hits / listings.length) * 100) : 0}%</b><span>called right</span></div>
    </div>
    <div class="panel"><div id="chart"></div>
      <div class="cap">Each dot is a listing, placed by how much Claude expected you to like it. Green you liked, red you passed. Good batches put green on the right.</div></div>
    <div class="tabs"><button class="on" data-t="grid">Grid</button><button data-t="web">Rank web</button></div>
    <div class="dash-body"><div class="scroll" id="tab-grid"><div class="grid" id="grid"></div>
      <p class="mode-note" style="margin-top:10px">Tap any tile to flip your call. Switch to Rank web to fine-tune: drag in or out, drop one onto another to group.</p></div>
      <div class="web-box" id="tab-web" hidden></div></div>
  </div>`);
  document.body.appendChild(m);
  drawCallChart($("#chart", m), listings, insights.accuracy || []);
  const grid = $("#grid", m);
  const paintGrid = async () => {
    const b = await api("/batches/" + cur.id);
    grid.innerHTML = "";
    b.listings.slice().sort((x, y) => (y.rank ?? 0) - (x.rank ?? 0)).forEach((l, i) => {
      const t = h(`<button class="tile ${l.verdict || ""}"><span class="badge">#${i + 1}</span><span class="tprice">${esc(money(l))}</span></button>`);
      if (l.photos?.[0]) t.style.backgroundImage = `url(${l.photos[0]})`;
      t.onclick = () => openListing(l.id, { onChange: paintGrid });
      grid.appendChild(t);
    });
  };
  paintGrid();
  let web = null;
  m.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    m.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    const isWeb = b.dataset.t === "web";
    $("#tab-grid", m).hidden = isWeb; $("#tab-web", m).hidden = !isWeb;
    if (isWeb) {
      if (!web) { web = mountWeb($("#tab-web", m), cur.id); S.web = web; }
      web.refresh();
    } else paintGrid();
  }));
  $("#done", m).onclick = async () => {
    closeSheet();
    try { await api(`/batches/${cur.id}/finish`, { body: {} }); } catch (e) { toast(e.message); }
    web?.destroy(); if (S.web === web) S.web = null;
    m.remove();
    await loadState();
    renderSwipe();
  };
}

function drawCallChart(el, listings, accuracy) {
  const w = el.clientWidth || 320, hgt = 92;
  const svg = d3.select(el).append("svg").attr("width", "100%").attr("viewBox", `0 0 ${w} ${hgt + (accuracy.length > 1 ? 70 : 0)}`);
  const x = d3.scaleLinear().domain([0, 1]).range([14, w - 14]);
  svg.append("line").attr("x1", x(0)).attr("x2", x(1)).attr("y1", 50).attr("y2", 50).attr("stroke", "#3a2f26");
  svg.append("line").attr("x1", x(0.5)).attr("x2", x(0.5)).attr("y1", 18).attr("y2", 82).attr("stroke", "#6a5444").attr("stroke-dasharray", "3 4");
  [["expected pass", 0, "start"], ["expected like", 1, "end"]].forEach(([t, v, a]) =>
    svg.append("text").attr("x", x(v)).attr("y", 14).attr("text-anchor", a).attr("fill", "#7d6d61").attr("font-size", 11).text(t));
  const sorted = listings.slice().sort((a, b) => (a.predicted ?? 0) - (b.predicted ?? 0));
  const lanes = [], placed = [];
  sorted.forEach((l) => {
    const px = x(l.predicted ?? 0.5);
    let lane = 0;
    while (lanes[lane] != null && px - lanes[lane] < 13) lane++;
    lanes[lane] = px;
    placed.push([l, px, lane]);
  });
  // squeeze the stacks so tall piles stay inside the panel
  const maxOff = Math.max(1, ...placed.map(([, , lane]) => Math.ceil(lane / 2)));
  const step = Math.min(12, 30 / maxOff);
  placed.forEach(([l, px, lane]) => {
    const y = 50 + (lane % 2 ? 1 : -1) * Math.ceil(lane / 2) * step;
    svg.append("circle").attr("cx", px).attr("cy", y).attr("r", Math.min(5.5, step / 2 + 1))
      .attr("fill", l.verdict === "like" ? "#4cc38a" : "#ff5a5f").attr("stroke", "#16110e").attr("stroke-width", 1.2);
  });
  if (accuracy.length > 1) {
    const top = hgt + 8, bottom = hgt + 60;
    const xs = d3.scaleLinear().domain([0, accuracy.length - 1]).range([30, w - 14]);
    const ys = d3.scaleLinear().domain([0, 1]).range([bottom, top]);
    svg.append("text").attr("x", 0).attr("y", top - 2).attr("fill", "#7d6d61").attr("font-size", 11).text("called right, by batch");
    svg.append("path").attr("d", d3.line().x((_, i) => xs(i)).y((d) => ys(d.accuracy))(accuracy))
      .attr("fill", "none").attr("stroke", "#ffd27a").attr("stroke-width", 2);
    accuracy.forEach((d, i) => svg.append("circle").attr("cx", xs(i)).attr("cy", ys(d.accuracy)).attr("r", 3).attr("fill", "#ffd27a"));
  }
}

// ------------------------------------------------------------------ likes web
function gemSvg(facets = 1, glow = false) {
  // a cut gem; each crystal adds a facet line
  const n = Math.max(1, Math.min(9, facets));
  const lines = [];
  for (let i = 1; i <= n; i++) {
    const x = 10 + (80 * i) / (n + 1);
    lines.push(`<path d="M${x.toFixed(1)} 30 L50 92" /><path d="M${x.toFixed(1)} 30 L${(x + (i % 2 ? -8 : 8)).toFixed(1)} 12" />`);
  }
  return `<svg viewBox="0 0 100 100" class="gem ${glow ? "glow" : ""}"><defs><linearGradient id="gemg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#bff3ff"/><stop offset=".5" stop-color="#8ec5ff"/><stop offset="1" stop-color="#d9a3ff"/></linearGradient></defs>
    <path d="M24 12h52l16 18-42 62L8 30z" fill="url(#gemg)" fill-opacity=".9" stroke="#e8fbff" stroke-width="2" stroke-linejoin="round"/>
    <path d="M8 30h84" stroke="#e8fbff" stroke-width="1.6" opacity=".9"/>
    <g stroke="#ffffff" stroke-width="1.1" opacity=".55" fill="none">${lines.join("")}</g></svg>`;
}

function renderLikes() {
  const st = S.state;
  const tab = sessionStorage.getItem("likesTab") || "web";
  const el = h(`<div class="screen">
    <div class="topbar"><button class="icon-btn" id="back">${I.back}</button><h1>Your likes</h1>
      <span class="pill ${st.web.locked ? "warn" : ""}">${st.web.count}/${st.web.limit}</span>
      <button class="icon-btn gem-side ${st.web.locked ? "hot" : ""}" id="crys-side" title="Crystallize" aria-label="Crystallize">${I.gem}</button></div>
    <div class="tabs" style="margin:10px 0 0"><button data-t="web" class="${tab === "web" ? "on" : ""}">Web</button>
      <button data-t="keepers" class="${tab === "keepers" ? "on" : ""}">Keepers${st.keepers ? " · " + st.keepers : ""}</button></div>
    <div class="web-box" id="webbox" style="margin-top:10px" ${tab === "web" ? "" : "hidden"}></div>
    <div class="scroll" id="keeperbox" style="margin-top:10px;flex:1" ${tab === "keepers" ? "" : "hidden"}></div>
  </div>`);
  app.replaceChildren(el);
  $("#back", el).onclick = () => go("home");
  $("#crys-side", el).onclick = () => openCrystallize();
  S.web = mountWeb($("#webbox", el));
  S.web.refresh().catch((e) => toast(e.message));
  if (st.web.locked) {
    const cta = h(`<button class="crys-cta">${gemSvg(st.crystals + 1)}<span><b>Crystallize</b><small>Your web is full. Lock in what it learned.</small></span></button>`);
    cta.onclick = () => openCrystallize();
    $("#webbox", el).appendChild(cta);
  }
  el.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
    sessionStorage.setItem("likesTab", b.dataset.t);
    el.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    $("#webbox", el).hidden = b.dataset.t !== "web";
    $("#keeperbox", el).hidden = b.dataset.t !== "keepers";
    if (b.dataset.t === "keepers") paintKeepers($("#keeperbox", el));
  }));
  if (tab === "keepers") paintKeepers($("#keeperbox", el));
}

async function paintKeepers(box) {
  const ks = await api("/keepers").catch(() => []);
  if (!ks.length) {
    box.innerHTML = `<div class="center-state" style="padding-top:40px"><div class="gem-big" style="opacity:.5">${gemSvg(1)}</div>
      <h2 style="font-size:22px">No keepers yet</h2><p>When you crystallize, you swipe right on anything you might still buy. They land here, safe from the reset.</p></div>`;
    return;
  }
  box.innerHTML = `<div class="keeper-head"><span>${ks.length} keeper${ks.length > 1 ? "s" : ""}</span>
    <span class="khbtns"><button class="btn" id="kcheck">Check availability</button>
    <button class="btn" id="kexport"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>Export</button></span></div>
    <div class="keeper-note" id="knote"></div>
    <div class="keeper-grid"></div>`;
  $("#kexport", box).onclick = () => exportDialog(null, true);
  $("#kcheck", box).onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Checking…";
    try {
      const r = await api("/keepers/check", { method: "POST", body: {} });
      await paintKeepers(box);
      const bits = [`${r.live} still available`, `${r.gone} gone`];
      if (r.unknown) bits.push(`${r.unknown} couldn't be checked`);
      if (r.changed) bits.push(`${r.changed} changed price`);
      $("#knote", box).textContent = bits.join(" · ") + (r.credits ? ` · ${r.credits} credit${r.credits > 1 ? "s" : ""}` : "");
    } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Check availability"; }
  };
  const grid = $(".keeper-grid", box);
  ks.forEach((k) => {
    const card = h(`<div class="keeper${k.avail === "gone" ? " gone" : ""}">
      <button class="kph"></button>
      <div class="kbody"><div class="kt">${esc(k.title)}</div>
        <div class="kp">${esc(money(k))}${k.price_prev != null ? ` <s class="kprev">${esc("$" + Number(k.price_prev).toLocaleString())}</s>` : ""} <span>${esc(k.location_text || "")}</span></div>
        ${k.avail ? `<div class="kavail ${k.avail}">${k.avail === "live" ? "Still available" : "No longer available"} <span>· ${esc(ago(k.avail_at))}</span></div>` : ""}
        <div class="krow"><a class="btn primary" href="${esc(k.url)}" target="_blank" rel="noopener">Open</a>
          <button class="btn ghost kx" aria-label="Remove keeper">✕</button></div></div></div>`);
    if (k.photos?.[0]) $(".kph", card).style.backgroundImage = `url(${k.photos[0]})`;
    $(".kph", card).onclick = () => openListing(k.id);
    $(".kx", card).onclick = async () => {
      if (!confirm(`Let "${k.title}" go? It won't come back.`)) return;
      await api("/keepers/" + k.id, { method: "DELETE" });
      card.remove();
      await loadState();
      const t = document.querySelector('.tabs button[data-t="keepers"]');
      if (t) t.textContent = "Keepers" + (S.state.keepers ? " · " + S.state.keepers : "");
      if (!grid.childElementCount) paintKeepers(box);
      else $(".keeper-head span", box).textContent = `${grid.childElementCount} keeper${grid.childElementCount > 1 ? "s" : ""}`;
    };
    grid.appendChild(card);
  });
}

// ------------------------------------------------------------------ crystallize
async function openCrystallize() {
  if ($(".modal.crys")) return;
  closeSheet();
  let pv;
  try { pv = await api("/crystallize/preview"); } catch (e) { return toast(e.message); }
  const landmarks = S.web?.getLandmarks?.() || [];
  const m = h(`<div class="modal crys"></div>`);
  document.body.appendChild(m);
  const close = () => m.remove();
  const nextNo = pv.crystals + 1;

  if (pv.blocking_batch) {
    m.innerHTML = `<div class="center-state"><div class="gem-big">${gemSvg(nextNo)}</div><h2>Finish batch ${pv.blocking_batch} first</h2>
      <p>Swipe through what's waiting, then come back and crystallize.</p>
      <button class="btn primary" id="cgo">Go swipe</button><button class="btn ghost" id="cx">Not now</button></div>`;
    $("#cgo", m).onclick = () => { close(); go("swipe"); };
    $("#cx", m).onclick = close;
    return;
  }
  if (!pv.web_count) {
    m.innerHTML = `<div class="center-state"><div class="gem-big" style="opacity:.5">${gemSvg(nextNo)}</div><h2>Nothing to crystallize yet</h2>
      <p>Swipe a batch or two first. The crystal is made from your web.</p><button class="btn" id="cx">Close</button></div>`;
    $("#cx", m).onclick = close;
    return;
  }

  const keepers = new Set(pv.listings.filter((l) => l.keeper).map((l) => l.id));
  const keepWeb = new Set();
  const deck = pv.listings.filter((l) => l.verdict === "like" && !l.keeper).sort((a, b) => b.rank - a.rank);

  // step 1: keeper deck
  const keeperStep = () => {
    if (!deck.length) return confirmStep();
    let i = 0;
    m.innerHTML = `<div class="crys-head"><button class="icon-btn" id="cx">${I.x}</button>
        <div><h1>Pick your keepers</h1><p>Swipe right on anything you might still buy. Everything else gets let go.</p></div></div>
      <div class="deck-wrap" id="kdeck"></div>
      <div class="crys-count" id="kcount"></div>
      <div class="actions"><button class="act nope" id="kno">${I.x}</button>
        <button class="act like gemact" id="kyes">${I.gem}</button></div>
      <button class="btn ghost" id="kskip" style="margin:10px auto 0;display:block">Skip to the summary</button>`;
    $("#cx", m).onclick = close;
    $("#kskip", m).onclick = confirmStep;
    const holder = $("#kdeck", m);
    let top = null;
    const mount = () => {
      holder.innerHTML = "";
      if (i >= deck.length) return confirmStep();
      $("#kcount", m).textContent = `${i + 1} of ${deck.length} liked · ${keepers.size} kept`;
      if (deck[i + 1]) { const nx = cardEl(deck[i + 1]); nx.classList.add("behind"); holder.appendChild(nx); }
      top = cardEl(deck[i]);
      holder.appendChild(top);
      fling(top, decide);
    };
    const decide = (keep) => {
      if (!top) return;
      if (keep) keepers.add(deck[i].id); else keepers.delete(deck[i].id);
      const dir = keep ? 1 : -1;
      top.style.transition = "transform .3s ease-in, opacity .3s";
      top.style.transform = `translate(${dir * innerWidth * 1.2}px,-30px) rotate(${dir * 22}deg)`;
      top.style.opacity = 0;
      top = null; i++;
      setTimeout(mount, 230);
    };
    $("#kno", m).onclick = () => decide(false);
    $("#kyes", m).onclick = () => decide(true);
    mount();
  };

  // step 2: what gets locked in, what's kept, what's forgotten
  const confirmStep = () => {
    const forgetCount = () => pv.listings.filter((l) => !keepers.has(l.id) && !keepWeb.has(l.id)).length;
    const chips = (xs, cls) => xs.map((x) => `<span class="chip ${cls}">${esc(x)}</span>`).join("") || '<span class="empty">nothing clear yet</span>';
    m.innerHTML = `<div class="crys-head"><button class="icon-btn" id="cback">${I.back}</button>
        <div><h1>Crystal #${nextNo}</h1><p>Read this over. There's no undo.</p></div></div>
      <div class="crys-body">
        <div class="gem-big">${gemSvg(nextNo, true)}</div>

        <div class="crys-sec lock"><h4>◆ Locked into the crystal</h4>
          <ul>
            <li><b>Your taste from ${pv.new_evidence} listing${pv.new_evidence === 1 ? "" : "s"}</b>: ${pv.traits} traits, each with how many listings back it up.</li>
            <li>Pulls you in: <div class="chips left">${chips(pv.pulls, "good")}</div></li>
            <li>Pushes you away: <div class="chips left">${chips(pv.pushes, "bad")}</div></li>
            ${pv.concepts.length ? `<li><b>Your categories</b> become lasting concepts, even after their listings go:
              <div class="chips left">${pv.concepts.map((k) => `<span class="chip">${esc(k.label)}${k.traits.length ? " · " + esc(k.traits.slice(0, 3).join(", ")) : ""}</span>`).join("")}</div></li>` : ""}
            <li><b>${pv.searches} search term${pv.searches === 1 ? "" : "s"}</b> and how each one did.</li>
            ${pv.taste_summary ? `<li><b>Your taste summary</b> as it stands: <div class="take" style="margin-top:6px;font-size:14px">${esc(pv.taste_summary)}</div></li>` : ""}
            <li>Every listing you've seen stays marked as seen, so none of them come back.</li>
            ${pv.crystals ? `<li>Your ${pv.crystals === 1 ? "earlier crystal" : pv.crystals + " earlier crystals"} start counting half as much, so your taste can keep moving.</li>` : ""}
          </ul></div>

        <div class="crys-sec"><h4>Keepers · ${keepers.size}</h4>
          ${keepers.size ? `<div class="kstrip">${pv.listings.filter((l) => keepers.has(l.id)).map((l) =>
            `<div class="kthumb" style="background-image:url(${l.photos?.[0] || ""})"></div>`).join("")}</div>
            <p class="mode-note">They move to the Keepers tab in Your likes, with photos and links.</p>`
            : `<p class="mode-note">None. ${deck.length ? '<button class="linkish" id="redo">Go back and pick some</button>' : ""}</p>`}</div>

        <div class="crys-sec"><h4>Keep in web</h4>
          <p class="mode-note">Tap any listing to keep it as a node in the new web. These count toward your next ${pv.limit}.</p>
          <div class="grid kw" id="kwgrid"></div></div>

        <div class="crys-sec forget"><h4>Forgotten</h4>
          <p><b id="fcount">${forgetCount()}</b> listings, their photos, and the links between them.</p></div>
      </div>
      <div class="crys-foot"><button class="big-btn gemgo" id="cgo">◆ Crystallize<small id="cgosub"></small></button></div>`;
    const sub = () => {
      $("#fcount", m).textContent = forgetCount();
      $("#cgosub", m).textContent = `${pv.new_evidence} listings of taste locked in · ${keepWeb.size} stay in web`;
    };
    sub();
    $("#cback", m).onclick = () => (deck.length ? keeperStep() : close());
    $("#redo", m) && ($("#redo", m).onclick = keeperStep);
    const grid = $("#kwgrid", m);
    pv.listings.slice().sort((a, b) => b.rank - a.rank).forEach((l) => {
      const t = h(`<button class="tile ${l.verdict}">${keepers.has(l.id) ? '<span class="badge gemb">◆</span>' : ""}<span class="stay">stays</span></button>`);
      if (l.photos?.[0]) t.style.backgroundImage = `url(${l.photos[0]})`;
      t.onclick = () => {
        if (keepWeb.has(l.id)) keepWeb.delete(l.id); else keepWeb.add(l.id);
        t.classList.toggle("kept", keepWeb.has(l.id));
        sub();
      };
      grid.appendChild(t);
    });
    $("#cgo", m).onclick = async () => {
      const btn = $("#cgo", m);
      btn.disabled = true; btn.style.opacity = 0.6;
      try {
        const r = await api("/crystallize", { body: { keepers: [...keepers], keep_in_web: [...keepWeb], landmarks } });
        doneStep(r);
      } catch (e) { toast(e.message); btn.disabled = false; btn.style.opacity = ""; }
    };
  };

  // step 3: the crystal forms
  const doneStep = (r) => {
    m.innerHTML = `<div class="center-state crys-done">
      <div class="gem-big forming">${gemSvg(r.number, true)}</div>
      <h2>Crystal #${r.number} formed</h2>
      <p>${r.absorbed} listings of taste locked in. ${r.kept} keeper${r.kept === 1 ? "" : "s"} saved, ${r.kept_in_web} kept in the web, ${r.forgotten} let go.</p>
      <button class="big-btn" id="cdone">Start a fresh web<small>New batches are open again</small></button></div>`;
    $("#cdone", m).onclick = async () => {
      close();
      store.set("flown", []);
      await loadState();
      route();
    };
  };

  keeperStep();
}

// shared fling gesture for decks outside the main swipe screen
function fling(card, decide) {
  let sx = 0, sy = 0, dx = 0, dragging = false;
  const like = $(".stamp.like", card), nope = $(".stamp.nope", card);
  if (like) like.textContent = "KEEP";
  if (nope) nope.textContent = "LET GO";
  card.addEventListener("pointerdown", (e) => { dragging = true; sx = e.clientX; sy = e.clientY; dx = 0; card.setPointerCapture(e.pointerId); card.style.transition = "none"; });
  card.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    dx = e.clientX - sx;
    card.style.transform = `translate(${dx}px, ${(e.clientY - sy) * 0.3}px) rotate(${dx / 18}deg)`;
    if (like) like.style.opacity = Math.max(0, Math.min(1, dx / 110));
    if (nope) nope.style.opacity = Math.max(0, Math.min(1, -dx / 110));
  });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    if (dx > 110) return decide(true);
    if (dx < -110) return decide(false);
    card.style.transition = "transform .3s cubic-bezier(.2,.9,.3,1.2)";
    card.style.transform = "";
    if (like) like.style.opacity = 0;
    if (nope) nope.style.opacity = 0;
    if (Math.abs(dx) < 6 && e.type === "pointerup") {
      const r = card.getBoundingClientRect();
      if ((e.clientY - r.top) / r.height < 0.6) card._tapPhoto((e.clientX - r.left) / r.width);
    }
  };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
}

// ------------------------------------------------------------------ profile
// ------------------------------------------------------------------ collapsible cards
// Tap a card's title to fold it. Which ones are folded is remembered on this device.
function collapsible(root, page) {
  const key = "kindling.folded." + page;
  let folded = [];
  try { folded = JSON.parse(localStorage.getItem(key) || "[]"); } catch {}
  root.querySelectorAll(".card-block[data-sec]").forEach((card) => {
    const head = card.querySelector(":scope > h3");
    if (!head) return;
    const sec = card.dataset.sec;
    head.classList.add("fold-head");
    head.setAttribute("role", "button");
    head.tabIndex = 0;
    const set = (closed) => {
      card.classList.toggle("folded", closed);
      head.setAttribute("aria-expanded", String(!closed));
    };
    set(folded.includes(sec));
    const toggle = () => {
      const closed = !card.classList.contains("folded");
      set(closed);
      folded = folded.filter((x) => x !== sec);
      if (closed) folded.push(sec);
      try { localStorage.setItem(key, JSON.stringify(folded)); } catch {}
    };
    head.onclick = toggle;
    head.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
  });
}

// ------------------------------------------------------------------ spending
const usd = (v) => (v == null ? "–" : v > 0 && v < 0.01 ? "<$0.01" : "$" + v.toFixed(2));
const MODEL_NAMES = { "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5" };
const bigNum = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e4 ? Math.round(n / 1e3) + "k" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n));

function paintSpending(box, sp) {
  if (!sp) { box.innerHTML = '<p class="empty">Couldn\'t load spending right now.</p>'; return; }
  const day = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const tile = (label, w) => `<div class="spend-tile"><span class="lab">${label}</span>
    <b>${usd(w.claude)}</b><span class="sub">Claude</span>
    <b class="cr">${w.credits.toLocaleString()}</b><span class="sub">scrape credits</span></div>`;
  box.innerHTML = `
    ${sp.budget.cap != null && S.state.mode.brain === "claude" ? budgetMeter(sp.budget) : ""}
    <div class="spend-tiles">${tile("This week", sp.week)}${tile("Last 30 days", sp.month)}${tile("All time", sp.all)}</div>
    <div class="spend-chart" id="ch-claude"></div>
    <div class="spend-chart" id="ch-credits"></div>
    ${sp.per_batch_claude != null ? `<p class="mode-note">A batch has been running about <b>${usd(sp.per_batch_claude)}</b> of Claude.</p>` : ""}
    ${sp.by_hunt.length ? `<div class="section"><h4>By hunt</h4>${sp.by_hunt.map((x) => `<div class="spend-row">
      <span>${esc(x.name)} <span class="mode-note">· ${x.batches} batch${x.batches === 1 ? "" : "es"}</span></span>
      <span class="n">${usd(x.claude)} · ${x.credits.toLocaleString()} cr</span></div>`).join("")}</div>` : ""}
    ${sp.by_model.length ? `<div class="section"><h4>Claude by model</h4>${sp.by_model.map((m) => `<div class="spend-row">
      <span>${esc(MODEL_NAMES[m.model] || m.model)} <span class="mode-note">· ${m.calls} call${m.calls === 1 ? "" : "s"} · ${bigNum(m.input_tokens)} in / ${bigNum(m.output_tokens)} out</span></span>
      <span class="n">${usd(m.cost)}</span></div>`).join("")}</div>` : ""}
    ${sp.everyone ? `<div class="section"><h4>Everyone (${sp.everyone.people} ${sp.everyone.people === 1 ? "person" : "people"})</h4>
      <div class="spend-row"><span>This week</span><span class="n">${usd(sp.everyone.week_claude)} · ${sp.everyone.week_credits.toLocaleString()} cr</span></div>
      <div class="spend-row"><span>All time</span><span class="n">${usd(sp.everyone.all_claude)} · ${sp.everyone.all_credits.toLocaleString()} cr</span></div>
      ${sp.scrape_balance != null ? `<div class="spend-row"><span>Left on the ScrapeCreators key</span><span class="n">${Number(sp.scrape_balance).toLocaleString()} cr</span></div>` : ""}</div>` : ""}
    <p class="mode-note" style="margin-top:10px">${sp.tracking_since ? `Claude spend is tracked from ${day(sp.tracking_since)} on, priced from the tokens each call used.` : "No Claude spend recorded yet. It's priced from the tokens each call uses."} Weeks start Monday.</p>`;
  weekBars($("#ch-claude", box), "Claude per week", sp.series, "claude", "#c08020", usd);
  weekBars($("#ch-credits", box), "Scrape credits per week", sp.series, "credits", "#3f86d4", (v) => v.toLocaleString() + " cr");
}

// One measure per chart (no dual axes). Tap or hover a bar to read it; the current week shows by default.
function weekBars(box, title, series, key, color, fmt) {
  const wd = 320, ht = 112, padX = 4, top = 8, bottom = 18;
  const max = Math.max(...series.map((d) => d[key]), 0);
  const last = series.length - 1;
  box.innerHTML = `<div class="spend-chart-head"><h4>${esc(title)}</h4><span class="readout"></span></div>`;
  const readout = $(".readout", box);
  const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${wd} ${ht}`).attr("width", "100%")
    .attr("role", "img").attr("aria-label", `${title}: ` + series.map((d) => `${d.label} ${fmt(d[key])}`).join(", "));
  const x = d3.scaleBand().domain(series.map((_, i) => i)).range([padX, wd - padX]).paddingInner(0.28).paddingOuter(0.1);
  const y = d3.scaleLinear().domain([0, max || 1]).range([ht - bottom, top]);
  const base = ht - bottom;
  svg.append("line").attr("x1", padX).attr("x2", wd - padX).attr("y1", base + 0.5).attr("y2", base + 0.5).attr("stroke", "#3a2f26");
  const bw = Math.min(x.bandwidth(), 26);
  series.forEach((d, i) => {
    const bx = x(i) + (x.bandwidth() - bw) / 2;
    const hgt = d[key] > 0 ? Math.max(2, base - y(d[key])) : 0;
    if (hgt > 0) {
      const r = Math.min(4, bw / 2, hgt), by = base - hgt;
      // rounded top, square base on the axis
      svg.append("path").attr("class", "bar").attr("data-i", i).attr("fill", color)
        .attr("d", `M${bx},${base} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + bw - r} Q${bx + bw},${by} ${bx + bw},${by + r} V${base} Z`);
    } else {
      svg.append("rect").attr("class", "bar").attr("data-i", i).attr("x", bx).attr("y", base - 1)
        .attr("width", bw).attr("height", 1).attr("fill", "#4a3d32");
    }
    if (i === 0 || i === last || i === Math.floor(last / 2))
      svg.append("text").attr("x", x(i) + x.bandwidth() / 2).attr("y", ht - 4).attr("text-anchor", "middle")
        .attr("fill", "#7d6d61").attr("font-size", 10).text(i === last ? "This wk" : d.label);
  });
  const show = (i) => {
    readout.innerHTML = `<span class="mode-note">${i === last ? "This week" : "Week of " + esc(series[i].label)}</span> <b>${fmt(series[i][key])}</b>`;
    svg.selectAll(".bar").attr("opacity", function () { return +this.dataset.i === i ? 1 : 0.5; });
  };
  // hit targets: the whole column, wider than the bar
  series.forEach((_, i) => svg.append("rect").attr("x", x(i) - 3).attr("y", 0).attr("width", x.bandwidth() + 6).attr("height", ht)
    .attr("fill", "transparent").style("cursor", "pointer").on("pointerenter", () => show(i)).on("click", () => show(i)));
  svg.on("pointerleave", (e) => { if (e.pointerType === "mouse") show(last); });
  show(last);
}

async function renderProfile() {
  const p = S.state.profile;
  const me = S.state.me, isAdmin = me.role === "admin";
  const [profiles, ins, batches, logs, people, spend, vibe] = await Promise.all([api("/profiles"), api("/insights"), api("/batches"),
    isAdmin ? api("/logs?n=20").catch(() => ({ entries: [] })) : null,
    isAdmin ? api("/admin/users").catch(() => []) : null, api("/spending").catch(() => null),
    api("/vibe/" + p.id).catch(() => ({ status: "none" }))]);
  const kmToMi = (k) => Math.round(k * 0.621371);
  const el = h(`<div class="screen scroll">
    <div class="topbar"><button class="icon-btn" id="back">${I.back}</button><h1>Your profile</h1>${modeBadge()}</div>
    <div class="profiles-row" style="margin-top:10px">
      ${profiles.map((x) => `<button data-p="${x.id}" class="${x.active ? "on" : ""}">${esc(x.name)}</button>`).join("")}
      <button id="newp">+ New hunt</button></div>
    ${!["none", "applied"].includes(vibe.status) ? `<button class="card-block vibe-banner" id="go-vibe"><b>Finish setting up this vibe hunt</b>
      <span class="mode-note">${vibe.status === "refined" ? "Your sharpened hunt is waiting" : vibe.status === "hone" ? "Your hone grid is waiting" : vibe.status === "drafted" ? "Your hunt is drafted" : "Pick up where you left off"}</span></button>` : ""}

    <div class="card-block" data-sec="hunt"><h3>What you're hunting for</h3>
      <div class="field"><label>Name</label><input id="f-name" value="${esc(p.name)}" maxlength="40"></div>
      <div class="field"><label>Describe it like you'd tell a friend</label>
        <textarea id="f-hunt" placeholder="A green or sage couch for a small Philly apartment, mid-century vibe, under 84 inches">${esc(p.hunt)}</textarea></div>
      <div class="field"><label>Checklist (shows up on every card)</label>
        <div class="chips" id="crit" style="justify-content:flex-start"></div>
        <div class="inline"><input id="f-crit" placeholder="e.g. 72 to 84 inches wide"><button class="btn" id="add-crit">Add</button></div></div>
      <div class="two">
        <div class="field"><label>Min price</label><input id="f-min" inputmode="numeric" value="${p.min_price ?? ""}" placeholder="$"></div>
        <div class="field"><label>Max price</label><input id="f-max" inputmode="numeric" value="${p.max_price ?? ""}" placeholder="$"></div>
      </div>
      <div class="field"><label>Search around</label>
        <div class="inline"><input id="f-loc" value="${esc(p.location_name)}"><button class="btn" id="find">Find</button></div>
        <div class="chips" id="locs" style="justify-content:flex-start;margin-top:6px"></div>
        <span class="mode-note" id="coords">${p.lat.toFixed(3)}, ${p.lng.toFixed(3)}</span></div>
      <div class="field"><label>Radius: <span id="radv">${kmToMi(p.radius_km)} mi</span></label>
        <input type="range" id="f-rad" min="2" max="160" value="${Math.round(p.radius_km)}"></div>
      <button class="btn primary" id="save" style="width:100%">Save</button>
    </div>

    <div class="card-block" data-sec="taste"><h3>Your taste, so far</h3>
      ${ins.taste_summary ? `<div class="take">${esc(ins.taste_summary)}</div>` : '<p class="empty">Finish a batch and this fills in.</p>'}
      <div class="section"><h4>What drives your swipes</h4><div class="bars" id="bars"></div></div>
      ${ins.groups.length ? `<div class="section"><h4>Your categories</h4><div class="chips" style="justify-content:flex-start">
        ${ins.groups.map((g) => `<span class="chip">${esc(g.label)} · ${g.members.length}</span>`).join("")}</div></div>` : ""}
    </div>

    <div class="card-block" data-sec="crystals"><h3>Crystals</h3>
      ${ins.crystals.length ? `<div class="crys-row"><div class="gem-mid">${gemSvg(ins.crystals.length, true)}</div>
        <div><b>${ins.crystals.length} crystal${ins.crystals.length === 1 ? "" : "s"}</b><p class="mode-note">Each one is a web's worth of taste, locked in. Older ones count less so your taste can drift.</p></div></div>
        ${ins.crystals.map((c) => `<div class="crys-item"><span class="bn">◆${c.number}</span>
          <div><div>${new Date(c.created_at * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${c.n_listings} listings · counts ${Math.round(c.factor * 100)}%</div>
          <div class="chips left">${c.pulls.map((t) => `<span class="chip good">${esc(t)}</span>`).join("")}</div></div></div>`).join("")}
        ${ins.concepts.length ? `<div class="section"><h4>Concepts carried forward</h4><div class="chips left">${ins.concepts.map((k) =>
          `<span class="chip">${esc(k.label)}${k.traits.length ? " · " + esc(k.traits.slice(0, 3).join(", ")) : ""}</span>`).join("")}</div></div>` : ""}`
      : `<p class="empty">None yet. Crystallize from Your likes any time; it's required once the web hits ${S.state.web.limit}.</p>`}
    </div>

    <div class="card-block" data-sec="learning"><h3>Is it learning?</h3><div id="learn"></div></div>

    <div class="card-block" data-sec="spending"><h3>Spending</h3><div id="spend"></div></div>

    <div class="card-block" data-sec="batches"><h3>Every batch's searches</h3><div id="qs"></div>
      <p class="mode-note" style="margin-top:10px">Source: ${esc(S.state.mode.source)} · Brain: ${S.state.mode.brain === "claude" ? "Claude" : "keyword fallback"} · ${ins.credits_used} credits used on this hunt</p></div>

    <div class="card-block" data-sec="you"><h3>${esc(me.name)}</h3>
      <p class="mode-note" style="margin:-4px 0 8px">${isAdmin ? "Admin" : "Standard account"} · signed in on this device</p>
      <button class="btn ghost" id="signout" style="margin-top:4px">Sign out of this device</button>
    </div>

    ${isAdmin ? `<div class="card-block" data-sec="people"><h3>People</h3>
      <div id="people">${people.map((u) => `<div class="person ${u.disabled ? "off" : ""}">
        <div class="pmain"><b>${esc(u.name)}</b> <span class="pill">${u.role}</span>${u.disabled ? ' <span class="pill warn">off</span>' : ""}
          <div class="mode-note">Claude this week $${u.budget.spent.toFixed(2)}${u.budget.cap != null ? " of $" + u.budget.cap.toFixed(2) : ""} · all time $${u.claude_total.toFixed(2)}
            · ${u.scrape_credits_week} scrape credits this week · ${u.devices} device${u.devices === 1 ? "" : "s"}
            ${u.last_seen ? "· seen " + new Date(u.last_seen * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}</div></div>
        ${u.role !== "admin" ? `<div class="pact"><button class="btn" data-cap="${u.id}">Cap</button>
          <button class="btn ghost" data-off="${u.id}" data-state="${u.disabled ? 1 : 0}">${u.disabled ? "Turn on" : "Turn off"}</button></div>` : ""}
      </div>`).join("")}</div>
      <div style="display:grid;gap:8px;margin-top:12px">
        <button class="btn primary" id="inv-friend">Invite someone ($3/week of Claude)</button>
        <button class="btn" id="inv-me">Sign in another of my devices</button>
      </div>
      <div id="invout"></div>
    </div>` : ""}

    ${isAdmin ? `<div class="card-block" data-sec="problems"><h3>Recent problems</h3>
      ${logs.entries.length ? logs.entries.map((e) => {
        const [first, ...rest] = e.split("\n");
        const m = /^(\S+ \S+) (\w+) (.*)$/.exec(first) || [];
        return `<details class="logline"><summary><span class="lvl ${esc((m[2] || "").toLowerCase())}">${esc(m[2] || "")}</span>
          <span class="when">${esc((m[1] || "").slice(5, 16))}</span> ${esc(m[3] || first)}</summary>
          ${rest.length ? `<pre>${esc(rest.join("\n"))}</pre>` : ""}</details>`;
      }).join("") : '<p class="empty">Nothing has gone wrong lately.</p>'}
      <p class="mode-note" style="margin-top:8px">Full log on the server: ${esc(logs.path || "data/kindling.log")}</p></div>` : ""}
    <div style="height:30px"></div>
  </div>`);
  app.replaceChildren(el);
  $("#back", el).onclick = () => go("home");
  collapsible(el, "profile");
  paintSpending($("#spend", el), spend);

  $("#signout", el).onclick = async () => {
    if (!confirm("Sign this device out? You'll need a new code to get back in.")) return;
    await api("/auth/logout", { body: {} }).catch(() => {});
    renderJoin();
  };
  if (isAdmin) {
    const showCode = (code, who) => {
      const link = `${location.origin}/#join/${code}`;
      $("#invout", el).innerHTML = `<div class="invite-box"><div class="mode-note">${esc(who)} · works once · expires in 7 days</div>
        <div class="code">${esc(code)}</div><div class="mode-note" style="word-break:break-all">${esc(link)}</div>
        <div style="display:flex;gap:8px;margin-top:8px"><button class="btn primary" id="share">Share</button><button class="btn" id="copy">Copy link</button></div></div>`;
      $("#copy", el).onclick = async () => { try { await navigator.clipboard.writeText(link); toast("Copied"); } catch { toast(link); } };
      $("#share", el).onclick = async () => {
        if (navigator.share) { try { await navigator.share({ title: "Kindling invite", text: `Join me on Kindling. Code: ${code}`, url: link }); } catch {} }
        else { try { await navigator.clipboard.writeText(link); toast("Copied"); } catch { toast(link); } }
      };
    };
    $("#inv-friend", el).onclick = async () => {
      const r = await api("/admin/invites", { body: { claude_cap: 3 } }).catch((e) => toast(e.message));
      if (r) showCode(r.code, "New standard account, $3/week of Claude");
    };
    $("#inv-me", el).onclick = async () => {
      const r = await api("/admin/invites", { body: { for_me: true } }).catch((e) => toast(e.message));
      if (r) showCode(r.code, `Signs a device in as ${me.name}`);
    };
    el.querySelectorAll("[data-cap]").forEach((b) => (b.onclick = async () => {
      const v = prompt("Weekly Claude budget in dollars (blank for no cap):", "3");
      if (v === null) return;
      const body = v.trim() === "" ? { no_cap: true } : { claude_cap: parseFloat(v) };
      if (body.claude_cap != null && !(body.claude_cap >= 0)) return toast("That's not a number");
      await api("/admin/users/" + b.dataset.cap, { method: "PUT", body });
      renderProfile();
    }));
    el.querySelectorAll("[data-off]").forEach((b) => (b.onclick = async () => {
      const off = b.dataset.state !== "1";
      if (off && !confirm("Turn this account off? They'll be signed out everywhere until you turn it back on.")) return;
      await api("/admin/users/" + b.dataset.off, { method: "PUT", body: { disabled: off } });
      renderProfile();
    }));
  }

  let criteria = [...(p.criteria || [])];
  let must = new Set((p.must_have || []).map((m) => m.toLowerCase()));
  let loc = { location_name: p.location_name, lat: p.lat, lng: p.lng, location_slug: p.location_slug };
  const paintCrit = () => {
    $("#crit", el).innerHTML = criteria.map((c, i) => `<span class="chip${must.has(c.toLowerCase()) ? " must" : ""}">${esc(c)}<button class="must-btn" data-m="${i}" aria-pressed="${must.has(c.toLowerCase())}" title="A no on a must have removes the listing">${must.has(c.toLowerCase()) ? "Must have" : "Nice to have"}</button><button data-i="${i}" aria-label="Remove ${esc(c)}">✕</button></span>`).join("")
      || '<span class="empty">Nothing yet. Add what you want checked, then mark the ones a listing must have.</span>';
    $("#crit", el).querySelectorAll("button[data-i]").forEach((b) => (b.onclick = () => { must.delete(criteria[+b.dataset.i].toLowerCase()); criteria.splice(+b.dataset.i, 1); paintCrit(); }));
    $("#crit", el).querySelectorAll("button[data-m]").forEach((b) => (b.onclick = () => { const k = criteria[+b.dataset.m].toLowerCase(); must.has(k) ? must.delete(k) : must.add(k); paintCrit(); }));
  };
  paintCrit();
  const addCrit = () => { const v = $("#f-crit", el).value.trim(); if (v) { criteria.push(v); $("#f-crit", el).value = ""; paintCrit(); } };
  $("#add-crit", el).onclick = addCrit;
  $("#f-crit", el).onkeydown = (e) => { if (e.key === "Enter") addCrit(); };
  $("#f-rad", el).oninput = (e) => ($("#radv", el).textContent = kmToMi(+e.target.value) + " mi");
  $("#find", el).onclick = async () => {
    try {
      const locs = await api("/locate", { body: { text: $("#f-loc", el).value } });
      $("#locs", el).innerHTML = locs.map((l, i) => `<button class="chip" data-i="${i}">${esc(l.name)}<br><small style="color:var(--muted)">${esc(l.subtitle || "")}</small></button>`).join("") || '<span class="empty">No match</span>';
      $("#locs", el).querySelectorAll("button").forEach((b) => (b.onclick = () => {
        const l = locs[+b.dataset.i];
        loc = { location_name: l.name, lat: l.lat ?? loc.lat, lng: l.lng ?? loc.lng, location_slug: l.slug || loc.location_slug };
        $("#f-loc", el).value = l.name;
        $("#coords", el).textContent = `${(+loc.lat).toFixed(3)}, ${(+loc.lng).toFixed(3)}`;
        $("#locs", el).innerHTML = "";
      }));
    } catch (e) { toast(e.message); }
  };
  $("#f-loc", el).onkeydown = (e) => { if (e.key === "Enter") $("#find", el).click(); };
  $("#save", el).onclick = async () => {
    const num = (v) => (v.trim() === "" ? null : Number(v.replace(/[^0-9.]/g, "")));
    try {
      // typed a place but never picked a Find result: look it up now so the edit actually sticks
      const typed = $("#f-loc", el).value.trim();
      if (typed && typed !== loc.location_name) {
        const [l] = await api("/locate", { body: { text: typed } });
        if (!l) { toast(`Couldn't find "${typed}". Try a city or ZIP`); return; }
        loc = { location_name: l.name, lat: l.lat ?? loc.lat, lng: l.lng ?? loc.lng, location_slug: l.slug || loc.location_slug };
        $("#f-loc", el).value = l.name;
        $("#coords", el).textContent = `${(+loc.lat).toFixed(3)}, ${(+loc.lng).toFixed(3)}`;
      }
      await api("/profiles/" + p.id, { method: "PUT", body: {
        name: $("#f-name", el).value.trim() || p.name, hunt: $("#f-hunt", el).value.trim(), criteria, must_have: criteria.filter((c) => must.has(c.toLowerCase())),
        min_price: num($("#f-min", el).value), max_price: num($("#f-max", el).value),
        radius_km: +$("#f-rad", el).value, ...loc } });
      toast("Saved. Next batch uses this.");
    } catch (e) { toast(e.message); }
  };
  el.querySelectorAll("[data-p]").forEach((b) => (b.onclick = async () => { await api(`/profiles/${b.dataset.p}/activate`, { body: {} }); route(); }));
  $("#go-vibe", el)?.addEventListener("click", () => go("vibe"));
  $("#newp", el).onclick = () => {
    const c = h(`<div><h2>New hunt</h2>
      <div class="field"><label>What should we call it?</label><input id="nh-name" maxlength="40" placeholder="Coffee table, or Cozy reading nook"></div>
      <div style="display:grid;gap:8px;margin-top:6px">
        <button class="big-btn" id="nh-item" style="flex:none">A specific item<small>You know what you're after</small></button>
        <button class="big-btn" id="nh-vibe" style="flex:none">A vibe<small>A feeling, not an object. Add photos, links or a description and Claude helps write the hunt</small></button>
      </div></div>`);
    openSheet(c);
    const create = async (hunt) => {
      const name = $("#nh-name", c).value.trim();
      if (!name) { toast("Give it a name first"); $("#nh-name", c).focus(); return null; }
      return api("/profiles", { body: { name, hunt: hunt ? name : "" } });
    };
    $("#nh-item", c).onclick = async () => { if (await create(true)) { closeSheet(); route(); } };
    $("#nh-vibe", c).onclick = async () => { if (await create(false)) { closeSheet(); go("vibe"); } };
  };

  // trait bars
  const w = ins.weights.filter((x) => x.n >= 2 && !/^shape:|^condition:/.test(x.tag));
  const pos = w.filter((x) => x.weight > 0.02).slice(0, 6);
  const neg = w.filter((x) => x.weight < -0.02).slice(-6).reverse();
  const maxW = Math.max(0.05, ...w.map((x) => Math.abs(x.weight)));
  const bars = $("#bars", el);
  if (!pos.length && !neg.length) bars.innerHTML = '<p class="empty">Needs a few more swipes to spot patterns.</p>';
  else {
    const rows = Math.max(pos.length, neg.length);
    for (let i = 0; i < rows; i++) {
      const n = neg[i], q = pos[i];
      bars.appendChild(h(`<div class="bar">
        <div class="l">${n ? `<i style="width:${(Math.abs(n.weight) / maxW) * 100}%"></i><span>${esc(n.tag.split(":")[1])}</span>` : ""}</div>
        <div class="r axis">${q ? `<i style="width:${(q.weight / maxW) * 100}%"></i><span>${esc(q.tag.split(":")[1])}</span>` : ""}</div></div>`));
    }
    bars.appendChild(h(`<div class="bar" style="color:var(--faint);font-size:11px"><div style="text-align:right;padding-right:6px">pushes you away</div><div style="padding-left:6px">pulls you in</div></div>`));
  }

  // learning chart
  const learn = $("#learn", el);
  const acc = ins.accuracy;
  if (acc.length < 2) learn.innerHTML = `<p class="empty">${acc.length ? "One batch in. The trend line shows up after the second." : "No finished batches yet."}</p>`;
  else {
    const wd = learn.clientWidth || 320, ht = 140;
    const svg = d3.select(learn).append("svg").attr("width", "100%").attr("viewBox", `0 0 ${wd} ${ht}`);
    const xs = d3.scaleLinear().domain([0, acc.length - 1]).range([28, wd - 10]);
    const ys = d3.scaleLinear().domain([0, 1]).range([ht - 22, 10]);
    [0, 0.5, 1].forEach((v) => {
      svg.append("line").attr("x1", 28).attr("x2", wd - 10).attr("y1", ys(v)).attr("y2", ys(v)).attr("stroke", "#3a2f26");
      svg.append("text").attr("x", 0).attr("y", ys(v) + 4).attr("fill", "#7d6d61").attr("font-size", 10).text(pct(v));
    });
    const line = (key, color) => {
      svg.append("path").attr("d", d3.line().x((_, i) => xs(i)).y((d) => ys(d[key])).curve(d3.curveMonotoneX)(acc))
        .attr("fill", "none").attr("stroke", color).attr("stroke-width", 2.2);
      acc.forEach((d, i) => svg.append("circle").attr("cx", xs(i)).attr("cy", ys(d[key])).attr("r", 3).attr("fill", color));
    };
    line("accuracy", "#ffd27a"); line("like_rate", "#4cc38a");
    acc.forEach((d, i) => svg.append("text").attr("x", xs(i)).attr("y", ht - 4).attr("text-anchor", "middle").attr("fill", "#7d6d61").attr("font-size", 10).text("#" + d.batch));
    learn.appendChild(h(`<p class="mode-note"><span style="color:var(--gold)">●</span> called your swipe right &nbsp; <span style="color:var(--like)">●</span> share you liked. Both climbing means each batch is better than the last.</p>`));
  }

  // per-batch queries
  const qs = $("#qs", el);
  if (!batches.length) qs.innerHTML = '<p class="empty">No batches yet.</p>';
  else {
    const t = h(`<table class="qtable"></table>`);
    batches.forEach((b) => {
      const date = new Date(b.created_at * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      const per = Object.fromEntries((b.per_query || []).map((q) => [q.query, q]));
      const chips = (b.queries || []).map((q) => {
        const s = per[q];
        const cls = s && s.n ? (s.likes / s.n >= 0.5 ? "good" : s.likes === 0 ? "bad" : "") : "";
        return `<span class="chip ${cls}">${esc(q)}${s ? ` · ${s.likes || 0}/${s.n}` : ""}</span>`;
      }).join(" ");
      t.appendChild(h(`<tr><td><span class="bn">#${b.number}</span><br><span class="mode-note">${date}${b.weirdness != null ? "<br>weird " + b.weirdness : ""}</span></td>
        <td><div class="chips" style="justify-content:flex-start">${(b.modifiers || []).map((m) => modChip(m)).join("")}${chips || '<span class="empty">' + esc(b.status) + "</span>"}</div></td>
        <td class="n">${b.likes}/${b.shown}<br>${b.credits_used} cr${b.claude_cost ? `<br>${usd(b.claude_cost)}` : ""}</td></tr>`));
    });
    qs.appendChild(t);
  }
}

route();

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// ------------------------------------------------------------------ vibe hunts
// Start a hunt from a feeling: references in, a drafted hunt out, then an optional one-time "hone" where
// real listings (one per way the vibe could be read) get a like, love or hate and a reason.
function vibeIcons() {
  return {
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M7 11v9H4v-9h3zM7 11l4-8c1.7 0 2.7 1.3 2.4 3L13 9h5.3a2 2 0 011.97 2.35l-1.1 6.5A2.5 2.5 0 0116.7 20H7"/></svg>',
    heart: I.heart,
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  };
}

async function fileToJpeg(file, max = 1024) {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

async function renderVibe() {
  const pid = S.state.profile.id;
  let v = await api("/vibe/" + pid);
  if (v.status === "none") v = await api("/vibe/" + pid, { method: "PUT", body: { text: "" } });
  paintVibe(v);
}

function vibeShell(title, back) {
  const el = h(`<div class="screen scroll vibe">
    <div class="topbar"><button class="icon-btn" id="vback">${I.back}</button><h1>${esc(title)}</h1>${modeBadge()}</div>
    <div class="vbody"></div></div>`);
  $("#vback", el).onclick = back || (() => go("profile"));
  app.replaceChildren(el);
  return $(".vbody", el);
}

function paintVibe(v) {
  clearInterval(S.poll); S.poll = null;
  const pid = S.state.profile.id;
  if (["analyzing", "fetching", "refining"].includes(v.status)) return vibeBusy(v, pid);
  if (v.status === "inputs" || v.edit) return vibeInputs(v, pid);
  if (v.status === "drafted") return vibeDraft(v, pid);
  if (v.status === "hone") return vibeHone(v, pid);
  return vibeResult(v, pid);
}

function vibeBusy(v, pid) {
  const body = vibeShell("Vibe hunt", () => go("profile"));
  const what = { analyzing: "Reading your references", fetching: "Finding listings to hone with", refining: "Sharpening your hunt" }[v.status];
  const note = { analyzing: "Claude is looking at everything you gave it and listing every way the vibe could be read.",
    fetching: "Searching Marketplace for each reading, then picking the best example of each. This can take a minute or two.",
    refining: "Folding your reactions into the hunt." }[v.status];
  body.replaceChildren(h(`<div class="center-state" style="min-height:70vh;min-height:70dvh"><div class="flame">${I.flame}</div>
    <h2>${what}</h2><p id="vprog">${esc(v.progress || "Getting started")}</p><p style="font-size:13px">${note} You can leave, it keeps going.</p></div>`));
  S.poll = setInterval(async () => {
    try {
      const nv = await api("/vibe/" + pid);
      if (nv.status !== v.status) { if (nv.error) toast(nv.error); paintVibe(nv); }
      else $("#vprog") && ($("#vprog").textContent = nv.progress || "");
    } catch {}
  }, 1500);
}

function vibeErr(v) { return v.error ? `<div class="vibe-err">${esc(v.error)}</div>` : ""; }

function vibeInputs(v, pid) {
  const body = vibeShell("Describe the vibe", v.edit ? () => paintVibe({ ...v, edit: false }) : () => go("profile"));
  const render = (cur) => {
    v = { ...cur, edit: v.edit };
    const srcs = v.sources.map((s) => `<div class="vsrc" data-id="${s.id}">
      <div class="vthumb" style="background-image:url(${s.images[0] || ""})">${s.images.length > 1 ? `<i>${s.images.length}</i>` : ""}</div>
      <div class="vlabel"><b>${esc(s.label)}</b><span class="mode-note">${{ image: "Photo", listing: "Marketplace listing", pin: "Pinterest pin", board: "Pinterest board" }[s.kind]}${s.images.length > 1 ? ` · ${s.images.length} pictures` : ""}</span></div>
      <button class="icon-btn vx" aria-label="Remove">${I.x}</button></div>`).join("");
    $(".vbody", app).innerHTML = `
      ${vibeErr(v)}
      <p class="mode-note" style="margin:10px 2px">Give Claude anything that shows the feeling. It will list every way that vibe could turn into something you can buy, then draft your hunt.</p>
      <div class="card-block"><h3>In words</h3>
        <div class="field" style="margin:0"><textarea id="v-text" rows="4" placeholder="e.g. I want a pop of color in my living room, or I'm into wall-mounted decor">${esc(v.text)}</textarea></div></div>
      <div class="card-block"><h3>Photos, listings and boards</h3>
        <div class="vsrcs">${srcs || '<p class="empty">Nothing added yet.</p>'}</div>
        <div class="inline" style="margin-top:10px"><input id="v-link" placeholder="Paste a Facebook listing, Pinterest pin or public board link" inputmode="url"><button class="btn" id="v-addlink">Add</button></div>
        <label class="btn vfile" for="v-file" style="margin-top:8px">Add photos (${v.images_left} left)</label>
        <input id="v-file" type="file" accept="image/*" multiple hidden>
        <p class="mode-note" style="margin-top:8px">Pinterest boards have to be public. For anything else, add a screenshot as a photo. Everything here is sent to Claude to read.</p></div>
      <button class="big-btn" id="v-go" style="margin-top:14px;flex:none">${v.readings.length ? "Redo my hunt" : "Write my hunt"}<small>Claude reads it all and drafts the hunt</small></button>`;
    wire();
  };
  const busy = async (btn, label, fn) => {
    const old = btn.textContent; btn.disabled = true; btn.textContent = label;
    try { await fn(); } catch (e) { if (!e.handled) toast(e.message); }
    btn.disabled = false; btn.textContent = old;
  };
  const wire = () => {
    const b = $(".vbody", app);
    const text = () => $("#v-text", b).value;
    $("#v-text", b).onblur = () => api("/vibe/" + pid, { method: "PUT", body: { text: text() } }).catch(() => {});
    b.querySelectorAll(".vsrc .vx").forEach((x) => (x.onclick = async () => {
      const t = text();
      render(await api(`/vibe/${pid}/source/${x.closest(".vsrc").dataset.id}`, { method: "DELETE" }));
      $("#v-text", b).value = t;
    }));
    const addLink = () => busy($("#v-addlink", b), "Fetching…", async () => {
      const url = $("#v-link", b).value.trim();
      if (!url) return;
      const t = text();
      const nv = await api(`/vibe/${pid}/link`, { body: { url } });
      render(nv); $("#v-text", $(".vbody", app)).value = t;
    });
    $("#v-addlink", b).onclick = addLink;
    $("#v-link", b).onkeydown = (e) => { if (e.key === "Enter") addLink(); };
    $("#v-file", b).onchange = async (e) => {
      const files = [...e.target.files]; e.target.value = "";
      const lbl = $(".vfile", b); lbl.textContent = "Adding…";
      const t = text(); let nv = null;
      for (const f of files) {
        try { nv = await api(`/vibe/${pid}/image`, { body: { data: await fileToJpeg(f) } }); }
        catch (err) { toast(err.message); break; }
      }
      render(nv || v); $("#v-text", $(".vbody", app)).value = t;
    };
    $("#v-go", b).onclick = () => busy($("#v-go", b), "Starting…", async () => {
      const nv = await api(`/vibe/${pid}/analyze`, { body: { text: text() } });
      paintVibe(nv);
    });
  };
  render(v);
}

// the editable hunt (text, checklist, budget) used for both the draft and the sharpened result
function huntEditor(d) {
  const crit = [...(d.criteria || [])];
  const el = h(`<div>
    <div class="field"><label>The hunt</label><textarea id="he-hunt" rows="5">${esc(d.hunt)}</textarea></div>
    <div class="field"><label>Checklist (shows up on every card)</label><div class="chips left" id="he-crit"></div>
      <div class="inline"><input id="he-add" placeholder="Add a checklist item"><button class="btn" id="he-addb">Add</button></div></div>
    <div class="two"><div class="field"><label>Min price</label><input id="he-min" inputmode="numeric" value="${d.min_price ?? ""}" placeholder="$"></div>
      <div class="field"><label>Max price</label><input id="he-max" inputmode="numeric" value="${d.max_price ?? ""}" placeholder="$"></div></div></div>`);
  const paint = () => {
    $("#he-crit", el).innerHTML = crit.map((c, i) => `<span class="chip mod">${esc(c)}<button data-i="${i}" aria-label="Remove">×</button></span>`).join("")
      || '<span class="empty">None yet</span>';
    el.querySelectorAll("#he-crit button").forEach((b) => (b.onclick = () => { crit.splice(+b.dataset.i, 1); paint(); }));
  };
  const add = () => { const v = $("#he-add", el).value.trim(); if (v) { crit.push(v); $("#he-add", el).value = ""; paint(); } };
  $("#he-addb", el).onclick = add;
  $("#he-add", el).onkeydown = (e) => { if (e.key === "Enter") add(); };
  paint();
  const num = (x) => (x.trim() === "" ? null : Number(x.replace(/[^0-9.]/g, "")));
  return { el, read: () => ({ hunt: $("#he-hunt", el).value.trim(), criteria: crit, min_price: num($("#he-min", el).value), max_price: num($("#he-max", el).value) }) };
}

function vibeDraft(v, pid) {
  const body = vibeShell("Your drafted hunt");
  const ed = huntEditor(v.draft);
  body.append(h(`<div>${vibeErr(v)}${v.draft.summary ? `<div class="take" style="margin-top:10px">${esc(v.draft.summary)}</div>` : ""}</div>`));
  const card = h(`<div class="card-block"><h3>Edit anything you like</h3></div>`);
  card.append(ed.el);
  body.append(card);
  body.append(h(`<details class="card-block vread"><summary><b>How I read your vibe</b> · ${v.readings.length} ways</summary>
    <p class="mode-note" style="margin:8px 0 0">Not what you meant? Tap the × and Claude drops it from your hone and steers away from it.</p>
    ${v.readings.map((r) => `<div class="vr" data-id="${r.id}"><div style="flex:1;min-width:0"><b>${esc(r.label)}</b>${r.note ? `<span class="mode-note"> ${esc(r.note)}</span>` : ""}<div class="mode-note">searches "${esc(r.query)}"</div></div>
      <button class="icon-btn vx" aria-label="Wrong reading: ${esc(r.label)}">${I.x}</button></div>`).join("")}</details>`));
  const acts = h(`<div class="vacts">
    ${v.honed ? "" : `<button class="big-btn" id="vhone" style="flex:none">Hone this hunt<small>Up to ${v.hone_size} real listings to react to, one per reading (a reading with nothing nearby is skipped). You get one hone per hunt</small></button>`}
    <button class="btn" id="vuse">${v.honed ? "Use this hunt" : "Use this and skip the hone"}</button>
    <button class="btn ghost" id="vedit">Change my references</button></div>`);
  body.append(acts);
  const save = () => api(`/vibe/${pid}/draft`, { method: "PUT", body: ed.read() });
  body.querySelectorAll(".vr .vx").forEach((x) => (x.onclick = async () => {
    const row = x.closest(".vr");
    x.disabled = true;
    try {
      const nv = await api(`/vibe/${pid}/reading/${row.dataset.id}`, { method: "DELETE" });
      v.readings = nv.readings; v.hone_size = nv.hone_size;
      row.remove();
      $(".vread summary").innerHTML = `<b>How I read your vibe</b> · ${nv.readings.length} ways`;
      const sm = $("#vhone small", acts);
      if (sm) sm.textContent = `Up to ${nv.hone_size} real listings to react to, one per reading (a reading with nothing nearby is skipped). You get one hone per hunt`;
    } catch (err) { toast(err.message); x.disabled = false; }
  }));
  $("#vhone", acts) && ($("#vhone", acts).onclick = async (e) => {
    const btn = e.currentTarget;  // currentTarget is null once the handler has awaited
    btn.disabled = true;
    try { await save(); paintVibe(await api(`/vibe/${pid}/hone`, { body: {} })); }
    catch (err) { toast(err.message); btn.disabled = false; }
  });
  $("#vuse", acts).onclick = async () => {
    try { await api(`/vibe/${pid}/apply`, { body: ed.read() }); toast("Hunt saved. Start a batch when you're ready."); go("home"); }
    catch (err) { toast(err.message); }
  };
  $("#vedit", acts).onclick = () => paintVibe({ ...v, edit: true });
}

function vibeHone(v, pid) {
  const body = vibeShell("Hone this hunt");
  const icons = vibeIcons();
  const items = v.items;
  const skipped = v.readings.filter((r) => r.found === false).length;
  body.append(h(`<div>${vibeErr(v)}<p class="mode-note" style="margin:10px 2px"><b>${items.length} listings</b>, each testing a different reading of your vibe${skipped ? ` (${skipped} reading${skipped === 1 ? "" : "s"} had nothing nearby)` : ""}.
    <span class="hi">${icons.up}</span> like, <span class="hi">${icons.heart}</span> love (up to 3), <span class="hi">${icons.trash}</span> hate. Skip any you feel nothing about. Then say why by picking a reason or writing a note, so Claude learns what you were really reacting to.</p></div>`));
  const grid = h(`<div class="hgrid"></div>`);
  body.append(grid);
  const foot = h(`<div class="hfoot"><span id="hcount"></span><button class="btn primary" id="hgo">Sharpen my hunt</button></div>`);
  app.firstElementChild.append(foot);
  const post = (it) => api(`/vibe/${pid}/react`, { body: { id: it.id, reaction: it.reaction, why: it.why, note: it.note } });
  const loves = () => items.filter((i) => i.reaction === "love").length;

  const paintFoot = () => {
    const rated = items.filter((i) => i.reaction), missing = rated.filter((i) => !i.why.length && !i.note.trim()).length;
    $("#hcount", foot).innerHTML = `${rated.length} reacted · <span class="hl">♥ ${loves()}/3</span>${missing ? ` · <b>${missing} need a why</b>` : ""}`;
    $("#hgo", foot).disabled = !rated.length || missing > 0;
  };
  const paintCard = (card, it) => {
    card.className = "hcard " + (it.reaction || "");
    card.querySelectorAll(".hbtn").forEach((b) => b.classList.toggle("on", b.dataset.r === it.reaction));
    const why = $(".hwhy", card);
    if (!it.reaction) { why.hidden = true; why.innerHTML = ""; return; }
    why.hidden = false;
    why.innerHTML = `<div class="hq">${it.reaction === "hate" ? "What puts you off?" : "What do you like about it?"} <span>Pick any, or just write a note.</span></div>
      <div class="chips left">${[...it.facets.map((f) => f.label), "Not sure"].map((l) =>
        `<button class="chip ${it.why.includes(l) ? "pick" : ""}" data-l="${esc(l)}">${esc(l)}</button>`).join("")}</div>
      <input class="hnote" placeholder="In your own words (optional)" value="${esc(it.note)}" maxlength="200">`;
    why.querySelectorAll(".chip").forEach((c) => (c.onclick = async () => {
      const l = c.dataset.l;
      if (l === "Not sure") it.why = it.why.includes(l) ? [] : [l];
      else { it.why = it.why.filter((x) => x !== "Not sure"); it.why = it.why.includes(l) ? it.why.filter((x) => x !== l) : [...it.why, l]; }
      paintCard(card, it); paintFoot();
      try { await post(it); } catch (e) { toast(e.message); }
    }));
    $(".hnote", why).oninput = (e) => { it.note = e.target.value; paintFoot(); };  // a note counts as a reason
    $(".hnote", why).onchange = async (e) => { it.note = e.target.value; try { await post(it); } catch (er) { toast(er.message); } };
  };
  items.forEach((it) => {
    const card = h(`<div class="hcard"><a class="himg" style="background-image:url(${it.photo})" ${it.url ? `href="${esc(it.url)}" target="_blank" rel="noopener"` : ""} aria-label="Open listing"></a>
      <div class="hmeta"><div class="htitle">${esc(it.title)}</div><div class="hprice">${esc(it.price_text)}</div><span class="chip">${esc(it.reading)}</span></div>
      <div class="hbtns"><button class="hbtn up" data-r="like" aria-label="Like">${icons.up}</button>
        <button class="hbtn love" data-r="love" aria-label="Love">${icons.heart}</button>
        <button class="hbtn down" data-r="hate" aria-label="Hate">${icons.trash}</button></div>
      <div class="hwhy" hidden></div></div>`);
    card.querySelectorAll(".hbtn").forEach((b) => (b.onclick = async () => {
      const r = b.dataset.r, before = { reaction: it.reaction, why: it.why, note: it.note };
      if (r === "love" && it.reaction !== "love" && loves() >= 3) return toast("You can love up to 3. Take a heart off another one first.");
      if (it.reaction === r) Object.assign(it, { reaction: null, why: [], note: "" });
      else Object.assign(it, { reaction: r, why: it.reaction && (it.reaction === "hate") === (r === "hate") ? it.why : [], note: it.note });
      paintCard(card, it); paintFoot();
      try { await post(it); } catch (e) { Object.assign(it, before); paintCard(card, it); paintFoot(); toast(e.message); }
    }));
    paintCard(card, it);
    grid.append(card);
  });
  paintFoot();
  $("#hgo", foot).onclick = async (e) => {
    e.currentTarget.disabled = true;
    try { foot.remove(); paintVibe(await api(`/vibe/${pid}/refine`, { body: {} })); }
    catch (err) { toast(err.message); app.firstElementChild.append(foot); paintFoot(); }
  };
}

function vibeResult(v, pid) {
  const body = vibeShell("Your sharpened hunt");
  const saved = v.status === "applied";
  const ed = huntEditor(saved ? { hunt: S.state.profile.hunt, criteria: S.state.profile.criteria, min_price: S.state.profile.min_price, max_price: S.state.profile.max_price } : v.result);
  const rated = v.items.filter((i) => i.reaction).length;
  if (v.result.learned?.length) body.append(h(`<div class="card-block"><h3>What I learned</h3><ul class="vlearn">${v.result.learned.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`));
  const card = h(`<div class="card-block"><h3>${saved ? "Saved to your hunt" : "Edit, then save"}</h3></div>`);
  card.append(ed.el);
  body.append(card);
  const acts = h(`<div class="vacts">
    <button class="big-btn" id="vsave" style="flex:none">${saved ? "Save changes" : "Save to my hunt"}<small>Your next batch uses this</small></button>
    ${rated ? `<button class="btn" id="vweb" ${v.web_added ? "disabled" : ""}>${v.web_added ? "Ratings are in your web" : `Also add my ${rated} rating${rated === 1 ? "" : "s"} to my web${rated < v.items.length ? ` (of ${v.items.length} listings)` : ""}`}</button>
      <p class="mode-note">Optional. The hone ratings only shaped this hunt. Adding them also teaches your taste web, as a finished batch.</p>` : ""}
    ${saved ? `<button class="btn ghost" id="vdone">Back to home</button>` : ""}</div>`);
  body.append(acts);
  $("#vsave", acts).onclick = async () => {
    try { await api(`/vibe/${pid}/apply`, { body: ed.read() }); toast("Saved. Start a batch when you're ready."); go("home"); }
    catch (err) { toast(err.message); }
  };
  $("#vweb", acts) && ($("#vweb", acts).onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const r = await api(`/vibe/${pid}/web`, { body: {} });
      toast(`Added ${r.added} of ${rated} to your web`);
      btn.textContent = "Ratings are in your web";
    } catch (err) { toast(err.message); btn.disabled = false; }
  });
  $("#vdone", acts) && ($("#vdone", acts).onclick = () => go("home"));
}
