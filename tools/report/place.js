/* Placing a pickup (and a taken trip's dropoff) by the rig's own rules:
 * the search plan, the NucBox's whole chain and its levels, the printed
 * door, the order in the car's end, and the places the pins make. Part of
 * the places report; tools/places_report.js has the rules and re-exports
 * every name here that it always has. */

'use strict';

var A = require('../../advice.js');
var MV = require('../../map-view.js');
var AS = require('../../assemble.js');

var ST = require('./stats.js');
var PLACE_SAME_MI = ST.PLACE_SAME_MI, FINISHED = ST.FINISHED, GPS_TIMED = ST.GPS_TIMED, seenAt = ST.seenAt,
    round5 = ST.round5;

/* --- placing a pickup, by the rig's own rules ----------------------------
 *
 * What the pickup text is, as a question: a door, a store's name, a corner,
 * a street with no number, or nothing searchable. searchPlan decides; the
 * name plan is the server's pickupNamePlan (three letters at least). */
function pickupKind(text) {
  var plan = typeof text === 'string' && text ? MV.searchPlan(text) : null;
  if (!plan) return { kind: 'none', plan: null };
  if (plan.kind === 'street') return { kind: plan.door ? 'door' : 'street', plan: plan };
  if (plan.kind === 'cross') return { kind: 'cross', plan: plan };
  if (plan.kind === 'name' && plan.q && /[A-Za-z]{3}/.test(plan.q)) return { kind: 'name', plan: plan };
  return { kind: 'none', plan: plan };
}

// The words a refusal is counted under. One list, printed as is.
var WHY = {
  nofix: 'no GPS fix on the card',
  nofixdoor: 'no GPS fix on the card, and no town or ZIP printed to search the region by',
  regiontown: 'no fix; the door found in the region is not in the printed town',
  corners: 'a corner whose streets meet in several places',
  nomeet: 'a corner whose streets do not meet inside the card\'s reach',
  nostreet: 'a street the street index does not hold',
  notwo: 'nothing searchable',
  long: 'a street with no door number',
  several: 'several places answer (a chain, or branches)',
  capped: 'several places answer (a chain, or branches)',
  // The search's own refusals, in the rig's words (MV.REFUSAL_WORDS; AUDITS.md,
  // Done, "Four refusals were one label"). All four were "not found inside the
  // card's reach" until 9 Nov 2026, where the rig said that of 'none' alone,
  // and three of them are not about the reach: a street found without its
  // number, a store's name OSM spells otherwise, a corner run together. A
  // placement carries its own words (`said`, `refusedSaid`: wordsOf, which
  // splits 'none' by what the box held); these are for one that does not.
  noplace: MV.REFUSAL_WORDS.noname,
  none: MV.REFUSAL_WORDS.nobox,
  nodoor: MV.REFUSAL_WORDS.nodoor,
  together: MV.REFUSAL_WORDS.together,
  cross: 'a corner, and no street index to ask',
  street: 'a street with no door number',
  notext: 'nothing searchable',
  unreachable: 'the NucBox did not answer',
  refused: 'the NucBox did not answer',
};

