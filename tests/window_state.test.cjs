const assert = require('node:assert/strict');
const {addCalendarDays, buildAvailability, WindowRequests, personalTimingLabel, compareSessions} = require('../web/static/window.js');

assert.equal(addCalendarDays('2026-12-31', 1), '2027-01-01');
assert.equal(addCalendarDays('2028-02-28', 1), '2028-02-29');
assert.equal(buildAvailability('2026-10-23', '2026-10-25', '06:00', '20:00').length, 3);
assert.deepEqual(buildAvailability('2026-10-23', '2026-10-23', '22:00', '03:00'),
                 [{start:'2026-10-23T22:00', end:'2026-10-24T03:00'}]);
assert.throws(() => buildAvailability('2026-10-23', '2026-10-30', '06:00', '20:00'));
assert.throws(() => buildAvailability('', '', '06:00', '20:00'));
assert.throws(() => buildAvailability('2026-10-25', '2026-10-23', '06:00', '20:00'));
const state = new WindowRequests();
const first = state.next(), second = state.next();
assert.equal(first.controller.signal.aborted, true);
assert.equal(state.current(first.sequence), false);
assert.equal(state.current(second.sequence), true);
state.next();
assert.equal(second.controller.signal.aborted, true);
const best = {personal_contribution:1, personal_events:[{contribution:1}],
  weather:{band:'calmer',gust_mph:8,precipitation_mm:0},
  shared:{major_overlap_seconds:120,minor_overlap_seconds:60}};
for (const [modify, reason] of [
  [row => {row.weather.band='less calm';row.personal_contribution=2;}, /calmer weather/],
  [row => {row.personal_contribution=0;row.shared.major_overlap_seconds=240;}, /chart contact weighs better/],
  [row => {row.shared.major_overlap_seconds=60;row.weather.gust_mph=7;}, /more of a major/],
  [row => {row.shared.minor_overlap_seconds=30;}, /more of a minor/],
  [row => {row.weather.gust_mph=8.001;}, /lower forecast gusts/],
  [row => {row.weather.precipitation_mm=0.001;}, /less forecast precipitation/],
  [row => {}, /starts earlier/],
]) {
  const other = structuredClone(best); modify(other);
  assert.match(compareSessions(best, other), reason);
}
assert.match(personalTimingLabel(best, false), /without your birth chart/);
assert.match(personalTimingLabel({...best,personal_events:[],personal_contribution:0}, true), /No exact chart contact/);
assert.match(personalTimingLabel(best, true), /favorable chart contact/);
assert.match(personalTimingLabel({...best,personal_contribution:-1,personal_events:[{contribution:-1}]}, true), /demanding chart contact/);
assert.match(personalTimingLabel({...best,personal_contribution:0,personal_events:[{contribution:-1},{contribution:1}]}, true), /easier and harder/);
const validRanges = [
  [['2026-10-24', '2026-10-30', '06:00', '20:00', '2026-10-24'], 7, '2026-10-30T20:00'],
  [['2026-10-30', '2026-10-30', '06:00', '20:00', '2026-10-24'], 1, '2026-10-30T20:00'],
  [['2026-12-29', '2027-01-04', '06:00', '20:00', '2026-12-29'], 7, '2027-01-04T20:00'],
  [['2026-11-01', '2026-11-07', '06:00', '20:00', '2026-11-01'], 7, '2026-11-07T20:00'],
  [['2026-10-24', '2026-10-30', '22:00', '00:00', '2026-10-24'], 7, '2026-10-31T00:00'],
  [['2026-10-24', '2026-10-29', '22:00', '03:00', '2026-10-24'], 6, '2026-10-30T03:00'],
];
for (const [args, count, end] of validRanges) {
  const rows = buildAvailability(...args);
  assert.equal(rows.length, count);
  assert.equal(rows.at(-1).end, end);
}
const invalidRanges = [
  [['2026-10-24', '2026-10-31', '06:00', '20:00', '2026-10-24'], 'last-date', /8 dates.*limit is 7/],
  [['2026-10-23', '2026-10-25', '06:00', '20:00', '2026-10-24'], 'first-date', /passed/],
  [['2026-10-31', '2026-10-31', '06:00', '20:00', '2026-10-24'], 'first-date', /beyond the forecast range/],
  [['2026-10-25', '2026-10-31', '06:00', '20:00', '2026-10-24'], 'last-date', /Forecasts currently end Fri, Oct 30/],
  [['2026-10-26', '2026-10-25', '06:00', '20:00', '2026-10-24'], 'last-date', /on or after the first/],
  [['2026-02-30', '2026-03-01', '06:00', '20:00'], 'first-date', /valid first date/],
  [['2026-02-28', '2026-02-30', '06:00', '20:00'], 'last-date', /valid last date/],
  [['2026-10-24', '2026-10-24', '24:00', '20:00'], 'from-time', /available-from/],
  [['2026-10-24', '2026-10-24', '06:00', '20:60'], 'until-time', /available-until/],
  [['2026-10-24', '2026-10-30', '22:00', '03:00', '2026-10-24'], 'until-time', /earlier last date or end at midnight/],
];
for (const [args, input, message] of invalidRanges) {
  assert.throws(() => buildAvailability(...args), error => error.input === input && message.test(error.message));
}
console.log(`20 existing window scenarios plus ${validRanges.length + invalidRanges.length} date-range scenarios passed`);
