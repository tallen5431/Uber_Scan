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
  return Object.assign({ app: 'uber', date: NOV7, finishedAt: '17:40', amount: 2.0, tip: 'processing',
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
eq('[keep] ...another minute is another trip', E.sameEntry(entry(), entry({ finishedAt: '17:41' })), false);
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
function at(h, m, s) { return new Date(2026, 10, 7, h, m, s || 0).getTime(); }
function record(o) {
  var took = o.ended - Math.round(o.minutes * 60000);
  return { kind: 'order', id: o.offer + '@' + took, offer: o.offer, app: o.app === undefined ? 'uber' : o.app,
           places: o.places !== false, how: 'gps', times: { took: took, ended: o.ended },
           card: { pay: o.pay, pickup: o.places === false ? undefined : o.store },
           pickups: o.places === false ? [{}] : [{ name: o.store, door: o.door }],
           dropoff: { text: o.places === false ? undefined : o.drop }, drive: { miles: o.miles } };
}
function keyed(list) {
  return list.map(function (e) { e = Object.assign({}, e); e.key = E.keyOf(e); return e; });
}

// A clear match: Uber's 5:40 PM, the order ended 5:40:30, same store, street,
// minutes and miles; the next order is 50 minutes away.
var day = [
  record({ offer: 'a', ended: at(17, 40, 30), minutes: 39.6, pay: 6.5, miles: 12.1, store: 'Pretend Pizza',
           door: '10 Placeholder Rd, Faketown', drop: '12 Placeholder Ct, Faketown' }),
  record({ offer: 'b', ended: at(16, 50, 20), minutes: 40.8, pay: 7.0, miles: 9.2, store: 'Make-Believe Burgers',
           door: '1200 Sample St NW, Faketown', drop: '742 Example Ave NE, Notaville' })
];
var orders = E.ordersFrom(day, []);
var clear = keyed([entry()]);
var m = E.matchDay(clear, orders)[clear[0].key];
eq('[match] a clear match: matched by the matcher to its order, the card\'s pay on the match',
   [m.status, m.by, m.offer, m.cardPay, m.source], ['matched', 'auto', 'a', 6.5, 'record']);
ok_('[match] ...over the threshold and clear of any runner-up (' + m.score + ', margin ' + m.margin + ')',
    m.score >= E.ACCEPT && m.margin >= E.MARGIN);
var parts = E.score(clear[0], orders[0], 0).parts;
eq('[match] ...every part agreeing: time, name, dropoff street, minutes, miles',
   Object.keys(parts).sort(), ['dropoff', 'miles', 'minutes', 'name', 'time']);
eq('[match] time alone can never be enough', E.W.time < E.ACCEPT, true);

// A chain: two orders from Make-Believe Burgers ending 5:38 and 5:42, no doors
// or dropoffs on file to tell them apart; Uber's trip at 5:40.
var chain = E.ordersFrom([
  record({ offer: 'c1', ended: at(17, 38), minutes: 30, pay: 8, miles: 5, store: 'Make-Believe Burgers' }),
  record({ offer: 'c2', ended: at(17, 42), minutes: 30, pay: 9, miles: 5, store: 'Make-Believe Burgers' })
], []);
var chainE = keyed([entry({ amount: 9.5, tip: null, minutes: 30, seconds: 0, miles: 5,
                            pickup: { name: 'Make-Believe Burgers', detail: 'Sample St NW & Fictional Ct' },
                            dropoff: null })]);
var cm = E.matchDay(chainE, chain)[chainE[0].key];
eq('[match] a chain\'s two orders minutes apart: it needs you, both offered, best first',
   [cm.status, (cm.candidates || []).map(function (c) { return c.offer; }).sort()], ['needs', ['c1', 'c2']]);
ok_('[match] ...at most ' + E.CANDIDATES_SHOWN + ' candidates, each with what tells them apart (took, ended, card)',
    cm.candidates.length <= E.CANDIDATES_SHOWN && cm.candidates.every(function (c) {
      return typeof c.tookAt === 'number' && typeof c.endedAt === 'number' && typeof c.pay === 'number';
    }));
// ...and the bracket's street found in one branch's door does tell them apart.
var chainDoors = E.ordersFrom([
  record({ offer: 'c1', ended: at(17, 38), minutes: 30, pay: 8, miles: 5, store: 'Make-Believe Burgers',
           door: '1200 Sample St NW, Faketown' }),
  record({ offer: 'c2', ended: at(17, 42), minutes: 30, pay: 9, miles: 5, store: 'Make-Believe Burgers',
           door: '88 Other Rd, Faketown' })
], []);
var cd = E.matchDay(chainE, chainDoors)[chainE[0].key];
eq('[match] ...with the branches\' doors on file, the branch on the bracket\'s corner comes first '
   + '(still the driver\'s to confirm while the clock cannot tell them apart by ' + E.MARGIN + ')',
   [cd.status, cd.status === 'matched' ? cd.offer : (cd.candidates[0] || {}).offer], ['needs', 'c1']);
ok_('[match] ...and the corner adds to that branch\'s score, not the other\'s',
    (E.score(chainE[0], chainDoors[0], 0).parts.street || 0) > 0 && !E.score(chainE[0], chainDoors[1], 0).parts.street);

// The rig was off: no order within the gate.
var off = keyed([entry({ finishedAt: '12:10' })]);
eq('[match] a day the rig was off: no order on file', E.matchDay(off, orders)[off[0].key].status, 'none');
eq('[match] ...nor on a day with no orders at all', E.matchDay(off, [])[off[0].key].status, 'none');

// The app's clock three minutes behind the rig's, all day: found from the
// confident matches, and a third trip that is only clear once it is applied.
var lag = 3 * 60000;
var lagDay = E.ordersFrom([
  record({ offer: 'l1', ended: at(15, 58) + lag, minutes: 22, pay: 7.25, miles: 4.0, store: 'Nowhere Noodles',
           drop: '9 Imaginary Way, Inventon' }),
  record({ offer: 'l2', ended: at(16, 50) + lag, minutes: 40.8, pay: 7.0, miles: 9.2, store: 'Make-Believe Burgers',
           drop: '742 Example Ave NE, Notaville' }),
  record({ offer: 'l3', ended: at(18, 30) + lag, minutes: 25, pay: 6.0, miles: 6.0, store: 'Imaginary Bistro' }),
  record({ offer: 'l4', ended: at(18, 30) - 9 * 60000, minutes: 25, pay: 6.0, miles: 6.0, store: 'Imaginary Bistro' })
], []);
var lagE = keyed([
  entry({ finishedAt: '15:58', amount: 7.25, tip: null, minutes: 22, seconds: 5, miles: 4.1,
          pickup: { name: 'Nowhere Noodles' }, dropoff: { street: 'Imaginary Way' } }),
  entry({ finishedAt: '16:50', amount: 25.05, tip: 19.54, minutes: 40, seconds: 48, miles: 9.38,
          pickup: { name: 'Make-Believe Burgers' }, dropoff: { street: 'Example Ave NE' } }),
  entry({ finishedAt: '18:30', amount: 6.0, tip: null, minutes: 25, seconds: 0, miles: 6.0,
          pickup: { name: 'Imaginary Bistro' }, dropoff: null })
]);
var lm = E.matchDay(lagE, lagDay);
eq('[match] the app\'s clock 3 minutes off the rig\'s: found from the day\'s confident matches',
   lm[lagE[0].key].offsetS, 180);
eq('[match] ...and with it applied, the trip with a same-store order 9 minutes the other way is matched to the right one',
   lagE.map(function (e) { return [lm[e.key].status, lm[e.key].offer]; }),
   [['matched', 'l1'], ['matched', 'l2'], ['matched', 'l3']]);

// One order, two entries that both fit it: neither is forced.
var one = E.ordersFrom([record({ offer: 'o1', ended: at(17, 40), minutes: 30, pay: 8, miles: 5, store: 'Pretend Pizza' })], []);
var two = keyed([entry({ finishedAt: '17:40', amount: 8, tip: null, minutes: 30, seconds: 0, miles: 5 }),
                 entry({ finishedAt: '17:41', amount: 9, tip: null, minutes: 30, seconds: 0, miles: 5 })]);
var tm = E.matchDay(two, one);
eq('[match] one order, two entries that fit it alike: neither is given it', two.map(function (e) { return tm[e.key].status; }),
   ['needs', 'needs']);

// An order of the other app is never a candidate.
var dd = E.ordersFrom([record({ offer: 'd1', app: 'doordash', ended: at(17, 40), minutes: 39.6, pay: 6.5,
                                miles: 12.1, store: 'Pretend Pizza' })], []);
eq('[match] a DoorDash order is no candidate for an Uber trip', E.matchDay(clear, dd)[clear[0].key].status, 'none');
var unread = E.ordersFrom([record({ offer: 'u1', app: null, ended: at(17, 40, 30), minutes: 39.6, pay: 6.5,
                                    miles: 12.1, store: 'Pretend Pizza' })], []);
eq('[match] ...an order whose app the rig did not read can be', E.matchDay(clear, unread)[clear[0].key].offer, 'u1');

// The driver's pick: kept, and its order out of the other's running.
var picked = keyed([Object.assign(entry({ finishedAt: '17:40', amount: 8, tip: null, minutes: 30, seconds: 0, miles: 5 })),
                    entry({ finishedAt: '17:41', amount: 9, tip: null, minutes: 30, seconds: 0, miles: 5 })]);
picked[0].match = { status: 'picked', by: 'you', offer: 'o1', tookAt: one[0].tookAt };
var pm = E.matchDay(picked, one);
eq('[match] the driver\'s pick is kept as picked, and the order it took is no one else\'s',
   [pm[picked[0].key].status, pm[picked[1].key].status], ['picked', 'none']);
picked[1].match = { status: 'none', by: 'you' };
eq('[match] ...and "none of these" is kept as the driver said', E.matchDay(picked, one)[picked[1].key], { status: 'none', by: 'you' });

// keepPlaces off: no names, no streets; the clock, minutes and miles still say.
var blind = E.ordersFrom([record({ offer: 'p1', places: false, ended: at(17, 40, 30), minutes: 39.6, pay: 6.5, miles: 12.1 })], []);
var bm = E.matchDay(clear, blind)[clear[0].key];
eq('[match] a record kept with keepPlaces off: matched on its clock, minutes and miles alone',
   [bm.status, bm.offer], ['matched', 'p1']);

// A day before the records: a run the report rebuilds from took/drop rows,
// with the offer's own pickup.
var rebuilt = E.ordersFrom([], [{ id: 'r9', app: 'uber', pay: 6.5, tookAt: at(17, 1), endedAt: at(17, 40, 30),
                                  by: 'drop', pickup: 'Pretend Pizza', dropoff: '12 Placeholder Ct, Faketown' }]);
var rm = E.matchDay(clear, rebuilt)[clear[0].key];
eq('[match] a day before the order record: matched to the rebuilt run, said to be rebuilt',
   [rm.status, rm.offer, rm.order, rm.source], ['matched', 'r9', null, 'rebuilt']);
eq('[match] ...a run a record already covers is not offered twice',
   E.ordersFrom([day[0]], [{ id: 'a', app: 'uber', tookAt: day[0].times.took + 200, endedAt: day[0].times.ended }]).length, 1);

eq('[match] a trip at 12:30 AM under Sat\'s heading is the small hours of Sunday',
   new Date(E.finishMs({ date: NOV7, finishedAt: '00:30' })).getDate(), 8);

eq('[match] names are alike past OCR slips and abbreviations, and two restaurants are not',
   [E.similar('Make-Belleve Burgers', 'Make-Believe Burgers') >= E.NAME_MIN,
    E.similar('Sample Street Northwest', 'Sample St NW') === 1,
    E.similar('Pretend Pizza', 'Nowhere Noodles') < E.NAME_OTHER], [true, true, true]);

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' earnings checks passed');
process.exit(bad ? 1 : 0);
