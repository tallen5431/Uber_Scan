/* What the journal already knows about where the work happened.
 *
 *   node tools/measure_places.js http://localhost:8080
 *   node tools/measure_places.js saved.json --json
 *
 * This decides a feature rather than implementing one. The question is whether
 * the rig could say how far apart two jobs are — the one thing the stacking
 * advice deliberately refuses to guess at today — and there are three ways to
 * answer it, at wildly different prices:
 *
 *   A. a street index built from an OpenStreetMap extract, on the Pi
 *   B. an online geocoder, which needs signal at the moment the card is up and
 *      sends a customer's address off the rig
 *   C. a table of the driver's own measured legs, built from the journal
 *
 * Which one is worth building is a fact about this driver's cards, not a matter
 * of taste, and every input to it is already on disk. So it is measured before
 * anything is built, against the rows the offers page actually sees.
 *
 * It reads through /api/journal rather than the file, deliberately: the server
 * already decides which reading of a card to believe, which rows are hidden and
 * which ticks apply. A second implementation of that here would answer a
 * question about a journal nobody looks at.
 *
 * Nothing is written. It is safe to run against the copy at home.
 */

'use strict';

var A = require('../advice.js');

/* --- what shape is this place? -------------------------------------------
 *
 * Not one of the places on these cards is a house-numbered street address, and
 * that is the single fact that decides between a street index and a geocoder.
 * An intersection of two named streets can be looked up and, when the reading
 * is damaged, can FAIL to be looked up — the streets simply do not cross. A
 * geocoder handed the same damage returns somewhere confident and wrong.
 *
 * So the shapes are counted rather than assumed, on this driver's own cards.
 */
var JUNCTION = /[A-Za-z]{3}.*\s&\s.*[A-Za-z]{3}/;
var BRACKETED = /\(.*\)/;
var STREET_WORD =
  /\b(?:Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Blvd|Pkwy|Hwy|St|Street|Ter|Trl|Pl|Way|Ave|Avenue|Cir|Run|Pt|Sq)\b/i;
// A number at the front is a door number: "925 Shiloh Rd Nw". These are the
// only places a geocoder would be the right tool for, and the count of them is
// the number that would change the answer.
var HOUSE_NUMBER = /^\s*\d{1,6}\s+[A-Za-z]/;

function shapeOf(place) {
  if (typeof place !== 'string' || !place.trim()) return 'nothing';
  var text = place.trim();
  if (JUNCTION.test(text)) return 'junction';
  if (BRACKETED.test(text)) return 'merchant';
  if (HOUSE_NUMBER.test(text)) return 'house number';
  if (STREET_WORD.test(text) && /,/.test(text)) return 'street+town';
  if (STREET_WORD.test(text)) return 'street';
  return 'merchant';
}

/* --- how coarsely can this place be placed? -------------------------------
 *
 * `area()` is the rig's own answer and is imported rather than reimplemented,
 * so these numbers predict what the rig would actually decide rather than what
 * a second copy of the rule would. Two grains are counted because they are the
 * two candidate keys for a table of measured legs, and they fail in opposite
 * directions: a town is coarse enough to lump twenty miles of Atlanta into one
 * bucket, and a town with a quadrant is fine enough that the bucket may never
 * see a second sample.
 */
function keyOf(place, grain) {
  var a = A.area(place);
  if (!a) return null;
  if (grain === 'town') return a.town || null;
  if (grain === 'town+quadrant') {
    if (!a.town) return null;
    return a.quadrant ? a.town + ' ' + a.quadrant : a.town;
  }
  if (grain === 'zip') return a.zip ? 'zip:' + a.zip : null;
  return null;
}

function grainOf(place) {
  var a = A.area(place);
  if (!a) return 'nowhere';
  if (a.zip) return 'zip';
  if (a.town && a.quadrant) return 'town+quadrant';
  if (a.town) return 'town only';
  return 'quadrant only';
}

