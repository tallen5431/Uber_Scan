/* The places report's words and page: the one-line verdicts it prints,
 * the Targets tab's area lines, and the page with every tab, its style
 * (page.css) and its script (page.js) beside this file. Formatting only:
 * every figure here was worked out by analyse (tools/places_report.js). */

'use strict';

var fs = require('fs');
var path = require('path');

var A = require('../../advice.js');
var MV = require('../../map-view.js');
// What $/hr to expect and what holding out paid (the Strategy tab), shared
// with the end-of-shift report so the two print one answer.
var S = require('../strategy.js');

var ST = require('./stats.js');
var TB = require('./tables.js');
var WW = require('./whenwhere.js');
var MIN_OUTINGS = ST.MIN_OUTINGS, PLACE_SAME_MI = ST.PLACE_SAME_MI, pText = ST.pText,
    shareName = ST.shareName, pct = ST.pct, labelOf = ST.labelOf;
var SPELL_MIN_N = TB.SPELL_MIN_N, TIER_MIN_N = TB.TIER_MIN_N, Q_BOOT_MAX = TB.Q_BOOT_MAX,
    bestLines = TB.bestLines;
var WW_DAYS = WW.WW_DAYS, WW_MIN_HOURS = WW.WW_MIN_HOURS, WW_MIN_DAYS = WW.WW_MIN_DAYS;

/* --- the one-line verdicts ------------------------------------------------ */

function testLine(what, c) {
  if (c.p === null) {
    return what + ': not tested — ' + c.groups.length + ' cell(s) clear the floor of ' + c.floor
      + ' offers on ' + c.outings + ' outings; ' + c.thin.length + ' under it.';
  }
  return what + ': ' + c.groups.length + ' cells, ' + c.kept + ' offers, '
    + (c.held ? 'hours held still, ' : '') + pText(c.p)
    + (c.held && c.rawP !== null ? ' (' + pText(c.rawP) + ' with the hour left in)' : '')
    + ' — ' + (c.significant ? 'beats chance' : 'NOT distinguishable from chance') + '.';
}

function summary(r) {
  var out = [];
  var cv = r.coverage, all = r.views.all;
  out.push('Offers counted: ' + cv.offers + ' over ' + r.outings + ' shift days'
           + (r.source && r.source.truncated ? '  (THE SERVER CUT THE WINDOW: ' + r.source.count
              + ' of ' + r.source.total + ' — use --since)' : ''));
  out.push('Pickups placed: ' + cv.all.placed.n + ' of ' + (cv.all.placed.n + cv.all.unplaced.n)
           + ' (' + pct(cv.all.placed.n, cv.all.placed.n + cv.all.unplaced.n) + ')');
  (cv.levels || []).forEach(function (l) {
    out.push('  placed at ' + l.level + ' level' + (l.point ? '' : ' (approximate)') + ': ' + l.n
             + (l.region ? ' (' + l.region + ' in the region box, no fix)' : '')
             + (l.refused ? '  [stood in for: ' + l.refused + ']' : ''));
  });
  cv.why.forEach(function (w) { out.push('  unplaced, ' + w.why + ': ' + w.n); });
  if (cv.all.gapPerHour !== null) {
    out.push('Placed pay $' + cv.all.placed.perHour.toFixed(2) + '/hr, unplaced $'
             + cv.all.unplaced.perHour.toFixed(2) + '/hr: the map leaves out offers paying '
             + (cv.all.gapPerHour >= 0 ? '$' + cv.all.gapPerHour.toFixed(2) + '/hr less'
                : '$' + (-cv.all.gapPerHour).toFixed(2) + '/hr more')
             + ' (' + pText(cv.all.p) + ')');
  }
  if (cv.points && cv.points.gapPerHour !== null && cv.levels && cv.levels.some(function (l) { return !l.point; })) {
    out.push('  points only (door, corner, name) against the unplaced: $' + cv.points.placed.perHour.toFixed(2) + '/hr vs $'
             + cv.points.unplaced.perHour.toFixed(2) + '/hr (' + pText(cv.points.p) + ')');
  }
  if (r.best) {
    var thr = Object.keys(r.best.thresholds).sort(function (a, b) { return a - b; });
    out.push('Top-tier thresholds (every offer in its own 3-hour block; ' + TIER_MIN_N + ' offers for one):');
    thr.forEach(function (k) {
      var t = r.best.thresholds[k];
      out.push('  ' + A.BLOCK_NAMES[Number(k)] + ': top 25% >= $' + t.p75.toFixed(2) + '/hr, top 10% >= $'
               + t.p90.toFixed(2) + '/hr  (n=' + t.n + ')');
    });
    if (!thr.length) out.push('  none: no block has ' + TIER_MIN_N + ' offers');
    [['town', 'Towns'], ['rest', 'Restaurants'], ['place', 'Places'], ['grid', r.gridMi + '-mile grid']].forEach(function (k) {
      var t = r.best.share[k[0]];
      out.push('Top-10% share, ' + k[1] + ': ' + (t.p === null ? 'not tested (' + t.groups.length + ' over the floor)'
               : t.groups.length + ' groups, hours held, ' + pText(t.p) + ' — '
                 + (t.significant ? 'beats chance' : 'NOT distinguishable from chance')));
      t.groups.filter(function (g) { return g.beats; }).forEach(function (g) {
        out.push('  ' + shareName(r, k[0], g.name) + '  ' + Math.round(g.top10 * 100) + '% top 10% vs '
                 + Math.round(g.expect * 100) + '% for the others, same hours [' + (g.sci[0] * 100).toFixed(1) + ', '
                 + (g.sci[1] * 100).toFixed(1) + ' points], n=' + g.n);
      });
    });
  }
  if (r.strategy) {
    out.push('Strategy (descriptive; the Strategy tab):');
    r.strategy.lines.forEach(function (l) { out.push('  ' + l); });
  }
  out.push(testLine('Places', all.place));
  if (all.rest) {
    out.push('Restaurants, by the name on the card, placed or not: ' + all.rest.groups.length + ' ranked of '
             + all.rest.names + ' names (' + all.rest.thin.length + ' too few), ' + all.rest.named + ' offers named, '
             + all.rest.placed + ' of them placed; ' + all.rest.noName + ' pickups printed no name (a door or a street)');
    out.push(testLine('Restaurants', all.rest));
  }
  out.push(testLine('Towns', all.town));
  out.push(testLine(r.gridMi + '-mile grid', all.grid));
  out.push(testLine('Wait after a drop, by town', all.dropTown));
  if (r.takes) {
    out.push('Taken: ' + r.takes.taken + ' orders, ' + r.takes.timed + ' timed at the door (GPS, screen, or a press '
             + 'the GPS log timed), ' + r.takes.pressed + ' put down by a press: ' + r.takes.gpsTimed
             + ' of them GPS-timed, ' + (r.takes.pressed - r.takes.gpsTimed) + ' not timed');
  }
  if (r.spells && r.spells.gps) out.push('Spells parked with no order in the car: ' + r.spells.n + ', ' + r.spells.hours + ' h');
  ['place', 'town'].forEach(function (k) {
    var q = r.quiet && r.quiet[k];
    (q && q.rows || []).filter(function (x) { return x.flag; }).forEach(function (x) {
      out.push('Gone quiet (' + k + '): ' + x.name + ' — ' + x.flag + ', last offer ' + x.last);
    });
  });
  ['place', 'rest', 'town', 'grid'].forEach(function (k) {
    var beat = all[k] ? all[k].groups.filter(function (g) { return g.beats; }) : [];
    if (!beat.length) return;
    out.push('Clear of the rest (' + (k === 'rest' ? 'restaurant' : k) + '):');
    beat.forEach(function (g) {
      out.push('  ' + labelOf(r, k, g.name) + '  ' + (g.score >= 0 ? '+' : '') + g.score.toFixed(2)
               + ' $/hr vs same hours elsewhere [' + g.sci[0].toFixed(2) + ', ' + g.sci[1].toFixed(2)
               + '], n=' + g.n);
    });
  });
  return out.join('\n');
}

/* The Targets tab's richer area lines, per hours view, off what the report
 * already worked out: the places, restaurants and 2-mile cells that beat
 * chance with their interval clear of zero (cells' `beats`), and, where the
 * GPS gave waiting spells, the town to wait in by top-10% offers an hour and
 * what working it paid (waitTable). Nothing new is tested here. */
function targetAreaLines(r) {
  var out = [];
  var views = ['all'].concat((r.targets.blocks || []).map(function (b) { return b.block; }));
  views.forEach(function (v) {
    var view = r.views[v];
    if (!view) return;
    var bits = [];
    [['place', 'places', view.place], ['rest', 'restaurants', view.rest], ['grid', r.gridMi + '-mile cells', view.grid]]
      .forEach(function (k) {
        var c = k[2];
        if (!c) return;
        var up = (c.groups || []).filter(function (g) { return g.beats && g.clear === 'above'; });
        if (c.p === null) bits.push(k[1] + ': not enough yet');
        else if (!c.significant) bits.push(k[1] + ': none beats chance (' + pText(c.p) + ')');
        else if (!up.length) bits.push(k[1] + ': differ beyond chance (' + pText(c.p) + '), none clearly better');
        else {
          bits.push(k[1] + ': ' + up.slice(0, 3).map(function (g) {
            return shareName(r, k[0], g.name) + ' (+$' + g.score.toFixed(2) + '/hr'
              + (g.top10 !== null && g.top10 !== undefined ? ', ' + Math.round(g.top10 * 100) + '% top-10%' : '') + ')';
          }).join('; '));
        }
      });
    var waits = (view.best && view.best.waitTown ? view.best.waitTown.rows : []).filter(function (w) {
      return w.top10PerHour !== null && (v === 'all' || w.block === A.BLOCK_NAMES[v]);
    }).sort(function (a, b) { return b.top10PerHour - a.top10PerHour; });
    if (!r.spells.gps) bits.push('waiting: no GPS log reached this report');
    else if (!waits.length) bits.push('waiting: no town has ' + SPELL_MIN_N + ' spells on ' + MIN_OUTINGS + ' shift days');
    else {
      bits.push('waiting: ' + waits.slice(0, 2).map(function (w) {
        return w.name + (v === 'all' ? ' (' + w.block + ')' : '') + ' ' + w.top10PerHour.toFixed(2)
          + ' top-10% offers an hour waiting, working it paid '
          + (w.expected === null ? '—' : '$' + w.expected.toFixed(2) + '/hr') + ' (' + w.n + ' spells)';
      }).join('; '));
    }
    out.push((v === 'all' ? 'All hours' : A.BLOCK_NAMES[v]) + ' — ' + bits.join('; ') + '.');
  });
  return out;
}

/* --- the page ------------------------------------------------------------ */

