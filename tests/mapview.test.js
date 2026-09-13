/* The map's deciding, with no map. Run with: node tests/mapview.test.js
 *
 * WHY THIS EXISTS BESIDE rpi/test_map.py
 * The browser suite drives the real page against a real server and is the only
 * thing that can check what gets drawn. It is also the only thing that can
 * check the rate limit, and it can afford to do that ONCE: the rule is one
 * request a second, so every case costs a second of wall clock. There are
 * cases worth checking that nobody would pay seconds for — two walks in a row,
 * a cache hit in the middle of a walk, a box around a driver near the equator
 * and one near the pole — and with the clock injected they cost nothing.
 *
 * So the split is not "unit vs integration". It is: everything here runs
 * against a fake clock and a fake network, which is what makes the awkward
 * cases affordable.
 *
 * WHAT IS BEING PROTECTED
 * Two things, and they pull in opposite directions.
 *
 * Nominatim blocks projects that exceed one request a second, and being
 * blocked means this stops working for everyone who pulls the repo — not just
 * for one run. Every question must be at least a second after the last one,
 * across every loop, including the ones a future change adds.
 *
 * And a geocoder answers a misread street with a real place somewhere, at the
 * same confidence as a right one. A pin in another state must be found and
 * kept out of the view, or the one bad lookup hides the ninety good ones.
 */

var MV = require('../map-view.js');

var pass = 0, fail = 0;

function eq(name, got, want) {
  var ok = got === want
    || (typeof got === 'number' && typeof want === 'number'
        && isFinite(got) && isFinite(want) && Math.abs(got - want) < 1e-6);
  if (ok) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + JSON.stringify(got)
                             + ' want ' + JSON.stringify(want)); }
}

function ok_(name, cond) { eq(name, !!cond, true); }
function no_(name, cond) { eq(name, !!cond, false); }

/* ---- the middle of a set, which is a median everywhere here ---------------
 *
 * Every use of it is a set expected to contain an outlier — a GPS fix that was
 * wrong, a geocode four states away — and the whole point is that the outlier
 * does not move the answer. A mean would move the box towards the bad fix and
 * the centre towards the bad pin, softening the two tests that exist to catch
 * them. */
eq('the middle of three is the middle one', MV.median([3, 1, 2]), 2);
eq('...of four, the average of the inner two', MV.median([1, 2, 4, 10]), 3);
eq('...and of nothing, nothing', MV.median([]), null);
// The point of a median, stated as a check: one wild value does not move it.
eq('one value four states away does not move it',
   MV.median([33.9, 34.0, 34.1, 41.8]), 34.05);

/* ---- reading a position off a row --------------------------------------- */
eq('a row with both numbers carries a fix',
   JSON.stringify(MV.fixOf({ lat: 33.9, lon: -84.5 })),
   JSON.stringify({ lat: 33.9, lon: -84.5 }));
eq('a row with neither does not', MV.fixOf({ pay: 12 }), null);
eq('...nor one with only a latitude', MV.fixOf({ lat: 33.9 }), null);
// NaN is the one that matters. `typeof NaN === 'number'`, so a check that only
// asked the type would let it through — and one NaN in a sort makes every
// median it lands in meaningless, which is every box and the shift's centre.
eq('a NaN is not a position', MV.fixOf({ lat: 33.9, lon: NaN }), null);
eq('...and neither is an infinity', MV.fixOf({ lat: Infinity, lon: -84.5 }), null);

/* ---- straight-line miles ------------------------------------------------ */
// A degree of latitude is about 69 miles, everywhere.
ok_('a degree of latitude is about 69 miles',
    Math.abs(MV.crowMiles({ lat: 33, lon: -84 }, { lat: 34, lon: -84 }) - 69) < 0.5);
// ...and a degree of longitude is that times the cosine of the latitude, which
// at 33°N is about 58. Getting this backwards would draw every box a fifth too
// narrow in the direction this driver's metro is widest.
ok_('a degree of longitude at 33°N is about 58',
    Math.abs(MV.crowMiles({ lat: 33, lon: -84 }, { lat: 33, lon: -83 }) - 57.9) < 1);
eq('a point is no distance from itself',
   MV.crowMiles({ lat: 33.9, lon: -84.5 }, { lat: 33.9, lon: -84.5 }), 0);

/* ---- the box drawn around where the car was ------------------------------
 *
 * Nominatim wants <left>,<top>,<right>,<bottom> — longitude first, and the
 * top is the HIGHER latitude. Getting that order wrong does not fail: it
 * sends a box that is inside out, and every lookup inside it comes back
 * empty, which reads exactly like a week of bad OCR. */
