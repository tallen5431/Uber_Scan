/* The reports checked against the real journal, in aggregates only.
 *
 *   node tools/report_check.js                       the NucBox's copy (http://localhost:8082)
 *   node tools/report_check.js http://localhost:8080 --since 2026-09-01
 *   node tools/report_check.js --json                the same figures as JSON
 *
 * Every report round so far ended "not yet run on the real journal, so no
 * figure of the owner's is recorded" (AUDITS.md), and the reporting review
 * found its worst faults — two hours rules, two rulers, a Took taken back
 * counted as taken — only by building journals by hand. This reads the
 * journal the way the places report does (its loadJournal over /api/journal,
 * paging past the server's limit, and /api/trends for the Trends tab's own
 * rows) and prints what the owner can paste back without a second thought:
 *
 *   - offers, rows and driver days, and the first and last date;
 *   - how many offers carry a gated GPS fix;
 *   - the top 10/20/30/50% cutoffs, the Trends tab's and the places report's;
 *   - for every Trends view and figure, the cells meeting the floors and the
 *     cells coloured (above and below);
 *   - hours online by the one rule (onlinePieces), beside the sitting's;
 *   - takes by each view's rule (Trends' ✓ bit, the Money tab's standing
 *     Tooks, section 7's Took-or-✓), and the weeks where they disagree;
 *   - each cost per mile the rows carry, and the dates it ran over;
 *   - the share of offers with the pay re-read, suspect, pay unread, and
 *     re-offered (the server's fold marks it, round B) or raised where a
 *     row marks it;
 *   - which half of the server's re-offered rule marked each card, and
 *     whether the same-trip pairs agree on miles and minutes;
 *   - whether the journal read was cut, how many pages it took, and how
 *     many days old its newest offer is;
 *   - how long the main computations took here.
 *
 * NEVER a place, a coordinate, a card's text, an id or one trip's amount:
 * counts, shares, dollar cutoffs over the whole range, settings and dates.
 * A check holds it (tests/reportcheck.test.js). Read only: nothing is
 * written, so it is safe beside the NucBox's server. Nothing on the rig
 * runs it, and lite never has it to run. */

'use strict';

var A = require('../advice.js');
var T = require('../trends.js');
var E = require('../earnings.js');
var MV = require('../map-view.js');
var S = require('./strategy.js');
var P = require('./places_report.js');

var USAGE = [
  'node tools/report_check.js [server] [--since YYYY-MM-DD] [--json]',
  '',
  'Run on the NucBox. Reads the journal through the server (default http://localhost:8082, the copy at home)',
  'and prints aggregates only: no place, coordinate, text, id or single trip\'s amount.'
].join('\n');

function r2(v) { return typeof v === 'number' && isFinite(v) ? Math.round(v * 100) / 100 : null; }
function share(k, n) { return n ? Math.round(k / n * 1000) / 10 : null; }

function timer(times) {
  return function (label, fn) {
    var t0 = process.hrtime.bigint();
    var out = fn();
    times.push({ what: label, ms: Math.round(Number(process.hrtime.bigint() - t0) / 1e5) / 10 });
    return out;
  };
}

// Cells meeting the floor, and coloured, over a list of cells.
function tally(cells) {
  var t = { cells: 0, enough: 0, above: 0, below: 0 };
  cells.forEach(function (c) {
    if (!c || c.off) return;
    t.cells += 1;
    if (c.enough) t.enough += 1;
    if (c.shade === 'above') t.above += 1;
    if (c.shade === 'below') t.below += 1;
  });
  return t;
}

/* Every figure, off the two answers already read. `journal` is
 * places_report's loadJournal answer, `trends` /api/trends's. */
/* Which half of server.js markReoffered marked the re-offered cards, and
 * what the pairs look like. The first real run marked more offers than
 * undeliverable orders coming round should account for, and the suspicion is the
 * pair half: where a card's dropoff is printed as a town, two different
 * orders from one busy restaurant to one town inside half an hour are keyed
 * as one trip. The same order offered again keeps its route, so its card
 * miles and minutes barely move (the leg to the pickup is the only part that
 * can) and its pay holds or rises; two different orders seldom agree on
 * both. So: the pairs this key finds, re-found here with the server's own
 * key and window, and how many agree on miles and minutes, and how the pay
 * moved. Counts only, never the places the key is made of. */
