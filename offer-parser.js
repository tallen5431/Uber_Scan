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

  /* A component of the payout, printed beside it, and never the payout.
   *
   * Uber puts a chip under the headline — "+$0.50 included", "+$2.39 included
   * for priority" — saying what part of the total came from where. findPay
   * takes the LARGEST dollar figure, on the stated reasoning that the headline
   * is the biggest number on the card. That premise holds until the chip loses
   * its decimal point, which is the first thing a decimal does through a lens.
   *
   * On this driver's own shift "+$050 included" was read as FIFTY DOLLARS
   * twice, on cards whose real payouts were $13.08 and $21.06, and both were
   * rated ACCEPT at $71/hr and $68/hr. Nothing caught them: the sane-rate
   * ceiling only fires above $200/hr. Eight cards in 309 took a chip as pay.
   *
   * Decided by the card's own grammar, like LEG_TAIL: a PLUS, an amount, and
   * the word the card prints to say what the amount is, with nothing between
   * them. That last part keeps it off the headline, which reads "$11.42
   * Guaranteed (incl. tip)" — "incl" is there too, but "Guaranteed" is in the
   * way. DC is spliced as an alternation, not nested in brackets, because the
   * two languages disagree about what a nested class means.
   *
   * The amount may arrive in two pieces, for the same reason a headline can:
   * see PAY_SPLIT. A chip reading "+$5 0.00 included" over a real $13.08
   * headline is the same fifty-dollar lie as "+$050 included", so the chip has
   * to cover the split form too — otherwise the rule that puts split numbers
   * back together would hand it straight back as the payout.
   */
  var PAY_CHIP = new RegExp(
    '\\+\\s*[$S5§]?\\s*((?:' + DC + '|[.,])+(?:\\s(?:' + DC + '|[.,])+)?)'
    + '\\s*incl(?:uded)?\\b', 'gi');

  /* One payout, cut in half by the reader.
   *
   * The headline is the biggest type on the card and the crop's own edge runs
   * through it: the space between the dollars and the cents comes back wider
   * than it is, and "$18.75" arrives as "$1 8.75". findPay then reads the
   * largest dollar figure it can see, which is $1.
   *
   * Nine of this driver's 309 cards, four distinct offers, and the worst of
   * them is an offer worth $38.52/hr shown as a red DECLINE. It is worse than
   * a wrong number: some frames of the same card read the headline whole and
   * some split it, so the accumulator — which keys a card by its payout —
   * files one physical offer as two, and the panel alternates between two
   * verdicts while the driver is looking at it. One card in the export
   * flickers between $28.85/hr and $1.54/hr five times in seventeen seconds.
   *
   * Glued only where the card's own label follows, and that is the whole
   * safety of it. A payout says what it is — "Guaranteed", "Includes expected
   * tip" — and gluing on the digits alone would read "$8 5.00" on a ride card,
   * where the 5.00 is the driver's star rating, as an eighty-five dollar
   * offer. That is the one direction this project will not go: a fabricated
   * payout that is LARGER reads as a green light. With the label required it
   * fires on all nine real cards, changes no payout that was already right,
   * and matches none of the 140 texts in the shared corpus.
   *
   * Only a plain space may sit between the halves, because that space IS the
   * defect: one number printed with too wide a gap. Anything else between them
   * means they are two different things, and this driver's cards are full of
   * stray marks that would happily glue an $8 offer into an $85 one — 60 of
   * the 420 texts on file change what they match if the gap may hold junk.
   */
  var PAY_SPLIT = new RegExp(
    '\\$\\s*(' + DC + '{1,3})\\s+(' + DC + '{1,2}[.,]' + DC + '{2})'
    + '\\s*(?=guarant|includ)', 'gi');

  function findPay(text) {
    var chips = collect(text, PAY_CHIP);
    var all = collect(text, MONEY_STRICT);
    if (!all.length) all = collect(text, MONEY_LOOSE);

    // A headline the reader cut in half. See PAY_SPLIT: the halves are put
    // back together only where the card's own label follows them, and the
    // joined figure then competes as an ordinary candidate. It always beats
    // the "$1" fragment it was built from — joining digits can only make a
    // number larger — so the largest-figure rule picks it up with no special
    // standing of its own.
    var joined = collectPair(text, PAY_SPLIT);
    all = all.concat(joined);
    if (!all.length) return null;

    // Cards can show a promo or a struck-through figure alongside the real
    // payout; the offer headline is the largest dollar figure on the card.
    var best = null;
    for (var i = 0; i < all.length; i++) {
      // ...unless it is inside a chip, which is part of the payout rather than
      // a candidate to be it. See PAY_CHIP.
      var inChip = false;
      for (var c = 0; c < chips.length; c++) {
        if (chips[c].index <= all[i].index
            && all[i].index + all[i].match.length
               <= chips[c].index + chips[c].match.length) {
          inChip = true;
          break;
        }
      }
      if (inChip) continue;
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

  // Like collect, but for a pattern whose number arrives in two pieces: the
  // halves are joined as text, before any parsing, so "1" + "8.75" is read as
  // the one number 18.75 rather than arithmetic on two.
  function collectPair(text, re) {
    var out = [], m;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      out.push({ value: m[1].trim() + m[2].trim(), index: m.index, match: m[0] });
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

  /* What a card calls a leg of the journey. Uber labels every one — "away",
     "trip", "total" — and prints its distance beside its time.

     So a minutes-only token that also carries one of these words is a leg whose
     distance did not read, which is the damage legsShortADistance exists for.
     One WITHOUT a label is not a leg at all, and the card is full of them:
     "Avg. wait time at pickup 4 min" under the address, a promo chip's "15 min
     left", an ETA badge's "arrives in 9 min". Each became a third leg on a
     two-leg card and tripped the guard, which marked the whole distance
     untrusted and made rate() charge no mileage. On one real shift that was 67
     of the 70 three-leg cards and a third of every offer read.

     Deciding it on the card's own grammar rather than on a list of phrases that
     are not legs is what makes it hold for the next one. It also fails safe: a
     real leg that loses BOTH its label and its distance is read as not-a-leg,
     so the other legs' distance is charged instead of none at all — a cost too
     low rather than absent, the less optimistic of the two errors. */
  var LEG_TAIL = /\b(?:away|tr[il1|]p|tota?l|dropoff|drop\s*off)\b/i;

  /* --- the shape a delivery card uses instead of a duration ---
   *
   * Uber states a journey as legs: "19 min (8.5 mi)". DoorDash does not state a
   * duration at all. It gives a deadline — "Deliver by 7:15 PM" — a distance on
   * its own, and the merchant. Three real cards off a driver's phone parsed to
   * nothing: no minutes, so no legs; no legs, so no miles; and with no minutes
   * the offer is incomplete, gets no verdict, and never reaches the journal.
   * Every DoorDash offer that driver was shown was invisible to the rig.
   *
   * The deadline is the honest denominator for one of these. It is not the
   * drive time — it is how long the job occupies the driver, waiting at the
   * counter included, which is what an hourly rate is supposed to divide by. */
  var DELIVER_BY = /deliver(?:ed|y)?\s*by\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*([ap])\.?\s*m\.?/i;

  // A decimal point inside a distance token, either way OCR renders it. Kept
  // because the fact is lost the moment the string becomes a number: "10.0 mi"
  // and "10 mi" arrive at checkDistance identical, and only one of them may
  // have its decimal "recovered".
  var LONE_DECIMAL = /[.,]/;

  /* A distance with no leg around it. Only consulted when no leg was found, so
     it cannot double-count a ride card — and never the "4 mi from fast charger"
     badge, which is a fact about the map rather than about the job. */
  var LONE_MILES = new RegExp(
    '(?:^|[^\\d.])(' + DC + '{1,3}(?:[.,]' + DC + '{1,2})?)\\s*mi(?:les?)?\\b(?!\\s*from)', 'i');

  /* What kind of job the card is offering, from the words it prints rather
     than inferred from its numbers. The offers page split "Rides" from "Shop"
     on whether an item count had been read, which is a fact about the OCR and
     not about the job: 22 offers in one real recording ran at shopping speeds
     with no item count, and all 22 were filed as rides. */
  var SHOP_CARD = /\bshop\b[\s&+]*(?:and\s*)?\bdeliver/i;

  var PICKUP = /\bpick\s?up\b[\s:.-]*([\s\S]{2,60}?)(?=\s*\(\s*\d+\s*orders?\s*\)|\s+customer\b|\s+dropoff\b|\s+accept\b|\s+add\s+to\b|\s+decline\b|$)/i;

  /* ...except where the word is not a label at all. A ride card prints "Avg.
     wait time at pickup" under the pickup address, and that "pickup" was read
     as the delivery card's own anchor: what followed it — the rest of the card
     — went into the journal as where the job went. One real shift stored the
     phrase itself as a place twice, and stored `1 min 23 min (8.4 mi) trip
     Celebration Blvd, Acworth` as another.

     Checked against the text before the match rather than with a lookbehind,
     which Safari did not have until 16.4. */
  var PICKUP_ALL = new RegExp(PICKUP.source, 'gi');
  var PICKUP_NOT_A_LABEL = /\b(?:at|time)\s*$/i;

  /* An address as these cards write one: a junction, or a street with a town
     after it. Deliberately narrow — a line that is not clearly a place is not
     stored, because a journal full of half-read map furniture is worse than one
     that cannot be searched by where an offer went.

     "A comma with a letter after it" was too narrow a definition of narrow.
     Over a real shift of 121 offers it admitted `a we, a oo 1 we, a in i ie. a
     ; . a ae eS My on - J ee ae` — sludge off the map behind the card, stored
     and then shown on the offers page as where the job went. A comma is not
     evidence. A street word is, a junction between two named things is, and so
     is a town: a capitalised word of three letters or more after the comma.

     Three patterns rather than one alternation, because the town test is the
     only one that cares about case and a single regex would need the `i` flag
     for the street words — which is how the capital that makes ", Kennesaw"
     evidence and ", a oo" not would have been thrown away. */
  var STREET_WORD = 'st|street|rd|road|ave|avenue|blvd|bivd|pkwy|parkway|dr|drive|'
    + 'ln|lane|way|ct|court|hwy|highway|pl|place|ter|terrace|cir|circle|trce|'
    + 'trail|trl|spgs|springs|county';
  var PLACE_STREET = new RegExp('\\b(?:' + STREET_WORD + ')\\b', 'i');
  var PLACE_JUNCTION = /[A-Za-z]{3}.*\s&\s.*[A-Za-z]{3}/;
  var PLACE_TOWN = /,\s*[A-Z][A-Za-z]{2,}/;
  var PLACE_WORD = /[A-Za-z]{3}/;

  /* Words a card puts near a place that are not part of its name.

     `total` is among them because a shop card prints "34 min (3.6 mi) total"
     and the merchant's name straight after it, so the leg tail begins with the
     word: 5 of one shift's addresses were stored as "total Five Guys (3450 Cobb
     Pkwy. NW)". */
  var PLACE_JUNK = /^(?:pickup|dropoff|customer|accept|decline|add\s+to\s+route|deliver(?:ed|y)?\s*by.*|verified|exclusive|guaranteed|tota?l|away|trip)\b[\s:.-]*/i;

  /* ...and where a place *ends*. PLACE_JUNK only ever trimmed a prefix, so
     every word the card printed after an address rode along with it into the
     journal. The commonest by far is Uber's own "Avg. wait time at pickup",
     which sits directly under the pickup address: it was on 25 of one shift's
     60 stored places, and what the offers page showed was `Cobb Pkwy NW,
     Acworth Avg. wait time at pickup; Canton Rd, Marietta`.

     A pipe ends one too. It is never in a street name and it is what the card's
     own dividers and its bottom icon row come back as.

     The charger badge is spelled out separately because it is the one entry
     here that is a word STEM. Inside the \b(?:...)\b group, "fast\s*charg"
     can never match "fast charger": the closing boundary would have to fall
     between "charg" and "e", and there is no boundary there. So the one badge
     this stopper was written for walked straight past it, and the address kept
     a charger advert stapled to its end. Three of one shift's 210 cards. */
  var PLACE_TAIL = /(?:\||\bfast\s*charg|\b(?:avg|wait\s*time|add\s+to\s+route|accept|decline|verified|exclusive|guaranteed|included|customer|dropoff|orders?)\b)/i;

  /* The commonest delivery card puts BOTH ends of the job after one total leg:
   *
   *   27 min (7.3 mi) total  Rick's Hotwings (Kennesaw)  Hamby Place Dr NW &
   *   Travistock Pl NW, Acworth
   *
   * There is no "Pickup" label to anchor on and only one leg, so the leg-tail
   * rule picked the whole thing up as ONE place — 71 characters of merchant and
   * address together, which the 60-character cap then threw away entire. Both
   * ends of the job, lost to a length check, on 53 of one shift's 210 cards.
   *
   * The card's own grammar separates them: Uber prints the merchant with its
   * branch in brackets and where the job goes after that, so the closing
   * bracket is the seam. */
  var PLACE_MERCHANT = /^(.{2,44}?\([^)]{2,34}\))\s*(.{4,})$/;

  /* ...and an address ends at its town. Nothing on the card marks the end of
   * one, which is what left "Lakeview Ter & Windmill Dr, Dallas ill" in the
   * journal — the "ill" is the bottom icon row. A comma, a capitalised name or
   * two, and that is the whole address.
   *
   * The possessive is allowed because a card does not always end on a town:
   * "1min (0.2 mi) Roswell Road, Johnny's Hideaway" ends on the venue, and a
   * rule stopping at the first capitalised word cut it to "Roswell Road,
   * Johnny". Lower case still ends it, which keeps the icon row out. */
  var PLACE_ENDS_AT_TOWN = /^(.*?,\s*[A-Z][A-Za-z]+(?:'s)?(?:\s+[A-Z][A-Za-z]+(?:'s)?)?)\b/;

  function endsAtTown(value) {
    var m = String(value || '').match(PLACE_ENDS_AT_TOWN);
    return m ? m[1] : value;
  }

  /* The card's bottom bar — a row of icons — comes back as one and two
     character scraps: `Kennesaw 4`, `Marietta %`, `Acworth ¥`, `Kennesaw 2c 4`.
     Two lists, not one: `S Main St NW` starts with a real single letter and
     `Chick-fil-A (2555 Dallas Highway) s` ends with a false one. Length is the
     test rather than shape — "Papa John's Store 3317" ends in a number that
     belongs to it, and four characters is not a scrap. */
  var PLACE_TRAIL_KEEP = ['nw', 'ne', 'sw', 'se', 'st', 'rd', 'dr', 'ct', 'ln', 'pl', 'ga'];
  var PLACE_LEAD_KEEP = PLACE_TRAIL_KEEP.concat(['n', 's', 'e', 'w']);
  var PLACE_EDGE = /^[^0-9A-Za-z]+|[^0-9A-Za-z]+$/g;
  var PLACE_STOP = /\b(?:accept|decline|verified|exclusive|guaranteed|add\s+to\s+route|\d+\s*mi\b)/i;
  var AFTER_DEADLINE_STOP = /\d|\b(?:accept|decline|pickup|customer|dropoff)\b/i;

  /* "Deliver by 7:15 PM" as minutes since midnight, or null. */
  function findDeadline(text) {
    var m = text.match(DELIVER_BY);
    if (!m) return null;
    var hour = parseInt(m[1], 10);
    var minute = parseInt(m[2], 10);
    if (!(hour >= 1 && hour <= 12) || minute > 59) return null;
    hour = hour % 12;
    if (m[3].toLowerCase() === 'p') hour += 12;
    return hour * 60 + minute;
  }

  /* How long is left, wrapping across midnight. A deadline already past is not
     a short job, it is a stale card. */
  function minutesUntil(deadline, nowMinutes) {
    if (deadline === null || deadline === undefined) return null;
    if (typeof nowMinutes !== 'number' || !isFinite(nowMinutes)) return null;
    var left = deadline - nowMinutes;
    if (left < 0) left += 24 * 60;
    return left;
  }

  /* Where the job goes, as the card writes it. Never invented — three anchors,
     each something the card actually prints. */
  /* Is this an address, or is it the map it was printed on? */
  function looksLikeAPlace(value) {
    value = String(value || '');
    if (!PLACE_WORD.test(value)) return false;
    return PLACE_STREET.test(value) || PLACE_JUNCTION.test(value)
      || PLACE_TOWN.test(value);
  }

  /* One address, with the card's furniture taken off both ends.

     An anchor says where a place *starts*; nothing on the card says where it
     stops, so what got stored was the address plus whatever the layout printed
     next to it. See PLACE_TAIL.

     Parentheses survive on purpose, and the Pi's port never trimmed them
     either: a branch address is printed inside them — "Dollar General (925
     Shiloh Rd Nw)" — so taking the closing one off leaves a dangling open
     bracket and a name that reads as truncated, and the two ports would store
     the same merchant under two different strings. */
  function trimPlace(value) {
    function scrap(token, keep) {
      var core = String(token).replace(PLACE_EDGE, '');
      return !core || (core.length <= 2 && keep.indexOf(core.toLowerCase()) < 0);
    }
    // The front first, and the tail after. Order matters: a pipe ends a place,
    // but `oN | Cobb Pkwy NW, Kennesaw 'a` is a pipe with the sludge on the
    // *near* side of it, and cutting there first threw the address away and
    // kept the "oN".
    var parts = String(value || '').split(/\s+/).filter(Boolean);
    for (;;) {
      while (parts.length && scrap(parts[0], PLACE_LEAD_KEEP)) parts.shift();
      // Two prefixes happen — "total Pickup Papa John's" — and the second is
      // only at the front once the first has gone.
      var shorter = parts.join(' ').trim().replace(PLACE_JUNK, '')
        .replace(/^[\s.,\-;:|]+|[\s.,\-;:|]+$/g, '').split(/\s+/).filter(Boolean);
      if (shorter.join(' ') === parts.join(' ')) break;
      parts = shorter;
    }
    parts = parts.join(' ').split(PLACE_TAIL)[0].split(/\s+/).filter(Boolean);
    while (parts.length && scrap(parts[parts.length - 1], PLACE_TRAIL_KEEP)) parts.pop();
    return parts.join(' ').replace(/^[\s.,\-;:|]+|[\s.,\-;:|]+$/g, '');
  }

  function findPlaces(text, legs) {
    var out = [];
    function keep(value) {
      value = trimPlace(value);
      if (value.length < 3 || value.length > 60) return;
      if (!/[A-Za-z]{2}/.test(value)) return;
      for (var i = 0; i < out.length; i++) {
        if (out[i].toLowerCase() === value.toLowerCase()) return;
      }
      out.push(value);
    }

    PICKUP_ALL.lastIndex = 0;
    for (var m; (m = PICKUP_ALL.exec(text)) !== null;) {
      if (PICKUP_NOT_A_LABEL.test(text.slice(Math.max(0, m.index - 14), m.index))) continue;
      keep(m[1]);
      break;
    }

    /* A delivery card without a "Pickup" label puts the merchant straight after
       the deadline: "Deliver by 6:39 PM / Cherry Cricket / 4 items 0.6 mi". */
    var d = DELIVER_BY.exec(text);
    if (d) {
      var after = text.slice(d.index + d[0].length, d.index + d[0].length + 60);
      keep(after.split(AFTER_DEADLINE_STOP)[0]);
    }

    for (var j = 0; j < legs.length; j++) {
      if (typeof legs[j].end !== 'number') continue;
      var stop = (j + 1 < legs.length && typeof legs[j + 1].start === 'number')
        ? legs[j + 1].start : text.length;
      // 130 rather than 80. On the single-total delivery card the tail holds
      // the merchant AND the address, and 80 cut the town off the end of the
      // one that matters: "Double Branches Ln & Sagamore Ct. Dal".
      var tail = text.slice(legs[j].end, stop).slice(0, 130);
      tail = tail.split(PLACE_STOP)[0];
      // Trimmed before it is judged, not after. The test asks whether this is
      // an address, and the thing to ask it about is the string that would be
      // stored — `1 min ~ 4 . mins | . = | i oO < * ~~ agama ae ae; i Old
      // Mountain Rd NW, Kennesaw` passes on the address buried at the end of it
      // and then goes into the journal sludge and all.
      var pieces = [tail], bar = tail.indexOf('|');
      if (bar >= 0 && looksLikeAPlace(trimPlace(tail.slice(bar + 1)))) {
        pieces = [tail.slice(0, bar), tail.slice(bar + 1)];
      }
      for (var k = 0; k < pieces.length; k++) {
        var piece = trimPlace(pieces[k]);
        // Two places in one tail, when the card wrote them that way. See
        // PLACE_MERCHANT: the merchant is kept without asking looksLikeAPlace,
        // because "Rick's Hotwings (Kennesaw)" names no street and no town and
        // is still exactly where the driver goes first.
        var pair = piece.match(PLACE_MERCHANT);
        if (pair) {
          keep(pair[1]);
          var drop = endsAtTown(trimPlace(pair[2]));
          if (looksLikeAPlace(drop)) keep(drop);
          continue;
        }
        piece = endsAtTown(piece);
        if (looksLikeAPlace(piece)) keep(piece);
      }
    }
    return out.slice(0, 4);
  }

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
        isTotal: /\btota?l\b/.test(tail), corrected: fixed.corrected,
        // Whether the card labelled this as part of the journey. Only
        // consulted for a leg with no distance, where it is the difference
        // between a leg that lost its miles and a line that never had any.
        labelled: LEG_TAIL.test(tail),
        // Where this leg sat in the text, so the address printed after it can
        // be found without searching the whole card again.
        start: m.index, end: m.index + m[0].length
      });

      if (m.index === LEG.lastIndex) LEG.lastIndex++;
    }
    return legs;
  }

  /* ---------- plausibility ---------- */

  // No offer averages highway speed door to door once pickup, lights and
  // parking are in it. A reading above this means the distance was misread —
  // but see UNREADABLE_MPH: the line above which a reading is *treated* as
  // unusable is a good deal higher, because the two questions are not the same.
  var MAX_MPH = 55;

  // Above this a distance is not merely fast, it is not a distance.
  //
  // These were one constant, and conflating them cost real money. Losing a
  // decimal multiplies apparent speed by exactly ten, so a 6 mph shopping
  // errand comes back at 63 mph — which is why MAX_MPH sits at 55, well below
  // it, and why three cases in the shared corpus depend on recovery firing at
  // 63.5. But a reading that keeps its decimal cannot have lost one, and for
  // those the same 55 was being read as "this distance is unusable", which
  // makes rate() drop the mileage cost altogether and show gross as net.
  //
  // The owner's longest real offer is 115 miles in about two hours: 56 mph,
  // genuine, one mile per hour the wrong side of the line. It was shown at
  // $24.96/hr against a truth of $8.40 — a PASS dressed as a near-miss, on the
  // largest commitment on the board. Between 55 and here a distance is at most
  // a third out; ten times out is what zeroing the cost was written for.
  var UNREADABLE_MPH = 75;

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
  /* Whether a reading is enough to judge an offer on.
   *
   * A delivery card is complete without a duration, because its deadline is
   * one — but only once something has told it what time it is. rate() fills
   * that in; parse() must stay a pure function of its text.
   *
   * One function rather than the rule written out wherever it is needed. On the
   * Pi it had been written out twice, and the second copy — in the accumulator,
   * which recomputes it after merging frames — was missing the deadline clause,
   * so every card that gives a deadline instead of a duration parsed complete
   * and came back incomplete. Exported so the two ports cannot drift the same
   * way. */
  function isComplete(pay, minutes, deliverBy) {
    if (pay === null || pay === undefined || !(pay > 0)) return false;
    if (minutes !== null && minutes !== undefined && minutes > 0) return true;
    return deliverBy !== null && deliverBy !== undefined;
  }

  /* Whether a reading has nothing further to gain from another frame.
   *
   * Not the same question as isComplete, and the difference is what to do next:
   * complete means judgeable, whole means finished. A card missing a leg is the
   * same pay over less time, so it always reads *better* than the offer is.
   *
   * Written out by hand in two places before this, and both said `hasTotal or
   * legs >= 2`. A delivery card has neither — a deadline instead of a duration
   * and no legs at all — so every DoorDash offer was permanently a fragment:
   * never spoken, always question-marked, and left out of every figure on the
   * offers page.
   *
   * The deadline branch asks for the distance, which the legs branch gets for
   * free: rate() charges no mileage for a distance it does not have, so without
   * it such a card shows gross wearing net's clothes. There is no second leg to
   * wait for, so the distance is the one thing another frame can still add. */
  function isWhole(parsed) {
    if (!parsed || !parsed.complete) return false;
    // Two shapes reach this. A raw parse() carries the legs themselves and no
    // summary; a reading merged across frames carries `hasTotal` and has
    // already trimmed the legs. Both are asked, because this scanner judges the
    // first and the rig judges the second, and they must agree about one card.
    var detail = parsed.legDetail || [];
    // A journey whose legs disagree about having a distance is not finished,
    // however many legs were found. `legs >= 2` below counts legs; it does not
    // ask whether they read. Another frame is exactly what fixes it.
    if (legsShortADistance(detail)) return false;
    if (parsed.hasTotal) return true;
    for (var i = 0; i < detail.length; i++) {
      if (detail[i] && detail[i].isTotal) return true;
    }
    if ((parsed.legs || 0) >= 2) return true;
    // One token, and whether it is half a journey or a whole job is decided by
    // whether the card labelled it — the same question legsShortADistance
    // asks, for the same reason. Uber labels every leg of a ride (away, trip,
    // total), so a labelled single leg has a sibling that did not read and
    // another frame can still supply it. An unlabelled one is the "2.4 mi ·
    // 20 min" line of a delivery card: a summary of the whole job, not a leg,
    // and there is no second half coming.
    //
    // This was 37 of the driver's own 309 cards, all reading `complete` and
    // never `whole`: shown with a question mark for the life of the offer,
    // never spoken, set aside on the offers page, and resampled until the card
    // went away — for a reading that had the pay, the distance and the time and
    // nothing left to learn.
    if ((parsed.legs || 0) === 1 && detail.length && !detail[0].labelled) {
      return parsed.miles !== null && parsed.miles !== undefined
        && parsed.minutes !== null && parsed.minutes !== undefined;
    }
    return !(parsed.legs || 0)
      && parsed.deliverBy !== null && parsed.deliverBy !== undefined
      && parsed.miles !== null && parsed.miles !== undefined;
  }

  /* True when some leg of a journey has a distance and another has none.
   *
   * The sum is then a whole journey's *time* against part of its distance, and
   * nothing downstream can tell. Every existing guard looks for a distance that
   * is too big — checkDistance catches a lost decimal turning a 6mph errand
   * into a 63mph one — and this failure produces one that is too small, which
   * reads as an ordinary slow trip and passes every check there is.
   *
   * Measured on a rendered card at three times the brightness it was exposed
   * for: "20 min (7.3 mi) trip" came back as "20 min (7.3 m1) trip", so the
   * second leg contributed its twenty minutes and no distance at all. The
   * reading was 23 minutes over 1.1 miles instead of 8.4, complete, whole,
   * unflagged, and rated — $41.01/hr for an offer worth $35.30/hr, because the
   * missing miles are missing *cost*. It errs optimistic, which is the one
   * direction that turns a pass into an accept. */
  function legsShortADistance(legs) {
    var list = [], i;
    for (i = 0; i < (legs || []).length; i++) if (legs[i]) list.push(legs[i]);
    // Two or more, and it does not ask whether any other leg kept its distance.
    // Both legs losing theirs is the worse case, not the exempt one: it leaves
    // miles null, which reads as "this card states no distance" rather than as
    // damage, so nothing marks it and its gross rate joins net ones in every
    // median. A single leg is left alone because it can be a total, which
    // states no distance and is a whole journey by itself.
    if (list.length < 2) return false;
    // A leg is part of the journey if it states a distance, or if the card
    // labelled it one. A minutes-only token with no label is a wait line, a
    // promo chip or an ETA badge — not a leg the reader failed on. Their
    // minutes are still counted: the driver really does wait, and dropping the
    // time would raise the rate, the one direction that turns a pass into an
    // accept.
    var travel = [];
    for (i = 0; i < list.length; i++) {
      if (list[i].miles !== null && list[i].miles !== undefined) travel.push(list[i]);
      else if (list[i].labelled) travel.push(list[i]);
    }
    if (travel.length < 2) return false;
    for (i = 0; i < travel.length; i++) {
      if (travel[i].miles === null || travel[i].miles === undefined) return true;
    }
    return false;
  }

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
    // Nothing to recover, so the only question left is whether this is a fast
    // trip or a broken number — and those get different answers. See
    // UNREADABLE_MPH: calling a genuine 56 mph highway run unreadable makes
    // rate() charge no mileage at all, which is the one direction that turns a
    // PASS into an ACCEPT.
    if (mph <= UNREADABLE_MPH) {
      return { miles: miles, corrected: false, uncertain: false };
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
    dist.uncertain = dist.uncertain || legsShortADistance(used);

    var itemMatch = text.match(ITEMS);
    var items = itemMatch ? toNumber(itemMatch[1]) : null;
    if (items !== null && (items < 0 || items > 200)) items = null;

    var pay = findPay(text);

    // A delivery card states no duration and puts its distance on its own, so
    // neither reaches the sum above.
    //
    // "Consulted only when the legs found nothing" is what this used to say,
    // and `!used.length` is not that test. The commonest card this driver is
    // shown reads
    //
    //     $7.20 Guaranteed (incl. tips) 2.4 mi + 20 min @ Pickup McDonald's
    //
    // where the distance and the time are two halves of ONE line, not a
    // journey leg. The "20 min" half is picked up as a minutes-only leg, `used`
    // is therefore non-empty, and the "2.4 mi" sitting four characters away is
    // thrown out. On the driver's own 309-card export that happened 37 times —
    // 12% of every offer read — and all 37 for this one reason. No distance
    // means no mileage charged, which means the panel showed a ceiling as if it
    // were a rate: the exact failure the uncosted cap exists to contain,
    // arriving through the door the cap cannot see.
    //
    // The right test is the one legsShortADistance already uses. A leg is part
    // of the journey if it states a distance or the card labelled it one; an
    // unlabelled minutes-only token was never a leg. So a lone distance is
    // consulted when nothing that travels was found, which still leaves a real
    // ride card alone — its legs carry distances — and still refuses to hand a
    // stray number to a LABELLED leg that lost its own, because that is damage
    // and legsShortADistance is already saying so.
    var deadline = findDeadline(text);
    var travelled = [];
    for (var t = 0; t < used.length; t++) {
      if (used[t].miles !== null || used[t].labelled) travelled.push(used[t]);
    }
    if (miles === null && !travelled.length) {
      var lone = text.match(LONE_MILES);
      if (lone) {
        var v = toNumber(lone[1]);
        if (v !== null && v > 0 && v <= 500) {
          miles = Math.round(v * 100) / 100;
          hadDecimal = LONE_DECIMAL.test(lone[1]);
        }
      }
    }

    return {
      pay: pay,
      minutes: minutes,
      miles: miles,
      // Minutes since midnight, not a duration: converting one to the other
      // needs to know the time, and a parser that reads the clock cannot be
      // checked against a fixed corpus. rate() does the subtraction.
      deliverBy: deadline,
      // Where it goes, for finding this offer again months later. Empty unless
      // the card printed something anchored enough to trust.
      places: findPlaces(text, legs),
      // The legs behind the sum, so a caller holding readings from several
      // frames can merge the ones a single frame missed.
      legDetail: used.map(function (l) {
        // `labelled` travels with them: isWhole re-runs legsShortADistance
        // over this projection, and a field the rule needs that does not
        // survive the trip is a rule that quietly stops working.
        return { minutes: l.minutes, miles: l.miles, isTotal: l.isTotal,
                 labelled: l.labelled };
      }),
      items: items,
      legs: used.length,
      milesCorrected: dist.corrected,
      milesUncertain: dist.uncertain,
      // A distance is only as checkable as the time beside it. On a ride card
      // checkDistance has already run against the legs' own minutes; on a
      // delivery card there are none, so it returned the number untouched and
      // this says whether it may still be recovered later. See rate(), which
      // is where the clock is.
      milesChecked: minutes !== null,
      milesHadDecimal: hadDecimal,
      // Enough to act on: without pay and time there is no rate to show.
      complete: isComplete(pay, minutes, deadline),
      // Null when the card did not say — the top chip may simply not have been
      // inside the crop — which is different from "not a shop order".
      shop: SHOP_CARD.test(text) ? true : null,
      text: text,
      /* ...and the same reading before normalize() flattened it.
       *
       * `text` above is what this parser works on: whitespace collapsed to
       * single spaces, so every rule can be written without caring how the
       * engine broke the lines. That flattening throws away WHICH LINE each
       * figure was on, and the card's meaning is partly in its lines: "2.4 mi
       * + 20 min" is one line and therefore one journey, while a distance and
       * a duration on separate lines are two different facts.
       *
       * Kept beside rather than instead: normalize() is deterministic, so the
       * flattened form can always be made again from this one. */
      rawText: typeof rawText === 'string' ? rawText : String(rawText || '')
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
    if (value === null || value === undefined) return fallback;
    if (typeof value !== 'number' && typeof value !== 'string') return fallback;
    // `Number('')` and `Number('  ')` are both 0, and 0 is a finite number, so
    // a target left as whitespace in config.json became a target of zero — every
    // offer an ACCEPT — while the Python read the same file and fell back to 25.
    // One config, two rigs, opposite verdicts, and nothing on either screen
    // saying which line it was using. Python's float() strips whitespace and
    // raises on what is left, so this has to do the same.
    if (typeof value === 'string' && value.trim() === '') return fallback;
    // The same guard toNumber uses, for the same reason and now on the same
    // pattern. `Number()` and `float()` are each generous and generous in
    // *different* ways: this read "0x10" as sixteen and refused "1_0", while
    // Python refused "0x10" and read "1_0" as ten. One config file grading the
    // same card against two different targets, with nothing on either screen
    // saying which, is the failure this function already exists to prevent.
    if (typeof value === 'string' && !NUMERIC.test(value.trim())) return fallback;
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
  // A rate no offer on these apps pays. Not a judgement about a good job — that
  // is what `target` is for — but the line above which the arithmetic itself
  // cannot be true, so the reading behind it is a misread rather than a
  // windfall. Measured against the owner's own shift of 202 offers: the highest
  // rate among readings whose distance was trusted was $37.29/hr, and
  // everything above $100/hr that shift was a lost decimal point. Five times
  // the highest real one, because a ceiling that clips a genuine surge hides an
  // offer the driver should have seen.
  var SANE_RATE = 200.0;
  // ...and only once the trip is long enough for a rate to describe it. A rate
  // ceiling on its own is wrong, because $/hr is unbounded as the duration
  // shrinks: $10 for a two-minute half-mile hop is $300/hr and is an ordinary
  // offer, which the corpus has held since before this check existed and which
  // the first version of it broke. Below ten minutes a few dollars of tip
  // dominates the rate; above it, the rate is a rate.
  var SANE_RATE_OVER_MINUTES = 10.0;

  // Why this reading cannot be true, or null if it might be. Written the same
  // way as offer_parser.doubt so the two cannot answer differently.
  //
  // Only the direction that produces a wrong ACCEPT is checked. A reading that
  // understates what an offer pays makes it look worse than it is, and the
  // driver declines something they might have taken — a real cost, but a
  // recoverable one, and the next offer is thirty seconds away. A reading that
  // overstates it puts them in a car for forty minutes for six dollars.
  function doubt(pay, minutes, miles) {
    // Not `isFinite`: Infinity and NaN are numbers, they are the two most
    // impossible values a pay can take, and guarding them out here returned
    // "nothing wrong with this reading" for both. The Python compared them
    // against the bounds and correctly called them doubtful, so the same card
    // was a query on the rig and a verdict on the phone. The bound checks below
    // reject them on their own — every comparison against NaN is false — which
    // is exactly how the Python does it.
    if (typeof pay !== 'number') return null;
    if (!(pay >= SANE_PAY[0] && pay <= SANE_PAY[1])) return 'pay';
    if (typeof minutes !== 'number') return null;
    if (!(minutes >= SANE_MINUTES[0] && minutes <= SANE_MINUTES[1])) return 'time';
    // Each of the two can be sane on its own and impossible together. $136 is
    // inside SANE_PAY and ten minutes is inside SANE_MINUTES, and $816/hr is
    // neither — it is a decimal point that did not survive the read.
    // Math.max, so the ceiling never loosens as the trip gets shorter. Written
    // as two branches first, and that made a STEP: below ten minutes nothing
    // but SANE_PAY's own $300 applied, so $136 over ten minutes was doubted at
    // $810/hr while the same $136 over NINE minutes was a green ACCEPT at
    // $899/hr. A guard a shorter trip walks under is not a guard. Below the
    // boundary this is a flat cap on the PAY — $33.33, the payout that reaches
    // SANE_RATE at ten minutes.
    if (pay / (Math.max(minutes, SANE_RATE_OVER_MINUTES) / 60) > SANE_RATE) {
      return 'rate';
    }
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

    // A delivery card gives a deadline where a ride card gives a duration. The
    // subtraction happens here rather than in parse(), because it needs to know
    // the time and a parser that reads the clock cannot be held to a fixed
    // corpus. `nowMinutes` is minutes since midnight; without it a card that
    // only has a deadline stays unjudged rather than being guessed at.
    var cardMinutes = parsed.minutes;
    var fromDeadline = false;
    if ((cardMinutes === null || cardMinutes === undefined)
        && parsed.deliverBy !== null && parsed.deliverBy !== undefined) {
      cardMinutes = minutesUntil(parsed.deliverBy, setting(s.nowMinutes, null));
      fromDeadline = cardMinutes !== null;
    }
    if (cardMinutes === null || cardMinutes === undefined || !(cardMinutes > 0)) {
      return { ready: false, state: 'empty' };
    }

    var shopMinutes = (parsed.items || 0) * secondsPerItem / 60;
    var minutes = cardMinutes + pad + shopMinutes;
    // A trip that takes no time pays infinitely well, which is the kind of
    // arithmetic that ends in an ACCEPT on nonsense. parse() will not produce
    // a zero-minute offer, but `pad` is a number a driver edits by hand and a
    // negative one can cancel the trip out. This returned Infinity and state
    // 'go'; the Python threw ZeroDivisionError and took the scan loop with it.
    if (!(minutes > 0)) return { ready: false, state: 'empty' };
    // A distance we do not trust must not be turned into a cost. Falling back
    // to gross pay overstates the rate slightly; using a bad distance can
    // understate it enormously, which is the error that loses you money.
    // A distance is only as checkable as the time beside it, and a delivery
    // card states none — so checkDistance returned the number untouched and a
    // lost decimal went straight into the cost. "2.4 mi" read as "24 mi" is
    // charged $7.20 of mileage instead of $0.72: $18.1/hr becomes $2.5/hr,
    // unflagged. A ride card never had this hole; its legs carry their minutes.
    //
    // The machinery was always there and unreachable — it just needs a
    // denominator, and for a delivery card that is the time left until its
    // deadline, worked out here because it needs the clock. milesHadDecimal is
    // what stops the cure being worse: a card that really says "10.0 mi" must
    // not have its decimal recovered down to 1.0.
    var miles = parsed.miles;
    var milesUncertain = !!parsed.milesUncertain;
    var milesCorrected = !!parsed.milesCorrected;
    // `=== false` and not a falsiness test. A caller that builds this object by
    // hand — the keypad, a test, an older row being re-rated — has no such key,
    // and treating its absence as "not checked" let rate() recover a decimal
    // from a distance that had already been checked, or typed.
    if (parsed.milesChecked === false && miles !== null && miles !== undefined) {
      var rechecked = checkDistance(cardMinutes, miles, !!parsed.milesHadDecimal);
      miles = rechecked.miles;
      milesCorrected = milesCorrected || rechecked.corrected;
      milesUncertain = milesUncertain || rechecked.uncertain;
    }

    var cost = milesUncertain ? 0 : (miles || 0) * costPerMile;
    // ...and whether that leaves a rate the target can be compared against.
    //
    // `target` is a NET line — the driver set it against rates with their
    // running costs already taken off. When no cost could be taken off and a
    // cost per mile is configured, `perHour` is a gross figure and therefore an
    // UPPER BOUND on the offer rather than the offer itself.
    //
    // Measured on the owner's own shift of 202 offers: 108 of them, 53%, were
    // rated with no running cost at all, and the overstatement on the ones that
    // did state a distance ran to a median of 30% and a maximum of 334%. 33 of
    // the 35 ACCEPTs that shift came out of that pool, and 20 fall below the
    // target once the distance printed on the card is charged.
    //
    // The verdict is capped rather than the number withheld: CLOSE CALL is the
    // honest answer to "this might clear your line and I cannot tell".
    var uncosted = costPerMile > 0 && cost === 0;
    var net = parsed.pay - cost;

    var perHour = net / (minutes / 60);
    var floor = target * (1 - band / 100);
    // Judged on what the card said, not on what the arithmetic made of it:
    // `pad` and the shopping allowance are the driver's own additions and a
    // card is not misread for having them applied.
    var why = doubt(parsed.pay, cardMinutes, parsed.miles);

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
      perMile: (miles && !milesUncertain) ? net / miles : null,
      // The distance this verdict was actually reached with, which is not
      // always the one the card appeared to state. Returned so the row that
      // gets written and the rate that gets shown cannot disagree about it.
      miles: miles === undefined ? null : miles,
      milesUncertain: milesUncertain,
      milesCorrected: milesCorrected,
      // The minutes the arithmetic used from the card, and whether they were a
      // stated duration or the time left until a delivery deadline. Those are
      // different claims and a record that cannot tell them apart cannot be
      // argued with later.
      cardMinutes: cardMinutes,
      fromDeadline: fromDeadline,
      // `ready` stays true and every number is still here, because the row has
      // to reach the journal: a reading this project got wrong is the most
      // useful row in the file, and one that is quietly dropped cannot be
      // studied or counted. What is withheld is only the verdict.
      doubt: why,
      // Whether the rate above is the offer or only a ceiling on it, so a
      // display can say which it is showing rather than leaving two different
      // kinds of number looking identical.
      uncosted: uncosted,
      state: why ? 'doubt'
           // An upper bound may not clear a net target. Capped, not demoted
           // further: below the floor it is still 'no'.
           : (uncosted && perHour >= target) ? 'warn'
           : perHour >= target ? 'go'
           : perHour >= floor ? 'warn' : 'no'
    };
  }

  // `setting` is exported so the cross-language corpus can check it. It is the
  // function that decides what target an offer is judged against, it had
  // drifted, and nothing could see that because it was not reachable from a
  // test.
  return { parse: parse, rate: rate, normalize: normalize, toNumber: toNumber,
           setting: setting, doubt: doubt, DEFAULT_SETTINGS: DEFAULT_SETTINGS,
           findDeadline: findDeadline, minutesUntil: minutesUntil,
           findPlaces: findPlaces, trimPlace: trimPlace,
           looksLikeAPlace: looksLikeAPlace,
           isComplete: isComplete, isWhole: isWhole,
           SANE_PAY: SANE_PAY, SANE_MINUTES: SANE_MINUTES, SANE_MPH: SANE_MPH,
           SANE_RATE: SANE_RATE, SANE_RATE_OVER_MINUTES: SANE_RATE_OVER_MINUTES,
           MAX_MPH: MAX_MPH, UNREADABLE_MPH: UNREADABLE_MPH };
}));
