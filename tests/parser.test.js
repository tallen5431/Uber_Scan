/* Parser tests. Run with: node tests/parser.test.js
   The OCR-mangled cases are the point — clean text is the easy half. */

var P = require('../offer-parser.js');

var pass = 0, fail = 0;

function eq(name, got, want) {
  var ok = got === want || (Math.abs(got - want) < 0.001 && typeof got === 'number');
  if (ok) { pass++; } else { fail++; console.log('FAIL  ' + name + ': got ' + got + ' want ' + want); }
}

function check(name, text, want) {
  var p = P.parse(text);
  eq(name + ' / pay', p.pay, want.pay);
  eq(name + ' / minutes', p.minutes, want.minutes);
  eq(name + ' / miles', p.miles, want.miles);
  if (want.items !== undefined) eq(name + ' / items', p.items, want.items);
}

/* ---- the real card from the driver's screenshot ---- */

check('shop & deliver (verbatim)',
  'Shop & Deliver Exclusive $7.09 Guaranteed (incl. tip) 6 items (6 units) ' +
  '34 min (3.6 mi) total Dollar General (925 Shiloh Rd Nw) Hidden Forest Ct, Marietta Accept',
  { pay: 7.09, minutes: 34, miles: 3.6, items: 6 });

/* ---- OCR damage on that same card ---- */

check('OCR: $ read as S, 0 as O',
  'Shop & Deliver S7.O9 Guaranteed (incl. tip) 6 items (6 units) 34 min (3.6 mi) total',
  { pay: 7.09, minutes: 34, miles: 3.6, items: 6 });

check('OCR: decimal read as comma',
  '$7,09 Guaranteed 34 min (3,6 mi) total',
  { pay: 7.09, minutes: 34, miles: 3.6 });

check('OCR: spacing lost around units',
  '$7.09 34min (3.6mi) total',
  { pay: 7.09, minutes: 34, miles: 3.6 });

check('OCR: 1 read as l, 5 as S',
  '$l2.4S 23 min (8.4 mi) trip',
  { pay: 12.45, minutes: 23, miles: 8.4 });

/* ---- rideshare: two legs, no total, must sum ---- */

check('rideshare pickup + trip',
  '$12.45 5 min (1.2 mi) away 23 min (8.4 mi) trip',
  { pay: 12.45, minutes: 28, miles: 9.6 });

check('hours and minutes',
  '$41.80 1 hr 4 min (26.1 mi) total',
  { pay: 41.80, minutes: 64, miles: 26.1 });

/* ---- a "total" line must not be added to the legs it summarises ---- */

check('total wins over legs',
  '$9.00 8 min (2.0 mi) to store 14 min (4.0 mi) to customer 22 min (6.0 mi) total',
  { pay: 9.00, minutes: 22, miles: 6.0 });

/* ---- things that must never be mistaken for pay ---- */

check('street numbers are not pay',
  '$7.09 6 items 34 min (3.6 mi) total Dollar General (925 Shiloh Rd Nw) Hidden Forest Ct',
  { pay: 7.09, minutes: 34, miles: 3.6, items: 6 });

check('largest dollar figure wins over a promo line',
  'Was $4.50 now $11.25 20 min (5.0 mi) total',
  { pay: 11.25, minutes: 20, miles: 5.0 });

/* ---- partial reads: report what was found, flag incomplete ---- */

(function () {
  var p = P.parse('$7.09 Guaranteed (incl. tip) 6 items');
  eq('no time / pay found', p.pay, 7.09);
  eq('no time / minutes null', p.minutes, null);
  eq('no time / incomplete', p.complete, false);

  var q = P.parse('blurry nonsense with no numbers at all');
  eq('garbage / pay null', q.pay, null);
  eq('garbage / incomplete', q.complete, false);

  var r = P.parse('$7.09 34 min total');
  eq('time without miles / minutes', r.minutes, 34);
  eq('time without miles / miles null', r.miles, null);
  eq('time without miles / complete', r.complete, true);
})();

/* ---- the decimal point is the fragile character through a camera ---- */

(function () {
  // "3.6 mi" misread as "36 mi" implies 63 mph on a 34 minute errand.
  var p = P.parse('$7.09 6 items (6 units) 34 min (36 mi) total');
  eq('lost decimal recovered', p.miles, 3.6);
  eq('recovery is flagged', p.milesCorrected, true);
  eq('recovery is not uncertainty', p.milesUncertain, false);

  // A real highway trip must be left alone: 26.1 mi in 64 min is 24 mph.
  var q = P.parse('$41.80 1 hr 4 min (26.1 mi) total');
  eq('plausible distance untouched', q.miles, 26.1);
  eq('plausible not corrected', q.milesCorrected, false);

  // 40 mi in 45 min is 53 mph — fast, but a real highway run. Leave it.
  var f = P.parse('$60.00 45 min (40 mi) trip');
  eq('fast highway trip untouched', f.miles, 40);

  // Implausible but the decimal was clearly read, so this is not a lost point.
  var u = P.parse('$20.00 10 min (30.5 mi) total');
  eq('implausible with decimal is uncertain', u.milesUncertain, true);
  eq('uncertain keeps raw value', u.miles, 30.5);

  // A distance we distrust must never be turned into a mileage cost.
  var r = P.rate(u, { target: 25, costPerMile: 0.70 });
  eq('uncertain distance costs nothing', r.net, 20);
  eq('uncertain distance hides $/mile', r.perMile, null);
  eq('uncertain flag reaches the caller', r.milesUncertain, true);

  // Without the guard this offer reads as negative pay.
  var bad = P.parse('$7.09 34 min (36 mi) total');
  var br = P.rate(bad, { target: 25, costPerMile: 0.30 });
  eq('guarded rate stays positive', br.perHour > 0, true);
  eq('guarded rate matches truth', Math.round(br.perHour * 100) / 100, 10.61);
})();