var box = MV.boxAround({ lat: 33.94, lon: -84.58 }).split(',').map(Number);
ok_('the box is longitude first, and the left is west of the right',
    box[0] < box[2]);
ok_('...and the top is north of the bottom', box[1] > box[3]);
ok_('...sixty miles of latitude, give or take',
    Math.abs((box[1] - box[3]) * 69 / 2 - 60) < 1);
ok_('...and wider than that in longitude, at this latitude',
    (box[2] - box[0]) > (box[1] - box[3]));
eq('no anchor, no box', MV.boxAround(null), null);
// The cosine guard. Without the floor, a driver at the pole gets a division by
// something near zero and a box spanning the planet — which is not a box at
// all, and quietly turns the whole feature off while looking like it works.
var polar = MV.boxAround({ lat: 89.9, lon: 0 }).split(',').map(Number);
ok_('a box near the pole stays a box', isFinite(polar[0]) && polar[2] - polar[0] < 360);

/* ---- which place gets searched near where the car actually was ----------- */
var ROWS = [
  { pickup: 'Chipotle', dropoff: 'Duval Ct', lat: 33.90, lon: -84.50 },
  { pickup: 'Chipotle', dropoff: 'Manchester Ln', lat: 33.92, lon: -84.52 },
  // The same shop, from a row that never knew where it was — every row the rig
  // wrote before it had a GPS, and every row whose fix had gone stale.
  { pickup: 'Chipotle', dropoff: 'Hereford Ct' },
  { pickup: 'Panda Express', dropoff: 'Farmington Dr' }
];
var anchor = MV.anchorFor(ROWS, 'Chipotle');
eq('a place named by rows that knew where they were gets an anchor',
   anchor.lat, 33.91);
eq('...at the middle of those rows and not of the whole range', anchor.lon, -84.51);
// A place whose OWN rows are silent gets nothing. The middle of the whole
// range was tried as a fallback and is deliberately not used: on a journal
// where only the last week carries positions it would box a place from eight
// months and two cities ago to last week's metro and refuse it.
eq('a place whose own rows are silent gets no anchor',
   MV.anchorFor(ROWS, 'Panda Express'), null);
eq('...and a place nothing names gets none either',
   MV.anchorFor(ROWS, 'Nowhere'), null);

/* ---- a pin that cannot be in this shift --------------------------------- */
var FOUND = {
  'Chipotle': { lat: 33.90, lon: -84.50 },
  'Duval Ct': { lat: 33.95, lon: -84.61 },
  'Manchester Ln': { lat: 33.88, lon: -84.44 },
  // "Daffodll Ln" resolved to a real Daffodil Lane, four states away.
  'Daffodll Ln': { lat: 41.88, lon: -87.63 }
};
var strays = MV.straysAmong(FOUND);
eq('exactly one pin is called a stray', Object.keys(strays).length, 1);
ok_('...and it is the one in another state', strays['Daffodll Ln'] > 500);
// The threshold is deliberately generous: a long ride is forty miles and
// nothing under seventy-five is refused, so what this catches is another
// state rather than a longer trip than usual.
var LONG = { a: { lat: 33.9, lon: -84.5 }, b: { lat: 33.9, lon: -84.4 },
             c: { lat: 34.5, lon: -84.5 } };   // 41 miles out
eq('a forty-mile job is not a stray', Object.keys(MV.straysAmong(LONG)).length, 0);
// A place that could not be found at all is not a stray — it is a different
// failure with a different list, and folding the two together would report
// "the geocoder got it wrong" over "the card never said".
eq('a place with no answer is not a stray',
   Object.keys(MV.straysAmong({ a: { lat: 33.9, lon: -84.5 }, b: null })).length, 0);
eq('nothing found, nothing stray', Object.keys(MV.straysAmong({})).length, 0);

/* ---- judging a job once both ends are placed -----------------------------
 *
 * The `impossible` test is the one place in this project where a geocoded
 * number meets a number off the card, and the DIRECTION of the conclusion is
 * the whole of why it is allowed. A straight line cannot beat the road, so a
 * straight line longer than the card's own total distance means a PIN is
 * wrong — never the card, never the rate, never the verdict the driver saw. */
var judged = MV.judge(
  [{ pickup: 'Chipotle', dropoff: 'Duval Ct', miles: 12 },
   { pickup: 'Chipotle', dropoff: 'Daffodll Ln', miles: 12 },
   { pickup: 'Chipotle', dropoff: null, miles: 4 },
   { pickup: 'Nowhere At All', dropoff: 'Duval Ct', miles: 9 }],
  FOUND, strays);
