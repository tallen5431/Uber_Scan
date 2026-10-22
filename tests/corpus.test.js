/* Runs the shared corpus against the JavaScript parser, so it and the Python
   port on the Pi stay in agreement. Run with: node tests/corpus.test.js */
var P = require('../offer-parser.js');
var cases = require('./fixtures/cases.json');

var ok = 0, bad = 0;
function eq(name, got, want) {
  var good = (typeof want === 'number' && typeof got === 'number')
    ? Math.abs(got - want) < 0.001 : got === want;
  if (good) ok++; else { bad++; console.log('FAIL  ' + name + ': got ' + got + ' want ' + want); }
}

cases.parse.forEach(function (c) {
  var p = P.parse(c.text);
  Object.keys(c.expect).forEach(function (k) { eq(c.name + ' / ' + k, p[k], c.expect[k]); });
});

cases.rate.forEach(function (c) {
  var r = P.rate(P.parse(c.text), c.settings);
  Object.keys(c.expect).forEach(function (k) {
    var got = r[k];
    if (/PerHour$/i.test(k) && typeof got === 'number') got = Math.round(got * 100) / 100;
    eq(c.name + ' / ' + k, got, c.expect[k]);
  });
});

/* The three functions that decide what an offer is judged against.
   All three had drifted, and none of it was reachable from a test. */
function value(v) {
  if (v === '@inf') return Infinity;
  if (v === '@-inf') return -Infinity;
  if (v === '@nan') return NaN;
  return v;
}

(cases.coerce ? cases.coerce.toNumber : []).forEach(function (c) {
  eq('toNumber / ' + c.name, P.toNumber(value(c.in)), c.expect);
});

(cases.coerce ? cases.coerce.setting : []).forEach(function (c) {
  eq('setting / ' + c.name, P.setting(value(c.in), c.fallback), c.expect);
});

(cases.coerce && cases.coerce.round2 ? cases.coerce.round2 : []).forEach(function (c) {
  // P.round2, not the expression again: written out here it was a third
  // copy of a rule offer-parser.js had two of, and changing either of
  // those left these nine cases passing.
  eq('round2 / ' + c.name, P.round2(value(c.in)), c.expect);
});

(cases.coerce ? cases.coerce.doubt : []).forEach(function (c) {
  eq('doubt / ' + c.name,
     P.doubt(value(c.pay), value(c.minutes), value(c.miles)), c.expect);
});

/* Where an offer went, and the delivery deadline that stands in for a duration.
   Both are new shapes the reader had to learn from real DoorDash cards, and both
   are the kind of thing that drifts silently between two implementations. */
