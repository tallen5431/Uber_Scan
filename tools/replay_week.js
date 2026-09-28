/* The browser port's half of tools/replay_week.py. Not run on its own.
 *
 * Reads the rows replay_week.py already took apart — frames from the `scans`
 * column by JSON, never by splitting on "|" — on stdin, parses every frame and
 * the stored text through offer-parser.js with the row's own settings, and
 * writes the same summary the Python half builds, keyed by row number, to
 * stdout. One summary shape for both ports, so they can be compared field by
 * field.
 */

'use strict';

var OP = require('../offer-parser.js');

function summary(parsed, rate) {
  var perHour = rate.ready ? rate.perHour : null;
  return {
    pay: parsed.pay === undefined ? null : parsed.pay,
    minutes: parsed.minutes === undefined ? null : parsed.minutes,
    miles: parsed.miles === undefined ? null : parsed.miles,
    pickup: parsed.pickup === undefined ? null : parsed.pickup,
    dropoff: parsed.dropoff === undefined ? null : parsed.dropoff,
    places: (parsed.places || []).slice(),
    state: rate.state === undefined ? null : rate.state,
    perHour: perHour === undefined ? null : perHour,
    whole: parsed.pay ? OP.isWhole(parsed) : null,
    doubt: rate.doubt === undefined ? null : rate.doubt,
    untimedMiles: parsed.untimedMiles === undefined ? null : parsed.untimedMiles,
  };
}

function one(text, settings) {
  var parsed = OP.parse(text);
  return summary(parsed, OP.rate(parsed, settings));
}

var input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', function (chunk) { input += chunk; });
process.stdin.on('end', function () {
  var rows = JSON.parse(input), out = {};
  rows.forEach(function (r) {
    out[r.row] = {
      frames: r.frames.map(function (f) { return one(f, r.settings); }),
      text: one(r.text, r.settings),
    };
  });
  process.stdout.write(JSON.stringify(out));
});
