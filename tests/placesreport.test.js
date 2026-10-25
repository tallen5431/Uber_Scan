/* The NucBox's offline report of where good offers start.
   Run with: node tests/placesreport.test.js

   tools/places_report.js changes no verdict and never reaches the rig, and
   that is the reason it is held hardest where it could flatter: a ranking
   printed in colour that chance would print as often, an hour of the night
   passed off as a place, a placed third of the record passed off as the
   whole, and a customer's door in a file meant for reading.

   Every name, street and coordinate here is invented: shops that do not
   exist, on streets that do not exist, round a point in open water (12.3 N,
   45.6 E) nowhere near the driver. The geocoder is a fake that answers in
   the relay's shape (server.js nbxHits), so the rig's own map-view.js rules
   decide every pin exactly as they would on the NucBox. */

'use strict';

process.env.TZ = process.env.TZ || 'America/New_York';

var path = require('path');
var fs = require('fs');
var os = require('os');
var P = require('../tools/places_report.js');
var MV = require('../map-view.js');
var A = require('../advice.js');

var pass = 0, fail = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass += 1; return; }
  fail += 1;
  console.log('FAIL  ' + name + ': got ' + JSON.stringify(got) + ' want ' + JSON.stringify(want));
}
function ok(name, cond) { eq(name, !!cond, true); }

var BASE = { lat: 12.3, lon: 45.6 };
function off(dLat, dLon) { return { lat: BASE.lat + dLat, lon: BASE.lon + dLon }; }

// A card the rig stands behind, its fix good, its distance a yardstick.
function card(extra) {
  var o = { id: 'x', at: at(1, 20), pay: 10, perHour: 20, minutes: 30, miles: 6, hasTotal: true,
            whole: true, state: 'no', lat: BASE.lat, lon: BASE.lon, gpsOk: true, gpsAge: 1,
            gpsErr: 5, gpsMode: 3 };
  Object.keys(extra || {}).forEach(function (k) { o[k] = extra[k]; });
  return o;
}

// Local ms on 2026-03-<day> at <h>:<m>, the driver's clock.
function at(day, h, m) { return new Date(2026, 2, day, h, m || 0).getTime(); }

function rng(seed) {
  var s = seed >>> 0;
  return function () { s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; };
}

/* --- the fake NucBox ------------------------------------------------------ */

function hit(name, kind, called, pt) {
  return { lat: pt.lat, lon: pt.lon, name: name, kind: kind, called: called };
}
var ANSWERS = {
  'Fernbrook Grill': [hit('Fernbrook Grill, 12, Pell Lane, Faketown', 'amenity', 'Fernbrook Grill', off(0.01, 0.01))],
  // A chain: three branches inside a 6-mile disc.
  'Bramble Burger': [hit('Bramble Burger, 1, Ash Row, Faketown', 'amenity', 'Bramble Burger', off(0.02, 0)),
                     hit('Bramble Burger, 9, Elm Row, Faketown', 'amenity', 'Bramble Burger', off(-0.03, 0.02)),
                     hit('Bramble Burger, 40, Oak Row, Faketown', 'amenity', 'Bramble Burger', off(0, -0.04))],
  'Nowhere Diner': [],
  // One branch inside the disc and one forty miles off: one answers.
  'Quince Tea': [hit('Quince Tea, 3, Pell Lane, Faketown', 'amenity', 'Quince Tea', off(0.005, 0)),
                 hit('Quince Tea, 5, Far Road, Elsewhere', 'amenity', 'Quince Tea', off(0.6, 0))],
};
var STREETS = {
  '77 Quillon Way': [hit('Tallow Noodle, 77, Quillon Way, Faketown, 99999', 'amenity', 'Tallow Noodle', off(-0.01, 0.01))],
  '742 Ombre Avenue': [hit('742, Ombre Avenue, Faketown, 99999', 'building', '', off(0.03, 0.03))],
};
// Ten of a name, as Nominatim's limit cuts a big chain.
ANSWERS['Starling Coffee'] = [];
for (var s = 0; s < 10; s++) {
  ANSWERS['Starling Coffee'].push(hit('Starling Coffee, ' + s + ', Ash Row', 'amenity', 'Starling Coffee', off(0.001 * s, 0)));
}
var asked = [];
function fakeFetch(u) {
  asked.push(u);
  var q = new URLSearchParams(u.split('?')[1] || '');
  var list = q.has('q') ? (ANSWERS[q.get('q')] || []) : (STREETS[q.get('street')] || []);
  var body = { ok: true, cutAt: list.length >= 10 ? 10 : null, hits: list };
  return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(body); } });
}
function nbx() {
  return new MV.NbxSearch({ gap: 0, fetch: fakeFetch });
}

