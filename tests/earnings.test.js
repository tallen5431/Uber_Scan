/* What the app paid, and which order it was for: earnings.js, with no
   server and no picture. Run with: node tests/earnings.test.js

   The owner, 7 Nov 2026: "compare what uber actually paid compared to the
   expected pay of the order" ... "Can it automatically figure out which order
   it belongs to in the journal?" Four things are held here:

     [parse]  the shared-corpus cases in tests/fixtures/earnings.json: Uber's
              Earnings Activity as tesseract reads it, its slips, a scroll
              past the top or off the bottom, the day and the year, and
              DoorDash said to be unread. (rpi/test_earnings.py reads the same
              screen off rendered pictures through the real tesseract.)
     [keep]   one trip however often it is seen: overlapping screenshots, a
              re-upload, a tip that settles and an older screenshot that
              would un-settle it, and the newest row winning the fold.
     [match]  a clear match; two of a chain's orders minutes apart left to
              the driver with both as candidates; a day the rig was off; the
              app's clock off the rig's, found from the day; one order for
              one entry; an order of the other app never a candidate; the
              driver's pick kept and its order out of the others' running;
              a record kept with keepPlaces off still matched by its clock,
              minutes and miles.
     [paid]   the total, base, tip and its status.

   Every restaurant, street, town and figure is invented. */
'use strict';
var E = require('../earnings.js');
var cases = require('./fixtures/earnings.json');

var ok = 0, bad = 0;
function eq(name, got, want) {
  var g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) ok++;
  else { bad++; console.log('FAIL  ' + name + ': got ' + g + ' want ' + w); }
}
function ok_(name, cond) { eq(name, !!cond, true); }

// Partial: every field the case names, nothing else.
function like(name, got, want) {
  if (want === null || typeof want !== 'object' || Array.isArray(want)) return eq(name, got, want);
  Object.keys(want).forEach(function (k) {
    if (k === 'entries' || k === 'others') {
      eq(name + ' / ' + k + ' count', (got[k] || []).length, want[k].length);
      want[k].forEach(function (we, i) { like(name + ' / ' + k + '[' + i + ']', (got[k] || [])[i] || {}, we); });
    } else {
      eq(name + ' / ' + k, got[k], want[k]);
    }
  });
}

/* [parse] ------------------------------------------------------------------ */
cases.parse.forEach(function (c) {
  var p = E.parse(c.text, { now: c.now });
  var got = { app: p.app, day: p.day ? p.day.iso : null, dayFrom: p.day ? p.day.from : null,
              entries: p.entries, others: p.others, notes: p.notes };
  like('[parse] ' + c.name, got, c.expect);
});

eq('[parse] the app is told from the text: Uber\'s heading, Uber\'s trip line alone, DoorDash, neither',
   [E.detectApp('Earnings Activity'), E.detectApp('Delivery - 12 min 3 sec - 2.0 mi'),
    E.detectApp('Dasher earnings'), E.detectApp('$16.05 20 min (7.3 mi) trip')],
   ['uber', 'uber', 'doordash', null]);
eq('[parse] every app has a parser\'s place, and DoorDash\'s reads nothing yet',
   [Object.keys(E.PARSERS).sort(), E.parse('Dasher', { app: 'doordash' }).entries.length], [['doordash', 'uber'], 0]);
eq('[parse] the app can be named by the caller', E.parse('Sat, Nov 7\n$1.00 1:00 PM\nDelivery - 1 min 0 sec - 0.5 mi', { app: 'uber', now: 1794146400000 }).entries.length, 1);

/* [keep] ------------------------------------------------------------------- */
var NOV7 = '2026-11-07';
function entry(o) {
  return Object.assign({ app: 'uber', date: NOV7, startedAt: '17:40', amount: 2.0, tip: 'processing',
                         type: 'Delivery', minutes: 39, seconds: 33, miles: 12.3,
                         pickup: { name: 'Pretend Pizza', detail: 'Faketown' },
                         dropoff: { street: 'Placeholder Ct', town: 'Faketown' } }, o || {});
}

// Two screenshots of one day overlapping by a trip: the shared trip is one.
var top = E.parse(cases.parse[0].text, { now: 1794146400000 });
var lower = E.parse(cases.parse[3].text, { now: 1794146400000 });
var seen = [];
[top, lower].forEach(function (p) {
  p.entries.forEach(function (raw) {
    var e = Object.assign({ app: 'uber', date: NOV7 }, raw);
    if (!seen.some(function (x) { return E.sameEntry(x, e); })) seen.push(e);
  });
});
eq('[keep] two overlapping screenshots of a day: the trip on both is one trip', seen.length, 3);
eq('[keep] the same minute and another restaurant is another trip',
   E.sameEntry(entry(), entry({ pickup: { name: 'Nowhere Noodles' } })), false);
