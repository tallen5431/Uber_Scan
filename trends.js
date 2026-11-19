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
 * Round one's per-row flag (F_GOOD) is no longer packed: the daily CSV and
 * goodPerHour fell back to it with no ruler, then stopped, and nothing read
 * it after (its bit stays unused; see the flag bits).
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
 * QUANTILES AND THE NIGHTS (the reporting review, Nov 2026). The table
 * above draws every offer independently, and a night's offers are not: on
 * a slow night the whole hour sits lower. Simulated again on a record like
 * the owner's (37 driver days in nine weeks, ~54 cards an hour, 6 hours a
 * night, no weekday or hour effect at all; tau the sd of a night's shift in
 * log $/hr, cv the swing in its card rate; 300 screens a row), the share of
 * no-effect cells shaded, before -> after:
 *
 *      tau, cv    |    P50          |    P75          |    P90
 *     ------------+-----------------+-----------------+----------------
 *      0,    0    | 0.77% -> 0.64%  | 0.70% -> 0.57%  | 0.65% -> 0.42%
 *      0.05, 0    | 2.86% -> 0.57%  | 2.34% -> 0.47%  | 1.73% -> 0.47%
 *      0.1,  0.4  | 11.3% -> 0.52%  | 9.50% -> 0.61%  | 5.43% -> 0.50%
 *      0.2,  0.4  | 33.2% -> 0.40%  | 30.0% -> 0.65%  | 20.7% -> 0.92%
 *
 * So each quantile interval is widened by its cell's own design effect
 * (quantCIw): the ranks taken at n / phi_q, phi_q = 1 + (m - 1) rho_q, m
 * the cell's offers a night and rho_q the record's own intra-night
 * correlation of "above the reference" (qRho), measured over every cell's
 * nights as good per hour's phi is. The compare mode's quantiles (0.4-0.7%
 * after, 13% before at 0.1) and the timeline's weeks and months take the
 * same widening, and the calendar's week column with its days as nights; a
 * calendar tile is one day, so a day's own swing is what it asks about and
 * it stays plain. The cost, a +20% hour on Friday and Saturday evenings:
 * shaded 92% -> 92% with no swing, and 84% -> 45% at tau 0.1 — where the
 * 84% stood beside 14% of no-effect cells shaded too. A cell under the
 * widening needs more offers before its ranks exist, so at a 20% swing a
 * P90 cell is grey far more often: that is the honest answer.
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
 * ROUND THREE (the owner, Nov 2026): what the hours EARNED, how long a good
 * offer takes, which app brings them, the rig off against a quiet hour, an
 * hour x date timeline, two periods cell by cell, one weekday over the weeks
 * and the thirds of a month. Still descriptive: nothing here reaches the
 * verdict, the target, the panel, the rig or any rule.
 *
 * EARNED PER HOUR ONLINE, gross or net. The card's pay of the offers the
 * driver ticked taken (the taken bit; silence is never an accept, so it is a
 * floor), net of their miles at ONE cost per mile — the rig's own setting,
 * the one every verdict is already net of (AUDITS.md, "Every verdict was net
 * of a cost per mile nobody chose") — over every minute online in the cell,
 * waiting included. Not a $/mi rule and not a floor: a cost the driver set,
 * subtracted for reading. The interval is earnCI's weighted-Poisson gamma
 * interval (Fay and Feuer), widened by phi off the takes. The brief offered
 * a bootstrap over driver days; it was simulated first and refused. Cells of
 * one-hour nights, takes 1 an hour with a 40% night-to-night swing, pay
 * log-normal around $12 (40 cells x 100 grids a row), shaded against the
 * true rate at 99%:
 *
 *     nights x hours | bootstrap over days | gamma, plain | gamma, widened | widened, +50%
 *     ---------------+---------------------+--------------+----------------+--------------
 *      2 x 1 h       |        51.6%        |     0.3%     |      0.2%      |      1%
 *      3 x 1 h       |        27.9%        |     0.5%     |      0.3%      |      2%
 *      4 x 1 h       |        20.4%        |     0.3%     |      0.3%      |      3%
 *      6 x 1 h       |        10.9%        |     1.2%     |      0.7%      |      5%
 *     10 x 1 h       |         6.6%        |     1.1%     |      0.9%      |      7%
 *      2 x 0.5 h     |        55.0%        |     0.2%     |      0.2%      |      1%
 *
 * A bootstrap over two or three nights can only draw the nights it has, so
 * its interval is the span between them, and a cell with no take on either
 * night bootstraps to [0, 0] and is shaded "below" with certainty. The gamma
 * interval holds 1% from the first row, so the floor is good/hr's own: 2
 * hours online on 2 driver days (phi needs two nights to measure). The last
 * column is the honest cost: a take an hour is a thin thing to rank hours
 * by, and a cell has to be far out, over many nights, to be shaded at all.
 *
 * A GOOD OFFER ABOUT EVERY N MINUTES is 60 over good per hour online: the
 * same count and the same hours, at the same floor (2 hours on 2 days in a
 * cell; 2 hours for one day's tile), and "too little time" under it. Where
 * that much time held no good offer it says so, rather than "every ∞ min".
 *
 * OFF IS NOT QUIET. A cell, tile or square with no minute online and no card
 * is `off` — the rig was not scanning — and drawn apart (hatched) from one
 * that was online and saw few offers, which is a finding.
 *
 * B AGAINST A, the compare mode's grid (gridCompare). B's figure minus A's
 * per cell, shaded only where both sides meet the grid's floor and the
 * difference clears 99%. Simulated with no difference at all (3,000 pairs a
 * row for quantiles; 40 cells x 100 grids for the rates):
 *
 *     quantile, n A/B | P50 null, +$3 | P75 null, +$3 | P90 null, +$3
 *     ----------------+---------------+---------------+--------------
 *        30 / 30      |  0.5%,  10%   |  0.1%,   5%   |  0.0%,   0%
 *        60 / 60      |  0.4%,  31%   |  0.4%,  24%   |  0.6%,  10%
 *       100 / 100     |  0.7%,  60%   |  0.6%,  45%   |  0.5%,  23%
 *        40 / 120     |  0.7%,  32%   |  0.7%,  21%   |  0.3%,  10%
 *       200 / 200     |  0.6%,  94%   |  0.7%,  87%   |  0.8%,  63%
 *
 *     nights A vs B | good/hr plain | good/hr widened, +50% | earned/hr widened, +50%
 *     --------------+---------------+-----------------------+------------------------
 *        2 vs 2     |     5.0%      |      0.6%,  2%        |      0.1%,  0%
 *        4 vs 4     |     4.9%      |      0.7%,  4%        |      0.3%,  1%
 *        8 vs 8     |     5.3%      |      0.8%, 10%        |      0.6%,  2%
 *        4 vs 10    |     5.2%      |      0.8%,  5%        |      0.4%,  1%
 *
 * A quantile is two order-statistic intervals at CMP_SIDE_ALPHA that must
 * not overlap (rank-based like the grid's own, so no draw and no seed); good
 * per hour is the exact conditional test of two Poisson rates on k/phi (a
 * plain one shaded 5% by chance, as the grid's did before it was widened);
 * earned per hour is two widened gamma intervals at CMP_SIDE_ALPHA that must
 * not overlap. All hold under 1%; the earned column says plainly that two
 * periods' earnings per hour rarely differ clearly enough cell by cell.
 *
 * THE TIMELINE, by day, week (Monday 4am) or month (driver day), newest row
 * first; each square pooled by the grid's rules, so a single day-hour stays
 * grey and the weeks and months are what can be shaded. MONTH THIRDS are
 * shaded only once each third holds THIRDS_MONTHS months.
 *
 * THE WEEK IN REVIEW (the owner, Nov 2026, the reporting work's third
 * round; weekReview): one driver week, Monday 4am to Monday 4am, as a card —
 * hours online, offers, good offers (the ruler) and good per hour, takes,
 * earned per hour gross and net, the best and worst slot, the data-quality
 * counts — stepped a week at a time. Every figure is the slice table's, so a
 * week here is exactly the timeline's week row. The page adds the Money tab's
 * matched-earnings coverage and paid-against-the-card median from earnings.js
 * rangeSummary over the week's own span (weekSpanMs: 169 hours the week of 1
 * Nov), never a copy of that sum. Two things are MARKED and nothing else:
 *   - against the week before, good per hour and earned per hour, only where
 *     BOTH weeks meet the week's floor (the calendar's week column:
 *     GOOD_FLOOR_HOURS online on GOOD_FLOOR_DAYS driver days), by compare
 *     mode's own tests at its own levels (good per hour the exact conditional
 *     test on k/phi; earned two widened gamma intervals at CMP_SIDE_ALPHA
 *     that must not overlap), phi measured over every week's days in the
 *     range. Under the floor, or with no difference that clears, last week's
 *     figure is printed plain or not at all: no arrow, no colour.
 *   - the best and worst slot, weekday x three-hour block. In one week that
 *     slot is ONE driver day, so the grid's two-night floor can never be met
 *     and is not pretended: it is a calendar tile's rule, GOOD_FLOOR_HOURS
 *     online and the plain Poisson interval on its good offers (99% shared
 *     over the slots that met it) clear of the range's own good per hour. Best is the highest marked above, worst
 *     the lowest marked below, and "none clear" where nothing is. The blocks
 *     are Advice's clock blocks on the driver's day, so Friday's 12-3am is
 *     the small hours after Friday evening and its 3-6am holds 4-6am Friday
 *     and 3-4am the next morning, both Friday's driver day.
 * Counts (hours, offers, takes) are printed beside last week's with no test:
 * a count is what it was — but like with like: a week still running beside
 * last week up to the same weekday and clock time, and a week before the
 * range began said to be part of one. A slot is one evening and is said so,
 * and is marked at 99% shared over the slots that met the floor (Bonferroni):
 * naming the best of seven at 99% each named one in 79% of no-effect weeks
 * once nights swing. Descriptive like every figure here.
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

  // advice.js is loaded first on every page that loads this one (journal.html
  // in its head) and required here in node: the 4am, the day keys and the
  // one quantile are its.
  var DAY_STARTS_AT = Advice.DAY_STARTS_AT;
  // The one 30: the places report's MIN_N reads it (see the header's table).
  var FLOOR = 30;
  var FLOOR_DAYS = 2;
  var CI_ALPHA = 0.01;
  // A day's or a week's point on a line: the fewest offers its median is drawn
  // from (under it the point is hollow and the band left out). Descriptive;
  // nothing is shaded by it. The one 10: the places report's DESC_MIN_N (its
  // DROP_MIN_N) and strategy.js's DIST_MIN_N read it, the floor under every
  // descriptive median and percentile in the three.
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
  var STATS = ['p50', 'p75', 'p90', 'goodRate', 'earned'];
  var STAT_P = { p50: 0.5, p75: 0.75, p90: 0.9 };
  var STAT_NAMES = { p50: 'median', p75: 'P75', p90: 'P90', goodRate: 'good/hr online', earned: 'earned/hr online' };
  // Two periods, B against A, cell by cell: each side's interval is drawn at
  // this level and a cell shaded only where the two do not overlap. For two
  // equal widths that is a 99% test of the difference (z = 2.576 / sqrt 2 =
  // 1.821 a side, two-sided 6.85%); for unequal widths it is stricter. See
  // the header, "B AGAINST A".
  var CMP_SIDE_ALPHA = 0.0685;
  // Month thirds are shaded only where each third holds days of at least
  // this many months: a day-of-month effect is one payday a month, so under
  // three months a third is one or two paydays and a weekday mix.
  var THIRDS_MONTHS = 3;
  // Good per hour online: the floor of a cell (hours on driver days), and of
  // a calendar tile (one day). See the header for the table they came from.
  // A clock-hour cell holds at most an hour a night — except the 1am hour
  // of the night the clocks go back (1 Nov 2026), which holds two — so 2
  // hours there is nearly always 2 nights, and the days half is what makes it
  // so on that night too; it is also what a week's figure needs, where two
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
  // 2 was F_GOOD, round one's "over its own target at the time", which
  // nothing read once the ruler took over (the header); it is left unused
  // rather than the bits above it moved down, so a packed answer from before
  // still reads the same.
  var F_OK = 1, F_SUSPECT = 4, F_CORRECTED = 8, F_UNREAD = 16, F_BOOST_KNOWN = 32, F_BOOST = 64,
      F_TAKEN = 128, F_REOFFER = 256;

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
      var known = Object.prototype.hasOwnProperty.call(o, 'boost');
      out.push({
        t: t, app: appCode(o.app),
        pay: ok ? o.pay : null,
        perHour: perHour,
        minutes: ok ? num(o.minutes) : null,
        miles: ok && !o.milesUncertain ? num(o.miles) : null,
        flags: (ok ? F_OK : 0)
          | (o.suspect ? F_SUSPECT : 0)
          | (c && typeof c.to === 'number' ? F_CORRECTED : 0)
          | (unread ? F_UNREAD : 0)
          | (known ? F_BOOST_KNOWN : 0)
          | (known && (typeof o.boost === 'number' ? o.boost > 0 : !!o.boost) ? F_BOOST : 0)
          | (o.accepted === true ? F_TAKEN : 0)
          // Round B: server.js's fold marks a card offered again (its
          // `reoffered`, absent otherwise); one bit, so the answer stays
          // numbers only.
          | (o.reoffered === true ? F_REOFFER : 0)
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

  // The driver's day of a moment, in the zone of whoever asks: 'YYYY-MM-DD';
  // and the Monday of a driver's day's week, as its key. advice.js's, the one
  // copy, still exported here under these names for the page and report_check.
  var dayKeyOf = Advice.dayKeyOf;
  var weekKeyOf = Advice.weekKeyOf;
  function dateOfKey(key) {
    var p = key.split('-').map(Number);
    return new Date(p[0], p[1] - 1, p[2], 12);
  }
  function addDays(key, n) {
    var d = dateOfKey(key);
    d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-'
      + String(d.getDate()).padStart(2, '0');
  }

  /* Rows back from columns, each given its day, week, weekday and hour on the
   * reader's own clock — the clock the page's day headers are on. */
  /* The day, week, month and weekday of a row are its driver day's, and
   * the rows come oldest first, so they are worked out once per driver day
   * and the clock hour once per hour (the reporting review's T5): a Date
   * and four string builds a row was 40 ms of 12,000 rows on a laptop and
   * four times that on the phone. A row outside the day or hour last seen
   * (or out of order) is worked out afresh, so the answer is the same. */
  function unpack(p) {
    var c = (p && p.cols) || {};
    var n = (c.t || []).length, out = new Array(n);
    var dLo = Infinity, dHi = -Infinity, day = null, week = null, month = null, dow = null;
    var hLo = Infinity, hHi = -Infinity, hour = null;
    for (var i = 0; i < n; i++) {
      var ms = c.t[i] * 1000;
      var f = c.flags[i] | 0;
      var pay = c.pay[i], mi = c.miles[i];
      if (!(ms >= dLo && ms < dHi)) {
        day = dayKeyOf(ms); week = weekKeyOf(day); month = day.slice(0, 7);
        var dd = dateOfKey(day);
        dow = dd.getDay();
        dLo = new Date(dd.getFullYear(), dd.getMonth(), dd.getDate(), DAY_STARTS_AT).getTime();
        dHi = new Date(dd.getFullYear(), dd.getMonth(), dd.getDate() + 1, DAY_STARTS_AT).getTime();
      }
      if (!(ms >= hLo && ms < hHi)) {
        var hd = new Date(ms);
        hour = hd.getHours();
        hLo = ms - (hd.getMinutes() * 60000 + hd.getSeconds() * 1000 + hd.getMilliseconds());
        hHi = hLo + 3600000;
      }
      out[i] = {
        t: ms, app: c.app[i] === 1 ? 'uber' : c.app[i] === 2 ? 'doordash' : null,
        pay: pay, perHour: c.perHour[i], minutes: c.minutes[i], miles: mi,
        perMile: pay !== null && mi !== null && mi >= 0.1 ? pay / mi : null,
        ok: !!(f & F_OK), suspect: !!(f & F_SUSPECT),
        corrected: !!(f & F_CORRECTED), unread: !!(f & F_UNREAD),
        boost: f & F_BOOST_KNOWN ? !!(f & F_BOOST) : null, taken: !!(f & F_TAKEN),
        reoffered: !!(f & F_REOFFER),
        day: day, week: week, month: month, dow: dow, hour: hour
      };
    }
    return out;
  }
  // rowsOf's own rows read the same way (the tests', and a caller with offers).
  function readRows(rows) { return unpack(pack(rows)); }

  /* --- the numbers -------------------------------------------------------- */

  // Numbers sorted in a Float64Array, by the engine's own numeric sort (the
  // reporting review's T3): every list sorted here is finite numbers
  // (valuesOf keeps no other), and a compare function per pair was most of
  // a quantile's cost. Indexed and measured like an array by everything here.
  function sorted(xs) {
    var a = new Float64Array(xs.length);
    for (var i = 0; i < xs.length; i++) a[i] = xs[i];
    return a.sort();
  }
  // The whole range's $/hr, sorted ONCE per set of rows: the ruler, every
  // view's reference quantile and the calendar each sorted all of it again.
  var rangeMemo = { rows: null, n: -1, s: null };
  function rangeSorted(rows) {
    if (rangeMemo.rows !== rows || rangeMemo.n !== rows.length) {
      rangeMemo = { rows: rows, n: rows.length, s: sorted(valuesOf(rows, 'perHour')) };
    }
    return rangeMemo.s;
  }
  // Linear between the two straddling values (R's type 7): advice.js's
  // quantile, which the page's percentile() is too.
  var q = Advice.quantile;
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

  /* The same interval widened by phi_q (the reporting review's S1). The
   * order-statistic interval treats every offer as its own draw, but a
   * night's offers move together: on a slow night the whole cell's spread
   * sits lower. Simulated on the owner's spread (the header's table,
   * "QUANTILES AND THE NIGHTS"), a 10% night-to-night swing in $/hr shaded
   * 11% of no-effect median cells and a 20% swing 33%. So the ranks are
   * taken at the effective n = n / phi_q — the count of offers a cell holds
   * once the nights' swing is allowed for — and scaled back onto the cell's
   * own sorted values, the lower down and the upper up, so the interval is
   * never narrower than the plain one. At phi_q = 1 it IS the plain one. */
  function quantCIw(s, p, alpha, phi) {
    var f = phi > 1 ? phi : 1;
    if (f === 1) return quantCI(s, p, alpha);
    var n = s.length, ne = Math.floor(n / f);
    if (ne < 1) return null;
    var r = quantRanks(ne, p, alpha);
    if (!(r[0] >= 1 && r[1] <= ne)) return null;
    var lo = Math.max(1, Math.floor(r[0] * n / ne)), hi = Math.min(n, Math.ceil(r[1] * n / ne));
    return [s[lo - 1], s[hi - 1]];
  }

  /* rho_q: how much a night's offers move together, measured off the
   * record as an intra-night correlation of "above the reference" (the same
   * figure the cell is shaded against). Each group (a cell, a week) is held
   * to its own share above, so a cell that truly sits higher moves its share
   * and not rho. Pearson's chi-square over the groups' nights has the
   * expectation sum n_i c_i (1 + (n_i - 1) rho), c_i = 1 - 2 n_i/N +
   * sum n_j^2 / N^2 (the share estimated from the group itself), and rho is
   * read off that by moments, between 0 and 1. `groups`: a list of groups,
   * each a list of its nights' $/hr lists. 0 where nothing can be measured.
   *
   * WHY A CORRELATION AND NOT ONE PHI (good per hour's form). A cell's
   * design effect is 1 + (m - 1) rho, m its offers a night: on the
   * simulated record a cell holds 13 to 85 offers a night, so one phi pooled
   * over the screen under-widened the busy cells and the P75 and P90 still
   * shaded 1.4-1.7% by chance at a 20% swing. Per cell, from rho, they hold
   * 1% (the header's table). */
  function qRho(groups, ref) {
    if (ref === null || ref === undefined) return 0;
    var S = 0, A = 0, B = 0;
    groups.forEach(function (g) {
      var N = 0, X = 0, N2 = 0, cnt = [];
      g.forEach(function (vals) {
        if (!vals.length) return;
        var x = 0;
        for (var i = 0; i < vals.length; i++) if (vals[i] > ref) x += 1;
        cnt.push([vals.length, x]); N += vals.length; X += x; N2 += vals.length * vals.length;
      });
      if (cnt.length < 2) return;
      var ph = X / N;
      if (!(ph > 0 && ph < 1)) return;
      cnt.forEach(function (c) {
        var e = c[0] * ph, ci = 1 - 2 * c[0] / N + N2 / (N * N);
        S += (c[1] - e) * (c[1] - e) / (ph * (1 - ph));
        A += c[0] * ci; B += c[0] * (c[0] - 1) * ci;
      });
    });
    // At most 1: a night's offers all moving as one, effective n the nights.
    return B > 0 ? Math.min(1, Math.max(0, (S - A) / B)) : 0;
  }
  // A group's phi_q from rho and its nights' offer counts: the design
  // effect 1 + (m - 1) rho, m = sum n^2 / sum n (unequal nights weighted as
  // a pooled share weights them).
  function qPhiOf(counts, rho) {
    if (!(rho > 0)) return 1;
    var n = 0, n2 = 0;
    counts.forEach(function (c) { n += c; n2 += c * c; });
    return n > 0 ? 1 + (n2 / n - 1) * rho : 1;
  }

  /* Shade a group's p-quantile against the same quantile of a reference:
   * 'above', 'below' or null, by the rule in the header. `days` is how many
   * driver days it rests on. Enough only where the floor holds AND the
   * interval exists; under either a cell is grey and shows its n. `phi`
   * (phi_q, where the caller measured one) widens the interval. */
  function shadeQ(vals, days, ref, p, minDays, phi) {
    var need = typeof minDays === 'number' ? minDays : FLOOR_DAYS;
    if (vals.length < FLOOR || days < need || ref === null) return { enough: false, shade: null, ci: null };
    var ci = quantCIw(sorted(vals), p, CI_ALPHA, phi);
    if (!ci) return { enough: false, shade: null, ci: null, noRanks: true };
    var shade = ci[0] > ref ? 'above' : ci[1] < ref ? 'below' : null;
    return { enough: true, shade: shade, ci: [r2(ci[0]), r2(ci[1])] };
  }

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
  function rateShade(k, hours, ref, phi, alpha) {
    if (!(hours > 0) || ref === null) return { shade: null, ci: null };
    var f = phi > 1 ? phi : 1, ci = poisCI(k / f, alpha || CI_ALPHA);
    var lo = ci[0] * f / hours, hi = ci[1] * f / hours;
    return { shade: lo > ref ? 'above' : hi < ref ? 'below' : null, ci: [r2(lo), r2(hi)] };
  }

  /* The gamma quantile: x with P(shape, x / scale) = p. */
  function gammaInv(p, shape, scale) {
    var top = shape + 20 * Math.sqrt(shape + 1) + 30;
    return scale * bisect(function (x) { return gammaP(shape, x); }, p, 0, top);
  }

  /* --- earned per hour online: a weighted Poisson sum ---------------------------
   *
   * The earned figure of a cell is a sum of takes, each weighted by its pay,
   * over hours. Its interval is Fay and Feuer's gamma interval for a weighted
   * Poisson sum (1997; the one used for age-standardised rates), with
   * Tiwari's (2006) mean weight in place of the largest for the upper end:
   * y = the sum, v = the sum of the squared weights, w = the range's mean
   * take; lower G(alpha/2; y^2/v, v/y), upper G(1 - alpha/2; (y+w)^2/(v+w^2),
   * (v+w^2)/(y+w)). With every weight 1 it is the Garwood interval poisCI
   * draws; with no take at all it is [0, 5.30 takes of w] at 99%, never
   * [0, 0]. Widened as good/hr is, by phi (v times phi), measured off the
   * takes' own night-to-night swing. Weights under 0 (a net take that paid
   * less than its miles cost) count as 0 in the interval only; the figure
   * printed is the true sum. SO A CELL HOLDING ONE IS NEVER SHADED (the
   * reporting review's S4, `clamped`): the interval is of a different sum
   * from the figure printed, and simulated it shaded a cell "above" at
   * $6.49/hr against a range of $11.80 (interval $12.61-$38.75, every
   * weight past the losers). Its figure is printed, grey, and said. Why not
   * the bootstrap over days the brief suggested: see the header, "EARNED
   * PER HOUR ONLINE". */
  function clampedOf(earned, y) { return earned < y - 1e-9; }
  function earnCI(y, v, wMean, phi, alpha) {
    var a = alpha || CI_ALPHA, f = phi > 1 ? phi : 1, w = wMean > 0 ? wMean : 0;
    var lo = y > 0 && v > 0 ? gammaInv(a / 2, y * y / (f * v), f * v / y) : 0;
    var hi = w > 0 || y > 0 ? gammaInv(1 - a / 2, (y + w) * (y + w) / (f * (v + w * w)), f * (v + w * w) / (y + w)) : 0;
    return [lo, hi];
  }
  function earnShade(y, v, hours, ref, wMean, phi, alpha) {
    if (!(hours > 0) || ref === null || !(wMean > 0)) return { shade: null, ci: null };
    var ci = earnCI(y, v, wMean, phi, alpha);
    var lo = ci[0] / hours, hi = ci[1] / hours;
    return { shade: lo > ref ? 'above' : hi < ref ? 'below' : null, ci: [r2(lo), r2(hi)] };
  }

  /* The regularized incomplete beta I_x(a, b) (Numerical Recipes' continued
   * fraction), for the ratio of two counts below. Real a and b, so an
   * effective count k/phi needs no rounding. */
  function betacf(a, b, x) {
    var qab = a + b, qap = a + 1, qam = a - 1, c = 1, d = 1 - qab * x / qap;
    if (Math.abs(d) < 1e-300) d = 1e-300;
    d = 1 / d;
    var h = d;
    for (var m = 1; m <= 300; m++) {
      var m2 = 2 * m, aa = m * (b - m) * x / ((qam + m2) * (a + m2));
      d = 1 + aa * d; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = 1 + aa / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d; h *= d * c;
      aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
      d = 1 + aa * d; if (Math.abs(d) < 1e-300) d = 1e-300;
      c = 1 + aa / c; if (Math.abs(c) < 1e-300) c = 1e-300;
      d = 1 / d;
      var del = d * c;
      h *= del;
      if (Math.abs(del - 1) < 1e-13) break;
    }
    return h;
  }
  function betaI(a, b, x) {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    var bt = Math.exp(lnGamma(a + b) - lnGamma(a) - lnGamma(b) + a * Math.log(x) + b * Math.log(1 - x));
    return x < (a + 1) / (a + b + 2) ? bt * betacf(a, b, x) / a : 1 - bt * betacf(b, a, 1 - x) / b;
  }
  /* Clopper-Pearson on a share x of n (both may be real): [lo, hi]. */
  function shareCI(x, n, alpha) {
    var lo = x > 0 ? bisect(function (p) { return betaI(x, n - x + 1, p); }, alpha / 2, 0, 1) : 0;
    var hi = x < n ? bisect(function (p) { return betaI(x + 1, n - x, p); }, 1 - alpha / 2, 0, 1) : 1;
    return [lo, hi];
  }

  /* --- the ruler --------------------------------------------------------------
   *
   * The top `top`% of the range's $/hr, as one dollar figure (to the cent the
   * rows are packed at, so "at or over $19.40" counts exactly what it says).
   * Over the money rows only, as every other figure. See the header: it is a
   * reading ruler and reaches nothing else.
   *
   * TIES AT THE CUT COUNT AS GOOD (the reporting review's S8, chosen over
   * breaking them): "good" is a dollar figure, and two offers at the same
   * $/hr are equally good, so the share called good can be over the top
   * X% where many offers sit exactly on the cut. `over` counts them, and the
   * page prints it ("1,240 of 5,800 offers"), so the share is never hidden.
   * Breaking ties by time or id would call one of two equal offers good. */
  function ruler(rows, top) {
    var t = TOPS.indexOf(Number(top)) >= 0 ? Number(top) : TOP_DEFAULT;
    var v = rangeSorted(rows);
    var cut = v.length ? r2(q(v, 1 - t / 100)) : null;
    var over = 0;
    if (cut !== null) for (var i = v.length - 1; i >= 0 && v[i] >= cut; i--) over += 1;
    return { top: t, cut: cut, n: v.length, over: over };
  }
  function isGood(r, cut) {
    return r.ok && typeof cut === 'number' && r.perHour !== null && r.perHour !== undefined && r.perHour >= cut;
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
  // One pass over each period's rows (the reporting review's T4): the five
  // metrics, the two apps' five, the quality, share and boost counts were
  // twenty-odd filters a period. The same figures.
  function periods(rows, by) {
    var g = groupBy(rows, function (r) { return by === 'week' ? r.week : r.day; });
    return g.keys.sort().map(function (k) {
      var list = g.by[k];
      var e = { key: k, n: list.length, counted: 0, metrics: {}, apps: {}, quality: null, share: null, boost: null };
      var vals = {}, appVals = { uber: {}, doordash: {} }, appN = { uber: 0, doordash: 0 };
      METRICS.forEach(function (m) { vals[m] = []; appVals.uber[m] = []; appVals.doordash[m] = []; });
      var counted = 0, sus = 0, cor = 0, unr = 0, bk = 0, by2 = 0;
      for (var i = 0; i < list.length; i++) {
        var r = list[i], av = r.app === 'uber' || r.app === 'doordash' ? appVals[r.app] : null;
        if (av) appN[r.app] += 1;
        if (r.ok) {
          counted += 1;
          for (var j = 0; j < METRICS.length; j++) {
            var v = r[METRICS[j]];
            if (v !== null && v !== undefined && isFinite(v)) { vals[METRICS[j]].push(v); if (av) av[METRICS[j]].push(v); }
          }
        }
        // Three counts that do not overlap: every "pay unread" row is suspect
        // too (server.js withPay), so `suspect` here is suspect for any OTHER
        // reason, and a strip stacking the three adds up to the offers it marks.
        if (r.suspect && !r.unread) sus += 1;
        if (r.corrected) cor += 1;
        if (r.unread) unr += 1;
        if (r.boost !== null && r.boost !== undefined) { bk += 1; if (r.boost) by2 += 1; }
      }
      METRICS.forEach(function (m) { e.metrics[m] = quarts(vals[m]); });
      e.counted = counted;
      APPS.forEach(function (a) {
        var ap = { n: appN[a] };
        METRICS.forEach(function (m) {
          var v = appVals[a][m];
          ap[m] = v.length >= DAY_MIN ? r2(q(sorted(v), 0.5)) : null;
          ap[m + 'N'] = v.length;
        });
        e.apps[a] = ap;
      });
      e.quality = { suspect: sus, corrected: cor, unread: unr };
      e.share = { uber: appN.uber, doordash: appN.doordash, unknown: list.length - appN.uber - appN.doordash };
      e.boost = bk ? { known: bk, yes: by2 } : null;
      return e;
    });
  }

  /* --- hours online, from the runs of scanning ------------------------------
   *
   * `runs` are [from, to] in ms: the offers page's own runs of scanning
   * (Advice.runs over Advice.usable, first card to last card), sent by the
   * server beside the rows. hoursBy credits a run to the driver day it
   * STARTED on — a run across 4am as one sitting, which is the Runs tab's
   * question. NO RATE ON THIS TAB READS IT ANY MORE (the reporting review,
   * Nov 2026): a rate is good offers over hours, and the cards are counted on
   * their own driver day, so a run from 1am to 7am Monday put its 4-7am cards
   * on Monday and all six hours on Sunday — Sunday read 0 good in 6 h, Monday
   * 19 good in no time, and the calendar's week column disagreed with the
   * week card's over the same week. Every rate takes onlineHoursBy instead.
   * Kept, exported, for a caller that asks the sitting's question. */
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
  // The pieces of the last few run lists asked for, by identity, length and
  // ends: a draw asks for the same runs' pieces a dozen times (T1/T3).
  // Nothing here writes to a piece, so the same object is handed back.
  var piecesMemo = [];
  function onlinePieces(runs) {
    var list = runs || [], n = list.length;
    var a0 = n ? list[0] && list[0][0] : null, b1 = n ? list[n - 1] && list[n - 1][1] : null;
    for (var mi = 0; mi < piecesMemo.length; mi++) {
      var m = piecesMemo[mi];
      if (m.runs === runs && m.n === n && m.a0 === a0 && m.b1 === b1) return m.out;
    }
    var res = piecesOf(runs);
    piecesMemo.unshift({ runs: runs, n: n, a0: a0, b1: b1, out: res });
    if (piecesMemo.length > 4) piecesMemo.length = 4;
    return res;
  }
  function piecesOf(runs) {
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
  /* The one hours rule for a rate (F1 of the reporting review): the slices'
   * own hours summed by the driver day each slice falls on — or its week
   * (Monday 4am) or month — so hours and cards are on the same day by
   * construction, and a day, a week column, a month and the week card are
   * each the pool of the same slices the grid and the timeline pool. The 1
   * Nov night counts its real 9 hours (1am happens twice), split at 4am. */
  function onlineHoursBy(runs, by) {
    var pieces = onlinePieces(runs), out = Object.create(null);
    Object.keys(pieces).forEach(function (k) {
      var p = pieces[k], key = by === 'week' ? weekKeyOf(p.day) : by === 'month' ? p.month : p.day;
      out[key] = (out[key] || 0) + p.hours;
    });
    return out;
  }

  /* --- round three: one table of driver-day x clock-hour slices ----------------
   *
   * Every cell this tab draws — weekday x hour, a timeline square, an hour of
   * the hour chart, a month third — is a pool of these: one per driver day
   * and clock hour that held a minute online or a card. Each slice carries
   * its minutes online (onlinePieces), its rows, its good offers (the ruler),
   * its takes and what they paid. A row in an hour with no minute online (a
   * run of one card is zero long) still makes its slice, with 0 hours, so it
   * is counted where it came.
   *
   * WHAT "EARNED" IS. The pay of the offers the driver ticked taken — the
   * taken bit only; silence is never an accept, so this is a floor on what
   * was taken — over every minute online in the cell, waiting included. The
   * CARD's pay, not what the app paid: the Money tab matches trips to cards,
   * and that match lives on the page over /api/earnings, with offer ids this
   * answer does not carry (no id leaves in /api/trends). A take whose pay
   * was not trusted (suspect, "pay unread") is counted as `unpaid` and adds
   * nothing. NET subtracts its miles times ONE cost per mile — the rig's
   * own setting, as /api/trends reads it off the newest offer (server.js
   * trendsOut) — over the whole range, so an old week and a new one are
   * costed alike, as the ruler is one line. A take with no miles read has
   * nothing subtracted and is counted as `noMiles`. With no setting known
   * there is no net, and the page says so rather than choosing a figure. */
  function takeOf(r, cpm) {
    if (!r.taken) return null;
    if (!r.ok || r.pay === null || r.pay === undefined) return { unpaid: true };
    var cost = 0, noMiles = false;
    if (typeof cpm === 'number') {
      if (r.miles === null || r.miles === undefined) noMiles = true; else cost = r.miles * cpm;
    }
    return { e: r.pay - cost, noMiles: noMiles };
  }

  function emptySlice(day, hour) {
    return { day: day, dow: dateOfKey(day).getDay(), hour: hour, month: day.slice(0, 7), week: weekKeyOf(day),
             hours: 0, rows: [], good: 0, takes: 0, earned: 0, y: 0, v: 0, unpaid: 0, noMiles: 0 };
  }
  function addTake(s, r, cpm) {
    var tk = takeOf(r, cpm);
    if (!tk) return;
    if (tk.unpaid) { s.unpaid += 1; return; }
    s.takes += 1;
    s.earned += tk.e;
    var w = tk.e > 0 ? tk.e : 0;
    s.y += w;
    s.v += w * w;
    if (tk.noMiles) s.noMiles += 1;
  }
  /* The table: { slices: { 'day|hour': slice }, wMean, totals }. `opts`:
   * cut (the ruler), cpm (a number for net, else gross), `keep` (a filter on
   * a slice's { day, dow, month }: a period, weekdays). */
  function sliceTable(rows, runs, opts) {
    opts = opts || {};
    var cut = opts.cut, cpm = typeof opts.cpm === 'number' ? opts.cpm : null, keep = opts.keep;
    var pieces = onlinePieces(runs), out = Object.create(null);
    Object.keys(pieces).forEach(function (k) {
      var p = pieces[k];
      if (keep && !keep(p)) return;
      var s = out[k] = emptySlice(p.day, p.hour);
      s.hours = p.hours;
    });
    var tot = { hours: 0, good: 0, takes: 0, earned: 0, wSum: 0, offers: 0 };
    rows.forEach(function (r) {
      if (keep && !keep(r)) return;
      var k = r.day + '|' + r.hour;
      var s = out[k] || (out[k] = emptySlice(r.day, r.hour));
      s.rows.push(r);
      if (isGood(r, cut)) s.good += 1;
      addTake(s, r, cpm);
    });
    Object.keys(out).forEach(function (k) {
      var s = out[k];
      tot.hours += s.hours; tot.good += s.good; tot.takes += s.takes; tot.earned += s.earned;
      tot.offers += s.rows.length; tot.wSum += s.y;
    });
    return { slices: out, cut: cut, cpm: cpm, net: cpm !== null,
             wMean: tot.takes ? tot.wSum / tot.takes : null,
             refRate: tot.hours > 0 ? tot.good / tot.hours : null,
             refEarn: tot.hours > 0 ? tot.earned / tot.hours : null,
             totals: tot };
  }
  function sliceList(tab) { return Object.keys(tab.slices).map(function (k) { return tab.slices[k]; }); }

  /* phi for a grouping: each group's slices, for the good count and for the
   * takes. Measured as the grid's is, over the cells' own nights. */
  function phis(groups, qref) {
    return {
      good: dispersion(groups.map(function (g) { return g.map(function (s) { return { k: s.good, h: s.hours }; }); })),
      takes: dispersion(groups.map(function (g) { return g.map(function (s) { return { k: s.takes, h: s.hours }; }); })),
      // A quantile's rho_q, only where the stat is one (qref: the range's
      // figure). Each slice is one night of its group.
      q: qref === null || qref === undefined ? 0
        : qRho(groups.map(function (g) { return g.map(function (s) { return valuesOf(s.rows, 'perHour'); }); }), qref)
    };
  }
  function isQ(stat) { return stat !== 'goodRate' && stat !== 'earned'; }

  /* One cell from its slices, in the stat asked, by the grid's rules: a
   * quantile shaded by shadeQ at FLOOR offers on `minDays` driver days; good
   * per hour and earned per hour at `floorHours` online on `floorDays` days,
   * widened by phi. Every cell says its hours online, the days they rest on,
   * and `off` where it has neither a minute online nor a card: the rig was
   * not scanning, which is not the same as a quiet hour. `waitMin`: minutes
   * online per good offer (60 / good per hour), only at the good floor;
   * `waitNone` where that much time held no good offer at all. */
  function poolCell(sl, ctx) {
    var stat = ctx.stat, list = [], hrs = 0, onDays = 0, good = 0, takes = 0, earned = 0, y = 0, v = 0, unpaid = 0,
        noMiles = 0, days = Object.create(null);
    sl.forEach(function (s) {
      for (var i = 0; i < s.rows.length; i++) list.push(s.rows[i]);
      if (s.hours > 0) { hrs += s.hours; if (!days[s.day]) { days[s.day] = 1; onDays += 1; } }
      good += s.good; takes += s.takes; earned += s.earned; y += s.y; v += s.v; unpaid += s.unpaid;
      noMiles += s.noMiles;
    });
    var vals = valuesOf(list, 'perHour'), srt = sorted(vals);
    var okDays = daysIn(list.filter(function (r) { return r.ok; }));
    var fH = typeof ctx.floorHours === 'number' ? ctx.floorHours : GOOD_FLOOR_HOURS;
    var fD = typeof ctx.floorDays === 'number' ? ctx.floorDays : GOOD_FLOOR_DAYS;
    var timeOk = hrs >= fH && onDays >= fD;
    var e = { n: vals.length, offers: list.length, days: okDays, hours: r2(hrs), onlineDays: onDays,
              good: good, takes: takes, earned: r2(earned), unpaid: unpaid, noMiles: noMiles,
              median: vals.length ? r2(q(srt, 0.5)) : null,
              off: hrs === 0 && list.length === 0,
              waitMin: timeOk && good > 0 ? Math.round(60 * hrs / good) : null,
              waitNone: timeOk && good === 0, timeOk: timeOk };
    if (stat === 'goodRate') {
      e.days = onDays;
      e.value = hrs > 0 ? r2(good / hrs) : null;
      e.enough = timeOk;
      var rs = timeOk ? rateShade(good, hrs, ctx.ref, ctx.phi ? ctx.phi.good : 1, ctx.alpha) : { shade: null, ci: null };
      e.shade = rs.shade; e.ci = rs.ci;
    } else if (stat === 'earned') {
      e.days = onDays;
      e.value = hrs > 0 ? r2(earned / hrs) : null;
      e.enough = timeOk;
      e.clamped = clampedOf(earned, y);
      var es = timeOk && !e.clamped ? earnShade(y, v, hrs, ctx.ref, ctx.wMean, ctx.phi ? ctx.phi.takes : 1, ctx.alpha)
        : { shade: null, ci: null };
      e.shade = es.shade; e.ci = es.ci;
    } else {
      var p = STAT_P[stat] || 0.5;
      e.value = vals.length ? r2(q(srt, p)) : null;
      var rho = ctx.phi ? ctx.phi.q : 0, perDay = Object.create(null);
      if (rho > 0) list.forEach(function (r) { if (r.ok && r.perHour !== null && r.perHour !== undefined) perDay[r.day] = (perDay[r.day] || 0) + 1; });
      e.phiQ = rho > 0 ? r2(qPhiOf(Object.keys(perDay).map(function (k) { return perDay[k]; }), rho)) : 1;
      var sh = shadeQ(vals, okDays, ctx.ref, p, ctx.minDays, e.phiQ);
      e.enough = sh.enough; e.shade = sh.shade; e.ci = sh.ci; e.noRanks = !!sh.noRanks;
    }
    e.vals = vals;
    e.wy = y; e.wv = v; e.clamped = clampedOf(earned, y);
    return e;
  }
  // The reference a cell is shaded against: the same figure over the range.
  function refOf(stat, rows, tab) {
    if (stat === 'goodRate') return tab.refRate;
    if (stat === 'earned') return tab.refEarn;
    var all = rangeSorted(rows);
    return all.length ? q(all, STAT_P[stat] || 0.5) : null;
  }
  function statOf(s) { return STATS.indexOf(s) >= 0 ? s : 'p50'; }
  function cpmOf(opts) { return opts && opts.net && typeof opts.costPerMile === 'number' ? opts.costPerMile : null; }

  /* Good offers per hour online, by day or week. "Good" is the ruler's cut,
   * which the page always gives. There was a fallback to each row's own
   * target at the time (round one's flag) when none was given, and the daily
   * CSV took it too, so a file whose header said `good_from_per_hour` could
   * count good by targets (the reporting code's second review): with no cut
   * nothing is good, as no line was drawn. Descriptive: it feeds nothing. */
  function goodPerHour(rows, runs, by, cut) {
    var hours = onlineHoursBy(runs, by);
    var g = groupBy(rows, function (r) { return by === 'week' ? r.week : r.day; });
    return g.keys.sort().map(function (k) {
      var list = g.by[k], hrs = hours[k] || 0;
      var good = list.filter(function (r) { return isGood(r, cut); }).length;
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
   * GOOD_FLOOR_HOURS on GOOD_FLOOR_DAYS. Round three: `earned` is the takes'
   * pay (net with `net` and `costPerMile`) over those same hours, at the
   * same floor; nothing on the hour chart is shaded. */
  function hourly(rows, opts) {
    opts = opts || {};
    var metric = opts.metric || 'perHour';
    var stat = statOf(opts.stat);
    var cpm = cpmOf(opts);
    // `period` (round three, compare mode): only the rows and the minutes
    // online of that period, as inPeriod reads it.
    function keepDay(x) {
      if (opts.month && x.month !== opts.month) return false;
      if (opts.period && !inPeriod(x, opts.period)) return false;
      if (opts.days === 'weekend') return x.dow === 0 || x.dow === 6;
      if (opts.days === 'weekday') return x.dow > 0 && x.dow < 6;
      return true;
    }
    var pick = rows.filter(keepDay);
    var by = groupBy(pick, function (r) { return r.hour; }).by;
    var online = Object.create(null);
    if (stat === 'goodRate' || stat === 'earned') {
      var pieces = onlinePieces(opts.runs);
      Object.keys(pieces).forEach(function (k) {
        var p = pieces[k];
        if (!keepDay(p)) return;
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
      if (stat === 'goodRate' || stat === 'earned') {
        var on = online[h] || { hours: 0, days: 0 };
        e.good = list.filter(function (r) { return isGood(r, opts.cut); }).length;
        e.hours = r2(on.hours);
        e.onlineDays = on.days;
        e.enough = on.hours >= GOOD_FLOOR_HOURS && on.days >= GOOD_FLOOR_DAYS;
        if (stat === 'goodRate') {
          e.value = on.hours > 0 ? r2(e.good / on.hours) : null;
        } else {
          var sl = emptySlice('2000-01-01', h);
          list.forEach(function (r) { addTake(sl, r, cpm); });
          e.takes = sl.takes; e.earned = r2(sl.earned); e.unpaid = sl.unpaid; e.noMiles = sl.noMiles;
          e.value = on.hours > 0 ? r2(sl.earned / on.hours) : null;
        }
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
   * the figure of the stat asked. Round three: built on the slice table
   * (poolCell), so every cell also carries its hours online, `off`, the wait
   * for a good offer and its takes; `earned` (with `net` and `costPerMile`)
   * is earned per hour online, shaded by earnShade. */
  function grid(rows, opts) {
    opts = opts || {};
    var stat = statOf(opts.stat);
    var tab = opts.table || sliceTable(rows, opts.runs, { cut: opts.cut, cpm: cpmOf(opts), keep: opts.keep });
    var byCell = Object.create(null);
    sliceList(tab).forEach(function (s) { (byCell[s.dow * 24 + s.hour] || (byCell[s.dow * 24 + s.hour] = [])).push(s); });
    var ref = refOf(stat, opts.keep ? rows.filter(opts.keep) : rows, tab);
    var ph = phis(Object.keys(byCell).map(function (c) { return byCell[c]; }), isQ(stat) ? ref : null);
    var ctx = { stat: stat, ref: ref, phi: ph, wMean: tab.wMean, minDays: FLOOR_DAYS };
    var cells = [];
    for (var d = 1; d <= 7; d++) {
      var dow = d % 7;                              // Monday first, Sunday last
      HOUR_ORDER.forEach(function (h) {
        var e = poolCell(byCell[dow * 24 + h] || [], ctx);
        e.dow = dow; e.hour = h;
        delete e.vals; delete e.wy; delete e.wv;
        cells.push(e);
      });
    }
    var out = { stat: stat, ref: ref === null ? null : r2(ref), floor: FLOOR, floorDays: FLOOR_DAYS, alpha: CI_ALPHA,
                cells: cells, cut: opts.cut === undefined ? null : opts.cut, net: tab.net, cpm: tab.cpm };
    if (stat === 'goodRate' || stat === 'earned') {
      out.phi = Math.round((stat === 'goodRate' ? ph.good : ph.takes) * 100) / 100;
      out.floorHours = GOOD_FLOOR_HOURS; out.floorDays = GOOD_FLOOR_DAYS;
    } else out.rhoQ = Math.round(ph.q * 1000) / 1000;
    if (stat === 'earned') {
      out.wMean = tab.wMean === null ? null : r2(tab.wMean);
      out.takes = tab.totals.takes;
      out.unpaid = sliceList(tab).reduce(function (a, s) { return a + s.unpaid; }, 0);
      out.noMiles = sliceList(tab).reduce(function (a, s) { return a + s.noMiles; }, 0);
      out.clamped = cells.filter(function (c) { return c.clamped && c.enough; }).length;
    }
    return out;
  }

  /* Good offers by app, pooled over the weekdays, by clock hour: the share
   * from Uber and from DoorDash and the counts (good offers whose app is not
   * known counted apart). Descriptive; printed only from APP_SHARE_MIN good
   * offers an hour, under it the count alone. */
  var APP_SHARE_MIN = 10;
  function goodAppShare(rows, cut) {
    var by = Object.create(null);
    rows.forEach(function (r) {
      if (!isGood(r, cut)) return;
      var e = by[r.hour] || (by[r.hour] = { uber: 0, doordash: 0, unknown: 0 });
      if (r.app === 'uber') e.uber += 1; else if (r.app === 'doordash') e.doordash += 1; else e.unknown += 1;
    });
    return HOUR_ORDER.map(function (h) {
      var e = by[h] || { uber: 0, doordash: 0, unknown: 0 }, known = e.uber + e.doordash;
      return { hour: h, uber: e.uber, doordash: e.doordash, unknown: e.unknown, good: known + e.unknown,
               enough: known >= APP_SHARE_MIN, uberShare: known ? r2(e.uber / known) : null };
    });
  }

  /* --- the calendar ----------------------------------------------------------
   *
   * A tile a driver day: its median $/hr and its offers per hour online, shaded
   * by the grid's own rule against the window's median (one day is one day, so
   * the two-day half of the floor does not apply to a tile). */
  /* Round two (the owner: "make comparing over time easy"): `opts.stat` and
   * `opts.cut` as the grid's, so a tile reads the same figure as the grid and
   * is counted against the same fixed ruler. A day's goodRate is its good
   * offers over its hours online (onlineHoursBy: the slices of every run on
   * that driver day, so a run across 4am puts its small hours on the night
   * before, where their cards are counted too), shaded by the plain
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
    var stat = statOf(opts.stat);
    var p = STAT_P[stat] || 0.5, cut = opts.cut, cpm = cpmOf(opts);
    var all = rangeSorted(rows);
    var refQ = all.length ? q(all, p) : null;
    var hours = onlineHoursBy(runs, 'day');
    var totalH = 0, totalK = 0;
    Object.keys(hours).forEach(function (k) { totalH += hours[k]; });
    rows.forEach(function (r) { if (isGood(r, cut)) totalK += 1; });
    // Earned per hour online, a tile at a time (round three): every take of
    // the day over the day's hours, the same hours good/hr uses.
    var dayTakes = Object.create(null), tk = emptySlice('2000-01-01', 0);
    rows.forEach(function (r) {
      var s = dayTakes[r.day] || (dayTakes[r.day] = emptySlice(r.day, 0));
      addTake(s, r, cpm); addTake(tk, r, cpm);
    });
    var wMean = tk.takes ? tk.y / tk.takes : null;
    var refRate = stat === 'goodRate' && totalH > 0 ? totalK / totalH
      : stat === 'earned' && totalH > 0 ? tk.earned / totalH : null;
    var ref = stat === 'goodRate' || stat === 'earned' ? refRate : refQ;
    var g = groupBy(rows, function (r) { return r.day; });
    var refMed = all.length ? q(all, 0.5) : null;
    var days = g.keys.sort().map(function (k) {
      var list = g.by[k];
      var v = valuesOf(list, 'perHour'), s = sorted(v);
      var hrs = hours[k] || 0;
      var good = list.filter(function (r) { return isGood(r, cut); }).length;
      var dt = dayTakes[k];
      var e = { day: k, dow: dateOfKey(k).getDay(), week: weekKeyOf(k), n: list.length, counted: v.length,
                median: v.length ? r2(q(s, 0.5)) : null, good: good,
                hours: r2(hrs), perOnlineHour: hrs > 0 ? r2(list.length / hrs) : null,
                takes: dt.takes, earned: r2(dt.earned), unpaid: dt.unpaid,
                // A good offer about every so many minutes online: a tile's
                // own floor (GOOD_FLOOR_HOURS, one day), or none said.
                waitMin: hrs >= GOOD_FLOOR_HOURS && good > 0 ? Math.round(60 * hrs / good) : null,
                waitNone: hrs >= GOOD_FLOOR_HOURS && good === 0 };
      if (stat === 'earned') {
        e.value = hrs > 0 ? r2(dt.earned / hrs) : null;
        e.enough = hrs >= GOOD_FLOOR_HOURS;
        e.clamped = clampedOf(dt.earned, dt.y);
        e.shade = e.enough && !e.clamped ? earnShade(dt.y, dt.v, hrs, refRate, wMean, 1).shade : null;
      } else if (stat === 'goodRate') {
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
        if (stat === 'goodRate' || stat === 'earned') {
          var wh = 0, wg = 0, pcs = [], wt = emptySlice(wk, 0);
          keys.forEach(function (dk) {
            var d = byDay[dk], h = hours[dk] || 0, dtk = dayTakes[dk];
            wh += h;
            if (d) wg += d.good;
            if (dtk) { wt.takes += dtk.takes; wt.earned += dtk.earned; wt.y += dtk.y; wt.v += dtk.v; }
            if (h > 0) pcs.push({ k: stat === 'earned' ? (dtk ? dtk.takes : 0) : (d ? d.good : 0), h: h });
          });
          dayGroups.push(pcs);
          w.good = wg; w.hours = r2(wh); w.onlineDays = pcs.length;
          w.takes = wt.takes; w.earned = r2(wt.earned); w.y = wt.y; w.v = wt.v;
          w.value = wh > 0 ? r2((stat === 'earned' ? wt.earned : wg) / wh) : null;
          w.enough = wh >= GOOD_FLOOR_HOURS && pcs.length >= GOOD_FLOOR_DAYS;
        } else {
          w.counted = wv.length;
          w.value = wv.length ? r2(q(sorted(wv), p)) : null;
          // Shaded below, once phi_q over every week's days is known.
          w.wv = wv; w.wdays = wdays;
          var gd = groupBy(wl, function (r) { return r.day; });
          dayGroups.push(gd.keys.map(function (k) { return valuesOf(gd.by[k], 'perHour'); }));
        }
        weeks.push(w);
        wk = addDays(wk, 7);
      }
      if (isQ(stat)) {
        var qrho = qRho(dayGroups, refQ);
        weeks.forEach(function (w, wi) {
          var ws = shadeQ(w.wv, w.wdays, refQ, p, FLOOR_DAYS,
                          qPhiOf(dayGroups[wi].map(function (v) { return v.length; }), qrho));
          w.enough = ws.enough; w.shade = ws.shade;
          delete w.wv; delete w.wdays;
        });
      }
      if (stat === 'goodRate' || stat === 'earned') {
        var phi = dispersion(dayGroups);
        weeks.forEach(function (w) {
          w.clamped = stat === 'earned' && clampedOf(w.earned, w.y);
          w.shade = !w.enough || w.clamped ? null : stat === 'earned' ? earnShade(w.y, w.v, w.hours, refRate, wMean, phi).shade
            : rateShade(w.good, w.hours, refRate, phi).shade;
          delete w.y; delete w.v;
        });
      }
    }
    return { stat: stat, ref: ref === null ? null : r2(ref), refMedian: r2(refMed), floor: FLOOR,
             floorHours: GOOD_FLOOR_HOURS, cut: cut === undefined ? null : cut, net: cpm !== null,
             days: days, weeks: weeks, months: monthFigures(rows, runs, stat, cut, cpm) };
  }

  /* The newest month in the rows so far against the whole month before it,
   * in the stat asked, each with its n: offers counted for a quantile, good
   * offers and hours online for goodRate. Null where the range holds nothing
   * of the month before (a 7- or 30-day range early in a month). */
  function monthFigures(rows, runs, stat, cut, cpm) {
    var mo = monthsOf(rows);
    if (!mo) return null;
    var hours = onlineHoursBy(runs, 'month');
    function side(m) {
      var list = rows.filter(function (r) { return r.month === m; });
      var e = { month: m, offers: list.length, days: daysIn(list) };
      if (!list.length) { e.value = null; e.n = 0; return e; }
      if (stat === 'goodRate' || stat === 'earned') {
        var h = hours[m] || 0;
        e.good = list.filter(function (r) { return isGood(r, cut); }).length;
        e.hours = r2(h); e.n = e.good;
        e.value = h > 0 ? r2(e.good / h) : null;
        if (stat === 'earned') {
          var sl = emptySlice(m + '-01', 0);
          list.forEach(function (r) { addTake(sl, r, cpm); });
          e.takes = sl.takes; e.earned = r2(sl.earned); e.n = sl.takes;
          e.value = h > 0 ? r2(sl.earned / h) : null;
        }
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
  /* Round three: `dow` may be null (any weekday) and `opts.from` / `opts.to`
   * (driver-day keys, inclusive) narrow it to dates — a timeline square is
   * one date, a week or a month at one clock hour. `stat` 'earned' reads the
   * takes' pay over the hours (`opts.net` with `opts.costPerMile`, as the
   * grid). It also says how long a good offer took to come (`waitMin`, at the
   * good floor of GOOD_FLOOR_HOURS on GOOD_FLOOR_DAYS days, or of the hours
   * alone for one date) and which app the good offers came from. */
  function cellDetail(rows, runs, dow, hour, opts) {
    opts = opts || {};
    var stat = statOf(opts.stat), cut = opts.cut, cpm = cpmOf(opts);
    var p = STAT_P[stat] || 0.5;
    // Round B: a window from the overview is several weekdays and hours at
    // once — `dow` and `hour` may each be a list — and is looked at in the
    // same panel, by the same sums, as one cell.
    var dows = Array.isArray(dow) ? dow : null, hours = Array.isArray(hour) ? hour : null;
    function inCell(x) {
      return (dows ? dows.indexOf(x.dow) >= 0 : dow === null || dow === undefined || x.dow === dow)
        && (hours ? hours.indexOf(x.hour) >= 0 : x.hour === hour)
        && (!opts.from || x.day >= opts.from) && (!opts.to || x.day <= opts.to);
    }
    var list = rows.filter(inCell);
    var money = list.filter(function (r) { return r.ok && r.perHour !== null && r.perHour !== undefined; });
    var pieces = onlinePieces(runs), hoursByWeek = Object.create(null), hrs = 0, onDays = Object.create(null);
    Object.keys(pieces).forEach(function (k) {
      var pc = pieces[k];
      if (!inCell(pc)) return;
      hrs += pc.hours;
      onDays[pc.day] = 1;
      var wk = weekKeyOf(pc.day);
      hoursByWeek[wk] = (hoursByWeek[wk] || 0) + pc.hours;
    });
    function earnedOf(sub) {
      var sl = emptySlice('2000-01-01', hours ? hours[0] : hour);
      sub.forEach(function (r) { addTake(sl, r, cpm); });
      return sl;
    }
    function figure(sub, h) {
      if (stat === 'goodRate') {
        var gd = sub.filter(function (r) { return isGood(r, cut); }).length;
        return h > 0 ? r2(gd / h) : null;
      }
      if (stat === 'earned') return h > 0 ? r2(earnedOf(sub).earned / h) : null;
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
    var nOnDays = Object.keys(onDays).length;
    var oneDate = !!opts.from && opts.from === opts.to;
    var good = list.filter(function (r) { return isGood(r, cut); }).length;
    var timeOk = hrs >= GOOD_FLOOR_HOURS && (oneDate || nOnDays >= GOOD_FLOOR_DAYS);
    var ek = earnedOf(list);
    var goodApps = { uber: apps.uber.good, doordash: apps.doordash.good };
    goodApps.unknown = good - goodApps.uber - goodApps.doordash;
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
      dow: dow === undefined ? null : dow, hour: hour, from: opts.from || null, to: opts.to || null,
      stat: stat, cut: typeof cut === 'number' ? cut : null, net: cpm !== null,
      offers: list.length, n: all.length, days: daysIn(money), hours: r2(hrs), onlineDays: nOnDays,
      good: good,
      taken: list.filter(function (r) { return r.taken; }).length,
      takes: ek.takes, earned: r2(ek.earned), unpaid: ek.unpaid, noMiles: ek.noMiles,
      earnedRate: hrs > 0 ? r2(ek.earned / hrs) : null,
      waitMin: timeOk && good > 0 ? Math.round(60 * hrs / good) : null, waitNone: timeOk && good === 0,
      timeOk: timeOk, goodApps: goodApps,
      off: hrs === 0 && list.length === 0,
      value: figure(list, hrs),
      p50: r2(q(all, 0.5)), p75: r2(q(all, 0.75)), p90: r2(q(all, 0.9)),
      dots: money.map(function (r) { return [r.perHour, r.taken ? 1 : 0, appCode(r.app)]; }),
      apps: apps, best: best, weeks: weeks
    };
  }

  /* --- the hour x date timeline ---------------------------------------------------
   *
   * Rows are driver days (or weeks, Monday 4am to Monday 4am, or months by
   * driver day), NEWEST FIRST — the night a driver asks about is last night,
   * and on a phone it should be the first row, not the ninetieth; columns
   * the 24 clock hours, 4am first. Every period from the first to the last is
   * a row, a week off included, so a gap is a gap. Each square is a pool of
   * the day-hour slices in it, by the grid's own rules (poolCell, the range's
   * own figure as the reference, phi over the squares' nights) — so one
   * day-hour, which can hold neither 30 offers on 2 days nor 2 hours on 2
   * days, is never shaded: it is grey with its n, which is what one hour of
   * one night can honestly say. Weeks and months pool enough to shade. */
  function periodKey(by, day) { return by === 'week' ? weekKeyOf(day) : by === 'month' ? day.slice(0, 7) : day; }
  function periodSpan(by, key) {
    if (by === 'week') return { from: key, to: addDays(key, 6) };
    if (by === 'month') {
      var y = Number(key.slice(0, 4)), m = Number(key.slice(5, 7));
      var last = new Date(y, m, 0, 12).getDate();
      return { from: key + '-01', to: key + '-' + String(last).padStart(2, '0') };
    }
    return { from: key, to: key };
  }
  function nextKey(by, key) {
    if (by === 'week') return addDays(key, 7);
    if (by === 'month') {
      var y = Number(key.slice(0, 4)), m = Number(key.slice(5, 7)) + 1;
      if (m > 12) { m = 1; y += 1; }
      return y + '-' + String(m).padStart(2, '0');
    }
    return addDays(key, 1);
  }
  function timeline(rows, runs, opts) {
    opts = opts || {};
    var stat = statOf(opts.stat), by = opts.by === 'week' || opts.by === 'month' ? opts.by : 'day';
    var tab = opts.table || sliceTable(rows, runs, { cut: opts.cut, cpm: cpmOf(opts) });
    var list = sliceList(tab);
    if (!list.length) return { by: by, stat: stat, ref: null, rows: [], firstCol: -1 };
    var first = null, last = null, groups = Object.create(null);
    list.forEach(function (sl) {
      if (first === null || sl.day < first) first = sl.day;
      if (last === null || sl.day > last) last = sl.day;
      var k = periodKey(by, sl.day) + '|' + sl.hour;
      (groups[k] || (groups[k] = [])).push(sl);
    });
    var ref = refOf(stat, rows, tab);
    var ph = phis(Object.keys(groups).map(function (k) { return groups[k]; }), isQ(stat) ? ref : null);
    var ctx = { stat: stat, ref: ref, phi: ph, wMean: tab.wMean, minDays: FLOOR_DAYS };
    var out = [], firstCol = -1;
    for (var k = periodKey(by, first), guard = 0; k <= periodKey(by, last) && guard < 5000; k = nextKey(by, k), guard++) {
      var span = periodSpan(by, k), hrs = 0, offers = 0;
      var cells = HOUR_ORDER.map(function (h, col) {
        var e = poolCell(groups[k + '|' + h] || [], ctx);
        delete e.vals; delete e.wy; delete e.wv;
        e.hour = h;
        hrs += e.hours; offers += e.offers;
        if (!e.off && (firstCol < 0 || col < firstCol)) firstCol = col;
        return e;
      });
      out.push({ key: k, from: span.from, to: span.to, hours: r2(hrs), offers: offers, off: hrs === 0 && offers === 0,
                 cells: cells });
    }
    out.reverse();
    return { by: by, stat: stat, ref: ref === null ? null : r2(ref), net: tab.net, newestFirst: true,
             phi: Math.round((stat === 'earned' ? ph.takes : ph.good) * 100) / 100,
             rhoQ: isQ(stat) ? Math.round(ph.q * 1000) / 1000 : null, rows: out, firstCol: firstCol };
  }

  /* --- B against A, cell by cell ------------------------------------------------
   *
   * Two periods (inPeriod's { from, to }), each pooled into the weekday x hour
   * grid by poolCell, and per cell B's figure minus A's. Shaded only where
   * both sides meet the grid's floor and the difference is clear at 99%:
   *   - a quantile: each side's order-statistic interval at CMP_SIDE_ALPHA
   *     (6.85%), shaded where the two do not overlap;
   *   - good per hour: the ratio of two Poisson rates, exactly — given the
   *     cell's good offers in both, B's share of them is binomial with p0 =
   *     B's hours over both under no difference — on the effective counts
   *     k/phi (phi over both periods' nights), Clopper-Pearson at 99%;
   *   - earned per hour: each side's weighted-Poisson interval (earnCI, phi
   *     over the takes) at CMP_SIDE_ALPHA, shaded where they do not overlap.
   * `diff` is B - A; `shade` is 'above' where B is the higher, 'below' where
   * lower. Simulated nulls are in the header. */
  function gridCompare(rows, runs, a, b, opts) {
    opts = opts || {};
    var stat = statOf(opts.stat), cpm = cpmOf(opts), p = STAT_P[stat] || 0.5;
    function side(per) {
      var tab = sliceTable(rows, runs, { cut: opts.cut, cpm: cpm, keep: function (x) { return inPeriod(x, per); } });
      var byCell = Object.create(null);
      sliceList(tab).forEach(function (s) { (byCell[s.dow * 24 + s.hour] || (byCell[s.dow * 24 + s.hour] = [])).push(s); });
      return { tab: tab, byCell: byCell };
    }
    var A = side(a), B = side(b);
    var groups = [];
    [A, B].forEach(function (S) { Object.keys(S.byCell).forEach(function (c) { groups.push(S.byCell[c]); }); });
    var tk = A.tab.totals.takes + B.tab.totals.takes;
    var wMean = tk ? (A.tab.totals.wSum + B.tab.totals.wSum) / tk : null;
    // A quantile's reference needs no table; only a rate's builds one.
    var refAll = refOf(stat, rows, isQ(stat) ? null : sliceTable(rows, runs, { cut: opts.cut, cpm: cpm }));
    var ph = phis(groups, isQ(stat) ? refAll : null);
    var ctx = { stat: stat, ref: refAll === null ? 0 : refAll, phi: ph, wMean: wMean, minDays: FLOOR_DAYS };
    var cells = [];
    for (var d = 1; d <= 7; d++) {
      var dow = d % 7;
      HOUR_ORDER.forEach(function (h) {
        var ea = poolCell(A.byCell[dow * 24 + h] || [], ctx), eb = poolCell(B.byCell[dow * 24 + h] || [], ctx);
        var c = { dow: dow, hour: h, a: slim(ea), b: slim(eb), enough: false, shade: null, ci: null,
                  diff: ea.value !== null && eb.value !== null ? r2(eb.value - ea.value) : null };
        if (stat === 'goodRate') {
          c.enough = ea.timeOk && eb.timeOk;
          var K = ea.good + eb.good;
          if (c.enough && K > 0) {
            var f = ph.good > 1 ? ph.good : 1, p0 = eb.hours / (ea.hours + eb.hours);
            var ci = shareCI(eb.good / f, K / f, CI_ALPHA);
            c.shade = ci[0] > p0 ? 'above' : ci[1] < p0 ? 'below' : null;
            // As a ratio of B's rate to A's: (p / (1 - p)) x (A's hours / B's).
            var ratio = function (x) { return x >= 1 ? null : r2(x / (1 - x) * ea.hours / eb.hours); };
            c.ci = [ratio(ci[0]), ratio(ci[1])];
            c.ciIs = 'ratio';
          }
        } else if (stat === 'earned') {
          c.enough = ea.timeOk && eb.timeOk && wMean > 0;
          c.clamped = ea.clamped || eb.clamped;
          if (c.enough && !c.clamped) {
            var ca = earnCI(ea.wy, ea.wv, wMean, ph.takes, CMP_SIDE_ALPHA), cb = earnCI(eb.wy, eb.wv, wMean, ph.takes, CMP_SIDE_ALPHA);
            var la = ca[0] / ea.hours, ua = ca[1] / ea.hours, lb = cb[0] / eb.hours, ub = cb[1] / eb.hours;
            c.shade = lb > ua ? 'above' : ub < la ? 'below' : null;
            c.ci = [r2(lb - ua), r2(ub - la)];
          }
        } else {
          var qa = ea.n >= FLOOR && ea.days >= FLOOR_DAYS ? quantCIw(sorted(ea.vals), p, CMP_SIDE_ALPHA, ea.phiQ) : null;
          var qb = eb.n >= FLOOR && eb.days >= FLOOR_DAYS ? quantCIw(sorted(eb.vals), p, CMP_SIDE_ALPHA, eb.phiQ) : null;
          c.enough = !!(qa && qb);
          if (c.enough) {
            c.shade = qb[0] > qa[1] ? 'above' : qb[1] < qa[0] ? 'below' : null;
            c.ci = [r2(qb[0] - qa[1]), r2(qb[1] - qa[0])];
          }
        }
        cells.push(c);
      });
    }
    return { stat: stat, net: cpm !== null,
             phi: Math.round((stat === 'earned' ? ph.takes : ph.good) * 100) / 100,
             rhoQ: isQ(stat) ? Math.round(ph.q * 1000) / 1000 : null,
             sideAlpha: CMP_SIDE_ALPHA, alpha: CI_ALPHA, cells: cells,
             a: { offers: A.tab.totals.offers, hours: r2(A.tab.totals.hours) },
             b: { offers: B.tab.totals.offers, hours: r2(B.tab.totals.hours) } };
  }
  function slim(e) {
    return { n: e.n, offers: e.offers, days: e.days, hours: e.hours, onlineDays: e.onlineDays, good: e.good,
             takes: e.takes, value: e.value, off: e.off, timeOk: e.timeOk };
  }

  /* --- days 1-10, 11-20, 21 to the end --------------------------------------------
   *
   * The chosen figure in each third of the month, over every month in the
   * range, pooled as a grid cell is. A third is shaded (against the range's
   * own figure, by the grid's rules; good and earned per hour widened by phi
   * over the third's days) only where EVERY third holds days of at least
   * THIRDS_MONTHS months: one or two months is one or two paydays, and the
   * weekdays that happened to fall in each third. Under that the thirds are
   * printed grey with their n and days. */
  function thirdOf(day) { var d = Number(day.slice(8, 10)); return d <= 10 ? 0 : d <= 20 ? 1 : 2; }
  function monthThirds(rows, runs, opts) {
    opts = opts || {};
    var stat = statOf(opts.stat);
    var tab = sliceTable(rows, runs, { cut: opts.cut, cpm: cpmOf(opts) });
    var parts = [[], [], []], months = [{}, {}, {}], byDay = [{}, {}, {}];
    sliceList(tab).forEach(function (sl) {
      var t = thirdOf(sl.day);
      parts[t].push(sl);
      months[t][sl.month] = 1;
      var d = byDay[t][sl.day] || (byDay[t][sl.day] = { good: 0, takes: 0, hours: 0, vals: [] });
      d.good += sl.good; d.takes += sl.takes; d.hours += sl.hours;
      var sv = valuesOf(sl.rows, 'perHour');
      for (var i = 0; i < sv.length; i++) d.vals.push(sv[i]);
    });
    var nMonths = months.map(function (m) { return Object.keys(m).length; });
    var gated = nMonths.every(function (n) { return n >= THIRDS_MONTHS; });
    var ph = phis(byDay.map(function (g) { return Object.keys(g).map(function (k) { return g[k]; }); }));
    var tref = refOf(stat, rows, tab);
    // A quantile's phi over each third's days, as good/hr's.
    if (isQ(stat)) ph.q = qRho(byDay.map(function (g) {
      return Object.keys(g).map(function (k) { return g[k].vals; });
    }), tref);
    var ctx = { stat: stat, ref: tref, phi: ph, wMean: tab.wMean, minDays: FLOOR_DAYS };
    var labels = ['1–10', '11–20', '21–end'];
    return { stat: stat, gated: gated, need: THIRDS_MONTHS, ref: ctx.ref === null ? null : r2(ctx.ref),
             net: tab.net, thirds: parts.map(function (sl, i) {
               var e = poolCell(sl, ctx);
               delete e.vals; delete e.wy; delete e.wv;
               e.label = labels[i]; e.months = nMonths[i]; e.dates = Object.keys(byDay[i]).length;
               if (!gated) e.shade = null;
               return e;
             }) };
  }

  /* --- one weekday over the weeks --------------------------------------------------
   *
   * Every driver day of one weekday from the range's first to its last, one
   * point each: its P90 $/hr (with its n), its good offers per hour online
   * and its earned per hour online (gross: the card's pay of its takes), with
   * the hours online under them. A day with no minute online and no card is
   * `off` (no point, said so). Hours as the calendar's tiles: the day's own
   * slices (onlineHoursBy), so a run across 4am gives its small hours to the
   * night before, as its cards are. A P90 under DAY_MIN offers, and a
   * rate under GOOD_FLOOR_HOURS online, is `thin` (a hollow point). */
  function sameWeekday(rows, runs, dow, opts) {
    opts = opts || {};
    var hours = onlineHoursBy(runs, 'day'), keys = Object.keys(hours);
    var g = groupBy(rows, function (r) { return r.day; });
    var all = g.keys.concat(keys).sort();
    if (!all.length) return { dow: dow, days: [] };
    var d0 = all[0], d1 = all[all.length - 1], k = d0;
    for (var i = 0; i < 7 && dateOfKey(k).getDay() !== dow; i++) k = addDays(k, 1);
    var out = [];
    for (var guard = 0; k <= d1 && guard < 1000; guard++, k = addDays(k, 7)) {
      var list = g.by[k] || [], h = hours[k] || 0;
      var v = sorted(valuesOf(list, 'perHour'));
      var good = list.filter(function (r) { return isGood(r, opts.cut); }).length;
      var sl = emptySlice(k, 0);
      list.forEach(function (r) { addTake(sl, r, null); });
      out.push({ day: k, n: v.length, offers: list.length, p90: v.length ? r2(q(v, 0.9)) : null, p90Thin: v.length < DAY_MIN,
                 good: good, hours: r2(h), goodRate: h > 0 ? r2(good / h) : null, takes: sl.takes, unpaid: sl.unpaid,
                 earned: r2(sl.earned), earnedRate: h > 0 ? r2(sl.earned / h) : null, rateThin: h < GOOD_FLOOR_HOURS,
                 off: h === 0 && list.length === 0 });
    }
    return { dow: dow, days: out };
  }

  /* --- the week in review ----------------------------------------------------------
   *
   * One driver week (Monday 4am to Monday 4am) as one card, and the week before
   * it beside it. See the header, "THE WEEK IN REVIEW", for what is compared,
   * what is marked and why. Everything here is a pool of the same day-hour
   * slices the grid, the timeline and the thirds are (sliceTable), so a week's
   * hours, good offers and earnings are the grid's own, cut at the same
   * clock hours, and a run across Monday 4am puts its 3am hour in the week
   * before, as the timeline does. */

  // The ms a driver week spans, on the local clock: the week holding 1 Nov
  // is 169 hours long (1am happens twice), the one holding the spring change
  // 167. What earnings.js rangeSummary is handed as from/to.
  function weekSpanMs(wk) {
    var a = dateOfKey(wk), b = dateOfKey(addDays(wk, 7));
    return [new Date(a.getFullYear(), a.getMonth(), a.getDate(), DAY_STARTS_AT).getTime(),
            new Date(b.getFullYear(), b.getMonth(), b.getDate(), DAY_STARTS_AT).getTime()];
  }

  // Every week from the first holding a row or a minute online to the last,
  // oldest first, a week off included: stepping ‹ › walks the calendar, and a
  // week with nothing in it says so rather than being skipped over.
  function weekKeys(rows, runs) {
    var first = null, last = null;
    function see(day) { if (first === null || day < first) first = day; if (last === null || day > last) last = day; }
    (rows || []).forEach(function (r) { see(r.day); });
    var pieces = onlinePieces(runs);
    Object.keys(pieces).forEach(function (k) { see(pieces[k].day); });
    if (first === null) return [];
    var out = [];
    for (var k = weekKeyOf(first), guard = 0; k <= weekKeyOf(last) && guard < 1000; k = addDays(k, 7), guard++) out.push(k);
    return out;
  }

  // The three-hour blocks a slot is named by: Advice's (the Strategy tab's and
  // strategy.js's "by time block"), on the driver's day.
  var BLOCK_NAMES = Advice && Advice.BLOCK_NAMES ? Advice.BLOCK_NAMES
    : ['12–3am', '3–6am', '6–9am', '9am–12', '12–3pm', '3–6pm', '6–9pm', '9pm–12'];

  // One week's figures off the two slice tables (gross, and net where a cost
  // per mile is known), and its slots and its days for phi.
  function weekFigures(gross, net, wk) {
    var e = { week: wk, from: wk, to: addDays(wk, 6), hours: 0, onlineDays: 0, offers: 0, good: 0, takes: 0,
              unpaid: 0, noMiles: 0, earned: 0, earnedNet: null, y: 0, v: 0, yNet: 0, vNet: 0,
              quality: { suspect: 0, corrected: 0, unread: 0 } };
    var days = Object.create(null), slots = Object.create(null);
    Object.keys(gross.slices).forEach(function (k) {
      var s = gross.slices[k];
      if (s.week !== wk) return;
      e.hours += s.hours; e.offers += s.rows.length; e.good += s.good; e.takes += s.takes; e.unpaid += s.unpaid;
      e.earned += s.earned; e.y += s.y; e.v += s.v;
      var d = days[s.day] || (days[s.day] = { day: s.day, good: 0, takes: 0, hours: 0 });
      d.good += s.good; d.takes += s.takes; d.hours += s.hours;
      var b = Math.floor(s.hour / 3), sk = s.day + '|' + b;
      var sl = slots[sk] || (slots[sk] = { day: s.day, dow: s.dow, block: b, name: WEEKDAYS[s.dow] + ' ' + BLOCK_NAMES[b],
                                           hours: 0, good: 0, offers: 0 });
      sl.hours += s.hours; sl.good += s.good; sl.offers += s.rows.length;
      s.rows.forEach(function (r) {
        if (r.suspect && !r.unread) e.quality.suspect += 1;
        if (r.corrected) e.quality.corrected += 1;
        if (r.unread) e.quality.unread += 1;
      });
    });
    if (net) {
      e.earnedNet = 0;
      Object.keys(net.slices).forEach(function (k) {
        var s = net.slices[k];
        if (s.week !== wk) return;
        e.earnedNet += s.earned; e.yNet += s.y; e.vNet += s.v; e.noMiles += s.noMiles;
      });
    }
    e.days = Object.keys(days).sort().map(function (k) { return days[k]; });
    e.onlineDays = e.days.filter(function (d) { return d.hours > 0; }).length;
    e.slots = Object.keys(slots).map(function (k) { return slots[k]; });
    e.enough = e.hours >= GOOD_FLOOR_HOURS && e.onlineDays >= GOOD_FLOOR_DAYS;
    e.any = e.hours > 0 || e.offers > 0;
    return e;
  }

  /* `rows`, `runs` as everywhere here; `wk` the Monday key; `opts`: cut (the
   * ruler, as the tab holds it), costPerMile (net where a number), first and
   * last (the range's own first and last driver day, for "part of this week
   * only"). Returns the week, the week before (null where it held nothing),
   * the comparisons that may be drawn, the best and worst slots, and the
   * reference they were marked against. */
  function weekReview(rows, runs, wk, opts) {
    opts = opts || {};
    var cut = opts.cut, cpm = typeof opts.costPerMile === 'number' ? opts.costPerMile : null;
    var gross = sliceTable(rows, runs, { cut: cut });
    var net = cpm !== null ? sliceTable(rows, runs, { cut: cut, cpm: cpm }) : null;
    // phi over every week's days in the range, as the calendar's week column
    // measures it: a week's nights swing, and two weeks compared as if they
    // did not would differ "clearly" by chance.
    var byWeek = Object.create(null);
    sliceList(gross).forEach(function (s) {
      var w = byWeek[s.week] || (byWeek[s.week] = Object.create(null));
      var d = w[s.day] || (w[s.day] = { good: 0, takes: 0, hours: 0 });
      d.good += s.good; d.takes += s.takes; d.hours += s.hours;
    });
    var ph = phis(Object.keys(byWeek).map(function (w) {
      return Object.keys(byWeek[w]).map(function (d) { return byWeek[w][d]; });
    }));
    var now = weekFigures(gross, net, wk);
    var before = weekFigures(gross, net, addDays(wk, -7));
    var prev = before.any ? before : null;
    function rate(x, h) { return h > 0 ? r2(x / h) : null; }
    [now, prev].forEach(function (e) {
      if (!e) return;
      e.goodRate = rate(e.good, e.hours);
      e.gross = rate(e.earned, e.hours);
      e.net = e.earnedNet === null ? null : rate(e.earnedNet, e.hours);
      e.earned = r2(e.earned);
      e.clampNet = e.earnedNet !== null && clampedOf(e.earnedNet, e.yNet);
      e.earnedNet = e.earnedNet === null ? null : r2(e.earnedNet);
      e.hours = r2(e.hours);
      e.partStart = !!opts.first && e.from < opts.first;
      e.partEnd = !!opts.last && e.to > opts.last;
    });

    // Counts beside last week's, like with like (the reporting review's F2):
    // a week still running is set against last week up to the same weekday
    // and clock time (`opts.now`, a moment inside this week), not against
    // all seven of its days; a week before the range began is said to be
    // only part of one (`partStart`), and the page says from when. With no
    // `now` inside the week the whole week before is the figure, and the
    // page says "full". Rates are not cut: a rate is already per hour, and
    // it is compared only under the floors below.
    var counts = null;
    if (prev) {
      var span = weekSpanMs(wk), pspan = weekSpanMs(addDays(wk, -7));
      var nowMs = typeof opts.now === 'number' ? opts.now : null;
      var soFar = nowMs !== null && nowMs > span[0] && nowMs < span[1];
      var until = pspan[1];
      if (soFar) { var same = new Date(nowMs); same.setDate(same.getDate() - 7); until = same.getTime(); }
      var ch = 0;
      (runs || []).forEach(function (r) {
        if (!r || !(r[1] > r[0])) return;
        var a = Math.max(r[0], pspan[0]), b = Math.min(r[1], until);
        if (b > a) ch += (b - a) / 3.6e6;
      });
      var co = 0, ct = 0, pk = addDays(wk, -7);
      rows.forEach(function (r) {
        if (r.week !== pk || r.t >= until) return;
        co += 1;
        var tk = takeOf(r, null);
        if (tk && !tk.unpaid) ct += 1;
      });
      counts = { soFar: soFar, until: soFar ? until : null, hours: r2(ch), offers: co, takes: ct,
                 partStart: prev.partStart, from: prev.partStart ? opts.first : null };
    }

    // Against the week before: only where BOTH meet the week's floor; the
    // tests are compare mode's (gridCompare), so a week's arrow means what a
    // B-vs-A cell's shading means.
    var cmp = { good: null, gross: null, net: null };
    if (prev && now.enough && prev.enough) {
      var K = now.good + prev.good, f = ph.good > 1 ? ph.good : 1;
      cmp.good = { prev: prev.goodRate, shade: null };
      if (K > 0) {
        var p0 = now.hours / (now.hours + prev.hours), ci = shareCI(now.good / f, K / f, CI_ALPHA);
        cmp.good.shade = ci[0] > p0 ? 'above' : ci[1] < p0 ? 'below' : null;
      }
      var earnCmp = function (yA, vA, yB, vB, prevFig, clamped) {
        var tk = now.takes + prev.takes, w = tk ? (yA + yB) / tk : 0;
        var out = { prev: prevFig, shade: null, clamped: !!clamped };
        if (!(w > 0) || clamped) return out;
        var ca = earnCI(yA, vA, w, ph.takes, CMP_SIDE_ALPHA), cb = earnCI(yB, vB, w, ph.takes, CMP_SIDE_ALPHA);
        var la = ca[0] / now.hours, ua = ca[1] / now.hours, lb = cb[0] / prev.hours, ub = cb[1] / prev.hours;
        out.shade = la > ub ? 'above' : ua < lb ? 'below' : null;
        return out;
      };
      cmp.gross = earnCmp(now.y, now.v, prev.y, prev.v, prev.gross);
      if (net) cmp.net = earnCmp(now.yNet, now.vNet, prev.yNet, prev.vNet, prev.net,
                                 now.clampNet || prev.clampNet);
    }

    // The week's slots: a weekday x block is ONE driver day in one week, so
    // it is marked as a calendar tile is — at GOOD_FLOOR_HOURS online, the
    // plain Poisson interval on its good offers clear of the range's own
    // good per hour (one day is one day; there is no second night to measure
    // phi on), and the card says "that evening", which is all it can say.
    // Best is the highest marked above, worst the lowest marked below.
    // BONFERRONI over the slots that met the floor (the reporting review's
    // S5): the card names the best of six or seven at 99% each, so on
    // nights that swing 40% (the owner's do) 79% of no-effect weeks named a
    // slot; at 0.01 / slots met, one name among them is under 1% by chance
    // with no swing (stats in the AUDITS entry).
    var ref = gross.refRate;
    var met = now.slots.filter(function (s) { return s.hours >= GOOD_FLOOR_HOURS; });
    var slotAlpha = met.length ? CI_ALPHA / met.length : CI_ALPHA;
    met.forEach(function (s) {
      s.rate = r2(s.good / s.hours);
      s.shade = ref === null ? null : rateShade(s.good, s.hours, ref, 1, slotAlpha).shade;
      s.hours = r2(s.hours);
    });
    var best = null, worst = null;
    met.forEach(function (s) {
      if (s.shade === 'above' && (!best || s.rate > best.rate)) best = s;
      if (s.shade === 'below' && (!worst || s.rate < worst.rate)) worst = s;
    });
    function slim(e) {
      if (!e) return null;
      return { week: e.week, from: e.from, to: e.to, hours: e.hours, onlineDays: e.onlineDays, offers: e.offers,
               good: e.good, goodRate: e.goodRate, takes: e.takes, unpaid: e.unpaid, noMiles: e.noMiles,
               earned: e.earned, earnedNet: e.earnedNet, gross: e.gross, net: e.net, enough: e.enough,
               quality: e.quality, partStart: e.partStart, partEnd: e.partEnd, any: e.any };
    }
    return { week: wk, span: weekSpanMs(wk), now: slim(now), prev: slim(prev), cmp: cmp, counts: counts, net: net !== null,
             cut: typeof cut === 'number' ? cut : null, ref: ref === null ? null : r2(ref),
             phi: { good: Math.round(ph.good * 100) / 100, takes: Math.round(ph.takes * 100) / 100 },
             slots: { met: met.length, of: now.slots.length, best: best, worst: worst,
                      floorHours: GOOD_FLOOR_HOURS, alpha: slotAlpha } };
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
                days: daysIn(list), good: list.filter(function (r) { return isGood(r, cut); }).length, metrics: {} };
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

  /* --- CSV -------------------------------------------------------------------
   *
   * For a spreadsheet, and Excel in particular (the owner, Nov 2026: "could the
   * CSV output be improved so the dates and times are also Excel friendly for
   * making charts?"). Every CSV the offers page makes keeps to the same rules:
   *   - the page puts BOM in front of the text it saves, or Excel opens a
   *     UTF-8 file in the local code page and the "–" in a label comes out
   *     as three letters of noise;
   *   - a missing value is an empty cell, never "null" or "NaN", which Excel
   *     takes for text and a chart then plots as zero or refuses;
   *   - a date is 'YYYY-MM-DD' and a moment 'YYYY-MM-DD HH:MM:SS' on the
   *     driver's clock, the two shapes Excel turns into a date or a
   *     date-time unasked; a week is the date of its Monday;
   *   - columns are only ever appended, so a sheet built on last month's file
   *     still finds its columns where it left them;
   *   - text a spreadsheet would run as a formula is defused (safeCell). */
  var BOM = '\ufeff';

  /* A text cell a spreadsheet would read as a formula, led with an apostrophe
   * (the usual CSV-injection rule: a leading = + - @, tab or carriage
   * return). Card text can start that way — a misread row of the card's
   * icons comes back as "-" or "=", Uber's add-on line reads "+ 1 order",
   * and a store can name itself "@Home Kitchen" — and a pickup that opens as
   * =HYPERLINK(...) would be a live link the driver never wrote. A plain
   * number keeps its sign: -3.50 is a figure (paid less the card), not a
   * formula. The order records CSV in journal.html keeps the same rule. */
  var FORMULA_LEAD = /^[=+\-@\t\r]/;
  var PLAIN_NUMBER = /^[-+]?(\d+\.?\d*|\.\d+)$/;
  function safeCell(s) {
    return FORMULA_LEAD.test(s) && !PLAIN_NUMBER.test(s) ? "'" + s : s;
  }

  function cell(v) {
    if (v === null || v === undefined) return '';
    if (typeof v === 'number' && !isFinite(v)) return '';
    var s = typeof v === 'number' ? String(v) : safeCell(String(v));
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function csvText(lines) { return lines.map(function (l) { return l.map(cell).join(','); }).join('\n') + '\n'; }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function dateKey(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  // Local 'YYYY-MM-DD HH:MM:SS', the end-of-shift report's own stamp (and
  // journal.html's stampOf): the shape Excel reads as a date-time.
  function stampOf(ms) {
    var d = new Date(ms);
    return dateKey(d) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  // '16:00-17:00' for clock hour 16: a label that sorts as it reads, beside
  // the bare hour a chart's axis wants.
  function hourLabel(h) { return pad2(h) + ':00-' + pad2((h + 1) % 24) + ':00'; }

  // `cut`: the ruler the good column was counted against, printed beside it,
  // so a CSV opened next month still says what "good" meant in it.
  // Appended (the Excel round, Nov 2026): week_start, the Monday of the
  // driver week, as a date on both tables, and the driver day's weekday on
  // the daily one, so a pivot by week or weekday needs no formula. The first
  // column keeps its name (week_of is already that Monday): sheets read it.
  function csvPeriods(list, goods, by, cut) {
    var gBy = Object.create(null);
    (goods || []).forEach(function (g) { gBy[g.key] = g; });
    var head = [by === 'week' ? 'week_of' : 'day', 'offers', 'counted'];
    METRICS.forEach(function (m) { ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { head.push(m + '_' + k); }); });
    head = head.concat(['uber_offers', 'doordash_offers', 'app_unknown', 'uber_median_per_hour',
                        'doordash_median_per_hour', 'good', 'good_from_per_hour', 'hours_online', 'good_per_online_hour',
                        'suspect', 'corrected', 'pay_unread', 'boost_known', 'boost_yes', 'week_start', 'weekday']);
    var lines = [head];
    list.forEach(function (e) {
      var row = [e.key, e.n, e.counted];
      METRICS.forEach(function (m) {
        ['p25', 'p50', 'p75', 'p90'].forEach(function (k) { row.push(e.metrics[m][k]); });
      });
      var g = gBy[e.key] || {};
      row = row.concat([e.share.uber, e.share.doordash, e.share.unknown, e.apps.uber.perHour,
                        e.apps.doordash.perHour, g.good, cut, g.hours, g.rate,
                        e.quality.suspect,
                        e.quality.corrected, e.quality.unread, e.boost ? e.boost.known : '',
                        e.boost ? e.boost.yes : '',
                        by === 'week' ? e.key : weekKeyOf(e.key),
                        by === 'week' ? '' : WEEKDAYS[dateOfKey(e.key).getDay()]]);
      lines.push(row);
    });
    return csvText(lines);
  }
  // `hours` is the day choice (all, weekday, weekend) and `hour` the clock
  // hour, a bare integer 0-23; hour_label appended for a category axis.
  function csvHourly(list, label) {
    var lines = [['hours', 'hour', 'offers', 'counted', 'days', 'p25', 'p50', 'p75', 'p90', 'enough', 'hour_label']];
    list.forEach(function (e) {
      lines.push([label || 'all', e.hour, e.offers, e.n, e.days, e.p25, e.p50, e.p75, e.p90, e.enough ? 'yes' : 'no',
                  hourLabel(e.hour)]);
    });
    return csvText(lines);
  }

  /* EVERY OFFER, ONE ROW EACH (the owner, Nov 2026: "the CSV download does
   * not seem to include the GPS data", and the dates Excel-friendly). Made in
   * the owner's browser on a press, from the /api/journal offers of the range
   * pressed (fetched uncapped where the page's own copy was cut): nothing new
   * is sent anywhere, and /api/trends still carries no position. One row per
   * offer id, the newest copy (distinct, the fold's rule), oldest first.
   *
   * THE CLOCK. `datetime` is when the card appeared (seenAt: the fold's
   * firstAt), local; `date`, `time`, `weekday` and `hour` are that moment's
   * calendar; `driver_day` is the 4am-to-4am day it belongs to (dayKeyOf, the
   * page's and the report's: 1am Saturday is Friday night), with its weekday,
   * and `week_start` that driver day's Monday. The night the clocks go back
   * (1 Nov 2026) the two 1:30ams print alike, as the wall clock read; both
   * belong to the driver day before.
   *
   * WHAT THE PAGE KNOWS, AND NO MORE. `panel_said` is the verdict the panel
   * printed in the car (the row's own state); `driver_marked` is the driver's
   * own word only — taken for a ✓, passed for a Passed — and EMPTY otherwise:
   * a card nobody answered for is not a take (Settled, silence is never read
   * as an accept). `during_job` is yes where Advice.busy put the card inside
   * a ticked job or the rig recorded a pairing for it (the page's own
   * marks), else empty.
   *
   * GOOD is this range's own ruler, trends.js's: the card's $/hr in the top
   * CSV_TOP% of the range's money rows (ruler), the cut the Trends tab draws
   * at its default, so the column is named for what it is
   * (good_top20_of_range) and the cut goes back to the page to print. Empty on
   * a row the money does not count (pay unread, suspect).
   *
   * GPS is the car's own fix on the card (journal.py fix_fields): lat and lon
   * to six places, the gate's yes or no, its error in metres and its age in
   * seconds, wherever the row carries a coordinate — a fix the gate refused
   * is written with gps_ok "no", for a sheet to filter — and empty where it
   * carries none (no receiver, no fix, or a row written under keepPlaces
   * off, which keeps no position). `keepPlaces` false, as the server reports
   * the rig's setting now, empties the GPS and place columns on every row, as
   * the order records CSV empties a record kept with places off
   * (recordPlaces): the driver chose not to keep where he was, so the export
   * does not either. The columns stay, so the sheet's shape does not move
   * with the setting. Pickup and dropoff are the row's own, as printed. */
  var CSV_TOP = 20;
  var OFFER_COLUMNS = ['datetime', 'date', 'time', 'weekday', 'hour', 'driver_day', 'driver_weekday', 'week_start',
                       'app', 'pay', 'boost', 'card_minutes', 'card_miles', 'per_hour', 'per_mile',
                       'panel_said', 'driver_marked', 'during_job', 'good_top' + CSV_TOP + '_of_range',
                       'counted', 'suspect', 'doubt', 'pay_reread', 'pay_unread',
                       'lat', 'lon', 'gps_ok', 'gps_err_m', 'gps_age_s', 'pickup', 'dropoff', 'offer_id',
                       // Round B, appended as every column is (the rule above).
                       'special_day', 'reoffered'];
  var SAID = { go: 'ACCEPT', warn: 'CLOSE CALL', no: 'PASS' };
  function fixed(v, places) { return num(v) === null ? null : Number(v.toFixed(places)); }
  function yn(b) { return b ? 'yes' : 'no'; }
  function offersCsv(offers, opts) {
    opts = opts || {};
    var busy = opts.busy || {}, paired = opts.paired || {};
    var noPlaces = opts.keepPlaces === false;
    // Round B: the two marks the Trends overview can leave out, as columns
    // (never as rows taken away): the special day's name, the owner's marked
    // days among them (`marked`), and the fold's `reoffered`.
    var marked = markedSet(opts.marked);
    var list = distinct(offers);
    var rule = ruler(readRows(rowsOf(list)), CSV_TOP);
    var lines = [OFFER_COLUMNS.slice()];
    var gps = 0;
    list.map(function (o) { return { o: o, t: seenAt(o) }; })
      .sort(function (a, b) { return (a.t === null ? Infinity : a.t) - (b.t === null ? Infinity : b.t); })
      .forEach(function (x) {
        var o = x.o, t = x.t;
        // The row as the ruler read it (packed to the cent, the money rule
        // applied), so "good" here counts exactly what the Trends tab counts.
        var r = t === null ? null : readRows(rowsOf([o]))[0];
        var when = t === null ? null : new Date(t);
        var day = t === null ? null : dayKeyOf(t);
        var hasFix = !noPlaces && num(o.lat) !== null && num(o.lon) !== null;
        if (hasFix) gps += 1;
        var pay = o.payUnread === true ? null : num(o.pay);
        var boost = !Object.prototype.hasOwnProperty.call(o, 'boost') || o.boost === null ? null
          : typeof o.boost === 'number' ? o.boost : yn(!!o.boost);
        var c = o.corrected && typeof o.corrected === 'object' ? o.corrected : null;
        // Counted as the page counts (trustworthy, with a rate): the rows
        // every money figure, and the ruler, are over.
        var ok = !!(r && r.ok && r.perHour !== null);
        lines.push([
          when ? stampOf(t) : null, when ? dateKey(when) : null,
          when ? pad2(when.getHours()) + ':' + pad2(when.getMinutes()) : null,
          when ? WEEKDAYS[when.getDay()] : null, when ? when.getHours() : null,
          day, day ? WEEKDAYS[dateOfKey(day).getDay()] : null, day ? weekKeyOf(day) : null,
          o.app === 'uber' || o.app === 'doordash' ? o.app : null,
          fixed(pay, 2), boost, fixed(o.minutes, 1), fixed(o.miles, 1), fixed(o.perHour, 2),
          pay !== null && num(o.miles) !== null && o.miles >= 0.1 ? fixed(pay / o.miles, 2) : null,
          SAID[o.state] || null,
          o.accepted === true ? 'taken' : o.accepted === false ? 'passed' : null,
          typeof o.id === 'string' && (busy[o.id] || paired[o.id]) ? 'yes' : null,
          ok && rule.cut !== null ? yn(isGood(r, rule.cut)) : null,
          yn(ok), yn(!!o.suspect), typeof o.doubt === 'string' ? o.doubt : null,
          yn(!!(c && typeof c.to === 'number')), yn(o.payUnread === true),
          hasFix ? fixed(o.lat, 6) : null, hasFix ? fixed(o.lon, 6) : null,
          hasFix ? yn(o.gpsOk === true) : null, hasFix ? fixed(o.gpsErr, 1) : null,
          hasFix ? fixed(o.gpsAge, 1) : null,
          noPlaces || typeof o.pickup !== 'string' ? null : o.pickup,
          noPlaces || typeof o.dropoff !== 'string' ? null : o.dropoff,
          typeof o.id === 'string' ? o.id : null,
          day ? specialDayOf(day, marked) : null, yn(o.reoffered === true)
        ]);
      });
    return { text: csvText(lines), rows: lines.length - 1, gps: gps, cut: rule.cut, top: CSV_TOP };
  }

  /* --- round B: the overview, special days, re-offered cards, outliers ---------
   *
   * The owner, Nov 2026: "a simplified overview that lets you expand into
   * more specific details ... to figure out when (time of day, day of the
   * week, etc) and where ... to find the most profitable times to work and
   * areas." And on outliers: "many very high paying orders to fast food
   * places tend to be undeliverable and the price ends up being very high but
   * is not real and can make the charts hard to read. Though it can be
   * impossible to tell, or certain days like Halloween pay very well due to
   * the holiday." Everything below READS the record: nothing deletes a row,
   * and nothing reaches the verdict, the target, the panel or the rig. */

  /* SPECIAL DAYS. A built-in list, by rule, and the days the owner marks
   * (server.js /api/specialdays, dates only). A special day is a DRIVER day
   * (4am to 4am), so Halloween's small hours after midnight are Halloween,
   * and New Year's Eve's last hours are the Eve, not the Day.
   *
   * SUPER BOWL SUNDAY, CHECKED. From the 2021 season on (17 games and a week
   * off before the game) it falls 22 weeks after the first Sunday after Labor
   * Day: 13 Feb 2022, 12 Feb 2023, 11 Feb 2024, 9 Feb 2025, 8 Feb 2026, all
   * the 2nd Sunday of February. The two rules are one: Labor Day falls 1-7
   * Sep, so that first Sunday is 7-13 Sep, and 154 days on is 8-14 Feb, which
   * is exactly the 2nd Sunday's range. The same rule gives 14 Feb 2027 (also
   * Valentine's Day; the day says both) and 13 Feb 2028. Before 2022 the
   * game was on the 1st Sunday (7 Feb 2021, 2 Feb 2020). A schedule change by
   * the league is what would break it, and a marked day covers that. */
  var specialMemo = Object.create(null);
  function nthSunday(y, m, n) { var d = new Date(y, m, 1, 12); return 1 + (7 - d.getDay()) % 7 + (n - 1) * 7; }
  function nthWeekdayOf(y, m, dow, n) { var d = new Date(y, m, 1, 12); return 1 + (dow - d.getDay() + 7) % 7 + (n - 1) * 7; }
  function specialDays(year) {
    var y = Number(year);
    if (specialMemo[y]) return specialMemo[y];
    var out = Object.create(null);
    function at(m, d, name) {
      var k = y + '-' + pad2(m + 1) + '-' + pad2(d);
      out[k] = out[k] ? out[k] + ' · ' + name : name;
    }
    at(0, 1, 'New Year\'s Day');
    at(1, 14, 'Valentine\'s Day');
    at(1, nthSunday(y, 1, y >= 2022 ? 2 : 1), 'Super Bowl Sunday');
    at(4, nthSunday(y, 4, 2), 'Mother\'s Day');
    at(6, 4, 'July 4th');
    at(9, 31, 'Halloween');
    at(10, nthWeekdayOf(y, 10, 4, 4), 'Thanksgiving');
    at(11, 24, 'Christmas Eve');
    at(11, 25, 'Christmas Day');
    at(11, 31, 'New Year\'s Eve');
    specialMemo[y] = out;
    return out;
  }
  var DATE_KEY = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;
  // A list of marked days (or a set already) as a set of 'YYYY-MM-DD'.
  function markedSet(marked) {
    if (marked && !Array.isArray(marked) && typeof marked === 'object') return marked;
    var out = Object.create(null);
    (marked || []).forEach(function (k) { if (typeof k === 'string' && DATE_KEY.test(k)) out[k] = true; });
    return out;
  }
  // The day's name, 'marked by you' for a day the owner marked, both where
  // both, else null.
  function specialDayOf(day, marked) {
    if (typeof day !== 'string' || !DATE_KEY.test(day)) return null;
    var name = specialDays(day.slice(0, 4))[day] || null;
    if (markedSet(marked)[day]) return name ? name + ' (marked by you)' : 'marked by you';
    return name;
  }

  /* LEAVE OUT. The overview's two switches, both off unless pressed, both
   * reading-only: the rows and runs every figure on the tab is worked from,
   * with the re-offered cards (the fold's `reoffered`) and/or every offer and
   * minute online on a special day taken out, and what was taken out. A run
   * is cut at 4am (a clock-hour edge, so no hour's piece changes) and its
   * pieces on a special day dropped, so a holiday's hours leave with its
   * offers and good per hour is not lowered by hours whose cards are gone. A
   * re-offered card's minutes stay: the driver was online for them. Nothing
   * on: the same rows and runs, by identity, so every cache holds. */
  function nextDayEdge(t) {
    var d = dateOfKey(dayKeyOf(t));
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1, DAY_STARTS_AT).getTime();
  }
  function leaveOut(rows, runs, opts) {
    opts = opts || {};
    var sp = !!opts.special, re = !!opts.reoffered;
    var out = { rows: rows, runs: runs, removed: 0, reoffered: 0, special: 0, days: [] };
    if (!sp && !re) return out;
    var marked = markedSet(opts.marked), named = Object.create(null), gone = Object.create(null);
    function special(day) {
      if (!(day in named)) named[day] = sp ? specialDayOf(day, marked) : null;
      return named[day];
    }
    out.rows = rows.filter(function (r) {
      var s = special(r.day), x = re && r.reoffered;
      if (s) gone[r.day] = s;
      if (!s && !x) return true;
      out.removed += 1;
      if (x) out.reoffered += 1;
      if (s) out.special += 1;
      return false;
    });
    if (sp) {
      out.runs = [];
      (runs || []).forEach(function (r) {
        if (!r || !(r[1] > r[0])) return;
        for (var t = r[0], guard = 0; t < r[1] && guard < 400; guard++) {
          var end = Math.min(r[1], nextDayEdge(t)), day = dayKeyOf(t), s = special(day);
          if (s) gone[day] = s; else out.runs.push([t, end]);
          t = end;
        }
      });
    }
    out.days = Object.keys(gone).sort().map(function (d) { return { day: d, name: gone[d] }; });
    return out;
  }

  /* WHEN: THE BEST AND WEAKEST WINDOWS. A window is a run of whole clock
   * hours, in the driver day's order (4am first, so a night is one stretch),
   * of 1 to WINDOW_MAX_H hours, on one driver weekday or a group of them
   * (Weekdays, Monday to Friday; Weekends, Saturday and Sunday, the driver's
   * days). Its figure is good offers per hour online, the grid's own: the
   * good count over the minutes online in those cells, pooled over the
   * nights. Floor: GOOD_FLOOR_HOURS online on GOOD_FLOOR_DAYS driver days,
   * the grid's. Clear: the grid's widened Poisson interval (phi measured over
   * the cells' nights, as the grid's) wholly above or below the range's own
   * rate.
   *
   * WHY THE INTERVAL IS SHARED OVER THE SEARCH. A grid cell is one question;
   * this asks a few hundred overlapping ones and keeps the best, and the best
   * of many at 99% each is clear by chance far more than 1 time in 100. So
   * the 99% is shared (Bonferroni) over every window that met the floor, as
   * the week card shares it over its slots: CI_ALPHA / m, m kept on the
   * answer (`searched`). Simulated on records built like the owner's (AUDITS.md,
   * the round B entry, has the table). Conservative where windows overlap,
   * which costs power and never a false "clearly".
   *
   * WHICH WINDOW SPEAKS FOR A STRETCH. Of the windows that are clear, the one
   * whose interval sits furthest from the range (the highest lower end for
   * the best, the lowest upper end for the weakest) is taken first, then the
   * next that shares no cell with it, and so on: a three-hour Friday evening
   * that is clearly better outranks the single hour inside it that happens
   * to read higher on fewer nights. The chosen ones are then listed by good
   * per hour. With none clear, the three highest by good per hour that share
   * no cell are listed as "leading, not yet clear". Every hour inside a
   * window had time online; untried hours (no minute online and no card in
   * the range) are listed apart and never as weak.
   * Descriptive: when offers paid best, never which to take. */
  var WINDOW_MAX_H = 6, WINDOW_BEST = 3, WINDOW_WORST = 2;
  var DAY_GROUPS = [[1], [2], [3], [4], [5], [6], [0], [1, 2, 3, 4, 5], [6, 0]];
  var GROUP_NAMES = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays',
                     'Weekdays', 'Weekends'];
  function clockName(h) { return (h % 12 || 12) + (h < 12 ? 'am' : 'pm'); }
  // '6–10pm', '10pm–2am', '4–5am': hours h0 to hLast inclusive.
  function spanName(h0, hLast) {
    var a = clockName(h0), b = clockName((hLast + 1) % 24);
    return (a.slice(-2) === b.slice(-2) ? a.slice(0, -2) : a) + '–' + b;
  }
  function windowName(w) { return GROUP_NAMES[w.group] + ' ' + spanName(w.from, w.to); }

  /* The search itself, over plain slices so the places report can hand it
   * its own (cards waited, not minutes online): each slice { day, dow, hour,
   * k (good), h (hours), offers, takes, e (earned) }. */
  function findWindows(slices, opts) {
    opts = opts || {};
    var fH = typeof opts.floorHours === 'number' ? opts.floorHours : GOOD_FLOOR_HOURS;
    var fD = typeof opts.floorDays === 'number' ? opts.floorDays : GOOD_FLOOR_DAYS;
    var maxLen = opts.maxLen || WINDOW_MAX_H, alpha = opts.alpha || CI_ALPHA;
    var cells = [];
    for (var c0 = 0; c0 < 168; c0++) cells.push({ K: 0, H: 0, offers: 0, takes: 0, e: 0, nights: Object.create(null) });
    var K = 0, H = 0;
    (slices || []).forEach(function (s) {
      var c = cells[s.dow * 24 + s.hour];
      if (!c) return;
      c.K += s.k || 0; c.H += s.h || 0; c.offers += s.offers || 0; c.takes += s.takes || 0; c.e += s.e || 0;
      var n = c.nights[s.day] || (c.nights[s.day] = { k: 0, h: 0 });
      n.k += s.k || 0; n.h += s.h || 0;
      K += s.k || 0; H += s.h || 0;
    });
    var ref = H > 0 ? K / H : null;
    // phi AT THE WINDOW'S OWN LENGTH. A slow night lowers every hour of it,
    // so a window's nights swing more than one cell's: measured over the
    // grid's per-cell phi, a four-hour window was clear by chance in 9% of
    // no-effect records with a 40% night-to-night swing (simulated, 300
    // records of nine weeks). So phi is measured per length, over every
    // single weekday's windows of that length, each night's good and hours
    // summed across the window's hours.
    var phiLen = [1];
    for (var L0 = 1; L0 <= maxLen; L0++) {
      var groups = [];
      for (var dd = 0; dd < 7; dd++) {
        for (var i0 = 0; i0 + L0 <= 24; i0++) {
          var nightsOf = Object.create(null);
          for (var j0 = 0; j0 < L0; j0++) {
            var cn = cells[dd * 24 + HOUR_ORDER[i0 + j0]].nights;
            for (var dk in cn) {
              var x = nightsOf[dk] || (nightsOf[dk] = { k: 0, h: 0 });
              x.k += cn[dk].k; x.h += cn[dk].h;
            }
          }
          groups.push(Object.keys(nightsOf).map(function (dk2) { return nightsOf[dk2]; }));
        }
      }
      phiLen.push(typeof opts.phi === 'number' ? opts.phi : dispersion(groups));
    }
    var cands = [];
    DAY_GROUPS.forEach(function (dows, g) {
      for (var i = 0; i < 24; i++) {
        var k = 0, h = 0, offers = 0, takes = 0, e = 0, days = Object.create(null), nDays = 0, keys = [];
        for (var len = 1; len <= maxLen && i + len <= 24; len++) {
          var hour = HOUR_ORDER[i + len - 1];
          // Every hour of a window was tried: one with no minute online on
          // any of its days ends the run (an untried hour is listed apart,
          // never folded into a window's figure or its name).
          var tried = false;
          for (var dt = 0; dt < dows.length; dt++) if (cells[dows[dt] * 24 + hour].H > 0) tried = true;
          if (!tried) break;
          for (var di = 0; di < dows.length; di++) {
            var c = cells[dows[di] * 24 + hour];
            k += c.K; h += c.H; offers += c.offers; takes += c.takes; e += c.e;
            keys.push(dows[di] * 24 + hour);
            for (var dy in c.nights) if (c.nights[dy].h > 0 && !days[dy]) { days[dy] = true; nDays += 1; }
          }
          if (h >= fH - 1e-9 && nDays >= fD) {
            cands.push({ group: g, dows: dows, from: HOUR_ORDER[i], to: hour, len: len, k: k, h: h, nights: nDays,
                         offers: offers, takes: takes, earned: e, cells: keys.slice() });
          }
        }
      }
    });
    var m = cands.length, a = alpha / Math.max(1, m);
    cands.forEach(function (w) {
      w.rate = w.k / w.h;
      w.shade = null; w.ci = null;
      if (ref === null) return;
      var phi = phiLen[w.len], f = phi > 1 ? phi : 1;
      // A screen before the exact interval, kept only where it cannot change
      // the answer: at a shared level under 1e-3 a count within 2 sd of the
      // range's (on k/phi) can never clear, and the bisections are most of
      // the search's cost on a phone.
      var mu = ref * w.h;
      if (a < 1e-3 && Math.abs(w.k - mu) / Math.sqrt(Math.max(w.k, mu, 1) * f) < 2) return;
      var rs = rateShade(w.k, w.h, ref, phi, a);
      w.shade = rs.shade; w.ci = rs.ci;
    });
    function pick(list, n, order) {
      var used = Object.create(null), chosen = [];
      list.slice().sort(order).forEach(function (w) {
        if (chosen.length >= n || w.cells.some(function (c) { return used[c]; })) return;
        w.cells.forEach(function (c) { used[c] = true; });
        chosen.push(w);
      });
      return chosen;
    }
    var byRate = function (x, y) { return y.rate - x.rate || y.h - x.h || x.group - y.group; };
    var best = pick(cands.filter(function (w) { return w.shade === 'above'; }), WINDOW_BEST, function (x, y) {
      return y.ci[0] - x.ci[0] || byRate(x, y);
    }).sort(byRate);
    var worst = pick(cands.filter(function (w) { return w.shade === 'below'; }), WINDOW_WORST, function (x, y) {
      return x.ci[1] - y.ci[1] || byRate(y, x);
    }).sort(function (x, y) { return x.rate - y.rate || y.h - x.h; });
    var leading = best.length ? [] : pick(cands.filter(function (w) { return w.shade !== 'below'; }), WINDOW_BEST, byRate);
    function said(w) {
      var at = HOUR_ORDER.indexOf(w.from);
      return { group: w.group, dows: w.dows, from: w.from, to: w.to, len: w.len, name: windowName(w),
               hours: HOUR_ORDER.slice(at, at + w.len), good: w.k, online: r2(w.h), nights: w.nights,
               offers: w.offers, rate: r2(w.rate), waitMin: w.k > 0 ? Math.round(60 * w.h / w.k) : null,
               shade: w.shade, ci: w.ci, takes: w.takes, earned: r2(w.earned), earnedRate: r2(w.earned / w.h),
               cells: w.cells };
    }
    // Untried: no minute online and no card, by weekday, as runs of hours;
    // a run untried on every weekday is said once, as every day's.
    var WEEK = [1, 2, 3, 4, 5, 6, 0], runsBy = [];
    for (var d0 = 0; d0 < 7; d0++) {
      var list = [], run = null;
      for (var hi = 0; hi < 24; hi++) {
        var hr = HOUR_ORDER[hi], cc = cells[d0 * 24 + hr];
        if (cc.H === 0 && cc.offers === 0) { if (run) run.to = hr; else run = { from: hr, to: hr }; }
        else if (run) { list.push(run); run = null; }
      }
      if (run) list.push(run);
      runsBy.push(list);
    }
    function offOn(d, r) { return runsBy[d].some(function (o) { return o.from === r.from && o.to === r.to; }); }
    var untried = [], every = Object.create(null);
    runsBy[1].forEach(function (r) {
      if (WEEK.every(function (d) { return offOn(d, r); })) {
        every[r.from + '-' + r.to] = true;
        untried.push({ dows: WEEK, every: true, from: r.from, to: r.to });
      }
    });
    WEEK.forEach(function (d) {
      runsBy[d].forEach(function (r) {
        if (!every[r.from + '-' + r.to]) untried.push({ dows: [d], every: false, from: r.from, to: r.to });
      });
    });
    untried.forEach(function (u) {
      u.name = (u.every ? 'every day' : WEEKDAYS[u.dows[0]]) + ' ' + spanName(u.from, u.to);
      u.hours = HOUR_ORDER.indexOf(u.to) - HOUR_ORDER.indexOf(u.from) + 1;
    });
    return { best: best.map(said), worst: worst.map(said), leading: leading.map(said), clear: best.length > 0,
             searched: m, alpha: a, ref: ref === null ? null : r2(ref), phi: phiLen.slice(1).map(r2),
             floorHours: fH, floorDays: fD, maxLen: maxLen, untried: untried, online: r2(H), good: K };
  }
  // The tab's windows: the slice table's own good, minutes online, takes and
  // earned (net at the rig's one cost per mile where `net` asks).
  function overviewWhen(rows, runs, opts) {
    opts = opts || {};
    var tab = sliceTable(rows, runs, { cut: opts.cut, cpm: cpmOf(opts) });
    var res = findWindows(sliceList(tab).map(function (s) {
      return { day: s.day, dow: s.dow, hour: s.hour, k: s.good, h: s.hours, offers: s.rows.length,
               takes: s.takes, e: s.earned };
    }), opts);
    res.cut = typeof opts.cut === 'number' ? opts.cut : null;
    res.net = tab.net;
    return res;
  }

  /* WHERE, on the offers page: the card's own towns (map-view.js townOf
   * over Advice.area, the Targets lines' rule; the caller hands it in, so
   * this file knows no place), the pickup's and the dropoff's apart, from
   * the offers the page already holds. Each town: offers counted, the share
   * good against the ruler, the typical $/hr, driver days; ranked by share
   * good at FLOOR offers on FLOOR_DAYS days, the rest counted as thin. A
   * share is called clearly above or below the range's only where its 99%
   * interval, shared over the towns ranked (Bonferroni), leaves the range's
   * share out. `keep` is the overview's switches, by the page. */
  function towns(offers, opts) {
    opts = opts || {};
    var cut = opts.cut, townOf = opts.townOf, keep = opts.keep;
    var minN = typeof opts.minN === 'number' ? opts.minN : FLOOR;
    var minD = typeof opts.minDays === 'number' ? opts.minDays : FLOOR_DAYS;
    var ends = { pickup: Object.create(null), dropoff: Object.create(null) };
    var unnamed = { pickup: 0, dropoff: 0 }, n = 0, good = 0;
    distinct(offers).forEach(function (o) {
      if (keep && !keep(o)) return;
      var ok = o.payUnread !== true && (Advice && Advice.trustworthy ? Advice.trustworthy(o) : !o.suspect)
        && num(o.perHour) !== null;
      var t = seenAt(o);
      if (!ok || t === null) return;
      var g = typeof cut === 'number' && o.perHour >= cut;
      n += 1; if (g) good += 1;
      ['pickup', 'dropoff'].forEach(function (end) {
        var name = typeof townOf === 'function' && typeof o[end] === 'string' ? townOf(o[end]) : null;
        if (!name) { unnamed[end] += 1; return; }
        var e = ends[end][name] || (ends[end][name] = { town: name, n: 0, good: 0, days: Object.create(null), v: [] });
        e.n += 1; if (g) e.good += 1;
        e.days[dayKeyOf(t)] = true;
        e.v.push(o.perHour);
      });
    });
    var share = n ? good / n : null;
    var res = { n: n, good: good, share: share === null ? null : r2(share), minN: minN, minDays: minD };
    ['pickup', 'dropoff'].forEach(function (end) {
      var ranked = [], thin = 0;
      Object.keys(ends[end]).forEach(function (k) {
        var e = ends[end][k], days = Object.keys(e.days).length;
        if (e.n >= minN && days >= minD) {
          ranked.push({ town: e.town, n: e.n, good: e.good, share: r2(e.good / e.n), days: days,
                        typical: r2(q(sorted(e.v), 0.5)) });
        } else thin += 1;
      });
      var a = CI_ALPHA / Math.max(1, ranked.length);
      ranked.forEach(function (e) {
        e.shade = null;
        if (share === null) return;
        var ci = shareCI(e.good, e.n, a);
        e.shade = ci[0] > share ? 'above' : ci[1] < share ? 'below' : null;
      });
      ranked.sort(function (x, y) { return y.share - x.share || y.typical - x.typical || y.n - x.n; });
      res[end] = { ranked: ranked, thin: thin, unnamed: unnamed[end] };
    });
    return res;
  }

  /* OUTLIERS, DRAWN, NEVER DROPPED. A chart of single offers scales its axis
   * to the bulk: the higher of the 99th percentile and Tukey's far fence (the
   * upper quartile plus three times the middle half's width), so at most one
   * offer in a hundred sits past it and a record with no wild offer has no
   * cap at all. The offers past it are counted on the edge ("↑ 4 above
   * $62/hr") and listed on a press. AN AXIS CAP FOR DRAWING IS NOT A FLOOR OR
   * A CEILING ON PAY (Settled: no $/mile rules and no payout floors): every
   * offer stays in every figure and the ruler; only the drawing's edge moves.
   * Under AXIS_CAP_MIN values there is too little to call anything the bulk. */
  var AXIS_CAP_MIN = 20;
  function axisCap(vals) {
    var s = sorted((vals || []).filter(function (v) { return typeof v === 'number' && isFinite(v); }));
    var max = s.length ? s[s.length - 1] : null;
    if (s.length < AXIS_CAP_MIN) return { cap: null, above: 0, max: max, n: s.length };
    var q1 = q(s, 0.25), q3 = q(s, 0.75), cap = Math.max(q(s, 0.99), q3 + 3 * (q3 - q1));
    if (!(max > cap)) return { cap: null, above: 0, max: max, n: s.length };
    var above = 0;
    for (var i = s.length - 1; i >= 0 && s[i] > cap; i--) above += 1;
    return { cap: r2(cap), above: above, max: max, n: s.length };
  }
  // The money rows over a cap, highest first: figures and when only (the
  // rows hold no text and no place).
  function outliers(rows, cap) {
    if (typeof cap !== 'number') return [];
    return rows.filter(function (r) { return r.ok && r.perHour !== null && r.perHour > cap; })
      .sort(function (a, b) { return b.perHour - a.perHour || a.t - b.t; })
      .map(function (r) {
        return { t: r.t, day: r.day, app: r.app, pay: r.pay, minutes: r.minutes, miles: r.miles,
                 perHour: r.perHour, reoffered: !!r.reoffered, taken: !!r.taken };
      });
  }

  /* COST PER MILE, AS THE ROWS CARRY IT. Every offer's $/hr is net of its
   * card miles at the cost per mile in force when it was seen (journal.py
   * row_for stores the setting beside the rate). /api/trends sends where that
   * changed in the window ([seconds, cost] at each change, numbers only), so
   * the tab can say "$/hr after $0.30/mi (card miles)" and, where it moved,
   * when and from what. */
  function costNote(costs) {
    var list = (costs || []).filter(function (c) { return c && num(c[0]) !== null && num(c[1]) !== null; });
    var changes = [];
    for (var i = 1; i < list.length; i++) {
      if (list[i][1] !== list[i - 1][1]) {
        changes.push({ t: list[i][0] * 1000, day: dayKeyOf(list[i][0] * 1000), from: list[i - 1][1], to: list[i][1] });
      }
    }
    return { now: list.length ? list[list.length - 1][1] : null, first: list.length ? list[0][1] : null,
             changes: changes };
  }

  /* WHAT THE RECORD CAN HOLD YET (the UX review's D4-D6): a view that cannot
   * say anything until the record is longer is hidden until it can, rather
   * than drawn grey. Months on the timeline and the days of the month need
   * three calendar months with data; one weekday over the weeks needs
   * SAME_DOW_MIN of that weekday with data; this month against last needs
   * two calendar months wholly inside the record's first and last driver day. */
  var SAME_DOW_MIN = 4;
  function reveals(rows, runs) {
    var months = Object.create(null), dayHas = Object.create(null), first = null, last = null;
    function see(day) {
      months[day.slice(0, 7)] = true;
      dayHas[day] = true;
      if (first === null || day < first) first = day;
      if (last === null || day > last) last = day;
    }
    rows.forEach(function (r) { see(r.day); });
    var pieces = onlinePieces(runs);
    Object.keys(pieces).forEach(function (k) { if (pieces[k].hours > 0) see(pieces[k].day); });
    var dowDays = [0, 0, 0, 0, 0, 0, 0];
    Object.keys(dayHas).forEach(function (d) { dowDays[dateOfKey(d).getDay()] += 1; });
    var full = 0;
    if (first !== null) {
      var y = Number(first.slice(0, 4)), m = Number(first.slice(5, 7)) - 1;
      for (var guard = 0; guard < 600; guard++) {
        var a = y + '-' + pad2(m + 1) + '-01';
        if (a > last) break;
        var z = y + '-' + pad2(m + 1) + '-' + pad2(new Date(y, m + 1, 0, 12).getDate());
        if (a >= first && z <= last) full += 1;
        m += 1; if (m > 11) { m = 0; y += 1; }
      }
    }
    var nMonths = Object.keys(months).length;
    return { months: nMonths, fullMonths: full, dowDays: dowDays,
             tlMonths: nMonths >= 3, thirds: nMonths >= 3, monthVsLast: full >= 2,
             sameDow: dowDays.map(function (n) { return n >= SAME_DOW_MIN; }) };
  }

  return {
    FLOOR: FLOOR, FLOOR_DAYS: FLOOR_DAYS, CI_ALPHA: CI_ALPHA, DAY_MIN: DAY_MIN,
    RATE_MIN_N: RATE_MIN_N, RATE_COLLINEAR: RATE_COLLINEAR, RATE_AT: RATE_AT, RATE_BOOTS: RATE_BOOTS,
    METRICS: METRICS, METRIC_NAMES: METRIC_NAMES, APPS: APPS, WEEKDAYS: WEEKDAYS, HOUR_ORDER: HOUR_ORDER,
    distinct: distinct, rowsOf: rowsOf, pack: pack, unpack: unpack, readRows: readRows,
    dayKeyOf: dayKeyOf, weekKeyOf: weekKeyOf, addDays: addDays,
    medianRank: medianRank, quarts: quarts,
    TOPS: TOPS, TOP_DEFAULT: TOP_DEFAULT, STATS: STATS, STAT_P: STAT_P, STAT_NAMES: STAT_NAMES,
    GOOD_FLOOR_HOURS: GOOD_FLOOR_HOURS, GOOD_FLOOR_DAYS: GOOD_FLOOR_DAYS, F_TAKEN: F_TAKEN,
    quantRanks: quantRanks, quantCI: quantCI, quantCIw: quantCIw, qRho: qRho, qPhiOf: qPhiOf, shadeQ: shadeQ, poisCI: poisCI, dispersion: dispersion,
    rateShade: rateShade, ruler: ruler, isGood: isGood,
    CMP_SIDE_ALPHA: CMP_SIDE_ALPHA, THIRDS_MONTHS: THIRDS_MONTHS, APP_SHARE_MIN: APP_SHARE_MIN,
    gammaInv: gammaInv, earnCI: earnCI, clampedOf: clampedOf, earnShade: earnShade, betaI: betaI, shareCI: shareCI,
    takeOf: takeOf, sliceTable: sliceTable, poolCell: poolCell, goodAppShare: goodAppShare,
    timeline: timeline, gridCompare: gridCompare, monthThirds: monthThirds, sameWeekday: sameWeekday,
    periodSpan: periodSpan, inPeriod: inPeriod,
    weekSpanMs: weekSpanMs, weekKeys: weekKeys, weekReview: weekReview, BLOCK_NAMES: BLOCK_NAMES,
    onlinePieces: onlinePieces, cellDetail: cellDetail,
    periods: periods, hoursBy: hoursBy, onlineHoursBy: onlineHoursBy, goodPerHour: goodPerHour, hourly: hourly, monthsOf: monthsOf,
    grid: grid, calendar: calendar, fit3: fit3, rateFit: rateFit, rateCard: rateCard,
    compare: compare, scatter: scatter, csvPeriods: csvPeriods, csvHourly: csvHourly,
    BOM: BOM, safeCell: safeCell, hourLabel: hourLabel, offersCsv: offersCsv, OFFER_COLUMNS: OFFER_COLUMNS,
    CSV_TOP: CSV_TOP, F_REOFFER: F_REOFFER,
    specialDays: specialDays, specialDayOf: specialDayOf, leaveOut: leaveOut, findWindows: findWindows,
    overviewWhen: overviewWhen, windowName: windowName, spanName: spanName, GROUP_NAMES: GROUP_NAMES,
    DAY_GROUPS: DAY_GROUPS, WINDOW_MAX_H: WINDOW_MAX_H, towns: towns, axisCap: axisCap, AXIS_CAP_MIN: AXIS_CAP_MIN,
    outliers: outliers, costNote: costNote, reveals: reveals, SAME_DOW_MIN: SAME_DOW_MIN
  };
}));