/* --- THE THIRD PASS: the rig's whole search chain, and its levels ---------
 *
 * The owner's first real run (25 Oct 2026) placed 8% of pickups: a corner
 * with no street index (the run asked Nominatim directly and so never asked
 * the index), a street with no door number, several answers, and cards with
 * no fix. The owner, 26 Oct: "Go ahead with all three, fast track to
 * experimental."
 *
 * ONE RULE IN ONE PLACE, still. NbxSearch.place IS the chain server.js
 * composes as doorChain for a held order's door — the street as printed
 * (pickInDisc), then the type word left out where the street was not in
 * reach (MV.streetRetry / retryWanted / pickRetry), the directional the other
 * way where the street was found and not the door (MV.dirRetry / dirWanted /
 * afterDir), the street index's one street for the name as read (nameWanted /
 * nameRetry / pickNamed), and for a door nothing answered its street alone
 * (MV.streetArea) — so this asks it, never a copy. A corner is NbxSearch's
 * corner (the street index's /cross, pickInDisc), a numberless street its
 * `whole` (NbxSearch.streetArea), a refused door's candidates the distance
 * band (NbxSearch.band: MV.bandTarget's Uber `toPickupMiles` or DoorDash's
 * upper bound, road miles off the relay's /route, MV.bandPick), and the
 * areas pickInDisc puts beside a refusal (MV.withArea: 'several', 'nodoor',
 * 'capped') are read as they come.
 *
 * LEVELS. Every placement says how it was placed:
 *   'door'    a printed door, found at its number (one place, or agreeing)
 *   'corner'  where the two streets meet, one meeting inside the reach
 *   'name'    a store's name, one place of it answered (pickPlace)
 * ...those three are a POINT. And three that are an AREA, never a pin on the
 * rig and approximate here, each with its spread (the two farthest
 * candidates apart, MV's own `miles`):
 *   'band'    the candidates the card's own miles by road kept (bandPick)
 *   'area'    the door's candidates, one general area (withArea)
 *   'street'  the street alone, its points one area (streetArea)
 *
 * FIX-LESS CARDS. Older cards carry no fix, so no disc. A printed door with
 * its town or ZIP after a comma is searched in the driver's own REGION
 * instead (regionOf: the bounding box of every good card fix in the record,
 * REGION_MARGIN_MI wider each way, as a disc round its middle reaching its
 * corners), through the same chain, and kept only at door or corner level
 * and only where an answer at the pin carries the printed town or ZIP: a
 * house number on a street of that name is not one place across a metro, but
 * in its own town it is. A store NAME with no fix stays unplaced — a chain is
 * everywhere, and which branch is a guess. No band (it measures from the
 * fix) and no area (a region is no card's reach) without a fix. */
var REGION_MARGIN_MI = 5;
// The band asks for its roads with the run's patience, not the panel's: an
// offline run can wait, and a band given up is the refusal as it was.
var BAND_WAIT_OFFLINE_MS = 30000;
// The level a placement is at, and whether it is a point.
var POINT_LEVELS = ['door', 'corner', 'name'];
var APPROX_LEVELS = ['band', 'area', 'street'];

/* The printed town or ZIP of an address text, as the card printed it after a
 * comma (map-view.js townOf, the rule the towns table reads), or null. */
function printedTown(text) {
  var s = String(text || '');
  var zip = /,[^,]*?\b(\d{5})(?:-\d{4})?\b/.exec(s);
  var town = MV.townOf(s, A.area);
  return town || (zip ? zip[1] : null) ? { town: town || null, zip: zip ? zip[1] : null } : null;
}

/* The driver's region off the record's own good card fixes (MV.cardFix):
 * their bounding box, REGION_MARGIN_MI wider on each side, and the disc
 * round its middle that reaches its corners. Null with no fix at all. */
function regionOf(offers) {
  var s = Infinity, n = -Infinity, w = Infinity, e = -Infinity, k = 0;
  (offers || []).forEach(function (o) {
    var f = o && MV.cardFix(o).at;
    if (!f) return;
    k += 1;
    s = Math.min(s, f.lat); n = Math.max(n, f.lat); w = Math.min(w, f.lon); e = Math.max(e, f.lon);
  });
  if (!k) return null;
  var dLat = REGION_MARGIN_MI / 69.0;
  var mid = (s + n) / 2;
  var dLon = REGION_MARGIN_MI / (69.0 * Math.max(0.2, Math.cos(mid * Math.PI / 180)));
  var box = { s: round5(s - dLat), n: round5(n + dLat), w: round5(w - dLon), e: round5(e + dLon) };
  var at = { lat: round5((box.s + box.n) / 2), lon: round5((box.w + box.e) / 2) };
  var miles = MV.crowMiles(at, { lat: box.n, lon: box.e });
  return { box: box, fixes: k, marginMi: REGION_MARGIN_MI,
           disc: { at: at, miles: Math.round(miles * 100) / 100, card: null, corrected: false, region: true } };
}

