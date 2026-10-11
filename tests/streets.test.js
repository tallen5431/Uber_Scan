/* The NucBox's street index, end to end. Run with: node tests/streets.test.js
 *
 * tests/fixtures/streets.osm is a handful of invented streets round Marietta
 * Square, each there for one rule:
 *
 *   Northgate Drive        north-south; meets Foxglove Trail at a shared node
 *   Foxglove Trail         one street split into four ways end to end
 *   a footway also called  meets Foxglove Trail 740 m east of the street's
 *     Northgate Drive      corner — kept, it would be a second corner
 *   Wren Road              crosses Foxglove Trail with NO shared node (a
 *                          bridge); shares nodes with both carriageways of
 *   Kestrel Parkway SE     a dual carriageway, two ways of one name 22 m apart
 *   Heron Way / Herron Way one letter apart, three miles apart, both real
 *   Juniper Circle         a loop meeting Northgate Drive twice, 444 m apart
 *   Church Street NW / SE  two streets, four miles apart
 *   Pine Court             meets Wren Road; there is no Pine Street
 *   Bramble Ct             OSM's own abbreviation
 *   Larkspur Parkway SE    alt_name Old Mill Road along its whole length, and
 *                          a second stretch of it 6.4 mi off
 *   not kept               an unnamed way, a building called Foxglove Trail,
 *                          and Faraway Road outside the metro
 *
 * Through the REAL exporter (tools/street_index.py, with osmium-tool when it
 * is installed and from tests/fixtures/streets.opl — osmium's own output for
 * that file, held here to what osmium writes now — when it is not), the real
 * streets.js, and the real server.js answering /api/streets. The rig's relay
 * of it is rpi/test_server.py's; what the panel does with it is
 * tests/mapview.test.js's and rpi/test_dashboard.py's. */
'use strict';

var cp = require('child_process');
var fs = require('fs');
var os = require('os');
var path = require('path');
var net = require('net');
var S = require('../streets.js');

var ROOT = path.join(__dirname, '..');
var FIX = path.join(__dirname, 'fixtures');
var pass = 0, fail = 0;

function eq(name, got, want) {
  var ok = got === want
    || (typeof got === 'number' && typeof want === 'number'
        && isFinite(got) && isFinite(want) && Math.abs(got - want) < 1e-6);
  if (ok) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + JSON.stringify(got)
                             + ' want ' + JSON.stringify(want)); }
}
function ok_(name, cond) { eq(name, !!cond, true); }

var tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'streets-'));

function exporter(args) {
  var r = cp.spawnSync('python3', [path.join(ROOT, 'tools', 'street_index.py')].concat(args),
                       { encoding: 'utf8' });
  return { status: r.status, said: (r.stderr || '') + (r.stdout || '') };
}

