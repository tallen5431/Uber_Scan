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

eq('[parse] a zero read as the letter O before "sec" (tesseract on the drawn 12 Nov layout) is a zero, not a block lost',
   (E.parse('Thu, Nov 12\n$12.64 6:23 PM\nDelivery - 22 min O sec - 6.30 mi', { now: 1794578400000 }).entries[0] || {}).seconds, 0);
eq('[parse] a canceled trip\'s line names Uber\'s screen when nothing else does',
   E.detectApp('$0.00 5:30 PM\nDelivery - You canceled'), 'uber');

/* [17nov] rides, icons and a canceled trip between two trips -----------------
 * The owner's screenshot of 17 Nov 2026, in invented text with the SHAPE of
 * what tesseract made of it: a ride's header with the person icon read as
 * "Bp" and its amount's point lost ("£2210"), a delivery whose time came on a
 * line of its own, a canceled $0.00 trip whose own time was unreadable
 * ("B5I PHI") straight above a ride whose header carried its icon as "3", an
 * "Increased" chip, a "Boost+" chip with no amount, a ride over an hour
 * ("1hr4 min"), and the place lines carrying the pin's icon as "9", "©",
 * "®", "é". Every name, street and figure is invented. */
var NOV17_NOW = 1794996000000;            // 18 Nov 2026, 10am New York
var NOV17 = ['11:52 5 TO@- Co', '€ Earnings Activity 6B =', 'Tue, Nov 17',
  'Bp £2210 10:31 PM', 'Comfort: 17 min 40 sec- 9.40 mi', '«> $3.00 Tip',
  '9 Sample St, Faketown, GA, USA', '© Mock Rd SE, Notaville, GA, USA',
  '$11.00', 'Delivery -12 min 30 sec : 3.10 mi', '« $6.00 Tip', 'Mock Rd', '9:37 PM',
  '® Pretend Pizza (100 Example Ave SE)', '© Imaginary Way, Inventon, GA, USA',
  '$0.00 B5I PHI', 'Delivery - You canceled', '9 Fictional Ct NW, Faketown, GA, USA', '© Unknown',
  '. T Increased', '3 $21.30 8:12 PM', 'Comfort: 26 min 10 sec - 12.20 mi',
  '9 Placeholder Pkwy, Notaville, GA, USA', 'é 12th St NE, Faketown, GA, USA',
  '$19.75', 'Delivery - 30 min 5 sec - 11.00 mi', '7:05 PM', '«© $2.50 Tip 6 Boost+',
  '9 Nowhere Noodles West Inventon', '© Storybook Ln, Faketown, GA, USA',
  '2 $30.10 5:48 PM', 'UberX-1hr4 min: 20.50 mi', '=S Ol',
  '9 Hidden Sample Ct, Notaville, GA, USA', '6 Sample St, Faketown, GA, USA',
  'End of activities during Nov 17, 2026', 'Home Discover Earnings Inbox Menu'].join('\n');
var n17 = E.parse(NOV17, { now: NOV17_NOW });
function brief(e) { return [e.startedAt, e.amount, e.type, e.status]; }
eq('[17nov] the canceled trip never takes the time of the trip below it: no $0.00 entry at 8:12 PM',
   n17.entries.filter(function (e) { return e.status === 'canceled' || e.amount === 0; }).map(brief), []);
eq('[17nov] five of six read, in the screen\'s order: the icon-prefixed rides, the delivery timed on a line of its '
   + 'own, the ride over an hour',
   n17.entries.map(brief),
   [['22:31', 22.1, 'Comfort', 'completed'], ['21:37', 11, 'Delivery', 'completed'],
    ['20:12', 21.3, 'Comfort', 'completed'], ['19:05', 19.75, 'Delivery', 'completed'],
    ['17:48', 30.1, 'UberX', 'completed']]);
eq('[17nov] ...the canceled one skipped and said, never filed at a guessed time',
   [n17.notes, n17.tally.skipped], [['a $0.00 trip with no time on it was skipped'],
                                     [{ amount: 0, status: 'canceled', why: 'no time' }]]);
eq('[17nov] the tally: every entry seen accounted for, in words for the page',
   [n17.tally.seen, n17.tally.read, n17.tally.unread.length, n17.tally.cut, E.tallyWords(n17.tally)],
   [6, 5, 0, 0, '6 entries seen, 5 read, 1 skipped (no time: $0.00 canceled)']);