var REOFFER_WINDOW_MS = 30 * 60 * 1000;      // server.js REOFFER_WINDOW_MS (a check holds them equal)
var REOFFER_GAP_MS = 60 * 1000;              // server.js REOFFER_GAP_MS: closer is one card under two ids
function reofferKey(o) {
  function pk(v) { return typeof v === 'string' ? v.toLowerCase().replace(/\s+/g, ' ').trim() : ''; }
  var pick = pk(o.pickup), drop = pk(o.dropoff);
  if (!pick) return null;
  if (drop) return { key: (o.app || '') + '|' + pick + '|' + drop, named: true };
  if (typeof o.minutes === 'number' && typeof o.miles === 'number') {
    return { key: (o.app || '') + '|' + pick + '||' + o.minutes + '|' + o.miles, named: false };
  }
  return null;
}
function reofferedHow(offers) {
  var marked = offers.filter(function (o) { return o && o.reoffered === true; });
  var sorted = offers.filter(function (o) { return o && typeof o.at === 'number'; })
    .slice().sort(function (a, b) { return a.at - b.at; });
  var recent = Object.create(null), inPair = Object.create(null);
  var pairs = { named: 0, unnamed: 0, sameMiles: 0, sameMinutes: 0, sameBoth: 0,
                payUp: 0, paySame: 0, payDown: 0, gaps: [], close: 0 };
  function pay(o) { return typeof o.pay === 'number' ? o.pay : null; }
  sorted.forEach(function (o) {
    var k = reofferKey(o);
    if (!k) return;
    var list = recent[k.key] || (recent[k.key] = []);
    while (list.length && o.at - list[0].at > REOFFER_WINDOW_MS) list.shift();
    // Each card against the one just before it under the same key: one pair
    // per step, so a chain of three is two pairs, as a driver would count
    // "offered again" twice.
    var prev = null;
    for (var i = list.length - 1; i >= 0; i--) { if (list[i].id !== o.id) { prev = list[i]; break; } }
    if (prev) {
      inPair[o.id] = 1; inPair[prev.id] = 1;
      pairs[k.named ? 'named' : 'unnamed'] += 1;
      var sm = typeof o.miles === 'number' && typeof prev.miles === 'number' && Math.abs(o.miles - prev.miles) <= 0.2;
      var sn = typeof o.minutes === 'number' && typeof prev.minutes === 'number' && Math.abs(o.minutes - prev.minutes) <= 2;
      if (sm) pairs.sameMiles += 1;
      if (sn) pairs.sameMinutes += 1;
      if (sm && sn) pairs.sameBoth += 1;
      var a = pay(prev), b = pay(o);
      if (a !== null && b !== null) {
        if (b > a + 0.01) pairs.payUp += 1; else if (b < a - 0.01) pairs.payDown += 1; else pairs.paySame += 1;
      }
      pairs.gaps.push((o.at - prev.at) / 60000);
      if ((typeof o.firstAt === 'number' ? o.firstAt : o.at) - prev.at <= REOFFER_GAP_MS) pairs.close += 1;
    }
    list.push(o);
  });
  var g = pairs.gaps.sort(function (x, y) { return x - y; });
  var total = pairs.named + pairs.unnamed;
  return {
    marked: marked.length,
    byPair: marked.filter(function (o) { return inPair[o.id]; }).length,
    bySpanOnly: marked.filter(function (o) { return !inPair[o.id]; }).length,
    pairs: { total: total, named: pairs.named, unnamed: pairs.unnamed,
             sameMiles: pairs.sameMiles, sameMinutes: pairs.sameMinutes, sameBoth: pairs.sameBoth,
             sameBothShare: share(pairs.sameBoth, total),
             payUp: pairs.payUp, paySame: pairs.paySame, payDown: pairs.payDown,
             gapMedianMin: g.length ? r2(g[Math.floor((g.length - 1) / 2)]) : null,
             withinAMinute: pairs.close, apart: total - pairs.close }
  };
}

