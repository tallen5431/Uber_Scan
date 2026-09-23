/* What line to draw. Run with: node tests/advice.test.js
 *
 * This is the one piece of the project that tells a driver what to do rather
 * than what something says, so the bar is different. A wrong verdict costs one
 * offer; a wrong target costs every offer for as long as it stands.
 *
 * The first version of this estimated an arrival rate and did renewal-reward
 * arithmetic on it. It looked entirely reasonable and it was not: estimating a
 * rate means picking a number of minutes that separates "waiting" from "not
 * driving", and on one real recording the answer moved by a factor of three as
 * that constant went from 45 minutes to 5. So a good half of what is checked
 * here is that the answer does not depend on that constant — and that when it
 * does, nothing is claimed.
 */

var A = require('../advice.js');

var pass = 0, fail = 0;

function eq(name, got, want) {
  var ok = got === want
    || (typeof got === 'number' && typeof want === 'number' && Math.abs(got - want) < 1e-6);
  if (ok) pass++;
  else { fail++; console.log('FAIL  ' + name + ': got ' + got + ' want ' + want); }
}

function ok_(name, cond) { eq(name, !!cond, true); }

var MIN = 60000;

/* An offer as the journal stores one. `cost` is what the car took, so
   pay - cost is what the driver keeps. */
function offer(atMinutes, pay, minutes, cost) {
  return { at: 1000000000000 + atMinutes * MIN, pay: pay, minutes: minutes,
           billedMinutes: minutes, cost: cost || 0,
           suspect: 0, whole: 1, hidden: 0 };
}

/* ---- runs, not shifts ---- */
/* The driver's own words: "not all the time here is from one continuous shift".
   A recording is stretches of scanning separated by gaps, and a gap can be a
   break, a trip, or a rig left switched on in a driveway. */
(function () {
  var rows = A.usable([
    offer(0, 10, 20), offer(2, 10, 20), offer(4, 10, 20),
    // ...a two-hour hole...
    offer(124, 10, 20), offer(126, 10, 20)
  ]);
  eq('a gap longer than the threshold starts a new run', A.runs(rows, 30).length, 2);
  eq('...and a shorter one does not', A.runs(rows, 180).length, 1);

  // A run of one offer has no span. Counting it as an instant of driving would
  // divide earnings by nearly zero.
  var lonely = A.usable([offer(0, 10, 20), offer(600, 10, 20)]);
  eq('a single offer on its own is not a run', A.runs(lonely, 30).length, 0);
  eq('nothing at all is no runs', A.runs([], 30).length, 0);
})();

/* ---- a trip is not a break ---- */
/* The silence after an accepted offer is the driver driving it, and counting
   that as time off is what stopped this answering at all. On one real recording
   eight of the fifteen gaps over ten minutes came straight after a take; raw,
   the gaps smeared evenly across 15-38 minutes with no defensible place to cut,
   and the suggested line swung $39 to $19 depending where you cut. */
(function () {
  // Two offers, then a 39-minute silence, then two more. The silence is longer
  // than the 30-minute break threshold either way; what changes is whether the
  // job before it was one the driver drove.
  function around(job) {
    return A.usable([offer(0, 10, 20), job, offer(40, 10, 20), offer(42, 10, 20)]);
  }

  var took = offer(1, 30, 35); took.accepted = true;
  eq('the silence while driving an accepted job is not a break',
     A.runs(around(took), 30).length, 1);

  var passed = offer(1, 30, 35); passed.accepted = false;
  eq('...but the same silence after one that was passed up is',
     A.runs(around(passed), 30).length, 2);

  // A trip excuses its own length and not a minute more: a five-minute job
  // cannot account for a thirty-nine-minute silence.
  var brief = offer(1, 30, 5); brief.accepted = true;
  eq('a trip only excuses its own length', A.runs(around(brief), 30).length, 2);

  // An untagged take reads as a break, and must. Guessing which silences were
  // really trips is the kind of invention this file exists to refuse.
  eq('an untagged take is not guessed at',
     A.runs(around(offer(1, 30, 35)), 30).length, 2);

  // A card scanned DURING a tagged trip does not cancel the rest of it. The
  // phone goes on showing offers while the driver is carrying somebody — that
  // is exactly what the replay models when it skips everything before
  // `busyUntil` — so the trip's length has to be measured from the trip, not
  // from whichever row happened to be last. Measuring from the last row alone
  // split this run at 58, dropped the offer after the trip as a run of one,
  // and counted a silence against the one stretch that was tagged.
  var hour = offer(0, 30, 60); hour.accepted = true;
  var during = A.usable([hour, offer(5, 8, 20), offer(58, 8, 20)]);
  eq('an offer seen mid-trip does not end the trip', A.runs(during, 30).length, 1);
  eq('...and nothing after it is thrown away', A.runs(during, 30)[0].length, 3);
  eq('...nor is a silence counted inside a trip that was tagged',
     A.unexplained(during, 30).silences, 0);
  // The control: without the mid-trip scan the old arithmetic was already
  // right. Seeing a row must not make the record worse.
  eq('...which is the answer it gave when nothing was seen mid-trip',
     A.runs(A.usable([hour, offer(58, 8, 20)]), 30).length, 1);
  // Still a floor, not a licence. The trip ends at 60; a row at 95 is beyond
  // it by more than the threshold and is a break however it is measured.
  eq('a tagged trip still only covers its own length',
     A.runs(A.usable([hour, offer(5, 8, 20), offer(95, 8, 20), offer(97, 8, 20)]),
            30).length, 2);

  // And the replay still ignores what was actually taken. It simulates a
  // policy; what happened is the thing it is being compared against, not an
  // input to it. Here the accepted offer is the one that misses the line and
  // the declined one clears it, so the two answers cannot be confused.
  var meagre = offer(0, 5, 20); meagre.accepted = true;      // $15/hr, taken
  var rich = offer(30, 20, 20); rich.accepted = false;       // $60/hr, passed
  var sim = A.replay(A.runs(A.usable([meagre, rich]), 30), 30);
  eq('the replay takes what clears the line, not what was taken', sim.trips, 1);
  eq('...which is the one that cleared it', sim.earned, 20);
})();

/* ---- saying what would settle it ---- */
/* When the answer swings, "drive more" is often the wrong advice: the swing
   comes from not knowing which silences were breaks and which were trips, and
   the driver is the only one who can say. Counting the silences nothing
   accounts for is what lets the page ask for the one thing that would help. */
(function () {
  var quiet = A.usable([offer(0, 10, 20), offer(1, 10, 20),
                        offer(60, 10, 20), offer(61, 10, 20),
                        offer(200, 10, 20), offer(201, 10, 20)]);
  var bare = A.unexplained(quiet, 30);
  eq('two long silences, nothing to account for either', bare.silences, 2);
  eq('...and nothing marked as taken', bare.tagged, 0);

  var withTag = A.usable([offer(0, 10, 20), (function () {
    var t = offer(1, 10, 45); t.accepted = true; return t;
  })(), offer(60, 10, 20), offer(61, 10, 20),
    offer(200, 10, 20), offer(201, 10, 20)]);
  var some = A.unexplained(withTag, 30);
  eq('a marked trip accounts for the silence after it', some.silences, 1);
  eq('...and is counted as marked', some.tagged, 1);

  // ...for its own length and no more. A five-minute job followed by an hour of
  // quiet is exactly the stretch worth asking about, and skipping the gap
  // outright whenever the previous offer was taken hid it.
  var brief = A.usable([offer(0, 10, 20), (function () {
    var t = offer(1, 10, 5); t.accepted = true; return t;
  })(), offer(60, 10, 20), offer(61, 10, 20)]);
  eq('a short trip does not excuse a long silence',
     A.unexplained(brief, 30).silences, 1);

  // The count is what the shortfall carries, so the page can ask for tags
  // rather than for another shift.
  var thin = A.advise([offer(0, 10, 20), offer(1, 10, 20), offer(90, 10, 20)],
                      { target: 20 });
  eq('the shortfall says how many silences are unaccounted for', thin.silences, 1);
  eq('...and how many trips are marked', thin.tagged, 0);
})();

/* ---- a refusal has to be arithmetic somebody can check ---- */
/* The page prints the range and the swing in one sentence, so they have to be
   the same quantity. They were not: the low came from the bottom of the plateau
   and the high from the *top* of it, while the swing was measured across the
   bottoms alone — "anywhere between $18 and $41, a $21 swing", about three
   numbers that cannot all be true together. */
(function () {
  // Bursts of offers separated by silences at 16, 24, 33 and 47 minutes, which
  // is the shape that makes the answer depend on where the recording is cut —
  // every threshold from 15 to 90 falls somewhere different among them.
  function bursty(burst) {
    var gaps = [16, 24, 33, 47], rows = [], t = 0;
    for (var b = 0; b < 14; b++) {
      for (var i = 0; i < burst; i++) {
        rows.push(offer(t, 4 + ((b * 7 + i * 5) % 11) * 2, 20));
        t += 1 + (i % 3);
      }
      t += gaps[b % gaps.length];
    }
    return rows;
  }

  var out = A.advise(bursty(7), { target: 25 });
  eq('a recording split four ways refuses rather than picking one',
     out.reason, 'unsettled');
  eq('the swing is the distance between the two numbers printed beside it',
     out.high - out.low, out.spread);
  ok_('...and the range is a range', out.high >= out.low);
  ok_('...drawn from the line that would actually be recommended',
      out.checkedAt.every(function (e) {
        return e.low >= out.low && e.low <= out.high;
      }));

  // And the case that reads as a bug if it is squeezed into that sentence: the
  // recommended line does not move at all, and the plateau around it does. The
  // page has to say something other than "anywhere between $43 and $43".
  var steady = A.advise(bursty(3), { target: 25 });
  eq('a plateau that moves under a line that does not still refuses',
     steady.reason, 'unsettled');
  eq('...with no swing in the line itself', steady.spread, 0);
  ok_('...but a real one in the band, which is why', steady.bandSpread > 0);
})();