var r1 = n17.entries[0];
eq('[17nov] "£2210" with its point lost: $22.10, marked guessed; the amounts read whole are not',
   [r1.amount, r1.amountGuessed, n17.entries.slice(1).some(function (e) { return e.amountGuessed; })], [22.1, true, false]);
eq('[17nov] a ride: its pickup the rider\'s street (an address), its dropoff the second street, said to be a ride',
   [r1.pickup, r1.dropoff, r1.ride, r1.tip], [{ name: 'Sample St', detail: 'Faketown', address: true },
                                              { street: 'Mock Rd SE', town: 'Notaville' }, true, 3]);
var x1 = n17.entries[4];
eq('[17nov] "UberX-1hr4 min": 64 minutes, its streets with the pin\'s "9" and "6" taken off',
   [x1.minutes, x1.seconds, x1.miles, x1.pickup.name, x1.dropoff.street], [64, 0, 20.5, 'Hidden Sample Ct', 'Sample St']);
eq('[17nov] the place icons read as "®" and "©" taken off; "é" before "12th St NE" too, the ordinal kept',
   [n17.entries[1].pickup, n17.entries[1].dropoff.street, n17.entries[2].dropoff.street],
   [{ name: 'Pretend Pizza', detail: '100 Example Ave SE' }, 'Imaginary Way', '12th St NE']);
eq('[17nov] ...but a restaurant\'s leading digit is kept: it may be its name ("3 Amigos")',
   n17.entries[3].pickup.name, '9 Nowhere Noodles West Inventon');
eq('[17nov] the chips: "Increased" filed a line above its header is that ride\'s; "Boost+" with no amount is a chip, '
   + 'not pay',
   [n17.entries[2].chips, n17.entries[3].chips, n17.entries[3].extras, n17.entries[3].amount, n17.entries[0].chips],
   [['increased'], ['boost+'], null, 19.75, undefined]);
ok_('[17nov] each trip keeps the raw lines of its block, header first, for "what was read"',
    n17.entries.every(function (e) { return Array.isArray(e.lines) && e.lines.length >= 3 && e.lines.length <= E.LINES_MAX; })
    && n17.entries[2].lines[0] === '3 $21.30 8:12 PM');

// The same screen with the 8:12 PM header unreadable two ways: an amount no
// rule reads ("3 $2l.3O") and no currency glyph at all ("3 21.30"). Either
// way the canceled trip above keeps no time, and the ride is reported unread.
var bad1 = E.parse(NOV17.replace('3 $21.30 8:12 PM', '3 $2l.3O 8:12 PM'), { now: NOV17_NOW });
var bad2 = E.parse(NOV17.replace('3 $21.30 8:12 PM', '3 21.30 8:12 PM'), { now: NOV17_NOW });
eq('[17nov] a header whose amount cannot be read still opens its block: unread with its time, the canceled trip '
   + 'above untimed',
   [bad1.entries.map(function (e) { return e.startedAt; }), bad1.tally.unread, E.tallyWords(bad1.tally)],
   [['22:31', '21:37', '19:05', '17:48'], [{ amount: null, at: '20:12', why: 'its amount could not be read' }],
    '6 entries seen, 4 read, 1 skipped (no time: $0.00 canceled), 1 unread (its amount could not be read at 8:12 PM)']);
eq('[17nov] a header not seen at all: the block with two trip lines is cut, the canceled trip keeps no time and the '
   + 'ride under it is unread, never merged',
   [bad2.entries.map(function (e) { return e.startedAt; }), bad2.tally.seen, bad2.tally.skipped.length,
    bad2.tally.unread.map(function (u) { return u.why; })],
   [['22:31', '21:37', '19:05', '17:48'], 6, 1, ['a trip line with no header read above it']]);
eq('[17nov] two different clocks in one block: the time is left unread, never picked',
   E.parse('Tue, Nov 17\n$9.00\nDelivery - 10 min 0 sec - 2.00 mi\n7:10 PM\nMock Rd 7:40 PM\nPretend Pizza\n'
           + 'Example Ave, Faketown, GA, USA', { now: NOV17_NOW }).tally.skipped,
   [{ amount: 9, status: 'completed', why: 'two times in its block' }]);

