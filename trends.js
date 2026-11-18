/* How the offers moved over the weeks: the offers page's Trends tab.
 *
 * The owner, Nov 2026, after three months on the rig: a tab of trends on the
 * offers report — the day's pay and $/hr over time, the hours of the day and
 * the days of the week, a rate card per app, two periods side by side, a
 * calendar — "report-only work". Nothing here reaches the panel, the verdict,
 * the target or a money rule, and lite never loads it: server.js answers
 * /api/trends with lite's own refusal, and the page hides the tab on it.
 *
 * ONE FILE FOR BOTH ENDS. server.js turns its folded window into compact rows
 * here (rowsOf, pack) and the page turns them back (unpack) and does every
 * sum here, so node tests hold the same arithmetic the browser runs.
 *
 * WHY THE SERVER SENDS ROWS AND THE PAGE DOES THE SUMS. The page already
 * holds /api/journal's offers, but that answer is capped at 5,000 (the DOM's
 * guard; Settled, "The journal read", says the cap stays and the server takes
 * none of its own) and each offer carries its text, its scans and its places:
 * 14.6 MB for All at 5,000. The owner's three months are about 11,900 offers,
 * so a Trends tab built on that answer would quietly be the newest 5,000 of
 * them. /api/trends sends every offer in the window — no cap, the range is an
 * honest span — as eight short columns and nothing else: no text, no place,
 * no position (about 45 bytes an offer; 12,000 offers in ~0.5 MB). The page
 * asks for it only when the tab is opened, so the page's own load is what it
 * was. The fold is the server's cached one (latestPerOffer), so the second
 * request costs the packing and not a second fold.
 *
 * WHAT IS COUNTED, AND WHAT IS IN THE MONEY. An offer is several journal
 * rows under one id; the server's fold has already chosen its reading, its
 * final state and its pay as corrected at read time (server.js withPay:
 * `corrected`, and `payUnread` where the text held only a part of the pay).
 * rowsOf counts each id once regardless, the newest copy winning, so a caller
 * that hands it raw rows gets the same count. Money and time statistics are
 * over Advice.trustworthy rows only — the page's one rule, which already sets
 * aside `suspect` (and every "pay unread" row is suspect) — and a "pay unread"
 * row is refused by name as well, in case a later reader stops marking it
 * suspect. Both are still COUNTED, in the data-quality strip and the offer
 * counts: they are offers the rig saw, and a quality view without them would
 * describe a cleaner record than the one on disk.
 *
 * SETTLED, AND HOW THIS STAYS INSIDE IT. Every figure is descriptive. $/mi is
 * drawn to read, never as a rule or a floor; the weekday x hour grid is a
 * picture of the record, and nothing reads it back into the accept line
 * (AUDITS.md, Settled, "The maps").
 *
 * THE RULER ("good"), round two of the tab (the owner, Nov 2026). The owner
 * takes the best offers, so the median $/hr every chart drew barely moved and
 * hid what they choose by. "Good" on this tab is now the top 10, 20, 30 or 50%
 * of the range's own $/hr (20% unless the viewer picks another), worked out
 * ONCE over the whole range pressed (ruler) and then held as a fixed dollar
 * figure, so a cell, an hour, a day and a week are all counted against the
 * same line and an old day compares fairly with a new one. Round one counted
 * each row against its own target at the time; the targets moved over the
 * weeks, so a day under a $22 target and one under $25 were not counted alike.
 * The flag (F_GOOD) is still packed, and nothing on the page reads it now.
 * THE RULER IS FOR READING ONLY: it is not the target, it never reaches the
 * verdict, the panel, the rig, scan_pi or any rule, and it is chosen per
 * viewer in the page's own storage. A percentile of your own history used as
 * an accept line is the line tuned to your history (Settled), so it is not.
 *
 * A TAKE is only the driver's own ✓ (the fold's `accepted === true`, a mark
 * the driver made). A card nobody answered for is not taken (silence is never
 * an accept), so F_TAKEN is a floor on what was taken, as Advice says of its
 * ticks.
 *
 * THE GRID'S FLOOR AND ITS SHADING, DERIVED TOGETHER. AUDITS.md's heat-map
 * entry: a cell coloured at a fixed band edge takes the wrong colour 21-25% of
 * the time at n=12 with no effect at all, because the floor and the scale were
 * tuned apart. So there is no band here. A cell is shaded only where the 99%
 * order-statistic interval of its median lies wholly above (or below) the
 * window's pooled median, and only at FLOOR offers on FLOOR_DAYS driver days;
 * every cell prints its median and its n either way. Simulated (log-normal
 * $/hr, median $13.95 and spread fitted to the owner's week's quartiles,
 * $10.45 / $17.87; 4,000 cells a row):
 *
 *      n  | no effect, shaded | +$2/hr, shaded | +$3/hr, shaded
 *     ----+-------------------+----------------+---------------
 *      12 |       0.8%        |       5%       |      15%
 *      20 |       0.2%        |       6%       |      22%
 *      30 |       0.4%        |      16%       |      50%
 *      45 |       0.8%        |      30%       |      76%
 *      60 |       0.7%        |      42%       |      90%
 *     100 |       0.8%        |      73%       |      99%
 *
 * At 95% the no-effect column was 4% from n=12 on: across 168 cells, seven
 * shaded by chance on a grid with nothing in it. At 99% it is under 1% at
 * every n, about one cell of 168. FLOOR is 30, where a real $3/hr difference
 * is shaded half the time, and the same 30 as the places report's MIN_N; under
 * it the cell is grey and says "n=". The calendar's tiles use the same pair.
 *
 * P75 AND P90 BY THE SAME RULE. The interval is the order-statistic one at
 * any share p (quantRanks: binomial ranks at p, not 1/2), compared with the
 * same share over the whole range. Its ranks must exist inside 1..n as well
 * as the floor holding: at 99% a P90 has no upper rank under 51 offers
 * (0.9^n must fall to 0.005), so a P90 cell under that stays grey whatever
 * its figure, rather than being shaded off a one-sided interval.
 *
 * GOOD OFFERS PER HOUR ONLINE, BY CELL. Good offers (the ruler) over the
 * hours the rig was scanning in that weekday and clock hour, the runs split
 * at every clock hour by the minutes in each (onlinePieces). A cell is shaded
 * where a 99% Poisson interval on its count, over its hours, clears the
 * range's own rate. A plain Poisson interval was not honest here. Simulated
 * (6 good an hour, each night's rate drawn with a 40% spread, as the owner's
 * nights swing $13.92 to $27.06; 40 cells x 150 grids a row):
 *
 *     hours on nights | plain Poisson, no effect | widened, no effect | widened, +50%
 *     ----------------+--------------------------+--------------------+--------------
 *       1 on 1        |          5.2%            |   (cannot widen)   |
 *       2 on 2        |          4.4%            |        1.0%        |      7%
 *       3 on 2        |          7.5%            |        1.0%        |      9%
 *       6 on 4        |          9.9%            |        1.0%        |     16%
 *      10 on 6        |          9.8%            |        0.9%        |     26%
 *
 * A night's own swing is not in a Poisson count, so the more hours a cell
 * held the narrower its interval drew and the more often it was shaded by
 * chance. So the interval is widened by the record's own overdispersion,
 * measured (dispersion) as Pearson's chi-square over each cell's nights
 * against the cell's own rate — the effective count k/phi, its Poisson
 * interval scaled back by phi. With no night-to-night swing at all phi comes
 * out 1.03-1.09 and the power is what the plain interval gave. phi needs two
 * nights to be measured, which is half the floor: GOOD_FLOOR_HOURS online on
 * GOOD_FLOOR_DAYS driver days, 2 and 2, the first row where the widened
 * interval holds 1% (at one night it cannot widen and shades 5-10% by
 * chance). A calendar tile is one day on purpose — the day-to-day swing IS
 * what a tile asks about — so it takes the plain interval at 2 hours.
 *
 * THE RATE CARD is least squares, pay = base + a·minutes + b·miles, per app
 * per ISO week, reported as the price of a 20-minute, 5-mile trip with a
 * percentile bootstrap interval (seeded, so a reload draws the same one). A
 * week is "too thin to fit" — said, and drawn as no point — under RATE_MIN_N
 * offers, or where minutes and miles move together so closely (r² over
 * RATE_COLLINEAR) that the fit cannot say which one the pay follows. It reads
 * how the apps priced the offers that came; it is not a model of what to take.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./advice.js'));
  else root.Trends = factory(root.Advice);
}(typeof self !== 'undefined' ? self : this, function (Advice) {
  'use strict';

  var DAY_STARTS_AT = Advice && typeof Advice.DAY_STARTS_AT === 'number' ? Advice.DAY_STARTS_AT : 4;
  var FLOOR = 30;
  var FLOOR_DAYS = 2;
  var CI_ALPHA = 0.01;
  // A day's or a week's point on a line: the fewest offers its median is drawn
  // from (under it the point is hollow and the band left out). Descriptive,
  // the places report's DESC_MIN_N; nothing is shaded by it.
  var DAY_MIN = 10;
  var RATE_MIN_N = 30;
  var RATE_COLLINEAR = 0.95;
  var RATE_BOOTS = 200;
  var RATE_AT = { minutes: 20, miles: 5 };
  var METRICS = ['pay', 'perHour', 'perMile', 'minutes', 'miles'];
  var METRIC_NAMES = { pay: 'pay', perHour: '$/hr', perMile: '$/mi', minutes: 'minutes', miles: 'miles' };
  var APPS = ['uber', 'doordash'];
  var WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  // The ruler's choices, the share of the range's offers called good.
  var TOPS = [10, 20, 30, 50];
  var TOP_DEFAULT = 20;
  // The one figure the grid, the hour chart and the calendar are read in.
  var STATS = ['p50', 'p75', 'p90', 'goodRate'];
  var STAT_P = { p50: 0.5, p75: 0.75, p90: 0.9 };
  var STAT_NAMES = { p50: 'median', p75: 'P75', p90: 'P90', goodRate: 'good/hr online' };
  // Good per hour online: the floor of a cell (hours on driver days), and of
  // a calendar tile (one day). See the header for the table they came from.
  // A clock-hour cell holds at most an hour a night, so 2 hours there is
  // already 2 nights; the days half is kept for a week's figure, where two
  // hours can be one evening.
  var GOOD_FLOOR_HOURS = 2;
  var GOOD_FLOOR_DAYS = 2;
  // A night's slice of a cell shorter than this is left out of phi's
  // measurement (not out of the cell): a run starts AT its first card, so a
  // five-minute slice holding that card reads as twelve an hour.
  var PIECE_MIN_H = 0.25;
  // The hours in the order a driver's day runs: 4am first, the small hours
  // last, so a night is one stretch of the chart and not its two ends.
  var HOUR_ORDER = [];
  for (var h0 = 0; h0 < 24; h0++) HOUR_ORDER.push((h0 + DAY_STARTS_AT) % 24);

  // Flag bits on a packed row.
  // F_TAKEN: the driver's own ✓ only (see the header); a bit, not a column,
  // so the answer grows by nothing and carries no more than it did.
  var F_OK = 1, F_GOOD = 2, F_SUSPECT = 4, F_CORRECTED = 8, F_UNREAD = 16, F_BOOST_KNOWN = 32, F_BOOST = 64,
      F_TAKEN = 128;

  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }
  function r2(v) { return v === null ? null : Math.round(v * 100) / 100; }

  /* --- the rows ---------------------------------------------------------- */

  // When the card appeared: the fold's `firstAt`, else `at`, as Advice.usable.
  function seenAt(o) { return num(o.firstAt) !== null ? o.firstAt : num(o.at); }

  // Each id once, the newest copy (by `at`, then by place in the list). A row
  // with no id is its own offer, as the server's fold treats it.
  function distinct(offers) {
    var byId = Object.create(null), out = [];
    (offers || []).forEach(function (o) {
      if (!o || typeof o !== 'object' || o.kind) return;
      if (typeof o.id !== 'string' || !o.id) { out.push(o); return; }
      var i = byId[o.id];
      if (i === undefined) { byId[o.id] = out.length; out.push(o); return; }
      if ((num(o.at) || 0) >= (num(out[i].at) || 0)) out[i] = o;
    });
    return out;
  }

  function appCode(a) { return a === 'uber' ? 1 : a === 'doordash' ? 2 : 0; }

  /* The folded offers as the few figures a trend needs, one per offer. */
  function rowsOf(offers) {
    var out = [];
    distinct(offers).forEach(function (o) {
      var t = seenAt(o);
      if (t === null) return;
      var unread = o.payUnread === true;
      var c = o.corrected && typeof o.corrected === 'object' ? o.corrected : null;
      var ok = !unread && !!(Advice && Advice.trustworthy ? Advice.trustworthy(o) : !o.suspect)
        && num(o.pay) !== null;
      var perHour = ok ? num(o.perHour) : null;
      var target = num(o.target);
      var known = Object.prototype.hasOwnProperty.call(o, 'boost');
      out.push({
        t: t, app: appCode(o.app),
        pay: ok ? o.pay : null,
        perHour: perHour,
        minutes: ok ? num(o.minutes) : null,
        miles: ok && !o.milesUncertain ? num(o.miles) : null,
        flags: (ok ? F_OK : 0)
          | (ok && perHour !== null && target !== null && perHour >= target ? F_GOOD : 0)
          | (o.suspect ? F_SUSPECT : 0)
          | (c && typeof c.to === 'number' ? F_CORRECTED : 0)
          | (unread ? F_UNREAD : 0)
          | (known ? F_BOOST_KNOWN : 0)
          | (known && (typeof o.boost === 'number' ? o.boost > 0 : !!o.boost) ? F_BOOST : 0)
          | (o.accepted === true ? F_TAKEN : 0)
      });
    });
    out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  /* Columns, seconds and cents: what /api/trends sends. */
  function pack(rows) {
    var cols = { t: [], app: [], pay: [], perHour: [], minutes: [], miles: [], flags: [] };
    rows.forEach(function (r) {
      cols.t.push(Math.round(r.t / 1000));
      cols.app.push(r.app);
      cols.pay.push(r.pay === null ? null : r2(r.pay));
      cols.perHour.push(r.perHour === null ? null : r2(r.perHour));
      cols.minutes.push(r.minutes === null ? null : Math.round(r.minutes * 10) / 10);
      cols.miles.push(r.miles === null ? null : Math.round(r.miles * 10) / 10);
      cols.flags.push(r.flags);
    });
    return { v: 1, n: rows.length, cols: cols };
  }

  // The driver's day of a moment, in the zone of whoever asks: 'YYYY-MM-DD'.
  function dayKeyOf(ms) {
    var d = new Date(ms);
    d.setHours(d.getHours() - DAY_STARTS_AT);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }
  function dateOfKey(key) {
    var p = key.split('-').map(Number);
    return new Date(p[0], p[1] - 1, p[2], 12);
  }
  // The Monday of a driver's day's week, as its key.
  function weekKeyOf(dayKey) {
    var d = dateOfKey(dayKey);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }
  function addDays(key, n) {
    var d = dateOfKey(key);
    d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }

  /* Rows back from columns, each given its day, week, weekday and hour on the
   * reader's own clock — the clock the page's day headers are on. */
  function unpack(p) {
    var c = (p && p.cols) || {};
    var n = (c.t || []).length, out = new Array(n);
    for (var i = 0; i < n; i++) {
      var ms = c.t[i] * 1000;
      var f = c.flags[i] | 0;
      var pay = c.pay[i], mi = c.miles[i];
      var day = dayKeyOf(ms);
      out[i] = withClock({
        t: ms, app: c.app[i] === 1 ? 'uber' : c.app[i] === 2 ? 'doordash' : null,
        pay: pay, perHour: c.perHour[i], minutes: c.minutes[i], miles: mi,
        perMile: pay !== null && mi !== null && mi >= 0.1 ? pay / mi : null,
        ok: !!(f & F_OK), good: !!(f & F_GOOD), suspect: !!(f & F_SUSPECT),
        corrected: !!(f & F_CORRECTED), unread: !!(f & F_UNREAD),
        boost: f & F_BOOST_KNOWN ? !!(f & F_BOOST) : null, taken: !!(f & F_TAKEN)
      }, day);
    }
    return out;
  }
  // rowsOf's own rows read the same way (the tests', and a caller with offers).
  function readRows(rows) { return unpack(pack(rows)); }

  function withClock(r, day) {
    var d = new Date(r.t);
    r.day = day;
    r.week = weekKeyOf(day);
    r.month = day.slice(0, 7);
    r.dow = dateOfKey(day).getDay();
    r.hour = d.getHours();
    return r;
  }

  /* --- the numbers -------------------------------------------------------- */

  function sorted(xs) { return xs.slice().sort(function (a, b) { return a - b; }); }
  // Linear between the two straddling values, as the page's percentile().
  function q(s, share) {
    if (!s.length) return null;
    if (s.length === 1) return s[0];
    var pos = share * (s.length - 1), lo = Math.floor(pos), hi = Math.ceil(pos);
    return s[lo] + (s[hi] - s[lo]) * (pos - lo);
  }
  function quarts(vals) {
    var s = sorted(vals);
    return { n: s.length, p25: r2(q(s, 0.25)), p50: r2(q(s, 0.5)), p75: r2(q(s, 0.75)), p90: r2(q(s, 0.9)) };
  }
  function valueOf(r, metric) { return r.ok ? r[metric] : null; }
  function valuesOf(rows, metric) {
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var v = valueOf(rows[i], metric);
      if (v !== null && v !== undefined && isFinite(v)) out.push(v);
    }
    return out;
  }

  // The rank k (1-based) of the 100(1 - alpha)% order-statistic interval of a
  // median, [x(k), x(n-k+1)]: the largest k with P(Binomial(n, 1/2) < k) <=
  // alpha/2. 0 where n is too small for any. In logs, so n in the thousands
  // does not underflow.
  var kMemo = Object.create(null);
  function medianRank(n, alpha) {
    var key = n + '/' + alpha;
    if (key in kMemo) return kMemo[key];
    var lc = 0, cum = 0, k = 0, lnHalf = n * Math.LN2;
    for (var i = 0; i <= n; i++) {
      if (i > 0) lc += Math.log(n - i + 1) - Math.log(i);
      var p = Math.exp(lc - lnHalf);
      if (cum + p > alpha / 2) break;
      cum += p;
      k = i + 1;
    }
    kMemo[key] = k;
    return k;
  }

  /* The same interval at any share p: [x(lo), x(hi)] with lo the largest rank
   * where P(Binomial(n, p) < lo) <= alpha/2 and hi the smallest where
   * P(Binomial(n, p) >= hi) <= alpha/2 — the chance the p-quantile sits below
   * x(lo), or above x(hi), each at most alpha/2. lo is 0 and hi is n + 1
   * where no rank qualifies, and then there is no interval. At p = 1/2 it is
   * medianRank exactly, and the upper rank is taken by symmetry so a
   * rounding in the sum cannot move a median's interval by one place. */
  var qMemo = Object.create(null);
  function quantRanks(n, p, alpha) {
    if (p === 0.5) { var k = medianRank(n, alpha); return k >= 1 ? [k, n - k + 1] : [0, n + 1]; }
    var key = n + '/' + p + '/' + alpha;
    if (key in qMemo) return qMemo[key];
    var half = alpha / 2, lnp = Math.log(p), lnq = Math.log(1 - p);
    var lc = 0, cum = 0, lo = 0, hi = n + 1, loDone = false;
    for (var i = 0; i <= n; i++) {
      if (i > 0) lc += Math.log(n - i + 1) - Math.log(i);
      var pm = Math.exp(lc + i * lnp + (n - i) * lnq);
      if (!loDone) { if (cum + pm > half) loDone = true; else lo = i + 1; }
      cum += pm;                                     // P(X <= i)
      if (cum >= 1 - half) { hi = i + 1; break; }    // P(X >= i + 1) <= alpha/2
    }
    qMemo[key] = [lo, hi];
    return qMemo[key];
  }
  function quantCI(s, p, alpha) {
    var r = quantRanks(s.length, p, alpha);
    return r[0] >= 1 && r[1] <= s.length ? [s[r[0] - 1], s[r[1] - 1]] : null;
  }
  function medianCI(s, alpha) { return quantCI(s, 0.5, alpha); }

  /* Shade a group's p-quantile against the same quantile of a reference:
   * 'above', 'below' or null, by the rule in the header. `days` is how many
   * driver days it rests on. Enough only where the floor holds AND the
   * interval exists; under either a cell is grey and shows its n. */
  function shadeQ(vals, days, ref, p, minDays) {
    var need = typeof minDays === 'number' ? minDays : FLOOR_DAYS;
    if (vals.length < FLOOR || days < need || ref === null) return { enough: false, shade: null, ci: null };
    var ci = quantCI(sorted(vals), p, CI_ALPHA);
    if (!ci) return { enough: false, shade: null, ci: null, noRanks: true };
    var shade = ci[0] > ref ? 'above' : ci[1] < ref ? 'below' : null;
    return { enough: true, shade: shade, ci: [r2(ci[0]), r2(ci[1])] };
  }
  function shadeOf(vals, days, ref, minDays) { return shadeQ(vals, days, ref, 0.5, minDays); }

  /* --- counts over hours: Poisson, and phi ------------------------------------
   *
   * ln Gamma (Lanczos) and the regularized lower incomplete gamma P(a, x)
   * (series under a + 1, continued fraction above), which is the Poisson
   * tail: P(X >= k; m) = P(k, m) and P(X <= k; m) = 1 - P(k + 1, m). Taken as
   * functions of a real k, so the effective count k/phi needs no rounding. */
  function lnGamma(x) {
    var c = [76.18009172947146, -86.50532032941677, 24.01409824083091, -1.231739572450155,
             0.1208650973866179e-2, -0.5395239384953e-5];
    var y = x, t = x + 5.5, s = 1.000000000190015;
    t -= (x + 0.5) * Math.log(t);
    for (var j = 0; j < 6; j++) s += c[j] / ++y;
    return -t + Math.log(2.5066282746310005 * s / x);
  }
  function gammaP(a, x) {
    if (x <= 0) return 0;
    var front = Math.exp(-x + a * Math.log(x) - lnGamma(a));
    if (x < a + 1) {
      var ap = a, sum = 1 / a, del = sum;
      for (var n = 0; n < 1000; n++) { ap += 1; del *= x / ap; sum += del; if (Math.abs(del) < Math.abs(sum) * 1e-13) break; }
      return Math.min(1, sum * front);
    }
    var b = x + 1 - a, c = 1e300, d = 1 / b, h = d;
    for (var i = 1; i < 1000; i++) {
      var an = -i * (i - a);
      b += 2; d = an * d + b; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = b + an / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d; var dl = d * c; h *= dl;
      if (Math.abs(dl - 1) < 1e-13) break;
    }
    return Math.max(0, 1 - front * h);
  }
  function bisect(f, target, lo, hi) {
    for (var i = 0; i < 100; i++) { var m = (lo + hi) / 2; if (f(m) < target) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  /* The exact (Garwood) 100(1 - alpha)% interval on a Poisson mean, from a
   * count k: [0, 5.30] at k = 0 and 99%, [3.72, 21.40] at k = 10. */
  function poisCI(k, alpha) {
    var top = k + 20 * Math.sqrt(k + 1) + 30;
    var lo = k > 0 ? bisect(function (m) { return gammaP(k, m); }, alpha / 2, 0, top) : 0;
    var hi = bisect(function (m) { return gammaP(k + 1, m); }, 1 - alpha / 2, 0, top);
    return [lo, hi];
  }

  /* phi: how much more the nights of a group differ than a Poisson count
   * would, measured off the record (Pearson's chi-square over each group's
   * own rate, over its degrees of freedom), never under 1. `groups` is a list
   * of lists of { k, h }: a cell's nights, or a week's days. 1 where no group
   * has two slices to compare. */
  function dispersion(groups) {
    var chi = 0, df = 0;
    groups.forEach(function (g) {
      var use = g.filter(function (x) { return x.h >= PIECE_MIN_H; });
      if (use.length < 2) return;
      var K = 0, H = 0;
      use.forEach(function (x) { K += x.k; H += x.h; });
      if (!(K > 0) || !(H > 0)) return;
      use.forEach(function (x) { var e = K / H * x.h; chi += (x.k - e) * (x.k - e) / e; });
      df += use.length - 1;
    });
    return df > 0 ? Math.max(1, chi / df) : 1;
  }

  /* Shade a count over hours against a reference rate: the Poisson interval
   * on k/phi, scaled back by phi and divided by the hours. */
  function rateShade(k, hours, ref, phi) {
    if (!(hours > 0) || ref === null) return { shade: null, ci: null };
    var f = phi > 1 ? phi : 1, ci = poisCI(k / f, CI_ALPHA);
    var lo = ci[0] * f / hours, hi = ci[1] * f / hours;
    return { shade: lo > ref ? 'above' : hi < ref ? 'below' : null, ci: [r2(lo), r2(hi)] };
  }

  /* --- the ruler --------------------------------------------------------------
   *
   * The top `top`% of the range's $/hr, as one dollar figure (to the cent the
   * rows are packed at, so "at or over $19.40" counts exactly what it says).
   * Over the money rows only, as every other figure. See the header: it is a
   * reading ruler and reaches nothing else. */
  function ruler(rows, top) {
    var t = TOPS.indexOf(Number(top)) >= 0 ? Number(top) : TOP_DEFAULT;
    var v = valuesOf(rows, 'perHour');
    var cut = v.length ? r2(q(sorted(v), 1 - t / 100)) : null;
    var over = cut === null ? 0 : v.filter(function (x) { return x >= cut; }).length;
    return { top: t, cut: cut, n: v.length, over: over };
  }
  function isGood(r, cut) {
    return r.ok && typeof cut === 'number' && r.perHour !== null && r.perHour !== undefined && r.perHour >= cut;
  }
  // The ruler where one is given, else the row's own flag (round one's).
  function goodOf(r, cut) { return typeof cut === 'number' ? isGood(r, cut) : r.good; }

  function groupBy(rows, key) {
    var out = Object.create(null), order = [];
    rows.forEach(function (r) {
      var k = key(r);
      if (k === null || k === undefined) return;
      if (!out[k]) { out[k] = []; order.push(k); }
      out[k].push(r);
    });
    return { by: out, keys: order };
  }
  function daysIn(rows) {
    var d = Object.create(null), n = 0;
    rows.forEach(function (r) { if (!d[r.day]) { d[r.day] = true; n += 1; } });
    return n;
  }

  /* --- by day, or by week --------------------------------------------------
   *
   * One entry per driver day (or ISO week) that holds an offer, oldest first:
   * every offer counted, the quartiles and P90 of each metric over the rows
   * the money counts, the per-app medians and counts, the data-quality
   * counts, the app share and the boost share. */
  function periods(rows, by) {
    var g = groupBy(rows, function (r) { return by === 'week' ? r.week : r.day; });
    return g.keys.sort().map(function (k) {
      var list = g.by[k];
      var e = { key: k, n: list.length, counted: 0, metrics: {}, apps: {}, quality: null, share: null, boost: null };
      METRICS.forEach(function (m) { e.metrics[m] = quarts(valuesOf(list, m)); });
      e.counted = list.filter(function (r) { return r.ok; }).length;
      APPS.forEach(function (a) {
        var mine = list.filter(function (r) { return r.app === a; });
        var ap = { n: mine.length };
        METRICS.forEach(function (m) {
          var v = valuesOf(mine, m);
          ap[m] = v.length >= DAY_MIN ? r2(q(sorted(v), 0.5)) : null;
          ap[m + 'N'] = v.length;
        });
        e.apps[a] = ap;
      });
      // Three counts that do not overlap: every "pay unread" row is suspect
      // too (server.js withPay), so `suspect` here is suspect for any OTHER
      // reason, and a strip stacking the three adds up to the offers it marks.
      e.quality = {
        suspect: list.filter(function (r) { return r.suspect && !r.unread; }).length,
        corrected: list.filter(function (r) { return r.corrected; }).length,
        unread: list.filter(function (r) { return r.unread; }).length
      };
      var known = list.filter(function (r) { return r.app; }).length;
      e.share = { uber: list.filter(function (r) { return r.app === 'uber'; }).length,
                  doordash: list.filter(function (r) { return r.app === 'doordash'; }).length,
                  unknown: list.length - known };
      var bk = list.filter(function (r) { return r.boost !== null; });
      e.boost = bk.length ? { known: bk.length, yes: bk.filter(function (r) { return r.boost; }).length } : null;
      e.good = list.filter(function (r) { return r.good; }).length;
      return e;
    });
  }

  /* --- hours online, from the runs of scanning ------------------------------
   *
   * `runs` are [from, to] in ms: the offers page's own runs of scanning
   * (Advice.runs over Advice.usable, first card to last card), sent by the
   * server beside the rows. A run is credited to the driver day it STARTED on
   * — a run across 4am is one sitting, not two. Hours, not "time worked": the
   * runs page says the same of its own total. */
  function hoursBy(runs, by) {
    var out = Object.create(null);
    (runs || []).forEach(function (sp) {
      if (!sp || !(sp[1] > sp[0])) return;
      var day = dayKeyOf(sp[0]);
      var k = by === 'week' ? weekKeyOf(day) : day;
      out[k] = (out[k] || 0) + (sp[1] - sp[0]) / 3.6e6;
    });
    return out;
  }

  /* The runs cut at every clock hour, as slices: { day, dow, hour, month,
   * hours } keyed by driver day and clock hour. A run from 7:40 to 9:10 is
   * 20 minutes of 7pm, an hour of 8pm and 10 minutes of 9pm. Each slice takes
   * the driver day of its own start — 4am is a clock-hour edge, so no slice
   * straddles two driver days, and a run across 4am puts its 3am minutes on
   * the night before and its 4am minutes on the next day, which is where the
   * cards in those minutes are counted too (unlike hoursBy, whose question is
   * a sitting, not a clock hour). The edge is found on the local clock, from
   * the zone's offset at that moment. */
  function onlinePieces(runs) {
    var out = Object.create(null);
    (runs || []).forEach(function (sp) {
      if (!sp || !(sp[1] > sp[0])) return;
      var t = sp[0];
      for (var guard = 0; t < sp[1] && guard < 10000; guard++) {
        var off = new Date(t).getTimezoneOffset() * 60000;
        var next = (Math.floor((t - off) / 3.6e6) + 1) * 3.6e6 + off;
        if (!(next > t)) next = t + 3.6e6;
        var end = Math.min(next, sp[1]);
        var day = dayKeyOf(t), hour = new Date(t).getHours(), key = day + '|' + hour;
        var e = out[key] || (out[key] = { day: day, dow: dateOfKey(day).getDay(), hour: hour,
                                          month: day.slice(0, 7), hours: 0 });
        e.hours += (end - t) / 3.6e6;
        t = end;
      }
    });
    return out;
  }
  /* Hours online by weekday x clock hour (key dow * 24 + hour), with the
   * driver days each rests on. */
  function hoursByCell(runs) {
    var pieces = onlinePieces(runs), out = Object.create(null);
    Object.keys(pieces).forEach(function (k) {
      var p = pieces[k], c = p.dow * 24 + p.hour;
      var e = out[c] || (out[c] = { hours: 0, days: 0 });
      e.hours += p.hours;
      e.days += 1;
    });
    return out;
  }

  /* Good offers per hour online, by day or week. "Good" is the ruler's (cut)
   * where one is given — the page always gives one — else the row's own
   * target at the time, round one's. Descriptive: it feeds nothing. */
  function goodPerHour(rows, runs, by, cut) {
    var hours = hoursBy(runs, by);
    var g = groupBy(rows, function (r) { return by === 'week' ? r.week : r.day; });
    return g.keys.sort().map(function (k) {
      var list = g.by[k], hrs = hours[k] || 0;
      var good = list.filter(function (r) { return goodOf(r, cut); }).length;
      return { key: k, good: good, offers: list.length, hours: r2(hrs),
               rate: hrs > 0 ? r2(good / hrs) : null, offersRate: hrs > 0 ? r2(list.length / hrs) : null };
    });
  }

  /* --- the hours of the day -------------------------------------------------
   *
   * Median, quartiles and n per clock hour, in the driver's-day order (4am
   * first). `days`: 'all', 'weekday' or 'weekend' (Sat and Sun as the DRIVER'S
   * day, so 1am Saturday is a Friday night). `month`: only rows of that month. */
  /* `stat` (p50, p75, p90 or goodRate) puts that figure in `value`: a
   * quantile, enough at the floor and where its interval's ranks exist; or
   * good offers (the ruler, `cut`) over the hours online in that clock hour
   * (`runs`, cut at the hour; the same days and month), enough at
   * GOOD_FLOOR_HOURS on GOOD_FLOOR_DAYS. */
  function hourly(rows, opts) {
    opts = opts || {};
    var metric = opts.metric || 'perHour';
    var stat = STATS.indexOf(opts.stat) >= 0 ? opts.stat : 'p50';
    function keepDay(dow, month) {
      if (opts.month && month !== opts.month) return false;
      if (opts.days === 'weekend') return dow === 0 || dow === 6;
      if (opts.days === 'weekday') return dow > 0 && dow < 6;
      return true;
    }
    var pick = rows.filter(function (r) { return keepDay(r.dow, r.month); });
    var by = groupBy(pick, function (r) { return r.hour; }).by;
    var online = Object.create(null);
    if (stat === 'goodRate') {
      var pieces = onlinePieces(opts.runs);
      Object.keys(pieces).forEach(function (k) {
        var p = pieces[k];
        if (!keepDay(p.dow, p.month)) return;
        var e = online[p.hour] || (online[p.hour] = { hours: 0, days: 0 });
        e.hours += p.hours; e.days += 1;
      });
    }
    return HOUR_ORDER.map(function (h) {
      var list = by[h] || [];
      var v = valuesOf(list, metric);
      var e = quarts(v);
      e.hour = h;
      e.offers = list.length;
      e.days = daysIn(list.filter(function (r) { return r.ok; }));
      e.enough = v.length >= FLOOR && e.days >= FLOOR_DAYS;
      e.stat = stat;
      if (stat === 'goodRate') {
        var on = online[h] || { hours: 0, days: 0 };
        e.good = list.filter(function (r) { return isGood(r, opts.cut); }).length;
        e.hours = r2(on.hours);
        e.onlineDays = on.days;
        e.value = on.hours > 0 ? r2(e.good / on.hours) : null;
        e.enough = on.hours >= GOOD_FLOOR_HOURS && on.days >= GOOD_FLOOR_DAYS;
      } else {
        e.value = e[stat];
        if (stat !== 'p50' && e.enough) e.enough = !!quantCI(sorted(v), STAT_P[stat], CI_ALPHA);
      }
      return e;
    });
  }

  // The newest month in the rows and the one before it, for the overlay.
  function monthsOf(rows) {
    if (!rows.length) return null;
    var last = rows[rows.length - 1].month;
    var y = Number(last.slice(0, 4)), m = Number(last.slice(5, 7));
    var py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1;
    return { now: last, before: py + '-' + String(pm).padStart(2, '0') };
  }

  /* --- weekday x hour -------------------------------------------------------- */

  /* `stat` as hourly's: a quantile (p50 unless asked) shaded by shadeQ
   * against the same quantile of the whole range, or goodRate — good offers
   * (the ruler, `cut`) over the cell's hours online (`runs`) — shaded by
   * rateShade against the range's own rate, phi measured over the cells'
   * nights. Every cell keeps `median` (round one's field) and adds `value`,
   * the figure of the stat asked. */
  function grid(rows, opts) {
    opts = opts || {};
    var metric = opts.metric || 'perHour';
    var stat = STATS.indexOf(opts.stat) >= 0 ? opts.stat : 'p50';
    var cells = [];
    var by = groupBy(rows, function (r) { return r.dow * 24 + r.hour; }).by;
    if (stat === 'goodRate') return goodGrid(rows, by, opts);
    var p = STAT_P[stat];
    var all = valuesOf(rows, metric);
    var ref = all.length ? q(sorted(all), p) : null;
    for (var d = 1; d <= 7; d++) {
      var dow = d % 7;                              // Monday first, Sunday last
      HOUR_ORDER.forEach(function (h) {
        var list = by[dow * 24 + h] || [];
        var v = valuesOf(list, metric), s = sorted(v);
        var days = daysIn(list.filter(function (r) { return r.ok; }));
        var sh = shadeQ(v, days, ref, p);
        cells.push({ dow: dow, hour: h, n: v.length, days: days,
                     median: v.length ? r2(q(s, 0.5)) : null,
                     value: v.length ? r2(q(s, p)) : null,
                     enough: sh.enough, shade: sh.shade, ci: sh.ci, noRanks: !!sh.noRanks });
      });
    }
    return { stat: stat, ref: r2(ref), floor: FLOOR, floorDays: FLOOR_DAYS, alpha: CI_ALPHA, cells: cells };
  }

  function goodGrid(rows, by, opts) {
    var cut = opts.cut, pieces = onlinePieces(opts.runs);
    // Each cell's nights: { k: good offers that night in it, h: its hours }.
    var nights = Object.create(null), totalH = 0, totalK = 0;
    Object.keys(pieces).forEach(function (key) {
      var p = pieces[key], c = p.dow * 24 + p.hour;
      (nights[c] || (nights[c] = Object.create(null)))[p.day] = { k: 0, h: p.hours };
      totalH += p.hours;
    });
    rows.forEach(function (r) {
      if (!isGood(r, cut)) return;
      totalK += 1;
      var n = nights[r.dow * 24 + r.hour];
      if (n && n[r.day]) n[r.day].k += 1;
    });
    var ref = totalH > 0 ? totalK / totalH : null;
    var groups = Object.keys(nights).map(function (c) {
      return Object.keys(nights[c]).map(function (dk) { return nights[c][dk]; });
    });
    var phi = dispersion(groups);
    var cells = [];
    for (var d = 1; d <= 7; d++) {
      var dow = d % 7;
      HOUR_ORDER.forEach(function (h) {
        var c = dow * 24 + h, list = by[c] || [];
        var good = list.filter(function (r) { return isGood(r, cut); }).length;
        var ns = nights[c] || {}, hrs = 0, days = 0;
        Object.keys(ns).forEach(function (dk) { if (ns[dk].h > 0) { hrs += ns[dk].h; days += 1; } });
        var v = valuesOf(list, 'perHour');
        var enough = hrs >= GOOD_FLOOR_HOURS && days >= GOOD_FLOOR_DAYS;
        var sh = enough ? rateShade(good, hrs, ref, phi) : { shade: null, ci: null };
        cells.push({ dow: dow, hour: h, n: v.length, good: good, hours: r2(hrs), days: days,
                     median: v.length ? r2(q(sorted(v), 0.5)) : null,
                     value: hrs > 0 ? r2(good / hrs) : null,
                     enough: enough, shade: sh.shade, ci: sh.ci });
      });
    }
    return { stat: 'goodRate', ref: ref === null ? null : r2(ref), phi: Math.round(phi * 100) / 100, cut: cut,
             floorHours: GOOD_FLOOR_HOURS, floorDays: GOOD_FLOOR_DAYS, alpha: CI_ALPHA, cells: cells };
  }

  /* --- the calendar ----------------------------------------------------------
   *
   * A tile a driver day: its median $/hr and its offers per hour online, shaded
   * by the grid's own rule against the window's median (one day is one day, so
   * the two-day half of the floor does not apply to a tile). */
  /* Round two (the owner: "make comparing over time easy"): `opts.stat` and
   * `opts.cut` as the grid's, so a tile reads the same figure as the grid and
   * is counted against the same fixed ruler. A day's goodRate is its good
   * offers over its hours online (hoursBy: a run is credited to the day it
   * began, as the good-per-hour chart has always done), shaded by the plain
   * Poisson interval at GOOD_FLOOR_HOURS — one day is one day, and a day's
   * own swing is the very thing a tile is asked about.
   *
   * `weeks`: the tiles as rows Monday to Sunday from the first week to the
   * last, so a weekday lines up down a column, each with the week's own
   * figure pooled over its offers (shaded on FLOOR_DAYS days, as a grid cell;
   * a week's goodRate widened by phi over its days, as the grid's over its
   * nights) and a month label on the first row and on the row holding a 1st.
   * `months`: the newest month in the range so far against the one before. */
  function calendar(rows, runs, opts) {
    opts = opts || {};
    var stat = STATS.indexOf(opts.stat) >= 0 ? opts.stat : 'p50';
    var p = STAT_P[stat] || 0.5, cut = opts.cut;
    var all = valuesOf(rows, 'perHour');
    var refQ = all.length ? q(sorted(all), p) : null;
    var hours = hoursBy(runs, 'day');
    var totalH = 0, totalK = 0;
    Object.keys(hours).forEach(function (k) { totalH += hours[k]; });
    rows.forEach(function (r) { if (isGood(r, cut)) totalK += 1; });
    var refRate = stat === 'goodRate' && totalH > 0 ? totalK / totalH : null;
    var ref = stat === 'goodRate' ? refRate : refQ;
    var g = groupBy(rows, function (r) { return r.day; });
    var refMed = all.length ? q(sorted(all), 0.5) : null;
    var days = g.keys.sort().map(function (k) {
      var list = g.by[k];
      var v = valuesOf(list, 'perHour'), s = sorted(v);
      var hrs = hours[k] || 0;
      var good = list.filter(function (r) { return isGood(r, cut); }).length;
      var e = { day: k, dow: dateOfKey(k).getDay(), week: weekKeyOf(k), n: list.length, counted: v.length,
                median: v.length ? r2(q(s, 0.5)) : null, good: good,
                hours: r2(hrs), perOnlineHour: hrs > 0 ? r2(list.length / hrs) : null };
      if (stat === 'goodRate') {
        e.value = hrs > 0 ? r2(good / hrs) : null;
        e.enough = hrs >= GOOD_FLOOR_HOURS;
        var rs = e.enough ? rateShade(good, hrs, refRate, 1) : { shade: null };
        e.shade = rs.shade;
      } else {
        e.value = v.length ? r2(q(s, p)) : null;
        var sh = shadeQ(v, 1, refQ, p, 1);
        e.enough = sh.enough; e.shade = sh.shade;
      }
      return e;
    });
    var byDay = Object.create(null);
    days.forEach(function (d) { byDay[d.day] = d; });

    var weeks = [];
    if (days.length) {
      var gw = groupBy(rows, function (r) { return r.week; });
      var wk = weekKeyOf(days[0].day), lastWk = weekKeyOf(days[days.length - 1].day);
      var dayGroups = [];
      for (var guard = 0; wk <= lastWk && guard < 1000; guard++) {
        var keys = [], label = null;
        for (var i = 0; i < 7; i++) {
          var dk = addDays(wk, i);
          keys.push(dk);
          if (dk.slice(8) === '01') label = dk.slice(0, 7);
        }
        if (!weeks.length) label = days[0].day.slice(0, 7);
        var wl = gw.by[wk] || [];
        var w = { week: wk, days: keys, month: label, n: wl.length };
        var wv = valuesOf(wl, 'perHour');
        var wdays = daysIn(wl.filter(function (r) { return r.ok; }));
        if (stat === 'goodRate') {
          var wh = 0, wg = 0, pcs = [];
          keys.forEach(function (dk) {
            var d = byDay[dk], h = hours[dk] || 0;
            wh += h;
            if (d) wg += d.good;
            if (h > 0) pcs.push({ k: d ? d.good : 0, h: h });
          });
          dayGroups.push(pcs);
          w.good = wg; w.hours = r2(wh); w.onlineDays = pcs.length;
          w.value = wh > 0 ? r2(wg / wh) : null;
          w.enough = wh >= GOOD_FLOOR_HOURS && pcs.length >= GOOD_FLOOR_DAYS;
        } else {
          w.counted = wv.length;
          w.value = wv.length ? r2(q(sorted(wv), p)) : null;
          var ws = shadeQ(wv, wdays, refQ, p);
          w.enough = ws.enough; w.shade = ws.shade;
        }
        weeks.push(w);
        wk = addDays(wk, 7);
      }
      if (stat === 'goodRate') {
        var phi = dispersion(dayGroups);
        weeks.forEach(function (w) {
          w.shade = w.enough ? rateShade(w.good, w.hours, refRate, phi).shade : null;
        });
      }
    }
    return { stat: stat, ref: ref === null ? null : r2(ref), refMedian: r2(refMed), floor: FLOOR,
             floorHours: GOOD_FLOOR_HOURS, cut: cut === undefined ? null : cut,
             days: days, weeks: weeks, months: monthFigures(rows, runs, stat, cut) };
  }

  /* The newest month in the rows so far against the whole month before it,
   * in the stat asked, each with its n: offers counted for a quantile, good
   * offers and hours online for goodRate. Null where the range holds nothing
   * of the month before (a 7- or 30-day range early in a month). */
  function monthFigures(rows, runs, stat, cut) {
    var mo = monthsOf(rows);
    if (!mo) return null;
    var hours = hoursBy(runs, 'day');
    function side(m) {
      var list = rows.filter(function (r) { return r.month === m; });
      var e = { month: m, offers: list.length, days: daysIn(list) };
      if (!list.length) { e.value = null; e.n = 0; return e; }
      if (stat === 'goodRate') {
        var h = 0;
        Object.keys(hours).forEach(function (k) { if (k.slice(0, 7) === m) h += hours[k]; });
        e.good = list.filter(function (r) { return isGood(r, cut); }).length;
        e.hours = r2(h); e.n = e.good;
        e.value = h > 0 ? r2(e.good / h) : null;
      } else {
        var v = valuesOf(list, 'perHour');
        e.n = v.length;
        e.value = v.length ? r2(q(sorted(v), STAT_P[stat] || 0.5)) : null;
      }
      return e;
    }
    var now = side(mo.now), before = side(mo.before);
    now.through = rows[rows.length - 1].day;
    return { now: now, before: before.offers ? before : null };
  }

  /* --- one cell, looked at closely ---------------------------------------------
   *
   * The weekday x hour cell a driver pressed: every money offer's $/hr in it
   * (for the dot strip, with whether the driver ticked it taken and its app),
   * the P50/P75/P90, the two apps apart, the best five by $/hr, and the cell's
   * figure week by week. Figures and times only: pay, minutes, miles, app and
   * when — no text and no place, because the rows carry none to give. */
  function cellDetail(rows, runs, dow, hour, opts) {
    opts = opts || {};
    var stat = STATS.indexOf(opts.stat) >= 0 ? opts.stat : 'p50', cut = opts.cut;
    var p = STAT_P[stat] || 0.5;
    var list = rows.filter(function (r) { return r.dow === dow && r.hour === hour; });
    var money = list.filter(function (r) { return r.ok && r.perHour !== null && r.perHour !== undefined; });
    var pieces = onlinePieces(runs), hoursByWeek = Object.create(null), hrs = 0;
    Object.keys(pieces).forEach(function (k) {
      var pc = pieces[k];
      if (pc.dow !== dow || pc.hour !== hour) return;
      hrs += pc.hours;
      var wk = weekKeyOf(pc.day);
      hoursByWeek[wk] = (hoursByWeek[wk] || 0) + pc.hours;
    });
    function figure(sub, h) {
      if (stat === 'goodRate') {
        var gd = sub.filter(function (r) { return isGood(r, cut); }).length;
        return h > 0 ? r2(gd / h) : null;
      }
      var v = valuesOf(sub, 'perHour');
      return v.length ? r2(q(sorted(v), p)) : null;
    }
    var all = sorted(valuesOf(list, 'perHour'));
    var apps = {};
    APPS.forEach(function (a) {
      var mine = list.filter(function (r) { return r.app === a; });
      apps[a] = { n: valuesOf(mine, 'perHour').length, offers: mine.length,
                  good: mine.filter(function (r) { return isGood(r, cut); }).length, value: figure(mine, hrs) };
    });
    var best = money.slice().sort(function (a, b) { return b.perHour - a.perHour || a.t - b.t; }).slice(0, 5)
      .map(function (r) {
        return { t: r.t, day: r.day, app: r.app, pay: r.pay, minutes: r.minutes, miles: r.miles,
                 perHour: r.perHour, taken: r.taken };
      });
    var gw = groupBy(list, function (r) { return r.week; });
    var wkeys = gw.keys.slice();
    Object.keys(hoursByWeek).forEach(function (wk) { if (wkeys.indexOf(wk) < 0) wkeys.push(wk); });
    var weeks = wkeys.sort().map(function (wk) {
      var sub = gw.by[wk] || [], h = hoursByWeek[wk] || 0;
      return { week: wk, n: valuesOf(sub, 'perHour').length, offers: sub.length,
               good: sub.filter(function (r) { return isGood(r, cut); }).length, hours: r2(h),
               value: figure(sub, h) };
    });
    return {
      dow: dow, hour: hour, stat: stat, cut: typeof cut === 'number' ? cut : null,
      offers: list.length, n: all.length, days: daysIn(money), hours: r2(hrs),
      good: list.filter(function (r) { return isGood(r, cut); }).length,
      taken: list.filter(function (r) { return r.taken; }).length,
      value: figure(list, hrs),
      p50: r2(q(all, 0.5)), p75: r2(q(all, 0.75)), p90: r2(q(all, 0.9)),
      dots: money.map(function (r) { return [r.perHour, r.taken ? 1 : 0, appCode(r.app)]; }),
      apps: apps, best: best, weeks: weeks
    };
  }

  /* --- the rate card --------------------------------------------------------- */

  // Least squares of y on [1, x1, x2]: [base, a, b], or null when singular.
  function fit3(xs1, xs2, ys) {
    var n = ys.length, s1 = 0, s2 = 0, sy = 0, s11 = 0, s22 = 0, s12 = 0, s1y = 0, s2y = 0;
    for (var i = 0; i < n; i++) {
      var a = xs1[i], b = xs2[i], y = ys[i];
      s1 += a; s2 += b; sy += y; s11 += a * a; s22 += b * b; s12 += a * b; s1y += a * y; s2y += b * y;
    }
    // Centred: the slopes from the 2x2 covariance system, then the base.
    var m1 = s1 / n, m2 = s2 / n, my = sy / n;
    var c11 = s11 / n - m1 * m1, c22 = s22 / n - m2 * m2, c12 = s12 / n - m1 * m2;
    var c1y = s1y / n - m1 * my, c2y = s2y / n - m2 * my;
    var det = c11 * c22 - c12 * c12;
    if (!(c11 > 0) || !(c22 > 0) || !(Math.abs(det) > 1e-12 * c11 * c22)) return null;
    var a1 = (c1y * c22 - c2y * c12) / det;
    var b1 = (c2y * c11 - c1y * c12) / det;
    return { base: my - a1 * m1 - b1 * m2, a: a1, b: b1,
             r2mm: (c12 * c12) / (c11 * c22) };
  }

  function lcg(seed) {
    var s = seed >>> 0;
    return function () { s = (1664525 * s + 1013904223) >>> 0; return s / 4294967296; };
  }
  function seedOf(text) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  /* One fit with its interval, or why there is none. */
  function rateFit(list, seedText, boots) {
    var rows = list.filter(function (r) {
      return r.ok && r.pay !== null && r.minutes !== null && r.miles !== null && r.minutes > 0 && r.miles > 0;
    });
    var out = { n: rows.length, base: null, a: null, b: null, price: null, lo: null, hi: null, thin: null };
    if (rows.length < RATE_MIN_N) { out.thin = 'fewer than ' + RATE_MIN_N + ' offers'; return out; }
    var x1 = rows.map(function (r) { return r.minutes; }), x2 = rows.map(function (r) { return r.miles; });
    var y = rows.map(function (r) { return r.pay; });
    var f = fit3(x1, x2, y);
    if (!f) { out.thin = 'minutes or miles never vary'; return out; }
    if (f.r2mm > RATE_COLLINEAR) { out.thin = 'minutes and miles move together; the fit cannot tell them apart'; return out; }
    out.base = r2(f.base); out.a = Math.round(f.a * 1000) / 1000; out.b = Math.round(f.b * 1000) / 1000;
    out.price = r2(f.base + f.a * RATE_AT.minutes + f.b * RATE_AT.miles);
    var reps = boots || RATE_BOOTS, rnd = lcg(seedOf(seedText)), n = rows.length;
    var b1 = new Array(n), b2 = new Array(n), by = new Array(n), prices = [];
    for (var k = 0; k < reps; k++) {
      for (var i = 0; i < n; i++) {
        var j = Math.floor(rnd() * n);
        b1[i] = x1[j]; b2[i] = x2[j]; by[i] = y[j];
      }
      var g = fit3(b1, b2, by);
      if (g) prices.push(g.base + g.a * RATE_AT.minutes + g.b * RATE_AT.miles);
    }
    if (prices.length >= reps * 0.9) {
      prices.sort(function (p1, p2) { return p1 - p2; });
      out.lo = r2(prices[Math.floor(0.025 * prices.length)]);
      out.hi = r2(prices[Math.ceil(0.975 * prices.length) - 1]);
    }
    return out;
  }

  function rateCard(rows, opts) {
    opts = opts || {};
    var g = groupBy(rows, function (r) { return r.week; });
    return { at: RATE_AT, minN: RATE_MIN_N, weeks: g.keys.sort().map(function (wk) {
      var e = { week: wk };
      APPS.forEach(function (a) {
        e[a] = rateFit(g.by[wk].filter(function (r) { return r.app === a; }), wk + a, opts.boots);
      });
      return e;
    }) };
  }

  /* --- two periods ----------------------------------------------------------
   *
   * A period is { from, to } as driver-day keys (inclusive), or 'weekday' /
   * 'weekend'. Medians of every metric side by side with their n, the good
   * share (the ruler's, `cut`, where given) and the offers counted.
   * Descriptive: no test, no verdict. */
  function inPeriod(r, p) {
    if (p === 'weekday') return r.dow > 0 && r.dow < 6;
    if (p === 'weekend') return r.dow === 0 || r.dow === 6;
    if (!p || typeof p !== 'object') return true;
    return (!p.from || r.day >= p.from) && (!p.to || r.day <= p.to);
  }
  function compare(rows, a, b, cut) {
    function side(p) {
      var list = rows.filter(function (r) { return inPeriod(r, p); });
      var e = { offers: list.length, counted: list.filter(function (r) { return r.ok; }).length,
                days: daysIn(list), good: list.filter(function (r) { return goodOf(r, cut); }).length, metrics: {} };
      METRICS.forEach(function (m) {
        var v = valuesOf(list, m);
        e.metrics[m] = { n: v.length, median: v.length ? r2(q(sorted(v), 0.5)) : null };
      });
      return e;
    }
    return { a: side(a), b: side(b) };
  }

  /* --- pay against miles -----------------------------------------------------
   *
   * Points [miles, pay, period], coloured by calendar month (the newest five
   * each their own, anything older as one). Thinned evenly in time past
   * `max`, and the answer says so: a scatter of twelve thousand dots on a
   * phone is a blot. */
  function scatter(rows, max) {
    var pts = rows.filter(function (r) { return r.ok && r.pay !== null && r.miles !== null; });
    var months = [];
    pts.forEach(function (r) { if (months.indexOf(r.month) < 0) months.push(r.month); });
    months.sort();
    var keep = months.slice(-5), older = months.length > keep.length;
    var labels = (older ? ['earlier'] : []).concat(keep);
    var count = max && pts.length > max ? max : pts.length, step = pts.length / Math.max(1, count);
    var out = [];
    for (var x = 0; x < count; x++) {
      var r = pts[Math.floor(x * step)];
      var i = keep.indexOf(r.month);
      out.push([r.miles, r.pay, i < 0 ? 0 : i + (older ? 1 : 0)]);
    }
    return { points: out, of: pts.length, labels: labels };
  }

  /* --- CSV ------------------------------------------------------------------- */

  function cell(v) {
    if (v === null || v === undefined) return '';
    var s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  // `cut`: the ruler the good column was counted against, printed beside it,
  // so a CSV opened next month still says what "good" meant in it.
  function csvPeriods(list, goods, by, cut) {
    var gBy = Object.create(null);
    (goods || []).forEach(function (g) { gBy[g.key] = g; });
    var head = [by === 'week' ? 'week_of' : 'day', 'offers', 'counted'];
    METRICS.forEach(function (m) { ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { head.push(m + '_' + k); }); });
    head = head.concat(['uber_offers', 'doordash_offers', 'app_unknown', 'uber_median_per_hour',
                        'doordash_median_per_hour', 'good', 'good_from_per_hour', 'hours_online', 'good_per_online_hour',
                        'suspect', 'corrected', 'pay_unread', 'boost_known', 'boost_yes']);
    var lines = [head];
    list.forEach(function (e) {
      var row = [e.key, e.n, e.counted];
      METRICS.forEach(function (m) {
        ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { row.push(e.metrics[m][k]); });
      });
      var g = gBy[e.key] || {};
      row = row.concat([e.share.uber, e.share.doordash, e.share.unknown, e.apps.uber.perHour,
                        e.apps.doordash.perHour, g.good !== undefined ? g.good : e.good, cut, g.hours, g.rate,
                        e.quality.suspect,
                        e.quality.corrected, e.quality.unread, e.boost ? e.boost.known : '',
                        e.boost ? e.boost.yes : '']);
      lines.push(row);
    });
    return lines.map(function (l) { return l.map(cell).join(','); }).join('\n') + '\n';
  }
  function csvHourly(list, label) {
    var lines = [['hours', 'hour', 'offers', 'counted', 'days', 'p25', 'p50', 'p75', 'p90', 'enough']];
    list.forEach(function (e) {
      lines.push([label || 'all', e.hour, e.offers, e.n, e.days, e.p25, e.p50, e.p75, e.p90, e.enough ? 'yes' : 'no']);
    });
    return lines.map(function (l) { return l.map(cell).join(','); }).join('\n') + '\n';
  }

  return {
    FLOOR: FLOOR, FLOOR_DAYS: FLOOR_DAYS, CI_ALPHA: CI_ALPHA, DAY_MIN: DAY_MIN,
    RATE_MIN_N: RATE_MIN_N, RATE_COLLINEAR: RATE_COLLINEAR, RATE_AT: RATE_AT, RATE_BOOTS: RATE_BOOTS,
    METRICS: METRICS, METRIC_NAMES: METRIC_NAMES, APPS: APPS, WEEKDAYS: WEEKDAYS, HOUR_ORDER: HOUR_ORDER,
    distinct: distinct, rowsOf: rowsOf, pack: pack, unpack: unpack, readRows: readRows,
    dayKeyOf: dayKeyOf, weekKeyOf: weekKeyOf, addDays: addDays,
    medianRank: medianRank, shadeOf: shadeOf, quarts: quarts,
    TOPS: TOPS, TOP_DEFAULT: TOP_DEFAULT, STATS: STATS, STAT_P: STAT_P, STAT_NAMES: STAT_NAMES,
    GOOD_FLOOR_HOURS: GOOD_FLOOR_HOURS, GOOD_FLOOR_DAYS: GOOD_FLOOR_DAYS, F_TAKEN: F_TAKEN,
    quantRanks: quantRanks, quantCI: quantCI, shadeQ: shadeQ, poisCI: poisCI, dispersion: dispersion,
    rateShade: rateShade, ruler: ruler, isGood: isGood,
    onlinePieces: onlinePieces, hoursByCell: hoursByCell, cellDetail: cellDetail,
    periods: periods, hoursBy: hoursBy, goodPerHour: goodPerHour, hourly: hourly, monthsOf: monthsOf,
    grid: grid, calendar: calendar, fit3: fit3, rateFit: rateFit, rateCard: rateCard,
    compare: compare, scatter: scatter, csvPeriods: csvPeriods, csvHourly: csvHourly
  };
}));