eq('[keep] ...and the same minute with no pickup on one (a scroll cut it off) and the same amount is the same trip',
   E.sameEntry(entry({ pickup: null, dropoff: null }), entry()), true);
eq('[keep] ...a tip settling raises the amount: still the same trip, by its name',
   E.sameEntry(entry(), entry({ amount: 6.0, tip: 4.0 })), true);
eq('[keep] ...and with no names, a pending tip and a larger settled amount are the same trip',
   E.sameEntry(entry({ pickup: null }), entry({ pickup: null, amount: 6.0, tip: 4.0 })), true);
eq('[keep] ...another minute is another trip', E.sameEntry(entry(), entry({ startedAt: '17:41' })), false);
eq('[keep] the key leaves out the amount, so the tip settling keeps it', E.keyOf(entry()) === E.keyOf(entry({ amount: 6, tip: 4 })), true);

var first = entry({ history: [{ at: 1000, amount: 2.0, tip: 'processing' }] });
var settled = E.mergeEntry(first, entry({ amount: 6.0, tip: 4.0 }), 2000);
eq('[keep] the tip settles: the amount and tip move, the story is kept (pending at T, $4.00 at T2)',
   [settled.changed, settled.entry.amount, settled.entry.tip, settled.entry.history],
   [true, 6.0, 4.0, [{ at: 1000, amount: 2.0, tip: 'processing' }, { at: 2000, amount: 6.0, tip: 4.0 }]]);
var older = E.mergeEntry(settled.entry, entry(), 3000);
eq('[keep] an older screenshot still saying "processing", uploaded after, does not un-settle it',
   [older.changed, older.entry.amount, older.entry.tip], [false, 6.0, 4.0]);
var again = E.mergeEntry(settled.entry, entry({ amount: 6.0, tip: 4.0 }), 4000);
eq('[keep] the same screenshot uploaded again changes nothing', again.changed, false);
var filled = E.mergeEntry(entry({ pickup: null, dropoff: null }), entry(), 5000);
eq('[keep] a pickup a scroll cut off is filled in from the screenshot that has it',
   [filled.changed, filled.entry.pickup.name], [true, 'Pretend Pizza']);

var rows = [
  { kind: 'earning', key: 'k1', at: 100, seq: 100, amount: 2 },
  { kind: 'earning', key: 'k1', at: 300, seq: 300, amount: 6 },
  { kind: 'earning', key: 'k1', at: 200, seq: 200, amount: 4 },
  { kind: 'order', key: 'k1', at: 900, amount: 99 },
  { kind: 'earning', key: 'k2', at: 50, seq: 50, amount: 7 }
];
eq('[keep] the fold: the newest row of each key, whatever order they were written in; no other kind',
   E.fold(rows).map(function (r) { return [r.key, r.amount]; }).sort(), [['k1', 6], ['k2', 7]]);

/* [paid] ------------------------------------------------------------------- */
eq('[paid] a settled tip: the total, the tip, the base',
   E.paidOf(entry({ amount: 25.05, tip: 19.54 })), { total: 25.05, tip: 19.54, tipStatus: 'settled', base: 5.51 });
eq('[paid] a tip processing: the total is the base, the tip not counted as nothing',
   E.paidOf(entry()), { total: 2, tip: null, tipStatus: 'pending', base: 2 });
eq('[paid] no tip line', E.paidOf(entry({ amount: 7.25, tip: null })),
   { total: 7.25, tip: null, tipStatus: 'none', base: 7.25 });

/* [match] ------------------------------------------------------------------ */
// A record as orderRow writes one: offered/took/ended, how it ended, its
// pickups (a batch has two), its dropoff, the odometer, the card.
function at(h, m, s, day) { return new Date(2026, 10, day || 7, h, m, s || 0).getTime(); }
function record(o) {
  var places = o.places !== false;
  var stores = o.stores || (o.store ? [o.store] : []);
  return { kind: 'order', id: o.offer + '@' + (o.took || o.offered), offer: o.offer,
           app: o.app === undefined ? 'uber' : o.app, places: places, how: o.how || 'gps',
           times: { offered: o.offered === undefined ? null : o.offered, took: o.took === undefined ? null : o.took,
                    ended: o.ended === undefined ? null : o.ended },
           card: { pay: o.pay, minutes: o.cardMinutes, miles: o.cardMiles,
                   pickup: places ? stores[0] : undefined, stores: places && stores.length > 1 ? stores : undefined },
           pickups: places ? stores.map(function (s, i) { return { name: s, door: i === 0 ? o.door : undefined }; }) : [{}],
           dropoff: { text: places ? o.drop : undefined }, drive: { miles: o.miles } };
}
function keyed(list) {
  return list.map(function (e) { e = Object.assign({}, e); e.key = E.keyOf(e); return e; });
}

