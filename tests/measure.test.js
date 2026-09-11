/* The measurement that decides how the rig should learn geography.
   Run with: node tests/measure.test.js

   tools/measure_places.js does not ship to the car and changes no verdict, so
   the temptation is to leave it unchecked. That is exactly backwards. Its
   output is the evidence a build-or-don't-build decision rests on, and a
   coverage number that is quietly too high sends weeks at the wrong design —
   a more expensive mistake than most bugs on the panel, and a silent one,
   because nothing downstream would ever contradict it.

   Two things are checked hardest, because they are the two that would flatter
   the answer:

     - the no-lookahead rule. A table scored against the same rows it was built
       from answers every question it has already been given, and would report
       near-total coverage on any journal at all.
     - the direction of a leg. "Have I driven Marietta to Kennesaw before" must
       not be answered by a Kennesaw-to-Marietta run, nor by one that happened
       AFTER the moment being asked about.

   The place shapes are asserted against the shared corpus rather than against
   strings written here, so the claim they support — that these cards carry
   intersections and not house numbers, which is what decides between a street
   index and a geocoder — is a claim about real cards. */

var path = require('path');
var M = require('../tools/measure_places.js');
var cases = require('../tests/fixtures/cases.json');

var pass = 0, fail = 0;
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass += 1; return; }
  fail += 1;
  console.log('FAIL  ' + name + ': got ' + JSON.stringify(got)
              + ' want ' + JSON.stringify(want));
}
function ok(name, cond) { eq(name, !!cond, true); }

/* --- what shape the real cards name ------------------------------------- */

eq('an intersection of two streets is a junction',
   M.shapeOf('Lakeview Ter & Windmill Dr, Dallas'), 'junction');
eq('a street with a town is a street+town',
   M.shapeOf('Canton Rd, Marietta'), 'street+town');
eq('a merchant with a branch in brackets is a merchant',
   M.shapeOf('Zaxbys (Old 41 Hwy)'), 'merchant');
eq('a bare merchant name is a merchant',
   M.shapeOf('Buffalo Wild Wings'), 'merchant');
// The one shape that would need a geocoder rather than a lookup. It appears
// only on the screen AFTER the accept, which is the whole reason the dropoff
// scan exists — so finding one among the offer cards would change the answer.
eq('a door number is called a house number',
   M.shapeOf('1234 Daffodil Ln, Powder Springs'), 'house number');
eq('nothing is nothing', M.shapeOf(''), 'nothing');
eq('a missing place is nothing', M.shapeOf(null), 'nothing');

var corpusPlaces = [];
cases.places.forEach(function (c) {
  (c.expect || []).forEach(function (p) {
    if (corpusPlaces.indexOf(p) === -1) corpusPlaces.push(p);
  });
});
ok('the corpus has places to classify', corpusPlaces.length > 15);
var shapes = {};
corpusPlaces.forEach(function (p) {
  var s = M.shapeOf(p);
  shapes[s] = (shapes[s] || 0) + 1;
});
// The load-bearing finding. If a card ever starts printing door numbers this
// check fails, and the geocoder question is genuinely reopened.
eq('not one place an offer card names is a house number',
   shapes['house number'] || 0, 0);
ok('and most of them are a junction or a street with a town ('
   + ((shapes.junction || 0) + (shapes['street+town'] || 0)) + ' of '
   + corpusPlaces.length + ')',
   (shapes.junction || 0) + (shapes['street+town'] || 0) >= corpusPlaces.length / 3);

/* --- how finely a place can be pinned ----------------------------------- */

eq('a town alone keys as its town', M.keyOf('Canton Rd, Marietta', 'town'), 'marietta');
eq('a quadrant sharpens the key',
   M.keyOf('Cobb Pkwy NW, Kennesaw', 'town+quadrant'), 'kennesaw NW');
eq('...but not at town grain',
   M.keyOf('Cobb Pkwy NW, Kennesaw', 'town'), 'kennesaw');
eq('a place with no town has no town key',
   M.keyOf('Buffalo Wild Wings', 'town'), null);
eq('a scanned address reports its ZIP as the finest grain',
   M.grainOf('1234 Daffodil Ln, Powder Springs, GA 30127'), 'zip');
eq('a street and town alone is coarser',
   M.grainOf('Canton Rd, Marietta'), 'town only');
eq('and a merchant is nowhere at all', M.grainOf('Buffalo Wild Wings'), 'nowhere');

/* --- the legs a journal holds -------------------------------------------- */

function offer(over) {
  return Object.assign({
    id: 'o' + Math.random().toString(36).slice(2, 8),
    at: 1000, pay: 12, minutes: 20, cost: 1, whole: true,
    pickup: 'Cobb Pkwy, Kennesaw', dropoff: 'Canton Rd, Marietta', miles: 8,
  }, over);
}