function tally(list) {
  var out = {};
  for (var i = 0; i < list.length; i++) {
    out[list[i]] = (out[list[i]] || 0) + 1;
  }
  return out;
}

function median(nums) {
  if (!nums.length) return null;
  var s = nums.slice().sort(function (a, b) { return a - b; });
  var mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

/* --- could the driver's own legs answer it? -------------------------------
 *
 * Every card states a distance and a time, and once both of its ends are
 * placed, that is a measured sample of the road between two areas — with real
 * traffic, at a known hour, and with no map involved at all.
 *
 * Two things have to hold for a table of them to be worth building, and both
 * are measured here rather than hoped for:
 *
 *   reach — when a new pair of areas comes up, has this pair been driven
 *           BEFORE? Walked in time order with no lookahead, because a table
 *           built from the whole file and then tested against it would score
 *           itself on answers it had already been given.
 *   spread — when a pair HAS been driven several times, do those samples
 *           agree? A pair whose samples run four to fifteen miles has a median
 *           that is a number rather than an estimate, and this project does not
 *           print those.
 *
 * The honest caveat, stated in the output too: the journal keeps the card's
 * TOTAL distance, which includes driving to the pickup. So a sample overstates
 * the pickup-to-dropoff leg by however far away the car happened to be. The
 * split is on the card and is not stored, which is itself a finding.
 */
function legs(offers, grain) {
  var out = [];
  for (var i = 0; i < offers.length; i++) {
    var o = offers[i];
    var from = keyOf(o.pickup, grain), to = keyOf(o.dropoff, grain);
    if (!from || !to || from === to) continue;
    if (typeof o.miles !== 'number' || !(o.miles > 0)) continue;
    // The card's total covers driving to the pickup as well as the job, and
    // that first part moves with wherever the car happened to be — so the same
    // two places give a different total every time it comes up. Where the row
    // records the split, it comes off and what is left is the road between the
    // two places. Where it does not, the sample is kept and marked: a row
    // written before the rig started recording the split cannot be repaired,
    // and dropping those would throw away the entire history.
    var offMiles = typeof o.toPickupMiles === 'number' ? o.toPickupMiles : null;
    var offMins = typeof o.toPickupMinutes === 'number' ? o.toPickupMinutes : null;
    var miles = offMiles === null ? o.miles : o.miles - offMiles;
    var minutes = typeof o.minutes === 'number'
      ? (offMins === null ? o.minutes : o.minutes - offMins) : null;
    // A subtraction that leaves nothing is damage, not a very short job.
    if (!(miles > 0)) continue;
    out.push({ at: o.at, pair: from + ' → ' + to, miles: miles,
               minutes: minutes !== null && minutes > 0 ? minutes : null,
               exact: offMiles !== null });
  }
  out.sort(function (a, b) { return a.at - b.at; });
  return out;
}

function reachOf(sampleList) {
  var seen = Object.create(null);
  var hit = 0, asked = 0;
  for (var i = 0; i < sampleList.length; i++) {
    var pair = sampleList[i].pair;
    // Asked BEFORE it is recorded, or every pair answers itself.
    asked += 1;
    if (seen[pair]) hit += 1;
    seen[pair] = (seen[pair] || 0) + 1;
  }
  return { asked: asked, hit: hit, distinct: Object.keys(seen).length };
}

function spreadOf(sampleList, atLeast) {
  var by = Object.create(null);
  for (var i = 0; i < sampleList.length; i++) {
    (by[sampleList[i].pair] = by[sampleList[i].pair] || []).push(sampleList[i].miles);
  }
  var relative = [];
  var pairs = 0;
  Object.keys(by).forEach(function (pair) {
    var miles = by[pair];
    if (miles.length < atLeast) return;
    pairs += 1;
    var mid = median(miles);
    if (!mid) return;
    var lo = Math.min.apply(null, miles), hi = Math.max.apply(null, miles);
    relative.push((hi - lo) / mid);
  });
  return { pairs: pairs, spread: median(relative) };
}

/* --- the moments this feature exists for ----------------------------------
 *
 * Not every offer — the ones that arrived while an order the driver had TICKED
 * was still live. That is the only situation the stacking advice speaks in, and
 * the reach of any of this is what fraction of those moments could have been
 * answered at all. `busy()` is the rig's own definition of "during", imported
 * for the same reason `area()` is.
 */
function stackMoments(offers, grain, sampleList) {
  var byId = Object.create(null);
  offers.forEach(function (o) { if (o.id) byId[o.id] = o; });
  var busy;
  try {
    busy = A.busy(A.usable(offers)) || {};
  } catch (e) {
    return { moments: 0, bothEnds: 0, covered: 0, error: String(e && e.message || e) };
  }
  // The table as it stood at each moment, so this is the same no-lookahead
  // question asked of the rows that matter rather than of all of them.
  var moments = 0, bothEnds = 0, covered = 0;
  var ids = Object.keys(busy);
  ids.forEach(function (id) {
    var arriving = byId[id];
    var into = (busy[id] && busy[id].into) || [];
    if (!arriving) return;
    // The most recent enclosing order is the one in the car. No guard on the
    // list being empty: busy() only reports a row it found an enclosing order
    // for, and an empty list would fall through to the check below anyway. A
    // branch nothing can reach is a branch no test can hold.
    var held = into.slice().sort(function (a, b) { return b.at - a.at; })[0];
    var heldOffer = held && byId[held.id];
    if (!heldOffer) return;
    moments += 1;
    var d1 = keyOf(heldOffer.dropoff, grain);
    var p2 = keyOf(arriving.pickup, grain);
    if (!d1 || !p2) return;
    bothEnds += 1;
    if (d1 === p2) { covered += 1; return; }
    var want = d1 + ' → ' + p2;
    var before = sampleList.some(function (s) {
      return s.pair === want && s.at < arriving.at;
    });
    if (before) covered += 1;
  });
  return { moments: moments, bothEnds: bothEnds, covered: covered, error: null };
}

function analyse(offers) {
  offers = (offers || []).filter(function (o) { return o && typeof o === 'object'; });
  var withPlaces = offers.filter(function (o) {
    return Array.isArray(o.places) && o.places.length;
  });
  var pickups = offers.filter(function (o) { return !!o.pickup; });
  var dropoffs = offers.filter(function (o) { return !!o.dropoff; });
  var bothEnds = offers.filter(function (o) { return !!o.pickup && !!o.dropoff; });

  var report = {
    offers: offers.length,
    withPlaces: withPlaces.length,
    withPickup: pickups.length,
    withDropoff: dropoffs.length,
    withBothEnds: bothEnds.length,
    dropoffShapes: tally(dropoffs.map(function (o) { return shapeOf(o.dropoff); })),
    pickupShapes: tally(pickups.map(function (o) { return shapeOf(o.pickup); })),
    dropoffGrain: tally(dropoffs.map(function (o) { return grainOf(o.dropoff); })),
    grains: {},
    topAreas: [],
  };

  ['town', 'town+quadrant'].forEach(function (grain) {
    var sampleList = legs(offers, grain);
    var exact = sampleList.filter(function (s) { return s.exact; });
    report.grains[grain] = {
      samples: sampleList.length,
      exact: exact.length,
      reach: reachOf(sampleList),
      spread: spreadOf(sampleList, 3),
      // The same question asked only of the rows that know how much of their
      // journey was the approach. It is the honest version of the number and
      // it starts at zero on any journal written before the rig kept that.
      exactSpread: spreadOf(exact, 3),
      stacks: stackMoments(offers, grain, sampleList),
    };
  });

  // What a hand-built table of centroids would have to cover, in the order
  // worth building it. Both ends of every card, counted where they are placed.
  var ends = [];
  offers.forEach(function (o) {
    [o.pickup, o.dropoff].forEach(function (p) {
      var k = keyOf(p, 'town+quadrant');
      if (k) ends.push(k);
    });
  });
  var counts = tally(ends);
  report.topAreas = Object.keys(counts)
    .map(function (k) { return { area: k, seen: counts[k] }; })
    .sort(function (a, b) { return b.seen - a.seen; });
  report.placedEnds = ends.length;
  return report;
}

function pct(n, of) {
  if (!of) return '  n/a';
  return (Math.round((n / of) * 1000) / 10).toFixed(1) + '%';
}

function render(r) {
  var out = [];
  function line(s) { out.push(s === undefined ? '' : s); }

  line('Offers read: ' + r.offers);
  if (!r.offers) {
    line('');
    line('Nothing to measure. Either the window is empty, or this journal was');
    line('written with "keepPlaces": false and holds no addresses at all.');
    return out.join('\n');
  }
  line('  with any place named   ' + r.withPlaces + '  (' + pct(r.withPlaces, r.offers) + ')');
  line('  with a pickup          ' + r.withPickup + '  (' + pct(r.withPickup, r.offers) + ')');
  line('  with a dropoff         ' + r.withDropoff + '  (' + pct(r.withDropoff, r.offers) + ')');
  line('  with BOTH ends         ' + r.withBothEnds + '  (' + pct(r.withBothEnds, r.offers) + ')');
  line();
  line('What shape the dropoffs are — this decides street index vs geocoder:');
  Object.keys(r.dropoffShapes).sort(function (a, b) {
    return r.dropoffShapes[b] - r.dropoffShapes[a];
  }).forEach(function (k) {
    line('  ' + k.padEnd(16) + String(r.dropoffShapes[k]).padStart(5)
         + '  (' + pct(r.dropoffShapes[k], r.withDropoff) + ')');
  });
  line();
  line('  A junction or a street+town is a LOOKUP: two named streets either');
  line('  cross or they do not, so a damaged reading fails loudly. A house');
  line('  number is the only shape that needs a geocoder, and a geocoder turns');
  line('  a misread street into a confident wrong pin.');
  line();
  line('How finely each dropoff can be placed:');
  Object.keys(r.dropoffGrain).sort(function (a, b) {
    return r.dropoffGrain[b] - r.dropoffGrain[a];
  }).forEach(function (k) {
    line('  ' + k.padEnd(16) + String(r.dropoffGrain[k]).padStart(5)
         + '  (' + pct(r.dropoffGrain[k], r.withDropoff) + ')');
  });

  Object.keys(r.grains).forEach(function (grain) {
    var g = r.grains[grain];
    line();
    line('=== a table of your own driven legs, keyed by ' + grain + ' ===');
    line('  usable legs on file    ' + g.samples);
    line('  ...with the approach known and taken off  ' + g.exact
         + '  (' + pct(g.exact, g.samples) + ')');
    line('  distinct pairs         ' + g.reach.distinct);
    line('  pair already driven    ' + g.reach.hit + ' of ' + g.reach.asked
         + '  (' + pct(g.reach.hit, g.reach.asked) + ')');
    if (g.spread.pairs) {
      line('  pairs driven 3+ times  ' + g.spread.pairs);
      line('  typical spread         ' + (g.spread.spread === null ? 'n/a'
           : Math.round(g.spread.spread * 100) + '% of the median'));
      line('       (low is good: it is how much the same pair varies run to run,');
      line('        and it is the ceiling on how precise such a table could be)');
      if (g.exactSpread.pairs) {
        line('  ...on the rows that know their approach: '
             + Math.round(g.exactSpread.spread * 100) + '% over '
             + g.exactSpread.pairs + ' pairs');
        line('       (this is the real number. The one above is inflated by');
        line('        approaches that could not be taken off.)');
      } else {
        line('  ...on the rows that know their approach: none yet, so the');
        line('       figure above is the inflated one. It improves by itself.');
      }
    } else {
      line('  pairs driven 3+ times  none — no pair repeats often enough to check');
    }
    if (g.stacks.error) {
      line('  stack moments          could not be worked out: ' + g.stacks.error);
    } else {
      line('  real stack moments     ' + g.stacks.moments
           + '  (an offer arrived while a ticked order was live)');
      line('    both ends placed     ' + g.stacks.bothEnds
           + '  (' + pct(g.stacks.bothEnds, g.stacks.moments) + ')');
      line('    pair already driven  ' + g.stacks.covered
           + '  (' + pct(g.stacks.covered, g.stacks.moments) + ')  <-- the reach');
    }
  });

  line();
  line('Areas to give a location to, commonest first (' + r.topAreas.length
       + ' distinct, ' + r.placedEnds + ' placed ends):');
  var running = 0;
  var ninety = null;
  r.topAreas.forEach(function (a, i) {
    running += a.seen;
    if (ninety === null && running >= r.placedEnds * 0.9) ninety = i + 1;
    if (i < 25) line('  ' + String(a.seen).padStart(5) + '  ' + a.area);
  });
  if (r.topAreas.length > 25) line('  ... and ' + (r.topAreas.length - 25) + ' more');
  if (ninety !== null) {
    line();
    line('  ' + ninety + ' of them cover 90% of every end you have driven to.');
    line('  That is the size of a hand-built table of centroids, if it comes to');
    line('  that — and it is the cheapest of the three options by a long way.');
  }

  line();
  line('On the approach, which is the caveat on all of the above: a card states');
  line('its TOTAL time and distance, and part of that is driving to the pickup');
  line('rather than doing the job. The rig records the split from the day it');
  line('learned to, and subtracts it here. A row written before that cannot be');
  line('repaired, so it is kept and counted apart rather than thrown away. The');
  line('"approach known" line above is what share of the history is clean, and');
  line('it rises on its own with every shift.');
  return out.join('\n');
}

/* --- getting the rows ---------------------------------------------------- */

function fromPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.offers)) return payload.offers;
  return null;
}