/* THE EVIDENCE DAY, invented. One real evening's Earnings Activity against
 * the rig's records for it (AUDITS.md), with every name, street and figure
 * made up but the SHAPE kept: Uber's time is the trip's start, the rig saw
 * each card 0 to 9 minutes after it (one batch 18, accepted on the phone
 * before the rig's Took), Uber's own minutes end 9 to 13 minutes before the
 * rig's end, one order expired on the rig and was never timed, and one had no
 * Took at all. */
var D12 = '2026-11-12';
function t12(h, m, s) { return at(h, m, s, 12); }
var evOrders = [
  // a batch: two pickups, two dropoffs; accepted on the phone 18 min before the rig's Took
  record({ offer: 'ev1', offered: t12(15, 31), took: t12(15, 31, 30), ended: t12(16, 9), pay: 23.47, miles: 12.4,
           stores: ['Make-Believe Burgers', 'Pretend Pizza'], door: '1200 Sample St, Faketown',
           drop: '31 Mock Ln, Faketown', cardMinutes: 40, cardMiles: 11 }),
  record({ offer: 'ev2', offered: t12(17, 35), took: t12(17, 54), ended: t12(18, 25), pay: 27.83, miles: 16.2,
           store: 'Imaginary Bistro', drop: '8 Example Ave NE, Notaville', cardMinutes: 38, cardMiles: 15.5 }),
  record({ offer: 'ev3', offered: t12(18, 23), took: t12(18, 24), ended: t12(18, 54), pay: 12.64, miles: 7.0,
           store: 'Nowhere Noodles', drop: '9 Imaginary Way, Inventon', cardMinutes: 24, cardMiles: 6.5 }),
  record({ offer: 'ev4', offered: t12(19, 8), took: t12(19, 8, 20), ended: t12(19, 42), pay: 16.38, miles: 7.3,
           store: 'Pretend Pizza', drop: '12 Placeholder Ct, Faketown', cardMinutes: 26, cardMiles: 7 }),
  // no Took: on the rig from its card to its end, never timed
  record({ offer: 'ev5', offered: t12(19, 40), ended: t12(20, 2), how: 'drop', pay: 12.27,
           store: 'Sample Sushi', drop: '4 Fictional Ct SW, Notaville', cardMinutes: 20, cardMiles: 9 }),
  // expired on the rig's own clock: an end that is no delivery's
  record({ offer: 'ev6', offered: t12(20, 12), took: t12(20, 13), ended: t12(21, 29), how: 'expiry', pay: 24.91,
           miles: 30.5, store: 'Placeholder Pho', drop: '77 Mock Rd, Inventon', cardMinutes: 35, cardMiles: 20 })
];
function ev(o) {
  return Object.assign({ app: 'uber', date: D12, type: 'Delivery', tip: null }, o);
}
var evEntries = keyed([
  ev({ startedAt: '15:13', minutes: 44, seconds: 50, miles: 11.40, amount: 23.47, tip: 12.80,
       pickup: { name: 'Make-Believe Burgers', detail: '1200 Sample St' }, dropoff: { street: 'Mock Ln', town: 'Faketown' } }),
  ev({ startedAt: '17:32', minutes: 40, seconds: 20, miles: 15.10, amount: 27.94, tip: 22.15,
       pickup: { name: 'Imaginary Bistro', detail: 'Faketown' }, dropoff: { street: 'Example Ave NE', town: 'Notaville' } }),
  ev({ startedAt: '18:23', minutes: 22, seconds: 0, miles: 6.30, amount: 12.64,
       pickup: { name: 'Nowhere Noodles', detail: 'Inventon' }, dropoff: { street: 'Imaginary Way', town: 'Inventon' } }),
  ev({ startedAt: '19:00', minutes: 27, seconds: 40, miles: 7.45, amount: 16.38,
       pickup: { name: 'Pretend Pizza', detail: 'Faketown' }, dropoff: { street: 'Placeholder Ct', town: 'Faketown' } }),
  ev({ startedAt: '19:31', minutes: 17, seconds: 50, miles: 8.90, amount: 12.27,
       pickup: { name: 'Sample Sushi', detail: 'Notaville' }, dropoff: { street: 'Fictional Ct SW', town: 'Notaville' } }),
  ev({ startedAt: '20:12', minutes: 37, seconds: 30, miles: 20.60, amount: 24.91, tip: 12.10,
       pickup: { name: 'Placeholder Pho', detail: 'Inventon' }, dropoff: { street: 'Mock Rd', town: 'Inventon' } }),
  // Took never pressed and the rig never saw the card: no order on file
  ev({ startedAt: '16:40', minutes: 33, seconds: 10, miles: 14.2, amount: 33.80, tip: 20.0,
       pickup: { name: 'Fabled Falafel', detail: 'Faketown' }, dropoff: { street: 'Storybook Ln', town: 'Faketown' } })
]);
var evO = E.ordersFrom(evOrders, []);
var evM = E.matchDay(evEntries, evO);
eq('[match] the evidence day, matched on Uber\'s START: all six on file matched to their orders, the one never '
   + 'seen "no order on file"',
   evEntries.map(function (e) { return [e.startedAt, evM[e.key].status, evM[e.key].offer || null]; }),
   [['15:13', 'matched', 'ev1'], ['17:32', 'matched', 'ev2'], ['18:23', 'matched', 'ev3'], ['19:00', 'matched', 'ev4'],
    ['19:31', 'matched', 'ev5'], ['20:12', 'matched', 'ev6'], ['16:40', 'none', null]]);
