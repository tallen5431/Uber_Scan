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
// The town rule, which map-view no longer carries a copy of. It is handed in
// at every call, the way map.html hands it in — see MV.townOf.
var ADV = require('../advice.js');

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
eq('a row with both numbers and the gate\'s yes carries a fix',
   JSON.stringify(MV.fixOf({ lat: 33.9, lon: -84.5, gpsOk: true })),
   JSON.stringify({ lat: 33.9, lon: -84.5 }));
eq('a row with neither does not', MV.fixOf({ pay: 12, gpsOk: true }), null);
eq('...nor one with only a latitude', MV.fixOf({ lat: 33.9, gpsOk: true }), null);
// NaN is the one that matters. `typeof NaN === 'number'`, so a check that only
// asked the type would let it through — and one NaN in a sort makes every
// median it lands in meaningless, which is every box and the shift's centre.
eq('a NaN is not a position', MV.fixOf({ lat: 33.9, lon: NaN, gpsOk: true }), null);
eq('...and neither is an infinity',
   MV.fixOf({ lat: Infinity, lon: -84.5, gpsOk: true }), null);
// The gate is rpi/gps.py's usable(), and its answer is on the row. Read here,
// never worked out again: a mode-3 fix gpsd itself put at 129 m is the same
// two numbers as a clear sky's, and only `gpsOk` tells them apart.
eq('a fix the GPS gate refused is no position here',
   MV.fixOf({ lat: 33.9526, lon: -84.5499, gpsErr: 129.2, gpsMode: 3,
              gpsOk: false, gpsWhy: 'rough' }), null);
eq('...nor one nobody judged — a row from before the gate, or not from the rig',
   MV.fixOf({ lat: 33.9526, lon: -84.5499 }), null);
eq('...and the refusal says which, so a count can say it',
   MV.fixRefused({ lat: 33.9526, lon: -84.5499, gpsOk: false, gpsWhy: 'rough' }),
   'rough');
eq('...or that nobody judged it',
   MV.fixRefused({ lat: 33.9526, lon: -84.5499 }), 'unjudged');
eq('a usable fix is not a refusal',
   MV.fixRefused({ lat: 33.9526, lon: -84.5499, gpsOk: true }), null);
eq('...and a row with no coordinate is not one either: it did not know',
   MV.fixRefused({ pay: 12 }), null);

/* ---- you are here --------------------------------------------------------
 *
 * The beat's newest fix, as both maps draw it. Marietta Square, a public
 * place; 27.8 m is the owner's receiver indoors, 129.2 m a four-satellite fix
 * real gpsd made mode 3. `freshFor` is how long gps.py said the fix stayed
 * inside its staleness rule when the beat left. */
var BEAT = { lat: 33.9526, lon: -84.5499, gpsAge: 0.6, gpsErr: 27.8,
             gpsMode: 3, gpsOk: true, gpsWhy: null, freshFor: 19.4 };
var dot = MV.hereDot(BEAT, 1400);
eq('a usable fix is a dot where it is', dot && dot.lat, 33.9526);
eq('...with a circle the size of its own error', dot && dot.err, 27.8);
eq('...and a label giving the error and the age', dot && dot.label, '±28 m · 2 s old');
eq('...not greyed while fresh', dot && dot.grey, false);
var silent = MV.hereDot(BEAT, 25000);
// The beat stopped coming. The fix is still where the car WAS, but "2 s old"
// would be a claim about now, so the age keeps counting and the dot goes grey.
eq('a dot whose beat stopped coming greys once its time is up',
   silent && silent.grey, true);
eq('...and its age keeps counting, not frozen at the beat', silent && silent.label,
   '±28 m · 26 s old');
var stale = MV.hereDot({ lat: 33.9526, lon: -84.5499, gpsAge: 45.0, gpsErr: 12.0,
                         gpsMode: 3, gpsOk: false, gpsWhy: 'stale', freshFor: 0 }, 500);
eq('a fix the gate called stale is drawn grey, where it was',
   stale && [stale.lat, stale.grey, stale.label].join('|'), '33.9526|true|±12 m · 46 s old');
var rough = MV.hereDot({ lat: 33.9526, lon: -84.5499, gpsAge: 0.5, gpsErr: 129.2,
                         gpsMode: 3, gpsOk: false, gpsWhy: 'rough' }, 0);
eq('a rough fix is not drawn, and says why with the figure',
   rough && [rough.lat, rough.line].join('|'), '|GPS too rough here (±129 m)');
eq('a fix with no error figure says so rather than vanishing',
   (MV.hereDot({ lat: 33.9526, lon: -84.5499, gpsOk: false, gpsWhy: 'unrated' }, 0)
    || {}).line, MV.GPS_REFUSED.unrated);
var stuck = MV.hereDot({ lat: 33.9526, lon: -84.5499, gpsAge: 0.6, gpsErr: 16.8,
                         gpsMode: 3, gpsOk: false, gpsWhy: 'frozen' }, 0);
eq('a frozen fix is not drawn as where the car is, and says it is stuck',
   stuck && [stuck.lat, stuck.line].join('|'), '|GPS stuck on one spot');
eq('no fix at all is nothing drawn and nothing said', MV.hereDot(null, 0), null);
eq('...and a beat that says no fix is the same', MV.hereDot({ lat: null }, 0), null);
eq('a fix with no time left on it is grey from the start',
   (MV.hereDot({ lat: 33.9526, lon: -84.5499, gpsAge: 0.5, gpsErr: 12, gpsMode: 3,
                 gpsOk: true }, 10) || {}).grey, true);
eq('minutes past the first sixty seconds',
   (MV.hereDot(BEAT, 185000) || {}).label, '±28 m · 3 min old');

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

/* ---- how far out of the way a stop is -------------------------------------
 *
 * The driver's own question about a second offer: is the pickup on the way to
 * where I am already going, or behind me? Three points, and the answer is what
 * the stop adds to the trip. */
var HERE = { lat: 33.90, lon: -84.50 };
var AHEAD = { lat: 34.00, lon: -84.50 };          // due north, about 7 miles
ok_('a stop on the line adds nothing',
    Math.abs(MV.detour(HERE, { lat: 33.95, lon: -84.50 }, AHEAD)) < 0.01);
// Half way there and half a degree east: out and back again.
ok_('a stop off to the side adds the going and the coming back',
    MV.detour(HERE, { lat: 33.95, lon: -84.20 }, AHEAD) > 20);
// The case the driver is really asking about. A pickup BEHIND you costs twice
// the distance back to it, and on a map alone that is easy to misjudge: the
// pin looks close, and it is close — in the wrong direction.
var BACK = MV.detour(HERE, { lat: 33.80, lon: -84.50 }, AHEAD);
ok_('a stop behind you costs twice the distance back to it (%s)',
    Math.abs(BACK - 2 * MV.crowMiles(HERE, { lat: 33.80, lon: -84.50 })) < 0.01);
// Two points is not a smaller detour. It is no answer at all, and computed
// anyway it comes out zero — which reads as "right on your way", which is the
// most expensive thing this could get wrong.
eq('with nowhere to be going, there is no detour to state',
   MV.detour(HERE, AHEAD, null), null);
eq('...nor with nothing to go by way of', MV.detour(HERE, null, AHEAD), null);
eq('...nor with no idea where the car is', MV.detour(null, HERE, AHEAD), null);

/* ---- the card's own disc --------------------------------------------------
 *
 * The design study's wrong-branch case, in invented points round Marietta
 * Square: a 9.4 mi card, a fix the gate passed, and the map's McDonald's
 * 21.8 mi north of it — the right branch was 2.1 mi away and the map never
 * returned it. With the order in the car ending 20.2 mi east, the panel's old
 * arithmetic printed "+31.3 mi out of your way" off that pin. A straight line
 * cannot beat the road, so a pin 21.8 mi from where the card came up cannot
 * be the pickup of a job the card says is 9.4 mi in all. */
var SQUARE = { lat: 33.9526, lon: -84.5499 };
var WRONG_BRANCH = { lat: 34.2683, lon: -84.5499 };   // 21.8 mi north
var RIGHT_BRANCH = { lat: 33.9830, lon: -84.5499 };   // 2.1 mi north
var HELD_END = { lat: 33.9526, lon: -84.1974 };       // 20.2 mi east
function card(extra) {
  return Object.assign({ lat: SQUARE.lat, lon: SQUARE.lon, gpsAge: 0.6,
                         gpsErr: 27.8, gpsMode: 3, gpsOk: true, gpsWhy: null,
                         miles: 9.4, hasTotal: true, legs: 1, whole: true,
                         milesUncertain: false, milesCorrected: false,
                         earlyLook: false, doubt: null }, extra || {});
}
eq('the wrong-branch case is the one the study measured: +31.3 off the pin',
   MV.detour(SQUARE, WRONG_BRANCH, HELD_END).toFixed(1), '31.3');
eq('a same-brand pin 21.8 mi from a fresh fix on a 9.4 mi card is refused, '
   + 'not printed as "+31.3"',
   MV.againstCard(card(), SQUARE, WRONG_BRANCH, "McDonald's", 'new'),
   "wrong pin for McDonald's — 21.8 mi from you, past the card's 9.4 mi");
eq('...and the right branch, 2.1 mi away, passes',
   MV.againstCard(card(), SQUARE, RIGHT_BRANCH, "McDonald's", 'new'), null);
// The half mile of slack is the edge, both sides of it: 9.4 + 0.5 = 9.9.
var EDGE_IN = { lat: SQUARE.lat + 9.85 / 69.05, lon: SQUARE.lon };
var EDGE_OUT = { lat: SQUARE.lat + 9.95 / 69.05, lon: SQUARE.lon };
eq('a pin just inside the card\'s distance plus half a mile passes',
   MV.againstCard(card(), SQUARE, EDGE_IN, 'X', 'new'), null);
ok_('...and one just past it is refused',
    MV.againstCard(card(), SQUARE, EDGE_OUT, 'X', 'new'));
// The rig's repair is not the screen's figure, as statedBy() says.
eq('a figure the rig put a decimal back in says so',
   MV.againstCard(card({ milesCorrected: true }), SQUARE, WRONG_BRANCH,
                  "McDonald's", 'new'),
   "wrong pin for McDonald's — 21.8 mi from you, past the card's 9.4 mi "
   + '(rig-corrected)');
// Two legs the rig summed are a yardstick as a printed total is; the summed
// figure, never the approach leg (`toPickupMiles`), whose only slack would be
// the half mile against motion nobody has measured.
eq('two legs the rig summed are a yardstick too',
   MV.cardYardstick(card({ hasTotal: false, legs: 2 })).miles, 9.4);
eq('...measured on the summed figure, not the approach leg',
   MV.cardYardstick(card({ toPickupMiles: 1.2 })).miles, 9.4);
// Every reason a card is no yardstick, each reached.
eq('a card that states no distance is no yardstick',
   MV.againstCard(card({ miles: null }), SQUARE, WRONG_BRANCH, 'X', 'new'),
   'this card states no distance to check the pickup pin against');
eq('a card judge() would not trust is no yardstick',
   MV.againstCard(card({ whole: false }), SQUARE, WRONG_BRANCH, 'X', 'new'),
   'the rig does not trust this card\'s distance, so the pickup pin cannot '
   + 'be checked');
eq('...nor one whose distance the rig doubted',
   MV.cardYardstick(card({ milesUncertain: true })).why, 'untrusted');
eq('...nor one rate() doubted a figure of',
   MV.cardYardstick(card({ doubt: 'speed' })).why, 'untrusted');
eq('an Early look card is never a yardstick',
   MV.againstCard(card({ earlyLook: true }), SQUARE, RIGHT_BRANCH, 'X', 'new'),
   'an Early look card may not measure from your car — no yardstick yet');
eq('a one-leg card (DoorDash\'s shape) has no yardstick yet',
   MV.againstCard(card({ hasTotal: false, legs: 1 }), SQUARE, RIGHT_BRANCH,
                  'X', 'new'),
   'this kind of card may not count the drive to the pickup — no yardstick '
   + 'yet');

// The card's own fix, and every reason there is none to measure from.
eq('a card\'s fix the gate passed is where it is measured from',
   JSON.stringify(MV.cardFix(card()).at), JSON.stringify(SQUARE));
eq('a card with no coordinate says it came up without a GPS fix',
   MV.fixLine(MV.cardFix(card({ lat: null, lon: null, gpsOk: null })), 'new'),
   'this card came up without a GPS fix');
eq('a rough fix says it is too rough, with the figure',
   MV.fixLine(MV.cardFix(card({ gpsErr: 129.2, gpsOk: false, gpsWhy: 'rough' })),
              'new'),
   'GPS fix on this card too rough to measure from (±129 m)');
eq('a fix with no accuracy says so',
   MV.fixLine(MV.cardFix(card({ gpsErr: null, gpsOk: false, gpsWhy: 'unrated' })),
              'new'),
   'GPS on this card gave no accuracy to measure from');
eq('a fix with no 2D/3D mode says so',
   MV.fixLine(MV.cardFix(card({ gpsMode: null, gpsOk: false, gpsWhy: 'nomode' })),
              'new'),
   'GPS on this card had no 2D/3D fix to measure from');
// The owner's VK-162 under gpsd's binary mode: one position repeated while
// the car drove. rpi/gps.py refuses it as `frozen`.
eq('a fix the GPS kept repeating while the car moved says it was stuck',
   MV.fixLine(MV.cardFix(card({ gpsOk: false, gpsWhy: 'frozen' })), 'new'),
   'GPS on this card was stuck on one spot, so nothing to measure from');
eq('a coordinate nobody judged is not a fix either',
   MV.fixLine(MV.cardFix(card({ gpsOk: undefined, gpsWhy: undefined })), 'new'),
   'GPS fix on this card was never judged, so nothing to measure from');

// The order in the car, checked against its OWN card the same way.
eq('the held order\'s end is checked against its own card',
   MV.againstCard(card({ miles: 9.4 }), SQUARE, HELD_END, 'Powder Springs Rd',
                  'held'),
   "wrong pin for Powder Springs Rd — 20.2 mi from your order's card, past "
   + 'its 9.4 mi');
eq('...and passes when its card allows it',
   MV.againstCard(card({ miles: 22.0 }), SQUARE, HELD_END, 'X', 'held'), null);
// A hold with no card is not a card without a fix: a holding.json written
// before the server kept the card has none, and nobody measured its GPS.
eq('a held order with no card says no card was kept, not that it had no fix',
   MV.fixLine(MV.cardFix(undefined), 'held'),
   'the rig kept no card for the order in your car, so its end cannot be '
   + 'checked');
