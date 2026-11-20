/* Where the good offers start, measured on the NucBox after the fact.
 *
 *   node tools/places_report.js http://localhost:8082 --out ~/places-report
 *   node tools/places_report.js http://localhost:8082 --out ~/places-report \
 *        --gps ~/gpslog --since 2026-09-01 --nominatim http://localhost:8088
 *
 * The owner's words (25 Oct 2026): "It would be helpful know where and what
 * places turn up good offers. If you could find a helpful way to visualize and
 * show that information, a table is also very helpful."
 *
 * AN OFFLINE REPORT, NOT A RIG HEAT MAP. AUDITS.md's "A heat map of $/hr by
 * area, asked for, designed, and refuted on the data" is binding on the rig,
 * and nothing here reaches the rig: no verdict, no target, no panel and no
 * page the rig serves reads this file or its output. It answers that entry's
 * three faults rather than walking past them:
 *
 *   - the miscolouring. A cell coloured by a fixed band at n=12 takes the
 *     wrong colour 21-25% of the time with no effect at all. Nothing here is
 *     coloured by a band. Every ranked cell is a median with a bootstrap
 *     interval on a dot plot, and a cell is drawn in colour ONLY where the
 *     grouping's own permutation test beats chance AND the cell's interval of
 *     its hour-held score is clear of zero. Everything else is grey and says
 *     "not distinguishable from the rest".
 *   - the hour. Each offer is measured against what the OTHER cells paid in
 *     its own three-hour block (Advice.areas' `matched`, the baseline the
 *     town table ships with), and the permutation is confined within blocks
 *     (Advice.areas' `strata`), so the test asks the question the score
 *     answers.
 *   - the biased third. Pickups that cannot be placed are counted, and the
 *     pay gap between placed and unplaced is printed with its own test, per
 *     shift day, at the top of the page, not in a footnote.
 *
 * ONE RULE IN ONE PLACE. The rows are /api/journal's, so the server's fold
 * decides which reading of a card to believe (as tools/measure_places.js
 * reads them); `Advice.trustworthy` decides which rows are evidence;
 * `Advice.areas` runs the ranking test; `MV.searchPlan`, `MV.discFor`,
 * `MV.NbxSearch` and `MV.pickPlace` place a pickup exactly as the rig's own
 * server places a held order's pickup (server.js searchHeldPickup /
 * searchHeldPickupName): a printed door by the door inside the disc round the
 * card's GPS fix; a store's name by `pickPlace` inside that disc, pinned only
 * when one place of that name answers; a chain's several branches, a list cut
 * at the limit, or no fix at all is UNPLACED and counted. "Would the driver's
 * rule take it" is the rig's own verdict on the row (`state === 'go'`), never
 * a new rule. The GPS log is read by tools/shift_report.py's load_fixes,
 * which reads it through rpi/gps.py's gate.
 *
 * NOT /api/places. That cache holds map.html's answers, chosen by a
 * different rule (the public geocoder's first answer inside a sixty-mile box
 * round the driver's town), and reusing them would place a "McDonald's" this
 * report's rule refuses. This keeps its own cache of the NucBox's ANSWERS (the
 * hit lists, keyed by the question), never of its decisions, so a re-run is
 * free and still decided by today's rules.
 *
 * PRIVACY. The report holds real places, so it is written outside the
 * repository (refused inside it) and never committed. Pickups are businesses
 * and are named. Dropoffs are customers: they are placed only to be counted
 * by area, a 2-mile cell with fewer than DROP_MIN_N trips is not named at all,
 * and no door, name or coordinate of a dropoff is written anywhere — the
 * answer cache is the one file that holds a dropoff's text, as the question
 * asked, and it lives in ~/.cache, beside nothing that is shared.
 *
 * Read-only against the server and the NucBox. The public geocoder is never
 * asked.
 *
 * THE SECOND PASS (26 Oct 2026), experimental and descriptive, one tab each:
 * your takes and their real $/hr, card against real minutes, restaurant
 * waits, strand risk per store, how busy an area is while parked (off the
 * GPS), Uber against DoorDash, add-on and stacking share, places gone quiet,
 * a weekly trend and $/mi. See "the second pass" (tools/report/tables.js) for
 * each one's rule and floor; tools/places_nightly.sh rebuilds the whole
 * report every night.
 *
 * THE THIRD PASS (26 Oct 2026, after the owner's first real run), experimental:
 * pickups placed by the rig's whole search chain with every placement's level
 * (door, corner, name; band, area, street), the street index asked even with
 * --nominatim (--streets), cards with no fix searched in the driver's region
 * by a printed door and town; the rig's store waits (--waits); Drop presses
 * timed by the GPS; and a "Best offers" tab on the top of the distribution —
 * hour-held top-25% / top-10% offers, P75 / P90, good offers per hour of
 * waiting, the expected $/hr of working an area, dead miles after a drop and
 * offer size bands. See "the third pass" (tools/report/tables.js) for each
 * rule and floor.
 *
 * THE STRATEGY TAB (7 Nov 2026, the owner: "being able to know what is a good
 * $/hr and $/mi metrics to expect would help decide which offers to take and
 * which to decline"): what offers looked like, what cards turned into, and
 * what holding out for each line of the panel's $/hr paid per hour on shift.
 * Worked out by tools/strategy.js — the end-of-shift report prints the same
 * numbers with --strategy — off this report's offers and its takes as realOf
 * times them; see strategyOrders (tools/report/tables.js) for the miles.
 * Descriptive, like the rest: no verdict, target or panel reads it.
 *
 * THE LAYOUT (7 Nov 2026, the owner, on a phone and a laptop: "consider how
 * the page and tabs are laid out, is there a better format for all this
 * information?"). Reorganised, nothing cut: an Overview that opens the page
 * (the few numbers that matter, picked out of the report object, each
 * linking to its tab with its n under it), the twenty tabs grouped by the
 * question each answers (GROUPS), a sticky nav of groups over the chosen
 * group's tabs, long tables folded under their headings on a phone (fold),
 * the curve drawn small for a phone and time of day as bars (blockChart).
 * Every old #hash still opens its tab; #overview is the new default, and a
 * fold's id opens the tab it sits in.
 *
 * WHEN & WHERE (18 Nov 2026). The owner, a selective driver, wants to know
 * which areas pay at a given time, and the answer was spread over a score of
 * tabs that each held one slice. One tab, first in "Where & when": pick the
 * driver's weekday (or Weekdays, Weekends, Any day) and a block, and the
 * areas where the car waited are ranked by good offers per hour waited, good
 * being a fixed top-share cutoff over the whole range. Off the Waited tab's
 * own line; see whenWhere (tools/report/whenwhere.js) for the slots, the
 * cutoff, the floor and the marking. Read only, like everything here.
 */

