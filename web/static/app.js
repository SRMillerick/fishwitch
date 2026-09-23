/* fishwitch browser layer — the profile vault.
   Custody model: profiles (birth data = identity-grade PII) live ONLY in this
   browser's localStorage. They travel exclusively inside POST bodies to render
   reports and never persist anywhere else. This file is the whole vault. */
"use strict";

const VAULT_KEY = "fishwitch_profiles";   // { name: profile }
const ACTIVE_KEY = "fishwitch_active";    // name | absent
const LEGACY_KEY = "fishwitch_profile";   // pre-vault single-profile key

// ── vault core ──────────────────────────────────────────────────────────────
function migrateLegacy() {
  const raw = localStorage.getItem(LEGACY_KEY);
  if (!raw) return;
  try {
    const p = JSON.parse(raw);
    if (p && p.name) {
      const v = vault();
      if (!v[p.name]) { v[p.name] = p; writeVault(v); localStorage.setItem(ACTIVE_KEY, p.name); }
    }
    localStorage.removeItem(LEGACY_KEY);
  } catch { localStorage.removeItem(LEGACY_KEY); }
}

function vault() {
  try { return JSON.parse(localStorage.getItem(VAULT_KEY) || "{}"); } catch { return {}; }
}
function writeVault(v) { localStorage.setItem(VAULT_KEY, JSON.stringify(v)); }
function getActive() {
  const a = localStorage.getItem(ACTIVE_KEY), v = vault();
  return (a && v[a]) ? v[a] : null;
}
function setActive(name) {
  if (name === null) localStorage.removeItem(ACTIVE_KEY);
  else localStorage.setItem(ACTIVE_KEY, name);
}
function saveProfile(p) { const v = vault(); v[p.name] = p; writeVault(v); setActive(p.name); }
function forget(name) {
  const v = vault(); delete v[name]; writeVault(v);
  if (localStorage.getItem(ACTIVE_KEY) === name) setActive(null);
}

// client-side mirror of the server's profile rules (webapp._client_profile)
function profileError(p) {
  if (!p || typeof p !== "object") return "not a JSON object";
  const n = String(p.name || "").trim();
  if (n.length < 1 || n.length > 40) return "name: 1–40 characters";
  const b = p.birth || {};
  if (!/^\d{4}-\d{2}-\d{2}$/.test(b.date || "")) return "birth.date: YYYY-MM-DD";
  const y = +b.date.slice(0, 4);
  if (y < 1850 || y > 2100) return "birth.date: between 1850 and 2100";
  if (!/^\d{2}:\d{2}$/.test(b.time || "")) return "birth.time: HH:MM (24h)";
  if (!(Math.abs(+b.lat) <= 90 && Math.abs(+b.lng) <= 180)) return "birth lat/lng out of range";
  if (p.arsenal !== undefined && (!Array.isArray(p.arsenal) || p.arsenal.length > 30
      || p.arsenal.some(a => typeof a !== "string" || a.length > 60)))
    return "arsenal: list of ≤ 30 strings, each ≤ 60 chars";
  if (p.knots !== undefined && (!Array.isArray(p.knots) || p.knots.length > 30
      || p.knots.some(a => typeof a !== "string" || a.length > 60)))
    return "knots: list of ≤ 30 strings, each ≤ 60 chars";
  if (p.line !== undefined && (!Array.isArray(p.line) || p.line.length > 30
      || p.line.some(a => typeof a !== "string" || a.length > 60)))
    return "line: list of ≤ 30 strings, each ≤ 60 chars";
  if (p.baits !== undefined && (!Array.isArray(p.baits) || p.baits.length > 30
      || p.baits.some(a => typeof a !== "string" || a.length > 60)))
    return "baits: list of ≤ 30 strings, each ≤ 60 chars";
  if (p.setups !== undefined) {
    const su = p.setups;
    const bad = !su || typeof su !== "object" || Array.isArray(su)
      || Object.keys(su).length > 30
      || Object.keys(su).some(k => k.length < 1 || k.length > 60)
      || Object.values(su).some(v => !v || typeof v !== "object" || Array.isArray(v)
           || Object.keys(v).length > 20
           || Object.values(v).some(x => typeof x !== "string" || x.length < 1 || x.length > 120));
    if (bad) return "setups: object of rig → object of strings (≤ 30 rigs, ≤ 20 parts, each ≤ 120 chars)";
  }
  if (p.astro_display !== undefined && !["fisher", "almanac", "astro"].includes(p.astro_display))
    return "astro_display: fisher | almanac | astro";
  return null;
}