function esc(s) {
  return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function money(v) { return v === null || v === undefined ? '—' : '$' + v.toFixed(2); }

function banner(r) {
  var cv = r.coverage.all, all = r.views.all;
  var total = cv.placed.n + cv.unplaced.n;
  var lines = [];
  lines.push('<b>Offered, not earned.</b> Every figure is what the cards offered; most offers were passed. '
             + 'It is where good offers <i>start</i>, not where to sit and wait.');
  lines.push('<b>It ranks only places near where you already wait.</b> The apps send offers from near the car, '
             + 'so a place you never wait near cannot show up here, good or bad.');
  lines.push('<b>' + pct(cv.unplaced.n, total) + ' of pickups could not be placed</b> ('
             + cv.unplaced.n + ' of ' + total + ': chains with several branches inside the card\'s reach, '
             + 'cards with no GPS fix, names the map does not hold). '
             + (cv.gapPerHour === null ? ''
                : 'They paid a median ' + money(cv.unplaced.perHour) + '/hr against ' + money(cv.placed.perHour)
                  + '/hr for the placed ones (' + pText(cv.p) + '), so the place and grid tables describe a '
                  + (cv.gapPerHour > 0 ? 'better' : cv.gapPerHour < 0 ? 'worse' : 'similar')
                  + '-paying slice than your whole record. The town and restaurant tables do not need a pin and are '
                  + 'not cut this way.'));
  lines.push('<b>Significance:</b> ' + esc(testLine('places', all.place)) + ' '
             + esc(testLine('restaurants', all.rest)) + ' '
             + esc(testLine('towns', all.town)) + ' ' + esc(testLine(r.gridMi + '-mile grid', all.grid)));
  return lines.map(function (l) { return '<p>' + l + '</p>'; }).join('\n');
}

/* Leaflet off unpkg, pinned by the digests map-view.js's needLeaflet checks
 * (MV.LEAFLET_SRI, one copy): the page holds the record's places and
 * figures, and a CDN that served anything else — compromised, or a man in
 * the middle — gets no script run in it. The page loaded it bare until the
 * reporting review's round 2. crossorigin because a browser checks an
 * integrity only on a CORS fetch; unpkg answers with Allow-Origin *. */
var LEAFLET_CSS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
var LEAFLET_JS = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
function pinnedAt(url) {
  if (!MV.LEAFLET_SRI[url]) throw new Error('map-view.js pins no digest for ' + url);
  return ' integrity="' + MV.LEAFLET_SRI[url] + '" crossorigin="anonymous"';
}

function html(r) {
  // The page's data is the report, plus which tabs the Hours picker reaches
  // (GROUPS' fourth field), so the script does not keep a second list.
  var hourly = [];
  GROUPS.forEach(function (g) { g[2].forEach(function (t) { if (t[3]) hourly.push(t[0]); }); });
  // The page reads no single wait (the reporting review's R3): section 7's
  // lists of every wait, kept on the analysis for a check that wants them,
  // are left out of the page's data, where nothing read them.
  var data = JSON.stringify(Object.assign({}, r, { hourly: hourly }), function (k, v) {
    return k === 'minutes' && v && Array.isArray(v.good) && Array.isArray(v.take) ? undefined : v;
  }).replace(/</g, '\\u003c');
  // Both ends as driver days (advice.js dayKeyOf, the 4am day every tab
  // counts by). They were the UTC dates: an evening's last offer after 8pm in
  // New York is the next day in UTC, and a 2am one the day after the shift,
  // so the range ran a day past the tabs' own.
  var span = r.span ? A.dayKeyOf(r.span[0]) + ' to ' + A.dayKeyOf(r.span[1]) : 'no offers';
  var cvAll = r.coverage.all, placedTotal = cvAll.placed.n + cvAll.unplaced.n;
  // Every section, keyed by its tab, so they can be written in the nav's
  // order whatever order they were built in: a reader paging through the
  // source, or a screen reader, meets them as the tabs list them.
  var SEC = Object.create(null);
  SEC.overview = OVERVIEW_SECTION(r, span);
  SEC.targets = TARGETS_SECTION(r);
  SEC.strategy = STRATEGY_SECTION(r);
  SEC.best = BEST_SECTION(r);
  SEC.whenwhere = WHENWHERE_SECTION(r);
  SEC.around = AROUND_SECTION(r);
  SEC.places = '<section data-tab="places"><h2>Places — a store at a location</h2><p class="note">A place is a pin at door, '
    + 'corner or name level, or an approximate placement where it is that store\'s: within ' + PLACE_SAME_MI
    + ' mi of a door or name pin of the same store, or its own candidates no more than ' + r.best.placeApproxMi
    + ' mi apart (see Coverage for every level). <b>P75 / P90</b> are the 75th and 90th percentiles of the '
    + 'place\'s $/hr; <b>top 10%</b> is the share of its offers at or over the 90th percentile of every offer in '
    + 'their own three hours. Click a heading to sort.</p><p class="note" id="placeTest"></p>'
    + '<div id="placePlot" class="plot"></div>'
    + fold('placesTable', 'The table, every place over the floor', '<div id="placeTable"></div>')
    + fold('placesThin', 'Too few to rank', '<div id="placeThin" class="thin"></div>') + '</section>\n';
  SEC.restaurants = '<section data-tab="restaurants"><h2>Restaurants — by the name on the card, placed or not</h2>'
    + '<p class="note">One row per name, every branch together: the pickup\'s name as the card printed it (Uber\'s '
    + 'bracketed street off), merged by the rig\'s own store-name rule (Assemble.storeKey: case, marks and a '
    + '“ – Town” tail aside; Assemble.sameStore: one i/l slip). <b>No map pin is needed</b>, so this holds the bare '
    + 'names the Places tab cannot place (chains with several branches in reach, cards with no fix): '
    + '<span id="restCover"></span> A branch\'s own label (“#1155”) is its own name, as the rig reads it. '
    + 'Ranked as the other tables are: ' + r.minN + ' offers on ' + r.minOutings + ' shift days, the score '
    + 'against the other ranked restaurants in the same three-hour block, colour only where the test beats chance '
    + 'and the interval is clear of zero. <b>Your take</b> is the share you took; <b>real $/hr</b> only on orders '
    + 'put down at the door by the GPS or the screen (a median needs ' + r.realMedN + '); the <b>wait</b> only where '
    + 'the name cannot be a guess — for a chain the wait is per branch, and the waits on record carry no place, so '
    + 'a chain\'s branches go without. <b>$/mi is for reading, not an accept rule.</b> Click ▸ for the placed '
    + 'branches; click a heading to sort.</p>'
    + '<p class="note" id="restTest"></p><div id="restPlot" class="plot"></div>'
    + fold('restTableFold', 'The table, every restaurant over the floor', '<div id="restTable"></div>')
    + '<div id="restThin"></div></section>\n';
  SEC.map = '<section data-tab="map"><h2>Map</h2><p class="note">One dot per place, sized by its offers. Coloured only where it '
    + 'beats chance: <span class="k up">●</span> pays more than the same hours elsewhere, '
    + '<span class="k down">●</span> less; <span class="k grey">●</span> not distinguishable from the rest; '
    + 'small hollow dots are too few to rank. Squares are the ' + r.gridMi + '-mile grid, by the same rule.</p>'
    + '<div id="map"></div></section>\n';
  SEC.towns = '<section data-tab="towns"><h2>Towns — the card\'s own town</h2><p class="note">The town the card printed, dropoff first and '
    + 'then pickup, the rule the rig\'s map ranks towns by (map-view.js townFor). No geocoder.</p>'
    + '<p class="note" id="townTest"></p><div id="townPlot" class="plot"></div>'
    + fold('townsTable', 'The table, every town over the floor', '<div id="townTable"></div>')
    + fold('townsThin', 'Too few to rank', '<div id="townThin" class="thin"></div>') + '</section>\n';
  SEC.grid = '<section data-tab="grid"><h2>' + r.gridMi + '-mile grid — by the pickup\'s pin</h2><p class="note">Every '
    + 'placement level, an approximate one only where its candidates lie within ' + r.best.areaMi + ' mi of each '
    + 'other (the rig\'s general area, half a cell).</p><p class="note" id="gridTest"></p>'
    + '<div id="gridPlot" class="plot"></div>'
    + fold('gridTableFold', 'The table, every cell over the floor', '<div id="gridTable"></div>')
    + fold('gridThinFold', 'Too few to rank', '<div id="gridThin" class="thin"></div>') + '</section>\n';
  SEC.after = '<section data-tab="after"><h2>Where trips leave you</h2><p class="note">For each order you took and put down at the door: '
    + 'how long until the next offer the rig said <b>take</b>, and what it paid. Placed by the GPS log at the drop '
    + '(' + r.trips.gps + ' trips) or the dropoff\'s door inside its card\'s reach (' + r.trips.pin + '); the town '
    + 'off the card for the town table (' + r.trips.town + '). A silence longer than ' + r.nextGapMin
    + ' minutes before one came is you stopping, counted as "ended", not as a long wait. Counted by area only: '
    + 'no dropoff is named, and a grid cell with fewer than ' + r.dropMinN + ' trips is not shown at all. '
    + r.trips.n + ' trips in all.</p>'
    + '<p class="note" id="dropTest"></p>'
    + fold('afterTown', 'By town', '<div id="dropTown"></div>')
    + fold('afterGrid', 'By ' + r.gridMi + '-mile cell', '<div id="dropGrid"></div>') + '</section>\n';
  var wd = r.waited, dn = wd.density;
  SEC.waited = '<section data-tab="waited"><h2>Where you waited — by the car\'s own fix when each card came up</h2>'
    + '<p class="exp">Offered, not earned. Offers are dispatched near the car, so this compares only places you already '
    + 'wait in; it cannot say a place you never tried would pay, nor whether an area is good for its wait or for where '
    + 'its trips go.</p>'
    + '<p class="note">The cards that came with no taken order in the car (' + wd.cards + '), placed by the GPS fix the '
    + 'gate passed on each card (' + wd.fixed + ' of them; ' + dn.refused + ' fixes refused by the gate, the rest had '
    + 'none). By the ' + r.gridMi + '-mile cell the car was in, and by that cell\'s town (the NucBox map\'s name for '
    + 'its centre: ' + wd.towns + ' cards named). <b>Ranked</b> as every ranked table is: each offer against the other '
    + 'cells in its own three-hour block, ' + r.minN + ' offers on ' + r.minOutings + ' shift days, colour only where '
    + 'the grouping beats chance and the cell\'s interval is clear of zero.</p>'
    + '<p class="note" id="waitedTownTest"></p><div id="waitedTownPlot" class="plot"></div>'
    + fold('waitedTownFold', 'Towns where the car was, ranked', '<div id="waitedTownTable"></div><div id="waitedTownThin" class="thin"></div>')
    + '<p class="note" id="waitedGridTest"></p><div id="waitedGridPlot" class="plot"></div>'
    + fold('waitedGridFold', r.gridMi + '-mile cells where the car was, ranked',
           '<div id="waitedGridTable"></div><div id="waitedGridThin" class="thin"></div>')
    + '<h3>Per area and hours: time there, offers an hour, the share that cleared your target</h3>'
    + '<p class="exp">Experimental, descriptive: counts, medians and intervals, not ranked or coloured.</p>'
    + '<p class="note"><b>Hours there are inferred</b>: each card\'s time to the next card, at most '
    + wd.creditMaxMin + ' minutes and none across a silence over ' + r.nextGapMin + ', credited to where the car was at '
    + 'the earlier card (the Busy tab\'s spells, off the GPS log, are the measured version). <b>Cleared target</b> is '
    + 'the card\'s $/hr at or over the target the panel judged it by. A <b>stay</b> is consecutive cards in one area '
    + 'with no silence; its minutes to the first card at target start at its first CARD, not at arrival, so a stay '
    + 'whose first card was at target reads 0. At target is each card\'s own target at the time, not the top-X% '
    + '"good" of When &amp; where and section 7. Figures at ' + r.descMinN + ' offers on ' + r.minOutings + ' shift days.</p>'
    + fold('f-waitedAreaTown', 'By town', '<div id="m-waitedAreaTown"></div>')
    + fold('f-waitedAreaGrid', 'By ' + r.gridMi + '-mile cell', '<div id="m-waitedAreaGrid"></div>')
    + '<h3>From a drop to the next Took</h3>'
    + '<p class="note">How dense the record\'s positions are between jobs: offer rows are the only journal rows with a '
    + 'fix (seen and health rows carry none; order rows carry a total, not a track). Good card fixes in this window: '
    + dn.fixed + ' of ' + dn.offers + ' counted offers, one every ' + (dn.gapMedian === null ? '—' : dn.gapMedian + ' min')
    + ' at the median within a run (P90 ' + (dn.gapP90 === null ? '—' : dn.gapP90 + ' min') + '; '
    + (dn.over5 === null ? '—' : Math.round(dn.over5 * 100) + '%') + ' of gaps over 5 min). So the two ends are known — '
    + 'where the drop left the car (the GPS log, the dropoff\'s door, or the first card within ' + wd.cardFixAfterMin
    + ' min after: ' + r.trips.cardFix + ' trips) and where the car was when the next order was taken (that card\'s '
    + 'fix) — and the path between them only through the cards: <b>a lower bound, not miles driven</b> (the Best tab\'s '
    + 'dead miles, off the GPS log, are that). <b>Moved</b> = the ends more than ' + wd.movedMi + ' mi apart. '
    + r.trips.empty + ' trips measured; a dropoff town under ' + r.dropMinN + ' is not named.</p>'
    + fold('f-emptyTown', 'Moved against stayed, and by dropoff town', '<div id="m-emptyTown"></div>')
    + '</section>\n';
  var more = MORE_SECTIONS(r);
  Object.keys(more).forEach(function (k) { SEC[k] = more[k]; });
  SEC.coverage = '<section data-tab="coverage"><h2>Coverage, shift day by shift day</h2><p class="note">Pickups placed and not, and what each paid. '
    + 'A gap that keeps the same sign day after day is a bias in what the map can show, not a fact about places.</p>'
    + fold('coverageLevels', 'Placed, by level', '<p class="note">door, corner and name are a point; band, area and street are '
      + 'approximate (an area, with its spread). "Stood in for" is the refusal an approximate placement was found '
      + 'beside. Street index: ' + esc(r.best.streets || 'none') + '. Router (for the band): '
      + esc(r.best.road || 'none') + '.</p><div id="levels"></div>')
    + fold('coverageDays', 'Placed and not, by shift day', '<div id="coverage"></div>') + '</section>\n';
  SEC.method = '<section data-tab="method" class="method"><h2>How this was measured</h2>' + METHOD(r) + '</section>\n';

  /* The top of the page. The title and the window, then the nav — the one
   * part that stays put while a long table scrolls under it — then the Hours
   * picker, which scrolls away with the page and shows only on the tabs it
   * reaches. The banner that opened the page (four paragraphs, taller than a
   * phone's screen, before a single figure) is the Overview's "Read before
   * the numbers" now, whole; every other tab keeps its gist in one line
   * under the nav, with a link back to it, so no tab reads without it. */
  var nav = '<div id="navAt"></div><nav class="nav" id="nav" aria-label="Report sections">'
    + '<div class="groups" id="groups" role="tablist">' + GROUPS.map(function (g) {
      return '<button type="button" role="tab" data-group="' + g[0] + '">' + esc(g[1]) + '</button>';
    }).join('') + '</div>'
    + '<div class="tabs" id="tabs">' + GROUPS.map(function (g) {
      return '<span class="tg" data-group="' + g[0] + '">' + g[2].map(function (t) {
        return '<button type="button" data-tab="' + t[0] + '">' + esc(t[1]) + '</button>';
      }).join('') + '</span>';
    }).join('') + '</div></nav>\n';
  var strip = '<p class="strip" id="strip"><b>Offered, not earned</b>; only places near where you wait; '
    + pct(cvAll.unplaced.n, placedTotal) + ' of pickups unplaced. <a href="#overview">Read before the numbers</a></p>\n'
    // A capped read said on the page, not only on stdout (the reporting
    // review's R2): every figure below is over what was read.
    + (r.source && r.source.truncated ? '<p class="strip warn" id="capped"><b>Not the whole journal:</b> the server sent '
      + r.source.count + ' of ' + r.source.total + ' offers and would not page further, so every figure here is over the '
      + 'newest ' + r.source.count + '. Narrow the window with --since, or update the server.</p>\n' : '');
  return '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    + '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    + '<title>Strategy &amp; Places Report</title>\n'
    + '<link rel="stylesheet" href="' + LEAFLET_CSS + '"' + pinnedAt(LEAFLET_CSS) + '>\n'
    + '<style>\n' + PAGE_CSS + '\n</style>\n</head>\n<body>\n<main>\n'
    + '<header class="head"><h1>Strategy &amp; places report</h1>\n'
    + '<p class="sub">' + esc(span) + ' · ' + r.coverage.offers + ' offers the rig stands behind, '
    + r.outings + ' shift days · made ' + esc(new Date(r.made).toISOString().slice(0, 16).replace('T', ' '))
    + ' UTC on the NucBox · offline report, nothing on the rig reads it'
    // The nightly's diagnostics beside the page (places_nightly.sh, --checks):
    // report_check and twin_ids, counts only, so the double-filed cards'
    // breakdown is read here rather than by running anything.
    + (r.source && r.source.checks ? ' · <a href="' + esc(r.source.checks) + '">nightly checks</a>' : '')
    + '</p></header>\n'
    + nav + strip
    + '<div class="bar" id="hoursBar"><label>Hours <select id="when"></select></label>'
    + '<span id="whenNote" class="note"></span></div>\n'
    + TABS.map(function (t) { return SEC[t[0]] || ''; }).join('')
    + '</main>\n<div id="tip" hidden></div>\n'
    + '<script type="application/json" id="data">' + data + '</script>\n'
    + '<script src="' + LEAFLET_JS + '"' + pinnedAt(LEAFLET_JS) + '></script>\n'
    + '<script>\n' + PAGE_JS + '\n</script>\n</body>\n</html>\n';
}

/* A long table behind its heading: a <details> that is open as written, so
 * a laptop (and a page with its script off) shows everything as before, and
 * that the page's script closes on a phone, where the tables are wider than
 * the screen and a tab of fourteen of them is a scroll of seven screens.
 * Its id is a deep link: #<id> opens the tab it sits in, opens it and
 * scrolls to it. Nothing is dropped; the heading says what is inside. */
function fold(id, title, inner) {
  return '<details class="fold"' + (id ? ' id="' + esc(id) + '"' : '') + ' open><summary><h3>' + esc(title)
    + '</h3></summary>' + inner + '</details>';
}

/* The Overview (7 Nov 2026), where a bare address now opens. The owner
 * asked whether there was "a better format for all this information"; the
 * answer here is a landing page of the few numbers that matter, each one a
 * link to the tab that works it out, with its sample size under it — and no
 * figure of its own. Everything on it is already in the report object
 * (strategy.js's answer, advice.js's Targets lines, the coverage), picked
 * out, never recomputed, so it cannot disagree with the tab it points to:
 *
 *   - the Strategy tab's own sentence on the best line, word for word;
 *   - tiles: the best line and the flat range round it, $/hr on shift gross
 *     and net, offers per free hour, card against actual, the typical offer,
 *     the record and how far to trust it (the Strategy tab's own "thin"
 *     line where it has one), and when this was made;
 *   - the curve, small, and time of day as bars;
 *   - where the good offers start: the Targets tab's town lines, word for
 *     word, and how much of the record could be placed at all;
 *   - the banner that used to head every tab, whole, under "Read before the
 *     numbers";
 *   - and a directory of every tab under its question.
 *
 * Descriptive, like the rest: nothing here is an accept rule or reaches the
 * rig. Formatting is one rule throughout: a rate carries its unit ($/hr,
 * $/mi), a count says n=. */
function fmtPH(v) { return typeof v === 'number' ? '$' + v.toFixed(2) + '/hr' : '—'; }
function fmtPM(v) { return typeof v === 'number' ? '$' + v.toFixed(2) + '/mi' : '—'; }

/* The front page's when and where (round B; glanceOf has the rules). */
function glanceSection(r) {
  var g = r.glance;
  if (!g) return '';
  var w = g.windows, shown = w.best.length ? w.best : w.leading;
  function areaName(e) { return e.town ? e.a : labelOf(r, 'grid', e.a); }
  function days(n, gi) {
    var names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'weekday', 'weekend day'];
    return n + ' ' + names[gi] + (n === 1 ? '' : 's');
  }
  var wins = shown.map(function (x) {
    return '<li><b>' + esc(x.name) + '</b> · ' + x.rate.toFixed(1) + ' good/hr waited'
      + (x.shade === 'above' ? ' <span class="ok">clearly above</span>' : '')
      + ' <small>' + x.online.toFixed(1) + ' h waited on ' + days(x.nights, x.group) + '</small>'
      + (x.areas && x.areas.length ? '<br><small>Waiting areas then (home left out): ' + x.areas.map(function (e) {
        return esc(areaName(e)) + ' ' + (e.r === null ? '—' : e.r.toFixed(1)) + ' good/hr over ' + e.h.toFixed(1) + ' h on '
          + e.d + ' day' + (e.d === 1 ? '' : 's');
      }).join('; ') + '</small>' : '<br><small>No waiting area there yet with ' + WW_MIN_HOURS + ' h on ' + WW_MIN_DAYS
        + ' days, home left out.</small>') + '</li>';
  }).join('');
  var weak = w.worst.map(function (x) {
    return '<li><b>' + esc(x.name) + '</b> · ' + x.rate.toFixed(1) + ' good/hr waited <span class="warn">clearly below</span>'
      + ' <small>' + x.online.toFixed(1) + ' h on ' + days(x.nights, x.group) + '</small></li>';
  }).join('');
  function towns(end, lead) {
    var t = g.towns[end], top = t.ranked.slice(0, 3);
    return '<p class="lead">' + lead + ': ' + (top.length ? top.map(function (e) {
      return '<b>' + esc(e.town) + '</b> ' + Math.round(e.share * 100) + '% good, typical ' + fmtPH(e.typical)
        + ' (n=' + e.n + ')' + (e.shade ? ' — clearly ' + e.shade : '');
    }).join('; ') : 'no town with ' + g.towns.minN + ' offers on ' + g.towns.minDays + ' days yet') + '.</p>';
  }
  return '<h3>When <a class="more" href="#whenwhere">When &amp; where ›</a></h3>'
    + '<p class="note">Good = top ' + g.top + '% of every offer in the range: '
    + (g.cut === null ? 'no offers yet' : '≥ ' + money(g.cut) + '/hr') + '. Good offers per hour WAITED (no order in '
    + 'the car), When &amp; where\'s own figure.</p>'
    + (w.best.length ? '<p class="lead">Good offers came clearly more often than the range\'s ' + w.ref.toFixed(1)
       + ' an hour waited:</p>' : '<p class="lead"><b>No window clearly better yet</b>; highest so far:</p>')
    + (wins ? '<ol class="lines">' + wins + '</ol>' : '<p class="note">No window has ' + WW_MIN_HOURS + ' h waited on '
       + WW_MIN_DAYS + ' days yet.</p>')
    + (weak ? '<p class="lead">Clearly less often:</p><ol class="lines">' + weak + '</ol>' : '')
    + '<p class="note">A window is 1 to ' + w.maxLen + ' whole hours on a weekday, on weekdays or on weekends, at '
    + w.floorHours + ' h waited on ' + w.floorDays + ' days; "clearly" holds at 99% shared over the ' + w.searched
    + ' windows looked at. Waiting areas leave out home (' + g.homeLeft + ' cards; Offers around you\'s rule).</p>'
    + '<h3>Where <a class="more" href="#around">Offers around you ›</a></h3>'
    + towns('pick', 'Pickup towns, by share good')
    + towns('drop', 'Drop-off towns, by share good')
    + '<p class="note">The town printed on the card (<a href="#towns">Towns</a>); where trips leave you is '
    + '<a href="#after">After a drop</a>; where you waited is <a href="#waited">Waited</a>.</p>';
}

