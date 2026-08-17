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
  var ENOUGH_TRIPS = 6;

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
   * Three exclusions, and each is a different kind of "no":
   *   hidden — the driver said this was not an offer they were made. The test
   *            card presented to check the rig is not a job.
   *   suspect — the reading cannot be true, so it is evidence about the camera
   *            rather than about the market.
   *   whole === false — only part of the journey was read, and a fragment
   *            always flatters: the same pay over less time. Left in, it pulls
   *            every figure and every recommendation upwards.
   *
   * `whole` is absent on rows written before it existed, and those were only
   * ever written when whole — so undefined counts as true. */
  function trustworthy(row) {
    return !!row && typeof row === 'object'
      && !row.hidden && !row.suspect && row.whole !== false;
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
      out.push({ at: seenAt, net: net, mins: mins, perHour: net / (mins / 60) });
    }
    out.sort(function (a, b) { return a.at - b.at; });
    return out;
  }

  /* Stretches of clock the scanner was being shown offers, split wherever it
     went quiet for longer than `breakMinutes`.

     This is the honest name for what used to be called a shift. It is not one:
     a single run can be half a shift, and a rig left switched on in a driveway
     produces a run with two offers in three hours. Runs of one offer have no
     span at all and are dropped rather than counted as an instant of driving. */
  function runs(rows, breakMinutes) {
    if (!rows.length) return [];
    var gap = (breakMinutes || SHOWN_AT) * 60000;
    var out = [[rows[0]]];
    for (var i = 1; i < rows.length; i++) {
      if (rows[i].at - rows[i - 1].at > gap) out.push([rows[i]]);
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
      takes: seen ? trips / seen : 0
    };
  }

  function ladder() {
    var out = [];
    for (var t = 0; t <= LADDER_MAX; t++) out.push(t);
    return out;
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
    var shortfall = { ready: false, offers: rows.length,
                      needOffers: o.enoughOffers || ENOUGH_OFFERS,
                      needHours: o.enoughHours || ENOUGH_HOURS,
                      hours: 0, runs: 0 };
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
      shortfall.low = lows.length ? Math.min.apply(null, lows) : null;
      shortfall.high = highs.length ? Math.max.apply(null, highs) : null;
      shortfall.spread = spread;
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
           bestAt: bestAt, trustworthy: trustworthy,
           THRESHOLDS: THRESHOLDS, SHOWN_AT: SHOWN_AT };
}));