/* THE FILES (19 Nov 2026). This file had grown to 6,600 lines, one scroll
 * from the floors to the page's script, and a change to one tab meant
 * finding it among twenty. It is cut along the sections it already had,
 * nothing reworded or re-decided, into tools/report/:
 *
 *   stats.js      the floors, the small pieces, the bootstrap, the grid
 *   place.js      placing a pickup by the rig's own rules (the NucBox chain)
 *   tables.js     the ranking, coverage, the second and third passes
 *   whenwhere.js  trips, waits, When & where, Offers around you, the glance
 *   render.js     the verdicts and the page, with page.css and page.js
 *                 (the page's style and script, real files read at build)
 *   csv.js        the tables as CSV
 *   io.js         the server, the NucBox, the GPS log, and the command
 *
 * This file keeps the whole analysis (analyse) and every name it exported
 * before the cut, so the suite, tools/report_check.js and tools/strategy.js
 * read it as before. The report was built on the invented 11,721-offer journal
 * before and after the cut: every CSV and the page the same to the byte
 * but the time it was made. */

'use strict';

var A = require('../advice.js');
var MV = require('../map-view.js');
// What $/hr to expect and what holding out paid (the Strategy tab), shared
// with the end-of-shift report so the two print one answer.
var S = require('./strategy.js');

var ST = require('./report/stats.js');
var PL = require('./report/place.js');
var TB = require('./report/tables.js');
var WW = require('./report/whenwhere.js');
var RN = require('./report/render.js');
var CSV = require('./report/csv.js');
var IO = require('./report/io.js');
var MIN_N = ST.MIN_N, MIN_OUTINGS = ST.MIN_OUTINGS, ALPHA = ST.ALPHA, SHUFFLES = ST.SHUFFLES,
    BOOTS = ST.BOOTS, GRID_MI = ST.GRID_MI, DROP_MIN_N = ST.DROP_MIN_N, NEXT_GAP_MIN = ST.NEXT_GAP_MIN,
    GPS_TIMED = ST.GPS_TIMED, minOf = ST.minOf, maxOf = ST.maxOf, counted = ST.counted, cellOf = ST.cellOf,
    VIEWS = ST.VIEWS;
var PLACE_APPROX_MI = PL.PLACE_APPROX_MI, gridOk = PL.gridOk, storeLabel = PL.storeLabel,
    placesOf = PL.placesOf;