/* ---- the replay ---- */
(function () {
  // Six offers, ten minutes apart, each a 20-minute trip paying $10. Taking
  // everything: accept at 0, busy until 20, so the offers at 10 are skipped -
  // exactly what happens to an offer that arrives while you are driving.
  var rows = A.usable([offer(0, 10, 20), offer(10, 10, 20), offer(20, 10, 20),
                       offer(30, 10, 20), offer(40, 10, 20), offer(50, 10, 20)]);
  var r = A.replay(A.runs(rows, 30), 0);
  eq('an offer arriving mid-trip is not taken', r.trips, 3);
  eq('...and the ones that are, are', r.earned, 30);
  // Offers span minute 0 to 50, but the trip accepted at 40 runs to minute 60,
  // and those twenty minutes are the driver's. Billing only to the last offer
  // handed every run one free trip: the more a recording was broken up, the
  // higher the apparent rate and the higher the line that won — which is
  // exactly the fragmentation the driver said their record has.
  eq('the clock runs until the last trip ends, not the last offer',
     Math.round(r.hours * 60), 60);

  // A line nothing clears is a shift spent parked.
  eq('a line nothing clears takes nothing', A.replay(A.runs(rows, 30), 99).trips, 0);
  eq('...and earns nothing', A.replay(A.runs(rows, 30), 99).earned, 0);

  // Net, not gross. The target is a figure after running costs and mixing the
  // two is how a comparison stops meaning anything.
  var costly = A.usable([offer(0, 20, 60, 12)]);
  eq('what the car took comes off first', costly[0].net, 8);
  eq('...before the rate is worked out', costly[0].perHour, 8);
})();

/* ---- the whole point: the answer must not depend on the break threshold ---- */
/* A market where cheap offers are constant and good ones are occasional. The
   right line is somewhere above the cheap ones, and which minute-count is used
   to chop the recording into runs must not change that. */
(function () {
  var offers = [];
  for (var m = 0; m < 600; m += 3) {
    // every third offer is a good one; a 25-minute hole every 90 minutes, which
    // is exactly the length that different thresholds disagree about
    if (m % 90 > 64) continue;
    offers.push((m / 3) % 3 === 0 ? offer(m, 18, 30) : offer(m, 5, 30));
  }
  var seen = {};
  [15, 20, 30, 45, 60, 90].forEach(function (b) {
    var r = A.bestAt(A.usable(offers), b);
    seen[b] = r ? r.best.target : null;
  });
  var values = Object.keys(seen).map(function (k) { return seen[k]; });
  var spread = Math.max.apply(null, values) - Math.min.apply(null, values);
  ok_('the recommended line survives every break threshold', spread <= 2);

  var a = A.advise(offers, { target: 30 });
  // Not wrapped in `if (a.ready)`. It was, with `ok_('...gets an answer',
  // a.ready)` INSIDE the branch — true by construction — and an else arm that
  // accepted a refusal, so the whole block could go quiet and take five checks
  // with it and the count would simply drop. This market is built to be
  // answerable, so an answer is the assertion.
  ok_('a market this clear gets an answer (reason: %s)'.replace('%s', String(a.reason)),
      a.ready === true);
  ok_('...only ever when it held at every threshold', a.stable);
  eq('...having been checked at each one', a.checkedAt.length, A.THRESHOLDS.length);
  ok_('...with the line above the cheap tier', a.suggested > 5);
  ok_('...and a plateau around it, not a single point', a.high >= a.low);
  ok_('...pointing at the bottom of that plateau', a.suggested === a.low);
  // This market is the one that earns the strong wording: the recommended line
  // is the same number at every threshold, so the page may say so.
  eq('...and here the line really did not move', a.spread, 0);
})();

/* ---- "held" is not "did not move" ---- */
/* `stable` allows the recommended line to wander by UNSTABLE_SPREAD across the
   thresholds, which is $6. The offers page printed "the same line comes out
   however the recording is split into runs, which is why it is worth acting
   on" over the whole of that allowance — a stronger claim than this file
   makes, in the sentence whose job is to say why the number can be trusted.

   What is checked here is that the case is REACHABLE, because if it were not
   the wording would have been harmless and the fix pointless. It is not
   theoretical: over a thousand synthetic markets, 104 came out answered with a
   line that moved, 49 of them by $3 or more. The page's own version of this,
   measured end to end, is in rpi/test_offerspage.py. */
(function () {
  // The same generator the offers-page fixture uses, so the two are the same
  // market and a change to one is visible in the other.
  // BigInt for the step, because Python's integers are exact and a double is
  // not: s * 1103515245 runs past 2^53 on the second iteration, and the two
  // ports then walk different markets. Found by this check disagreeing with
  // the Python fixture it is supposed to share.
  var rows = [], s = 73n;
  for (var i = 0; i < 120; i++) {
    s = (s * 1103515245n + 12345n) % 2147483648n;
    var r = Number(s) / 2147483648;
    var mins = 10 + Math.floor(r * 30);
    var pay = 4 + Math.floor(r * r * 4000) / 100;
    rows.push({ at: 1700000000000 + Math.floor((i * 8 + r * 16) * MIN),
                pay: pay, minutes: mins, billedMinutes: mins, cost: 0,
                suspect: 0, whole: 1, hidden: 0 });
  }
  var w = A.advise(rows, { target: 25 });
  ok_('a market can be answered with a line that still moves', w.ready);
  ok_('...by as much as the threshold allows', w.spread === 6);
  ok_('...which is the whole allowance, not a rounding',
      w.spread === A.UNSTABLE_SPREAD);
  var lows = w.checkedAt.map(function (e) { return e.low; });
  eq('...and the six cuts do not agree', JSON.stringify(lows),
     JSON.stringify([24, 24, 30, 30, 30, 30]));
  eq('...while the figure shown is the one at the cut the page uses',
     w.suggested, 30);
})();

/* ---- it must refuse, far more often than it answers ---- */
(function () {
  eq('nothing at all is not an answer', A.advise([]).ready, false);
  eq('undefined is not an answer', A.advise(undefined).ready, false);
  eq('null is not an answer', A.advise(null).ready, false);

  var thin = [];
  for (var i = 0; i < 20; i++) thin.push(offer(i * 2, 10, 20));
  eq('one afternoon is not a season', A.advise(thin).ready, false);
  eq('...and it says how far along it is', A.advise(thin).offers, 20);
  ok_('...and what it is waiting for', A.advise(thin).needOffers > 0);

  // Plenty of offers inside twenty minutes: a rig left running against a
  // screenshot, not a shift.
  var burst = [];
  for (var j = 0; j < 100; j++) burst.push(offer(j * 0.2, 10, 20));
  eq('a hundred offers in twenty minutes is not two hours of driving',
     A.advise(burst).ready, false);

  // Enough offers and enough hours, but the line only ever produces two or
  // three trips. That is a recommendation resting on three coincidences.
  var sparse = [];
  for (var k = 0; k < 60; k++) sparse.push(offer(k * 5, 6, 200));
  var s = A.advise(sparse, { target: 25 });
  ok_('a handful of trips is not a finding', !s.ready);

  // Forty-four rows, of which the replay walks thirty-six. The other eight are
  // singles two hours from anything, so runs() drops each with its own
  // one-offer run at every threshold the stability check uses — they are never
  // evidence, at any setting.
  //
  // This is the case that tells the two counts apart. The headline was
  // corrected to report the walked pile and the gate was left on the raw one,
  // so a window could be refused by the number it printed and admitted by a
  // number it did not. Built so the run underneath is a clean, stable,
  // answerable market: with the gate on rows.length this comes out ready with
  // a line of $31 on it.
  var walked = [];
  for (var m = 0; walked.length < 36; m += 4) {
    if (m % 90 > 64) continue;
    walked.push((m / 4) % 3 === 0 ? offer(m, 18, 10) : offer(m, 5, 10));
  }
  var lastAt = (walked[walked.length - 1].at - 1000000000000) / MIN;
  var padded = walked.slice();
  for (var p = 1; p <= 8; p++) padded.push(offer(lastAt + 120 * p, 18, 10));

  eq('rows the replay never walked are not counted toward the threshold',
     A.advise(padded, { target: 30 }).ready, false);
  eq('...and the count it reports is the pile it walked',
     A.advise(padded, { target: 30 }).offers, 36);
  // The run on its own is the same answer, which is the point: the eight
  // stragglers changed nothing except the number the gate used to read.
  eq('...the stragglers having moved neither',
     A.advise(walked, { target: 30 }).offers, 36);
  // And the eight are accounted for rather than quietly missing. A refusal
  // that says "36 offers so far" over a list of 44 is the gap that makes a
  // reader distrust the rest of the page.
  eq('...with the eight it set aside named, not dropped',
     A.advise(padded, { target: 30 }).setAside, 8);
  eq('...and nothing set aside when nothing was',
     A.advise(walked, { target: 30 }).setAside, 0);
})();