// What may and may not open an entry.
function opens(t) { return E.parse('Tue, Nov 17\n' + t, { now: NOV17_NOW }).entries.length; }
eq('[17nov] an icon before the amount opens an entry only on a line carrying the trip\'s clock or straight above the '
   + 'trip\'s line; a lost point only with the clock and a trip line under it; a map label with a number never',
   [opens('3 $21.30 8:12 PM\nComfort - 26 min 10 sec - 12.20 mi'),
    opens('3 $21.30\nMock Rd\nComfort - 26 min 10 sec - 12.20 mi\n8:12 PM'),
    opens('& $21.30 + Increased\nComfort - 26 min 10 sec - 12.20 mi\nSample St, Faketown, GA, USA\n8:12 PM'),
    opens('£2210 10:31 PM\nComfort - 17 min 40 sec - 9.40 mi'),
    opens('£2210 10:31 PM\nMock Rd\nSample Ave\nPretend Pizza\nComfort - 17 min 40 sec - 9.40 mi'),
    opens('£2210\nComfort - 17 min 40 sec - 9.40 mi\n10:31 PM'),
    opens('61 124 Mock 9:00 PM\nComfort - 17 min 40 sec - 9.40 mi')],
   [1, 0, 1, 1, 0, 0, 0]);
eq('[17nov] a trip\'s line with hours: "1 hr 4 min", "1hr4 min", "1 hr", "2 hrs 5 min"; minutes and seconds as before',
   ['UberX · 1 hr 4 min · 21.70 mi', 'UberX-1hr4 min: 21.70 mi', 'Comfort · 1 hr · 30.00 mi',
    'XL · 2 hrs 5 min · 80.2 mi', 'Delivery - 13 min 37 sec - 4.65 mi'].map(function (l) {
     var d = E.detailOf(l); return d && [d.kind, d.minutes, d.seconds, d.miles];
   }),
   [['UberX', 64, 0, 21.7], ['UberX', 64, 0, 21.7], ['Comfort', 60, 0, 30], ['XL', 125, 0, 80.2],
    ['Delivery', 13, 37, 4.65]]);
eq('[17nov] the icon is taken off only where it is clearly the icon',
   [E.stripIcon('® Pretend Pizza'), E.stripIcon('} Pretend Pizza'), E.stripIcon('e Pretend Pizza'),
    E.stripIcon('9 Pretend Tacos', false), E.stripIcon('9 Sample St', true), E.stripIcon('A Taste Of Make-Believe'),
    E.stripIcon('St Pretend'), E.stripIcon('9 12th St', true)],
   ['Pretend Pizza', 'Pretend Pizza', 'Pretend Pizza', '9 Pretend Tacos', 'Sample St', 'A Taste Of Make-Believe',
    'St Pretend', '9 12th St']);

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
   E.paidOf(entry({ amount: 25.05, tip: 19.54 })),
   { total: 25.05, tip: 19.54, tipStatus: 'settled', extras: null, base: 5.51, canceled: false });
eq('[paid] a tip processing: the total is the base, the tip not counted as nothing',
   E.paidOf(entry()), { total: 2, tip: null, tipStatus: 'pending', extras: null, base: 2, canceled: false });
eq('[paid] no tip line', E.paidOf(entry({ amount: 7.25, tip: null })),
   { total: 7.25, tip: null, tipStatus: 'none', extras: null, base: 7.25, canceled: false });
eq('[paid] a tip and a surge: the base is what is left of the total without either',
   E.paidOf(entry({ amount: 9.5, tip: 6.0, extras: { surge: 1.25 } })),
   { total: 9.5, tip: 6, tipStatus: 'settled', extras: { surge: 1.25 }, base: 2.25, canceled: false });
eq('[paid] a canceled trip says so', E.paidOf(entry({ amount: 0, tip: null, status: 'canceled' })).canceled, true);
eq('[keep] a canceled trip and a completed one of the same minute are two trips',
   E.sameEntry(entry({ status: 'canceled', amount: 0, tip: null }), entry({ amount: 0, tip: null })), false);

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

// THE BATCH, as Uber may print it the other way: one entry naming the SECOND
// store (Pretend Pizza) and the door the rig did not file. Still the order:
// any of its pickups is its name, and a batch's other door costs nothing.
var batchOther = keyed([Object.assign({}, evEntries[0], {
  pickup: { name: 'Pretend Pizza', detail: 'Faketown' }, dropoff: { street: 'Storybook Way', town: 'Faketown' } })]);