eq('...while a held card that came up with no coordinate says that',
   MV.fixLine(MV.cardFix(card({ lat: null, lon: null, gpsOk: null })), 'held'),
   'the order in your car came up without a GPS fix, so its end cannot be '
   + 'checked');
eq('...and a rough one, with the figure',
   MV.fixLine(MV.cardFix(card({ gpsErr: 88.0, gpsOk: false, gpsWhy: 'rough' })),
              'held'),
   'GPS fix on the order in your car too rough to check its end (±88 m)');
eq('...and a stuck one',
   MV.fixLine(MV.cardFix(card({ gpsOk: false, gpsWhy: 'frozen' })), 'held'),
   'GPS on the order in your car was stuck on one spot, so its end cannot be '
   + 'checked');
eq('a held order on a one-leg card has no yardstick yet for its end',
   MV.againstCard(card({ hasTotal: false }), SQUARE, HELD_END, 'X', 'held'),
   'the order in your car is a kind of card with no yardstick yet for its end');
eq('...nor on an Early look card',
   MV.againstCard(card({ earlyLook: true }), SQUARE, HELD_END, 'X', 'held'),
   'the order in your car was an Early look card — no yardstick yet for its end');
// judge() and the disc share one rule and one slack, so they cannot drift.
// This asserted MV.SLACK_MI === 0.5, which says nothing about judge(): with
// judge's edge moved to 0.7 every check here still passed. So judge() is put
// at the disc's own edge, both sides, on the same 9.4 mi figure.
function judgedAt(pin) {
  return MV.judge([{ pickup: 'a', dropoff: 'b', miles: 9.4, whole: true }],
                  { a: SQUARE, b: pin })[0].impossible;
}
eq('judge() and the card\'s disc share the half mile: both pass just inside',
   JSON.stringify([judgedAt(EDGE_IN), MV.cardRefuses(card(), SQUARE, EDGE_IN)]),
   '[false,null]');
eq('...and both refuse just past it',
   JSON.stringify([judgedAt(EDGE_OUT), !!MV.cardRefuses(card(), SQUARE, EDGE_OUT)]),
   '[true,true]');
// cardRefuses is the fact live.html colours the pin by and words the line
// from: a figure withheld is not a pin refused, so a card with no yardstick
// refuses nothing, however far the pin.
eq('a card that is no yardstick refuses no pin, however far',
   MV.cardRefuses(card({ earlyLook: true }), SQUARE, WRONG_BRANCH), null);
eq('...nor does a card with no fix to measure from',
   MV.cardRefuses(card(), null, WRONG_BRANCH), null);
eq('the wrong branch is refused with the figures the line states',
   JSON.stringify(MV.cardRefuses(card({ milesCorrected: true }), SQUARE,
                                 WRONG_BRANCH),
                  function (k, v) { return k === 'crow' ? v.toFixed(1) : v; }),
   '{"crow":"21.8","miles":9.4,"corrected":true}');

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
/* Bounded at BOTH ends. The padding means this is no longer exactly sixty, so
   the check became "at least sixty" — and a bound that can only fail downward
   stops being a bound at all: a box a hundred times too wide, which searches
   half a continent and is the thing BOX_MILES exists to prevent, would pass it.
   The ceiling is the padding's own worst case, half a step of latitude, so it
   fails the moment the box grows for any reason other than the one intended. */
var halfLat = (box[1] - box[3]) * 69 / 2;
ok_('...sixty miles of latitude at least', halfLat >= 60);
ok_('...and not appreciably more than that (' + halfLat.toFixed(1) + ' mi)',
    halfLat <= 60 + (MV.ANCHOR_STEP / 2) * 69 + 0.5);
ok_('...and wider than that in longitude, at this latitude',
    (box[2] - box[0]) > (box[1] - box[3]));
eq('no anchor, no box', MV.boxAround(null), null);

/* ---- the same place, asked the same question --------------------------
 *
 * The anchor is a median over whichever rows are loaded, so it moves when a
 * card is added or the day range is changed. The box is part of the cache
 * key, so an anchor that moves is a place asked again — and the places it
 * costs are the ones you go back to.
 *
 * Snapped, an anchor moving within a cell asks the same question. These
 * three points are within a few hundred feet of each other, which is the
 * spread one more card of the same shop actually produces. */
var NEARBY = [{ lat: 34.0300, lon: -84.6000 },
              { lat: 34.0330, lon: -84.6012 },
              { lat: 34.0290, lon: -84.5980 }];
var keys = NEARBY.map(function (at) { return MV.boxAround(at); });
eq('an anchor that drifts a few hundred feet asks the same question',
   keys.filter(function (k) { return k !== keys[0]; }).length, 0);
// ...and not by making every question the same one. A place in the next
// metro is still a different question, or the box has stopped meaning
// anything.
no_('...while somewhere genuinely else is still a different one',
    MV.boxAround({ lat: 33.7490, lon: -84.3880 }) === keys[0]);

/* What the padding is for. Snapping moves the centre by up to half a step,
 * so without padding the snapped box would sit off to one side of the box
 * that was wanted and a place out the other side would fall outside it —
 * a narrower search that quietly misses the long deliveries, which is the
 * one direction BOX_MILES exists to prevent. The box must therefore
 * CONTAIN every point the true box would have. */
var worst = { lat: 34.0000 + MV.ANCHOR_STEP / 2, lon: -84.5000 + MV.ANCHOR_STEP / 2 };
var wb = MV.boxAround(worst).split(',').map(Number);
var reach = [[MV.BOX_MILES / 69, 0], [-MV.BOX_MILES / 69, 0],
             [0, MV.BOX_MILES / (69 * Math.cos(worst.lat * Math.PI / 180))],
             [0, -MV.BOX_MILES / (69 * Math.cos(worst.lat * Math.PI / 180))]];
ok_('...and still reaches sixty miles every way from where the car was',
    reach.every(function (d) {
      var la = worst.lat + d[0], lo = worst.lon + d[1];
      return lo >= wb[0] && lo <= wb[2] && la <= wb[1] && la >= wb[3];
    }));
// The cosine guard. Without the floor, a driver at the pole gets a division by
// something near zero and a box spanning the planet — which is not a box at
// all, and quietly turns the whole feature off while looking like it works.
var polar = MV.boxAround({ lat: 89.9, lon: 0 }).split(',').map(Number);
ok_('a box near the pole stays a box', isFinite(polar[0]) && polar[2] - polar[0] < 360);