/* ---- the rows a decision must not be built on ---- */
(function () {
  var good = [];
  for (var i = 0; i < 100; i++) good.push(offer(i * 3, 10, 20));

  // A card read as $1184 for a twenty-minute ride would, left in, drag the
  // recommended line above anything real and empty the shift.
  eq('a misread offer is not evidence about the market',
     A.usable(good.concat([{ at: 1, pay: 1184, minutes: 20, billedMinutes: 20,
                             cost: 0, suspect: 1, whole: 1, hidden: 0 }])).length,
     A.usable(good).length);

  // A card missing its pickup leg is the same pay over less time, so it always
  // reads better than it is.
  eq('a half-read card is not evidence either',
     A.usable(good.concat([{ at: 1, pay: 40, minutes: 10, billedMinutes: 10,
                             cost: 0, suspect: 0, whole: false, hidden: 0 }])).length,
     A.usable(good).length);

  // The test card a driver keeps presenting to check the rig still works.
  eq('a hidden offer stays out',
     A.usable(good.concat([{ at: 1, pay: 99, minutes: 5, billedMinutes: 5,
                             cost: 0, suspect: 0, whole: 1, hidden: 1 }])).length,
     A.usable(good).length);

  /* The legacy shape, and the reason this exclusion exists.
   *
   * Until 19 August the threshold for distrusting a distance (MAX_MPH, 55) and
   * the one for calling a whole reading suspect (SANE_MPH, 75) were different
   * numbers reached by different reasoning in different parts of the parser.
   * A journey computing between the two — a real highway run, or a misread
   * landing in that band — was written distrusted, not suspect, and whole.
   * Nothing above catches any of that, and rate() charges no mileage on a
   * distance it does not trust, so the row's $/hr is a before-costs figure
   * sitting in a list of after-costs ones. They are still in the journal. */
  function legacyUncertain(pay, minutes, costPerMile, atMinutes) {
    return { at: 1000000000000 + (atMinutes || 0) * MIN,
             pay: pay, minutes: minutes, billedMinutes: minutes,
             cost: 0, costPerMile: costPerMile, milesUncertain: true,
             suspect: 0, whole: 1, hidden: 0 };
  }

  eq('a rate with no running cost taken off it is not evidence either',
     A.usable(good.concat([legacyUncertain(40, 20, 0.35)])).length,
     A.usable(good).length);
  ok_('...and the test would pass on the old rule too unless it is this shape',
      !legacyUncertain(40, 20, 0.35).suspect
      && legacyUncertain(40, 20, 0.35).whole === 1);

  // ...but only where a running cost is actually charged. At zero nothing was
  // ever deducted from anything, so this rate is not out of step with its
  // neighbours and dropping it would throw away a good offer for a difference
  // that does not exist.
  eq('a rig that charges no mileage keeps them',
     A.usable(good.concat([legacyUncertain(40, 20, 0)])).length,
     A.usable(good).length + 1);
  eq('...and so does one that never recorded a cost per mile',
     A.usable(good.concat([legacyUncertain(40, 20, undefined)])).length,
     A.usable(good).length + 1);

  /* The whole point, in the figures the page is actually read for.
   *
   * Honest offers: $10 over twenty minutes with $3 of car, so $21/hr net.
   * Legacy rows: $30 over the same twenty minutes with nothing deducted, so
   * $90/hr — the shape a highway run took before 19 August. Excluded, the
   * typical rate is the honest one; left in, the same page reports a market
   * that does not exist. The `before` list is the same rows with the guard
   * defeated, which is what the old code did with them.
   *
   * An even split, and deliberately so. A handful of these among a hundred
   * honest rows moves a median barely at all — that is what a median is for,
   * and it is why this went unnoticed. What is being checked here is that the
   * rows are capable of moving the figures, not a claim about how many of them
   * anybody's journal holds. The quartiles and the recommended line are where
   * even a few of them show up first. */
  var honest = [], legacy = [];
  for (var g = 0; g < 20; g++) honest.push(offer(g * 3, 10, 20, 3));
  // Arriving after the honest ones and at the same spacing, so they form part
  // of the same shift rather than a run the replay would drop for having no
  // length — which is what a shared timestamp would make them.
  for (var t = 0; t < 20; t++) legacy.push(legacyUncertain(30, 20, 0.35, 60 + t * 3));

  function typicalOf(rows) {
    var v = rows.map(function (r) { return r.perHour; })
                .sort(function (x, y) { return x - y; });
    return v.length ? v[Math.floor(v.length / 2)] : null;
  }

  var after = A.usable(honest.concat(legacy));
  // Defeating the guard the only way the module allows: say no cost was ever
  // charged. Same pay, same minutes, same missing deduction.
  var before = A.usable(honest.concat(legacy.map(function (r) {
    var copy = {}; for (var k in r) copy[k] = r[k];
    copy.costPerMile = 0;
    return copy;
  })));

  eq('the honest rows all survive', after.length, honest.length);
  eq('...and the legacy ones are what the difference is', before.length,
     honest.length + legacy.length);
  eq('the typical rate is the after-costs one', Math.round(typicalOf(after)), 21);
  ok_('...where leaving them in reported a market that does not exist ('
      + Math.round(typicalOf(before)) + '/hr)',
      typicalOf(before) > typicalOf(after) + 5);
  // The advice built on the same rows describes a different shift: twice the
  // offers, twice the hours, and a replay earning two and a half times as much
  // per hour from them. The recommended *line* happens not to move on this
  // fixture — the plateau covers the same range either way, which is the point
  // of reporting a plateau rather than a maximum — so the claim made here is
  // the one that is true rather than the one that sounds worst.
  var adviceAfter = A.bestAt(after, 30), adviceBefore = A.bestAt(before, 30);
  eq('the replay walks only the honest rows', adviceAfter.offers, honest.length);
  eq('...where it used to walk all of them', adviceBefore.offers,
     honest.length + legacy.length);
  ok_('...and credited itself two and a half times the hourly rate for it ($'
      + Math.round(adviceBefore.best.perHour) + ' against $'
      + Math.round(adviceAfter.best.perHour) + ')',
      adviceBefore.best.perHour > adviceAfter.best.perHour * 2);

  eq('and so does a row with no pay',
     A.usable([{ at: 1, pay: null, minutes: 20, cost: 0 }]).length, 0);
  eq('or no time', A.usable([{ at: 1, pay: 10, minutes: 0, cost: 0 }]).length, 0);
  eq('or no clock', A.usable([{ pay: 10, minutes: 20, cost: 0 }]).length, 0);
  eq('or a pay that is not a number',
     A.usable([{ at: 1, pay: Infinity, minutes: 20, cost: 0 }]).length, 0);
  eq('or a clock that is not a number',
     A.usable([{ at: NaN, pay: 10, minutes: 20, cost: 0 }]).length, 0);
  eq('or a cost that is not a number',
     A.usable([{ at: 1, pay: 10, minutes: 20, cost: NaN }])[0].net, 10);
  eq('a row that is not a row at all', A.usable([null, 7, 'x']).length, 0);
})();

/* ---- rows out of order ---- */
/* The journal is append-only and the web side appends to it too, so nothing
   guarantees the file is sorted. A replay walked out of order would take an
   offer, then take one that arrived before it finished. */
(function () {
  var forwards = [], backwards = [];
  for (var i = 0; i < 60; i++) forwards.push(offer(i * 3, 10, 20));
  for (var j = 59; j >= 0; j--) backwards.push(offer(j * 3, 10, 20));
  var a = A.replay(A.runs(A.usable(forwards), 30), 0);
  var b = A.replay(A.runs(A.usable(backwards), 30), 0);
  eq('a shuffled journal replays the same way', b.trips, a.trips);
  eq('...and earns the same', b.earned, a.earned);
})();

/* ---- what it claims, and what it declines to claim ---- */
(function () {
  var offers = [];
  for (var m = 0; m < 900; m += 4) {
    if (m % 120 > 90) continue;
    offers.push(m % 12 === 0 ? offer(m, 20, 30) : offer(m, 6, 30));
  }
  var a = A.advise(offers, { target: 10 });
  ok_('an answer knows how many separate runs it is built from', a.runs >= 1);
  ok_('...and over how long', a.hours > 0);
  if (!a.ready) {
    ok_('...or refuses with a reason the page can render', !!a.reason);
  } else {
  ok_('...and how many trips the suggested line would have meant', a.trips > 0);

  // The improvement is a ratio on purpose. A dollar figure per hour would
  // depend on how much of the recorded time was really driving - the one thing
  // this cannot know - and on the recording it was built from that figure
  // ranged from $22 to $78 while the ratio stayed between +19% and +25%.
  ok_('the gain over a too-high target is positive', a.gain > 0);
  eq('nothing claims a dollars-per-hour the driver would earn', a.perHour, undefined);
  eq('nor an earnings figure', a.earned, undefined);

  }
  // No current target given, nothing to compare against, so no claim.
  eq('with no target set there is no comparison',
     A.advise(offers).gain, null);

  // A line nothing clears is a shift spent parked. The ratio is undefined
  // because the denominator is a driver earning nothing, and reporting that as
  // "no comparison available" would bury the one case where the target is
  // doing visible harm.
  var parked = A.advise(offers, { target: 500 });
  eq('a target nothing clears takes nothing', parked.current.trips, 0);
  eq('...which is not a missing comparison', parked.currentTakesNothing, true);
  eq('...and not a ratio either', parked.gain, null);
  eq('a workable target is not flagged that way',
     A.advise(offers, { target: 10 }).currentTakesNothing, false);
})();

/* ---- when the thresholds disagree, say so ---- */
(function () {
  // A recording whose whole character changes with where it is cut: a dense
  // burst of poor offers, then long gaps around a few excellent ones.
  var offers = [];
  for (var i = 0; i < 90; i++) offers.push(offer(i * 1.5, 4, 25));
  for (var j = 0; j < 12; j++) offers.push(offer(200 + j * 37, 40, 25));
  var a = A.advise(offers, { target: 25 });
  // Same shape as above, and the else arm here was `ok_(..., true)` — a check
  // that cannot fail, standing in for three that would not run. Whether this
  // market is answerable or refused, the fields it reports on are the claim:
  // a refusal has to name its reason, and an answer has to carry what it saw.
  if (a.ready) {
    ok_('a disagreement between thresholds is reported, not averaged away',
        typeof a.stable === 'boolean');
    ok_('...with the spread it saw', typeof a.spread === 'number');
    ok_('...and every threshold it asked at', a.checkedAt.length > 1);
  } else {
    ok_('...or it refuses, and names which refusal (reason: %s)'
          .replace('%s', String(a.reason)),
        ['thin', 'trips', 'unsettled', 'nolinehelps'].indexOf(a.reason) >= 0);
  }
})();

/* ---- the same offers, chopped up differently, must not change the answer ---- */
/* The driver's whole point. Their record is fragmented — four runs across ten
   hours with holes of 35 minutes, 39 minutes and nearly three hours — and the
   first version of this replay billed each run only from its first offer to its
   last, while keeping the full fare of a trip accepted near the end. One free
   trip per run: the more a recording was broken up, the higher the apparent
   rate and the higher the line that won. Measured at four runs of ten offers it
   reported $200/hr where the honest figure was $46. */
(function () {
  // Four runs, each nine minutes of cheap offers ending in a 30-minute fare.
  var offers = [];
  for (var r = 0; r < 4; r++) {
    for (var i = 0; i < 10; i++) {
      offers.push(i === 9 ? offer(r * 600 + i, 30, 30) : offer(r * 600 + i, 3, 30));
    }
  }
  var out = A.replay(A.runs(A.usable(offers), 30), 20);
  eq('four end-of-run fares are taken', out.trips, 4);
  eq('...and paid', out.earned, 120);
  // 4 runs x 9 min of offers = 36 min, plus 4 x 30 min of driving = 156 min.
  eq('...with all four trips on the clock', Math.round(out.hours * 60), 156);
  eq('...so the rate is the honest one, not four times it',
     Math.round(out.perHour), 46);

  // The same offers at the same spacing, cut into different numbers of runs.
  // Either the recommendation holds, or it refuses — what it must not do is
  // quietly climb with fragmentation while still reporting itself as stable.
  function chopped(runCount) {
    var out = [], per = Math.floor(200 / runCount), at = 0;
    for (var k = 0; k < runCount; k++) {
      for (var i = 0; i < per; i++) out.push(offer(at + i * 2.5, i % 3 === 0 ? 20 : 6, 25));
      at += per * 2.5 + 120;
    }
    return out;
  }
  var answers = [1, 2, 4, 10].map(function (n) {
    var a = A.advise(chopped(n), { target: 25 });
    return a.ready ? a.suggested : null;
  }).filter(function (v) { return v !== null; });
  if (answers.length > 1) {
    var swing = Math.max.apply(null, answers) - Math.min.apply(null, answers);
    ok_('breaking the same offers into more runs does not raise the line', swing <= 6);
  } else {
    ok_('...or it declines to answer, which is also correct', true);
  }
})();