// An answer's hit list says the printed town (or ZIP) near `at`.
function townAt(res, at, said) {
  var hits = res && res.seen && Array.isArray(res.seen.hits) ? res.seen.hits : [];
  return hits.some(function (h) {
    if (MV.crowMiles(h, at) > PLACE_SAME_MI) return false;
    var nm = String(h.name || '').toLowerCase();
    return (said.town && nm.indexOf(said.town.toLowerCase()) >= 0) || (said.zip && nm.indexOf(said.zip) >= 0);
  });
}

/* The words a refusal is counted under in the Coverage tab and the summary:
 * the rig's for the search's own four (MV.refusalWords with `count`, so a
 * 'none' is "no such door in the reach's box" or "door found past the reach"
 * by what the bounded box held, one label each and no miles; a store asked by
 * its name alone, `byName`), WHY's for the rest — "several places answer (a
 * chain, or branches)" is the report's own, and says more here than the
 * rig's "several answers". `res` is the search's answer, `why` the key kept. */
var RIG_WORDED = ['none', 'noplace', 'nodoor', 'together'];
function wordsOf(res, why, kind) {
  if (RIG_WORDED.indexOf(why) >= 0) {
    var r = res && res.why === why ? res : { why: why };
    var w = MV.refusalWords(r, { count: true, byName: kind === 'name' });
    if (w) return w;
  }
  return WHY[why] || why;
}

function placedAt(at, kind, level, spread, extra) {
  return Object.assign({ at: { lat: at.lat, lon: at.lon }, why: null, kind: kind, level: level,
                         spread: spread ? Math.round(spread * 100) / 100 : 0 }, extra || {});
}

/* One pickup, placed or refused: { at, why, kind, level, spread }. `nbx` is
 * an NbxSearch; `streets` whether the street index answers; `ctx`
 * { region (regionOf), road (the router answers), budget ({left}, road
 * questions) }. Without `ctx` or `streets` it is the first pass's rule. */
