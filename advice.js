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
  // stray capital, at most three of them. Reads 15 more towns off this driver's
  // dropoffs and no false ones.
  var PLACE_TOWN = /[,.]\s*(?:[^A-Za-z\s]\s*|[A-Z]\s+){0,3}([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,})?)\s*$/;
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

  function sameArea(a, b) {
    var x = area(a), y = area(b);
    if (!x || !y) return null;
    if (x.zip && y.zip && x.zip === y.zip) return 'same-zip';
    if (x.town && y.town && x.town !== y.town) return 'elsewhere';
    if (x.quadrant && y.quadrant && x.quadrant !== y.quadrant) return 'elsewhere';
    if (!x.town || !y.town) {
      // Same quadrant, no town on one of them: a quadrant is a whole side of
      // the metro, and on its own that is not enough to promise anything. A
      // ZIP on one side and not the other lands here too, and for the same
      // reason - one address being precise says nothing about the other.
      return null;
    }
    return (x.quadrant && y.quadrant) ? 'same-side' : 'same-town';
  }

  function stack(active, offer, settings, now) {
    if (!active || !offer) return null;
    var target = (settings && typeof settings.target === 'number')
      ? settings.target : 0;
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
      // stated without a hedge.
      sure: worst >= alone,
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
      state: worst >= target ? 'go' : (best >= target ? 'warn' : 'no')
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
  function runs(rows, breakMinutes) {
    if (!rows.length) return [];
    var gap = (breakMinutes || SHOWN_AT) * 60000;
    var out = [[rows[0]]];
    for (var i = 1; i < rows.length; i++) {
      var prev = rows[i - 1];
      var freeAgain = prev.took ? prev.at + prev.mins * 60000 : prev.at;
      if (rows[i].at - freeAgain > gap) out.push([rows[i]]);
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
      var prev = rows[i - 1];
      var freeAgain = prev.took ? prev.at + prev.mins * 60000 : prev.at;
      if (rows[i].at - freeAgain > gap) silences++;
    }
    return { tagged: tagged, silences: silences };
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

    if (rows.length < (o.enoughOffers || ENOUGH_OFFERS)) return shortfall;
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
    var gain = null, current = null, currentTakesNothing = false;
    if (typeof o.target === 'number' && isFinite(o.target)) {
      current = replay(runs(rows, o.breakMinutes || SHOWN_AT), o.target);
      if (current.perHour > 0) {
        // Measured at the line that is actually recommended, not at the
        // argmax. Those are different lines — the recommendation is the bottom
        // of the plateau — so quoting the argmax's improvement beside the
        // recommended figure credits it with a gain it does not produce.
        var atSuggested = replay(runs(rows, o.breakMinutes || SHOWN_AT), suggested);
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

    return {
      ready: true,
      offers: shown.offers,
      // Rows that were read but fell outside any counted run — a stray offer in
      // a driveway, the last one before the rig was switched off. Named rather
      // than silently dropped, because "231 offers" against a journal holding
      // 234 is the kind of gap that makes a reader distrust the rest.
      setAside: rows.length - shown.offers,
      runs: shown.runs,
      hours: shown.hours,
      from: rows[0].at,
      to: rows[rows.length - 1].at,
      suggested: suggested,
      low: shown.low,
      high: shown.high,
      trips: shown.best.trips,
      takes: shown.best.takes,
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

  return { advise: advise, usable: usable, runs: runs, replay: replay,
           bestAt: bestAt, trustworthy: trustworthy, grossRate: grossRate,
           unexplained: unexplained, stack: stack, sameArea: sameArea, area: area,
           mapSearch: mapSearch, mapRoute: mapRoute, mapQuery: mapQuery,
           THRESHOLDS: THRESHOLDS, SHOWN_AT: SHOWN_AT };
}));