/* ---- refusing, with a reason the page can act on ---- */
(function () {
  // A market where being selective buys nothing: every offer is the same, so
  // taking everything is exactly as good as any line. The plateau reaches zero,
  // and the bottom of that plateau is $0 — "set your target to nothing".
  var flat = [];
  for (var i = 0; i < 200; i++) flat.push(offer(i * 3, 10, 20));
  var a = A.advise(flat, { target: 25 });
  eq('a market with nothing to choose between offers no line', a.ready, false);
  eq('...and says that is what happened', a.reason, 'nolinehelps');
  eq('...rather than recommending zero', a.suggested, undefined);

  // Not enough yet.
  var thin = [];
  for (var j = 0; j < 20; j++) thin.push(offer(j * 2, 10, 20));
  var t = A.advise(thin, { target: 25 });
  eq('too little is refused', t.ready, false);
  ok_('...with what it is waiting for', t.needOffers > 0 && t.needHours > 0);

  // Every refusal must carry something the page can render, or the panel
  // silently disappears and a driver cannot tell it from a broken feature.
  [flat, thin, [], [offer(0, 10, 20)]].forEach(function (set, i) {
    var r = A.advise(set, { target: 25 });
    if (!r.ready) {
      ok_('refusal ' + i + ' can be explained',
          typeof r.offers === 'number' && typeof r.hours === 'number');
    }
  });
})();


/* --- two orders at once ---------------------------------------------------
 *
 * The arithmetic behind stacking, and — as much the point — the cases where it
 * has to refuse. This rig cannot see a map, so every claim it makes here has to
 * be true whatever the two routes turn out to look like.
 */
(function () {
  var SET = { target: 25, band: 15, costPerMile: 0.3 };
  var T0 = 1700000000000;
  function active(o) {
    return { pay: 12, minutes: 30, miles: 8, cost: 2.4, acceptedAt: T0,
             ...o };
  }
  function newOffer(o) { return { pay: 9, minutes: 20, miles: 6, cost: 1.8, ...o }; }

  // Ten minutes into a thirty-minute job: twenty left, two thirds of the fare
  // still to earn.
  var s = A.stack(active(), newOffer(), SET, T0 + 10 * 60000);
  ok_('a stack is worked out', !!s);
  eq('...with the right time left on the old order', s.leftMinutes, 20);
  // 12 - 2.4 = 9.60 net, two thirds of it = 6.40, plus 9 - 1.8 = 7.20.
  eq('...pro-rating the old order rather than counting it whole', s.pay, 13.6);
  eq('...worst case is the two times added', s.maxMinutes, 40);
  eq('...best case is the longer of the two', s.minMinutes, 20);
  eq('...and the worst rate divides by the worst time', s.worst, 20.4);
  eq('...the best rate by the best', s.best, 40.8);

  // The bound has to be a bound: nothing that could happen on any map may fall
  // outside it, and the order must never invert.
  ok_('the range is the right way round', s.best >= s.worst);
  ok_('...and the honest floor is the no-sharing case', s.worst <= s.best);

  // ACCEPT only when the WHOLE range clears the line. A range straddling the
  // target is a maybe, and a maybe drawn in green is a wrong answer.
  eq('a range straddling the target is not a green light', s.state, 'warn');
  eq('...it is green only when even the worst case clears it',
     A.stack(active(), newOffer({ pay: 30 }), SET, T0 + 10 * 60000).state, 'go');
  eq('...and red when even the best case does not',
     A.stack(active(), newOffer({ pay: 1, cost: 0 }), SET, T0 + 10 * 60000).state, 'no');

  // The claim that does not need the geography: better than just finishing,
  // even with nothing shared.
  // A real running cost on both sides, because `cost: 0` is not a tidier
  // fixture — it is the gross case, and this claim may not be made on it.
  ok_('a better-paying second job beats finishing alone',
      A.stack(active(), newOffer({ pay: 40 }), SET, T0 + 10 * 60000).sure);
  eq('...and a worse-paying one does not',
     A.stack(active(), newOffer({ pay: 1 }), SET, T0 + 10 * 60000).sure, false);

  // ...and it is not made at all when the offer printed no chargeable
  // distance. `sure` is the one clause stated without a hedge — the only one
  // the 3.5" hat has room for — and on a gross offer it is comparing a ceiling
  // with a net rate, which is the mixing of two kinds of money that caps
  // `state` seventeen lines above it. A pay of 40 against a held job of 12
  // clears by any measure; the point is that the rig will not say so.
  //
  // NULL, not false. Withheld and answered-no were the same value here, and a
  // reader cannot undo that: the offers page printed `sure ? yes : 'no — the
  // worst end is below finishing alone'` and so announced the opposite of the
  // truth on every withheld pair. This case is one — pay 40 against a held 12
  // clears comfortably — so `false` here would be a wrong answer, not a
  // missing one.
  eq('the unhedged claim is withheld when the offer has no cost taken off',
     A.stack(active(), newOffer({ pay: 40, cost: 0 }), SET, T0 + 10 * 60000).sure,
     null);
  ok_('...and withheld is a different value from answered-no, or no reader '
      + 'downstream can tell them apart',
      A.stack(active(), newOffer({ pay: 40, cost: 0 }), SET, T0 + 10 * 60000).sure
      !== A.stack(active(), newOffer({ pay: 1 }), SET, T0 + 10 * 60000).sure);
  ok_('...and the pair is still reported, marked as a ceiling',
      A.stack(active(), newOffer({ pay: 40, cost: 0 }), SET, T0 + 10 * 60000).uncosted);
  // The asymmetry is deliberate. A gross HELD job inflates netA, which sits in
  // both sides of the comparison — but `alone` divides it by the time left and
  // `worst` by that plus the new job, so the right-hand side rises faster and
  // the claim gets harder to make. Understating is the safe direction and
  // costs nothing to allow.
  ok_('...while a gross HELD job does not withhold it, because it understates',
      A.stack(active({ cost: 0 }), newOffer({ pay: 40 }), SET, T0 + 10 * 60000).sure);

  // Refusals. Each of these would otherwise put a second job's time against a
  // first job's pay and call it a rate.
  eq('no active order, no stack', A.stack(null, newOffer(), SET, T0), null);
  eq('no offer, no stack', A.stack(active(), null, SET, T0), null);
  eq('an order already over is not stacked onto',
     A.stack(active(), newOffer(), SET, T0 + 31 * 60000), null);
  eq('...nor one that ends exactly now',
     A.stack(active(), newOffer(), SET, T0 + 30 * 60000), null);
  eq('an order with no stated time is not stacked onto',
     A.stack(active({ minutes: null }), newOffer(), SET, T0), null);
  eq('...nor an offer with none', A.stack(active(), newOffer({ minutes: null }), SET, T0), null);
  eq('an offer with no payout is not stacked',
     A.stack(active(), newOffer({ pay: null }), SET, T0), null);
  eq('a zero-length order is refused rather than divided by',
     A.stack(active({ minutes: 0 }), newOffer(), SET, T0), null);
  // ...and so is a zero-length OFFER, which is the same division one field
  // along. `null` was already refused above by the is-it-a-number test, so a
  // guard covering only null looks complete and divides by zero on a real 0.
  eq('a zero-length offer is refused too',
     A.stack(active(), newOffer({ minutes: 0 }), SET, T0), null);
  eq('...and a negative one, which no card states and OCR can still produce',
     A.stack(active(), newOffer({ minutes: -5 }), SET, T0), null);

  // No accept time is not the same as no order. A rig restarted mid-delivery
  // knows the order and not the clock, and the honest reading of that is that
  // none of it has run yet — which is the pessimistic one.
  var noClock = A.stack(active({ acceptedAt: null }), newOffer(), SET, T0 + 99 * 60000);
  ok_('an order with no start time is still stacked, from the top', !!noClock);
  eq('...with all of its minutes still ahead', noClock.leftMinutes, 30);

  // Costs come off both sides, or the stacked figure is gross while every other
  // number on the same screen is net.
  var free = A.stack(active({ cost: 0 }), newOffer({ cost: 0 }), SET, T0 + 10 * 60000);
  ok_('mileage is deducted from the pair', free.pay > s.pay);

  // A figure rate() refused to score may not be re-scored here.
  //
  // rate() keeps `ready: true` and every number on an impossible reading so the
  // row reaches the journal, and withholds only the verdict. This function
  // looked at neither and rebuilt one. The real pair: held $11.84 / 20 min, the
  // next card's pay read as $1184 — headline blanked to "--", CHECK THE PAY,
  // and beneath it in green "$1791–$3580/hr · beats finishing alone".
  eq('an offer the reading doubted gets no pair verdict',
     A.stack(active(), newOffer({ pay: 1184, doubt: 'pay' }), SET, T0 + 10 * 60000),
     null);
  eq('...and neither does a doubted order in the car',
     A.stack(active({ doubt: 'time' }), newOffer(), SET, T0 + 10 * 60000), null);
  // The gate is the flag and not the size of the number: doubt() is where that
  // judgement lives, and a second opinion here is a second thing to drift.
  ok_('...while the same figures without the doubt are still judged',
      !!A.stack(active(), newOffer({ pay: 1184 }), SET, T0 + 10 * 60000));

  // An upper bound may not clear a net target — rate()'s rule, applied to a
  // pair. `target` was drawn against rates with running costs already off; a
  // card that printed no distance leaves nothing to take off, so the money is
  // gross and the comparison is between two different kinds of dollar.
  var noMiles = A.stack(active(), newOffer({ pay: 30, cost: 0 }), SET, T0 + 10 * 60000);
  ok_('a pair with nothing charged for the miles says so', noMiles.uncosted);
  eq('...and is capped at a close call however well it reads',
     noMiles.state, 'warn');
  ok_('...on a range that would otherwise have been green',
      noMiles.worst >= SET.target);
  // The held order counts too: either side being gross makes the pair gross,
  // and this is the case nothing on the driving screen would otherwise explain
  // — the note above the verdict only speaks about the offer.
  eq('an order in the car with no distance caps the pair as well',
     A.stack(active({ cost: 0 }), newOffer({ pay: 30 }), SET, T0 + 10 * 60000).state,
     'warn');
  // ...and the cap only exists because a cost per mile is configured. With
  // none set, `target` is a gross line and nothing is missing.
  eq('with no running cost configured there is nothing to cap',
     A.stack(active({ cost: 0 }), newOffer({ pay: 30, cost: 0 }),
             { target: 25, band: 15, costPerMile: 0 }, T0 + 10 * 60000).state,
     'go');
  // Capped, not demoted: below the floor it is still a PASS, exactly as
  // rate() leaves it.
  eq('...and a bad pair with no distance is still a pass',
     A.stack(active(), newOffer({ pay: 1, cost: 0 }), SET, T0 + 10 * 60000).state,
     'no');
})();