var sampleLegs = M.legs([
  offer({ at: 3000, miles: 9 }),
  offer({ at: 1000, miles: 8 }),
  offer({ at: 2000, miles: 7 }),
], 'town');
eq('every placed card with a distance is a leg', sampleLegs.length, 3);
eq('...in the order they happened, whatever order they arrived in',
   sampleLegs.map(function (l) { return l.at; }), [1000, 2000, 3000]);
eq('...keyed from one end to the other', sampleLegs[0].pair, 'kennesaw → marietta');

eq('a card with no dropoff is not a leg',
   M.legs([offer({ dropoff: null })], 'town').length, 0);
eq('a card with no distance is not a leg',
   M.legs([offer({ miles: null })], 'town').length, 0);
eq('a card with no distance worth the name is not a leg',
   M.legs([offer({ miles: 0 })], 'town').length, 0);
// Both ends in one town measures nothing about the road between two towns.
eq('a card that starts and ends in one town is not a leg',
   M.legs([offer({ pickup: 'A St, Kennesaw', dropoff: 'B Rd, Kennesaw' })], 'town').length, 0);
eq('a merchant pickup cannot be placed, so it is not a leg',
   M.legs([offer({ pickup: 'Buffalo Wild Wings' })], 'town').length, 0);

/* --- the approach, taken off where the card said what it was ------------- */

// A card's total covers driving to the pickup as well as doing the job, and
// the approach moves with wherever the car was. Left in, the same two towns
// measure differently every time and no table of them can ever be tight.
var split = M.legs([offer({ miles: 9.6, minutes: 28,
                            toPickupMiles: 1.2, toPickupMinutes: 5 })], 'town');
eq('the drive to the pickup comes off the distance', split[0].miles, 8.4);
eq('...and off the time', split[0].minutes, 23);
eq('...and the sample says it is a clean one', split[0].exact, true);

var unsplit = M.legs([offer({ miles: 9.6, minutes: 28 })], 'town');
eq('a row that never knew its approach keeps the whole total',
   unsplit[0].miles, 9.6);
// Kept rather than dropped: a journal written before the rig recorded the
// split is most of the history, and throwing it away would leave nothing to
// measure at all.
eq('...and is kept, marked as the inexact sample it is', unsplit[0].exact, false);

// A subtraction that leaves nothing is damage, not a very short job.
eq('an approach as long as the whole card is not a leg of zero',
   M.legs([offer({ miles: 4, toPickupMiles: 4 })], 'town').length, 0);
eq('...nor is one longer than the card',
   M.legs([offer({ miles: 4, toPickupMiles: 6 })], 'town').length, 0);

/* --- reach, and the lookahead that would fake it ------------------------- */

var reach = M.reachOf([
  { pair: 'a → b', at: 1 },
  { pair: 'a → b', at: 2 },
  { pair: 'c → d', at: 3 },
]);
eq('every leg is a question asked of the table', reach.asked, 3);
// Two, not three: the first sighting of a pair cannot have been answered by a
// table that had never seen it. A version that recorded before asking would
// say 3 here and would report full coverage on any journal in the world.
eq('...and only a pair driven BEFORE counts as an answer', reach.hit, 1);
eq('...with the distinct pairs counted', reach.distinct, 2);
eq('the same pair three times answers twice',
   M.reachOf([{ pair: 'a → b' }, { pair: 'a → b' }, { pair: 'a → b' }]).hit, 2);
eq('a reversed pair is a different pair',
   M.reachOf([{ pair: 'a → b' }, { pair: 'b → a' }]).hit, 0);
eq('an empty journal asks nothing', M.reachOf([]).asked, 0);

/* --- spread, which is the ceiling on how precise any of this can be ------ */

var tight = M.spreadOf([
  { pair: 'a → b', miles: 10 }, { pair: 'a → b', miles: 10 }, { pair: 'a → b', miles: 10 },
], 3);
eq('a pair driven three times the same way has no spread', tight.spread, 0);
eq('...and is counted as a pair worth checking', tight.pairs, 1);
var loose = M.spreadOf([
  { pair: 'a → b', miles: 5 }, { pair: 'a → b', miles: 10 }, { pair: 'a → b', miles: 15 },
], 3);
eq('five to fifteen miles around a ten is a whole median of spread',
   loose.spread, 1);
eq('a pair driven twice is not enough to judge it',
   M.spreadOf([{ pair: 'a → b', miles: 5 }, { pair: 'a → b', miles: 9 }], 3).pairs, 0);

/* --- the moments the feature exists for ---------------------------------- */

// An order ticked as taken, thirty minutes long, and an offer arriving ten
// minutes into it. That is a stack, and it is the only situation any of this
// would ever speak in.
var HELD = offer({ id: 'held', at: 1000000, minutes: 30, accepted: true,
                   pickup: 'Shop St, Acworth', dropoff: 'Canton Rd, Marietta' });