const esc = s => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── tag fields — one consistent multi-value control for the interview ───────
// The native datalist only helps with the FIRST comma-separated item; every
// later value had to be typed blind. This behaves the same for all fields:
// chips for what's chosen, a suggestion menu while typing, Enter/comma adds,
// free text still accepted, hidden input keeps the form contract unchanged.
function makeTagField(root) {
  const dl = document.getElementById(root.dataset.suggest || "");
  const all = dl ? [...dl.options].map(o => o.value) : [];
  const hidden = root.querySelector('input[type="hidden"]');
  const chips = document.createElement("span"); chips.className = "tag-chips";
  const input = document.createElement("input");
  input.type = "text"; input.className = "tag-text";
  input.placeholder = root.dataset.placeholder || "";
  input.setAttribute("autocomplete", "off");
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  const menu = document.createElement("div"); menu.className = "tag-menu"; menu.hidden = true;
  menu.setAttribute("role", "listbox");
  root.append(chips, input, menu);

  let values = [];
  const sync = () => { if (hidden) hidden.value = values.join(", "); };
  const draw = () => {
    chips.textContent = "";
    values.forEach((v, i) => {
      const chip = document.createElement("span"); chip.className = "tag";
      chip.appendChild(document.createTextNode(v));
      const x = document.createElement("button");
      x.type = "button"; x.tabIndex = -1; x.textContent = "\u00d7";
      x.setAttribute("aria-label", "remove " + v);
      x.addEventListener("click", () => { values.splice(i, 1); draw(); sync(); input.focus(); });
      chip.appendChild(x); chips.appendChild(chip);
    });
  };
  const hide = () => { menu.hidden = true; input.setAttribute("aria-expanded", "false"); };
  const matches = () => {
    const q = input.value.trim().toLowerCase();
    const have = new Set(values.map(v => v.toLowerCase()));
    return all.filter(s => !have.has(s.toLowerCase()) && (!q || s.toLowerCase().includes(q))).slice(0, 8);
  };
  const show = () => {
    const opts = matches();
    if (!opts.length) { hide(); return; }
    menu.textContent = "";
    for (const s of opts) {
      const o = document.createElement("div");
      o.className = "tag-opt"; o.setAttribute("role", "option"); o.textContent = s;
      o.addEventListener("mousedown", ev => { ev.preventDefault(); add(s); input.focus(); });
      menu.appendChild(o);
    }
    menu.hidden = false; input.setAttribute("aria-expanded", "true");
  };
  const add = raw => {
    const v = String(raw || "").replace(/,+$/, "").trim();
    if (!v) { input.value = ""; hide(); return; }
    if (!values.some(x => x.toLowerCase() === v.toLowerCase())) values.push(v);
    input.value = ""; draw(); sync(); show();
  };
  input.addEventListener("input", show);
  input.addEventListener("focus", show);
  input.addEventListener("keydown", ev => {
    if (ev.key === "Enter" || ev.key === ",") {
      ev.preventDefault(); ev.stopPropagation(); add(input.value);
    } else if (ev.key === "Backspace" && !input.value && values.length) {
      values.pop(); draw(); sync();
    } else if (ev.key === "Escape") hide();
  });
  input.addEventListener("blur", () => setTimeout(() => {
    if (input.value.trim()) add(input.value);
    hide();
  }, 120));
  draw(); sync();
  return { setValues: vs => { values = [...(vs || [])]; draw(); sync(); },
           values: () => [...values] };
}

// ── header menu ─────────────────────────────────────────────────────────────
const menu = document.getElementById("profile-menu");

function renderMenu() {
  if (!menu) return;
  const v = vault(), active = localStorage.getItem(ACTIVE_KEY);
  const who = menu.querySelector("summary .who");
  if (who) who.textContent = (active && v[active]) ? v[active].name
                 : (Object.keys(v).length ? "Profiles" : "Anonymous");
  const body = menu.querySelector(".menu-body");
  let h = "";
  for (const name of Object.keys(v)) {
    const on = name === active ? " on" : "";
    h += `<div class="mrow${on}" data-act="use" data-name="${esc(name)}">
            <span>${esc(name)}</span>
            <span class="micons">
              <a href="#" data-act="edit" data-name="${esc(name)}" title="edit name, tackle box and builds">edit</a>
              <a href="#" data-act="export" data-name="${esc(name)}" title="download profile.json">download</a>
              <a href="#" data-act="forget" data-name="${esc(name)}" title="forget this profile in this browser">forget</a>
            </span></div>`;
  }
  if (!Object.keys(v).length) h += `<div class="mhint">No profiles in this browser yet.</div>`;
  h += `<div class="mrow" data-act="new">New profile…</div>`;
  h += `<div class="mrow" data-act="import">Import profile.json…</div>`;
  if (active) h += `<div class="mrow" data-act="anon">Browse anonymously</div>`;
  h += `<div class="mhint">Profiles stay in this browser — sent nowhere except to render your reports.</div>`;
  body.innerHTML = h;
}

if (menu) {
  renderMenu();
  const filePick = document.createElement("input");
  filePick.type = "file"; filePick.accept = "application/json,.json"; filePick.hidden = true;
  menu.appendChild(filePick);
  menu.querySelector(".menu-body").addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-act]");
    if (!t) return;
    ev.preventDefault();
    const act = t.dataset.act, name = t.dataset.name;
    if (act === "use") { setActive(name); window.location.reload(); }
    else if (act === "anon") { setActive(null); window.location.reload(); }
    else if (act === "edit") { setActive(name); window.location.href = "/interview"; }
    else if (act === "new") { setActive(null); window.location.href = "/interview"; }
    else if (act === "export") {
      const p = vault()[name]; if (!p) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: "application/json" }));
      a.download = "baromoon-profile-" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-") + ".json";
      a.click(); URL.revokeObjectURL(a.href);
    } else if (act === "forget") {
      if (confirm(`Forget ${name}'s profile in this browser? (the downloaded file, if any, is untouched)`)) {
        forget(name); window.location.reload();
      }
    } else if (act === "import") filePick.click();
  });
  filePick.addEventListener("change", () => {
    const f = filePick.files[0]; if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      let p, err;
      try { p = JSON.parse(rd.result); err = profileError(p); }
      catch { err = "not valid JSON"; }
      if (err) { alert("profile rejected: " + err); return; }
      saveProfile(p); window.location.reload();
    };
    rd.readAsText(f);
  });
  document.addEventListener("click", (ev) => {  // close on outside click
    if (menu.open && !menu.contains(ev.target)) menu.open = false;
  });
  document.addEventListener("keydown", (ev) => {  // and on Escape
    if (ev.key === "Escape" && menu.open) menu.open = false;
  });
}