/* ---- where the two jobs end ---------------------------------------------
 *
 * Not a distance. The driver's ask was "close enough so that I don't take two
 * orders that end up in completely different places", so the only output that
 * matters is a veto, and it is deliberately asymmetric: a wrong "elsewhere"
 * costs a stack that could have been taken, a wrong "near" costs an hour and a
 * late delivery. All the addresses below are the driver's own, off real cards. */

eq('a town agreeing with only one quadrant known is the weaker claim',
   A.sameArea('Park Pl, Atlanta', 'Cobalt Dr NW & Ember Ln NW, Atlanta'), 'same-town');
eq('...and a town AND quadrant agreeing is the stronger one',
   A.sameArea('Hamby Place Dr NW & Travistock Pl NW, Acworth',
              'Brookstone Walk NW & Downington Trl NW, Acworth'), 'same-side');
// 354 of the agreeing pairs on file are Atlanta NE to Atlanta NE, and northeast
// Atlanta is not a neighbourhood. Saying "same side of town" is what was
// actually checked; saying "nearby" would be a promise the cards cannot keep.
eq('...which is a side of town, not a neighbourhood',
   A.sameArea('Armour Cir NE & Armour Dr NE, Atlanta',
              'N Highland Ave NE & Saint Louis Pl NE, Atlanta'), 'same-side');
eq('a different town is somewhere else',
   A.sameArea('Hamby Place Dr NW & Travistock Pl NW, Acworth',
              'Lakeview Ter & Windmill Dr, Dallas'), 'elsewhere');
eq('...the twenty-mile pair the driver actually stacked',
   A.sameArea('Cochran Ridge Rd & Jewel Cole Rd, Hiram',
              'Chastain Meadows Pkwy NW, Marietta'), 'elsewhere');
eq('...and the same town on opposite sides of it is too',
   A.sameArea('Cobalt Dr NW & Ember Ln NW, Atlanta',
              'E Twin Oaks Dr SE & Spruce Dr, Smyrna'), 'elsewhere');

/* --- handing a place to a map --------------------------------------------
 *
 * No coordinates are computed anywhere for this, and none are needed: the card
 * names places in words and a map takes words. The query goes to Google as
 * text and Google resolves it, in the driver's browser, when they press it.
 *
 * That is the safer design and not merely the cheaper one. A geocoder run by
 * the rig turns a misread street into a confident coordinate and then into a
 * distance on the panel - wrong, and silent. Opened as a map, the same
 * misreading is a pin in the wrong place, which a person spots at a glance. */

eq('a cross-street goes to a map as the card wrote it',
   A.mapSearch('Duval Ct & Manchester Ln, Villa Rica'),
   'https://www.google.com/maps/search/?api=1&query='
   + 'Duval%20Ct%20%26%20Manchester%20Ln%2C%20Villa%20Rica');
// The ampersand is the whole point of encoding this rather than pasting it:
// 72% of this driver's distinct dropoffs are cross-streets, so an unencoded
// "&" would truncate the query on nearly three quarters of them.
eq('...with the ampersand encoded, not ending the query',
   A.mapSearch('Oak Ln & Elm St').indexOf('%26') > 0, true);
// ...and a pair of bare initials is not a cross-street. Every real place has a
// word in it, so two letters running is the floor - without it "S & B" from an
// icon row opens a map of somewhere confident and irrelevant.
eq('two initials are not a place', A.mapSearch('A & B'), null);

eq('two ends become a route with driving directions',
   A.mapRoute('Grace St & Hidden Forest Ct, Marietta', 'Canton Rd, Marietta'),
   'https://www.google.com/maps/dir/?api=1'
   + '&origin=Grace%20St%20%26%20Hidden%20Forest%20Ct%2C%20Marietta'
   + '&destination=Canton%20Rd%2C%20Marietta&travelmode=driving');

// The refusals. A link to a map of somewhere irrelevant is worse than no link:
// it costs a press and a moment's belief, and the driver is deciding.
eq('icon-row scrap is not a place', A.mapSearch('} :'), null);
eq('a single letter is not a place', A.mapSearch('j'), null);
eq('nothing is not a place', A.mapSearch(''), null);
eq('and neither is a missing one', A.mapSearch(null), null);
eq('a route needs both ends', A.mapRoute('Canton Rd, Marietta', null), null);
eq('...either of them', A.mapRoute(null, 'Canton Rd, Marietta'), null);

// The route rides on the stack advice, because that is where the question is
// asked: both ends are DROPOFFS, which is how far apart the two jobs finish.
(function () {
  var now = 1700000000000;
  var held = { pay: 16.05, minutes: 36, acceptedAt: now - 5 * 60000,
               dropoff: 'Grace St & Hidden Forest Ct, Marietta' };
  var offer = { pay: 12.0, minutes: 24, miles: 6.6, ready: true,
                dropoff: 'Duval Ct & Manchester Ln, Villa Rica' };
  var cfg = { target: 25, band: 15, costPerMile: 0.3 };
  var s = A.stack(held, offer, cfg, now);
  eq('the stack line carries a route between the two ends',
     typeof s.route === 'string' && s.route.indexOf('Villa%20Rica') > 0, true);
  eq('...and still says what it checked in the card\'s own words',
     s.ends, 'elsewhere');

  // Half of real pairs name only one end, and a route to nowhere is not an
  // answer - it is a control that opens a map of the wrong thing.
  var blind = A.stack({ pay: 16.05, minutes: 36, acceptedAt: now - 5 * 60000,
                        dropoff: null }, offer, cfg, now);
  eq('no route when the order in the car ends nowhere named',
     blind.route, null);
}());

/* --- the address scanned off the screen after the accept ------------------
 *
 * An offer card carries no ZIP - Uber prints "Customer dropoff" and no address
 * until the job is taken - so everything below is reachable only once the
 * driver has pressed the button and the rig has read the screen that follows.
 * It is the finest key available and it changes the answer where the answer was
 * weakest: 44% of this driver's placed dropoffs are in Atlanta, which is 135
 * square miles, and a metro ZIP is a few. */

// The integration that had to land with the parser or the feature would have
// gone backwards. PLACE_TOWN anchors on the END of the string and a full
// address ends in a ZIP, so before PLACE_ZIP was stripped first, area() of a
// scanned address was null - and the geography went SILENT on exactly the
// orders the scan was added to rescue.
eq('an address is a place, not a null',
   JSON.stringify(A.area('1234 Daffodil Ln, Powder Springs, GA 30127')),
   JSON.stringify({ town: 'powder springs', quadrant: null, zip: '30127' }));
eq('...and a card-derived place still is one',
   JSON.stringify(A.area('Chastain Rd NW, Kennesaw')),
   JSON.stringify({ town: 'kennesaw', quadrant: 'NW', zip: null }));

eq('one ZIP is the strongest thing these two can agree on',
   A.sameArea('1234 Daffodil Ln, Powder Springs, GA 30127',
              '88 Lilac Springs Dr, Powder Springs, GA 30127'), 'same-zip');
eq('...and it outranks the town, which is the point of scanning at all',
   A.sameArea('55 Peachtree St NE, Atlanta, GA 30303',
              '9 Piedmont Ave NE, Atlanta, GA 30303'), 'same-zip');

// The asymmetry, and the reason it is not symmetric. ZIPs tile finely, so two
// that merely differ are often next door - concluding "elsewhere" from that
// would refuse stacks a mile apart. A fine-grained key is safe for
// STRENGTHENING a near and never for manufacturing a far, because a wrong
// "elsewhere" costs a fare and a wrong "near" costs an hour and a rating.
// Deciding how far apart two different ZIPs are needs their centroids, which
// this rig does not have and will not guess at.
eq('two ZIPs that differ are not evidence of distance',
   A.sameArea('55 Peachtree St NE, Atlanta, GA 30303',
              '9 Boulevard NE, Atlanta, GA 30312'), 'same-side');
eq('...and inside one town they are still the same town',
   A.sameArea('1 Oak Ln, Powder Springs, GA 30127',
              '2 Elm St, Powder Springs, GA 30144'), 'same-town');
// ...but a different TOWN still is, exactly as before. The ZIP adds a stronger
// agreement; it takes nothing away from the veto that was already there.
eq('a different town is still somewhere else, ZIP or no ZIP',
   A.sameArea('1234 Daffodil Ln, Powder Springs, GA 30127',
              '12 Oak Ln, Marietta, GA 30060'), 'elsewhere');

// A scanned address on one side and a card-read cross-street on the other,
// which is the ordinary case: the order in the car was scanned, the offer being
// judged is a card. One being precise says nothing about the other.
eq('a scanned end and a card-read end still compare',
   A.sameArea('1234 Daffodil Ln, Powder Springs, GA 30127',
              'Lilac Springs Dr, Powder Springs'), 'same-town');
eq('...and disagree when they should',
   A.sameArea('1234 Daffodil Ln, Powder Springs, GA 30127',
              'Canton Rd, Marietta'), 'elsewhere');
eq('a ZIP on one side alone promises nothing',
   A.sameArea('Chastain Rd NW, Kennesaw', 'GA 30127'), null);

// Atlanta alone covers 250 of the 960 places the parser reads off these cards,
// so the town on its own is far too coarse. The quadrant is what splits it, and
// the split is real: the Atlanta dropoffs on file run NE 50, NW 20, SE 10, SW 5.
eq('the same town on opposite quadrants is somewhere else',
   A.sameArea('Cobalt Dr NW & Ember Ln NW, Atlanta',
              'Ormewood Ave SE & Woodland Ave SE, Atlanta'), 'elsewhere');
// The card's icon row lands between the comma and the town. All four of these
// are real dropoffs off this driver's cards.
eq('a stray glyph before the town does not hide it',
   A.area('Grace St & Hidden Forest Ct, } Marietta').town, 'marietta');
eq('...nor do several of them',
   A.area('Grady Grier Dr & New Towne Dr, , : Powder Springs').town, 'powder springs');
eq('...nor a stray capital',
   A.area('Crestmont Pkwy & Haygoode Dr, E Marietta').town, 'marietta');
// ...and the same mark in lower case, which is the same mark. Taking one and
// refusing the other is not a rule about towns, it is an accident of which
// glyph tesseract picked - and it left area() returning null on 25 of the 1528
// places on file, with the town printed perfectly plainly beside the furniture.
// All four of these are real dropoffs off this driver's cards.
eq('...nor a stray letter in lower case, which is the same icon',
   A.area('Daffodil Ln & Lilac Springs Dr, j Powder Springs').town,
   'powder springs');
eq('...whichever letter the icon came back as',
   A.area('Grant Dr NW & Russell Dr NW, i Kennesaw').town, 'kennesaw');