function check(journal, trends, opts) {
  opts = opts || {};
  var times = [], time = timer(times);
  var offers = Array.isArray(journal && journal.offers) ? journal.offers : [];
  var rows = time('unpack /api/trends', function () { return T.unpack((trends && trends.rows) || { cols: {} }); });
  var runs = ((trends && trends.runs) || []).map(function (s) { return [s[0] * 1000, s[1] * 1000]; });
  var res = { made: opts.now || Date.now() };

  // 1. What was read.
  var ats = offers.map(function (o) { return typeof o.firstAt === 'number' ? o.firstAt : o.at; })
    .filter(function (t) { return typeof t === 'number' && isFinite(t); });
  res.journal = { offers: offers.length, total: journal ? journal.total : null, pages: journal && journal.pages || 1,
                  truncated: !!(journal && journal.truncated), driverDays: A.outingsIn(offers),
                  first: ats.length ? T.dayKeyOf(Math.min.apply(null, ats)) : null,
                  last: ats.length ? T.dayKeyOf(Math.max.apply(null, ats)) : null };
  var rDays = Object.create(null);
  rows.forEach(function (r) { rDays[r.day] = 1; });
  res.trends = { rows: rows.length, counted: rows.filter(function (r) { return r.ok; }).length,
                 driverDays: Object.keys(rDays).length, runs: runs.length,
                 first: rows.length ? rows[0].day : null, last: rows.length ? rows[rows.length - 1].day : null };

  // 2. GPS fixes on the cards.
  var fixed = offers.filter(function (o) { return !!MV.fixOf(o); }).length;
  res.gps = { offers: offers.length, fixed: fixed, share: share(fixed, offers.length) };

  // 3. The cutoffs, both ways: they should be the same figure wherever the
  // two read the same offers.
  var rr = time('places report rulers', function () { return P.reportRulers(offers); });
  res.cuts = T.TOPS.map(function (t) {
    var tr = T.ruler(rows, t), pr = rr.byTop[t] || {};
    return { top: t, trends: tr.cut, trendsOver: tr.over, trendsN: tr.n, report: pr.cut === undefined ? null : pr.cut,
             reportOver: pr.over || 0, reportN: pr.n || 0 };
  });
  var cut = T.ruler(rows, T.TOP_DEFAULT).cut;

  // 4. Every Trends view, every figure: cells at the floor and coloured.
  var cpm = trends && typeof trends.costPerMile === 'number' ? trends.costPerMile : null;
  var lastDay = rows.length ? rows[rows.length - 1].day : null;
  var B = lastDay ? { from: T.addDays(lastDay, -6), to: lastDay } : null;
  var Aw = lastDay ? { from: T.addDays(lastDay, -13), to: T.addDays(lastDay, -7) } : null;
  var figures = T.STATS.map(function (s) { return { stat: s, net: false }; });
  if (cpm !== null) figures.push({ stat: 'earned', net: true });
  res.views = figures.map(function (f) {
    var o = { stat: f.stat, cut: cut, runs: runs, net: f.net, costPerMile: cpm };
    var name = f.stat + (f.stat === 'earned' ? (f.net ? ' net' : ' gross') : '');
    var g = time('grid ' + name, function () { return T.grid(rows, o); });
    var cal = time('calendar ' + name, function () { return T.calendar(rows, runs, o); });
    var v = { figure: name, grid: tally(g.cells), calendarDays: tally(cal.days), calendarWeeks: tally(cal.weeks) };
    ['day', 'week', 'month'].forEach(function (by) {
      var tl = time('timeline ' + by + ' ' + name, function () { return T.timeline(rows, runs, Object.assign({ by: by }, o)); });
      var all = [];
      tl.rows.forEach(function (r) { r.cells.forEach(function (c) { all.push(c); }); });
      v['timeline' + by[0].toUpperCase() + by.slice(1)] = tally(all);
    });
    var th = T.monthThirds(rows, runs, o);
    v.thirds = tally(th.thirds); v.thirds.gated = th.gated;
    if (B) {
      var cmp = T.gridCompare(rows, runs, Aw, B, o);
      v.compareLastTwoWeeks = tally(cmp.cells);
    }
    if (g.clamped !== undefined) v.clampedCells = g.clamped;
    return v;
  });

  // 5. Hours online, the one rule beside the sitting's.
  var pieces = T.onlinePieces(runs), online = 0, sitting = 0;
  Object.keys(pieces).forEach(function (k) { online += pieces[k].hours; });
  var hb = T.hoursBy(runs, 'day');
  Object.keys(hb).forEach(function (k) { sitting += hb[k]; });
  var od = T.onlineHoursBy(runs, 'day');
  res.hours = { online: r2(online), sittings: r2(sitting), daysOnline: Object.keys(od).length,
                note: 'the same total by both: the rule moves hours between days, never adds or loses them' };

  // 6. Takes by each view's rule, and the weeks they disagree.
  var byWeek = Object.create(null);
  function bump(wk, k) { var e = byWeek[wk] || (byWeek[wk] = { week: wk, trends: 0, money: 0, section7: 0 }); e[k] += 1; }
  rows.forEach(function (r) { if (r.taken) bump(r.week, 'trends'); });
  var records = Array.isArray(journal && journal.records) ? journal.records : [];
  records.forEach(function (r) {
    if (!r || r.kind !== 'order' || typeof r.offer !== 'string' || S.TAKEN_BACK[r.how]) return;
    var t = r.times && typeof r.times.took === 'number' ? r.times.took : null;
    if (t !== null) bump(T.weekKeyOf(T.dayKeyOf(t)), 'money');
  });
  var dd = S.dedupe(offers);
  var orders = P.strategyOrders(journal && journal.taken || [], records, null, null);
  var how = S.acceptedIds(dd.list, orders, null);
  var seenOf = Object.create(null);
  dd.list.forEach(function (x) { if (x.row && typeof x.row.id === 'string' && x.seen !== null) seenOf[x.row.id] = x.seen; });
  Object.keys(how).forEach(function (id) {
    if (how[id] === 'took' && seenOf[id] !== undefined) bump(T.weekKeyOf(T.dayKeyOf(seenOf[id])), 'section7');
  });
  var weeks = Object.keys(byWeek).sort().map(function (k) { return byWeek[k]; });
  var tot = { trends: 0, money: 0, section7: 0 };
  weeks.forEach(function (w) { tot.trends += w.trends; tot.money += w.money; tot.section7 += w.section7; });
  res.takes = { total: tot, moneyRangeSummary: E.rangeSummary([], records, {}).all.taken,
                disagree: weeks.filter(function (w) { return w.trends !== w.money || w.trends !== w.section7; }),
                rules: { trends: 'the fold\'s ✓ (accepted === true)', money: 'an order record whose Took stands',
                         section7: 'a Took that stands, or the ✓' } };

  // 7. Cost per mile on the rows, each value and its dates.
  var cpms = Object.create(null);
  offers.forEach(function (o) {
    if (typeof o.costPerMile !== 'number') return;
    var t = typeof o.firstAt === 'number' ? o.firstAt : o.at, k = String(o.costPerMile);
    var e = cpms[k] || (cpms[k] = { value: o.costPerMile, offers: 0, first: null, last: null });
    e.offers += 1;
    var d = typeof t === 'number' ? T.dayKeyOf(t) : null;
    if (d && (!e.first || d < e.first)) e.first = d;
    if (d && (!e.last || d > e.last)) e.last = d;
  });
  res.costPerMile = { trends: cpm, seen: Object.keys(cpms).map(function (k) { return cpms[k]; })
    .sort(function (a, b) { return (a.first || '') < (b.first || '') ? -1 : 1; }),
                      without: offers.filter(function (o) { return typeof o.costPerMile !== 'number'; }).length };

  // 8. The pay, as the record marks it.
  function n(f) { return offers.filter(f).length; }
  var reoffer = n(function (o) { return o.reoffered === true || o.reOffered === true || o.repeat === true; });
  var raised = n(function (o) { return o.raised === true || typeof o.raisedFrom === 'number'; });
  res.pay = { offers: offers.length,
              corrected: n(function (o) { return o.corrected && typeof o.corrected === 'object' && typeof o.corrected.to === 'number'; }),
              suspect: n(function (o) { return o.suspect === true; }),
              payUnread: n(function (o) { return o.payUnread === true; }),
              reoffered: reoffer, raised: raised,
              marked: { reoffered: reoffer > 0, raised: raised > 0 } };
  ['corrected', 'suspect', 'payUnread', 'reoffered', 'raised'].forEach(function (k) { res.pay[k + 'Share'] = share(res.pay[k], offers.length); });
  res.pay.reofferedHow = reofferedHow(offers);

  // 9. How old the newest offer is. The first real run read a copy whose
  // newest offer was weeks before the day it ran: a rig that has stopped
  // syncing home looks exactly like a driver who has not driven, and only the
  // owner can say which.
  var newest = ats.length ? Math.max.apply(null, ats) : null;
  res.journal.daysSinceNewest = newest === null ? null : Math.floor((res.made - newest) / 86400000);

  // 10. How long the main computations take here.
  if (lastDay) {
    var wk = T.weekKeyOf(lastDay);
    time('weekReview (newest week)', function () { return T.weekReview(rows, runs, wk, { cut: cut, costPerMile: cpm }); });
  }
  time('strategy.js analyse (the Strategy tab)', function () {
    return S.analyse({ offers: offers, orders: orders, rulers: rr.byTop, boots: opts.boots || undefined });
  });
  time('When & where', function () { return P.whenWhere(offers, P.waitingLine(offers, journal && journal.taken || [], null, null), rr); });
  res.times = times;
  return res;
}