var cells = TB.cells, coverage = TB.coverage, DESC_MIN_N = TB.DESC_MIN_N, REAL_MED_N = TB.REAL_MED_N,
    QUIET_DAYS = TB.QUIET_DAYS, SPELL_M = TB.SPELL_M, SPELL_MIN_S = TB.SPELL_MIN_S,
    SPELL_GAP_S = TB.SPELL_GAP_S, SPELL_MIN_N = TB.SPELL_MIN_N, appOf = TB.appOf, runsOf = TB.runsOf,
    realOf = TB.realOf, takesTable = TB.takesTable, waitsTable = TB.waitsTable, strandTable = TB.strandTable,
    busyTable = TB.busyTable, appsTable = TB.appsTable, ppmTable = TB.ppmTable, stackTable = TB.stackTable,
    quietTable = TB.quietTable, trendTable = TB.trendTable, restaurantNames = TB.restaurantNames,
    restaurantsTable = TB.restaurantsTable, TIER_MIN_N = TB.TIER_MIN_N, TAKE_SLACK_MS = TB.TAKE_SLACK_MS,
    DEAD_MAX_MIN = TB.DEAD_MAX_MIN, STOP_M = TB.STOP_M, STOP_MIN_S = TB.STOP_MIN_S,
    PRESS_AFTER_MIN = TB.PRESS_AFTER_MIN, PRESS_BEFORE_MIN = TB.PRESS_BEFORE_MIN,
    SHORT_MILES = TB.SHORT_MILES, tiersOf = TB.tiersOf, shareTest = TB.shareTest, goodTable = TB.goodTable,
    waitTable = TB.waitTable, deadOf = TB.deadOf, deadTable = TB.deadTable, sizeTable = TB.sizeTable,
    strategyOrders = TB.strategyOrders;
var timelineOf = WW.timelineOf, tripsOf = WW.tripsOf, dropTable = WW.dropTable,
    CREDIT_MAX_MIN = WW.CREDIT_MAX_MIN, waitingLine = WW.waitingLine, waitedTable = WW.waitedTable,
    reportRulers = WW.reportRulers, whenWhere = WW.whenWhere, aroundYou = WW.aroundYou,
    glanceOf = WW.glanceOf, CARD_FIX_AFTER_MIN = WW.CARD_FIX_AFTER_MIN, MOVED_MI = WW.MOVED_MI,
    emptyOf = WW.emptyOf, emptyTable = WW.emptyTable, fixDensity = WW.fixDensity;

/* --- the whole analysis, given placements --------------------------------
 *
 * `placed[i]` is offers[i]'s pickup answer { at, why, kind } (or undefined
 * for a row not asked about), `dropAt(t, o)` a taken trip's position or null. */

/* The line the driver judges against: the newest counted row's own target
 * not stamped after `now`, else 25 (journal.html render's and server.js
 * targetsOut's rule). */
function targetLine(counts, now) {
  var at = typeof now === 'number' && now > 0 ? now : Date.now();
  var sorted = counts.slice().sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
  for (var i = sorted.length - 1; i >= 0; i--) {
    if ((sorted[i].at || 0) <= at) return typeof sorted[i].target === 'number' ? sorted[i].target : 25;
  }
  return 25;
}