eq('...including one that is also an English word',
   A.area('Campus Loop Rd NW & Owl Dr, a Kennesaw').town, 'kennesaw');
eq('...and mixed in among the glyphs',
   A.area('Holly Springs Rd & Skylane Dr, j 4 Marietta').town, 'marietta');
// A whole lower-case WORD is not the icon row, and must not be skipped: it is
// either part of the name or evidence this is not an address at all.
eq('a whole lower-case word before the town is not stray furniture',
   A.area('Cobalt Dr NW, near Marietta').town, null);
eq('a town after a full stop is still the town',
   A.area('Double Branches Ln & Sagamore Ct. Dallas').town, 'dallas');
// ...but the abbreviation that ate the comma must not become one.
eq('a street abbreviation is not a town', A.area('Cobb Pkwy. NW').town, null);
eq('...and a two-letter state code is not one either',
   A.area('Somewhere, IL'), null);

// A quadrant has to be a word of its own. 28 of the places on file contain an
// ALL-CAPS word - "HOME DEPOT 0156", "GOODFELLAS PIZZA & WINGS", "MIDTOWN" - and
// KENNESAW has an NE inside it. A town that shouts must not donate a compass
// point it never printed, or two dropoffs in the same town read as opposite
// sides of it.
eq('a capitalised town does not donate a quadrant',
   A.sameArea('HOME DEPOT 0156 I Stonewall Dr, KENNESAW',
              'Cobb Place Ln NW, Kennesaw'), 'same-town');

// OCR shouts: this driver's cards carry "COBB PKWY & MARS" and "shallowford rd".
// A town that came back in capitals is the same town.
eq('a town in capitals is the same town',
   A.sameArea('Cobb Pkwy NW, ACWORTH', 'Main St NW, Acworth'), 'same-side');

// --- one town, read two ways ------------------------------------------------
//
// PLACE_TOWN allows a second capitalised word because towns have them, and it
// anchors on the end of the string - so one more capitalised word out of the
// OCR joins the town. 21 of the 73 distinct town readings on file are a real
// town with a junk word stuck to it (`Acworth Page`, `Kennesaw State`,
// `Marietta BORE`), and 96 pairs of real dropoffs were being called `elsewhere`
// on that alone.
eq('a junk word stuck to the town does not make it another town',
   A.sameArea('Cobb Pkwy NW, Acworth', 'Main St, Acworth Page'), null);
eq('...in either order',
   A.sameArea('Main St, Acworth Page', 'Cobb Pkwy NW, Acworth'), null);
// The other shape, and the reason dropping the second word is not the fix: the
// regex anchors on the end, so `Sandy Springs` would read as `springs` and the
// two readings would stop relating at all.
eq('...and a town clipped short of its second word is the same town',
   A.sameArea('Alastair Dr, Sandy Springs',
              'Peachtree Dunwoody Rd, Sandy'), null);
// It withdraws an `elsewhere`; it never manufactures a `near`. Staking the
// expensive mistake - an hour and a rating - on a guess about OCR damage is
// exactly what this rule must not do.
eq('...but two readings that merely COULD be one town are never called near',
   ['same-town', 'same-side', 'same-zip'].indexOf(
     A.sameArea('Cobb Pkwy NW, Acworth', 'Main St, Acworth Page')), -1);
// The word boundary is what makes it safe. Douglas and Douglasville are two
// different Georgia towns, 150 miles apart.
eq('a town whose name merely starts the same is still elsewhere',
   A.sameArea('Main St, Douglas', 'Bankhead Hwy, Douglasville'), 'elsewhere');
// And getting past the town veto is not a pass on the quadrant one.
eq('two readings that could be one town still disagree about a quadrant',
   A.sameArea('Cobb Pkwy NW, Acworth', 'Main St SE, Acworth Page'), 'elsewhere');

// Half of real pairs land here, and saying nothing is the answer they get.
eq('a dropoff the card did not name says nothing',
   A.sameArea('Luckie St NW & Spring St NW, Atlanta', null), null);
eq('...nor does a place with neither a town nor a quadrant',
   A.sameArea('Somewhere', 'Elsewhere'), null);
eq('a shared quadrant alone is a whole side of the metro, not a promise',
   A.sameArea('George Busbee Pkwy NW', 'Cobb Place Ln NW, Kennesaw'), null);

// The veto rides on stack(), which is what the driving screen reads.
var heldFar = { pay: 12, minutes: 30, cost: 1, acceptedAt: 0,
                dropoff: 'Cochran Ridge Rd & Jewel Cole Rd, Hiram' };
var offerFar = { pay: 10, minutes: 20, cost: 1,
                 dropoff: 'Chastain Meadows Pkwy NW, Marietta' };
var far = A.stack(heldFar, offerFar, { target: 25 }, 0);
eq('stack() reports where the pair ends', far.ends, 'elsewhere');
eq('...and still reports the money, which the geography only qualifies',
   typeof far.worst === 'number' && typeof far.best === 'number', true);
var near = A.stack(heldFar,
   { pay: 10, minutes: 20, cost: 1, dropoff: 'Jewel Cole Rd, Hiram' },
   { target: 25 }, 0);
eq('...and says so when they end in the same place', near.ends, 'same-town');
var blind = A.stack(heldFar, { pay: 10, minutes: 20, cost: 1 }, { target: 25 }, 0);
eq('...and says nothing when the second card named nowhere', blind.ends, null);

/* ---- which offers arrived while a ticked job was running -----------------
 *
 * The one measured piece of occupancy the record holds, as against replay()'s
 * simulated one. What is checked here is mostly what it must REFUSE to say:
 * it can only see jobs that were ticked, so "nothing returned" has to mean
 * "no ticked job was running" and never "the driver was free". */
(function () {
  var MIN = 60000;
  //  a: ticked, 20 min          b: 5 min in, not ticked     c: 8 min in, ticked
  //  d: half an hour later, free                            e: never ticked
  var rows = [
    { at: 0,        net: 16, mins: 20, id: 'a', took: true },
    { at: 5 * MIN,  net: 9,  mins: 15, id: 'b', took: false },
    { at: 8 * MIN,  net: 12, mins: 10, id: 'c', took: true },
    { at: 30 * MIN, net: 7,  mins: 12, id: 'd', took: false },
  ];
  var b = A.busy(rows);
  eq('an offer inside a ticked job is marked', !!b.b, true);
  eq('...naming the job it arrived into', b.b.into[0].id, 'a');
  eq('...and it was not itself taken', b.b.stacked, false);
  // The strongest thing to get wrong: the driver demonstrably took this one.
  eq('an offer inside a window that was ITSELF ticked is marked as a stack',
     b.c.stacked, true);
  eq('an offer after the job ended is not marked', b.d, undefined);
  // The job that defines a window is not inside its own window.
  eq('a ticked job is not counted as busy against itself', b.a, undefined);

  // The boundaries. An offer at the exact moment a job starts or ends is not
  // inside it — measured on the real record, strict and inclusive bounds give
  // the identical 333, so the rule is chosen for being defensible rather than
  // for changing an answer.
  var edge = A.busy([
    { at: 0,       net: 16, mins: 20, id: 'a', took: true },
    { at: 0,       net: 9,  mins: 5,  id: 'start', took: false },
    { at: 20 * MIN, net: 9, mins: 5,  id: 'end', took: false },
  ]);
  eq('an offer at the very start of a job is not inside it', edge.start, undefined);
  eq('...nor one at the very moment it ends', edge.end, undefined);

  // Nothing ticked is not the same as nothing busy, and it must produce no
  // claim at all rather than a claim that everything was free.
  eq('with no ticks at all, nothing is marked',
     Object.keys(A.busy([{ at: 0, net: 9, mins: 10, id: 'x', took: false },
                          { at: MIN, net: 9, mins: 10, id: 'y', took: false }])).length,
     0);
  // A row with no id cannot be joined back to anything, so it is skipped
  // rather than keyed on undefined.
  eq('a row with no id is skipped',
     Object.keys(A.busy([{ at: 0, net: 16, mins: 20, took: true },
                          { at: MIN, net: 9, mins: 5, took: false }])).length, 0);

  // freeAgain is the shared definition runs() and unexplained() both use, and
  // busy() is the third caller. It is a floor on occupancy, not a measurement.
  eq('an untaken offer frees the driver the moment it appears',
     A.freeAgain({ at: 100, mins: 20, took: false }), 100);
  eq('...and a taken one for the minutes it stated',
     A.freeAgain({ at: 100, mins: 20, took: true }), 100 + 20 * MIN);

  // usable() has to carry the id or none of this can be joined to a row.
  var carried = A.usable([{ at: 1, id: 'keepme', pay: 10, minutes: 20,
                            perHour: 30, whole: true }]);
  eq('usable carries the id through', carried.length && carried[0].id, 'keepme');
})();

/* ---- the figures beside the recommendation belong to the recommendation ---- */
/* `suggested` is the BOTTOM of the plateau and `shown.best` is the argmax.
   Usually those are the same number — the replay curve climbs to its peak and
   the 95% band spreads upward from there — which is why this went unnoticed and
   why the shape below had to be hunted for. The page prints them in one
   sentence: "taking the first one at or above $12 whenever free gives 173
   trips." At $12 it gives 187.

   The existing check asked only `a.trips > 0`, which both lines satisfy: it
   named the right property and could not tell them apart.

   The shape is a two-population market — a bulk of cheap offers around $10/hr
   and a dense cluster between $38 and $52 — which is what puts a shallow
   shoulder under the argmax and pulls the plateau's bottom a long way below it.
   It is contrived, and it has to be: a check built on a recording where the two
   lines coincide cannot fail whatever the code does. The guard below says so
   out loud rather than letting that happen quietly. */
(function () {
  // Built from a rate rather than a payout, because the ladder this walks is
  // in dollars per hour — a fact worth stating here, since every other fixture
  // in this file names a payout and a duration and leaves it implied.
  function rate(min, r, dur) {
    var row = offer(min, r * dur / 60, dur);
    row.perHour = r;
    return row;
  }
  var rows = [];
  for (var m = 0, i = 0; m < 60 * 160; m += 6, i++) {
    if (m % 180 > 150) continue;
    rows.push(rate(m, (i % 4 === 0) ? 38 + ((i * 7) % 56) / 4
                                    : 9 + ((i * 5) % 12) / 4, 30));
  }
  var a = A.advise(rows, { target: 10 });
  ok_('the two-line shape produces an answer at all', a.ready);
  if (a.ready) {
    var steps = A.runs(A.usable(rows), 30);
    var at = A.replay(steps, a.suggested);
    // The recommendation is well below the best-scoring line here, which is
    // the only condition under which the three checks after it mean anything.
    ok_('...whose recommendation ($' + a.suggested + ') is below the '
        + 'best-scoring line ($' + a.high + '), or nothing below could fail',
        a.suggested < a.high);
    // And it is the bottom of the plateau that is recommended, not the peak.
    // Deliberately: a lower line takes more work for the same money and leaves
    // less riding on the recording being representative, and being too picky is
    // the failure that hides itself. Pinned here because this is the one
    // fixture where the two are far enough apart to tell.
    eq('...and it is the bottom of the plateau that is recommended',
       a.suggested, a.low);
    eq('the trips quoted are the ones the suggested line takes',
       a.trips, at.trips);
    eq('...and the takes', a.takes, at.takes);
    eq('...and the hours the money is divided by',
       Math.round(a.hours * 100), Math.round(at.hours * 100));
  }
})();