function OVERVIEW_SECTION(r, span) {
  var s = r.strategy, cv = s.curve, c = s.counts, all = s.seen.all, act = s.actual.all;
  function line(re) { return s.lines.filter(function (l) { return re.test(l); })[0] || null; }
  function tile(href, label, value, sub, foot, cls) {
    return '<a class="tile' + (cls ? ' ' + cls : '') + '" href="' + href + '"><span class="tl">' + esc(label) + '</span>'
      + '<span class="tv">' + value + '</span>' + (sub ? '<span class="ts">' + sub + '</span>' : '')
      + (foot ? '<span class="tf">' + foot + '</span>' : '') + '</a>';
  }
  var best = cv.drawn ? cv.best : null;
  var lead = line(/^Holding out for/), yours = line(/^Your line/), trust = line(/^How far to trust it/);
  var pct0 = Math.round((1 - s.floors.plateau) * 100);
  var tiles = [];
  tiles.push(tile('#strategy', 'Best line to hold out for',
    best ? '$' + best.T + '+<small>/hr</small>' : '—',
    best ? (best.from === best.to ? 'no other line within ' + pct0 + '%' : 'flat from $' + best.from + ' to $' + best.to
            + ' (within ' + pct0 + '% of the best)') + (cv.target && cv.target.side ? '; your $' + cv.target.T + ' is '
            + (cv.target.side === 'inside' ? 'inside it' : cv.target.side + ' it') : '')
      : 'not enough record for a curve yet',
    best ? 'n=' + best.n + ' offers at $' + best.T + '+ seen free · Strategy' : 'Strategy'));
  tiles.push(tile('#s-curve', '$/hr on shift at that line',
    best ? '$' + best.value.toFixed(2) + (cv.bestNet && cv.cost.perMile !== null
      ? ' <small>gross</small><br>$' + cv.bestNet.value.toFixed(2) + ' <small>net</small>' : '') : '—',
    'every hour on shift, waiting included' + (cv.bestCi ? '; 95% $' + cv.bestCi[0].toFixed(2) + '–$' + cv.bestCi[1].toFixed(2) : '')
      + (typeof cv.everything.gross === 'number' ? '; taking everything ' + fmtPH(cv.everything.gross) : ''),
    cv.days + ' shift days, ' + (cv.freeHours || 0) + ' h free · Strategy'));
  tiles.push(tile('#s-seen', 'Offers per free hour',
    typeof all.perFreeHour === 'number' ? all.perFreeHour.toFixed(1) : '—',
    'seen with no order in the car',
    'n=' + (c.free || 0) + ' offers in ' + c.freeHours + ' h free of ' + c.shiftHours + ' h on shift · Strategy'));
  tiles.push(tile('#s-actual', 'Card against actual',
    typeof act.ratio === 'number' ? act.ratio.toFixed(2) + '×' : '—',
    typeof act.ratio === 'number' ? 'minutes really taken ÷ the card\'s; a $25/hr card ≈ ' + fmtPH(25 / act.ratio) + ' actual'
      : 'fewer than ' + s.floors.ratio + ' timed orders: cards taken at their word',
    'n=' + act.timed + ' timed orders · Strategy'));
  tiles.push(tile('#s-seen', 'The typical offer',
    all.ph.p50 !== null ? fmtPH(all.ph.p50).replace('/hr', '<small>/hr</small>') : '—',
    all.ph.p50 !== null ? 'half between $' + all.ph.p25.toFixed(2) + ' and $' + all.ph.p75.toFixed(2) + '; top 10% from '
      + fmtPH(all.ph.p90) + (all.pm.p50 !== null ? '; ' + fmtPM(all.pm.p50) + ' median (read only)' : '') : '',
    'n=' + all.n + ' offers on ' + all.outings + ' shift days · Strategy'));
  // The record, and how far to trust it: the Strategy tab's own sentence
  // where it calls the record thin, so the warning is worded once.
  tiles.push(tile('#strategy', trust ? 'How far to trust it' : 'The record',
    trust ? 'thin' : c.outings + ' <small>shift days</small>',
    trust ? esc(trust.replace(/^How far to trust it: thin — /, '')) : c.offers + ' offers, ' + act.timed
      + ' timed orders, ' + (cv.freeHours || 0) + ' h free: not flagged thin',
    'made ' + esc(new Date(r.made).toISOString().slice(0, 16).replace('T', ' ')) + ' UTC · ' + esc(span),
    trust ? 'warn' : ''));

  // Time of day in words: the blocks with a curve of their own, highest
  // $/hr on shift first. An ordering of point estimates, said as such.
  var ranked = (s.slices.block || []).filter(function (b) { return b.drawn && b.best; })
    .sort(function (a, b) { return b.best.value - a.best.value; });
  var blocksSaid = ranked.length
    ? 'Highest $/hr on shift, each block at its own best line: ' + ranked.slice(0, 3).map(function (b) {
      return esc(b.name) + ' ' + fmtPH(b.best.value) + ' (n=' + b.offers + ')';
    }).join(', ') + '. Point estimates with no test between them; the held-out check in the Strategy tab says '
      + 'whether a line per block beat one line on this record.'
    : 'No block has a curve of its own yet.';

  var cvAll = r.coverage.all, total = cvAll.placed.n + cvAll.unplaced.n;
  var areas = r.targets && r.targets.lines ? r.targets.lines.areas : [];
  var wwCut = r.whenwhere.cuts[r.whenwhere.tops.indexOf(r.whenwhere.top)];
  return '<section data-tab="overview"><h2>Overview — the few numbers that matter</h2>'
    + '<p class="exp">Descriptive. Every figure is from the tab it links to, with its sample size under it; nothing '
    + 'here is an accept rule or changes a verdict, and nothing on the rig reads it. '
    + '<a href="#caveats">Read before the numbers</a>.</p>'
    // Round B: when and where first, the owner's two questions.
    + glanceSection(r)
    // The figures first, then the Strategy tab's own sentence on them: on a
    // phone the sentence is a screen long, and the tiles are what a glance
    // is for.
    + '<div class="tiles">' + tiles.join('') + '</div>'
    + (lead ? '<p class="lead">' + esc(lead) + (yours ? ' ' + esc(yours) : '') + ' <a href="#strategy">Strategy ›</a></p>' : '')
    + '<div class="pair">'
    + '<div><h3>Holding out for a line <a class="more" href="#s-curve">curve ›</a></h3>'
    + '<div class="plot fluid">' + strategyChart(cv, 'small') + '</div>'
    + '<p class="note">Gross (solid) and net (dashed) $/hr on shift against the line held out for; shaded, within '
    + pct0 + '% of the best; hollow points are thin (under ' + s.floors.curveOffers + ' offers).</p></div>'
    + '<div><h3>Time of day <a class="more" href="#s-blocks">blocks ›</a></h3>'
    + '<div class="plot fluid">' + blockChart(s.slices.block) + '</div>'
    + '<p class="note">' + blocksSaid + '</p></div>'
    + '</div>'
    + '<h3>Where the good offers start <a class="more" href="#targets">Targets ›</a></h3>'
    + '<ul class="lines">' + areas.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'
    // Which area at a given time is its own tab, with its own picker; the
    // Overview names it and its cutoff and works nothing out.
    + '<p class="lead"><a href="#whenwhere">When &amp; where ›</a> which area gave the most good offers per hour '
    + 'waited, on the day and hours you pick (good = top ' + r.whenwhere.top + '%: '
    + (wwCut === null ? 'no offers yet' : '≥ ' + money(wwCut) + '/hr') + ').</p>'
    + '<p class="note">' + pct(cvAll.unplaced.n, total) + ' of pickups could not be placed (' + cvAll.unplaced.n + ' of '
    + total + '), so the Places, Map and Grid tabs describe a slice of the record: <a href="#coverage">Coverage ›</a>. '
    + 'Towns and Restaurants need no pin.</p>'
    + '<details class="caveats" id="caveats" open><summary><h3>Read before the numbers</h3></summary>'
    + '<div class="banner">' + banner(r) + '</div></details>'
    + '<h3>Every tab, by the question it answers</h3><div class="dir">'
    + GROUPS.filter(function (g) { return g[0] !== 'overview'; }).map(function (g) {
      return '<div><h4>' + esc(g[1]) + '</h4><ul>' + g[2].map(function (t) {
        return '<li><a href="#' + t[0] + '">' + esc(t[1]) + '</a> — ' + esc(t[2]) + '</li>';
      }).join('') + '</ul></div>';
    }).join('') + '</div>'
    + '</section>\n';
}

/* The Targets tab: advice.js's lines (the offers page's box, word for word),
 * then the richer area lines only this report can give. */