// ── compact mobile nav ──────────────────────────────────────────────────────
const navToggle = document.getElementById("nav-toggle");
if (navToggle) {
  const navEl = navToggle.closest("nav");
  const setNav = (open) => {
    navEl.classList.toggle("open", open);
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open && menu && menu.open) menu.open = false;
  };
  navToggle.addEventListener("click", () => setNav(!navEl.classList.contains("open")));
  document.addEventListener("click", (ev) => {   // close on outside click
    if (navEl.classList.contains("open") && !navEl.contains(ev.target)) setNav(false);
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && navEl.classList.contains("open")) setNav(false);
  });
}

// ── landing: personalize the tier ledger when a profile is active ──────────
const ledgerRows = document.getElementById("ledger-rows");
if (ledgerRows) {
  const p = getActive();
  if (p) {
    const scope = document.getElementById("ledger-scope");
    const note = document.getElementById("ledger-note");
    if (scope) scope.textContent = p.name + "’s waters · next 5 days";
    if (note) note.textContent = "casting the windows for " + p.name + "…";
    ledgerRows.innerHTML = '<li class="fine">casting…</li>';
    fetch("/api/outlook", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: 5, profile: p }),
    }).then(r => r.json()).then(j => {
      if (j.error || !j.rows) { ledgerRows.innerHTML = ""; return; }
      ledgerRows.innerHTML = j.rows.map(r =>
        `<li><a class="trow ${r.tier}" href="/report?lake=${encodeURIComponent(r.lake_id)}&at=${encodeURIComponent(r.start)}&hours=2&voice=${p.astro_display || 'almanac'}">` +
        `<span class="tier">${r.tier}</span>` +
        `<span class="when"><span class="day">${esc(r.day)}</span><span class="clock">${esc(r.clock)}</span> <span class="lune">${r.moon}</span></span>` +
        `<span class="where">${esc(r.lake)}</span>` +
        `<span class="rig">${esc(r.rig)}</span>` +
        `<span class="score">${r.overall}<i>/10</i></span></a></li>`).join("");
      if (note) note.textContent = j.rows.length
        ? `Best upcoming windows for ${p.name} — transits + tackle, nearest waters.`
        : "no scorable windows in range";
    }).catch(() => { ledgerRows.innerHTML = ""; });
  }
}

// ── landing: nearest-water preview for anonymous visitors ────────────────
// The registry ride-along (#bm-waters) is enough to pick the closest water
// in-browser. Coordinates never leave this page: we only navigate to
// /?lake=<id> once we know which public water won. Anonymous visitors get an
// automatic location request on load (the browser's native prompt); the quiet
// link stays as the fallback when the prompt is blocked or dismissed.
const watersEl = document.getElementById("bm-waters");
const nearWrap = document.getElementById("near-me-wrap");
const nearLink = document.getElementById("near-me");
const nearNote = document.getElementById("near-me-note");
if (ledgerRows && watersEl) {
  let waters = [];
  try { waters = JSON.parse(watersEl.textContent || "[]") || []; } catch {}
  const params = new URLSearchParams(location.search);
  const chosen = params.get("lake");
  const rad = (d) => d * Math.PI / 180;
  const km = (lat, lng, w) => {
    const dLat = rad(w.lat - lat), dLng = rad(w.lng - lng);
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(rad(lat)) * Math.cos(rad(w.lat)) * Math.sin(dLng / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
  };
  const nearest = (lat, lng) => waters
    .filter(w => w.lat != null && w.lng != null)
    .sort((a, b) => km(lat, lng, a) - km(lat, lng, b))[0];
  const sortWaters = (lat, lng) => {
    const ul = document.getElementById("waters-list");
    if (!ul) return;
    [...ul.children]
      .map(li => [li, li.dataset.lat && li.dataset.lng
        ? km(lat, lng, { lat: +li.dataset.lat, lng: +li.dataset.lng }) : Infinity])
      .sort((a, b) => a[1] - b[1])
      .forEach(([li]) => ul.appendChild(li));
  };
  const locate = () => new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve([p.coords.latitude, p.coords.longitude]),
      () => resolve(null), { maximumAge: 86400000, timeout: 8000 });
  });
  const apply = (fix) => {
    if (nearLink) nearLink.textContent = "Waters near me";
    if (!fix) {
      if (nearNote) nearNote.textContent = " — location unavailable; showing the demo water.";
      if (nearWrap) nearWrap.hidden = false;
      return;
    }
    sortWaters(fix[0], fix[1]);
    const w = nearest(fix[0], fix[1]);
    if (w && !chosen) location.replace("/?lake=" + encodeURIComponent(w.id) + "#ledger");
  };
  const ask = () => {
    if (nearLink) nearLink.textContent = "locating…";
    locate().then(apply);
  };
  if (nearLink) nearLink.addEventListener("click", (ev) => {
    ev.preventDefault();
    if (nearNote) nearNote.textContent = "";
    ask();
  });
  if (getActive()) {
    if (nearWrap) nearWrap.hidden = true;      // the profile ledger takes over
  } else {
    let asked = false;
    try { asked = sessionStorage.getItem("bm-geo-asked") === "1"; } catch {}
    const promptOnce = () => {                 // once per tab, so a dismissal isn't nagged
      if (asked) { if (nearWrap) nearWrap.hidden = false; return; }
      asked = true;
      try { sessionStorage.setItem("bm-geo-asked", "1"); } catch {}
      ask();
    };
    let perm = null;
    try { perm = navigator.permissions && navigator.permissions.query({ name: "geolocation" }); } catch {}
    if (perm) {
      perm.then((p) => {
        if (p.state === "granted") ask();      // silent when already allowed
        else if (p.state === "denied" && !chosen) {
          if (nearNote) nearNote.textContent = " — location blocked for this site; showing the demo water.";
          if (nearWrap) nearWrap.hidden = false;
        } else if (p.state === "prompt" && !chosen) {
          promptOnce();                        // native prompt on the demo landing
        }
      }).catch(() => { if (!chosen) promptOnce(); });
    } else if (!chosen) {
      promptOnce();                            // no Permissions API: still try on load
    }
  }
}