/* --- the tests ------------------------------------------------------------ */

(async function () {

  /* --- placing a pickup, by the rig's own rules --- */

  var n = nbx();
  var one = await P.placePickup(n, 'Fernbrook Grill', card(), false);
  ok('a store\'s name that one place answers inside the disc is pinned', one.at);
  eq('...at that place', one.at && [one.at.lat, one.at.lon], [12.31, 45.61]);
  eq('...as a name', one.kind, 'name');
  var chain = await P.placePickup(n, 'Bramble Burger', card(), false);
  eq('a chain with several branches inside the disc is not placed', chain.at, null);
  eq('...and says so', chain.why, 'several');
  var cut = await P.placePickup(n, 'Starling Coffee', card(), false);
  eq('a list cut at the limit is not placed, however close its answers', [cut.at, cut.why], [null, 'capped']);
  var lone = await P.placePickup(n, 'Quince Tea', card(), false);
  ok('a name with one branch inside the disc and one far outside is pinned', lone.at && Math.abs(lone.at.lat - 12.305) < 1e-9);
  var none = await P.placePickup(n, 'Nowhere Diner', card(), false);
  eq('a name the map does not hold is not placed', [none.at, none.why], [null, 'noplace']);
  var door = await P.placePickup(n, 'Tallow Noodle (77 Quillon Way)', card(), false);
  ok('Uber\'s bracketed door is placed by the door', door.at && door.kind === 'door');
  ok('...and the street question went out without the store\'s name',
     asked.some(function (u) { return /street=77%20Quillon%20Way/.test(u); }));
  var noFix = await P.placePickup(n, 'Fernbrook Grill', card({ gpsOk: false, gpsWhy: 'stale' }), false);
  eq('a card with no usable fix is not placed (no disc, no answer)', [noFix.at, noFix.why], [null, 'nofix']);
  var before = asked.length;
  await P.placePickup(n, 'Fernbrook Grill', card({ gpsOk: undefined, lat: undefined, lon: undefined }), false);
  eq('...and nothing is asked for it', asked.length, before);
  var corner = await P.placePickup(n, 'Larkspur Ct & Ombre Rd, Faketown', card(), false);
  eq('a corner with no street index is not placed', [corner.at, corner.why], [null, 'cross']);
  var street = await P.placePickup(n, 'Quillon Way, Faketown', card(), false);
  eq('a street with no number is not a place', [street.at, street.why], [null, 'street']);
  ok('no question carried a town after a comma', !asked.some(function (u) { return /Faketown/.test(u); }));
  ok('every question was bounded by a viewbox', asked.every(function (u) { return /viewbox=/.test(u); }));

  // A pin far outside a short card's reach is refused by the disc.
  var near = await P.placePickup(n, 'Fernbrook Grill', card({ miles: 0.2 }), false);
  eq('a place outside the card\'s own distance plus slack is not placed', near.at, null);

  eq('the store label drops Uber\'s bracket', P.storeLabel('Tallow Noodle (77 Quillon Way)'), 'Tallow Noodle');
  eq('...and a printed door keeps the line before its comma',
     P.storeLabel('77 Quillon Way, Faketown, ZZ 99999'), '77 Quillon Way');

  /* --- the direct path asks what the relay asks, and keeps the answer --- */

  var realFetch = global.fetch;
  var seen = [];
  global.fetch = function (u) {
    seen.push(u);
    var list = [{ lat: '12.31', lon: '45.61', display_name: 'Fernbrook Grill, 12, Pell Lane',
                  category: 'amenity', name: 'Fernbrook Grill', place_id: 1 }];
    return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(list); } });
  };
  var cache = { answers: {}, hits: 0, fresh: 0 };
  var f = P.nbxFetch({ cache: cache, server: 'http://nucbox.invalid:8081', nominatim: 'http://nucbox.invalid:8088' });
  var r1 = await (await f('/api/nbx/search?q=Fernbrook%20Grill&viewbox=45.5%2C12.4%2C45.7%2C12.2')).json();
  eq('the direct search is Nominatim\'s jsonv2, ten, bounded', seen[0],
     'http://nucbox.invalid:8088/search?format=jsonv2&limit=10&q=Fernbrook%20Grill&viewbox=45.5%2C12.4%2C45.7%2C12.2&bounded=1');
  eq('...answered in the relay\'s shape', r1.hits[0], { lat: 12.31, lon: 45.61, name: 'Fernbrook Grill, 12, Pell Lane',
                                                        kind: 'amenity', called: 'Fernbrook Grill' });
  await f('/search?q=Fernbrook%20Grill&viewbox=45.5%2C12.4%2C45.7%2C12.2');
  eq('...and asked once: the second comes from the cache', [seen.length, cache.hits, cache.fresh], [1, 1, 1]);
  await f('/api/nbx/cross?a=X&b=Y&box=1');
  eq('a street-index question goes through the relay', seen[1], 'http://nucbox.invalid:8081/api/nbx/cross?a=X&b=Y&box=1');
  // ...and through an NbxSearch, as the command builds it: its default base
  // in front of every question.
  var through = await P.placePickup(new MV.NbxSearch({ gap: 0, fetch: f }), 'Fernbrook Grill', card(), false);
  ok('an NbxSearch over the adapter pins the place', through.at && seen.length === 3);
  global.fetch = function () { return Promise.reject(new Error('ECONNREFUSED')); };
  var down = await f('/search?q=Other&viewbox=1');
  eq('a NucBox that does not answer is "unreachable", and not kept', [down.ok, Object.keys(cache.answers).length], [false, 2]);
  global.fetch = realFetch;
  eq('hitsOf says a full list is cut', P.hitsOf(new Array(10).fill({ lat: 1, lon: 1 })).cutAt, 10);

  /* --- places and cells --- */

  var grouped = P.placesOf([
    { row: 0, label: 'Fernbrook Grill', at: off(0, 0) },
    { row: 1, label: 'Fernbrook grill', at: off(0.001, 0) },
    { row: 2, label: 'Fernbrook Grill', at: off(0.05, 0) },
  ]);
  eq('one store at one spot is one place, its label case aside', grouped.byRow[0], grouped.byRow[1]);
  ok('...and the same store 3 miles off is another', grouped.byRow[2] !== grouped.byRow[0]);
  var c1 = P.cellOf(off(0, 0)), c2 = P.cellOf(off(0.0005, 0.0005));
  eq('two points a few yards apart share a cell', c1.id, c2.id);
  var wide = MV.crowMiles({ lat: c1.lat, lon: c1.w }, { lat: c1.lat, lon: c1.e });
  var tall = MV.crowMiles({ lat: c1.s, lon: c1.lon }, { lat: c1.n, lon: c1.lon });
  ok('a cell is about ' + P.GRID_MI + ' miles a side (' + wide.toFixed(2) + ' x ' + tall.toFixed(2) + ')',
     Math.abs(wide - P.GRID_MI) < 0.05 && Math.abs(tall - P.GRID_MI) < 0.05);

  /* --- the statistics, on rows placed by hand --- */

  // n offers at one place, spread over `days` shift days and the given blocks,
  // rates from `rate(r, block)`.
  var R = rng(7);
  function rowsAt(place, count, opts) {
    var out = [];
    for (var i = 0; i < count; i++) {
      var block = opts.blocks[i % opts.blocks.length];
      var day = 2 + (i % (opts.days || 3));
      var o = card({ id: place + i, at: at(day, block * 3 + 1, i % 60), pickup: place,
                     dropoff: opts.dropoff || null,
                     perHour: Math.round(opts.rate(R, block) * 100) / 100,
                     pay: opts.pay ? opts.pay(R) : 10 });
      o.state = o.perHour >= 25 ? 'go' : 'no';
      o.place = place;
      o.pin = opts.pin || off(0, 0);
      out.push(o);
    }
    return out;
  }
  function byHand(rows) {
    return rows.map(function (o) { return o.pin ? { at: o.pin, why: null, kind: 'name' } : undefined; });
  }
  function noise(r) { return 12 + r() * 12 + (r() < 0.1 ? r() * 30 : 0); }

  // No effect: four places, one distribution.
  var flat = [];
  ['Ash Cafe', 'Birch Deli', 'Cedar Wok', 'Damson Pie'].forEach(function (p, i) {
    flat = flat.concat(rowsAt(p, 60, { blocks: [5, 6, 7], rate: noise, pin: off(0.05 * i, 0) }));
  });
  var rep0 = P.analyse(flat, [], byHand(flat), function () { return null; }, { now: 0 });
  var pl0 = rep0.views.all.place;
  eq('no effect: all four places are ranked', pl0.groups.length, 4);
  ok('no effect: the test does not call it significant (p = ' + pl0.p + ')', pl0.p >= 0.05 && !pl0.significant);
  ok('no effect: no place is coloured', pl0.groups.every(function (g) { return !g.beats; }));
  // ...and over many no-effect worlds, it says "significant" about as often as alpha.
  var falsePos = 0, worlds = 40;
  for (var w = 0; w < worlds; w++) {
    var Rw = rng(1000 + w), rows = [];
    ['Ash Cafe', 'Birch Deli', 'Cedar Wok'].forEach(function (p, i) {
      for (var k = 0; k < 40; k++) {
        var o = card({ id: p + w + '-' + k, at: at(2 + k % 3, 19 + k % 4, k % 60), pickup: p,
                       perHour: 12 + Rw() * 12 });
        o.pin = off(0.05 * i, 0);
        rows.push(o);
      }
    });
    var cw = P.cells(rows, function (o) { return o.pickup; }, { hold: true, shuffles: 200 });
    if (cw.significant && cw.groups.some(function (g) { return g.beats; })) falsePos += 1;
  }
  ok('no effect, ' + worlds + ' worlds: a coloured cell in at most 5 of them (' + falsePos + ')', falsePos <= 5);

  // A strong effect: one place pays $8 more in the same hours.
  var strong = flat.filter(function (o) { return o.place !== 'Ash Cafe'; })
    .concat(rowsAt('Ash Cafe', 60, { blocks: [5, 6, 7], rate: function (r) { return noise(r) + 8; } }));
  var rep1 = P.analyse(strong, [], byHand(strong), function () { return null; }, { now: 0 });
  var pl1 = rep1.views.all.place;
  ok('strong effect: significant (p = ' + pl1.p + ')', pl1.significant);
  var ash = pl1.groups.filter(function (g) { return rep1.places[g.name].label === 'Ash Cafe'; })[0];
  ok('strong effect: the paying place is ranked first', pl1.groups[0] === ash);
  // ...and the others, each against the rest in the same hours, are below:
  // "the rest" holds the paying place. True, and smaller by about a third.
  eq('strong effect: it alone is coloured above the rest',
     pl1.groups.filter(function (g) { return g.clear === 'above'; }).map(function (g) { return rep1.places[g.name].label; }),
     ['Ash Cafe']);
  ok('...and every other place sits nearer zero than it does',
     pl1.groups.every(function (g) { return g === ash || Math.abs(g.score) < ash.score / 2; }));
  ok('...its interval is clear of zero and holds its score', ash.sci[0] > 0 && ash.sci[0] <= ash.score && ash.score <= ash.sci[1]);
  ok('...and its median\'s interval holds the median', ash.ci[0] <= ash.median && ash.median <= ash.ci[1]);
  eq('the score is advice.js\'s own `matched`, recomputed with its intervals',
     pl1.groups.map(function (g) { return g.score; }), pl1.groups.map(function (g) { return g.matched; }));
  eq('the take share is the rig\'s own verdict on the rows',
     ash.take, Math.round(strong.filter(function (o) { return o.place === 'Ash Cafe' && o.state === 'go'; }).length / 60 * 100) / 100);

  // The hour wearing a place's clothes: late night pays more, and one place
  // is mostly seen late. Inside each block the two pay the same.
  function byBlock(r, block) { return (block === 0 ? 24 : 14) + r() * 6; }
  var hourly = rowsAt('Night Owl Bar', 80, { blocks: [0, 0, 0, 5], rate: byBlock, pin: off(0, 0) })
    .concat(rowsAt('Day Lark Cafe', 80, { blocks: [5, 5, 5, 0], rate: byBlock, pin: off(0.05, 0) }))
    .concat(rowsAt('Even Keel Deli', 80, { blocks: [0, 5], rate: byBlock, pin: off(0.1, 0) }));
  var rep2 = P.analyse(hourly, [], byHand(hourly), function () { return null; }, { now: 0 });
  var pl2 = rep2.views.all.place;
  var owl = pl2.groups.filter(function (g) { return rep2.places[g.name].label === 'Night Owl Bar'; })[0];
  var lark = pl2.groups.filter(function (g) { return rep2.places[g.name].label === 'Day Lark Cafe'; })[0];
  ok('the hour: raw medians are far apart (' + owl.median + ' vs ' + lark.median + ')', owl.median - lark.median > 5);
  ok('...and the raw test calls it real (p = ' + pl2.rawP + ')', pl2.rawP < 0.05);
  ok('...but held to the hour the test does not (p = ' + pl2.p + ')', pl2.p >= 0.05 && pl2.held);
  ok('...and the scores are small (' + owl.score + ', ' + lark.score + ')',
     Math.abs(owl.score) < 2.5 && Math.abs(lark.score) < 2.5);
  ok('...so nothing is coloured', pl2.groups.every(function (g) { return !g.beats; }));
  var blk = rep2.views[0].place;
  eq('a picked block holds nothing still', blk.held, false);
  ok('...and is filtered to its own hours', rep2.views[0].offers === hourly.filter(function (o) { return A.blockOf(o.at) === 0; }).length);

  // The floor: 29 offers is too few, 30 on one shift day is too few, 30 on two ranks.
  var floorRows = rowsAt('Twenty Nine', 29, { blocks: [5], rate: noise, pin: off(0.2, 0) })
    .concat(rowsAt('Thirty One Day', 30, { blocks: [5], rate: noise, days: 1, pin: off(0.25, 0) }))
    .concat(rowsAt('Thirty Two Days', 30, { blocks: [5], rate: noise, days: 2, pin: off(0.3, 0) }))
    .concat(rowsAt('Forty Two Days', 40, { blocks: [5], rate: noise, days: 2, pin: off(0.35, 0) }));
  var rep3 = P.analyse(floorRows, [], byHand(floorRows), function () { return null; }, { now: 0 });
  var pl3 = rep3.views.all.place;
  eq('the floor is ' + P.MIN_N + ' offers on two shift days',
     pl3.groups.map(function (g) { return rep3.places[g.name].label; }).sort(), ['Forty Two Days', 'Thirty Two Days']);
  eq('...and the rest are listed as too few, with their n',
     pl3.thin.map(function (t) { return [rep3.places[t.name].label, t.n, t.outings]; }),
     [['Thirty One Day', 30, 1], ['Twenty Nine', 29, 3]]);
  var html3 = P.html(rep3);
  ok('...and the page names them as too few', /Too few to rank/.test(html3));

  /* --- coverage: what was placed, and what the rest paid --- */

  var cov = [];
  for (var c = 0; c < 20; c++) {
    cov.push(card({ id: 'p' + c, at: at(2 + c % 2, 20, c), pickup: 'Fernbrook Grill', perHour: 20, pay: 12 }));
    cov.push(card({ id: 'u' + c, at: at(2 + c % 2, 21, c), pickup: 'Bramble Burger', perHour: 15, pay: 9 }));
  }
  cov.push(card({ id: 'np', at: at(2, 22), pickup: null }));
  var covPlaced = cov.map(function (o) {
    if (!o.pickup) return undefined;
    return o.pickup === 'Fernbrook Grill' ? { at: off(0, 0), why: null, kind: 'name' }
      : { at: null, why: 'several', kind: 'name' };
  });
  var rep4 = P.analyse(cov, [], covPlaced, function () { return null; }, { now: 0 });
  var cv = rep4.coverage;
  eq('coverage counts placed and unplaced pickups', [cv.all.placed.n, cv.all.unplaced.n, cv.noPickup], [20, 20, 1]);
  eq('...the gap in $/hr and in pay', [cv.all.gapPerHour, cv.all.gapPay], [5, 3]);
  ok('...tested (p = ' + cv.all.p + ')', cv.all.p < 0.05);
  eq('...why the unplaced were not placed', cv.why, [{ why: 'several places answer (a chain, or branches)', n: 20 }]);
  eq('...and shift day by shift day', cv.days.map(function (d) { return [d.day, d.placed.n, d.unplaced.n, d.gapPerHour]; }),
     [['2026-03-02', 10, 10, 5], ['2026-03-03', 10, 10, 5]]);
  ok('the banner says how many could not be placed and what they paid',
     /50\.0% of pickups could not be placed/.test(P.html(rep4)) && /\$15\.00\/hr against \$20\.00\/hr/.test(P.html(rep4)));
  ok('the summary says it too', /unplaced, several places answer[^\n]*: 20/.test(P.summary(rep4)));

  /* --- where trips leave you --- */

  var T = at(3, 19, 0);
  function o2(id, mins, state, ph) {
    return card({ id: id, at: T + mins * 60000, state: state, perHour: ph || 20, pay: 11 });
  }
  var line = P.timelineOf([o2('a', -5, 'go'), o2('b', 2, 'no'), o2('c', 7, 'go', 31), o2('d', 9, 'go')]);
  eq('the next take after a drop is the first go after it', P.nextTake(line, T),
     { censored: false, wait: 7, perHour: 31, pay: 11 });
  eq('a silence longer than the rig\'s break ends the wait unmeasured',
     P.nextTake(P.timelineOf([o2('b', 2, 'no'), o2('c', 2 + P.NEXT_GAP_MIN + 1, 'go')]), T), { censored: true });
  eq('...as does the first offer coming that late', P.nextTake(P.timelineOf([o2('c', P.NEXT_GAP_MIN + 1, 'go')]), T),
     { censored: true });
  eq('...and no offer at all', P.nextTake([], T), { censored: true });
  var suspectGo = card({ id: 's', at: T + 60000, state: 'go', suspect: true });
  eq('a go the rig does not stand behind is not a take', P.nextTake(P.timelineOf([suspectGo, o2('c', 4, 'go')]), T).wait, 4);

  // Trips: twelve ending in Faketown (the GPS at each drop), three in
  // Otherville; one replaced, which measures nothing.
  var DOOR = '742 Ombre Avenue, Faketown';
  var tripsRows = [], taken = [];
  for (var k = 0; k < 15; k++) {
    var tAt = at(2 + k % 3, 19, 0) + k * 3600000 / 4;
    var town = k < 12 ? 'Faketown' : 'Otherville';
    var tr = card({ id: 't' + k, at: tAt - 1800000, state: 'go', pickup: 'Fernbrook Grill',
                    dropoff: '742 Ombre Avenue, ' + town });
    tripsRows.push(tr);
    tripsRows.push(card({ id: 'n' + k, at: tAt + (3 + k % 5) * 60000, state: 'go', perHour: 26 }));
    taken.push({ id: 't' + k, tookAt: tAt - 1800000, endedAt: tAt, by: k === 14 ? 'replaced' : 'gps' });
  }
  var dropFix = off(0.03317, 0.03291);
  var rep5 = P.analyse(tripsRows, taken, [], function (t) {
    return { at: t.id === 't13' ? off(0.4123, 0.4123) : dropFix, how: 'gps' };
  }, { now: 0 });
  var dt = rep5.views.all.dropTown;
  eq('trips put down at the door are counted, a replaced one not', rep5.trips.n, 14);
  eq('the town table ranks the town over its floor', dt.groups.map(function (g) { return [g.name, g.trips, g.n]; }),
     [['Faketown', 12, 12]]);
  eq('...with its median wait', dt.groups[0].median, 4.5);
  eq('...and the town under the floor is listed with its n', dt.thin.map(function (t) { return [t.name, t.n]; }),
     [['Otherville', 2]]);
  var dg = rep5.views.all.dropGrid;
  eq('the grid table ranks the one cell over its floor', dg.groups.length, 1);
  eq('...and a cell under the floor is not named, only counted', [dg.thin, dg.thinCount, dg.thinTrips], [[], 1, 1]);
  eq('the next take\'s pay and rate are on the row', [dt.groups[0].nextPerHour, dt.groups[0].nextPay], [26, 10]);

  /* --- the page, and what it must not hold --- */

  var page = P.html(rep5);
  ok('the page builds, with its banner', /Offered, not earned/.test(page)
     && /ranks only places near where you already wait/.test(page));
  ok('...Leaflet pinned at map.html\'s version', /unpkg\.com\/leaflet@1\.9\.4\/dist\/leaflet\.js/.test(page));
  ok('...OSM\'s tiles, as map.html draws them', /tile\.openstreetmap\.org\/\{z\}\/\{x\}\/\{y\}\.png/.test(page));
  ok('...and the hour filter', /id="when"/.test(page));
  ok('no dropoff text is on the page', page.indexOf('Ombre') < 0 && page.indexOf('742') < 0);
  ok('no drop position is on the page', page.indexOf(String(dropFix.lat).slice(0, 7)) < 0 && page.indexOf('12.712') < 0);
  var embedded = JSON.parse(page.split('<script type="application/json" id="data">')[1].split('</script>')[0]);
  ok('the embedded data parses', embedded.views && embedded.views.all);
  ok('...and holds no field named dropoff anywhere', !/"dropoff"/.test(JSON.stringify(embedded)));
  ok('...and no list of trips, only their counts', typeof embedded.trips.n === 'number' && !Array.isArray(embedded.trips));
  var csvs = P.dropCsv(rep5, 'dropTown') + P.dropCsv(rep5, 'dropGrid') + P.csvOf(rep5, 'place')
           + P.coverageCsv(rep5);
  ok('no dropoff text or drop position in the CSVs', csvs.indexOf('Ombre') < 0 && csvs.indexOf(String(dropFix.lat).slice(0, 7)) < 0);
  ok('the drop cell is named by its 2-mile cell, not a door', /cell near/.test(P.dropCsv(rep5, 'dropGrid')));
  ok('the page\'s script parses', (function () {
    var js = page.split('<script>\n')[1].split('\n</script>')[0];
    try { new Function(js); return true; } catch (e) { console.log(e); return false; }
  }()));
  ok('the page is not coloured by any band: no rank colour or ramp',
     page.indexOf('rankColour') < 0 && page.indexOf('#17c964') < 0);
  eq('the dropoff test uses its own floor', dt.floor, P.DROP_MIN_N);

  /* --- the GPS log, read by tools/shift_report.py through rpi/gps.py's gate --- */

  var logDir = fs.mkdtempSync(path.join(os.tmpdir(), 'places-gps-'));
  var lines = [], here = off(0.0123, 0.0456);
  function tpv(t, lat, lon, eph) {
    var iso = new Date(t * 1000).toISOString().replace(/\.\d+Z$/, '.000Z');
    return (t.toFixed(6)) + ': ' + JSON.stringify({ class: 'TPV', device: '/dev/ttyACM0', mode: 3, time: iso,
                                                  lat: lat, lon: lon, eph: eph, speed: 0 });
  }
  var t0 = at(3, 19, 0) / 1000;
  for (var sec = 0; sec < 300; sec++) lines.push(tpv(t0 + sec, here.lat + (sec % 2 ? 1e-5 : -1e-5), here.lon, 8));
  // Half an hour on, one fix the gate refuses (eph 80 m, over FIX_ERR_MAX).
  lines.push(tpv(t0 + 1800, here.lat + 0.1, here.lon, 80));
  fs.writeFileSync(path.join(logDir, '2026-03-03_1900.jsonl'), lines.join('\n') + '\n');
  var g = P.gpsAt(logDir, [at(3, 19, 2), at(3, 19, 30), at(3, 19, 10)]);
  ok('the car at a drop is the usable fix nearest it', g.at[0] && Math.abs(g.at[0][0] - here.lat) < 1e-4
     && Math.abs(g.at[0][1] - here.lon) < 1e-6);
  eq('...a moment with only a refused fix near it has none', g.at[1], null);
  eq('...nor one more than shift_report\'s NEAR_S from any fix', g.at[2], null);
  ok('...and the gate passed the good fixes', g.passed >= 290 && g.files === 1);
  eq('no log directory is no positions', P.gpsAt(path.join(logDir, 'none'), [at(3, 19, 2)]).at, [null]);

  /* --- the command line, and where it may write --- */

  var ROOT = path.resolve(__dirname, '..');
  ok('a path inside the repository is inside it', P.inside(path.join(ROOT, 'out'), ROOT));
  ok('...and the home directory is not', !P.inside(os.homedir() + '/places-report', ROOT) || ROOT === os.homedir());
  var refused = path.join(ROOT, 'tmp-places-report-should-not-exist');
  var logs = [], errs = [];
  var log = console.log, err = console.error;
  console.log = function (x) { logs.push(x); };
  console.error = function (x) { errs.push(x); };
  await P.main(['http://127.0.0.1:9', '--out', refused]);
  console.log = log; console.error = err;
  ok('the report is refused inside the repository', /must not be written inside the/.test(errs.join('\n')));
  ok('...and nothing was written', !fs.existsSync(refused));
  process.exitCode = 0;
  eq('options parse', (function () {
    var a = P.parseArgs(['http://h:8081', '--out', '/x', '--gps', '/g', '--since', '2026-09-01',
                         '--nominatim', 'http://h:8088']);
    return [a.server, a.out, a.gps, a.since, a.nominatim, a.minN];
  }()), ['http://h:8081', '/x', '/g', '2026-09-01', 'http://h:8088', P.MIN_N]);
  ok('a bad date is refused', (function () { try { P.parseArgs(['--since', '9/1']); } catch (e) { return true; } return false; }()));

  console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                   : '\nAll ' + pass + ' places-report checks passed');
  process.exitCode = fail ? 1 : 0;
}()).catch(function (e) {
  console.log('FAIL  the suite threw: ' + (e && e.stack || e));
  process.exitCode = 1;
});