/* ---- the rate math on the real offer ---- */

(function () {
  var p = P.parse('$7.09 6 items (6 units) 34 min (3.6 mi) total');

  var gross = P.rate(p, { target: 25, costPerMile: 0 });
  eq('real offer gross $/hr', Math.round(gross.perHour * 100) / 100, 12.51);
  eq('real offer verdict', gross.state, 'no');

  var net = P.rate(p, { target: 25, costPerMile: 0.30 });
  eq('real offer net $/hr', Math.round(net.perHour * 100) / 100, 10.61);

  // 6 items at 90s each adds 9 minutes of shopping the card does not mention.
  var shop = P.rate(p, { target: 25, costPerMile: 0.30, secondsPerItem: 90 });
  eq('with shopping time', Math.round(shop.perHour * 100) / 100, 8.39);
  eq('shopping minutes', shop.shopMinutes, 9);

  var generous = P.rate(p, { target: 10, costPerMile: 0 });
  eq('clears a $10 target', generous.state, 'go');

  // A rate a driver cannot reconstruct is a rate they cannot trust. Working
  // 7.09 over 34 minutes by hand gives $12.51/hr; the screen said $10.61 and
  // said nothing about the $1.08 of running costs that made up the gap. The
  // result has to carry enough to explain itself.
  eq('the deduction is reported', Math.round(net.cost * 100) / 100, 1.08);
  eq('...and the rate it came from', net.costPerMile, 0.30);
  eq('gross deducts nothing', gross.cost, 0);
  eq('...and says so', gross.costPerMile, 0);
  eq('net pay is pay less the deduction',
     Math.round(net.net * 100) / 100, Math.round((p.pay - net.cost) * 100) / 100);

  // A trip that takes no time pays infinitely well. parse() will not produce a
  // zero-minute offer, but `pad` is a number edited by hand in config.json and
  // a negative one cancels the trip out. This returned Infinity and a state of
  // 'go' - a confident ACCEPT on nonsense - while the Python threw
  // ZeroDivisionError and took the scan loop down with it.
  var nil = P.rate(p, { target: 25, costPerMile: 0, pad: -p.minutes });
  eq('no time left is not a verdict', nil.ready, false);
  eq('...and not a state either', nil.state, 'empty');
  var neg = P.rate(p, { target: 25, costPerMile: 0, pad: -p.minutes - 10 });
  eq('nor is negative time', neg.ready, false);
})();

/* ---- a reading that cannot be true ---- */
/* From 234 offers off a real rig: three that had lost a decimal point and two
   whose misread time implied 110 and 120 mph. Every one was shown as ACCEPT, in
   green. Checked here as well as in the Python because these two files must not
   disagree about what a real offer looks like - one of them is what the rig in
   the car decides on, the other is what the phone in the hand decides on, and a
   driver comparing the two would have no way to tell which was lying. */
(function () {
  var S = { target: 25, costPerMile: 0.30 };
  function card(pay, minutes, miles) {
    return { pay: pay, minutes: minutes, miles: miles, items: null,
             complete: true, milesUncertain: false, milesCorrected: false };
  }

  var lostPoint = P.rate(card(1184.0, 20.0, 3.9), S);
  eq('$11.84 read as $1184 is not an ACCEPT', lostPoint.state, 'doubt');
  eq('...and says which figure to look at', lostPoint.doubt, 'pay');
  eq('...while still being a complete row for the journal', lostPoint.ready, true);

  var fast = P.rate(card(56.65, 63.0, 115.6), S);
  eq('115 miles in 63 minutes is not an ACCEPT', fast.state, 'doubt');
  eq('...and names the distance', fast.doubt, 'speed');

  /* The same trip with the time read correctly is the fastest real average in
     that shift, 56 mph, and must get a verdict rather than a query. */
  var realLong = P.rate(card(56.65, 123.0, 115.6), S);
  eq('...but 115 miles in 123 minutes is believed', realLong.doubt, null);
  eq('...and judged: at 30c a mile it does not clear the target', realLong.state, 'no');

  /* Only the direction that produces a wrong ACCEPT is checked. */
  eq('crawling through traffic is a PASS, not a doubt',
     P.rate(card(7.09, 34.0, 3.6), S).state, 'no');
  eq('an ordinary offer is unaffected', P.rate(card(16.05, 23.0, 8.4), S).state, 'go');

  /* Judged on the card's own time, not on what the driver added to it. */
  eq('a huge pad does not make the card a misread',
     P.rate(card(30.0, 20.0, 4.0), { target: 25, costPerMile: 0.3, pad: 300 }).doubt, null);

  eq('a two-minute card is believed', P.rate(card(5.0, 2.0, 0.5), S).doubt, null);
  eq('a one-minute card is not', P.rate(card(5.0, 1.0, 0.5), S).doubt, 'time');
  eq('a very short hop is not judged on speed',
     P.rate(card(5.0, 3.0, 0.9), S).doubt, null);
})();

/* ---- a sum of one-decimal distances has one decimal ---- */
/* 3.5 + 6.1 is 9.600000000000001 in binary floating point, and twenty of one
   shift's 234 offers reached the journal and the CSV export looking like that. */
(function () {
  var two = P.parse('$12.00 8 min (3.5 mi) pickup 20 min (6.1 mi) dropoff');
  eq('two legs are summed', two.legs, 2);
  eq('...to a distance a card could have printed', String(two.miles), '9.6');
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED' : '\nAll ' + pass + ' parser checks passed');
process.exit(fail ? 1 : 0);