no_('a job whose straight line fits inside the card is believed',
    judged[0].impossible);
ok_('...and one whose straight line beats the card is not', judged[1].impossible);
// Which END is in another state is the whole of what a driver needs to judge
// it, so it is kept per end rather than as one flag on the job.
eq('the stray end is named', judged[1].toStray > 500, true);
eq('...and the good end is not', judged[1].fromStray, null);
eq('a job with only one end has no line to measure', judged[2].crow, null);
no_('...and cannot be impossible', judged[2].impossible);
eq('an end the geocoder never found leaves the job unplaced', judged[3].from, null);
// A card that never stated a distance cannot contradict anything, and must not
// be marked wrong for it — that would make "the OCR missed the miles" look
// identical to "the pin is in Illinois".
var noMiles = MV.judge([{ pickup: 'Chipotle', dropoff: 'Daffodll Ln' }], FOUND, {});
no_('a card with no stated distance is never called impossible',
    noMiles[0].impossible);

/* ---- one pin per place, not one per offer -------------------------------
 *
 * Every job at the same shop resolves to the same coordinate. Keyed on the
 * place as the CARD wrote it rather than on the coordinate: two spellings the
 * geocoder happened to agree on are two things the rig read, and this page
 * exists to check what the rig read. */
var pins = MV.byPlace(MV.judge(
  [{ pickup: 'Chipotle', dropoff: 'Duval Ct' },
   { pickup: 'Chipotle', dropoff: 'Manchester Ln' },
   { pickup: 'Chipotle', dropoff: 'Duval Ct' }], FOUND, {}));
eq('three jobs at one shop make one pin', pins.length, 3);
eq('...carrying the count', pins[0].jobs.length, 3);
eq('...and named as the card named it', pins[0].name, 'Chipotle');
eq('a place used as both ends is one pin with both roles',
   MV.byPlace(MV.judge([{ pickup: 'Chipotle', dropoff: 'Duval Ct' },
                        { pickup: 'Duval Ct', dropoff: 'Chipotle' }], FOUND, {}))
     .filter(function (p) { return p.roles.pickup && p.roles.dropoff; }).length, 2);

/* ---- the rate limit, against a clock that costs nothing -------------------
 *
 * The reason this is worth a fake clock: the rule is one request a second, so
 * every real case costs a second, and the cases that have actually gone wrong
 * here are the ones nobody would pay seconds to check — a second walk starting
 * right after the first ended, and a cache hit in the middle of a walk. Both
 * of those shipped broken. */
function fakeGeo(answers, opts) {
  opts = opts || {};
  var clock = { t: 1000 };
  var sent = [];
  var geo = new MV.Geocoder({
    hint: opts.hint || function () { return ''; },
    now: function () { return clock.t; },
    // Sleeping moves the clock and nothing else, so a whole week of lookups
    // runs in a millisecond and the gaps are still exactly what they would be.
    sleep: function (ms) { clock.t += ms; return Promise.resolve(); },
    fetch: function (url) {
      sent.push({ url: url, at: clock.t });
      // Time passes during a request too, or a stub would make every gap look
      // like exactly the sleep and hide a limiter that measures the wrong end.
      clock.t += 40;
      var q = decodeURIComponent((/[?&]q=([^&]*)/.exec(url) || [])[1] || '');
      var hit = answers[q];
      return Promise.resolve({
        ok: true,
        json: function () {
          return Promise.resolve(hit ? [{ lat: hit.lat, lon: hit.lon,
                                          display_name: q, type: 'place' }] : []);
        }
      });
    }
  });
  return { geo: geo, sent: sent, clock: clock };
}

function gaps(sent) {
  return sent.slice(1).map(function (s, i) { return s.at - sent[i].at; });
}

