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
    if (k === 'perHour' && typeof got === 'number') got = Math.round(got * 100) / 100;
    eq(c.name + ' / ' + k, got, c.expect[k]);
  });
});

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' shared-corpus checks passed (js)');
process.exit(bad ? 1 : 0);