async function placePickup(nbx, text, card, streets, ctx) {
  ctx = ctx || {};
  var k = pickupKind(text);
  if (k.kind === 'none') return { at: null, why: 'notext', kind: k.kind };
  if (k.kind === 'street' && !streets) return { at: null, why: 'street', kind: k.kind };
  if (k.kind === 'cross' && !streets) return { at: null, why: 'cross', kind: k.kind };
  var disc = MV.discFor(card || null), region = false;
  if (!disc) {
    var said = k.kind === 'door' ? printedTown(text) : null;
    if (!said || !ctx.region) return { at: null, why: k.kind === 'door' ? 'nofixdoor' : 'nofix', kind: k.kind };
    disc = ctx.region.disc;
    region = said;
  }
  var res;
  try {
    if (k.kind === 'name') res = await nbx.placeSearch(k.plan.q, disc);
    else if (k.kind === 'street') {
      // The street index's `whole` for the street as printed (NbxSearch.
      // streetArea asks it for a door plan's street; a numberless street IS
      // its street), its points one area by MV.streetArea's rule.
      var body = await nbx.get('/whole?name=' + encodeURIComponent(k.plan.street) + '&box='
                               + encodeURIComponent(MV.discBox(disc)));
      var a = body && !body.unreachable && !body.refused ? MV.streetArea(body, disc) : null;
      return a ? placedAt(a, k.kind, 'street', a.miles) : { at: null, why: 'street', kind: k.kind };
    } else {
      // ...a printed door with its store's name beside it (`ctx.store`,
      // placeRow's), for the street printed short: the index's /tail, the
      // door by the one full name, else the store by its name along that
      // street (NbxSearch.place `store`, MV.pickStoreAlong) — the rig's own
      // order (server.js pickupTail), and only after the door refused.
      res = await nbx.place(text, disc, { streets: !!streets,
                                          store: k.kind === 'door' && ctx.store ? ctx.store : null });
    }
  } catch (e) {
    return { at: null, why: 'refused', kind: k.kind };
  }
  if (res && res.at) {
    if (region && !townAt(res, res.at, region)) return { at: null, why: 'regiontown', kind: k.kind };
    // (A store found by its name along its street is a place by its name,
    // not its door: 'name' level, a point all the same.)
    return placedAt(res.at, k.kind, k.kind === 'name' || res.by === 'store' ? 'name'
                    : k.kind === 'cross' ? 'corner' : 'door', 0,
                    region ? { region: true } : null);
  }
  var why = res && res.why;
  why = WHY[why] ? why : 'none';
  var said = wordsOf(res, why, k.kind);
  if (region || k.kind !== 'door') return { at: null, why: why, said: said, kind: k.kind };
  // The door refused: the band first (it narrows; an area it found is tighter
  // than the one it was chosen from), else the area beside the refusal.
  if (ctx.road) {
    var spec = MV.bandTarget(card, 'pickup');
    var band = spec ? await nbx.band(text, res, disc, spec, null, ctx.budget || null, !!streets) : null;
    if (band) {
      return placedAt(band, k.kind, 'band', band.miles, { refused: why, refusedSaid: said, cardMi: band.cardMi });
    }
  }
  if (res && res.area) {
    return placedAt(res.area, k.kind, res.area.rough ? 'street' : 'area', res.area.miles,
                    { refused: why, refusedSaid: said });
  }
  return { at: null, why: why, said: said, kind: k.kind };
}

/* --- a DoorDash pickup by the door its card printed, before its name -------
 *
 * THE FAULT (AUDITS.md, Done, "Four refusals were one label", and the Open
 * entry of 7 Nov it came from, (4)). A DoorDash stops card prints the store's
 * NAME (`pickup`, "Utopian Bowl Kitchen") and under it the store's DOOR
 * (`pickupLine`, "164 Ash Row, Faketown"; with two stores or more every one
 * is listed, `stores` [{name, door}], the parser's `places`/`placeDoors`).
 * The rig searches the printed door — server.js searchCardEarly asks
 * `pickupLine` first for an offer, pickupAsks for a held order, door level in
 * the card's disc, the store's name beside it for pickupTail — and asks a
 * store by its bare name only when no door is on record at all. This report
 * read `row.pickup` alone. So every DoorDash pickup was asked as a NAME, and
 * MV.pickPlace pins a name only where OSM holds a feature with the same words
 * (placeNamed, one slip) and only one inside the disc — and a one-leg DoorDash
 * card ('shape', 528 of the real week's 1,166 offers) sets no radius, so its
 * disc is the sixty-mile default, where a chain's name is every branch. The
 * printed door, which pins at door level wherever the NucBox holds its
 * number, was never asked.
 *
 * So, in the rig's order: the row's printed door (printedDoor) through
 * placePickup — door level inside the card's disc, the retries, and the
 * store's name beside it for MV.pickStoreAlong ONLY after the door refused
 * (`ctx.store`) — and a POINT from it is kept: 'door', or 'name' for the
 * store along its street. No point: the store's name as this report always
 * asked it (pickPlace: one place of that name in the disc, the justified
 * exact place the rig's held pickup by name takes), so nothing placed before
 * is lost; and with neither, the door's approximate area or band, or the
 * DOOR's refusal, which is what is counted (the rig's rule: the door's
 * refusal stands). The band is asked only then, so its road questions are
 * not spent on a pickup the name places. `asked` says which text placed it
 * ('door' or 'name'). A row with no printed door is placed as before. */
