/* The places report's tables as CSV, one file a table, written beside the
 * page. Every figure is the report object's; nothing is worked out here. */

'use strict';

var TR = require('../../trends.js');
var ST = require('./stats.js');
var VIEWS = ST.VIEWS, shareName = ST.shareName, labelOf = ST.labelOf;

/* --- CSV ----------------------------------------------------------------- */

/* A text cell goes through trends.js's safeCell, the rule the offers page's
 * every-offer and records CSVs already keep: these files carry card text too
 * (a pickup, a restaurant, a town as the card spelled it), and a pickup read
 * as "=HYPERLINK(...)", "-" or "+ 1 order" went out raw and ran as a formula
 * when places.csv was opened in Excel. A number is a figure and keeps its
 * sign. A \r is quoted as \n is: bare, a spreadsheet ends the row on it. */
function csvCell(v) {
  if (v === null || v === undefined) return '';
  var s = typeof v === 'number' ? String(v) : TR.safeCell(String(v));
  return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

/* Each file starts with the BOM the offers page's CSVs start with (trends.js
 * BOM): without it Excel opens UTF-8 in the machine's code page, and every
 * "6–9pm" hours label came out as mojibake. Put on as a file is written
 * (io.js writeCsv), so the text the suite matches line by line is the table
 * alone. */
var BOM = TR.BOM;

function csvOf(r, kind) {
  var head = ['hours', kind === 'grid' ? 'cell' : kind, 'lat', 'lon', 'n', 'outings',
              'median_per_hour', 'median_lo', 'median_hi', 'score_vs_same_hours', 'score_lo',
              'score_hi', 'median_pay', 'share_rig_said_take', 'clear', 'beats_chance',
              'grouping_p', 'ranked', 'p75_per_hour', 'p90_per_hour', 'p90_lo', 'p90_hi', 'top25_share',
              'top10_share'];
  var lines = [head.join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v][kind];
    c.groups.forEach(function (g) {
      var at = kind === 'place' ? r.places[g.name] : kind === 'grid' ? r.cells[g.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, g.name), at && at.lat, at && at.lon, g.n,
                  g.outings, g.median, g.ci && g.ci[0], g.ci && g.ci[1], g.score,
                  g.sci && g.sci[0], g.sci && g.sci[1], g.pay, g.take, g.clear,
                  g.beats ? 'yes' : 'no', c.p, 'yes', g.p75, g.p90, g.p90Ci && g.p90Ci[0], g.p90Ci && g.p90Ci[1],
                  g.top25, g.top10].map(csvCell).join(','));
    });
    c.thin.forEach(function (t) {
      var at = kind === 'place' ? r.places[t.name] : kind === 'grid' ? r.cells[t.name] : null;
      lines.push([r.views[v].name, labelOf(r, kind, t.name), at && at.lat, at && at.lon, t.n,
                  t.outings, '', '', '', '', '', '', '', '', '', 'too few', c.p, 'no', '', '', '', '', '', '']
                 .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function dropCsv(r, kind) {
  var head = ['hours', kind === 'dropGrid' ? 'cell' : 'town', 'trips', 'measured', 'ended_unmeasured',
              'median_wait_min', 'wait_lo', 'wait_hi', 'wait_vs_same_hours', 'vs_lo', 'vs_hi',
              'next_take_per_hour', 'next_take_pay', 'grouping_p'];
  var lines = [head.join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v][kind];
    c.groups.forEach(function (g) {
      var name = kind === 'dropGrid' && g.box
        ? 'cell near ' + g.box.lat.toFixed(3) + ', ' + g.box.lon.toFixed(3) : g.name;
      lines.push([r.views[v].name, name, g.trips, g.n, g.ended, g.median, g.ci && g.ci[0],
                  g.ci && g.ci[1], g.score, g.sci && g.sci[0], g.sci && g.sci[1], g.nextPerHour,
                  g.nextPay, c.p].map(csvCell).join(','));
    });
    c.thin.forEach(function (t) {
      lines.push([r.views[v].name, t.name, '', t.n, '', 'too few', '', '', '', '', '', '', '', c.p]
                 .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

/* One of the second pass's tables as CSV: its raw values, an interval as
 * two columns, a trend's weeks as one line each; per hours view when `pick`
 * takes a view, else once. */
function tableCsv(r, pick, perView) {
  var lines = [], head = null;
  function emit(t, hours) {
    if (!t || !t.cols || !t.cols.length) return;
    var spark = t.cols.filter(function (c) { return c.f === 'spark'; })[0];
    var flat = t.cols.filter(function (c) { return c.f !== 'spark'; });
    if (!head) {
      head = (perView ? ['hours'] : []).concat([].concat.apply([], flat.map(function (c) {
        return /ci$/.test(c.f) ? [c.k + '_lo', c.k + '_hi'] : [c.k];
      }))).concat(spark ? ['week', 'week_n', 'week_score', 'week_lo', 'week_hi'] : []);
      lines.push(head.join(','));
    }
    t.rows.forEach(function (row) {
      var cellsOut = (perView ? [hours] : []).concat([].concat.apply([], flat.map(function (c) {
        var v = row[c.k];
        return /ci$/.test(c.f) ? [v ? v[0] : null, v ? v[1] : null] : [v];
      })));
      if (!spark) { lines.push(cellsOut.map(csvCell).join(',')); return; }
      (row[spark.k] || []).forEach(function (w) {
        lines.push(cellsOut.concat([w.w, w.n, w.score, w.ci && w.ci[0], w.ci && w.ci[1]]).map(csvCell).join(','));
      });
    });
  }
  if (perView) VIEWS.forEach(function (v) { emit(pick(r.views[v]), r.views[v].name); });
  else emit(pick(r), null);
  return (lines.length ? lines.join('\n') : '') + '\n';
}

// The second pass's CSVs: file name -> [pick, per hours view].
var MORE_CSVS = {
  'takes_places.csv': [function (v) { return v.more.takesPlace; }, true],
  'takes_towns.csv': [function (v) { return v.more.takesTown; }, true],
  'takes_grid.csv': [function (v) { return v.more.takesGrid; }, true],
  'waits.csv': [function (v) { return v.more.waits; }, true],
  'strand.csv': [function (v) { return v.more.strand; }, true],
  'busy_towns.csv': [function (v) { return v.more.busyTown; }, true],
  'busy_grid.csv': [function (v) { return v.more.busyGrid; }, true],
  'apps_places.csv': [function (v) { return v.more.appsPlace; }, true],
  'apps_towns.csv': [function (v) { return v.more.appsTown; }, true],
  'apps_grid.csv': [function (v) { return v.more.appsGrid; }, true],
  'per_mile_places.csv': [function (v) { return v.more.ppmPlace; }, true],
  'per_mile_towns.csv': [function (v) { return v.more.ppmTown; }, true],
  'per_mile_grid.csv': [function (v) { return v.more.ppmGrid; }, true],
  'stacking.csv': [function (v) { return v.more.stack; }, true],
  'quiet_places.csv': [function (r) { return r.quiet.place; }, false],
  'quiet_towns.csv': [function (r) { return r.quiet.town; }, false],
  'trend_places.csv': [function (r) { return r.trend.place; }, false],
  'trend_towns.csv': [function (r) { return r.trend.town; }, false],
  'good_towns.csv': [function (v) { return v.best.goodTown; }, true],
  'good_grid.csv': [function (v) { return v.best.goodGrid; }, true],
  'good_restaurants.csv': [function (v) { return v.best.goodRest; }, true],
  'good_apps.csv': [function (v) { return v.best.goodApp; }, true],
  'waiting_towns.csv': [function (v) { return v.best.waitTown; }, true],
  'waiting_grid.csv': [function (v) { return v.best.waitGrid; }, true],
  'dead_miles_towns.csv': [function (v) { return v.best.deadTown; }, true],
  'dead_miles_grid.csv': [function (v) { return v.best.deadGrid; }, true],
  'size_towns.csv': [function (v) { return v.best.sizeTown; }, true],
  'size_apps.csv': [function (v) { return v.best.sizeApp; }, true],
  'size_restaurants.csv': [function (v) { return v.best.sizeRest; }, true],
  'waited_towns.csv': [function (v) { return v.more.waitedAreaTown; }, true],
  'waited_grid.csv': [function (v) { return v.more.waitedAreaGrid; }, true],
  'empty_driving.csv': [function (v) { return v.more.emptyTown; }, true],
};

/* The top-10% share tests (all hours, hours held), one CSV, a line a group. */
function shareCsv(r) {
  var lines = ['grouping,name,ranked,n,outings,top10_share,top25_share,others_same_hours,score,score_lo,score_hi,clear,beats_chance,grouping_p'];
  ['town', 'rest', 'place', 'grid'].forEach(function (k) {
    var t = r.best.share[k];
    t.groups.forEach(function (g) {
      lines.push([k, shareName(r, k, g.name), 'yes', g.n, g.outings, g.top10, g.top25, g.expect, g.score,
                  g.sci && g.sci[0], g.sci && g.sci[1], g.clear, g.beats ? 'yes' : 'no', t.p].map(csvCell).join(','));
    });
    t.thin.forEach(function (g) {
      lines.push([k, shareName(r, k, g.name), 'too few', g.n, g.outings, '', '', '', '', '', '', '', '', t.p]
        .map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function levelsCsv(r) {
  var lines = ['level,point,placed,median_per_hour,in_region_box,stood_in_for'];
  (r.coverage.levels || []).forEach(function (l) {
    lines.push([l.level, l.point ? 'yes' : 'no', l.n, l.perHour, l.region, l.refused].map(csvCell).join(','));
  });
  return lines.join('\n') + '\n';
}

/* The Restaurants tab as two CSVs: a line per restaurant per hours view, and
 * a line per placed branch (and the not-placed rest) per hours view. */
var REST_COLS = ['n', 'outings', 'score', 'score_lo', 'score_hi', 'median_per_hour', 'median_lo', 'median_hi',
                 'median_pay', 'median_per_mile', 'taken', 'take_rate', 'take_lo', 'take_hi', 'timed_at_door',
                 'real_per_hour', 'real_lo', 'real_hi', 'real_minus_card_min', 'wait_min', 'waits', 'wait_not_joined',
                 'addon_share', 'stacked_share', 'uber_n', 'uber_per_hour', 'doordash_n', 'doordash_per_hour',
                 'gps_timed', 'p75_per_hour', 'p90_per_hour', 'top10_share'];
function restVals(g) {
  function lo(c) { return c ? c[0] : null; }
  function hi(c) { return c ? c[1] : null; }
  return [g.n, g.outings, g.score, lo(g.sci), hi(g.sci), g.median !== undefined ? g.median : g.perHour,
          lo(g.ci), hi(g.ci), g.pay, g.ppm, g.taken, g.take, lo(g.takeCi), hi(g.takeCi), g.timed,
          g.realPerHour, lo(g.realCi), hi(g.realCi), g.cardVsReal, g.wait, g.waitN, g.waitWhy,
          g.addon, g.stacked, g.uberN, g.uberPerHour, g.doordashN, g.doordashPerHour, g.gpsTimed,
          g.p75, g.p90, g.top10];
}
function restCsv(r) {
  var lines = [['hours', 'restaurant', 'ranked', 'chain', 'placed_offers', 'placed_branches'].concat(REST_COLS)
    .concat(['clear', 'beats_chance', 'grouping_p']).join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v].rest;
    c.groups.concat(c.thin).forEach(function (g) {
      lines.push([r.views[v].name, g.label, g.ranked ? 'yes' : 'too few', g.chain ? 'yes' : 'no', g.placedN, g.branchN]
        .concat(g.ranked ? restVals(g) : restVals(Object.assign({}, g, { median: g.perHour })))
        .concat([g.clear, g.beats ? 'yes' : 'no', c.p]).map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}
function restBranchCsv(r) {
  var lines = [['hours', 'restaurant', 'branch', 'lat', 'lon', 'place_score', 'place_score_lo', 'place_score_hi',
                'place_beats_chance'].concat(REST_COLS.filter(function (k) { return !/^score/.test(k); }))
    .join(',')];
  VIEWS.forEach(function (v) {
    var c = r.views[v].rest;
    c.groups.concat(c.thin).forEach(function (g) {
      g.branches.forEach(function (b) {
        var vals = restVals(Object.assign({}, b, { median: b.perHour, ci: null, score: null, sci: null }));
        vals.splice(2, 3);
        lines.push([r.views[v].name, g.label, b.name, b.lat, b.lon, b.placeScore, b.placeSci && b.placeSci[0],
                    b.placeSci && b.placeSci[1], b.unplaced ? '' : b.placeBeats ? 'yes' : 'no'].concat(vals)
          .map(csvCell).join(','));
      });
    });
  });
  return lines.join('\n') + '\n';
}

/* The Strategy tab's curves as one CSV: a line per threshold, $/hr then
 * $/mi (the second for reading only, as the tab says). */
function strategyCsv(r) {
  var s = r.strategy;
  var head = ['on', 'line', 'offers_seen_free', 'per_free_hour', 'mean_pay', 'mean_card_minutes', 'actual_over_card',
              'ratio_from', 'gross_per_hour_on_shift', 'ci_lo', 'ci_hi', 'net_per_hour_on_shift', 'thin'];
  var lines = [head.join(',')];
  [['per_hour', s.curve.points], ['per_mile_reading_only', s.curveMile.points]].forEach(function (k) {
    k[1].forEach(function (p) {
      lines.push([k[0], p.T, p.n, p.perFreeHour, p.pay, p.cardMin, p.ratio,
                  p.ratioFrom === 'carried' ? 'carried from ' + p.ratioAt : p.ratioFrom, p.gross,
                  p.ci ? p.ci[0] : null, p.ci ? p.ci[1] : null, p.net, p.thin ? 'thin' : ''].map(csvCell).join(','));
    });
  });
  return lines.join('\n') + '\n';
}

function coverageCsv(r) {
  var lines = ['day,placed,unplaced,placed_per_hour,unplaced_per_hour,gap_per_hour,placed_pay,unplaced_pay,gap_pay,p'];
  r.coverage.days.concat([Object.assign({ day: 'all' }, r.coverage.all)]).forEach(function (d) {
    lines.push([d.day, d.placed.n, d.unplaced.n, d.placed.perHour, d.unplaced.perHour, d.gapPerHour,
                d.placed.pay, d.unplaced.pay, d.gapPay, d.p].map(csvCell).join(','));
  });
  return lines.join('\n') + '\n';
}

module.exports = {
  csvCell: csvCell, BOM: BOM, csvOf: csvOf, dropCsv: dropCsv, tableCsv: tableCsv, MORE_CSVS: MORE_CSVS, shareCsv: shareCsv,
  levelsCsv: levelsCsv, restCsv: restCsv, restBranchCsv: restBranchCsv, strategyCsv: strategyCsv,
  coverageCsv: coverageCsv,
};