// ── report form: POST the active profile with the query ────────────────────
const form = document.getElementById("report-form");
if (form) {
  { // whose profile will this render use? say so up front
    const note = document.getElementById("profile-note");
    const p0 = getActive();
    if (note) note.className = "pill " + (p0 ? "on" : "");
    if (note) note.textContent = p0
      ? "Rendering as " + p0.name + " — transits + tackle · profile stays in this browser"
      : "Rendering anonymously — build a profile for transits + your tackle →";
  }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const date = f.get("date") || new Date().toISOString().slice(0, 10);
    const time = f.get("time") || "18:00";
    const payload = {
      lake: f.get("lake"), at: date + " " + time,
      hours: f.get("hours"), voice: f.get("voice"), species: f.get("species"),
      bottom: f.get("bottom"), clarity: f.get("clarity"),
      profile: getActive() || undefined,
    };
    const out = document.getElementById("report-out");
    out.innerHTML = '<p class="fine">casting…</p>';
    try {
      const r = await fetch("/api/report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (j.error) {
        out.innerHTML = '<p class="error">' + esc(j.error)
          + (j.details ? "<br>" + esc(j.details.join("; ")) : "") + "</p>";
        return;
      }
      const p = getActive();
      const note = document.getElementById("profile-note");
      if (note) note.textContent = p
        ? `Rendered with ${p.name}'s profile (transits + tackle) — profile stays in this browser.`
        : "Rendering anonymously — pick or create a profile for transits + tackle.";
      out.innerHTML =
        '<div class="scorebar">overall <strong>' + j.overall + "/10</strong> · " + esc(j.lake) + "</div>"
        + j.html + renderTackle(j.rods) + renderTrends(j.trends) + renderShopping(j.shopping) + renderGap(j.gap);
      const logLink = document.getElementById("log-session");
      if (logLink) {
        logLink.href = "/log?" + new URLSearchParams({
          lake: f.get("lake") || "", at: date + " " + time,
          species: f.get("species") || "", lure: (j.picks && j.picks[0]) || "",
        }).toString();
      }
    } catch (e) {
      out.innerHTML = '<p class="error">render failed: ' + esc(String(e)) + "</p>";
    }
  });
}

function buildList(entryId, comps, src) {
  const rows = comps.map(c => {
    const links = (c.offers || []).filter(o => o.url).map(o =>
      " <a href='/out/" + encodeURIComponent(entryId) + "/" + encodeURIComponent(o.retailer) +
      "?comp=" + encodeURIComponent(c.id) + "&src=" + src + "' target='_blank' rel='sponsored noopener'>" +
      esc(o.retailer_label || o.retailer) + "</a>").join("");
    return esc(c.label) + links;
  }).join(" · ");
  return "<div class='fine build'><span class='sc'>build it:</span> " + rows + "</div>";
}

function renderTrends(list) {
  if (!list || !list.length) return "";
  let h = '<section class="tackle"><h2>📈 Trend watch — what\'s winning</h2>' +
    '<p class="fine">Dated tournament/creator signals for rigs that already fit these conditions — ' +
    'shown after ranking and never scored into it.</p><ul class="plain">';
  for (const t of list.slice(0, 4)) {
    h += "<li><strong>" + esc(t.label) + "</strong> — scores " + esc(t.score) + " here · " +
      (t.url ? "<a href='" + esc(t.url) + "' target='_blank' rel='noopener'>" + esc(t.source) + "</a>" : esc(t.source)) +
      " <span class='fine'>(" + esc(t.observed_at) + ")</span>";
    if (t.quote) h += "<div class='fine'>“" + esc(t.quote.slice(0, 200)) + "”</div>";
    h += "</li>";
  }
  return h + "</ul></section>";
}