function sameList(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

(cases.places || []).forEach(function (c) {
  var got = P.parse(c.text).places;
  if (sameList(got, c.expect)) ok++;
  else { bad++; console.log('FAIL  places / ' + c.name + ': got ' + JSON.stringify(got)
                            + ' want ' + JSON.stringify(c.expect)); }
});

/* The address off the screen after the accept. [line, city, zip] rather than
   field by field: those three are what the rest of the rig consumes - `line` is
   shown and stored, `city` and `zip` are what the geography is decided on. */
(cases.address || []).forEach(function (c) {
  var a = P.findAddress(c.text);
  var got = a ? [a.line, a.city, a.zip] : null;
  var same = (got === null && c.expect === null) ||
             (got !== null && c.expect !== null && sameList(got, c.expect));
  if (same) ok++;
  else { bad++; console.log('FAIL  address / ' + c.name + ': got '
                            + JSON.stringify(got) + ' want '
                            + JSON.stringify(c.expect)); }
});

/* The stops on Uber's Trip Planner, every field of every stop in one fixed
   order. A key findPlanner leaves out is '<missing>', not null - null is an
   expected value here, "this field did not read". rpi/test_parser.py runs the
   same cases in the same order. */
var PLANNER_KEYS = ['kind', 'orders', 'name', 'expectedBy', 'street', 'city',
                    'state', 'zip', 'line', 'place'];
/* ...and `partial` last, absent rather than null on a stop the page shows
   whole, so compared as absent-is-null: see _stops in rpi/test_parser.py. */
function stopFields(stops) {
  return stops === null ? null : stops.map(function (s) {
    return PLANNER_KEYS.map(function (k) {
      return Object.prototype.hasOwnProperty.call(s, k) ? s[k] : '<missing>';
    }).concat([s.partial === undefined ? null : s.partial]);
  });
}
(cases.planner || []).forEach(function (c) {
  var got = JSON.stringify(stopFields(P.findPlanner(c.text)));
  var want = JSON.stringify(stopFields(c.expect));
  if (got === want) ok++;
  else { bad++; console.log('FAIL  planner / ' + c.name + ': got ' + got + ' want ' + want); }
  /* ...and whether both ends of the list are on the screen. Every case says;
     one that does not compares against undefined and fails. */
  var ends = P.plannerBounded(c.text);
  if (ends === c.bounded) ok++;
  else { bad++; console.log('FAIL  planner ends / ' + c.name + ': got ' + ends + ' want ' + c.bounded); }
  /* ...and, where a case says, whether a Pickup header opens the read with
     the foot under it (plannerFramed; the owner's planner of 21 Oct). */
  if (c.framed !== undefined) {
    var framed = P.plannerFramed(c.text);
    if (framed === c.framed) ok++;
    else { bad++; console.log('FAIL  planner framed / ' + c.name + ': got ' + framed + ' want ' + c.framed); }
  }
  /* ...and whether it is the trip's last block, its header cropped off, the
     foot straight under it (plannerFoot; the owner's read of 21 Oct, 15:00). */
  if (c.footed !== undefined) {
    var footed = P.plannerFoot(c.text);
    if (footed === c.footed) ok++;
    else { bad++; console.log('FAIL  planner foot / ' + c.name + ': got ' + footed + ' want ' + c.footed); }
  }
});

/* What screen a reading is, for a sighting: app and screen as one pair. The
   same cases rpi/test_parser.py runs. See screen_type in offer_parser.py. */
(cases.screens || []).forEach(function (c) {
  var s = P.screenType(c.text);
  eq('screens / ' + c.name, JSON.stringify([s.app, s.screen]),
     JSON.stringify([c.expect.app, c.expect.screen]));
});

/* The delivery app's own screen from after a delivery: {app, screen, pay,
   name} or null. The same cases rpi/test_parser.py runs. See delivered_screen
   in offer_parser.py. */
(cases.delivered || []).forEach(function (c) {
  eq('delivered / ' + c.name, JSON.stringify(P.deliveredScreen(c.text)),
     JSON.stringify(c.expect));
});

/* Uber's opened navigation sheet: its address over "Dropoff type", with the
   customer's name above, or null. The same cases rpi/test_parser.py runs.
   See sheet_dropoff in offer_parser.py. */
(cases.sheets || []).forEach(function (c) {
  eq('sheets / ' + c.name, JSON.stringify(P.sheetDropoff(c.text)), JSON.stringify(c.expect));
});

/* DoorDash's place popup, opened from a stop on an offer card: its role, the
   store's name and the address, or null. The same cases rpi/test_parser.py
   runs. See place_popup in offer_parser.py. */
(cases.popups || []).forEach(function (c) {
  eq('popups / ' + c.name, JSON.stringify(P.placePopup(c.text)), JSON.stringify(c.expect));
});

/* The store's door off the line under its name on DoorDash's stops card, or
   null: the rule parse() takes `pickupLine` by. The same cases
   rpi/test_parser.py runs. See STORE_DOOR in offer_parser.py. */
(cases.doors || []).forEach(function (c) {
  eq('doors / ' + c.name, P.storeDoor(c.line), c.expect);
});

/* What a navigation or "Deliver to" screen gives as a destination nobody
   pressed for. `expect` is [screen, line, stop, under, asOffer]; this port has
   no address_stop, so it holds the screen, findAddress's line and the offer
   test (a payout or a place: the scanner's `an_offer`), and
   rpi/test_parser.py holds all five. */
(cases.navStops || []).forEach(function (c) {
  var p = P.parse(c.text);
  var a = P.findAddress(c.text);
  eq('navStops / ' + c.name,
     JSON.stringify([P.screenType(c.text).screen, a ? a.line : null,
                     p.pay !== null || p.places.length > 0]),
     JSON.stringify([c.expect[0], c.expect[1], c.expect[4]]));
});

(cases.whole || []).forEach(function (c) {
  var got = P.isWhole(P.parse(c.text));
  if (got === c.expect) ok++;
  else { bad++; console.log('FAIL  whole / ' + c.name + ': got ' + got
                            + ' want ' + c.expect); }
});

/* How much of the journey is the drive to the pickup. A pair rather than two
   sections, because the two halves are one claim: minutes without miles is a
   split that cannot be subtracted from a distance, and reporting them
   separately would let one port pass on half of it. */
(cases.toPickup || []).forEach(function (c) {
  var p = P.parse(c.text);
  var got = (p.toPickupMinutes === null || p.toPickupMinutes === undefined)
    ? null : [p.toPickupMinutes, p.toPickupMiles === undefined ? null : p.toPickupMiles];
  if (JSON.stringify(got) === JSON.stringify(c.expect)) ok++;
  else { bad++; console.log('FAIL  to pickup / ' + c.name + ': got '
                            + JSON.stringify(got) + ' want ' + JSON.stringify(c.expect)); }
});

/* Which end is which. A pair, because the two answers are one claim: a dropoff
   is only right relative to the pickup it is not. */
(cases.ends || []).forEach(function (c) {
  var pickup, dropoff;
  if (c.places) {
    /* `ends` beside `places` is the card's own layout travelling with the
       merged list, which is the shape the Pi's accumulator hands these two.
       Without it a case can only reach the rules that read the STRINGS, and
       the fault this section now pins is the list's ORDER being read as the
       journey's. See P.placeEnds. */
    pickup = P.findPickup(c.places, c.ends || null);
    dropoff = P.findDropoff(c.places, c.text || null, c.ends || null);
  } else {
    var p = P.parse(c.text);
    pickup = p.pickup;
    dropoff = p.dropoff;
  }
  var got = [pickup === undefined ? null : pickup,
             dropoff === undefined ? null : dropoff];
  if (JSON.stringify(got) === JSON.stringify(c.expect)) ok++;
  else { bad++; console.log('FAIL  ends / ' + c.name + ': got '
                            + JSON.stringify(got) + ' want ' + JSON.stringify(c.expect)); }
});

(cases.deadline || []).forEach(function (c) {
  eq('deadline / ' + c.name, P.parse(c.text).deliverBy, c.expect);
});

(cases.until || []).forEach(function (c) {
  eq('minutes left / ' + c.name, P.minutesUntil(c.deadline, c.now), c.expect);
});

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' shared-corpus checks passed (js)');
process.exit(bad ? 1 : 0);