var bo = E.matchDay(batchOther, evO)[batchOther[0].key];
var boP = E.score(batchOther[0], evO[0], 0).parts;
eq('[match] a batch: one Uber entry naming its other store and its other door is still that order',
   [bo.status, bo.offer, boP.name, boP.dropoff], ['matched', 'ev1', E.W.name, 0]);
eq('[match] ...the order is said to be a batch (two pickups), and a single order\'s other street still costs it',
   [evO[0].batch, evO[1].batch, E.score(Object.assign({}, evEntries[1], { dropoff: { street: 'Storybook Ln' } }),
                                        evO[1], 0).parts.dropoff], [true, false, -E.DROP_PENALTY]);

// The trip the driver canceled on the phone at 5:30 PM ("$0.00 · Delivery ·
// You canceled", with its map and places): the rig had its card on the panel
// at 5:31 and the Took taken back at 5:34. Two minutes later the next card
// (ev2, delivered) came up — a better clock than the taken-back one, and
// never a canceled trip's.
var cancelRec = record({ offer: 'ev7', offered: t12(17, 31), took: t12(17, 31, 20), ended: t12(17, 34), how: 'untick',
                         pay: 9.5, store: 'Sample Sushi', drop: '4 Fictional Ct SW, Notaville' });
var cancelE = ev({ startedAt: '17:30', amount: 0, minutes: null, seconds: null, miles: null, status: 'canceled',
                   canceledBy: 'you', pickup: { name: 'Sample Sushi', detail: 'Notaville' },
                   dropoff: { street: 'Fictional Ct SW', town: 'Notaville' } });
var withCancel = keyed(evEntries.concat([cancelE]));
var wcO = E.ordersFrom(evOrders.concat([cancelRec]), []);
var wcM = E.matchDay(withCancel, wcO);
var wcK = withCancel[withCancel.length - 1].key;
eq('[match] a canceled trip: matched to the order taken back on the rig, and the six on file still their own',
   [wcM[wcK].status, wcM[wcK].offer, withCancel.slice(0, 6).map(function (e) { return wcM[e.key].offer; })],
   ['matched', 'ev7', ['ev1', 'ev2', 'ev3', 'ev4', 'ev5', 'ev6']]);
eq('[match] ...never a delivered order: ev2, whose card came up two minutes after it, is no candidate',
   [E.score(cancelE, wcO[1], 0), E.score(cancelE, wcO[6], 0) !== null], [null, true]);
eq('[match] ...and nothing of a delivery is held against it: no finish, miles or pay part',
   Object.keys(E.score(cancelE, wcO[6], 0).parts).sort(), ['dropoff', 'name', 'start']);
var cancelAlone = keyed([cancelE]);
eq('[match] with only delivered orders near it, a canceled trip has no order on file',
   E.matchDay(cancelAlone, evO)[cancelAlone[0].key].status, 'none');

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

/* [phone] an offer the rig showed and never Took'd ---------------------------- */
// The evidence day's 4:18 PM trip, "$9.50 ($6.00 Tip, $1.25 Surge)": the rig
// had shown its card at 4:20 as "Took $9.27?" and never heard it was taken.
// Around it, the cards of the evening as offer rows: each order's own (taken,
// so covered by its record), one the driver passed, and an unrelated card at
// 4:42 two minutes after the trip the rig never saw.
function offerRow(id, h, m, pay, pickup, extra) {
  return Object.assign({ id: id, at: t12(h, m) + 5000, firstAt: t12(h, m), app: 'uber', pay: pay, minutes: 25,
                         miles: 6, pickup: pickup }, extra || {});
}
var evOffers = [
  offerRow('ev2', 17, 35, 27.83, 'Imaginary Bistro'), offerRow('ev3', 18, 23, 12.64, 'Nowhere Noodles'),
  offerRow('ph1', 16, 20, 9.27, 'Fabled Falafel', { dropoff: '5 Storybook Ln, Faketown' }),
  offerRow('px1', 16, 17, 10.0, 'Fabled Falafel', { accepted: false }),
  offerRow('ox1', 16, 42, 22.40, 'Imaginary Bistro')
];
var phoneE = ev({ startedAt: '16:18', minutes: 24, seconds: 10, miles: 6.4, amount: 9.5, tip: 6.0,
                  extras: { surge: 1.25 }, pickup: { name: 'Fabled Falafel', detail: 'Faketown' },
                  dropoff: { street: 'Storybook Ln', town: 'Faketown' } });