// Everything below runs inside main(), so a check that throws is reported
// as a failure by name rather than ending the run with nothing said.
var IDX, doc, ix, st, box;
function offline() {
/* ---- the exporter -------------------------------------------------------- */
var haveOsmium = cp.spawnSync('osmium', ['--version'], { encoding: 'utf8' }).status === 0;
var fromOpl = path.join(tmp, 'from-opl.json');
var r = exporter([path.join(FIX, 'streets.osm'), fromOpl, '--opl', path.join(FIX, 'streets.opl')]);
eq('the exporter reads osmium\'s OPL and writes an index', r.status, 0);
ok_('...saying what it kept and what it dropped (' + r.said.trim() + ')',
    /kept 17 ways, 175 nodes, 13 names; dropped 1 unnamed, 0 other highway, 0 no location/
      .test(r.said));
IDX = fromOpl;
if (haveOsmium) {
  var fromPbf = path.join(tmp, 'from-osm.json'), opl = path.join(tmp, 'now.opl');
  r = exporter([path.join(FIX, 'streets.osm'), fromPbf, '--keep-opl', opl]);
  eq('with osmium-tool, the exporter runs the three osmium commands itself', r.status, 0);
  eq('...and osmium writes exactly the OPL committed beside the fixture',
     fs.readFileSync(opl, 'utf8'), fs.readFileSync(path.join(FIX, 'streets.opl'), 'utf8'));
  eq('...so the index from the .osm and from the OPL are one file',
     fs.readFileSync(fromPbf, 'utf8'), fs.readFileSync(fromOpl, 'utf8'));
  IDX = fromPbf;
} else {
  console.log('osmium-tool is not installed: the OPL step is checked against the '
              + 'committed copy only (sudo apt install osmium-tool)');
}
doc = JSON.parse(fs.readFileSync(IDX, 'utf8'));
ix = S.build(doc);
eq('the index is the format the server reads', doc.format, S.FORMAT);
eq('alt_name is a name too, and Faraway Road (outside the metro) is not kept',
   JSON.stringify([doc.names.indexOf('Old Mill Road') >= 0, doc.names.indexOf('Faraway Road')]),
   '[true,-1]');
// The ways an OSM name was kept as, found by its name as OSM spells it.
function waysNamed(name) {
  var w = [];
  ix.byKey.forEach(function (e) { if (e.names.indexOf(name) >= 0) w = w.concat(e.ways); });
  return w;
}
eq('the footway called Northgate Drive is not kept: one way of that name',
   waysNamed('Northgate Drive').length, 1);
eq('the building called Foxglove Trail is not kept: the street\'s own four ways',
   waysNamed('Foxglove Trail').length, 4);
// A node two ways share is ONE node in the index: that is a junction.
function wayNodes(w) { return Array.from(ix.nodes.slice(ix.start[w], ix.start[w + 1])); }
var ng = [].concat.apply([], waysNamed('Northgate Drive').map(wayNodes));
var fx = [].concat.apply([], waysNamed('Foxglove Trail').map(wayNodes));
var both = ng.filter(function (n) { return fx.indexOf(n) >= 0; });
eq('Foxglove Trail and Northgate Drive share one node, at 33.96, -84.55',
   both.length === 1 && [ix.lat[both[0]], ix.lon[both[0]]].join(','), '33.96,-84.55');
// The exporter's own list, where osmium did not filter first.
var stray = path.join(tmp, 'stray.opl');
fs.writeFileSync(stray, 'w1 v1 dV c0 t i0 u Thighway=footway,name=Some%20%Path '
                 + 'Nn1x-84.5y33.9,n2x-84.4y33.9\n'
                 + 'w2 v1 dV c0 t i0 u Thighway=residential,name=Some%20%Road '
                 + 'Nn1x-84.5y33.9,n3x\n');
r = exporter([path.join(FIX, 'streets.osm'), path.join(tmp, 'stray.json'), '--opl', stray]);
ok_('a footway reaching the exporter is dropped by its own list, and a way with '
    + 'one located node by its own check (' + r.said.trim() + ')',
    /kept 0 ways.*0 unnamed, 1 other highway, 1 no location/.test(r.said));

/* ---- names --------------------------------------------------------------- */
// Every street of the fixture is inside this box; the OCR rule is asked only
// inside a box (a card's disc), so the name checks are asked in one.
var ALL = S.boxOf('-84.6,34.0,-84.4,33.8');
function m(name, box) {
  var x = S.match(ix, name, box === undefined ? ALL : box);
  return x.names.join(' | ') + ' (' + x.how + ')';
}
eq('the card\'s "Trl" finds OSM\'s "Trail"', m('Foxglove Trl'), 'Foxglove Trail (exact)');
eq('...and "Court" finds an OSM name written "Ct": abbreviations both ways',
   m('Bramble Court'), 'Bramble Ct (exact)');
eq('"Kestrel Pkwy SE" finds "Kestrel Parkway Southeast"', m('Kestrel Pkwy SE'),
   'Kestrel Parkway Southeast (exact)');
eq('a directional on one side only finds both streets of that name',
   m('Church St'), 'Church Street Northwest | Church Street Southeast (dir)');
eq('...and "SE" finds only the SE one', m('Church St SE'), 'Church Street Southeast (exact)');
eq('...and "NE" finds neither: two directionals that differ never match',
   m('Church St NE'), ' (null)');
eq('one letter read wrong in a street word: "Tri" for Trl', m('Foxglove Tri'),
   'Foxglove Trail (ocr)');
eq('...and in a long word: "Foxgiove Trl" for Foxglove Trail', m('Foxgiove Trl'),
   'Foxglove Trail (ocr)');
eq('...but only the letter the reader is seen to misread, i for l: "Wen Rd" is not '
   + 'Wren Road', m('Wen Rd'), ' (null)');
eq('...and never with no box to keep the guess to: "Foxglove Tri" asked of the whole '
   + 'index', m('Foxglove Tri', null), ' (null)');
// Juniper Circle is at 33.965-33.969; this box is south of it.
eq('...and only among the names inside the box: "Junlper Cir" in a box short of '
   + 'Juniper Circle finds nothing', m('Junlper Cir', S.boxOf('-84.56,33.959,-84.551,33.95')),
   ' (null)');
eq('...where one holding it finds it', m('Junlper Cir', S.boxOf('-84.56,33.97,-84.54,33.96')),
   'Juniper Circle (ocr)');
eq('...never one street word for another: "Pine St" is not Pine Court', m('Pine St'), ' (null)');
eq('a name the index holds exactly is never widened to its neighbour: Heron Way '
   + 'is not also Herron Way', m('Heron Way'), 'Heron Way (exact)');
eq('the OCR\'s litter is dropped after the street\'s type: "Foxglove Trl x"',
   m('Foxglove Trl x'), 'Foxglove Trail (junk)');
// The town a reader glued on is only ever on a dropoff with no comma, which
// map-view.js asks of Nominatim and never of this (see cleaned).
eq('...but a word after the type is not dropped as a town: "Northgate Dr NE '
   + 'Marietta" is refused', m('Northgate Dr NE Marietta'), ' (null)');
eq('a name nothing like any street finds nothing', m('Quintessence Blvd'), ' (null)');
// Guards measured on the week's real names (see the commit): each kept two
// real, different streets apart.
function tiny(names) {
  return S.build({ format: S.FORMAT, e: 6, names: names, nodes: [0, 0, 1, 1],
                   ways: names.map(function (n, i) { return [[i], [0, 1]]; }) });
}
// "Ol Canton Rd" is the card's Old Canton Road with its first word misread;
// dropped as litter it was asked as Canton Road, a different street whose
// corner was a mile off.
eq('"Ol Canton Rd" is not Canton Road: a word before the type is the name, never litter',
   S.match(tiny(['Canton Road', 'Old Canton Road']), 'Ol Canton Rd').how, null);
eq('a lone digit is a route\'s number, never litter: "Old Hwy 5" is not "Old Highway"',
   S.match(tiny(['Old Highway']), 'Old Hwy 5').how, null);
eq('nothing is dropped after a type spelled out, which may be the name: "Orange '
   + 'Grove PI" is not "Orange Grove"', S.match(tiny(['Orange Grove']), 'Orange Grove PI').how,
   null);
eq('"Main St NW" is not "S Main St": two names each with a directional the other '
   + 'lacks never match, before or after', S.match(tiny(['S Main Street']), 'Main St NW').how,
   null);
eq('...nor "Cobb Pkwy S" "S Cobb Pkwy NW", whose S is before the name and NW after',
   S.match(tiny(['S Cobb Parkway NW']), 'Cobb Pkwy S').how, null);
eq('...but one more on one side still matches: "Lincoln Trace Ave SE" finds '
   + '"S Lincoln Trace Ave SE"', S.match(tiny(['S Lincoln Trace Avenue SE']),
                                          'Lincoln Trace Ave SE').how, 'dir');
// tiny()'s one way is at 0,0; a box round it, as a card's disc would be.
var NEAR = [-1, -1, 1, 1];
eq('"17th St NW" is not "12th Street Northwest": no OCR letter is a digit',
   S.match(tiny(['12th Street Northwest']), '17th St NW', NEAR).how, null);
eq('"Parliament Ct" is not "Parliament Street"', S.match(tiny(['Parliament Street']),
                                                          'Parliament Ct', NEAR).how, null);
// ...and that holds of every pair of street words, so St is never read as
// Ct: none is another with the one letter the reader misreads.
var vocab = Object.keys(S.TYPES).map(function (k) { return S.TYPES[k]; })
  .concat(Object.keys(S.DIRS).map(function (k) { return S.DIRS[k]; }));
eq('no street word is another street word read one letter wrong',
   vocab.filter(function (a) {
     return vocab.some(function (b) { return S.ocrMay(a, b); });
   }).join(' '), '');
eq('"Ell Ct" is not "Eli Court": no OCR letter in a word under four letters',
   S.match(tiny(['Eli Court']), 'Ell Ct', NEAR).how, null);
eq('"Beach St" is not "Beech St", both on the week\'s cards: a, e and any letter but '
   + 'i and l are never read for each other', S.match(tiny(['Beech Street']), 'Beach St',
                                                      NEAR).how, null);
// Ellis Street is held across town; Eliis Street, one OCR letter from it,
// inside the card's box. The card printed a name the index holds.
var twoPlaces = S.build({ format: S.FORMAT, e: 6, names: ['Ellis Street', 'Eliis Street'],
                          nodes: [-84500000, 33900000, 100, 0, 100000, 100000, 100, 0],
                          ways: [[[0], [0, 1]], [[1], [2, 1]]] });
eq('a name the index holds anywhere is never read as another inside the box: '
   + '"Ellis St" is not the box\'s "Eliis Street"',
   S.match(twoPlaces, 'Ellis St', S.boxOf('-84.41,34.01,-84.39,33.99')).names.join(),
   'Ellis Street');

/* ---- where two streets meet --------------------------------------------- */
function meets(a, b, box) {
  return S.cross(ix, a, b, box ? S.boxOf(box) : null).meets.map(function (x) {
    return [x.lat, x.lon, x.n, x.spanM, x.shared ? 'node' : 'crossing'].join(',');
  }).join(' ; ');
}
eq('ways sharing a node meet there, once, though one of them is four ways',
   meets('Foxglove Trl', 'Northgate Dr'), '33.96,-84.55,1,0,node');
eq('ways that cross with no shared node meet where their segments cross',
   meets('Wren Rd', 'Foxglove Trl'), '33.96,-84.5455,1,0,crossing');
eq('a road across a dual carriageway meets it twice, 22 m apart: one corner',
   meets('Wren Rd', 'Kestrel Pkwy SE'), '33.9451,-84.5455,2,22,node');
eq('a loop meeting a street twice, 444 m apart, is two corners',
   meets('Juniper Cir', 'Northgate Dr'), '33.965,-84.55,1,0,node ; 33.969,-84.55,1,0,node');
eq('two names on one way run together for its length: one meeting 1199 m long',
   meets('Larkspur Pkwy SE', 'Old Mill Rd'), '33.948,-84.5585,14,1199,node');
eq('"Church St" (no directional) meets Northgate Drive where the NW one does',
   meets('Church St', 'Northgate Dr'), '33.955,-84.55,1,0,node');
eq('...and "Church St SE" does not meet it at all', meets('Church St SE', 'Northgate Dr'), '');
eq('only inside the box asked: a box short of the corner holds none',
   meets('Foxglove Trl', 'Northgate Dr', '-84.56,33.959,-84.551,33.95'), '');
// ...and the box is held to the POINT, not only to the ways: both streets
// reach into this box, and only the northern corner is in it.
eq('...and of Juniper Circle\'s two corners, a box holding one answers one',
   meets('Juniper Cir', 'Northgate Dr', '-84.551,33.97,-84.54,33.966'),
   '33.969,-84.55,1,0,node');
var cx = S.cross(ix, 'Pine St', 'Wren Rd', null);
eq('a name the index does not hold is said, with no meeting',
   JSON.stringify([cx.a.names, cx.b.names, cx.meets]), '[[],["Wren Road"],[]]');
// More meetings than one answer carries: a comb of 60 teeth 200 m apart.
var comb = { format: S.FORMAT, e: 6, names: ['Comb Road', 'Spine Road'], nodes: [], ways: [] };
var spine = [];
for (var t = 0; t < 60; t++) {
  comb.nodes.push(t === 0 ? -84500000 : 2000, t === 0 ? 33900000 : 0);
  spine.push(t === 0 ? 0 : 1);
}
comb.ways.push([[1], spine]);
// Each tooth runs from 0.001 degrees north of the spine to 0.001 south,
// halfway between two of its nodes; coordinates are deltas, node to node.
for (t = 0; t < 60; t++) {
  comb.nodes.push(t === 0 ? 1000 - 2000 * 59 : 2000, t === 0 ? 1000 : 2000, 0, -2000);
  comb.ways.push([[0], [60 + 2 * t, 1]]);
}
// The teeth cross the spine with no shared node.
var combed = S.cross(S.build(comb), 'Comb Rd', 'Spine Rd', null);
eq('sixty meetings are cut at ' + S.MEETS_MAX + ', and say so',
   [combed.meets.length, combed.cutAt].join(','), S.MEETS_MAX + ',' + S.MEETS_MAX);

/* ---- the stretch of one street ------------------------------------------ */
box = '-84.56,33.95,-84.54,33.94';
st = S.stretch(ix, 'Larkspur Pkwy SE', S.boxOf(box));
var pts = [].concat.apply([], st.lines);
ok_('a stretch is only the part inside the box (' + pts.length + ' points)',
    pts.length && pts.every(function (p) {
      return p[0] >= 33.94 && p[0] <= 33.95 && p[1] >= -84.56 && p[1] <= -84.54;
    }));
eq('...cut at the box\'s edge, not at the nearest node inside it',
   JSON.stringify([st.lines.length, st.lines[0][0], st.lines[0][st.lines[0].length - 1]]),
   '[1,[33.948,-84.56],[33.948,-84.552]]');
eq('...and without a box, both stretches of it, 6.4 mi apart',
   S.stretch(ix, 'Larkspur Pkwy SE', null).lines.length, 2);
var cutSt = S.stretch(ix, 'Larkspur Pkwy SE', null, 5);
eq('a stretch longer than the answer carries is cut and says so, with no lines',
   JSON.stringify([cutSt.cutAt, cutSt.lines.length]), '[5,0]');

}