/* --- which part of the day a row belongs to -------------------------------
 *
 * The offer log's "By time of day" chart and map.html's `when` box are cut on
 * these, and they are here rather than in either page because two copies of
 * eight edges is two answers to one question. Everything below is about the
 * two ways that goes wrong: an edge that moves, and a stamp no clock can read.
 */
(function () {
  eq('the day is cut into eight blocks', A.BLOCK_NAMES.length, 8);
  // Every name pinned, because these are read by a driver off a chart and off
  // a select, and a block called "3–6pm" that holds 6pm is a chart that lies
  // quietly. A length check alone would pass with all eight named "night".
  eq('...and they are named for the hours they hold',
     A.BLOCK_NAMES.join('|'),
     '12–3am|3–6am|6–9am|9am–12|12–3pm|3–6pm|6–9pm|9pm–12');

  // Local hours, off the reading device's own clock — the same rule the offer
  // log's dayOf uses, and the only rule available, since no journal row
  // carries a timezone. Built with the local Date constructor deliberately:
  // an ISO string with a Z would test UTC and pass wherever this ran.
  function at(h, m) { var d = new Date(2026, 8, 18, h, m || 0, 0); return d.getTime(); }

  eq('midnight opens the first block', A.blockOf(at(0, 0)), 0);
  // Both sides of one edge, which is the only way an off-by-one is visible:
  // a rule shifted by an hour puts 14:59 and 15:00 in the same block.
  eq('...and 2:59pm is still the afternoon block', A.blockOf(at(14, 59)), 4);
  eq('...and 3:00pm opens the next one', A.blockOf(at(15, 0)), 5);
  eq('...and 11:59pm is still the last one', A.blockOf(at(23, 59)), 7);

  // The branch the offer log used to die on. `new Date(1e20).getHours()` is
  // NaN, `Math.floor(NaN / 3)` is NaN, and indexing an eight-element array
  // with NaN gives undefined — so the push threw inside the chart pass and
  // took the charts below it down with it. The journal has held such a row:
  // CLOCK_BELIEVABLE_UNTIL in server.js exists because one arrived stamped
  // 1e20, and the server filters the LOW end of that range, not the high one.
  eq('a stamp past the end of time has no block rather than a NaN one',
     A.blockOf(1e20), null);
  eq('...and so does the largest date there is, plus one',
     A.blockOf(8.64e15 + 1), null);
  eq('...and so does something that is not a time at all',
     A.blockOf('a Tuesday'), null);
  // ...and the guard has not swallowed the ordinary case with them.
  eq('...while the largest date there IS still has one',
     A.blockOf(8.64e15), 0);

  /* How many separate days a pile of rows came off.
   *
   * The whole hazard of a by-the-hour view: "9pm–12 pays $14.43" reads as a
   * habit and may be one evening. On the owner's real week the three busiest
   * blocks rest on three separate evenings each and 3–6am rests on one, and
   * nothing but this count tells those two apart. */
  eq('three rows in one evening are one day',
     A.daysIn([{ at: at(20, 0) }, { at: at(21, 0) }, { at: at(23, 30) }]), 1);
  // Forty minutes apart and a different day, which is the case a duration
  // would get wrong and a calendar date gets right.
  eq('...and either side of midnight is two',
     A.daysIn([{ at: at(23, 40) }, { at: at(24, 20) }]), 2);
  // A week later is the same weekday and the same hour, and it is not the
  // same day — the case a key built from the hour alone would fold into one.
  eq('...and the same hour a week later is two',
     A.daysIn([{ at: at(20, 0) }, { at: at(20, 0) + 7 * 24 * 60 * MIN }]), 2);
  eq('nothing came off no days', A.daysIn([]), 0);
  eq('...and so does nothing at all', A.daysIn(null), 0);
  eq('a row no clock can read is not a day',
     A.daysIn([{ at: 1e20 }, { at: at(20, 0) }]), 1);
})();


/* ---- which areas paid, and whether that may be said at all ---- */
/*
 * The feature this guards is a ranking a driver would act on by DRIVING
 * somewhere, so the thing most worth checking is not that it ranks — anything
 * ranks — but that it REFUSES. The obvious version of this feature, a league
 * table of the places the cards named, is noise on the owner's own week at
 * p = 0.21, and a page printing it would have sent them across town on a coin
 * toss. So every check below comes in a pair: a fixture with a real difference
 * in it, and one with the same group sizes, the same rates and no difference,
 * which has to come back refused.
 */