var phDay = keyed(evEntries.concat([phoneE]));
var phO = E.ordersFrom(evOrders, [], evOffers);
var phM = E.matchDay(phDay, phO);
var phK = phDay[phDay.length - 1].key;
eq('[phone] the unconfirmed offer ("Took $9.27?") is the trip\'s: matched to its offer row, said accepted on the phone',
   [phM[phK].status, phM[phK].offer, phM[phK].source, phM[phK].tookAt, phM[phK].said, phM[phK].cardPay],
   ['matched', 'ph1', 'offer', null, 'accepted on the phone, no Took', 9.27]);
eq('[phone] ...an offer an order record covers is no second candidate, nor one the driver passed',
   phO.filter(function (c) { return c.source === 'offer'; }).map(function (c) { return c.offer; }).sort(), ['ox1', 'ph1']);
eq('[phone] ...the six on file still their own, and the trip the rig never saw still "no order on file" '
   + 'beside an unrelated card two minutes after it',
   phDay.slice(0, 7).map(function (e) { return phM[e.key].offer || phM[e.key].status; }),
   ['ev1', 'ev2', 'ev3', 'ev4', 'ev5', 'ev6', 'none']);
var bareOffer = E.ordersFrom([], [], [offerRow('ob1', 16, 20, 4.0, null)]);
var bareE = keyed([Object.assign({}, phoneE, { pickup: null, dropoff: null })]);
eq('[phone] a card whose only likeness is its clock is no candidate at all (' + E.OFFER_MORE + ' points besides it)',
   E.matchDay(bareE, bareOffer)[bareE[0].key].status, 'none');
var canPh = keyed([Object.assign({}, cancelE, { startedAt: '16:18', pickup: { name: 'Fabled Falafel' }, dropoff: null })]);
eq('[phone] a canceled trip can be an offer never confirmed (the phone accepted it, then canceled)',
   (E.matchDay(canPh, phO)[canPh[0].key] || {}).offer, 'ph1');

/* [timed] an untimed order timed by Uber ------------------------------------- */
// The evidence day's expired order (ev6) and the one with no Took (ev5), with
// their trips' matches as the server keeps them: Uber's minutes and miles.
var evRows = evEntries.map(function (e) { return Object.assign({ at: 1 }, e, { match: evM[e.key] }); });
eq('[timed] the expired order: Uber\'s minutes and seconds and its miles, said to be Uber\'s',
   E.uberTimingFor(evRows, 'ev6', evOrders[5].times.took),
   { minutes: 37.5, miles: 20.60, source: 'uber', key: evEntries[5].key });
eq('[timed] ...the order with no Took, by its trip whose match has no Took either',
   (E.uberTimingFor(evRows, 'ev5', null) || {}).minutes, 17.83);
eq('[timed] ...not at another Took, not for an order with no trip matched, never off a canceled trip',
   [E.uberTimingFor(evRows, 'ev6', evOrders[5].times.took + 120000), E.uberTimingFor(evRows, 'nope', null),
    E.uberTimingFor([Object.assign({}, evRows[5], { status: 'canceled' })], 'ev6', evOrders[5].times.took)],
   [null, null, null]);

/* [compare] the card against what happened, on the evidence day --------------- */
// The six matched trips with two pays changed (invented): 6:23 PM's tip
// raised by $3.00 after the card, 7:00 PM's cut by $2.00; and 3:13 PM's batch,
// 44.8 Uber minutes against a 40-minute card, slower than the card said.
var cmpRows = evRows.slice(0, 6).map(function (r, i) {
  return Object.assign({}, r, i === 2 ? { amount: 15.64 } : i === 3 ? { amount: 14.38 } : {});
});
var c1 = E.compareOf(cmpRows[0]), c2 = E.compareOf(cmpRows[1]);
eq('[compare] the match keeps the card as read beside Uber\'s figures: pay, minutes, miles, its places, the rig\'s timing',
   [evM[evEntries[0].key].cardPay, evM[evEntries[0].key].cardMinutes, evM[evEntries[0].key].cardMiles,
    evM[evEntries[0].key].cardPickup, evM[evEntries[0].key].cardDropoff, evM[evEntries[0].key].rigMinutes],
   [23.47, 40, 11, 'Make-Believe Burgers', '31 Mock Ln, Faketown', 37.5]);
