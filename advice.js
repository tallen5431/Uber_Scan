/* What line to draw, worked out from the offers this rig actually saw.
 *
 * The target in the settings is the one number in this project nobody has ever
 * checked. It is a guess made once — $25/hr sounds like a reasonable wage — and
 * every verdict since has been measured against it. But a target is not a wage.
 * It is a decision about how long to wait, and whether it is the right decision
 * depends entirely on what the next offer is likely to be and how soon it comes,
 * which is a local fact about a market, a day and a driver's hours.
 *
 * Set it too low and every hour goes on work that barely clears its own costs.
 * Set it too high and the car sits still: the offers that clear the line are
 * genuinely better, and there are not enough of them to fill a shift. One of
 * those failures is loud and the other is silent, and the silent one is the one
 * a driver keeps making, because a screen full of PASS looks like discipline.
 *
 * HOW THIS ANSWERS
 * A shift is a chain of cycles: wait for an offer worth taking, drive it, wait
 * again. Over a long enough run the take-home rate is total pay over total time,
 * so for a candidate line T:
 *
 *     earned per hour  =  average net pay of the offers at or above T
 *                         ------------------------------------------
 *                          (average wait for one)  +  (average trip)
 *
 * Raising T raises the numerator and the wait underneath it. The best line is
 * where those stop trading evenly, and it is nearly always well below the rate
 * it produces — waiting for $40 offers is how you earn $18.
 *
 * WHAT IT CANNOT KNOW
 * The arrival rate is counted from offers that reached the screen, and some of
 * those arrived while the driver was already carrying somebody and could not
 * have taken them. That inflates the rate, which makes waiting look cheaper
 * than it is, which biases the answer high. There is no way to tell the two
 * apart from this data — the scanner cannot see whether the car is occupied and
 * must not guess — so instead of one number this returns the answer at the
 * observed rate and again at half of it, and the honest recommendation is the
 * lower one. Where they agree, the answer is not sensitive to the thing that
 * cannot be measured; where they disagree, that gap is the real uncertainty and
 * is worth showing rather than averaging away.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Advice = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Longer than any gap between offers in a working shift, shorter than a break.
  // Used only to avoid counting the hours a parked car was not being offered
  // anything as hours it was waiting for something better.
  var BREAK_MS = 30 * 60 * 1000;

  // Below this the answer is arithmetic on noise. A shift is ~50 offers, so this
  // is roughly "come back after you have driven a couple of times".
  var ENOUGH_OFFERS = 40;
  var ENOUGH_HOURS = 2;

  // How much of the observed arrival rate to assume is actually reachable, for
  // the cautious end of the range. Half is not measured — it is a deliberate
  // "suppose only half of what you saw was yours to take".
  var CAUTIOUS = 0.5;

  function median(v) {
    if (!v.length) return null;
    var s = v.slice().sort(function (a, b) { return a - b; });
    var i = Math.floor(s.length / 2);
    return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2;
  }

  function mean(v) {
    var t = 0;
    for (var i = 0; i < v.length; i++) t += v[i];
    return v.length ? t / v.length : 0;
  }

  /* Hours the rig was being offered work, rather than hours between the first
     offer and the last. A shift that ran 6pm-9pm and again at 2am is five hours
     of driving inside an eight-hour span, and counting the span would say the
     market is half as busy as it is. */
  function watchedHours(times, breakMs) {
    if (!times.length) return 0;
    var gap = breakMs || BREAK_MS;
    var t = times.slice().sort(function (a, b) { return a - b; });
    var total = 0, start = t[0], last = t[0];
    for (var i = 1; i < t.length; i++) {
      if (t[i] - last > gap) { total += last - start; start = t[i]; }
      last = t[i];
    }
    return (total + (last - start)) / 3600000;
  }

  /* One offer reduced to what the arithmetic needs: what it pays after the car
     is paid for, and how long it occupies the driver.

     Net rather than gross throughout, because the target is a net figure and
     mixing the two is how a comparison stops meaning anything. Billed minutes
     rather than the card's, because a shopping order really does occupy the
     time the allowance describes. */
  function usable(offers) {
    var out = [];
    for (var i = 0; i < (offers || []).length; i++) {
      var o = offers[i];
      if (!o || o.hidden) continue;
      // The same exclusions the medians on the page use. A misread offer is
      // worth keeping in the file and worth keeping out of a decision; a
      // half-read card always looks better than it is, so leaving it in would
      // pull the recommended line upwards for no reason.
      if (o.suspect || o.whole === false) continue;
      var mins = typeof o.billedMinutes === 'number' ? o.billedMinutes : o.minutes;
      if (typeof o.pay !== 'number' || typeof mins !== 'number' || !(mins > 0)) continue;
      if (typeof o.at !== 'number') continue;
      var net = o.pay - (typeof o.cost === 'number' ? o.cost : 0);
      out.push({ at: o.at, net: net, mins: mins, perHour: net / (mins / 60) });
    }
    return out;
  }

  /* What a shift would have earned per hour holding out for `target`. Null when
     nothing clears the line, which is not zero — it is "this is not a strategy". */
  function earnedAt(rows, target, perHour) {
    var acc = [];
    for (var i = 0; i < rows.length; i++) if (rows[i].perHour >= target) acc.push(rows[i]);
    if (!acc.length) return null;
    var share = acc.length / rows.length;
    var waitHours = 1 / (perHour * share);
    var tripHours = mean(acc.map(function (r) { return r.mins; })) / 60;
    return {
      target: target,
      takes: share,
      earned: mean(acc.map(function (r) { return r.net; })) / (waitHours + tripHours),
      waitMinutes: waitHours * 60,
      tripMinutes: tripHours * 60
    };
  }

  function bestOf(rows, perHour, ladder) {
    var best = null;
    for (var i = 0; i < ladder.length; i++) {
      var r = earnedAt(rows, ladder[i], perHour);
      // A line only two or three offers clear is a number the next shift will
      // move. Require a tenth of them, so the answer is about the market rather
      // than about its best afternoon.
      if (!r || r.takes < 0.10) continue;
      if (!best || r.earned > best.earned) best = r;
    }
    return best;
  }

  /* The whole answer, or null when there is not yet enough to say anything.
   *
   * Returning null rather than a number with a caveat attached is deliberate:
   * a recommendation drawn from one afternoon would be acted on exactly as
   * confidently as one drawn from a season, and this project's rule is that a
   * confident wrong number is worse than no number. */
  function advise(offers, opts) {
    var o = opts || {};
    var rows = usable(offers);
    var hours = watchedHours(rows.map(function (r) { return r.at; }), o.breakMs);
    var enoughOffers = o.enoughOffers || ENOUGH_OFFERS;
    var enoughHours = o.enoughHours || ENOUGH_HOURS;
    if (rows.length < enoughOffers || hours < enoughHours) {
      return { ready: false, offers: rows.length, hours: hours,
               needOffers: enoughOffers, needHours: enoughHours };
    }

    var perHour = rows.length / hours;
    var ladder = [];
    for (var t = 0; t <= 60; t += 1) ladder.push(t);

    var optimistic = bestOf(rows, perHour, ladder);
    var cautious = bestOf(rows, perHour * CAUTIOUS, ladder);
    if (!optimistic || !cautious) return { ready: false, offers: rows.length, hours: hours,
                                           needOffers: enoughOffers, needHours: enoughHours };

    // The cautious end, because the error this cannot measure runs one way: some
    // of the offers counted arrived while the car was already full.
    var suggested = Math.min(optimistic.target, cautious.target);
    var current = typeof o.target === 'number'
      ? earnedAt(rows, o.target, perHour * CAUTIOUS) : null;

    return {
      ready: true,
      offers: rows.length,
      hours: hours,
      offersPerHour: perHour,
      suggested: suggested,
      range: [Math.min(optimistic.target, cautious.target),
              Math.max(optimistic.target, cautious.target)],
      cautious: cautious,
      optimistic: optimistic,
      current: current,
      // What holding the suggested line would have earned, judged on the same
      // cautious assumption the suggestion came from, so the two can be compared
      // without one of them quietly using a friendlier arrival rate.
      suggestedEarns: earnedAt(rows, suggested, perHour * CAUTIOUS),
      medianOffer: median(rows.map(function (r) { return r.perHour; }))
    };
  }

  return { advise: advise, watchedHours: watchedHours, usable: usable,
           earnedAt: earnedAt, BREAK_MS: BREAK_MS };
}));