eq('[match] ...on the rig\'s ordinary lag behind the phone: no clock offset found',
   evM[evEntries[0].key].offsetS, 0);
ok_('[match] ...each over the threshold and clear by the margin ('
    + evEntries.slice(0, 6).map(function (e) { return evM[e.key].score + '/' + evM[e.key].margin; }).join(', ') + ')',
    evEntries.slice(0, 6).every(function (e) { return evM[e.key].score >= E.ACCEPT && evM[e.key].margin >= E.MARGIN; }));
eq('[match] ...the start taken from the card\'s first sighting where the Took came late (17:32 against offered 17:35, '
   + 'took 17:54)', evM[evEntries[1].key].startBy, 'offered');
var p1 = E.score(evEntries[0], evO[0], 0);
ok_('[match] the batch accepted on the phone 18 min before the rig\'s Took: part of the start (' + p1.parts.start
    + '), the finish in full (' + p1.parts.finish + ')',
    p1.parts.start > 0 && p1.parts.start < E.W.start && p1.parts.finish === E.W.finish);
var p6 = E.score(evEntries[5], evO[5], 0);
eq('[match] an expired order: no finish and no miles held against it (its end is a clock, not a delivery)',
   [p6.parts.finish, p6.parts.miles, p6.parts.start], [undefined, undefined, E.W.start]);
eq('[match] an order with no Took is matched on its card\'s first sighting',
   [evM[evEntries[4].key].startBy, evM[evEntries[4].key].tookAt], ['offered', null]);

// The same evening with keepPlaces off: no names, no streets. The clean
// deliveries still match on the two clocks, the miles and the pay; the batch
// and the expired order, with less to go on, are left to the driver.
var blindEv = E.ordersFrom(evOrders.map(function (r) {
  var b = JSON.parse(JSON.stringify(r));
  b.places = false; b.pickups = [{}]; b.dropoff = {}; delete b.card.pickup; delete b.card.stores;
  return b;
}), []);
var bevE = keyed(evEntries.map(function (e) { return Object.assign({}, e, { pickup: null, dropoff: null }); }));
var bevM = E.matchDay(bevE, blindEv);
eq('[match] the evidence day with keepPlaces off: the clean deliveries matched, the batch and the expired order '
   + 'left to you, never guessed',
   bevE.map(function (e) { return [bevM[e.key].status, bevM[e.key].offer || null]; }),
   [['needs', null], ['matched', 'ev2'], ['matched', 'ev3'], ['matched', 'ev4'], ['matched', 'ev5'], ['needs', null],
    ['none', null]]);