function printedDoor(row) {
  if (!row || typeof row.pickup !== 'string' || !row.pickup.trim()) return null;
  var door = typeof row.pickupLine === 'string' && row.pickupLine.trim() ? row.pickupLine.trim() : null;
  if (!door) {
    // ...else the door the card listed beside the store this row names:
    // `stores` (the offer line's, server.js storesOf), or the parser's two
    // lists side by side. The FIRST store's is `pickupLine` itself.
    var list = Array.isArray(row.stores) ? row.stores
      : Array.isArray(row.places) && Array.isArray(row.placeDoors) && row.places.length === row.placeDoors.length
        ? row.places.map(function (n, i) { return { name: n, door: row.placeDoors[i] }; }) : [];
    for (var i = 0; i < list.length; i++) {
      var st = list[i];
      if (st && typeof st.name === 'string' && typeof st.door === 'string' && st.door.trim()
          && AS.sameStore(st.name, row.pickup)) { door = st.door.trim(); break; }
    }
  }
  if (!door || door === row.pickup.trim()) return null;
  return pickupKind(door).kind === 'door' ? door : null;
}

async function placeRow(nbx, row, streets, ctx) {
  ctx = ctx || {};
  var door = printedDoor(row);
  if (!door) return placePickup(nbx, row.pickup, row, streets, ctx);
  var first = await placePickup(nbx, door, row, streets, Object.assign({}, ctx, { road: false, store: row.pickup }));
  if (first.at && isPoint(first)) return Object.assign(first, { asked: 'door' });
  if (pickupKind(row.pickup).kind === 'name') {
    var byName = await placePickup(nbx, row.pickup, row, streets, ctx);
    if (byName.at) return Object.assign(byName, { asked: 'name', doorWhy: first.at ? first.refused : first.why });
  }
  var last = ctx.road ? await placePickup(nbx, door, row, streets, Object.assign({}, ctx, { store: row.pickup }))
    : first;
  return Object.assign(last, { asked: 'door' });
}

/* A taken order's dropoff, placed to be COUNTED by area and nothing else:
 * by the same chain (no band: it measures from the placed pickup), kept at
 * any level whose spread is a 2-mile cell's to tell (AREA_MI). */
async function placeDropoff(nbx, text, card, streets, ctx) {
  var k = pickupKind(text);
  if (k.kind !== 'door' && !(k.kind === 'cross' && streets)) return null;
  var r = await placePickup(nbx, text, card, streets, { region: ctx && ctx.region });
  return r && r.at && !(r.spread > MV.AREA_MI) ? { lat: r.at.lat, lon: r.at.lon } : null;
}

/* --- a card read with an order in the car, searched from that order's end --
 *
 * THE FAULT (AUDITS.md, the Open entry of 7 Nov, (5)): the one real reach
 * miss. An offer shown while another order is held may print miles that
 * start at THAT order's end, not at the car (the owner's 29 Oct shift, #6:
 * 4.3 mi from #5's door). The rig gives a held order taken beside another
 * the `also` circles that cure it (MV.afterParts, round each such end the
 * card's miles and SLACK_MI and the end's own `widen`), and since 9 Nov an
 * offer read while orders are held the same (server.js offerCard). This
 * report's rows carry no `after`, so a stacked offer was searched from the
 * car alone: 10,000 invented stacked offers, 15.1% of their stores outside
 * the disc, most of those "no such door in the reach's box" because the
 * bounded box never reached them.
 *
 * So the report rebuilds `after` the rig's way, from the record: every order
 * TAKEN (the journal's `taken`, takenRuns) whose Took was before the card was
 * first seen and which was not yet put down then, the card's own order
 * aside — its end as one anchor (MV.endAnchor's shape, {lat, lon, widen,
 * from}), at most MV.AFTER_MAX. The anchor is where the order ENDED:
 *
 *   - the GPS at its drop, for an order the GPS or the app's screen put down
 *     at the door (or a press the GPS log timed, a finish the GPS made):
 *     `widen` AFTER_GPS_WIDEN_MI, from 'gps' — the car at the door, give or
 *     take the gate's error and where it stopped (CHOSEN, NOT MEASURED: the
 *     rig's AGREE_MI, its "one place" for two pins); an untimed Drop press is
 *     no position, as timePresses says;
 *   - else its dropoff placed by the same chain as a pickup (placePickup in
 *     its own card's disc): a door or a corner `widen` 0 ('pin'), an area
 *     its spread when that is a general area (MV.AREA_MI or less: 'area'),
 *     exactly the rig's endAnchor over an end pin or an end area.
 *
 * An order with neither gives no circle (MV.endAnchor says why not a disc).
 * A pin still needs door level, or one place of that name, INSIDE the union
 * of circles — the circles widen where a door may be, never what a pin
 * needs. Customers' doors: placed only to anchor, never written anywhere
 * (the answer cache aside, as for every dropoff). */