var ARRIVING = offer({ id: 'next', at: 1000000 + 600000, accepted: undefined,
                       pickup: 'Cobb Pkwy, Kennesaw', dropoff: 'Main St, Dallas' });

var alone = M.stackMoments([HELD, ARRIVING], 'town', []);
eq('an offer arriving inside a ticked order is a stack moment', alone.moments, 1);
eq('...with both of the ends that matter placed', alone.bothEnds, 1);
eq('...and nothing driven before, so nothing could be said', alone.covered, 0);

// The leg that would answer it — Marietta, where the held order ends, to
// Kennesaw, where the new one starts — driven earlier.
var EARLIER = offer({ id: 'earlier', at: 500000,
                      pickup: 'Canton Rd, Marietta', dropoff: 'Cobb Pkwy, Kennesaw' });
var helped = M.stackMoments([EARLIER, HELD, ARRIVING], 'town',
                            M.legs([EARLIER, HELD, ARRIVING], 'town'));
eq('a leg driven earlier answers the moment', helped.covered, 1);

// ...and the same leg driven AFTERWARDS does not. This is the second half of
// the no-lookahead rule and it is the one that would be easiest to lose.
var LATER = offer({ id: 'later', at: 9000000,
                    pickup: 'Canton Rd, Marietta', dropoff: 'Cobb Pkwy, Kennesaw' });
var notYet = M.stackMoments([HELD, ARRIVING, LATER], 'town',
                            M.legs([HELD, ARRIVING, LATER], 'town'));
eq('a leg driven later does not answer a moment that came first',
   notYet.covered, 0);

// The direction matters: driving Kennesaw to Marietta is not evidence about
// Marietta to Kennesaw when one of them is one-way round a lake.
var BACKWARDS = offer({ id: 'back', at: 500000,
                        pickup: 'Cobb Pkwy, Kennesaw', dropoff: 'Canton Rd, Marietta' });
var wrongWay = M.stackMoments([BACKWARDS, HELD, ARRIVING], 'town',
                              M.legs([BACKWARDS, HELD, ARRIVING], 'town'));
eq('a leg driven the other way round does not answer it', wrongWay.covered, 0);

// An offer that arrives after the held order has finished is not a stack.
var AFTER = offer({ id: 'after', at: 1000000 + 30 * 60000 + 1, accepted: undefined });
eq('an offer arriving after the order finished is not a stack moment',
   M.stackMoments([HELD, AFTER], 'town', []).moments, 0);
// ...and neither is one arriving during an order the driver never ticked.
var UNTICKED = Object.assign({}, HELD, { id: 'untick', accepted: undefined });
eq('an order that was never ticked was never in the car',
   M.stackMoments([UNTICKED, ARRIVING], 'town', []).moments, 0);
// Both ends in the same place needs no table at all.
var SAME = offer({ id: 'same', at: 1000000 + 600000, accepted: undefined,
                   pickup: 'Other Rd, Marietta', dropoff: 'X St, Dallas' });
eq('a pickup in the town the order already ends in is covered outright',
   M.stackMoments([HELD, SAME], 'town', []).covered, 1);

/* --- reading the rows ---------------------------------------------------- */

eq('a bare array of offers is accepted', M.fromPayload([{ id: 'x' }]).length, 1);
eq('...and so is the reply /api/journal actually sends',
   M.fromPayload({ offers: [{ id: 'x' }], pairs: [] }).length, 1);
eq('anything else is refused rather than guessed at',
   M.fromPayload({ nope: true }), null);
eq('...including nothing at all', M.fromPayload(null), null);

/* --- the report itself --------------------------------------------------- */

var report = M.analyse([HELD, ARRIVING, EARLIER]);
eq('the report counts the offers it read', report.offers, 3);
eq('...and how many named both ends', report.withBothEnds, 3);
ok('...and keys the areas worth placing', report.topAreas.length >= 3);
ok('...commonest first', report.topAreas.every(function (a, i, all) {
  return i === 0 || all[i - 1].seen >= a.seen;
}));

var empty = M.analyse([]);
eq('an empty journal reports nothing rather than dividing by it', empty.offers, 0);
ok('...and says so in words rather than printing a page of n/a',
   M.render(empty).indexOf('keepPlaces') !== -1);
// A journal written with keepPlaces off is the case this must not read as "you
// have never driven anywhere near the same place twice".
var placeless = M.analyse([offer({ pickup: null, dropoff: null, places: [] }),
                           offer({ pickup: null, dropoff: null, places: [] })]);
eq('a journal kept without places has no ends to place', placeless.withBothEnds, 0);
eq('...and no legs to learn from', placeless.grains.town.samples, 0);
ok('...and renders without throwing', M.render(placeless).length > 0);

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' measurement checks passed');
process.exit(fail ? 1 : 0);
