/* The assembler. Run with: node tests/assemble.test.js
 *
 * assemble.js decides where the order in the car ends: an address the scanner
 * read, a Trip Planner over one page or several, a lone dropoff on a
 * single-trip card. This suite drives it the way server.js does — a sighting
 * in, its candidates through Assemble.dropoff, the kept ones through
 * Assemble.file — over tests/fixtures/sequences.json, and then holds the
 * rules one at a time. A planner page in the fixtures is TEXT, made into the
 * sighting rpi/scan_pi.py's sighting() would send by offer-parser.js's own
 * findPlanner, plannerEnds, plannerTitled and screenType, so a page here is a
 * page the reader could produce. Every name and street is invented.
 */

var A = require('../assemble.js');
var OP = require('../offer-parser.js');
var SEQ = require('./fixtures/sequences.json').sequences;

var pass = 0, fail = 0;

function eq(name, got, want) {
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + g + ' want ' + w); }
}

function ok_(name, cond) { eq(name, !!cond, true); }

/* What rpi/scan_pi.py's sighting() sends for a whole-screen read of `text`. */
function pageOf(text, at, asked, app) {
  var stops = OP.findPlanner(text) || [];
  var kind = OP.screenType(text);
  return {
    at: at, asked: !!asked, whole: true, titled: OP.plannerTitled(text),
    laidOut: OP.plannerLaidOut(text), framed: OP.plannerFramed(text),
    footed: OP.plannerFoot(text),
    app: app || kind.app, screen: kind.screen, page: OP.plannerEnds(text),
    stops: stops.map(function (s) {
      return { kind: s.kind, orders: s.orders, name: s.name, place: s.place,
               expectedBy: s.expectedBy, street: s.street, city: s.city, state: s.state,
               zip: s.zip, line: s.line, partial: s.partial || null, label: s.kind };
    }),
    orderCount: null, keep: true
  };
}

function holdOf(seed, id) {
  var h = { id: id || 'o-held', acceptedAt: seed.acceptedAt, minutes: 30,
            dropoff: seed.dropoff || null, dropoffScanned: false,
            card: seed.card || null };
  if (seed.planner) h.planner = seed.planner;
  h.fields = A.cardFields({ dropoff: h.dropoff, pickup: null }, h.acceptedAt);
  return h;
}

/* One sequence, the way server.js runs one: returns the hold, the decisions
 * made (each said.why, or 'not a single trip' for a dropped lone dropoff), and
 * the reason each planner page's planner line would have carried. */
function play(seq) {
  var st = A.fresh();
  var hold = holdOf(seq.hold);
  A.took(st, hold);
  var decisions = [], unfiled = [];
  function arrive(d) {
    var said = A.dropoff(hold, d, null);
    if (said.drop) { decisions.push(said.why); return; }
    A.file(hold, d, said, st);
    decisions.push(said.why);
  }
  seq.events.forEach(function (e) {
    if (e.took) {
      hold = holdOf({ acceptedAt: e.t, dropoff: e.took.dropoff, card: e.took.card },
                    e.took.id);
      A.took(st, hold);
    } else if (e.dropoff) {
      arrive(Object.assign({ at: e.t }, e.dropoff));
    } else if (e.page || e.sighting) {
      var s = e.page ? pageOf(e.page, e.t, e.asked, e.app)
        : Object.assign({ at: e.t }, e.sighting);
      var r = A.sighting(st, hold, s, e.t);
      r.candidates.forEach(arrive);
      if (e.page) unfiled.push(A.verdictFor(st, e.t));
    }
  });
  return { hold: hold, decisions: decisions, unfiled: unfiled, st: st };
}

function brief(f) {
  return f ? { value: f.value, from: f.from } : null;
}

/* ---- the sequences ---- */
SEQ.forEach(function (seq) {
  var out = play(seq);
  var x = seq.expect;
  Object.keys(x.fields || {}).forEach(function (k) {
    eq(seq.name + ' — ' + k, brief(out.hold.fields[k]), x.fields[k]);
  });
  if (x.dropoffScanned !== undefined) {
    eq(seq.name + ' — dropoffScanned', out.hold.dropoffScanned, x.dropoffScanned);
  }
  if (x.fields && x.fields.dropoff !== undefined) {
    eq(seq.name + ' — the hold\'s own dropoff is the field\'s',
       out.hold.dropoff, x.fields.dropoff ? x.fields.dropoff.value : null);
  }
  if (x.pending) {
    eq(seq.name + ' — pending pool',
       A.pending(out.st).map(function (p) { return p.why; }), x.pending);
  }
  if (x.refused) {
    eq(seq.name + ' — refused', out.st.refused.map(function (r) { return r.why; }), x.refused);
  }
  if (x.decisions) eq(seq.name + ' — decisions', out.decisions, x.decisions);
  if (x.unfiled) eq(seq.name + ' — the planner line\'s reason', out.unfiled, x.unfiled);
});

/* ---- the same pages, read hot ----
 *
 * With the heat guard on, the scanner reads the screen unpressed no nearer
 * than SCREEN_AUTO_HOT apart (rpi/scan_pi.py, read off the file rather than
 * copied). Each sequence again, every unpressed page moved to at least that
 * long after the page before it (and everything after moved with it), must
 * end where it ends at its own pace: a planner over two pages files as it
 * does cool. At a STITCH_MS of 20 s, the five that stitch filed the card's
 * end instead. */
(function () {
  var src = require('fs').readFileSync(require('path').join(__dirname, '..', 'rpi',
                                                            'scan_pi.py'), 'utf8');
  var hotMs = Number((/^SCREEN_AUTO_HOT = ([\d.]+)/m.exec(src) || [])[1]) * 1000;
  ok_('(SCREEN_AUTO_HOT read off rpi/scan_pi.py: ' + hotMs + ' ms)', hotMs > 0);
  var stitched = 0;
  var moved = SEQ.filter(function (seq) {
    var last = null, shift = 0;
    var events = seq.events.map(function (e0) {
      var e = Object.assign({}, e0, { t: e0.t + shift });
      if (e.page && !e.asked && last !== null && e.t - last < hotMs) {
        shift += hotMs - (e.t - last);
        e.t = last + hotMs;
      }
      if (e.page) last = e.t;
      return e;
    });
    var cool = play(seq).hold.fields.dropoff;
    var hot = play(Object.assign({}, seq, { events: events })).hold.fields.dropoff;
    if (cool && cool.from === 'planner' && seq.events.filter(function (e) {
      return e.page;
    }).length > 1) stitched += 1;
    return JSON.stringify(brief(cool)) !== JSON.stringify(brief(hot));
  }).map(function (seq) { return seq.name; });
  eq('read at the heat guard\'s pace, a planner over two pages still files (' + stitched
     + ' sequences stitch cool)', moved, []);
})();