function analyse(offers, taken, placed, dropAt, opts) {
  opts = opts || {};
  // Filtered as pairs, so `placed` stays beside the row it answers.
  var pairs = (offers || []).map(function (o, i) { return [o, (placed || [])[i]]; })
    .filter(function (p) { return p[0] && typeof p[0] === 'object'; });
  offers = pairs.map(function (p) { return p[0]; });
  placed = pairs.map(function (p) { return p[1]; });
  var idx = new Map();
  offers.forEach(function (o, i) { idx.set(o, i); });
  function answer(o) {
    var r = placed[idx.get(o)];
    return r || { at: null, why: 'notext', kind: 'none' };
  }
  var pins = [];
  offers.forEach(function (o, i) {
    var r = placed[i];
    if (r && r.at) pins.push({ row: i, at: r.at, label: storeLabel(o.pickup), level: r.level, spread: r.spread || 0 });
  });
  var grouped = placesOf(pins);
  var cellBoxes = Object.create(null);
  function placeKey(o) { return grouped.byRow[idx.get(o)] || null; }
  function cellKey(o) {
    var r = answer(o);
    var c = gridOk(r) ? cellOf(r.at) : null;
    if (c) cellBoxes[c.id] = c;
    return c ? c.id : null;
  }
  function townKey(o) { return MV.townFor(o, A.area); }
  var names = restaurantNames(offers);
  function restKey(o) { return names.of(o); }
  function appKey(o) { return appOf(o); }
  var tiers = tiersOf(offers);
  var tierOf = tiers.of;

  var trips = tripsOf(offers, taken, dropAt);
  var runs = runsOf(taken);
  var byIdAll = Object.create(null);
  offers.forEach(function (o) { if (o && typeof o.id === 'string') byIdAll[o.id] = o; });
  if (opts.fixes) deadOf(trips, taken, byIdAll, opts.fixes);
  emptyOf(trips, taken, byIdAll, offers);
  // Where you waited (waitingLine): the cards that came with no order in the
  // car, by the car's own fix. Their cells join cellBoxes so the page names
  // them as it names every cell, by the cell's centre.
  var waiting = waitingLine(offers, taken, opts.cellTown, cellBoxes);
  var waitBy = new Map();
  waiting.forEach(function (w) { waitBy.set(w.o, w); });
  function waitCellKey(o) { var w = waitBy.get(o); return w ? w.cell : null; }
  function waitTownKey(o) { var w = waitBy.get(o); return w ? w.town : null; }
  // When & where: the same line, by the driver's weekday and block.
  var rulers = reportRulers(offers);
  var whenwhere = whenWhere(offers, waiting, rulers);
  // Offers around you: the same line drawn as dots, home left out (aroundYou).
  var around = aroundYou(offers, waiting, whenwhere);
  // The front page's when and where (round B; glanceOf).
  var glance = glanceOf(offers, waiting, rulers);
  var tookRuns = (taken || []).filter(function (t) { return t && typeof t.tookAt === 'number'; });
  // Spells parked with no order in the car (main reads them off the GPS
  // log): each to its 2-mile cell and, where the NucBox named one, the town
  // of that cell's centre; with the offers counted while there and the
  // minutes to the first the rig said take.
  var line = timelineOf(offers).filter(function (t) { return t.counted; });
  var spells = (opts.spells || []).map(function (sp) {
    var c = cellOf(sp);
    if (c) cellBoxes[c.id] = c;
    var during = line.filter(function (t) { return t.at >= sp.from && t.at <= sp.to; });
    var go = during.filter(function (t) { return t.go; })[0];
    var tops = during.map(function (t) { return { t: tierOf(t.o), o: t.o }; }).filter(function (x) { return x.t; });
    var t10 = tops.filter(function (x) { return x.t.top10; });
    var takes = tookRuns.filter(function (t) { return t.tookAt >= sp.from && t.tookAt <= sp.to + TAKE_SLACK_MS; })
      .map(function (t) { var rr = realOf(t); return { pay: t.pay, mins: rr ? rr.mins : null }; });
    return { from: sp.from, to: sp.to, cell: c ? c.id : null,
             town: c && opts.cellTown ? opts.cellTown[c.id] || null : null,
             seen: during.length, go: go ? (go.at - sp.from) / 60000 : null,
             goN: during.filter(function (t) { return t.go; }).length,
             top25N: tops.filter(function (x) { return x.t.top25; }).length, top10N: t10.length,
             top10Pay: t10.reduce(function (a, x) { return a + (typeof x.o.pay === 'number' ? x.o.pay : 0); }, 0),
             top10Min: t10.reduce(function (a, x) { return a + (typeof x.o.minutes === 'number' ? x.o.minutes : 0); }, 0),
             takes: takes };
  });
  function placeLabel(k) { return (grouped.places[k] && grouped.places[k].label) || k; }
  function cellLabel(k) {
    var c = cellBoxes[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : k;
  }
  function same(k) { return k; }
  var views = {};
  var diffs = null;
  VIEWS.forEach(function (v) {
    var rows = v === 'all' ? offers : offers.filter(function (o) { return A.blockOf(o.at) === v; });
    var tv = v === 'all' ? trips : trips.filter(function (t) { return A.blockOf(t.at) === v; });
    var hold = v === 'all';
    views[v] = {
      name: v === 'all' ? 'all hours' : A.BLOCK_NAMES[v],
      offers: rows.filter(counted).length,
      place: cells(rows, placeKey, { hold: hold, minN: opts.minN, keepDiffs: hold, tierOf: tierOf }),
      town: cells(rows, townKey, { hold: hold, minN: opts.minN, keepDiffs: hold, tierOf: tierOf }),
      grid: cells(rows, cellKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
      dropTown: dropTable(tv, 'town', hold),
      dropGrid: dropTable(tv, 'cell', hold),
      waitedTown: cells(rows, waitTownKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
      waitedGrid: cells(rows, waitCellKey, { hold: hold, minN: opts.minN, tierOf: tierOf }),
    };
    views[v].rest = restaurantsTable(rows, { key: restKey, placeKey: placeKey, places: grouped.places,
                                             names: names, runs: runs, waits: opts.waits, hold: hold,
                                             minN: opts.minN, placeCells: views[v].place, tierOf: tierOf });
    if (hold) {
      diffs = { place: views[v].place.diffs, town: views[v].town.diffs };
      delete views[v].place.diffs;
      delete views[v].town.diffs;
    }
  });
  // A dropoff cell is named only where the all-hours table names it.
  var namedCells = Object.create(null);
  views.all.dropGrid.groups.forEach(function (g) { namedCells[g.name] = g.box || cellBoxes[g.name] || null; });
  var dropBoxes = Object.create(null);
  trips.forEach(function (t) { if (t.cell && t.cellBox) dropBoxes[t.cell] = t.cellBox; });
  // A dropoff cell is named in the dead-miles table only over its floor
  // (deadTable drops the thinner ones), by its 2-mile cell's centre.
  function deadCellName(k) {
    var c = dropBoxes[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : 'a cell';
  }
  function dropCellName(k) {
    var c = namedCells[k];
    return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : 'a cell';
  }
  VIEWS.forEach(function (v) {
    var rows = v === 'all' ? offers : offers.filter(function (o) { return A.blockOf(o.at) === v; });
    var tv = v === 'all' ? trips : trips.filter(function (t) { return A.blockOf(t.at) === v; });
    var sv = v === 'all' ? spells : spells.filter(function (sp) { return A.blockOf(sp.from) === v; });
    var wv = v === 'all' ? waiting : waiting.filter(function (w) { return A.blockOf(w.at) === v; });
    views[v].more = {
      takesPlace: takesTable(rows, runs, placeKey, placeLabel, 'place'),
      takesTown: takesTable(rows, runs, townKey, same, 'town'),
      takesGrid: takesTable(rows, runs, cellKey, cellLabel, 'cell'),
      waits: waitsTable(rows, grouped.places, opts.waits, placeKey),
      strand: strandTable(rows, tv, placeKey, grouped.places, views[v].dropTown, namedCells, dropCellName),
      busyTown: busyTable(sv, 'town', same, 'town'),
      busyGrid: busyTable(sv, 'cell', cellLabel, 'cell'),
      appsPlace: appsTable(rows, runs, placeKey, placeLabel, 'place'),
      appsTown: appsTable(rows, runs, townKey, same, 'town'),
      appsGrid: appsTable(rows, runs, cellKey, cellLabel, 'cell'),
      ppmPlace: ppmTable(rows, placeKey, placeLabel, 'place'),
      ppmTown: ppmTable(rows, townKey, same, 'town'),
      ppmGrid: ppmTable(rows, cellKey, cellLabel, 'cell'),
      stack: stackTable(rows, placeKey, placeLabel),
      waitedAreaTown: waitedTable(wv, 'town', same, 'town where the car was'),
      waitedAreaGrid: waitedTable(wv, 'cell', cellLabel, 'cell where the car was'),
      emptyTown: emptyTable(tv, 'town', same, 'dropoff town'),
    };
    function restLabel(k) { return names.labels[k] || k; }
    views[v].best = {
      goodTown: goodTable(rows, townKey, same, 'town', tierOf),
      goodGrid: goodTable(rows, cellKey, cellLabel, 'cell', tierOf),
      goodRest: goodTable(rows, restKey, restLabel, 'restaurant', tierOf),
      goodApp: goodTable(rows, appKey, same, 'app', tierOf),
      waitTown: waitTable(sv, 'town', same, 'town'),
      waitGrid: waitTable(sv, 'cell', cellLabel, 'cell'),
      deadTown: deadTable(tv, 'town', same, 'dropoff town'),
      deadGrid: deadTable(tv, 'cell', deadCellName, 'dropoff cell'),
      sizeTown: sizeTable(rows, townKey, same, 'town', tierOf),
      sizeApp: sizeTable(rows, appKey, same, 'app', tierOf),
      sizeRest: sizeTable(rows, restKey, restLabel, 'restaurant', tierOf),
    };
  });
  // Top-tier share, all hours, hours held (shareTest).
  var shareTests = { town: shareTest(offers, townKey, tierOf, { minN: opts.minN }),
                     rest: shareTest(offers, restKey, tierOf, { minN: opts.minN }),
                     place: shareTest(offers, placeKey, tierOf, { minN: opts.minN }),
                     grid: shareTest(offers, cellKey, tierOf, { minN: opts.minN }) };
  var quiet = { place: quietTable(offers, placeKey, placeLabel, diffs.place, 'place'),
                town: quietTable(offers, townKey, same, diffs.town, 'town') };
  var trend = { place: trendTable(diffs.place, placeLabel, 'place'),
                town: trendTable(diffs.town, same, 'town') };
  var cov = coverage(offers, answer);
  var counts = offers.filter(counted);
  // The Targets tab's headline: advice.js's own computation, the one the
  // offers page shows (server.js targetsOut), over this report's offers and
  // takes, with the card's town as the rig's (townKey) and the report's real
  // time (realOf, which also counts a Drop it timed off the GPS).
  var targets = A.targets(offers, taken, {
    target: targetLine(counts, opts.now), key: townKey, shuffles: SHUFFLES,
    townFloor: typeof opts.minN === 'number' ? opts.minN : MIN_N,
    isTimed: function (t) { return realOf(t) !== null; },
    timedSaid: 'put down at the door by the GPS or the app\'s screen, a Drop the GPS finished, or a Drop this '
      + 'report timed off the GPS log'
  });
  // The Strategy tab: tools/strategy.js over every row (an untrusted card
  // still says the rig was on), this report's takes as its own realOf timed
  // them, the card's town as the area (townKey, as every town table here),
  // and the driver's line beside the curve.
  var strategyIn = strategyOrders(taken, opts.records, opts.fixes, opts.earnings);
  // ...and, where the server has them, the trips read off the app's own
  // earnings screenshots and matched to orders (/api/earnings): the card
  // against what was paid, under the curve.
  var strategy = S.analyse({ offers: offers, orders: strategyIn, areaOf: townKey, appOf: appOf,
                             // One ruler for section 7 and When & where.
                             rulers: rulers.byTop,
                             target: targetLine(counts, opts.now), boots: opts.boots,
                             earnings: Array.isArray(opts.earnings) ? opts.earnings : undefined,
                             // The Gold card's goal and Uber's own figures,
                             // as the offers page saved them (/api/gold).
                             gold: opts.gold || undefined });
  strategy.miles = { odometer: strategyIn.filter(function (o) { return o.milesFrom === 'odometer'; }).length,
                     uber: strategyIn.filter(function (o) { return o.timedBy === 'uber'; }).length,
                     log: strategyIn.filter(function (o) { return o.milesFrom === 'log'; }).length,
                     records: (opts.records || []).length, gps: !!opts.fixes };
  var times = counts.map(function (o) { return o.at; }).filter(isFinite);
  return {
    // A time given is the time, 0 included: `opts.now || Date.now()` read the
    // suite's { now: 0 } as none and stamped the clock.
    made: typeof opts.now === 'number' ? opts.now : Date.now(),
    span: times.length ? [minOf(times), maxOf(times)] : null,
    outings: A.outingsIn(counts),
    minN: typeof opts.minN === 'number' ? opts.minN : MIN_N,
    dropMinN: DROP_MIN_N, minOutings: MIN_OUTINGS, alpha: ALPHA, shuffles: SHUFFLES,
    boots: BOOTS, gridMi: GRID_MI, nextGapMin: NEXT_GAP_MIN,
    taken: (taken || []).length,
    trips: {
      n: trips.length,
      gps: trips.filter(function (t) { return t.how === 'gps'; }).length,
      pin: trips.filter(function (t) { return t.how === 'pin'; }).length,
      town: trips.filter(function (t) { return t.town; }).length,
      ended: trips.filter(function (t) { return t.next.censored; }).length,
      cardFix: trips.filter(function (t) { return t.how === 'card fix'; }).length,
      empty: trips.filter(function (t) { return t.empty && !t.empty.censored; }).length,
    },
    waited: { cards: waiting.length, fixed: waiting.filter(function (w) { return w.fix; }).length,
              towns: waiting.filter(function (w) { return w.town; }).length,
              creditMaxMin: CREDIT_MAX_MIN, movedMi: MOVED_MI, cardFixAfterMin: CARD_FIX_AFTER_MIN,
              density: fixDensity(offers) },
    coverage: cov,
    quiet: quiet, trend: trend,
    takes: { taken: (taken || []).length, onCounted: offers.filter(function (o) { return counted(o) && runs[o.id]; }).length,
             timed: (taken || []).filter(function (t) { return realOf(t); }).length,
             gpsTimed: (taken || []).filter(function (t) { return t && t.by === GPS_TIMED; }).length,
             pressed: (taken || []).filter(function (t) {
               return t && (t.by === 'drop' || t.by === 'chooser' || t.by === GPS_TIMED);
             }).length },
    spells: { n: spells.length, hours: Math.round(spells.reduce(function (s2, sp) { return s2 + (sp.to - sp.from); }, 0) / 3.6e5) / 10,
              towns: spells.filter(function (sp) { return sp.town; }).length, gps: !!opts.spells },
    waitsOnRecord: (opts.waits || []).length, waitsFrom: opts.waitsFrom || null,
    descMinN: DESC_MIN_N, realMedN: REAL_MED_N, quietDays: QUIET_DAYS, spellM: SPELL_M,
    spellMinS: SPELL_MIN_S, spellGapS: SPELL_GAP_S, spellMinN: SPELL_MIN_N,
    best: { thresholds: tiers.th, share: shareTests, tierMinN: TIER_MIN_N, spellMinN: SPELL_MIN_N,
            takeSlackMin: TAKE_SLACK_MS / 60000, deadMaxMin: DEAD_MAX_MIN,
            dead: { gps: !!opts.fixes, n: trips.filter(function (t) { return t.dead && !t.dead.censored; }).length },
            presses: opts.presses || null, stopM: STOP_M, stopMinS: STOP_MIN_S, pressAfterMin: PRESS_AFTER_MIN,
            shortMiles: SHORT_MILES,
            pressBeforeMin: PRESS_BEFORE_MIN, placeApproxMi: PLACE_APPROX_MI, areaMi: MV.AREA_MI,
            region: opts.region ? { box: opts.region.box, fixes: opts.region.fixes, marginMi: opts.region.marginMi,
                                    miles: opts.region.disc.miles } : null,
            streets: opts.streetsSaid || null, road: opts.roadSaid || null },
    targets: targets,
    whenwhere: whenwhere,
    around: around,
    glance: glance,
    strategy: strategy,
    places: grouped.places,
    restNames: names.labels,
    cells: cellBoxes,
    views: views,
    source: opts.source || null,
  };
}

module.exports = {
  waitingLine: WW.waitingLine, waitedTable: WW.waitedTable, nextOffer: WW.nextOffer,
  cardFixAfter: WW.cardFixAfter, emptyOf: WW.emptyOf, emptyTable: WW.emptyTable, fixDensity: WW.fixDensity,
  goodOf: WW.goodOf, CREDIT_MAX_MIN: WW.CREDIT_MAX_MIN, MOVED_MI: WW.MOVED_MI,
  CARD_FIX_AFTER_MIN: WW.CARD_FIX_AFTER_MIN, MIN_N: ST.MIN_N, DROP_MIN_N: ST.DROP_MIN_N, GRID_MI: ST.GRID_MI,
  NEXT_GAP_MIN: ST.NEXT_GAP_MIN, VIEWS: ST.VIEWS, pickupKind: PL.pickupKind, placePickup: PL.placePickup,
  placeDropoff: PL.placeDropoff, storeLabel: PL.storeLabel, printedDoor: PL.printedDoor, placeRow: PL.placeRow,
  heldEndsOf: PL.heldEndsOf, afterFor: PL.afterFor, AFTER_GPS_WIDEN_MI: PL.AFTER_GPS_WIDEN_MI,
  placesOf: PL.placesOf, cellOf: ST.cellOf, bootCI: ST.bootCI, minOf: ST.minOf, maxOf: ST.maxOf,
  cells: TB.cells, coverage: TB.coverage, nextTake: WW.nextTake, timelineOf: WW.timelineOf,
  tripsOf: WW.tripsOf, dropTable: WW.dropTable, analyse: analyse, summary: RN.summary, testLine: RN.testLine,
  html: RN.html, csvOf: CSV.csvOf, dropCsv: CSV.dropCsv, paidSection: RN.paidSection,
  loadEarnings: IO.loadEarnings, coverageCsv: CSV.coverageCsv, restCsv: CSV.restCsv,
  restBranchCsv: CSV.restBranchCsv, nameOf: TB.nameOf, restaurantNames: TB.restaurantNames,
  restaurantsTable: TB.restaurantsTable, waitOf: TB.waitOf, hitsOf: IO.hitsOf, nbxFetch: IO.nbxFetch,
  degraded: IO.degraded, DEGRADED_SHARE: IO.DEGRADED_SHARE, DEGRADED_MIN: IO.DEGRADED_MIN, gpsAt: IO.gpsAt,
  parseArgs: IO.parseArgs, DESC_MIN_N: TB.DESC_MIN_N, REAL_MED_N: TB.REAL_MED_N, QUIET_DAYS: TB.QUIET_DAYS,
  SPELL_M: TB.SPELL_M, SPELL_MIN_S: TB.SPELL_MIN_S, SPELL_GAP_S: TB.SPELL_GAP_S, SPELL_MIN_N: TB.SPELL_MIN_N,
  REAL_BY: TB.REAL_BY, FINISHED: ST.FINISHED, EARLY_LOOK: TB.EARLY_LOOK, MULTI_ORDER: TB.MULTI_ORDER,
  MANY_DROPOFFS: TB.MANY_DROPOFFS, MORE_CSVS: CSV.MORE_CSVS, payPerMile: TB.payPerMile, appOf: TB.appOf,
  flagsOf: TB.flagsOf, wilson: TB.wilson, poissonLE: TB.poissonLE, isoWeek: TB.isoWeek, runsOf: TB.runsOf,
  realOf: TB.realOf, takesTable: TB.takesTable, waitsTable: TB.waitsTable, strandTable: TB.strandTable,
  busyTable: TB.busyTable, appsTable: TB.appsTable, ppmTable: TB.ppmTable, stackTable: TB.stackTable,
  quietTable: TB.quietTable, trendTable: TB.trendTable, spellsOf: TB.spellsOf, heldOf: TB.heldOf,
  gpsFixes: IO.gpsFixes, gpsLog: IO.gpsLog, cellTownOf: IO.cellTownOf, tableCsv: CSV.tableCsv, inside: IO.inside,
  realish: IO.realish, outingOf: ST.outingOf, main: IO.main, printedTown: PL.printedTown,
  regionOf: PL.regionOf, wordsOf: PL.wordsOf, WHY: PL.WHY, isPoint: PL.isPoint, gridOk: PL.gridOk,
  PLACE_APPROX_MI: PL.PLACE_APPROX_MI, REGION_MARGIN_MI: PL.REGION_MARGIN_MI, quantile: TB.quantile,
  qOf: TB.qOf, tiersOf: TB.tiersOf, topOf: TB.topOf, timePresses: TB.timePresses, stillRuns: TB.stillRuns,
  shareTest: TB.shareTest, goodTable: TB.goodTable, waitTable: TB.waitTable, deadOf: TB.deadOf,
  deadTable: TB.deadTable, sizeTable: TB.sizeTable, bestLines: TB.bestLines, targetLine: targetLine,
  targetAreaLines: RN.targetAreaLines, shareCsv: CSV.shareCsv, levelsCsv: CSV.levelsCsv,
  strategyOrders: TB.strategyOrders, recordFor: TB.recordFor, milesBetween: TB.milesBetween,
  strategyCsv: CSV.strategyCsv, RECORD_MATCH_MS: TB.RECORD_MATCH_MS, streetsBase: IO.streetsBase,
  loadWaits: IO.loadWaits, GPS_TIMED: ST.GPS_TIMED, TIER_MIN_N: TB.TIER_MIN_N, STOP_M: TB.STOP_M,
  STOP_MIN_S: TB.STOP_MIN_S, PRESS_AFTER_MIN: TB.PRESS_AFTER_MIN, PRESS_BEFORE_MIN: TB.PRESS_BEFORE_MIN,
  SHORT_MILES: TB.SHORT_MILES, DEAD_MAX_MIN: TB.DEAD_MAX_MIN, SIZE_BANDS: TB.SIZE_BANDS,
  TAKE_SLACK_MS: TB.TAKE_SLACK_MS, GROUPS: RN.GROUPS, TABS: RN.TABS, blockChart: RN.blockChart, fold: RN.fold,
  bootCIPlain: ST.bootCIPlain, loadJournal: IO.loadJournal, JOURNAL_PAGE: IO.JOURNAL_PAGE,
  whenWhere: WW.whenWhere, reportRulers: WW.reportRulers, wwSlotOf: WW.wwSlotOf, poissonCI: WW.poissonCI,
  WW_BLOCKS: WW.WW_BLOCKS, WW_TOPS: WW.WW_TOPS, aroundYou: WW.aroundYou, homeOf: WW.homeOf,
  glanceOf: WW.glanceOf, glanceSection: RN.glanceSection, gridCell: ST.gridCell, HOME_MI: WW.HOME_MI,
  AROUND_BIN_MI: WW.AROUND_BIN_MI, AROUND_BIN_DAYS: WW.AROUND_BIN_DAYS, AROUND_RINGS: WW.AROUND_RINGS,
  PICKUP_BANDS: WW.PICKUP_BANDS, WW_TOP: WW.WW_TOP, WW_MIN_HOURS: WW.WW_MIN_HOURS, WW_MIN_DAYS: WW.WW_MIN_DAYS,
  WW_CONF: WW.WW_CONF,
};

if (require.main === module) IO.main(process.argv.slice(2));
