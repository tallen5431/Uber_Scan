/* Turns the raw text of an Uber offer card into pay / minutes / miles / items.
   Shared by the camera scanner and the test suite so both agree exactly.

   Written to survive OCR, which is why it is forgiving about lookalike
   characters, stray punctuation and words glued together. Real cards look like:

     $7.09  Guaranteed (incl. tip)   6 items (6 units)   34 min (3.6 mi) total
     $12.45   5 min (1.2 mi) away    23 min (8.4 mi) trip
     $18.20   1 hr 4 min (26.1 mi) total
*/

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.OfferParser = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Characters OCR routinely swaps for digits, but only ever applied inside a
  // token we already believe is a number.
  var DIGIT_FIX = {
    O: '0', o: '0', Q: '0', D: '0',
    l: '1', I: '1', i: '1', '|': '1', '!': '1',
    S: '5', s: '5',
    B: '8', b: '6',
    Z: '2', z: '2',
    g: '9', G: '6', T: '7'
  };

  function fixDigits(token) {
    var out = '';
    for (var i = 0; i < token.length; i++) {
      var c = token[i];
      out += DIGIT_FIX.hasOwnProperty(c) ? DIGIT_FIX[c] : c;
    }
    return out;
  }

  // The whole token has to be the number, not just the start of it.
  //
  // This is where the two parsers came apart. `parseFloat` reads a leading
  // number and silently discards whatever follows, while Python's `float()`
  // rejects the lot — so on text an OCR engine really produces they disagreed
  // about the money. Fuzzed over 4000 damaged cards, 36000 field comparisons,
  // 317 disagreements: "53L min" was 53 minutes here and no leg at all there,
  // turning one card into a 62-minute job on the phone and a 9-minute one on
  // the Pi. "18.^6 mi" read as 18.8 on one side and was dropped on the other.
  //
  // The strict reading is the one to keep. A digit string with rubbish stuck to
  // it is not a number that happens to have a typo, it is a measurement nobody
  // should be acting on — and dropping it leaves the reading incomplete, which
  // the rest of this already handles properly by refusing to call it whole.
  var NUMERIC = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

  function toNumber(token) {
    if (token === undefined || token === null) return null;
    // OCR often reads a decimal point as a comma, and thousands separators
    // never appear on these cards, so a comma is always a decimal point.
    var s = fixDigits(String(token)).replace(',', '.').trim();
    if (!NUMERIC.test(s)) return null;
    var n = parseFloat(s);
    return isFinite(n) ? n : null;
  }

  // Flatten whatever the OCR engine produced into one forgiving line.
  function normalize(text) {
    return String(text || '')
      .replace(/[‘’“”]/g, "'")
      .replace(/[–—−]/g, '-')
      .replace(/ /g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /* ---------- pay ---------- */

  // Digits as OCR may render them. Kept narrow on purpose: letters like G and T
  // are corrected inside a confirmed number but are too risky to match on.
  var DC = '[\\dOoQlIiSsBbZz]';

  // A dollar sign is often read as S, 5 or §. Require a currency-ish marker so
  // that bare numbers (item counts, addresses, times) can never be mistaken for pay.
  var MONEY_STRICT = new RegExp('\\$\\s*(' + DC + '{1,4}(?:[.,]' + DC + '{1,2})?)', 'g');
  // The fallback insists on cents, which every Uber payout has. Without that it
  // will invent one: "E 61 St & S Rhodes Ave" came back from a real card as
  // "S 4S Rhodes", which this read as a $45.00 offer — a confident ACCEPT on a
  // $7 job. Guessing the currency symbol is already one guess; allowing a
  // digits-only amount on top of it is two, and addresses are full of tokens
  // that survive two guesses.
  var MONEY_LOOSE = new RegExp('(?:^|[\\s(])[$S5§]\\s?(' + DC + '{1,4}[.,]' + DC + '{2})', 'g');

  function findPay(text) {
    var all = collect(text, MONEY_STRICT);
    if (!all.length) all = collect(text, MONEY_LOOSE);
    if (!all.length) return null;

    // Cards can show a promo or a struck-through figure alongside the real
    // payout; the offer headline is the largest dollar figure on the card.
    var best = null;
    for (var i = 0; i < all.length; i++) {
      var v = toNumber(all[i].value);
      if (v !== null && v > 0 && v < 2000 && (best === null || v > best)) best = v;
    }
    return best;
  }

  function collect(text, re) {
    var out = [], m;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      out.push({ value: m[1].trim(), index: m.index, match: m[0] });
      if (m.index === re.lastIndex) re.lastIndex++;
    }
    return out;
  }

  /* ---------- time and distance ---------- */

  // "34 min (3.6 mi) total", "1 hr 4 min (26.1 mi)", "23 min (8.4mi) trip".
  // The distance group is optional so a time with no miles still registers.
  // The minute unit has to be spelled out. It was once allowed to be a bare
  // "m", and on a map full of street names that turns any two letters into a
  // journey: "ZIM" out of the road texture became a 21-minute leg, which is
  // enough to make a screen with no offer on it look like an offer. The "i" may
  // still be a lookalike, because that is one guess inside a confirmed word.
  var LEG = new RegExp(
    '(?:(\\d{1,2})\\s*h(?:r|rs|our|ours)?\\s*)?' +   // optional hours
    '(' + DC + '{1,3})\\s*m[il1|]n(?:s|ute|utes)?\\b' +
    '(?:[^(\\d]{0,6}\\(?\\s*(' + DC + '{1,3}(?:[.,]' + DC + '{1,2})?)\\s*m(?:i|ile|iles)\\b\\s*\\)?)?',
    'gi'
  );

  var ITEMS = new RegExp('(' + DC + '{1,3})\\s*items?\\b', 'i');

  function findLegs(text) {
    var legs = [], m;
    LEG.lastIndex = 0;
    while ((m = LEG.exec(text)) !== null) {
      var hours = toNumber(m[1]) || 0;
      var mins = toNumber(m[2]);
      // The number has to contain a real digit. "SI min" is two guesses
      // stacked, and stacked guesses are how noise becomes data.
      if (mins === null || !/\d/.test(String(m[2]))) continue;
      var minutes = hours * 60 + mins;
      if (minutes <= 0 || minutes > 600) continue;

      var miles = toNumber(m[3]);
      if (miles !== null && (miles < 0 || miles > 500)) miles = null;
      // A decimal point is one or two pixels through a camera and is the first
      // thing to be lost, so remember whether this reading actually had one.
      var hadDecimal = m[3] !== undefined && /[.,]/.test(String(m[3]));

      // Recover a decimal lost from this leg alone, before it reaches the sum.
      // "20 min (7.3 mi)" read as "(73 mi)" is a 219 mph leg, and left alone it
      // does more than inflate the distance: a merger keying legs by distance
      // files it as a third leg beside the real one, so a 23-minute card
      // reports 43 minutes.
      var fixed = recoverDecimal(minutes, miles, hadDecimal);
      miles = fixed.miles;

      // Uber labels a combined figure "total"; a card that has one is not also
      // listing its legs, so mixing the two would double count the trip.
      var tail = text.slice(m.index + m[0].length, m.index + m[0].length + 14).toLowerCase();
      legs.push({
        minutes: minutes, miles: miles, hadDecimal: hadDecimal || fixed.corrected,
        isTotal: /\btota?l\b/.test(tail), corrected: fixed.corrected
      });

      if (m.index === LEG.lastIndex) LEG.lastIndex++;
    }
    return legs;
  }

  /* ---------- plausibility ---------- */

  // No offer averages highway speed door to door once pickup, lights and
  // parking are in it. A reading above this means the distance was misread.
  var MAX_MPH = 55;

  // Deliberately narrower than checkDistance: only ever divides by ten, only
  // when the reading had no decimal at all, and only when that lands the leg
  // back in a believable range. Anything else is left for the total to judge,
  // because leg times are whole minutes and a two-minute leg is too coarse to
  // argue with — a rounded 2 min over 2.0 mi is already "60 mph" and real.
  function recoverDecimal(minutes, miles, hadDecimal) {
    if (miles === null || miles === undefined || !minutes || hadDecimal) {
      return { miles: miles, corrected: false };
    }
    if (miles / (minutes / 60) <= MAX_MPH) return { miles: miles, corrected: false };
    var recovered = miles / 10;
    var mph = recovered / (minutes / 60);
    if (mph >= 0.5 && mph <= MAX_MPH) return { miles: recovered, corrected: true };
    return { miles: miles, corrected: false };
  }

  // Guards against the one OCR failure that silently inverts the answer:
  // losing the decimal in "3.6 mi" turns a 6 mph errand into a 63 mph one, and
  // the phantom 32 extra miles can swallow the whole fare as mileage cost.
  function checkDistance(minutes, miles, hadDecimal) {
    if (miles === null || minutes === null || minutes <= 0) {
      return { miles: miles, corrected: false, uncertain: false };
    }
    var mph = miles / (minutes / 60);
    if (mph <= MAX_MPH) return { miles: miles, corrected: false, uncertain: false };

    // A missing decimal is the likeliest cause, and only when the reading did
    // not have one to begin with. Recovering it must be visible, never silent.
    if (!hadDecimal && (mph / 10) <= MAX_MPH && (mph / 10) >= 0.5) {
      return { miles: miles / 10, corrected: true, uncertain: false };
    }
    return { miles: miles, corrected: false, uncertain: true };
  }

  /* ---------- public ---------- */

  function parse(rawText) {
    var text = normalize(rawText);
    var legs = findLegs(text);

    var totals = legs.filter(function (l) { return l.isTotal; });
    var used = totals.length ? totals : legs;

    var minutes = null, miles = null, hadDecimal = false, correctedLeg = false;
    for (var i = 0; i < used.length; i++) {
      minutes = (minutes || 0) + used[i].minutes;
      if (used[i].miles !== null) {
        miles = (miles || 0) + used[i].miles;
        if (used[i].hadDecimal) hadDecimal = true;
        if (used[i].corrected) correctedLeg = true;
      }
    }

    // A card gives distances to one decimal place, so a sum of them has one
    // decimal place. Binary floating point disagrees: 3.5 + 6.1 is
    // 9.600000000000001, and that went into the journal, into the CSV export
    // and into anything reading either. Rounded here rather than at each
    // display, so the stored number and the shown number are the same number.
    if (miles !== null) miles = Math.round(miles * 100) / 100;
    var dist = checkDistance(minutes, miles, hadDecimal);
    miles = dist.miles;
    dist.corrected = dist.corrected || correctedLeg;

    var itemMatch = text.match(ITEMS);
    var items = itemMatch ? toNumber(itemMatch[1]) : null;
    if (items !== null && (items < 0 || items > 200)) items = null;

    var pay = findPay(text);

    return {
      pay: pay,
      minutes: minutes,
      miles: miles,
      // The legs behind the sum, so a caller holding readings from several
      // frames can merge the ones a single frame missed.
      legDetail: used.map(function (l) {
        return { minutes: l.minutes, miles: l.miles, isTotal: l.isTotal };
      }),
      items: items,
      legs: used.length,
      milesCorrected: dist.corrected,
      milesUncertain: dist.uncertain,
      // Enough to act on: without pay and time there is no rate to show.
      complete: pay !== null && pay > 0 && minutes !== null && minutes > 0,
      text: text
    };
  }

  /* ---------- rate ---------- */

  // Mirrors the manual app, plus a per-item allowance because shop-and-deliver
  // offers quote a time that assumes the shopping itself is instant.
  // The defaults, and the only values these ever take if what is in config.json
  // cannot be read as a number.
  var DEFAULT_SETTINGS = { target: 25, band: 15, costPerMile: 0, pad: 0,
                           secondsPerItem: 0 };

  // A number a person typed into config.json, or the default if it is not one.
  //
  // The driver is told to hand-edit this block, so `"target": "30"` with the
  // quotes left on, or a value deleted to `null`, is a keystroke away — and the
  // two languages got it wrong in opposite directions. Python multiplied a
  // string by a float and raised, inside the read guard, which reports a
  // permanent misconfiguration as one bad frame and suppresses the repeat: a
  // whole shift of no verdicts and no journal rows behind a green dot. This
  // side coerced silently, and `s.target || 25` turned a *deliberate* zero into
  // 25 while a deleted target put the accept floor at zero — which makes every
  // offer an ACCEPT.
  //
  // So a number is taken from anything that reads as one — "30" is what the
  // driver meant — and anything else falls back to the documented default.
  // Written the same way as offer_parser.setting so the two cannot answer
  // differently.
  function setting(value, fallback) {
    if (typeof value === 'boolean') return fallback;
    if (value === null || value === undefined || value === '') return fallback;
    if (typeof value !== 'number' && typeof value !== 'string') return fallback;
    var n = Number(value);
    return isFinite(n) ? n : fallback;
  }

  // What a real offer looks like from the outside, used to catch a reading that
  // cannot be true rather than a ride that is merely unusual.
  //
  // These come from 234 offers off a real rig. Three of them had lost a decimal
  // point — $11.84 read as $1184, $12.51 as $1251 — and two more had a misread
  // time that put the trip at 110 and 120 mph. All five were shown as ACCEPT,
  // in green, with a spoken "accept, three thousand five hundred an hour". The
  // journal flagged the first three afterwards and said nothing about the other
  // two, which is the wrong end of the problem: by then the driver has already
  // looked at the screen and decided.
  //
  // The bounds sit well clear of anything genuine in that data — the best real
  // offer was $45/hr, the fastest real trip averaged 56 mph over a 115-mile
  // highway run — so a card has to be misread, not just unusual, to trip them.
  var SANE_PAY = [1.0, 300.0];
  var SANE_MINUTES = [2.0, 240.0];
  var SANE_MPH = 75.0;

  // Why this reading cannot be true, or null if it might be. Written the same
  // way as offer_parser.doubt so the two cannot answer differently.
  //
  // Only the direction that produces a wrong ACCEPT is checked. A reading that
  // understates what an offer pays makes it look worse than it is, and the
  // driver declines something they might have taken — a real cost, but a
  // recoverable one, and the next offer is thirty seconds away. A reading that
  // overstates it puts them in a car for forty minutes for six dollars.
  function doubt(pay, minutes, miles) {
    if (typeof pay !== 'number' || !isFinite(pay)) return null;
    if (!(pay >= SANE_PAY[0] && pay <= SANE_PAY[1])) return 'pay';
    if (typeof minutes !== 'number' || !isFinite(minutes)) return null;
    if (!(minutes >= SANE_MINUTES[0] && minutes <= SANE_MINUTES[1])) return 'time';
    if (typeof miles === 'number' && isFinite(miles) && miles >= 1.0
        && minutes > 0 && miles / (minutes / 60) > SANE_MPH) return 'speed';
    return null;
  }

  function rate(parsed, settings) {
    var s = settings || {};
    var target = setting(s.target, DEFAULT_SETTINGS.target);
    var band = setting(s.band, DEFAULT_SETTINGS.band);
    var costPerMile = setting(s.costPerMile, DEFAULT_SETTINGS.costPerMile);
    var pad = setting(s.pad, DEFAULT_SETTINGS.pad);
    var secondsPerItem = setting(s.secondsPerItem, DEFAULT_SETTINGS.secondsPerItem);

    if (!parsed.complete) return { ready: false, state: 'empty' };

    var shopMinutes = (parsed.items || 0) * secondsPerItem / 60;
    var minutes = parsed.minutes + pad + shopMinutes;
    // A trip that takes no time pays infinitely well, which is the kind of
    // arithmetic that ends in an ACCEPT on nonsense. parse() will not produce
    // a zero-minute offer, but `pad` is a number a driver edits by hand and a
    // negative one can cancel the trip out. This returned Infinity and state
    // 'go'; the Python threw ZeroDivisionError and took the scan loop with it.
    if (!(minutes > 0)) return { ready: false, state: 'empty' };
    // A distance we do not trust must not be turned into a cost. Falling back
    // to gross pay overstates the rate slightly; using a bad distance can
    // understate it enormously, which is the error that loses you money.
    var cost = parsed.milesUncertain ? 0 : (parsed.miles || 0) * costPerMile;
    var net = parsed.pay - cost;

    var perHour = net / (minutes / 60);
    var floor = target * (1 - band / 100);
    // Judged on what the card said, not on what the arithmetic made of it:
    // `pad` and the shopping allowance are the driver's own additions and a
    // card is not misread for having them applied.
    var why = doubt(parsed.pay, parsed.minutes, parsed.miles);

    return {
      ready: true,
      minutes: minutes,
      shopMinutes: shopMinutes,
      net: net,
      cost: cost,
      // Echoed back so a display can say what it deducted and why, rather
      // than showing a number nobody can reconstruct. The target and band go
      // with it because a verdict outlives the settings that produced it: a
      // stored "PASS" means nothing a month later without the line it was
      // being held to at the time.
      costPerMile: costPerMile,
      target: target,
      band: band,
      perHour: perHour,
      // The same rate before running costs come off, over the same minutes.
      // A display that works this out for itself from the card's own time
      // divides by a different number as soon as `pad` or `secondsPerItem`
      // is set, and then the two rates it shows cannot be reconciled by
      // subtracting the cost it also shows.
      grossPerHour: parsed.pay / (minutes / 60),
      perMin: net / minutes,
      // Net, like perHour, so the two agree about what a dollar means. A
      // display showing one gross and the other net invites exactly the
      // arithmetic that does not add up.
      perMile: (parsed.miles && !parsed.milesUncertain) ? net / parsed.miles : null,
      milesUncertain: !!parsed.milesUncertain,
      milesCorrected: !!parsed.milesCorrected,
      // `ready` stays true and every number is still here, because the row has
      // to reach the journal: a reading this project got wrong is the most
      // useful row in the file, and one that is quietly dropped cannot be
      // studied or counted. What is withheld is only the verdict.
      doubt: why,
      state: why ? 'doubt'
           : perHour >= target ? 'go'
           : perHour >= floor ? 'warn' : 'no'
    };
  }

  return { parse: parse, rate: rate, normalize: normalize, toNumber: toNumber,
           doubt: doubt, SANE_PAY: SANE_PAY, SANE_MINUTES: SANE_MINUTES,
           SANE_MPH: SANE_MPH };
}));