/* ---- which place gets searched near where the car actually was ----------- */
var ROWS = [
  { pickup: 'Chipotle', dropoff: 'Duval Ct', lat: 33.90, lon: -84.50, gpsOk: true },
  { pickup: 'Chipotle', dropoff: 'Manchester Ln', lat: 33.92, lon: -84.52, gpsOk: true },
  // A fix rpi/gps.py's gate refused, far off: it must not pull the anchor.
  { pickup: 'Chipotle', dropoff: 'Kestrel Ct', lat: 34.80, lon: -85.40, gpsOk: false,
    gpsWhy: 'rough' },
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

/* ---- the town to search near, when nothing can be boxed ----------------
 *
 * On the owner's own week not one of 1,166 rows carried a position, so
 * `anchorFor` answered null for every place and every lookup went out as a
 * bare string to a world-wide geocoder. Half of this driver's distinct places
 * have no comma in them at all — "McDonald's", "Burger King", "Papa Johns
 * Pizza" — and handed one of those a geocoder returns a real one, confidently,
 * four thousand miles away. That is where the map's "nowhere near the rest"
 * list comes from.
 *
 * The cards already carry the answer, so this reads it back rather than
 * guessing at geography. */
var TOWNS = [
  { pickup: 'Chipotle (Barrett Pkwy), Marietta', dropoff: 'Oak Ln, Marietta' },
  { pickup: 'Zaxbys, Kennesaw', dropoff: 'Ring Rd NW, Marietta' },
  { pickup: 'McDonalds', dropoff: 'Cobb Pkwy, Marietta' },
  { pickup: 'Wendys', dropoff: 'Barrett Pkwy, Kennesaw' }
];
eq('the town the cards keep naming is what a bare name is searched near',
   MV.localityOf(TOWNS, ADV.area), 'Marietta');
// Counted over DISTINCT place strings, not over offers: one restaurant the
// driver is sent to forty times must not decide where the window is searched.
var REPEATED = [
  { pickup: 'Chipotle, Kennesaw' }, { pickup: 'Chipotle, Kennesaw' },
  { pickup: 'Chipotle, Kennesaw' }, { pickup: 'Chipotle, Kennesaw' },
  { pickup: 'A St, Marietta' }, { pickup: 'B St, Marietta' }
];
eq('...counted once per distinct place, not once per offer',
   MV.localityOf(REPEATED, ADV.area), 'Marietta');
// OCR wreckage is not a town. "ies, LAS" is one of the strings that really did
// produce a stray pin, and a hint taken off it would send the whole window to
// Nevada.
eq('a shouted OCR fragment is not taken for a town',
   MV.localityOf([{ pickup: 'ies, LAS' }, { dropoff: 'x, LAS' }], ADV.area), null);
eq('...nor is a number', MV.localityOf([{ pickup: 'Store, 414' }], ADV.area), null);
// A suite number reads as a town to anything that only asks "does it have a
// lowercase letter in it". The driver's own cards carry plenty — "ALDI (860
// Cobb Pl Blvd NW Ste 400)" — and a window searched near "Ste 400" is a window
// searched nowhere.
eq('a suite number is not a town',
   MV.localityOf([{ pickup: 'ALDI, Ste 400' }, { dropoff: 'x, Ste 400' }], ADV.area), null);
eq('...nor is a tail that starts small',
   MV.localityOf([{ pickup: 'x, total House' }, { dropoff: 'y, total House' }], ADV.area), null);
// ...and a real town still wins against a cardful of those, rather than the
// guard quietly rejecting everything.
eq('...while a real town among them still wins',
   MV.localityOf([{ pickup: 'ALDI, Ste 400' }, { dropoff: 'y, Smyrna' }], ADV.area), 'Smyrna');
// Nothing to go on is answered as nothing, so the page leaves the box empty
// and says so rather than inventing a metro.
eq('places with no town in them give no hint',
   MV.localityOf([{ pickup: 'McDonalds' }, { dropoff: 'Wendys' }], ADV.area), null);
eq('...and no offers at all give none', MV.localityOf([], ADV.area), null);
eq('...and neither does nothing', MV.localityOf(null, ADV.area), null);

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

/* ---- the same accusation, against a point that was measured ---------------
 *
 * straysAmong votes among the pins and needs a shift's worth to vote with. The
 * panel's map has two or three places, where the middle IS the midpoint of the
 * pair being judged — so it had no stray test at all, and a misread street
 * answered two states away was drawn, framed, and used as one end of the "out
 * of your way" figure. farFrom asks a different question: how far is this pin
 * from where the car actually WAS, which is measured rather than looked up. */
var CAR = { lat: 33.90, lon: -84.50 };
var FAR = MV.farFrom(CAR, FOUND);
eq('only the pin in another state is called wrong', Object.keys(FAR).length, 1);
ok_('...and it is named, with how far out it is', FAR['Daffodll Ln'] > 500);
// The case straysAmong cannot do at all, and it fails in the worse of the two
// possible ways. With two places its median is their midpoint, so BOTH come out
// equally far and both are accused — the good pin condemned alongside the bad
// one, on a pane that has exactly this many places.
var PAIR = { 'Chipotle': FOUND['Chipotle'], 'Daffodll Ln': FOUND['Daffodll Ln'] };
eq('the vote accuses both ends of a pair when one is wrong',
   Object.keys(MV.straysAmong(PAIR)).length, 2);
eq('...where the measured anchor accuses only the one that is',
   Object.keys(MV.farFrom(CAR, PAIR)).length, 1);
ok_('...and names it', !!MV.farFrom(CAR, PAIR)['Daffodll Ln']);
// A long job is not a bad lookup. The threshold is the same generous one the
// shift map uses, so what this catches is another state and not another county.
eq('a forty-mile job is not called wrong',
   Object.keys(MV.farFrom(CAR, { a: { lat: 34.5, lon: -84.5 } })).length, 0);
// No anchor, no accusation. A rig whose rows carry no position knows nothing
// new about these places, and guessing on thinner evidence is how a right pin
// gets called wrong.
eq('with no position the page accuses nothing',
   Object.keys(MV.farFrom(null, FOUND)).length, 0);
eq('...and a place with no answer is not accused either',
   Object.keys(MV.farFrom(CAR, { a: null })).length, 0);

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

/* ---- ...and only against a distance the rig itself stands behind ----------
 *
 * The accusation is made of two claims and the argument above carries only
 * one. A straight line cannot beat the ROAD — but where the reading holds a
 * fraction of the journey, the straight line beat a number that was never the
 * road, and the inequality comes out true while meaning nothing. The pins are
 * then blamed for a shortfall the READER produced, in the words "This cannot
 * be right", on the page whose whole job is to say whether the rig is right.
 *
 * Chipotle to Duval Ct is about 7.2 miles here, so a card carrying 3 is
 * accused by the old rule whatever else the row says. */
var SHORT = { pickup: 'Chipotle', dropoff: 'Duval Ct', miles: 3 };
var yard = MV.judge(
  [SHORT,
   // The shape that manufactures this: a leg lost its distance, so the sum is
   // a fraction of the journey and the reader said so by not calling it whole.
   // offer_parser.legs_short_a_distance measured one at 1.1 miles of a card
   // that printed 8.4.
   Object.assign({}, SHORT, { whole: false }),
   // ...and a row the reader would not vouch for at all.
   Object.assign({}, SHORT, { suspect: true }),
   // A row written before `whole` existed carries no such key, and those were
   // only ever written when whole. Same convention as advice.js's trustworthy;
   // without it this change would silently stop checking the older half of the
   // journal.
   Object.assign({}, SHORT, { whole: undefined })],
  FOUND, {});
ok_('a whole reading whose line beats its card is still accused',
    yard[0].impossible);
no_('...but a reading that stopped part-way through the journey is not',
    yard[1].impossible);
ok_('...it is marked unjudged instead, so the pair does not just vanish',
    yard[1].unjudged);
no_('...and a reading the rig called suspect is not accused either',
    yard[2].impossible);
ok_('...and is marked unjudged too', yard[2].unjudged);
ok_('a row too old to carry `whole` is judged, not quietly excused',
    yard[3].impossible);
// The two are exclusive by construction, and a surface that printed both would
// be accusing a pair in the same breath as saying it cannot be checked.
no_('an accused pair is never also unjudged', yard[0].unjudged);
/* ...and the flag the reader raises for the DISTANCE itself, which neither of
   the other two covers. rpi/test_journal.py asserts as a property that every
   route to `milesUncertain` also trips `suspect` or `whole === false` — true
   of the rig, and journal-client.js writes both of those as literals while
   reporting `milesUncertain` honestly off rate(). So this is the shape a card
   read by the PHONE's scanner arrives in: put the corpus's own damaged card
   `$16.05 3 min (1.1 mi) away 20 min (7.3 m1) trip` through the real
   journal-client and the row is 1.1 miles of an 8.4-mile job — the approach
   leg alone — flagged, whole and not suspect. Any two pins more than 1.6
   miles apart are then accused, which is every pair on a real card. */
var PHONE = Object.assign({}, SHORT,
                          { milesUncertain: true, whole: true, suspect: false });
var phoned = MV.judge([PHONE], FOUND, {})[0];
no_('a distance the reader would not trust cannot accuse a pin either',
    phoned.impossible);
ok_('...it is marked unjudged like the other two', phoned.unjudged);
ok_('...and named as the distance rather than the reading (' 
    + MV.unchecked(phoned) + ')',
    MV.unchecked(phoned).indexOf('would not trust') !== -1);
// Two pins and no figure at all is the older, separate case above: there is
// nothing to be unjudged ABOUT, and saying so would put a line on the majority
// of this driver's cards for a distance they never printed.
no_('a card that stated no distance is not reported as unchecked',
    noMiles[0].unjudged);
// One end placed is not a pair. Nothing is drawn between them, so there is no
// comparison to withhold and no sentence to write about withholding it.
no_('a job with one end is neither accused nor unjudged',
    judged[2].impossible || judged[2].unjudged);

/* ---- and what the figure beside the line actually is ---------------------
 *
 * check_distance divides a distance by ten to put back a decimal the read
 * lost: "9.5 mi" read as 95, a speed no car makes, repaired. rate() is right
 * to use the repair — but all three surfaces printed it as "card said 9.5 mi
 * total", and the card said 95. On the owner's week that is 328 of 1,166
 * offers, and 262 of the 579 that name both ends, so nearly half the lines
 * this page can draw attributed the rig's arithmetic to the screen. A driver
 * who goes back to the card to settle which pin is wrong finds 95 and
 * concludes the page is broken. */
var said = MV.judge(
  [{ pickup: 'Chipotle', dropoff: 'Duval Ct', miles: 9.5 },
   { pickup: 'Chipotle', dropoff: 'Duval Ct', miles: 9.5, milesCorrected: true }],
  FOUND, {});
eq('a figure off the card is reported as the card’s', MV.statedBy(said[0]),
   'card said 9.5 mi total');
no_('...and carries no correction', said[0].corrected);
ok_('a figure the rig repaired says so', said[1].corrected);
ok_('...in the words that do not put it in the card’s mouth ('
    + MV.statedBy(said[1]) + ')',
    MV.statedBy(said[1]).indexOf('card said') === -1);
ok_('...naming what was done to it',
    MV.statedBy(said[1]).indexOf('decimal') !== -1);
ok_('...and still giving the figure the line is measured against',
    MV.statedBy(said[1]).indexOf('9.5') !== -1);
// ...but NOT claiming this figure is the repaired one. rpi/accumulate.py ORs
// milesCorrected across the window and calls it advisory in as many words, so
// the flag means "some frame of this card needed a decimal put back", not
// "the card printed ten times this". A sentence that says otherwise sends a
// driver to the screen looking for a number that is not on it.
ok_('...without claiming the card printed ten times it ('
    + MV.statedBy(said[1]) + ')',
    MV.statedBy(said[1]).indexOf('put back') === -1
    || MV.statedBy(said[1]).indexOf('had to be put back') !== -1);
ok_('...and sending the driver to the screen rather than asserting the repair',
    MV.statedBy(said[1]).indexOf('check it against the screen') !== -1);
eq('a card with no distance has nothing to attribute',
   MV.statedBy(noMiles[0]), '');
// The two reasons a pair goes unchecked are different facts about the rig and
// a driver deciding whether to go and look at the crop needs the right one.
ok_('an unfinished reading says it is unfinished (' + MV.unchecked(yard[1]) + ')',
    MV.unchecked(yard[1]).indexOf('only part of this card was read') === 0);
ok_('...a suspect one says that instead',
    MV.unchecked(yard[2]).indexOf('suspect') !== -1);
ok_('...and both name the figure they are declining to use',
    MV.unchecked(yard[1]).indexOf('3 mi') !== -1
    && MV.unchecked(yard[2]).indexOf('3 mi') !== -1);
eq('a pair that WAS checked gets no such sentence', MV.unchecked(yard[0]), '');

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
/* ...and what became of the offers at that pin.
   `jobs` counts OFFERS, and most offers are turned down: a pin reading 12 on a
   shop the driver took two jobs from said they had worked there twelve times,
   in the largest glyph on the page. `accepted` is a tri-state and folding it to
   a boolean tells a different lie — a range where nothing was ever ticked would
   report "0 taken" of twelve, which reads as twelve refusals. */
var TALLY = MV.byPlace(MV.judge(
  [{ pickup: 'Chipotle', dropoff: 'Duval Ct', accepted: true },
   { pickup: 'Chipotle', dropoff: 'Manchester Ln', accepted: false },
   { pickup: 'Chipotle', dropoff: 'Duval Ct' }], FOUND, {}))[0];
eq('a pin counts every offer at the place', TALLY.jobs.length, 3);
eq('...the ones that were taken', TALLY.took, 1);
eq('...the ones that were passed on', TALLY.passed, 1);
// The state that matters most, because it is the commonest: a card nobody ever
// ticked either way. Counted as a refusal it would make a driver who does not
// use the tick look like one who turns everything down.
eq('...and the ones nobody marked, kept apart from both', TALLY.unmarked, 1);
eq('a range where nothing was ticked reports none taken and none refused',
   JSON.stringify([TALLY.took, TALLY.passed].length && MV.byPlace(MV.judge(
     [{ pickup: 'Chipotle', dropoff: 'Duval Ct' }], FOUND, {}))[0])
     .indexOf('"took":0,"passed":0,"unmarked":1') !== -1, true);

eq('a place used as both ends is one pin with both roles',
   MV.byPlace(MV.judge([{ pickup: 'Chipotle', dropoff: 'Duval Ct' },
                        { pickup: 'Duval Ct', dropoff: 'Chipotle' }], FOUND, {}))
     .filter(function (p) { return p.roles.pickup && p.roles.dropoff; }).length, 2);

/* ---- the shift in the order it happened ----------------------------------
 *
 * The miles between two jobs are the ones nobody pays for, and they are what
 * decides whether a stack was worth taking. The danger in drawing them is that
 * a journal is mostly offers that were DECLINED: join those in time order and
 * the map shows a route through places the car never went, which looks like
 * evidence and is fiction. So the gate is `accepted`, and it is checked first
 * because everything else here is only worth having if that holds. */
var HOUR = 3600000;
var T0 = 1700000000000;
var SHIFT = MV.chain(MV.judge([
  // Deliberately out of time order in the list: the journal is folded per
  // offer and nothing promises these arrive sorted.
  { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + HOUR,
    accepted: true, minutes: 20 },
  { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true, minutes: 20 },
  // Turned down. It sits between the two in neither time nor space, and it
  // must not appear in the chain at all.
  { pickup: 'Chipotle', dropoff: 'Manchester Ln', at: T0 + HOUR / 2, minutes: 20 }
], FOUND, strays));
eq('only the jobs that were ticked count as taken', SHIFT.taken, 2);
eq('...and two of them make one hop', SHIFT.hops.length, 1);
// The hop is the EMPTY run: out of where the last job ended, into where the
// next one began. Drawing pickup-to-pickup or dropoff-to-dropoff would be a
// line the car never drove.
eq('the hop leaves from where the first job ended', SHIFT.hops[0].fromName, 'Duval Ct');
eq('...and arrives where the next one began', SHIFT.hops[0].toName, 'Manchester Ln');
// The COORDINATE as well as the name, because the two are worked out from the
// same end separately. A line drawn between the right pair of points under the
// wrong pair of names, or the reverse, is a popup that lies about a line that
// is fine — and either half on its own cannot catch that.
eq('...from the coordinate that end resolved to',
   SHIFT.hops[0].from.lat, FOUND['Duval Ct'].lat);
eq('...to the coordinate the next one resolved to',
   SHIFT.hops[0].to.lon, FOUND['Manchester Ln'].lon);
ok_('...having sorted them by time and not by list order',
    SHIFT.hops[0].a.offer.at < SHIFT.hops[0].b.offer.at);
ok_('...and it has straight-line miles on it', SHIFT.hops[0].miles > 0);
no_('an hour apart on a twenty-minute job is not a stack', SHIFT.hops[0].stacked);

// A second offer that came up before the first was due to finish is a stack,
// and the line between them is then NOT an empty run — the popup says so, and
// it can only say so if this flag is right.
var STACK = MV.chain(MV.judge([
  { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true, minutes: 30 },
  { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + 6 * 60000,
    accepted: true, minutes: 30 }
], FOUND, {}));
ok_('an offer six minutes into a thirty-minute job is a stack', STACK.hops[0].stacked);
// A card that never stated a duration cannot say whether the next offer
// interrupted it — and `false` would read on the map exactly like "we checked,
// and it did not". Null is the third answer and the difference matters: these
// two offers are a minute apart, which under any stated duration at all would
// have come back true.
eq('a job with no stated minutes cannot say whether the next one stacked',
   MV.chain(MV.judge([
     { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true },
     { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + 60000, accepted: true }
   ], FOUND, {})).hops[0].stacked, null);
eq('...where a card that did state one answers yes or no',
   MV.chain(MV.judge([
     { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true, minutes: 20 },
     { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + HOUR, accepted: true }
   ], FOUND, {})).hops[0].stacked, false);

/* A pin in another state is a bad lookup, not a place. Chaining to one would
   drag the evening's route out to Illinois and back, and the empty miles the
   page quotes would be wrong by the width of four states. The job still
   belongs in the chain — it was taken — so the usable end stands in. */
var STRAYEND = MV.chain(MV.judge([
  { pickup: 'Chipotle', dropoff: 'Daffodll Ln', at: T0, accepted: true },
  { pickup: 'Manchester Ln', dropoff: 'Duval Ct', at: T0 + HOUR, accepted: true }
], FOUND, strays));
eq('a job whose dropoff landed in another state still joins the chain',
   STRAYEND.hops.length, 1);
eq('...leaving from the end that is not a stray', STRAYEND.hops[0].fromName, 'Chipotle');
ok_('...and the miles are a real shift, not four states',
    STRAYEND.hops[0].miles < 75);
// And the same on the way IN, which is a separate line of code reading a
// separate field: a stray PICKUP must not be what the chain arrives at either.
var STRAYSTART = MV.chain(MV.judge([
  { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0, accepted: true },
  { pickup: 'Daffodll Ln', dropoff: 'Duval Ct', at: T0 + HOUR, accepted: true }
], FOUND, strays));
eq('a job whose pickup landed in another state still joins the chain',
   STRAYSTART.hops.length, 1);
eq('...arriving at the end that is not a stray', STRAYSTART.hops[0].toName, 'Duval Ct');
ok_('...and the miles are a real shift, not four states',
    STRAYSTART.hops[0].miles < 75);

/* A taken job with nothing placeable does not break the chain and does not
   vanish from it either. It is stepped over, and the hop it fell inside
   carries the count — drawing across a gap without saying it is a gap is the
   same lie the rest of this page exists to refuse. */
var GAP = MV.chain(MV.judge([
  { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true },
  { pickup: 'Nowhere At All', dropoff: 'Nor Here', at: T0 + HOUR, accepted: true },
  { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + 2 * HOUR, accepted: true }
], FOUND, strays));
eq('a job that could not be placed does not break the chain', GAP.hops.length, 1);
eq('...and the hop says a job is unaccounted for inside it', GAP.hops[0].skipped, 1);
eq('...and it is still counted as taken', GAP.taken, 3);
eq('...and named as having no pin', GAP.unplaced, 1);
// The count belongs to the hop it fell inside and to no other. Carried
// forward, every later hop in the shift would claim a job went missing inside
// it too, and a driver checking the one real gap would find four.
var GAPTHEN = MV.chain(MV.judge([
  { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true },
  { pickup: 'Nowhere At All', dropoff: 'Nor Here', at: T0 + HOUR, accepted: true },
  { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + 2 * HOUR, accepted: true },
  { pickup: 'Duval Ct', dropoff: 'Manchester Ln', at: T0 + 3 * HOUR, accepted: true }
], FOUND, strays));
eq('the gap is reported once', GAPTHEN.hops[0].skipped, 1);
eq('...and the hop after it is clean', GAPTHEN.hops[1].skipped, 0);
// Counted over the whole list rather than off the running total, which resets
// at every hop — so an unplaceable job that came LAST would otherwise be
// dropped from the reckoning silently.
eq('a taken job with no pin at the end of the shift is still counted',
   MV.chain(MV.judge([
     { pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0, accepted: true },
     { pickup: 'Manchester Ln', dropoff: 'Chipotle', at: T0 + HOUR, accepted: true },
     { pickup: 'Nowhere At All', dropoff: 'Nor Here', at: T0 + 2 * HOUR, accepted: true }
   ], FOUND, strays)).unplaced, 1);

// Without a timestamp there is no order to put it in, and putting it first or
// last would be inventing one.
eq('a taken job with no time cannot be placed in an order',
   MV.chain(MV.judge([{ pickup: 'Chipotle', dropoff: 'Duval Ct', accepted: true }],
                     FOUND, {})).taken, 0);

// The offers page calls this on every draw, before anybody has ticked
// anything. It must answer nothing rather than throw.
eq('an empty range has no hops', MV.chain([]).hops.length, 0);
eq('...and nothing taken', MV.chain([]).taken, 0);
eq('...and no argument at all is the same', MV.chain().hops.length, 0);
eq('a range with nothing ticked draws no chain',
   MV.chain(MV.judge([{ pickup: 'Chipotle', dropoff: 'Duval Ct', at: T0 }],
                     FOUND, {})).taken, 0);

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
    store: opts.store || null,
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

/* ---- the NucBox: searching inside the card's disc, and the road -----------
 *
 * Against the REAL server.js, relaying to tests/fake-nucbox.js — the one fake
 * NucBox the three suites share, in the real install's answer shapes — so
 * what is checked is the page's half and the server's half together, through
 * real HTTP. Every point is invented round Marietta Square (33.9526,
 * -84.5499) and the public places near it; distances from the Square,
 * measured with crowMiles: the fake's McDonald's are 2.10 mi (north), 5.49
 * (Cumberland), 10.64 (Kennesaw) and 21.81 (Acworth); Shadowood Parkway's two
 * pieces are 7.27 away and 0.275 apart; 1985 Cobb Parkway is 3.36; the two
 * Church Streets 0.39 (Marietta) and 5.23 (Smyrna). */
function startServer(env) {
  var cp = require('child_process'), path = require('path'), os = require('os');
  var fs = require('fs'), net = require('net');
  return new Promise(function (resolve, reject) {
    var probe = net.createServer().listen(0, '127.0.0.1', function () {
      var port = probe.address().port;
      probe.close(function () {
        var dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mvnbx-'));
        var proc = cp.spawn('node', [path.join(__dirname, '..', 'server.js')], {
          env: Object.assign({}, process.env, env, {
            PORT: String(port), HTTPS_PORT: '0', SCANNER: '0',
            JOURNAL: path.join(dir, 'journal.jsonl') }),
          stdio: 'ignore' });
        var base = 'http://127.0.0.1:' + port;
        var tries = 0;
        (function poll() {
          fetch(base + '/api/status').then(function () {
            resolve({ base: base, stop: function () { proc.kill(); } });
          }, function () {
            if (++tries > 100) { proc.kill(); reject(new Error('server never came up')); }
            else setTimeout(poll, 100);
          });
        }());
      });
    });
  });
}

// The street index of tests/fixtures/streets.osm, made by the real exporter
// from osmium's committed OPL into a directory of its own.
function streetIndex() {
  var path = require('path'), fs = require('fs'), os = require('os');
  var dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mvidx-'));
  var file = path.join(dir, 'streets.json');
  require('child_process').execFileSync('python3', [
    path.join(__dirname, '..', 'tools', 'street_index.py'),
    path.join(__dirname, 'fixtures', 'streets.osm'), file,
    '--opl', path.join(__dirname, 'fixtures', 'streets.opl')], { stdio: 'ignore' });
  return { file: file, drop: function () { fs.rmSync(dir, { recursive: true, force: true }); } };
}

async function nucbox() {
  var FAKE = require('./fake-nucbox.js');
  var SQ = { lat: 33.9526, lon: -84.5499 };
  function card(o) {
    return Object.assign({ lat: SQ.lat, lon: SQ.lon, gpsAge: 0.6, gpsErr: 12, gpsMode: 3,
                           gpsOk: true, gpsWhy: null, miles: 9.4, hasTotal: true,
                           legs: 2, whole: true }, o || {});
  }
  function hitsOf(list) {
    return list.map(function (h) {
      return { lat: Number(h.lat), lon: Number(h.lon), name: h.display_name };
    });
  }

  /* What is asked, by the shape of the string. */
  eq('a bracket that opens with a house number is asked as that street',
     JSON.stringify(MV.searchPlan("Jimmy John's (1985 Cobb Parkway NW)")),
     JSON.stringify({ kind: 'street', street: '1985 Cobb Parkway NW', door: true,
                      house: '1985' }));
  eq('...and one the card\'s edge cut off is still the street',
     MV.searchPlan("Culver's (1275 Hwy").street, '1275 Hwy');
  eq('"Street, Town" is the street, the town not kept at all',
     JSON.stringify(MV.searchPlan('Shadowood Pkwy SE, Atlanta Pverel')),
     JSON.stringify({ kind: 'street', street: 'Shadowood Pkwy SE', door: false,
                      house: null }));
  eq('...and the Trip Planner\'s door line the same, a door with its number',
     JSON.stringify(MV.searchPlan('77 Birch Ln NW, Roswell, GA 30075')),
     JSON.stringify({ kind: 'street', street: '77 Birch Ln NW', door: true,
                      house: '77' }));
  eq('cross streets are not asked of a search that answers one point a street',
     JSON.stringify(MV.searchPlan('Birch Ln & Kestrel Dr, Roswell')),
     JSON.stringify({ kind: 'cross', a: 'Birch Ln', b: 'Kestrel Dr' }));
  // 63 of the week's 403 corner dropoffs came off the card with no comma, a
  // town or the OCR's litter run on after the second street: those go to
  // Nominatim as a name, as they always did, never to the street index
  // (README "Corners and streets").
  eq('a corner with no comma before its town is asked as a name, not as a corner',
     JSON.stringify(MV.searchPlan('Birch Ln & Kestrel Dr NE Roswell')),
     JSON.stringify({ kind: 'name', q: 'Birch Ln & Kestrel Dr NE Roswell' }));
  eq('...and three names, or an empty one, are not a corner',
     JSON.stringify([MV.searchPlan('Atami Grill & Sushi Atwater Dr & Kolora Chase, Smyrna'),
                     MV.searchPlan(' & Kolora Chase, Smyrna')]),
     JSON.stringify([{ kind: 'cross', a: null, b: null }, { kind: 'cross', a: null, b: null }]));
  eq('a merchant is asked by name, its "(Plaza)" dropped',
     JSON.stringify(MV.searchPlan("McDonald's (Marietta Sq)")),
     JSON.stringify({ kind: 'name', q: "McDonald's" }));

  /* The disc: the card's fix, its distance plus the half mile. */
  var d94 = MV.discFor(card());
  eq('a card with a fix and a yardstick is searched in its own distance plus '
     + 'the half mile', d94.miles, 9.9);
  eq('...a card with a fix and no yardstick in the sixty miles the public box '
     + 'stands for', JSON.stringify([MV.discFor(card({ legs: 1, hasTotal: false })).miles,
                                     MV.discFor(card({ legs: 1, hasTotal: false })).card]),
     JSON.stringify([60, null]));
  eq('...and a card with no fix the gate passed in nothing',
     MV.discFor(card({ gpsOk: false, gpsWhy: 'rough', gpsErr: 129.2 })), null);
  var vb = MV.discBox(d94).split(',').map(Number);
  ok_('the box asked for holds the whole disc (' + vb.join(',') + ')',
      [{ lat: SQ.lat + 9.9 / 69, lon: SQ.lon }, { lat: SQ.lat - 9.9 / 69, lon: SQ.lon },
       { lat: SQ.lat, lon: SQ.lon + 9.9 / (69 * Math.cos(SQ.lat * Math.PI / 180)) },
       { lat: SQ.lat, lon: SQ.lon - 9.9 / (69 * Math.cos(SQ.lat * Math.PI / 180)) }]
        .every(function (p) {
          return p.lon >= vb[0] && p.lat <= vb[1] && p.lon <= vb[2] && p.lat >= vb[3];
        }));

  /* Choosing among the candidates — pickInDisc, on all four branches at once,
     so the disc and not the box is what decides. */
  var mcd = hitsOf(FAKE.MCD);
  var one = MV.pickInDisc(mcd, MV.discFor(card({ miles: 3.0 })), MV.searchPlan("McDonald's"));
  eq('the disc keeps the one branch inside a 3.0 mi card\'s distance, of four',
     one.at && [one.at.lat, one.at.lon, one.n].join(','), '33.983,-84.5499,1');
  var two = MV.pickInDisc(mcd, d94, MV.searchPlan("McDonald's"));
  eq('...and refuses two inside a 9.4 mi card that are not one place',
     JSON.stringify([two.at, two.why, two.n]), JSON.stringify([null, 'several', 2]));
  var far = MV.pickInDisc(mcd, MV.discFor(card({ lat: 33.9700, lon: -84.5650, miles: 0.6 })),
                          MV.searchPlan("McDonald's"));
  eq('...and refuses when none is inside, saying how far the nearest was',
     JSON.stringify([far.at, far.why, typeof far.nearest === 'number' ? far.nearest.toFixed(2) : null]),
     JSON.stringify([null, 'none', '1.25']));
  var street = MV.pickInDisc(hitsOf(FAKE.SHADOWOOD), d94,
                             MV.searchPlan('Shadowood Pkwy SE, Atlanta'));
  ok_('a street answered in two pieces 0.275 mi apart is one street, pinned between them',
      street.at && Math.abs(street.at.lat - 33.8779) < 0.0001);
  var church = hitsOf(FAKE.CHURCH);
  var tie = MV.pickInDisc(church, d94, MV.searchPlan('Church St, Marietta'));
  eq('two streets of one name in two towns, both inside, are refused whatever '
     + 'the card\'s town says', JSON.stringify([tie.at, tie.why, tie.n]),
     JSON.stringify([null, 'several', 2]));
  /* The verifier's probe: the street in Cumberland and a namesake 1.35 mi
     off whose OSM address says Atlanta, both inside a 3.0 mi card. The
     card's postal "Atlanta" pinned the namesake when the town broke ties. */
  var shadow2 = MV.pickInDisc(
    [{ lat: 33.94, lon: -84.52, name: 'Shadowood Parkway Southeast, Cumberland, Cobb County, Georgia' },
     { lat: 33.925, lon: -84.505, name: 'Shadowood Parkway Southeast, Atlanta, Fulton County, Georgia' }],
    MV.discFor(card({ miles: 3.0 })), MV.searchPlan('Shadowood Pkwy SE, Atlanta'));
  eq('...so "Shadowood Pkwy SE, Atlanta" with a namesake in OSM\'s Atlanta 1.35 mi '
     + 'off is refused, not pinned on the word Atlanta',
     JSON.stringify([shadow2.at, shadow2.why]), JSON.stringify([null, 'several']));
  eq('...and the town is never a filter: a lone candidate in another town is used',
     (MV.pickInDisc(church.slice(1), d94, MV.searchPlan('Church St, Marietta')).at || {}).lat,
     33.883);

  /* The words. The refusal leads, so the clamp keeps "no pin for". */
  eq('none inside, the card\'s words',
     MV.nbxRefusal(far, MV.discFor(card({ lat: 33.97, lon: -84.565, miles: 0.6 })),
                   "McDonald's", 'new'),
     "no pin for McDonald's — none fit the card · within 0.6 mi of you, nearest 1.2 mi");
  eq('several, the card\'s words',
     MV.nbxRefusal(two, d94, "McDonald's", 'new'),
     "no pin for McDonald's — 2 fit the card and disagree · within 9.4 mi of you");
  eq('several, the held card\'s words, with the rig\'s repair named',
     MV.nbxRefusal(two, MV.discFor(card({ miles: 22, milesCorrected: true })), 'Held End',
                   'held'),
     'no pin for Held End — 2 fit its card and disagree · within 22 mi (rig-corrected)');
  eq('several with no fix to choose by',
     MV.nbxRefusal({ at: null, why: 'several', n: 10 }, null, "McDonald's", 'new'),
     "no pin for McDonald's — 10 found · no GPS fix to choose between them");
  eq('none within the sixty miles of a card with no yardstick',
     MV.nbxRefusal({ why: 'none', nearest: null }, MV.discFor(card({ legs: 1, hasTotal: false })),
                   'X', 'held'),
     "no pin for X — none found · within 60 mi of your order's card");
  eq('an answer of no kind this knows is no line at all',
     MV.nbxRefusal({ at: null, why: 'unreachable' }, d94, 'X', 'new'), null);
  eq('a cross street with no street index to ask',
     MV.nbxRefusal({ why: 'cross' }, d94, 'Birch Ln…', 'new'),
     'no pin for Birch Ln… — no street index to ask');
  eq('a pin is no refusal', MV.nbxRefusal(one, d94, "McDonald's", 'new'), null);

  /* A door asked, its street answered: never pinned as the door. */
  var d30 = MV.discFor(card({ miles: 3.0 }));
  var kestrel = MV.pickInDisc(hitsOf(FAKE.KESTREL), d30, MV.searchPlan('4821 Kestrel Dr, Marietta'));
  eq('a house number answered only by its street is refused, not pinned as the door',
     JSON.stringify([kestrel.at, kestrel.why]), JSON.stringify([null, 'nodoor']));
  eq('...in words that say the street was found and not the door',
     MV.nbxRefusal(kestrel, d30, '4821 Kestrel Dr, Marietta', 'new'),
     'no pin for 4821 Kestrel Dr, Marietta — street found, not that door');
  eq('...while the same street asked with no number is pinned as the street',
     (MV.pickInDisc(hitsOf(FAKE.KESTREL), d30, MV.searchPlan('Kestrel Dr, Marietta')).at || {}).lat,
     33.97);
  ok_('...and a door is read off the first two parts of the name, so the '
      + 'postcode is never taken for the house number',
      MV.hasDoor({ name: '1985, Cobb Parkway, Kennesaw' }, '1985')
      && MV.hasDoor({ name: "McDonald's, 1155, Roswell Street Northeast" }, '1155')
      && !MV.hasDoor({ name: 'Kestrel Drive, Marietta, Cobb County, Georgia, 30060' }, '30060'));

  /* A list cut at the limit proves nothing about what is inside the disc. */
  var sb = hitsOf(FAKE.STARBUCKS.slice(0, 10));
  var sbOne = MV.pickInDisc(sb, d30, MV.searchPlan('Starbucks'), null);
  eq('ten candidates with one inside a 3.0 mi card would pin that one if the '
     + 'list were whole', sbOne.at && sbOne.at.lat, 33.9671);
  var sbCut = MV.pickInDisc(sb, d30, MV.searchPlan('Starbucks'), 10);
  eq('...and cut at the limit, it is refused: "only one fits" is not proven',
     JSON.stringify([sbCut.at, sbCut.why, sbCut.n]), JSON.stringify([null, 'capped', 10]));
  eq('...nor is "none fits" of a cut list',
     MV.pickInDisc(sb.slice(1), d30, MV.searchPlan('Starbucks'), 10).why, 'capped');
  eq('...in words that say there were too many to be sure',
     MV.nbxRefusal(sbCut, d30, 'Starbucks', 'new'),
     'no pin for Starbucks — too many to be sure · the NucBox lists 10 at most');
  eq('a question the rig refused is said as a bug',
     MV.nbxRefusal({ at: null, why: 'refused', error: 'refused: limit' }, d30, 'X', 'new'),
     'no pin for X — a bug: the rig refused the question');

  /* The road figure's two refusals, at their bounds, off a stub of the relay. */
  function stubRoad(by, direct, snapBy, snapDirect) {
    return new MV.NbxSearch({ gap: 0, fetch: function (u) {
      var three = decodeURIComponent(u).split(';').length === 3;
      return Promise.resolve({ ok: true, status: 200, json: function () {
        return Promise.resolve(three ? { ok: true, metres: by, snaps: snapBy || [3, 3, 3] }
                                     : { ok: true, metres: direct, snaps: snapDirect || [3, 3] });
      } });
    } });
  }
  var P1 = { lat: 33.95, lon: -84.55 }, P2 = { lat: 33.96, lon: -84.54 }, P3 = { lat: 33.97, lon: -84.53 };
  eq('a road detour a hair below zero (-0.037 mi) is the panel\'s 0.0 and stands',
     ((await stubRoad(1000, 1060).detour(P1, P2, P3)).miles || 0).toFixed(3), '-0.037');
  eq('...past the rounding (-0.062 mi) the router took different roads, and no '
     + 'figure is stated', JSON.stringify(await stubRoad(1000, 1100).detour(P1, P2, P3)),
     JSON.stringify({ why: 'otherroads' }));
  eq('a point the router moved 321 m (under 0.2 mi) to reach a road leaves the figure',
     typeof (await stubRoad(3000, 2000, [3, 321, 3]).detour(P1, P2, P3)).miles, 'number');
  eq('...and one moved 323 m (over 0.2 mi) refuses it, on either route',
     JSON.stringify([await stubRoad(3000, 2000, [3, 323, 3]).detour(P1, P2, P3),
                     await stubRoad(3000, 2000, null, [323, 3]).detour(P1, P2, P3)]),
     JSON.stringify([{ why: 'snap' }, { why: 'snap' }]));

  /* Through the real server.js and the fake NucBox. */
  /* A numberless street's stretch, kept inside the disc (MV.stretchInDisc).
     Lines are [[lat, lon], ...], as the street index sends them. */
  var d1 = MV.discFor(card({ miles: 0.5 }));                  // 1.0 mi round the Square
  var across = [[[SQ.lat, -84.60], [SQ.lat, -84.50]]];         // through it, ends far out
  var runs = MV.clipToDisc(across, d1);
  var ends = runs.length === 1 ? [runs[0][0], runs[0][runs[0].length - 1]] : [];
  ok_('a segment with both ends outside the disc is kept for the part through it, '
      + 'cut at the edge (' + ends.map(function (p) { return MV.crowMiles(SQ, p).toFixed(4); }) + ')',
      ends.length === 2 && ends.every(function (p) {
        var d = MV.crowMiles(SQ, p);
        return d <= 1.0 && d > 0.999;
      }));
  var inOut = [[[SQ.lat, -84.5499], [SQ.lat, -84.53], [SQ.lat + 0.001, -84.53],
                [SQ.lat + 0.001, -84.5499]]];                  // out east and back
  eq('...and a line that leaves the disc and comes back is two runs, never a '
     + 'chord across the outside', MV.clipToDisc(inOut, d1).length, 2);
  var lark = [[[33.948, -84.565], [33.948, -84.56], [33.948, -84.552]],
              [[33.88, -84.47], [33.88, -84.46]]];             // the fixture's Larkspur
  var d3 = MV.discFor(card({ miles: 3.0 }));
  var st3 = MV.stretchInDisc(lark, d3, SQ, 'Larkspur Parkway Southeast');
  eq('a stretch is pinned at its point nearest the car — here its east end',
     st3.at && [st3.at.lat, st3.at.lon, st3.at.nearestOf].join(','), '33.948,-84.552,true');
  eq('...and with the car at its west end, there: the pin is the car\'s, not the street\'s',
     (MV.stretchInDisc(lark, d3, { lat: 33.948, lon: -84.58 }, 'L').at || {}).lon, -84.565);
  eq('...carrying the part of the street inside the disc, for the figure along it',
     JSON.stringify(st3.at && st3.at.stretch), JSON.stringify([lark[0]]));
  var st94 = MV.stretchInDisc(lark, d94, SQ, 'L');
  eq('two stretches of one name 6.4 mi apart, both inside a 9.4 mi card, are two '
     + 'streets, refused', JSON.stringify([st94.at, st94.why, st94.n]),
     JSON.stringify([null, 'several', 2]));
  var stOut = MV.stretchInDisc([lark[1]], d3, SQ, 'L');
  eq('...and a stretch wholly outside the disc is none, with how far it was',
     [stOut.why, stOut.nearest && stOut.nearest.toFixed(1)].join(','), 'none,6.8');

  /* The figure to a numberless street (MV.stretchSpan): the detour at every
     point of its stretch in the disc, stated only where it is one answer.
     The cases are q8v/nearest.js's, where the figure was measured to the
     pin nearest the car: a street running 8 mi north-south a mile east of
     the car, in a 6.5 mi disc, showed true +1.5 as +0.6, true +0.7 as "on
     your way" and true +0.4 as +5.1. */
  var CAR = { lat: 33.95, lon: -84.55 };
  function mi(eastMi, northMi) {
    return { lat: CAR.lat + northMi / 69.0,
             lon: CAR.lon + eastMi / (69.0 * Math.cos(CAR.lat * Math.PI / 180)) };
  }
  function road(x0, y0, x1, y1) {
    var line = [];
    for (var k = 0; k <= 80; k++) {
      var q = mi(x0 + (x1 - x0) * k / 80, y0 + (y1 - y0) * k / 80);
      line.push([q.lat, q.lon]);
    }
    return [line];
  }
  function spanOf(lines, discMi, pickAt, truth) {
    var dsc = { at: CAR, miles: discMi, card: discMi, corrected: false };
    var pin = MV.stretchInDisc(lines, dsc, CAR, 'S').at;
    var sp = MV.stretchSpan(CAR, pickAt, pin);
    return { sp: sp, pinFig: MV.detour(CAR, pickAt, pin), truth: MV.detour(CAR, pickAt, truth) };
  }
  var longRoad = road(1, -4, 1, 4);
  var cases = [spanOf(longRoad, 6.5, mi(1, 0.5), mi(1, -3)),
               spanOf(longRoad, 6.5, mi(1, 0.2), mi(1, 3)),
               spanOf(longRoad, 6.5, mi(0.5, 3), mi(1, 3))];
  eq('a figure to the pin nearest the car was wrong by up to five miles: true '
     + '+1.5, +0.7, +0.4 against the pin\'s',
     cases.map(function (c) { return c.truth.toFixed(1) + '/' + c.pinFig.toFixed(1); }).join(' '),
     '1.5/0.6 0.7/0.2 0.4/5.1');
  eq('...and each is refused now: the figure along the street runs from 0.0 to as '
     + 'much as 5.9, not one answer',
     cases.map(function (c) { return c.sp.stated + ' ' + c.sp.lo.toFixed(1) + '-' + c.sp.hi.toFixed(1); })
       .join(', '), 'false 0.0-1.5, false 0.0-1.1, false 0.0-5.9');
  eq('...in words that lead with the refusal and say how long the street runs in '
     + 'the card', MV.spanRefusal(cases[0].sp, 'Long St', 'held'),
     'no figure for Long St — the street runs 8.0 mi in its card');
  eq('...or this card\'s', MV.spanRefusal(cases[0].sp, 'Long St', 'new'),
     'no figure for Long St — the street runs 8.0 mi in the card');
  var short6 = spanOf(road(-0.3, 2, 0.3, 2), 4, mi(1, 0), mi(-0.2, 2));
  eq('a 0.6 mi street whose figure goes from +1.1 to +1.4 along it is stated, as that '
     + 'range, with the truth (+1.3) inside it',
     [short6.sp.stated, short6.sp.lo.toFixed(1), short6.sp.hi.toFixed(1),
      short6.truth >= short6.sp.lo && short6.truth <= short6.sp.hi].join(','),
     'true,1.1,1.4,true');
  eq('...and no words to refuse it with', MV.spanRefusal(short6.sp, 'S', 'new'), null);
  var wide15 = spanOf(road(-0.75, 2, 0.75, 2), 4, mi(1, 0), mi(0.6, 2));
  eq('the same street 1.5 mi long goes from +0.9 to +1.5: half a mile or more apart '
     + 'is refused', [wide15.sp.stated, wide15.sp.lo.toFixed(1), wide15.sp.hi.toFixed(1)].join(','),
     'false,0.9,1.5');
  var onWay = spanOf(road(-0.15, 3, 0.15, 3), 4, mi(0, 1), mi(0.1, 3));
  eq('a short street straight ahead is "on your way" from every point of it',
     [onWay.sp.stated, onWay.sp.hi < MV.ON_WAY_MI].join(','), 'true,true');
  // A held end on a street 2 mi ahead, the pickup 1 mi ahead: the figure
  // is 0 where the street crosses the way straight on, and grows either side.
  function heldOn(x0, x1) {
    return { lat: 0, lon: 0, stretch: [[[mi(x0, 2).lat, mi(x0, 2).lon],
                                        [mi(x1, 2).lat, mi(x1, 2).lon]]] };
  }
  // The cut "on your way" is said under. A span across it is refused even
  // when it is narrow: "on your way" at one end and not at the other.
  var straddle = MV.stretchSpan(CAR, mi(0, 1), heldOn(2, 3));
  eq('a figure from +0.4 to +0.6 is refused: "on your way" at one end, not the other',
     [straddle.stated, straddle.lo.toFixed(1), straddle.hi.toFixed(1)].join(','),
     'false,0.4,0.6');
  // ...and measured at every point, not at the ends: a street 6 mi long
  // crossing the way has its least, 0, in the middle, where both its ends
  // are +0.6. Measured at its ends it was +0.6 at both, stated as one figure.
  var across = MV.stretchSpan(CAR, mi(0, 1), heldOn(-3, 3));
  eq('...and measured along the street, not at its ends: one crossing the way ahead '
     + 'has its least, 0.0, in the middle, so it is refused',
     [across.stated, across.lo.toFixed(1), across.hi.toFixed(1)].join(','), 'false,0.0,0.6');
  eq('no stretch at either end is no span: the figure is the pins\' own',
     MV.stretchSpan(CAR, mi(0, 1), mi(0, 2)), null);

  /* The words for a corner. */
  eq('a corner whose streets meet twice in the card',
     MV.nbxRefusal({ why: 'corners', n: 2 }, d3, 'Juniper Cir…', 'new'),
     'no pin for Juniper Cir… — 2 corners fit the card · within 3 mi of you');
  eq('...and that do not meet in it, with the nearest meeting',
     MV.nbxRefusal({ why: 'nomeet', nearest: 1.21 }, d3, 'X', 'held'),
     'no pin for X — none fit its card · within 3 mi, nearest 1.2 mi');
  eq('...and with no fix at all', MV.nbxRefusal({ why: 'nomeet', nearest: null }, null, 'X', 'new'),
     'no pin for X — its streets do not meet');
  eq('...and that run together', MV.nbxRefusal({ why: 'together', n: 1 }, d3, 'X', 'new'),
     'no pin for X — its streets run together');
  eq('...and that names a street the NucBox does not hold',
     MV.nbxRefusal({ why: 'nostreet' }, d3, 'X', 'new'),
     'no pin for X — a street name not on the NucBox');
  eq('...and that is not two names', MV.nbxRefusal({ why: 'notwo' }, d3, 'X', 'new'),
     'no pin for X — not two street names');
  eq('a stretch too long to send', MV.nbxRefusal({ why: 'long', n: 8000 }, d3, 'X', 'new'),
     'no pin for X — street too long to be sure · the NucBox sends 8000 points at most');
  // A corner list the index cut at its limit, off a stub of the relay.
  var cutCorner = await new MV.NbxSearch({ gap: 0, fetch: function () {
    return Promise.resolve({ ok: true, status: 200, json: function () {
      return Promise.resolve({ ok: true, a: { names: ['A'] }, b: { names: ['B'] },
                               meets: [], cutAt: 50 });
    } });
  } }).place('A St & B St, Town', d3, { streets: true });
  eq('...and a corner list cut at its limit is too many to be sure, not "none meet"',
     [cutCorner.why, cutCorner.n].join(','), 'capped,50');

  var fake = await new Promise(function (r) { FAKE.start(r); });
  var fb = 'http://127.0.0.1:' + fake.port;
  // The NucBox's own server.js holding the street index of the fixture
  // streets (tests/streets.test.js), made by the real exporter from
  // osmium's OPL.
  var idx = streetIndex();
  var nuc = await startServer({ NUCBOX_STREETS_FILE: idx.file });
  var nucShort = await startServer({ NUCBOX_STREETS_FILE: idx.file,
                                     NUCBOX_STREETS_POINTS_MAX: '5' });
  var on = await startServer({ NUCBOX_SEARCH: fb, NUCBOX_ROUTER: fb, NUCBOX_STREETS: nuc.base });
  var onShort = await startServer({ NUCBOX_SEARCH: fb, NUCBOX_STREETS: nucShort.base });
  var off = await startServer({});
  var down = await startServer({ NUCBOX_SEARCH: 'http://127.0.0.1:9',
                                 NUCBOX_ROUTER: 'http://127.0.0.1:9',
                                 NUCBOX_STREETS: 'http://127.0.0.1:9' });
  try {
    function via(srv) { return function (u) { return fetch(srv.base + u); }; }
    eq('with nothing set the page is told none is, and does what it always did',
       JSON.stringify(await MV.nbxSettings(via(off))),
       JSON.stringify({ search: false, route: false, streets: false }));
    eq('...and set, all three', JSON.stringify(await MV.nbxSettings(via(on))),
       JSON.stringify({ search: true, route: true, streets: true }));
    eq('...and a server that cannot be reached is none, not a page that stops',
       JSON.stringify(await MV.nbxSettings(function () { return Promise.reject(new Error('x')); })),
       JSON.stringify({ search: false, route: false, streets: false }));

    var nbx = new MV.NbxSearch({ base: on.base + '/api/nbx' });
    var got = await nbx.place("McDonald's", MV.discFor(card({ miles: 3.0 })));
    eq('through the server, a 3.0 mi card\'s McDonald\'s is the one 2.1 mi north',
       got.at && [got.at.lat, got.at.lon].join(','), '33.983,-84.5499');
    got = await nbx.place("McDonald's (Marietta Sq)", d94);
    eq('...and a 9.4 mi card\'s is refused as two that disagree',
       [got.why, got.n].join(','), 'several,2');
    var n0 = fake.asked.length;
    got = await nbx.place('Shadowood Pkwy SE, Atlanta', d94);
    var sent = fake.asked.slice(n0).join(' ');
    ok_('"Shadowood Pkwy SE, Atlanta" is pinned in Cumberland, where OSM has it',
        got.at && /Cumberland/.test(got.at.name));
    ok_('...asked as the street alone, the town left at home (' + sent + ')',
        /street=Shadowood%20Pkwy%20SE&/.test(sent) && !/Atlanta/i.test(sent)
        && !/city=/.test(sent));
    got = await nbx.place("Jimmy John's (1985 Cobb Parkway NW)", d94);
    ok_('a bracketed door is pinned at 1985, Cobb Parkway, Kennesaw — the postal '
        + 'town on the card was never asked', got.at && /^1985, Cobb Parkway, Kennesaw/.test(got.at.name));
    got = await nbx.place('4821 Kestrel Dr, Marietta', d94);
    eq('through the server, a door the NucBox answers with only its street is '
       + 'refused as the street', [got.at, got.why].join(','), ',nodoor');
    got = await nbx.place('Starbucks', MV.discFor(card({ miles: 3.0 })));
    eq('...and twelve Starbucks cut at ten, one inside a 3.0 mi card, are too many '
       + 'to be sure', [got.at, got.why, got.n].join(','), ',capped,10');
    got = await nbx.place('X'.repeat(121), d94);
    eq('...and a question the relay refuses is a bug said with its reason, not a '
       + 'NucBox that is down', [got.why, got.error].join(' | '),
       'refused | q must be 1 to 120 printable characters');
    n0 = fake.asked.length;
    got = await nbx.place('Birch Ln & Kestrel Dr, Roswell', d94);
    eq('a cross street is refused without asking anybody',
       [got.why, fake.asked.length - n0].join(','), 'cross,0');

    /* Corners and stretches, through this rig's server to the NucBox's
       street index. The fixture's corners are a few tenths of a mile from
       the Square; its Juniper Circle meets Northgate Drive twice. */
    var ST = { streets: true, car: SQ };
    var nbxS = new MV.NbxSearch({ base: on.base + '/api/nbx' });
    got = await nbxS.place('Foxglove Trl & Northgate Dr, Marietta', d3, ST);
    eq('a corner the card names is pinned where its two streets meet',
       got.at && [got.at.lat, got.at.lon, got.at.name].join(','),
       '33.96,-84.55,Foxglove Trail & Northgate Drive');
    eq('...as the card\'s reader misread it too ("Foxglove Tri")',
       ((await nbxS.place('Foxglove Tri & Northgate Dr, Marietta', d3, ST)).at || {}).lat, 33.96);
    var askedS = Object.keys(nbxS.cache).join(' ');
    ok_('...asked as its two streets inside the disc\'s box, the town left at home ('
        + askedS.slice(0, 90) + ')',
        /\/cross\?a=Foxglove%20Trl&b=Northgate%20Dr&box=/.test(askedS) && !/Marietta/.test(askedS));
    got = await nbxS.place('Wren Rd & Kestrel Pkwy SE, Marietta', d3, ST);
    eq('a road across a dual carriageway is one corner, between the two',
       got.at && [got.at.lat, got.at.lon].join(','), '33.9451,-84.5455');
    got = await nbxS.place('Juniper Cir & Northgate Dr, Marietta', d3, ST);
    eq('two streets that meet in two places inside the card are refused, not pinned '
       + 'at one', JSON.stringify([got.at, got.why, got.n]), JSON.stringify([null, 'corners', 2]));
    got = await nbxS.place('Juniper Cir & Northgate Dr, Marietta',
                           MV.discFor(card({ miles: 0.2 })), ST);
    eq('...and where neither is inside the card, none, with the nearest',
       [got.why, got.nearest && got.nearest.toFixed(1)].join(','), 'nomeet,0.9');
    got = await nbxS.place('Church St SE & Northgate Dr, Marietta', d3, ST);
    eq('two streets that do not meet at all are said not to meet',
       [got.why, got.nearest].join(','), 'nomeet,');
    got = await nbxS.place('Larkspur Pkwy SE & Old Mill Rd, Atlanta', d3, ST);
    eq('two names of one road meet along all of it: refused as no one corner',
       got.why, 'together');
    got = await nbxS.place('Pine St & Wren Rd, Marietta', d3, ST);
    eq('a street name the index does not hold is said, not matched to Pine Court',
       got.why, 'nostreet');
    got = await nbxS.place('Larkspur Pkwy SE, Atlanta', d3, ST);
    eq('a numberless street is its stretch inside the card, pinned nearest the car',
       got.at && [got.at.lat, got.at.lon, got.at.nearestOf, got.at.stretch.length].join(','),
       '33.948,-84.552,true,1');
    ok_('...every point of the stretch inside the disc',
        got.at && got.at.stretch[0].every(function (p) {
          return MV.crowMiles(SQ, { lat: p[0], lon: p[1] }) <= d3.miles;
        }));
    got = await nbxS.place('Larkspur Pkwy SE, Atlanta', d94, ST);
    eq('...and its two stretches 6.4 mi apart inside a 9.4 mi card are refused',
       [got.why, got.n].join(','), 'several,2');
    got = await nbxS.place('Shadowood Pkwy SE, Atlanta', d94, ST);
    ok_('a street the index does not hold is asked of the search as before, and '
        + 'pinned by it (' + (got.at && got.at.name) + ')',
        got.at && /Cumberland/.test(got.at.name) && !got.at.nearestOf
        && Object.keys(nbxS.cache).some(function (u) {
          return /^\/stretch\?name=Shadowood/.test(u);
        }) && Object.keys(nbxS.cache).some(function (u) {
          return /^\/search\?street=Shadowood/.test(u);
        }));
    got = await new MV.NbxSearch({ base: onShort.base + '/api/nbx' })
      .place('Larkspur Pkwy SE, Atlanta', d3, ST);
    eq('a stretch the NucBox would not send whole is refused as too long',
       [got.why, got.n].join(','), 'long,5');
    got = await new MV.NbxSearch({ base: down.base + '/api/nbx' })
      .place('Foxglove Trl & Northgate Dr, Marietta', d3, ST);
    eq('a street index that does not answer is unreachable, the page\'s cue for the '
       + 'public map', got.why, 'unreachable');
    var none0 = Object.keys(nbxS.cache).length;
    got = await nbxS.place('Atami Grill & Sushi Atwater Dr & Kolora Chase, Smyrna', d3, ST);
    eq('three names before the comma are not a corner, and nobody is asked',
       [got.why, Object.keys(nbxS.cache).length - none0].join(','), 'notwo,0');

    /* The road. */
    var A = { lat: 33.983, lon: -84.5499 }, S = { lat: 33.8779, lon: -84.46 };
    var road = await nbx.detour(SQ, A, S);
    var by = await nbx.road([SQ, A, S]), direct = await nbx.road([SQ, S]);
    eq('the road detour is road(car, pickup, held end) less road(car, held end), in miles',
       road.miles, (by.metres - direct.metres) / 1609.344);
    ok_('...a real figure off the router (' + (road.miles || 0).toFixed(2) + ' road mi)',
        road.miles > 0.5);
    eq('...and nothing in it but miles: no minutes anywhere',
       Object.keys(road).join(','), 'miles');
    var asked = fake.asked.filter(function (u) { return /^\/route/.test(u); });
    ok_('...and the router was never asked about any fourth point (' + asked.length + ' routes)',
        asked.every(function (u) { return u.split('?')[0].split(';').length <= 3; }));
    eq('a route the router says has no road is said as no road, not as a figure',
       (await nbx.detour(SQ, { lat: 34.0010, lon: -84.5560 }, S)).why, 'noroute');
    eq('...and one it refuses with any other code is the router down, not "no road"',
       (await nbx.detour(SQ, { lat: 34.1, lon: -84.6 }, S)).why, 'unreachable');
    var W = { lat: Number(FAKE.WAFFLE[0].lat), lon: Number(FAKE.WAFFLE[0].lon) };
    eq('through the server, a pickup the road by is 400 m shorter than the road '
       + 'direct is no figure: the router took different roads',
       JSON.stringify(await nbx.detour(SQ, W, S)), JSON.stringify({ why: 'otherroads' }));
    var Fm = { lat: Number(FAKE.FARM[0].lat), lon: Number(FAKE.FARM[0].lon) };
    eq('...and a pickup the router moved 450 m to reach a road is no figure either',
       JSON.stringify(await nbx.detour(SQ, Fm, S)), JSON.stringify({ why: 'snap' }));
    eq('the real install\'s own route, Marietta Square to Five Points: 31307.4 m',
       (await nbx.road([SQ, { lat: 33.7490, lon: -84.3880 }])).metres, 31307.4);

    /* A NucBox that is not there is said, and is the page's cue for the
       public geocoder — never "nothing there". */
    var gone = new MV.NbxSearch({ base: down.base + '/api/nbx' });
    got = await gone.place("McDonald's", d94);
    eq('an unreachable NucBox is said as unreachable, with the server\'s reason',
       [got.why, got.error].join(' | '),
       'unreachable | the NucBox did not answer (ECONNREFUSED)');
    eq('...and its router the same', (await gone.detour(SQ, A, S)).why, 'unreachable');
    got = await new MV.NbxSearch({ base: 'http://127.0.0.1:9/api/nbx' }).place("McDonald's", d94);
    ok_('...and this rig\'s own server not answering is unreachable too (' + got.error + ')',
        got.why === 'unreachable' && /did not answer/.test(got.error));
    var noSet = new MV.NbxSearch({ base: off.base + '/api/nbx' });
    eq('...and a server with no NucBox set is not mistaken for an answer',
       (await noSet.place("McDonald's", d94)).why, 'unreachable');

    /* No minutes anywhere in what the NucBox path can put on the panel. */
    var words = [MV.nbxRefusal(far, d94, 'X', 'new'), MV.nbxRefusal(two, d94, 'X', 'held'),
                 MV.nbxRefusal({ why: 'several', n: 3 }, null, 'X', 'held'),
                 MV.nbxRefusal({ why: 'none', nearest: null }, null, 'X', 'new'),
                 MV.nbxRefusal({ why: 'cross' }, null, 'X', 'new')];
    eq('no NucBox line speaks of minutes', words.filter(function (w) {
      return /\bmin/.test(w);
    }).length, 0);

    /* HOW EACH PLACE WAS FOUND, as Map view draws it (MV.discShape,
       MV.located): what the NucBox sent kept beside what was chosen from it
       (`seen`), so drawing it asks nobody anything. Each kind: a pin and the
       candidates beside it, a refusal, candidates outside the disc, a door
       answered by its street, a cut list, a corner's meetings, a street's
       stretch — and the answers with no list behind them. */
    var dS = MV.discShape(d94);
    eq('the card\'s disc is drawn at its fix, its distance and the half mile, in metres',
       [dS.lat, dS.lon, dS.metres.toFixed(3)].join(','),
       [SQ.lat, SQ.lon, (9.9 * 1609.344).toFixed(3)].join(','));
    eq('...none for a card with no yardstick (its sixty miles are no card\'s reach), '
       + 'and none with no fix', [MV.discShape(MV.discFor(card({ legs: 1, hasTotal: false }))),
                                 MV.discShape(null)].join(','), ',');

    // The relay stubbed with all four McDonald's, unbounded, counting every
    // question it is asked.
    var stubAsked = 0;
    var allMcd = hitsOf(FAKE.MCD);
    var stubbed = new MV.NbxSearch({ gap: 0, fetch: function () {
      stubAsked++;
      return Promise.resolve({ ok: true, status: 200, json: function () {
        return Promise.resolve({ ok: true, hits: allMcd });
      } });
    } });
    var pinned = await stubbed.place("McDonald's", d30);
    eq('the answer carries every candidate the NucBox sent, beside the one chosen',
       JSON.stringify([pinned.at && pinned.at.lat, pinned.seen && pinned.seen.hits.length]),
       JSON.stringify([33.983, 4]));
    var lp = MV.located(pinned, d30, "McDonald's", 'new');
    eq('a pin: the one inside drawn grey under it, the three past the disc hollow',
       lp.marks.map(function (m) { return m.kind; }).join(','),
       'candidate,outside,outside,outside');
    eq('...the one inside saying it was the pin',
       (lp.marks[0] || {}).tip, "McDonald's — the one inside the 3.5 mi searched, pinned");
    eq('...and one outside saying how far out it was, and that it was not used',
       (lp.marks[2] || {}).tip, "McDonald's — 10.6 mi from the card's fix, outside the 3.5 mi "
       + 'searched, not used');
    var refused = await stubbed.place("McDonald's", d94);
    var lr = MV.located(refused, d94, "McDonald's", 'new');
    eq('a refusal: no pin, the two inside drawn grey with the caption\'s own words',
       [refused.at, lr.marks.filter(function (m) {
         return m.kind === 'candidate' && m.tip === MV.nbxRefusal(refused, d94, "McDonald's", 'new');
       }).length].join(','), ',2');
    eq('...and the two past its edge hollow, the refusal and how far out',
       lr.marks.filter(function (m) { return m.kind === 'outside'; })
         .map(function (m) { return m.tip.split(' · this one ')[1]; }).join(' | '),
       "10.6 mi from the card's fix, outside the 9.9 mi searched | 21.8 mi from the "
       + "card's fix, outside the 9.9 mi searched");
    var lnone = MV.located(far, MV.discFor(card({ lat: 33.97, lon: -84.565, miles: 0.6 })),
                           "McDonald's", 'new');
    eq('none inside: nothing drawn for an answer with no list behind it',
       lnone.marks.length + lnone.lines.length, 0);
    var noFix = await stubbed.place("McDonald's", null);
    eq('with no fix to hold them to, all four are candidates: no disc, so none is outside',
       MV.located(noFix, null, "McDonald's", 'new').marks
         .filter(function (m) { return m.kind === 'candidate'; }).length, 4);
    eq('drawing all of it asked the NucBox nothing: one question for each place',
       stubAsked, 3);

    // Through the real server.js and the fake NucBox.
    var door = MV.located(await nbx.place('4821 Kestrel Dr, Marietta', d94), d94, 'Jimmy', 'new');
    ok_('a door answered by its street: the street drawn, no pin, saying not that door ('
        + (door.marks[0] || {}).tip + ')',
        door.marks.length >= 1 && door.marks.every(function (m) {
          return / — street found, not that door · this one its street, not door 4821$/.test(m.tip);
        }));
    var cutRes = await nbx.place('Starbucks', d30);
    var cut = MV.located(cutRes, d30, 'Starbucks', 'new');
    eq('a list cut at the limit: all ten drawn as sent, one inside, every one too many',
       [cut.marks.length, cut.marks.filter(function (m) { return m.kind === 'candidate'; }).length,
        cut.marks.every(function (m) { return m.tip.indexOf(MV.nbxRefusal(cutRes, d30, 'Starbucks', 'new')) === 0; })]
         .join(','), '10,1,true');
    var two2 = await nbxS.place('Juniper Cir & Northgate Dr, Marietta', d3, ST);
    var corners = MV.located(two2, d3, 'Juniper', 'held');
    eq('a corner refused for meeting twice: both meetings drawn, each with the refusal',
       [corners.marks.length, corners.marks.every(function (m) {
         return m.kind === 'candidate' && m.tip === MV.nbxRefusal(two2, d3, 'Juniper', 'held');
       })].join(','), '2,true');
    var fox = await nbxS.place('Foxglove Trl & Northgate Dr, Marietta', d3, ST);
    var foxL = MV.located(fox, d3, 'Foxglove', 'held');
    eq('...and a corner pinned: its meeting drawn under the pin, saying so',
       foxL.marks.map(function (m) { return [m.lat, m.lon, m.tip].join(' '); }).join(' | '),
       '33.96 -84.55 Foxglove — the one inside the 3.5 mi searched, pinned');
    var lark3 = await nbxS.place('Larkspur Pkwy SE, Atlanta', d3, ST);
    var larkL = MV.located(lark3, d3, 'Larkspur', 'held');
    eq('a numberless street pinned: its stretch inside the disc drawn as the chosen line, '
       + 'the very runs the pin carries, and no marks',
       [larkL.lines.length, (larkL.lines[0] || {}).kind,
        JSON.stringify((larkL.lines[0] || {}).pts) === JSON.stringify(lark3.at.stretch[0]),
        larkL.marks.length].join(','),
       '1,chosen,true,0');
    var lark94 = await nbxS.place('Larkspur Pkwy SE, Atlanta', d94, ST);
    var lark94L = MV.located(lark94, d94, 'Larkspur', 'held');
    eq('...refused as two streets: both stretches drawn grey, with the refusal',
       [lark94L.lines.length, lark94L.lines.every(function (l) {
         return l.kind === 'candidate' && l.tip === MV.nbxRefusal(lark94, d94, 'Larkspur', 'held');
       })].join(','), '2,true');
    // A street through a 1.0 mi disc with its ends five miles out, refused:
    // only the part inside is drawn.
    var crossing = MV.located({ at: null, why: 'several', n: 2,
                                seen: { lines: [[[SQ.lat, -84.60], [SQ.lat, -84.50]],
                                                [[SQ.lat + 0.1, -84.6], [SQ.lat + 0.1, -84.5]]] } },
                              d1, 'X', 'new');
    ok_('...and of a street running out of the disc, only the part inside it is drawn',
        crossing.lines.length === 1 && crossing.lines[0].pts.every(function (p) {
          return MV.crowMiles(SQ, { lat: p[0], lon: p[1] }) <= 1.0 + 1e-9;
        }));
    // Not "a stretch too long to send whole": the index sends no lines for
    // one (streets.js stretch empties them past its cap), so with or without
    // NbxSearch.stretch's cutAt return there was nothing to draw, and a check
    // of it could not fail.
    eq('nothing drawn for an answer with no list behind it: no street index to ask, '
       + 'a NucBox down',
       [MV.located({ at: null, why: 'cross' }, d94, 'X', 'new'),
        MV.located(await gone.place("McDonald's", d94), d94, 'X', 'new')]
         .map(function (h) { return h.marks.length + h.lines.length; }).join(','), '0,0');
    eq('...and an answer of a kind with no words is never drawn as a pin',
       MV.located({ at: null, why: 'odd', n: 1, seen: { hits: [SQ] } }, d94, 'X', 'new')
         .marks[0].tip, 'no pin for X');
    var drawnWords = [lp, lr, door, cut, corners, foxL, larkL, lark94L].reduce(function (all, h) {
      return all.concat(h.marks.map(function (m) { return m.tip; }),
                        h.lines.map(function (l) { return l.tip; }));
    }, []);
    eq('...and nothing drawn speaks of minutes',
       drawnWords.filter(function (w) { return /\bmin/.test(w); }).length, 0);
  } finally {
    on.stop(); off.stop(); down.stop(); nuc.stop(); nucShort.stop(); onShort.stop();
    idx.drop();
    fake.server.close();
  }
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

  /* ...and the "near" box does not fork the cache for a place that HAS one.
   *
   * The map page passes whatever the driver typed into "near"; the offers page
   * passes nothing. Both build a Geocoder over the same store. Applied to
   * every lookup, one word typed on one page made every key there different
   * from the same place asked on the other — so the two stopped sharing, and
   * the one-a-second limit was paid twice for places already found.
   *
   * The hint is for a row whose car position was never recorded: no box, so
   * nothing stops the geocoder answering with a same-named street in another
   * state. A boxed place does not need it, and the box says where to look more
   * precisely than a town name does. */
  var typed = 'Georgia';
  var hinted = fakeGeo({}, { hint: function () { return typed; } });
  var plain = fakeGeo({});
  var someBox = MV.boxAround({ lat: 33.9, lon: -84.5 });
  eq('a boxed place is asked the same way whether or not a town was typed',
     hinted.geo.keyFor('Duval Ct', someBox), plain.geo.keyFor('Duval Ct', someBox));
  // ...and the hint still does its job where there is no box, which is the
  // only case it was ever for.
  no_('an unboxed place still takes the hint',
      hinted.geo.keyFor('Duval Ct', null) === plain.geo.keyFor('Duval Ct', null));
  ok_('...and the hint is what makes the difference',
      hinted.geo.keyFor('Duval Ct', null).indexOf('Georgia') !== -1);

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

  /* TWO PAGES, ONE DEVICE.
   *
   * The map page and the offers page both build a Geocoder over the same
   * localStorage key, and a PWA keeps both alive — opening the map from a row
   * on the offers page leaves two of these in existence. Each reads the store
   * ONCE, when it is constructed. Writing the whole in-memory copy back on
   * every answer then means whichever page answers last writes its own
   * snapshot over everything the other learned in between.
   *
   * What that costs is work, not correctness: the addresses are gone, nothing
   * says so, and the next press pays the one-a-second rate limit again for
   * places already found — the exact cost the anchor snapping exists to
   * remove, reintroduced by the page next to it.
   *
   * Staged as it really happens: both built while the store is empty, which is
   * what makes both snapshots stale. */
  var device = { blob: '{}' };
  var shared = { get: function () { return device.blob; },
                 set: function (v) { device.blob = v; },
                 clear: function () { device.blob = '{}'; } };
  var P1 = fakeGeo({ 'Kroger': { lat: 33.9, lon: -84.5 } }, { store: shared });
  var P2 = fakeGeo({ 'Zaxbys': { lat: 33.8, lon: -84.4 } }, { store: shared });
  await P1.geo.lookup('Kroger', null);
  await P2.geo.lookup('Zaxbys', null);
  var onDevice = JSON.parse(device.blob);
  ok_('the first page answer is still on the device after the second writes',
      Object.prototype.hasOwnProperty.call(onDevice, 'Kroger'));
  ok_('...alongside the second page own answer',
      Object.prototype.hasOwnProperty.call(onDevice, 'Zaxbys'));
  // ...and the page that wrote last has the other's work in memory too, so it
  // does not ask again for something already on the device.
  ok_('...and the second page need not ask about the first page place',
      P2.geo.knows('Kroger', null));

  /* ...and a page still open does not put back what Forget threw away.
   *
   * The same two-page fact from the other side, and the one that cost the
   * driver something rather than costing work. `map.html`'s "Forget lookups"
   * is the only control that can throw away a bad geocode — a misread street
   * answered in Idaho, which the map page lists as a stray and which nothing
   * else can correct. Writing the whole in-memory copy back meant the panel in
   * the car, still open, restored its entire history on the next place it
   * looked up. The button emptied the device and the next answer undid it.
   *
   * Staged in that order deliberately: the panel is built and fills up first,
   * the desk page presses Forget after, and then the panel answers one more
   * place, because that is the sequence a driver produces. */
  var P3 = fakeGeo({ 'Chipotle': { lat: 33.7, lon: -84.3 },
                     'Wingstop': { lat: 33.6, lon: -84.2 } }, { store: shared });
  await P3.geo.lookup('Chipotle', null);
  // P3 was built after the other two answered, so it holds their places in
  // memory as well as its own — which is exactly the page that did the damage.
  ok_('the still-open page holds the earlier places in memory',
      P3.geo.knows('Kroger', null) && P3.geo.knows('Zaxbys', null));
  P2.geo.forget();
  ok_('Forget empties the device',
      Object.keys(JSON.parse(device.blob)).length === 0);
  await P3.geo.lookup('Wingstop', null);
  var after = JSON.parse(device.blob);
  no_('...and an answer that follows it does not restore the forgotten places',
      Object.prototype.hasOwnProperty.call(after, 'Kroger')
      || Object.prototype.hasOwnProperty.call(after, 'Zaxbys'));
  ok_('...while the answer itself is kept',
      Object.prototype.hasOwnProperty.call(after, 'Wingstop'));
  no_('...so a page opened next does not believe them again',
      new MV.Geocoder({ store: shared }).knows('Kroger', null));

  /* A store that refuses every write still accumulates for the session.
   *
   * Site data blocked, or a full quota. The write throws, and the throw is
   * what stops this page adopting a device snapshot the write never reached —
   * so the answers it has paid for stay in memory. Adopting before writing
   * would drop each one as the next arrived, and a second press would re-ask
   * every place at the one-a-second rate. Nothing else in this file measures
   * the order those two lines are in. */
  var refuses = { get: function () { return '{}'; },
                  set: function () { throw new Error('quota'); },
                  clear: function () {} };
  var stuck = new MV.Geocoder({ store: refuses });
  stuck.remember('A', { lat: 1, lon: 1 });
  stuck.remember('B', { lat: 2, lon: 2 });
  stuck.remember('C', { lat: 3, lon: 3 });
  ok_('a page whose store refuses writes still knows what it asked earlier',
      stuck.knows('A', null) && stuck.knows('B', null));


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
      lat: 33.90, lon: -84.50, gpsOk: true },
    { pickup: 'Chipotle', dropoff: 'Far Away Rd', miles: 12,
      lat: 33.92, lon: -84.52, gpsOk: true }
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
  /* How each place was asked, kept for map.html's pins (MV.howFound): the
     walk's own record, so saying it asks nothing. */
  var sentBefore = E.sent.length;
  eq('the run says which place its box found nothing for, so was asked wide',
     JSON.stringify(Object.keys(run.asked).filter(function (q) { return run.asked[q].wide; })),
     JSON.stringify(['Far Away Rd']));
  ok_('...and the box every place was searched in',
      Object.keys(run.asked).every(function (q) { return /^-?\d/.test(run.asked[q].box || ''); }));
  // The box as searched, its size read off it: boxAround's 60 miles each
  // way, widened by half a 0.25-degree grid step, round the grid point —
  // 137 mi north–south by 134 east–west here, not "the 60 mi box".
  eq('...so the far pin, answered in Chicago, is drawn ringed: found only outside its box',
     JSON.stringify(MV.howFound(run.found['Far Away Rd'], run.asked['Far Away Rd'])),
     JSON.stringify({ outside: true, line: 'nothing inside the box searched round where the '
                      + 'car was, 137 mi north–south by 134 east–west, so asked without it — '
                      + 'and found outside it' }));
  eq('...and a pin its box found is not, and says so, with the box it searched',
     JSON.stringify(MV.howFound(run.found['Chipotle'], run.asked['Chipotle'])),
     JSON.stringify({ outside: false, line: 'found inside the box searched round where the car '
                      + 'was, 137 mi north–south by 134 east–west' }));
  eq('...one asked wide and answered inside its box after all is not called outside',
     MV.howFound({ lat: 33.90, lon: -84.50 },
                 { box: run.asked['Chipotle'].box, wide: true }).outside, false);
  eq('...one with no box says it had none, and why',
     MV.howFound({ lat: 33.9, lon: -84.5 }, { box: null, wide: false }).line,
     'asked with no box — no row naming it knows where the car was');
  eq('...and one the walk never asked, or never placed, has nothing to say',
     [MV.howFound(null, run.asked['Chipotle']), MV.howFound({ lat: 1, lon: 1 }, undefined)]
       .join(','), ',');
  eq('...and saying all of it asked the geocoder nothing', E.sent.length, sentBefore);

  /* A run over nothing must not throw, say something false, or claim a
   * division it did not do. The offers page will call this on every load
   * before anybody has pressed anything. */
  var F = fakeGeo({});
  var empty = await MV.placeAll([], F.geo, function () {});
  eq('an empty range asks nothing', F.sent.length, 0);
  eq('...and draws nothing', empty.drawn, 0);
  eq('...of nothing', empty.couldDraw, 0);
  eq('...with no strays', Object.keys(empty.strays).length, 0);

  /* --- the two ends, in the order the journey runs -----------------------
   *
   * Three surfaces drew them out of `places` joined with an arrow — the
   * driving panel's address row and the offers page's log and detail rows —
   * and `places` is the accumulator's union in the order the FRAMES arrived.
   * The two-ends fix gave `pickup` and `dropoff` that order and deliberately
   * left the list alone, so the arrow went on claiming one the list has not
   * got. Measured over the owner's week: 12 of 1,166 readings drew it
   * backwards, and 182 drew a three- or four-stop chain for a two-ended job.
   *
   * The offers page's own detail SHEET already drew [pickup, dropoff], so one
   * page answered this two ways a few hundred lines apart. */
  eq('the two ends come back in journey order, not arrival order',
     MV.ends({ pickup: 'Happy Hawg BBQ (Hiram)', dropoff: 'Tibbitts Rd, Dallas',
               places: ['Tibbitts Rd, Dallas', 'Happy Hawg BBQ (Hiram)'] }).join(' -> '),
     'Happy Hawg BBQ (Hiram) -> Tibbitts Rd, Dallas');
  eq('...and a union of four readings is still a job with two ends',
     MV.ends({ pickup: 'A', dropoff: 'B', places: ['B', 'A', 'B ', 'A,'] }).length, 2);
  /* It REORDERS what the card printed and never adds to it. A dropoff the
     driver revealed on their phone is not in `places`, and the offers page
     keeps it in a row of its own under its own label for a stated reason —
     folding it into "Where" would hide that a card printing "Customer
     dropoff" now has an address at all. */
  eq('an end the card never printed is not folded into what it printed',
     MV.ends({ pickup: 'A', dropoff: 'read off the phone',
               places: ['A'] }).join('|'), 'A');
  eq('...and a row the card gave no names for draws nothing',
     MV.ends({ pickup: 'A', dropoff: 'B' }).length, 0);
  eq('...and with neither end known the list is all the card gave',
     MV.ends({ places: ['X', 'Y'] }).join('|'), 'X|Y');
  eq('...a row with nothing on it draws nothing', MV.ends({}).length, 0);
  eq('...and neither does no row at all', MV.ends(null).length, 0);

  /* --- one rule for "this cannot be right" -------------------------------
   *
   * map.html draws a pair with a stray end as a RED DASHED line captioned
   * "This cannot be right". Three places decided that separately and two
   * disagreed: render() and the sidebar heading counted `impossible ||
   * fromStray || toStray`, while placeAll's own `drawn` — the figure in the
   * status line under the same map — tested only `impossible`, and so counted
   * an accusation as a success. Same words, one screen, two numbers.
   *
   * `impossible` cannot cover the stray half: it needs a second pin to argue
   * against, and a stray is a pin nowhere near the rest of the shift. */
  ok_('a pair with an impossible distance is an accusation',
      MV.accused({ impossible: true }));
  ok_('...so is one whose pickup is nowhere near the shift',
      MV.accused({ fromStray: true }));
  ok_('...and one whose dropoff is', MV.accused({ toStray: true }));
  ok_('a pair with none of those is a drawing', !MV.accused({}));
  ok_('...and nothing at all accuses nobody', !MV.accused(null));

  /* The figure the status line prints has to count the same thing the map
   * draws. Two pairs, both placed at both ends, one of them with a stray
   * pickup: the line under the map used to say both were drawn end to end
   * while one of them was on screen in red, dashed, saying it cannot be
   * right. */
  var strayed = [{ from: { lat: 34, lon: -84 }, to: { lat: 34.1, lon: -84.1 },
                   impossible: false, fromStray: true },
                 { from: { lat: 34, lon: -84 }, to: { lat: 34.1, lon: -84.1 },
                   impossible: false }];
  eq('the count under the map leaves the accusations out',
     strayed.filter(function (p) { return p.from && p.to && !MV.accused(p); }).length, 1);
  /* ...and placeAll's own figure has to be that figure, through the whole
   * run and not just in a filter written beside it.
   *
   * The card states no distance here, and that is the point: `impossible`
   * needs a stated distance for a yardstick, so without one it cannot fire
   * however far the pin lands. A stray end is then the ONLY thing saying the
   * pair is wrong, and the status line's count was the one reader not asking.
   * 15 of the owner's 579 both-ended pairs sit in exactly this state. */
  var G = fakeGeo({ 'Chipotle': { lat: 33.90, lon: -84.50 },
                    'Duval Ct': { lat: 33.93, lon: -84.55 },
                    'Chicago Ave': { lat: 41.88, lon: -87.63 } });
  var noYardstick = await MV.placeAll(
    [{ pickup: 'Chipotle', dropoff: 'Duval Ct', lat: 33.90, lon: -84.50 },
     { pickup: 'Chipotle', dropoff: 'Chicago Ave', lat: 33.92, lon: -84.52 }],
    G.geo, function () {});
  eq('a pin in another state is still a stray without a distance to check it',
     Object.keys(noYardstick.strays).length, 1);
  ok_('...and nothing calls that pair impossible, having nothing to argue with',
      noYardstick.placed.every(function (p) { return !p.impossible; }));
  eq('...so both pairs were placed at both ends',
     noYardstick.placed.filter(function (p) { return p.from && p.to; }).length, 2);
  eq('...and the status line still counts only the one that is not an accusation',
     noYardstick.drawn, 1);
  ok_('...and says so in words', /1 of 2 drawn end to end/.test(noYardstick.done));


  /* The summary used to be printed HERE, two sections from the end of the
   * file, and everything below it was counted but never announced. On a red run
   * it printed "All 195 map-view checks passed" and then the FAIL lines
   * underneath — the suite's own text making a claim its exit code did not
   * honour. It goes last now, which is the only place it can be true. */
  /* --- which end of a job named the town it is ranked under --------------
   *
   * The map's "Where the money is" groups on MV.townFor, which takes the
   * DROPOFF first and falls back to the pickup. On the owner's real week 86%
   * of the placed rows come off the dropoff — so a town near the top of that
   * list is mostly a town jobs END in, and the panel's note said the opposite
   * ("these are the offers that came to you where you already were") on a
   * page where no row carries a position at all.
   *
   * townFor is derived from townEndFor rather than restating the precedence,
   * so the two cannot disagree. Written the other way round first, which is
   * two copies of one rule and the first edit to either would have made the
   * ranking's rows disagree with the ranking.
   *
   * Checked here because rpi/test_map.py's fixture carries every ranked town
   * on the PICKUP, so the page can prove the silence and not the sentence. */
  var byEnd = { pickup: 'Zaxbys', dropoff: 'Peachtree St NE, Atlanta' };
  eq('a job whose dropoff names a town is ranked under that town',
     MV.townFor(byEnd, ADV.area), 'Atlanta');
  eq('...and says the dropoff is where it came from',
     MV.townEndFor(byEnd, ADV.area), 'dropoff');
  // THE DROPOFF WINS when both ends name one, which is the whole reason the
  // panel's note had to change: it is what makes 86% of the placed rows a
  // statement about where jobs END. Without this the order can be swapped and
  // every other case here still passes, because no other fixture has a town
  // at both ends — measured, by swapping it.
  var both = { pickup: 'Barrett Pkwy, Kennesaw', dropoff: 'Oak Ln, Acworth' };
  eq('with a town at both ends the dropoff is the one ranked',
     MV.townFor(both, ADV.area), 'Acworth');
  eq('...and is named as the end it came from', MV.townEndFor(both, ADV.area), 'dropoff');

  // ONE RULE, HANDED IN. map-view used to carry its own idea of what a town
  // is — a comma, a shape, a lowercase letter — while advice.js carried
  // another, and townOf's own comment said it had been lifted out "rather
  // than written a second time, because two copies of 'what counts as a town'
  // would answer differently the first time either was touched". They already
  // did: on the owner's 1,325 distinct place strings they disagreed on 81.
  //
  // Every disagreement went map-view's way and map-view was wrong on all of
  // them — 69 towns it could not see through OCR damage or a ZIP tail, 7 junk
  // strings it accepted, and 5 where it kept the damage IN the name. Those
  // five mattered most: "F Marietta" and "Marietta" ranked as two towns.
  eq('a town damaged by OCR is still read',
     MV.townOf('Bob Cox Rd NW & Granville Dr NW, I Marietta', ADV.area),
     'Marietta');
  eq('...and one behind a ZIP tail, which is what a scanned address ends in',
     MV.townOf('322 Thompson Dr, Dallas, GA 30132-3289', ADV.area), 'Dallas');
  eq('...and a two-word one keeps both words',
     MV.townOf('Waterway Cir, - R Lithia Springs', ADV.area), 'Lithia Springs');
  // The one piece of the old judgement that is still map-view's, and the case
  // it was written for: an all-capitals tail is an abbreviation or a fragment
  // of a road name, not a place anybody lives. The rule reads "LAS" as a town
  // quite happily, so this cannot be delegated with the rest.
  eq('an all-capitals tail is not a town', MV.townOf('ies, LAS', ADV.area), null);
  // Title case, because this is what the ranking prints and the rule
  // lowercases in order to compare.
  eq('a town comes back as it is printed, not as it is compared',
     MV.townOf('Oak Ln, Powder Springs', ADV.area), 'Powder Springs');
  // WITHOUT the rule there is no answer, rather than a second opinion. That is
  // the whole point: map-view is not allowed to decide this on its own any
  // more, and a quiet fallback would be the duplication growing back.
  eq('with no rule handed in there is no town', MV.townOf('Peachtree, Atlanta'), null);
  eq('...and no end either', MV.townEndFor({ dropoff: 'Peachtree, Atlanta' }), null);

  var byPickup = { pickup: 'Canton Rd, Marietta', dropoff: 'Zaxbys' };
  eq('a job whose dropoff names nowhere falls back to the pickup',
     MV.townFor(byPickup, ADV.area), 'Marietta');
  eq('...and says so', MV.townEndFor(byPickup, ADV.area), 'pickup');
  var neither = { pickup: 'Zaxbys', dropoff: 'Wendys' };
  eq('a job naming no town is under none', MV.townFor(neither, ADV.area), null);
  eq('...and names no end either', MV.townEndFor(neither, ADV.area), null);
  eq('nothing at all is nothing', MV.townEndFor(null, ADV.area), null);
  // The derivation, not a restatement of it: whatever end is named, the town
  // is the town OF that end. A precedence that drifted would break this
  // without breaking any single case above.
  [byEnd, byPickup, neither, { pickup: 'Barrett Pkwy, Kennesaw',
                               dropoff: 'Oak Ln, Acworth' }]
    .forEach(function (o, i) {
      var end = MV.townEndFor(o, ADV.area);
      eq('the town is read off the end that named it (' + i + ')',
         MV.townFor(o, ADV.area), end ? MV.townOf(o[end], ADV.area) : null);
    });

  /* ---- the figure that leads a town's row ---- */
  //
  // Three different questions, and the third is the one that needed a function.
  // `Advice.areas` reports `matched: null` for a town whose every hour held no
  // other town: there is nothing it can be said to have paid more or less THAN.
  // `null >= 0` is TRUE in JavaScript, so the obvious formatter prints
  // "+$NaN/hr" — a confidently wrong number arriving through a comparison
  // operator, on the page's most quotable figure.
  eq('a ranking that is not held still leads with what the town paid',
     MV.rankLead({ name: 'Acworth', median: 14.01, matched: null }, false).text,
     '$14.01');
  eq('...with a unit, being a rate',
     MV.rankLead({ median: 14.01 }, false).unit, true);
  eq('held still, the lead is what it paid over the same hours elsewhere',
     MV.rankLead({ median: 19.95, matched: 3.28 }, true).text, '+$3.28');
  // A real minus sign, not a hyphen, and before the dollar — the rule this
  // project states for every negative figure on every screen.
  eq('...and a town that paid less says so with a minus, not a hyphen',
     MV.rankLead({ median: 13.62, matched: -1.7 }, true).text, '−$1.70');
  ok_('...never as $-1.70',
      MV.rankLead({ median: 13.62, matched: -1.7 }, true).text.indexOf('$-') < 0);
  eq('a town with nothing to compare against leads with a dash',
     MV.rankLead({ median: 15.8, matched: null }, true).text, '—');
  // ...and no unit on it. "—/hr" reads as a rate that failed to print rather
  // than as a question with no answer.
  eq('...and takes no unit', MV.rankLead({ median: 15.8, matched: null }, true).unit,
     false);
  ok_('...and never prints a number it does not have',
      MV.rankLead({ median: 15.8, matched: null }, true).text.indexOf('NaN') < 0);
  // A missing key is the same absence as an explicit null: a reading from a
  // server one release behind carries no `matched` at all.
  eq('a row with no matched key at all is the same absence',
     MV.rankLead({ median: 15.8 }, true).text, '—');
  // Zero is an ANSWER — "it paid what the others did" — and must not be
  // mistaken for the absence of one.
  eq('a town level with the others is plus nothing, not a dash',
     MV.rankLead({ median: 15.8, matched: 0 }, true).text, '+$0.00');

  /* ---- where a pin's town stands ---- */
  //
  // The popup quoted the POSITION from the hour-held order beside the RAW
  // median, and the two orders are not the same list. These four are the
  // owner's week, "any time", in the order Advice.areas returns them: Kennesaw
  // is 3rd and paid $15.32, Woodstock 4th and paid $15.80. Tapping the two pins
  // read "3 of 9, median $15.32" against "4 of 9, median $15.80" — the better
  // position with the worse number, and nothing saying the hour was held.
  var held = { real: true, matched: true, groups: [
    { name: 'Atlanta', median: 19.95, matched: 3.28 },
    { name: 'Mableton', median: 15.94, matched: 0.13 },
    { name: 'Kennesaw', median: 15.32, matched: 0.13 },
    { name: 'Woodstock', median: 15.8, matched: -0.13 },
  ] };
  var stood = MV.standings(held);
  eq('a pin quotes its town\'s position with the figure it was ranked by',
     stood.Kennesaw, 'Kennesaw is 3 of 4 towns here at +$0.13/hr once the hour '
       + 'is held still; $15.32 median');
  // ...and it is the sidebar's own lead, not a second formatting of it, so the
  // popup and the row it quotes cannot come apart.
  ok_('...the same figure the sidebar\'s row leads with',
      stood.Woodstock.indexOf(MV.rankLead(held.groups[3], true).text + '/hr') >= 0);
  // The whole claim, as a property: down the order, the figure beside the
  // ordinal never goes UP. With the raw median beside it, Woodstock's $15.80
  // under Kennesaw's $15.32 breaks exactly this.
  var quoted = held.groups.map(function (g) {
    var m = /at ([+−])\$([\d.]+)\/hr/.exec(stood[g.name] || '');
    return m ? (m[1] === '−' ? -1 : 1) * Number(m[2]) : NaN;
  });
  ok_('...so a better position never quotes a worse figure (' + quoted.join(', ') + ')',
      quoted.every(function (v, i) { return !isNaN(v) && (i === 0 || v <= quoted[i - 1]); }));
  // A town with no hour-held figure is not IN the order — it is sorted last
  // for having no place — so it gets no ordinal, and the count leaves it out.
  var withLonely = { real: true, matched: true, groups: held.groups.concat(
    [{ name: 'Lonely', median: 22.1, matched: null }]) };
  var lonely = MV.standings(withLonely);
  ok_('a town with nothing to be compared against is given no position (' + lonely.Lonely + ')',
      !/ is \d+ of /.test(lonely.Lonely) && lonely.Lonely.indexOf('$22.10 median') >= 0);
  ok_('...and is not counted among the towns that have one',
      lonely.Atlanta.indexOf('1 of 4 towns') >= 0);
  // Not held still, the median IS the figure the order was sorted by, and the
  // plain line is right.
  eq('a ranking not held still quotes the median it was ranked by',
     MV.standings({ real: true, matched: false, groups: [
       { name: 'Here', median: 21.3, matched: null },
       { name: 'There', median: 12.4, matched: null }] }).There,
     'There is 2 of 2 towns here, median $12.40/hr');
  // ...and nothing at all off a ranking the page has called chance.
  eq('a ranking that does not beat chance puts nothing on a pin',
     Object.keys(MV.standings({ real: false, matched: true,
                                groups: held.groups })).length, 0);

  await nucbox();

  console.log(fail ? ('\n' + pass + ' passed, ' + fail + ' FAILED')
                   : '\nAll ' + pass + ' map-view checks passed');
  process.exit(fail ? 1 : 0);
})().catch(function (e) {
  console.log('FAIL  the suite itself threw: ' + (e && e.stack || e));
  process.exit(1);
});