function renderShopping(list) {
  if (!list || !list.length) return "";
  let h = '<section class="tackle"><h2>🛒 Shopping list — everything the top rigs need</h2>' +
    '<p class="fine">One row per part, consolidated across the recommended rigs. Links attach ' +
    'after ranking, and ranking never sees them.</p><ul class="plain">';
  for (const s of list) {
    h += "<li><strong>" + esc(s.label) + "</strong>";
    if (s.for_labels && s.for_labels.length)
      h += " <span class='fine'>for " + esc(s.for_labels.join(" · ")) + "</span>";
    if (s.note) h += "<div class='fine'>" + esc(s.note) + "</div>";
    for (const o of (s.offers || [])) if (o.url)
      h += " · <a href='/out/" + encodeURIComponent(o.entry) + "/" + encodeURIComponent(o.retailer) +
        "?comp=" + encodeURIComponent(s.id) + "&src=shopping' target='_blank' rel='sponsored noopener'>" +
        esc(o.retailer_label || o.retailer) + "</a> <span class='fine'>(" + esc(o.disclosure) + ")</span>";
    if (s.alternatives && s.alternatives.length)
      h += "<div class='fine'>also: " + s.alternatives.map(a => {
        let t = esc(a.label);
        for (const o of (a.offers || [])) if (o.url)
          t += " <a href='/out/" + encodeURIComponent(o.entry) + "/" + encodeURIComponent(o.retailer) +
            "?comp=" + encodeURIComponent(s.id) + "&src=shopping' target='_blank' rel='sponsored noopener'>" +
            esc(o.retailer_label || o.retailer) + "</a>";
        return t;
      }).join(" · ") + "</div>";
    h += "</li>";
  }
  return h + "</ul></section>";
}

function renderTackle(rods) {
  if (!rods || !rods.length) return "";
  let h = '<section class="tackle"><h2>Tackle for this session — sources & offers</h2>' +
    '<p class="fine">Ranking never sees these links. They attach after the pipe ends.</p><ul class="plain">';
  for (const r of rods) {
    h += "<li><span class='badge " + (r.verified ? "ok" : "pend") + "'>" +
      (r.verified ? "cited" : "unverified") + "</span>";
    if (r.owned !== undefined && r.owned !== null)
      h += " <span class='badge " + (r.owned ? "mine" : "gap") + "'>" +
        (r.owned ? "in your box" : "gap") + "</span>";
    h += " <strong>" + esc(r.label) + "</strong>";
    if (r.product_url) h += " · <a href='/out/" + encodeURIComponent(r.id) + "/manufacturer?src=tackle' target='_blank' rel='nofollow noopener'>" +
      esc(r.product || "manufacturer page") + "</a>";
    for (const o of (r.offers || [])) if (o.url)
      h += " · <a href='/out/" + encodeURIComponent(r.id) + "/" + encodeURIComponent(o.retailer) + "?src=tackle' target='_blank' rel='sponsored noopener'>" + esc(o.retailer_label || o.retailer) +
        "</a> <span class='fine'>(" + esc(o.disclosure) + ")</span>";
    if (r.components && r.components.length) h += buildList(r.id, r.components, "tackle");
    if (r.your_setup_line) h += "<div class='fine'><span class='sc'>your build:</span> " + esc(r.your_setup_line) + "</div>";
    else if (r.spec_line) h += "<div class='fine'><span class='sc'>build:</span> " + esc(r.spec_line) + "</div>";
    h += "<div class='fine'>" + esc(r.source) +
      (r.source_url ? " · <a href='" + r.source_url + "' target='_blank' rel='noopener'>source</a>" : "") + "</div></li>";
  }
  return h + "</ul></section>";
}