// The rig's clock 12 minutes ahead of the phone's all evening: past the
// ordinary lag, found from the confident matches, and every trip still its own.
var skew = 12 * 60000;
var skewO = E.ordersFrom(evOrders.map(function (r) {
  var b = JSON.parse(JSON.stringify(r));
  ['offered', 'took', 'ended'].forEach(function (k) { if (b.times[k] !== null) b.times[k] += skew; });
  return b;
}), []);
var skM = E.matchDay(evEntries, skewO);
ok_('[match] the rig\'s clock 12 min ahead: an offset found past the ordinary lag (' + skM[evEntries[0].key].offsetS + ' s)',
    skM[evEntries[0].key].offsetS >= 120 && skM[evEntries[0].key].offsetS <= 720);
eq('[match] ...and with it applied every trip on file is still matched to its own order',
   evEntries.slice(0, 6).map(function (e) { return skM[e.key].offer || skM[e.key].status; }),
   ['ev1', 'ev2', 'ev3', 'ev4', 'ev5', 'ev6']);

// The old reading — Uber's time as the FINISH — would have put the 18:23 trip
// against an order that ENDED at 18:25 (ev2) rather than the one that started
// then: under the start reading it is no candidate's best.
eq('[match] an order that ended at Uber\'s time is not the trip that started then',
   evM[evEntries[2].key].offer !== 'ev2', true);

eq('[match] neither clock alone, nor both, is enough: one more thing must agree',
   [E.W.start < E.ACCEPT, E.W.start + E.W.finish < E.ACCEPT], [true, true]);

// A chain: two orders from Make-Believe Burgers offered 5:38 and 5:42, no
// doors or dropoffs on file to tell them apart; Uber's trip started 5:40.
function trip(o) {
  return Object.assign({ app: 'uber', date: NOV7, startedAt: '17:40', amount: 8, tip: null, type: 'Delivery',
                         minutes: 30, seconds: 0, miles: 5, pickup: { name: 'Pretend Pizza', detail: 'Faketown' },
                         dropoff: null }, o || {});
}
function plain(o) {
  return record(Object.assign({ took: o.offered + 30000, ended: o.offered + 42 * 60000, miles: 5 }, o));
}
var chain = E.ordersFrom([
  plain({ offer: 'c1', offered: at(17, 38), pay: 8, store: 'Make-Believe Burgers' }),
  plain({ offer: 'c2', offered: at(17, 42), pay: 9, store: 'Make-Believe Burgers' })
], []);
var chainE = keyed([trip({ amount: 8.5, pickup: { name: 'Make-Believe Burgers', detail: 'Sample St NW & Fictional Ct' } })]);
var cm = E.matchDay(chainE, chain)[chainE[0].key];
eq('[match] a chain\'s two orders minutes apart: it needs you, both offered',
   [cm.status, (cm.candidates || []).map(function (c) { return c.offer; }).sort()], ['needs', ['c1', 'c2']]);
ok_('[match] ...at most ' + E.CANDIDATES_SHOWN + ' candidates, each with what tells them apart (offered, took, card)',
    cm.candidates.length <= E.CANDIDATES_SHOWN && cm.candidates.every(function (c) {
      return typeof c.offeredAt === 'number' && typeof c.tookAt === 'number' && typeof c.pay === 'number';
    }));
var chainDoors = E.ordersFrom([
  plain({ offer: 'c1', offered: at(17, 38), pay: 8, store: 'Make-Believe Burgers', door: '1200 Sample St NW, Faketown' }),
  plain({ offer: 'c2', offered: at(17, 42), pay: 9, store: 'Make-Believe Burgers', door: '88 Other Rd, Faketown' })
], []);
var cd = E.matchDay(chainE, chainDoors)[chainE[0].key];
eq('[match] ...with the branches\' doors on file, the branch on the bracket\'s corner comes first '
   + '(still the driver\'s to confirm while it is not clear by ' + E.MARGIN + ')',
   [cd.status, cd.status === 'matched' ? cd.offer : (cd.candidates[0] || {}).offer], ['needs', 'c1']);
ok_('[match] ...and the corner adds to that branch\'s score, not the other\'s',
    (E.score(chainE[0], chainDoors[0], 0).parts.street || 0) > 0 && !E.score(chainE[0], chainDoors[1], 0).parts.street);

// The rig was off: no order within the gate.
var pz = E.ordersFrom([plain({ offer: 'a', offered: at(17, 41), pay: 8, store: 'Pretend Pizza' })], []);
var off = keyed([trip({ startedAt: '12:10' })]);
eq('[match] a day the rig was off: no order on file', E.matchDay(off, pz)[off[0].key].status, 'none');
eq('[match] ...nor on a day with no orders at all', E.matchDay(off, [])[off[0].key].status, 'none');

