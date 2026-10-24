"use strict";

// Calendar arithmetic is independent of the browser's timezone. The server
// resolves every selected clock time in the water's historical IANA timezone.
function addCalendarDays(value, count) {
  const day = new Date(value + "T12:00:00Z");
  day.setUTCDate(day.getUTCDate() + count);
  return day.toISOString().slice(0, 10);
}

function calendarLabel(value) {
  return new Intl.DateTimeFormat("en-US", {timeZone:"UTC", weekday:"short", month:"short", day:"numeric"})
    .format(new Date(value + "T12:00:00Z"));
}

function isCalendarDay(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const day = new Date(value + "T12:00:00Z");
  return !Number.isNaN(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

function availabilityError(input, message) {
  const error = new Error(message); error.input = input;
  return error;
}

function buildAvailability(first, last, from, until, today = null) {
  if (!isCalendarDay(first)) throw availabilityError("first-date", "Choose a valid first date.");
  if (!isCalendarDay(last)) throw availabilityError("last-date", "Choose a valid last date.");
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(from)) throw availabilityError("from-time", "Choose a valid available-from time.");
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(until)) throw availabilityError("until-time", "Choose a valid available-until time.");
  if (last < first) throw availabilityError("last-date", "The last date must be on or after the first date.");
  const latest = today ? addCalendarDays(today, 6) : addCalendarDays(first, 6);
  if (today && first < today) throw availabilityError("first-date", `That first date has passed at this water. Choose ${calendarLabel(today)} or later, through ${calendarLabel(latest)}.`);
  if (today && first > latest) throw availabilityError("first-date", `The first date is beyond the forecast range. Choose ${calendarLabel(today)} through ${calendarLabel(latest)}.`);
  const count = Math.round((Date.parse(last + "T12:00:00Z") - Date.parse(first + "T12:00:00Z")) / 86400000) + 1;
  if (count > 7) throw availabilityError("last-date", `That range includes ${count} dates. The limit is 7, counting both the first and last date. Choose a last date no later than ${calendarLabel(latest)}.`);
  if (today && last > latest) throw availabilityError("last-date", `Forecasts currently end ${calendarLabel(latest)}. Set the last date to ${calendarLabel(latest)} or earlier; the seven forecast dates include today.`);
  if (today && last === latest && until <= from && until !== "00:00") {
    throw availabilityError("until-time", `On ${calendarLabel(latest)}, these hours run into the next day, beyond the forecast range. Choose an earlier last date or end at midnight (00:00).`);
  }
  const rows = [];
  for (let day = first; day <= last; day = addCalendarDays(day, 1)) {
    rows.push({start: day + "T" + from,
               end: (until <= from ? addCalendarDays(day, 1) : day) + "T" + until});
  }
  return rows;
}

class WindowRequests {
  constructor() { this.sequence = 0; this.controller = null; }
  next() {
    if (this.controller) this.controller.abort();
    this.controller = new AbortController();
    return {sequence: ++this.sequence, controller: this.controller};
  }
  current(sequence) { return sequence === this.sequence; }
}

function personalTimingLabel(row, personalized) {
  if (!personalized) return "Shared timing; no birth chart input.";
  if (!row.personal_events.length) return "No selected personal timing event.";
  const mixed = row.personal_events.some(event => event.contribution > 0) && row.personal_events.some(event => event.contribution < 0);
  if (mixed) return "Mixed personal timing: supportive and challenging alignments.";
  return row.personal_contribution > 0 ? "Supportive personal timing." : "Challenging personal timing.";
}

// Describe the first actual ranking distinction. Display rounding must never
// invent a tie or substitute a different explanation for the engine's decision.
function compareSessions(best, other) {
  if (best.weather.band !== other.weather.band) return "It has calmer weather; weather takes priority over chart timing.";
  if (best.personal_contribution !== other.personal_contribution) return "It has a higher personal timing contribution in similar weather.";
  if (best.shared.major_overlap_seconds !== other.shared.major_overlap_seconds) return "It overlaps more of a major Moon window after personal timing ties.";
  if (best.shared.minor_overlap_seconds !== other.shared.minor_overlap_seconds) return "It overlaps more of a minor Moon window after the preceding timing factors tie.";
  if (best.weather.gust_mph !== other.weather.gust_mph) return "The timing factors tie; it has lower forecast gusts.";
  if (best.weather.precipitation_mm !== other.weather.precipitation_mm) return "Timing and gusts tie; it has less forecast precipitation.";
  return "The other factors tie; it starts earlier.";
}