function renderGap(gap) {
  if (!gap || !gap.length) return "";
  const products = gap.filter(g => g.kind !== "rig");
  const rigs = gap.filter(g => g.kind === "rig");
  let h = "";
  if (products.length) {
    h += '<section class="tackle"><h2>🧭 The gap in your tackle box</h2>' +
      '<p class="fine">Scored by the same pipe for these exact conditions — you don’t own these yet. ' +
      'Links attach after ranking, never before.</p><ul class="plain">';
    for (const g of products) {
      h += "<li><span class='badge " + (g.verified ? "ok" : "pend") + "'>" +
        (g.verified ? "cited" : "unverified") + "</span> <strong>" + esc(g.label) + "</strong> — scores " +
        g.score + " here" + (g.why ? " · <span class='fine'>" + esc(g.why) + "</span>" : "");
      if (g.product_url) h += " · <a href='/out/" + encodeURIComponent(g.id) + "/manufacturer?src=gap' target='_blank' rel='nofollow noopener'>" +
        esc(g.product || "manufacturer page") + "</a>";
      for (const o of (g.offers || [])) if (o.url)
        h += " · <a href='/out/" + encodeURIComponent(g.id) + "/" + encodeURIComponent(o.retailer) + "?src=gap' target='_blank' rel='sponsored noopener'>" + esc(o.retailer_label || o.retailer) +
          "</a> <span class='fine'>(" + esc(o.disclosure) + ")</span>";
      h += "</li>";
    }
    h += "</ul></section>";
  }
  if (rigs.length) {
    h += '<section class="tackle"><h2>🧵 Rig &amp; technique gaps</h2>' +
      '<p class="fine">Rigging patterns these conditions favor that aren’t in your box — built from ' +
      'hooks, weights, and plastics you mostly own. A how-to, not a purchase.</p><ul class="plain">';
    for (const g of rigs) {
      h += "<li><span class='badge'>rig</span> <strong>" + esc(g.label) + "</strong> — scores " +
        g.score + " here" + (g.why ? " · <span class='fine'>" + esc(g.why) + "</span>" : "");
      if (g.components && g.components.length) h += buildList(g.id, g.components, "gap");
      h += "</li>";
    }
    h += "</ul></section>";
  }
  return h;
}
const iv = document.getElementById("interview");
if (iv) {
  let picked = null;
  let step = 1;
  const steps = [...iv.querySelectorAll(".istep")];
  const tagFields = {};
  iv.querySelectorAll("[data-tagfield]").forEach(el => {
    const name = (el.querySelector('input[type="hidden"]') || {}).name;
    if (name) tagFields[name] = makeTagField(el);
  });

  // step 4: show only the reference builds that match the angler's arsenal
  const builds = document.getElementById("builds");
  const renderBuilds = () => {
    if (!builds) return;
    const owned = (tagFields.arsenal && tagFields.arsenal.values()) || [];
    const norm = s => (s || "").trim().toLowerCase();
    const ownedSet = new Set(owned.map(norm));
    let shown = 0;
    builds.querySelectorAll(".build-card").forEach(card => {
      const names = (card.dataset.aliases || "").split("|").map(norm).filter(Boolean);
      let hit = names.some(n => ownedSet.has(n));          // exact first
      if (!hit) hit = owned.some(o => {                    // then substring
        const s = norm(o);
        return names.some(n => n.includes(s) || s.includes(n));
      });
      card.hidden = !hit;
      if (hit) shown++;
    });
    const empty = document.getElementById("builds-empty");
    if (empty) empty.hidden = shown > 0;
  };

  const showStep = (n) => {
    step = n;
    steps.forEach(s => s.classList.toggle("on", +s.dataset.step === n));
    document.querySelectorAll("#wiz-progress li").forEach(li =>
      li.classList.toggle("on", +li.dataset.step === n));
    if (n === 4) renderBuilds();
  };

  // prefill from the active profile (edit mode)
  const cur = getActive();
  if (cur) {
    const eyebrow = document.querySelector(".eyebrow");
    if (eyebrow) eyebrow.textContent = "editing " + (cur.name || "your") + " — change the name to create a separate profile";
    iv.querySelector('[name="name"]').value = cur.name || "";
    if (cur.birth) {
      iv.querySelector('[name="bdate"]').value = cur.birth.date || "";
      if (cur.birth.time_known === false) {
        iv.querySelector('[name="time_unknown"]').checked = true;
        iv.querySelector('[name="btime"]').value = "";
      } else iv.querySelector('[name="btime"]').value = cur.birth.time || "";
      iv.querySelector('[name="bplace"]').value = cur.birth.place || "";
      picked = { name: cur.birth.place || "", lat: cur.birth.lat, lng: cur.birth.lng, tz: cur.birth.tz };
      const box0 = document.getElementById("geocode-out");
      if (box0 && cur.birth.place) box0.textContent =
        "→ from saved profile (" + (+cur.birth.lat).toFixed(3) + ", " + (+cur.birth.lng).toFixed(3) + ", " + cur.birth.tz + ")";
    }
    iv.querySelector('[name="species"]').value = cur.species || "largemouth bass";
    if (tagFields.arsenal) tagFields.arsenal.setValues(cur.arsenal || []);
    if (tagFields.baits) tagFields.baits.setValues(cur.baits || []);
    if (tagFields.line) tagFields.line.setValues(cur.line || []);
    if (tagFields.knots) tagFields.knots.setValues(cur.knots || []);
    if (cur.setups && builds) {   // prefill saved builds (edit mode)
      builds.querySelectorAll(".build-card").forEach(card => {
        const s = cur.setups[card.dataset.rig] || {};
        card.querySelectorAll("input[data-part]").forEach(inp => {
          if (s[inp.dataset.part]) inp.value = s[inp.dataset.part];
        });
      });
    }
    if (cur.home_lake) iv.querySelector('[name="home_lake"]').value = cur.home_lake;
    iv.querySelector('[name="voice"]').value = cur.astro_display || "almanac";
  }

  const place = document.getElementById("bplace");
  if (place) place.addEventListener("change", async () => {   // guard: static build has no #bplace
    picked = null;
    const box = document.getElementById("geocode-out");
    box.textContent = "looking up…";
    try {
      const r = await fetch("/api/geocode", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: place.value }),
      });
      const cands = await r.json();
      if (!Array.isArray(cands) || !cands.length) {
        box.textContent = "no match — try ‘City, State’ or ‘City, State, Country’ (e.g. Santa Rosa, CA)";
        return;
      }
      picked = cands[0];
      box.textContent = "→ " + [picked.name, picked.region, picked.country].filter(Boolean).join(", ") +
        "  (" + picked.lat.toFixed(3) + ", " + picked.lng.toFixed(3) + ", " + picked.tz + ")";
    } catch {
      box.textContent = "Geocoding service unreachable — check the connection and try again";
    }
  });

  const stepValid = (n) => {
    if (n === 1) {
      if (!(iv.querySelector('[name="name"]').value || "").trim())
        return "your name (first is fine) keeps profiles separate in this browser";
    }
    if (n === 2) {
      const bd = iv.querySelector('[name="bdate"]').value;
      const bt = iv.querySelector('[name="btime"]').value;
      const unk = iv.querySelector('[name="time_unknown"]').checked;
      const pl = (iv.querySelector('[name="bplace"]').value || "").trim();
      if (!bd) return "birth date powers the sky layer — even a rough year works";
      if (!bt && !unk) return "birth time — or tick ‘time unknown’";
      if (pl && !picked) return "place not matched yet — wait for the → line, or retype (City, State)";
    }
    return null;
  };
  const tryNext = () => {
    const err = stepValid(step);
    if (err) { document.getElementById("status").textContent = err; return; }
    document.getElementById("status").textContent = "";
    showStep(Math.min(step + 1, 4));
  };
  iv.querySelectorAll(".next").forEach(b => b.addEventListener("click", tryNext));
  iv.querySelectorAll(".back").forEach(b => b.addEventListener("click", () =>
    showStep(Math.max(step - 1, 1))));
  iv.addEventListener("keydown", (ev) => {   // Enter advances instead of submitting early
    if (ev.key === "Enter" && ev.target.tagName !== "BUTTON" && step < 4) {
      ev.preventDefault(); tryNext();
    }
  });

  iv.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(iv);
    const unknown = f.get("time_unknown") === "on";
    const placeStr = (f.get("bplace") || "").trim();
    if (placeStr && !picked) {
      document.getElementById("status").textContent =
        "couldn’t geocode ‘" + placeStr + "’ — retype it (City, State, Country) and wait for the match before saving.";
      return;
    }
    const p = {
      name: (f.get("name") || "friend").trim(),
      birth: {
        date: f.get("bdate"), time: unknown ? "12:00" : (f.get("btime") || "12:00"),
        time_known: !unknown, place: placeStr,
        lat: picked ? picked.lat : 0, lng: picked ? picked.lng : 0,
        tz: picked ? picked.tz : "UTC",
      },
      species: f.get("species") || "largemouth bass",
      arsenal: (f.get("arsenal") || "").split(",").map(s => s.trim()).filter(Boolean),
      baits: (f.get("baits") || "").split(",").map(s => s.trim()).filter(Boolean),
      line: (f.get("line") || "").split(",").map(s => s.trim()).filter(Boolean),
      knots: (f.get("knots") || "").split(",").map(s => s.trim()).filter(Boolean),
      home_lake: f.get("home_lake"),
      astro_display: f.get("voice") || "almanac",
      created: (cur && cur.created) || new Date().toISOString(),   // keep original on edit
      updated: new Date().toISOString(),
    };
    const setups = {};
    iv.querySelectorAll(".build-card").forEach(card => {
      if (card.hidden) return;
      const obj = {};
      card.querySelectorAll("input[data-part]").forEach(inp => {
        const v = (inp.value || "").trim();
        if (v) obj[inp.dataset.part] = v;
      });
      if (Object.keys(obj).length) setups[card.dataset.rig] = obj;
    });
    if (Object.keys(setups).length) p.setups = setups;
    const err = profileError(p);
    if (err) { document.getElementById("status").textContent = err; return; }
    saveProfile(p);
    renderMenu();
    const blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    const dl = document.getElementById("download");
    dl.href = URL.createObjectURL(blob); dl.hidden = false;
    document.getElementById("first-report").hidden = false;
    document.getElementById("clear").hidden = false;
    const btn = iv.querySelector('button[type="submit"]');
    if (btn) btn.textContent = "Saved — " + p.name + "'s profile lives in this browser";
    document.getElementById("status").textContent =
      p.name + " is in this browser's vault (and downloadable). " +
      "Your next report will use it automatically — nothing is stored anywhere else. Switch anglers from the menu, top right.";
  });

  const clearBtn = document.getElementById("clear");
  if (getActive()) clearBtn.hidden = false;
  clearBtn.addEventListener("click", () => {
    forget(getActive().name);
    window.location.reload();
  });
}

