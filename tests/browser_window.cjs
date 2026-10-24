/* Real Chromium/CDP checks, using installed browser + Node only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const root = path.resolve(__dirname, '..');
const browserRoot = path.join(os.homedir(), '.cache/ms-playwright');
const browserFolder = fs.readdirSync(browserRoot).filter(name => /^chromium-\d+$/.test(name)).sort().at(-1);
const binary = process.env.BAROMOON_CHROME || path.join(browserRoot, browserFolder, 'chrome-linux64/chrome');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'baromoon-browser-'));
const python = process.env.BAROMOON_PYTHON || path.join(os.homedir(), '.astro-venv/bin/python');
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const server = spawn(python, ['tests/window_browser_server.py'], {cwd:root,
  env:{...process.env, PYTHONPATH:root + path.delimiter + path.dirname(root)}, stdio:['ignore','ignore','pipe']});
const browser = spawn(binary, ['--headless', '--no-sandbox', '--disable-gpu', '--disable-background-networking',
  '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=9223', '--user-data-dir=' + profile, 'about:blank'],
  {stdio:['ignore','ignore','pipe']});
let diagnostics = '';
server.stderr.on('data', data => { diagnostics += data.toString(); });
browser.stderr.on('data', data => { diagnostics += data.toString(); });
let socket;
let command = 0;
const pending = new Map();
const network = [], errors = [];
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++command;
  pending.set(id, {resolve, reject});
  socket.send(JSON.stringify({id, method, params}));
});
async function evaluate(expression) {
  const value = await send('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true});
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.text + ' ' + JSON.stringify(value.exceptionDetails.exception));
  return value.result.value;
}
async function until(expression, message, timeout = 5000) {
  for (let attempt = 0; attempt < timeout / 50; attempt++) {
    if (await evaluate(expression)) return;
    await pause(50);
  }
  throw new Error(message);
}
const change = (id, value) => evaluate(`(() => {const e=document.getElementById(${JSON.stringify(id)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
const click = id => evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
const submit = () => evaluate(`document.getElementById('window-form').requestSubmit()`);
const ready = () => until(`!document.getElementById('result').hidden && !document.getElementById('submit-window').disabled`, 'No result appeared');
async function load() {
  await send('Page.navigate', {url:'http://127.0.0.1:7781/'});
  await until(`typeof WindowRequests !== 'undefined' && !!document.getElementById('window-form')`, 'Page did not load');
}
async function control(data) {
  await evaluate(`fetch('/__fixture',{method:'POST',headers:{'Content-Type':'application/json'},body:${JSON.stringify(JSON.stringify(data))}}).then(r=>r.json())`);
}

(async () => {
  for (let attempt = 0; attempt < 100; attempt++) {
    try { await fetch('http://127.0.0.1:7781/'); await fetch('http://127.0.0.1:9223/json/version'); break; }
    catch { if (attempt === 99) throw new Error('Local test processes failed: ' + diagnostics); await pause(100); }
  }
  const targets = await (await fetch('http://127.0.0.1:9223/json/list')).json();
  const target = targets.find(value => value.type === 'page');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, {once:true}));
  socket.addEventListener('message', message => {
    const data = JSON.parse(message.data);
    if (data.id) {
      const item = pending.get(data.id); pending.delete(data.id);
      if (data.error) item.reject(new Error(data.error.message)); else item.resolve(data.result);
    }
    if (data.method === 'Network.requestWillBeSent') network.push(data.params.request);
    if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails);
  });
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await load();
  assert.equal(await evaluate(`document.getElementById('result').hidden`), true);
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, 0);
  await change('water', 'clear-lake');
  await change('birth-date', '1990-01-15'); await change('birth-time', '08:30');
  await evaluate(`document.getElementById('birth-place').focus()`);
  const lookupsBefore = network.filter(r => r.url.endsWith('/api/window/place')).length;
  await change('birth-place', 'S'); await change('birth-place', 'Sy');
  await change('birth-place', 'Synthetic City');
  await until(`!document.getElementById('place-suggestions').hidden`, 'Automatic place lookup failed');
  assert.equal(network.filter(r => r.url.endsWith('/api/window/place')).length, lookupsBefore + 1, 'Typing must debounce lookup requests');
  assert.equal(await evaluate(`document.getElementById('birth-place').getAttribute('aria-activedescendant')`), 'place-option-0');
  assert.equal(await evaluate(`document.activeElement.id`), 'birth-place');
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowDown', code:'ArrowDown', windowsVirtualKeyCode:40});
  assert.equal(await evaluate(`document.getElementById('birth-place').getAttribute('aria-activedescendant')`), 'place-option-1');
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'ArrowUp', code:'ArrowUp', windowsVirtualKeyCode:38});
  await submit();
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, 0, 'An ambiguous city must be confirmed');
  assert.equal(await evaluate(`document.getElementById('place-suggestions').hidden`), false);
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'Enter', code:'Enter', windowsVirtualKeyCode:13});
  await send('Input.dispatchKeyEvent', {type:'keyUp', key:'Enter', code:'Enter', windowsVirtualKeyCode:13});
  assert.equal(await evaluate(`document.getElementById('place-suggestions').hidden`), true);
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, 0, 'Choosing a place must not submit the form');
  await submit(); await ready();
  assert.equal(await evaluate(`document.getElementById('result-mode').textContent`), 'Birth chart checked');
  assert.equal(await evaluate(`document.getElementById('setup').open`), false);
  assert.equal(await evaluate(`localStorage.getItem('baromoon-window-v1')`), null);
  assert.equal(await evaluate(`JSON.parse(sessionStorage.getItem('baromoon-window-v1')).birthDate`), '1990-01-15');
  assert.match(await evaluate(`document.getElementById('result-day').textContent`), /\w+, \w+ \d+/);
  assert.match(await evaluate(`document.getElementById('result-time').textContent`), /PDT|PST/);
  assert.equal(await evaluate(`document.getElementById('why-content').textContent.includes('sha256')`), false);
  assert.equal(await evaluate(`document.getElementById('why-content').textContent.includes('Personal contribution:')`), false);
  assert.equal(await evaluate(`document.getElementById('calculation-details').open`), false);
  assert.equal(await evaluate(`document.body.classList.contains('has-result')`), true);
  assert.match(await evaluate(`document.getElementById('result-weather').textContent`), /no precipitation forecast/);
  await evaluate(`document.querySelector('#other > summary').click()`);
  assert.equal(await evaluate(`document.getElementById('other').open`), true);
  assert.match(await evaluate(`document.getElementById('other-content').innerText`), /Why the recommended window leads:/);
  assert.match(await evaluate(`document.getElementById('other-content').innerText`), /personal timing|personal alignment/i);
  assert.equal(await evaluate(`document.getElementById('other-content').innerText.includes('personal_contribution')`), false);
  await evaluate(`document.querySelector('#other > summary').click()`);
  console.log('first-use personal request, place confirmation, and session-only storage passed');

  await send('Emulation.setDeviceMetricsOverride', {width:375,height:900,deviceScaleFactor:1,mobile:true});
  await evaluate(`document.getElementById('setup').open=true;document.getElementById('availability-group').open=true`);
  const forecastFirst = await evaluate(`document.getElementById('first-date').min`);
  const forecastLast = await evaluate(`addCalendarDays(${JSON.stringify(forecastFirst)},6)`);
  const eighthDate = await evaluate(`addCalendarDays(${JSON.stringify(forecastFirst)},7)`);
  assert.equal(await evaluate(`document.getElementById('last-date').max`), forecastLast);
  assert.match(await evaluate(`document.getElementById('forecast-dates').textContent`), /Today counts as day 1.*first and last date/);
  await change('first-date', forecastFirst);
  await evaluate(`document.getElementById('last-date').focus()`);
  const rangeRequests = network.filter(r => r.url.endsWith('/api/window')).length;
  await change('last-date', eighthDate);
  assert.match(await evaluate(`document.getElementById('error-availability').textContent`), /8 dates.*limit is 7/);
  assert.equal(await evaluate(`document.activeElement.id`), 'last-date', 'Live feedback must not steal focus');
  assert.equal(await evaluate(`document.getElementById('last-date').value`), eighthDate, 'Do not silently clamp the chosen dates');
  assert.equal(await evaluate(`document.getElementById('last-date').getAttribute('aria-invalid')`), 'true');
  assert.equal(await evaluate(`document.getElementById('result').hidden`), true);
  await submit();
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, rangeRequests, 'Invalid dates must not reach the API');
  assert.equal(await evaluate(`document.activeElement.id`), 'last-date');
  assert.equal(await evaluate(`(() => {const r=document.getElementById('error-availability').getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;})()`), true, 'Date-range error must be visible on the phone');
  const rangeCapture = await send('Page.captureScreenshot', {format:'png'});
  fs.writeFileSync('/tmp/baromoon-date-range-error.png', Buffer.from(rangeCapture.data,'base64'));
  await change('last-date', forecastLast);
  assert.equal(await evaluate(`document.getElementById('error-availability').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('last-date').hasAttribute('aria-invalid')`), false);
  assert.equal(await evaluate(`document.getElementById('date-range-status').textContent`), '7 dates selected.');
  await submit(); await ready();
  assert.equal(JSON.parse(network.filter(r => r.url.endsWith('/api/window')).at(-1).postData).availability.length, 7, 'Exactly seven forecast dates must work');
  assert.equal(await evaluate(`document.getElementById('birth-date').value`), '1990-01-15');
  await evaluate(`document.getElementById('setup').open=true`);
  await change('first-date', await evaluate(`addCalendarDays(${JSON.stringify(forecastFirst)},1)`));
  await change('last-date', eighthDate);
  assert.match(await evaluate(`document.getElementById('error-availability').textContent`), /Forecasts currently end/);
  const horizonRequests = network.filter(r => r.url.endsWith('/api/window')).length;
  await submit();
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, horizonRequests, 'A later-starting seven-date range must still fit the forecast horizon');
  await change('first-date', forecastFirst); await change('last-date', forecastLast);
  await change('from-time', '22:00'); await change('until-time', '03:00');
  assert.match(await evaluate(`document.getElementById('error-availability').textContent`), /earlier last date or end at midnight/);
  await submit();
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, horizonRequests);
  assert.equal(await evaluate(`document.activeElement.id`), 'until-time');
  await change('until-time', '00:00');
  assert.equal(await evaluate(`document.getElementById('error-availability').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('date-range-status').textContent`), '7 dates selected.');
  await change('from-time', '06:00'); await change('until-time', '20:00');
  await change('last-date', await evaluate(`addCalendarDays(${JSON.stringify(forecastFirst)},2)`));
  await submit(); await ready();
  console.log('visible mobile date limits, inclusive seven-date success, overrun/overnight validation, and correction without re-entering birth details passed');

  await evaluate(`document.getElementById('setup').open=true;document.getElementById('birth-group').open=true;document.getElementById('birth-place').focus()`);
  await change('birth-place', 'Slow City');
  await until(`document.getElementById('place-confirmed').textContent.includes('Finding')`, 'Delayed lookup did not start');
  await change('birth-place', 'Synthetic City');
  await until(`!document.getElementById('place-suggestions').hidden`, 'Replacement lookup failed');
  await pause(900);
  assert.match(await evaluate(`document.getElementById('place-option-0').textContent`), /^Synthetic City/);
  await click('place-option-1');
  assert.equal(await evaluate(`JSON.parse(sessionStorage.getItem('baromoon-window-v1')).place.tz`), 'America/New_York');
  await change('birth-place', 'No Match');
  await until(`document.getElementById('place-confirmed').textContent.startsWith('No match')`, 'No-match state missing');
  assert.equal(await evaluate(`JSON.parse(sessionStorage.getItem('baromoon-window-v1')).place`), null);
  assert.equal(await evaluate(`document.getElementById('place-suggestions').hidden`), true);
  await change('birth-place', 'Synthetic City');
  await until(`!document.getElementById('place-suggestions').hidden`, 'Final lookup failed');
  await click('place-option-0'); await submit(); await ready();
  console.log('debounced suggestions, keyboard/click choices, ambiguity, stale lookups, and no-match state passed');

  await evaluate(`document.getElementById('setup').open=true;document.getElementById('water-group').open=true`);
  const trip = await evaluate(`document.getElementById('first-date').value`);
  await change('water', 'lake-berryessa');
  assert.equal(await evaluate(`document.getElementById('first-date').value`), trip);
  assert.equal(await evaluate(`document.getElementById('birth-date').value`), '1990-01-15');
  assert.equal(await evaluate(`document.getElementById('result').hidden`), true);
  await control({delay:true}); await submit();
  await change('water', 'clear-lake'); await submit(); await ready();
  await pause(1000);
  assert.match(await evaluate(`document.getElementById('setup-summary').textContent`), /Clear Lake/);
  console.log('edit preservation and superseded-response checks passed');

  await evaluate(`document.getElementById('setup').open=true`);
  await click('remember'); await load(); await ready();
  assert.equal(await evaluate(`document.getElementById('result-mode').textContent`), 'Birth chart checked');
  assert.equal(await evaluate(`JSON.parse(localStorage.getItem('baromoon-window-v1')).remember`), true);
  await evaluate(`(() => {const s=JSON.parse(localStorage.getItem('baromoon-window-v1'));s.first=${JSON.stringify(forecastFirst)};s.last=${JSON.stringify(eighthDate)};localStorage.setItem('baromoon-window-v1',JSON.stringify(s));sessionStorage.setItem('baromoon-window-v1',JSON.stringify(s));})()`);
  const invalidSavedRequests = network.filter(r => r.url.endsWith('/api/window')).length;
  await load(); await pause(200);
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, invalidSavedRequests);
  assert.equal(await evaluate(`document.getElementById('last-date').value`), eighthDate);
  assert.equal(await evaluate(`document.getElementById('error-availability').hidden`), false);
  assert.match(await evaluate(`document.getElementById('error-availability').textContent`), /8 dates.*limit is 7/);
  assert.equal(await evaluate(`document.activeElement.id`), 'last-date');
  await evaluate(`const s=JSON.parse(localStorage.getItem('baromoon-window-v1'));s.first='2020-01-01';s.last='2020-01-01';localStorage.setItem('baromoon-window-v1',JSON.stringify(s));sessionStorage.setItem('baromoon-window-v1',JSON.stringify(s));`);
  const before = network.filter(r => r.url.endsWith('/api/window')).length;
  await load(); await pause(200);
  assert.equal(network.filter(r => r.url.endsWith('/api/window')).length, before);
  assert.equal(await evaluate(`document.getElementById('first-date').value`), '2020-01-01');
  assert.equal(await evaluate(`document.getElementById('birth-date').value`), '1990-01-15');
  assert.match(await evaluate(`document.getElementById('error-availability').textContent`), /passed/);
  console.log('remembered return, invalid saved range, and expired-trip checks passed');

  await evaluate(`document.getElementById('birth-group').open=true;document.querySelector('input[name=precision][value=unknown]').click()`);
  assert.equal(await evaluate(`document.getElementById('shared-hint').hidden`), false);
  const current = await evaluate(`addCalendarDays(new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),1)`);
  await change('first-date', current); await change('last-date', current);
  await submit(); await ready();
  assert.equal(await evaluate(`document.getElementById('result-mode').textContent`), 'Shared local almanac');
  const lastRequest = network.filter(r => r.url.endsWith('/api/window')).at(-1);
  assert.deepEqual(JSON.parse(lastRequest.postData).birth, {time_known:false});
  await control({mode:'offline'}); await submit(); await ready();
  assert.equal(await evaluate(`document.getElementById('result-mode').textContent`), 'No recommendation yet');
  assert.match(await evaluate(`document.getElementById('result-reason').textContent`), /unavailable/);
  await control({mode:'storm'}); await submit(); await ready();
  assert.match(await evaluate(`document.getElementById('result-reason').textContent`), /exclusion/);
  await control({mode:'normal'});
  console.log('unknown-time, unavailable-weather, and exclusion states passed');

  for (const width of [320, 375, 768, 1280]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height:900, deviceScaleFactor:1, mobile:width < 500});
    assert.equal(await evaluate(`document.documentElement.scrollWidth <= innerWidth`), true, 'Horizontal overflow at ' + width);
  }
  await send('Emulation.setDeviceMetricsOverride', {width:375,height:900,deviceScaleFactor:1,mobile:true});
  await evaluate(`document.getElementById('setup').open=true;document.getElementById('birth-group').open=true;document.querySelector('input[name=precision][value=known]').click()`);
  await submit(); await ready();
  const resultCapture = await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:true});
  fs.writeFileSync('/tmp/baromoon-window-result.png', Buffer.from(resultCapture.data,'base64'));
  await evaluate(`document.getElementById('setup').open=true;document.getElementById('water-group').open=true;document.getElementById('water').focus()`);
  await send('Input.dispatchKeyEvent', {type:'keyDown', key:'Tab', code:'Tab', windowsVirtualKeyCode:9});
  await send('Input.dispatchKeyEvent', {type:'keyUp', key:'Tab', code:'Tab', windowsVirtualKeyCode:9});
  assert.notEqual(await evaluate(`document.activeElement.id`), 'water');
  const capture = await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:true});
  fs.writeFileSync('/tmp/baromoon-window-mobile.png', Buffer.from(capture.data,'base64'));
  console.log('keyboard focus and 320/375/768/1280px layouts passed');

  await control({delay:11});
  const deadlineStart = Date.now();
  await submit();
  await until(`document.getElementById('status').textContent.includes('timed out') && !document.getElementById('submit-window').disabled`, 'No definitive timeout state', 12000);
  assert.equal(await evaluate(`document.getElementById('result').hidden`), true);
  assert.ok(Date.now() - deadlineStart < 10500);
  console.log('9.5-second browser deadline returns an explicit state');

  await evaluate(`localStorage.setItem('fishwitch_active','synthetic');localStorage.setItem('fishwitch_profiles',JSON.stringify({synthetic:{birth:{}},other:{birth:{time_known:false}}}));`);
  await click('forget'); await click('confirm-forget');
  assert.equal(await evaluate(`localStorage.getItem('baromoon-window-v1')`), null);
  assert.equal(await evaluate(`sessionStorage.getItem('baromoon-window-v1')`), null);
  assert.deepEqual(await evaluate(`Object.keys(JSON.parse(localStorage.getItem('fishwitch_profiles')))`), ['other']);
  assert.equal(await evaluate(`document.getElementById('birth-date').value`), '');
  assert.equal(network.some(r => /https?:/.test(r.url) && !r.url.startsWith('http://127.0.0.1:7781/')), false);
  assert.equal(network.some(r => r.url.includes('1990-01-15')), false);
  assert.equal(errors.length, 0, 'Browser runtime errors: ' + JSON.stringify(errors));
  console.log('forget semantics, private URLs, and first-party-only requests passed');
  // Installed-client cutover: an existing v3-equivalent worker and stale caches
  // must update, purge old cached home/API data, and leave the profile vault alone.
  await control({legacy_sw:true});
  await evaluate(`navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'})`);
  await until(`!!navigator.serviceWorker.controller`, 'Old worker did not take control');
  await evaluate(`(async () => {const c=await caches.open('baromoon-v3');
    await c.put('/',new Response('synthetic stale homepage'));
    await c.put('/api/window',new Response('synthetic stale API'));
    localStorage.setItem('upgrade-sentinel','synthetic settings kept');})()`);
  await control({legacy_sw:false});
  await load(); // window.js explicitly requests the existing registration's update.
  await until(`caches.keys().then(keys=>!keys.includes('baromoon-v3'))`, 'Old caches were not purged', 10000);
  assert.equal(await evaluate(`localStorage.getItem('upgrade-sentinel')`), 'synthetic settings kept');
  assert.deepEqual(await evaluate(`Object.keys(JSON.parse(localStorage.getItem('fishwitch_profiles')))`), ['other']);
  assert.equal(await evaluate(`fetch('/api/window').then(r=>r.status)`), 405, 'Do not serve a cached API response');
  assert.deepEqual(await evaluate(`fetch('/api/window',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>[r.status,r.headers.get('Cache-Control')])`), [400,'no-store']);
  await load();
  assert.equal(await evaluate(`(async()=>{for(const name of await caches.keys()){
    for(const req of await (await caches.open(name)).keys()){
      const p=new URL(req.url).pathname;if(p==='/'||p.startsWith('/api/'))return true;
    }}return false;})()`), false, 'Home/API must not enter Cache Storage');
  await send('Network.emulateNetworkConditions', {offline:true, latency:0, downloadThroughput:-1, uploadThroughput:-1});
  const offlineNavigation = await send('Page.navigate',{url:'http://127.0.0.1:7781/?offline-upgrade-check=1'});
  assert.ok(offlineNavigation.errorText, 'Offline homepage must fail instead of replaying a cached forecast');
  await send('Network.emulateNetworkConditions', {offline:false, latency:0, downloadThroughput:-1, uploadThroughput:-1});
  await load();
  assert.equal(await evaluate(`localStorage.getItem('upgrade-sentinel')`), 'synthetic settings kept');
  console.log('installed v3→v4 worker upgrade, cache purge, offline behavior, and saved-data preservation passed');
  console.log('Real-browser window acceptance passed; screenshot /tmp/baromoon-window-mobile.png');
})().catch(async error => {
  console.error(error);
  try { console.error(await evaluate(`JSON.stringify({status:document.getElementById('status')?.textContent,errors:[...document.querySelectorAll('.error')].filter(e=>!e.hidden).map(e=>e.textContent)})`)); }
  catch {}
  console.error('Runtime exceptions:', JSON.stringify(errors));
  process.exitCode = 1;
}).finally(() => {
  if (socket) socket.close();
  browser.kill(); server.kill();
});
