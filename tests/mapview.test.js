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