var AFTER_GPS_WIDEN_MI = MV.AGREE_MI;
var GPS_ANCHOR_BY = ['gps', 'screen', GPS_TIMED].concat(FINISHED);

/* Each taken order's end as an anchor: [{id, tookAt, endedAt, anchor}],
 * anchor null where neither the GPS nor its dropoff gives one. `gpsPos` is
 * main's, keyed id@endedAt. */
async function heldEndsOf(nbx, taken, byId, gpsPos, streets, region) {
  var out = [];
  for (var i = 0; i < (taken || []).length; i++) {
    var t = taken[i];
    if (!t || typeof t.tookAt !== 'number' || typeof t.endedAt !== 'number' || !(t.endedAt > t.tookAt)) continue;
    var anchor = null;
    var g = gpsPos && gpsPos[t.id + '@' + t.endedAt];
    if (g && GPS_ANCHOR_BY.indexOf(t.by || 'drop') >= 0) {
      anchor = { lat: g.lat, lon: g.lon, widen: AFTER_GPS_WIDEN_MI, from: 'gps' };
    } else if (byId[t.id] && typeof byId[t.id].dropoff === 'string') {
      var row = byId[t.id];
      var r = await placePickup(nbx, row.dropoff, row, streets, { region: region });
      if (r && r.at) {
        anchor = MV.endAnchor(isPoint(r) ? { pin: r.at }
          : gridOk(r) ? { area: { lat: r.at.lat, lon: r.at.lon, miles: r.spread } } : null);
      }
    }
    out.push({ id: t.id, tookAt: t.tookAt, endedAt: t.endedAt, anchor: anchor });
  }
  return out;
}

/* The `after` a row's card gets: the anchors of the orders in the car when it
 * was first seen (seenAt), its own order aside, the earliest-taken first,
 * at most MV.AFTER_MAX. [] when none was held, so its disc is as before. */
function afterFor(row, held) {
  var when = row ? seenAt(row) : null;
  if (typeof when !== 'number' || !isFinite(when)) return [];
  return (held || []).filter(function (h) {
    return h.anchor && h.id !== row.id && h.tookAt < when && when < h.endedAt;
  }).sort(function (a, b) { return a.tookAt - b.tookAt; }).slice(0, MV.AFTER_MAX).map(function (h) {
    return Object.assign({ of: h.id }, h.anchor);
  });
}

/* PLACES TAKE A POINT, AND AN AREA ONLY WHERE IT IS ONE STORE'S. A place is
 * a store at a location, and an area is not a location: so an approximate
 * placement joins Places only (a) within PLACE_SAME_MI (AGREE_MI) of a point
 * placement of the same store name — the area agrees with a door or name
 * already found for that store, and is that place — or (b) where its own
 * spread is PLACE_APPROX_MI or less, a few blocks, the size of one shopping
 * centre. 0.3 mi is CHOSEN, NOT MEASURED: AGREE_MI (0.2) is the rig's "one
 * place" for two pins, and a spread is the two FARTHEST candidates, so its
 * middle is within half of it of either — 0.15 mi, inside AGREE_MI. The
 * 2-mile grid takes every level whose spread is AREA_MI or less (a mile:
 * the rig's own general area, half a cell). Towns read the card's text and
 * are unchanged. */