(async function () {
  var A = fakeGeo({ 'one': { lat: 33.9, lon: -84.5 },
                    'two': { lat: 33.91, lon: -84.51 },
                    'three': { lat: 33.92, lon: -84.52 } });
  var into = {};
  await A.geo.walk(['one', 'two', 'three'], function () { return null; }, into);
  eq('three places, three questions', A.sent.length, 3);
  ok_('...every one of them at least a second after the last',
      gaps(A.sent).every(function (g) { return g >= 1000; }));
  eq('...and every answer kept', Object.keys(into).length, 3);

  /* A SECOND walk, starting the instant the first ended. This is the case that
   * shipped broken: the pacing was a sleep at the bottom of one loop, which is
   * correct for one loop and says nothing about the gap between two. Measured
   * against the browser suite's stub at the time: 4ms, under a rule of one a
   * second. */
  var before = A.sent.length;
  await A.geo.walk(['four'], function () { return null; }, into);
  eq('a second walk asks its question', A.sent.length, before + 1);
  ok_('...still a second after the first walk\'s last',
      A.sent[before].at - A.sent[before - 1].at >= 1000);

  /* A place already remembered costs nothing and delays nothing. The waiting
   * lives around the REQUEST, not around the loop, so a cached place in the
   * middle of a walk does not buy a second of silence that was never owed. */
  var B = fakeGeo({ 'a': { lat: 33.9, lon: -84.5 }, 'b': { lat: 33.91, lon: -84.51 } });
  await B.geo.walk(['a'], function () { return null; }, {});
  var t0 = B.clock.t;
  await B.geo.walk(['a', 'a', 'a'], function () { return null; }, {});
  eq('a remembered place asks nothing', B.sent.length, 1);
  eq('...and waits for nothing', B.clock.t, t0);

  /* The cache key carries the box. The same place asked inside a box and asked
   * without one are two different questions with two different right answers,
   * and storing the second under the first's key is how a good answer gets
   * overwritten by a worse one. */
  var C = fakeGeo({ 'Duval Ct': { lat: 33.9, lon: -84.5 } });
  var aBox = MV.boxAround({ lat: 33.9, lon: -84.5 });
  await C.geo.lookup('Duval Ct', aBox);
  no_('a place answered inside a box is not thereby known without one',
      C.geo.knows('Duval Ct', null));
  ok_('...but is known inside that box', C.geo.knows('Duval Ct', aBox));
  await C.geo.lookup('Duval Ct', null);
  eq('...so asking it wide is a second question', C.sent.length, 2);
  ok_('...and the boxed question carried the box',
      C.sent[0].url.indexOf('viewbox=') !== -1 && C.sent[0].url.indexOf('bounded=1') !== -1);
  no_('...where the wide one did not', C.sent[1].url.indexOf('viewbox=') !== -1);

  /* The hint is part of the question, so it has to be part of the key too. A
   * driver who types a town after a blank run must not get the answers from
   * the blank run handed back. */
  var hint = '';
  var D = fakeGeo({ 'Duval Ct': { lat: 33.9, lon: -84.5 },
                    'Duval Ct, Georgia': { lat: 33.91, lon: -84.51 } },
                  { hint: function () { return hint; } });
  await D.geo.lookup('Duval Ct', null);
  hint = 'Georgia';
  no_('typing a hint makes it a different question', D.geo.knows('Duval Ct', null));
  await D.geo.lookup('Duval Ct', null);
  eq('...which is asked', D.sent.length, 2);
  ok_('...with the hint in it', D.sent[1].url.indexOf('Georgia') !== -1);

  /* A dead network does not stop the walk — and is not remembered as an
   * answer about the place.
   *
   * This is the difference between "nobody there" and "nobody answered", and
   * it used to be collapsed: both became null, and null went into the cache,
   * and the cache is localStorage. A hotspot that drops for four seconds part
   * way through a paced walk is the ordinary case in a car, and every place
   * asked inside that gap became a permanent "the geocoder could not find
   * this" — never asked again, listed on the map page as a misread address,
   * with the only recovery being to throw away every good answer too. */
  var dead = new MV.Geocoder({
    now: function () { return 0; }, sleep: function () { return Promise.resolve(); },
    fetch: function () { return Promise.reject(new Error('offline')); }
  });
  eq('a request that never arrives is not an answer about the place',
     await dead.lookup('Anywhere', null), undefined);
  no_('...and is not remembered as one', dead.knows('Anywhere', null));
  var refused = new MV.Geocoder({
    now: function () { return 0; }, sleep: function () { return Promise.resolve(); },
    fetch: function () { return Promise.resolve({ ok: false, status: 429 }); }
  });
  // 429 and 403 are what Nominatim sends a client it is throttling or has
  // blocked. Caching those as "no such place" turns a bad minute into a
  // permanent hole in the map.
  eq('...nor is a refusal', await refused.lookup('Anywhere', null), undefined);
  no_('...which is also not remembered', refused.knows('Anywhere', null));
  // An answer that DID arrive and held nothing is a fact about the place, and
  // is remembered — that is what makes the second run of a week free.
  var nothing = new MV.Geocoder({
    now: function () { return 0; }, sleep: function () { return Promise.resolve(); },
    fetch: function () {
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve([]); } });
    }
  });
  eq('an answer that arrived and held nothing is a null',
     await nothing.lookup('Nowhere At All', null), null);
  ok_('...and that one IS remembered', nothing.knows('Nowhere At All', null));
  // ...and a walk carries on through the dead patch rather than stopping at
  // the first place the hotspot dropped.
  var flaky = 0;
  var patchy = new MV.Geocoder({
    now: function () { return 0; }, sleep: function () { return Promise.resolve(); },
    fetch: function () {
      flaky++;
      if (flaky === 2) return Promise.reject(new Error('offline'));
      return Promise.resolve({ ok: true, json: function () {
        return Promise.resolve([{ lat: '33.9', lon: '-84.5', display_name: 'x', type: 'road' }]);
      } });
    }
  });
  var through = {};
  await patchy.walk(['a', 'b', 'c'], function () { return null; }, through);
  eq('a walk through a dead patch asks for all three', flaky, 3);
  ok_('...keeps the answers either side of it', !!through.a && !!through.c);
  no_('...and leaves the one it could not ask to be asked again',
      patchy.knows('b', null));

  /* --- the whole run ------------------------------------------------------
   *
   * Places a box refused are asked AGAIN, wide, through the same paced walk.
   * A box is a claim that the answer is within sixty miles of where the car
   * was, and losing a genuinely distant pin to a feature meant to gain pins is
   * the wrong trade. */
  var OFFERS = [
    { pickup: 'Chipotle', dropoff: 'Duval Ct', miles: 12,
      lat: 33.90, lon: -84.50 },
    { pickup: 'Chipotle', dropoff: 'Far Away Rd', miles: 12,
      lat: 33.92, lon: -84.52 }
  ];
  // "Far Away Rd" is answered only when asked without a box, which is exactly
  // the shape of a genuinely distant dropoff.
  var answered = { 'Chipotle': { lat: 33.90, lon: -84.50 },
                   'Duval Ct': { lat: 33.95, lon: -84.55 },
                   'Far Away Rd': { lat: 41.88, lon: -87.63 } };
  var E = fakeGeo(answered);
  var boxedAway = 0;
  var realFetch = E.geo.fetch;
  E.geo.fetch = function (url, init) {
    if (url.indexOf('viewbox=') !== -1 && url.indexOf(encodeURIComponent('Far Away Rd')) !== -1) {
      boxedAway++;
      E.sent.push({ url: url, at: E.clock.t });
      E.clock.t += 40;
      return Promise.resolve({ ok: true, json: function () { return Promise.resolve([]); } });
    }
    return realFetch(url, init);
  };
  var said = [];
  var run = await MV.placeAll(OFFERS, E.geo, function (s) { said.push(s); });
  eq('the place a box refused was asked again', boxedAway, 1);
  ok_('...and found the second time', !!run.found['Far Away Rd']);
  ok_('...and every question was still a second apart',
      gaps(E.sent).every(function (g) { return g >= 1000; }));
  eq('the far pin is kept out of the view', Object.keys(run.strays).length, 1);
  ok_('...by name', run.strays['Far Away Rd'] > 500);
  eq('both jobs could have been drawn', run.couldDraw, 2);
  // Counted against what could ever be drawn, not against everything loaded:
  // folding "the card never said where this went" into the same figure as
  // "the geocoder got it wrong" reports two different problems as one.
  eq('...and one of them honestly was', run.drawn, 1);
  ok_('the page is told what happened', said.length > 1);
  ok_('...including that some were not found near the driver',
      said.some(function (s) { return s.indexOf('not found near you') !== -1; }));
  ok_('...and the final line counts against what could be drawn',
      /1 of 2 drawn end to end/.test(run.done));

  /* A run over nothing must not throw, say something false, or claim a
   * division it did not do. The offers page will call this on every load
   * before anybody has pressed anything. */
  var F = fakeGeo({});
  var empty = await MV.placeAll([], F.geo, function () {});
  eq('an empty range asks nothing', F.sent.length, 0);
  eq('...and draws nothing', empty.drawn, 0);
  eq('...of nothing', empty.couldDraw, 0);
  eq('...with no strays', Object.keys(empty.strays).length, 0);

  console.log(fail ? ('\n' + pass + ' passed, ' + fail + ' FAILED')
                   : '\nAll ' + pass + ' map-view checks passed');
  process.exit(fail ? 1 : 0);
})().catch(function (e) {
  console.log('FAIL  the suite itself threw: ' + (e && e.stack || e));
  process.exit(1);
});
