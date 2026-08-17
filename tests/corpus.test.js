/* Runs the shared corpus against the JavaScript parser, so it and the Python
   port on the Pi stay in agreement. Run with: node tests/corpus.test.js */
var P = require('../offer-parser.js');
var cases = require('./fixtures/cases.json');

var ok = 0, bad = 0;
function eq(name, got, want) {
  var good = (typeof want === 'number' && typeof got === 'number')
    ? Math.abs(got - want) < 0.001 : got === want;
  if (good) ok++; else { bad++; console.log('FAIL  ' + name + ': got ' + got + ' want ' + want); }
}

cases.parse.forEach(function (c) {
  var p = P.parse(c.text);
  Object.keys(c.expect).forEach(function (k) { eq(c.name + ' / ' + k, p[k], c.expect[k]); });
});

cases.rate.forEach(function (c) {
  var r = P.rate(P.parse(c.text), c.settings);
  Object.keys(c.expect).forEach(function (k) {
    var got = r[k];
    if (/PerHour$/i.test(k) && typeof got === 'number') got = Math.round(got * 100) / 100;
    eq(c.name + ' / ' + k, got, c.expect[k]);
  });
});

/* The three functions that decide what an offer is judged against.
   All three had drifted, and none of it was reachable from a test. */
function value(v) {
  if (v === '@inf') return Infinity;
  if (v === '@-inf') return -Infinity;
  if (v === '@nan') return NaN;
  return v;
}

(cases.coerce ? cases.coerce.toNumber : []).forEach(function (c) {
  eq('toNumber / ' + c.name, P.toNumber(value(c.in)), c.expect);
});

(cases.coerce ? cases.coerce.setting : []).forEach(function (c) {
  eq('setting / ' + c.name, P.setting(value(c.in), c.fallback), c.expect);
});

(cases.coerce && cases.coerce.round2 ? cases.coerce.round2 : []).forEach(function (c) {
  eq('round2 / ' + c.name, Math.round(value(c.in) * 100) / 100, c.expect);
});

(cases.coerce ? cases.coerce.doubt : []).forEach(function (c) {
  eq('doubt / ' + c.name,
     P.doubt(value(c.pay), value(c.minutes), value(c.miles)), c.expect);
});

/* Where an offer went, and the delivery deadline that stands in for a duration.
   Both are new shapes the reader had to learn from real DoorDash cards, and both
   are the kind of thing that drifts silently between two implementations. */
function sameList(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

(cases.places || []).forEach(function (c) {
  var got = P.parse(c.text).places;
  if (sameList(got, c.expect)) ok++;
  else { bad++; console.log('FAIL  places / ' + c.name + ': got ' + JSON.stringify(got)
                            + ' want ' + JSON.stringify(c.expect)); }
});

(cases.deadline || []).forEach(function (c) {
  eq('deadline / ' + c.name, P.parse(c.text).deliverBy, c.expect);
});

(cases.until || []).forEach(function (c) {
  eq('minutes left / ' + c.name, P.minutesUntil(c.deadline, c.now), c.expect);
});

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' shared-corpus checks passed (js)');
process.exit(bad ? 1 : 0);
