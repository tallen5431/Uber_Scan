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

  function toNumber(token) {
    if (token === undefined || token === null) return null;
    // OCR often reads a decimal point as a comma, and thousands separators
    // never appear on these cards, so a comma is always a decimal point.
    var n = parseFloat(fixDigits(String(token)).replace(',', '.'));
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
  var MONEY_LOOSE = new RegExp('(?:^|[\\s(])[$S5§]\\s?(' + DC + '{1,4}(?:[.,]' + DC + '{1,2})?)', 'g');

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
  var LEG = new RegExp(
    '(?:(\\d{1,2})\\s*h(?:r|rs|our|ours)?\\s*)?' +   // optional hours
    '(' + DC + '{1,3})\\s*m(?:in|ins|inute|inutes)?\\b' +
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
      if (mins === null) continue;
      var minutes = hours * 60 + mins;
      if (minutes <= 0 || minutes > 600) continue;

      var miles = toNumber(m[3]);
      if (miles !== null && (miles < 0 || miles > 500)) miles = null;
      // A decimal point is one or two pixels through a camera and is the first
      // thing to be lost, so remember whether this reading actually had one.
      var hadDecimal = m[3] !== undefined && /[.,]/.test(String(m[3]));

      // Uber labels a combined figure "total"; a card that has one is not also
      // listing its legs, so mixing the two would double count the trip.
      var tail = text.slice(m.index + m[0].length, m.index + m[0].length + 14).toLowerCase();
      legs.push({
        minutes: minutes, miles: miles, hadDecimal: hadDecimal,
        isTotal: /\btota?l\b/.test(tail)
      });

      if (m.index === LEG.lastIndex) LEG.lastIndex++;
    }
    return legs;
  }

  /* ---------- plausibility ---------- */

  // No offer averages highway speed door to door once pickup, lights and
  // parking are in it. A reading above this means the distance was misread.
  var MAX_MPH = 55;

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

    var minutes = null, miles = null, hadDecimal = false;
    for (var i = 0; i < used.length; i++) {
      minutes = (minutes || 0) + used[i].minutes;
      if (used[i].miles !== null) {
        miles = (miles || 0) + used[i].miles;
        if (used[i].hadDecimal) hadDecimal = true;
      }
    }

    var dist = checkDistance(minutes, miles, hadDecimal);
    miles = dist.miles;

    var itemMatch = text.match(ITEMS);
    var items = itemMatch ? toNumber(itemMatch[1]) : null;
    if (items !== null && (items < 0 || items > 200)) items = null;

    var pay = findPay(text);

    return {
      pay: pay,
      minutes: minutes,
      miles: miles,
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
  function rate(parsed, settings) {
    var s = settings || {};
    var target = s.target || 25;
    var band = s.band === undefined ? 15 : s.band;
    var costPerMile = s.costPerMile || 0;
    var pad = s.pad || 0;
    var secondsPerItem = s.secondsPerItem || 0;

    if (!parsed.complete) return { ready: false, state: 'empty' };

    var shopMinutes = (parsed.items || 0) * secondsPerItem / 60;
    var minutes = parsed.minutes + pad + shopMinutes;
    // A distance we do not trust must not be turned into a cost. Falling back
    // to gross pay overstates the rate slightly; using a bad distance can
    // understate it enormously, which is the error that loses you money.
    var cost = parsed.milesUncertain ? 0 : (parsed.miles || 0) * costPerMile;
    var net = parsed.pay - cost;

    var perHour = net / (minutes / 60);
    var floor = target * (1 - band / 100);

    return {
      ready: true,
      minutes: minutes,
      shopMinutes: shopMinutes,
      net: net,
      cost: cost,
      perHour: perHour,
      perMin: net / minutes,
      perMile: (parsed.miles && !parsed.milesUncertain) ? parsed.pay / parsed.miles : null,
      milesUncertain: !!parsed.milesUncertain,
      milesCorrected: !!parsed.milesCorrected,
      state: perHour >= target ? 'go' : (perHour >= floor ? 'warn' : 'no')
    };
  }

  return { parse: parse, rate: rate, normalize: normalize, toNumber: toNumber };
}));