function format(res) {
  var out = [];
  var j = res.journal, t = res.trends;
  out.push('report_check — aggregates only (no place, coordinate, text, id or single trip\'s amount)');
  out.push('');
  out.push('journal: ' + j.offers + ' offers of ' + j.total + ' in the window, ' + j.driverDays + ' driver days, '
           + (j.first || '—') + ' to ' + (j.last || '—') + '; read in ' + j.pages + ' page' + (j.pages === 1 ? '' : 's')
           + (j.truncated ? ' — CUT: the server would not page past its limit' : ', not cut'));
  if (typeof j.daysSinceNewest === 'number' && j.daysSinceNewest >= 3) {
    out.push('newest:  ' + j.daysSinceNewest + ' days before today — not driven since, or the rig has stopped syncing home');
  }
  out.push('trends:  ' + t.rows + ' rows (' + t.counted + ' with money), ' + t.driverDays + ' driver days, ' + t.runs
           + ' runs, ' + (t.first || '—') + ' to ' + (t.last || '—'));
  out.push('gps:     ' + res.gps.fixed + ' of ' + res.gps.offers + ' offers carry a gated fix (' + res.gps.share + '%)');
  out.push('');
  out.push('cutoffs (top X%: Trends | places report, each over its own offers)');
  res.cuts.forEach(function (c) {
    out.push('  top ' + c.top + '%: $' + c.trends + ' (' + c.trendsOver + ' of ' + c.trendsN + ') | $' + c.report + ' ('
             + c.reportOver + ' of ' + c.reportN + ')' + (c.trends !== c.report ? '  <- differ' : ''));
  });
  out.push('');
  out.push('Trends views: cells at the floor / coloured (above, below) of cells with anything in them');
  res.views.forEach(function (v) {
    out.push('  ' + v.figure + (v.clampedCells ? ' (' + v.clampedCells + ' grid cells holding a loss, never coloured)' : ''));
    ['grid', 'calendarDays', 'calendarWeeks', 'timelineDay', 'timelineWeek', 'timelineMonth', 'thirds',
     'compareLastTwoWeeks'].forEach(function (k) {
      var x = v[k];
      if (!x) return;
      out.push('    ' + (k + ':').padEnd(21) + x.enough + ' / ' + (x.above + x.below) + ' (' + x.above + ' above, ' + x.below
               + ' below) of ' + x.cells + (k === 'thirds' ? (x.gated ? '' : ', not gated yet') : ''));
    });
  });
  out.push('');
  out.push('hours online: ' + res.hours.online + ' h by the slices (onlinePieces), ' + res.hours.sittings
           + ' h by sittings, on ' + res.hours.daysOnline + ' driver days');
  var tk = res.takes;
  out.push('takes: Trends ' + tk.total.trends + ', Money ' + tk.total.money + ' (rangeSummary ' + tk.moneyRangeSummary
           + '), section 7 ' + tk.total.section7);
  out.push('  rules: Trends = ' + tk.rules.trends + '; Money = ' + tk.rules.money + '; section 7 = ' + tk.rules.section7);
  if (!tk.disagree.length) out.push('  every week agrees');
  tk.disagree.forEach(function (w) {
    out.push('  week of ' + w.week + ': Trends ' + w.trends + ', Money ' + w.money + ', section 7 ' + w.section7);
  });
  out.push('');
  out.push('cost per mile: Trends uses ' + (res.costPerMile.trends === null ? 'none' : '$' + res.costPerMile.trends)
           + '; ' + res.costPerMile.without + ' offers carry none');
  res.costPerMile.seen.forEach(function (c) {
    out.push('  $' + c.value + ' on ' + c.offers + ' offers, ' + c.first + ' to ' + c.last);
  });
  var p = res.pay;
  out.push('pay: re-read ' + p.corrected + ' (' + p.correctedShare + '%), suspect ' + p.suspect + ' (' + p.suspectShare
           + '%), pay unread ' + p.payUnread + ' (' + p.payUnreadShare + '%), re-offered '
           // Round B: the server's fold marks re-offered cards (server.js
           // markReoffered), so none is now a count, not a gap in the record;
           // a raise is one of its shapes, not marked apart.
           + (p.marked.reoffered ? p.reoffered + ' (' + p.reofferedShare + '%)' : 'none marked by the fold')
           + ', raised ' + (p.marked.raised ? p.raised + ' (' + p.raisedShare + '%)' : 'not marked apart (a raise is '
             + 'a re-offer)'));
  var h = p.reofferedHow;
  if (h && h.marked) {
    var q = h.pairs;
    out.push('  re-offered by: same trip under two ids ' + h.byPair + ', one id back on screen only ' + h.bySpanOnly);
    out.push('  same-trip pairs: ' + q.total + ' (' + q.named + ' keyed on a printed dropoff, ' + q.unnamed
             + ' on pickup + minutes + miles); agreeing on miles (±0.2) and minutes (±2) ' + q.sameBoth
             + ' (' + q.sameBothShare + '%), miles only ' + (q.sameMiles - q.sameBoth) + ', minutes only '
             + (q.sameMinutes - q.sameBoth) + '; pay up ' + q.payUp + ', same ' + q.paySame + ', down ' + q.payDown
             + '; median gap ' + q.gapMedianMin + ' min');
    out.push('  pairs inside a minute (one card under two ids, not marked since the gap rule) ' + q.withinAMinute
             + ', a minute or more apart (re-offered) ' + q.apart);
  }
  out.push('');
  out.push('timings here:');
  res.times.forEach(function (x) { out.push('  ' + String(x.ms).padStart(8) + ' ms  ' + x.what); });
  return out.join('\n');
}

