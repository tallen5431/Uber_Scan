/* The places report's page script: it switches between the views the
 * report worked out (the JSON in #data) and draws them. It computes no
 * statistic of its own. tools/report/render.js writes it into the page
 * from the line that opens "(function () {", this header left out. */
(function () {
  var R = JSON.parse(document.getElementById('data').textContent);
  var css = getComputedStyle(document.documentElement);
  function col(name) { return css.getPropertyValue(name).trim(); }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function m(v) { return v === null || v === undefined ? '—' : '$' + v.toFixed(2); }
  function sg(v) { return v === null || v === undefined ? '—' : (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toFixed(2); }
  function ci(c, f) { return c ? '[' + f(c[0]) + ', ' + f(c[1]) + ']' : '—'; }
  function pc(v) { return v === null || v === undefined ? '—' : Math.round(v * 100) + '%'; }
  function pTxt(p) {
    return p === null ? 'not tested' : p === 0 ? 'p < ' + (1 / R.shuffles).toFixed(4) : 'p = ' + p.toFixed(3);
  }
  function label(kind, name) {
    if (kind === 'place') return (R.places[name] && R.places[name].label) || name;
    if (kind === 'rest') return (R.restNames && R.restNames[name]) || name;
    if (kind === 'grid') {
      var c = R.cells[name];
      return c ? 'cell near ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) : name;
    }
    return name;
  }
  function tag(g, lowGood) {
    if (!g.beats) return '<span class="tag grey">not distinguishable</span>';
    var good = lowGood ? g.clear === 'below' : g.clear === 'above';
    return '<span class="tag ' + (good ? 'up' : 'down') + '">' + (g.clear === 'above' ? 'above' : 'below')
      + ' the rest</span>';
  }
  var tip = document.getElementById('tip');
  function showTip(e, text) {
    tip.hidden = false; tip.innerHTML = text;
    var x = Math.min(e.clientX + 12, innerWidth - 310);
    tip.style.left = x + 'px'; tip.style.top = (e.clientY + 12) + 'px';
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (t) showTip(e, t.getAttribute('data-tip')); else tip.hidden = true;
  });
  document.addEventListener('mousemove', function (e) { if (!tip.hidden) showTip(e, tip.innerHTML); });

  function testText(c, what) {
    if (c.p === null) {
      return what + ': not tested — ' + c.groups.length + ' cell(s) clear the floor of ' + c.floor + ' on '
        + c.outings + ' shift days.';
    }
    return what + ': ' + c.groups.length + ' cells over ' + c.kept + ', ' + (c.held ? 'hours held still, ' : '')
      + pTxt(c.p) + (c.held && c.rawP !== null ? ' (' + pTxt(c.rawP) + ' with the hour left in)' : '') + ' — '
      + (c.significant ? '<b>beats chance</b>; colour only where a cell\'s interval is clear of zero.'
         : '<b>not distinguishable from chance</b>, so nothing is coloured: read the order as noise.');
  }

  /* A ranked dot plot: one row per cell, the score's interval as a bar and
     the score as a dot, zero marked. Colour only on cells that beat chance. */
  function dotPlot(el, c, kind, unit, lowGood) {
    var gs = c.groups.filter(function (g) { return g.score !== null; });
    if (!gs.length) { el.innerHTML = '<p class="note">No cell clears the floor here.</p>'; return; }
    var lo = 0, hi = 0;
    gs.forEach(function (g) {
      var a = g.sci ? g.sci[0] : g.score, b = g.sci ? g.sci[1] : g.score;
      lo = Math.min(lo, a); hi = Math.max(hi, b);
    });
    var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    var W = 720, L = 230, Rr = 20, rowH = 24, top = 26, H = top + gs.length * rowH + 10;
    function x(v) { return L + (v - lo) / (hi - lo) * (W - L - Rr); }
    var step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 4)));
    if ((hi - lo) / step > 8) step *= 2;
    if ((hi - lo) / step > 8) step *= 2.5;
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="ranked dot plot">';
    for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) {
      s += '<line x1="' + x(t) + '" x2="' + x(t) + '" y1="' + (top - 6) + '" y2="' + (H - 6) + '" stroke="'
        + col('--grid') + '"/><text x="' + x(t) + '" y="' + (top - 10) + '" text-anchor="middle">'
        + (Math.abs(t) < 1e-9 ? '0' : (t > 0 ? '+' : '−') + Math.abs(t).toFixed(step < 1 ? 1 : 0)) + '</text>';
    }
    s += '<line x1="' + x(0) + '" x2="' + x(0) + '" y1="' + (top - 6) + '" y2="' + (H - 6) + '" stroke="'
      + col('--axis') + '" stroke-width="2"/>';
    gs.forEach(function (g, i) {
      var y = top + i * rowH + rowH / 2;
      var good = lowGood ? g.clear === 'below' : g.clear === 'above';
      var colour = g.beats ? col(good ? '--up' : '--down') : col('--grey');
      var name = label(kind, g.name);
      var tipText = esc(name) + '<br>n = ' + g.n + ' on ' + g.outings + ' shift days<br>'
        + (unit === 'min' ? 'wait vs same hours elsewhere: ' : 'vs same hours elsewhere: ') + sg(g.score)
        + ' ' + ci(g.sci, sg) + '<br>median ' + (unit === 'min' ? (g.median + ' min') : m(g.median) + '/hr')
        + (g.beats ? '' : '<br>not distinguishable from the rest');
      s += '<g data-tip="' + esc(tipText) + '"><rect x="0" y="' + (y - rowH / 2) + '" width="' + W + '" height="'
        + rowH + '" fill="transparent"/>';
      s += '<text x="' + (L - 10) + '" y="' + (y + 4) + '" text-anchor="end">'
        + esc(name.length > 30 ? name.slice(0, 29) + '…' : name) + ' (' + g.n + ')</text>';
      if (g.sci) {
        s += '<line x1="' + x(g.sci[0]) + '" x2="' + x(g.sci[1]) + '" y1="' + y + '" y2="' + y
          + '" stroke="' + colour + '" stroke-width="3" stroke-linecap="round"/>';
      }
      s += '<circle cx="' + x(g.score) + '" cy="' + y + '" r="5" fill="' + colour + '" stroke="'
        + col('--surface') + '" stroke-width="2"/></g>';
    });
    s += '</svg><p class="note">' + (unit === 'min'
      ? 'Minutes of wait against the same hours elsewhere, with 95% intervals. Left of zero is a shorter wait.'
      : '$/hr against what the other cells paid in the same three-hour blocks, with 95% intervals.') + '</p>';
    el.innerHTML = s;
  }

  function table(el, c, kind) {
    var rows = c.groups.map(function (g) {
      return '<tr><td>' + esc(label(kind, g.name)) + '</td><td>' + g.n + '</td><td>' + g.outings + '</td><td>'
        + sg(g.score) + '</td><td>' + ci(g.sci, sg) + '</td><td>' + m(g.median) + '</td><td>' + ci(g.ci, m)
        + '</td><td>' + m(g.p75) + '</td><td>' + m(g.p90) + '</td><td>' + ci(g.p90Ci, m)
        + '</td><td data-v="' + (g.top10 === null || g.top10 === undefined ? '' : g.top10) + '">' + pc(g.top10)
        + '</td><td>' + m(g.pay) + '</td><td>' + m(g.ppm) + '</td><td>' + ci(g.ppmCi, m) + '</td><td>' + pc(g.take)
        + '</td><td>' + tag(g, false) + '</td></tr>';
    }).join('');
    el.innerHTML = c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (kind === 'place' ? 'place'
      : kind === 'town' ? 'town' : 'cell') + '</th><th>n</th><th>days</th><th>vs same hours</th><th>95%</th>'
      + '<th>median $/hr</th><th>95%</th><th>P75 $/hr</th><th>P90 $/hr</th><th>95%</th><th>top 10% (for its hours)</th>'
      + '<th>median pay</th><th>$/mi (read only)</th><th>95%</th>'
      + '<th>rig said take</th><th></th></tr></thead><tbody>'
      + rows + '</tbody></table></div>' : '';
  }

  function thinList(el, c, kind, unit) {
    if (!c.thin.length) { el.innerHTML = ''; return; }
    el.innerHTML = '<p><b>Too few to rank</b> (under ' + c.floor + ' ' + unit + ' or ' + c.outings
      + ' shift days): ' + c.thin.slice(0, 60).map(function (t) {
        return esc(label(kind, t.name)) + ' (' + t.n + ')';
      }).join(', ') + (c.thin.length > 60 ? ', and ' + (c.thin.length - 60) + ' more' : '') + '.</p>';
  }

  function dropTable(el, c, what) {
    var rows = c.groups.map(function (g) {
      var name = what === 'cell' && g.box ? 'cell near ' + g.box.lat.toFixed(3) + ', ' + g.box.lon.toFixed(3)
        : g.name;
      return '<tr><td>' + esc(name) + '</td><td>' + g.trips + '</td><td>' + g.n + '</td><td>' + g.ended
        + '</td><td>' + g.median.toFixed(1) + ' min</td><td>' + ci(g.ci, function (v) { return v.toFixed(1); })
        + '</td><td>' + (g.score === null ? '—' : (g.score >= 0 ? '+' : '−') + Math.abs(g.score).toFixed(1) + ' min')
        + '</td><td>' + m(g.nextPerHour) + '</td><td>' + m(g.nextPay)
        + '</td><td>' + (g.anyMin === null || g.anyMin === undefined ? '—' : g.anyMin.toFixed(1) + ' min')
        + '</td><td>' + m(g.anyPerHour) + '</td><td>' + pc(g.anyGood) + '</td><td>' + tag(g, true) + '</td></tr>';
    }).join('');
    var thin = what === 'cell'
      ? (c.thinCount ? '<p class="thin">' + c.thinCount + ' more cells (' + c.thinTrips
         + ' trips) have too few to show, and are not named.</p>' : '')
      : (c.thin.length ? '<p class="thin"><b>Too few</b> (under ' + c.floor + ' measured waits): '
         + c.thin.map(function (t) { return esc(t.name) + ' (' + t.n + ')'; }).join(', ') + '.</p>' : '');
    // Its heading is the fold's round it now (html()), so none is written here.
    el.innerHTML = (c.groups.length ? '<div class="tw"><table><thead><tr><th>' + (what === 'cell' ? 'cell' : 'town')
        + '</th><th>trips</th><th>measured</th><th>ended</th><th>median wait</th><th>95%</th><th>vs same hours</th>'
        + '<th>next take $/hr</th><th>next take pay</th><th>next offer, min</th><th>next offer $/hr</th>'
        + '<th>next offer cleared target</th><th></th></tr></thead><tbody>' + rows
        + '</tbody></table></div>' : '<p class="note">No area clears the floor here.</p>') + thin;
  }

  /* The Restaurants table: a tbody per restaurant, its branches hidden under
     it until ▸ is clicked, so a sort moves a restaurant with its branches. */
  var REST_HEAD = ['restaurant', 'offers', 'days', 'vs same hours', '95%', 'median $/hr', '95%', 'P90 $/hr', 'top 10% (for its hours)',
                   'median pay',
                   '$/mi (read only)', 'you took', 'real $/hr', 'timed', 'real − card', 'wait', 'add-on', 'stacked',
                   'Uber · DD', ''];
  function restCells(g, isBranch) {
    function td(v, text) { return '<td data-v="' + esc(v === null || v === undefined ? '' : String(v)) + '">' + text + '</td>'; }
    // (and the worst, where the rig sends it: storeWaitsOut's worstMin)
    var wait = g.wait !== null && g.wait !== undefined ? g.wait.toFixed(1) + ' min (' + g.waitN + ')'
      + (typeof g.waitWorst === 'number' ? ', worst ' + g.waitWorst.toFixed(1) : '')
      : g.waitWhy && g.waitWhy !== 'none on record' ? '<span title="' + esc(g.waitWhy) + '">— ' + esc(g.waitWhy) + '</span>' : '—';
    var score = isBranch ? (g.placeScore !== null && g.placeScore !== undefined
      ? '<span title="as a place, against the other places">' + sg(g.placeScore) + ' (place)</span>' : '—') : sg(g.score);
    return [td(g.n, String(g.n)), td(g.outings, String(g.outings)), td(isBranch ? g.placeScore : g.score, score),
            td(g.sci ? g.sci[0] : '', isBranch ? '' : ci(g.sci, sg)),
            td(g.ranked ? g.median : g.perHour, m(g.ranked && !isBranch ? g.median : g.perHour)),
            td(g.ci ? g.ci[0] : '', isBranch ? '' : ci(g.ci, m)), td(g.p90, m(g.p90)), td(g.top10, pc(g.top10)),
            td(g.pay, m(g.pay)), td(g.ppm, m(g.ppm)),
            td(g.take, pc(g.take) + (g.taken ? ' (' + g.taken + ')' : '')), td(g.realPerHour, m(g.realPerHour)),
            td(g.timed, String(g.timed)),
            td(g.cardVsReal, g.cardVsReal === null ? '—' : (g.cardVsReal >= 0 ? '+' : '−') + Math.abs(g.cardVsReal).toFixed(1) + ' min'),
            td(g.wait, wait), td(g.addon, pc(g.addon)), td(g.stacked, pc(g.stacked)),
            td(g.uberN, g.uberN + ' · ' + g.doordashN)].join('');
  }
  function restRows(list, ranked) {
    return list.map(function (g, i) {
      var nb = g.branches.filter(function (b) { return !b.unplaced; }).length;
      var btn = g.branches.length ? '<button type="button" class="xb" aria-expanded="false" title="placed branches">▸ '
        + nb + '</button>' : '';
      var head = '<tr><td data-v="' + esc(label('rest', g.name).toLowerCase()) + '">' + btn + esc(label('rest', g.name))
        + (g.chain ? ' <span class="note">chain</span>' : '') + '</td>' + restCells(g, false) + '<td>'
        + (ranked ? tag(g, false) : '<span class="tag grey">too few</span>') + '</td></tr>';
      var subs = g.branches.map(function (b) {
        var nm = b.unplaced ? 'not placed' : b.name + (b.lat !== undefined ? ' <span class="note">near '
          + b.lat.toFixed(3) + ', ' + b.lon.toFixed(3) + '</span>' : '');
        return '<tr class="br" hidden><td>↳ ' + (b.unplaced ? '<i>not placed</i>' : nm) + '</td>' + restCells(b, true)
          + '<td>' + (b.placeBeats ? '<span class="note">clear of the rest in Places</span>' : '') + '</td></tr>';
      }).join('');
      return '<tbody>' + head + subs + '</tbody>';
    }).join('');
  }
  function restTable(c) {
    document.getElementById('restCover').textContent = c.named + ' offers carry a name, ' + c.placed + ' of them '
      + 'placed (' + (c.named ? Math.round(c.placed / c.named * 100) : 0) + '%); ' + c.noName
      + ' printed a door, a street or a corner and no name, and are not here.';
    var head = '<thead><tr>' + REST_HEAD.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') + '</tr></thead>';
    document.getElementById('restTable').innerHTML = c.groups.length
      ? '<div class="tw"><table class="groups">' + head + restRows(c.groups, true) + '</table></div>' : '';
    var CAP = 150, thin = c.thin.slice(0, CAP);
    document.getElementById('restThin').innerHTML = c.thin.length
      ? '<h3>Too few to rank</h3><p class="thin">Under ' + c.floor + ' offers or ' + c.outings + ' shift days: listed '
        + 'for reading, neither ranked nor tested nor coloured' + (c.thin.length > CAP ? '; the ' + CAP
        + ' with the most offers shown, all ' + c.thin.length + ' in restaurants.csv' : '') + '.</p>'
        + '<div class="tw"><table class="groups">' + head + restRows(thin, false) + '</table></div>' : '';
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button.xb');
    if (!b) return;
    e.stopPropagation();
    var open = b.getAttribute('aria-expanded') !== 'true';
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    b.textContent = (open ? '▾ ' : '▸ ') + b.textContent.slice(2);
    Array.prototype.forEach.call(b.closest('tbody').querySelectorAll('tr.br'), function (r) { r.hidden = !open; });
  });

  function levelsTable() {
    var ls = R.coverage.levels || [];
    document.getElementById('levels').innerHTML = ls.length ? '<div class="tw"><table><thead><tr><th>level</th>'
      + '<th>kind</th><th>placed</th><th>median $/hr</th><th>no fix, region box</th><th>stood in for</th></tr></thead><tbody>'
      + ls.map(function (l) {
        return '<tr><td>' + esc(l.level) + '</td><td>' + (l.point ? 'point' : 'approximate') + '</td><td>' + l.n
          + '</td><td>' + m(l.perHour) + '</td><td>' + l.region + '</td><td>' + esc(l.refused || '—') + '</td></tr>';
      }).join('') + '</tbody></table></div>'
      + (R.coverage.points && R.coverage.points.gapPerHour !== null ? '<p class="note">Points only (door, corner, '
         + 'name) against the unplaced: ' + m(R.coverage.points.placed.perHour) + '/hr against '
         + m(R.coverage.points.unplaced.perHour) + '/hr (' + pTxt(R.coverage.points.p) + '). The table below counts '
         + 'every level as placed.</p>' : '')
      : '<p class="note">Nothing placed.</p>';
  }
  function shareTests() {
    var B = R.best.share, out = '';
    [['town', 'Towns'], ['rest', 'Restaurants'], ['place', 'Places'], ['grid', R.gridMi + '-mile cells']].forEach(function (k) {
      var t = B[k[0]];
      out += '<h3>' + esc(k[1]) + '</h3><p class="note">' + (t.p === null ? 'Not tested: ' + t.groups.length
        + ' over the floor.' : t.groups.length + ' groups over ' + t.kept + ' offers, hours held, ' + pTxt(t.p) + ' — '
        + (t.significant ? '<b>beats chance</b>; colour only where a group\'s interval is clear of zero.'
           : '<b>not distinguishable from chance</b>, so nothing is coloured.')) + '</p>';
      if (!t.groups.length) return;
      out += '<div class="tw"><table><thead><tr><th>' + esc(k[1].toLowerCase()) + '</th><th>offers</th><th>days</th>'
        + '<th>top 10% (for its hours)</th><th>the others, same hours</th><th>vs same hours</th><th>95%</th><th>top 25% (for its hours)</th>'
        + '<th></th></tr></thead><tbody>'
        + t.groups.map(function (g) {
          function pts(v) { return v === null || v === undefined ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v * 100).toFixed(1) + ' pts'; }
          var pl = k[0] === 'place' ? R.places[g.name] : null;
          return '<tr><td>' + esc(label(k[0], g.name)) + (pl ? ' <span class="note">near ' + pl.lat.toFixed(3) + ', '
            + pl.lon.toFixed(3) + '</span>' : '') + '</td><td>' + g.n + '</td><td>' + g.outings + '</td><td data-v="'
            + g.top10 + '">' + pc(g.top10) + '</td><td>' + pc(g.expect) + '</td><td data-v="' + g.score + '">' + pts(g.score)
            + '</td><td>' + ci(g.sci, pts) + '</td><td>' + pc(g.top25) + '</td><td>' + tag(g, false) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    });
    document.getElementById('shareTests').innerHTML = out;
  }
  function coverageTable() {
    var d = R.coverage.days.concat([Object.assign({ day: 'all days' }, R.coverage.all)]);
    document.getElementById('coverage').innerHTML = '<div class="tw"><table><thead><tr><th>shift day</th>'
      + '<th>placed</th><th>unplaced</th><th>placed $/hr</th><th>unplaced $/hr</th><th>gap</th><th>placed pay</th>'
      + '<th>unplaced pay</th><th>test</th></tr></thead><tbody>' + d.map(function (r) {
        return '<tr><td>' + esc(r.day) + '</td><td>' + r.placed.n + '</td><td>' + r.unplaced.n + '</td><td>'
          + m(r.placed.perHour) + '</td><td>' + m(r.unplaced.perHour) + '</td><td>' + sg(r.gapPerHour) + '</td><td>'
          + m(r.placed.pay) + '</td><td>' + m(r.unplaced.pay) + '</td><td>' + pTxt(r.p) + '</td></tr>';
      }).join('') + '</tbody></table></div><p class="note">Why the unplaced were not placed: '
      + R.coverage.why.map(function (w) { return esc(w.why) + ' ' + w.n; }).join(' · ') + '</p>';
  }

  var map = null, layer = null;
  function drawMap(v) {
    if (typeof L === 'undefined') {
      document.getElementById('map').innerHTML = '<p class="note" style="padding:12px">The map needs the '
        + 'internet for Leaflet and its tiles; the tables above and below do not.</p>';
      return;
    }
    if (!map) {
      map = L.map('map');
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    }
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);
    var pts = [];
    v.grid.groups.forEach(function (g) {
      var c = R.cells[g.name];
      if (!c) return;
      var colour = g.beats ? col(g.clear === 'above' ? '--up' : '--down') : col('--grey');
      L.rectangle([[c.s, c.w], [c.n, c.e]], { color: colour, weight: 1, fillOpacity: g.beats ? 0.18 : 0.06 })
        .bindTooltip('2-mile cell · n ' + g.n + ' · ' + sg(g.score) + ' ' + ci(g.sci, sg)
                     + (g.beats ? '' : ' · not distinguishable from the rest')).addTo(layer);
    });
    var biggest = Math.max.apply(null, [1].concat(v.place.groups.map(function (g) { return g.n; })));
    v.place.groups.forEach(function (g) {
      var p = R.places[g.name];
      if (!p) return;
      var colour = g.beats ? col(g.clear === 'above' ? '--up' : '--down') : col('--grey');
      L.circleMarker([p.lat, p.lon], { radius: 5 + 13 * Math.sqrt(g.n / biggest), color: col('--surface'),
        weight: 2, fillColor: colour, fillOpacity: 0.9 })
        .bindTooltip(esc(p.label) + '<br>n ' + g.n + ' · median ' + m(g.median) + '/hr ' + ci(g.ci, m)
                     + '<br>vs same hours ' + sg(g.score) + ' ' + ci(g.sci, sg)
                     + (g.beats ? '' : '<br>not distinguishable from the rest')).addTo(layer);
      pts.push([p.lat, p.lon]);
    });
    v.place.thin.forEach(function (t) {
      var p = R.places[t.name];
      if (!p) return;
      L.circleMarker([p.lat, p.lon], { radius: 3, color: col('--grey'), weight: 1, fill: false })
        .bindTooltip(esc(p.label) + ' · ' + t.n + ' offers · too few to rank').addTo(layer);
      pts.push([p.lat, p.lon]);
    });
    if (pts.length) map.fitBounds(pts, { padding: [20, 20], maxZoom: 14 });
    else map.setView([0, 0], 2);
  }

  /* The second pass's tables: one renderer for every one, by its columns'
     kinds. Sortable by any column (click a heading); the value sorted by is
     the raw figure, kept on the cell. */
  function fmt(f, v) {
    if (v === null || v === undefined || v === '') return '—';
    if (f === 't') return esc(v);
    if (f === 'n') return String(v);
    if (f === '$') return m(v);
    if (f === 's$') return sg(v);
    if (f === '%') return pc(v);
    if (f === 'min') return v.toFixed(1) + ' min';
    if (f === 'dmin') return (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(1) + ' min';
    if (f === 'mi') return v.toFixed(1) + ' mi';
    if (f === 'h') return v.toFixed(1) + ' h';
    if (f === 'r') return v.toFixed(1);
    if (f === 'r2') return v.toFixed(2);
    if (f === 'x') return v.toFixed(2) + '×';
    if (f === 'p') return v === 0 ? 'p < ' + (1 / R.shuffles).toFixed(4) : v.toFixed(3);
    if (f === '$ci') return ci(v, m);
    if (f === '%ci') return ci(v, pc);
    if (f === 'minci' || f === 'dminci') return ci(v, function (x) { return x.toFixed(1); });
    if (f === 'mici') return ci(v, function (x) { return x.toFixed(1); });
    return esc(v);
  }
  function sparkSvg(weeks, top) {
    if (!weeks || !weeks.length) return '—';
    var W = 140, H = 30, n = weeks.length;
    function x(i) { return n === 1 ? W / 2 : 4 + i * (W - 8) / (n - 1); }
    function y(v) { return H / 2 - (v / top) * (H / 2 - 3); }
    var pts = weeks.map(function (w, i) { return x(i).toFixed(1) + ',' + y(w.score).toFixed(1); });
    var tipText = weeks.map(function (w) { return esc(w.w) + ': ' + sg(w.score) + ' (n ' + w.n + ')'; }).join('<br>');
    return '<svg class="spark" viewBox="0 0 ' + W + ' ' + H + '" data-tip="' + esc(tipText) + '" role="img" '
      + 'aria-label="score by week"><line class="z" x1="0" x2="' + W + '" y1="' + y(0) + '" y2="' + y(0) + '"/>'
      + '<polyline points="' + pts.join(' ') + '"/>' + weeks.map(function (w, i) {
        return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(w.score).toFixed(1) + '" r="2"/>';
      }).join('') + '</svg>';
  }
  function sortVal(f, v) {
    if (v === null || v === undefined || v === '') return '';
    if (/ci$/.test(f)) return v[0];
    if (f === 'spark') return v.length;
    return v;
  }
  function moreTable(el, t) {
    if (!el) return;
    if (!t || !t.rows || !t.rows.length) { el.innerHTML = '<p class="note">Nothing clears the floor here.</p>'; return; }
    var top = 1;
    t.cols.forEach(function (c) {
      if (c.f !== 'spark') return;
      t.rows.forEach(function (r) { (r[c.k] || []).forEach(function (w) { top = Math.max(top, Math.abs(w.score)); }); });
    });
    el.innerHTML = '<div class="tw"><table><thead><tr>' + t.cols.map(function (c) {
      return '<th>' + esc(c.h) + '</th>';
    }).join('') + '</tr></thead><tbody>' + t.rows.map(function (r) {
      return '<tr>' + t.cols.map(function (c) {
        var sv = sortVal(c.f, r[c.k]);
        return '<td data-v="' + esc(typeof sv === 'number' ? String(sv) : sv) + '">'
          + (c.f === 'spark' ? sparkSvg(r[c.k], top) : fmt(c.f, r[c.k])) + '</td>';
      }).join('') + '</tr>';
    }).join('') + '</tbody></table></div>';
  }
  function drawMore(v) {
    Object.keys(v.more).forEach(function (k) { moreTable(document.getElementById('m-' + k), v.more[k]); });
    Object.keys(v.best).forEach(function (k) { moreTable(document.getElementById('b-' + k), v.best[k]); });
    moreTable(document.getElementById('m-quietPlace'), R.quiet.place);
    moreTable(document.getElementById('m-quietTown'), R.quiet.town);
    moreTable(document.getElementById('m-trendPlace'), R.trend.place);
    moreTable(document.getElementById('m-trendTown'), R.trend.town);
  }

  // Any table: click a heading to sort by it, again to turn it round.
  function cellVal(td) {
    var d = td.getAttribute('data-v');
    var t = d !== null ? d : td.textContent.replace(/[$,%×+]|min|mi|\s/g, '').replace('−', '-');
    if (t === '' || t === '—') return null;
    var n = Number(t);
    return isFinite(n) ? n : (d !== null ? d : td.textContent).toLowerCase();
  }
  document.addEventListener('click', function (e) {
    var th = e.target.closest && e.target.closest('th');
    if (!th) return;
    var table = th.closest('table'), body = table.tBodies[0];
    if (!body) return;
    var i = Array.prototype.indexOf.call(th.parentNode.children, th);
    var dir = th.getAttribute('aria-sort') === 'descending' ? 1 : -1;
    Array.prototype.forEach.call(th.parentNode.children, function (h) { h.removeAttribute('aria-sort'); });
    th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
    if (table.classList.contains('groups')) {
      // A restaurant moves with its branches: sort the tbodies by their first row.
      var bodies = Array.prototype.slice.call(table.tBodies);
      bodies.sort(function (a, b) {
        var x = cellVal(a.rows[0].cells[i]), y = cellVal(b.rows[0].cells[i]);
        if (x === null) return y === null ? 0 : 1;
        if (y === null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
      bodies.forEach(function (b) { table.appendChild(b); });
      return;
    }
    var rows = Array.prototype.slice.call(body.rows);
    rows.sort(function (a, b) {
      var x = cellVal(a.cells[i]), y = cellVal(b.cells[i]);
      if (x === null) return y === null ? 0 : 1;
      if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  });
  function markSortable() {
    Array.prototype.forEach.call(document.querySelectorAll('th'), function (h) { h.classList.add('sortable'); });
  }

  /* Tabs: one section at a time, the pick kept in the address, in two rows
     (html()'s nav): the groups, and the chosen group's tabs. A tab's group
     is the span it sits in, so the page needs no second list of them. */
  var tabs = document.getElementById('tabs');
  var groups = document.getElementById('groups');
  var current = null;
  var lastIn = {};     // the tab last open in each group, for a press on the group
  function buttons() { return Array.prototype.slice.call(tabs.querySelectorAll('button[data-tab]')); }
  function groupOf(id) {
    var b = tabs.querySelector('button[data-tab="' + id + '"]');
    return b ? b.parentNode.getAttribute('data-group') : null;
  }
  // The tabs the Hours picker reaches (GROUPS' fourth field, carried over in
  // the data as R.hourly); elsewhere it is hidden, not left changing nothing.
  var HOURLY = {};
  (R.hourly || []).forEach(function (t) { HOURLY[t] = true; });
  var navAt = document.getElementById('navAt');
  function showTab(id) {
    if (!groupOf(id)) id = 'overview';
    current = id;
    var g = groupOf(id);
    lastIn[g] = id;
    buttons().forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-tab') === id ? 'true' : 'false');
    });
    Array.prototype.forEach.call(groups.children, function (b) {
      b.setAttribute('aria-selected', b.getAttribute('data-group') === g ? 'true' : 'false');
    });
    // The chosen group's tabs only; the Overview is one tab and needs no row.
    Array.prototype.forEach.call(tabs.children, function (sp) { sp.hidden = sp.getAttribute('data-group') !== g; });
    tabs.hidden = g === 'overview';
    Array.prototype.forEach.call(document.querySelectorAll('section[data-tab]'), function (sec) {
      sec.hidden = sec.getAttribute('data-tab') !== id;
    });
    document.getElementById('hoursBar').hidden = !HOURLY[id];
    document.getElementById('strip').hidden = id === 'overview';
    // The pressed tab into view in its sideways row (a phone's), without
    // moving the page.
    var on = tabs.querySelector('button[aria-pressed="true"]');
    if (on && tabs.scrollWidth > tabs.clientWidth) tabs.scrollLeft = on.offsetLeft - tabs.clientWidth / 2 + on.offsetWidth / 2;
    if (id === 'map') {
      drawMap(R.views[sel.value]);
      if (map) map.invalidateSize();
    }
    // Drawn when first shown (a Leaflet map made in a hidden section has no
    // size), and again on each pick.
    if (id === 'around') {
      drawAround();
      if (aMap) { aMap.invalidateSize(); drawAround(); }
    }
  }
  // A new tab starts at its top: a press from far down a long table would
  // otherwise open the next tab somewhere in its middle.
  function toTop() {
    var y = navAt.getBoundingClientRect().top + window.pageYOffset;
    if (window.pageYOffset > y) window.scrollTo(0, y);
  }
  function remember(id) {
    try { history.replaceState(null, '', '#' + id); } catch (err) { /* a file: page */ }
  }
  tabs.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-tab]');
    if (!b) return;
    showTab(b.getAttribute('data-tab'));
    remember(b.getAttribute('data-tab'));
    toTop();
  });
  groups.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button[data-group]');
    if (!b) return;
    var g = b.getAttribute('data-group');
    var first = tabs.querySelector('.tg[data-group="' + g + '"] button[data-tab]');
    var id = lastIn[g] || (first && first.getAttribute('data-tab'));
    showTab(id);
    remember(id);
    toTop();
  });
  /* The address: a tab's id (#strategy, #targets, every one the page ever
     had), or the id of a part inside one (#s-blocks, a fold's id): that tab
     opens, the part's folds open, and it is scrolled to. Anything else is the
     Overview. Read on load and on every change, so the Overview's links (and
     a link from elsewhere, like the offers page's #strategy) work in place. */
  function route() {
    var h = '';
    try { h = decodeURIComponent((location.hash || '').slice(1)); } catch (err) { h = ''; }
    if (groupOf(h)) { showTab(h); toTop(); return; }
    var el = h ? document.getElementById(h) : null;
    var sec = el && el.closest ? el.closest('section[data-tab]') : null;
    if (!sec) { showTab('overview'); return; }
    showTab(sec.getAttribute('data-tab'));
    for (var d = el; d; d = d.parentNode) if (d.tagName === 'DETAILS') d.open = true;
    el.scrollIntoView();
  }
  window.addEventListener('hashchange', route);
  // On a phone the folds start shut: the tables are wider than the screen,
  // and the Strategy tab's fourteen of them were seven screens of scrolling.
  // As written they are open, which is what a laptop (and a page with no
  // script) gets.
  if (window.matchMedia && window.matchMedia('(max-width: 640px)').matches) {
    Array.prototype.forEach.call(document.querySelectorAll('details.fold'), function (d) { d.open = false; });
  }
  // A fold with nothing in it (no "too few" list this time) is not shown,
  // rather than offering a heading that opens on nothing. Asked after every
  // draw, because the hours picked change what each holds.
  function tidyFolds() {
    Array.prototype.forEach.call(document.querySelectorAll('details.fold'), function (d) {
      var body = Array.prototype.slice.call(d.children, 1);
      d.hidden = !body.some(function (n) { return (n.textContent || '').trim() || n.querySelector('table,svg'); });
    });
  }
  var sel = document.getElementById('when');
  ['all'].concat([0, 1, 2, 3, 4, 5, 6, 7]).forEach(function (k) {
    var v = R.views[k];
    var o = document.createElement('option');
    o.value = k;
    o.textContent = (k === 'all' ? 'All hours, held to each 3-hour block' : v.name) + ' (' + v.offers + ')';
    sel.appendChild(o);
  });
  function draw() {
    var v = R.views[sel.value];
    document.getElementById('whenNote').textContent = sel.value === 'all'
      ? 'Hours held still: each offer is compared with the same three hours elsewhere.'
      : 'One block picked: nothing left to hold still, so the score is against the other cells in these hours.';
    [['place', 'places'], ['town', 'towns'], ['grid', 'grid cells']].forEach(function (k) {
      document.getElementById(k[0] + 'Test').innerHTML = testText(v[k[0]], k[1]);
      dotPlot(document.getElementById(k[0] + 'Plot'), v[k[0]], k[0], '$', false);
      table(document.getElementById(k[0] + 'Table'), v[k[0]], k[0]);
      thinList(document.getElementById(k[0] + 'Thin'), v[k[0]], k[0], 'offers');
    });
    [['waitedTown', 'town', 'towns where the car was'], ['waitedGrid', 'grid', 'cells where the car was']].forEach(function (k) {
      if (!v[k[0]] || !document.getElementById(k[0] + 'Test')) return;
      document.getElementById(k[0] + 'Test').innerHTML = testText(v[k[0]], k[2]);
      dotPlot(document.getElementById(k[0] + 'Plot'), v[k[0]], k[1], '$', false);
      table(document.getElementById(k[0] + 'Table'), v[k[0]], k[1]);
      thinList(document.getElementById(k[0] + 'Thin'), v[k[0]], k[1], 'offers');
    });
    document.getElementById('restTest').innerHTML = testText(v.rest, 'restaurants');
    dotPlot(document.getElementById('restPlot'), v.rest, 'rest', '$', false);
    restTable(v.rest);
    document.getElementById('dropTest').innerHTML = testText(v.dropTown, 'wait by town');
    dropTable(document.getElementById('dropTown'), v.dropTown, 'town');
    dropTable(document.getElementById('dropGrid'), v.dropGrid, 'cell');
    drawMore(v);
    markSortable();
    tidyFolds();
    if (current === 'map') drawMap(v);
  }
  sel.addEventListener('change', draw);

  /* When & where: the slot picked out of R.whenwhere and its areas sorted by
     the top share picked. Nothing is worked out here but the sort. */
  function wwName(id) { var s0 = document.getElementById(id); return s0.options[s0.selectedIndex].getAttribute('data-name'); }
  function rt(v) { return v === null || v === undefined ? '—' : v.toFixed(2); }
  /* The hour strip: the day picked, its 24 clock hours in the driver day's
     order, each the slot line's good/hr (every area together). Coloured by
     the slot line's own mark (against every slot together), grey with its n
     under the floor, blank with no waiting; a press picks that hour. */
  function shortHour(i) { var c = (i + 4) % 24; return (c % 12 || 12) + (c < 12 ? 'a' : 'p'); }
  function drawStrip(W, d, b, ti) {
    var el = document.getElementById('wwStrip');
    if (!el) return;
    var blk = W.blocks.length && /^\d$/.test(b) ? Number(b) : null;
    var BL = [[0, 6], [6, 10], [10, 13], [13, 16], [16, 19], [19, 24]];
    var cells = '';
    for (var i = 0; i < 24; i++) {
      var sl = W.slots[d + '|h' + i], a = sl && sl.all, cls = [], val, tipText;
      // An hour with no time waited is greyed (the UX review's R1), as one
      // with no card at all: nothing to read there either way.
      if (!a || !(a.h > 0)) { cls.push('none'); val = '–'; tipText = W.hours[i] + ': no time waited on record'; }
      else if (!a.ok) {
        cls.push('thin'); val = 'n' + a.n;
        tipText = W.hours[i] + ': ' + a.n + ' offers, ' + a.h.toFixed(1) + ' h on ' + a.d + ' shift days — under the floor';
      } else {
        var mk = a.mk && a.mk[ti];
        if (mk) cls.push(mk === 'above' ? 'up' : 'down');
        val = a.r[ti].toFixed(1);
        tipText = W.hours[i] + ': ' + rt(a.r[ti]) + ' good/hr (99% ' + rt(a.lo[ti]) + '–' + rt(a.hi[ti]) + '), '
          + a.h.toFixed(1) + ' h, ' + a.n + ' offers' + (mk ? ', ' + mk + ' every slot together' : '');
      }
      if (b === 'h' + i) cls.push('on');
      if (blk !== null && i >= BL[blk][0] && i < BL[blk][1]) cls.push('in');
      cells += '<button type="button" data-h="' + i + '" class="' + cls.join(' ') + '" title="' + esc(tipText)
        + '" aria-label="' + esc(tipText) + '"><span class="hl">' + shortHour(i) + '</span><span>' + val + '</span></button>';
    }
    el.innerHTML = cells;
    var every = W.slots['any|any'];
    document.getElementById('wwStripNote').innerHTML = esc(wwName('wwDay')) + ', hour by hour, every area together: '
      + 'good per hour waited. Coloured only where its 99% interval (widened by how the days swing) lies wholly above '
      + 'or below every slot together (' + (every ? rt(every.all.r[ti]) : '—') + ' good/hr); grey with its offers (n) '
      + 'under ' + W.minHours + ' h on ' + W.minDays + ' shift days. About 1 coloured square in 100 can be chance. '
      + 'Press an hour to pick it.';
  }
  function drawWW() {
    var W = R.whenwhere, el = document.getElementById('wwTable');
    if (!W || !el) return;
    var d = document.getElementById('wwDay').value, b = document.getElementById('wwBlock').value;
    var ti = Number(document.getElementById('wwTop').value), unit = document.getElementById('wwUnit').value;
    var cut = W.cuts[ti];
    document.getElementById('wwCut').textContent = cut === null ? 'no offers yet'
      : 'good = top ' + W.tops[ti] + '%: ≥ ' + m(cut) + '/hr';
    // Each block's hours on the day picked, so an empty slot shows before it is picked.
    Array.prototype.forEach.call(document.getElementById('wwBlock').options, function (o) {
      var sl = W.slots[d + '|' + o.value];
      o.textContent = o.getAttribute('data-name') + ' · ' + (sl ? sl.all.h : 0).toFixed(1) + ' h';
    });
    drawStrip(W, d, b, ti);
    var slot = W.slots[d + '|' + b], every = W.slots['any|any'];
    var said = '<b>' + esc(wwName('wwDay') + ', ' + wwName('wwBlock').toLowerCase()) + '</b>';
    if (!slot) {
      document.getElementById('wwSlot').innerHTML = said + ': no waiting on record in this slot.';
      el.innerHTML = ''; document.getElementById('wwThin').innerHTML = '';
      return;
    }
    var a0 = slot.all;
    document.getElementById('wwSlot').innerHTML = said + ': ' + a0.h.toFixed(1) + ' h waited on ' + a0.d
      + ' shift days, ' + a0.n + ' offers, ' + a0.g[ti] + ' good — <b>' + rt(a0.r[ti]) + ' good/hr</b> (99% '
      + rt(a0.lo[ti]) + '–' + rt(a0.hi[ti]) + '), P90 ' + m(a0.p90) + '/hr, median ' + m(a0.p50) + '/hr.'
      + (every && every !== slot ? ' Every slot together: ' + rt(every.all.r[ti]) + ' good/hr over '
         + every.all.h.toFixed(1) + ' h.' : '');
    var u = slot[unit];
    function nm(a) { return unit === 'cell' ? label('grid', a) : a; }
    function apps(s) {
      var k = s.u + s.dd;
      return k ? Math.round(s.u / k * 100) + '% · ' + Math.round(s.dd / k * 100) + '%' : '—';
    }
    var rows = u.ranked.slice().sort(function (x, y) { return y.r[ti] - x.r[ti] || y.h - x.h; });
    el.innerHTML = rows.length ? '<div class="tw"><table><thead><tr><th>' + (unit === 'cell' ? 'cell' : 'town')
      + '</th><th>good / hr</th><th>99%</th><th>hours waited</th><th>offers</th><th>good</th><th class="wide">P90 $/hr</th>'
      + '<th>median $/hr</th><th class="wide">Uber · DD</th><th></th></tr></thead><tbody>' + rows.map(function (s) {
        var mk = s.mk[ti];
        // The rate and its interval beside the name: on a phone the table
        // scrolls sideways and the first columns are the ones seen.
        // On a phone P90 and the app split ride under the name (R1), the
        // table's own columns for them hidden, so it scrolls less.
        return '<tr><td>' + esc(nm(s.a)) + '<small class="narrow">P90 ' + m(s.p90) + '/hr · Uber · DD ' + apps(s)
          + '</small></td><td data-v="' + s.r[ti] + '">' + rt(s.r[ti]) + '</td><td data-v="'
          + s.lo[ti] + '">' + rt(s.lo[ti]) + '–' + rt(s.hi[ti]) + '</td><td data-v="' + s.h + '">' + s.h.toFixed(1)
          + ' h</td><td>' + s.n + '</td><td>' + s.g[ti] + '</td><td class="wide">' + m(s.p90) + '</td><td>' + m(s.p50) + '</td><td class="wide" data-v="'
          + (s.u + s.dd ? s.u / (s.u + s.dd) : '') + '">' + apps(s) + '</td><td>'
          + (mk ? '<span class="tag ' + (mk === 'above' ? 'up' : 'down') + '">' + mk + ' the slot</span>' : '')
          + '</td></tr>';
      }).join('') + '</tbody></table></div>'
      : '<p class="note">No ' + (unit === 'cell' ? 'cell' : 'town') + ' has ' + W.minHours + ' h waited on '
        + W.minDays + ' shift days in this slot yet.</p>';
    document.getElementById('wwThin').innerHTML = (u.thin.length ? '<p><b>Too little time there yet</b> (under '
      + W.minHours + ' h or ' + W.minDays + ' shift days in this slot): ' + u.thin.slice(0, 60).map(function (t) {
        return esc(nm(t.a)) + ' ' + t.h.toFixed(1) + ' h (' + t.d + (t.d === 1 ? ' day' : ' days') + ')';
      }).join(', ') + (u.thin.length > 60 ? ', and ' + (u.thin.length - 60) + ' more' : '') + '.</p>' : '')
      + (u.left ? '<p>' + u.left + ' more ' + (unit === 'cell' ? 'cell' : 'town') + (u.left === 1 ? '' : 's')
         + ' where the car waited in this hour ' + (u.left === 1 ? 'clears' : 'clear') + ' the floor in no single hour of this day, so '
         + (u.left === 1 ? 'it is' : 'they are')
         + ' not listed hour by hour; pick a block to see ' + (u.left === 1 ? 'it' : 'them') + '.</p>' : '');
    markSortable();
  }
  var stripEl = document.getElementById('wwStrip');
  if (stripEl) stripEl.addEventListener('click', function (e) {
    var bt = e.target.closest && e.target.closest('button[data-h]');
    if (!bt) return;
    document.getElementById('wwBlock').value = 'h' + bt.getAttribute('data-h');
    drawWW();
  });
  ['wwDay', 'wwBlock', 'wwTop', 'wwUnit'].forEach(function (id) {
    var e0 = document.getElementById(id);
    if (e0) e0.addEventListener('change', drawWW);
  });
  /* Offers around you (aroundYou): the dots of the slot picked, coloured by
     the cutoff picked, on the Map tab's own Leaflet and tiles — or, with no
     internet, on a blank square — and three bar charts. This tab is the
     page's one exception to "computes no statistic of its own": the counts
     by ring and band over the slot picked, a median, and Wilson's interval
     on each share (the report's own wilson()), because the dots are already
     here and every slot of them worked out beforehand would be most of the
     file. The rings, the bands and the cutoffs are the server's. */
  function wilsonP(k, n) {
    if (!n) return null;
    var z = 1.96, p = k / n, dd = 1 + z * z / n;
    var mid = (p + z * z / (2 * n)) / dd, half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd;
    return [Math.max(0, mid - half), Math.min(1, mid + half)];
  }
  function aPick(d, b, day, h) {
    var A0 = R.around;
    if (d === 'wkday' && !(day >= 1 && day <= 5)) return false;
    if (d === 'wkend' && !(day === 0 || day === 6)) return false;
    if (/^\d$/.test(d) && Number(d) !== day) return false;
    if (b === 'any') return true;
    if (b[0] === 'h') return Number(b.slice(1)) === h;
    var bl = A0.blockHours[Number(b)];
    return h >= bl[0] && h < bl[1];
  }
  function hbRow(name, frac, cls, fig, whisk, thin) {
    return '<div class="hb' + (thin ? ' thinrow' : '') + '"><span class="nm">' + esc(name) + '</span><span class="track">'
      + (frac === null ? '' : '<span class="fill' + (cls ? ' ' + cls : '') + '" style="width:'
         + Math.max(0, Math.min(100, frac * 100)).toFixed(1) + '%"></span>')
      + (whisk ? '<span class="wh" style="left:' + (whisk[0] * 100).toFixed(1) + '%;width:'
         + Math.max(0.5, (whisk[1] - whisk[0]) * 100).toFixed(1) + '%"></span>' : '')
      + '</span><span class="fig">' + fig + '</span></div>';
  }
  var aMap = null, aLayer = null;
  // Each dot of a square at a point of a sunflower inside it, in miles from
  // the square's centre: spread by geography, so it scales with the zoom.
  function spread(list, binMi) {
    var out = [], n = list.length;
    list.forEach(function (x, j) {
      var rr = 0.42 * binMi * Math.sqrt((j + 0.5) / n), th = j * 2.399963;
      out.push({ x: x, dy: rr * Math.cos(th), dx: rr * Math.sin(th) });
    });
    return out;
  }
  function drawAround() {
    var A0 = R.around, W = R.whenwhere, el = document.getElementById('aMap');
    if (!A0 || !el) return;
    var d = document.getElementById('aDay').value, b = document.getElementById('aBlock').value;
    var ti = Number(document.getElementById('aTop').value), cut = W.cuts[ti];
    document.getElementById('aCut').textContent = cut === null ? 'no offers yet'
      : 'top ' + W.tops[ti] + '%: ≥ ' + m(cut) + '/hr';
    var D = A0.dots, byBin = {}, shown = 0, good = 0;
    for (var i = 0; i < D.b.length; i++) {
      if (!aPick(d, b, D.d[i], D.h[i])) continue;
      var g = cut !== null && D.r[i] >= cut;
      (byBin[D.b[i]] = byBin[D.b[i]] || []).push(g);
      shown += 1; if (g) good += 1;
    }
    var said = '<b>' + esc(wwName('aDay') + ', ' + wwName('aBlock').toLowerCase()) + '</b>';
    document.getElementById('aSays').innerHTML = said + ': ' + shown + ' offers drawn, ' + good + ' good'
      + (shown ? ' (' + Math.round(good / shown * 100) + '%)' : '') + (cut === null ? '' : ' at ≥ ' + m(cut) + '/hr') + '.';
    var pts = [];
    Object.keys(byBin).forEach(function (k) {
      var c = A0.bins[Number(k)];
      spread(byBin[k], A0.binMi).forEach(function (p) {
        pts.push({ lat: c[0] + p.dy / 69, lon: c[1] + p.dx / (69 * Math.cos(c[0] * Math.PI / 180)), good: p.x });
      });
    });
    var up = col('--up'), grey = col('--grey');
    var note = document.getElementById('aMapNote');
    if (typeof L !== 'undefined') {
      if (!aMap) {
        aMap = L.map('aMap', { preferCanvas: true });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(aMap);
      }
      if (aLayer) aLayer.remove();
      aLayer = L.layerGroup().addTo(aMap);
      if (A0.centre) {
        for (var rg = 1; rg <= Math.min(A0.rings, 5); rg++) {
          L.circle([A0.centre.lat, A0.centre.lon], { radius: rg * A0.ringMi * 1609.34, color: col('--axis'), weight: 1,
            dashArray: '4 4', fill: false, interactive: false }).addTo(aLayer);
        }
      }
      pts.forEach(function (p) {
        L.circleMarker([p.lat, p.lon], { radius: 3, stroke: false, fillColor: p.good ? up : grey, fillOpacity: 0.85 })
          .addTo(aLayer);
      });
      if (pts.length) aMap.fitBounds(pts.map(function (p) { return [p.lat, p.lon]; }), { padding: [20, 20], maxZoom: 15 });
      else if (A0.centre) aMap.setView([A0.centre.lat, A0.centre.lon], 12);
      else aMap.setView([0, 0], 2);
      note.textContent = 'Dashed rings: 1 to 5 miles from the most-used waiting area, as in the chart below.';
    } else {
      // No Leaflet (no internet): the same dots on a blank square, north up,
      // a mile to scale, and the rings — no street under them.
      var Wd = el.clientWidth || 600, Hd = el.clientHeight || 460;
      var lats = pts.map(function (p) { return p.lat; }), lons = pts.map(function (p) { return p.lon; });
      if (A0.centre) { lats.push(A0.centre.lat); lons.push(A0.centre.lon); }
      if (!lats.length) { el.innerHTML = '<p class="note" style="padding:12px">No dot in this slot.</p>'; }
      else {
        // A loop, not Math.min.apply: an Any-day slot holds a dot for every
        // offer, past the ~125,000 arguments the stack takes (minOf's note).
        var la0 = Infinity, la1 = -Infinity, lo0 = Infinity, lo1 = -Infinity;
        for (var di = 0; di < lats.length; di++) {
          if (lats[di] < la0) la0 = lats[di];
          if (lats[di] > la1) la1 = lats[di];
          if (lons[di] < lo0) lo0 = lons[di];
          if (lons[di] > lo1) lo1 = lons[di];
        }
        var kx = Math.cos((la0 + la1) / 2 * Math.PI / 180);
        var spanX = Math.max((lo1 - lo0) * kx, 0.01), spanY = Math.max(la1 - la0, 0.01);
        var sc = Math.min((Wd - 40) / spanX, (Hd - 40) / spanY);
        var ox = (Wd - spanX * sc) / 2, oy = (Hd - spanY * sc) / 2;
        var X = function (lon) { return ox + (lon - lo0) * kx * sc; };
        var Y = function (lat) { return Hd - oy - (lat - la0) * sc; };
        var mile = sc / 69;
        var svg = '<svg viewBox="0 0 ' + Wd + ' ' + Hd + '" aria-hidden="true">';
        if (A0.centre) {
          for (var rr2 = 1; rr2 <= Math.min(A0.rings, 5); rr2++) {
            svg += '<circle cx="' + X(A0.centre.lon).toFixed(1) + '" cy="' + Y(A0.centre.lat).toFixed(1) + '" r="'
              + (rr2 * A0.ringMi * mile).toFixed(1) + '" fill="none" stroke="' + col('--axis') + '" stroke-dasharray="4 4"/>';
          }
        }
        pts.forEach(function (p) {
          svg += '<circle cx="' + X(p.lon).toFixed(1) + '" cy="' + Y(p.lat).toFixed(1) + '" r="2.6" fill="'
            + (p.good ? up : grey) + '" fill-opacity="0.85"/>';
        });
        svg += '<line x1="16" x2="' + (16 + mile).toFixed(1) + '" y1="' + (Hd - 14) + '" y2="' + (Hd - 14)
          + '" stroke="' + col('--ink2') + '" stroke-width="2"/><text x="16" y="' + (Hd - 20) + '" fill="'
          + col('--ink2') + '" font-size="12">1 mi</text></svg>';
        el.innerHTML = svg;
      }
      note.textContent = 'The map needs the internet for Leaflet and its tiles: the dots are drawn on a blank '
        + 'square, north up, with a mile to scale and dashed rings 1 to 5 miles from the most-used waiting area.';
    }
    // (a) the share good by ring.
    var nR = [], kR = [];
    for (var j = 0; j < D.b.length; j++) {
      if (D.g[j] === null || !aPick(d, b, D.d[j], D.h[j])) continue;
      nR[D.g[j]] = (nR[D.g[j]] || 0) + 1;
      if (cut !== null && D.r[j] >= cut) kR[D.g[j]] = (kR[D.g[j]] || 0) + 1;
    }
    var rings = '';
    for (var q = 0; q <= A0.rings; q++) {
      var n = nR[q] || 0, k = kR[q] || 0;
      if (!n) continue;
      var nm = q === A0.rings ? A0.rings * A0.ringMi + ' mi or more' : q * A0.ringMi + '–' + (q + 1) * A0.ringMi + ' mi';
      if (n < R.descMinN) { rings += hbRow(nm, null, '', n + ' offers — too few', null, true); continue; }
      var w0 = wilsonP(k, n);
      rings += hbRow(nm, k / n, 'up', pc(k / n) + ' good [' + pc(w0[0]) + ', ' + pc(w0[1]) + '] · n ' + n, w0, false);
    }
    document.getElementById('aRings').innerHTML = rings || '<p class="note">No dot in this slot.</p>';
    // (b) When & where's slot table, drawn.
    var slot = W.slots[d + '|' + b], areas = '';
    if (slot) {
      var unit = slot.town.ranked.length ? 'town' : 'cell', u = slot[unit];
      var rows = u.ranked.slice().sort(function (x, y) { return y.r[ti] - x.r[ti] || y.h - x.h; });
      var top = Math.max.apply(null, [0.1].concat(rows.map(function (s0) { return s0.hi[ti]; })));
      rows.forEach(function (s0) {
        var mk = s0.mk[ti];
        areas += hbRow(unit === 'cell' ? label('grid', s0.a) : s0.a, s0.r[ti] / top, mk === 'above' ? 'up' : mk === 'below' ? 'down' : '',
                       rt(s0.r[ti]) + ' good/hr [' + rt(s0.lo[ti]) + '–' + rt(s0.hi[ti]) + '] · ' + s0.h.toFixed(1) + ' h',
                       [s0.lo[ti] / top, s0.hi[ti] / top], false);
      });
      if (!rows.length) areas = '<p class="note">No area has ' + W.minHours + ' h waited on ' + W.minDays
        + ' shift days in this slot yet.</p>';
      if (u.thin.length) areas += '<p class="note">Too little time there yet: ' + u.thin.length + ' '
        + (unit === 'cell' ? 'cell' : 'town') + (u.thin.length === 1 ? '' : 's') + ' (see When &amp; where).</p>';
    } else {
      areas = '<p class="note">No waiting on record in this slot.</p>';
    }
    document.getElementById('aAreas').innerHTML = areas;
    // (c) the card's own drive to the pickup.
    var P0 = A0.pickup, byB = {};
    for (var e = 0; e < P0.b.length; e++) {
      if (!aPick(d, b, P0.d[e], P0.h[e])) continue;
      (byB[P0.b[e]] = byB[P0.b[e]] || []).push(P0.r[e]);
    }
    var bands = '';
    P0.bands.forEach(function (nm2, bi) {
      var v = byB[bi] || [];
      if (!v.length) return;
      if (v.length < R.descMinN) { bands += hbRow(nm2, null, '', v.length + ' offers — too few', null, true); return; }
      var kk = cut === null ? 0 : v.filter(function (x) { return x >= cut; }).length;
      var s1 = v.slice().sort(function (x, y) { return x - y; });
      var med = s1.length % 2 ? s1[(s1.length - 1) / 2] : (s1[s1.length / 2 - 1] + s1[s1.length / 2]) / 2;
      var w1 = wilsonP(kk, v.length);
      bands += hbRow(nm2, kk / v.length, 'up', pc(kk / v.length) + ' good [' + pc(w1[0]) + ', ' + pc(w1[1]) + '] · median '
                     + m(med) + '/hr · n ' + v.length, w1, false);
    });
    document.getElementById('aPickup').innerHTML = bands
      || '<p class="note">No card in this slot printed its drive to the pickup.</p>';
  }
  ['aDay', 'aBlock', 'aTop'].forEach(function (id) {
    var e0 = document.getElementById(id);
    if (e0) e0.addEventListener('change', drawAround);
  });
  coverageTable();
  levelsTable();
  shareTests();
  draw();
  drawWW();
  route();
}());
