/* What line to draw, worked out by replaying the offers this rig actually saw.
 *
 * The target is the one number in this project nobody ever checked. It gets
 * picked once — $25/hr sounds like a reasonable wage — and every verdict since
 * has been measured against it.
 *
 * A target is not a wage. It is a decision about how long to wait. Set it too
 * low and every hour goes on work that barely clears its own costs; set it too
 * high and the car sits still, because the offers that clear the line really are
 * better and there are not enough of them to fill a shift. The first failure is
 * loud. The second is silent — a screen full of PASS looks like discipline — and
 * it is the one that keeps being made.
 *
 * HOW THIS ANSWERS: BY REPLAY, NOT BY MODEL
 * The obvious way to do this is a renewal-reward model: estimate how often an
 * offer arrives, work out the expected wait for one above the line, and divide.
 * That was the first version of this file and it was wrong in a way worth
 * recording, because it looked completely reasonable.
 *
 * Estimating an arrival rate means deciding which stretches of clock the driver
 * was actually working, which means picking a number of minutes that separates
 * "waiting for the next offer" from "not driving". On one real 234-offer
 * recording the answer moved from 30 offers/hour to 88 offers/hour as that
 * threshold went from 45 minutes to 5 — a factor of three, entirely from a
 * constant nobody could defend. Every conclusion downstream inherited it.
 *
 * The gaps themselves say why. Half of them are under thirty seconds and ninety
 * per cent are under two and a half minutes; then there is a cliff, and thirteen
 * gaps of fifteen to forty minutes. That second group is not the market going
 * quiet. It is the length of a trip: the driver accepted something and was
 * driving it, and no card was on the screen to read. An "arrival rate" averaged
 * over both is a number describing nothing.
 *
 * So this does not estimate anything. It walks the real stream of offers in the
 * order they arrived, and for a candidate line simulates the shift: when free,
 * take the first offer at or above the line; then be busy for exactly as long as
 * that offer said; ignore everything that arrives meanwhile — which is what
 * really happened to the offers that arrived during a trip. Total earned over
 * total time. No arrival rate, no expected wait, no distribution assumed.
 *
 * WHAT IT REPORTS, AND WHAT IT REFUSES TO
 * The replay still needs to know which stretches of clock to count, so the
 * threshold problem does not disappear — it moves. What changes is that it stops
 * mattering. On that same recording the best line came out at $20 at every
 * threshold from 15 minutes to 90, with a plateau of $20-$24 at every one, while
 * the pounds-per-hour those produce ranged from $26 to $78.
 *
 * That is the shape of an honest answer here: the decision is robust and the
 * level is not. So this reports the line, and the improvement over the driver's
 * current line as a percentage — both stable — and does not report a dollar
 * figure per hour at all, because that figure depends entirely on how much of
 * the recorded time was really driving, which nothing here knows. It also checks
 * the answer at several thresholds and says so if they disagree.
 *
 * A range rather than a point, always. The exact maximum of a replay over a few
 * hundred offers moves with one lucrative offer landing at the right moment; the
 * plateau around it does not.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Advice = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Thresholds the answer is checked against, in minutes. Not a range of
  // plausible break lengths — a range chosen to disagree. If the recommendation
  // survives being computed at 15 and at 90 it is not an artefact of either.
  var THRESHOLDS = [15, 20, 30, 45, 60, 90];

  // The one used for the figures shown, chosen as the middle of that spread
  // rather than for any claim about how long a driver's break is.
  var SHOWN_AT = 30;

  // How far below the best a line can earn and still be inside the answer. The
  // exact maximum is noise; the plateau is the finding.
  var PLATEAU = 0.95;

  // Two lines this far apart across thresholds means the data has not settled
  // and no single answer should be given.
  var UNSTABLE_SPREAD = 6;

  // A wide plateau is not itself a problem: in a market with cheap offers and
  // good ones and nothing in between, every line between the two tiers behaves
  // identically, and "anywhere in this range" is a true and useful answer.
  //
  // The pathology is a plateau that reaches all the way down to zero. That says
  // taking everything earned within five per cent of the best line available —
  // being selective bought nothing measurable — and the bottom of that band is
  // $0, which is how "set your target to nothing" gets recommended with a
  // straight face. There is no line to draw; say so.

  // Below these there is not enough to say anything. A recommendation drawn from
  // one afternoon would be acted on exactly as confidently as one drawn from a
  // season, and this project's rule is that a confident wrong number is worse
  // than no number.
  var ENOUGH_OFFERS = 40;
  var ENOUGH_HOURS = 2;
  var ENOUGH_TRIPS = 12;

  var LADDER_MAX = 60;

  function median(v) {
    if (!v.length) return null;
    var s = v.slice().sort(function (a, b) { return a - b; });
    var i = Math.floor(s.length / 2);
    return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
  }

  /* One offer reduced to what a replay needs: when it appeared, what it pays
     after the car is paid for, and how long it would occupy the driver.

     Net rather than gross throughout, because the target is a net figure and
     mixing the two is how a comparison stops meaning anything. Billed minutes
     rather than the card's, because a shopping order really does occupy the
     time the allowance describes. */
  /* Whether a row is evidence about the market, as opposed to a row worth
     keeping.
   *
   * Every figure in this project that is derived from more than one offer has
   * to agree about this, and for a while two places did not: the page had its
   * own copy alongside a comment claiming they were the same test. They were
   * not, and whichever happened to be stricter silently governed a different
   * set of figures from the other.
   *
   * Four exclusions, and each is a different kind of "no":
   *   hidden — the driver said this was not an offer they were made. The test
   *            card presented to check the rig is not a job.
   *   suspect — the reading cannot be true, so it is evidence about the camera
   *            rather than about the market.
   *   whole === false — only part of the journey was read, and a fragment
   *            always flatters: the same pay over less time. Left in, it pulls
   *            every figure and every recommendation upwards.
   *   a rate with no running cost taken off it, on a rig that takes running
   *            costs off — see grossRate below.
   *
   * `whole` is absent on rows written before it existed, and those were only
   * ever written when whole — so undefined counts as true. */
  function trustworthy(row) {
    return !!row && typeof row === 'object'
      && !row.hidden && !row.suspect && row.whole !== false
      && !grossRate(row);
  }

  /* A row whose $/hr is gross while every row around it is net.
   *
   * `rate()` charges no mileage at all for a distance it does not trust —
   * which is the right call, since costing a journey on a number that was
   * misread invents the correction as well as the distance. The consequence is
   * that such a row's $/hr is a gross figure, and on a rig with a cost per
   * mile it sits in the list a few dollars above where it belongs.
   *
   * Nothing the scanner writes today lands here. Every route to
   * `milesUncertain` also trips `suspect` or `whole === false`, both already
   * excluded above, and test_journal.py asserts that as a property rather than
   * trusting the coincidence. This is about the rows already on disk.
   *
   * Until 19 Aug 2026 the two thresholds were different numbers reached by
   * different reasoning in different parts of offer_parser.py: a distance was
   * distrusted above MAX_MPH, 55, and a reading called suspect above SANE_MPH,
   * 75. Every journey computing between the two — a real highway run, or a
   * misread landing in that band — was written distrusted, not suspect, and
   * whole. Those rows are still in the journal, they are indistinguishable
   * from clean ones to every test above, and each of them pulls the median,
   * both quartiles and the recommended line upwards.
   *
   * Guarded on the row's own `costPerMile`, which has been written on every
   * row since the journal existed. At zero nothing was ever deducted from
   * anything, so a cost-free rate is not out of step with its neighbours and
   * there is nothing to exclude — dropping it there would be throwing away a
   * perfectly good offer for a difference that does not exist. */
  function grossRate(row) {
    return !!row.milesUncertain
      && typeof row.costPerMile === 'number' && row.costPerMile > 0;
  }

  /* Two orders at once, and the one question the rig can honestly answer.
   *
   * Working two apps, the driver accepts an order and then a second offer
   * arrives while the first is still in the car. The question is whether both
   * fit. The obvious way to answer it is to map the four addresses and route
   * them, and this rig cannot do that — the measurement, from the driver's own
   * 836-offer export:
   *
   *   - The car is offline most of the time, so nothing can be geocoded at the
   *     moment the offer is on screen.
   *   - Caching geocodes ahead of time does not help. 971 place sightings hold
   *     814 distinct places: a cache built from three days of driving covers
   *     11% of the next day's. Restaurants repeat; customers do not.
   *   - 69% of the addresses name a town, but 66 of 177 name "Atlanta", which
   *     is twenty miles across. A centroid there is not a location.
   *   - Not one card in 836 stated a deadline, so "in time" has nothing on the
   *     card to be measured against.
   *
   * So this does not pretend to know the geography. It answers the part that is
   * arithmetic, which is the part a driver cannot do at a glance and the part
   * the card really does state: what the two jobs pay together, over a time
   * that is bounded at both ends.
   *
   *   worst — nothing is shared. The new job starts when the old one ends and
   *           the minutes simply add. This is a real lower bound: any route
   *           overlap at all makes it better.
   *   best  — the new job rides along inside the old one and costs only the
   *           longer of the two. Nothing can beat it.
   *
   * The truth is between, and where between is a fact about two maps on a phone
   * the driver is already looking at. That is the right division: the rig does
   * the arithmetic the driver cannot do while driving, and the driver does the
   * geography the rig cannot see. Claiming a single number here would be
   * claiming the geography, which is the one thing this file must not do.
   *
   * ACCEPT only when even the WORST case clears the line, for the same reason a
   * rate with no running cost taken off it cannot: a range that straddles the
   * target is a maybe, and a maybe drawn in green is a wrong answer.
   *
   * The active order's remaining pay is pro-rated by its remaining time rather
   * than counted whole. A driver twenty minutes into a twenty-five minute job
   * is not earning the entire fare in the last five minutes, and treating them
   * as if they were makes "just finish it" beat everything on earth in the last
   * moments of every order. */
  /* Where a place is, as coarsely as the card honestly allows.
   *
   * Two signals, both printed on the card and neither invented: the town after
   * the last comma, and the compass quadrant these addresses carry - NW, NE,
   * SW, SE. Of 960 places the parser reads off this driver's cards, 65% end in
   * a town and 47% carry a quadrant.
   *
   * A town alone is coarse: "Atlanta" covers 250 of those places. The quadrant
   * is what splits it, and it splits it well - the Atlanta dropoffs on file run
   * NE 50, NW 20, SE 10, SW 5. Together they are about the granularity of "side
   * of town", which is exactly what was asked for: not a distance, just enough
   * not to take two orders that end up in completely different places. */
  // A comma OR a full stop, because a street abbreviation eats the comma:
  // "Double Branches Ln & Sagamore Ct. Dallas" is a real dropoff on file. Three
  // letters at least, which is what keeps the abbreviation itself out - "Cobb
  // Pkwy. NW" must not report a town called NW - and keeps a state code like
  // "IL" from standing in for one.
  // ...and a short run of junk is allowed between the separator and the town,
  // because the card's icon row lands there: "Grace St & Hidden Forest Ct, }
  // Marietta", "Grady Grier Dr & New Towne Dr, , : Powder Springs", "Crestmont
  // Pkwy & Haygoode Dr, E Marietta". Either a non-letter glyph or a single
  // stray letter, at most three of them. Reads 15 more towns off this driver's
  // dropoffs and no false ones.
  //
  // A single stray letter of EITHER case, and the case is the correction. The
  // first version took an uppercase one only, and that is not a rule about
  // towns - it is an accident of which glyph tesseract picked for the same icon.
  // The identical mark comes back as "E Marietta" and as "j Powder Springs",
  // and taking one and refusing the other left `area()` returning **null** on
  // 25 of the 1528 places on file - the geography going silent on a town that
  // is printed perfectly plainly beside a piece of furniture. `offer_parser.py`
  // has said so in a comment since the address reader was written; this is the
  // other half of it.
  //
  // No US town name is preceded by a standalone one-letter word, so nothing
  // real is being skipped. On the driver's 210 distinct dropoffs it places
  // three more and moves 414 pairs off "cannot say" onto an answer - 382
  // `elsewhere`, 32 `same-town` - and changes no answer that was already given.
  var PLACE_TOWN = /[,.]\s*(?:[^A-Za-z\s]\s*|[A-Za-z]\s+){0,3}([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})?)\s*$/;
  var PLACE_QUADRANT = /\b(NW|NE|SW|SE)\b/;

  /* The tail of a full street address: "…, Powder Springs, GA 30127".
   *
   * An offer card almost never prints one - Uber does not say where a delivery
   * ends until it has been accepted - so this is here for the screen AFTER the
   * accept, read by OP.find_address and stored against the order in the car.
   *
   * It has to be stripped before PLACE_TOWN runs, because PLACE_TOWN anchors on
   * the END of the string and an address ends in a ZIP. Without this, feeding a
   * scanned address to area() returns null and the geography goes SILENT on
   * exactly the orders the scan was added to rescue. */
  var PLACE_ZIP = /,\s*([A-Za-z]{2})\s+(\d{5})(?:\s*-\s*\d{4})?\s*$/;

  function area(place) {
    if (typeof place !== 'string' || !place) return null;
    var z = PLACE_ZIP.exec(place);
    if (z) place = place.slice(0, z.index);
    var t = PLACE_TOWN.exec(place);
    var q = PLACE_QUADRANT.exec(place);
    if (!t && !q && !z) return null;
    return { town: t ? t[1].toLowerCase() : null, quadrant: q ? q[1] : null,
             zip: z ? z[2] : null };
  }

  /* --- which part of the day a row belongs to -----------------------------
   *
   * The time twin of area() above, and here for the same reason: it is a fact
   * about a row that more than one page needs, and the pages that need it must
   * not each keep their own copy of where the edges are.
   *
   * Eight three-hour blocks anchored on midnight. The offer log has drawn its
   * "By time of day" chart off exactly these since it was written; map.html
   * now filters by them. Two copies of eight edges is two answers to "which
   * hours does this driver work", and they drift the first time somebody
   * decides 2am belongs with the evening — which has already happened once, in
   * an analysis of the owner's week that cut it at 14:00/17:00/20:00/23:00/
   * 02:00 and got different block totals for the same offers.
   *
   * Eight and not twenty-four, which is the offer log's reasoning moved here
   * rather than restated: hourly rows would be mostly empty and mostly noise.
   * On the owner's real week five of these eight carry any offers at all —
   * 196, 33, 0, 0, 2, 361, 201, 373 — so even eight is generous.
   *
   * Local hours, off the reading device's own clock. That is what a driver
   * means by "nine to midnight", it is the rule the offer log's dayOf already
   * uses, and there is no timezone on a journal row to use instead.
   *
   * NOT here and deliberately: anything that reads a rate off a block. Five of
   * eight blocks on a week is a thin enough base that "evenings pay $14" wants
   * the number of separate evenings printed beside it, and that is what
   * daysIn() below is for. */
  var BLOCK_NAMES = ['12–3am', '3–6am', '6–9am', '9am–12', '12–3pm',
                     '3–6pm', '6–9pm', '9pm–12'];

  /* NULL for a stamp no clock can read, rather than an index.
   *
   * `new Date(8.64e15 + 1).getHours()` is NaN, `Math.floor(NaN / 3)` is NaN,
   * and the offer log indexed its block array with it — so one corrupt row
   * threw inside the chart pass and took the three charts below it with it.
   * This is not hypothetical for this journal: CLOCK_BELIEVABLE_UNTIL in
   * server.js exists because a row arrived stamped 1e20. The server filters
   * the LOW end (CLOCK_BELIEVABLE_AFTER, for a Pi that boots in 1970) and the
   * high end reaches the page. */
  function blockOf(at) {
    var hour = new Date(at).getHours();
    if (!isFinite(hour)) return null;
    return Math.floor(hour / 3);
  }

  /* How many separate days a pile of rows came off.
   *
   * The hazard in any by-the-hour view is that "9pm–12 pays $14.43" reads as a
   * habit and may be one evening. Measured on the owner's week: the three
   * busiest blocks rest on three separate evenings each, and 3–6am rests on
   * one — 33 offers, all of 20 September. This count is the only thing that
   * keeps those two apart, and the offer log already prints the same figure
   * over its chart for the same reason.
   *
   * A calendar date, and the offer log's 4am shift boundary is deliberately
   * NOT used: every block above lies inside one calendar date by construction,
   * so one date is exactly one occurrence of that block. Folding a midnight
   * block back into the previous evening would count two separate nights of
   * 12–3am as one day and undercount the very thing this is for. */
  function daysIn(rows) {
    var seen = Object.create(null), n = 0;
    (rows || []).forEach(function (r) {
      var d = new Date(r && r.at);
      if (!isFinite(d.getTime())) return;
      var key = d.getFullYear() + '/' + d.getMonth() + '/' + d.getDate();
      if (!(key in seen)) { seen[key] = true; n += 1; }
    });
    return n;
  }

  /* --- which areas paid, and whether that may be said at all ---------------
   *
   * The driver's question: "find areas where it might be best to find high
   * paying rides". The honest answer is a ranking, and the reason this is
   * forty lines of argument rather than a groupBy is that the OBVIOUS ranking
   * is noise, and it took a measurement rather than an opinion to find that
   * out.
   *
   * WHAT WAS MEASURED, on the owner's own week — 1,140 counted offers over
   * five driving days, 13–20 Sep 2026. Each line is a permutation test:
   * group the rates, compute Kruskal–Wallis H, then reshuffle the same rates
   * into the same group sizes a few hundred times and ask how often chance
   * alone does as well.
   *
   *   grouping                       groups  offers        p   verdict
   *   the place the card named          19      163   0.2260   NOISE
   *   ...with a floor of 8 offers        5       79   0.9400   NOISE
   *   the TOWN, from either end           9      367   0.0000   real
   *   the three-hour block                5    1,138   0.0000   real  (control)
   *
   * Every figure here is on the DRIVER'S clock, not the machine that measured
   * it. That matters and it was got wrong once: this rig's owner is at UTC-4,
   * a container measuring in UTC put the same offers four hours into the wrong
   * three-hour blocks, and the block census came out 382/220/112/0/0/0/254/198
   * against the true 196/33/0/0/2/361/201/373. `blockOf` reads the local clock
   * for exactly this reason, and so does everything below.
   *
   * So: ranking the PLACES — "Shake Shack $18.57, Chipotle $7.27" — is the
   * feature everybody wants and it is a coin toss wearing a decimal point. The
   * best-minus-worst spread across those nineteen places is $11.30, and
   * shuffling the rates at random produces a spread that big or bigger 36% of
   * the time. A page printing that ranking would be this project's first fault
   * class, a confidently wrong number, in the one place a driver would act on
   * it — they would drive across town to sit outside a restaurant chosen by
   * noise.
   *
   * The TOWN survives, and survives the obvious objection. It is not one night
   * out of the metro: restricted to the seven towns seen on four or more
   * separate dates it is still p < 0.001. It is not trip length dressed up
   * either — tested inside each third of the distance range separately it
   * holds in all three (p = 0.0000 / 0.0020 / 0.0000), and Atlanta leads all
   * three. The best town's median trip is no longer than the worst's: Atlanta
   * $20.07/hr over 9.2 miles against Marietta $14.63 over 9.5.
   *
   * WHY THE TEST IS IN THE PAGE AND NOT JUST IN THIS COMMENT. Those numbers
   * are one week of one driver. The next window, the next month and the next
   * driver are not that week, and a threshold tuned to it is a threshold that
   * will be wrong somewhere else without saying so. So the page runs the test
   * on whatever is loaded and refuses the ranking when it does not beat
   * chance. That is cheap: the ranks are computed once and a shuffle only
   * reassigns them, so this is O(n) per shuffle and a few milliseconds on a
   * window the server will actually send.
   *
   * WHAT `key` IS AND WHY IT IS AN ARGUMENT. The grouping comes from the
   * CARD — the town the rig read off it — never from a geocoder. That is the
   * whole safety argument of map-view.js applied here: a lookup may position
   * one of these figures on a map, and may never change one. This file does
   * not know how to parse a place name and must not learn; the caller passes
   * `MapView.townOf`, which is the tail rule `localityOf` has always used.
   *
   * Nothing here reads `lat`, `lon`, or any answer a geocoder gave.
   */

  /* Below this a median is not a number to read. Eight offers is the floor,
   * and the day count beside it is not a second opinion about the same thing:
   * eight offers from one evening is one evening, which this file has said
   * since `daysIn`. */
  var AREA_FLOOR = 8;
  var AREA_DAYS = 2;
  /* Enough shuffles to resolve the alpha below with room to spare, and few
   * enough that this stays under a frame on the biggest window the server
   * sends. 500 gives p to the nearest 0.002. */
  var AREA_SHUFFLES = 500;
  var AREA_ALPHA = 0.05;

  /* Ranks, with ties averaged, which is what makes the test hold for a
   * distribution as skewed as offer rates. A mean over $/hr is dragged by the
   * one misread that got through; a rank is not. */
  function ranksOf(values) {
    var order = values.map(function (v, i) { return i; })
                      .sort(function (a, b) { return values[a] - values[b]; });
    var ranks = new Array(values.length);
    var i = 0;
    while (i < order.length) {
      var j = i;
      while (j + 1 < order.length && values[order[j + 1]] === values[order[i]]) j += 1;
      var shared = (i + j) / 2 + 1;
      for (var k = i; k <= j; k++) ranks[order[k]] = shared;
      i = j + 1;
    }
    return ranks;
  }

  /* Kruskal–Wallis H over ranks already computed, given the group sizes in
   * the order the ranks are laid out. Written to take the ranks rather than
   * the values precisely so a shuffle costs a shuffle and not a re-sort. */
  function kruskal(ranks, sizes) {
    var n = ranks.length;
    if (n < 2) return 0;
    var mid = (n + 1) / 2, out = 0, pos = 0;
    for (var g = 0; g < sizes.length; g++) {
      var sum = 0;
      for (var i = 0; i < sizes[g]; i++) sum += ranks[pos + i];
      pos += sizes[g];
      var gap = sum / sizes[g] - mid;
      out += sizes[g] * gap * gap;
    }
    return 12 / (n * (n + 1)) * out;
  }

  /* A seeded shuffle, because a page that answers "this is chance" on one
   * press and "this is real" on the next, over the same rows, has told the
   * driver nothing twice. The seed is fixed: the same window always gets the
   * same verdict, and a test can assert it.
   *
   * `pens` is the one thing that makes this a fair test rather than a
   * flattering one. Given a list of index-lists, values are only ever
   * exchanged WITHIN a list — so a shuffle can move an offer between towns but
   * never between hours, and the question the test answers becomes "does the
   * town matter once the hour is held still" instead of "does the town matter,
   * counting the hours the driver happened to be in it". See `areas`. */
  function shuffled(ranks, seed, pens) {
    var a = ranks.slice(), s = seed >>> 0;
    function swirl(idx) {
      for (var i = idx.length - 1; i > 0; i--) {
        // Numerical Recipes' LCG, which is plenty for reassigning labels.
        s = (1664525 * s + 1013904223) >>> 0;
        var j = s % (i + 1);
        var t = a[idx[i]]; a[idx[i]] = a[idx[j]]; a[idx[j]] = t;
      }
    }
    if (pens) { for (var p = 0; p < pens.length; p++) swirl(pens[p]); }
    else {
      var all = [];
      for (var k = 0; k < a.length; k++) all.push(k);
      swirl(all);
    }
    return a;
  }

  /* The ranking, its support, and whether it beats chance.
   *
   * Returns the groups that clear the floor, best first, and — always — what
   * was left out and why. A ranking that quietly drops the eleven towns with
   * three offers each reports the window as tidier than it is, which is this
   * project's second fault class.
   */
  function areas(offers, opts) {
    opts = opts || {};
    var key = opts.key;
    var floor = typeof opts.floor === 'number' ? opts.floor : AREA_FLOOR;
    var needDays = typeof opts.days === 'number' ? opts.days : AREA_DAYS;
    var alpha = typeof opts.alpha === 'number' ? opts.alpha : AREA_ALPHA;
    // What must be held still while the groups are compared. Optional, and
    // the caller supplies it for the same reason it supplies `key`: this file
    // knows what a rate is and not what an hour of the driver's night is.
    var strata = typeof opts.strata === 'function' ? opts.strata : null;
    var shuffles = typeof opts.shuffles === 'number' ? opts.shuffles : AREA_SHUFFLES;
    var out = { groups: [], kept: 0, named: 0, unnamed: 0,
                thin: 0, thinOffers: 0, p: null, real: false, spread: null,
                rawSpread: null, matched: false,
                floor: floor, days: needDays };
    if (typeof key !== 'function') return out;

    // `trustworthy`, not a fourth copy of the rule. A row the rig would not
    // stand behind is not evidence about a town, and the offer log and the
    // panel already agree on what that means.
    var pool = (offers || []).filter(function (o) {
      return trustworthy(o) && typeof o.perHour === 'number' && isFinite(o.perHour);
    });

    var byKey = Object.create(null), order = [];
    pool.forEach(function (o) {
      var name = key(o);
      if (!name) { out.unnamed += 1; return; }
      out.named += 1;
      if (!byKey[name]) { byKey[name] = []; order.push(name); }
      byKey[name].push(o);
    });

    var kept = [];
    order.forEach(function (name) {
      var rows = byKey[name];
      // outingsIn, not daysIn: see its comment. An area is not tied to an
      // hour, so a single overnight shift must not report two days.
      var days = outingsIn(rows);
      if (rows.length < floor || days < needDays) {
        out.thin += 1;
        out.thinOffers += rows.length;
        return;
      }
      kept.push({ name: name, n: rows.length, days: days,
                  median: Math.round(median(rows.map(function (o) {
                    return o.perHour;
                  })) * 100) / 100,
                  took: rows.filter(function (o) { return o.accepted === true; }).length,
                  offers: rows });
    });
    kept.sort(function (a, b) { return b.median - a.median; });
    out.groups = kept;
    out.kept = kept.reduce(function (s, g) { return s + g.n; }, 0);
    if (kept.length < 2) return out;
    out.spread = Math.round((kept[0].median - kept[kept.length - 1].median) * 100) / 100;

    // The test. Ranks over the kept rates once; a shuffle only reassigns them.
    var flat = [], pen = [];
    kept.forEach(function (g) {
      g.offers.forEach(function (o) {
        flat.push(o.perHour);
        pen.push(strata ? String(strata(o)) : '');
      });
    });
    var sizes = kept.map(function (g) { return g.n; });
    var ranks = ranksOf(flat);
    var real = kruskal(ranks, sizes);

    /* HOLDING THE HOUR STILL, which is the difference between a finding and a
     * flattering one — and this shipped without it for exactly as long as it
     * took two independent readers to catch it.
     *
     * The rate a town pays is tangled with WHEN the driver is in it. Measured
     * on the owner's week, on his clock: 12–3am pays $21.24 and 3–6pm pays
     * $14.17, and 57 of Atlanta's 98 offers are in the 12–3am block while 41
     * of Kennesaw's 69 and 40 of Marietta's 82 are in the 3–6pm one. So the
     * raw ranking — Atlanta $20.01 against Marietta $14.63 — is partly a fact
     * about the towns and partly a fact about the clock, and a driver reading
     * it would go to Atlanta at six in the evening and find $14.
     *
     * With the hours held still the town still matters and matters LESS: the
     * gap from top to fourth goes from **$4.20 to $1.09**, and the order moves
     * (Mableton to the top, Smyrna from sixth to last at −$3.11). That is a
     * number a driver acts on being four times larger than the truth, which is
     * this project's first fault class, so it is not an enrichment — it is the
     * correction that makes the feature honest.
     *
     * Two halves, and both are needed. `matched` below is how much of a town's
     * rate is left once each offer is measured against what its own hour paid;
     * the shuffle above is confined to the same pens, so the test asks the
     * same question the number answers. */
    var pens = null;
    if (strata) {
      var byPen = Object.create(null);
      pen.forEach(function (k, i) { (byPen[k] = byPen[k] || []).push(i); });
      pens = Object.keys(byPen).map(function (k) { return byPen[k]; });
    }
    /* ...unless there is only one pen, in which case there is nothing to hold
     * still and saying otherwise is noise. That is the ordinary case once the
     * driver has picked a three-hour block: the filter has already held the
     * hour, every offer is measured against the same baseline, and `matched`
     * would be the median shifted by a constant — the same order, reported as
     * though something had been controlled for. The plain median is the right
     * number there, and the page says the plainer sentence. */
    if (pens && pens.length > 1) {
      // What each hour paid, over the kept pool and nothing wider: a town is
      // being compared with the other towns on this page, not with a journal.
      var penRates = Object.create(null);
      Object.keys(byPen).forEach(function (k) {
        penRates[k] = median(byPen[k].map(function (i) { return flat[i]; }));
      });
      var seen = 0;
      kept.forEach(function (g) {
        var diffs = g.offers.map(function (o) {
          return flat[seen] - penRates[pen[seen++]];
        });
        g.matched = Math.round(median(diffs) * 100) / 100;
      });
      // Ordered by what is left, not by what it paid. The question is which
      // town is worth being in, and the raw figure answers a different one.
      kept.sort(function (a, b) { return b.matched - a.matched; });
      out.matched = true;
      out.spread = Math.round((kept[0].matched
                               - kept[kept.length - 1].matched) * 100) / 100;
      out.rawSpread = Math.round((Math.max.apply(null, kept.map(function (g) { return g.median; }))
                                  - Math.min.apply(null, kept.map(function (g) { return g.median; }))) * 100) / 100;
    }

    var asGood = 0;
    for (var s = 0; s < shuffles; s++) {
      if (kruskal(shuffled(ranks, s + 1, pens), sizes) >= real) asGood += 1;
    }
    out.h = Math.round(real * 100) / 100;
    out.p = asGood / shuffles;
    out.real = out.p < alpha;
    return out;
  }

  /* When a driver's day starts, which is not when the calendar's does.
   *
   * 4am is the conventional boundary for shift work and nobody is driving
   * then, so no shift can straddle it. `journal.html` and `live.html` have
   * each carried this number since long before this file did; they now read it
   * from here so the three cannot come apart, and their own day helpers stay
   * where they are because each does more than return a key.
   */
  var DAY_STARTS_AT = 4;

  /* How many separate OUTINGS a pile of rows came off — which is a different
   * question from `daysIn` above, not a second answer to it.
   *
   * `daysIn` counts calendar dates and is right for a BLOCK, for the reason
   * written there: every three-hour block lies inside one calendar date by
   * construction, so one date is exactly one occurrence of it, and folding
   * midnight back into the previous evening would count two separate nights of
   * 12–3am as one.
   *
   * An area is not tied to an hour, and that same rule breaks it. A single
   * shift from 8pm to 2am touches two calendar dates, so an area seen only on
   * that one outing reports **two days** and clears a floor of two — which is
   * precisely the "one evening wearing a habit's clothes" the floor exists to
   * refuse, arriving through the calendar rather than through the data. This
   * driver works nights: on the owner's own week the calendar says six dates
   * where five shifts were driven, and Atlanta read `days=6` against five
   * outings before this existed.
   */
  function outingsIn(rows) {
    var seen = Object.create(null), n = 0;
    (rows || []).forEach(function (r) {
      var d = new Date(r && r.at);
      if (!isFinite(d.getTime())) return;
      d.setHours(d.getHours() - DAY_STARTS_AT);
      var key = d.getFullYear() + '/' + d.getMonth() + '/' + d.getDate();
      if (!(key in seen)) { seen[key] = true; n += 1; }
    });
    return n;
  }

  /* Do these two jobs end anywhere near each other?
   *
   * Deliberately asymmetric, because the two mistakes cost different amounts. A
   * wrong "elsewhere" costs a stack the driver could have taken. A wrong
   * "near" costs an hour, a late delivery and a rating. So "near" is only said
   * when the two agree on everything they both state, and "elsewhere" the
   * moment they disagree on anything.
   *
   * It says what it checked rather than how far apart they are, because how far
   * apart they are is not something these cards can support. A town and a
   * quadrant that both agree is 'same-side'; a town alone is 'same-town', which
   * is a weaker claim and is reported as one - 354 of the agreeing pairs on
   * file are Atlanta NE to Atlanta NE, and northeast Atlanta is not a
   * neighbourhood. The driver knows which of their towns are big.
   *
   * A ZIP outranks both, and is the reason scanning the post-acceptance screen
   * is worth doing at all. It is the finest thing available - a metro ZIP is a
   * few square miles, where "same town" in Atlanta is a hundred and thirty-five
   * of them and 44% of this driver's placed dropoffs are in Atlanta. So two
   * addresses in one ZIP get their own answer rather than being flattened into
   * the claim that covers half the county.
   *
   * But only in the AGREEING direction, and that asymmetry is deliberate.
   * Different ZIPs are not evidence of distance: they tile finely, so
   * neighbouring ones are next door to each other, and concluding 'elsewhere'
   * from a ZIP that merely differs would refuse stacks that are a mile apart.
   * Saying it the other way round - a wrong 'elsewhere' costs a fare, a wrong
   * 'near' costs an hour and a rating - the safe use of a fine-grained key is
   * to STRENGTHEN a near, never to manufacture a far. Deciding how far apart
   * two different ZIPs are needs their centroids, which this rig does not have
   * and will not guess at.
   *
   * Returns 'same-zip', 'elsewhere', 'same-side', 'same-town', or null for "the
   * cards did not say enough" - which is about half of real pairs, and is the
   * honest answer rather than a guess dressed up as one. */
  /* --- handing a place to a map ------------------------------------------
   *
   * The cards name places in words - "Duval Ct & Manchester Ln, Villa Rica" -
   * and a map takes words. So no coordinates are computed here, and none are
   * needed: the query goes to Google as text and Google resolves it, on the
   * driver's own device, at the moment they ask.
   *
   * That is not a shortcut, it is the safer design, and the reason is the
   * failure mode. A geocoder run by this rig would turn a misread street into a
   * confident coordinate and then into a distance on the panel, wrong and
   * silent - the failure this project refuses above all others. A map opened by
   * the driver puts the same misreading on a screen as a PIN IN THE WRONG
   * PLACE, which a person spots instantly and dismisses. The check moves from
   * the machine, which cannot do it, to the human, who can.
   *
   * It also answers the harder question the arithmetic here cannot: a route
   * gives real driving time with real traffic, where a straight line between
   * two dropoffs would be three miles that might be five minutes or twenty.
   *
   * No API key, no rate limit, no cost, and - because the request is made by
   * the driver's browser and not by this rig - no customer's home address is
   * ever sent anywhere by the rig itself. See the Maps URLs API, which is the
   * documented keyless form. */
  function mapQuery(place) {
    if (typeof place !== 'string') return null;
    var text = place.replace(/\s+/g, ' ').trim();
    // Enough of a place to be worth searching. Two letters somewhere and a few
    // characters: below that it is icon-row scrap, and a map given scrap
    // answers with somewhere confident and irrelevant.
    if (text.length < 4 || !/[A-Za-z]{2}/.test(text)) return null;
    return text;
  }

  function mapSearch(place) {
    var q = mapQuery(place);
    return q ? 'https://www.google.com/maps/search/?api=1&query='
             + encodeURIComponent(q) : null;
  }

  function mapRoute(from, to) {
    var a = mapQuery(from), b = mapQuery(to);
    if (!a || !b) return null;
    // Deliberately no waypoint and no second leg. This asks one question -
    // how far apart do these two ends sit, in driving time, right now - and a
    // route the rig invented through a pickup it is guessing at would answer a
    // question nobody asked.
    return 'https://www.google.com/maps/dir/?api=1&origin='
         + encodeURIComponent(a) + '&destination=' + encodeURIComponent(b)
         + '&travelmode=driving';
  }

  /* Two readings of one town, or two towns?
   *
   * PLACE_TOWN allows a second capitalised word, because towns really have
   * them - Powder Springs, Sandy Springs and Lithia Springs are all on this
   * driver's cards - and it anchors on the END of the string. So when the OCR
   * puts one more capitalised word after the town, that word joins the town:
   * `Cobb Pkwy NW, Acworth Page`, `Canton Pl NW, Kennesaw State`,
   * `Farmington Dr SW & Hereford Ct SW, Marietta BORE`.
   *
   * Twenty-one of the 73 distinct town readings on file are a real town with
   * one junk word stuck to it, and one more is the other shape - `sandy` where
   * the card said Sandy Springs. Between them they were turning 96 pairs of
   * real dropoffs into `elsewhere` on nothing but OCR damage.
   *
   * Dropping the second word is not the fix. The regex anchors on the end, so
   * `Sandy Springs` would then read as `springs` and the two readings of it
   * would stop relating at all.
   *
   * What every one of these has in common is that one reading is the other
   * plus or minus a WHOLE WORD at the end. That is the test, and the word
   * boundary is what makes it safe: Douglas and Douglasville are two different
   * Georgia towns and this does not join them.
   *
   * It only ever withdraws an `elsewhere`. It never manufactures a `near` -
   * see where it lands below. Over every pair of the 210 distinct dropoffs on
   * file it moves 96 pairs from `elsewhere` to null and nothing else moves: no
   * new `same-town` is created, and not one of the 22 town pairs it stops
   * calling `elsewhere` is actually two different towns. When it is wrong the
   * cost is silence, which is what this line already gives on half of real
   * pairs; calling them `same-town` instead would stake the expensive mistake
   * - an hour and a rating - on a guess about OCR damage. */
  function couldBeOneTown(a, b) {
    if (a === b) return true;
    var shorter = a.length <= b.length ? a : b;
    var longer = a.length <= b.length ? b : a;
    return longer.indexOf(shorter + ' ') === 0;
  }

  function sameArea(a, b) {
    var x = area(a), y = area(b);
    if (!x || !y) return null;
    if (x.zip && y.zip && x.zip === y.zip) return 'same-zip';
    if (x.town && y.town && !couldBeOneTown(x.town, y.town)) return 'elsewhere';
    if (x.quadrant && y.quadrant && x.quadrant !== y.quadrant) return 'elsewhere';
    if (!x.town || !y.town || x.town !== y.town) {
      // Same quadrant, no town on one of them: a quadrant is a whole side of
      // the metro, and on its own that is not enough to promise anything. A
      // ZIP on one side and not the other lands here too, and for the same
      // reason - one address being precise says nothing about the other.
      //
      // Two readings that COULD be one town land here as well, and this is
      // where couldBeOneTown is kept honest. Getting past the veto above is
      // not the same as agreeing: "these might be the same town" must not be
      // reported as "these are near each other".
      return null;
    }
    return (x.quadrant && y.quadrant) ? 'same-side' : 'same-town';
  }

  function stack(active, offer, settings, now) {
    if (!active || !offer) return null;
    var target = (settings && typeof settings.target === 'number')
      ? settings.target : 0;
    // A figure rate() refused to score cannot be re-scored here.
    //
    // rate() withholds the verdict on an impossible reading — `state: 'doubt'`
    // — but keeps `ready: true` and every number, because the row still has to
    // reach the journal. This function looked at neither, so it rebuilt a full
    // money verdict out of the same figures doubt() had just declared could
    // not all be true. Real pair off this driver's own record: held $11.84 /
    // 20 min, next card's pay read as $1184, headline blanked to "--" with
    // CHECK THE PAY above — and directly beneath it, in green, "+ the one you
    // have: $1791–$3580/hr over 20–40 min · beats finishing alone". 6 of 337
    // real pairs carry an offer today's doubt() refuses and 5 of those came
    // out green.
    //
    // Both sides, because a doubted order in the car poisons `netA` exactly as
    // a doubted offer poisons `netB`. Silence is already the right answer on
    // about half of real pairs; this is one more place it is the right answer.
    if (active.doubt || offer.doubt) return null;
    var totalA = num(active.minutes);
    var payA = num(active.pay);
    var minB = num(offer.minutes);
    var payB = num(offer.pay);
    if (totalA === null || payA === null || minB === null || payB === null) return null;
    if (!(totalA > 0) || !(minB > 0)) return null;

    var startedAt = num(active.acceptedAt);
    var elapsed = (startedAt === null || typeof now !== 'number')
      ? 0 : Math.max(0, (now - startedAt) / 60000);
    var left = Math.max(0, totalA - elapsed);
    // The old order is done, or as good as. There is nothing to stack onto and
    // saying otherwise would put a second job's time against a first job's pay.
    if (left <= 0) return null;

    var costA = num(active.cost) || 0;
    var costB = num(offer.cost) || 0;
    var netA = (payA - costA) * (left / totalA);
    var netB = payB - costB;
    var money = netA + netB;
    // ...and whether "net" is what those two words mean here.
    //
    // The same rule rate() applies to one offer, applied to a pair: when a cost
    // per mile is configured and no cost could be taken off — the card printed
    // no distance, or the distance was not trusted — the figure is GROSS, and
    // `target` is a line the driver drew against net rates. Comparing the two
    // is comparing different kinds of money.
    //
    // rate() has capped its own verdict at 'warn' for this since the uncosted
    // cap was written; stack() went straight to `worst >= target ? 'go'` and
    // called a gross number green. On this driver's own 3,065 recorded offers
    // 788 — 26% — had no running cost taken off, and 188 of those clear the
    // $25 target on the gross figure alone: exactly the pool where the cap is
    // the difference between a green and an amber.
    //
    // Either side, because either one being gross makes `money` gross. Capped
    // and not withheld, for rate()'s reason: CLOSE CALL is the honest answer to
    // "this might clear your line and I cannot tell".
    var costPerMile = (settings && typeof settings.costPerMile === 'number')
      ? settings.costPerMile : 0;
    var uncosted = costPerMile > 0 && (costA === 0 || costB === 0);
    /* ...and which SIDE is gross, because `sure` below is not symmetric the way
       `state` is.
       `sure` is `worst >= alone`, and `alone` is the held job's own net rate.
       A gross OFFER inflates `money`, so it inflates `worst` alone and the
       claim can come out true when the truth is that it is not: that is the
       direction that misleads. A gross HELD job inflates netA, which is in
       both — but `alone` divides it by `left` where `worst` divides it by
       `left + minB`, so the right-hand side rises faster and the claim gets
       harder to make. That direction understates, which is the safe one and
       costs nothing to allow. */
    var offerGross = costPerMile > 0 && costB === 0;

    var maxMinutes = left + minB;              // nothing shared
    var minMinutes = Math.max(left, minB);     // the new one rides along
    var worst = money / (maxMinutes / 60);
    var best = money / (minMinutes / 60);
    // What the minutes already committed pay if this offer is declined. Not a
    // full picture of declining — something better may well arrive — but it is
    // the one alternative that is certain, and it is the floor to beat.
    var alone = netA / (left / 60);

    return {
      leftMinutes: Math.round(left * 10) / 10,
      minMinutes: Math.round(minMinutes * 10) / 10,
      maxMinutes: Math.round(maxMinutes * 10) / 10,
      pay: Math.round(money * 100) / 100,
      worst: Math.round(worst * 100) / 100,
      best: Math.round(best * 100) / 100,
      alone: Math.round(alone * 100) / 100,
      // Better than finishing alone even with no route shared at all. This is
      // the claim that does not depend on the geography, so it is the only one
      // stated without a hedge — which is exactly why it may not be made on a
      // figure that is a ceiling rather than a rate.
      //
      // `state` has been capped for this since the uncosted cap was written,
      // and the seventeen lines above say why: `target` is a line the driver
      // drew against net rates, and comparing the two is comparing different
      // kinds of money. `sure` compares the same two kinds and went on saying
      // "beats finishing alone" without a hedge, on the one clause of the stack
      // line that the 3.5" hat has room for.
      //
      // Withheld only when the OFFER is the gross one. See offerGross: a gross
      // held job pushes this the other way and understates it, which is the
      // safe direction and not worth losing a true claim over.
      //
      // THREE VALUES, not two. Withheld is `null`; `false` means the claim was
      // made and is no. They were the same value here, and a reader cannot
      // undo that: the offers page printed `sure ? yes : "no — the worst end
      // is below finishing alone"` and so announced the OPPOSITE of the truth
      // on every withheld pair. Of the (held, gross-offer) pairs that can be
      // drawn from the owner's own week, 77.4% have worst >= alone, so the
      // printed "no" is false about three times in four.
      //
      // Null and not a separate field because there is one question here and
      // one answer to it, and "not asked" is one of the answers. Every reader
      // that tests it for truth — live.html's ' · beats finishing alone', the
      // panel's own line — keeps behaving exactly as before, because null is
      // falsy and saying nothing is what withheld means to them.
      sure: offerGross ? null : worst >= alone,
      // Where the two jobs END, compared as coarsely as the cards allow. This
      // is the half of the question the time arithmetic above cannot reach:
      // `maxMinutes` assumes nothing is shared and `minMinutes` assumes the
      // new job rides along inside the old one, and which of those is true is
      // decided by geography. 'elsewhere' means the range above should be read
      // from its worst end. See sameArea.
      ends: sameArea(active && active.dropoff, offer && offer.dropoff),
      // ...and the same question handed to a map, which can answer it in
      // driving minutes where `ends` can only answer it in the card's own
      // words. Both ends are DROPOFFS: this asks how far apart the two jobs
      // finish, which is the half the arithmetic above cannot reach and the
      // half the driver said decides it. Null when either end was not named,
      // which is about half of real pairs. See mapRoute.
      route: mapRoute(active && active.dropoff, offer && offer.dropoff),
      // Whether the money above is the pair or only a ceiling on it, so a
      // display can say which it is showing — the same field, and the same
      // word, rate() returns for one offer.
      uncosted: uncosted,
      state: (uncosted && worst >= target) ? 'warn'
           : worst >= target ? 'go'
           : (best >= target ? 'warn' : 'no')
    };
  }

  function num(v) {
    return (typeof v === 'number' && isFinite(v)) ? v : null;
  }

  function usable(offers) {
    var out = [];
    for (var i = 0; i < (offers || []).length; i++) {
      var o = offers[i];
      if (!trustworthy(o)) continue;
      var mins = typeof o.billedMinutes === 'number' ? o.billedMinutes : o.minutes;
      if (typeof o.pay !== 'number' || !isFinite(o.pay)) continue;
      if (typeof mins !== 'number' || !isFinite(mins) || !(mins > 0)) continue;
      // When the offer *appeared*, not when the last correction to it was
      // written. A card read at 18:00 and re-read better at 18:01 carries
      // `at` 18:01, and the replay is a simulation of a shift in the order
      // things arrived — so the arrival is the honest field. The difference is
      // seconds and it has never changed an answer; it is the right one to
      // divide a shift by all the same.
      var seenAt = (typeof o.firstAt === 'number' && isFinite(o.firstAt))
        ? o.firstAt : o.at;
      if (typeof seenAt !== 'number' || !isFinite(seenAt)) continue;
      var net = o.pay - (typeof o.cost === 'number' && isFinite(o.cost) ? o.cost : 0);
      // Whether the driver said they took this one. Used only to work out when
      // they were busy — see runs(). The replay deliberately never looks at it:
      // it is simulating a policy, and what actually happened is the thing it
      // is being compared against.
      out.push({ at: seenAt, net: net, mins: mins, perHour: net / (mins / 60),
                 // Carried so a caller can join what busy() returns back onto
                 // the row it is about. Nothing in the replay reads it.
                 id: o.id,
                 took: o.accepted === true });
    }
    out.sort(function (a, b) { return a.at - b.at; });
    return out;
  }

  /* Stretches of clock the scanner was being shown offers, split wherever it
     went quiet for longer than `breakMinutes`.

     This is the honest name for what used to be called a shift. It is not one:
     a single run can be half a shift, and a rig left switched on in a driveway
     produces a run with two offers in three hours. Runs of one offer have no
     span at all and are dropped rather than counted as an instant of driving.

     The gap is measured from when the previous offer's work *finished*, not
     from when it appeared. A driver who accepts a twenty-minute job is not
     shown another offer for twenty minutes, and counting that silence as a
     break is the difference between an answer and no answer: on one real
     recording, eight of the fifteen gaps over ten minutes came straight after
     an accepted trip, and subtracting each trip's own length left between
     minus nine and plus twelve minutes of actual waiting. Raw, the gaps smear
     evenly across 15–38 minutes and there is no defensible place to cut, so
     the suggested line swung from $39 to $19 depending on where you cut and
     the whole thing was refused as unsettled. Corrected, the same data
     answers $19 at every threshold from fifteen minutes to ninety.

     This only knows about trips the driver *told* it about. An untagged take
     still reads as a break — which is a reason to tag them, not a reason to
     guess. */
  /* When the driver was free again after this offer.
   *
   * The moment it appeared, unless they ticked it — in which case the job it
   * describes occupied them for the minutes it stated. This is the one piece
   * of occupancy the record actually contains, as opposed to the replay's
   * simulated version of it.
   *
   * One function because the same expression was written out twice, in runs()
   * and in unexplained(), and the two are answering the same question about
   * the same rows. Two copies of a rule drift.
   *
   * `mins` is billed minutes — what usable() carries — and on this driver's
   * record that is identical to the card's own on all 1,672 rows, because the
   * pad and the shopping allowance are both zero and no ticked row is a shop
   * order. So the choice is unobservable here and has to be argued rather than
   * measured: billed is what the driver is occupied for, which is the question.
   *
   * It is a FLOOR on occupancy and not a measurement of it. A job runs late,
   * a pickup waits, and this rig's own server calls a job live for minutes ×
   * 1.5 + 10 (see holding() in server.js) — which over this record would mark
   * 830 of 1,672 offers busy against 333 for the stated minutes. Two
   * definitions of one idea, and this is the conservative one on purpose:
   * every use of it below is a disclosure, never a correction to a figure. */
  function freeAgain(row) {
    return row.took ? row.at + row.mins * 60000 : row.at;
  }

  /* ...and the latest such moment so far, which is not the same as the last
   * row's.
   *
   * Asking only the PREVIOUS row when the driver was free throws the trip's
   * length away the instant another offer is scanned during it — and offers
   * arriving mid-trip is not an edge case, it is the normal thing: the phone
   * keeps showing cards while the driver is carrying someone, which is exactly
   * what replay() models when it skips everything before `busyUntil`. So the
   * two halves of this file were reading the same rows under two different
   * pictures of the shift.
   *
   * Measured, on a tagged hour-long trip with one offer glimpsed five minutes
   * in and the next arriving at fifty-eight:
   *
   *   previous row only   the run splits at 58; the offer after the trip is
   *                       left alone in a one-row run and DROPPED; and a
   *                       silence is counted against a stretch the driver had
   *                       already tagged — so the page asks for a tag on the
   *                       one trip that has one.
   *   latest so far       one run of three, nothing dropped, no silence.
   *
   * Without the mid-trip scan the old code got the right answer. A row being
   * *seen* made the record worse, which is backwards.
   *
   * busy() below was already right — it asks every earlier ticked row whether
   * its window covers this one, rather than only the last. So two of the three
   * places in this file that reason about occupancy agreed, and these were the
   * two that did not.
   *
   * This is deliberately a running maximum over every earlier row and not a
   * window: rows are sorted, so an untagged row's own `at` becomes the maximum
   * as soon as the clock passes the last trip's end, and the figure only ever
   * reaches forward while a tagged job says the driver is still in it. The
   * exposure that buys is a single over-long `mins` covering more silence than
   * it should — the same trust replay() already places in the same field, and
   * freeAgain's header explains why it is a floor. */
  function occupancy(rows) {
    var out = [];
    var free = -Infinity;
    for (var i = 0; i < rows.length; i++) {
      free = Math.max(free, freeAgain(rows[i]));
      out.push(free);
    }
    return out;
  }

  function runs(rows, breakMinutes) {
    if (!rows.length) return [];
    var gap = (breakMinutes || SHOWN_AT) * 60000;
    var free = occupancy(rows);
    var out = [[rows[0]]];
    for (var i = 1; i < rows.length; i++) {
      if (rows[i].at - free[i - 1] > gap) out.push([rows[i]]);
      else out[out.length - 1].push(rows[i]);
    }
    return out.filter(function (r) { return r.length > 1 && r[r.length - 1].at > r[0].at; });
  }

  /* The shift as it would have gone, holding out for `target`.
   *
   * Free, take the first offer at or above the line; then busy for exactly as
   * long as that offer said. Everything arriving meanwhile is skipped, which is
   * not an approximation — it is what happened to the offers that arrived while
   * the driver was already carrying somebody. */
  function replay(theRuns, target) {
    var earned = 0, seconds = 0, trips = 0, seen = 0;
    for (var r = 0; r < theRuns.length; r++) {
      var run = theRuns[r];
      var lastAt = run[run.length - 1].at;
      var busyUntil = -Infinity;
      for (var i = 0; i < run.length; i++) {
        var o = run[i];
        seen++;
        if (o.at < busyUntil) continue;
        if (o.perHour >= target) {
          earned += o.net;
          trips++;
          busyUntil = o.at + o.mins * 60000;
        }
      }
      // The clock runs until the last trip finishes, not until the last offer
      // appeared. Without this a run of two offers thirty seconds apart could
      // be credited with a whole thirty-minute fare over a thirty-second
      // denominator — thousands of dollars an hour, from two rows — and a
      // handful of those is enough to move which line comes out best. A trip
      // accepted at the end of a run really does occupy the driver for its
      // whole length; the scanner simply stops seeing offers during it.
      seconds += (Math.max(lastAt, isFinite(busyUntil) ? busyUntil : lastAt)
                  - run[0].at) / 1000;
    }
    return {
      target: target,
      earned: earned,
      hours: seconds / 3600,
      perHour: seconds > 0 ? earned / (seconds / 3600) : 0,
      trips: trips,
      // How many offers this walk actually looked at. `takes` is a fraction of
      // it, and without it the fraction has no stated denominator — which is
      // how the journal page came to print `takes` beside a percentage worked
      // out over a different set, and invite the reader to subtract them. It
      // is not the same as the number of offers handed in: `runs()` drops the
      // ones that fall outside a run of scanning.
      seen: seen,
      takes: seen ? trips / seen : 0
    };
  }

  function ladder() {
    var out = [];
    for (var t = 0; t <= LADDER_MAX; t++) out.push(t);
    return out;
  }

  /* Silences nothing accounts for, and how many trips were tagged at all.
   *
   * A silence longer than the break threshold is either a break or a trip the
   * driver did not tag, and those two are indistinguishable from here — which
   * is the whole difficulty runs() is up against. Counting them is what lets
   * the page say something better than "drive more": on the recording that
   * prompted this, eleven trips were tagged out of two hundred and thirty-three
   * offers, and tagging a few more of the long silences was worth more than
   * another whole shift of scanning would have been. */
  function unexplained(rows, breakMinutes) {
    var gap = (breakMinutes || SHOWN_AT) * 60000;
    var free = occupancy(rows);
    var tagged = 0, silences = 0;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].took) tagged++;
      if (i === 0) continue;
      // The same arithmetic runs() uses, and for the same reason: a tagged trip
      // accounts for its own length and not a minute more. Skipping the gap
      // outright whenever the previous offer was taken — which this did — hides
      // the case worth surfacing most, a five-minute job followed by an hour of
      // silence, and so asked for tags on everything except the stretch that
      // needed one.
      //
      // Against the latest moment the driver was free, not the previous row's —
      // see occupancy(). This function's whole output is a request for more
      // tags, so counting a silence inside a trip that IS tagged is the one
      // wrong answer it can give.
      if (rows[i].at - free[i - 1] > gap) silences++;
    }
    return { tagged: tagged, silences: silences };
  }

  /* --- what a line actually feels like ---------------------------------
   *
   * `bestAt` says which line earns most. It does not say what holding that
   * line is LIKE, and a driver deciding whether they can afford to be pickier
   * is asking the second question. Measured on the owner's own week, inside
   * runs of scanning: at $20 a line takes 23.7% of what comes past and the
   * next one is about two minutes off; at $35 it is 2.3% and half an hour.
   * The shape of that curve is the whole of "how picky can I be", and nothing
   * here could draw it.
   *
   * WHY THIS IS AFFORDABLE AT ALL, and it is the fact that reframes the
   * feature: offers are not scarce. 1,140 of them reached this rig over 26
   * hours of scanning — 43 an hour, 81% of them arriving less than a minute
   * after the one before. They are not the same card read twice: only 1.1% of
   * consecutive pairs share a payout and 3.6% share both ends. Declining costs
   * seconds, so the line is the whole game.
   *
   * From every offer to the next one at or above the line, within a run —
   * which is what a driver who has just declined experiences. A gap that spans
   * a break is not a wait and runs() has already cut those out.
   */
  function waitFor(theRuns, lines, rows) {
    var all = rows || [];
    return (lines || []).map(function (line) {
      var waits = [];
      (theRuns || []).forEach(function (run) {
        for (var i = 0; i < run.length; i++) {
          var j = i + 1;
          while (j < run.length && run[j].perHour < line) j++;
          if (j < run.length) waits.push(run[j].at - run[i].at);
        }
      });
      waits.sort(function (a, b) { return a - b; });
      var clears = all.filter(function (o) { return o.perHour >= line; }).length;
      return {
        line: line,
        // Of everything that came past, not of what was taken.
        share: all.length ? clears / all.length : null,
        n: waits.length,
        median: waits.length ? waits[waits.length >> 1] : null,
        // The tail is the half that decides whether a line is liveable. A
        // six-minute median with a half-hour ninetieth is a different night
        // from a six-minute median with an eight-minute ninetieth.
        p90: waits.length ? waits[Math.floor(0.9 * (waits.length - 1))] : null
      };
    });
  }

  /* The line the driver KEEPS, as against the one they set.
   *
   * These are different numbers and only one of them is in the settings. On
   * the owner's own week the target is $25 and the median of what was actually
   * ticked is $30.20 — the top 4.8% of what came past. The rig holds both and
   * has never put them side by side, and the gap is worth about $3/hr in the
   * replay. Being too picky is the failure that hides itself: it looks like
   * high standards and shows up only as an empty evening.
   *
   * Over what was ticked, which is the only record of a decision this has. A
   * thin count is reported rather than hidden — see `n`.
   */
  function keptLine(rows) {
    var all = rows || [];
    var took = all.filter(function (r) { return r.took; });
    if (!took.length) return { n: 0, median: null, share: null };
    var mid = Math.round(median(took.map(function (r) {
      return r.perHour;
    })) * 100) / 100;
    // ...and how much of what came past would have cleared that line, which is
    // what turns "$30.20" from a number into "the top 5%". Computed here so
    // the page does not re-filter a pile it has a different name for.
    var clears = all.filter(function (r) { return r.perHour >= mid; }).length;
    return { n: took.length, median: mid,
             share: all.length ? clears / all.length : null };
  }

  /* How much of the clock was spent carrying somebody.
   *
   * The biggest lever there is and nothing reported it: on the owner's week
   * 13.6 of 26.4 scanning hours are covered by a ticked trip, so 48% of the
   * time the rig was on, the car was empty. (Summing the trips' own durations
   * instead gives 15.5 — see the merge below, which is what stops a stacked
   * pair being counted twice.) A line is chosen against that
   * number — being pickier buys a better rate and pays for it here.
   *
   * MERGED intervals, not a sum of durations: two ticked offers can overlap
   * when a second is picked up before the first is delivered, and adding their
   * lengths would report a driver as busier than the clock allows. Clipped to
   * the runs as well, so a trip that ran past the last scan does not borrow
   * time from a stretch nobody was scanning.
   *
   * AND IT IS A CEILING ON IDLENESS, NOT A MEASUREMENT, which is why
   * `silences` comes back with it. A trip the driver never ticked is
   * indistinguishable from a break, so every untagged trip inflates this. On
   * the owner's week 31 trips are tagged and 8 silences are accounted for by
   * nothing — the page must say so rather than print 41% as a fact.
   */
  function idleIn(theRuns, breakMinutes, rows) {
    var spans = [], busy = [];
    (theRuns || []).forEach(function (run) {
      var from = run[0].at, to = run[run.length - 1].at;
      run.forEach(function (o) {
        if (!o.took) return;
        var end = o.at + o.mins * 60000;
        // The clock runs until the last trip FINISHES, not until the last
        // offer appeared — the same rule replay() states in as many words, and
        // for the same reason. Clipping the tail instead charged the driver
        // for a trip that ran past the last scan and then called that time
        // idle: on the owner's week that reads 51% idle against a true 48%.
        if (end > to) to = end;
        busy.push([Math.max(o.at, from), end]);
      });
      spans.push([from, to]);
    });
    busy.sort(function (x, y) { return x[0] - y[0]; });
    var merged = [];
    busy.forEach(function (iv) {
      var last = merged[merged.length - 1];
      if (last && iv[0] <= last[1]) last[1] = Math.max(last[1], iv[1]);
      else merged.push(iv.slice());
    });
    var scanning = spans.reduce(function (s, v) { return s + (v[1] - v[0]); }, 0);
    var carrying = merged.reduce(function (s, v) { return s + (v[1] - v[0]); }, 0);
    var counted = unexplained((theRuns || []).reduce(function (a, r) {
      return a.concat(r);
    }, []), breakMinutes);
    return {
      hours: scanning / 3600000,
      busyHours: carrying / 3600000,
      share: scanning ? 1 - carrying / scanning : null,
      tagged: counted.tagged,
      // Stretches longer than the break that no ticked trip accounts for. Each
      // one is either a break or a trip nobody tagged, and from here they look
      // identical — so this is how far the figure above could be wrong.
      silences: counted.silences
    };
  }

  /* The best line at one threshold, and the plateau around it. */
  function bestAt(rows, breakMinutes) {
    var theRuns = runs(rows, breakMinutes);
    if (!theRuns.length) return null;
    var steps = ladder().map(function (t) { return replay(theRuns, t); });
    var best = null;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].trips < 1) continue;
      if (!best || steps[i].perHour > best.perHour) best = steps[i];
    }
    if (!best || best.perHour <= 0) return null;

    // The unbroken stretch around the winner, not the outer edges of every line
    // that happens to score well.
    //
    // A replay curve can have two peaks with a trough between them, and taking
    // the min and max of the whole qualifying set then reports a range whose
    // middle is excluded from it. On one real recording that produced "$20 to
    // $35" where only $20, $33, $34 and $35 actually qualified: a driver told
    // that range and setting $28 would have landed in the trough, on the
    // authority of this file.
    var good = {};
    for (var i2 = 0; i2 < steps.length; i2++) {
      if (steps[i2].trips >= 1 && steps[i2].perHour >= best.perHour * PLATEAU) {
        good[steps[i2].target] = true;
      }
    }
    var low = best.target, high = best.target;
    while (good[low - 1]) low--;
    while (good[high + 1]) high++;

    var inRuns = 0;
    for (var k = 0; k < theRuns.length; k++) inRuns += theRuns[k].length;
    return {
      best: best,
      low: low,
      high: high,
      runs: theRuns.length,
      // Offers the replay actually walked. Rows dropped with their single-offer
      // run are not evidence it used, and counting them in the headline made
      // the answer look better supported than it was.
      offers: inRuns,
      hours: best.hours,
      steps: steps
    };
  }

  /* What a mile is being charged at, read off the rows rather than asked for.
   *
   * Every row carries the deduction the rig applied (`cost`) and the distance
   * it applied it to, so the rate is already in the data and nothing has to be
   * told it. Median, not mean, for the same reason everything else here is:
   * one row with a misread distance would otherwise move it.
   *
   * Null when no row can answer — a week with no distances is a week with no
   * running cost, and saying 0 would be inventing the very number this is
   * about. */
  function costPerMileIn(offers) {
    var rates = [];
    (offers || []).forEach(function (o) {
      if (!o || typeof o.miles !== 'number' || !isFinite(o.miles) || o.miles <= 0) return;
      if (typeof o.cost !== 'number' || !isFinite(o.cost)) return;
      rates.push(o.cost / o.miles);
    });
    return rates.length ? median(rates.sort(function (a, b) { return a - b; })) : null;
  }

  /* How much of the answer rests on that rate.
   *
   * This project has built an apparatus to check the LINE — replay, bestAt, a
   * plateau, leave-one-night-out, and three Settled entries refusing rules
   * that lose to it — and never once asked whether the other number in every
   * verdict is right. It is not measured, it is a SEED: rpi/calibrate.py sets
   * a new config to 30c and its own comment calls that "a petrol midsize with
   * some depreciation in it", a figure the driver is expected to edit. On the
   * owner's week it is 30c on all 1,166 rows, which is what never editing it
   * looks like.
   *
   * It matters because it moves the answer, not a little: over that same week
   * the recommended line is $24 at 15c, $20 at 30c and $18 at 45c, and the
   * driver's own $25 is inside the plateau at the first two and OUTSIDE it at
   * the third. "Your line is right" is true conditional on a number nobody
   * checked.
   *
   * Anchored on the driver's own rate rather than on a fixed list, because the
   * question is about THEIR number and a table that did not contain it would
   * be answering somebody else's. Halved and doubled, which is the spread
   * between "fuel and tyres on a small car" and "fuel, tyres, servicing and
   * depreciation counted properly" — wide enough that if the answer holds
   * across it, the rate is not what the line is resting on.
   *
   * Re-scored through `usable()` rather than beside it. The deduction is read
   * in exactly one place and this hands that place different rows, so a sweep
   * can never drift from the figure it is a sweep OF. */
  function costLadder(offers, opts) {
    var o = opts || {};
    var mine = costPerMileIn(offers);
    var out = [];
    // No guard on `mine` here, and that is deliberate rather than an omission.
    //
    // A rate of null (no row carries both a distance and a deduction) or of
    // zero (the driver pays nothing a mile) both come out as nothing from the
    // bottom of this function anyway: every multiple of zero is zero and the
    // dedup below leaves one column, every multiple of null is NaN and
    // `bestAt` has nothing to answer with — and one column is not a sweep, so
    // `out.length > 1` refuses it. An explicit `if (!(mine > 0)) return null`
    // was written first and it could not be made to fail: both inputs were
    // already refused, by a longer route, with the guard deleted. This
    // project deletes branches no input can reach.
    //
    // What that leaves is a behaviour nothing states, so it is stated here and
    // both cases are pinned in tests/advice.test.js against the OUTCOME rather
    // than against whichever line produces it.
    [0.5, 0.75, 1, 1.5, 2].forEach(function (mult) {
      var rate = Math.round(mine * mult * 100) / 100;
      if (out.length && out[out.length - 1].perMile === rate) return;
      var rescored = (offers || []).map(function (row) {
        var copy = {}, k;
        for (k in row) { if (Object.prototype.hasOwnProperty.call(row, k)) copy[k] = row[k]; }
        copy.cost = (typeof row.miles === 'number' && isFinite(row.miles) && row.miles > 0)
          ? row.miles * rate : 0;
        return copy;
      });
      var b = bestAt(usable(rescored), o.breakMinutes || SHOWN_AT);
      if (!b) return;
      out.push({
        perMile: rate,
        mine: mult === 1,
        suggested: b.low,
        low: b.low,
        high: b.high,
        // Whether the driver's own line survives this assumption. The whole
        // point of the row: a target inside the plateau at 30c and outside it
        // at 45c is a target whose rightness is an assumption, not a finding.
        holds: typeof o.target === 'number' && isFinite(o.target)
          ? (o.target >= b.low && o.target <= b.high) : null
      });
    });
    return out.length > 1 ? out : null;
  }

  /* The whole answer, or a `ready: false` saying what it is short of.
   *
   * `target` in opts is the driver's current line, used only for the comparison. */
  function advise(offers, opts) {
    var o = opts || {};
    var rows = usable(offers);
    var counted = unexplained(rows, o.breakMinutes || SHOWN_AT);
    var shortfall = { ready: false, offers: rows.length,
                      needOffers: o.enoughOffers || ENOUGH_OFFERS,
                      needHours: o.enoughHours || ENOUGH_HOURS,
                      hours: 0, runs: 0,
                      tagged: counted.tagged, silences: counted.silences };
    if (!rows.length) return shortfall;

    var shown = bestAt(rows, o.breakMinutes || SHOWN_AT);
    if (!shown) return shortfall;
    shortfall.hours = shown.hours;
    shortfall.runs = shown.runs;
    /* The pile the answer is actually built from, not every row in the window.
       Until here `offers` is rows.length, which is right for the two returns
       above — they happen before there is a replay to have walked anything. */
    shortfall.offers = shown.offers;
    /* ...and the same reconciliation the ready path already makes, for the same
       reason it makes it. The refusal names a count and a threshold in one
       sentence, and dropping rows out of the count without saying so leaves the
       page disagreeing with its own list underneath. Carried here too because
       the refusal is the state this spends most of its life in. */
    shortfall.setAside = rows.length - shown.offers;

    /* ...and the gate is asked of that same pile.
       It tested rows.length: every usable row, including the ones runs() throws
       away with their single-offer run. The headline was corrected for exactly
       this a few lines up — "Rows dropped with their single-offer run are not
       evidence it used, and counting them in the headline made the answer look
       better supported than it was" — and the gate was not brought along. So a
       window of six rows that the replay reduced to two could pass a threshold
       whose own comment says "below these there is not enough to say anything.
       A recommendation drawn from one afternoon would be acted on exactly as
       confidently as one drawn from a season." */
    if (shown.offers < (o.enoughOffers || ENOUGH_OFFERS)) return shortfall;
    if (shown.hours < (o.enoughHours || ENOUGH_HOURS)) return shortfall;
    if (shown.best.trips < (o.enoughTrips || ENOUGH_TRIPS)) {
      shortfall.reason = 'trips';
      return shortfall;
    }
    if (shown.low <= 0) {
      shortfall.reason = 'nolinehelps';
      shortfall.low = shown.low;
      shortfall.high = shown.high;
      return shortfall;
    }

    // The same question asked at thresholds chosen to disagree. If they do not,
    // the answer is not an artefact of the one that was picked.
    var elsewhere = [];
    for (var i = 0; i < THRESHOLDS.length; i++) {
      var b = bestAt(rows, THRESHOLDS[i]);
      if (b) elsewhere.push({ minutes: THRESHOLDS[i], target: b.best.target,
                              low: b.low, high: b.high });
    }
    // Checked on the number that is actually recommended, which is the bottom
    // of the plateau, not the argmax. Those are different numbers: on one
    // recording the argmax agreed at every threshold while the recommended low
    // swung from $18 to $26, and the page printed "the same answer comes out
    // however the recording is split, which is why it is worth acting on" over
    // an $8 spread. A check that guards a number nobody sees is worse than no
    // check, because it is believed.
    var lows = elsewhere.map(function (e) { return e.low; });
    var highs = elsewhere.map(function (e) { return e.high; });
    var spread = lows.length
      ? Math.max.apply(null, lows) - Math.min.apply(null, lows) : 0;
    var bandSpread = highs.length
      ? Math.max.apply(null, highs) - Math.min.apply(null, highs) : 0;
    var stable = lows.length > 1
      && spread <= UNSTABLE_SPREAD && bandSpread <= UNSTABLE_SPREAD;
    if (!stable) {
      // Printing the number and retracting it in smaller type underneath is not
      // a caveat, it is a number with an excuse attached — and the number is
      // what gets acted on. What the recording can honestly support is the
      // range the thresholds actually produced, and that a longer record will
      // settle it.
      shortfall.reason = 'unsettled';
      // The range of the line that would actually be *recommended*, which is
      // the bottom of the plateau at each threshold. It used to report the
      // lowest low against the highest high while quoting the lows-only spread
      // beside them, so the page said "anywhere between $18 and $41 — a $21
      // swing" about three numbers that do not make that sentence true. One
      // quantity now: where the recommendation went, and how far.
      shortfall.low = lows.length ? Math.min.apply(null, lows) : null;
      shortfall.high = lows.length ? Math.max.apply(null, lows) : null;
      shortfall.spread = spread;
      // How much the top of the plateau moved. Not shown, but it is half of
      // why this refused, so it should be possible to ask.
      shortfall.bandSpread = bandSpread;
      shortfall.checkedAt = elsewhere;
      return shortfall;
    }

    // Where in the plateau to point. The bottom of it: a lower line takes more
    // work for the same money and leaves less riding on the recording being
    // representative, and being too picky is the failure that hides itself.
    //
    // Declared before the comparison below, which measures against it. `var`
    // hoists, so reading it from above would have quietly compared against
    // `undefined` — a line no offer clears — and reported a gain of nothing.
    var suggested = shown.low;

    // The improvement over the driver's current line, as a share rather than a
    // rate. A rate here would be a dollar figure per hour, and that depends
    // entirely on how much of the recorded time was really driving — the one
    // thing this cannot know. The ratio is the stable part where the level is
    // not.
    // What the recommended line actually does, worked out once.
    //
    // Everything reported below about "taking the first offer at or above
    // `suggested`" has to come from here, and three figures did not: `trips`,
    // `takes` and `hours` were read off `shown.best`, which is the ARGMAX — a
    // different line. The page names `suggested` in the same sentence: "taking
    // the first one at or above $13 whenever free gives 108 trips." Measured on
    // a curve with a broad plateau, $13 gives 314 trips and 68.5 hours against
    // the 108 and 70.7 that were printed — a third of the truth, in the
    // direction that makes the recommendation look worse than it is.
    //
    // This file had already caught the same mistake twice, in the two places
    // below and above: the stability check and the gain. Each was fixed on its
    // own and the reasoning was written out both times. It was never applied to
    // the counts, which is the argument for computing the replay once, up here,
    // rather than reaching for `shown.best` again.
    var atSuggested = replay(runs(rows, o.breakMinutes || SHOWN_AT), suggested);

    // The improvement over the driver's current line, as a share rather than a
    // rate. A rate here would be a dollar figure per hour, and that depends
    // entirely on how much of the recorded time was really driving — the one
    // thing this cannot know. The ratio is the stable part where the level is
    // not.
    var gain = null, current = null, currentTakesNothing = false;
    if (typeof o.target === 'number' && isFinite(o.target)) {
      current = replay(runs(rows, o.breakMinutes || SHOWN_AT), o.target);
      if (current.perHour > 0) {
        // Measured at the line that is actually recommended, not at the
        // argmax. Those are different lines — the recommendation is the bottom
        // of the plateau — so quoting the argmax's improvement beside the
        // recommended figure credits it with a gain it does not produce.
        gain = (atSuggested.perHour - current.perHour) / current.perHour;
      } else if (current.trips === 0) {
        // Not a missing comparison — the strongest finding this can make. A
        // line nothing clears is a shift spent parked, and the ratio is
        // undefined precisely because the denominator is a driver earning
        // nothing. Reporting it as "no comparison available" would bury the
        // one case where the target is doing visible harm.
        currentTakesNothing = true;
      }
    }

    /* ...and what that line is like to hold, which is the half `bestAt` has
       never answered. Lines around the DRIVER's own target rather than a fixed
       ladder: the question is what their decision costs, and a table that
       ignores the number in their settings is answering somebody else's. */
    var theRuns = runs(rows, o.breakMinutes || SHOWN_AT);
    var mine = typeof o.target === 'number' && isFinite(o.target) && o.target > 0
      ? o.target : suggested;
    var steps = [mine - 5, mine, mine + 5, mine + 10].filter(function (v, i, a) {
      return v > 0 && a.indexOf(v) === i;
    }).sort(function (a, b) { return a - b; });

    return {
      ready: true,
      offers: shown.offers,
      // What each line takes and what it costs in waiting. See waitFor.
      waits: waitFor(theRuns, steps, rows),
      // The line actually kept, against the one set. See keptLine.
      kept: keptLine(rows),
      // How much of the clock was carrying somebody, and how far that could be
      // wrong. See idleIn.
      idle: idleIn(theRuns, o.breakMinutes || SHOWN_AT, rows),
      // Rows that were read but fell outside any counted run — a stray offer in
      // a driveway, the last one before the rig was switched off. Named rather
      // than silently dropped, because "231 offers" against a journal holding
      // 234 is the kind of gap that makes a reader distrust the rest.
      setAside: rows.length - shown.offers,
      runs: shown.runs,
      // At the recommended line, not the argmax — see `atSuggested` above. The
      // page prints this in the same sentence that names `suggested`, and it is
      // the span the money is divided by, so it is a fact about that line and
      // not about the recording.
      hours: atSuggested.hours,
      from: rows[0].at,
      to: rows[rows.length - 1].at,
      suggested: suggested,
      low: shown.low,
      high: shown.high,
      trips: atSuggested.trips,
      takes: atSuggested.takes,
      stable: stable,
      spread: spread,
      checkedAt: elsewhere,
      current: current,
      currentTarget: typeof o.target === 'number' ? o.target : null,
      gain: gain,
      currentTakesNothing: currentTakesNothing,
      medianOffer: median(rows.map(function (r) { return r.perHour; }))
    };
  }

  /* Which offers arrived while a job the driver had ticked was still running.
   *
   * The one measured version of "you could not have taken this". Everything
   * else in this file that reasons about occupancy is SIMULATED — replay()
   * masks against its own hypothetical driver at a candidate target, which is
   * a different mask for a different purpose: on this recording the simulation
   * was free for 82 of the 301 counted busy rows at a $19 line and 102 at $25.
   * Neither is a substitute for the other and neither may be fed the other.
   *
   * WHAT IT IS NOT FOR, which matters more than what it is for. It does not
   * correct a statistic, and nothing that produces a default figure calls it.
   * Measured over the seven exports: dropping all 301 counted rows that arrived
   * inside a ticked window moves the median $13.95 -> $13.95, p25 $10.45 ->
   * $10.46, p75 $17.87 -> $17.90, and "cleared $25" 6.3% -> 6.2%. The busy pile
   * is not a biased sample — its own median is $13.85 against $13.95 for the
   * rest — it is a random fifth of the log. The figures it was suspected of
   * distorting, it does not distort.
   *
   * What it does distort is exactly one pile: of the 127 ACCEPT-rated offers
   * the driver did not tick, 19 arrived while a ticked job was running. So
   * "the pattern in what they passed" is 15% offers that were never passable,
   * and that is the question this exists to let somebody ask properly.
   *
   * AND THE HEDGE IS THE WHOLE THING. This can only see jobs that were TICKED.
   * 49 ticks across 8 days of scanning is plainly not every job worked, and the
   * share of offers that look busy tracks how hard the driver was ticking
   * rather than how busy they were: on the three days carrying one to three
   * ticks, 3.5% of offers land inside a window; on the four days carrying ten
   * or eleven, 27.7%. The market did not change eightfold between the 26th and
   * the 28th of August. So a row this returns nothing for means "no ticked job
   * was running" and never "you were free" — those words must not appear
   * anywhere built on this.
   *
   * `stacked` because 12 of the 49 ticks are themselves inside another tick's
   * window. Marking those "already out" would be the strongest possible thing
   * to get wrong: the driver demonstrably took them. They are a stack, which
   * this rig now records as a `pair` row of its own.
   */
  function busy(rows) {
    var out = {};
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      if (row.id === undefined || row.id === null) continue;
      var into = [];
      for (var j = 0; j < rows.length; j++) {
        var w = rows[j];
        if (j === i || !w.took) continue;
        if (w.at < row.at && row.at < freeAgain(w)) {
          into.push({ at: w.at, net: w.net, mins: w.mins, id: w.id });
        }
      }
      if (into.length) out[row.id] = { into: into, stacked: row.took === true };
    }
    return out;
  }

  return { advise: advise, usable: usable, runs: runs, replay: replay,
           busy: busy, freeAgain: freeAgain,
           bestAt: bestAt, trustworthy: trustworthy, grossRate: grossRate,
           unexplained: unexplained, stack: stack, sameArea: sameArea, area: area,
           // The offer log's chart and the map's time filter ask one question
           // and must not each keep their own eight edges.
           BLOCK_NAMES: BLOCK_NAMES, blockOf: blockOf, daysIn: daysIn,
           // The area ranking and the test that decides whether it may be
           // shown. The thresholds are exported for the same reason
           // THRESHOLDS below is: a page that says "eight offers on two days"
           // in words must read the number it is describing.
           waitFor: waitFor, keptLine: keptLine, idleIn: idleIn,
           areas: areas, AREA_FLOOR: AREA_FLOOR, AREA_DAYS: AREA_DAYS,
           AREA_ALPHA: AREA_ALPHA, AREA_SHUFFLES: AREA_SHUFFLES,
           outingsIn: outingsIn,
           // The one place the driver's 4am day boundary is written down.
           DAY_STARTS_AT: DAY_STARTS_AT,
           costPerMileIn: costPerMileIn, costLadder: costLadder,
           mapSearch: mapSearch, mapRoute: mapRoute, mapQuery: mapQuery,
           // Exported because a page that prints how far the line moved has to
           // be able to say what "settled" was allowed to mean, and a check
           // that the wording matches has to read the same number this does.
           THRESHOLDS: THRESHOLDS, SHOWN_AT: SHOWN_AT,
           UNSTABLE_SPREAD: UNSTABLE_SPREAD };
}));