function TARGETS_SECTION(r) {
  var t = r.targets, L = t.lines;
  function ul(xs) { return '<ul class="lines">' + xs.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'; }
  return '<section data-tab="targets"><h2>Targets — what the record says to aim for</h2>'
    + '<p class="exp">Descriptive. The same lines the offers page shows (advice.js targets): realistic $/hr by '
    + 'three-hour block, the replay\'s one line for all hours, the $/mi good offers tend to have, and the towns '
    + 'that beat chance. Nothing here is an accept rule or changes a verdict.</p>'
    + '<h3>$/hr and $/mi, by time of day</h3>' + ul(L.rate)
    + '<h3>Best areas to work: towns</h3>' + ul(L.areas)
    + '<h3>Best areas to work: places, restaurants, cells and waiting</h3>'
    + '<p class="note">From the tables in the other tabs, by the same tests: named only where the grouping beats '
    + 'chance and the interval of its hour-held score is clear of zero; waiting from the GPS spells (Best offers tab).</p>'
    + ul(targetAreaLines(r))
    + '<p class="note">Floors: ' + t.floors.offers + ' offers in a block for its percentiles, ' + t.floors.timed
    + ' timed takes for a median real $/hr, ' + t.floors.cleared + ' offers over the line for a $/mi, '
    + t.floors.town + ' offers on ' + t.floors.townDays + ' shift days for a town.</p>'
    + ul(L.notes).replace('class="lines"', 'class="note"')
    + '</section>\n';
}

/* The Strategy tab (7 Nov 2026): tools/strategy.js's answer, drawn here and
 * worked out there. The plain lines first (strategy.js words them, for this
 * page and the end-of-shift report alike), then the curve as a chart and a
 * table, the slices, and the two descriptive halves under it. Static HTML:
 * the hours picker above does not reach it, because the curve is over all
 * hours and its blocks are rows of their own. */
/* Two sizes of one drawing. 'wide' is the 640 x 260 the tab always drew,
 * for a laptop; 'small' is 360 x 220 with fewer labels, for a phone and for
 * the Overview: the wide one squeezed to a 343px screen prints its labels at
 * six pixels, and given its old 520px floor it scrolled sideways instead,
 * hiding the right half of the curve — where the best line usually is. */
function strategyChart(cv, size) {
  var small = size === 'small';
  var pts = cv.points, W = small ? 360 : 640, H = small ? 220 : 260, L = small ? 40 : 52, R = small ? 10 : 16, T = 14,
      B = small ? 32 : 34;
  var vals = [];
  pts.forEach(function (p) {
    [p.gross, p.net, p.ci && p.ci[0], p.ci && p.ci[1]].forEach(function (v) { if (typeof v === 'number') vals.push(v); });
  });
  if (cv.everything && typeof cv.everything.gross === 'number') vals.push(cv.everything.gross);
  if (!vals.length) return '<p class="note">Nothing to draw yet.</p>';
  var lo = Math.max(0, Math.floor(Math.min.apply(null, vals) / 5) * 5), hi = Math.ceil(Math.max.apply(null, vals) / 5) * 5;
  if (hi <= lo) hi = lo + 5;
  var x0 = cv.grid[0], x1 = cv.grid[cv.grid.length - 1];
  function X(v) { return L + (v - x0) / (x1 - x0) * (W - L - R); }
  function Y(v) { return T + (hi - v) / (hi - lo) * (H - T - B); }
  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Effective $/hr on shift against the line held out for">'];
  // The flat region first, under everything: "anything in here gives about the same".
  if (cv.best) {
    out.push('<rect x="' + X(cv.best.from).toFixed(1) + '" y="' + T + '" width="' + Math.max(2, X(cv.best.to) - X(cv.best.from)).toFixed(1)
             + '" height="' + (H - T - B) + '" fill="var(--grid)" opacity="0.7"><title>Within '
             + Math.round((1 - S.PLATEAU) * 100) + '% of the best: $' + cv.best.from + ' to $' + cv.best.to + '</title></rect>');
  }
  for (var gy = lo; gy <= hi; gy += (small && hi - lo > 20 ? 10 : 5)) {
    out.push('<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(gy).toFixed(1) + '" y2="' + Y(gy).toFixed(1)
             + '" stroke="var(--grid)"/><text x="' + (L - 6) + '" y="' + (Y(gy) + 4).toFixed(1) + '" text-anchor="end">$' + gy + '</text>');
  }
  cv.grid.forEach(function (gx, i) {
    if (i % (small ? 3 : 2)) return;
    out.push('<text x="' + X(gx).toFixed(1) + '" y="' + (H - B + 16) + '" text-anchor="middle">$' + gx + '</text>');
  });
  out.push('<text x="' + ((L + W - R) / 2) + '" y="' + (H - 4) + '" text-anchor="middle">'
           + (small ? 'line held out for ($/hr on the panel)' : 'cards held out for: the panel\'s $/hr or more') + '</text>');
  // The 95% band, where shift days were resampled.
  var band = pts.filter(function (p) { return p.ci; });
  if (band.length >= 2) {
    out.push('<polygon fill="var(--up)" opacity="0.15" points="' + band.map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p.ci[1]).toFixed(1); })
      .concat(band.slice().reverse().map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p.ci[0]).toFixed(1); })).join(' ') + '"/>');
  }
  if (cv.everything && typeof cv.everything.gross === 'number') {
    out.push('<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(cv.everything.gross).toFixed(1) + '" y2="' + Y(cv.everything.gross).toFixed(1)
             + '" stroke="var(--ink2)" stroke-dasharray="2 4"><title>Taking everything: $' + cv.everything.gross.toFixed(2) + '/hr</title></line>');
  }
  if (cv.target && typeof cv.target.T === 'number' && cv.target.T >= x0 && cv.target.T <= x1) {
    out.push('<line x1="' + X(cv.target.T).toFixed(1) + '" x2="' + X(cv.target.T).toFixed(1) + '" y1="' + T + '" y2="' + (H - B)
             + '" stroke="var(--ink2)" stroke-dasharray="4 3"/><text x="' + (X(cv.target.T) + 4).toFixed(1) + '" y="' + (T + 10)
             + '">your line</text>');
  }
  [['gross', 'var(--up)', ''], ['net', 'var(--ink2)', ' stroke-dasharray="6 4"']].forEach(function (s) {
    var seg = pts.filter(function (p) { return typeof p[s[0]] === 'number'; });
    if (seg.length < 2) return;
    out.push('<polyline fill="none" stroke="' + s[1] + '" stroke-width="2"' + s[2] + ' points="'
             + seg.map(function (p) { return X(p.T).toFixed(1) + ',' + Y(p[s[0]]).toFixed(1); }).join(' ') + '"/>');
    seg.forEach(function (p) {
      // A thin point is hollow: it can be neither the best nor in the flat region.
      out.push('<circle cx="' + X(p.T).toFixed(1) + '" cy="' + Y(p[s[0]]).toFixed(1) + '" r="' + (small ? 3 : 4) + '" stroke="' + s[1] + '" stroke-width="2" fill="'
               + (p.thin ? 'var(--surface)' : s[1]) + '"><title>$' + p.T + '+: ' + s[0] + ' $' + p[s[0]].toFixed(2) + '/hr on shift, '
               + p.n + ' offers seen free' + (p.thin ? ' (thin)' : '') + '</title></circle>');
    });
    // Labelled at the left end, gross above its line and net below its own:
    // at the right end both curves fall to the same few offers and meet.
    var first = seg[0];
    out.push('<text x="' + (X(first.T) + 6).toFixed(1) + '" y="' + (Y(first[s[0]]) + (s[0] === 'gross' ? -10 : 18)).toFixed(1)
             + '">' + s[0] + '</text>');
  });
  out.push('</svg>');
  return out.join('');
}

/* A table of strategy.js's rows. `thin`, where given, marks a row whose
 * sample is under its floor (a hollow point, a slice with no curve, a row
 * with no quartile): drawn muted and in italics, so a figure over too few
 * offers never reads as loud as one over enough, and its n stays beside it. */
