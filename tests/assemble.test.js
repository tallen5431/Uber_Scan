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
  eq('...one that is the held card\'s pickup is refused',
     run(hold({ pickup: '12 Wren Hollow Ct, Acworth' }), navSight(5000, LINE)).refused,
     ['a pickup']);
  var hp = hold();
  hp.fields.pickupAddr = { value: '12 Wren Hollow Ct, Acworth', from: 'planner', conf: 2 };
  eq('...and one that is the pickup a planner filed on it', run(hp, navSight(5000, LINE)).refused,
     ['a pickup']);
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

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
  : '\nAll ' + pass + ' assembler checks passed');
process.exit(fail ? 1 : 0);
