/* fishwitch browser layer — profile custody + progressive enhancement.
   The server renders everything; this only (1) keeps the profile in
   localStorage, (2) upgrades form submits to fetch the personal render. */
"use strict";

const KEY = "fishwitch_profile";

function getProfile() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}

function chip() {
  const p = getProfile(), el = document.getElementById("profile-chip");
  if (!el) return;
  if (p && p.name) { el.hidden = false; el.textContent = "⚓ " + p.name; }
  else el.hidden = true;
}

/* ── report form: intercept submit, POST profile + fields, inject render ── */
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
      profile: getProfile() || undefined,
    };
    const out = document.getElementById("report-out");
    out.innerHTML = '<p class="fine">casting…</p>';
    try {
      const r = await fetch("/api/report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (j.error) { out.innerHTML = '<p class="error">' + j.error + "</p>"; return; }
      const note = document.getElementById("profile-note");
      if (getProfile()) note.textContent = "Rendered with your profile (transits + arsenal) — profile stays in this browser.";
      out.innerHTML =
        '<div class="scorebar">overall <strong>' + j.overall + "/10</strong> · " +
        j.lake + "</div>" + j.html + renderTackle(j.rods);
    } catch (e) {
      out.innerHTML = '<p class="error">render failed: ' + e + "</p>";
    }
  });
}

function renderTackle(rods) {
  if (!rods || !rods.length) return "";
  let h = '<section class="tackle"><h2>Tackle for this session — sources & offers</h2>' +
    '<p class="fine">Ranking never sees these links. They attach after the pipe ends.</p><ul class="plain">';
  for (const r of rods) {
    h += "<li><span class='badge " + (r.verified ? "ok" : "pend") + "'>" +
      (r.verified ? "sourced" : "editorial") + "</span> <strong>" + r.label + "</strong>";
    if (r.product_url) h += " · <a href='" + r.product_url + "' target='_blank' rel='nofollow noopener'>" +
      (r.product || "manufacturer page") + "</a>";
    for (const o of (r.offers || [])) if (o.url)
      h += " · <a href='" + o.url + "' target='_blank' rel='sponsored noopener'>" + o.retailer +
        "</a> <span class='fine'>(" + o.disclosure + ")</span>";
    h += "<div class='fine'>" + r.source +
      (r.source_url ? " · <a href='" + r.source_url + "' target='_blank' rel='noopener'>source</a>" : "") + "</div></li>";
  }
  return h + "</ul></section>";
}

/* ── interview: geocode + build profile + custody controls ── */
const iv = document.getElementById("interview");
if (iv) {
  const place = document.getElementById("bplace");
  let picked = null;
  place.addEventListener("change", async () => {
    picked = null;
    const box = document.getElementById("geocode-out");
    box.textContent = "looking up…";
    try {
      const r = await fetch("/api/geocode", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: place.value }),
      });
      const cands = await r.json();
      if (!cands.length) { box.textContent = "no geocode match — coordinates can be edited by hand in the JSON later"; return; }
      picked = cands[0];
      box.textContent = "→ " + [picked.name, picked.region, picked.country].filter(Boolean).join(", ") +
        "  (" + picked.lat.toFixed(3) + ", " + picked.lng.toFixed(3) + ", " + picked.tz + ")";
    } catch { box.textContent = "geocode failed"; }
  });

  iv.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = new FormData(iv);
    const unknown = f.get("time_unknown") === "on";
    const p = {
      name: f.get("name") || "friend",
      birth: {
        date: f.get("bdate"), time: unknown ? "12:00" : (f.get("btime") || "12:00"),
        time_known: !unknown, place: f.get("bplace"),
        lat: picked ? picked.lat : 0, lng: picked ? picked.lng : 0,
        tz: picked ? picked.tz : "UTC",
      },
      species: f.get("species") || "largemouth bass",
      arsenal: (f.get("arsenal") || "").split(",").map(s => s.trim()).filter(Boolean),
      home_lake: f.get("home_lake"),
      astro_display: f.get("voice") || "almanac",
      created: new Date().toISOString(),
    };
    localStorage.setItem(KEY, JSON.stringify(p));
    chip();
    const blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    const dl = document.getElementById("download");
    dl.href = URL.createObjectURL(blob); dl.hidden = false;
    document.getElementById("clear").hidden = false;
    document.getElementById("status").textContent =
      "✅ profile saved to this browser (and downloadable). It is sent only to render your reports — never stored server-side.";
  });

  const clearBtn = document.getElementById("clear");
  if (getProfile()) clearBtn.hidden = false;
  clearBtn.addEventListener("click", () => {
    localStorage.removeItem(KEY); chip();
    document.getElementById("status").textContent = "profile forgotten.";
  });
}

chip();