function strategyTable(cols, rows, thin) {
  if (!rows || !rows.length) return '<p class="note">None.</p>';
  function cell(v, f) {
    if (v === null || v === undefined) return '—';
    if (f === '$') return '$' + v.toFixed(2);
    if (f === '$ci') return '[$' + v[0].toFixed(2) + ', $' + v[1].toFixed(2) + ']';
    if (f === 'x') return v.toFixed(2) + '×';
    if (f === 'r') return v.toFixed(2);
    if (f === 'h') return v.toFixed(1);
    return esc(v);
  }
  return '<div class="tw"><table><thead><tr>' + cols.map(function (c) { return '<th>' + esc(c[1]) + '</th>'; }).join('')
    + '</tr></thead><tbody>' + rows.map(function (r) {
      return '<tr' + (thin && thin(r) ? ' class="thinrow"' : '') + '>'
        + cols.map(function (c) { return '<td>' + cell(typeof c[0] === 'function' ? c[0](r) : r[c[0]], c[2]) + '</td>'; }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
}

/* Time of day, drawn: one bar per three-hour block, its length the $/hr on
 * shift that holding out for that block's own best line gave (strategy.js's
 * slices), a tick where taking everything in that block would have been, and
 * the line, the offers seen free and the shift days under it. A block with
 * no curve of its own (under its floors) gets no bar, only its counts, in
 * grey. Every bar is one colour: these are point estimates with no test
 * between them, and AUDITS.md's Settled entry found a line tuned to the hour
 * earned less on the nights it was not fitted to — the held-out check under
 * the Strategy tab's lines says how that went on this record. Inline SVG off
 * the page's own colours, so it needs no library, works offline and follows
 * light and dark. */
function blockChart(blocks) {
  blocks = blocks || [];
  if (!blocks.length) return '<p class="note">No three-hour block saw an offer while free.</p>';
  var W = 360, rowH = 32, L = 64, Rr = 8, T = 6, H = T + blocks.length * rowH + 2;
  var top = 0;
  blocks.forEach(function (b) {
    [b.best && b.drawn ? b.best.value : null, b.everything && b.everything.gross].forEach(function (v) {
      if (typeof v === 'number') top = Math.max(top, v);
    });
  });
  top = Math.max(5, Math.ceil(top / 5) * 5);
  function X(v) { return L + v / top * (W - L - Rr); }
  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="$/hr on shift by three-hour block">'];
  blocks.forEach(function (b, i) {
    var y = T + i * rowH, has = b.drawn && b.best;
    out.push('<text x="' + (L - 6) + '" y="' + (y + 12) + '" text-anchor="end">' + esc(b.name) + '</text>');
    if (has) {
      out.push('<rect x="' + L + '" y="' + (y + 2) + '" width="' + Math.max(1, X(b.best.value) - L).toFixed(1)
               + '" height="12" rx="2" fill="var(--up)"><title>' + esc(b.name) + ': $' + b.best.value.toFixed(2)
               + '/hr on shift holding out for $' + b.best.T + '+ (n=' + b.best.n + ' offers)</title></rect>');
      out.push('<text x="' + L + '" y="' + (y + 27) + '" class="sm">$' + b.best.value.toFixed(2) + '/hr at $' + b.best.T
               + '+ · n=' + b.offers + ' seen free · ' + b.days + ' days</text>');
    } else {
      out.push('<rect x="' + L + '" y="' + (y + 2) + '" width="' + (W - L - Rr) + '" height="12" rx="2" fill="none" '
               + 'stroke="var(--axis)" stroke-dasharray="3 3"/><text x="' + L + '" y="' + (y + 27)
               + '" class="sm">too few for a curve · n=' + b.offers + ' seen free · ' + b.days + ' days</text>');
    }
    if (b.everything && typeof b.everything.gross === 'number') {
      var xe = X(b.everything.gross).toFixed(1);
      out.push('<line x1="' + xe + '" x2="' + xe + '" y1="' + y + '" y2="' + (y + 16) + '" stroke="var(--ink)" stroke-width="2">'
               + '<title>' + esc(b.name) + ': taking everything $' + b.everything.gross.toFixed(2) + '/hr</title></line>');
    }
  });
  out.push('</svg>');
  return out.join('') + '<p class="note">Bar: $/hr on shift at the block\'s own best line. Tick: taking everything in '
    + 'that block. Point estimates, no test between blocks.</p>';
}

/* Card against what the app paid (the owner, 7 Nov 2026: "compare what uber
 * actually paid compared to the expected pay of the order"): strategy.js's
 * cardVsPaid over the trips read off the app's earnings screenshots and
 * matched to orders (server.js /api/earnings, earnings.js). By app, by
 * three-hour block of the trip's start and by restaurant, each with its n; a
 * group under its floor is thin (muted, italic, never the headline), and a
 * trip whose tip is still processing is left out of every figure and
 * counted. A server with no earnings, or none uploaded: one sentence. */
function paidSection(p) {
  if (!p) return '';
  var cols = [['name', ''], ['n', 'orders'], ['card', 'cards', '$'], ['paid', 'paid', '$'], ['diff', 'paid − card', '$'],
              ['medianDiff', 'typical order', '$'], ['tips', 'settled tips', '$'], ['over', 'paid more'], ['under', 'paid less']];
  function thin(g) { return g.thin; }
  var c = p.counts;
  return '<h3 id="s-paid">Card vs paid</h3>'
    + '<p class="note">What the app paid, read off its own earnings screenshots uploaded on the offers page, against what '
    + 'the card said, for the trips matched to an order (' + c.matched + ' of ' + c.entries + ' read; ' + c.unmatched
    + ' not matched — no order on file, or waiting for you to pick). <b>' + c.pending + '</b> with a tip still processing '
    + 'are left out of every figure until a later upload settles them' + (c.noCard ? '; ' + c.noCard + ' with no card pay on file' : '')
    + '. A group under ' + p.floor + ' orders is <b>thin</b>. Descriptive: nothing on the rig reads it.</p>'
    + (c.entries ? strategyTable(cols, [p.all], thin)
       + fold('s-paid-app', 'By app', strategyTable(cols, p.byApp, thin))
       + fold('s-paid-block', 'By three-hour block (of the trip\'s start)', strategyTable(cols, p.byBlock, thin))
       + fold('s-paid-rest', 'By restaurant (as the app names it)', strategyTable(cols, p.byRestaurant, thin))
       : '<p class="note">No earnings screenshots have been uploaded yet.</p>');
}

/* Uber's acceptance rate and the line that keeps the goal (strategy.js
 * section 6; the owner, 15 Nov 2026: Gold needs 25%). Its lines are among
 * the tab's own above; here, Uber's curve with the share of exclusive
 * requests each line would have kept. Descriptive, as the rest. */
function GOLD_PART(s) {
  var g = s.gold;
  if (!g || !g.line) return '';
  var goal = Math.round(g.goal * 100) + '%';
  var cols = [['T', 'line ($/hr+)', '$'], ['n', 'Uber offers seen free'], ['gross', 'gross $/hr on shift', '$'],
              [function (p) { return Math.round(p.share * 100) + '%'; }, 'requests at or above it'],
              [function (p) { return Math.round(p.shareKept * 100) + '%'; }, '…with your takes below it'],
              [function (p) { return g.line.best && p.T === g.line.best.T ? 'best' : g.line.kept && p.T === g.line.kept.T
                ? 'best keeping ' + goal : ''; }, ''],
              [function (p) { return p.thin ? 'thin' : ''; }, '']];
  return '<h3 id="s-gold">Uber acceptance — the line that keeps ' + esc(goal) + '</h3>'
    + '<p class="note">Uber\'s cards alone, as the rig saw them: the share of the ' + g.line.requests + ' exclusive requests on '
    + 'record whose card was at each line, beside what holding out for that line paid per hour on shift. The share counts '
    + 'every card at the line as taken, an upper bound. Trip Radar, Early look, reservations and DoorDash are left out; a '
    + 'card with no Exclusive tag read is counted. Not a rule: no verdict, target or panel line reads it. Check Uber Pro\'s '
    + 'own terms for what it counts.</p>'
    + fold('s-gold-points', 'Every line, with its share of requests', strategyTable(cols, g.line.points, function (p) { return p.thin; }));
}

/* The good offers passed on (strategy.js section 7; the reporting work's
 * third round): placed straight under the curve because it is the curve's
 * own question asked of what was done — the curve says what holding out for
 * a line would have paid, this says which good cards were taken and what
 * came after the ones let go. A stacked bar per three-hour block (taken, the
 * phone's own accept, let go, busy: counts, so the bar is as long as the
 * block's good offers), the waits under it, then the table and the four
 * rulers folded. Words in the past tense; no test between blocks, and no
 * block is marked: these are counts, and the blocks are rows of a table. */
function PASSED_PART(s) {
  var p = s.passed;
  if (!p || p.cut === null || !p.all.good) return '';
  var max = 0;
  p.byBlock.forEach(function (g) { max = Math.max(max, g.good); });
  function pctOf(v) { return (max ? v / max * 100 : 0).toFixed(1) + '%'; }
  function wait(w) {
    return !w.n ? 'no wait measured' : w.p50 === null ? 'next good after: n=' + w.n + ', too few for a median'
      : 'next good after a median ' + w.p50 + ' min (P75 ' + w.p75 + '; n=' + w.n + ')';
  }
  var rows = p.byBlock.map(function (g) {
    var seg = [['taken', g.taken], ['phone', g.phone], ['passed', g.passed], ['busy', g.busy]];
    return '<div class="prow"><div class="pname">' + esc(g.name) + '</div><div class="pbar">'
      + seg.map(function (x) {
        return x[1] ? '<i class="p' + x[0] + '" style="width:' + pctOf(x[1]) + '" title="' + esc(x[0]) + ' ' + x[1] + '"></i>' : '';
      }).join('') + '</div><div class="pfig">' + g.good + ' good · took ' + g.taken
      + (g.shareTaken !== null ? ' (' + Math.round(g.shareTaken * 100) + '%)' : '') + ' · no answer ' + g.unanswered
      + ' · let go ' + g.passed + (g.declined ? ' (' + g.declined + ' marked)' : '') + (g.phone ? ' · phone ' + g.phone : '')
      + ' · busy ' + g.busy
      + ' · ' + esc(wait(g.wait)) + '</div></div>';
  }).join('');
  var w = p.waits, wc = w.counts;
  function waitSay(x) {
    var open = x.open ? ', ' + x.open + ' still open' : '';
    return x.p50 === null ? '(too few waits to give a median: n=' + x.n + open + ')'
      : 'after <b>a median ' + x.p50 + ' min</b> (P75 ' + x.p75 + ' min; n=' + x.n + open + ')';
  }
  function waitCell(x) { return x.p50 === null ? (x.n ? 'n=' + x.n + ' (too few)' : '—') : x.p50 + ' / ' + x.p75 + ' min (n=' + x.n + ')'; }
  var blockCols = [['name', ''], ['good', 'good seen'], ['taken', 'taken'],
                   [function (g) { return g.shareTaken === null ? null : Math.round(g.shareTaken * 100) + '%'; }, 'of taken + let go'],
                   ['unanswered', 'no answer'], ['passed', 'let go'], ['declined', '…marked passed'],
                   ['phone', 'on the phone, no Took'], ['busy', 'order already in the car'],
                   [function (g) { return waitCell(g.wait); }, 'to the next good: median / P75']];
  var topCols = [[function (t) { return 'top ' + t.top + '%' + (t.top === p.top ? ' (shown)' : ''); }, 'good ='],
                 ['cut', 'from ($/hr)', '$'], ['good', 'good seen'], ['taken', 'taken'],
                 [function (t) { return t.shareTaken === null ? null : Math.round(t.shareTaken * 100) + '%'; }, 'of taken + let go'],
                 ['passed', 'let go'], ['phone', 'phone'], ['busy', 'busy'],
                 [function (t) { return waitCell(t.waitGood); }, 'to the next good'],
                 [function (t) { return waitCell(t.waitTake); }, 'to the next take']];
  return '<h3 id="s-passed">Good offers not taken on the record</h3>'
    + '<p class="note">Good is the top ' + p.top + '% of ' + (p.report ? 'this report\'s ' + p.n + ' offers over its '
      + (p.days || 0) + ' days' : 'this record\'s own panel $/hr') + ': <b>$' + p.cut.toFixed(2)
    + '/hr or more</b> (' + p.over + ' of ' + p.n + ' offers), one dollar line held fixed across days and blocks — '
    + (p.report ? 'the same line When &amp; where reads, worked out once for the whole report. '
      : 'the offers page\'s Trends ruler, worked out by the same function. ')
    + '<b>No answer</b> is most of what is not taken: a card nobody ticked or Took, counted before <b>let go</b>, '
    + 'which adds the ones you marked passed. <b>Taken</b> is a Took or your ✓ on the card; a card '
    + 'nobody answered for is not taken (silence is never an accept). <b>Busy</b>: it came inside an order\'s hold, Took to '
    + 'its end, or was an Uber add-on — no free driver was choosing it, and an order you never Took leaves its cards '
    + 'reading free. <b>On the phone</b>: Uber\'s earnings screen matched it with no Took, so it is neither taken nor let '
    + 'go here. <b>The wait</b> is minutes online and free from a card let go to the next good card that was not busy, '
    + 'and to your next take: minutes with the rig off are not counted (' + wc.acrossOff + ' of ' + wc.origins
    + ' waits ran across such a stretch), nor the minutes of a trip you took meanwhile (' + (wc.throughHold || 0)
    + ' ran through one)' + (wc.openGood ? '; ' + wc.openGood + ' with no good card after it in the record ' + (wc.openGood === 1
      ? 'is' : 'are') + ' still open, said beside each median and in none' : '') + (wc.lone ? '; ' + wc.lone + ' let go alone, outside any run, start no wait' : '')
    + '. A median needs ' + s.floors.dist + ' waits. History, not advice: no verdict, target or '
    + 'panel line reads it, and the blocks are rows, not a line tuned to the hour.</p>'
    + '<div class="plegend"><span><i class="ptaken"></i>taken</span><span><i class="pphone"></i>on the phone, no Took</span>'
    + '<span><i class="ppassed"></i>let go</span><span><i class="pbusy"></i>order already in the car</span></div>'
    + '<div class="pblocks">' + rows + '</div>'
    + '<p class="note">After one let go, over every block: the next good one came ' + waitSay(w.good)
    + '; your next take came ' + waitSay(w.take) + '.</p>'
    + fold('s-passed-blocks', 'By three-hour block, in full', strategyTable(blockCols, [p.all].concat(p.byBlock)))
    + fold('s-passed-tops', 'At the other rulers (top 10, 20, 30 and 50%)', strategyTable(topCols, p.tops || []));
}

/* Rush against quiet hours (strategy.js section 8; the owner, Nov 2026,
 * asking whether $/mi would serve better "when traffic dies down"): placed
 * straight after the $/mi curve it reads against, worked out there and only
 * drawn here. The plain lines, then the split hour by hour, each half's
 * lines in and out of sample, and card against real by the same split. No
 * colour on any row: the verdict is words, with its interval beside it. */
function QUIET_PART(s) {
  var q = s.quiet;
  if (!q) return '';
  function ul(xs) { return '<ul class="lines">' + xs.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'; }
  function clock(h) { return h === 0 ? '12am' : h < 12 ? h + 'am' : h === 12 ? '12pm' : (h - 12) + 'pm'; }
  var says = { mile: '$/mi line ahead, beyond chance', hour: '$/hr line ahead, beyond chance', even: 'neither, beyond chance',
               thin: 'not enough yet' };
  function held(p, k) { return p.heldOut ? p.heldOut[k] : null; }
  var partCols = [['name', ''], ['days', 'shift days'], ['freeHours', 'hours free', 'h'], ['offers', 'offers seen free'],
    ['timed', 'timed orders'], [function (p) { return p.bestHour ? p.bestHour.T : null; }, 'best $/hr line', '$'],
    [function (p) { return p.bestHour ? p.bestHour.value : null; }, '…its $/hr', '$'],
    [function (p) { return p.bestMile ? p.bestMile.T : null; }, 'best $/mi line', '$'],
    [function (p) { return p.bestMile ? p.bestMile.value : null; }, '…its $/hr', '$'],
    [function (p) { return held(p, 'hr'); }, '$/hr line held out', '$'], [function (p) { return held(p, 'hrCi'); }, '95%', '$ci'],
    [function (p) { return held(p, 'mi'); }, '$/mi line held out', '$'], [function (p) { return held(p, 'miCi'); }, '95%', '$ci'],
    [function (p) { return held(p, 'diff'); }, '$/mi less $/hr', '$'], [function (p) { return held(p, 'diffCi'); }, '95%', '$ci'],
    [function (p) { return says[p.verdict]; }, 'verdict']];
  var hourCols = [[function (h) { return clock(h.hour); }, 'clock hour'], ['freeHours', 'hours free', 'h'],
                  ['offers', 'offers seen free'], ['perFreeHour', 'per hour free', 'r'], ['part', 'half']];
  var cv = q.cardVsReal;
  var cvCols = [['name', ''], ['timed', 'timed'], ['ratio', 'real ÷ card min', 'x'], ['ratioMedian', 'typical order', 'x']];
  var basis = q.parts.length && q.parts[0].basis === 'net' ? 'net of the running cost the rows carry' : 'gross (the rows carry no running cost)';
  return '<h3 id="s-quiet">Rush vs quiet hours: $/hr line against $/mi line</h3>'
    + '<p class="note"><b>Reading only.</b> Your own record replayed in two halves of the clock. <b>Quiet</b> is the clock '
    + 'hours with the fewest offers per free hour that together hold ' + Math.round(q.floors.share * 100) + '% of your free '
    + 'time, <b>busy</b> the rest: read off the record, not chosen. In each half the accept-threshold curve above, once '
    + 'on $/hr and once on $/mi, its time the card\'s minutes × the half\'s own measured real ÷ card ratio, ' + basis + '. '
    + 'The best line of each kind in sample flatters both, so each is also <b>held out</b>: picked on the other shift days '
    + 'and scored on the one left out, every day in turn, the days resampled for a 95% interval. A verdict needs '
    + q.floors.days + ' shift days and ' + q.floors.timed + ' timed orders in the half. Nothing on the rig reads this, and '
    + 'no verdict, target or panel line moves; a $/mi accept rule and a line tuned to the hour stay refused (AUDITS.md, '
    + 'Settled) unless you revisit them with this evidence.</p>'
    + ul(q.lines)
    + (q.parts.length ? strategyTable(partCols, q.parts, function (p) { return p.verdict === 'thin'; }) : '')
    + fold('s-quiet-hours', 'The split, hour by hour', strategyTable(hourCols, q.split.byHour))
    + fold('s-quiet-card', 'Card minutes against real, by the split',
           (q.parts.length ? strategyTable(cvCols, q.parts.map(function (p) { return p.actual; }), function (a) { return a.ratio === null; })
             : '<p class="note">None.</p>')
           + '<p class="note">Below 1.00× the card overstated the trip. Quiet less busy'
           + (cv && cv.diffCi ? ': ' + cv.diff.toFixed(2) + ' (95% ' + cv.diffCi[0].toFixed(2) + ' to ' + cv.diffCi[1].toFixed(2)
              + ', shift days resampled).' : ': no interval yet (each half needs ' + q.floors.ratio + ' timed orders on '
              + q.floors.days + ' shift days).') + '</p>');
}

function STRATEGY_SECTION(r) {
  var s = r.strategy, cv = s.curve, f = s.floors, c = s.counts;
  function ul(xs) { return '<ul class="lines">' + xs.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'; }
  function seenRows(list) {
    return strategyTable([['name', ''], ['n', 'offers'], ['outings', 'shift days'],
      [function (x) { return x.ph.p25; }, '$/hr P25', '$'], [function (x) { return x.ph.p50; }, 'median', '$'],
      [function (x) { return x.ph.p75; }, 'P75', '$'], [function (x) { return x.ph.p90; }, 'P90', '$'],
      [function (x) { return x.pm.p25; }, '$/mi P25', '$'], [function (x) { return x.pm.p50; }, 'median', '$'],
      [function (x) { return x.pm.p75; }, 'P75', '$'], [function (x) { return x.pm.p90; }, 'P90', '$'],
      ['freeHours', 'hours free', 'h'], ['perFreeHour', 'offers / hr free', 'r']], list,
      function (x) { return x.ph.p50 === null; });
  }
  function actRows(list, expected) {
    var cols = [['name', ''], ['timed', 'timed'], ['together', 'carried with another'], ['ratio', 'actual ÷ card min', 'x'],
                ['ratioMedian', 'typical order', 'x'], ['cardPH', 'median card $/hr', '$'], ['actualPH', 'median actual $/hr', '$'],
                ['milesN', 'with miles'], ['mileRatio', 'GPS ÷ card mi', 'x']];
    if (expected) cols.push(['expected', 'card ÷ ratio', '$']);
    return strategyTable(cols, list, function (x) { return x.ratio === null; });
  }
  function sliceRows(list) {
    return strategyTable([['name', ''], ['days', 'shift days'], ['freeHours', 'hours free', 'h'], ['offers', 'offers seen free'],
      ['timed', 'timed orders'], [function (x) { return x.best ? x.best.T : null; }, 'best line', '$'],
      [function (x) { return x.best ? x.best.value : null; }, '$/hr on shift', '$'],
      [function (x) { return x.best ? '$' + x.best.from + '–$' + x.best.to : null; }, 'about the same'],
      [function (x) { return x.everything.gross; }, 'taking everything', '$'],
      ['actualAtBest', 'actual $/hr of cards at the best line', '$']], list,
      function (x) { return !x.drawn || !x.best; });
  }
  var pointCols = [['T', 'line ($/hr+)', '$'], ['n', 'offers seen free'], ['perFreeHour', 'per hour free', 'r'],
                   ['pay', 'mean pay', '$'], ['cardMin', 'mean card min', 'r'], ['ratio', 'actual ÷ card', 'x'],
                   [function (p) { return p.ratioFrom === 'carried' ? 'carried from $' + p.ratioAt : p.ratioFrom; }, 'ratio from'],
                   ['gross', 'gross $/hr on shift', '$'], ['ci', '95%', '$ci'], ['net', 'net $/hr on shift', '$'],
                   [function (p) { return p.thin ? 'thin' : ''; }, '']];
  var mileCols = pointCols.filter(function (col) { return col[1] !== '95%'; }).map(function (col) {
    return col[0] === 'T' ? ['T', 'line ($/mi+)', '$'] : col;
  });
  function isThin(p) { return p.thin; }
  var mi = s.miles || {};
  // The order is the tab's own, top to bottom: the lines; the curve drawn,
  // its table folded under it; the slices drawn, their tables folded; the
  // $/mi curve folded whole (for reading only); then the two descriptive
  // halves, each with its all-offers row open and its breakdowns folded.
  // Every heading that opens a part has an id, so the Overview links to it.
  return '<section data-tab="strategy"><h2>Strategy — what $/hr to expect, and what holding out paid</h2>'
    + '<p class="exp">Descriptive. What your own record shows about the offers seen, what cards turned into, and what '
    + 'holding out for a line would have paid per hour on shift. Nothing here is an accept rule or changes a verdict; '
    + 'the $/mi figures are for reading only (AUDITS.md, Settled: a $/mile rule replayed 24% below $/hr).</p>'
    + ul(s.lines)
    + '<h3 id="s-curve">The accept-threshold curve</h3>'
    + '<p class="note">For each line T on the panel\'s $/hr: of the offers seen with no order in the car, those at T or more '
    + 'came at λ(T) an hour; each paid pay(T) and took time(T), its card minutes × the actual ÷ card ratio of the timed '
    + 'orders whose card was at T or more. <b>Effective $/hr on shift = pay(T) ÷ (1/λ(T) + time(T))</b> — every free hour '
    + 'waiting plus every order\'s time, over what they paid. A point with fewer than ' + f.curveOffers + ' offers is '
    + '<b>thin</b> (hollow): it is never the best and never in the flat region (shaded: within '
    + Math.round((1 - f.plateau) * 100) + '% of the best). The band is a 95% interval with shift days resampled ('
    + (cv.boots ? cv.boots + ' times' : 'not drawn: it needs ' + f.bootOutings + ' shift days') + '). '
    + '<b>Net</b> takes off ' + (cv.cost.perMile !== null ? '$' + cv.cost.perMile.toFixed(2) + '/mi (the rate the rows carry)'
      : 'nothing: the rows carry no running cost') + ' on the card\'s miles × '
    + (cv.cost.mileRatio !== null ? cv.cost.mileRatio.toFixed(2) + ' (GPS ÷ card miles over ' + cv.cost.milesN + ' orders)' : '1 (too few orders with miles)')
    + '. Dotted: taking everything. It reads low by whatever stacking earns: a driver who takes nothing while carrying.</p>'
    // The wide drawing on a laptop, the small one on a phone (the CSS picks).
    + '<div class="plot wide">' + strategyChart(cv) + '</div>'
    + '<div class="plot small">' + strategyChart(cv, 'small') + '</div>'
    + fold('s-points', 'Every point of the curve', strategyTable(pointCols, cv.points, isThin))
    + PASSED_PART(s)
    + GOLD_PART(s)
    + '<h3 id="s-slices">The same, by time of day, app and weekday</h3>'
    + '<p class="note">Point estimates, each slice\'s own free hours, offers and (with ' + f.ratio + ' or more) its own timed '
    + 'orders for the ratio. An app\'s curve is that app\'s cards alone in the same free hours. Read as description: a line '
    + 'tuned to the hour earned less on the nights it was not fitted to (AUDITS.md, Settled), and the held-out check in '
    + 'the lines above runs that test again on this record.</p>'
    + '<div class="plot fluid">' + blockChart(s.slices.block) + '</div>'
    + fold('s-blocks', 'By three-hour block', sliceRows(s.slices.block))
    + fold('s-apps', 'By app', sliceRows(s.slices.app))
    + fold('s-week', 'Weekday and weekend', sliceRows(s.slices.week))
    + fold('s-mile', 'The curve on $/mi — for reading only',
           '<p class="note">The same arithmetic with the line on pay ÷ card miles. Not an accept rule: printed because it was asked for.</p>'
           + strategyTable(mileCols, s.curveMile.points, isThin))
    + QUIET_PART(s)
    + '<h3 id="s-seen">What offers look like</h3>'
    + '<p class="note">Every offer seen that the rig stands behind (' + c.offers + ', once per offer; ' + c.untrusted
    + ' untrusted and ' + c.unrated + ' with no rate left out). $/hr is the panel\'s; $/mi is pay over the card\'s miles, '
    + 'nothing off. Weekend is a Saturday or Sunday shift day (4am to 4am). A quartile needs ' + f.dist + ' offers. '
    + 'Offers per hour free counts only offers seen with no order in the car, over the hours with none (' + c.freeHours
    + ' h of ' + c.shiftHours + ' h on shift); an area has no free hours of its own here (the Busy tab has them, off the GPS).</p>'
    + seenRows([s.seen.all])
    + fold('s-seen-app', 'By app', seenRows(s.seen.byApp))
    + fold('s-seen-block', 'By three-hour block', seenRows(s.seen.byBlock))
    + fold('s-seen-week', 'Weekday and weekend', seenRows(s.seen.byWeek))
    + fold('s-seen-town', 'By town (the card\'s own)', seenRows(s.seen.byArea || [])
      + (s.seen.areaThin ? '<p class="note">' + s.seen.areaThin.areas + ' towns under ' + f.dist + ' offers (' + s.seen.areaThin.offers
         + ' offers) and ' + s.seen.areaThin.noArea + ' offers with no town are not listed.</p>' : ''))
    + '<h3 id="s-actual">How cards turn into actuals</h3>'
    + '<p class="note">Over the orders this report timed at the door (as the Your takes tab: ' + c.timed + ' of ' + c.orders
    + ' taken; ' + c.unmeasured + ' with no time at the door, ' + c.addons + ' add-ons (their card minutes are an increment), '
    + c.tooSoon + ' put down in under ' + f.tooSoon + ' of the card, ' + c.clock + ' with a clock that stepped or held over '
    + f.holdMaxMin + ' min, left out). <b>Actual ÷ card</b> is the sum of actual minutes over the sum of card minutes, with '
    + 'the typical order\'s ratio beside it; a ratio needs ' + f.ratio + ' orders. Card and actual $/hr are both net of the '
    + 'card\'s running cost, as the panel\'s figure is. <b>Card ÷ ratio</b> is what a card in that band has turned into. '
    + 'Miles: the order record\'s odometer (' + (mi.odometer || 0) + ') or the GPS log (' + (mi.log || 0) + ')'
    + (mi.gps ? '' : '; no GPS log reached this report') + '.</p>'
    + actRows([s.actual.all])
    + fold('s-act-rate', 'By card $/hr', actRows(s.actual.byRate, true))
    + fold('s-act-app', 'By app', actRows(s.actual.byApp))
    + fold('s-act-length', 'By card length', actRows(s.actual.byLength))
    + fold('s-act-block', 'By three-hour block (of the Took)', actRows(s.actual.byBlock))
    + fold('s-act-town', 'By town (the card\'s own)', actRows(s.actual.byArea || []))
    + paidSection(s.paid)
    + '<p class="note">The shift: every offer seen and every order\'s hold, joined across silences under ' + f.breakMin
    + ' minutes; free is that less every hold (Took to its end, however it ended; the card\'s minutes where it has none). '
    + c.duplicates + ' repeat readings folded, ' + c.alone + ' offers alone in a silence, ' + c.held + ' seen with an order '
    + 'in the car, ' + c.addOnCards + ' add-on cards: none of them in λ.</p>'
    + '</section>\n';
}

/* The page's tabs, grouped by the question each answers (7 Nov 2026, the
 * owner: "consider how the page and tabs are laid out, is there a better
 * format for all this information?"). Twenty tabs in one wrapping row of
 * pills was four rows of buttons on a phone, below a banner taller than the
 * screen, before a single figure. Now four groups — the overview, what to
 * take, where and when, and the record — one row of groups and, under it,
 * the chosen group's tabs, which scroll sideways on a narrow screen. Every
 * tab and every hash the page ever had is still here (#targets, #strategy,
 * #best, ... a bookmark keeps working); only #overview is new, and it is
 * where a bare address opens.
 *
 * [group id, group label, [[tab id, tab label, what it answers, hours?], ...]]
 * `hours` marks the tabs the Hours picker reaches (they draw a view of
 * R.views); on the others it is hidden rather than left offering a choice
 * that changes nothing on the page. */
var GROUPS = [
  ['overview', 'Overview', [
    ['overview', 'Overview', 'The few numbers that matter, each linking to its tab.', false]]],
  ['take', 'What to take', [
    ['strategy', 'Strategy', 'What $/hr to expect, what cards turn into, what holding out for a line paid.', false],
    ['targets', 'Targets', 'The offers page\'s Targets lines, word for word, and the richer areas.', false],
    ['apps', 'Uber vs DoorDash', 'Each app\'s offers, $/hr, $/mi and your take, per area.', true],
    ['ppm', '$/mi', 'Pay over the card\'s miles per area — for reading, not a rule.', true]]],
  ['where', 'Where & when', [
    ['whenwhere', 'When & where', 'Which area gave the most good offers per hour waited, on the day and hours you pick.', false],
    ['around', 'Offers around you', 'Where the car was when each offer came up, good or not, home left out (the map needs the internet).', false],
    ['places', 'Places', 'Pinned pickups ranked against the same hours elsewhere.', true],
    ['restaurants', 'Restaurants', 'Pay by the name on the card, placed or not.', true],
    ['map', 'Map', 'The places and the 2-mile grid on a map (needs the internet).', true],
    ['towns', 'Towns', 'The card\'s own town, ranked.', true],
    ['grid', 'Grid', 'A 2-mile grid by the pickup\'s pin, ranked.', true],
    ['busy', 'Busy', 'Offers per hour while parked, by area and hours (GPS).', true],
    ['waited', 'Waited', 'Offers by where the car was when each came up (its own fix), against the same hours.', true],
    ['waits', 'Store waits', 'The rig\'s measured waits beside a place\'s pay.', true],
    ['after', 'After a drop', 'Where trips leave you: minutes to the next take.', true],
    ['strand', 'Strand risk', 'How far a store\'s cards run and where its trips end.', true],
    ['stack', 'Add-ons', 'Add-on and stacking chance per store.', true]]],
  ['record', 'Record', [
    ['best', 'Best offers', 'Where the top 10% turns up, per hour of waiting, dead miles, offer size.', true],
    ['takes', 'Your takes', 'What you took and what it really paid.', true],
    ['quiet', 'Gone quiet', 'Places and towns with fewer offers lately.', false],
    ['trend', 'Trend', 'Each area\'s score by week.', false],
    ['coverage', 'Coverage', 'What could be placed, by day and level, and what that biases.', false],
    ['method', 'Method', 'How every figure was measured.', false]]]
];
// ...and flat, in that order: [id, label], as the page has always listed them.
var TABS = [];
GROUPS.forEach(function (g) { g[2].forEach(function (t) { TABS.push([t[0], t[1]]); }); });

var EXPERIMENTAL = '<p class="exp">Experimental, descriptive: counts, medians and intervals. Nothing in this tab '
  + 'is ranked by a test or coloured, and none of it is a rule.</p>';

// The second pass's tabs, keyed by tab id (html() writes them in the nav's
// order). Each table sits in a fold() under its heading.
function MORE_SECTIONS(r) {
  var out = Object.create(null);
  function sec(id, title, note, divs) {
    out[id] = '<section data-tab="' + id + '"><h2>' + title + '</h2>' + EXPERIMENTAL + '<p class="note">' + note + '</p>'
      + divs.map(function (d) { return fold('f-' + d[0], d[1], '<div id="m-' + d[0] + '"></div>'); }).join('')
      + '</section>\n';
    return '';
  }
  var tk = r.takes;
  sec('takes', 'Your takes, and what they really paid',
             'Taken = the offer\'s id is one of the journal\'s taken orders (server.js takenRuns: a put-down row '
             + 'carrying its Took), ' + tk.taken + ' in the window, ' + tk.onCounted + ' on rows the rig stands behind. '
             + 'Take rate is taken over offered, with a Wilson 95% interval. <b>Real $/hr</b> is the card\'s pay over '
             + 'the real time, Took to put-down, before the car\'s cost (as the offers page\'s "Card against what it '
             + 'took"), and <b>only for orders put down at the door</b> by the GPS, the app\'s own screen, or a Drop '
             + 'press the GPS log timed (' + tk.timed + ' in all, ' + tk.gpsTimed + ' of them a press GPS-timed: the '
             + 'stop the press belongs to, its end the car leaving the door — Method says the rule). A press with no '
             + 'such stop (' + (tk.pressed - tk.gpsTimed) + ' of ' + tk.pressed + ') can come before the door and is left out. '
             + '<b>Real − card</b> is real minutes less the card\'s minutes. A median needs ' + r.realMedN
             + ' timed trips and an interval ' + r.descMinN + '; an area needs ' + r.descMinN
             + ' offers or one take to be listed.',
             [['takesPlace', 'By place'], ['takesTown', 'By town'], ['takesGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('apps', 'Uber against DoorDash',
          'Per area, each app\'s offers, median $/hr, median $/mi and the share you took. The app is the row\'s own, '
          + 'else offer-parser.js screenType off its text. A median needs ' + r.descMinN + ' offers of that app; an '
          + 'area needs ' + r.descMinN + ' offers. The first row is every area together.',
          [['appsPlace', 'By place'], ['appsTown', 'By town'], ['appsGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('ppm', '$/mi — pay over the card\'s miles',
          '<b>$/mi is shown for reading, not as an accept rule</b> (AUDITS.md, Settled: a $/mile rule measured worse '
          + 'than $/hr on the replay). The offers page\'s payPerMile: the card\'s pay over its miles, nothing taken '
          + 'off, no card under a tenth of a mile. Median with a 95% bootstrap interval, areas with '
          + r.descMinN + ' or more; per app where that app has ' + r.descMinN + '. Click a column to sort.',
          [['ppmPlace', 'By place'], ['ppmTown', 'By town'], ['ppmGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('waits', 'Restaurant waits beside pay',
          'The rig\'s measured waits at a store (server.js storeWaitsOut: name, how many, the median and the worst '
          + 'minutes, and how many were found from the stop pattern — the car\'s first stop of two minutes or more '
          + 'after the Took, for a pickup the GPS never visited because it was never pinned; '
          + r.waitsOnRecord + ' stores on record' + (r.waitsFrom ? ', from ' + esc(r.waitsFrom) : '') + ') joined to a place by its name as Assemble.sameStore compares '
          + 'two, and only where the join is not a guess: not a chain\'s name, one store of that name on record, and '
          + 'one place of that name here. The waits are all hours; the pay follows the hours picked.',
          [['waits', 'Places']])
    + sec('strand', 'Strand risk per store',
          'Per pickup place: how far its cards run (median card miles), where its taken trips ended — by town and '
          + 'by 2-mile cell, counts only, a cell named only where "Where trips leave you" names it — its own '
          + 'measured minutes to the next take after those trips, and the wait its trips\' towns predict: the mean '
          + 'of the town table\'s median wait over its trips, shown when the towns that clear that table\'s floor '
          + 'cover half its trips.',
          [['strand', 'Places']])
    + sec('busy', 'How busy each area is, while you wait',
          (r.spells.gps ? r.spells.n + ' spells, ' + r.spells.hours + ' hours. ' : '<b>No GPS log was given (--gps), '
            + 'so there are no spells.</b> ')
          + 'A spell is the car parked: every GPS fix within ' + r.spellM + ' m of the first, for '
          + Math.round(r.spellMinS / 60) + ' minutes or more, no gap over ' + Math.round(r.spellGapS / 60)
          + ' minutes, and <b>no order in the car</b> (every taken order\'s Took to put-down is cut out). '
          + 'Thresholds chosen, not measured. Per area and three-hour block: hours waited, offers the rig counted '
          + 'per hour of it, the share of spells that saw an offer the rig said take, and the minutes to the first. '
          + 'Under ' + r.spellMinN + ' spells or ' + r.minOutings + ' shift days a row gives its n only. The town is '
          + 'the NucBox map\'s name for the 2-mile cell\'s centre (' + r.spells.towns + ' spells named).',
          [['busyTown', 'By town'], ['busyGrid', 'By ' + r.gridMi + '-mile cell']])
    + sec('stack', 'Add-on and stacking chance per store',
          'The share of a store\'s offers whose card was an Uber add-on, more than one order, more than one '
          + 'dropoff, or an early look — each over the cards where it could be read (the row\'s field, else its '
          + 'text by scan_pi\'s own patterns). Places with ' + r.descMinN + ' offers or more.',
          [['stack', 'Places']])
    + sec('quiet', 'Gone quiet',
          'The last ' + r.quietDays + ' days of the record (to its newest offer, not today) against the rest'
          + (r.quiet.place.cut ? ', split at ' + esc(r.quiet.place.cut) + ' (' + r.quiet.place.outingsBefore
             + ' shift days before, ' + r.quiet.place.outingsRecent + ' since)' : '') + '. <b>Fewer offers</b>: '
          + 'with ' + r.minN + '+ offers before and 3+ shift days since, the before rate per shift day out predicts '
          + '5 or more since, and a count this low has Poisson p < ' + r.alpha + '. <b>Lower score</b>: '
          + r.descMinN + '+ hour-held scores each side, recent below before, rank test p < ' + r.alpha
          + '. All hours only.',
          [['quietPlace', 'By place'], ['quietTown', 'By town']])
    + sec('trend', 'Trend by week',
          'Each ranked area\'s score — its offers\' $/hr against the other cells in the same three-hour block — '
          + 'by ISO week of the shift day, weeks with ' + r.descMinN + ' or more offers only (a week under that is '
          + 'left out of the line, not drawn as zero; hover a line for its weeks). The dashed rule is zero; every '
          + 'line is on one scale. All hours only.',
          [['trendPlace', 'By place'], ['trendTown', 'By town']]);
  return out;
}

/* The When & where tab (whenWhere). The pickers and the rule are written
 * here, so a page with its script off still says what was measured and
 * where the cutoff sits; the script fills the slot's line and its areas from
 * R.whenwhere, and does nothing to them but pick and sort. */
function wwDayName(o) {
  return o === 'any' ? 'Any day' : o === 'wkday' ? 'Weekdays (Mon–Fri)' : o === 'wkend' ? 'Weekends (Sat, Sun)'
    : WW_DAYS[Number(o)];
}
function WHENWHERE_SECTION(r) {
  var w = r.whenwhere, ti = w.tops.indexOf(w.top), any = w.slots['any|any'];
  function opt(v, text, on, name) {
    return '<option value="' + esc(v) + '"' + (on ? ' selected' : '') + (name ? ' data-name="' + esc(name) + '"' : '')
      + '>' + esc(text) + '</option>';
  }
  function hoursIn(key) { var sl = w.slots[key]; return (sl ? sl.all.h : 0).toFixed(1) + ' h'; }
  function cutSaid(i) { return w.cuts[i] === null ? 'no offers yet' : 'good = top ' + w.tops[i] + '%: ≥ ' + money(w.cuts[i]) + '/hr'; }
  // By town where the NucBox named the cells the car waited in; else the cells.
  var towns = any ? any.town.ranked.length + any.town.thin.length : 0;
  return '<section data-tab="whenwhere"><h2>When &amp; where — which area, on the day and hours you pick</h2>'
    + '<p class="exp">Experimental, descriptive. <b>Offered, not earned</b>: offers are dispatched near the car, so '
    + 'only areas you already wait in compete, and a good offer seen is not one taken. Nothing here is a rule, and '
    + 'nothing on the rig reads it.</p>'
    + '<p class="note">Every area where the car waited, for the slot you pick, ranked by <b>good per hour waited '
    + '(each gap capped at ' + r.waited.creditMaxMin + ' min, none while carrying)</b>. That is not the offers page\'s '
    + 'Trends "good per hour online", which counts every minute the rig was scanning, carrying included: the two '
    + 'measure different hours, so their figures differ by design. <b>Day</b> is the driver\'s, 4am to 4am: 1am on a Saturday is Friday night; Weekends are the '
    + 'driver\'s Saturday and Sunday. <b>Where</b> is the car\'s own GPS fix on each card that came with no order in '
    + 'the car (the Waited tab\'s line: ' + w.cards + ' cards), by the town of its ' + r.gridMi + '-mile cell or the '
    + 'cell itself; <b>hours waited</b> are inferred as that tab infers them, each card\'s time to the next, at most '
    + r.waited.creditMaxMin + ' minutes and none across a silence over ' + r.nextGapMin + '. <b>Good</b> is the card\'s '
    + '$/hr at or over one fixed cutoff, the top share picked of all ' + w.offers + ' offers in this report\'s range, '
    + 'the same dollars in every slot and the same as the Strategy tab\'s section 7, over this report\'s '
    + r.outings + ' days: <b id="wwCut">' + esc(cutSaid(ti)) + '</b>. The interval is the exact 99% '
    + 'Poisson interval on the good offers over the hours, widened by how much more an area\'s days differ than '
    + 'chance alone would (×' + (w.phi ? w.phi.town[ti].toFixed(2) + ' by town, ×' + w.phi.cell[ti].toFixed(2) + ' by cell'
    : '1') + ' on this record); an area is <b>marked only where it lies wholly above or '
    + 'below the slot\'s own rate</b>, and printed without colour otherwise. About 1 coloured square in 100 can be '
    + 'chance. Ranked at ' + w.minHours + ' h waited on '
    + w.minDays + ' shift days in the slot; under that, listed as too little time there yet.</p>'
    + '<div class="bar" id="wwBar">'
    + '<label>Day <select id="wwDay">' + w.dayOpts.map(function (o) {
      return opt(o, wwDayName(o) + ' · ' + hoursIn(o + '|any'), o === 'any', wwDayName(o));
    }).join('') + '</select></label>'
    + '<label>Hours <select id="wwBlock">' + w.blockOpts.map(function (o) {
      var nm = o === 'any' ? 'Any time' : w.blocks[Number(o)];
      return opt(o, nm + ' · ' + hoursIn('any|' + o), o === 'any', nm);
    }).join('')
    // The single hours after the blocks, in one picker rather than a second
    // control: on a phone one select is one tap, and a toggle beside it was
    // a fifth control on a bar that already wraps to four lines.
    + '<optgroup label="One hour">' + w.hourOpts.map(function (o, i) {
      return opt(o, w.hours[i] + ' · ' + hoursIn('any|' + o), false, w.hours[i]);
    }).join('') + '</optgroup></select></label>'
    + '<label>Good <select id="wwTop">' + w.tops.map(function (t, i) {
      return opt(String(i), 'top ' + t + '%' + (w.cuts[i] === null ? '' : ' (≥ ' + money(w.cuts[i]) + '/hr)'), i === ti);
    }).join('') + '</select></label>'
    + '<label>Area <select id="wwUnit">' + opt('town', 'Town', towns > 0) + opt('cell', r.gridMi + '-mile cell', !towns)
    + '</select></label></div>'
    + '<p class="lead" id="wwSlot"></p>'
    + '<div class="wwstrip" id="wwStrip" role="group" aria-label="Good offers per hour waited, by clock hour"></div>'
    + '<p class="note" id="wwStripNote"></p><div id="wwTable"></div><div id="wwThin" class="thin"></div>'
    + '</section>\n';
}

/* The Offers around you tab (aroundYou). The pickers are When & where's —
 * the same choices, the same driver day and blocks and hours, the same
 * cutoffs — with their own ids, so each tab keeps its own pick. What is
 * left out, and why, is written here, so a page with no script (or no
 * internet for the map) still says it. */
function AROUND_SECTION(r) {
  var a = r.around, w = r.whenwhere, ti = w.tops.indexOf(w.top), L0 = a.left;
  function opt(v, text, on, name) {
    return '<option value="' + esc(v) + '"' + (on ? ' selected' : '') + (name ? ' data-name="' + esc(name) + '"' : '')
      + '>' + esc(text) + '</option>';
  }
  var drawn = a.dots.b.length;
  return '<section data-tab="around"><h2>Offers around you — where the car was when each offer came up</h2>'
    + '<p class="exp">Experimental, descriptive. <b>Offered, not earned</b>: offers are dispatched near the car, so '
    + 'this shows the offers that came where you already wait, not what a place you never tried would send. '
    + 'Nothing here is a rule, and nothing on the rig reads it.</p>'
    + '<p class="note">One dot per offer that came with no order in the car (the Waited tab\'s line: '
    + a.cards + ' cards), at the car\'s own GPS fix the gate passed — never a pin, never DoorDash\'s map label. '
    + '<span class="k up">●</span> good: its $/hr at or over the cutoff picked, the same dollars in every slot '
    + '(<b id="aCut">' + (w.cuts[ti] === null ? 'no offers yet' : 'top ' + w.top + '%: ≥ ' + money(w.cuts[ti]) + '/hr')
    + '</b>); <span class="k grey">●</span> the rest. Each dot sits in its ' + a.binMi + '-mile square, spread inside '
    + 'it, so a busy spot is a disc of dots whose colours are its offers: a dot is one offer, never an area\'s '
    + 'average, so no square is coloured by a share. A square is drawn only where the car was on ' + a.binDays
    + ' shift days or more, so a door passed once (a drop) is never a dot. <b>Home is left out</b>: each day\'s '
    + 'starting stay (every card before the car first moves more than ' + a.homeMi + ' mi from where the day began) '
    + 'and every card within ' + a.homeMi + ' mi of a place two or more days began at — so going online at home '
    + 'never draws home. That also leaves out a day begun at a restaurant until the car leaves it. Left out: '
    + L0.start + ' cards in a starting stay, ' + L0.usual + ' near a usual start (' + a.usualDays + ' of '
    + a.homeDays + ' days began at one), ' + L0.oneDay + ' in a square seen on one day only, ' + L0.noFix
    + ' with no fix the gate passed. ' + drawn + ' dots drawn.</p>'
    + '<div class="bar" id="aBar">'
    + '<label>Day <select id="aDay">' + w.dayOpts.map(function (o) {
      return opt(o, wwDayName(o), o === 'any', wwDayName(o));
    }).join('') + '</select></label>'
    + '<label>Hours <select id="aBlock">' + w.blockOpts.map(function (o) {
      var nm = o === 'any' ? 'Any time' : w.blocks[Number(o)];
      return opt(o, nm, o === 'any', nm);
    }).join('')
    + '<optgroup label="One hour">' + w.hourOpts.map(function (o, i) {
      return opt(o, w.hours[i], false, w.hours[i]);
    }).join('') + '</optgroup></select></label>'
    + '<label>Good <select id="aTop">' + w.tops.map(function (t, i) {
      return opt(String(i), 'top ' + t + '%' + (w.cuts[i] === null ? '' : ' (≥ ' + money(w.cuts[i]) + '/hr)'), i === ti);
    }).join('') + '</select></label></div>'
    + '<p class="lead" id="aSays"></p>'
    + '<div id="aMap" class="amap" role="img" aria-label="Where the car was when each offer came up"></div>'
    + '<p class="note" id="aMapNote"></p>'
    + '<h3>Good offers by distance from your most-used waiting area</h3>'
    + '<p class="note">' + (a.centre ? 'Rings of ' + a.ringMi + ' mile from the centre of the ' + r.gridMi
      + '-mile cell where the car waited longest among the dots drawn (' + a.centre.hours + ' h credited, the home '
      + 'stays already out), measured from each dot\'s square. The share of each ring\'s offers that were good, '
      + 'with its 95% Wilson interval; a ring under ' + r.descMinN + ' offers gives its n only. The last ring is '
      + a.rings + ' mi and beyond.' : 'No dot to measure from yet.') + '</p>'
    + '<div id="aRings" class="hbars"></div>'
    + '<h3>Good offers per hour waited, by area, for the slot picked</h3>'
    + '<p class="note">When &amp; where\'s own table for the same day and hours, drawn: good offers per hour waited '
    + 'there, its 99% interval as the whisker, coloured only where that tab marks it (wholly above or below the '
    + 'slot\'s own rate). Ranked at ' + w.minHours + ' h on ' + w.minDays + ' shift days. That table counts every '
    + 'waiting card, so home is not left out of it yet (AUDITS.md, Open).</p>'
    + '<div id="aAreas" class="hbars"></div>'
    + '<h3>Good offers by the card\'s own drive to the pickup</h3>'
    + '<p class="note">Needs no GPS: the miles to the pickup the card itself printed ("x min (y mi) away", the leg '
    + 'offer-parser.js splits off where the card prints it — mostly Uber\'s), over every counted offer in the slot, '
    + 'an order in the car or not. The share good at the cutoff picked (95% Wilson) and the median $/hr; a band '
    + 'under ' + r.descMinN + ' offers gives its n only. To read, not a distance rule.</p>'
    + '<div id="aPickup" class="hbars"></div>'
    + '</section>\n';
}

/* The Best offers tab: plain lines first, then where good offers turn up
 * per hour of waiting and what working an area paid, then the share tests,
 * then the descriptive tables. */
function BEST_SECTION(r) {
  function tbl(id, title) { return fold('f-b-' + id, title, '<div id="b-' + id + '"></div>'); }
  var b = r.best;
  return '<section data-tab="best"><h2>Best offers — where the top of the pay turns up</h2>'
    + '<p class="exp">Experimental. Offered, not earned; only near where you wait; and see Coverage for what could '
    + 'be placed. Thresholds are percentiles of your own offers, to read — not an accept rule.</p>'
    + '<ul class="lines">' + bestLines(r).map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul>'
    + '<p class="note"><b>Top 25% / top 10%</b>: an offer at or over the 75th / 90th percentile $/hr of EVERY offer '
    + 'in its own three-hour block (' + b.tierMinN + ' offers for a block to have one), so each hour is held to '
    + 'itself. <b>Rig said take</b> is the rig\'s own verdict at the time. <b>Per hour of waiting</b> counts the '
    + 'offers that came while the car was parked in that area with no order in it (the Busy tab\'s spells), over '
    + 'the hours parked; ' + b.spellMinN + ' spells on ' + r.minOutings + ' shift days for a figure. <b>Expected $/hr '
    + 'working it</b> = pay of the orders taken while waiting there (a Took inside the spell or ' + b.takeSlackMin
    + ' min after) ÷ (hours waited + those orders\' real hours); only orders with a real time count, on both '
    + 'sides, so many untimed takes make it read low. <b>If every top 10% taken</b> is the pay of the top-10% '
    + 'offers seen while waiting ÷ (hours waited + their card minutes): <b>offered, not earned</b>, and it ignores '
    + 'that taking one ends the wait.</p>'
    + tbl('waitTown', 'Waiting, by town and hours') + tbl('waitGrid', 'Waiting, by ' + r.gridMi + '-mile cell and hours')
    + '<h3>Does the top-10% share differ by area? (all hours, hours held)</h3><p class="note">A permutation of the '
    + 'top-10% marks within each three-hour block (' + r.shuffles + ' shuffles); the score is a group\'s share less '
    + 'what the other groups showed in the same hours, with a 95% bootstrap interval. Coloured only where the test '
    + 'beats chance and the interval is clear of zero. ' + r.minN + ' offers on ' + r.minOutings + ' shift days.</p>'
    + fold('shareTestsFold', 'The tests, group by group', '<div id="shareTests"></div>')
    + tbl('goodTown', 'Good offers by town') + tbl('goodRest', 'Good offers by restaurant (the name on the card)')
    + tbl('goodGrid', 'Good offers by ' + r.gridMi + '-mile cell') + tbl('goodApp', 'Good offers by app')
    + '<h3>Offer size</h3><p class="note">By card miles: under 4, 4–8, 8–12, 12 and over. Median and P90 $/hr, '
    + 'top-10% share, and $/mi — <b>$/mi for reading, not an accept rule</b>. A median needs ' + r.descMinN + '.</p>'
    + tbl('sizeTown', 'By town') + tbl('sizeApp', 'By app') + tbl('sizeRest', 'By restaurant')
    + '<h3>Dead miles after a drop</h3><p class="note">' + (b.dead.gps ? b.dead.n + ' trips measured. '
      : '<b>No GPS log was given (--gps), so nothing is measured.</b> ')
    + 'From each put-down at the door to the next Took: the GPS log\'s miles (straight lines between fixes ten '
    + 'seconds apart, a little under the road), plus the next card\'s printed drive to the pickup where Uber printed '
    + 'one. Not counted: no Took within ' + b.deadMaxMin + ' minutes, or the log broken between. <b>Unpaid share</b> '
    + '= dead ÷ (dead + the delivered trips\' card miles). By the dropoff\'s town and cell, counts only; a cell under '
    + r.dropMinN + ' measured trips is not named.</p>'
    + tbl('deadTown', 'By dropoff town') + tbl('deadGrid', 'By dropoff cell')
    + '</section>\n';
}

function METHOD(r) {
  var b = r.best;
  return '<ul>'
    + '<li><b>Placing a pickup, third pass</b>: map-view.js\'s NbxSearch chain — the door as printed, the type word '
    + 'left out, the directional the other way, the street index\'s one street for the name as read, the street '
    + 'alone where nothing answered; a corner by the street index; a numberless street by its <code>whole</code> '
    + 'answer; a refused door\'s candidates by the distance band (road miles off the router, held to the card\'s '
    + 'own figure — distance only). Levels: door, corner, name (a point); band, area, street (an area, with its '
    + 'spread). <b>Places</b> take a point, and an area only within ' + PLACE_SAME_MI + ' mi of a point of the same store '
    + 'or with its candidates within ' + b.placeApproxMi + ' mi (chosen); <b>the grid</b> every level within '
    + b.areaMi + ' mi; towns unchanged.</li>'
    + '<li><b>A DoorDash pickup by its printed door</b>, as the rig asks it: the store\'s door the card printed under '
    + 'its name (<code>pickupLine</code>, or its line among the card\'s stores) first, at door level, the store\'s '
    + 'name along that street only after the door refused; then the name alone as before (one place of that name '
    + 'in the disc). With neither, the door\'s refusal is what is counted.</li>'
    + '<li><b>Cards with no fix</b>: a printed door with its town or ZIP is searched in the region '
    + (b.region ? 'from ' + b.region.box.s.toFixed(2) + ',' + b.region.box.w.toFixed(2) + ' to ' + b.region.box.n.toFixed(2)
       + ',' + b.region.box.e.toFixed(2) + ' (the box round ' + b.region.fixes + ' good card fixes, ' + b.region.marginMi
       + ' mi wider each way)' : '(none: the record has no good card fix)')
    + ', kept only at door or corner level with the printed town or ZIP at the pin. A store name with no fix is '
    + 'not placed: a chain is everywhere.</li>'
    + '<li><b>A pressed drop timed by the GPS</b> (chosen, not measured): the stop — every fix within ' + b.stopM
    + ' m for ' + b.stopMinS + ' s or more, beginning after the Took — that contains the press, else the first '
    + 'starting within ' + b.pressAfterMin + ' min after it, else the last ending within ' + b.pressBeforeMin
    + ' min before it; the real end is that stop\'s end, the car leaving the door. No stop: still left out. '
    + 'A stop reached with the car\'s GPS miles since the Took under ' + b.shortMiles + ' of the card\'s (an '
    + 'add-on aside) is the pickup\'s, not the door: left out too. '
    + (b.presses ? b.presses.timed + ' of ' + b.presses.pressed + ' presses timed (' + b.presses.inside + ' inside, '
       + b.presses.early + ' early, ' + b.presses.late + ' late; ' + (b.presses.short || 0)
       + ' at a stop not driven to).' : 'No GPS log, so none timed.') + '</li>'
    + '<li><b>Top tiers, P75 and P90</b>: percentiles of $/hr (linear between order statistics); intervals are '
    + 'bootstraps at ' + r.minN + ' values or more, and the binomial order-statistic interval at ' + Q_BOOT_MAX
    + ' or more.</li>'
    + '<li><b>$/hr</b> is the card\'s rate as the rig worked it out (the row\'s <code>perHour</code>, pay less the car\'s '
    + 'cost over the minutes it was judged over), on rows advice.js\'s <code>trustworthy</code> keeps.</li>'
    + '<li><b>Score</b> is the median, over a cell\'s offers, of each offer\'s $/hr less what the <i>other</i> ranked '
    + 'cells paid in the same three-hour block — advice.js\'s <code>matched</code>, the figure the rig\'s town table ranks by. '
    + 'Zero is "paid what the same hours paid elsewhere".</li>'
    + '<li><b>The test</b> is advice.js\'s <code>areas</code>: Kruskal-Wallis H on ranks against ' + r.shuffles
    + ' seeded shuffles of the same rates, confined within three-hour blocks in the all-hours view. '
    + 'Alpha ' + r.alpha + '.</li>'
    + '<li><b>Intervals</b> are 95% percentile bootstraps of the median (' + r.boots + ' resamples, seeded).</li>'
    + '<li><b>Colour</b> only where the grouping beats chance <i>and</i> the cell\'s score interval is clear of zero. '
    + 'No colour bands: AUDITS.md measured a band map miscolouring 21-25% of cells with no effect at all.</li>'
    + '<li><b>Too few:</b> under ' + r.minN + ' offers or ' + r.minOutings + ' shift days a cell is listed with its n '
    + 'and neither ranked nor tested (' + r.dropMinN + ' trips for the wait after a drop).</li>'
    + '<li><b>Placing a pickup</b> uses map-view.js as the rig\'s server does for an order in the car: a printed door '
    + 'by its door, a store\'s name by <code>pickPlace</code>, both inside the disc round the card\'s GPS fix and the card\'s '
    + 'own distance; pinned only where one place answers. The local NucBox only, never the public geocoder.</li>'
    + '<li><b>Take share</b> is the share of a cell\'s offers the rig itself said <b>take</b> (go) at the time, '
    + 'against the target you had then.</li>'
    + '<li><b>When &amp; where</b>: the Waited tab\'s line (the cards that came with no taken order in the car, at '
    + 'the car\'s own gated GPS fix; never a pin or DoorDash\'s map label), each card in the slot of its driver\'s day '
    + '(4am to 4am) and one of six blocks (' + r.whenwhere.blocks.join(', ') + '; chosen round the meal peaks and so '
    + 'that a night stays whole in its shift day, not measured) or one clock hour of it (4am first, 3am last: 3am '
    + 'on a Saturday is Friday\'s last hour). Hours waited: each card\'s time to the next, at most '
    + r.waited.creditMaxMin + ' min, none across a silence over ' + r.nextGapMin + ' min, credited to the earlier '
    + 'card\'s area. Good: the card\'s $/hr at or over a fixed cutoff, the top 10/20/30/50% of all ' + r.whenwhere.offers
    + ' counted offers in the range (' + r.whenwhere.tops.map(function (t, i) {
      return 'top ' + t + '% ≥ ' + money(r.whenwhere.cuts[i]);
    }).join(', ') + '), worked out once and held fixed across every slot and area, and handed to the Strategy tab\'s '
    + 'section 7 so both read one line. Good/hr with its exact (Garwood) '
    + Math.round(r.whenwhere.conf * 100) + '% Poisson interval, the hours taken as exact, widened by phi: Pearson\'s '
    + 'chi-square of each area\'s shift days against its own rate within each weekday and block, pooled, never under '
    + '1 (trends.js dispersion, as the offers page\'s Trends grid); the hour strip by one phi over every weekday and '
    + 'hour. A plain interval marked 4-13% of no-effect areas once the nights swing 40%; widened, about 1%. An area is ranked at '
    + r.whenwhere.minHours + ' h waited on ' + r.whenwhere.minDays + ' shift days in the slot (chosen: two days is the '
    + 'report\'s own floor, two hours a dozen card gaps at least) and marked only where its interval lies wholly '
    + 'above or below the slot\'s overall rate. A single hour takes the same cutoff, interval, marking and floor, '
    + 'so most areas sit under the floor there; the <b>hour strip</b> draws the slot\'s own line for each of the day\'s '
    + '24 hours (every area together), held to the same floor (grey with its n under it) and marked by the same rule '
    + 'against every slot together. A card\'s credit counts in the hour its card came up in, though up to '
    + r.waited.creditMaxMin + ' min of it may run into the next. <b>Offered, not earned</b>, and descriptive: it never feeds the '
    + 'rig, a verdict, the target or the accept line, and the line is not tuned to an hour or a weekday.</li>'
    + '<li><b>Offers around you</b>: the same line as When &amp; where (no order in the car, the car\'s own gated '
    + 'fix), one dot per offer, coloured by its own $/hr against When &amp; where\'s fixed cutoff for the top share '
    + 'picked, with that tab\'s Day and Hours choices. <b>Dots, not a coloured grid</b>: a dot is one offer\'s own '
    + 'fact, so nothing estimated is coloured (AUDITS.md\'s heat-map entry measured a band-coloured grid '
    + 'miscolouring a fifth of its cells at a dozen offers). Each dot keeps only its ' + r.around.binMi + '-mile '
    + 'square (gridCell, the 2-mile grid\'s rule at a quarter mile) and is drawn on a sunflower inside it; a square '
    + 'is drawn only where the car was on ' + r.around.binDays + ' shift days or more, so a door passed once after a '
    + 'drop is never a dot (chosen, the report\'s own two-day rule). <b>Home</b> (chosen, not measured): each driver '
    + 'day\'s starting stay — every card before the car\'s fix first lies more than ' + r.around.homeMi + ' mi from '
    + 'that day\'s first fix — and every card within ' + r.around.homeMi + ' mi of a first fix two or more days share, '
    + 'on any day, are left out; ' + r.around.homeMi + ' mi is the report\'s distance for one place, about six times the '
    + 'GPS gate\'s worst error. <b>Rings</b>: whole miles from the centre of the ' + r.gridMi + '-mile cell with the '
    + 'most credited waiting hours among the dots drawn, measured from each dot\'s square; the share good with '
    + 'Wilson\'s 95% interval at ' + r.descMinN + ' offers. <b>Areas</b>: When &amp; where\'s own slot table, drawn, '
    + 'home not left out of it (AUDITS.md, Open). <b>Drive to the pickup</b>: the card\'s own toPickupMiles '
    + '(offer-parser.js\'s split of the approach leg, where the card prints one), every counted offer, no GPS: '
    + 'the share good and the median $/hr per band (' + r.around.pickup.bands.join(', ') + '). Descriptive, like '
    + 'everything here: no distance or $/mi rule, no floor, and nothing reaches the rig.</li>'
    + '</ul>';
}

/* The page's style and script, real files beside this one and read once
 * when this loads: the script was ~890 lines inside String(function),
 * which no linter or editor reads as the browser code it is. What reaches
 * the page is what String(function) gave, to the byte: the style without
 * the comments page.css keeps for its reader, the script from the line
 * that opens "(function () {", without the header that says what it is. */
var PAGE_CSS = fs.readFileSync(path.join(__dirname, 'page.css'), 'utf8')
  .replace(/^\/\*[\s\S]*?\*\/\n/gm, '').replace(/\n$/, '');
var PAGE_JS = (function (src) { return src.slice(src.indexOf('\n(function () {') + 1).replace(/\n$/, ''); }(
  fs.readFileSync(path.join(__dirname, 'page.js'), 'utf8')));

module.exports = {
  targetAreaLines: targetAreaLines, testLine: testLine, summary: summary, html: html, fold: fold,
  glanceSection: glanceSection, blockChart: blockChart, paidSection: paidSection, GROUPS: GROUPS, TABS: TABS,
};
