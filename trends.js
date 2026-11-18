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
 * drawn to read, never as a rule or a floor; "good" is the row's OWN target at
 * the time (the line the panel judged it against), never a line tuned to an
 * hour or a weekday; the weekday x hour grid is a picture of the record, and
 * nothing reads it back into the accept line (AUDITS.md, Settled, "The maps").
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
  // The hours in the order a driver's day runs: 4am first, the small hours
  // last, so a night is one stretch of the chart and not its two ends.
  var HOUR_ORDER = [];
  for (var h0 = 0; h0 < 24; h0++) HOUR_ORDER.push((h0 + DAY_STARTS_AT) % 24);

  // Flag bits on a packed row.
  var F_OK = 1, F_GOOD = 2, F_SUSPECT = 4, F_CORRECTED = 8, F_UNREAD = 16, F_BOOST_KNOWN = 32, F_BOOST = 64;

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
        boost: f & F_BOOST_KNOWN ? !!(f & F_BOOST) : null
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
  function medianCI(s, alpha) {
    var k = medianRank(s.length, alpha);
    return k >= 1 ? [s[k - 1], s[s.length - k]] : null;
  }

  /* Shade a group against a reference median: 'above', 'below' or null, by
   * the rule in the header. `days` is how many driver days it rests on. */
  function shadeOf(vals, days, ref, minDays) {
    var need = typeof minDays === 'number' ? minDays : FLOOR_DAYS;
    if (vals.length < FLOOR || days < need || ref === null) return { enough: false, shade: null, ci: null };
    var s = sorted(vals);
    var ci = medianCI(s, CI_ALPHA);
    var shade = ci && ci[0] > ref ? 'above' : ci && ci[1] < ref ? 'below' : null;
    return { enough: true, shade: shade, ci: ci ? [r2(ci[0]), r2(ci[1])] : null };
  }

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

  /* Good offers per hour online, by day or week. "Good" is the row's own
   * target (the panel's verdict at the time). Descriptive: it feeds nothing. */
  function goodPerHour(rows, runs, by) {
    var hours = hoursBy(runs, by);
    return periods(rows, by).map(function (e) {
      var hrs = hours[e.key] || 0;
      return { key: e.key, good: e.good, offers: e.n, hours: r2(hrs),
               rate: hrs > 0 ? r2(e.good / hrs) : null, offersRate: hrs > 0 ? r2(e.n / hrs) : null };
    });
  }

  /* --- the hours of the day -------------------------------------------------
   *
   * Median, quartiles and n per clock hour, in the driver's-day order (4am
   * first). `days`: 'all', 'weekday' or 'weekend' (Sat and Sun as the DRIVER'S
   * day, so 1am Saturday is a Friday night). `month`: only rows of that month. */
  function hourly(rows, opts) {
    opts = opts || {};
    var metric = opts.metric || 'perHour';
    var pick = rows.filter(function (r) {
      if (opts.month && r.month !== opts.month) return false;
      if (opts.days === 'weekend') return r.dow === 0 || r.dow === 6;
      if (opts.days === 'weekday') return r.dow > 0 && r.dow < 6;
      return true;
    });
    var by = groupBy(pick, function (r) { return r.hour; }).by;
    return HOUR_ORDER.map(function (h) {
      var list = by[h] || [];
      var v = valuesOf(list, metric);
      var e = quarts(v);
      e.hour = h;
      e.offers = list.length;
      e.days = daysIn(list.filter(function (r) { return r.ok; }));
      e.enough = v.length >= FLOOR && e.days >= FLOOR_DAYS;
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

  function grid(rows, opts) {
    opts = opts || {};
    var metric = opts.metric || 'perHour';
    var all = valuesOf(rows, metric);
    var ref = all.length ? q(sorted(all), 0.5) : null;
    var cells = [];
    var by = groupBy(rows, function (r) { return r.dow * 24 + r.hour; }).by;
    for (var d = 1; d <= 7; d++) {
      var dow = d % 7;                              // Monday first, Sunday last
      HOUR_ORDER.forEach(function (h) {
        var list = by[dow * 24 + h] || [];
        var v = valuesOf(list, metric);
        var days = daysIn(list.filter(function (r) { return r.ok; }));
        var sh = shadeOf(v, days, ref);
        cells.push({ dow: dow, hour: h, n: v.length, days: days,
                     median: v.length ? r2(q(sorted(v), 0.5)) : null,
                     enough: sh.enough, shade: sh.shade, ci: sh.ci });
      });
    }
    return { ref: r2(ref), floor: FLOOR, floorDays: FLOOR_DAYS, alpha: CI_ALPHA, cells: cells };
  }

  /* --- the calendar ----------------------------------------------------------
   *
   * A tile a driver day: its median $/hr and its offers per hour online, shaded
   * by the grid's own rule against the window's median (one day is one day, so
   * the two-day half of the floor does not apply to a tile). */
  function calendar(rows, runs) {
    var all = valuesOf(rows, 'perHour');
    var ref = all.length ? q(sorted(all), 0.5) : null;
    var hours = hoursBy(runs, 'day');
    var g = groupBy(rows, function (r) { return r.day; });
    return { ref: r2(ref), floor: FLOOR, days: g.keys.sort().map(function (k) {
      var list = g.by[k];
      var v = valuesOf(list, 'perHour');
      var sh = shadeOf(v, 1, ref, 1);
      var hrs = hours[k] || 0;
      return { day: k, dow: dateOfKey(k).getDay(), n: list.length, counted: v.length,
               median: v.length ? r2(q(sorted(v), 0.5)) : null,
               hours: r2(hrs), perOnlineHour: hrs > 0 ? r2(list.length / hrs) : null,
               enough: sh.enough, shade: sh.shade };
    }) };
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
   * share and the offers counted. Descriptive: no test, no verdict. */
  function inPeriod(r, p) {
    if (p === 'weekday') return r.dow > 0 && r.dow < 6;
    if (p === 'weekend') return r.dow === 0 || r.dow === 6;
    if (!p || typeof p !== 'object') return true;
    return (!p.from || r.day >= p.from) && (!p.to || r.day <= p.to);
  }
  function compare(rows, a, b) {
    function side(p) {
      var list = rows.filter(function (r) { return inPeriod(r, p); });
      var e = { offers: list.length, counted: list.filter(function (r) { return r.ok; }).length,
                days: daysIn(list), good: list.filter(function (r) { return r.good; }).length, metrics: {} };
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
  function csvPeriods(list, goods, by) {
    var gBy = Object.create(null);
    (goods || []).forEach(function (g) { gBy[g.key] = g; });
    var head = [by === 'week' ? 'week_of' : 'day', 'offers', 'counted'];
    METRICS.forEach(function (m) { ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { head.push(m + '_' + k); }); });
    head = head.concat(['uber_offers', 'doordash_offers', 'app_unknown', 'uber_median_per_hour',
                        'doordash_median_per_hour', 'good', 'hours_online', 'good_per_online_hour',
                        'suspect', 'corrected', 'pay_unread', 'boost_known', 'boost_yes']);
    var lines = [head];
    list.forEach(function (e) {
      var row = [e.key, e.n, e.counted];
      METRICS.forEach(function (m) {
        ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { row.push(e.metrics[m][k]); });
      });
      var g = gBy[e.key] || {};
      row = row.concat([e.share.uber, e.share.doordash, e.share.unknown, e.apps.uber.perHour,
                        e.apps.doordash.perHour, e.good, g.hours, g.rate, e.quality.suspect,
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
    periods: periods, hoursBy: hoursBy, goodPerHour: goodPerHour, hourly: hourly, monthsOf: monthsOf,
    grid: grid, calendar: calendar, fit3: fit3, rateFit: rateFit, rateCard: rateCard,
    compare: compare, scatter: scatter, csvPeriods: csvPeriods, csvHourly: csvHourly
  };
}));