async function fetchAll(server, sinceMs, getter) {
  var get = getter || async function (u) {
    var r = await fetch(u, { headers: { Accept: 'application/json' } });
    var b = null;
    try { b = await r.json(); } catch (e) { b = null; }
    return { ok: r.ok, status: r.status, body: b };
  };
  var base = server.replace(/\/+$/, '');
  var journal = await P.loadJournal(base, sinceMs, get);
  var tr = await get(base + '/api/trends?' + (sinceMs ? 'since=' + sinceMs : 'days=0'));
  if (!tr.ok || !tr.body || tr.body.ok !== true) {
    throw new Error(base + '/api/trends answered ' + tr.status + (tr.body && tr.body.lite ? ' (a lite rig has no Trends)' : ''));
  }
  return { journal: journal, trends: tr.body };
}

function parseArgs(argv) {
  var o = { server: null, since: null, json: false };
  for (var i = 0; i < argv.length; i++) {
    var a = argv[i];
    if (a === '--since') { if (i + 1 >= argv.length) throw new Error('--since wants a value'); o.since = argv[++i]; }
    else if (a === '--json') o.json = true;
    else if (a === '-h' || a === '--help') o.help = true;
    else if (/^--/.test(a)) throw new Error('unknown option ' + a);
    else if (!o.server) o.server = a;
    else throw new Error('one server address, not two');
  }
  // 8082, the copy the rig syncs to and places_nightly.sh reads. It was
  // 8081 — the NucBox's relay server, which holds a journal of its own — and
  // the first real run read that one: weeks stale, and the sync blamed.
  if (!o.server) o.server = 'http://localhost:8082';
  if (o.since && !/^\d{4}-\d\d-\d\d$/.test(o.since)) throw new Error('--since is YYYY-MM-DD');
  return o;
}

async function main(argv, getter) {
  var o;
  try { o = parseArgs(argv); } catch (e) { console.error(e.message + '\n\n' + USAGE); process.exitCode = 2; return null; }
  if (o.help) { console.log(USAGE); return null; }
  var sinceMs = null;
  if (o.since) {
    var ymd = o.since.split('-').map(Number);
    sinceMs = new Date(ymd[0], ymd[1] - 1, ymd[2], A.DAY_STARTS_AT).getTime();
  }
  var got;
  try { got = await fetchAll(o.server, sinceMs, getter); } catch (e) {
    console.error('could not read ' + o.server + ': ' + (e && e.message || e));
    process.exitCode = 1;
    return null;
  }
  var res = check(got.journal, got.trends);
  console.log(o.json ? JSON.stringify(res, null, 1) : format(res));
  return res;
}

module.exports = { check: check, format: format, fetchAll: fetchAll, parseArgs: parseArgs, main: main, USAGE: USAGE };

if (require.main === module) main(process.argv.slice(2));