async function load(where) {
  if (/^https?:\/\//.test(where)) {
    var url = where.replace(/\/+$/, '')
      + '/api/journal?days=3650&limit=20000';
    var res = await fetch(url);
    if (!res.ok) throw new Error(url + ' answered ' + res.status);
    var body = await res.json();
    if (body && body.unreadable) {
      throw new Error('the server could not read its journal (' + body.unreadable + ')');
    }
    return fromPayload(body);
  }
  var fs = require('fs');
  return fromPayload(JSON.parse(fs.readFileSync(where, 'utf8')));
}

async function main(argv) {
  var args = argv.filter(function (a) { return a !== '--json'; });
  var wantJson = argv.indexOf('--json') !== -1;
  var where = args[0] || 'http://localhost:8080';
  var offers;
  try {
    offers = await load(where);
  } catch (e) {
    console.error('could not read ' + where + ': ' + (e && e.message || e));
    console.error('');
    console.error('Point this at the rig or at the copy at home, whichever is up:');
    console.error('  node tools/measure_places.js http://uberscan.local:8080');
    process.exitCode = 1;
    return;
  }
  if (!offers) {
    console.error(where + ' did not answer with offers. Expected /api/journal, or');
    console.error('a file holding its reply.');
    process.exitCode = 1;
    return;
  }
  var report = analyse(offers);
  console.log(wantJson ? JSON.stringify(report, null, 1) : render(report));
}

module.exports = { analyse: analyse, render: render, shapeOf: shapeOf,
                   keyOf: keyOf, grainOf: grainOf, legs: legs,
                   reachOf: reachOf, spreadOf: spreadOf,
                   stackMoments: stackMoments, fromPayload: fromPayload };

if (require.main === module) main(process.argv.slice(2));