migrateLegacy();
renderMenu();

// ── navigation progress ─────────────────────────────────────────────────────
// Some full-page renders (the 7-day outlook scan) take a moment. Show that a
// click registered immediately, so a slow render never reads as a dead link.
(function () {
  const bar = document.createElement("div");
  bar.className = "nav-progress";
  bar.setAttribute("aria-hidden", "true");
  document.body.appendChild(bar);
  let loading = false;
  const arm = () => {
    if (loading) return;
    loading = true;
    document.body.classList.add("is-loading");
  };
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest && ev.target.closest("a[href]");
    if (!a || a.target === "_blank" || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    const href = a.getAttribute("href") || "";
    if (!href || href.charAt(0) === "#" || /^(mailto|tel):/.test(href)) return;
    try { if (new URL(a.href, location.href).origin !== location.origin) return; } catch { return; }
    arm();
  });
  document.addEventListener("submit", (ev) => { if (!ev.defaultPrevented) arm(); });
  window.addEventListener("pageshow", () => {
    loading = false;
    document.body.classList.remove("is-loading");
  });
})();

// ── field mode: print the report as a pocket card ───────────────────────────
const printCard = document.getElementById("print-card");
if (printCard) printCard.addEventListener("click", (ev) => {
  ev.preventDefault();
  window.print();
});