if (typeof module !== "undefined") module.exports = {addCalendarDays, buildAvailability, WindowRequests, personalTimingLabel, compareSessions};

if (typeof document !== "undefined") (function () {
  const $ = id => document.getElementById(id);
  const form = $("window-form");
  if (!form) return;
  const KEY = "baromoon-window-v1";
  const requests = new WindowRequests();
  let place = null;
  let places = [];
  let placeSequence = 0;
  let placeController = null;
  let placeTimer = null;
  let placePending = null;
  let placeQuery = "";
  let activePlace = -1;
  let legacy = null;
  let restoring = true;

  function read(storage, key) { try { return JSON.parse(storage.getItem(key) || "null"); } catch { return null; } }
  function waterZone() { return $("water").selectedOptions[0]?.dataset.tz || null; }
  function waterNow() {
    const zone = waterZone();
    if (!zone) return null;
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {timeZone:zone,
      year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23"})
      .formatToParts(new Date()).map(p => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }
  function precision() { return form.querySelector('input[name="precision"]:checked').value; }
  function birthFields() {
    const known = precision() === "known";
    $("birth-fields").hidden = !known;
    $("shared-hint").hidden = known;
    $("birth-fields").querySelectorAll("input,button,select").forEach(input => { input.disabled = !known; });
    if (!known) cancelPlaces();
  }
  function clearErrors() {
    document.querySelectorAll(".error").forEach(node => { node.hidden = true; node.textContent = ""; });
    form.querySelectorAll("[aria-invalid]").forEach(node => node.removeAttribute("aria-invalid"));
  }
  function error(field, message, inputId = null, focus = true) {
    let name = field.replaceAll(".", "-").replaceAll("_", "-");
    if (name.startsWith("birth-") && !["birth-date", "birth-time"].includes(name)) name = "birth-place";
    if (["daylight", "duration"].includes(name)) name = "availability";
    const node = $("error-" + name) || $("error-request");
    node.textContent = message;
    node.hidden = false;
    $("setup").open = true;
    const group = node.closest("details.group");
    if (group) group.open = true;
    const input = inputId || ({"birth-date":"birth-date", "birth-time":"birth-time", "birth-place":"birth-place",
                    "water-id":"water", "availability":"first-date", "duration-minutes":"duration"})[name];
    if (input) $(input).setAttribute("aria-invalid", "true");
    if (focus) {
      if (input) $(input).focus();
      node.scrollIntoView({block:"nearest"});
    }
  }
  function capture() {
    return {version:1, precision:precision(), birthDate:$("birth-date").value, birthTime:$("birth-time").value,
      placeQuery:$("birth-place").value, place, water:$("water").value,
      first:$("first-date").value, last:$("last-date").value, from:$("from-time").value,
      until:$("until-time").value, duration:$("duration").value, daylight:$("daylight").checked,
      remember:$("remember").checked};
  }
  function save() {
    if (restoring) return;
    const data = JSON.stringify(capture());
    try {
      sessionStorage.setItem(KEY, data);
      if ($("remember").checked) localStorage.setItem(KEY, data);
      else localStorage.removeItem(KEY);
      $("storage-note").hidden = true;
    } catch {
      $("storage-note").textContent = "Device storage is unavailable. Keep this page open; your settings may not survive a refresh.";
      $("storage-note").hidden = false;
    }
  }
  function invalidate() {
    if (restoring) return;
    requests.next();
    $("result").hidden = true;
    document.body.classList.remove("has-result");
    $("result").removeAttribute("aria-busy");
    $("status").textContent = "Settings changed. Find your window to calculate this selection.";
    $("submit-window").disabled = false;
    $("submit-window").textContent = "Find my window";
    clearErrors();
    refreshAvailability();
    save();
  }
  function refreshAvailability(showErrors = true) {
    const today = waterNow()?.slice(0, 10);
    const latest = today ? addCalendarDays(today, 6) : null;
    $("forecast-dates").textContent = today
      ? `Available forecast dates: ${calendarLabel(today)} – ${calendarLabel(latest)}. Today counts as day 1; both the first and last date are included.`
      : "Choose a water to see the available forecast dates. Both the first and last date count toward the seven-day limit.";
    for (const id of ["first-date", "last-date"]) {
      if (today) { $(id).min = today; $(id).max = latest; }
      else { $(id).removeAttribute("min"); $(id).removeAttribute("max"); }
    }
    $("date-range-status").textContent = "";
    for (const id of ["first-date", "last-date", "from-time", "until-time"]) $(id).removeAttribute("aria-invalid");
    $("error-availability").hidden = true; $("error-availability").textContent = "";
    if (!["first-date", "last-date", "from-time", "until-time"].every(id => $(id).value)) return;
    try {
      const rows = buildAvailability($("first-date").value, $("last-date").value, $("from-time").value, $("until-time").value, today);
      $("date-range-status").textContent = `${rows.length} ${rows.length === 1 ? "date" : "dates"} selected.`;
    } catch (err) {
      if (showErrors) error("availability", err.message, err.input, false);
    }
  }
  function refreshWater() {
    const zone = waterZone();
    $("water-zone").textContent = zone ? "All trip times: " + zone : "All trip times use the water’s timezone.";
    if (!zone) {
      if ($("water").value) error("water_id", "This water needs a confirmed timezone. Choose another listed water.");
      refreshAvailability(false);
      return;
    }
    const today = waterNow().slice(0, 10);
    if (!$("first-date").value) $("first-date").value = today;
    if (!$("last-date").value) $("last-date").value = addCalendarDays(today, 2);
    refreshAvailability(!restoring);
  }
  function restore(data) {
    if (!data || data.version !== 1) return false;
    const radio = form.querySelector(`input[name="precision"][value="${["known", "unknown", "none"].includes(data.precision) ? data.precision : "none"}"]`);
    radio.checked = true;
    for (const [id, key] of [["birth-date","birthDate"], ["birth-time","birthTime"], ["birth-place","placeQuery"],
      ["water","water"], ["first-date","first"], ["last-date","last"], ["from-time","from"], ["until-time","until"], ["duration","duration"]]) {
      if (typeof data[key] === "string") $(id).value = data[key];
    }
    place = data.place && typeof data.place === "object" ? data.place : null;
    $("place-confirmed").textContent = place ? "Confirmed: " + place.label + " · " + place.tz : "";
    $("daylight").checked = data.daylight !== false;
    $("remember").checked = data.remember === true;
    $("birth-group").open = false;
    $("water-group").open = false;
    return true;
  }
  function append(parent, tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    parent.append(node);
    return node;
  }
  function tripLabel(row, zone) {
    const start = new Date(row.start), end = new Date(row.end);
    const day = new Intl.DateTimeFormat("en-US", {timeZone:zone, weekday:"long", month:"short", day:"numeric"});
    const clock = new Intl.DateTimeFormat("en-US", {timeZone:zone, hour:"numeric", minute:"2-digit", timeZoneName:"short"});
    const endDay = day.format(start) !== day.format(end) ? day.format(end) + " · " : "";
    return `${day.format(start)} · ${clock.format(start)} – ${endDay}${clock.format(end)}`;
  }
  function localClock(value, zone) {
    return new Intl.DateTimeFormat("en-US", {timeZone:zone, hour:"numeric", minute:"2-digit", timeZoneName:"short"}).format(new Date(value));
  }
  function weatherLabel(row) {
    const wx = row.weather;
    const wind = `Wind up to ${Math.round(wx.wind_mph)} mph, gusting to ${Math.round(wx.gust_mph)} mph`;
    const rain = wx.precipitation_mm === 0 ? "no precipitation forecast" : wx.precipitation_mm < 0.1
      ? "a trace of precipitation forecast" : `about ${wx.precipitation_mm.toFixed(1)} mm of precipitation forecast`;
    return `${wind}; ${rain}.`;
  }
  function sharedSummary(row, zone) {
    const kind = row.shared.major_overlap_seconds > 0 ? "major" : "minor";
    const events = row.shared.events.filter(event => event.kind === kind);
    if (!events.length) return "";
    return `It overlaps a local Moon window around ${localClock(events[0].exact, zone)}.`;
  }
  function render(data) {
    const result = $("result"), row = data.recommended;
    const zone = data.water.timezone;
    result.hidden = false;
    document.body.classList.toggle("has-result", !!row);
    $("result-water").textContent = data.water.name;
    $("result-reason").textContent = data.reason + (row && !row.personal_events.length ? " " + sharedSummary(row, zone) : "");
    $("result-mode").textContent = row ? (data.personalized ? "Birth chart checked" : "Shared local almanac") : "No recommendation yet";
    $("result-day").textContent = row ? new Intl.DateTimeFormat("en-US", {timeZone:zone, weekday:"long", month:"short", day:"numeric"}).format(new Date(row.start)) : "Try different availability.";
    $("result-time").textContent = row ? tripLabel(row, zone).split(" · ").slice(1).join(" · ") : "";
    $("result-duration").textContent = row ? `${(new Date(row.end) - new Date(row.start)) / 3600000}-hour session${$("daylight").checked ? " · daylight only" : ""}` : "";
    $("result-weather").textContent = row ? weatherLabel(row) : "";
    $("result-updated").textContent = data.weather_acquired_at
      ? "Forecast updated " + new Intl.DateTimeFormat("en-US", {timeZone:zone, month:"short", day:"numeric", hour:"numeric", minute:"2-digit", timeZoneName:"short"}).format(new Date(data.weather_acquired_at))
      : "Current weather unavailable.";
    const why = $("why-content"); why.replaceChildren();
    if (row) {
      if (!row.personal_events.length) append(why, "p", data.personalized
        ? "No exact personal alignment falls inside this session. Your birth chart was checked; it adds no timing advantage here."
        : "This uses the local almanac, without birth chart timing.");
      for (const event of row.personal_events) {
        append(why, "p", event.explanation);
      }
      for (const event of row.shared.events) append(why, "p", `${event.kind === "major" ? "Major" : "Minor"} Moon window: ${localClock(event.start, zone)} – ${localClock(event.end, zone)}, centered on ${localClock(event.exact, zone)}.`);
      if (row.shared.events.length) append(why, "p", "These Moon windows are shared by everyone at this water. Major windows surround the Moon’s upper or lower meridian passage; minor windows surround moonrise or moonset.", "hint");
      append(why, "p", `Compared sessions within your selected dates and hours. Weather comes first, then your birth chart timing, shared Moon windows, gusts, rainfall, and earlier start.`, "hint");
    }
    for (const limitation of data.limitations || []) {
      if (!limitation.startsWith("Astrological interpretation") && !limitation.startsWith("Shared local almanac only") && !limitation.startsWith("Birth time unknown")) append(why, "p", limitation, "hint");
    }
    const calculation = $("calculation-content"); calculation.replaceChildren();
    $("calculation-details").hidden = !row;
    append(calculation, "p", `Rules ${data.rule_version} · calculation ${data.calculation_version}.`);
    if (row) append(calculation, "pre", JSON.stringify({weather_band:row.weather.band, personal_contribution:row.personal_contribution,
      personal_events:row.personal_events, shared:row.shared, environment:data.environment}, null, 2));
    const other = $("other-content"); other.replaceChildren();
    for (const alternative of data.alternatives || []) {
      const div = document.createElement("div"); div.className = "alternative";
      append(div, "p", tripLabel(alternative, data.water.timezone));
      append(div, "p", personalTimingLabel(alternative, data.personalized), "personal-comparison");
      for (const event of alternative.personal_events) append(div, "p", event.explanation, "hint");
      append(div, "p", "Why the recommended window leads: " + compareSessions(row, alternative), "hint");
      append(div, "p", weatherLabel(alternative), "hint"); other.append(div);
    }
    if (row && data.alternatives.length) {
      const lead = document.createElement("div"); lead.className = "alternative";
      append(lead, "p", "Recommended · " + tripLabel(row, zone));
      append(lead, "p", personalTimingLabel(row, data.personalized), "personal-comparison");
      append(lead, "p", "Alternatives below are ordered by the same weather and timing rules.", "hint");
      other.prepend(lead);
    }
    $("other").hidden = !row;
    if (row && !data.alternatives.length) append(other, "p", "No separate alternative session fits this availability.");
    if (row) {
      $("setup").open = false;
      $("birth-summary").textContent = data.personalized ? "Birth details confirmed · Edit" : "Shared-only timing · Edit";
      $("water-summary").textContent = data.water.name + " · Edit";
      $("setup-summary").textContent = data.water.name + " · " + ($("daylight").checked ? "daylight · " : "") + $("duration").selectedOptions[0].textContent + " · Change";
      $("status").textContent = "";
    } else {
      $("setup").open = true;
      $("availability-group").open = true;
      $("status").textContent = "";
    }
  }

  function hidePlaces() {
    $("place-suggestions").hidden = true;
    $("birth-place").setAttribute("aria-expanded", "false");
    $("birth-place").removeAttribute("aria-activedescendant");
  }
  function cancelPlaces() {
    clearTimeout(placeTimer); ++placeSequence;
    if (placeController) placeController.abort();
    placePending = null; hidePlaces();
  }
  function highlightPlace(index) {
    activePlace = index;
    [...$("place-suggestions").children].forEach((node, i) => node.setAttribute("aria-selected", String(i === index)));
    const option = $("place-option-" + index);
    if (option) {
      $("birth-place").setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({block:"nearest"});
    }
  }
  function choosePlace(index) {
    const choice = places[index];
    if (!choice) return;
    place = {lat:choice.lat, lng:choice.lng, tz:choice.tz,
      label:[choice.name, choice.region, choice.country].filter(Boolean).join(", ")};
    $("birth-place").value = place.label;
    cancelPlaces();
    $("place-confirmed").textContent = "Selected: " + place.label;
    invalidate();
  }
  function showPlaces() {
    const list = $("place-suggestions"); list.replaceChildren();
    places.forEach((entry, index) => {
      const option = append(list, "li", [entry.name, entry.region, entry.country].filter(Boolean).join(", "));
      option.id = "place-option-" + index; option.setAttribute("role", "option");
      append(option, "small", entry.tz.replaceAll("_", " "));
      option.addEventListener("mousedown", event => event.preventDefault());
      option.addEventListener("click", () => choosePlace(index));
    });
    list.hidden = !places.length;
    $("birth-place").setAttribute("aria-expanded", String(places.length > 0));
    highlightPlace(places.length ? 0 : -1);
  }
  function lookupPlaces() {
    clearTimeout(placeTimer);
    const query = $("birth-place").value.trim();
    if (query.length < 2 || precision() !== "known" || place) return Promise.resolve();
    if (query === placeQuery && placePending) return placePending;
    if (query === placeQuery && places.length) { showPlaces(); return Promise.resolve(); }
    cancelPlaces();
    const sequence = placeSequence;
    const controller = new AbortController(); placeController = controller;
    placeQuery = query; places = [];
    const timer = setTimeout(() => controller.abort(), 8000);
    $("place-confirmed").textContent = "Finding matching places…";
    placePending = (async () => {
      try {
        const response = await fetch("/api/window/place", {method:"POST", headers:{"Content-Type":"application/json"},
          body:JSON.stringify({query}), signal:controller.signal, cache:"no-store"});
        const data = await response.json();
        if (sequence !== placeSequence) return;
        if (!response.ok) throw new Error("Place lookup unavailable");
        places = data.places;
        $("place-confirmed").textContent = places.length ? "Choose your city below, or press Enter for the first match." : "No match. Try the city name without a street or address.";
        if (document.activeElement === $("birth-place")) showPlaces();
      } catch {
        if (sequence === placeSequence) $("place-confirmed").textContent = "Place lookup unavailable. Edit the city name to try again, or continue without birth details.";
      } finally {
        clearTimeout(timer);
        if (sequence === placeSequence) placePending = null;
      }
    })();
    return placePending;
  }
  $("birth-place").addEventListener("focus", () => { if (!place) lookupPlaces(); });
  $("birth-place").addEventListener("blur", hidePlaces);
  $("birth-place").addEventListener("keydown", event => {
    if (event.key === "Escape") { cancelPlaces(); return; }
    if (event.key === "Enter" && !$("place-suggestions").hidden && activePlace >= 0) {
      event.preventDefault(); choosePlace(activePlace);
    } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      if ($("place-suggestions").hidden) lookupPlaces();
      else highlightPlace((activePlace + (event.key === "ArrowDown" ? 1 : places.length - 1)) % places.length);
    } else if (event.key === "Enter" && !place) {
      event.preventDefault(); lookupPlaces();
    }
  });
  form.addEventListener("input", event => {
    if (event.target.id === "birth-place") {
      place = null; cancelPlaces(); places = []; placeQuery = "";
      $("place-confirmed").textContent = "";
      if ($("birth-place").value.trim().length >= 2) placeTimer = setTimeout(lookupPlaces, 350);
    }
    birthFields(); invalidate();
  });
  form.addEventListener("change", event => {
    birthFields(); invalidate();
    if (event.target.id === "water") { refreshWater(); save(); }
  });
  form.addEventListener("submit", async event => {
    event.preventDefault(); clearErrors();
    const task = requests.next();
    $("result").hidden = true;
    if (!$("water").value) { error("water_id", "Choose a listed water first."); return; }
    refreshAvailability(false);
    let availability;
    try { availability = buildAvailability($("first-date").value, $("last-date").value, $("from-time").value, $("until-time").value, waterNow()?.slice(0, 10)); }
    catch (err) { error("availability", err.message, err.input); return; }
    let birth = null;
    if (precision() === "known") {
      if (!place) {
        error("birth.place", $("birth-place").value.trim() ? "Choose your city from the suggestions below the field." : "Enter your birthplace city or town.");
        lookupPlaces(); return;
      }
      birth = {date:$("birth-date").value, time:$("birth-time").value, time_known:true,
               place:place.label, lat:place.lat, lng:place.lng, tz:place.tz};
    } else if (precision() === "unknown") birth = {time_known:false};
    const requestId = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(task.sequence);
    const payload = {request_id:requestId, water_id:$("water").value, availability,
      duration_minutes:Number($("duration").value), daylight:$("daylight").checked, birth};
    save();
    $("submit-window").disabled = true; $("submit-window").textContent = "Calculating…";
    $("status").textContent = "Calculating this selection…";
    const timer = setTimeout(() => task.controller.abort(), 9500);
    try {
      const response = await fetch("/api/window", {method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload), signal:task.controller.signal, cache:"no-store"});
      const data = await response.json();
      if (!requests.current(task.sequence)) return;
      if (!response.ok) { error(data.field || "request", data.error || "Calculation unavailable. Try again shortly."); $("status").textContent = "No current result."; return; }
      if (data.request_id !== requestId) throw new Error("Superseded request");
      render(data);
    } catch (err) {
      if (!requests.current(task.sequence)) return;
      $("status").textContent = "No current result. The request timed out or the service is unavailable. Try again.";
      error("request", "Try again shortly; your settings are still here.");
    } finally {
      clearTimeout(timer);
      if (requests.current(task.sequence)) { $("submit-window").disabled = false; $("submit-window").textContent = "Find my window"; }
    }
  });

  $("use-legacy").addEventListener("click", () => {
    if (!legacy) return;
    const birth = legacy.birth || {};
    form.querySelector(`input[name="precision"][value="${birth.time_known === false ? "unknown" : "known"}"]`).checked = true;
    $("birth-date").value = birth.date || ""; $("birth-time").value = birth.time || "";
    $("birth-place").value = birth.place || "";
    place = birth.tz && birth.lat != null && birth.lng != null ? {label:birth.place || "Saved birthplace", lat:birth.lat, lng:birth.lng, tz:birth.tz} : null;
    $("place-confirmed").textContent = place ? "Using saved birthplace: " + place.label + " · " + place.tz : "Find and confirm your birthplace.";
    if (!$("water").value && legacy.home_lake) $("water").value = legacy.home_lake;
    refreshWater(); birthFields(); invalidate();
    $("use-legacy").hidden = true;
  });
  $("forget").addEventListener("click", () => { $("forget-confirm").hidden = false; $("confirm-forget").focus(); });
  $("cancel-forget").addEventListener("click", () => { $("forget-confirm").hidden = true; $("forget").focus(); });
  $("confirm-forget").addEventListener("click", () => {
    requests.next(); cancelPlaces(); places = []; placeQuery = "";
    try {
      sessionStorage.removeItem(KEY); localStorage.removeItem(KEY);
      const active = localStorage.getItem("fishwitch_active");
      const vault = read(localStorage, "fishwitch_profiles");
      if (active && vault && typeof vault === "object") { delete vault[active]; localStorage.setItem("fishwitch_profiles", JSON.stringify(vault)); }
      const single = read(localStorage, "fishwitch_profile");
      if (!active || !single || single.name === active) localStorage.removeItem("fishwitch_profile");
      localStorage.removeItem("fishwitch_active"); localStorage.removeItem("bm-lake-v1");
    } catch {}
    restoring = true; form.reset(); place = null; legacy = null;
    $("place-confirmed").textContent = "";
    $("result").hidden = true; $("forget-confirm").hidden = true; $("use-legacy").hidden = true;
    document.body.classList.remove("has-result");
    $("setup").open = true; $("birth-group").open = true; $("water-group").open = true;
    $("setup-summary").textContent = "Choose your water, birth details, and availability";
    $("birth-summary").textContent = "1. Your birth details"; $("water-summary").textContent = "2. Your water";
    $("water-zone").textContent = "All trip times use the water’s timezone.";
    $("submit-window").disabled = false; $("submit-window").textContent = "Find my window";
    clearErrors(); refreshAvailability(false); birthFields(); restoring = false;
    $("status").textContent = "Your active birth details and this page’s saved settings have been forgotten.";
  });

  let saved = null;
  try {
    saved = read(sessionStorage, KEY) || read(localStorage, KEY);
    const vault = read(localStorage, "fishwitch_profiles"), active = localStorage.getItem("fishwitch_active");
    legacy = vault && active ? vault[active] : read(localStorage, "fishwitch_profile");
  } catch {}
  const restored = restore(saved);
  if (!restored && $("water").dataset.selected) {
    $("water").value = $("water").dataset.selected;
    if (!$("water").value) error("water_id", "That water is unsupported. Choose a listed water.");
  }
  $("use-legacy").hidden = !legacy;
  refreshWater(); birthFields(); restoring = false;
  if (restored && waterZone()) {
    try {
      const rows = buildAvailability($("first-date").value, $("last-date").value, $("from-time").value, $("until-time").value, waterNow().slice(0, 10));
      if (rows.every(row => row.end <= waterNow())) {
        error("availability", "Your saved trip has passed. Choose new availability; your other settings are here.");
      } else { form.requestSubmit(); }
    } catch (err) { error("availability", err.message, err.input); }
  }
  // Update an existing legacy worker so its old homepage cache is retired.
  // This page does not install a service worker or cache personal results.
  if (typeof navigator !== "undefined" && navigator.serviceWorker) navigator.serviceWorker.getRegistration().then(reg => reg?.update()).catch(() => {});
})();
