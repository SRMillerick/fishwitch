/* Browser request-state regressions using Node's built-in VM; no DOM package. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/static/app.js'), 'utf8');
const reportSource = source.slice(source.indexOf('const form = document.getElementById("report-form")'),
                                 source.indexOf('\nfunction buildList('));

function page({profile = null, search = '', fields = {}} = {}) {
  const values = {date: '2026-10-25', time: '09:45', hours: '2', lake: 'synthetic', ...fields};
  const listeners = {};
  const out = {innerHTML: 'shared fixture', textContent: ''};
  const note = {textContent: ''};
  const pending = [];
  let url = '';
  const form = {
    addEventListener: (name, fn) => { listeners[name] = fn; },
    querySelector: () => ({value: values.date}),
    requestSubmit: () => listeners.submit({preventDefault() {}}),
  };
  const context = {
    document: {
      getElementById: id => ({'report-form': form, 'report-out': out, 'profile-note': note}[id] || null),
      querySelectorAll: () => [], querySelector: () => null,
    },
    FormData: class { get(key) { return values[key] ?? null; } },
    getActive: () => profile,
    localStorage: {setItem() {}},
    history: {replaceState: (_a, _b, next) => { url = next; }},
    location: {search}, URLSearchParams, AbortController,
    fetch: (_path, options) => new Promise(resolve => pending.push({options, resolve})),
    esc: String,
    renderTackle: () => '', renderTrends: () => '', renderShopping: () => '',
    renderGap: () => '', renderNext: () => '',
  };
  vm.runInNewContext(reportSource, context);
  return {out, note, values, pending, form, listeners, url: () => url};
}

const result = (html, personalized) => ({json: async () => ({html, personalized, lake: 'Synthetic', overall: 5})});

(async () => {
  const initial = page({profile: {name: 'Synthetic'}});
  assert.match(initial.note.textContent, /Shared-only/);
  assert.equal(initial.pending.length, 0);

  const linked = page({profile: {name: 'Synthetic'}, search: '?lake=synthetic&at=2026-10-25T09:45'});
  assert.equal(linked.pending.length, 1);
  assert.equal(JSON.parse(linked.pending[0].options.body).at, '2026-10-25 09:45');
  assert.doesNotMatch(linked.note.textContent, /Personal timing calculated/);
  linked.pending[0].resolve(result('personal fixture', true));
  await new Promise(resolve => setImmediate(resolve));
  assert.match(linked.note.textContent, /Personal timing calculated/);

  const shared = page({profile: {name: 'Synthetic', birth: {time_known: false}}});
  const submit = shared.form.requestSubmit();
  shared.pending[0].resolve(result('shared fixture', false));
  await submit;
  assert.match(shared.note.textContent, /Shared-only/);

  const pin = page({fields: {lake: null, lat: '0', lng: '2'}});
  const pinSubmit = pin.form.requestSubmit();
  const payload = JSON.parse(pin.pending[0].options.body);
  assert.equal(payload.lat, '0');
  assert.equal(payload.lng, '2');
  assert.match(pin.url(), /lat=0&lng=2/);
  assert.doesNotMatch(pin.url(), /birth|profile/);
  pin.pending[0].resolve(result('pin fixture', false));
  await pinSubmit;

  const race = page();
  const first = race.form.requestSubmit();
  race.values.time = '12:00';
  const second = race.form.requestSubmit();
  assert.equal(race.pending[0].options.signal.aborted, true);
  race.pending[1].resolve(result('NEW selection', false));
  await second;
  race.pending[0].resolve(result('OLD selection', true));
  await first;
  assert.match(race.out.innerHTML, /NEW selection/);
  assert.doesNotMatch(race.out.innerHTML, /OLD selection/);
  assert.match(race.note.textContent, /Shared-only/);

  const edit = page();
  const outdated = edit.form.requestSubmit();
  edit.listeners.input();
  assert.equal(edit.pending[0].options.signal.aborted, true);
  edit.pending[0].resolve(result('STALE result', true));
  await outdated;
  assert.doesNotMatch(edit.out.innerHTML, /STALE result/);
  assert.match(edit.note.textContent, /No result/);

  const failed = page();
  const failure = failed.form.requestSubmit();
  failed.pending[0].resolve({json: async () => ({error: 'invalid availability'})});
  await failure;
  assert.match(failed.note.textContent, /No result/);
  assert.match(failed.out.innerHTML, /invalid availability/);

  const missing = page({fields: {date: ''}});
  await missing.form.requestSubmit();
  assert.equal(missing.pending.length, 0);
  assert.match(missing.out.textContent, /Choose your available date/);
  console.log('8 report-state scenarios passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