/* ---- the real server, on the NucBox -------------------------------------- */
function freePort() {
  return new Promise(function (resolve) {
    var s = net.createServer().listen(0, '127.0.0.1', function () {
      var p = s.address().port;
      s.close(function () { resolve(p); });
    });
  });
}
async function serve(env) {
  var port = await freePort();
  var out = '';
  var proc = cp.spawn('node', [path.join(ROOT, 'server.js')], {
    env: Object.assign({}, process.env, env, { PORT: String(port), HTTPS_PORT: '0',
      SCANNER: '0', JOURNAL: path.join(tmp, 'j' + port + '.jsonl') }) });
  proc.stdout.on('data', function (d) { out += d; });
  proc.stderr.on('data', function (d) { out += d; });
  var base = 'http://127.0.0.1:' + port;
  for (var i = 0; i < 100; i++) {
    try { await fetch(base + '/api/status'); break; } catch (e) {
      await new Promise(function (r2) { setTimeout(r2, 100); });
    }
  }
  return { base: base, said: function () { return out; }, stop: function () { proc.kill(); } };
}
async function get(srv, u, init) {
  var res = await fetch(srv.base + u, init);
  var body = await res.json().catch(function () { return null; });
  return { status: res.status, body: body };
}

(async function () {
  try { offline(); } catch (e) {
    fail++;
    console.log('FAIL  the checks before the server threw: ' + (e && e.stack || e));
  }
  var nuc = await serve({ NUCBOX_STREETS_FILE: IDX });
  var none = await serve({});
  var bad = path.join(tmp, 'bad.json');
  fs.writeFileSync(bad, '{"format": "something else"}');
  var broken = await serve({ NUCBOX_STREETS_FILE: bad });
  try {
    var g = await get(nuc, '/api/streets');
    eq('the NucBox\'s server loads the index named by NUCBOX_STREETS_FILE and says what is in it',
       JSON.stringify([g.body.loaded, g.body.counts]),
       JSON.stringify([true, { names: 13, ways: 17, nodes: 175 }]));
    ok_('...and prints it at start, with what loading it took (' +
        (/Street index: .*/.exec(nuc.said()) || [''])[0] + ')',
        /Street index: 13 names, 17 ways, 175 nodes from .*, loaded in \d+ ms, heap \d+ MB/
          .test(nuc.said()));
    g = await get(nuc, '/api/streets/cross?a=' + encodeURIComponent('Foxglove Tri')
                  + '&b=' + encodeURIComponent('Northgate Dr') + '&box=-84.6,34.0,-84.5,33.9');
    eq('/api/streets/cross answers where two streets meet inside the box',
       JSON.stringify([g.status, g.body.a.names, g.body.a.how, g.body.meets]),
       JSON.stringify([200, ['Foxglove Trail'], 'ocr',
                       [{ lat: 33.96, lon: -84.55, n: 1, spanM: 0, shared: true }]]));
    g = await get(nuc, '/api/streets/stretch?name=' + encodeURIComponent('Larkspur Pkwy SE')
                  + '&box=' + box);
    eq('/api/streets/stretch answers the street inside the box',
       JSON.stringify([g.status, g.body.lines]), JSON.stringify([200, st.lines]));
    var refused = [
      ['/api/streets/cross?a=x&b=y&limit=5', 'refused: limit'],
      ['/api/streets/cross?a=x&a=y&b=z', 'given more than once: a'],
      ['/api/streets/cross?a=x', 'a and b must each be'],
      ['/api/streets/cross?a=x&b=' + 'y'.repeat(121), 'a and b must each be'],
      ['/api/streets/stretch?name=x&box=1,2,3', 'box is left,top,right,bottom'],
      ['/api/streets/stretch?a=x', 'refused: a'],
      ['/api/streets/near?name=x', 'no such street endpoint']];
    for (var i = 0; i < refused.length; i++) {
      g = await get(nuc, refused[i][0]);
      ok_('the NucBox refuses ' + refused[i][0].slice(0, 50) + ' (' + JSON.stringify(g.body) + ')',
          (g.status === 400 || g.status === 404) && g.body
          && String(g.body.error).indexOf(refused[i][1]) >= 0);
    }
    g = await get(nuc, '/api/streets/cross?a=x&b=y', { method: 'POST', body: '{}' });
    eq('...and answers GET only', g.status, 405);
    g = await get(none, '/api/streets/cross?a=x&b=y');
    eq('with no index set, a question is "not loaded here", not "no such street"',
       JSON.stringify([g.status, g.body.configured]), '[404,false]');
    eq('...and /api/streets says nothing is loaded', (await get(none, '/api/streets')).body.loaded,
       false);
    g = await get(broken, '/api/streets/cross?a=x&b=y');
    ok_('an index that cannot be read is said as that, with the reason, on every question ('
        + JSON.stringify(g.body) + ')',
        g.status === 503 && /could not be read \(not a street index/.test(g.body.error));
    ok_('...and at start', /could not be read .* — \/api\/streets answers that/.test(broken.said()));
  } finally {
    nuc.stop(); none.stop(); broken.stop();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  console.log(fail ? ('\n' + pass + ' passed, ' + fail + ' FAILED')
                   : '\nAll ' + pass + ' street index checks passed');
  process.exit(fail ? 1 : 0);
})().catch(function (e) {
  console.log('FAIL  the suite itself threw: ' + (e && e.stack || e));
  process.exit(1);
});
