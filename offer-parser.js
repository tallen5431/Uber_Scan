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
      // The UNION of what the two languages call whitespace. Python's \s is
      // Unicode and JavaScript's is not; they disagree about U+001C-U+001F and
      // U+0085 (Python only) and U+FEFF (JavaScript only). Six invisible
      // characters that decide whether a map screen is rated as an offer - see
      // WHITESPACE in offer_parser.py, which adds U+FEFF at the other end.
      .replace(/[\s\u001c-\u001f\u0085]+/g, ' ')
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

  /* A number that is a duration or a distance, wearing a dollar sign.
   *
   * The rig photographs whatever is on the phone, and between jobs that is the
   * map. One screen off this driver's own shift:
   *
   *   The Townes at Chastain ... Windsor Drive ... 3min  11 min  $ 22min
   *   3 min (1.0 mi)  Fastest route now due to traffic conditions
   *
   * Route alternatives, with a map glyph in front of one that read as a dollar
   * sign. findPay took $22, the four times added to 39 minutes, and the panel
   * showed a green ACCEPT at $33.38/hr for a road - journalled as an offer and
   * counted in the medians as a rate.
   *
   * The grammar is the card's own and needs no list of screens: a payout says
   * what it is, or says nothing, but it is never glued to a unit. "$13.05 ...
   * $ 12 min (6.3 mi)" is a real card off the same shift, where a stray glyph
   * sits in front of the leg - the $12 is refused and the $13.05 headline is
   * untouched, which is the whole test of whether this rule is narrow enough. */
  // Only the abbreviations these screens actually print - "min", "mins", "mi" -
  // and not the spelled-out forms LEG tolerates. A merchant is what sits next to
  // a payout when the label between them does not read, and "$12 Minute Maid
  // Park" would lose its payout to a rule that accepts "minute". "Mi Casa" is
  // the collision that remains, and it is the safe direction: no payout, so no
  // verdict, rather than the wrong one.
  var PAY_IS_A_DURATION = new RegExp(
    '\\$\\s*(?:' + DC + '{1,4}(?:[.,]' + DC + '{1,2})?)\\s*'
    + '(?:m[il1|]ns?|mi)\\b', 'gi');

  /* The offer's headline payout, and — if asked — where every candidate was.
   *
   * `where` is filled with {value, at} for each figure that passed this
   * filter. parse() needs it to know where one card stops: Uber's Trip Radar
   * screen lists offers, so the top of the NEXT card shows below the first,
   * and the only thing marking the boundary is where the next headline starts.
   * Gathered here rather than re-derived by the caller so there is one rule
   * for what counts as a headline rather than two that can drift. */
  function findPay(text, where) {
    var chips = collect(text, PAY_CHIP);
    var units = collectSpans(text, PAY_IS_A_DURATION);
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
      // ...and a figure that is really a duration or a distance is not a
      // candidate either. See PAY_IS_A_DURATION.
      var inUnit = false;
      for (var u = 0; u < units.length; u++) {
        if (units[u].index <= all[i].index
            && all[i].index + all[i].match.length
               <= units[u].index + units[u].match.length) {
          inUnit = true;
          break;
        }
      }
      if (inUnit) continue;
      // An amount has to contain a real digit. DC lets a letter stand in for a
      // digit inside a number that is otherwise confirmed, which is right — but
      // a token made ENTIRELY of those stand-ins is not a number that lost a
      // character, it is a word.
      //
      // "$ Bound Ct & Shoals" came off a real card. B reads as 8, o reads as 0,
      // and a street name two lines under the headline became an EIGHTY DOLLAR
      // payout on a $9.03 delivery, published at $153.52/hr — the highest
      // ACCEPT of that shift. The dollar sign was real; every digit after it
      // was a guess. This is the rule findLegs already applies to a duration,
      // in the same words, and the split-headline join needs both halves to
      // pass it because joining two guesses is the same two guesses stacked.
      var parts = all[i].halves || [all[i].value], allDigits = true;
      for (var h = 0; h < parts.length; h++) {
        if (!/\d/.test(parts[h])) { allDigits = false; break; }
      }
      if (!allDigits) continue;
      var v = toNumber(all[i].value);
      if (v !== null && v > 0 && v < 2000) {
        if (where) where.push({ value: v, at: all[i].index });
        if (best === null || v > best) best = v;
      }
    }
    if (where) where.sort(function (a, b) { return a.at - b.at; });
    return best;
  }

  /* The legs belonging to the headline payout, and nothing below it.
   *
   * Trip Radar is a LIST of offers: the top of the next card shows under the
   * first, and its legs read exactly like more legs of this one. Nothing in
   * the grammar of a leg says which card it came off, so they were summed.
   *
   * Measured on row 227 of this driver's own export, real frames, no damage:
   * a $22.03 card stating 35 min / 19.7 mi was read as 54 min / 32.5 mi by
   * taking a leg off the $16.08 card below it — published as PASS $13.64/hr
   * and spoken aloud, on a job worth about $27.63/hr net. They declined a job
   * that cleared their target, and nothing said why.
   *
   * A card's own legs sit after its payout and before the next card's. A BATCH
   * — one payout over two pickups — has a single headline and is untouched,
   * which is the case this must not break. */
  function oneCard(legs, where) {
    if (!where || where.length < 2) return legs;
    var top = where[0], i;
    for (i = 1; i < where.length; i++) {
      if (where[i].value > top.value) top = where[i];
    }
    var edge = null;
    for (i = 0; i < where.length; i++) {
      if (where[i].at > top.at && (edge === null || where[i].at < edge)) {
        edge = where[i].at;
      }
    }
    return legs.filter(function (l) {
      return l.start > top.at && (edge === null || l.start < edge);
    });
  }

  /* Where the chosen card's own words are, or null if there is only one card.
   *
   * THE LEGS WERE BOUNDED AND NOTHING ELSE WAS. oneCard above trims the legs to
   * the chosen headline's card, and every other field went on reading the whole
   * frame: the deadline, the lone distance, the item count, and the Pickup
   * anchor that names the merchant. Measured on two real card shapes printed on
   * one frame — identical in both ports:
   *
   *     top card alone      $8.00   0.6 mi   4 items   ->  $50.85/hr  go
   *     bottom card alone   $14.00  9.4 mi   12 items  ->   $9.81/hr  no
   *     both on one frame   $14.00  0.6 mi   4 items   ->  $90.85/hr  go
   *
   * The pay came off the card that was chosen and the distance off the card
   * that was not. A $9.81/hr pass published as a green $90.85/hr accept.
   *
   * BETWEEN THE PAYOUTS EITHER SIDE. The corpus holds both layouts and they
   * print their figures on opposite sides of the money — "…4 items 0.6 mi
   * $8.00" against "$41.11 Guaranteed (incl. tips) 9.8 mi Deliver by…" — so a
   * span anchored on the chosen payout is right for one and points at the
   * neighbour for the other. The gap between the two NEIGHBOURING payouts holds
   * exactly one payout and whichever side its own fields sit on.
   *
   * The legs keep oneCard's narrower rule: they exist only on the Uber layout,
   * which prints them after the money, and two corpus cases pin it. */
  function cardSpan(where) {
    if (!where || where.length < 2) return null;
    var top = where[0], i;
    for (i = 1; i < where.length; i++) {
      if (where[i].value > top.value) top = where[i];
    }
    var lo = 0, hi = null;
    for (i = 0; i < where.length; i++) {
      if (where[i].at < top.at && where[i].at > lo) lo = where[i].at;
      if (where[i].at > top.at && (hi === null || where[i].at < hi)) hi = where[i].at;
    }
    return { lo: lo, hi: hi };
  }

  /* `text` with everything outside the chosen card blanked out.
   *
   * Blanked rather than sliced, so every index into this string is still an
   * index into the original — several rules downstream compare positions, and a
   * slice would silently move all of them. Newlines survive, because line shape
   * is structure: the item count and the Pickup anchor are read off line
   * starts, and flattening the blanked half would let a pattern match across
   * what used to be a break. */
  function onlyCard(text, span) {
    if (!span) return text;
    var hi = span.hi === null ? text.length : span.hi;
    var blank = function (part) {
      return part.replace(/[^\n]/g, ' ');
    };
    // The blanks BEFORE the card stay — they hold every index in place. The
    // ones after are dropped: several anchors need a real end to match
    // against, and a tail of spaces is not one, so a card whose merchant was
    // the last thing on it lost the merchant.
    return blank(text.slice(0, span.lo)) + text.slice(span.lo, hi).replace(/\s+$/, '');
  }

  // Spans of a pattern that captures nothing of its own.
  function collectSpans(text, re) {
    var out = [], m;
    re.lastIndex = 0;
    while ((m = re.exec(text)) !== null) {
      out.push({ index: m.index, match: m[0] });
      if (m.index === re.lastIndex) re.lastIndex++;
    }
    return out;
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
      // Both halves kept beside the joined value: the real-digit rule has to
      // see them separately, or "$1 O.SO" passes on the strength of the 1 and
      // joins a confirmed digit to a guessed one.
      out.push({ value: m[1].trim() + m[2].trim(), index: m.index, match: m[0],
                 halves: [m[1].trim(), m[2].trim()] });
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
  /* A leg's two numbers sit side by side, and the card decides which comes
   * first. This used to read time-then-distance only, because that is what the
   * older card printed. The card this driver is mostly shown now prints the
   * other way round - "8.0 mi + 25 min" - and against that LEG matched the
   * minutes alone: 142 of 604 cards on file came out with a time and no
   * distance, and the whole per-leg machinery went past them.
   *
   * It is not only the parse that suffers. accumulate.py matches a leg to a
   * slot on EITHER its time or its distance agreeing, and a leg with no
   * distance has only the one signal. One frame misreading the minutes lines up
   * with nothing, the window resets, and the same card is filed again.
   *
   * So the rule is adjacency in EITHER order, and the glue is the card's own
   * bullet: at least one non-space non-word glyph, at most three. Measured over
   * the 604, every distance-then-time pair on file is joined by punctuation,
   * never by a bare space - a bare space is two things next to each other
   * rather than one printed line. Brackets are excluded because a distance the
   * card closed a bracket on belonged to what came before it. */
  var LEG = new RegExp(
    '(?:(' + DC + '{1,3}(?:[.,]' + DC + '{1,2})?)\\s*m(?:i|ile|iles)\\b' +
    '\\s*[^\\s\\w()]{1,3}\\s*)?' +                 // distance, then the card's bullet
    '(?:(' + DC + '{1,2})\\s*h(?:r|rs|our|ours)?\\s*)?' +   // optional hours, lookalikes too
    '(' + DC + '{1,3})\\s*m[il1|]n(?:s|ute|utes)?\\b' +
    // ...and the trailing distance is not a badge's. "20 min trip 4 mi from
    // fast charger": with the trip's own bracket lost to glare, the charger
    // badge's 4 miles sat six characters past "min" and was charged as the
    // trip. LONE_MILES has refused "from" since it was written; this
    // window did not.
    '(?:[^(\\d]{0,6}\\(?\\s*(' + DC + '{1,3}(?:[.,]' + DC + '{1,2})?)\\s*m(?:i|ile|iles)\\b(?!\\s*from)\\s*\\)?)?',
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

  /* The leg that is the drive to the pickup, which an Uber card labels "away".

     It is inside the total the rate is computed over and it should be: the
     driver spends those minutes and those miles whether or not the job is
     worth taking. It is kept apart because it is the only part of the journey
     that is not the JOB - the gap between where the car happens to be and
     where the work starts - and nothing downstream can separate it again once
     the legs have been summed.

     Deliberately exact, with none of the damage tolerance LEG_TAIL carries for
     "trip". A missed label records no split at all, which is a silence; a
     loose one would label the wrong leg and hand out a confident wrong
     distance between two jobs. See toPickup(), which is the rule this feeds. */
  var APPROACH_TAIL = /\baway\b/;

  /* The other way a leg says it is part of the journey: it printed a distance
     and the reader did not get it. Matched against the same tail LEG_TAIL sees,
     on a leg that came out with no distance.

     LEG_TAIL is a word list, and this driver's ride cards do not use those
     words. They label a leg with an ADDRESS — "12 min (8.1 mi) Oak Ln,
     Marietta" — so both legs of a two-leg card count as travel only because
     they carry distances. The moment one loses its distance it drops out of the
     set legsShortADistance counts, the count falls to one, and the rule that
     exists for exactly this damage returns false. Measured: it fires on ONE of
     the driver's 604 cards, and on none of 1080 readings with a leg's distance
     broken.

     A bracket holding a digit is the distance still sitting on the card. It has
     to be the FIRST thing after the minutes, which is the whole difference
     between

         20 min (7.3 m1) trip                    <- the bracket is this leg's
         Avg. wait time at pickup: 1 min 9 mins (2.6 mi) Sedgefield Rd

     where a bracket appears in the wait line's tail too, but another leg's
     minutes come first. Searching the tail loosely instead fires on 43% of
     clean cards; anchored it fires on 3%, and every one of those is an "Add a
     delivery" card whose distance really is printed and really did not read.

     This is what a wait line, a promo chip and an ETA badge do not have, which
     is the objection the `travel` set was built to answer: they are followed by
     the next leg, and a leg begins with a word.

     Nothing is asked about what is INSIDE the bracket. Requiring a digit there
     sounds like a second belt and is a hole: the number is exactly what the
     damage removes, so "9 min (~ mi)" — the distance gone altogether — carries
     no digit to find. Measured over 3466 readings damaged four different ways,
     the digit clause halved what the rule caught, 2096 down to 1052, and bought
     nothing: both versions fire on zero of the 604 clean cards. */
  var LEG_LOST_MILES = /^[^\w(]{0,3}\(/;

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
   * bracket is the seam.
   *
   * 40 inside the brackets rather than 34, measured. `Wendy's (3442 Ernest W.
   * Barrett Parkway N.W.)` is 35 and `Olive Garden (Ernest W Barrett Pkwy NW &
   * Roberts Ct)` is 37, and on the driver's own 272-card export those two were
   * the only cards the limit touched: both stored NOTHING, because the seam was
   * one character out of reach and the whole piece then failed the length check
   * below. */
  var PLACE_MERCHANT = /^(.{2,44}?\([^)]{2,40}\))\s*(.{4,})$/;

  /* The other seam, for the cards that write no brackets.
   *
   * Uber's second layout puts the merchant and the destination on one line with
   * nothing but a map-pin icon between them, and the camera turns that icon into
   * whatever it likes — `7`, `9`, `©`, or nothing at all. There is no character
   * to split on. What there IS, on 13 of the 15 cards this went wrong on, is a
   * JUNCTION: the destination is `<street> & <street>` and the merchant is not.
   *
   * Exactly one junction, or nothing: see where this is used. A piece with two
   * of them is one the parser cannot read, not one to guess at.
   *
   * Capitalised words only, and at most four each side, so this anchors on a
   * street name rather than on the first ampersand in a line of icon sludge. */
  var PLACE_JUNCTION_AT = /(?:[A-Z][A-Za-z'.]*\s+){0,3}[A-Z][A-Za-z'.]*\s*&\s*(?:[A-Z][A-Za-z'.]*\s+){0,3}[A-Z][A-Za-z'.]*/g;

  /* The longest thing that may be stored as one place. Named because two rules
   * consult it: `keep` refuses anything over it, and the junction seam only
   * looks for a seam in a piece that is over it. */
  var MAX_PLACE = 60;

  /* ...and how many of them one card may hold.
   *
   * Named here because it is named in the Python port, where its own comment
   * says why: "the accumulator and the journal both cap their own collections
   * at the same number and three copies of it is three chances to disagree
   * about what a card can hold". This side had the fourth copy, as a bare `4`
   * at the end of findPlaces, where nothing could see it disagree.
   *
   * It is not only a display cap. `journal.py:content_of` folds the places
   * tuple into the fingerprint that decides whether a new reading SUPERSEDES
   * an older one, so a rig keeping five places and a phone keeping four make
   * two different fingerprints for the same physical card — and the card stops
   * being recognised as the same card. */
  var MAX_PLACES = 4;

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
  /* Is `at` inside a bracket the card opened and closes again?
   *
   * A merchant's branch address is bracketed and wraps across two lines; the
   * crop takes the card's own border with it and the border comes back as a
   * pipe at the head of the continuation line. So a pipe between a `(` and its
   * `)` is the frame's edge, not a divider between two places. The bracket has
   * to CLOSE: an unclosed one is as often a `(` the camera made out of sludge,
   * and that must not switch the stopper off for the rest of the string.
   * Measured on a real frame of this driver's — `22min(@smi total a / Asian
   * Garden a / . | I Elderberry Dr NW & ...` — the loose version stores
   * `'(@smi total a Asian Garden'` as a place. The Python twin is
   * rpi/offer_parser.py's `_inside_a_bracket`. */
  function insideABracket(value, at) {
    var open = 0, close = 0, i;
    for (i = 0; i < at; i++) {
      if (value.charAt(i) === '(') open++;
      else if (value.charAt(i) === ')') close++;
    }
    return open > close && value.indexOf(')', at) >= 0;
  }

  /* Cut a place at the first stopper, with the card's border marks removed.
   *
   * `split(PLACE_TAIL)[0]` was what this replaced, and it cannot tell a
   * border from a divider, because split does not say where the match was.
   *
   * The flags come off PLACE_TAIL rather than being written out again: it is
   * one regex, and a second statement of its flag set is a second place to
   * get it wrong. (The corpus does catch the drift — dropping the `i` fails
   * three `places` cases — so this is hygiene, not a hole.) The `g` already
   * there is taken off first: `new RegExp(source, 'gg')` throws, and this
   * runs at parse time on every page, so PLACE_TAIL gaining a `g` one day
   * would be a blank screen rather than a wrong place. */
  function cutAtTail(value) {
    var flags = PLACE_TAIL.flags.replace(/g/g, '') + 'g';
    var re = new RegExp(PLACE_TAIL.source, flags), out = '', at = 0, m;
    while ((m = re.exec(value)) !== null) {
      if (m[0] === '|' && insideABracket(value, m.index)) {
        out += value.slice(at, m.index);
        at = m.index + m[0].length;
        re.lastIndex = at;
        continue;
      }
      return out + value.slice(at, m.index);
    }
    return out + value.slice(at);
  }

  /* The first pipe that divides two places, or -1.
   *
   * The pipe split this feeds stays exactly as it was for every card with a
   * real divider — it was added for a disagreement between the phone and the
   * rig on 21 of 309 cards, and this must not undo it. */
  function dividerBar(value) {
    var at = value.indexOf('|');
    while (at >= 0) {
      if (!insideABracket(value, at)) return at;
      at = value.indexOf('|', at + 1);
    }
    return -1;
  }

  /* A `)` with nothing opening it: half of one field welded onto another.
   *
   * Nothing here can say where the seam was, so the place is refused rather
   * than repaired. Repairing it — cutting everything up to the stray `)` —
   * was tried and measured on this driver's week: the stray sits past
   * position 20 on 7 of them, where it is icon-row sludge rather than a seam,
   * and `'McDuffie Cir & Stanley Dr, . . Douglasville s ED) 5-10 bags'`
   * becomes `'5-10 bags'`.
   *
   * ONE DIRECTION ONLY, and this is the line a reader will want to
   * symmetrise. An unmatched `(` is the ordinary end of the 130-character leg
   * window landing inside a merchant's bracket, and refusing those costs 29
   * of the 500 dropoffs and 8 of the 1,080 pickups this parser reads off the
   * owner's 1,166-offer week — clean addresses, every one: 'Lakefield Ct &
   * Lakefield Walk, Marietta', 'Scenic Mountain Dr SE, Acworth'. Measured, by
   * making it symmetrical and counting. Do not.
   *
   * It took a `mark` argument so it could be asked about `(` too, and no
   * caller in either port ever passed one: the whole reversed-string half was
   * a branch no input could reach, standing there as an invitation to do the
   * thing the paragraph above says not to. The Python twin is
   * rpi/offer_parser.py's `_closes_what_it_never_opened`. */
  function closesWhatItNeverOpened(value) {
    var depth = 0, i, ch;
    for (i = 0; i < value.length; i++) {
      ch = value.charAt(i);
      if (ch === '(') depth++;
      else if (ch === ')') {
        if (depth === 0) return true;
        depth--;
      }
    }
    return false;
  }

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
    parts = cutAtTail(parts.join(' ')).split(/\s+/).filter(Boolean);
    while (parts.length && scrap(parts[parts.length - 1], PLACE_TRAIL_KEEP)) parts.pop();
    return parts.join(' ').replace(/^[\s.,\-;:|]+|[\s.,\-;:|]+$/g, '');
  }

  /* A name the card put a bracket after - "Kroger (Shiloh Square)", "GoPuff
   * (Drive)". That is how these cards write a shop, and it is the one thing
   * that distinguishes the place a job STARTS from the place it ENDS. */
  var PLACE_IS_A_SHOP = /\([^)]{2,40}\)\s*$/;

  /* Where the job ENDS, or null when the card did not say.
   *
   * The driver's own description: "the drop off locations will always pretty
   * much be someone's home address and not the restaurant". So the dropoff is
   * the last place the card named, unless that place is a shop, and unless the
   * card printed it at the START end - a shop being a name the card bracketed,
   * which is the card's own grammar rather than a list of chains. The bracket
   * is not the only thing that tells a start from an end any more: row 113 of
   * the owner's week is the bracket getting it wrong while the layout gets it
   * right. See placeEndsOf. Over 562 cards naming any place the last is a bracketed
   * shop on 9, every one a card where only the merchant read at all. */
  /* The card's own word for where a job starts. A place printed right after it
   * is a pickup however it is named - "@ Pickup Crumbl" - and brackets have
   * nothing to do with it. */
  // Between the label and the shop there is nothing but marks - "@ Pickup |",
  // "@ Pickup 3)". Between the label and a LATER leg's address there is always
  // a leg, and a leg is spelled with letters: "at pickup: 1 min 10 mins
  // (4.6 mi) N Cobb Pkwy NW". So "no letters in between" is the discriminator.
  var PICKUP_LABEL = /\bpick\s?up\b[^A-Za-z]*$/i;

  /* --- the address the card will not show you until you have taken the job ---
   *
   * 106 of the driver's 604 offer cards print "Customer dropoff" and no address
   * at all: Uber does not say where a delivery ends until it has been accepted.
   * That is 18% of every card the rig sees and it drives 39% of the pairs where
   * the stacking advice can say nothing. No parser reaches an address that is
   * not on the screen, so this reads the screen that comes AFTER the accept.
   *
   * The anchor is a two-letter state code followed by five digits. It is the
   * one part of a US address that is short, positional and CHECKABLE - "GA
   * 30127" is a state and a ZIP or it is not, where a street name misread by
   * one letter is still a perfectly plausible street name and nothing
   * downstream can tell. That checkability is the whole reason this is worth
   * doing: the alternative was sending the address to a geocoder, and a
   * geocoder returns a confident coordinate for "Daffodll Ln" as readily as for
   * the real one - a wrong distance wearing decimal precision. */
  var ZIP_RX = '[\\dOoQlIiSsBbZz]{5}';

  /* The fifty states, DC and the inhabited territories. A list, deliberately:
     the rule against phrase-lists is about lists that do not generalise to the
     next card. This alphabet is closed, national and older than the app, and it
     is doing the opposite job - it is here to REFUSE, so a misread lands on "no
     address" rather than on a confident wrong one. */
  var STATES = {};
  ('AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS ' +
   'MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV ' +
   'WI WY DC AS GU MP PR VI').split(' ').forEach(function (s) { STATES[s] = true; });

  var ADDRESS = new RegExp(
    '([A-Za-z][A-Za-z.\'’-]*(?:\\s+[A-Za-z][A-Za-z.\'’-]*){0,3})' +
    '\\s*,\\s*([A-Za-z]{2})\\s+(' + ZIP_RX + ')' +
    '(?:\\s*-\\s*[\\dOoQlIiSsBbZz]{4})?(?!\\d)', 'g');

  /* A house number and a street, shown and never decided on - but WORDS, not
     "anything but a comma". A card printing "28 min (11.2 mi) total 100
     Rosemont Ct" satisfies the loose version from the "28", and the driver is
     shown the offer's own arithmetic dressed up as a street name. */
  var STREET = /([\dOoQlIiSsBbZz]{1,6}\s+[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z0-9.'-]+){0,4})\s*$/;

  /* Where a street stops and a town starts when the address did not say with a
     comma - the case to EXPECT, not the exception: a screen puts the street and
     the town on two lines and normalize joins them with a space. The USPS
     suffix abbreviations, a list for the same reason STATES is one. The
     optional trailing quadrant belongs to the street: "Chastain Rd NW
     Kennesaw". */
  var STREET_ENDS = /\b(?:st|street|rd|road|dr|drive|ln|lane|ave|avenue|blvd|boulevard|ct|court|way|pkwy|parkway|cir|circle|trl|trail|hwy|highway|ter|terrace|pl|place|xing|crossing|sq|square|loop|run|walk|path|row|bnd|bend)\b\.?(?:\s+(?:NW|NE|SW|SE|N|S|E|W))?\s+/gi;

  /* A single letter alone in front of a town is the icon row, not a word: "l
     Atlanta", "j Powder Springs". PLACE_TOWN in advice.js tolerates exactly
     this, and the two have to agree about what a town is called or the same
     place read twice compares unequal to itself. */
  var CITY_JUNK = /^(?:[A-Za-z]\s+)+/;

  function findAddress(text) {
    if (!text) return null;
    text = normalize(text);
    var best = null, after = 0, m;
    ADDRESS.lastIndex = 0;
    while ((m = ADDRESS.exec(text)) !== null) {
      if (m.index === ADDRESS.lastIndex) ADDRESS.lastIndex++;
      var state = m[2].toUpperCase();
      // fixDigits first: the ZIP is five characters of small type through a
      // lens and "3O127" is this OCR's commonest confusion, not a different
      // number. The state gets no such help - two letters have no digits in
      // them, and "6A" corrected to "GA" would be inventing the one token that
      // is here to refuse.
      var digits = fixDigits(m[3]);
      if (!STATES[state] || !/^\d{5}$/.test(digits)) continue;
      var code = parseInt(digits, 10);
      if (!(code >= 501 && code <= 99950)) continue;
      var city = m[1].replace(/\s+/g, ' ').replace(/^[\s.,]+|[\s.,]+$/g, '')
                     .replace(CITY_JUNK, '');
      if (city.length < 3) continue;
      var cityAt = m.index;
      var before = text.slice(after, cityAt).replace(/\s+$/, '');
      if (before && before.charAt(before.length - 1) !== ',') {
        // ...unless the street named its own end. The LAST suffix in the group:
        // a town that contains one - "Powder Springs Rd Marietta" - puts the
        // real break at the later of the two.
        var split = null, sm;
        STREET_ENDS.lastIndex = 0;
        while ((sm = STREET_ENDS.exec(m[1])) !== null) {
          split = sm.index + sm[0].length;
          if (sm.index === STREET_ENDS.lastIndex) STREET_ENDS.lastIndex++;
        }
        if (split !== null && m[1].length - split >= 3) {
          cityAt = m.index + split;
          /* CITY_JUNK here as well as on the comma path above. The icon row
             lands between the street and the town whichever way the address was
             punctuated, and this is the path the code itself calls "the case to
             expect". Stripped only there, "800 Forrest St NW l Atlanta, GA
             30318" gave the town as "l Atlanta", which PLACE_TOWN in advice.js
             cannot read at all - its junk allowance covers a single UPPERCASE
             letter, not a lowercase one - so area() returns no town and the
             geography goes silent on exactly the orders the scan rescues. */
          city = text.slice(cityAt, m.index + m[1].length)
                     .replace(/\s+/g, ' ').replace(/^[\s.,]+|[\s.,]+$/g, '')
                     .replace(CITY_JUNK, '');
        } else {
          city = null;
        }
      }
      // From the end of the PREVIOUS address, never before it: a screen listing
      // two stops puts a ZIP between them, and a street search over the whole
      // head reaches back across it. Up to where the city starts, not where the
      // match does, so the half of the group that turned out to be the street is
      // still shown as one.
      var head = text.slice(after, cityAt).replace(/[\s,]+$/, '');
      var sme = STREET.exec(head);
      var street = sme ? sme[1].replace(/\s+/g, ' ')
                            .replace(/^[\s.,]+|[\s.,]+$/g, '') : null;
      var parts = [];
      if (street) parts.push(street);
      if (city) parts.push(city);
      // What to SHOW, as opposed to what to decide on. When the city could not
      // be trusted the driver still gets everything that was read - they are
      // looking at this to judge whether the scan worked, and "GA 30127" does
      // not tell them that. `city` stays null either way, so nothing downstream
      // treats the unsplit text as a town.
      var line = parts.length
        ? parts.concat([state + ' ' + digits]).join(', ')
        : m[0].replace(/\s+/g, ' ').replace(/^[\s.,]+|[\s.,]+$/g, '');
      // The LAST one on the screen: a navigation screen shows where you are
      // going, and a pickup already made comes above it. Same reasoning as
      // findDropoff.
      best = { line: line, street: street, city: city, state: state, zip: digits };
      after = m.index + m[0].length;
    }
    return best;
  }

  function labelledPickup(text, place) {
    var at = text ? text.indexOf(place) : -1;
    if (at <= 0) return false;
    // Everything before the place, not a window of it: a window was an
    // arbitrary number doing a job the letter rule already does, and on all 604
    // cards the two agree exactly.
    return PICKUP_LABEL.test(text.slice(0, at));
  }

  /* The card saying, in its own words, that it will not tell you where the job
     ends. Uber prints this instead of an address on a delivery offer: furniture,
     in a fixed place, meaning exactly one thing.

     Measured on 103 offers off this driver's own rig: 48 print it, and on every
     one the card names the merchant and nothing else. Not one of the 103 prints
     this sentence AND a second real place.

     On that export it refuses nothing the rule below would not also have
     refused. It is kept because it is the card stating the fact directly, where
     the other rule depends on the invention happening to contain the merchant's
     name — an accident of how this reader fails rather than something to lean
     on. */
  /* Screens that are the app talking about ITSELF, not offering a job.
   *
   * parse() has no offer-card token it can require. 79 of the owner's own 272
   * recorded cards carry none of "Accept", "Decline", "Guaranteed" or "Pickup"
   * — they are ride offers that read as a payout, a rating and two legs — so
   * demanding a positive anchor would refuse a third of the real traffic. The
   * only thing that can be required is the ABSENCE of the app's own furniture.
   *
   * Two screens in those 272 produced a verdict, and both were confident:
   * Uber's route planner ("Drive ... 50 min $120 ... Add stops < Share") read
   * as $120 over 105 minutes, $68.18/hr, a green ACCEPT; and DoorDash's idle
   * screen ("This dash / Finding offers. / You're in a good place to wait for
   * offers") read as $12.55 over 2 minutes, $376.50/hr. Neither is catchable
   * by the numbers — $68/hr is an ordinary rate, and $12.55 is under the flat
   * pay cap doubt() applies below ten minutes.
   *
   * TWO phrases, and both earn their place. Four were written first; mutation
   * testing showed the other two were already covered by "finding offers", and
   * a pattern nothing can show is dead weight. Each of these is the ONLY
   * evidence against its own phantom — including the second frame of the idle
   * screen, where most of the text did not survive the read. */
  var NOT_AN_OFFER = /add\s*stops|finding\s*offers/i;

  var DROPOFF_NOT_STATED = /custom[ea]r\s*drop\s*-?\s*off/i;

  function placeKey(value) {
    return (value || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  /* One end of the job wearing two readings of the same words. Containment
     rather than equality, because the ends come from different frames as often
     as not and one carries a tail of map furniture the other does not —
     "Chuy's nae" beside "Chuy''s heey". A real dropoff does not contain the
     whole merchant name, so this does not join two different places.

     The Pi has a fuzzier rule for merging readings across frames. This one runs
     in both ports and the shared corpus holds them to the same answers, so it
     has to be something the JavaScript can do identically. */
  function samePlace(a, b) {
    var x = placeKey(a), y = placeKey(b);
    if (!x || !y) return false;
    return x.indexOf(y) !== -1 || y.indexOf(x) !== -1;
  }

  /* The place the card's layout put at `want`, or null.

     Each end keeps the rule that already chose it, applied to the shorter
     list: findPickup scans FORWARD and takes the first, findDropoff scans
     BACKWARD and takes the last. So this narrows the candidates to the ones
     the card put at that end and changes nothing else - where the list order
     and the layout already agree, the answer is the one that was there before.

     Taking the last at BOTH ends was written first and the owner's week
     refused it: it swapped six pickups for a worse reading of the same street,
     and skipping the guards along with the scan cost another row its
     destination. See the Python twin, which carries both measurements. */
  function theOtherEnd(ends, i, mine) {
    var at = (ends && i < ends.length) ? ends[i] : null;
    /* null means the card did not say, which is not the card saying "the other
       one" and must not be read as it. Most entries are null: only the two-leg
       layout speaks at all. */
    return at !== null && at !== undefined && at !== mine;
  }

  function findDropoff(places, text, ends) {
    // The card said so itself. Nothing below can improve on that.
    if (text && DROPOFF_NOT_STATED.test(text)) return null;
    var startedAt = findPickup(places, ends);
    for (var i = (places || []).length - 1; i >= 0; i--) {
      /* The card printed this name against the FIRST leg, which is where the
         job starts. Every rule below is an inference off the STRING; this is
         where Uber put the words, and it outranks them. See placeEndsOf.

         It is what rows 213, 811 and 812 of the owner's week needed: two
         readings of the pickup's own street that samePlace cannot join are two
         entries, the last entry wins this scan, and the destination - in the
         middle of the list, read cleanly on every frame - was dropped. */
      if (theOtherEnd(ends, i, 1)) continue;
      if (PLACE_IS_A_SHOP.test(places[i])) continue;
      // ...and a place the card LABELLED as the pickup is a pickup, bracket or
      // no bracket. 112 of the 135 dropoffs the rig could not place on a map
      // were exactly this: an unbracketed shop name standing in for somebody's
      // front door. The word has to end right where the place begins.
      if (text && labelledPickup(text, places[i])) continue;
      // ...and where a job starts is not where it ends, whatever else is true.
      // The rule above can only refuse a place it can find in this frame's
      // text, and `places` is a union across frames while `text` is one frame.
      // On 103 real offers the old code recorded 57 dropoffs and 35 were this:
      // the restaurant being collected from, recorded as where the customer
      // lives. It is why a map of those rows could not be drawn.
      if (startedAt && samePlace(startedAt, places[i])) continue;
      return places[i];
    }
    return null;
  }

  /* Where it STARTS - for showing rather than judging, because the driver does
   * not take a second order whose pickup is far away in the first place. */
  function findPickup(places, ends) {
    /* The card's layout narrows both scans and replaces neither. Where it said
       nothing - every card that is not the two-leg shape, which is most of
       them - this reads exactly as it always did.

       The bracket rule is inside the narrowing rather than ahead of it, and
       row 113 of the owner's week is why: `Brogdon Rd & Mendi Ct, Suwanee YF
       Long trip (45+ min)` ends in a bracket because UBER'S OWN BADGE is
       bracketed, so PLACE_IS_A_SHOP called the destination a merchant and
       returned it out of a list whose first entry was the real pickup. The
       bracket rule cannot tell a badge from a branch address; the layout can,
       and did, on four frames of eight. */
    var rest = [];
    for (var i = 0; i < (places || []).length; i++) {
      if (!theOtherEnd(ends, i, 0)) rest.push(places[i]);
    }
    for (var j = 0; j < rest.length; j++) {
      if (PLACE_IS_A_SHOP.test(rest[j])) return rest[j];
    }
    if (rest.length) return rest[0];
    /* Every name on this card, the card printed against the SECOND leg: rows
       307 and 1149 of the owner's week, where the pickup never read at all.
       There is no start here to give, and nothing is lost by refusing it -
       findDropoff is about to store that same string at the end it belongs to.
       `rest` is empty only when the layout SPOKE and named every entry an end,
       never merely because the list is: an empty list returned null before and
       still does. */
    return null;
  }

  /* `whose`, when an array is passed, is filled beside the return value with
     the leg each place was found against - an index into `legs`, or null for
     one found against the Pickup or Deliver-by label. Same shape as findPay's
     `_where` and for the same reason: the caller that needs to know where a
     place sat gets this pass's own answer rather than a second search that
     could disagree with it. See laidOutApproach, the rule it feeds. */
  function findPlaces(text, legs, whose) {
    var out = [], foundOn = [];
    function keep(value, leg) {
      value = trimPlace(value);
      if (value.length < 3 || value.length > MAX_PLACE) return;
      if (closesWhatItNeverOpened(value)) return;
      if (!/[A-Za-z]{2}/.test(value)) return;
      for (var i = 0; i < out.length; i++) {
        if (out[i].toLowerCase() === value.toLowerCase()) return;
      }
      out.push(value);
      foundOn.push(leg === undefined ? null : leg);
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
      var pieces = [tail], bar = dividerBar(tail);
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
          keep(pair[1], j);
          var drop = endsAtTown(trimPlace(pair[2]));
          if (looksLikeAPlace(drop)) keep(drop, j);
          continue;
        }
        // Too long to store whole, and the reason it is too long is that it
        // holds BOTH ends of the job with no bracket between them.
        //
        // This was a silent drop: `keep` refuses anything over 60 characters,
        // so `Smash Hit Burgers - Kennesaw Allgood Rd & Monarch Dr, Marietta`
        // — sixty-one — went in the bin with the merchant, the junction and
        // the town in it, and the card stored no place at all. On the driver's
        // own 272 that happened 15 times. The cap is right: a journal full of
        // half-read map furniture is worse than one that cannot be searched.
        // What was wrong is throwing away a piece the parser's own test had
        // just called a place, and saying nothing.
        if (trimPlace(piece).length > MAX_PLACE && looksLikeAPlace(piece)) {
          PLACE_JUNCTION_AT.lastIndex = 0;
          var seams = [], sm;
          while ((sm = PLACE_JUNCTION_AT.exec(piece)) !== null) seams.push(sm.index);
          // Exactly one, or the parser does not know which ampersand is the
          // seam and does not guess. Two means either the merchant's own name
          // has an ampersand — `Freddy's Frozen Custard & Steakburgers Hamby
          // Place Dr NW & Travistock Pl NW, Acworth`, where splitting at
          // either puts half a street name on the wrong side — or the
          // 130-character window cut through a merchant's bracket and left
          // its back end here: `NW & Barretts Lake Blvd) Glencrest Dr &
          // Sourwood Dr, Marietta`.
          //
          // That second one is why refusing is not merely cautious. The
          // destination in it is good, and keeping only that is still WRONG:
          // it goes into the list ahead of the merchant a later leg finds,
          // findPickup takes the first place and findDropoff takes what is
          // left, and the card comes out saying the job ENDED at Jersey
          // Mike's, which is where it began. A missing dropoff is a gap; that
          // is a wrong answer, and this parser may produce the first and not
          // the second.
          if (seams.length === 1) {
            var seam = seams[0];
            var shop = trimPlace(piece.slice(0, seam));
            var dest = endsAtTown(trimPlace(piece.slice(seam)));
            // Neither half is judged here and neither needs to be. `keep`
            // already refuses anything too short, too long or with no letters
            // in it, and a piece that begins at a junction match begins with a
            // capitalised street word and holds an ampersand — so asking
            // looksLikeAPlace about it was a test no input could fail, which
            // reads like a guard and guards nothing.
            //
            // The merchant is kept unasked for the same reason the bracketed
            // branch keeps it: "Smash Hit Burgers" names no street and no
            // town, and it is still where the driver goes first.
            if (shop) keep(shop, j);
            keep(dest, j);
            continue;
          }
        }
        piece = endsAtTown(piece);
        if (looksLikeAPlace(piece)) keep(piece, j);
      }
    }
    if (whose) {
      whose.length = 0;
      for (var w = 0; w < foundOn.length && w < MAX_PLACES; w++) whose.push(foundOn[w]);
    }
    return out.slice(0, MAX_PLACES);
  }

  function findLegs(text) {
    var legs = [], m;
    LEG.lastIndex = 0;
    while ((m = LEG.exec(text)) !== null) {
      // An hour unit whose number has no real digit — "l hr", the lookalike
      // this file calls the commonest there is — is a leg that did not read,
      // not a leg with no hours. Matched, it silently dropped sixty minutes:
      // "l hr 10 min (4.6 mi) total" read as a ten-minute job, whole, no
      // doubt, $141/hr ACCEPT. Refused, the next frame supplies it.
      if (m[2] !== undefined && m[2] !== null && !/\d/.test(String(m[2]))) continue;
      var hours = toNumber(m[2]) || 0;
      var mins = toNumber(m[3]);
      // The number has to contain a real digit. "SI min" is two guesses
      // stacked, and stacked guesses are how noise becomes data.
      if (mins === null || !/\d/.test(String(m[3]))) continue;
      var minutes = hours * 60 + mins;
      if (minutes <= 0 || minutes > 600) continue;

      // The distance printed BEFORE the time, if the card put it there. It
      // keeps the two rules a lone distance already keeps: a real digit, and
      // not preceded by a digit or a decimal point - without the second,
      // "1.9 mi" damaged to ".9 mi" reads as nine miles. When the lead matched
      // it begins the match, so m.index is where it starts.
      var lead = (m[1] === undefined || m[1] === null) ? null : m[1];
      if (lead !== null && (!/\d/.test(lead)
          || (m.index > 0 && '0123456789.,'.indexOf(text.charAt(m.index - 1)) >= 0))) {
        lead = null;
      }
      // The bracketed one wins when a card prints both: the bracket is the card
      // saying which time this distance belongs to.
      var side = (m[4] === undefined || m[4] === null) ? lead : m[4];
      var miles = toNumber(side);
      // NOT the real-digit rule money and the lone distance now keep, and the
      // reason is worth writing down so it is not "fixed" later. Refusing
      // "(SO mi)" leaves the leg with a time and no distance, and on a single
      // leg the card labelled `total` that reading calls itself WHOLE: no
      // distance means no mileage charged, so "$12.45 20 min (SO mi) total"
      // goes from $32.85/hr with a distance to $37.35/hr without one,
      // unflagged. Today the same token becomes 50 miles, which checkDistance
      // catches as 150 mph and pulls back. A guard that turns a caught error
      // into a silent one is not a guard.
      if (miles !== null && (miles < 0 || miles > 500)) miles = null;
      // A decimal point is one or two pixels through a camera and is the first
      // thing to be lost, so remember whether this reading actually had one.
      var hadDecimal = side !== null && side !== undefined && /[.,]/.test(String(side));

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
        // Whether the card called this leg the drive to the pickup. See
        // APPROACH_TAIL and toPickup().
        isApproach: APPROACH_TAIL.test(tail),
        // Whether the card labelled this as part of the journey. Only
        // consulted for a leg with no distance, where it is the difference
        // between a leg that lost its miles and a line that never had any.
        labelled: LEG_TAIL.test(tail),
        // The same question asked of the card's punctuation rather than its
        // vocabulary: a bracket sitting where this leg's distance should be, on
        // a leg that has none. See LEG_LOST_MILES. Only meaningful when the
        // distance did not read, so it is not set when one did — a leg that has
        // its miles is already part of the journey.
        /* ...or the leg's own distance group matched and the token inside it
           would not become a number. The tail test can only ever see a bracket
           the LEG regex FAILED to consume, so it catches damage on the unit -
           "(8.1 m1)" - and is blind to damage on the DIGITS, which is the class
           this rule was written for. "(8.L mi)" is a 1 read as an L, the
           commonest single confusion there is: the bracket is swallowed by the
           match, the tail begins at the address, and the leg drops silently out
           of the journey - 17 minutes charged against 1.8 of 9.9 miles, whole
           and unflagged, a green $72.49/hr where the truth is $63.92. */
        lostMiles: miles === null && (side !== null && side !== undefined
                                      || LEG_LOST_MILES.test(tail)),
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
  /* The leg that is the drive to the pickup, when the card split it out.

     The journal has always stored a card's TOTAL distance and time, which
     includes getting to the pickup. That is the right figure to judge an offer
     on - the driver spends it either way - and it is the wrong figure for
     every question about where the WORK is, because it moves with wherever the
     car happened to be when the card arrived.

     Two jobs at once is the question that needs the difference. How far the
     second pickup sits from the first dropoff cannot be recovered from a total
     with an unknown approach folded into it, and the card states the split
     perfectly plainly. It was being read and thrown away.

     Refuses in four cases rather than guessing, because every one of them
     would produce a wrong distance rather than no distance: fewer than two
     legs, where a lone "away" would let a caller work out a trip of zero; no
     leg the card named as the approach, which is most delivery cards; more
     than one leg claiming to be the approach, which is damage; and a leg whose
     own speed is impossible. The first three are about the SHAPE of the card,
     the fourth about the numbers on the leg that shape picked out - and
     nothing else asks, because checkDistance runs on the summed card, where
     one absurd leg can hide inside a believable total.

     A card names its approach leg with the word "away" or by where it printed
     the pickup - see laidOutApproach, which sets the same flag off the layout
     so this stays the only rule that decides.

     Returns the leg, or null. The caller subtracts. */
  function toPickup(legs) {
    if (!legs || legs.length < 2) return null;
    var approach = legs.filter(function (leg) {
      return leg && leg.isApproach && !leg.isTotal;
    });
    if (approach.length !== 1) return null;
    var leg = approach[0];
    /* The fourth refusal, and the only one about the NUMBERS rather than the
       shape - see the Python port for the measurement. One frame of row 18's
       eight read `1 min (46.0 mi)` where seven saw no approach at all, and the
       merge keeps it because isApproach is ORed so a glare frame cannot lose a
       real leg. UNREADABLE_MPH, not MAX_MPH: the corpus holds a 60 mph leg
       that is plausible and must survive. */
    if (leg.minutes && leg.miles !== null && leg.miles !== undefined
        && leg.miles / (leg.minutes / 60) > UNREADABLE_MPH) return null;
    return leg;
  }

  /* Which leg the card's LAYOUT calls the drive to the pickup, or null.

     APPROACH_TAIL is a word list and this driver's cards stopped using the
     word. Measured on a real week of 1,166 offers: "away" appears on 0 of
     them, while 110 print the split plainly -

         $26.04
         8 min (3.2 mi)                                <- the drive TO the pickup
         Ector Chase NW & Ector Overlook NW, Kennesaw  <- the pickup
         39 mins (25.1 mi)                             <- the trip
         Hale St NE & Inman Village Pkwy NE, Atlanta   <- the dropoff

     The card's own statement is the ORDER: a leg, the place it arrives at, a
     leg, the place THAT one arrives at. So a leg followed by the pickup's name
     is the drive to the pickup, said positionally instead of in words.

     Not by size. On those cards the first leg is the shorter one on 62 of the
     100 that state both distances, so taking the smaller would be a guess
     dressed as a reading, and every fourth one would be wrong.

     Refuses wherever the layout is not that, because toPickup's rule is that a
     wrong split is worse than no split: anything but two legs; a leg the card
     called a `total`, which is the whole journey in one line and is also what
     a frame holding two delivery cards looks like; a card that named only one
     end, which is 10 of the week's 104 two-leg cards; and a pickup not sitting
     against the FIRST leg or a dropoff not against the second, which is the
     other 5 of those 10 - they print a place before any leg at all, a layout
     this rule cannot read and must not pretend to. */
  /* Whether the card printed the shape `leg, place, leg, place`.

     Written once and asked by both the rules that read that shape —
     laidOutApproach, which takes the drive to the pickup off it, and
     placeEndsOf, which takes which end each place is. Two copies of this
     question is the third fault class, and they would drift: the same card has
     to give the same answer to "is this the layout" whichever rule is asking.

     Anything but two legs cannot be this shape; a leg the card called a
     `total` is the whole journey in one line and cannot be half of it, which
     is also what a frame holding two delivery cards looks like; and legTravels
     refuses the pickup-wait line, which the card prints in exactly the slot
     the first leg occupies.

     BOTH legTravels calls are live here, and one looked dead an hour before
     this function existed: laidOutApproach adds a stronger guard of its own —
     the leg it publishes must STATE a distance — which subsumes legTravels for
     the FIRST leg, so while that was the only caller the first call could not
     change an answer and was deleted. placeEndsOf publishes no number and has
     no such guard, so for it that call is the only thing between a wait line
     and being read as where the job starts. A branch is dead only with respect
     to its callers. The Python twin is `two_leg_layout`.

     The distance guard is NOT here, deliberately: it belongs to
     laidOutApproach alone, because that rule publishes a number off the leg
     and this one only reads an order. */
  function twoLegLayout(legs) {
    if (!legs || legs.length !== 2) return false;
    if (legs[0].isTotal || legs[1].isTotal) return false;
    return !!(legTravels(legs[0]) && legTravels(legs[1]));
  }

  /* Which end of the job each place is, as the card's own ORDER states it.

     Returns a list beside `places`: 0 where the card put the name against the
     FIRST leg, which is where the job starts; 1 against the second, which is
     where it ends; null where the card did not say. All null unless the layout
     is the one twoLegLayout reads. The Python twin is `place_ends`, and the
     measurement is there: the merged list is in the order the FRAMES arrived,
     and reading it as the journey's order labelled the two ends wrongly on
     nine of the owner's 1,166 offers, in three shapes. */
  function placeEndsOf(legs, places, whose) {
    var out = [];
    for (var i = 0; i < (places || []).length; i++) out.push(null);
    if (!twoLegLayout(legs)) return out;
    for (var j = 0; j < out.length; j++) {
      var at = (whose && j < whose.length) ? whose[j] : null;
      if (at === 0 || at === 1) out[j] = at;
    }
    return out;
  }

  function laidOutApproach(legs, places, whose, pickup, dropoff) {
    if (!twoLegLayout(legs)) return null;
    /* The leg being PUBLISHED has to state its distance.

       The card prints a pickup-wait line in exactly the place the drive to the
       pickup goes — first, above the merchant — so `Avg. wait time at pickup:
       3 min` was published as the approach. legTravels is the project's test
       for "is this line a leg" and was tried here first; it accepts a leg on
       `lostMiles`, which is right where the question is whether a card is
       MISSING a distance and wrong where a number gets published off the
       answer. One frame whose merchant name fails to read leaves the tail
       after `3 min` beginning with the bracket below it, so the wait line
       looks like a leg — and the Pi's accumulator ORs isApproach across the
       window, so one such frame in five stamps the card.

       twoLegLayout above has already asked legTravels of both lines. For THIS
       leg that call cannot change the answer, because a line failing it has no
       distance and this guard refuses it anyway — but it is not dead, because
       placeEndsOf asks the same predicate and publishes no number. See the
       Python twin for the measurement. */
    if (legs[0].miles === null || legs[0].miles === undefined) return null;
    /* A card that already LABELLED a leg is not skipped here, and the case that
       decides it is a card whose word and whose layout name DIFFERENT legs.
       Skipping, the word would win and the trip would be published as the drive
       to the pickup. Marking both, toPickup sees two legs claiming to be the
       approach and refuses - the rule it already keeps for damage, and a
       contradiction between the two things a card says about itself is exactly
       that. Where the two agree, this marks a flag that is already set. */
    /* Load-bearing, and the two ports fail DIFFERENTLY without it: Python
       raises `ValueError: None is not in list` from places.index below, while
       this one returns null harmlessly because indexOf(null) is -1 and
       whose[-1] is undefined. So no shared-corpus case can catch its removal -
       only rpi/test_parser.py can, and this sentence is the record of why. */
    if (!pickup || !dropoff) return null;
    if (whose[places.indexOf(pickup)] !== 0) return null;
    /* No matching clause for the DROPOFF, and its absence is the measurement:
       findDropoff narrows by the same layout and drops every entry the card
       printed at the START end, so what it returns sits against the second leg
       or against no leg — and the second cannot happen, because a place with no
       leg came off the `Pickup` anchor and findDropoff's own labelled-pickup
       skip always matches it in a single-frame parse. Reached 110 times over
       1,476 real and corpus texts, and saw 1 every time. See the Python twin. */
    return 0;
  }

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
    if (legsShortADistance(detail, parsed.miles)) return false;
    // ...and its mirror: a distance the card printed that no leg claimed. The
    // leg that lost its minutes was dropped whole, so the journey is short a
    // time AND short a distance, which flatters the rate twice.
    if (parsed.shortATime) return false;
    // A shop order whose item count did not read is not finished either.
    // The count is what the shopping allowance is charged on, and with it
    // lost the same card rated $24.74/hr CLOSE CALL over 38 minutes instead
    // of $16.79/hr PASS over 56. Another frame can still supply the count.
    if (parsed.shop === true && (parsed.items === null || parsed.items === undefined)) return false;
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
  /* A distance the card printed that no leg claimed.
   *
   * The mirror of legsShortADistance, and the more dangerous half: that one
   * catches a leg that lost its miles, this one catches a leg that lost its
   * MINUTES - and minutes are the denominator, so losing them makes the rate
   * look bigger twice over. The leg goes entirely, taking its distance with it.
   *
   * On these cards a bracketed distance belongs to the time printed beside it,
   * which is what LEG's own trailing group says. So a bracketed distance
   * sitting outside every leg is a leg the reader failed on.
   *
   * Five of this driver's 604 cards, two causes, four of them turning a PASS
   * into an ACCEPT: "$9.05 * 5.00 min (44 mi)", where the star rating sits
   * where the duration goes and "00" reads as zero minutes; and "ll min
   * (35 mi)", where the minutes are spelled entirely in stand-ins and are
   * correctly refused. Both refusals are right. What was wrong is that the
   * distance went with them.
   *
   * The answer is not to guess the missing time but to stop calling the
   * reading whole, so the rig keeps looking and a later frame supplies it. */
  var LEG_ORPHAN = new RegExp(
    '\\(\\s*(' + DC + '{1,3}(?:[.,]' + DC + '{1,2})?)\\s*m(?:i|ile|iles)\\b\\s*\\)', 'gi');

  /* Every orphan bracket, handed out so the two questions asked of them -
     is anything missing, and how much - are answered by one scan and one rule
     about what counts. */
  function orphanDistances(text, legs) {
    var m, i, inside, out = [];
    LEG_ORPHAN.lastIndex = 0;
    while ((m = LEG_ORPHAN.exec(text)) !== null) {
      if (m.index === LEG_ORPHAN.lastIndex) LEG_ORPHAN.lastIndex++;
      // The same real-digit rule the minutes beside it keep.
      if (!/\d/.test(m[1])) continue;
      inside = false;
      for (i = 0; i < legs.length; i++) {
        if (legs[i].start <= m.index
            && m.index + m[0].length <= legs[i].end) { inside = true; break; }
      }
      if (!inside) out.push(m);
    }
    return out;
  }

  function distanceWithoutATime(text, legs) {
    return orphanDistances(text, legs).length > 0;
  }

  /* How far the leg that lost its minutes was, if the card said.
   *
   * The same orphan brackets read as numbers rather than counted, because
   * WHICH leg went missing decides how bad the damage is and the card states
   * that in miles whether or not it labelled anything.
   *
   * Losing the approach leg costs a journey the two minutes it takes to reach
   * the rider. Losing the trip leg costs it the job. Both set shortATime, and
   * on this driver's own corpus they differ by a factor of eight:
   *
   *   $16.05 ٣ min (1.1 mi) away 20 min (7.3 mi) trip  -> $48/hr vs a true $42
   *   $16.05 3 min (1.1 mi) away ٢٠ min (7.3 mi) trip  -> $321/hr vs a true $42
   *
   * The largest, where there is more than one: what is asked downstream is how
   * much of the journey went missing, and the biggest missing piece answers it.
   * null when nothing is missing, and ALSO null when an orphan was found and
   * would not become a number - those two are told apart by `shortATime`, which
   * is true only in the second case. See mostOfTheJourneyMissing.
   *
   * LEG_ORPHAN is built with the 'i' flag, so DC matches `L` and `q` as well as
   * the characters it lists, and toNumber has no entry for either: `(3.q mi)`
   * is a bracket this pattern really produces. */
  function untimedMiles(text, legs) {
    var found = orphanDistances(text, legs), worst = null, i, value;
    for (i = 0; i < found.length; i++) {
      value = toNumber(found[i][1]);
      if (worst === null || value > worst) worst = value;
    }
    return worst;
  }

  /* True when the leg this reading could not time is bigger than the ones it
     could - so the minutes it is about to divide by are the small half.

     Compared against the distance the reading ENDED UP with, from any source,
     because that is the journey the rate is actually worked out over. Miles it
     has none of are the same case as miles smaller than the orphan: a reading
     with no distance and a 44-mile leg it could not time knows nothing about
     how long this job takes. */
  function mostOfTheJourneyMissing(parsed) {
    var lost = parsed.untimedMiles, held = parsed.miles;
    // No number for it: either nothing is missing, or a leg IS untimed and its
    // distance would not read either - a journey missing a piece of unknown
    // size, which is refused for the same reason a reading with no distance at
    // all is. `shortATime` is what tells the two apart.
    if (typeof lost !== 'number' || !isFinite(lost)) return !!parsed.shortATime;
    if (typeof held !== 'number' || !isFinite(held)) return true;
    return lost > held;
  }

  /* Whether this line is a leg of the journey or furniture beside it.

     A leg is part of the journey if it states a distance, if the card labelled
     it one, or if a distance is printed beside it that did not read. A
     minutes-only token with none of those is a wait line, a promo chip or an
     ETA badge — `Avg. wait time at pickup: 3 min` — and reading it as a leg
     switched the mileage cost off on a third of every offer read.

     Asked in two places and written once. legsShortADistance has always needed
     it; laidOutApproach needs the same question answered the same way, because
     the card's LAYOUT puts that wait line exactly where the drive to the pickup
     goes — first, above the merchant — so a card printing one had its wait
     published as the approach. The Python twin is `leg_travels`. */
  function legTravels(leg) {
    return (leg.miles !== null && leg.miles !== undefined)
      || !!leg.labelled || !!leg.lostMiles;
  }
  /* `miles` is the distance the READING ended up with, from any source, and is
     consulted only for the single-leg case. null or undefined means the reading
     has no distance at all - which is also the default, so a caller that
     forgets to say lands on doubt rather than on a number nobody checked. */

  function legsShortADistance(legs, miles) {
    var list = [], i;
    for (i = 0; i < (legs || []).length; i++) if (legs[i]) list.push(legs[i]);
    /* A single leg used to be left alone entirely, because it can be a total,
       which states no distance and is a whole journey by itself. That exemption
       was never about the COUNT - it was about not being able to tell a total
       from a leg whose distance failed to read, and lostMiles is what tells
       them apart: a total prints no bracket where a distance would go, and a
       damaged leg still has one. Once the two-leg hole was closed this became
       the bigger half - 335 of the 337 damaged readings still publishing an
       optimistic rate had ONE leg.

       The miles guard is the whole risk. "Add a delivery" cards have one leg
       whose distance did not read AND a lone distance the branch in parse()
       recovers a few lines later, so they end up with the RIGHT number.
       Doubting those would throw away a good reading, which this project treats
       as exactly as bad as publishing a wrong one. */
    if (list.length === 1) {
      return !!list[0].lostMiles && (miles === null || miles === undefined);
    }
    // Two or more, and it does not ask whether any other leg kept its distance.
    // Both legs losing theirs is the worse case, not the exempt one: it leaves
    // miles null, which reads as "this card states no distance" rather than as
    // damage, so nothing marks it and its gross rate joins net ones in every
    // median. A single leg is left alone because it can be a total, which
    // states no distance and is a whole journey by itself.
    if (list.length < 2) return false;
    // A leg is part of the journey if it states a distance, if the card
    // labelled it one, or if a distance is printed beside it that did not read.
    // A minutes-only token with none of those is a wait line, a promo chip or
    // an ETA badge — not a leg the reader failed on. Their minutes are still
    // counted: the driver really does wait, and dropping the time would raise
    // the rate, the one direction that turns a pass into an accept.
    //
    // `lostMiles` is the third clause, and without it this rule was
    // unreachable: the label words are ride-card vocabulary this driver's cards
    // do not print, so damage that removed a leg's distance also removed the
    // leg from the set counted here. See LEG_LOST_MILES.
    var travel = [];
    for (i = 0; i < list.length; i++) {
      if (legTravels(list[i])) travel.push(list[i]);
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
    // Asked once. The legs need the candidate positions and the reading needs
    // the amount, and they must be the same answer — two calls would be two
    // chances to disagree about which figure is the headline, which is the
    // whole thing this boundary rests on.
    var payWhere = [];
    var pay = findPay(text, payWhere);
    legs = oneCard(legs, payWhere);
    // ...and the same boundary for every other field the card states. See
    // cardSpan: the legs were bounded and the distance, the deadline, the item
    // count and the merchant were not, so a frame holding two cards priced one
    // of them and described the other.
    var mine = onlyCard(text, cardSpan(payWhere));

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
    var dist = { miles: miles, corrected: correctedLeg, uncertain: false };

    var itemMatch = mine.match(ITEMS);
    var items = itemMatch ? toNumber(itemMatch[1]) : null;
    if (items !== null && (items < 0 || items > 200)) items = null;


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
    var deadline = findDeadline(mine);
    var travelled = [];
    for (var t = 0; t < used.length; t++) {
      if (used[t].miles !== null || used[t].labelled) travelled.push(used[t]);
    }
    if (miles === null && !travelled.length) {
      var lone = mine.match(LONE_MILES);
      // "4, Smi ~ fast charger" is on a real card, and S reads as 5. A lone
      // distance is already the least anchored number the parser takes; one
      // spelled entirely in stand-ins is not anchored at all.
      //
      // ...unless it printed a decimal point, which is structure the badge does
      // not have. The badge shapes are bare - "Smi", "Lmi", "Imi" - while a
      // real distance reads "l.S" or "ll.l", and a "1" lost to an l or an I is
      // this OCR's commonest single confusion. Without this clause the card has
      // NO distance, so no mileage is charged, the rate goes UP and the verdict
      // is capped: "l.S mi + 25 min" on a $12.50 offer published $30.00/hr
      // CLOSE CALL where the truth is 1.5 miles and a $28.92/hr ACCEPT.
      if (lone && (/\d/.test(lone[1]) || LONE_DECIMAL.test(lone[1]))) {
        var v = toNumber(lone[1]);
        if (v !== null && v > 0 && v <= 500) {
          miles = Math.round(v * 100) / 100;
          hadDecimal = LONE_DECIMAL.test(lone[1]);
        }
      }
    }

    /* The distance is checked HERE, below the lone-distance branch, and not
     * above it where this call used to sit.
     *
     * Above it, the check ran while `miles` was still null on every card whose
     * distance the legs did not carry — the delivery card that prints
     * "8.0 mi + 25 min", where the "25 min" half is a minutes-only leg and the
     * distance arrives from LONE_MILES a few lines below. So the distance was
     * set after the last check that could have looked at it, and then stamped
     * `milesChecked: true`, whose own comment claims checkDistance has already
     * run against the legs' own minutes. It had not.
     *
     * 140 of the 604 cards on file take that path. Five of them are damaged,
     * and were being published at 98, 117, 157, 196 and 2220 mph — three at a
     * NEGATIVE dollars per hour, because the phantom distance ate the fare as
     * mileage cost. checkDistance never returns null, so `miles === null` in
     * the branch above is unchanged by the motion, and every card whose
     * distance came from a leg gets the identical answer. */
    var checked = checkDistance(minutes, miles, hadDecimal);
    miles = checked.miles;
    dist.corrected = dist.corrected || checked.corrected;
    dist.uncertain = dist.uncertain || checked.uncertain;
    /* Asked HERE, below the lone-distance branch and below checkDistance, not
       up beside the leg sum where it used to sit. The single-leg clause turns
       on whether the reading ended up with a distance from anywhere, and up
       there the answer is only "did the legs carry one" - which on an "Add a
       delivery" card is No a few lines before the lone branch makes it Yes.
       The multi-leg branch does not look at miles at all. */
    dist.uncertain = dist.uncertain || legsShortADistance(used, miles);

    var whose = [];
    var places = findPlaces(mine, legs, whose);
    /* Which end of the job the card printed each name against, from this same
       pass's record of where they sat. Asked before the two ends, because it
       is what decides them when the card stated it. */
    var ends = placeEndsOf(legs, places, whose);
    var pickup = findPickup(places, ends);
    var dropoff = findDropoff(places, text, ends);
    /* The card can name its approach leg in words or by where it printed the
       pickup, and this is the second one. Written onto the leg rather than
       handed to toPickup, so the one rule that decides keeps deciding and so
       the flag travels: `legDetail` carries it to the accumulator, which ORs it
       across the window exactly as it already ORs a lost "away". A frame whose
       crop cut off the dropoff must not un-say a split a clearer frame read. */
    var laidOut = laidOutApproach(legs, places, whose, pickup, dropoff);
    /* In place, because `used` is these same objects whenever this fires - the
       rule refuses every card with a `total` leg, and `used` is only ever a
       different list when there is one. */
    if (laidOut !== null) legs[laidOut].isApproach = true;
    var approach = toPickup(used);
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
      places: places,
      // The two ends, named. `places` is what the card said; these say which of
      // them is which, so a second offer can be judged against the one already
      // in the car. See findDropoff, which is the half that decides.
      pickup: pickup,
      dropoff: dropoff,
      // ...and which end the CARD said each entry of `places` was, beside it,
      // so an accumulator can ask the same question of the merged list.
      // Travels for the same reason `legDetail[].isApproach` travels: this
      // frame knows where the words sat on the screen and a merged view cannot
      // work it out afterwards, because `places` is a union across frames and
      // the text beside it is one frame's. See placeEndsOf.
      placeEnds: ends,
      // A full street address, which an offer card almost never shows - Uber
      // does not say where a delivery ends until it has been accepted. Here so
      // the screen AFTER the accept can go through the same pipeline.
      //
      // "null on every one of the 604 offer cards on file bar three" is what
      // this said. Over the 900 texts on file now it is five: a merchant's
      // branch address carries the same `, ST ZIP` anchor a real one does. The
      // destination scan used to trust that count and had no guard of its own;
      // it refuses any frame carrying a payout now. See findAddress.
      address: findAddress(text),
      // Whether this is a screen rather than an offer. See NOT_AN_OFFER.
      // Reported, not acted on here: parse() says what it read and rate()
      // decides what to do about it, the same division the other doubts keep.
      notAnOffer: NOT_AN_OFFER.test(text || ''),
      // Whether the card REFUSED a destination, as opposed to the reader
      // simply not finding one. Uber prints "Customer dropoff" where the
      // address will be, so the address exists and the driver has not earned
      // it yet — one tap on the phone reveals it. Both arrive downstream as a
      // null dropoff and only this one is a state anybody can act on.
      endRefused: DROPOFF_NOT_STATED.test(text || ''),
      // The legs behind the sum, so a caller holding readings from several
      // frames can merge the ones a single frame missed.
      legDetail: used.map(function (l) {
        // `labelled` travels with them: isWhole re-runs legsShortADistance
        // over this projection, and a field the rule needs that does not
        // survive the trip is a rule that quietly stops working.
        return { minutes: l.minutes, miles: l.miles, isTotal: l.isTotal,
                 labelled: l.labelled, isApproach: l.isApproach,
                 lostMiles: l.lostMiles };
      }),
      // How much of the sum above is the drive to the pickup rather than the
      // job. Null whenever the card did not split it, which is most delivery
      // cards. See toPickup() for why it refuses rather than estimating.
      toPickupMinutes: approach ? approach.minutes : null,
      toPickupMiles: approach ? approach.miles : null,
      items: items,
      legs: used.length,
      milesCorrected: dist.corrected,
      milesUncertain: dist.uncertain,
      // A distance is only as checkable as the time beside it. Where the card
      // states a time, checkDistance has run against it - whatever the
      // distance's source, since the call moved below the lone-distance branch;
      // on a card with no minutes it returned the number untouched, and this
      // says whether it may still be recovered later. See rate(), which is
      // where the clock is.
      //
      // The wording used to say "on a ride card", and that was the whole
      // defect: the delivery cards this driver is mostly shown DO state a time,
      // so they were stamped checked while their distance had met no check at
      // all - and this flag gates rate()'s second attempt.
      milesChecked: minutes !== null,
      milesHadDecimal: hadDecimal,
      // Whether the card printed a distance no leg claimed, which means a leg
      // lost its minutes and took its miles with it. See distanceWithoutATime:
      // not a number, but the reason the reading is not finished.
      shortATime: distanceWithoutATime(text, legs),
      // ...and how far that leg was, which is what decides whether this is a
      // reading to hedge or one to refuse outright. See untimedMiles.
      untimedMiles: untimedMiles(text, legs),
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
    // No isFinite: an infinite distance is judged by the bound like any
    // other, as the Python port judges it. NaN fails every comparison on
    // its own. The two ports answered this differently and the corpus is
    // what keeps them the same.
    if (typeof miles === 'number' && miles >= 1.0
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

    // Not on a deadline card. DoorDash prints "4 items" on a restaurant
    // pickup and states a deadline instead of a duration; the time to the
    // deadline already includes the wait at the counter, and charging the
    // allowance on top took a real $23.46/hr CLOSE CALL to $18.05/hr PASS
    // on a card nobody shops for. A shop order is charged whichever way it
    // states its time.
    var shopMinutes = (parsed.shop === true || !fromDeadline)
      ? (parsed.items || 0) * secondsPerItem / 60 : 0;
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
    //
    // `miles`, not `parsed.miles`: the distance this verdict was actually
    // reached with, including the recovery a few lines up. This line said
    // `parsed.miles` and the Python said `miles`, so on a delivery card the
    // browser doubted a reading it had already repaired - it published 2.4
    // miles, charged $0.72 of mileage on 2.4, printed the rate, and then
    // withheld the verdict because the number BEFORE the repair was 75.8 mph.
    // The Pi showed CLOSE CALL and the phone showed no verdict at all, for the
    // same card on the same clock. Introduced by d4cb918, which changed the
    // Python line and touched this file without making the matching change;
    // the shared corpus missed it because its fixture for that card asserts
    // miles and cost but never `state`.
    var why = doubt(parsed.pay, cardMinutes, miles);
    /* ...and the one kind of wrong rate no check on the figures can reach,
     * because every figure in it is a figure the card really printed.
     *
     * A leg that lost its minutes is dropped whole, so the journey comes out
     * over the WRONG leg rather than over a damaged number: $18.40 for the
     * five minutes it takes to reach the rider, on a card whose trip leg says
     * an hour and twenty-four. $220.80/hr, green, against a true $12.40 - and
     * doubt() passes it, correctly, because $18.40 and 5 minutes are each an
     * ordinary thing for a card to say and the pair clears SANE_RATE at the
     * ten-minute floor.
     *
     * What is wrong is not a number, it is that most of the journey is not in
     * the reading at all, and the card says so in the distance it printed
     * beside the minutes that did not read. Asked LAST: a reading already
     * doubted for its figures keeps the more specific reason. */
    if (!why && mostOfTheJourneyMissing(parsed)) why = 'leg';

    /* ...and a screen that is not an offer at all.
     *
     * Last of the reasons, because it is the least likely and the others are
     * about figures this one has no opinion on. Withheld rather than dropped,
     * like every other doubt: if this rule ever fires on a genuine card, a
     * withheld verdict costs one offer the driver can still see on the phone,
     * where refusing to parse would lose the row and leave a hole nothing
     * could account for later. See NOT_AN_OFFER. */
    if (!why && parsed.notAnOffer) why = 'screen';

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
      // How much of the journey the reading could not time, when that is why
      // the verdict is being withheld. On the wire because the panel says it
      // out loud, and because a row saying only 'leg' cannot be argued with
      // later.
      untimedMiles: why === 'leg' ? parsed.untimedMiles : null,
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
           findPickup: findPickup, findDropoff: findDropoff,
           placeEnds: placeEndsOf, twoLegLayout: twoLegLayout,
           findAddress: findAddress,
           looksLikeAPlace: looksLikeAPlace,
           isComplete: isComplete, isWhole: isWhole, toPickup: toPickup,
           /* Exported so the default can be checked directly. Everything that
              ships passes `miles`, so nothing reachable through parse() or
              isWhole() exercises the omitted argument — and the argument is
              the guard that decides whether a good reading is thrown away. */
           legsShortADistance: legsShortADistance,
           SANE_PAY: SANE_PAY, SANE_MINUTES: SANE_MINUTES, SANE_MPH: SANE_MPH,
           SANE_RATE: SANE_RATE, SANE_RATE_OVER_MINUTES: SANE_RATE_OVER_MINUTES,
           MAX_MPH: MAX_MPH, UNREADABLE_MPH: UNREADABLE_MPH,
           MAX_PLACE: MAX_PLACE, MAX_PLACES: MAX_PLACES};
}));