var PLACE_APPROX_MI = 0.3;
function isPoint(r) { return !!(r && r.at && (!r.level || POINT_LEVELS.indexOf(r.level) >= 0)); }
function gridOk(r) { return !!(r && r.at && !(r.spread > MV.AREA_MI)); }

// The store a pickup names, as printed: Uber's bracketed street off the end,
// or for a printed door (a DoorDash stops line) the line before its comma.
function storeLabel(text) {
  var s = AS.storeOf(String(text || '')).replace(/\s+/g, ' ').trim();
  if (/^\d/.test(s)) s = s.split(',')[0].trim();
  return s || String(text || '').trim();
}

/* Pins grouped into places: one store (Assemble.storeKey of its label) at one
 * location (within PLACE_SAME_MI of the place's first pin). Returns
 * { byRow: {rowIndex: placeId}, places: {id: {label, lat, lon, pins}} }. */
function placesOf(placed) {
  var byKey = Object.create(null), places = Object.create(null), byRow = Object.create(null);
  // Points first, so an area can find the door or name it agrees with
  // (PLACE_APPROX_MI above); a pin with no `level` is a point, as before.
  var points = placed.filter(function (p) { return isPoint(p); });
  var areas = placed.filter(function (p) { return !isPoint(p); });
  points.concat(areas).forEach(function (p) {
    var key = AS.storeKey(p.label) || p.label.toLowerCase();
    var list = byKey[key] || (byKey[key] = []);
    var hit = null;
    for (var i = 0; i < list.length; i++) {
      if (MV.crowMiles(list[i].first, p.at) <= PLACE_SAME_MI
          && (isPoint(p) || list[i].point || p.spread <= PLACE_APPROX_MI)) { hit = list[i]; break; }
    }
    if (!hit && !isPoint(p) && !(p.spread <= PLACE_APPROX_MI)) return;
    if (!hit) {
      hit = { id: key + '#' + (list.length + 1), first: p.at, pins: [], labels: {}, point: isPoint(p) };
      list.push(hit);
    }
    hit.pins.push(p.at);
    hit.labels[p.label] = (hit.labels[p.label] || 0) + 1;
    byRow[p.row] = hit.id;
  });
  Object.keys(byKey).forEach(function (k) {
    byKey[k].forEach(function (h) {
      var mid = MV.middleOf(h.pins);
      var label = Object.keys(h.labels).sort(function (a, b) {
        return h.labels[b] - h.labels[a] || (a < b ? -1 : 1);
      })[0];
      places[h.id] = { label: label, lat: round5(mid.lat), lon: round5(mid.lon), pins: h.pins.length };
    });
  });
  return { byRow: byRow, places: places };
}

module.exports = {
  pickupKind: pickupKind, WHY: WHY, REGION_MARGIN_MI: REGION_MARGIN_MI,
  BAND_WAIT_OFFLINE_MS: BAND_WAIT_OFFLINE_MS, POINT_LEVELS: POINT_LEVELS, APPROX_LEVELS: APPROX_LEVELS,
  printedTown: printedTown, regionOf: regionOf, wordsOf: wordsOf, placePickup: placePickup,
  printedDoor: printedDoor, placeRow: placeRow, placeDropoff: placeDropoff,
  AFTER_GPS_WIDEN_MI: AFTER_GPS_WIDEN_MI, heldEndsOf: heldEndsOf, afterFor: afterFor,
  PLACE_APPROX_MI: PLACE_APPROX_MI, isPoint: isPoint, gridOk: gridOk, storeLabel: storeLabel,
  placesOf: placesOf,
};