// One order, two entries that both fit it: neither is forced.
var two = keyed([trip({ startedAt: '17:40' }), trip({ startedAt: '17:41', amount: 8.1 })]);
var tm = E.matchDay(two, pz);
eq('[match] one order, two entries that fit it alike: neither is given it', two.map(function (e) { return tm[e.key].status; }),
   ['needs', 'needs']);

// An order of the other app is never a candidate.
var clear = keyed([trip()]);
var dd = E.ordersFrom([plain({ offer: 'd1', app: 'doordash', offered: at(17, 41), pay: 8, store: 'Pretend Pizza' })], []);
eq('[match] a DoorDash order is no candidate for an Uber trip', E.matchDay(clear, dd)[clear[0].key].status, 'none');
var unread = E.ordersFrom([plain({ offer: 'u1', app: null, offered: at(17, 41), pay: 8, store: 'Pretend Pizza' })], []);
eq('[match] ...an order whose app the rig did not read can be', E.matchDay(clear, unread)[clear[0].key].offer, 'u1');

// The driver's pick: kept, and its order out of the other's running.
var picked = keyed([trip({ startedAt: '17:40' }), trip({ startedAt: '17:41', amount: 8.1 })]);
picked[0].match = { status: 'picked', by: 'you', offer: 'a', tookAt: pz[0].tookAt };
var pm = E.matchDay(picked, pz);
eq('[match] the driver\'s pick is kept as picked, and the order it took is no one else\'s',
   [pm[picked[0].key].status, pm[picked[1].key].status], ['picked', 'none']);
picked[1].match = { status: 'none', by: 'you' };
eq('[match] ...and "none of these" is kept as the driver said', E.matchDay(picked, pz)[picked[1].key], { status: 'none', by: 'you' });

// keepPlaces off: no names, no streets; the two clocks, the miles and the pay still say.
var blind = E.ordersFrom([plain({ offer: 'p1', places: false, offered: at(17, 41), pay: 8 })], []);
var bm = E.matchDay(clear, blind)[clear[0].key];
eq('[match] a record kept with keepPlaces off: matched on its clocks, miles and pay alone',
   [bm.status, bm.offer], ['matched', 'p1']);

// A day before the records: a run the report rebuilds from took/drop rows,
// with the offer's own pickup and first sighting.
var rebuilt = E.ordersFrom([], [{ id: 'r9', app: 'uber', pay: 8, offeredAt: at(17, 41), tookAt: at(17, 42),
                                  endedAt: at(18, 22), by: 'drop', pickup: 'Pretend Pizza' }]);
var rm = E.matchDay(clear, rebuilt)[clear[0].key];
eq('[match] a day before the order record: matched to the rebuilt run, said to be rebuilt',
   [rm.status, rm.offer, rm.order, rm.source], ['matched', 'r9', null, 'rebuilt']);
eq('[match] ...a run a record already covers is not offered twice',
   E.ordersFrom([evOrders[2]], [{ id: 'ev3', app: 'uber', tookAt: evOrders[2].times.took + 200,
                                  endedAt: evOrders[2].times.ended }]).length, 1);

eq('[match] a trip at 12:30 AM under Sat\'s heading is the small hours of Sunday',
   new Date(E.startMs({ date: NOV7, startedAt: '00:30' })).getDate(), 8);
eq('[match] a row an earlier build wrote (`finishedAt`) is read as the same start and keeps its key',
   [E.startMs({ date: NOV7, finishedAt: '17:40' }) === E.startMs({ date: NOV7, startedAt: '17:40' }),
    E.keyOf(trip({ startedAt: undefined, finishedAt: '17:40' })) === E.keyOf(trip())], [true, true]);
eq('[match] Uber\'s finish is its start plus its own minutes and seconds',
   (E.endMs(trip({ minutes: 44, seconds: 50 })) - E.startMs(trip())) / 1000, 44 * 60 + 50);

eq('[match] names are alike past OCR slips and abbreviations, and two restaurants are not',
   [E.similar('Make-Belleve Burgers', 'Make-Believe Burgers') >= E.NAME_MIN,
    E.similar('Sample Street Northwest', 'Sample St NW') === 1,
    E.similar('Pretend Pizza', 'Nowhere Noodles') < E.NAME_OTHER], [true, true, true]);

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' earnings checks passed');
process.exit(bad ? 1 : 0);
