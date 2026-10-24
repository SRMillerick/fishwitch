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
  [row => {row.personal_contribution=0;row.shared.major_overlap_seconds=240;}, /higher personal timing/],
  [row => {row.shared.major_overlap_seconds=60;row.weather.gust_mph=7;}, /more of a major/],
  [row => {row.shared.minor_overlap_seconds=30;}, /more of a minor/],
  [row => {row.weather.gust_mph=8.001;}, /lower forecast gusts/],
  [row => {row.weather.precipitation_mm=0.001;}, /less forecast precipitation/],
  [row => {}, /starts earlier/],
]) {
  const other = structuredClone(best); modify(other);
  assert.match(compareSessions(best, other), reason);
}
assert.match(personalTimingLabel(best, false), /no birth chart input/);
assert.match(personalTimingLabel({...best,personal_events:[],personal_contribution:0}, true), /No selected/);
assert.match(personalTimingLabel(best, true), /Supportive/);
assert.match(personalTimingLabel({...best,personal_contribution:-1,personal_events:[{contribution:-1}]}, true), /Challenging/);
assert.match(personalTimingLabel({...best,personal_contribution:0,personal_events:[{contribution:-1},{contribution:1}]}, true), /Mixed/);
console.log('20 window calendar, request-state, and comparison scenarios passed');