eq('[compare] the batch: slower than the card said by 4.8 min, the rig\'s own minutes beside, the pay as carded',
   [c1.time, c1.pay.word, c1.pay.flag],
   [{ card: 40, uber: 44.83, diff: 4.83, word: 'slower', rig: 37.5 }, 'as carded', false]);
eq('[compare] 5:32 PM: 11 cents more than the card (no flag), on time, longer by under the band',
   [c2.pay.diff, c2.pay.word, c2.pay.flag, c2.time.word, c2.miles.word], [0.11, 'more', false, 'on time', 'as said']);
eq('[compare] the tip raised: $3.00 more than the card, flagged',
   [E.compareOf(cmpRows[2]).pay.diff, E.compareOf(cmpRows[2]).pay.flag], [3, true]);
eq('[compare] the tip cut: $2.00 less than the card, flagged',
   [E.compareOf(cmpRows[3]).pay.diff, E.compareOf(cmpRows[3]).pay.word, E.compareOf(cmpRows[3]).pay.flag],
   [-2, 'less', true]);
eq('[compare] the card\'s $/hr and $/mi against the actual (paid over Uber\'s minutes and miles)',
   [c2.perHour, c2.perMile], [{ card: 43.94, actual: 41.57 }, { card: 1.8, actual: 1.85 }]);
eq('[compare] a canceled trip compares nothing; a tip processing leaves the pay out',
   [E.compareOf(Object.assign({}, cmpRows[1], { status: 'canceled' })),
    E.compareOf(Object.assign({}, cmpRows[1], { tip: 'processing' })).pay.pending], [{ canceled: true }, true]);
var sum12 = E.daySummary(cmpRows.concat([evRows[6]]));
eq('[compare] the day: cards against paid, faster/on time/slower, the median minute gap, the widest pay gaps',
   [sum12.trips, sum12.matched, sum12.none, sum12.compared, sum12.card, sum12.paid, sum12.diff,
    sum12.faster, sum12.onTime, sum12.slower, sum12.medianMinutes,
    sum12.biggest.map(function (b) { return [b.startedAt, b.diff]; })],
   [7, 6, 1, 6, 117.5, 118.61, 1.11, 0, 5, 1, 2, [['18:23', 3], ['19:00', -2], ['17:32', 0.11]]]);
ok_('[compare] no word of it says what to take', JSON.stringify([c1, c2, sum12]).indexOf('declin') === -1);

/* [17nov match] a ride, and an amount guessed past a lost point --------------
 * The 10:31 PM ride of the invented 17 Nov text against its ride card: the
 * card's pickup the rider's corner, its dropoff a corner near the door. */
var D17 = '2026-11-17';
function t17(h, m, s) { return at(h, m, s, 17); }
var rideRec = record({ offer: 'rd1', offered: t17(22, 32), took: t17(22, 32, 20), ended: t17(22, 55), pay: 22.10,
                       miles: 9.6, store: 'Sample St & Mock Ave, Faketown', door: 'Sample St & Mock Ave, Faketown',
                       drop: 'Storybook Ln & Fictional Ct, Notaville', cardMinutes: 20, cardMiles: 9.5 });
var rideO = E.ordersFrom([rideRec], []);
var rideE = keyed([Object.assign({ app: 'uber', date: D17 }, n17.entries[0])]);
var rideS = E.score(rideE[0], rideO[0], 0);
eq('[17nov match] a ride: its pickup street found on the card\'s corner for the name\'s points; its dropoff street, '
   + 'not on the card\'s corner, costs it nothing; its guessed amount earns no pay points',
   [rideS.parts.name, rideS.parts.dropoff, rideS.parts.pay], [E.W.name, 0, undefined]);
eq('[17nov match] ...and it is matched, on its clocks, its street and its miles',
   [E.matchDay(rideE, rideO)[rideE[0].key].status, E.matchDay(rideE, rideO)[rideE[0].key].offer], ['matched', 'rd1']);
eq('[17nov match] a delivery\'s other street still costs it, as before',
   E.score(Object.assign({}, rideE[0], { ride: undefined }), rideO[0], 0).parts.dropoff, -E.DROP_PENALTY);