// ── PWA install affordance ──────────────────────────────────────────────────
// Chrome's native prompt can be dismissed and then goes quiet; this keeps a
// button in the footer so install is always findable. iOS has no prompt event,
// so the button shows the Share-sheet instruction instead.
(function () {
  const btn = document.getElementById("install-app");
  const hint = document.getElementById("install-hint");
  if (!btn) return;
  if (window.matchMedia("(display-mode: standalone)").matches || navigator.standalone) return;
  let deferred = null;
  const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  window.addEventListener("beforeinstallprompt", (ev) => {
    ev.preventDefault();
    deferred = ev;
    btn.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    btn.hidden = true;
    if (hint) hint.hidden = true;
  });
  // always offer it: Chrome may suppress its own prompt after a dismissal,
  // and iOS has no prompt event at all — the click falls back to instructions
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    if (deferred) {
      deferred.prompt();
      try { await deferred.userChoice; } catch (e) { /* dismissed */ }
      deferred = null;
      btn.hidden = true;
      return;
    }
    if (hint) {
      hint.textContent = isIOS
        ? "tap Share, then “Add to Home Screen”."
        : "open your browser menu, then “Install app” / “Add to Home screen”.";
      hint.hidden = false;
    }
  });
})();

// ── field-mode log queue (public site / phone) ─────────────────────────────
// The server never receives these entries: they live in this browser until the
// angler exports the JSON and imports it on the local machine's /log page.
(function () {
  const form = document.getElementById("log-form");
  if (!form || form.dataset.mode !== "field") return;
  const KEY = "fishwitch_log_queue";
  const count = document.getElementById("queue-count");
  const table = document.getElementById("queue-table");
  const tbody = table && table.querySelector("tbody");
  const ex = document.getElementById("queue-export");
  const clr = document.getElementById("queue-clear");
  const flash = document.getElementById("queue-flash");
  const read = () => {
    try { const q = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(q) ? q : []; }
    catch { return []; }
  };
  const write = (q) => localStorage.setItem(KEY, JSON.stringify(q));
  function render() {
    const q = read();
    if (count) count.textContent = q.length
      ? q.length + " queued — export before you leave the water" : "nothing queued yet";
    if (table) table.hidden = !q.length;
    if (tbody) tbody.innerHTML = q.slice().reverse().map(e => "<tr><td>" + esc(e.ts || "")
      + "</td><td>" + esc(e.angler || "") + "</td><td>" + esc(e.lake || "") + "</td><td>"
      + (e.result === "skunk" ? "skunk"
         : esc(e.lure || "?") + (e.length ? " (" + esc(e.length) + ")" : "")) + "</td></tr>").join("");
    if (ex) ex.hidden = !q.length;
    if (clr) clr.hidden = !q.length;
    form.querySelectorAll('input[name="length"], input[name="lure"], input[name="notes"]')
      .forEach(i => { i.value = ""; });
    const sk = form.querySelector('input[name="skunk"]');
    if (sk) sk.checked = false;
  }
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const date = f.get("date") || new Date().toISOString().slice(0, 10);
    const time = f.get("time") || "18:00";
    const skunk = f.get("skunk") === "on";
    let length = (f.get("length") || "").trim();
    if (/^\d+(\.\d+)?$/.test(length)) length += "lb";
    const sel = form.querySelector('select[name="lake"]');
    const entry = {
      angler: (f.get("angler") || "Angler").trim(),
      lake: sel ? sel.options[sel.selectedIndex].text : (f.get("lake") || ""),
      species: skunk ? "bass" : ((f.get("species") || "bass").trim()),
      lure: skunk ? "" : (f.get("lure") || "").trim(),
      length: skunk ? "" : length,
      notes: (f.get("notes") || "").trim(),
      result: skunk ? "skunk" : "catch",
      ts: date + "T" + time,
    };
    const q = read(); q.push(entry); write(q);
    render();
    if (flash) flash.textContent = "✅ added to the queue — log the next one, or export when you're done.";
  });
  if (ex) ex.addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(read(), null, 2)], { type: "application/json" }));
    a.download = "baromoon-field-log-" + new Date().toISOString().slice(0, 10) + ".json";
    a.click(); URL.revokeObjectURL(a.href);
  });
  if (clr) clr.addEventListener("click", () => {
    if (confirm("Clear the " + read().length + " queued entries? Export first if you haven't.")) {
      write([]); render();
    }
  });
  render();
})();

// ── theme pair: first-light / crisp-dark (system-aware, manual override) ────
(function () {
  const root = document.documentElement;
  const KEY = "bm-theme-v2";
  const COLORS = { "first-light": "#f7f5ef", "crisp-dark": "#0a0f12", "loam": "#10140d", "almanac": "#f3eddc" };
  const systemTheme = () => (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches)
    ? "crisp-dark" : "first-light";
  const paint = (t) => {
    root.dataset.theme = t;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta && COLORS[t]) meta.setAttribute("content", COLORS[t]);
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.setAttribute("aria-label",
      t === "crisp-dark" ? "Switch to light theme" : "Switch to dark theme");
    window.dispatchEvent(new CustomEvent("bm:theme", { detail: { theme: t } }));
  };
  const btn = document.getElementById("theme-toggle");
  if (btn) btn.addEventListener("click", () => {
    const t = root.dataset.theme === "crisp-dark" ? "first-light" : "crisp-dark";
    try { localStorage.setItem(KEY, t); } catch (e) {}
    paint(t);
  });
  if (window.matchMedia) {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e) => {
      let chosen = null;
      try { chosen = localStorage.getItem(KEY); } catch (err) {}
      if (!chosen || chosen === "system") paint(e.matches ? "crisp-dark" : "first-light");
    };
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }
})();