/* ---- precedence, one rule at a time ---- */
(function () {
  function f(from, value, conf, key) {
    return { value: value || 'x', from: from, conf: conf || 0, at: 1, screen: null, key: key };
  }
  ok_('a blank takes anything', A.outranks(f('seen'), null));
  ok_('a press replaces what another press said', A.outranks(f('press', 'b'), f('press', 'a')));
  ok_('...and a less complete press still replaces it: the button says what it read',
      A.outranks(f('press', 'b', 1), f('press', 'a', 3)));
  ok_('a label never replaces a press', !A.outranks(f('label'), f('press')));
  ok_('a planner never replaces a press', !A.outranks(f('planner'), f('press')));
  ok_('a label replaces what the card said', A.outranks(f('label'), f('card')));
  ok_('a planner replaces what the card said', A.outranks(f('planner'), f('card')));
  ok_('an unlabelled sighting does not replace what the card said',
      !A.outranks(f('seen'), f('card')));
  ok_('a second label does not replace the first', !A.outranks(f('label', 'b'), f('label', 'a')));
  ok_('a label does not replace a planner value', !A.outranks(f('label'), f('planner')));
  ok_('a fuller reading of the same planner stop replaces a thinner one',
      A.outranks(f('planner', 'b', 2, 'dropoff|Mara T.|1202'),
                 f('planner', 'a', 1, 'dropoff|Mara T.|1202')));
  ok_('...a less complete one of the same rank does not',
      !A.outranks(f('planner', 'b', 1, 'dropoff|Mara T.|1202'),
                  f('planner', 'a', 2, 'dropoff|Mara T.|1202')));
  ok_('...nor a fuller one of a different stop',
      !A.outranks(f('planner', 'b', 2, 'dropoff|Orrin B.|1220'),
                  f('planner', 'a', 1, 'dropoff|Mara T.|1202')));
  // 19 Oct night: "1106 Commor" filed first, "1106 Commons Ln" read later.
  ok_('a later reading of the same stop whose street names its type replaces one that does not',
      A.outranks(f('planner', '1106 Wren Commons Ln', 1, 'dropoff|Mara T.|1202'),
                 f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202')));
  ok_('...but not with another house number',
      !A.outranks(f('planner', '1160 Wren Commons Ln', 1, 'dropoff|Mara T.|1202'),
                  f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor of a different stop',
      !A.outranks(f('planner', '1106 Wren Commons Ln', 1, 'dropoff|Orrin B.|1220'),
                  f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor the garbled one back over the clean one',
      !A.outranks(f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202'),
                  f('planner', '1106 Wren Commons Ln', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor a typed street over another typed one',
      !A.outranks(f('planner', '1106 Wren Commons Ct', 1, 'dropoff|Mara T.|1202'),
                  f('planner', '1106 Wren Commons Ln NW', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor one untyped reading over another',
      !A.outranks(f('planner', '1106 Wren Commo', 1, 'dropoff|Mara T.|1202'),
                  f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor a bare type word with the street\'s name lost',
      !A.outranks(f('planner', '1106 Ln', 1, 'dropoff|Mara T.|1202'),
                  f('planner', '1106 Wren Commor', 1, 'dropoff|Mara T.|1202')));
  ok_('...nor a street with no house number',
      !A.outranks(f('planner', 'Wren Commons Ln', 1, 'dropoff|Mara T.|1202'),
                  f('planner', 'Wren Commor', 1, 'dropoff|Mara T.|1202')));
  eq('the ranks, highest first', Object.keys(A.RANK).sort(function (a, b) {
    return A.RANK[b] - A.RANK[a];
  }), ['press', 'label', 'nav', 'planner', 'popup', 'card', 'seen']);
  // A navigation destination files as a label does, and the driver's words
  // for it add the sighting and the same address read fuller.
  ok_('a navigation destination replaces what the card said', A.outranks(f('nav'), f('card')));
  ok_('...and an address no label proved', A.outranks(f('nav'), f('seen')));
  ok_('...never a press', !A.outranks(f('nav', '9 A St, Acworth, GA 30101', 3),
                                       f('press', '9 A St, Acworth', 2)));
  ok_('...never a different address an earlier screen read gave',
      !A.outranks(f('nav', '9 A St, Acworth, GA 30101', 3), f('label', '7 B St, Acworth', 2)));
  ok_('...but the same address read fuller, over a label',
      A.outranks(f('nav', '9 A St, Acworth, GA 30101', 3), f('label', '9 A St, Acworth', 2)));
  ok_('...or over a planner stop', A.outranks(f('nav', '9 A St, Acworth, GA 30101', 3),
                                              f('planner', '9 A St, Acworth', 2, 'dropoff|P.|1')));
  ok_('...and not the same address read no fuller',
      !A.outranks(f('nav', '9 A St, Acworth', 2), f('nav', '9 A St, Acworth, GA', 2)));
  ok_('a label never replaces a navigation destination', !A.outranks(f('label'), f('nav')));
  // The opened sheet loses a house number's first digits at the left of the
  // line: the number read whole afterwards is the same door read fuller.
  ok_('a navigation destination whose house number gains the digits a read lost '
      + 'replaces it', A.outranks(f('nav', '4416 Wren Dr NW, Kennesaw', 2),
                                  f('nav', '16 Wren Dr NW, Kennesaw', 2)));
  ok_('...never the other way', !A.outranks(f('nav', '16 Wren Dr NW, Kennesaw', 2),
                                            f('nav', '4416 Wren Dr NW, Kennesaw', 2)));
  ok_('...nor a number that does not end in the one filed',
      !A.outranks(f('nav', '4417 Wren Dr NW, Kennesaw', 2), f('nav', '16 Wren Dr NW, Kennesaw', 2)));
  ok_('...nor in another town', !A.outranks(f('nav', '4416 Wren Dr NW, Marietta', 2),
                                            f('nav', '16 Wren Dr NW, Kennesaw', 2)));
  ok_('...nor over a press', !A.outranks(f('nav', '4416 Wren Dr NW, Kennesaw', 2),
                                         f('press', '16 Wren Dr NW, Kennesaw', 2)));
})();

/* ---- a navigation screen, read whole without a press ----
 *
 * The sighting rpi/scan_pi.py's sighting() sends for a whole-screen read of a
 * screen that is not the planner: one stop, the frame's one address, typed by
 * the label in front of it. Streets invented. */
(function () {
  function navSight(at, line, more, stop) {
    var parts = line.split(', ');
    return Object.assign({
      at: at, asked: false, whole: true, titled: false, app: 'uber', screen: 'uber.nav',
      page: { top: null, bottom: null },
      stops: [Object.assign({ kind: 'dropoff', orders: null, name: null, place: null,
                              expectedBy: null, street: parts[0], city: parts[1] || null,
                              state: 'GA', zip: '30101', line: line, partial: null,
                              label: 'dropoff' }, stop || {})],
      orderCount: null, keep: true }, more || {});
  }
  function hold(extra) {
    var h = Object.assign({ id: 'o', acceptedAt: 1000, dropoff: 'Oak Dr & Elm Dr, Acworth',
                            dropoffScanned: false, card: { legs: 1, multiOrder: false } },
                          extra || {});
    A.fieldsOf(h);
    return h;
  }
  function run(h, s) {
    var st = A.fresh();
    var r = A.sighting(st, h, s, s.at);
    var said = r.candidates.map(function (c) {
      var d = A.dropoff(h, c, null);
      A.file(h, c, d, st);
      return [c.line, d.from, d.why];
    });
    return { said: said, refused: st.refused.map(function (x) { return x.why; }), st: st };
  }
  var LINE = '12 Wren Hollow Ct, Acworth, GA 30101';
  var h = hold();
  var got = run(h, navSight(5000, LINE));
  eq('a navigation screen\'s address under "Deliver to" is filed over the card\'s end, '
     + 'rank nav', [got.said, h.dropoff, h.fields.dropoff.from],
     [[[LINE, 'nav', 'over the card']], LINE, 'nav']);
  var bare = run(hold(), navSight(5000, LINE, null, { kind: null, label: null }));
  eq('...an unlabelled one is refused, and says so', [bare.said, bare.refused],
     [[], ['no label']]);
  eq('...one under a Pickup label is a pickup',
     run(hold(), navSight(5000, LINE, null, { kind: 'pickup', label: 'pickup' })).refused,
     ['a pickup']);
  eq('...a store\'s navigation files nothing, whatever label its address is under',
     run(hold(), navSight(5000, LINE, { screen: 'uber.pickupNav' })).refused,
     ['a pickup screen']);
  // The place the sheet printed for the stop rides onto the hold with its
  // end (the owner, 17 Oct: searched when the NucBox lacks the door).
  var hp = hold();
  run(hp, navSight(5000, LINE, null, { place: 'Wrenfield Parking Deck' }));
  eq('a navigation sheet\'s place goes onto the hold with the end it was printed for',
     [hp.dropoff, hp.dropoffPlace], [LINE, 'Wrenfield Parking Deck']);
  var pressed = { found: true, line: '9 Fable Ct, Acworth, GA 30101', street: '9 Fable Ct',
                  city: 'Acworth', state: 'GA', zip: '30101', asked: true, at: 6000 };
  A.file(hp, pressed, A.dropoff(hp, pressed, null));
  eq('...and an end filed after it with no place takes the old place away',
     [hp.dropoff, hp.dropoffPlace], ['9 Fable Ct, Acworth, GA 30101', undefined]);
  var withPlace = Object.assign({}, pressed, { place: '  Lantern Parking Deck ', at: 7000 });
  A.file(hp, withPlace, A.dropoff(hp, withPlace, null));
  eq('...while a press\'s dropoff line carries its own place, trimmed', hp.dropoffPlace,
     'Lantern Parking Deck');
  // ...and a Trip Planner's dropoff stop with a place line over its street
  // (the hotel layout), filed off the planner.
  var pstop = function (k, street, place, name) {
    return { kind: k, orders: 1, name: name, place: place, expectedBy: 1200, street: street,
             city: 'Acworth', state: 'GA', zip: null, line: street + ', Acworth, GA',
             partial: null, label: k };
  };
  var hpl = hold({ dropoff: null });
  var pst = A.fresh();
  A.took(pst, hpl);
  A.sighting(pst, hpl, { at: 5000, asked: false, whole: true, titled: true, laidOut: true,
                         app: 'uber', screen: 'uber.planner', page: { top: true, bottom: true },
                         stops: [pstop('pickup', '5 Mill St', null, 'Fable Grill'),
                                 pstop('dropoff', '1000 Quarry Rd NW', 'Wrenfield Parking Deck',
                                       'Lee M.')],
                         orderCount: null, keep: true }, 5000).candidates
    .forEach(function (c) { A.file(hpl, c, A.dropoff(hpl, c, null), pst); });
  eq('...and so does a Trip Planner dropoff stop\'s place',
     [hpl.dropoff, hpl.dropoffPlace], ['1000 Quarry Rd NW, Acworth, GA', 'Wrenfield Parking Deck']);
  eq('placeOf: a dropoff\'s place, or null for none, a blank or not a string',
     [A.placeOf({ place: 'Deck' }), A.placeOf({ place: '  ' }), A.placeOf({ place: 7 }),
      A.placeOf(null)], ['Deck', null, null, null]);
  eq('...one that is the held card\'s pickup is refused',
     run(hold({ pickup: '12 Wren Hollow Ct, Acworth' }), navSight(5000, LINE)).refused,
     ['a pickup']);
  var hp = hold();
  hp.fields.pickupAddr = { value: '12 Wren Hollow Ct, Acworth', from: 'planner', conf: 2 };
  eq('...and one that is the pickup a planner filed on it', run(hp, navSight(5000, LINE)).refused,
     ['a pickup']);
  // The card's own words for the store's door, which the hold now keeps
  // (server.js carries `pickupLine` at ✓ Took): DoorDash's printed door under
  // the store's name, and an Uber card's "Store (<n> <street>)".
  eq('...and one that is the store\'s door DoorDash printed under its name (pickupLine)',
     run(hold({ pickup: 'Example Diner', pickupLine: '12 Wren Hollow Ct, Acworth, GA 30101' }),
         navSight(5000, LINE)).refused, ['a pickup']);
  eq('...and one that is the door in an Uber card\'s "Store (<n> <street>)", closed or cut',
     [run(hold({ pickup: 'Example Diner (12 Wren Hollow Ct)' }), navSight(5000, LINE)).refused,
      run(hold({ pickup: 'Example Diner (12 Wren Hollow Ct' }), navSight(5000, LINE)).refused],
     [['a pickup'], ['a pickup']]);
  eq('...while a store\'s name, and a door on another street, are no pickup of it',
     [run(hold({ pickup: 'Example Diner' }), navSight(5000, LINE)).refused,
      run(hold({ pickup: 'Example Diner (14 Wren Hollow Ct)', pickupLine: '9 Fable Ct, Acworth' }),
          navSight(5000, LINE)).refused], [[], []]);
  eq('bracketDoor: the door in a store\'s bracket, closed or cut by the edge, trailing '
     + 'punctuation off; no number, no street word, no bracket or no string is none',
     [A.bracketDoor('Example Diner (12 Wren Hollow Ct.)'), A.bracketDoor("Culver's (1275 Hwy"),
      A.bracketDoor('Example Diner (Store 12)'), A.bracketDoor('Papa (12 A)'),
      A.bracketDoor('Example Diner'), A.bracketDoor(null)],
     ['12 Wren Hollow Ct', '1275 Hwy', null, null, null, null]);
  eq('...a read older than the Took is nothing, not a sighting that may fill a blank',
     run(hold({ dropoff: null }), navSight(500, LINE)).said, [[LINE, 'nav', 'before the Took']]);
  eq('...and with the order gone, nothing',
     A.dropoff(null, { line: LINE, asked: false, labelled: 'dropoff', nav: true, at: 5000 },
               { id: 'c', dropoff: null }).to, null);
  eq('a card-box read, a pressed read, or no order held makes no navigation destination',
     [A.sighting(A.fresh(), hold(), navSight(5000, LINE, { whole: false }), 5000).candidates,
      A.sighting(A.fresh(), hold(), navSight(5000, LINE, { asked: true }), 5000).candidates,
      A.sighting(A.fresh(), null, navSight(5000, LINE), 5000).candidates], [[], [], []]);
  var st = A.fresh(), h2 = hold();
  A.sighting(st, h2, navSight(5000, LINE), 5000);
  eq('...and one screen read every ten seconds is offered once per order in the car',
     A.sighting(st, h2, navSight(15000, LINE), 15000).candidates, []);

  // Two orders: the candidate carries what attribute() needs, and a store of
  // EITHER order is no destination.
  function order(id, at, more) {
    var o = Object.assign({ id: id, acceptedAt: at, tookAt: at + 5, minutes: 40,
                            app: 'uber', pickup: null, deliverBy: null, dropoff: null,
                            dropoffScanned: false }, more || {});
    A.fieldsOf(o);
    return o;
  }
  var a = order('a', 1000, { pickup: '40 Larkspur Way, Acworth' }), b = order('b', 2000);
  var c2 = A.sighting(A.fresh(), [a, b], navSight(9000, LINE, null, { expectedBy: 1205 }), 9000)
    .candidates;
  eq('two held: a navigation destination carries its app, time and read for the cues',
     c2.map(function (c) { return [c.line, c.app, c.expectedBy, c.at, c.asked]; }),
     [[LINE, 'uber', 1205, 9000, false]]);
  var s2 = A.fresh();
  A.sighting(s2, [a, b], navSight(9000, '40 Larkspur Way, Acworth, GA 30101'), 9000);
  eq('...and one that is either order\'s pickup is refused',
     s2.refused.map(function (x) { return x.why; }), ['a pickup']);
})();

/* ---- one hold: the server's old dropoff branch, rule by rule ---- */
(function () {
  function hold(dropoff, scanned, extra) {
    var h = Object.assign({ id: 'o', acceptedAt: 1000, dropoff: dropoff,
                            dropoffScanned: !!scanned, card: { legs: 1, multiOrder: false } },
                          extra || {});
    A.fieldsOf(h);
    return h;
  }
  function d(line, extra) {
    return Object.assign({ found: true, line: line, street: line.split(',')[0],
                           city: 'Acworth', state: 'GA', zip: '30101', at: 5000 }, extra);
  }
  var said = A.dropoff(hold('Oak Dr & Elm Dr, Acworth'), d('9 A St, Acworth', { asked: false }),
                       null);
  eq('an unlabelled sighting is not filed over the card\'s end', [said.to, said.kept], [null, false]);
  said = A.dropoff(hold(null), d('9 A St, Acworth', { asked: false }), null);
  eq('...while it fills a hold that names no end', [said.to, said.from], ['hold', 'seen']);
  said = A.dropoff(hold('Oak Dr & Elm Dr, Acworth'),
                   d('9 A St, Acworth', { asked: false, labelled: 'dropoff', at: 500 }), null);
  eq('a labelled read from before the Took is not label-proven', [said.labelled, said.to],
     [false, null]);
  said = A.dropoff(hold('Oak Dr & Elm Dr, Acworth', false, { card: { legs: 1 } }),
                   d('9 A St, Acworth', { asked: false, labelled: 'dropoff',
                                          singleCardOnly: true }), null);
  eq('a lone dropoff is dropped whole on a card that does not say it is one order',
     [said.drop, said.why], [true, 'not a single trip']);
  said = A.dropoff(null, d('9 A St, Acworth', { asked: false }), { id: 'c', dropoff: null });
  eq('with nothing held, an unprompted address fills the screened card\'s blank',
     [said.to, said.tally], ['card', false]);
  said = A.dropoff(null, d('9 A St, Acworth', { asked: false }),
                   { id: 'c', dropoff: 'Somewhere, Acworth' });
  eq('...and does not move an end the screened card named', said.to, null);
  said = A.dropoff(hold('x'), d('9 A St, Acworth', { asked: false }), null);
  eq('an unprompted address while an order is held is owed a tally row', said.tally, true);

  // Filing keeps the old fields in step, and says where it came from.
  var h = hold('Oak Dr & Elm Dr, Acworth');
  var line = d('9 A St, Acworth', { asked: false, labelled: 'dropoff' });
  said = A.dropoff(h, line, null);
  A.file(h, line, said);
  eq('a label-proven address files over the card, and the hold says so in both shapes',
     [h.dropoff, h.dropoffScanned, h.fields.dropoff.from, h.fields.dropoff.conf],
     ['9 A St, Acworth', true, 'label', 3]);

  // The card being screened keeps how its address was read, for the Took.
  var card = { id: 'c', dropoff: null };
  line = d('9 A St, Acworth', { asked: true });
  A.fileCard(card, line, A.dropoff(null, line, card));
  eq('a screened card keeps whether its address was pressed for',
     [card.dropoff, card.dropoffScanned, card.dropoffFrom], ['9 A St, Acworth', true, 'press']);
  eq('...and the hold made from it at Took starts from that provenance',
     brief(A.cardFields(card, 1).dropoff), { value: '9 A St, Acworth', from: 'press' });
  eq('a card with nothing read off the screen starts from the card',
     brief(A.cardFields({ dropoff: 'Oak Dr & Elm Dr, Acworth' }, 1).dropoff),
     { value: 'Oak Dr & Elm Dr, Acworth', from: 'card' });
})();

/* ---- a press at the restaurant: the store's screen is not the order's end ----
 *
 * The 17 Oct fault, in invented names: an Uber order held with the Trip
 * Planner's door as its end, ⌖ pressed at the restaurant over Uber's
 * navigation to the store (uber.pickupNav), and the press read the town line
 * alone and replaced the planner's door with "<Town>, GA 30066". */
(function () {
  var DOOR = '283 Quillon St NW, Smyrna';
  function hold(extra) {
    var h = Object.assign({ id: 'o', acceptedAt: 1000, pickup: 'Fable Grill',
                            dropoff: 'Customer dropoff', dropoffScanned: false,
                            card: { legs: 1, multiOrder: false } }, extra || {});
    A.fieldsOf(h);
    // The planner filed its door, unprompted, as on the shift.
    var pl = { found: true, line: DOOR, street: '283 Quillon St NW', city: 'Smyrna',
               state: 'GA', zip: null, asked: false, labelled: 'dropoff', planner: true,
               at: 2000 };
    A.file(h, pl, A.dropoff(h, pl, null));
    return h;
  }
  function press(line, screen, extra) {
    var parts = line.split(', ');
    return Object.assign({ found: true, line: line,
                           street: /^\d/.test(parts[0]) ? parts[0] : null,
                           city: /^\d/.test(parts[0]) ? parts[1] : parts[0], state: 'GA',
                           zip: '30066', asked: true, labelled: null, app: 'uber',
                           screen: screen, at: 5000 }, extra || {});
  }
  function ends(h) {
    return [h.dropoff, h.fields.dropoff && h.fields.dropoff.from];
  }
  var h = hold();
  eq('the premise: the held order\'s end is the planner\'s door', ends(h), [DOOR, 'planner']);
  var town = press('Smyrna, GA 30066', 'uber.pickupNav');
  var said = A.dropoff(h, town, null);
  A.file(h, town, said);
  eq('a press over Uber\'s navigation to the store is refused while an order is held, and the '
     + 'planner\'s door stays its end',
     [said.to, said.kept, said.asked, said.why, ends(h)],
     [null, false, true, 'a pickup screen', [DOOR, 'planner']]);
  var h2 = hold();
  var street = press('1150 Larch Pkwy, Smyrna, GA 30080', 'uber.pickupNav');
  said = A.dropoff(h2, street, null);
  eq('...whatever line it read off that screen, a door with a house number included',
     [said.to, said.why, ends(h2)], [null, 'a pickup screen', [DOOR, 'planner']]);
  // Nothing held: a press is about the card being screened — but not off
  // Uber's navigation to a store, which is nobody's end (the owner, 17 Oct:
  // that screen is drawn only for an order accepted, never for an offer).
  var card = { id: 'c', dropoff: 'Customer dropoff' };
  said = A.dropoff(null, town, card);
  A.fileCard(card, town, said);
  eq('with nothing held a press over the store\'s navigation is refused for the screened '
     + 'card too, and the card keeps its end',
     [said.to, said.kept, said.why, card.dropoff, card.dropoffFrom],
     [null, false, 'a pickup screen', 'Customer dropoff', undefined]);
  said = A.dropoff(null, town, null);
  eq('...and with no card either it is refused, by name', [said.to, said.why],
     [null, 'a pickup screen']);
  var card2 = { id: 'c2', dropoff: null };
  var custNav = press('61 Saddlebrook Ln, Smyrna, GA 30080', 'uber.nav');
  said = A.dropoff(null, custNav, card2);
  A.fileCard(card2, custNav, said);
  eq('...while a press over any other screen still files on the screened card',
     [said.to, said.why, card2.dropoff, card2.dropoffFrom],
     ['card', 'press', '61 Saddlebrook Ln, Smyrna, GA 30080', 'press']);
  eq('storeScreen: the store\'s navigation is a store\'s screen with nothing held, the held '
     + 'pickup\'s words are the hold\'s alone',
     [A.storeScreen(null, town), A.storeScreen(null, press('1150 Larch Pkwy, Smyrna, GA 30080',
                                                            'uber.nav'))],
     ['a pickup screen', null]);
  // The held order's pickup, by each word on record, off a screen that is not
  // the store's navigation.
  var STORE = '1150 Larch Pkwy, Smyrna';
  var hp = hold();
  hp.fields.pickupAddr = { value: STORE, from: 'planner', conf: 2, at: 2000, screen: null };
  said = A.dropoff(hp, press(STORE + ', GA 30080', 'uber.nav'), null);
  eq('a press whose line is the pickup a planner filed on the held order is refused',
     [said.to, said.why, ends(hp)], [null, 'a pickup', [DOOR, 'planner']]);
  var hs = hold({ planner: { stops: [{ kind: 'pickup', street: '1150 Larch Pkwy',
                                       line: STORE }] } });
  said = A.dropoff(hs, press(STORE + ', GA 30080', 'unknown'), null);
  eq('...and one whose line is one of its planner\'s pickups',
     [said.to, said.why, ends(hs)], [null, 'a pickup', [DOOR, 'planner']]);
  var hc = hold({ pickup: STORE });
  said = A.dropoff(hc, press(STORE + ', GA 30080', 'uber.nav'), null);
  eq('...and one whose line is the pickup its card printed',
     [said.to, said.why, ends(hc)], [null, 'a pickup', [DOOR, 'planner']]);
  // ...on every road a press takes to the hold: pressBetween's navigation cue
  // gives it to the order, and the order refuses it.
  var ht = hold();
  ht.tookAt = 1000;
  ht.app = 'uber';
  ht.fields.pickupAddr = { value: STORE, from: 'planner', conf: 2, at: 2000, screen: null };
  var onNav = press(STORE + ', GA 30080', 'uber.nav');
  var between = A.pressBetween(ht, { id: 'c-other', app: 'uber', dropoff: null }, onNav);
  said = A.dropoff(ht, onNav, { id: 'c-other', dropoff: null });
  eq('a press pressBetween gives the held order on its navigation cue is still refused '
     + 'when it reads the held pickup', [between && between.to, said.to, said.why, ends(ht)],
     ['hold', null, 'a pickup', [DOOR, 'planner']]);
  // The premise of all of it: an ordinary press still replaces anything.
  var hn = hold();
  var cust = press('61 Saddlebrook Ln, Smyrna, GA 30080', 'uber.nav');
  said = A.dropoff(hn, cust, null);
  A.file(hn, cust, said);
  eq('an ordinary press over the customer\'s navigation still replaces the planner\'s door',
     [said.to, said.why, ends(hn)],
     ['hold', 'press', ['61 Saddlebrook Ln, Smyrna, GA 30080', 'press']]);
  var hu = hold();
  said = A.dropoff(hu, press('61 Saddlebrook Ln, Smyrna, GA 30080', 'unknown'), null);
  eq('...and so does one off a screen nothing typed', [said.to, said.why], ['hold', 'press']);
})();

/* ---- the planner's one dropoff: moved from rpi/scan_pi.py, the same names ---- */
(function () {
  function stop(kind, street, city, line) {
    return { kind: kind, orders: 1, name: 'Pat Q.', expectedBy: 978, street: street || null,
             city: city || null, state: city ? 'GA' : null, zip: null, line: line || null };
  }
  var KESTREL = stop('dropoff', '4821 Kestrel Dr', 'Marietta', '4821 Kestrel Dr, Marietta');
  var BIRCH = stop('dropoff', '77 Birch Ln NW', 'Roswell', '77 Birch Ln NW, Roswell');
  var got = A.plannerDestination([stop('pickup'), KESTREL], true);
  eq('one dropoff whose street and town read, on a list seen whole, is the order\'s '
     + 'destination', [got.address && got.address.line, got.why],
     ['4821 Kestrel Dr, Marietta', null]);
  eq('...two dropoffs are not guessed between',
     A.plannerDestination([KESTREL, BIRCH], true).why, 'dropoffs');
  eq('...one dropoff on a list the rig could not see both ends of is not taken for '
     + 'the trip\'s only one', A.plannerDestination([stop('pickup'), KESTREL], false).why, 'list');
  eq('...a dropoff whose street did not read is not filed: a town alone is no address',
     A.plannerDestination([stop('dropoff', null, 'Marietta', 'Marietta')], true).why, 'address');
  eq('...and a planner of pickups gives no destination and has nothing to explain',
     [A.plannerDestination([stop('pickup', '310 Mill St', 'Roswell')], true).address,
      A.plannerDestination([stop('pickup', '310 Mill St', 'Roswell')], true).why], [null, null]);
  eq('...and a stop of no kind is not counted',
     A.plannerDestination([{ kind: null, partial: 'top', street: '1 A St', city: 'Acworth' },
                           KESTREL], true).why, null);
  eq('the lone dropoff is one order whose street and town read',
     A.plannerLoneDropoff([stop('pickup'), KESTREL]).line, '4821 Kestrel Dr, Marietta');
  eq('...and not one whose header says two orders',
     A.plannerLoneDropoff([Object.assign({}, KESTREL, { orders: 2 })]), null);
})();

/* ---- false stitches ---- */
(function () {
  var A1 = [{ kind: 'pickup', name: 'Juniper Taqueria', expectedBy: 1180, partial: 'bottom' }];
  var B1 = [{ kind: null, partial: 'top', expectedBy: null, street: '1 A St', city: 'Acworth' },
            { kind: 'dropoff', name: 'Mara T.', expectedBy: 1202, street: '2 B St',
              city: 'Acworth' }];
  eq('a header cut at the foot joins the block at the top of the next page',
     A.placements(A1, B1), [0]);
  eq('...not when the block\'s own time says it is another stop',
     A.placements(A1, [Object.assign({}, B1[0], { expectedBy: 1190 }), B1[1]]), []);
  eq('...and a whole stop with no key never anchors a page',
     A.placements([{ kind: 'dropoff', name: null, expectedBy: null, street: '1 A St' }],
                  [{ kind: 'dropoff', name: null, expectedBy: null, street: '1 A St' }]), []);
  eq('a stop key is its kind, name and time', A.keyOf(B1[1]), 'dropoff|Mara T.|1202');
  // Two orders for one customer at one time print two stops with one key, so
  // a page showing one of them fits under the other page in two places.
  var K = { kind: 'dropoff', name: 'Mara T.', expectedBy: 1202, street: '2 B St',
            city: 'Acworth' };
  var two = { at: 1000, app: 'uber', epoch: 0, top: true, bottom: false,
              stops: [K, Object.assign({}, K)] };
  var one = { at: 2000, app: 'uber', epoch: 0, top: false, bottom: true,
              stops: [Object.assign({}, K)] };
  eq('a page that fits in two places is not stitched at all',
     A.linked([two, one], one).pages.length, 1);
})();

/* ---- the pool across a hold's end ---- */
(function () {
  var st = A.fresh();
  var h = { id: 'o', acceptedAt: 1000, card: { legs: 1, multiOrder: true },
            dropoff: null, dropoffScanned: false };
  A.fieldsOf(h);
  A.sighting(st, h, pageOf('Trip Planner\nDropoff • 1 order\nMara T.\nExpected by 8:02 PM\n'
                           + 'Address\n415 Ostrander Way NW\nKennesaw, GA\nView details',
                           2000), 2000);
  eq('a page that cannot file yet waits in the pool', A.pending(st).length, 1);
  A.took(st, null);
  eq('...and is refused when the hold ends, saying so',
     [A.pending(st).length, st.refused.map(function (r) { return r.why; })],
     [0, ['the hold ended']]);
  eq('a card-box read is no page', A.sighting(st, h, Object.assign(
    pageOf('Dropoff • 1 order\nMara T.', 3000), { whole: false }), 3000).candidates, []);
})();

/* ---- two orders in the car: attribution (Stage 5) ----
 *
 * attribute() decides whose an address is from what the screen proves, and
 * nothing else; with no cue, or cues that disagree, nobody's. Stores, people
 * and streets invented. */
(function () {
  function order(id, at, more) {
    var o = Object.assign({ id: id, acceptedAt: at, tookAt: at + 5, holdId: id + '@' + at,
                            minutes: 40, app: 'uber', pickup: null, deliverBy: null,
                            dropoff: null, dropoffScanned: false }, more || {});
    A.fieldsOf(o);
    return o;
  }
  var a = order('a', 1000, { pickup: 'Wren Street Noodles', deliverBy: 1170 });
  var b = order('b', 5000, { pickup: 'Larkspur Tacos', deliverBy: 1205 });
  var d = function (more) {
    return Object.assign({ line: '12 Oak St, Marietta', at: 9000, app: 'uber' }, more || {});
  };
  var who = function (st, orders, x) {
    var r = A.attribute(st, orders, x);
    return [r.order ? r.order.id : null, r.cue, r.why];
  };
  var st = A.fresh();
  eq('two orders, no cue: nobody\'s', who(st, [a, b], d()), [null, null, 'no cue']);
  eq('the app is a hard rule: a DoorDash screen is not an Uber order\'s',
     who(st, [a, order('dd', 5000, { app: 'doordash' })], d({ app: 'doordash' })),
     ['dd', 'only', null]);
  eq('a read older than an order\'s Took is not that order\'s',
     who(st, [a, b], d({ at: 3000 })), ['a', 'only', null]);
  eq('...and older than both is nobody\'s', who(st, [a, b], d({ at: 500 })),
     [null, null, 'nobody']);
  // A list seen whole with more dropoffs than the hard rules leave orders: the
  // other dropoff may be the one order's too (a two-customer card), so the
  // hard rules alone file neither.
  var two = { bounded: true, others: ['30 Larch Way, Kennesaw'] };
  var dd = order('dd', 5000, { app: 'doordash' });
  eq('a two-dropoff list, one Uber order and a DoorDash order held: no `only`',
     who(st, [a, dd], d(two)), [null, null, 'no cue']);
  eq('...nor with a Took that landed during the read',
     who(st, [a, b], d(Object.assign({ at: 3000 }, two))), [null, null, 'no cue']);
  eq('...but a cue that names the one order left still decides',
     who(st, [a, dd], d(Object.assign({ expectedBy: 1171 }, two))), ['a', 'deadline', null]);
  eq('...and a list of one dropoff is that order\'s, as before',
     who(st, [a, dd], d({ bounded: true, others: [] })), ['a', 'only', null]);
  eq('the deadline cue: "Expected by" within 2 minutes of one card\'s "Deliver by"',
     who(st, [a, b], d({ expectedBy: 1207 })), ['b', 'deadline', null]);
  eq('...and not at 3 minutes', who(st, [a, b], d({ expectedBy: 1208 })),
     [null, null, 'no cue']);
  eq('...round midnight too',
     who(st, [order('m', 1000, { deliverBy: 1439 }), b], d({ expectedBy: 1 })),
     ['m', 'deadline', null]);
  eq('the name cue: the store against the card\'s pickup, normalised',
     who(st, [a, b], d({ store: 'oe Larkspur  TACOS – Roswell' })), ['b', 'name', null]);
  eq('...with one i/l slip', who(st, [a, b], d({ store: 'Wren Street Noodies' })),
     ['a', 'name', null]);
  eq('...one i/l slip, not a different letter',
     [A.sameStore('Wren Street Nood1es', 'Wren Street Noodles'),
      A.sameStore('Wren Street Noodies', 'Wren Street Noodles'),
      A.sameStore('Wren Street Noodiis', 'Wren Street Noodlls')], [false, true, false]);
  eq('a cue that fits both orders is no vote: a tie, which only the map may break',
     who(st, [a, order('b2', 5000, { pickup: 'Wren Street Noodles' })],
         d({ store: 'Wren Street Noodles' })), [null, null, 'tie']);
  eq('cues that disagree decide nothing',
     who(st, [a, b], d({ store: 'Wren Street Noodles', expectedBy: 1205 })),
     [null, null, 'cues disagree']);
  eq('cues that agree decide, under the first',
     who(st, [a, b], d({ store: 'Larkspur Tacos', expectedBy: 1205 })), ['b', 'name', null]);

  // Growth: a list seen whole after B's Took that is the list seen whole
  // before it plus one dropoff.
  var g = A.fresh();
  g.views = [{ app: 'uber', at: 3000, drops: ['dropoff|Mara T.|1170'] }];
  var grown = ['dropoff|Mara T.|1170', 'dropoff|Jules K.|1205'];
  eq('growth: the dropoff a list gained after the newer Took is the newer order\'s',
     who(g, [a, b], d({ key: 'dropoff|Jules K.|1205', listDrops: grown })),
     ['b', 'growth', null]);
  eq('...and the one it already had is the older\'s',
     who(g, [a, b], d({ key: 'dropoff|Mara T.|1170', listDrops: grown })),
     ['a', 'growth', null]);
  eq('...but not from a list that lost a stop it had (a misread key)',
     who(g, [a, b], d({ key: 'dropoff|Jules K.|1205',
                        listDrops: ['dropoff|Mara 7.|1170', 'dropoff|Jules K.|1205'] })),
     [null, null, 'no cue']);

  // Elimination: two same-app orders, a bounded list of two dropoffs, one
  // already filed as A's.
  var af = order('af', 1000);
  A.file(af, { line: '4821 Kestrel Dr, Marietta', street: '4821 Kestrel Dr',
               city: 'Marietta', at: 6000 },
         { to: 'hold', from: 'press' }, null);
  eq('elimination: the other dropoff on a list seen whole is the other order\'s',
     who(st, [af, b], d({ bounded: true, others: ['4821 Kestrel Dr, Marietta, GA'] })),
     ['b', 'elimination', null]);
  eq('...never off a list not seen whole',
     who(st, [af, b], d({ bounded: false, others: ['4821 Kestrel Dr, Marietta, GA'] })),
     [null, null, 'no cue']);
  eq('...nor off an end the CARD gave, which proves nothing',
     who(st, [order('ac', 1000, { dropoff: '4821 Kestrel Dr, Marietta' }), b],
         d({ bounded: true, others: ['4821 Kestrel Dr, Marietta'] })),
     [null, null, 'no cue']);

  // The pool: parked with no cue, filed when a cue comes, dropped when one of
  // its two orders leaves the car.
  var p = A.fresh();
  A.park(p, d({ line: '9 Elm Ct, Smyrna' }), [a, b]);
  A.park(p, d({ line: '3 Ash Way, Smyrna', expectedBy: null }), [a, b]);
  eq('an address no cue decides waits, counted', A.unowned(p), 2);
  eq('...and is never handed to the one order left when the other goes',
     [A.retryUnowned(p, [a]).length, A.unowned(p)], [0, 0]);
  A.park(p, d({ line: '9 Elm Ct, Smyrna', bounded: true,
                others: ['4821 Kestrel Dr, Marietta'] }), [af, b]);
  eq('...and a cue that arrives later files it',
     A.retryUnowned(p, [af, b]).map(function (r) { return [r.d.line, r.order.id, r.cue]; }),
     [['9 Elm Ct, Smyrna', 'b', 'elimination']]);

  // The planner with two held: each dropoff of a list seen whole a
  // candidate, the store only on a one-pickup one-dropoff list.
  var s2 = A.fresh();
  var page = pageOf('Trip Planner\nPickup • 1 order\nLarkspur Tacos\nExpected by 7:50 PM\n'
                    + 'Address\n5 Mill St\nRoswell, GA\n'
                    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\n'
                    + 'Address\n415 Ostrander Way NW\nKennesaw, GA\nWaybill', 9000);
  var c2 = A.sighting(s2, [a, b], page, 9000).candidates;
  eq('two held: a list seen whole gives its dropoff with the store of its one pickup',
     c2.map(function (c) { return [c.line, c.store, c.expectedBy, c.bounded]; }),
     [['415 Ostrander Way NW, Kennesaw', 'Larkspur Tacos', 1202, true]]);
  eq('...which the name cue gives to B', who(s2, [a, b], c2[0]), ['b', 'name', null]);
  eq('one order held is decided exactly as before (a list, not two orders)',
     A.sighting(A.fresh(), [a], page, 9000).candidates.length,
     A.sighting(A.fresh(), a, page, 9000).candidates.length);

  // The re-offer, beside the held order's own card.
  var held = { seenAs: { pay: 12.4, miles: 6.2, minutes: 35, pickup: 'Wren Street Noodles',
                         dropoff: '12 Oak St, Marietta', tookAt: 1000 } };
  var again = { pay: 13.15, miles: 6.2, minutes: 35, pickup: 'Wren Street Noodles',
                dropoff: '12 Oak St, Marietta' };
  eq('a re-offer: same miles, minutes and both ends, a different pay, inside the window',
     [A.reOffer(held, again, 2000, 180000),
      A.reOffer(held, Object.assign({}, again, { pay: 12.4 }), 2000, 180000),
      A.reOffer(held, Object.assign({}, again, { dropoff: null }), 2000, 180000),
      A.reOffer(held, again, 999999, 180000)],
     [true, false, false, false]);

  /* An Uber add-on held with the order it joined (server.js placeTook, the
     owner's decision of 17 Oct): the Trip Planner then shows both orders'
     stops, and each dropoff is filed on a positive cue or not at all. The 16
     Oct shift's first order had its planner door on record when the add-on
     came. Stores, people and streets invented. */
  var PLAN_ONE = 'Trip Planner\nPickup • 1 order\nFable Grill\nExpected by 7:50 PM\n'
    + 'Address\n283 Quillon St NW\nSmyrna, GA\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\n'
    + 'Address\n415 Ostrander Way NW\nKennesaw, GA\nWaybill';
  var PLAN_TWO = 'Trip Planner\nPickup • 1 order\nFable Grill\nExpected by 7:50 PM\n'
    + 'Address\n283 Quillon St NW\nSmyrna, GA\n'
    + 'Pickup • 1 order\nKestrel Noodle Bar\nExpected by 7:58 PM\n'
    + 'Address\n41 Wren Way\nSmyrna, GA\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\n'
    + 'Address\n415 Ostrander Way NW\nKennesaw, GA\n'
    + 'Dropoff • 1 order\nJules K.\nExpected by 8:20 PM\n'
    + 'Address\n9 Elm Ct\nSmyrna, GA\nWaybill';
  // ...and the shape with one store for both: "Pickup · 2 orders".
  var PLAN_SHOP = 'Trip Planner\nPickup • 2 orders\nFable Grill\nExpected by 7:50 PM\n'
    + 'Address\n283 Quillon St NW\nSmyrna, GA\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\n'
    + 'Address\n415 Ostrander Way NW\nKennesaw, GA\n'
    + 'Dropoff • 1 order\nJules K.\nExpected by 8:20 PM\n'
    + 'Address\n9 Elm Ct\nSmyrna, GA\nWaybill';
  function addOnRun(plan) {
    var st = A.fresh();
    var root = order('root', 1000, { pickup: 'Fable Grill' });
    A.took(st, root);
    // The original alone: its planner read whole files its door, and the list
    // is remembered for growth.
    A.sighting(st, root, pageOf(PLAN_ONE, 3000), 3000).candidates.forEach(function (c) {
      A.file(root, c, A.dropoff(root, c, null), st);
    });
    var add = order('add', 5000, { pickup: 'Kestrel Noodle Bar', addOn: true,
                                   of: root.holdId });
    var cands = A.sighting(st, [root, add], pageOf(plan, 9000), 9000).candidates;
    return { st: st, views: (st.views || []).length,
             who: cands.map(function (c) {
               var r = A.attribute(st, [root, add], c);
               return [c.line, r.order ? r.order.id : null, r.cue];
             }) };
  }
  var run2 = addOnRun(PLAN_TWO);
  eq('[add-on] a list seen whole with ONE order in the car is remembered for growth',
     run2.views >= 1, true);
  eq('[add-on] the planner with both orders\' stops: the add-on\'s door by growth, the '
     + 'original\'s by growth too', run2.who,
     [['415 Ostrander Way NW, Kennesaw', 'root', 'growth'],
      ['9 Elm Ct, Smyrna', 'add', 'growth']]);
  eq('[add-on] ...and the same with "Pickup · 2 orders", one store for both',
     addOnRun(PLAN_SHOP).who,
     [['415 Ostrander Way NW, Kennesaw', 'root', 'growth'],
      ['9 Elm Ct, Smyrna', 'add', 'growth']]);
  // With no list remembered from before the add-on (its door came off a
  // navigation screen, say): elimination for the add-on's, and the original's
  // own door is the original's by `filed` — it waited in the pool before.
  var rf = order('rf', 1000);
  A.file(rf, { line: '415 Ostrander Way NW, Kennesaw', street: '415 Ostrander Way NW',
               city: 'Kennesaw', at: 2000 }, { to: 'hold', from: 'nav' }, null);
  var ad = order('ad', 5000, { addOn: true, of: rf.holdId });
  var both = { bounded: true };
  eq('[add-on] no list from before: the add-on\'s door by elimination',
     who(A.fresh(), [rf, ad], d(Object.assign({ line: '9 Elm Ct, Smyrna',
                                                 others: ['415 Ostrander Way NW, Kennesaw'] },
                                               both))), ['ad', 'elimination', null]);
  eq('[add-on] ...and the original\'s own door, read again on the list, by `filed`',
     who(A.fresh(), [rf, ad], d(Object.assign({ line: '415 Ostrander Way NW, Kennesaw, GA',
                                                 others: ['9 Elm Ct, Smyrna'] }, both))),
     ['rf', 'filed', null]);
  eq('[add-on] `filed` never off a list not seen whole',
     who(A.fresh(), [rf, ad], d({ line: '415 Ostrander Way NW, Kennesaw', bounded: false,
                                  others: ['9 Elm Ct, Smyrna'] })), [null, null, 'no cue']);
  eq('[add-on] ...nor across apps',
     who(A.fresh(), [rf, order('dx', 5000, { app: 'doordash' })],
         d({ line: '415 Ostrander Way NW, Kennesaw', bounded: true, app: null,
             others: ['9 Elm Ct, Smyrna'] })), [null, null, 'no cue']);
  var rf2 = order('rf2', 5000);
  A.file(rf2, { line: '415 Ostrander Way NW, Kennesaw', street: '415 Ostrander Way NW',
                city: 'Kennesaw', at: 6000 }, { to: 'hold', from: 'nav' }, null);
  eq('[add-on] ...and two orders filed to one door decide nothing, and are no tie for the map',
     who(A.fresh(), [rf, rf2], d({ line: '415 Ostrander Way NW, Kennesaw', bounded: true,
                                   others: ['9 Elm Ct, Smyrna'] })), [null, null, 'no cue']);
  eq('[add-on] with nothing remembered and nothing filed, neither door is filed: they wait',
     who(A.fresh(), [order('n1', 1000), order('n2', 5000, { addOn: true })],
         d({ line: '9 Elm Ct, Smyrna', bounded: true, others: ['415 Ostrander Way NW, Kennesaw'] })),
     [null, null, 'no cue']);

  // An original and TWO add-ons, one trip of three (the owner's 16 Oct trip
  // details: $25.03 + $9.50 + $6.89). Growth from the list seen between the
  // second and third Tooks names the third's door, and only that one: a door
  // already on that list is one of the two older orders', and which is not
  // growth's to say.
  var t1 = order('t1', 1000), t2 = order('t2', 5000, { addOn: true }),
      t3 = order('t3', 7000, { addOn: true });
  var g3 = A.fresh();
  g3.views = [{ app: 'uber', at: 6000,
                drops: ['dropoff|Mara T.|1202', 'dropoff|Jules K.|1220'] }];
  var drops3 = ['dropoff|Mara T.|1202', 'dropoff|Jules K.|1220', 'dropoff|Ines V.|1235'];
  eq('[add-on] three in the car: the list grown by one gives the newest its door',
     who(g3, [t1, t2, t3], d({ key: 'dropoff|Ines V.|1235', listDrops: drops3 })),
     ['t3', 'growth', null]);
  eq('[add-on] ...and a door it already had to nobody by growth alone',
     who(g3, [t1, t2, t3], d({ key: 'dropoff|Jules K.|1220', listDrops: drops3 })),
     [null, null, 'no cue']);
  A.file(t1, { line: '415 Ostrander Way NW, Kennesaw', street: '415 Ostrander Way NW',
               city: 'Kennesaw', at: 2000 }, { to: 'hold', from: 'nav' }, null);
  eq('[add-on] three in the car, one end filed: no elimination for the other two',
     who(A.fresh(), [t1, t2, t3], d({ line: '3 Ash Way, Smyrna', bounded: true,
                                      others: ['415 Ostrander Way NW, Kennesaw',
                                               '9 Elm Ct, Smyrna'] })),
     [null, null, 'no cue']);
  A.file(t2, { line: '9 Elm Ct, Smyrna', street: '9 Elm Ct', city: 'Smyrna', at: 6000 },
         { to: 'hold', from: 'nav' }, null);
  eq('[add-on] ...two filed: the third door on the list is the third order\'s',
     who(A.fresh(), [t1, t2, t3], d({ line: '3 Ash Way, Smyrna', bounded: true,
                                      others: ['415 Ostrander Way NW, Kennesaw',
                                               '9 Elm Ct, Smyrna'] })),
     ['t3', 'elimination', null]);
  eq('[add-on] ...but not when the list shows fewer dropoffs than orders',
     who(A.fresh(), [t1, t2, t3], d({ line: '3 Ash Way, Smyrna', bounded: true,
                                      others: ['9 Elm Ct, Smyrna'] })),
     [null, null, 'no cue']);
})();

/* ---- DoorDash's place popup, read while a card is screened ----------------
 *
 * The driver taps a stop on a DoorDash card before deciding and the phone shows
 * its address (offer_parser.place_popup). Assemble.popup decides whether it
 * goes onto the card being screened, and filePopup puts it there; at ✓ Took
 * cardFields carries it into the hold at rank `popup`. Every store, street and
 * door invented. */
(function () {
  var CARD_AT = 1000;
  function card(more) {
    return Object.assign({ id: 'dd-1', app: 'doordash', screen: 'dd.offer', pay: 7.75,
                           pickup: 'S &, Lark Owl Pizza ; 1200 Fable Parkway Nort',
                           dropoff: null, manyDropoffs: false }, more || {});
  }
  function pop(more) {
    return Object.assign({ role: 'pickup', name: 'Lark Owl Pizza',
                           line: '1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144',
                           street: '1200 Fable W Lantern Pkwy NW', city: 'Kennesaw',
                           state: 'GA', zip: '30144', app: 'doordash',
                           screen: 'dd.placePopup', at: 4000 }, more || {});
  }
  var CTX = { held: [], offerAt: CARD_AT, seenAt: 3000, cardMs: 16000 };
  function decide(c, p, ctx) { return A.popup(c, p, Object.assign({}, CTX, ctx || {})); }

  var c1 = card(), p1 = pop();
  var said = decide(c1, p1);
  A.filePopup(c1, p1, said);
  eq('a store popup read while a card is screened gives the card its pickup address',
     [said.to, said.field, c1.pickupAddr && c1.pickupAddr.value, c1.pickupAddr && c1.pickupAddr.from],
     ['card', 'pickupAddr', '1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144', 'popup']);
  eq('...and leaves its end and its own name for the store as they were',
     [c1.dropoff, c1.pickup], [null, 'S &, Lark Owl Pizza ; 1200 Fable Parkway Nort']);

  var c2 = card({ pickup: 'Lark Owl Pizza' });
  var p2 = pop({ role: 'dropoff', name: null, line: '412 Wrenfield Ct NE, Marietta, GA 30062',
                 street: '412 Wrenfield Ct NE', city: 'Marietta', zip: '30062' });
  var said2 = decide(c2, p2);
  A.filePopup(c2, p2, said2);
  eq('a customer popup gives the dropoff',
     [said2.to, said2.field, c2.dropoff, c2.dropoffScanned, c2.dropoffFrom],
     ['card', 'dropoff', '412 Wrenfield Ct NE, Marietta, GA 30062', true, 'popup']);

  var c3 = card();
  var said3 = decide(c3, pop({ role: null }));
  A.filePopup(c3, pop({ role: null }), said3);
  eq('a popup with no role cue files nothing', [said3.to, said3.why, c3.pickupAddr, c3.dropoff],
     [null, 'no role', undefined, null]);

  var c4 = card();
  var p4 = pop({ name: 'Wren Street Noodles' });
  var said4 = decide(c4, p4);
  A.filePopup(c4, p4, said4);
  eq('a popup for a different store files nothing', [said4.to, said4.why, c4.pickupAddr],
     [null, 'a different store', undefined]);
  eq('...nor one for another branch of the same store: the card printed its number',
     [decide(card(), pop({ street: '880 Fable W Lantern Pkwy NW',
                           line: '880 Fable W Lantern Pkwy NW, Kennesaw, GA 30144' })).why],
     ['a different branch']);
  eq('...but a number the card cut at its left is the same door',
     decide(card({ pickup: 'Lark Owl Pizza ; 00 Fable Parkway Nort' }), pop()).to, 'card');
  eq('one i/l slip in the name is the same store, two are not',
     [decide(card({ pickup: 'Lark Owi Pizza' }), pop()).to,
      decide(card({ pickup: 'Iark Owi Pizza' }), pop()).why],
     ['card', 'a different store']);

  // Never onto the held order: not its card come back, not its id on the slot.
  var held = { id: 'dd-1', acceptedAt: 500 };
  var c5 = card({ heldCard: 'dd-1@500' });
  var said5 = decide(c5, pop());
  var c6 = card();
  var said6 = decide(c6, pop(), { held: [held] });
  var c7 = card();
  var p7 = pop({ role: 'dropoff', name: null });
  var said7 = decide(c7, p7, { held: [held] });
  eq('never onto the held order',
     [said5.to, said5.why, said6.to, said6.why, said7.to, said7.why],
     [null, 'the order in the car', null, 'the order in the car', null, 'the order in the car']);
  eq('...and nothing with no card being screened', decide(null, pop()).why,
     'no card being screened');
  eq('a popup read before the card came onto the slot is not about it',
     decide(card(), pop({ at: 999 })).why, 'before the card');
  eq("...nor one on another app's card", decide(card({ app: 'uber' }), pop()).why,
     "another app's card");
  eq("a customer's popup needs the card still on the screen when it was read",
     [decide(card(), pop({ role: 'dropoff', at: 20000 })).why,
      decide(card(), pop({ role: 'dropoff', at: 18000 })).to],
     ['the card not on the screen', 'card']);
  eq('...and a card with one customer: "Multiple dropoffs" is two doors',
     decide(card({ manyDropoffs: true }), pop({ role: 'dropoff' })).why,
     'more than one customer');
  eq('a popup does not move a pressed end, and does move the card\'s own',
     [decide(card({ dropoff: '9 A St, Acworth', dropoffScanned: true, dropoffFrom: 'press' }),
             pop({ role: 'dropoff' })).why,
      decide(card({ dropoff: 'Elm St & Oak Ave, Marietta' }), pop({ role: 'dropoff' })).why,
      decide(card({ dropoff: '9 A St, Acworth', dropoffScanned: true, dropoffFrom: 'seen' }),
             pop({ role: 'dropoff' })).why],
     ['outranked by press', 'over the card', 'over a sighting']);

  // ✓ Took: the card's popup addresses become the hold's fields, at their rank.
  var taken = card();
  A.filePopup(taken, pop(), decide(taken, pop()));
  A.filePopup(taken, p2, decide(taken, p2));
  var fields = A.cardFields(taken, 9000);
  eq('carried into the hold at Took',
     [fields.pickupAddr.value, fields.pickupAddr.from, fields.pickupAddr.at,
      fields.dropoff.value, fields.dropoff.from],
     ['1200 Fable W Lantern Pkwy NW, Kennesaw, GA 30144', 'popup', 4000,
      '412 Wrenfield Ct NE, Marietta, GA 30062', 'popup']);
  eq('...below press and label, above the card: each replaces it or is refused by it',
     [!!A.outranks(Object.assign({}, fields.dropoff, { from: 'label' }), fields.dropoff),
      !!A.outranks(Object.assign({}, fields.dropoff, { from: 'press' }), fields.dropoff),
      !!A.outranks(Object.assign({}, fields.dropoff, { from: 'card' }), fields.dropoff),
      !!A.outranks(Object.assign({}, fields.dropoff, { from: 'seen' }), fields.dropoff)],
     [true, true, false, false]);
  eq('...and a card with no popup is carried as it always was',
     A.cardFields(card(), 9000).pickupAddr.from, 'card');
})();

/* ---- a headless page with two orders in the car ---- */
/* sightingMany holds the page as sighting does (pageStops): the cut header on
   a titled page over the address block and Waybill on the next is a list
   seen whole, and its one dropoff a candidate for the cues to attribute. The
   headless page alone gives none. Invented streets, as the sequences'. */
(function () {
  var UPPER = 'Trip Planner\nPickup • 1 order\nJuniper Taqueria\nExpected by 7:40 PM\n'
    + 'Address\n2210 Quarry Bend Rd NW,\nKennesaw, GA 30144\nView details\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM';
  var HEADLESS = 'Address\n415 Ostrander Way NW\nKennesaw, GA\nView details\nWaybill';
  var a = holdOf({ acceptedAt: 1000 }, 'o-a'), b = holdOf({ acceptedAt: 1500 }, 'o-b');
  var st = A.fresh();
  var alone = A.sighting(st, [a, b], pageOf(HEADLESS, 2000), 2000);
  eq('two orders: a headless page alone gives no candidate', alone.candidates.length, 0);
  var st2 = A.fresh();
  A.sighting(st2, [a, b], pageOf(UPPER, 2000), 2000);
  var joined = A.sighting(st2, [a, b], pageOf(HEADLESS, 9000), 9000);
  eq('...and under the cut header of the page before, its dropoff is a candidate, '
     + 'on a list seen whole',
     joined.candidates.map(function (c) { return [c.line, c.bounded, c.pages]; }),
     [['415 Ostrander Way NW, Kennesaw', true, 2]]);
})();

/* ---- a ⌖ press between the order in the car and a card being screened ---- */
/* One order held, its end on record, and another card on the slot: a press is
   the card's on its own place popup, the order's on its navigation or Trip
   Planner read since its Took, and otherwise nobody's until the driver picks
   (pressBetween; server.js opens the chooser). Invented stores and streets. */
(function () {
  var PLAN = 'Trip Planner\nPickup • 1 order\nJuniper Taqueria\nExpected by 7:40 PM\n'
    + 'Address\n2210 Quarry Bend Rd NW,\nKennesaw, GA 30144\nView details\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\nAddress\n415 Ostrander Way NW\n'
    + 'Kennesaw, GA\nView details\nWaybill';
  function held(more) {
    var h = Object.assign({ id: 'o-held', acceptedAt: 1000, tookAt: 1200, app: 'uber',
                            pickup: 'Juniper Taqueria', minutes: 30,
                            dropoff: '77 Birch Ln, Roswell, GA 30075', dropoffScanned: true },
                          more || {});
    h.fields = A.cardFields({ dropoff: h.dropoff, dropoffScanned: true, dropoffFrom: 'press' },
                            h.acceptedAt);
    return h;
  }
  function card(more) {
    return Object.assign({ id: 'c-screened', app: 'doordash', pickup: 'Lark Owl Pizza',
                           dropoff: '412 Wrenfield Ct NE, Marietta, GA 30062',
                           dropoffScanned: true, dropoffFrom: 'popup' }, more || {});
  }
  function press(line, screen, more) {
    return Object.assign({ found: true, line: line, street: line.split(',')[0],
                           city: 'Marietta', state: 'GA', zip: null, asked: true,
                           labelled: null, ms: 10, app: 'doordash', screen: screen,
                           expectedBy: null, at: 5000 }, more || {});
  }
  function planned(h, at) {
    return A.sighting(A.fresh(), h, pageOf(PLAN, at, true), at).candidates[0];
  }
  var OWN = '412 Wrenfield Ct NE, Marietta, GA 30062';

  // The card's own popup: the press files on the card, at press rank, and
  // the order in the car keeps its end.
  var h1 = held(), c1 = card(), d1 = press(OWN, 'dd.placePopup');
  var said1 = A.pressBetween(h1, c1, d1);
  var filed1 = A.dropoff(null, d1, c1);
  A.fileCard(c1, d1, filed1, said1.cue);
  eq('pressBetween: over the card\'s own popup, the card',
     [said1.to, said1.cue, c1.dropoff, c1.dropoffFrom, h1.dropoff, h1.fields.dropoff.value],
     ['card', 'popup', OWN, 'press', '77 Birch Ln, Roswell, GA 30075',
      '77 Birch Ln, Roswell, GA 30075']);
  eq('...carried into the hold at Took at press rank',
     brief(A.cardFields(c1, 9000).dropoff), { value: OWN, from: 'press' });
  eq('...and a popup the card was never given is no cue: the driver picks',
     [A.pressBetween(held(), card({ dropoff: null, dropoffScanned: false }), d1).to,
      A.pressBetween(held(), card({ dropoffFrom: 'seen' }), d1).to,
      A.pressBetween(held(), card(), press('9 Heron Ct, Smyrna, GA 30080', 'dd.placePopup')).why],
     [null, null, "not the card's own popup"]);

  // The held order's own planner, pressed for after its Took: the order.
  var h2 = held(), cand = planned(h2, 5000);
  var said2 = A.pressBetween(h2, card(), cand);
  var filed2 = A.dropoff(h2, cand, card());
  A.file(h2, cand, filed2);
  eq('pressBetween: over the held order\'s planner, the order',
     [said2.to, said2.cue, cand.app, cand.store, h2.dropoff, h2.fields.dropoff.from],
     ['hold', 'planner', 'uber', 'Juniper Taqueria', '415 Ostrander Way NW, Kennesaw', 'press']);
  eq('...and over its navigation, the order',
     A.pressBetween(held(), card(), press('77 Birch Ln, Roswell', 'uber.nav', { app: 'uber' })),
     { to: 'hold', cue: 'nav', why: null });
  // ...but each of its three conditions holds or the screen is no cue.
  eq('...not one read before the order\'s Took',
     A.pressBetween(held(), card(), planned(held(), 1100)).why, 'before the Took');
  eq('...nor another app\'s',
     A.pressBetween(held({ app: 'doordash' }), card(), planned(held(), 5000)).why,
     'another app');
  eq('...nor one naming another store than the order\'s card',
     A.pressBetween(held({ pickup: 'Wren Street Noodles' }), card(), planned(held(), 5000)).why,
     'another store');

  // No cue: nothing decided, for every screen that is not one — read after
  // the Took and of the order's own app, so the screen alone is asked.
  eq('pressBetween: with no cue nobody is given it',
     ['unknown', 'uber.pickupNav', 'dd.offer', undefined].map(function (s) {
       return A.pressBetween(held(), card(), press('9 Heron Ct, Smyrna', s, { app: 'uber' })).to;
     }), [null, null, null, null]);

  // Not the question at all: dropoff() decides as it always has.
  eq('pressBetween: not asked with nothing held, no card, its own card, a card already taken, '
     + 'or a sighting',
     [A.pressBetween(null, card(), d1), A.pressBetween(held(), null, d1),
      A.pressBetween(held(), card({ id: 'o-held' }), d1),
      A.pressBetween(held(), card({ heldCard: 'o-held@1000' }), d1),
      A.pressBetween(held(), card({ accepted: true }), d1),
      A.pressBetween(held(), card(), press(OWN, 'dd.placePopup', { asked: false }))],
     [null, null, null, null, null, null]);

  // A row picked from the chooser: said so on the card, and a press after.
  var c3 = card({ dropoff: null, dropoffScanned: false, dropoffFrom: undefined });
  var d3 = press('9 Heron Ct, Smyrna, GA 30080', 'unknown');
  A.fileCard(c3, d3, A.dropoff(null, d3, c3), 'chooser');
  eq('a chooser pick on the card says so, and stands as a press',
     [c3.dropoffFrom, A.cardRank(c3), brief(A.cardFields(c3, 9000).dropoff),
      A.popup(c3, { role: 'dropoff', line: OWN, at: 4000, app: 'doordash' },
              { held: [], offerAt: 1000, seenAt: 3000, cardMs: 16000 }).why],
     ['chooser', 'press', { value: '9 Heron Ct, Smyrna, GA 30080', from: 'press' },
      'outranked by press']);

  // Two orders held: whether the card screened could own a press at all —
  // not on an order's own navigation or planner (asked of an Uber card, so
  // the screen alone says no), not another app's, not a card already taken
  // or an order's own, not a sighting.
  var two = [held(), held({ id: 'o-two', acceptedAt: 1100, tookAt: 1300, app: 'doordash' })];
  eq('cardCandidate: a screened card can own a press, but not over an order\'s navigation or '
     + 'planner, of another app, taken, an order\'s own, or unpressed',
     [A.cardCandidate(two, card(), d1),
      A.cardCandidate(two, card(), press('9 Heron Ct, Smyrna', 'unknown')),
      A.cardCandidate(two, card({ app: 'uber' }),
                      press('77 Birch Ln, Roswell', 'uber.nav', { app: 'uber' })),
      A.cardCandidate(two, card({ app: 'uber' }), planned(held(), 5000)),
      A.cardCandidate(two, card({ app: 'uber' }), d1),
      A.cardCandidate(two, card({ accepted: true }), d1),
      A.cardCandidate(two, card({ id: 'o-two' }), d1),
      A.cardCandidate(two, card(), press(OWN, 'dd.placePopup', { asked: false }))],
     [true, true, false, false, false, false, false, false]);
  // ...and while it could, the one order the hard rules leave is not chosen
  // on that alone; a cue that names it still chooses it.
  var dd = press('9 Heron Ct, Smyrna', 'unknown');
  var due = press('9 Heron Ct, Smyrna', 'unknown', { expectedBy: 1200 });
  var twoDue = [two[0], Object.assign({}, two[1], { deliverBy: 1201 })];
  eq('attribute with a screened card: no order by `only`, one by a cue that names it',
     [A.attribute(A.fresh(), two, dd).cue,
      [A.attribute(A.fresh(), two, dd, { card: true }).order,
       A.attribute(A.fresh(), two, dd, { card: true }).why],
      A.attribute(A.fresh(), twoDue, due, { card: true }).cue],
     ['only', [null, 'no cue'], 'deadline']);

  // The customer's popup read on its own, unpressed, on the whole screen: the
  // popup's own line files it on the card; this read files it on no order.
  var popSight = { at: 5000, asked: false, whole: true, titled: false, app: 'doordash',
                   screen: 'dd.placePopup', page: { top: null, bottom: null },
                   stops: [{ kind: 'dropoff', line: OWN, street: '412 Wrenfield Ct NE',
                             city: 'Marietta', label: 'dropoff' }], orderCount: null, keep: false };
  eq('the card\'s own popup read unpressed on the whole screen is no order\'s end, one held or two',
     [A.sighting(A.fresh(), held(), popSight, 5000).candidates.length,
      A.sighting(A.fresh(), [held(), held({ id: 'o-two', acceptedAt: 1100 })], popSight,
                 5000).candidates.length],
     [0, 0]);
})();

/* ---- a stop header the reader lost ----
 *
 * tests/fixtures/cases.json's planner cases with a header deleted (invented
 * streets): a page whose list was not read whole files nothing, pressed or
 * not, with one order held or two. The first is the one the parsers now call
 * unbounded; the third reads as bounded on the glass, and the pickups' count
 * against the dropoffs' is what refuses it (listShort). Before either, both
 * filed the second customer's door, 903 Brindle Ct, as the order's end. */
(function () {
  var byName = {};
  require('./fixtures/cases.json').planner.forEach(function (c) { byName[c.name] = c.text; });
  var lost = [
    'a dropoff header the reader lost leaves the list unbounded, and its other dropoff unfiled',
    '...and on a single trip, the one dropoff\'s header lost, the pickup keeps no address of '
      + 'the customer\'s',
    'a dropoff header lost with its time leaves the list bounded on the glass, and the '
      + 'pickups\' count says a dropoff is missing'];
  function single(id, at) {
    var h = { id: id || 'o', acceptedAt: at || 1000, card: { legs: 1, multiOrder: false },
              app: 'uber', dropoff: null, dropoffScanned: false };
    A.fieldsOf(h);
    return h;
  }
  lost.forEach(function (name) {
    var text = byName[name];
    ok_('the premise: the case is there (' + name.slice(0, 40) + '…)', !!text);
    if (!text) return;
    var filed = [
      A.sighting(A.fresh(), single(), pageOf(text, 2000, true), 2000).candidates.length,
      A.sighting(A.fresh(), single(), pageOf(text, 2000, false), 2000).candidates.length,
      A.sighting(A.fresh(), [single('a', 1000), single('b', 1500)], pageOf(text, 2000, true),
                 2000).candidates.length];
    eq('a lost stop header files nothing, pressed, unpressed or with two orders held — '
       + name.slice(0, 60) + '…', filed, [0, 0, 0]);
  });
  var st = A.fresh();
  A.sighting(st, single(), pageOf(byName[lost[2]], 2000, true), 2000);
  eq('...and the bounded one says the list was not seen whole', A.verdictFor(st, 2000), 'list');
  eq('...and its lone dropoff is not a single trip either',
     A.plannerLoneDropoff(OP.findPlanner(byName[lost[2]])), null);
})();

/* ---- the 16 Oct shift's single-trip planner, its label and town misread ----
 *
 * tests/fixtures/cases.json's "Measured: the single trip's planner with both
 * slips…" (names and streets invented): the dropoff's label read "Addres" and
 * its town line "<Town>. GA", so the stop had no street and no town, and the
 * held order kept the card's corner as its end. With both parsed, its lone
 * dropoff is a single trip's. The page shows no Waybill, so it is 'list'.
 *
 * Measured on this page through sighting(): with its title read whole it files
 * onto a held card of one order on one leg, unpressed, as `singleCardOnly`.
 * As read on shift, the title came back "ny. mS"; by the owner's decision
 * (16 Oct) its LAYOUT stands in for the title on an unpressed read — a Pickup
 * and a Dropoff header each with its "Expected by", "View details" and the
 * "Stop New Requests" bar (plannerLaidOut) — and it files too. A press on it
 * still files nothing (a press's lone dropoff is not taken, as before), nor
 * does the page without the bar, nor onto a card of two legs. Before the
 * parser fix, no page here filed anything. */
(function () {
  var name = 'Measured: the single trip\'s planner with both slips, its title misread '
    + 'and the bar under it';
  var text = null;
  require('./fixtures/cases.json').planner.forEach(function (c) {
    if (c.name === name) text = c.text;
  });
  ok_('the premise: the shift\'s planner case is there', !!text);
  if (!text) return;
  var titled = text.replace('ny. mS', 'Trip Planner');
  ok_('the premise: the case as read has no title, and with it read whole it does',
      !OP.plannerTitled(text) && OP.plannerTitled(titled));
  function single() {
    var h = { id: 'o-single', acceptedAt: 1000, card: { legs: 1, multiOrder: false },
              app: 'uber', dropoff: null, dropoffScanned: false };
    A.fieldsOf(h);
    return h;
  }
  eq('the shift\'s planner: its one dropoff, label "Addres" and town "<Town>. GA", is a '
     + 'single trip\'s lone dropoff',
     (A.plannerLoneDropoff(OP.findPlanner(text)) || {}).line, '283 Quillon St NW, Smyrna');

  // Hold a single-trip card, then the page under its title, unpressed: it files.
  var st = A.fresh();
  var hold = single();
  A.took(st, hold);
  var r = A.sighting(st, hold, pageOf(titled, 2000, false), 2000);
  var kept = r.candidates.map(function (d) {
    var said = A.dropoff(hold, d, null);
    if (!said.drop) A.file(hold, d, said, st);
    return [d.singleCardOnly === true, said.drop ? 'dropped' : said.from];
  });
  eq('the shift\'s planner under its title, unpressed, files its lone dropoff on a '
     + 'single-trip hold',
     [r.why, kept, hold.dropoff, hold.dropoffScanned, brief(hold.fields.dropoff)],
     ['list', [[true, 'planner']], '283 Quillon St NW, Smyrna', true,
      { value: '283 Quillon St NW, Smyrna', from: 'planner' }]);

  // The page as read on shift, title misread, unpressed: its layout proves it.
  function play1(page, card) {
    var s2 = A.fresh(), h2 = single();
    if (card) h2.card = card;
    A.took(s2, h2);
    var r2 = A.sighting(s2, h2, page, 2000);
    r2.candidates.forEach(function (d) {
      var said = A.dropoff(h2, d, null);
      if (!said.drop) A.file(h2, d, said, s2);
    });
    return [r2.candidates.length, h2.dropoff, A.verdictFor(s2, 2000)];
  }
  ok_('the premise: the page as read is laid out as a planner, and without its bar it is not',
      OP.plannerLaidOut(text) && !OP.plannerLaidOut(text.replace('Stop New Requests', 'S Q')));
  eq('a planner whose title was misread files its lone dropoff when its layout proves it',
     play1(pageOf(text, 2000, false)), [1, '283 Quillon St NW, Smyrna', null]);
  eq('...but a press on it files nothing, as a press on any unbounded list',
     play1(pageOf(text, 2000, true)), [0, null, 'list']);
  // (22 Oct) The bar is now known by its icons too ("S Q" over "=o",
  // PLANNER_ICON_Q), so "no bar" takes them off with its words...
  ok_('the premise: the page has the bar\'s icons over its words',
      text.indexOf('S Q\n=o\nStop New Requests') !== -1);
  eq('...nor the same page without the "Stop New Requests" bar or its icons',
     play1(pageOf(text.replace('S Q\n=o\nStop New Requests', ''), 2000, false)),
     [0, null, 'list']);
  // ...and with the icons and not the words, the page's last block is the
  // trip's last stop (footDropoff), filed at rank label.
  eq('...but with the bar\'s icons and its words unread, the last block is the trip\'s last stop',
     play1(pageOf(text.replace('Stop New Requests', 'pe J bs a'), 2000, false)).slice(0, 2),
     [1, '283 Quillon St NW, Smyrna']);
  eq('...nor onto a held card of two legs',
     play1(pageOf(text, 2000, false), { legs: 2, multiOrder: false })[1], null);
})();

/* A single trip's planner with its title scrolled off (framedTrip; the
 * owner's read of 21 Oct, 13:57, one Uber order held, carrying two on). The
 * shared case "Measured: the single trip's planner of 21 Oct…" (names and
 * streets invented): "Pickup - 1 order" the first line of the read, the bar
 * the last, no title and no Waybill, so the list is 'list'. The held card
 * read badly — legs 0, hasTotal false, multiOrder false — and the lone
 * dropoff was dropped as 'not a single trip': the order kept the card's
 * corner. Now the page's own frame, one Pickup of one order then one Dropoff
 * of one order, stands in for the card's legs, 0 allowed; nothing else of
 * the lone-dropoff rule moves. */
(function () {
  var name = 'Measured: the single trip\'s planner of 21 Oct, its title scrolled off the top, '
    + 'the store\'s street with a suite';
  var text = null;
  require('./fixtures/cases.json').planner.forEach(function (c) {
    if (c.name === name) text = c.text;
  });
  ok_('[framed] the premise: the 21 Oct planner case is there', !!text);
  if (!text) return;
  var ends = OP.plannerEnds(text);
  eq('[framed] the premise: the page is framed and laid out, with neither end of the list',
     [OP.plannerFramed(text), OP.plannerLaidOut(text), OP.plannerTitled(text), ends.top,
      ends.bottom], [true, true, false, false, false]);
  function held(card, extra) {
    var h = Object.assign({ id: 'o-framed', acceptedAt: 1000,
                            card: card === undefined
                              ? { legs: 0, multiOrder: false, hasTotal: false } : card,
                            app: 'uber', dropoff: 'Corbins Dr, Marietta',
                            dropoffScanned: false }, extra || {});
    h.fields = A.cardFields({ dropoff: h.dropoff, pickup: null }, h.acceptedAt);
    return h;
  }
  // One page through sighting(), its candidates through dropoff() and file().
  function run(page, h) {
    var st = A.fresh();
    h = h || held();
    A.took(st, h);
    var r = A.sighting(st, h, page, 2000);
    var said = r.candidates.map(function (d) {
      var s = A.dropoff(h, d, null);
      if (!s.drop) A.file(h, d, s, st);
      return [d.framed === true, s.drop ? s.why : s.from];
    });
    return [said, h.dropoff, brief(h.fields.dropoff), A.verdictFor(st, 2000)];
  }
  var page = pageOf(text, 2000, false);
  eq('[framed] the fault: the lone dropoff files onto a held card whose legs read 0, as a '
     + 'planner end, and the planner line says nothing unfiled',
     run(page),
     [[[true, 'planner']], '2282 Corbin, Marietta',
      { value: '2282 Corbin, Marietta', from: 'planner' }, null]);
  eq('[framed] ...and without the frame or the foot the old refusal stands: dropped, the '
     + 'card\'s corner kept, "list"',
     run(Object.assign({}, page, { framed: false, footed: false })),
     [[[false, 'not a single trip']], 'Corbins Dr, Marietta',
      { value: 'Corbins Dr, Marietta', from: 'card' }, 'list']);
  // (22 Oct) ...but without the frame and WITH the foot — the last block a
  // Dropoff over the bar's icons and the bar — the lone dropoff is still
  // refused, its card's legs unread, and the trip's last stop files the same
  // door at rank label beside it (footDropoff).
  eq('[framed] ...without the frame, footed: refused as a lone dropoff, filed as the trip\'s '
     + 'last stop, rank label',
     run(Object.assign({}, page, { framed: false })),
     [[[false, 'label'], [false, 'not a single trip']], '2282 Corbin, Marietta',
      { value: '2282 Corbin, Marietta', from: 'label' }, 'list']);
  eq('[framed] ...a card of one leg files as it always did',
     run(page, held({ legs: 1, multiOrder: false }))[1], '2282 Corbin, Marietta');
  eq('[framed] ...but not a card of two legs',
     run(page, held({ legs: 2, multiOrder: false }))[0], [[true, 'not a single trip']]);
  eq('[framed] ...nor a card of two orders',
     run(page, held({ legs: 0, multiOrder: true }))[0], [[true, 'not a single trip']]);
  eq('[framed] ...nor a card too old to say whether it was two orders',
     run(page, held({ legs: 0 }))[0], [[true, 'not a single trip']]);
  eq('[framed] ...nor a card that never said its legs',
     run(page, held({ multiOrder: false }))[0], [[true, 'not a single trip']]);
  eq('[framed] ...nor a hold with no card',
     run(page, held(null))[0], [[true, 'not a single trip']]);
  eq('[framed] ...nor an add-on\'s trip, by `addOn`',
     run(page, held(undefined, { addOn: true }))[0], [[false, 'not a single trip']]);
  eq('[framed] ...nor by `of`',
     run(page, held(undefined, { of: 'o-root@1' }))[0], [[false, 'not a single trip']]);
  eq('[framed] a press on the page files nothing: a press is the press\'s rule',
     run(pageOf(text, 2000, true)).slice(0, 2), [[], 'Corbins Dr, Marietta']);
  // An end the driver pressed for stays: a planner never outranks a press.
  var pressed = held();
  A.file(pressed, { line: '2290 Corbins Dr, Marietta', asked: true, at: 1500 },
         A.dropoff(pressed, { line: '2290 Corbins Dr, Marietta', asked: true, at: 1500 }, null));
  eq('[framed] ...and it never files over an end the driver pressed for',
     run(page, pressed).slice(1, 3),
     ['2290 Corbins Dr, Marietta', { value: '2290 Corbins Dr, Marietta', from: 'press' }]);
  // A read refused unframed (the title showing, no foot) does not hide the
  // framed read of the same door that follows: each is its own.
  (function () {
    var st = A.fresh(), h = held();
    A.took(st, h);
    var first = A.sighting(st, h, Object.assign({}, page, { at: 2000, framed: false,
                                                           footed: false }), 2000);
    first.candidates.forEach(function (d) { A.dropoff(h, d, null); });
    var r = A.sighting(st, h, Object.assign({}, page, { at: 3000 }), 3000);
    r.candidates.forEach(function (d) {
      var s = A.dropoff(h, d, null);
      if (!s.drop) A.file(h, d, s, st);
    });
    eq('[framed] a read refused unframed does not hide the framed read of the same door',
       [first.candidates.length, r.candidates.length, h.dropoff],
       [1, 1, '2282 Corbin, Marietta']);
  })();
  // With two orders held nothing of this rule is asked: sightingMany offers
  // no lone dropoff and nothing framed.
  (function () {
    var st = A.fresh();
    var a = held(), b = held(undefined, { id: 'o-other', acceptedAt: 1200 });
    var r = A.sighting(st, [a, b], page, 2000);
    eq('[framed] with two orders held no candidate is framed or a lone dropoff',
       r.candidates.filter(function (d) { return d.framed || d.singleCardOnly; }).length, 0);
  })();
  // The page's shape, one condition at a time (framedTrip).
  var stops = page.stops;
  var with_ = function (i, f) {
    return stops.map(function (s, k) { return k === i ? Object.assign({}, s, f) : s; });
  };
  var asked = function (s, pg) {
    var p = Object.assign({}, page, pg || {}, { stops: s });
    return A.framedTrip(held(), p, { stops: s });
  };
  eq('[framed] framedTrip: the fault\'s page is the trip; each part taken away is not',
     [asked(stops), asked(stops, { framed: false }),
      asked(with_(0, { orders: 2 })), asked(with_(1, { orders: 2 })),
      asked(with_(0, { kind: 'dropoff' })), asked(with_(1, { kind: 'pickup' })),
      asked(with_(1, { partial: 'header' })), asked(with_(0, { partial: 'top' })),
      asked(stops.concat([stops[1]])), asked(stops.slice(1)),
      asked([Object.assign({}, stops[1], { kind: null, partial: 'top' })].concat(stops))],
     [true, false, false, false, false, false, false, false, false, false, false]);
  eq('[framed] framedTrip: ...and the list it is read as must be the same one trip',
     A.framedTrip(held(), page, { stops: stops.concat([stops[1]]) }), false);
})();

/* The trip's last stop, its Dropoff header cropped off (footDropoff; the
 * owner's card-box read of 21 Oct, 15:00, one Uber order held, its end the
 * card's corner). The shared case "Measured: the card-box read of 21 Oct,
 * 15:00 …" (the street invented): "Address / <n> <street> / <Town>, GA /
 * View details / Waybill / … / Stop New Requests". Filed at rank `label`
 * over the card's corner, card box or whole; never with two held, an add-on,
 * a press, before the Took, or onto one of the order's own pickups. */
(function () {
  var name = 'Measured: the card-box read of 21 Oct, 15:00, the trip\'s last stop under its '
    + 'cropped Dropoff header, Waybill and the bar under it';
  var text = null;
  require('./fixtures/cases.json').planner.forEach(function (c) {
    if (c.name === name) text = c.text;
  });
  ok_('[foot] the premise: the 21 Oct 15:00 case is there, footed', !!text && OP.plannerFoot(text));
  if (!text) return;
  function held(extra) {
    var h = Object.assign({ id: 'o-foot', acceptedAt: 1000, app: 'uber',
                            card: { legs: 0, multiOrder: false },
                            pickup: 'Fable Grill (3400 Fable International Blvd NW)',
                            dropoff: 'Wren Flat Ct & Oriel Rd, Marietta',
                            dropoffScanned: false }, extra || {});
    h.fields = A.cardFields({ dropoff: h.dropoff, pickup: h.pickup }, h.acceptedAt);
    return h;
  }
  function run(page, h, st) {
    st = st || A.fresh();
    h = h || held();
    A.took(st, h);
    var r = A.sighting(st, h, page, page.at);
    var said = r.candidates.map(function (d) {
      var s = A.dropoff(h, d, null);
      if (s.to === 'hold') A.file(h, d, s, st);
      return [d.foot === true, s.to ? s.from : s.why];
    });
    return [said, h.dropoff, brief(h.fields.dropoff)];
  }
  var box = Object.assign(pageOf(text, 2000, false), { whole: false });
  var corner = 'Wren Flat Ct & Oriel Rd, Marietta';
  var door = '3259 Wrenfield Oaks Dr, Marietta';
  eq('[foot] the fault: the card-box read files the door over the card\'s corner, rank label',
     run(box), [[[true, 'label']], door, { value: door, from: 'label' }]);
  eq('[foot] ...and read whole, the same',
     run(pageOf(text, 2000, false))[1], door);
  eq('[foot] ...said once per hold: the same read again offers nothing',
     (function () {
       var st = A.fresh(), h = held();
       run(box, h, st);
       return run(Object.assign({}, box, { at: 3000 }), h, st)[0];
     })(), []);
  eq('[foot] ...not without the shape (`footed` false)',
     run(Object.assign({}, box, { footed: false })).slice(0, 2), [[], corner]);
  eq('[foot] ...not off a press',
     run(Object.assign({}, box, { asked: true })).slice(0, 2), [[], corner]);
  eq('[foot] ...not read before the Took',
     run(Object.assign({}, box, { at: 500 })).slice(0, 2), [[], corner]);
  eq('[foot] ...not onto an add-on\'s trip, by `addOn` or by `of`',
     [run(box, held({ addOn: true }))[1], run(box, held({ of: 'o-root@1' }))[1]],
     [corner, corner]);
  eq('[foot] ...not when the block is the held order\'s own pickup',
     run(box, held({ pickup: 'Fable Grill (3259 Wrenfield Oaks Dr)' })).slice(0, 2),
     [[], corner]);
  eq('[foot] ...nor a stop with a kind, or a page of two stops',
     [run(Object.assign({}, box, { stops: [Object.assign({}, box.stops[0],
                                                         { kind: 'pickup' })] }))[1],
      run(Object.assign({}, box, { stops: box.stops.concat(box.stops) }))[1]],
     [corner, corner]);
  // An end the driver pressed for stays: rank `label` never outranks a press.
  var pressed = held();
  A.file(pressed, { line: '3261 Wrenfield Oaks Dr, Marietta', asked: true, at: 1500 },
         A.dropoff(pressed, { line: '3261 Wrenfield Oaks Dr, Marietta', asked: true, at: 1500 },
                   null));
  eq('[foot] ...and never over an end the driver pressed for',
     run(box, pressed)[1], '3261 Wrenfield Oaks Dr, Marietta');
  // With two orders held nothing of this rule is asked (sightingMany).
  (function () {
    var st = A.fresh();
    var a = held(), b = held({ id: 'o-other', acceptedAt: 1200 });
    var r = A.sighting(st, [a, b], box, 2000);
    eq('[foot] with two orders held the cropped last stop is offered nowhere',
       r.candidates.filter(function (d) { return d.foot; }).length, 0);
  })();
})();

/* The owner's planner of 22 Oct, one Uber order held whose card read legs 0,
 * its end the card's corner: the whole read had the title, both stops and
 * the bar, its lines edged with the cloth's noise and words over the title,
 * and the card box saw the Dropoff block alone over the bar's icons and the
 * bar. Neither filed. The shared cases "the owner's whole-screen planner of
 * 22 Oct …" and "...and the card box's read of the same screen …" (names and
 * streets invented): the whole read is framed by its title and files as a
 * planner end; the card box's block is the trip's last stop WITH its header
 * (footDropoff) and files at rank label. */
(function () {
  var texts = {};
  require('./fixtures/cases.json').planner.forEach(function (c) { texts[c.name] = c.text; });
  var whole = texts['the owner\'s whole-screen planner of 22 Oct: the cloth\'s noise at both '
    + 'edges of the stops\' lines and over the title, and no Waybill'];
  var boxText = texts['...and the card box\'s read of the same screen: the Dropoff block over '
    + 'the bar, and Dr read as Or'];
  var peek = texts['...but a name between the block and the bar is the next stop peeking out: '
    + 'not the trip\'s last stop'];
  ok_('[foot 22 Oct] the premise: the three cases are there', !!whole && !!boxText && !!peek);
  if (!whole || !boxText || !peek) return;
  var corner = 'Wren Flat Ct & Oriel Rd, Kennesaw';
  var door = '412 Brindle Dr NW, Kennesaw';
  function held(extra) {
    var h = Object.assign({ id: 'o-1022', acceptedAt: 1000, app: 'uber',
                            card: { legs: 0, multiOrder: false, hasTotal: false },
                            pickup: 'Fable Grill (Kennesaw, GA)', dropoff: corner,
                            dropoffScanned: false }, extra || {});
    h.fields = A.cardFields({ dropoff: h.dropoff, pickup: h.pickup }, h.acceptedAt);
    return h;
  }
  function run(page, h) {
    var st = A.fresh();
    h = h || held();
    A.took(st, h);
    var r = A.sighting(st, h, page, page.at);
    var said = r.candidates.map(function (d) {
      var s = A.dropoff(h, d, null);
      if (s.to === 'hold') A.file(h, d, s, st);
      return [d.foot === true, d.framed === true, s.to ? s.from : s.why];
    });
    return [said, h.dropoff, brief(h.fields.dropoff), brief(h.fields.expectedBy)];
  }
  var box = Object.assign(pageOf(boxText, 2000, false), { whole: false });
  eq('[foot 22 Oct] the card box: the Dropoff block over the bar is the trip\'s last stop, '
     + 'its door ("Or" read as Dr) filed over the corner at rank label with its time',
     run(box), [[[true, false, 'label']], door, { value: door, from: 'label' },
                { value: 1130, from: 'label' }]);
  eq('[foot 22 Oct] the whole read: framed by its title over the noise, the lone dropoff files '
     + 'as a planner end',
     run(pageOf(whole, 2000, false)).slice(0, 3),
     [[[false, true, 'planner']], door, { value: door, from: 'planner' }]);
  var d = box.stops[0];
  var pick = { kind: 'pickup', orders: 1, name: 'Fable Grill', expectedBy: 1098,
               street: '1200 Wrenfield Pkwy NW', city: 'Kennesaw', state: 'GA', zip: '30144',
               line: '1200 Wrenfield Pkwy NW, Kennesaw, GA 30144', partial: null,
               label: 'pickup' };
  var withStops = function (stops) { return Object.assign({}, box, { stops: stops }); };
  eq('[foot 22 Oct] ...a Pickup of one order above it is allowed',
     run(withStops([pick, d]))[1], door);
  eq('[foot 22 Oct] ...not with another dropoff on the page, a block of no kind above it, a '
     + 'pickup of two orders (a header lost), or the Dropoff cut by an edge',
     [run(withStops([Object.assign({}, d, { line: '17 Quillon Way, Marietta',
                                            street: '17 Quillon Way', city: 'Marietta' }), d]))[1],
      run(withStops([Object.assign({}, d, { kind: null, orders: null, partial: 'top' }), d]))[1],
      run(withStops([Object.assign({}, pick, { orders: 2 }), d]))[1],
      run(withStops([Object.assign({}, d, { partial: 'bottom' })]))[1]],
     [corner, corner, corner, corner]);
  eq('[foot 22 Oct] ...nor with the next stop\'s name peeking out between it and the bar',
     run(Object.assign(pageOf(peek, 2000, false), { whole: false })).slice(0, 2), [[], corner]);
  eq('[foot 22 Oct] ...nor an add-on\'s trip, nor off a press, nor before the Took',
     [run(box, held({ addOn: true }))[1], run(Object.assign({}, box, { asked: true }))[1],
      run(Object.assign({}, box, { at: 500 }))[1]],
     [corner, corner, corner]);
  (function () {
    var r = A.sighting(A.fresh(), [held(), held({ id: 'o-other', acceptedAt: 1200 })], box, 2000);
    eq('[foot 22 Oct] with two orders held it is offered nowhere',
       r.candidates.filter(function (c) { return c.foot; }).length, 0);
  })();
})();

/* The same store as an order in the car (Assemble.samePickup; the owner's
 * decision of 18 Oct 2026). The 17 Oct shape, invented: an Uber order held
 * from "<Store> (113 <Street> NW)" and a DoorDash card whose stops line reads
 * the same door with the quadrant NE. Every store and street invented. */
(function () {
  var side = function (pickup, extra) { return A.pickupSide(Object.assign({ pickup: pickup }, extra || {}), null, null); };
  var held = side('Larkspur Tacos (113 Quillon St NW)');
  var dd = side('Larkspur Tacos', { pickupLine: '113 Quillon St NE, Marietta, 30060 GA' });
  eq('same store: the same door with the quadrant read differently is the same store',
     A.samePickup(held, dd, null), 'door');
  eq('...and with the street\'s type spelt out, and an i read as l in it',
     A.samePickup(side('Larkspur Tacos (113 Quillon Street)'),
                  side('Larkspur Tacos', { pickupLine: '113 Qulllon St NE, Marietta' }), null), 'door');
  eq('...and a house number read with an O for its 0',
     A.sameDoor('Fable Pizza (1O5 Wren Pkwy)', '105 Wren Parkway NW, Kennesaw'), true);
  eq('...but not a different house number on the same street',
     A.samePickup(held, side('Larkspur Tacos', { pickupLine: '118 Quillon St NE, Marietta' }), 0),
     null);
  eq('...nor two slips in the street, nor one that is not a look-alike',
     [A.sameDoor('1 Quillon St', '1 Qulll0n St'), A.sameDoor('1 Quillon St', '1 Quiiton St')],
     [false, false]);
  eq('...nor a suite taken for the street: the door is before it',
     A.doorOf('Fable Pizza (1200 Fable Pkwy NW STE 100)'), { house: '1200', street: 'fable' });
  eq('...and a name with no door has none',
     [A.doorOf('Larkspur Tacos'), A.doorOf("Papa John's (Store 3317)")], [null, null]);
  eq('a chain\'s name at the same door IS the same store',
     A.samePickup(side('Chick-fil-A (2290 Kestrel Rd NW)'),
                  side('Chick-fil-A', { pickupLine: '2290 Kestrel Rd, Kennesaw' }), null), 'door');
  eq('...and a distinctive name at two different doors is two branches, whatever the names say',
     A.samePickup(held, side('Larkspur Tacos', { pickupLine: '940 Wren Ave, Smyrna' }), 0), null);
  eq('a distinctive name, no door on one side, the pickups proven within half a mile: the same',
     A.samePickup(side('Larkspur Tacos'), held, 0.3), 'name');
  eq('...at exactly the half mile too, and not past it',
     [A.samePickup(side('Larkspur Tacos'), held, A.SAME_STORE_NEAR_MI),
      A.samePickup(side('Larkspur Tacos'), held, A.SAME_STORE_NEAR_MI + 0.01)], ['name', null]);
  eq('...nor with nothing to bound them: can\'t tell is not the same',
     [A.samePickup(side('Larkspur Tacos'), held, null),
      A.samePickup(side('Larkspur Tacos'), held, function () { return null; })], [null, null]);
  eq('...and the bound is asked only once the names have matched',
     (function () {
       var asked = 0;
       A.samePickup(side('Larkspur Tacos'), side('Wren Street Noodles'),
                    function () { asked += 1; return 0; });
       return asked;
     })(), 0);
  eq('a chain\'s name alone is not the same store, however near',
     [A.samePickup(side('Chick-fil-A'), side('Chick-fil-A'), 0.1),
      A.samePickup(side("McDonald's"), side("McDonald's #1155"), 0.1)], [null, null]);
  eq('...and far apart, no more so',
     A.samePickup(side('Chick-fil-A'), side('Chick-fil-A'), 12.0), null);
  eq('what is a chain: national names, a branch\'s label, a name too short to be one place',
     [A.chainName('Chick-fil-A'), A.chainName("McDonald's"), A.chainName("Papa John's Store 3317"),
      A.chainName('AtHome - 0020-Kennesaw'), A.chainName('Bo'), A.chainName('Larkspur Tacos'),
      A.chainName('Larkspur Tacos (113 Quillon St NW)')],
     [true, true, true, true, true, false, false]);
  eq('a hold\'s own planner pickup is its door, by its id or, unmarked, by its name',
     [A.pickupSide({ pickup: 'Larkspur Tacos' },
                   [{ kind: 'pickup', name: 'oe Larkspur Tacos', street: '113 Quillon St NW',
                      line: '113 Quillon St NW, Marietta' }], 'h@1').doors,
      A.pickupSide({ pickup: 'Larkspur Tacos' },
                   [{ kind: 'pickup', name: 'Wren Street Noodles', of: 'h@1', street: '7 Wren Ave' }],
                   'h@1').doors,
      A.pickupSide({ pickup: 'Larkspur Tacos' },
                   [{ kind: 'pickup', name: 'Larkspur Tacos', of: 'other@2', street: '7 Wren Ave' },
                    { kind: 'dropoff', name: 'Larkspur Tacos', street: '9 Wren Ave' }],
                   'h@1').doors],
     [['Larkspur Tacos', '113 Quillon St NW, Marietta'], ['Larkspur Tacos', '7 Wren Ave'],
      ['Larkspur Tacos']]);
  eq('...and a tapped popup\'s door, on the card or the hold',
     [A.pickupSide({ pickup: 'Larkspur Tacos',
                     pickupAddr: { value: '113 Quillon St', from: 'popup' } }).doors,
      A.pickupSide({ pickup: 'Larkspur Tacos',
                     fields: { pickupAddr: { value: '113 Quillon St', from: 'popup' } } }).doors],
     [['Larkspur Tacos', '113 Quillon St'], ['Larkspur Tacos', '113 Quillon St']]);
})();

/* ---- a batched Uber trip: one card, one Took, two doors (the owner's facts of
   17 and 19 Oct 2026; the decision of 19 Oct). The planner seen whole lists
   two dropoffs for ONE order held; the end is the last door. Every store,
   person and street invented. ---- */
(function () {
  var BATCH = 'Trip Planner\nPickup • 1 order\nTamsin Bakehouse\nExpected by 5:20 PM\n'
    + 'Address\n40 Quarrel St\nSmyrna, GA\n'
    + 'Pickup • 1 order\nOrrin Noodle Co\nExpected by 5:26 PM\n'
    + 'Address\n12 Pellow Ave\nSmyrna, GA\n'
    + 'Dropoff • 1 order\nVesna R.\nExpected by 5:42 PM\n'
    + 'Address\n88 Hollin Ct\nMarietta, GA\n'
    + 'Dropoff • 1 order\nCorvin D.\nExpected by 6:00 PM\n'
    + 'Address\n517 Tarrow Ridge Dr NW\nMarietta, GA\nWaybill';
  var CARD_END = 'Tarrow Ridge Dr & Brisk Ln, Marietta';
  function batchHold(dropoff, more) {
    var h = Object.assign({ id: 'b-1', acceptedAt: 1000, tookAt: 1005, minutes: 51,
                            app: 'uber', pickup: 'Tamsin Bakehouse (40 Quarrel St)',
                            dropoff: dropoff === undefined ? CARD_END : dropoff,
                            dropoffScanned: false,
                            card: { legs: 1, multiOrder: false } }, more || {});
    h.seenAs = { dropoff: h.dropoff };
    A.fieldsOf(h);
    return h;
  }
  // The server's road: sighting → dropoff → file.
  function run(h, text, at, st) {
    st = st || A.fresh();
    A.took(st, h);
    var r = A.sighting(st, h, pageOf(text, at || 5000), at || 5000);
    var saids = r.candidates.map(function (c) {
      var said = A.dropoff(h, c, null);
      A.file(h, c, said, st);
      return said.why;
    });
    return { st: st, r: r, saids: saids, verdict: A.verdictFor(st, at || 5000) };
  }
  var h = batchHold();
  var got = run(h, BATCH);
  eq('[batch] two dropoffs on a list seen whole with one order held: the LAST door is '
     + 'the end, over the card\'s corner, from the planner',
     [h.dropoff, A.fieldsOf(h).dropoff.from, got.saids],
     ['517 Tarrow Ridge Dr NW, Marietta', 'planner', ['over the card']]);
  eq('[batch] ...the hold carries `batch` and every door, in the planner\'s order',
     [h.batch, (h.drops || []).map(function (d) { return [d.line, d.expectedBy]; })],
     [true, [['88 Hollin Ct, Marietta', 1062], ['517 Tarrow Ridge Dr NW, Marietta', 1080]]]);
  eq('[batch] ...the planner line says no reason, and batchWhy none',
     [got.verdict, A.batchWhy(got.st, h)], [null, null]);
  eq('[batch] ...and the last door\'s customer and time are the hold\'s',
     [A.fieldsOf(h).customer.value, A.fieldsOf(h).expectedBy.value], ['Corvin D.', 1080]);
  // The latest "Expected by" decides, not the screen's order.
  var swapped = BATCH.replace('Expected by 5:42 PM', 'Expected by 6:10 PM');
  var hs = batchHold('Hollin Ct & Brisk Ln, Marietta');
  run(hs, swapped);
  eq('[batch] the last door is the latest time, wherever it sits on the list',
     hs.dropoff, '88 Hollin Ct, Marietta');
  // A tie goes to the card's street, else the last on screen.
  var tie = BATCH.replace('Expected by 6:00 PM', 'Expected by 5:42 PM');
  var ht = batchHold('Hollin Ct & Brisk Ln, Marietta');
  run(ht, tie);
  var ht2 = batchHold('Brisk Ln & Tarrow Ridge Dr, Marietta');
  run(ht2, tie);
  eq('[batch] a tie in time goes to the dropoff on the card\'s street',
     [ht.dropoff, ht2.dropoff], ['88 Hollin Ct, Marietta', '517 Tarrow Ridge Dr NW, Marietta']);
  // The guard: the card's corner names none of the planner's streets.
  var hx = batchHold('Wexley Pkwy & Brisk Ln, Kennesaw');
  var gx = run(hx, BATCH);
  eq('[batch] a card whose end is on none of the planner\'s dropoffs batches nothing, '
     + 'and says why', [hx.dropoff, !!hx.batch, gx.verdict, A.batchWhy(gx.st, hx)],
     ['Wexley Pkwy & Brisk Ln, Kennesaw', false, 'dropoffs', 'card end elsewhere']);
  var hn = batchHold(null);
  var gn = run(hn, BATCH);
  eq('[batch] ...nor a card that printed no street at all',
     [hn.dropoff, !!hn.batch, A.batchWhy(gn.st, hn)], [null, false, 'no card street']);
  // The list running off the screen: no Waybill under the last stop.
  var hl = batchHold();
  var gl = run(hl, BATCH.replace('\nWaybill', ''));
  eq('[batch] a list whose foot is off the screen batches nothing',
     [hl.dropoff, !!hl.batch, gl.r.candidates.length], [CARD_END, false, 0]);
  var hp = batchHold();
  var stp = A.fresh();
  A.took(stp, hp);
  var gp = A.sighting(stp, hp, pageOf(BATCH, 5000, true), 5000);
  eq('[batch] ...and a PRESS over the list is the press\'s rule: nothing',
     [gp.candidates.length, !!hp.batch], [0, false]);
  // An earlier door without its street: batched without it. The last one
  // without: the order waits.
  var noFirst = BATCH.replace('Address\n88 Hollin Ct\nMarietta, GA\n', '');
  var hf = batchHold();
  run(hf, noFirst);
  eq('[batch] an earlier dropoff with no street is left off, the batch still made',
     [hf.dropoff, (hf.drops || []).length], ['517 Tarrow Ridge Dr NW, Marietta', 1]);
  var noLast = BATCH.replace('Address\n517 Tarrow Ridge Dr NW\nMarietta, GA\n', '');
  var hw = batchHold();
  var gw = run(hw, noLast);
  eq('[batch] ...the last one with no street: nothing filed, the order waits',
     [hw.dropoff, !!hw.batch, A.batchWhy(gw.st, hw)], [CARD_END, false, 'address']);
  // Over the first customer's door a navigation screen filed: replaced by the
  // last. Never over a press.
  var hv = batchHold();
  hv.fields.dropoff = { value: '88 Hollin Ct, Marietta', from: 'nav', conf: 2, at: 3000,
                        screen: 'uber.nav' };
  hv.dropoff = '88 Hollin Ct, Marietta';
  hv.dropoffScanned = true;
  run(hv, BATCH);
  var hq = batchHold();
  hq.fields.dropoff = { value: '88 Hollin Ct, Marietta', from: 'press', conf: 2, at: 3000,
                        screen: 'uber.nav' };
  hq.dropoff = '88 Hollin Ct, Marietta';
  run(hq, BATCH);
  eq('[batch] the last door replaces a first door a screen filed, never a press',
     [hv.dropoff, !!hv.batch, hq.dropoff, !!hq.batch],
     ['517 Tarrow Ridge Dr NW, Marietta', true, '88 Hollin Ct, Marietta', false]);
  // An add-on trip is not a batch: two orders go to sightingMany, and an
  // add-on alone is refused.
  var ha = batchHold(undefined, { addOn: true, of: 'x@1' });
  var ga = run(ha, BATCH);
  eq('[batch] an add-on\'s hold is no batch', [!!ha.batch, A.batchWhy(ga.st, ha)],
     [false, 'an add-on']);
  var root = batchHold(), add = batchHold(undefined, { id: 'b-2', acceptedAt: 2000,
                                                       addOn: true, of: 'b-1@1000' });
  var sm = A.fresh();
  A.took(sm, [root, add]);
  var cm = A.sighting(sm, [root, add], pageOf(BATCH, 5000), 5000).candidates;
  eq('[batch] ...and two orders held never make one', cm.some(function (c) {
    return !!c.batch;
  }), false);
  eq('[batch] the same list read again files nothing twice',
     run(h, BATCH, 6000, got.st).r.candidates.length, 0);
  eq('[batch] the card\'s streets: a corner\'s two, a door\'s one, a town none',
     [A.cardStreets(CARD_END), A.cardStreets('40 Quarrel St, Smyrna'),
      A.cardStreets('Marietta, GA')], [['tarrow ridge', 'brisk'], ['quarrel'], []]);

  // The mutation catch-up of 21 Oct: one check per guard nothing held.
  eq('[batch] ...a corner printed with "and", "at" or "/" is two streets too',
     ['Tarrow Ridge Dr and Brisk Ln, Marietta', 'Tarrow Ridge Dr at Brisk Ln, Marietta',
      'Tarrow Ridge Dr / Brisk Ln, Marietta'].map(A.cardStreets),
     [['tarrow ridge', 'brisk'], ['tarrow ridge', 'brisk'], ['tarrow ridge', 'brisk']]);
  eq('[batch] streetCore: a house number makes a street of a name with no type word',
     [A.streetCore('40 Quarrel'), A.streetCore('Quarrel')], ['quarrel', null]);
  function drop(street, at, city) {
    return { kind: 'dropoff', orders: 1, name: 'C. ' + at, expectedBy: at, street: street,
             city: city === undefined ? 'Marietta' : city };
  }
  eq('[batch] batchPlan: one dropoff is no batch',
     A.batchPlan(batchHold(), [drop('517 Tarrow Ridge Dr NW', 1080)]).why, 'one dropoff');
  eq('[batch] ...an add-on by either mark is none: `addOn` alone, `of` alone',
     [A.batchPlan(batchHold(undefined, { addOn: true }), [drop('88 Hollin Ct', 1062),
       drop('517 Tarrow Ridge Dr NW', 1080)]).why,
      A.batchPlan(batchHold(undefined, { of: 'x@1' }), [drop('88 Hollin Ct', 1062),
       drop('517 Tarrow Ridge Dr NW', 1080)]).why], ['an add-on', 'an add-on']);
  eq('[batch] ...a last door with its street and no town waits as \'address\'',
     A.batchPlan(batchHold(), [drop('88 Hollin Ct', 1062),
                               drop('517 Tarrow Ridge Dr NW', 1080, null)]).why, 'address');
  // A tie with BOTH doors on the card's streets: the last on the screen.
  var hb = batchHold('Hollin Ct & Tarrow Ridge Dr, Marietta');
  run(hb, tie);
  eq('[batch] a tie with both doors on the card\'s streets goes to the last on the screen',
     hb.dropoff, '517 Tarrow Ridge Dr NW, Marietta');
  // Past midnight: 12:10 AM is after 11:50 PM, wherever it sits.
  var late = BATCH.replace('Expected by 5:42 PM', 'Expected by 12:10 AM')
    .replace('Expected by 6:00 PM', 'Expected by 11:50 PM');
  var hm = batchHold();
  run(hm, late);
  eq('[batch] a trip past midnight: 12:10 AM is the last door, not 11:50 PM',
     hm.dropoff, '88 Hollin Ct, Marietta');
  // A dropoff that printed no time: the last on the screen, whatever the others say.
  var untimed = BATCH.replace('Vesna R.\nExpected by 5:42 PM\n', 'Vesna R.\n');
  var hu = batchHold('Hollin Ct & Tarrow Ridge Dr, Marietta');
  run(hu, untimed);
  eq('[batch] ...a door with no time on the list: the last on the screen',
     hu.dropoff, '517 Tarrow Ridge Dr NW, Marietta');
  // More picked up than dropped off: a header lost, so no batch.
  var hs2 = batchHold();
  var gs2 = run(hs2, BATCH.replace('Pickup • 1 order\nOrrin', 'Pickup • 2 orders\nOrrin'));
  eq('[batch] a list whose pickups carry more orders than its dropoffs batches nothing',
     [hs2.dropoff, !!hs2.batch, gs2.r.candidates.length], [CARD_END, false, 0]);
  eq('[batch] the sighting that batched says no reason either',
     got.r.why, null);
  eq('[batch] batchWhy is the refusal for THIS hold only',
     [A.batchWhy(gx.st, hx), A.batchWhy(gx.st, batchHold(undefined, { id: 'b-9' }))],
     ['card end elsewhere', null]);
  eq('[batch] a batch\'s reads are not one stop\'s readings: no house tally',
     h.dropoffReads, undefined);
  // The planner line's 'dropoffs' from before the batch goes with it.
  var hd = batchHold();
  hd.planner = { stops: [], unfiled: 'dropoffs' };
  run(hd, BATCH);
  eq('[batch] the hold\'s planner line loses its "dropoffs" when the batch files',
     [hd.planner.unfiled, hd.batch], [null, true]);
  // The last door filed alone first (its own list, one dropoff), then the list
  // of both: the batch is recorded over the same door.
  var ONE = BATCH.replace(/Dropoff • 1 order\nVesna R\.\nExpected by 5:42 PM\nAddress\n88 Hollin Ct\nMarietta, GA\n/, '')
    .replace('Pickup • 1 order\nOrrin Noodle Co\nExpected by 5:26 PM\nAddress\n12 Pellow Ave\nSmyrna, GA\n', '');
  var h1 = batchHold();
  var st1 = run(h1, ONE, 4000).st;
  var mid = [h1.dropoff, !!h1.batch];
  run(h1, BATCH, 5000, st1);
  eq('[batch] the last door filed alone first, then the list of both: the batch is recorded',
     [mid, h1.dropoff, h1.batch, (h1.drops || []).length],
     [['517 Tarrow Ridge Dr NW, Marietta', false], '517 Tarrow Ridge Dr NW, Marietta', true, 2]);
})();

/* ---- the most-read reading of one planner stop (the owner, 19 Oct 21:41) ----
 * "305 <Name> Dr" read once and filed, "905 <Name> Dr" every read after: the
 * same stop key, as complete, so outranks() alone kept "305". Invented. */
(function () {
  var KEY = 'dropoff|Mara T.|1202';
  function hold() {
    var h = { id: 'o', acceptedAt: 1000, pickup: 'Fable Grill', dropoff: null,
              dropoffScanned: false, card: { legs: 1, multiOrder: false } };
    A.fieldsOf(h);
    return h;
  }
  function read(house, key, at) {
    var street = house + ' Quillon Dr';
    return { found: true, line: street + ', Smyrna', street: street, city: 'Smyrna',
             state: 'GA', zip: null, asked: false, labelled: 'dropoff', planner: true,
             at: at || 2000, key: key || KEY };
  }
  function say(h, d) {
    if (A.plannerVote(h, d)) d.vote = true;
    var said = A.dropoff(h, d, null);
    A.file(h, d, said);
    return said.why;
  }
  var h = hold();
  var whys = [say(h, read('305')), say(h, read('905')), say(h, read('905'))];
  eq('[vote] "305" filed once, then "905" twice: the tie keeps "305", the third read files "905"',
     [whys, h.dropoff], [['blank', 'outranked by planner', 'most read'], '905 Quillon Dr, Smyrna']);
  eq('[vote] ...and "905" stays on a fourth read of it, and a lone "305" back does not undo it',
     [say(h, read('905')), say(h, read('305')), h.dropoff],
     ['outranked by planner', 'outranked by planner', '905 Quillon Dr, Smyrna']);
  h = hold();
  say(h, read('305'));
  [read('905', 'dropoff|Orrin B.|1220'), read('905', 'dropoff|Orrin B.|1220'),
   read('905', 'dropoff|Orrin B.|1220')].forEach(function (d) { say(h, d); });
  eq('[vote] never across stops: another key\'s reads do not move the filed one',
     h.dropoff, '305 Quillon Dr, Smyrna');
  h = hold();
  var pr = Object.assign(read('305'), { asked: true, labelled: null, key: undefined });
  say(h, pr);
  [1, 2, 3].forEach(function () { say(h, read('905')); });
  eq('[vote] never over a press', [h.dropoff, h.fields.dropoff.from],
     ['305 Quillon Dr, Smyrna', 'press']);
  h = hold();
  say(h, read('305'));
  say(h, read('905'));
  say(h, read('605'));
  eq('[vote] three readings once each: the filed one stays', h.dropoff, '305 Quillon Dr, Smyrna');
  h = hold();
  say(h, read('305'));
  for (var i = 0; i < A.VOTE_READS; i++) say(h, read('305'));
  say(h, read('905'));
  say(h, read('905'));
  eq('[vote] only the last ' + A.VOTE_READS + ' reads count: "305" ×6 then "905" ×2 keeps "305"',
     [h.dropoff, h.dropoffReads.reads.length], ['305 Quillon Dr, Smyrna', A.VOTE_READS]);

  // The mutation catch-up of 21 Oct: one check per guard nothing held.
  h = hold();
  say(h, read('305'));
  eq('[vote] a pressed read is not counted, nor a read that is no planner stop\'s',
     [A.plannerVote(h, Object.assign(read('905'), { asked: true })),
      A.plannerVote(h, Object.assign(read('905'), { asked: true })),
      A.plannerVote(h, Object.assign(read('905'), { planner: false })),
      A.plannerVote(h, Object.assign(read('905'), { planner: false })), h.dropoffReads.reads],
     [false, false, false, false, ['305 quillon dr']]);
  eq('[vote] ...nor a read whose street did not read',
     [A.plannerVote(h, Object.assign(read('905'), { line: '' })),
      A.plannerVote(h, Object.assign(read('905'), { line: '' })), h.dropoffReads.reads],
     [false, false, ['305 quillon dr']]);
  h = hold();
  say(h, read('305'));
  eq('[vote] another stop\'s reads start their own tally, and never win over the filed stop',
     [A.plannerVote(h, read('905', 'dropoff|Orrin B.|1220')),
      A.plannerVote(h, read('905', 'dropoff|Orrin B.|1220')), h.dropoffReads],
     [false, false, { key: 'dropoff|Orrin B.|1220', reads: ['905 quillon dr', '905 quillon dr'] }]);
  h = hold();
  say(h, read('305'));
  say(h, read('305'));
  say(h, read('305'));
  say(h, read('905', 'dropoff|Orrin B.|1220'));
  eq('[vote] ...so back on the filed stop the tally is anew: one "905" now outvotes the filed one',
     [say(h, read('905')), h.dropoff], ['most read', '905 Quillon Dr, Smyrna']);
  h = hold();
  say(h, Object.assign(read('305'), { asked: true, labelled: null }));
  eq('[vote] a press filed with the stop\'s own key: nothing voted over it',
     [h.fields.dropoff.key, A.plannerVote(h, read('905')), A.plannerVote(h, read('905'))],
     [KEY, false, false]);
  h = hold();
  say(h, read('305'));
  h.dropoffReads = { key: KEY, reads: ['605 quillon dr', '605 quillon dr', '605 quillon dr'] };
  eq('[vote] a line read more often than the filed one, but less than another, is not the most read',
     A.plannerVote(h, read('905')), false);
  // dropoff() asks the vote's own rules again of a `vote` it is handed.
  h = hold();
  say(h, read('305'));
  eq('[vote] dropoff(): a `vote` never moves another stop\'s end, nor files a read no label proved',
     [A.dropoff(h, Object.assign(read('905', 'dropoff|Orrin B.|1220'), { vote: true }), null).why,
      A.dropoff(h, Object.assign(read('905', KEY, 500), { vote: true }), null).why],
     ['outranked by planner', 'outranked by planner']);
  h = hold();
  say(h, Object.assign(read('305'), { planner: false }));
  eq('[vote] ...nor an end a label filed, the same key on it',
     [h.fields.dropoff.from,
      A.dropoff(h, Object.assign(read('905'), { vote: true }), null).why],
     ['label', 'outranked by label']);
})();

/* ---- the most-read reading through sighting(): the dedupe lets the winner by ---- */
(function () {
  var PAGE = 'Trip Planner\nPickup • 1 order\nFable Grill\nExpected by 7:40 PM\n'
    + 'Address\n40 Quarrel St\nSmyrna, GA\n'
    + 'Dropoff • 1 order\nMara T.\nExpected by 8:02 PM\nAddress\n305 Quillon Dr\nSmyrna, GA\n'
    + 'Waybill';
  var h = { id: 'o', acceptedAt: 1000, tookAt: 1005, pickup: 'Fable Grill', dropoff: null,
            dropoffScanned: false, card: { legs: 1, multiOrder: false } };
  A.fieldsOf(h);
  var st = A.fresh();
  A.took(st, h);
  var whys = [];
  [['305', 2000], ['905', 30000], ['905', 60000]].forEach(function (r) {
    var text = PAGE.replace('305 Quillon Dr', r[0] + ' Quillon Dr');
    A.sighting(st, h, pageOf(text, r[1]), r[1]).candidates.forEach(function (c) {
      var said = A.dropoff(h, c, null);
      A.file(h, c, said, st);
      whys.push(said.why);
    });
  });
  eq('[vote] through sighting(): "305" filed, "905" tied, and "905" read again gets past the '
     + 'once-per-line dedupe as the most read',
     [whys, h.dropoff], [['blank', 'outranked by planner', 'most read'],
                         '905 Quillon Dr, Smyrna']);
})();

/* ---- a card-box read of the planner over a garbled planner street (the
 * owner, 20 Oct 20:44) ----
 * "2100 <Ellison> Lakes Dr" read whole-screen as "2100 <Ellison> Lake r" and
 * filed from 'planner'; every read after was a card-box read, a dropoff line
 * under a Dropoff label (rank `label`, no key), clean. Invented. */
(function () {
  var KEY = 'dropoff|Mara T.|1202';
  function hold() {
    var h = { id: 'o', acceptedAt: 1000, pickup: 'Fable Grill', dropoff: null,
              dropoffScanned: false, card: { legs: 1, multiOrder: false } };
    A.fieldsOf(h);
    return h;
  }
  function line(street, more) {
    return Object.assign({ found: true, line: street + ', Kennesaw', street: street,
                           city: 'Kennesaw', state: 'GA', zip: null, asked: false,
                           labelled: 'dropoff', screen: 'uber.planner', at: 2000 }, more || {});
  }
  // The whole-screen planner read, as sighting() makes it.
  function planner(street, key) { return line(street, { planner: true, key: key || KEY }); }
  function say(h, d) {
    if (A.plannerVote(h, d)) d.vote = true;
    var said = A.dropoff(h, d, null);
    A.file(h, d, said);
    return said.why;
  }
  var h = hold();
  var whys = [say(h, planner('2100 Quillon Lake r')), say(h, line('2100 Quillon Lakes Dr'))];
  eq('[box typed] a box read "2100 Quillon Lakes Dr" replaces the planner\'s "2100 Quillon Lake r", '
     + 'at its own rank', [whys, h.dropoff, h.fields.dropoff.from],
     [['blank', 'typed street'], '2100 Quillon Lakes Dr, Kennesaw', 'label']);
  eq('[box typed] ...and the garbled one read again is not taken back',
     [say(h, line('2100 Quillon Lake r')), say(h, planner('2100 Quillon Lake r')), h.dropoff],
     ['outranked by label', 'outranked by label', '2100 Quillon Lakes Dr, Kennesaw']);
  h = hold();
  say(h, planner('2100 Quillon Lake r'));
  eq('[box typed] ...a whole-screen planner read of another stop key, typed, replaces it too',
     [say(h, planner('2100 Quillon Lakes Dr NW', 'dropoff|Mara T.|1205')), h.fields.dropoff.from],
     ['typed street', 'planner']);
  h = hold();
  say(h, planner('2100 Quillon Commor'));
  eq('[box typed] ...and a filed street with no type at all: "2100 Quillon Commor"',
     [say(h, line('2100 Quillon Commons Ln')), h.dropoff],
     ['typed street', '2100 Quillon Commons Ln, Kennesaw']);
  h = hold();
  say(h, planner('2100 Quillon Lake r'));
  eq('[box typed] never another house number', [say(h, line('2110 Quillon Lakes Dr')), h.dropoff],
     ['outranked by planner', '2100 Quillon Lake r, Kennesaw']);
  h = hold();
  say(h, planner('2100 Quillon Lakes Ct'));
  eq('[box typed] never one typed street over another', say(h, line('2100 Quillon Lakes Dr')),
     'outranked by planner');
  h = hold();
  say(h, line('2100 Quillon Lake r', { asked: true, labelled: null }));
  eq('[box typed] never over a press', [say(h, line('2100 Quillon Lakes Dr')),
                                        h.fields.dropoff.from], ['outranked by press', 'press']);
  h = hold();
  say(h, line('2100 Quillon Lake r'));
  eq('[box typed] never over a label read: the filed street must be the planner\'s',
     say(h, line('2100 Quillon Lakes Dr')), 'outranked by label');
  h = hold();
  say(h, planner('2100 Quillon Lake r'));
  eq('[box typed] never a read no label proved, nor one older than the Took',
     [say(h, line('2100 Quillon Lakes Dr', { labelled: null })),
      say(h, line('2100 Quillon Lakes Dr', { at: 500 })), h.dropoff],
     ['outranked by planner', 'outranked by planner', '2100 Quillon Lake r, Kennesaw']);

  // The house vote counts the box reads (labelVote).
  h = hold();
  whys = [say(h, planner('305 Quillon Dr')), say(h, line('905 Quillon Dr')),
          say(h, planner('905 Quillon Dr'))];
  eq('[box vote] "305" filed, a box read of "905" counted, and the planner\'s first "905" wins',
     [whys, h.dropoff, h.dropoffReads.reads],
     [['blank', 'outranked by planner', 'most read'], '905 Quillon Dr, Kennesaw',
      ['305 quillon dr', '905 quillon dr', '905 quillon dr']]);
  h = hold();
  whys = [say(h, planner('305 Quillon Dr')), say(h, line('905 Quillon Dr')),
          say(h, line('905 Quillon Dr'))];
  eq('[box vote] ...and two box reads of "905" win alone, filed at their own rank',
     [whys, h.dropoff, h.fields.dropoff.from],
     [['blank', 'outranked by planner', 'most read'], '905 Quillon Dr, Kennesaw', 'label']);
  h = hold();
  say(h, line('305 Quillon Dr', { asked: true, labelled: null }));
  [1, 2, 3].forEach(function () { say(h, line('905 Quillon Dr')); });
  eq('[box vote] never over a press, and nothing counted against one',
     [h.dropoff, h.dropoffReads || null], ['305 Quillon Dr, Kennesaw', null]);
  h = hold();
  say(h, planner('305 Quillon Dr'));
  eq('[box vote] a tie keeps the filed one', say(h, line('905 Quillon Dr')), 'outranked by planner');

  // The mutation catch-up of 21 Oct: one check per guard nothing held.
  h = hold();
  say(h, planner('2100 Quillon Lake r'));
  eq('[box typed] never a navigation screen\'s read', say(h, line('2100 Quillon Lakes Dr',
     { nav: true, screen: 'uber.nav' })), 'outranked by planner');
  h = hold();
  say(h, Object.assign(planner('305 Quillon Dr'), { asked: true, labelled: null }));
  [1, 2, 3].forEach(function () { say(h, line('905 Quillon Dr')); });
  eq('[box vote] never over a press that carries the planner stop\'s key, nothing counted',
     [h.fields.dropoff.key, h.dropoff, h.dropoffReads || null],
     [KEY, '305 Quillon Dr, Kennesaw', null]);
  h = hold();
  say(h, line('305 Quillon Dr', { planner: true }));
  [1, 2, 3].forEach(function () { say(h, line('905 Quillon Dr')); });
  eq('[box vote] a planner end filed with no stop key has no tally to count in',
     [h.dropoff, h.dropoffReads || null], ['305 Quillon Dr, Kennesaw', null]);
  h = hold();
  say(h, planner('305 Quillon Dr'));
  say(h, planner('305 Quillon Dr', 'dropoff|Orrin B.|1220'));
  whys = [say(h, line('905 Quillon Dr')), say(h, line('905 Quillon Dr'))];
  eq('[box vote] a tally of another stop is started anew from the filed line: one box read '
     + 'ties, the second wins', [whys, h.dropoffReads.key],
     [['outranked by planner', 'most read'], KEY]);
  h = hold();
  say(h, planner('305 Quillon Dr'));
  for (var i = 0; i < A.VOTE_READS; i++) say(h, planner('305 Quillon Dr'));
  whys = [1, 2, 3].map(function () { return say(h, line('905 Quillon Dr')); });
  eq('[box vote] only the last ' + A.VOTE_READS + ' reads count: "305" ×6, then the third box '
     + '"905" wins', [whys, h.dropoffReads.reads.length],
     [['outranked by planner', 'outranked by planner', 'most read'], A.VOTE_READS]);
  h = hold();
  say(h, planner('305 Quillon Dr'));
  [1, 2, 3].forEach(function () { say(h, line('', { line: '', street: null })); });
  eq('[box vote] a box read whose street did not read is not counted',
     [h.dropoff, h.dropoffReads.reads], ['305 Quillon Dr, Kennesaw', ['305 quillon dr']]);
})();

/* ---- the card's own street (the owner, 20 Oct 19:06–19:08) ----
 *
 * An Uber order held off a card whose end is a corner, an add-on on its
 * trip, and the Trip Planner seen only in pages scrolled: the order's door by
 * `cardStreet`, the add-on's by elimination after it. Streets and names
 * invented. */
(function () {
  function order(id, at, more) {
    var o = Object.assign({ id: id, acceptedAt: at, tookAt: at + 5, holdId: id + '@' + at,
                            minutes: 40, app: 'uber', pickup: null, deliverBy: null,
                            dropoff: null, dropoffScanned: false }, more || {});
    // ...and what its card printed, as server.js keeps it at the Took.
    o.seenAs = { dropoff: o.dropoff, tookAt: o.tookAt };
    A.fieldsOf(o);
    return o;
  }
  var CORNER = 'Larkspur Rd NW & Ombre Cir NW, Kennesaw';
  function trip() {
    var root = order('r', 1000, { dropoff: CORNER, pickup: 'Fable Grill' });
    var add = order('x', 5000, { addOn: true, of: root.holdId, pickup: 'Kestrel Noodle Bar' });
    return [root, add];
  }
  function pd(line, street, more) {
    return Object.assign({ line: line, street: street, city: 'Kennesaw', at: 9000,
                           app: 'uber', asked: false, labelled: 'dropoff', planner: true,
                           screen: 'uber.planner', partial: true, bounded: false }, more || {});
  }
  var DOOR = pd('1800 Ombre Circle, Kennesaw', '1800 Ombre Circle');
  var OTHER = pd('608 Wickerby St NW, Marietta', '608 Wickerby St NW', { city: 'Marietta' });
  function who(orders, x, st) {
    var r = A.attribute(st || A.fresh(), orders, x);
    return [r.order ? r.order.id : null, r.cue, r.why];
  }
  var t = trip();
  eq('[cardStreet] a planner door on one side of the card\'s corner is that order\'s, '
     + 'type and quadrant aside', who(t, DOOR), ['r', 'cardStreet', null]);
  eq('[cardStreet] ...and its other side too',
     who(t, pd('22 Larkspur Road, Kennesaw', '22 Larkspur Road')), ['r', 'cardStreet', null]);
  eq('[cardStreet] a door on no card\'s street, nothing filed yet: no cue (it waits)',
     who(t, OTHER), [null, null, 'no cue']);
  var same = [order('r', 1000, { dropoff: CORNER }),
              order('y', 5000, { dropoff: '40 Ombre Cir NW, Kennesaw' })];
  eq('[cardStreet] two cards naming the same street: no cue',
     who(same, DOOR), [null, null, 'no cue']);
  eq('[cardStreet] never over a press: a pressed read is the chooser\'s',
     who(t, Object.assign({}, DOOR, { asked: true })), [null, null, 'no cue']);
  eq('[cardStreet] never a pickup: a held order\'s store on the card\'s street',
     who([order('r', 1000, { dropoff: CORNER, pickup: 'Fable Grill (1800 Ombre Circle)' }),
          t[1]], DOOR), [null, null, 'no cue']);
  eq('[cardStreet] a partial read before the add-on\'s Took is no `only` for the original',
     who(t, Object.assign({}, OTHER, { at: 3000 })), [null, null, 'no cue']);
  // The first door filed by cardStreet, as server.js files it.
  A.file(t[0], DOOR, A.dropoff(t[0], DOOR, null), null);
  eq('[cardStreet] the premise: the original\'s end is the planner door',
     [t[0].dropoff, t[0].fields.dropoff.from], ['1800 Ombre Circle, Kennesaw', 'planner']);
  eq('[elimination] ...then a different door of the trip, on no card\'s street, is the '
     + 'add-on\'s', who(t, OTHER), ['x', 'elimination', null]);
  eq('[elimination] ...but not from a read before the add-on\'s Took',
     who(t, Object.assign({}, OTHER, { at: 4000 })), [null, null, 'no cue']);
  eq('[elimination] ...nor the first order\'s own door read again',
     who(t, pd('1800 Ombre Circle, Kennesaw', '1800 Ombre Circle')), ['r', 'cardStreet', null]);
  var t2 = trip();
  A.file(t2[0], DOOR, A.dropoff(t2[0], DOOR, null), null);
  A.file(t2[1], OTHER, { to: 'hold', from: 'nav' }, null);
  eq('[elimination] ...nor when the add-on already has an end the screen filed',
     who(t2, pd('9 Elm Ct, Marietta', '9 Elm Ct')), [null, null, 'no cue']);
  var t3 = trip();
  A.file(t3[0], DOOR, { to: 'hold', from: 'press' }, null);
  eq('[elimination] ...nor off a first door the driver pressed for',
     who(t3, OTHER), [null, null, 'no cue']);
  // The pages as sightingMany reads them: two pages, neither the list whole.
  var st = A.fresh();
  var t4 = trip();
  function page(at, top, drops) {
    return { at: at, asked: false, whole: true, titled: top, app: 'uber',
             screen: 'uber.planner', page: { top: top, bottom: false }, orderCount: null,
             keep: false,
             stops: drops.map(function (x) {
               return { kind: 'dropoff', orders: 1, name: x[0], expectedBy: x[3],
                        street: x[1], city: x[2], state: 'GA', zip: null,
                        line: x[1] + ', ' + x[2], partial: null };
             }) };
  }
  var c1 = A.sighting(st, t4, page(9000, true, [['Ines B.', '608 Wickerby St NW', 'Marietta',
                                                 1188]]), 9000).candidates;
  var c2 = A.sighting(st, t4, page(9500, false, [['Rhea A.', '1800 Ombre Cir NW', 'Kennesaw',
                                                  1170]]), 9500).candidates;
  eq('[cardStreet] a list never seen whole still offers its dropoffs, `partial`',
     [c1.map(function (c) { return [c.line, c.partial, c.store, c.listDrops]; }),
      c2.map(function (c) { return c.line; })],
     [[['608 Wickerby St NW, Marietta', true, null, null]], ['1800 Ombre Cir NW, Kennesaw']]);
  A.park(st, c1[0], t4);
  var a2 = A.attribute(st, t4, c2[0]);
  A.file(a2.order, c2[0], A.dropoff(a2.order, c2[0], null), st);
  var back = A.retryUnowned(st, t4);
  eq('[cardStreet] the snap: the order\'s door by cardStreet, then the waiting door by '
     + 'elimination, out of the pool',
     [a2.order.id, a2.cue, back.map(function (f) { return [f.d.line, f.order.id, f.cue]; }),
      A.unowned(st)],
     ['r', 'cardStreet', [['608 Wickerby St NW, Marietta', 'x', 'elimination']], 0]);
  eq('[cardStreet] no card street on any held order: a list not seen whole offers nothing',
     A.sighting(A.fresh(), [order('p', 1000), order('q', 5000)],
                page(9000, true, [['Ines B.', '608 Wickerby St NW', 'Marietta', 1188]]),
                9000).candidates, []);

  // The mutation catch-up of 21 Oct: one check per guard nothing held.
  eq('[cardStreet] only a Trip Planner\'s dropoff: a box or navigation read on the card\'s '
     + 'street is no cue', who(t, Object.assign({}, DOOR, { planner: false })), [null, null, 'no cue']);
  eq('[cardStreet] ...nor with one order held: a partial read is nobody\'s by the card alone',
     who([trip()[0]], DOOR), [null, null, 'no cue']);
  var p6 = [order('p', 1000, { dropoff: '9 Elm Ct, Marietta' }), order('q', 5000, { dropoff: CORNER })];
  eq('[cardStreet] ...nor the card of an order taken after the read',
     who(p6, Object.assign({}, DOOR, { at: 3000 })), [null, null, 'no cue']);
  var t5 = trip();
  A.file(t5[0], pd('5 Elm Ct, Marietta', '5 Elm Ct'), { to: 'hold', from: 'press' }, null);
  eq('[cardStreet] ...nor onto an order whose end the driver pressed', who(t5, DOOR),
     [null, null, 'no cue']);
  var t6 = trip();
  t6[0].planner = { stops: [{ kind: 'pickup', street: '1800 Ombre Circle',
                              line: '1800 Ombre Circle, Kennesaw' }] };
  var t7 = trip();
  t7[0].fields.pickupAddr = { value: '1800 Ombre Circle, Kennesaw', from: 'planner', conf: 2 };
  eq('[cardStreet] never a pickup by the planner\'s own pickups, nor by a pickup address filed',
     [who(t6, DOOR), who(t7, DOOR)], [[null, null, 'no cue'], [null, null, 'no cue']]);
  // Two cards naming the street: no cue, and no elimination either, though
  // one order's end is on a street its card alone names.
  var s2 = [order('r', 1000, { dropoff: CORNER }),
            order('y', 5000, { dropoff: '40 Ombre Cir NW, Kennesaw' })];
  A.file(s2[0], pd('22 Larkspur Road, Kennesaw', '22 Larkspur Road'),
         A.dropoff(s2[0], pd('22 Larkspur Road, Kennesaw', '22 Larkspur Road'), null), null);
  eq('[cardStreet] two cards naming the door\'s street: no cue, nor elimination off the other',
     who(s2, DOOR), [null, null, 'no cue']);
  function firstFiled(more) {
    var o = trip();
    if (more) Object.assign(o[1], more);
    A.file(o[0], DOOR, A.dropoff(o[0], DOOR, null), null);
    return o;
  }
  var e1 = firstFiled();
  e1[1] = order('y', 5000, { app: 'doordash' });
  eq('[elimination] ...not onto an order of another app', who(e1, OTHER), [null, null, 'no cue']);
  var e2 = firstFiled();
  delete e2[1].tookAt;
  eq('[elimination] ...nor onto an order with no Took time on record', who(e2, OTHER),
     [null, null, 'no cue']);
  var e3 = [order('r', 1000, { dropoff: CORNER }),
            order('x', 5000, { addOn: true, of: 'r@1000', dropoff: 'Ombre Cir NW, Kennesaw' })];
  A.file(e3[0], DOOR, A.dropoff(e3[0], DOOR, null), null);
  eq('[elimination] ...nor off a first door whose street the other card names too',
     who(e3, OTHER), [null, null, 'no cue']);
  // A partial read is decided by the card's street ALONE: no store, deadline
  // or filed cue, even handed one.
  var tc = [order('r', 1000, { dropoff: CORNER, pickup: 'Fable Grill' }),
            order('x', 5000, { addOn: true, of: 'r@1000', pickup: 'Kestrel Noodle Bar',
                               deliverBy: 1188 })];
  eq('[cardStreet] a partial read: no store cue, no deadline cue',
     [who(tc, Object.assign({}, OTHER, { store: 'Kestrel Noodle Bar' })),
      who(tc, Object.assign({}, OTHER, { expectedBy: 1188 }))],
     [[null, null, 'no cue'], [null, null, 'no cue']]);
  var tf = trip();
  A.file(tf[1], OTHER, { to: 'hold', from: 'nav' }, null);
  eq('[cardStreet] ...and no `filed` cue, though marked bounded and on an order\'s filed end',
     who(tf, Object.assign({}, OTHER, { bounded: true, others: [] })), [null, null, 'no cue']);
  // sightingMany: a pressed page is not offered partial; a page's one pickup
  // is no store for its one dropoff; a page read again offers nothing again.
  var sp = A.fresh();
  var tp = trip();
  eq('[cardStreet] a PRESSED list not seen whole offers nothing',
     A.sighting(sp, tp, Object.assign(page(9000, true, [['Ines B.', '608 Wickerby St NW',
                                                         'Marietta', 1188]]), { asked: true }),
                9000).candidates, []);
  var pk = page(9000, true, [['Ines B.', '608 Wickerby St NW', 'Marietta', 1188]]);
  pk.stops.unshift({ kind: 'pickup', orders: 1, name: 'Kestrel Noodle Bar', expectedBy: 1160,
                     street: '12 Pellow Ave', city: 'Smyrna', state: 'GA', zip: null,
                     line: '12 Pellow Ave, Smyrna', partial: null });
  var sq = A.fresh();
  var cq = A.sighting(sq, trip(), pk, 9000).candidates;
  eq('[cardStreet] ...a page\'s one pickup is no store for its dropoff, and the page read again '
     + 'offers nothing', [cq.map(function (c) { return [c.line, c.store]; }),
                          A.sighting(sq, trip(), Object.assign({}, pk, { at: 9200 }), 9200)
                            .candidates.length],
     [[['608 Wickerby St NW, Marietta', null]], 0]);
})();

/* ---- a single trip's dropoff whose header the reader lost (the owner, 20 Oct 21:08) ----
 *
 * tests/fixtures/cases.json's "a single trip's dropoff whose header the reader
 * lost…" (names and streets invented): "Dropoff · 1 order" lost to OCR on a
 * whole-screen read, the customer's door under the pickup's "View details",
 * and the hold kept the card's end, "<Name> Creek Bivd, Marietta", no house
 * number. The parser keeps the stop `partial: 'header'`; this files it only
 * where the held card names its street (lostHeaderDropoff). */
(function () {
  var text = null;
  require('./fixtures/cases.json').planner.forEach(function (c) {
    if (/^a single trip's dropoff whose header the reader lost/.test(c.name)) text = c.text;
  });
  ok_('[lost header] the premise: the case is there', !!text);
  if (!text) return;
  function single(end, more) {
    var h = Object.assign({ id: 'o', acceptedAt: 1000, tookAt: 1005, holdId: 'o@1000',
                            card: { legs: 1, multiOrder: false }, app: 'uber',
                            pickup: 'Fable Steakhouse (810 Ardley West Corwin Parkway)',
                            dropoff: end, dropoffScanned: false }, more || {});
    h.seenAs = { dropoff: end, tookAt: h.tookAt };
    A.fieldsOf(h);
    return h;
  }
  var END = 'Tansy Creek Bivd, Marietta';
  var p = pageOf(text, 2000, false);
  eq('[lost header] the premise: the page is the planner, its dropoff kept as header-lost, '
     + 'not bounded, not laid out',
     [p.screen, p.stops.map(function (s) { return [s.kind, s.orders, s.partial]; }),
      p.page.top || p.page.bottom, p.laidOut],
     ['uber.planner', [['pickup', 1, null], ['dropoff', null, 'header']], false, false]);
  var h = single(END);
  var c = A.sighting(A.fresh(), h, p, 2000).candidates;
  eq('[lost header] unprompted, on a card whose end names the street ("Bivd" the reader\'s '
     + 'Blvd), the door is a candidate, a single trip\'s',
     c.map(function (x) { return [x.line, x.asked, x.singleCardOnly, x.labelled]; }),
     [['2400 Tansy Creek Blvd, Marietta', false, true, 'dropoff']]);
  var said = A.dropoff(h, c[0], null);
  A.file(h, c[0], said, null);
  eq('[lost header] ...and is filed over the card\'s own end, from the planner',
     [said.to, said.from, h.dropoff, h.fields.dropoff.from],
     ['hold', 'planner', '2400 Tansy Creek Blvd, Marietta', 'planner']);
  eq('[lost header] a press on the same page files nothing (a press\'s rule is one dropoff '
     + 'read whole)', A.sighting(A.fresh(), single(END), pageOf(text, 2000, true), 2000)
       .candidates.length, 0);
  eq('[lost header] a card whose end names another street, a town only, or nothing: nothing',
     [single('Quillon Way, Marietta'), single('Marietta, GA'), single(null)].map(function (o) {
       return A.sighting(A.fresh(), o, pageOf(text, 2000, false), 2000).candidates.length;
     }), [0, 0, 0]);
  eq('[lost header] an add-on trip\'s order: nothing (its list is two orders\')',
     A.sighting(A.fresh(), single(END, { addOn: true, of: 'r@1' }), pageOf(text, 2000, false),
                2000).candidates.length, 0);
  var two = single(END, { card: { legs: 2, multiOrder: false } });
  var c2 = A.sighting(A.fresh(), two, pageOf(text, 2000, false), 2000).candidates;
  eq('[lost header] a card of two legs: the candidate is refused as not a single trip',
     [c2.length, A.dropoff(two, c2[0], null).why], [1, 'not a single trip']);
  var early = single(END);
  var ce = A.sighting(A.fresh(), early, pageOf(text, 900, false), 900).candidates;
  eq('[lost header] read before the Took: nothing filed',
     ce.map(function (x) { return A.dropoff(early, x, null).to; }), [null]);
  var other = { id: 'q', acceptedAt: 1500, tookAt: 1505, holdId: 'q@1500', app: 'uber',
                card: { legs: 1, multiOrder: false }, pickup: 'Kestrel Noodle Bar',
                dropoff: '903 Brindle Ct, Acworth', dropoffScanned: false };
  other.seenAs = { dropoff: other.dropoff, tookAt: other.tookAt };
  A.fieldsOf(other);
  var pair = [single(END), other];
  var cm = A.sighting(A.fresh(), pair, pageOf(text, 2000, false), 2000).candidates;
  var r = cm.length ? A.attribute(A.fresh(), pair, cm[0]) : {};
  eq('[lost header] with two orders held it is a `partial` candidate, and only the card\'s '
     + 'street files it, on the order whose card names it',
     [cm.map(function (x) { return [x.line, x.partial]; }), r.order && r.order.id, r.cue],
     [[['2400 Tansy Creek Blvd, Marietta', true]], 'o', 'cardStreet']);
  eq('[lost header] lostHeaderDropoff: a dropoff whose header read is not this rule\'s',
     A.lostHeaderDropoff(single(END), [
       { kind: 'pickup', orders: 1, street: '810 Ardley West Corwin Parkway', city: 'Kennesaw' },
       { kind: 'dropoff', orders: 1, street: '2400 Tansy Creek Blvd', city: 'Marietta',
         line: '2400 Tansy Creek Blvd, Marietta' }]), null);

  // The mutation catch-up of 21 Oct: one check per guard nothing held.
  var PICK = { kind: 'pickup', orders: 1, street: '810 Ardley West Corwin Parkway', city: 'Kennesaw' };
  var LOST = { kind: 'dropoff', orders: null, name: 'Pat J', expectedBy: 1294,
               street: '2400 Tansy Creek Blvd', city: 'Marietta', state: 'GA', zip: null,
               line: '2400 Tansy Creek Blvd, Marietta', partial: 'header' };
  eq('[lost header] lostHeaderDropoff: the premise, the parser\'s stop on the card\'s street',
     A.lostHeaderDropoff(single(END), [PICK, LOST]).line, '2400 Tansy Creek Blvd, Marietta');
  eq('[lost header] ...not under a pickup of two orders, nor with a second pickup, nor a second '
     + 'dropoff', [A.lostHeaderDropoff(single(END), [Object.assign({}, PICK, { orders: 2 }), LOST]),
                   A.lostHeaderDropoff(single(END), [PICK, PICK, LOST]),
                   A.lostHeaderDropoff(single(END), [PICK, LOST,
                     { kind: 'dropoff', orders: 1, street: '17 Quillon Way', city: 'Marietta' }])],
     [null, null, null]);
  eq('[lost header] ...nor a door with no town',
     A.lostHeaderDropoff(single(END), [PICK, Object.assign({}, LOST, { city: null })]), null);
  eq('[lost header] ...nor an add-on by either mark: `addOn` alone, `of` alone',
     [A.lostHeaderDropoff(single(END, { addOn: true }), [PICK, LOST]),
      A.lostHeaderDropoff(single(END, { of: 'r@1' }), [PICK, LOST])], [null, null]);
  // Stitched (mergeStop): the page below reads the header the first page
  // lost. The header is the page's that printed it — "1 order" — so the
  // planner's lone dropoff answers, with no card street needed.
  var BELOW = 'Dropoff • 1 order\nPat J\nExpected by 9:34 PM\nAddress\n2400 Tansy Creek Blvd\n'
    + 'Marietta, GA\nView details\nWaybill';
  function stitched(end, upper, lower) {
    var o = single(end), s = A.fresh();
    A.took(s, o);
    var cs = [upper, lower].map(function (x, i) {
      return A.sighting(s, o, pageOf(x, 2000 + 500 * i, false), 2000 + 500 * i).candidates
        .map(function (c) { return [c.line, !!c.singleCardOnly, c.pages || 1]; });
    });
    return cs;
  }
  eq('[lost header] a page below that read the lost header gives the header: the stitched stop '
     + 'is the list\'s lone dropoff of "1 order", on a card naming another street',
     stitched('Quillon Way, Marietta', 'Trip Planner\n' + text, BELOW),
     [[], [['2400 Tansy Creek Blvd, Marietta', true, 2]]]);
  // ...and two reads that both lost it keep it lost: the card's street files it.
  var ZIP = text.replace('Marietta, GA\nView details\nStop New Requests',
                         'Marietta, GA 30060\nView details\nWaybill');
  eq('[lost header] ...two reads that both lost the header stitch to a stop still header-lost, '
     + 'filed on the card\'s street', stitched(END, text, ZIP),
     [[['2400 Tansy Creek Blvd, Marietta', true, 1]],
      [['2400 Tansy Creek Blvd, Marietta, GA 30060', true, 2]]]);
})();

/* ---- the planner the hold keeps, pages merged (Assemble.mergePlanner) ----
 *
 * The owner's snap of 24 Oct, 03:03-03:04, invented: one Uber trip, ONE
 * pickup ("Pickup • 2 orders") and two dropoffs. Page 1 read the pickup with
 * its door, the first dropoff (by 3:23) and the second's header and nothing
 * else; the scrolled pages after it the second dropoff alone, then both. Each
 * used to replace the last on the hold, and the restaurant went with page 1. */
(function () {
  function stop(kind, name, by, street, city, extra) {
    return Object.assign({ kind: kind, orders: 1, name: name || null, place: null,
                           expectedBy: by === undefined ? null : by, street: street || null,
                           city: city || null, state: city ? 'GA' : null, zip: null,
                           line: street ? (city ? street + ', ' + city : street) : null,
                           label: kind }, extra || {});
  }
  function said(stops) {
    return stops.map(function (s) { return [s.kind, s.name, s.expectedBy, s.line]; });
  }
  var P = stop('pickup', 'Example Grill', null, '250 Example Road', 'Kennesaw', { orders: 2 });
  var A1 = stop('dropoff', 'Pat Q.', 203, '4821 Kestrel Dr', 'Kennesaw');
  var HDR = stop('dropoff', null, null, null, null);
  var B1 = stop('dropoff', 'Lee R.', 216, '1985 Cobb Parkway', 'Kennesaw');
  var page1 = [P, A1, HDR];
  var m2 = A.mergePlanner(page1, [B1], null);
  eq('[planner pages] the snap: page 2 (the second dropoff alone) onto page 1 keeps page 1\'s '
     + 'pickup with its door and its first dropoff, the second where page 1 cut its header',
     said(m2), said([P, A1, B1]));
  var m3 = A.mergePlanner(m2, [A1, B1], null);
  eq('[planner pages] ...and page 3 (both dropoffs) onto that keeps the pickup ahead of them',
     said(m3), said([P, A1, B1]));
  eq('[planner pages] ...in place of the old replace, which kept the last page alone',
     said(m3).length, 3);
  ok_('[planner pages] ...copies: neither read\'s stops are changed',
      m2[0] !== P && m2[2] !== B1 && page1[2].name === null && page1.length === 3);
  eq('[planner pages] nothing kept: the read as it is, copied',
     [said(A.mergePlanner(null, [B1], null)), A.mergePlanner([], [B1], null)[0] === B1],
     [said([B1]), false]);
  // The same stop read twice: the newer read's header words where it printed
  // them, the address block whole from the read that has more of it.
  var aBare = stop('dropoff', 'Pat Q.', null, '4821 Kestrel Dr', null);
  var aNoName = stop('dropoff', null, 203, '4821 Kestrel Dr', 'Kennesaw');
  eq('[planner pages] one stop off two reads: a time one lost, a town the other read',
     said(A.mergePlanner([aBare], [aNoName], null)), [['dropoff', 'Pat Q.', 203,
                                                     '4821 Kestrel Dr, Kennesaw']]);
  eq('[planner pages] ...and the fuller address stays when the newer read has less of it',
     said(A.mergePlanner([A1], [aBare], null)), [['dropoff', 'Pat Q.', 203,
                                                 '4821 Kestrel Dr, Kennesaw']]);
  eq('[planner pages] ...never a street off one read and a town off the other',
     A.mergePlanner([stop('dropoff', 'Pat Q.', 203, null, 'Kennesaw')],
                    [stop('dropoff', 'Pat Q.', 203, '4821 Kestrel Dr', null)], null)[0].city,
     null);
  // A header with nothing under it between two stops in common is the stop
  // the other read shows there: a door read before is not lost to it.
  eq('[planner pages] a newer header cut at the foot over a stop kept whole keeps its door',
     said(A.mergePlanner([P, A1, B1], [A1, HDR], null)), said([P, A1, B1]));
  // Two customers on one street are two stops; two names are two stops.
  var A2 = stop('dropoff', 'Lee R.', 216, '4900 Kestrel Dr', 'Kennesaw');
  eq('[planner pages] two doors on one street, two names, are two stops, in time order',
     said(A.mergePlanner([A1], [A2], null)), said([A1, A2]));
  eq('[planner pages] ...and the same door under two names is two stops too',
     said(A.mergePlanner([A1], [stop('dropoff', 'Kim T.', 203, '4821 Kestrel Dr',
                                     'Kennesaw')], null)).length, 2);
  // Two reads with nothing in common: their times put them in order.
  eq('[planner pages] a newer page whose times come first goes first',
     said(A.mergePlanner([B1], [P, A1], null)), said([P, A1, B1]));
  var late = stop('dropoff', 'Pat Q.', 1430, '4821 Kestrel Dr', 'Kennesaw');
  var after = stop('dropoff', 'Lee R.', 10, '1985 Cobb Parkway', 'Kennesaw');
  eq('[planner pages] ...past midnight unwrapped: 11:50 PM before 12:10 AM',
     [said(A.mergePlanner([late], [after], null)), said(A.mergePlanner([after], [late], null))],
     [said([late, after]), said([late, after])]);
  var noTime = stop('dropoff', 'Lee R.', null, '1985 Cobb Parkway', 'Kennesaw');
  eq('[planner pages] ...no times: the kept first (a list is read scrolling down), the newer '
     + 'first when its page shows the top',
     [said(A.mergePlanner([P], [noTime], null)),
      said(A.mergePlanner([noTime], [P], { top: true, bottom: false }))],
     [said([P, noTime]), said([P, noTime])]);
  // A read that shows the top has the last word above its first stop, one
  // that shows the foot below its last.
  eq('[planner pages] a newer read from the list\'s top leaves out the kept pickup above it '
     + '(swiped in the app)',
     said(A.mergePlanner([P, A1, B1], [A1, B1], { top: true, bottom: false })), said([A1, B1]));
  eq('[planner pages] ...one that shows the foot leaves out what was kept below it',
     said(A.mergePlanner([P, A1, B1], [P, A1], { top: false, bottom: true })), said([P, A1]));
  eq('[planner pages] ...and a read whose page is not known, or that shows neither, keeps both',
     [said(A.mergePlanner([P, A1, B1], [A1], null)),
      said(A.mergePlanner([P, A1, B1], [A1], { top: false, bottom: false }))],
     [said([P, A1, B1]), said([P, A1, B1])]);
  // A kept header with nothing under it, matched to nothing, is left out.
  eq('[planner pages] a kept header with nothing read under it, matched to nothing, is left out',
     said(A.mergePlanner([HDR, P], [P, A1], null)), said([P, A1]));
  eq('[planner pages] ...but one beside a stop in common is the stop the newer read shows there',
     said(A.mergePlanner([P, HDR], [P, A1], null)), said([P, A1]));
  // A name misread in the same slot, due at the same minute, is one stop
  // under the newer read's name — never a second customer conjured.
  var mara = stop('dropoff', 'Mara T.', 203, null, null);
  var jules = stop('dropoff', 'Jules K.', 203, null, null);
  eq('[planner pages] one slot beside a stop in common, one "Expected by", no doors that '
     + 'differ: one stop, the newer read\'s name',
     said(A.mergePlanner([P, mara], [P, jules], null)), said([P, jules]));
  eq('[planner pages] ...but not at another minute, nor with another door',
     [said(A.mergePlanner([P, mara], [P, stop('dropoff', 'Jules K.', 216, null, null)],
                          null)).length,
      said(A.mergePlanner([P, A1], [P, stop('dropoff', 'Jules K.', 203, '1985 Cobb Parkway',
                                            'Kennesaw')], null)).length], [3, 3]);
  // A read that changes nothing gives the stops it was given, byte for byte
  // (server.js writes holding.json only when the orders change).
  var bare = [{ kind: 'pickup', orders: 1, name: 'Example Grill', expectedBy: 1100,
                line: '5 Mill St, Roswell', street: '5 Mill St', city: 'Roswell', state: null,
                zip: null }];
  eq('[planner pages] the same read again is the same list, byte for byte',
     JSON.stringify(A.mergePlanner(A.mergePlanner(null, bare, null), bare, null)),
     JSON.stringify(bare));
  // The order a pickup was given (server.js ownPickups' `of`) survives a read
  // that gave it none.
  var Pof = Object.assign({}, P, { of: 'o-1' });
  eq('[planner pages] a pickup\'s order (`of`) is kept through a read that gave it none, and '
     + 'a read that gives one wins',
     [A.mergePlanner([Pof], [P], null)[0].of,
      A.mergePlanner([Pof], [Object.assign({}, P, { of: 'o-2' })], null)[0].of],
     ['o-1', 'o-2']);
  // What the hold's pickups are asked from (MV.heldPickups, server.js
  // pickupAsks): the page-1 pickup is still there after page 2.
  var MVp = require('../map-view.js');
  eq('[planner pages] the pickup page 1 read is still one to ask after page 2 lands',
     JSON.stringify(MVp.heldPickups(m2)), JSON.stringify([{ q: '250 Example Road, Kennesaw',
                                                          name: 'Example Grill' }]));
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
  : '\nAll ' + pass + ' assembler checks passed');
process.exit(fail ? 1 : 0);