var readWhole = Object.assign({}, rideE[0], { amount: 22.1 });
delete readWhole.amountGuessed;
var mg1 = E.mergeEntry(rideE[0], readWhole, 9000), mg2 = E.mergeEntry(readWhole, Object.assign({}, rideE[0], { amount: 2.21 }), 9100);
eq('[17nov match] a guessed amount is replaced by one read whole, its mark gone; a guess never replaces one read whole',
   [mg1.changed, mg1.entry.amount, mg1.entry.amountGuessed, mg2.changed, mg2.entry.amount], [true, 22.1, undefined, false, 22.1]);
var gRow = Object.assign({}, rideE[0], { match: E.matchDay(rideE, rideO)[rideE[0].key] });
eq('[17nov match] the card against paid: a guessed amount shown, never compared, and out of the day\'s compared total',
   [E.compareOf(gRow).pay, E.daySummary([gRow]).compared, E.daySummary([gRow]).guessed],
   [{ card: 22.1, paid: 22.1, guessed: true }, 0, 1]);
eq('[17nov match] the day\'s total as read, every trip matched or not, to hold against Uber\'s own day total',
   E.daySummary(n17.entries.map(function (e) { return Object.assign({ app: 'uber', date: D17 }, e); })).total,
   Math.round((22.1 + 11 + 21.3 + 19.75 + 30.1) * 100) / 100);

eq('[match] names are alike past OCR slips and abbreviations, and two restaurants are not',
   [E.similar('Make-Belleve Burgers', 'Make-Believe Burgers') >= E.NAME_MIN,
    E.similar('Sample Street Northwest', 'Sample St NW') === 1,
    E.similar('Pretend Pizza', 'Nowhere Noodles') < E.NAME_OTHER], [true, true, true]);

/* --- Uber's Acceptance rate screen (the owner, 15 Nov 2026) --------------
 * The text tesseract gives of an invented copy (rpi/testearnings.py
 * acceptance_screen), and the faults it is checked against. */
var ACC_TEXT = '7:41\n\n23%\n\nAcceptance rate\n\n4/10 last 10 exclusive requests\n\n'
  + 'Your acceptance rate is the percentage of exclusive trip\nrequests that you accepted over the last 100 requests.\n'
  + 'Exclusive trip requests are requests sent directly to you.\nYour acceptance rate excludes Trip Radar requests.\n\n'
  + 'Based on your last 100 exclusive requests\n\nExclusive trip requests 100\nAccepted 23\n\nDeclined 77\n';
function accOf(t) {
  var a = E.acceptanceScreen(t);
  return [a.requests, a.accepted, a.declined, a.rate, a.last10, a.ok, a.problems];
}
eq('acceptance screen: the three figures, the percentage and the last ten; the explanation\'s words read as none',
   accOf(ACC_TEXT), [100, 23, 23 + 54, 23, 4, true, []]);
eq('...figures read apart from their labels are taken in the box\'s order',
   accOf(ACC_TEXT.replace('requests 100\nAccepted 23\n\nDeclined 77\n', 'requests\nAccepted\n\nDeclined\n\n100\n23\n77\n')),
   [100, 23, 77, 23, 4, true, []]);
eq('...a second reading fills what the first left out (server.js asks again with --psm 6)',
   accOf([ACC_TEXT.replace('Accepted 23', 'Accepted'), ACC_TEXT.replace('23%', '')]), [100, 23, 77, 23, 4, true, []]);
eq('...a k/10 read "2/110" (the slash\'s foot taken for a 1) is still 2 of the last ten',
   accOf(ACC_TEXT.replace('4/10 last', '2/110 last'))[4], 2);
eq('...figures that do not add up are refused, not mended',
   accOf(ACC_TEXT.replace('Declined 77', 'Declined 71')).slice(5), [false, ['accepted and declined do not add up to the requests']]);
eq('...nor a percentage that is not accepted over requests',
   accOf(ACC_TEXT.replace('23%', '32%')).slice(5), [false, ['the percentage is not accepted ÷ requests']]);
eq('...and an earnings screenshot is not this screen', accOf('Earnings Activity\nSat, Nov 7\n$7.25 3:58 PM').slice(5),
   [false, ['not Uber\'s Acceptance rate screen']]);

console.log(bad ? '\n' + ok + ' passed, ' + bad + ' FAILED' : '\nAll ' + ok + ' earnings checks passed');
process.exit(bad ? 1 : 0);
