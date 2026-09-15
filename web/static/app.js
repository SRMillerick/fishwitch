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
  if (p.astro_display !== undefined && !["fisher", "almanac", "astro"].includes(p.astro_display))
    return "astro_display: fisher | almanac | astro";
  return null;
}

const esc = s => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── header menu ─────────────────────────────────────────────────────────────
const menu = document.getElementById("profile-menu");

function renderMenu() {
  if (!menu) return;
  const v = vault(), active = localStorage.getItem(ACTIVE_KEY);
  const sum = menu.querySelector("summary");
  sum.textContent = (active && v[active]) ? "⚓ " + v[active].name
                 : (Object.keys(v).length ? "👤 profiles" : "👤 anonymous");
  const body = menu.querySelector(".menu-body");
  let h = "";
  for (const name of Object.keys(v)) {
    const on = name === active ? " on" : "";
    h += `<div class="mrow${on}" data-act="use" data-name="${esc(name)}">
            <span>${on ? "⚓ " : ""}${esc(name)}</span>
            <span class="micons">
              <a href="#" data-act="export" data-name="${esc(name)}" title="download profile.json">⤓</a>
              <a href="#" data-act="forget" data-name="${esc(name)}" title="forget this profile in this browser">✕</a>
            </span></div>`;
  }
  if (!Object.keys(v).length) h += `<div class="mhint">no profiles stored in this browser</div>`;
  h += `<div class="mrow" data-act="import">＋ import profile.json</div>`;
  if (active) h += `<div class="mrow" data-act="anon">🚫 browse anonymously</div>`;
  h += `<div class="mhint">profiles stay in this browser — never sent anywhere except to render your reports</div>`;
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
    else if (act === "export") {
      const p = vault()[name]; if (!p) return;
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(p, null, 2)], { type: "application/json" }));
      a.download = "fishwitch-profile-" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-") + ".json";
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
}

// ── report form: POST the active profile with the query ────────────────────
const form = document.getElementById("report-form");
if (form) {
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const date = f.get("date") || new Date().toISOString().slice(0, 10);
    const time = f.get("time") || "18:00";
    const payload = {
      lake: f.get("lake"), at: date + " " + time,
      hours: f.get("hours"), voice: f.get("voice"), species: f.get("species"),
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
        ? `Rendered with ${p.name}'s profile (transits + arsenal) — profile stays in this browser.`
        : "Rendering anonymously — pick or create a profile for transits + arsenal.";
      out.innerHTML =
        '<div class="scorebar">overall <strong>' + j.overall + "/10</strong> · " + esc(j.lake) + "</div>"
        + j.html + renderTackle(j.rods);
    } catch (e) {
      out.innerHTML = '<p class="error">render failed: ' + esc(String(e)) + "</p>";
    }
  });
}

function renderTackle(rods) {
  if (!rods || !rods.length) return "";
  let h = '<section class="tackle"><h2>Tackle for this session — sources & offers</h2>' +
    '<p class="fine">Ranking never sees these links. They attach after the pipe ends.</p><ul class="plain">';
  for (const r of rods) {
    h += "<li><span class='badge " + (r.verified ? "ok" : "pend") + "'>" +
      (r.verified ? "sourced" : "editorial") + "</span> <strong>" + esc(r.label) + "</strong>";
    if (r.product_url) h += " · <a href='" + r.product_url + "' target='_blank' rel='nofollow noopener'>" +
      esc(r.product || "manufacturer page") + "</a>";
    for (const o of (r.offers || [])) if (o.url)
      h += " · <a href='" + o.url + "' target='_blank' rel='sponsored noopener'>" + esc(o.retailer) +
        "</a> <span class='fine'>(" + esc(o.disclosure) + ")</span>";
    h += "<div class='fine'>" + esc(r.source) +
      (r.source_url ? " · <a href='" + r.source_url + "' target='_blank' rel='noopener'>source</a>" : "") + "</div></li>";
  }
  return h + "</ul></section>";
}

// ── interview: geocode + build profile + save into the vault ────────────────
const iv = document.getElementById("interview");
if (iv) {
  let picked = null;

  // prefill from the active profile (edit mode)
  const cur = getActive();
  if (cur) {
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
    iv.querySelector('[name="arsenal"]').value = (cur.arsenal || []).join(", ");
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
      box.textContent = "⚠ geocoding service unreachable — check the connection and try again";
    }
  });

  iv.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(iv);
    const unknown = f.get("time_unknown") === "on";
    const placeStr = (f.get("bplace") || "").trim();
    if (placeStr && !picked) {
      document.getElementById("status").textContent =
        "⚠ couldn’t geocode ‘" + placeStr + "’ — retype it (City, State, Country) and wait for the ✓ match before saving.";
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
      home_lake: f.get("home_lake"),
      astro_display: f.get("voice") || "almanac",
      created: new Date().toISOString(),
    };
    const err = profileError(p);
    if (err) { document.getElementById("status").textContent = "⚠ " + err; return; }
    saveProfile(p);
    renderMenu();
    const blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    const dl = document.getElementById("download");
    dl.href = URL.createObjectURL(blob); dl.hidden = false;
    document.getElementById("clear").hidden = false;
    const btn = iv.querySelector('button[type="submit"]');
    if (btn) btn.textContent = "✅ Saved — " + p.name + "'s profile lives in this browser";
    document.getElementById("status").textContent =
      "✅ " + p.name + "'s profile saved to this browser's vault (and downloadable). " +
      "It is sent only to render reports — never stored anywhere else. Switch anglers from the menu, top right.";
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