(function () {
  function day(n, h, m) {
    return new Date(2026, 8, 14 + n, h, m || 0, 0).getTime();
  }
  /* A counted offer in a town. `whole` and the two flags are what
     Advice.trustworthy looks at; a row it would not stand behind is not
     evidence about a town and must not reach the ranking. */
  function inTown(town, rate, when) {
    return { at: when, perHour: rate, dropoff: 'Some St & Other St, ' + town,
             pay: 10, minutes: 20, whole: 1, suspect: 0, hidden: 0 };
  }
  var KEY = function (o) {
    var p = String(o.dropoff || '').split(',');
    return p.length > 1 ? p[p.length - 1].trim() : null;
  };

  // Two towns, ten offers each, over two evenings, and one really does pay
  // more than the other. No overlap at all, which is the clearest signal the
  // data could carry — and the point of starting here is that if THIS comes
  // back "chance" the test is broken rather than strict.
  var clear = [];
  for (var i = 0; i < 10; i++) {
    clear.push(inTown('Rich', 24 + i * 0.1, day(i % 2, 19, i)));
    clear.push(inTown('Poor', 9 + i * 0.1, day(i % 2, 20, i)));
  }
  var sharp = A.areas(clear, { key: KEY });
  eq('two towns are ranked', sharp.groups.length, 2);
  eq('...the better-paying one first', sharp.groups[0].name, 'Rich');
  ok_('...at its own median', sharp.groups[0].median > 24);
  eq('...with the offers behind it counted', sharp.groups[0].n, 10);
  eq('...and the separate days behind it', sharp.groups[0].days, 2);
  ok_('...and a difference this clean is not called chance', sharp.real);
  eq('...with the odds said as a number the page can print', sharp.p, 0);

  // The SAME twenty rates, the same two towns, the same ten-and-ten split —
  // dealt out so neither town has an edge. Everything above still holds and
  // the verdict has to flip, or the test above passed on a function that
  // always says yes.
  var muddled = [];
  for (var j = 0; j < 20; j++) {
    var rate = (j < 10 ? 24 + j * 0.1 : 9 + (j - 10) * 0.1);
    // The day varies independently of the town, or each town lands on one
    // evening and the day floor drops it before the test is even reached.
    muddled.push(inTown(j % 2 ? 'Rich' : 'Poor', rate,
                        day(Math.floor(j / 2) % 2, 19, j)));
  }
  var noise = A.areas(muddled, { key: KEY });
  eq('...the same rates dealt evenly still make two towns', noise.groups.length, 2);
  eq('...over the same number of offers', noise.groups[0].n, 10);
  ok_('...but that ranking is refused', !noise.real);
  ok_('...on odds the page can quote back', noise.p > A.AREA_ALPHA);

  // The same window twice must not answer differently. A page that says
  // "act on this" on one press and "this is chance" on the next, over the
  // same rows, has told the driver nothing twice.
  eq('the same window gets the same verdict twice',
     A.areas(clear, { key: KEY }).p, sharp.p);
  // ...and the exact odds, not merely the same odds. `p` equal to itself
  // passes under Math.random() too, and under any other deterministic
  // sequence — it is only the VALUE that pins the seeded shuffle this file
  // promises. 0.68 is what 500 seeded shuffles make of a fixture with no
  // difference in it; if the shuffling changes, this is the check that says
  // so rather than a verdict quietly moving across the line somewhere else.
  eq('...on the exact odds a seeded shuffle gives', noise.p, 0.68);
  eq('...from the statistic behind them', noise.h, 0.14);

  // Ties, which real rates are full of — a shift of $12.00 twenty-minute
  // deliveries is a pile of identical $/hr. Ranks have to be AVERAGED across
  // them, or a tied run is ranked in whatever order the rows happened to
  // arrive in and the same window answers differently depending on how the
  // server sorted it. Held by giving the same offers in the opposite order.
  // Every offer the same to the cent, which is the case that makes the
  // difference visible: averaged, the two towns tie exactly and the ranking is
  // refused. Ranked by position instead, whichever town's rows the server
  // happened to send first takes the whole bottom half of the ranks and the
  // page reports one town as paying better than another when not one offer
  // between them differed.
  var tied = [];
  for (var y = 0; y < 8; y++) tied.push(inTown('Flat', 15, day(y % 2, 19, y)));
  for (var z = 0; z < 8; z++) tied.push(inTown('Same', 15, day(z % 2, 20, z)));
  var forward = A.areas(tied, { key: KEY });
  var backward = A.areas(tied.slice().reverse(), { key: KEY });
  eq('a window full of tied rates is ranked at all', forward.groups.length, 2);
  eq('...and reversing the rows does not change the odds', backward.p, forward.p);
  eq('...nor the statistic behind them', backward.h, forward.h);
  ok_('...and two towns paying identically are not told apart', !forward.real);
  eq('...with nothing at all between them', forward.h, 0);

  // The floor. Seven offers is not a median to read, and a town dropped for
  // that has to be COUNTED rather than quietly missing — the second fault
  // class, one level down.
  var thin = clear.slice();
  for (var k = 0; k < 7; k++) thin.push(inTown('Tiny', 30, day(k % 2, 21, k)));
  var withThin = A.areas(thin, { key: KEY });
  eq('a town under the floor is not ranked', withThin.groups.length, 2);
  eq('...it is counted as left out', withThin.thin, 1);
  eq('...with its offers', withThin.thinOffers, 7);
  ok_('...and it is not the one that would have led the list',
      withThin.groups[0].name === 'Rich');

  // ...and the day floor, which is the one that keeps a single evening from
  // wearing a habit's clothes. Ten offers is plenty; one outing is not.
  var oneNight = clear.slice();
  for (var n = 0; n < 10; n++) oneNight.push(inTown('Once', 30, day(0, 19, n)));
  eq('ten offers from one evening are not a town that pays',
     A.areas(oneNight, { key: KEY }).groups.length, 2);

  // The case calendar dates get wrong, and the whole reason outingsIn exists.
  // One shift, 10pm to 1am, is ONE outing — and two calendar dates. Counted
  // the old way this town clears a floor of two days on a single night out.
  var overnight = clear.slice();
  for (var m = 0; m < 5; m++) overnight.push(inTown('Late', 30, day(0, 22, m)));
  for (var q = 0; q < 5; q++) overnight.push(inTown('Late', 30, day(1, 1, q)));
  var spanning = A.areas(overnight, { key: KEY });
  eq('one shift across midnight is one outing, not two days',
     spanning.groups.length, 2);
  eq('...and it is counted as left out like any other thin town',
     spanning.thin, 1);
  // The control for that: the same ten offers, the same hours, two nights
  // apart, really are two outings and really do get ranked.
  var twoNights = clear.slice();
  for (var t = 0; t < 5; t++) twoNights.push(inTown('Late', 30, day(0, 22, t)));
  for (var u = 0; u < 5; u++) twoNights.push(inTown('Late', 30, day(2, 1, u)));
  eq('...while the same offers on two separate nights are ranked',
     A.areas(twoNights, { key: KEY }).groups.length, 3);

  // A row the rig would not stand behind is not evidence about a town. Asked
  // of trustworthy rather than of a fourth copy of the rule.
  var doubted = clear.slice();
  for (var v = 0; v < 12; v++) {
    doubted.push(Object.assign(inTown('Doubt', 900, day(v % 2, 22, v)), { suspect: 1 }));
  }
  eq('a town made of suspect rows is not a town that pays',
     A.areas(doubted, { key: KEY }).groups.length, 2);

  // What the key could not name. Silence here would report the window as
  // tidier than it is.
  var nameless = clear.concat([
    { at: day(0, 19), perHour: 40, dropoff: 'Nowhere', whole: 1, suspect: 0, hidden: 0 }
  ]);
  eq('an offer whose card named no town is counted, not dropped',
     A.areas(nameless, { key: KEY }).unnamed, 1);
  eq('...and the ones that did are counted too',
     A.areas(nameless, { key: KEY }).named, 20);

  // Refusals. Each of these would otherwise rank something against nothing.
  eq('one town alone is not a ranking', A.areas(clear.filter(function (o) {
    return KEY(o) === 'Rich';
  }), { key: KEY }).real, false);
  eq('...and says so rather than quoting odds', A.areas(clear.filter(function (o) {
    return KEY(o) === 'Rich';
  }), { key: KEY }).p, null);
  eq('no offers, no ranking', A.areas([], { key: KEY }).groups.length, 0);
  eq('...nor from nothing at all', A.areas(null, { key: KEY }).groups.length, 0);
  // Without a key this file would have to know how to read a place name, and
  // it deliberately does not. See the header: the grouping comes from the card.
  eq('no key, no ranking', A.areas(clear, {}).groups.length, 0);

  /* ---- holding the hour still ---- */
  //
  // The correction that makes this feature honest rather than flattering. A
  // town's rate is tangled with WHEN the driver is in it: on the owner's own
  // week 12-3am paid $21.24 and 3-6pm paid $14.17, and 57 of Atlanta's 98
  // offers are in the first while 40 of Marietta's 82 are in the second. Raw,
  // Atlanta leads Marietta by $5.38; with the hours held still it is $2.45,
  // the best-to-worst gap drops from $6.47 to $3.69, and three towns change
  // places. A driver reading the raw list would drive to Atlanta at six in the
  // evening and find the six-o'clock rate.
  //
  // The fixture is that failure in its purest form: the two towns pay
  // IDENTICALLY at any given hour, and one of them is only ever visited during
  // the good hour. Raw it is a landslide. Held still there is nothing there at
  // all, and nothing can move between the towns under a within-hour shuffle,
  // so the page must refuse it.
  var GOOD = 21, POOR = 11;
  function atHour(town, h, rate, n2) {
    return inTown(town, rate, new Date(2026, 8, 14 + n2, h, 0, 0).getTime());
  }
  var clockOnly = [];
  for (var w = 0; w < 10; w++) {
    clockOnly.push(atHour('Late', 1, GOOD + (w % 3) * 0.5, w % 2));
    clockOnly.push(atHour('Early', 16, POOR + (w % 3) * 0.5, w % 2));
  }
  var HOUR = function (o) { return new Date(o.at).getHours() < 12 ? 'late' : 'early'; };
  var unheld = A.areas(clockOnly, { key: KEY });
  ok_('a town seen only during the good hour looks like a landslide', unheld.real);
  ok_('...by a wide margin', unheld.spread > 9);
  var held = A.areas(clockOnly, { key: KEY, strata: HOUR });
  ok_('...and with the hour held still there is nothing there', !held.real);
  eq('...nothing at all', held.p, 1);
  eq('...and neither town is better than its own hour', held.groups[0].matched, 0);
  eq('...nor is the other', held.groups[1].matched, 0);
  ok_('...while the raw medians are still reported, being what was earned',
      held.groups[0].median > 20 || held.groups[1].median > 20);
  ok_('...and the page is told which spread is which',
      held.matched === true && held.rawSpread > held.spread);

  // The control, and the half that says this does not simply refuse
  // everything: a town that pays better AT THE SAME HOURS still comes through.
  var reallyBetter = [];
  for (var x = 0; x < 10; x++) {
    reallyBetter.push(atHour('Rich', 1, GOOD + 6 + (x % 3) * 0.5, x % 2));
    reallyBetter.push(atHour('Rich', 16, POOR + 6 + (x % 3) * 0.5, x % 2));
    reallyBetter.push(atHour('Poor', 1, GOOD + (x % 3) * 0.5, x % 2));
    reallyBetter.push(atHour('Poor', 16, POOR + (x % 3) * 0.5, x % 2));
  }
  var stillReal = A.areas(reallyBetter, { key: KEY, strata: HOUR });
  ok_('a town that pays more at the same hours survives holding them still',
      stillReal.real);
  eq('...and is named first', stillReal.groups[0].name, 'Rich');
  ok_('...by what is left once the hour is out of it',
      stillReal.groups[0].matched > stillReal.groups[1].matched);

  // The two orders are NOT the same list, which is the only reason the
  // distinction is worth making on screen. `Flash` earns more per hour than
  // `Steady` — it is almost always out during the good hour — and `Steady` is
  // the better town to be in, because at any given hour it pays more. On the
  // owner's own week this is Atlanta against Mableton: Atlanta leads by
  // median and Mableton by what is left.
  //
  // A third town carries the fixture, and it has to. What an hour pays is
  // taken from the offers in it, so with only the two towns being compared the
  // one that dominates an hour IS that hour's baseline and comes out level
  // with itself by construction. A metro is not two towns, and neither is this
  // — `Middle` works both hours evenly at the going rate and is what the other
  // two are measured against.
  var crossed = [];
  for (var c = 0; c < 12; c++) {
    crossed.push(atHour('Middle', c < 6 ? 1 : 16,
                        (c < 6 ? GOOD : POOR) + (c % 3) * 0.2, c % 2));
    // Flash is out during the good hour and paid the going rate for it.
    crossed.push(atHour('Flash', c < 9 ? 1 : 16,
                        (c < 9 ? GOOD : POOR) + (c % 3) * 0.2, c % 2));
    // Steady works the poor hour and beats the going rate wherever it is.
    crossed.push(atHour('Steady', c < 3 ? 1 : 16,
                        (c < 3 ? GOOD : POOR) + 4 + (c % 3) * 0.2, c % 2));
  }
  var byPaid = A.areas(crossed, { key: KEY });
  var byLeft = A.areas(crossed, { key: KEY, strata: HOUR });
  eq('the town that earned most is the one out at the best hour',
     byPaid.groups[0].name, 'Flash');
  eq('...and the town worth being in is the other one',
     byLeft.groups[0].name, 'Steady');
  ok_('...which is why the ranking is ordered by what is left',
      byLeft.groups[0].matched > byLeft.groups[1].matched);
  ok_('...even though it is not the one with the bigger median',
      byLeft.groups[0].median < byLeft.groups[1].median);

  // One hour is no hours to hold still. Once the driver has picked a block the
  // filter has already done it, every offer is measured against the same
  // baseline, and `matched` would be the median shifted by a constant — the
  // same order, reported as though something had been controlled for.
  var oneHour = [];
  for (var e = 0; e < 10; e++) {
    oneHour.push(atHour('Here', 1, GOOD + (e % 3) * 0.5, e % 2));
    oneHour.push(atHour('There', 1, POOR + (e % 3) * 0.5, e % 2));
  }
  var single = A.areas(oneHour, { key: KEY, strata: HOUR });
  eq('two towns inside one hour are still ranked', single.groups.length, 2);
  eq('...but nothing is held still, because nothing varies',
     single.matched, false);
  eq('...so the figure on the row is what the town paid',
     single.groups[0].median > 20, true);

  /* ---- outings against calendar days ---- */
  // Two questions, not two answers to one. daysIn is right for a BLOCK, which
  // lies inside one calendar date by construction; outingsIn is right for
  // anything that does not.
  var nightOut = [{ at: day(0, 22, 0) }, { at: day(1, 1, 0) }];
  eq('a shift across midnight is two calendar days', A.daysIn(nightOut), 2);
  eq('...and one outing', A.outingsIn(nightOut), 1);
  eq('...while two evenings are two of both',
     A.outingsIn([{ at: day(0, 22, 0) }, { at: day(1, 22, 0) }]), 2);
  // 4am is the edge, so both sides of it are the check that says where it is.
  eq('3:59am still belongs to the night before',
     A.outingsIn([{ at: day(0, 22, 0) }, { at: day(1, 3, 59) }]), 1);
  eq('...and 4:00am opens a new one',
     A.outingsIn([{ at: day(0, 22, 0) }, { at: day(1, 4, 0) }]), 2);
  eq('a row no clock can read is not an outing',
     A.outingsIn([{ at: 1e20 }, { at: day(0, 22, 0) }]), 1);
  eq('nothing came off no outings', A.outingsIn([]), 0);
  eq('...and so does nothing at all', A.outingsIn(null), 0);
})();

console.log(fail ? '\n' + pass + ' passed, ' + fail + ' FAILED'
                 : '\nAll ' + pass + ' target-advice checks passed');
process.exit(fail ? 1 : 0);
