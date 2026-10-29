/* The assembler: what the screen said, attributed to the order in the car.
 *
 * Stage 3 of the multi-order design, with ONE hold. server.js keeps the I/O —
 * the journal's mark and tally rows, the stream, the hooks that search a filed
 * end on the NucBox — and asks this file every question about WHERE an order
 * ends: whether an address the scanner read is filed onto the order in the
 * car, onto the card being screened, or nowhere; what a Trip Planner gives the
 * order; and when the planner's stops come off it. No I/O, no clock read and
 * no global: every input is an argument, so tests/assemble.test.js drives the
 * same functions the server does, off tests/fixtures/sequences.json.
 *
 * WHAT CHANGED, AND WHAT DID NOT. With one hold every decision is the one the
 * old code made — the server's dropoff branch, the singleCardOnly check, the
 * planner pickup guard, and rpi/scan_pi.py's planner_destination and
 * planner_lone_dropoff, moved here rather than rewritten. The one gain is that
 * a Trip Planner may now be filed from SEVERAL PAGES: a list whose "Waybill"
 * is on the page below, a stop whose header is on one page and its address on
 * the next. The scanner sends every page as a `sighting` (emit_sighting) and
 * this stitches them; the scanner itself now only types what it saw.
 *
 * POSITIVE CUES ONLY. Nothing here attributes an address by elimination — "a
 * different card is on the slot, so this is not the held order's" is the guard
 * AUDITS.md refuses twice, because measured, it throws away the held job's own
 * destination. An address is filed when the screen says what it is (a press,
 * a Dropoff label, the planner's one dropoff on a list seen whole) and refused
 * when the screen says what it is not (a pickup, a read older than the Took),
 * and for no other reason.
 *
 * TWO ORDERS (Stage 5, behind server.js's `carryTwo`). The same holds with two
 * orders in the car, and it is what decides between them: an address goes to
 * one of two orders on a cue the screen gave (attribute(), below), and with no
 * cue to neither — the driver is asked, or it waits. Elimination appears there
 * as a cue, and only in the one shape the screen proves it: a list seen whole,
 * two dropoffs, one already filed as one order's. "Another card is on the
 * slot" is still never a reason.
 *
 * ONE ORDER AND A CARD. A ⌖ press with one order in the car and another card
 * being screened is the same question between the order and the card, and is
 * answered the same way, with carrying two off as well as on (pressBetween):
 * a cue the screen gave, or the chooser.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Assemble = factory();
}(this, function () {
  'use strict';

  /* ---------- the hold's fields and where each came from -------------------
   *
   * A hold carries `fields: {dropoff, pickupAddr, customer, expectedBy}`, each
   * `{value, from, conf, at, screen}` or null. `from` is one of, highest first:
   *
   *   press    the driver pressed ⌖ and this is what the screen showed
   *   label    unprompted, printed under a Dropoff label in its own block,
   *            off the card box (the scanner's dropoff line)
   *   nav      unprompted, printed under a "Deliver to" or "Dropoff" label in
   *            its own block, off the whole-screen read the scanner makes on
   *            its own while an order is held (navCandidate, below)
   *   planner  unprompted, the Trip Planner's one dropoff (one page or several)
   *   popup    unprompted, off DoorDash's place popup while the card was being
   *            screened, onto that card and carried here at ✓ Took (popup(),
   *            below)
   *   card     what the offer card said, at ✓ Took
   *   seen     unprompted, off the screen with no label to stand on — or a
   *            screening read whose asking was not kept on the card
   *
   * `seen` is below `card` because that is today's rule for it: an address
   * nobody asked for and no label proves fills a blank and moves nothing. It is
   * not in the plan's list of four, and naming it `card` would have been a
   * provenance that lies.
   *
   * `popup` is above `card` and `seen` and below everything read after the
   * Took. Above the card because it is the door where the card printed a
   * store's name with its street cut off, or "Customer dropoff" and nothing,
   * and it was proven to be this card's on its way in (the store's name
   * against the card's pickup, or the card on the slot when the frame was
   * taken); above `seen` because a popup carries its own role label and
   * `seen` carries none. Below planner, nav, label and press because those
   * are about the order IN THE CAR, read after the driver said they took it,
   * where a popup was read about an offer before anyone decided anything — if
   * the two disagree, the screen after the Took is the later and nearer
   * witness.
   *
   * `conf` is how much of the value read: for an address, how many of its
   * street, town and ZIP; for a name or a time, 1. `at` is the scanner's clock
   * when it read the screen (the Took for `card`), `screen` the screen type off
   * the sighting, or null where the line carried none.
   *
   * The hold's older fields — `dropoff`, `dropoffScanned` — are kept in step by
   * file() below, so the stack line, the pair rows, the map and the GPS drop
   * read exactly what they read before. */
  var RANK = { seen: 0, card: 1, popup: 2, planner: 3, nav: 4, label: 5, press: 6 };
  var FIELDS = ['dropoff', 'pickupAddr', 'customer', 'expectedBy'];

  function addressConf(a) {
    if (!a) return 0;
    return (a.street ? 1 : 0) + (a.city ? 1 : 0) + (a.zip ? 1 : 0);
  }

  function field(value, from, conf, at, screen, key) {
    if (value === null || value === undefined || value === '') return null;
    var f = { value: value, from: from, conf: conf, at: at, screen: screen || null };
    // The planner stop it came off, so a fuller reading of the SAME stop can
    // be told from a different address. Absent on everything else.
    if (key) f.key = key;
    return f;
  }

  /* The rank a card being screened holds its end at: what it printed
   * (`card`), or — read off the screen while it was screened — the provenance
   * the screening branch kept on it (`dropoffFrom`), else `seen`. A row the
   * driver picked from the chooser (`chooser`, pressBetween below) stands as
   * the press it answered: it is one, given to this card by the driver. */
  function cardRank(o) {
    if (!o || !o.dropoffScanned) return 'card';
    if (o.dropoffFrom === 'chooser') return 'press';
    return RANK[o.dropoffFrom] !== undefined ? o.dropoffFrom : 'seen';
  }

  /* The fields a hold starts with, at ✓ Took: what the card said, or — when
   * the card already carried an address read off the screen while it was
   * being screened — that, at the rank it was read at (cardRank). */
  function cardFields(offer, at) {
    var o = offer || {};
    var from = cardRank(o);
    // ...and the store's door a place popup filed on the card while it was
    // screened (filePopup), at its own rank and with its own read's time, in
    // place of the card's name for it.
    var tapped = o.pickupAddr && typeof o.pickupAddr === 'object'
      && typeof o.pickupAddr.value === 'string' && o.pickupAddr.from === 'popup'
      ? o.pickupAddr : null;
    return {
      dropoff: field(o.dropoff || null, from, 0, at, null),
      pickupAddr: tapped
        ? field(tapped.value, 'popup', tapped.conf || 0, tapped.at, tapped.screen)
        : field(o.pickup || null, 'card', 0, at, null),
      customer: null,
      expectedBy: null
    };
  }

  /* The hold's fields, made from its older ones for a hold written before
   * this file existed (a holding.json restored at boot). Same reading of
   * `dropoffScanned` as cardFields. */
  function fieldsOf(hold) {
    if (!hold) return null;
    if (!hold.fields || typeof hold.fields !== 'object') {
      hold.fields = cardFields({ dropoff: hold.dropoff, dropoffScanned: hold.dropoffScanned,
                                 pickup: hold.pickup }, hold.acceptedAt);
    }
    FIELDS.forEach(function (k) { if (hold.fields[k] === undefined) hold.fields[k] = null; });
    return hold.fields;
  }

  /* Whether `next` replaces `cur` in one field, and why; null when it does not.
   *
   *   - Nothing there: taken.
   *   - A press replaces anything, and a press is replaced only by a later
   *     press. A later press is ALWAYS taken, a less complete one included:
   *     the panel says what that press read, and a hold that kept the earlier
   *     one would disagree with the button on the glass.
   *   - What the card said is replaced by what the screen said above it
   *     (label, planner) — a door beats the card's corner or town — and not
   *     by `seen`.
   *   - Anything else the screen said unprompted is replaced only by a press,
   *     or by a FULLER reading of the same planner stop at the same rank
   *     (another page that showed more of it). Never by a less complete one,
   *     and never by a different stop: that is today's `dropoffScanned` rule,
   *     which a second label-proven address does not get past.
   *   - A navigation destination (`nav`) files as a label does, and the
   *     driver's words for it say two things more: it also replaces `seen`,
   *     an address no label proved; and over an end the screen gave before
   *     it (label, planner, nav) it is taken only as the SAME address read
   *     fuller — the same street (sameStreet), more of street, town and ZIP
   *     read. A planner stop has a key to say "the same"; a navigation
   *     screen has only its street. ...or the same street with a longer
   *     house number that ENDS in the one filed (numberFuller): the opened
   *     sheet loses a number's first digits at the left of the line, and on
   *     12 Oct one delivery's sheet read a four-digit number with its first
   *     two digits gone, twice, before it read all four, the street and town
   *     the same. */
  function outranks(next, cur) {
    if (!next) return null;
    if (!cur) return 'blank';
    if (next.from === 'press') return 'press';
    // (A press already there falls through to null: nothing below lets a
    // label, a planner, a navigation screen or a sighting past one.)
    if (cur.from === 'card') return RANK[next.from] > RANK.card ? 'over the card' : null;
    // A place popup's address: over a sighting, which no label proved; and
    // replaced by anything read after the Took (RANK), or by the same street
    // read fuller off another popup.
    if (next.from === 'popup' && cur.from === 'seen') return 'over a sighting';
    if (cur.from === 'popup') {
      if (RANK[next.from] > RANK.popup) return 'over a tap';
      return next.from === 'popup' && next.conf > cur.conf && sameStreet(next.value, cur.value)
        ? 'fuller' : null;
    }
    if (next.from === 'nav' && cur.from === 'seen') return 'over a sighting';
    if (next.from === cur.from && next.key && next.key === cur.key
        && (next.conf > cur.conf || typedOver(next.value, cur.value))) {
      return 'fuller';
    }
    if (next.from === 'nav' && cur.from !== 'press'
        && ((next.conf > cur.conf && sameStreet(next.value, cur.value))
            || (next.conf >= cur.conf && numberFuller(next.value, cur.value)))) {
      return 'fuller';
    }
    return null;
  }

  /* Whether `a` names its street's type and `b` does not, the house number
   * the same: the SAME planner stop (the caller holds the key) read clean
   * after a garbled frame. 19 Oct night: "1106 Commor" on several frames,
   * the phone printing "1106 Commons Ln"; both read a street and nothing
   * more, so conf alone never let the clean one past. The type words are
   * offer-parser.js's STREET_SUFFIX (a copy: this file loads nothing). */
  var STREET_SUFFIX = new RegExp('^(?:st|street|rd|road|dr|drive|ln|lane|ave|avenue|blvd'
    + '|boulevard|ct|court|way|pkwy|parkway|cir|circle|trl|trail|hwy|highway|ter|terrace'
    + '|pl|place|xing|crossing|sq|square|loop|run|walk|path|row|bnd|bend)$');
  var QUADRANT = /^(?:nw|ne|sw|se|n|s|e|w)$/;
  function typedOver(a, b) {
    function door(v) {
      var w = streetKey(v).split(' ');
      if (w.length > 2 && QUADRANT.test(w[w.length - 1])) w.pop();
      return /^\d+[a-z]?$/.test(w[0]) && w.length > 1
        ? { house: w[0], typed: w.length > 2 && STREET_SUFFIX.test(w[w.length - 1]) } : null;
    }
    var x = door(a), y = door(b);
    return !!x && !!y && x.house === y.house && x.typed && !y.typed;
  }

  /* Two address lines on the same street: the part before the first comma,
   * case, commas and spacing ignored, and something there to compare. */
  function sameStreet(a, b) {
    var x = streetKey(a), y = streetKey(b);
    return !!x && x === y;
  }

  /* Whether `a` is `b` with digits read that `b` lost off the front of its
   * house number: the same street after the number, the same town, and a's
   * number longer and ending in b's ("4416 Fable Dr NW" over "16 Fable Dr
   * NW"). Never the other way: a number does not lose digits by being read
   * better. */
  function numberFuller(a, b) {
    var x = /^(\d+) (.+)$/.exec(streetKey(a)), y = /^(\d+) (.+)$/.exec(streetKey(b));
    var townA = norm(String(a).split(',')[1] || ''), townB = norm(String(b).split(',')[1] || '');
    return !!x && !!y && x[2] === y[2] && townA === townB && x[1].length > y[1].length
      && x[1].slice(-y[1].length) === y[1];
  }

  /* ---------- the order's own planner pickups --------------------------------
   *
   * Whether `dropoff` is one of the held order's own Trip Planner pickups — a
   * restaurant's door, which a label-proven sighting must never be filed as.
   * Compared on the street where both read one (the planner prints no ZIP, so
   * its line and find_address's never match whole), else on the line; case,
   * commas and spacing ignored. Moved from server.js. */
  function norm(t) {
    return typeof t === 'string' ? t.toLowerCase().replace(/[\s,.]+/g, ' ').trim() : '';
  }

  function plannerPickup(held, dropoff) {
    var stops = held && held.planner && Array.isArray(held.planner.stops)
      ? held.planner.stops : [];
    return stops.some(function (st) {
      if (!st || st.kind !== 'pickup') return false;
      var a = norm(st.street), b = norm(dropoff.street);
      if (a && b) return a === b;
      return !!norm(st.line) && norm(st.line) === norm(dropoff.line);
    });
  }

  /* Whether `dropoff` is a pickup of the held order by ANY word on record:
   * one of its planner pickups (above), the pickup address a planner filed
   * on it (`fields.pickupAddr`), or the pickup its card named — on the street,
   * as sameStreet. What a navigation destination is held to: a store's door
   * read off a navigation screen is the confidently wrong end, so a nav
   * destination that is any held order's pickup is refused outright.
   *
   * ...and the card's own words for the store's DOOR, which the hold now
   * keeps (pickupWords): DoorDash's `pickupLine`, the address printed under
   * the store's name, carried onto the hold at ✓ Took, and an Uber card's
   * "Store (<n> <street>)", whose street is inside the bracket. Before, the
   * hold had the store's name alone, so "4100 Fable Rd" read off a navigation
   * screen was never the pickup "Example Diner" was (AUDITS.md, the DoorDash
   * pickupLine entry's Open note). */
  function heldPickup(held, dropoff) {
    if (!held || !dropoff) return false;
    if (plannerPickup(held, dropoff)) return true;
    return pickupWords(held).some(function (p) {
      return sameStreet(p, dropoff.line);
    });
  }

  // The held order's pickup by every word its card and its fields carry: the
  // field, the card's name, its printed door, the bracket's door. One that is
  // absent or not a string has no street, and sameStreet says no of it.
  function pickupWords(held) {
    var f = fieldsOf(held).pickupAddr;
    return [f ? f.value : null, held.pickup, held.pickupLine, bracketDoor(held.pickup)];
  }

  /* The door inside a store's bracket — "Store (123 Main St)", or cut off by
   * the card's edge, "Culver's (1275 Hwy" — or null: map-view.js searchPlan's
   * bracket, the SAME expression and the same three-letter test (held so by
   * rpi/test_lint.py), so the street this refuses a navigation screen by is
   * the street the server searches the pickup by. */
  var BRACKET_DOOR = /\(\s*(\d+[A-Za-z]?\s+[^()]*?)\s*\)?\s*$/;
  function bracketDoor(name) {
    // (exec reads anything else as its string, which no bracket is in.)
    var br = BRACKET_DOOR.exec(name);
    return br && /[A-Za-z]{3}/.test(br[1]) ? br[1].replace(/[\s,.]+$/, '') : null;
  }

  /* Why `d` is the store's and not where an order goes, or null: Uber's
   * navigation to the store (uber.pickupNav), 'a pickup screen' — whatever
   * line it read, since that screen prints the store's door and town and
   * nothing of the customer's, and whoever it was read for: the held order,
   * the card being screened, or nobody (`held` null) — else a pickup of
   * `held` by any word on record (heldPickup), 'a pickup'. navCandidate's
   * first and last refusals, the two that are about the store rather than
   * the label; dropoff() holds a press to the same two (its rule 5). */
  function storeScreen(held, d) {
    if (!d) return null;
    if (d.screen === 'uber.pickupNav') return 'a pickup screen';
    return heldPickup(held, d) ? 'a pickup' : null;
  }

  /* The Trip Planner's stops come off the order in the car at the moment the
   * driving screen forgets them (live.html's forgetDest): a different offer
   * on the record. See forgetPlanner in server.js, which says why, and which
   * now asks this. A ⌖ press was the other moment, until the owner asked on
   * 24 Oct for the press to merge (mergePlanner's `pressed`): it keeps them
   * now, here and on the panel. */
  function forgetPlanner(held) {
    if (held) delete held.planner;
  }

  /* ---------- an address arriving: where it goes ----------------------------
   *
   * `d` is a dropoff line's body (rpi/scan_pi.py, emit_dropoff) or a candidate
   * this file made off a planner (see sighting()). `held` is holding(now) —
   * NEVER the raw slot, for the reason server.js gives at the branch that
   * calls this — and `screening` is the card on the slot when it is still what
   * the driver is looking at (screeningCard), else null.
   *
   * The answer: {to: 'hold'|'card'|null, kept, asked, labelled, from, why,
   * tally, drop}. Nothing is changed here; file() and fileCard() do that, and
   * server.js does the writing and the saying. Every rule is the one the
   * server's dropoff branch had, in its order:
   *
   *   1. A planner's lone dropoff off a list whose end was below the screen
   *      (`singleCardOnly`) is filed only onto a held order whose card was ONE
   *      order on ONE leg: what the screen did not show may be a second
   *      customer's door, and the card the driver took is the only witness
   *      that there is none. `multiOrder` must say false — a card from a
   *      scanner too old to say is refused — and `legs` must be 1, or 0 when
   *      the page itself framed the trip as one pickup and one dropoff
   *      (`framed`, framedTrip; the owner's read of 21 Oct). Refused, it is
   *      dropped whole (`drop`), as it always was.
   *   2. Whether the driver ASKED (missing means asked, so a scanner older
   *      than the field keeps the behaviour it had).
   *   3. Whether an unasked one is LABEL-PROVEN: the screen printed it under
   *      "Dropoff" in its own stop block, and it was read at or after the
   *      Took — `at` is the scanner's clock, and a read older than the hold
   *      is not about it. One that fails the second half is no longer
   *      label-proven, and is `seen`: it may still fill a blank.
   *      ...except a navigation destination (`nav`, navCandidate): it is
   *      label-proven after the Took or nothing — it never falls to `seen` —
   *      and with nothing held it is nothing too.
   *   4. Not one of the hold's own planner pickups, when label-proven: a
   *      restaurant's door filed as where the customer lives is the
   *      confidently wrong direction, so it is refused outright, blank or not.
   *      A navigation destination was held to every pickup on record, of
   *      every order in the car, before it got here (navCandidate).
   *   5. A PRESS off a store's screen is refused, and the end it would have
   *      replaced stays what it was: the screen is Uber's navigation to the
   *      store (`screen` uber.pickupNav), 'a pickup screen' — for ANYONE: the
   *      held order, and since 17 Oct the card being screened too — or the
   *      line is a pickup of the held order by any word on record
   *      (heldPickup), 'a pickup'. outranks() lets a press past anything, and on 17 Oct that
   *      was the fault: an Uber order held with the Trip Planner's door as its
   *      end, ⌖ pressed at the restaurant over "Arriving soon / <Store> / <n>
   *      <Street> & / Suite 128, <Town>, GA / 30066 / Note from business", and
   *      the press read the town line alone and filed "<Town>, GA 30066" over
   *      the planner's door — Map view ran the order to the town's centre, and
   *      every offer for twenty minutes was judged against it. navCandidate
   *      already refuses an unprompted read off that screen and off a held
   *      pickup; a press is the driver saying "this screen", and a store's
   *      screen is not where the order goes, whoever asked. ...and not where
   *      a CARD goes either (the owner, 17 Oct): with an order held and
   *      another card on the slot, a press over the store's navigation opened
   *      the chooser, and "This card" filed the store's address onto the
   *      card; with nothing held it filed there straight away. Uber draws
   *      that screen only for an order accepted, so it is never the card
   *      being screened's end, and the press is refused for it as for the
   *      hold (server.js no longer opens the chooser for one, whoseDropoff).
   *      The held order's pickups by word (heldPickup) are the hold's alone:
   *      with nothing held there are none to ask.
   *   6. Onto the hold when outranks() says so; held and not outranked is
   *      nothing, and nothing said.
   *   7. With nothing held, onto the card being screened when it is asked, or
   *      when that card names no end.
   *
   * `tally` is whether the journal's `kind: 'sighting'` count row is owed:
   * every unprompted address that arrives while an order is carried. */
  /* Rule 1's question of a lone dropoff (`singleCardOnly`): the held card was
   * ONE order on ONE leg — or, off a page that frames the whole trip itself
   * (`framed`, framedTrip), legs 0: the card's legs unread, the page the
   * witness. Also asked by sighting(), which offers the trip's last stop
   * (footDropoff) beside a lone dropoff this refuses. */
  function loneTaken(held, d) {
    return !!held && !!held.card && held.card.multiOrder === false
      && (held.card.legs === 1 || (!!d && d.framed === true && held.card.legs === 0));
  }

  function dropoff(held, d, screening) {
    var out = { to: null, kept: false, asked: true, labelled: false, from: null,
                why: null, tally: false, drop: false };
    if (!d) return out;
    if (d.singleCardOnly === true) {
      if (!loneTaken(held, d)) {
        out.drop = true;
        out.why = 'not a single trip';
        return out;
      }
    }
    if (typeof d.line !== 'string') return out;
    var wasAsked = d.asked !== false;
    var labelled = !wasAsked && !!held && d.labelled === 'dropoff'
      && typeof d.at === 'number' && d.at >= held.acceptedAt;
    var nav = !wasAsked && d.nav === true;
    // (A navigation destination was held to every order's pickups when it was
    // made, navCandidate: with two in the car only that sees them all.)
    var aPickup = labelled && !nav && plannerPickup(held, d);
    out.asked = wasAsked;
    out.labelled = labelled;
    out.from = wasAsked ? 'press'
      : nav ? 'nav'
      : labelled ? (d.planner === true || d.singleCardOnly === true ? 'planner' : 'label')
      : 'seen';
    out.tally = !wasAsked && !!held;
    // A navigation destination is never `seen` and never the screened card's:
    // the scanner reads one only while an order is held, so one that is not
    // label-proven is a read older than the Took — or arrived with the order
    // already gone — and is nothing.
    if (nav && !labelled) {
      out.why = held ? 'before the Took' : 'nothing held';
      return out;
    }
    if (aPickup) {
      out.why = 'a pickup';
      return out;
    }
    // Rule 5: a press off a store's screen. Every road a press takes onto
    // a hold ends here — straight, pressBetween's 'hold', the chooser's row,
    // attribute()'s cue with two in the car — and so does every road onto
    // the card being screened, so this is the one place it is asked, before
    // either. Nothing filed, `to` null; server.js tells the panel why.
    var offStore = wasAsked ? storeScreen(held, d) : null;
    if (offStore) {
      out.why = offStore;
      return out;
    }
    if (held) {
      var cur = fieldsOf(held).dropoff;
      var why = outranks(field(d.line, out.from, addressConf(d), d.at, d.screen, d.key), cur);
      // A batch's last door (batchPlan) is filed over anything the screen
      // gave unprompted — a navigation screen or a planner read before the
      // list showed both doors may have filed the FIRST customer's — and over
      // the same door again, so the batch is recorded; never over a press,
      // which is the driver's own word for the end.
      if (!why && d.batch && labelled && cur && cur.from !== 'press') why = 'the last door';
      // ...and the reading of the SAME planner stop seen most often of late
      // (plannerVote, which sighting() asked as it was read), over a
      // different one filed first; never over a press or another stop.
      if (!why && d.vote === true && out.from === 'planner' && cur && cur.from === 'planner'
          && d.key && cur.key === d.key) {
        why = 'most read';
      }
      // ...and a card-box read under a Dropoff label (rank `label`), counted
      // in that stop's tally (labelVote) whatever else is decided, and filed
      // when it is now the most read...
      // (Rank `label` or `planner` is itself a read a Dropoff label proved
      // after the Took, unpressed and not a navigation screen: out.from
      // above. So neither rule asks `labelled` or `nav` again.)
      var won = labelVote(held, d, out.from);
      // ...and the same door read with its street's type, over a planner
      // street filed without one or with a garbled last word (labelTyped).
      if (!why && labelTyped(d, cur, out.from)) why = 'typed street';
      // ...and the trip's last stop filed off its cropped block (footDropoff:
      // rank `label`, off the planner's screen) read again under its header,
      // stitched or whole, the same street: the planner's reading of the same
      // door, with its customer and time, in its place.
      if (!why && out.from === 'planner' && cur && cur.from === 'label'
          && cur.screen === 'uber.planner' && sameStreet(d.line, cur.value)) {
        why = 'same door';
      }
      if (!why && won) why = 'most read';
      if (why) {
        out.to = 'hold';
        out.kept = true;
        out.why = why;
      } else {
        out.why = 'outranked by ' + (cur ? cur.from : 'nothing');
      }
      return out;
    }
    if (screening && (wasAsked || !screening.dropoff)) {
      out.to = 'card';
      out.kept = true;
      out.why = wasAsked ? 'press' : 'blank';
    }
    return out;
  }

  /* The owner, 19 Oct 21:41: the planner's dropoff read "305 <Name> Dr" once
   * and was filed; every later read said "905 <Name> Dr", the same stop key
   * and as complete, so outranks() kept "305" and its door was never found.
   * "Rescanning can throw out previous good scans." So the hold keeps the
   * street lines (house number and street, streetKey) of the last VOTE_READS
   * readings of ONE planner stop (`dropoffReads`: its key and the lines,
   * the filed one counted as it was read), and a reading whose line is now
   * seen more often than the filed one's, and most often of all, replaces
   * it. A tie keeps the filed one. Another key starts the tally anew; a press,
   * or anything filed that is not that stop's planner read, is never voted
   * over. Returns whether `d` wins. VOTE_READS is CHOSEN, not measured.
   * Asked by sighting() for every unprompted planner reading of a stop, the
   * ones its once-per-line dedupe drops included (else a repeat would never
   * count), and the winner passes that dedupe; dropoff() files it. */
  var VOTE_READS = 5;
  function plannerVote(held, d) {
    if (!held || !d || d.asked || d.planner !== true || !d.key) return false;
    var cur = fieldsOf(held).dropoff;
    var line = streetKey(d.line);
    if (!line) return false;
    var v = held.dropoffReads;
    if (!v || v.key !== d.key) v = held.dropoffReads = { key: d.key, reads: [] };
    v.reads.push(line);
    if (v.reads.length > VOTE_READS) v.reads.shift();
    if (!cur || cur.from !== 'planner' || cur.key !== d.key) return false;
    return mostRead(v.reads, line, streetKey(cur.value));
  }

  // Whether `line` is seen more often than `filed` among `reads`, and as often
  // as any line there. Never the filed line itself: it is not seen more often
  // than itself.
  function mostRead(reads, line, filed) {
    function count(x) { return reads.filter(function (r) { return r === x; }).length; }
    var mine = count(line);
    return mine > count(filed) && reads.every(function (r) { return count(r) <= mine; });
  }

  /* The owner, 20 Oct 20:44: the planner's dropoff "2100 <Ellison> Lakes Dr /
   * Kennesaw, GA" read whole-screen as "2100 <Ellison> Lake r" and filed
   * (from 'planner'); the NucBox found nothing. Every read after was a
   * CARD-BOX read of the planner (not whole), which the scanner sends as a
   * dropoff line under a Dropoff label — rank `label`, no stop key — and said
   * "2100 <Ellison> Lakes Dr" cleanly; but the typed-street replacement
   * (typedOver, in outranks) and the house vote (plannerVote) count only the
   * same planner stop's whole-screen reads, and a label does not replace a
   * planner. So the hold kept the garbled one.
   *
   * labelTyped: an unprompted read under a Dropoff label after the Took, at
   * rank `label` or `planner` (box or whole, any key), with the SAME house
   * number as the planner street filed, its street ending in a type word,
   * where the filed one's does not (no type word, or a garbled last word: "r"
   * in "Lake r"), replaces it (typedOver). Filed at its own rank. Never over
   * a press or anything not a planner read; never the untyped one back; never
   * one typed street over another, or another house number.
   *
   * labelVote: the same card-box reads are counted in the filed stop's
   * `dropoffReads` (plannerVote's tally, under the filed key; started with
   * the filed line where the tally is another stop's or none), so a box read
   * of the right house number counts toward the planner's next read of it —
   * and files 'most read' itself when it is now the most read, over a
   * planner read only. Planner reads are counted by plannerVote alone.
   * Returns whether `d` wins. The text changes either way, so the held-end
   * search runs again for it. */
  function labelTyped(d, cur, from) {
    return (from === 'label' || from === 'planner') && !!cur && cur.from === 'planner'
      && typedOver(d.line, cur.value);
  }

  function labelVote(held, d, from) {
    if (from !== 'label') return false;
    var cur = fieldsOf(held).dropoff;
    if (!cur || cur.from !== 'planner' || !cur.key) return false;
    var line = streetKey(d.line), filed = streetKey(cur.value);
    if (!line || !filed) return false;
    var v = held.dropoffReads;
    if (!v || v.key !== cur.key) v = held.dropoffReads = { key: cur.key, reads: [filed] };
    v.reads.push(line);
    while (v.reads.length > VOTE_READS) v.reads.shift();
    return mostRead(v.reads, line, filed);
  }

  /* What a kept decision changes on the hold: the field, the older fields
   * beside it, and — for an address off a planner stop — the customer and the
   * time that stop gave, by the same outranks(). A planner's lone dropoff that
   * files clears the reason the planner said none was filed, on the hold and,
   * given the assembler's state `st`, for the planner line still to come. */
  function file(held, d, said, st) {
    if (!held || !said || said.to !== 'hold') return;
    var f = fieldsOf(held);
    f.dropoff = field(d.line, said.from, addressConf(d), d.at, d.screen, d.key);
    held.dropoff = d.line;
    held.dropoffScanned = true;
    // ...and the place the phone printed for that stop (placeOf), or none:
    // it belongs to THIS end, so an end filed without one takes the old one
    // away. The server searches the held end by it when the NucBox has the
    // street and not the door (server.js searchHeldPlace, the owner's
    // decision of 17 Oct); until then a place was shown and never searched.
    var place = placeOf(d);
    if (place) held.dropoffPlace = place;
    else delete held.dropoffPlace;
    if (d.stop) {
      [['customer', d.stop.name], ['expectedBy', d.stop.expectedBy]].forEach(function (p) {
        var next = field(p[1], said.from, 1, d.at, d.screen, d.key);
        if (outranks(next, f[p[0]])) f[p[0]] = next;
      });
    }
    if (d.pickupAddr) {
      var pk = field(d.pickupAddr.line, said.from, addressConf(d.pickupAddr), d.at, d.screen,
                     d.pickupAddr.key);
      if (outranks(pk, f.pickupAddr)) f.pickupAddr = pk;
    }
    // ...and a batch (batchPlan): every door of the trip, on the hold, so
    // the panel and /api/status can say there are more than one. The hold's
    // end is the last of them, set above; the GPS drop arms on that one
    // alone, so an earlier door never puts the order down.
    if (d.batch && Array.isArray(d.batch.drops)) {
      held.batch = true;
      held.drops = d.batch.drops.map(function (x) { return Object.assign({}, x); });
    }
    if (d.singleCardOnly === true || d.batch) {
      if (held.planner) held.planner.unfiled = null;
      // ...and the planner line that follows this read's sighting is told so,
      // and the pages it came off leave the pool: the order has its end.
      if (st) {
        st.verdicts.forEach(function (v) { if (v.at === d.at) v.why = null; });
        st.pages.forEach(function (p) {
          if ((d.pageAts || []).indexOf(p.at) !== -1) {
            p.pending = false;
            p.why = null;
          }
        });
      }
    }
  }

  /* The place a dropoff's stop was printed with ("<Something> Parking Deck"),
   * or null: the dropoff line's own `place` (rpi/scan_pi.py emit_dropoff,
   * off the customer sheet), or a candidate's made here off a Trip Planner
   * stop or a navigation sheet (candidate, navCandidate). The readers' rule
   * for it (offer_parser.py, the planner's and the sheet's place) is theirs;
   * here it is only carried. */
  function placeOf(d) {
    var p = d && d.place;
    return typeof p === 'string' && p.trim() ? p.trim() : null;
  }

  /* ...and onto the card being screened. `dropoffFrom` rides with it, so the
   * hold made from this card at ✓ Took knows a press from a sighting — and a
   * press the driver gave this card from the chooser (`cue` 'chooser',
   * pressBetween) says so, `chooser`, which cardRank carries as a press. */
  function fileCard(card, d, said, cue) {
    if (!card || !said || said.to !== 'card') return;
    card.dropoff = d.line;
    card.dropoffScanned = true;
    card.dropoffFrom = said.from === 'press' && cue === 'chooser' ? 'chooser' : said.from;
  }

  /* ---------- a ⌖ press between the order in the car and a card -----------
   *
   * The owner's habit: screening a DoorDash offer, tap the customer's dropoff
   * open on the phone to read where it goes — with an order already in the
   * car. A press then may be about either job, and dropoff() gives a press to
   * the order in the car whatever is on the slot. Measured against the real
   * server at b337a44, one order held with its end on record and a different
   * card being screened, carrying two off and on alike: a press replaced the
   * held order's end every time; and over the card's own customer popup, whose
   * line had already filed that address on the card, one address became both
   * jobs' end.
   *
   * Stage 5's rule (AUDITS.md, Settled, plan 3.1), with one order: positive
   * cues only, otherwise the driver picks. {to, cue, why}:
   *
   *   card   the press read DoorDash's place popup (`screen` dd.placePopup),
   *          which the app draws over an offer card and never over an order
   *          taken, on the street the card's end already came off the screen
   *          as: a popup popup() filed there — its role label, read after the
   *          card came onto the slot and inside the card's window, the same
   *          app, one customer — or an earlier press. Cue 'popup'.
   *          A store's popup sends no address under a press: the scanner
   *          refuses one under a Pickup label, asked or not, so its door
   *          reaches the card through popup() alone and this is not asked.
   *   hold   the press read a screen of an order taken, not offered: Uber's
   *          navigation or Trip Planner (`screen` uber.nav, uber.planner),
   *          read at or after the order's ✓ Took, of its app where both say
   *          one, and naming its store where the screen names one and the
   *          card printed one (cardNames). Cue 'nav' or 'planner'.
   *   null   neither — `why` says which half failed — and server.js opens
   *          the chooser over the order and the card, filing nothing unless
   *          the driver picks.
   *
   * No DoorDash screen is typed as one after an accept (offer_parser
   * screen_type: its delivery screens are 'unknown'), so a DoorDash order in
   * the car has no screen cue here, and a press over its own screen while a
   * card is up is the driver's to answer.
   *
   * Null, not this question at all, when `d` was not pressed for, when nothing
   * is held, when no card is being screened, or when the card IS the order in
   * the car (its card back on the phone, or its id on the slot): dropoff()
   * then decides exactly as it did. ...and when the card on the slot is one
   * the driver already marked taken (`accepted`): that is an order, not an
   * offer being screened — the slot keeps it after its order is put down, and
   * a Took sent with the panel's own copy of a card leaves it there — and a
   * press is not about it. */
  function pressBetween(held, card, d) {
    if (!held || !card || !d || d.asked === false || typeof d.line !== 'string') return null;
    if (card.heldCard || card.id === held.id || card.accepted === true) return null;
    var out = { to: null, cue: null, why: null };
    if (d.screen === 'dd.placePopup') {
      if (ownPopup(card, d)) {
        out.to = 'card';
        out.cue = 'popup';
      } else {
        out.why = "not the card's own popup";
      }
      return out;
    }
    if (d.screen === 'uber.nav' || d.screen === 'uber.planner') {
      var since = typeof held.tookAt === 'number' ? held.tookAt : held.acceptedAt;
      out.why = typeof d.at !== 'number' || d.at < since ? 'before the Took'
        : d.app && held.app && d.app !== held.app ? 'another app'
        : d.store && typeof held.pickup === 'string' && held.pickup
          && !cardNames(held.pickup, d.store) ? 'another store'
        : null;
      if (!out.why) {
        out.to = 'hold';
        out.cue = d.screen === 'uber.nav' ? 'nav' : 'planner';
      }
      return out;
    }
    out.why = 'no cue';
    return out;
  }

  /* The card cue, on its own: `d`, a press, read DoorDash's place popup on the
   * street this card's end already came off the screen as — a popup popup()
   * filed there, or an earlier press. pressBetween's, and with two orders
   * held server.js's whoseDropoff asks it before attribute(). */
  function ownPopup(card, d) {
    return !!card && !!d && d.screen === 'dd.placePopup' && typeof d.line === 'string'
      && typeof card.dropoff === 'string'
      && (cardRank(card) === 'popup' || cardRank(card) === 'press')
      && sameStreet(card.dropoff, d.line);
  }

  /* Whether the card being screened is a third owner a press could belong
   * to with two orders held — so that no order is chosen for it by the
   * hard rules alone (attribute(), `card`): a press, a card that is no order
   * in the car (not its id, not its card back) and not one already marked
   * taken, of the press's app where both say one, and a screen that is not
   * one of an order taken — Uber's navigation and Trip Planner (`screen`
   * uber.nav, uber.planner) show only orders accepted, which an offer being
   * screened is not. */
  function cardCandidate(orders, card, d) {
    if (!card || !d || d.asked === false) return false;
    if (card.heldCard || card.accepted === true) return false;
    if ((orders || []).some(function (o) { return o && o.id === card.id; })) return false;
    if (d.app && card.app && d.app !== card.app) return false;
    return d.screen !== 'uber.nav' && d.screen !== 'uber.planner';
  }

  /* ---------- a place popup, read while a card is screened -----------------
   *
   * DoorDash's place popup (offer_parser.place_popup): the driver taps a stop
   * on an offer card before deciding, and the phone shows that stop's address.
   * The scanner sends it on its own line (rpi/scan_pi.py, emit_popup), never
   * as a dropoff line, because a dropoff line's road ends on the order in the
   * car and this is never about the order in the car.
   *
   * `card` is the card being screened (server.js screeningCard) or null; `p`
   * the popup line; `ctx` {held: the orders in the car, offerAt: when this
   * card came onto the slot, seenAt: when it was last read, cardMs: how long
   * after that a customer's popup may still be about it}. Positive cues only,
   * as everything in this file:
   *
   *   1. A role, from the popup's own label — the reader refuses one without,
   *      and so does this.
   *   2. A card being screened, and not an order in the car: never onto the
   *      held order, nor onto its card come back on the phone.
   *   3. Read after the card came onto the slot: `p.at` is when the popup's
   *      frame was TAKEN, so a card that replaced the one it was opened over
   *      — or arrived while it was being read — is not given it.
   *   4. The same app: the popup is DoorDash's, and so must the card be.
   *   5. A store's popup names the card's pickup — sameStore over a run of the
   *      card's words, so ONE i/l slip is allowed and nothing else — and where
   *      the card printed a house number after the name, the popup's ends in
   *      it (the card's street loses digits at its left as the navigation
   *      sheet's does; see numberFuller). A name that matches, a number that
   *      does not, is another branch of the same chain.
   *   6. A customer's popup has no name to match, so the card has to be the
   *      one still on the screen: read within `cardMs` before the popup's
   *      frame. And the card must have ONE customer: "Multiple dropoffs"
   *      (`manyDropoffs`) leaves which door this is undecided.
   *   7. outranks() against what the card already holds for that end: a door
   *      over the card's own words or a sighting, never over a press.
   *
   * {to: 'card'|null, field: 'pickupAddr'|'dropoff'|null, from: 'popup', why}.
   * Nothing is changed here; filePopup() does that. */
  function popup(card, p, ctx) {
    var c = ctx || {};
    var out = { to: null, field: null, from: 'popup', why: null };
    if (!p || (p.role !== 'pickup' && p.role !== 'dropoff')) { out.why = 'no role'; return out; }
    if (typeof p.line !== 'string' || !p.line) { out.why = 'no address'; return out; }
    out.field = p.role === 'pickup' ? 'pickupAddr' : 'dropoff';
    if (!card) { out.why = 'no card being screened'; return out; }
    if (card.heldCard || (c.held || []).some(function (o) { return o && o.id === card.id; })) {
      out.why = 'the order in the car';
      return out;
    }
    if (typeof p.at !== 'number' || typeof c.offerAt !== 'number' || p.at < c.offerAt) {
      out.why = 'before the card';
      return out;
    }
    if (card.app !== (p.app || 'doordash')) { out.why = "another app's card"; return out; }
    var cur, next = field(p.line, 'popup', addressConf(p), p.at, p.screen || 'dd.placePopup');
    if (p.role === 'pickup') {
      var named = cardNames(card.pickup, p.name);
      if (!named) { out.why = 'a different store'; return out; }
      var mine = /^(\d+) /.exec(p.street || p.line);
      if (named.number && !(mine && mine[1].length >= named.number.length
                            && mine[1].slice(-named.number.length) === named.number)) {
        out.why = 'a different branch';
        return out;
      }
      cur = card.pickupAddr || null;
    } else {
      if (card.manyDropoffs === true) { out.why = 'more than one customer'; return out; }
      if (typeof c.seenAt !== 'number' || p.at - c.seenAt > (c.cardMs || 0)) {
        out.why = 'the card not on the screen';
        return out;
      }
      cur = !card.dropoff ? null : field(card.dropoff, cardRank(card), 0, null, null);
    }
    var why = outranks(next, cur);
    if (!why) { out.why = 'outranked by ' + (cur ? cur.from : 'nothing'); return out; }
    out.to = 'card';
    out.why = why;
    return out;
  }

  /* Whether the card's pickup line names the store `name`: a run of its words
   * that is sameStore with it. {number} — the house number the card printed
   * straight after the name, or null — when it does; null when it does not. */
  function cardNames(pickup, name) {
    if (typeof pickup !== 'string' || typeof name !== 'string' || !storeKey(name)) return null;
    var words = pickup.split(/\s+/).filter(Boolean);
    var want = storeKey(name).length;
    for (var i = 0; i < words.length; i++) {
      for (var j = i; j < words.length; j++) {
        var run = words.slice(i, j + 1).join(' ');
        if (storeKey(run).length > want) break;
        if (!sameStore(run, name)) continue;
        var after = words.slice(j + 1, j + 3).map(function (w) { return w.replace(/[^0-9A-Za-z]/g, ''); })
          .filter(Boolean)[0] || '';
        return { number: /^\d+$/.test(after) ? after : null };
      }
    }
    return null;
  }

  /* What a kept popup changes on the card: the store's door as `pickupAddr`,
   * the field cardFields() carries into the hold at ✓ Took; a customer's as
   * the card's end, through the same three fields a screening ⌖ press sets,
   * so the hold, the map and the journal's mark read it as they read that. */
  function filePopup(card, p, said) {
    if (!card || !said || said.to !== 'card') return;
    if (said.field === 'pickupAddr') {
      card.pickupAddr = { value: p.line, from: 'popup', conf: addressConf(p), at: p.at,
                          screen: p.screen || 'dd.placePopup', name: p.name || null };
    } else {
      card.dropoff = p.line;
      card.dropoffScanned = true;
      card.dropoffFrom = 'popup';
    }
  }

  /* ---------- the Trip Planner: one page ------------------------------------
   *
   * The address a Trip Planner gives the order in the car, and why not —
   * moved from rpi/scan_pi.py's planner_destination, word for word in rule:
   *
   * {address, why}: the address when it gives one; {null, why} when it does
   * not, `why` being the word the panel says it with; {null, null} for a
   * planner with no dropoff on it at all.
   *
   * EXACTLY ONE DROPOFF ON THE TRIP. With two or more — orders stacked —
   * nothing on the screen says which one belongs to the order the driver
   * marked taken, and the planner lists them in the order they will be
   * driven, not the order they were accepted: 'dropoffs'.
   *
   * ...ON THE TRIP, NOT ON THE SCREEN. Two open stops fill the list
   * (offer_parser.planner_bounded has the measurement), so one dropoff is the
   * trip's only one when the list is seen whole, `bounded`; otherwise 'list'.
   *
   * ...AND BOTH THE STREET AND THE TOWN READ. With no ZIP on this screen the
   * street is the only precision there is: a town alone would put a pin on
   * the middle of Marietta: 'address'.
   *
   * `stops` are the HEADED stops — a stop of no kind (the top of a page that
   * starts mid-stop) is not counted, as planner_stops never handed it over. */
  var ADDRESS_KEYS = ['line', 'street', 'city', 'state', 'zip'];

  function addressOf(s) {
    var a = {};
    ADDRESS_KEYS.forEach(function (k) { a[k] = s[k] === undefined ? null : s[k]; });
    return a;
  }

  function headed(stops) {
    return (stops || []).filter(function (s) { return s && s.kind; });
  }

  /* Whether a planner sighting is a page the stitch may hold: one with a
   * headed stop, or a HEADLESS page — its one stop of no kind, `partial:
   * 'top'`, an address read (find_planner's _planner_headless: an address
   * block with "Waybill" under it and no header anywhere). The second is the
   * foot of a list whose last header the page above cut, and it is held only
   * so that the stitch can join it under that header (fits, below: same app,
   * no other screen between, within STITCH_MS, equal times where both print
   * one). Alone it decides nothing: every rule that files counts headed()
   * stops, and it has none, so it waits in the pool as 'no dropoff'. */
  function pageStops(stops) {
    if (!Array.isArray(stops)) return false;
    if (headed(stops).length) return true;
    var s = stops.length === 1 ? stops[0] : null;
    return !!(s && typeof s === 'object' && !s.kind && s.partial === 'top'
              && (s.street || s.city));
  }

  /* Whether the pickups' "N orders" add up to more than the dropoffs' do. A
   * trip delivers what it picks up, so on a list read whole the two are equal;
   * more picked up than dropped off is a dropoff the reader did not read — its
   * header lost to OCR, its lines filed under the stop above (find_planner) —
   * and the dropoff that is left may be another customer's door. A count that
   * did not read (`orders` null) counts nothing on either side. Said as 'list',
   * the list not seen whole, which is what it is, and a later read that gets
   * the header back can still file: 'dropoffs' would refuse the pages for good
   * over a misread. */
  function listShort(stops) {
    var sum = function (kind) {
      return headed(stops).reduce(function (n, s) {
        return n + (s.kind === kind && typeof s.orders === 'number' ? s.orders : 0);
      }, 0);
    };
    return sum('pickup') > sum('dropoff');
  }

  function plannerDestination(stops, bounded) {
    var drops = headed(stops).filter(function (s) { return s.kind === 'dropoff'; });
    if (!drops.length) return { address: null, why: null, stop: null };
    if (drops.length > 1) return { address: null, why: 'dropoffs', stop: null };
    if (!bounded || listShort(stops)) return { address: null, why: 'list', stop: drops[0] };
    if (!(drops[0].street && drops[0].city)) return { address: null, why: 'address', stop: drops[0] };
    return { address: addressOf(drops[0]), why: null, stop: drops[0] };
  }

  /* The address of the planner's one dropoff when the list's end is off the
   * screen ('list' above) and the screen still says this much: exactly one
   * Dropoff stop, its header "1 order", its street and town read. Null
   * otherwise. Moved from rpi/scan_pi.py's planner_lone_dropoff.
   *
   * The owner's decision, after a hotel dropoff on a two-stop trip went
   * unfiled because "Waybill" was under the bar: trust a single-trip offer.
   * What is below the screen is still unseen, so this is only HALF the
   * answer — the other half is the held order's own card, one order on one
   * leg, which dropoff() asks of the hold (`singleCardOnly`). */
  function plannerLoneDropoff(stops) {
    var drops = headed(stops).filter(function (s) { return s.kind === 'dropoff'; });
    if (drops.length !== 1 || drops[0].orders !== 1) return null;
    // ...and not when the pickups say the trip carries more than it drops off:
    // that is not a single trip, whatever is left on the glass (listShort).
    if (listShort(stops)) return null;
    if (!(drops[0].street && drops[0].city)) return null;
    return addressOf(drops[0]);
  }

  /* The address of a single trip's dropoff whose header the reader lost
   * (offer_parser._planner_lost_dropoff, `partial: 'header'`), when the held
   * order's OWN card names its street; null otherwise. The owner's read of 20
   * Oct, 21:08: "Dropoff · 1 order" lost to OCR on a whole-screen read of the
   * planner, the customer's name, time and door under the pickup's "View
   * details", and the hold kept the card's end, "<Name> Creek Bivd, Marietta",
   * with no house number.
   *
   * The parser keeps that stop only in one shape (one Pickup header of "1
   * order", the pickup's block open and closed by "View details" straight over
   * the lost name, exactly two "Expected by", a door with its town read), and
   * never as bounded: the header that would say "dropoff" and "1 order" is
   * the line lost, so plannerDestination and plannerLoneDropoff never file it
   * (its count is null and listShort says so). What says it is THIS order's
   * door is the witness the two-order rule already trusts (streetCues,
   * `cardStreet`): the card the driver took names the street, streetCore to
   * streetCore (house number, type and quadrant gone). So, all of:
   *   - the list read is exactly one pickup of "1 order" and that one dropoff;
   *   - one order held, not an add-on trip's (`addOn`, `of`), and asked by the
   *     caller of an unprompted whole-screen read only;
   *   - the held card's end (cardEndOf: what it printed) names the street;
   *   - and, as the lone-dropoff rule, the card is one order on one leg
   *     (`singleCardOnly`, asked by dropoff()).
   * With two orders held the same stop is offered as sightingMany's `partial`
   * candidates are, and only the cardStreet cue can file it. */
  function lostHeaderDropoff(held, stops) {
    var all = headed(stops);
    var drops = all.filter(function (s) { return s.kind === 'dropoff'; });
    var picks = all.filter(function (s) { return s.kind === 'pickup'; });
    if (drops.length !== 1 || drops[0].partial !== 'header') return null;
    // (A headed stop is a pickup or a dropoff, so these two are the list.)
    if (picks.length !== 1 || picks[0].orders !== 1) return null;
    if (!held || held.addOn || held.of) return null;
    var d = drops[0];
    if (!(d.street && d.city)) return null;
    var core = streetCore(d.street);
    if (!core || cardStreets(cardEndOf(held)).indexOf(core) === -1) return null;
    return addressOf(d);
  }

  /* The trip's LAST stop, its header cropped off, as a dropoff candidate, or
   * null. The owner's card-box read of 21 Oct, 15:00, one Uber order held:
   * "Address / 3259 <Name> Oaks Dr / Marietta, GA / View details / Waybill /
   * … / Stop New Requests", the "Dropoff" header above the crop, and nothing
   * filed — a card-box read is no page, and a headless stop has no kind. On
   * Uber's Trip Planner the trip ends on a dropoff, so the block the list's
   * foot sits straight under is one, whatever header it had. The parser says
   * the shape (offer_parser.planner_foot, the sighting's `footed`): no stop
   * header on the read, the last "View details" straight under "Address",
   * "<n> <street>" and "<Town>, ST", and "Waybill" or the bar straight under
   * it. Card box or whole, all of:
   *   - the sighting is the planner's, `footed`, unpressed (a ⌖ press is the
   *     press's own rule, and outranks() keeps a pressed end over this), and
   *     its one stop is that headless block, street and town read;
   *   - exactly ONE order held, not an add-on trip's (`addOn`, `of`):
   *     sightingMany takes two and never asks this;
   *   - read at or after its Took (dropoff() asks `at` again);
   *   - not one of the held order's pickups by any word on record
   *     (heldPickup): a store's door is the confidently wrong end.
   * Filed at rank `label` — a dropoff the screen proved, as a card-box read
   * under a Dropoff label is (`labelled`, not `planner`) — so it fills the
   * card's corner or town and never passes a press or a planner's door.
   *
   * ...and the same block WITH its "Dropoff" header (the owner's card-box
   * read of 22 Oct: "Dropoff - 1 order", the block, the bar's icons and the
   * bar, one Uber order held whose card read legs 0; planner_foot now says
   * `footed` of it). The last stop on the sighting is then that Dropoff,
   * whole (no `partial`), and every other stop on it a headed Pickup: a page
   * that shows another dropoff may be an add-on's list, whose last door is
   * attribute()'s and batchPlan's to give, and a block of no kind above it
   * (cut by the top edge) may be one — the stitch decides those, as it did.
   * The customer is left off as on a headless page: a name read at rank
   * `label` would stand over the planner's cleaner reading of it. */
  function footDropoff(held, s, at) {
    if (!held || held.addOn || held.of || !s || s.footed !== true || s.asked === true) return null;
    if (s.screen !== 'uber.planner' || !Array.isArray(s.stops) || !s.stops.length) return null;
    var d = s.stops[s.stops.length - 1];
    if (!d || typeof d !== 'object') return null;
    var headless = s.stops.length === 1 && !d.kind && d.partial === 'top';
    // ...and never a list whose pickups carry more orders than its dropoffs
    // (listShort: "Pickup - 2 orders" over one dropoff is a header lost).
    var headed = d.kind === 'dropoff' && !d.partial && s.stops.every(function (x) {
      return x === d || (x && typeof x === 'object' && x.kind === 'pickup');
    }) && !listShort(s.stops);
    if (!headless && !headed) return null;
    if (!(d.street && d.city && typeof d.line === 'string')) return null;
    if (typeof at !== 'number' || at < held.acceptedAt) return null;
    if (heldPickup(held, d)) return null;
    return { found: true, line: d.line, street: d.street, city: d.city,
             state: d.state || null, zip: d.zip || null, asked: false,
             labelled: 'dropoff', singleCardOnly: null, planner: false, foot: true,
             screen: 'uber.planner', key: null,
             place: typeof d.place === 'string' ? d.place : null,
             stop: { name: null, expectedBy: d.expectedBy === undefined ? null : d.expectedBy },
             ms: null, at: at };
  }

  // Whether the trip's last stop (footDropoff) is new for this hold: said
  // once, as every unprompted planner candidate is (`said`).
  function saidOnce(st, c) {
    var seen = c.line + '|foot';
    if (st.said[seen]) return false;
    st.said[seen] = true;
    return true;
  }

  /* Whether a planner page proves, by itself, that the trip is ONE pickup and
   * ONE dropoff, so that the lone dropoff it shows (plannerLoneDropoff) may
   * be filed onto a held card whose legs read 0. The owner's read of 21 Oct,
   * 13:57, one Uber order held, carrying two on: the planner read whole with
   * its title scrolled off the top and the bar at the foot, "Pickup - 1
   * order" the first line of the read, its block, then "Dropoff - 1 order"
   * and the customer's door; the list was 'list', and the held card read
   * badly (legs 0, hasTotal false, multiOrder false), so `singleCardOnly`
   * refused it and the order kept the card's corner, no house number.
   *
   * This narrows the lone-dropoff rule's `card.legs === 1` for THIS page
   * shape only (dropoff(), rule 1), all of:
   *   - the page is unprompted (the caller asks), read whole, and `framed`
   *     (offer_parser.planner_framed): the first stop header of the read is
   *     a Pickup with only the title or furniture above it — no stop above
   *     it — and the foot on the screen, the bar or "Waybill";
   *   - the page's own stops, and the list it is read as, are exactly one
   *     Pickup of "1 order" then one Dropoff of "1 order", neither cut by a
   *     page edge nor header-lost (`partial`), nothing of no kind;
   *   - one order held, not an add-on trip's (`addOn`, `of`): sightingMany
   *     takes two and never asks this.
   * dropoff() still wants the card's `multiOrder` false and its legs a
   * number no more than 1. A press is the press's rule, and outranks() keeps
   * a pressed end over this as over any planner. */
  function oneTripStops(stops) {
    var s = stops || [];
    return s.length === 2 && s.every(function (x) { return x && !x.partial; })
      && s[0].kind === 'pickup' && s[0].orders === 1
      && s[1].kind === 'dropoff' && s[1].orders === 1;
  }

  function framedTrip(held, page, view) {
    if (!held || held.addOn || held.of || !page.framed) return false;
    return oneTripStops(page.stops) && oneTripStops(view.stops);
  }

  /* ---------- a batched Uber trip: one card, one Took, two doors -------------
   *
   * The owner's facts (17 and 19 Oct 2026): Uber sends BATCHED orders — ONE
   * offer card, one ✓ Took, two pickups and/or two dropoffs. 17 Oct: the card
   * named one store and one corner ("<Store A> (40 <St>) · <Cross> & <Cross>,
   * <Town>", the offer line said legs 1, multiOrder false), and the Trip
   * Planner after the Took listed two pickups and two dropoffs, the card's
   * corner the LAST dropoff's street. 19 Oct: one store, two dropoffs. The rig
   * held one order, plannerDestination said 'dropoffs' and filed nothing, and
   * nothing knew the trip had two doors. No snap of a batched card is on file,
   * so the CARD cannot yet be told for one (AUDITS.md, Open): the planner is
   * the only witness, and this asks it only where it can be believed.
   *
   * batchPlan(held, stops) → {end, endStop, drops, why}. A batch — `end` the
   * address of the trip's LAST door, `drops` every dropoff with street and town
   * as {line, name, expectedBy, key} — only when, all of them (the caller,
   * sighting(), has already asked for ONE order held, an unpressed read under
   * the title or its layout, the list seen whole and not short):
   *   - the hold is no add-on trip's (`addOn`, `of`): an add-on's planner is
   *     two orders' list, which attribute() files on cues ('an add-on');
   *   - the list has MORE than one dropoff (otherwise plannerDestination);
   *   - THE LAST DOOR is the dropoff with the latest "Expected by" — the
   *     order Uber drives them in; a tie goes to the one on the card's street
   *     (cardStreets) when exactly one is, else the last on the screen, which
   *     is also the answer when any dropoff printed no time;
   *   - that last one has its street and town read ('address' otherwise: the
   *     order waits, a later read may have them); an earlier one without is
   *     left off `drops` and does not stop the batch;
   *   - the CARD's end is one of them (cardEndOk): its corner or door names
   *     the street of at least one dropoff on the list. One it names none of
   *     is 'card end elsewhere' — the list may hold an order the driver took
   *     on the phone with no ✓ Took, and its door would become this order's
   *     end. A card that printed no street ("Customer dropoff", a town) is no
   *     witness either way: 'no card street', and nothing is batched.
   * `why` is the refusal, said on /api/status as `batchWhy`. */
  var BATCH_STREET_WORDS = /^(st|street|rd|road|dr|drive|ln|lane|ave|av|avenue|blvd|bivd|boulevard|ct|court|way|pkwy|pky|parkway|cir|circle|pl|place|trl|trail|ter|terrace|hwy|highway|sq|square|loop|run|path|pass|row|xing|crossing|pt|point|walk|trce|trace|cv|cove|n|s|e|w|ne|nw|se|sw|north|south|east|west|northeast|northwest|southeast|southwest)$/;

  // A street's name with its house number, its type and its directions gone:
  // "40 Bramble Rd NW" and "Bramble Road" are both "bramble". "Bivd" is the
  // reader's i/l slip of "Blvd" (offer_parser's STREET_WORD takes it too): the
  // owner's held card of 20 Oct printed "<Name> Creek Bivd, Marietta". Null for text
  // with no street word or house number in it, which is a town, not a street.
  function streetCore(text) {
    var ws = String(text || '').toLowerCase().replace(/['’]/g, '')
      .split(/[^a-z0-9]+/).filter(Boolean);
    var typed = ws.some(function (w) { return BATCH_STREET_WORDS.test(w); })
      || /^\d+$/.test(ws[0] || '');
    var core = ws.filter(function (w, i) {
      return !(i === 0 && /^\d+[a-z]?$/.test(w)) && !BATCH_STREET_WORDS.test(w);
    }).join(' ');
    return typed && core ? core : null;
  }

  // The streets the card's end names: its corner's two ("A Rd & B St, Town")
  // or its door's one, before the town.
  function cardStreets(text) {
    if (typeof text !== 'string') return [];
    return text.split(',')[0].split(/\s*(?:&|\band\b|\bat\b|\/)\s*/i)
      .map(streetCore).filter(Boolean);
  }

  // The card's own end as the driver took it: what it printed (seenAs, kept
  // whatever a ⌖ later wrote over `dropoff`), else the hold's end while the
  // card still gives it.
  function cardEndOf(held) {
    if (held && held.seenAs && typeof held.seenAs.dropoff === 'string') return held.seenAs.dropoff;
    var f = held && held.fields && held.fields.dropoff;
    if (f && f.from === 'card') return f.value;
    return held && !held.dropoffScanned && typeof held.dropoff === 'string' ? held.dropoff : null;
  }

  // Minutes past midnight, unwrapped across it: on a trip that runs past
  // twelve, 11:50 PM comes before 12:10 AM.
  function byKeys(drops) {
    var ts = drops.map(function (s) { return s.expectedBy; });
    if (!ts.every(function (t) { return typeof t === 'number' && isFinite(t); })) return null;
    var span = Math.max.apply(null, ts) - Math.min.apply(null, ts);
    return span > 720 ? ts.map(function (t) { return t < 720 ? t + 1440 : t; }) : ts;
  }

  function batchPlan(held, stops) {
    var out = { end: null, endStop: null, drops: [], why: null };
    var drops = headed(stops).filter(function (s) { return s.kind === 'dropoff'; });
    if (drops.length < 2) { out.why = 'one dropoff'; return out; }
    if (!held || held.addOn || held.of) { out.why = 'an add-on'; return out; }
    var streets = cardStreets(cardEndOf(held));
    var onCard = function (s) {
      var c = streetCore(s.street);
      return !!c && streets.indexOf(c) !== -1;
    };
    // The last door: the latest time, a tie to the card's street, else the
    // last on the screen.
    var keys = byKeys(drops);
    var last = drops[drops.length - 1];
    if (keys) {
      var top = Math.max.apply(null, keys);
      var tied = drops.filter(function (s, i) { return keys[i] === top; });
      var mine = tied.filter(onCard);
      last = mine.length === 1 ? mine[0] : tied[tied.length - 1];
    }
    if (!(last.street && last.city)) { out.why = 'address'; return out; }
    if (!streets.length) { out.why = 'no card street'; return out; }
    if (!drops.some(onCard)) { out.why = 'card end elsewhere'; return out; }
    out.end = addressOf(last);
    out.endStop = last;
    out.drops = drops.filter(function (s) { return s.street && s.city; }).map(function (s) {
      return { line: addressOf(s).line, name: s.name || null,
               expectedBy: typeof s.expectedBy === 'number' ? s.expectedBy : null,
               key: keyOf(s) };
    });
    return out;
  }

  /* Why the planner gave the order in the car no batch, for /api/status's
   * `batchWhy`: the last refusal batchPlan said for THIS hold, or null. */
  function batchWhy(st, held) {
    var b = st && st.batchWhy;
    return b && held && b.holdId === holdIdOf(held) ? b.why : null;
  }

  /* ---------- the Trip Planner: several pages --------------------------------
   *
   * A stop's key is its kind, name and time, `kind|name|expectedBy`: what two
   * pages of one list both print for the same stop. A stop with neither a
   * name nor a time has no key — two such stops would match on the kind
   * alone — and nor does the stop a page begins in the middle of, which has
   * no kind.
   *
   * HOW LONG A PAGE WAITS FOR ITS NEIGHBOUR: STITCH_MS, 60 s. CHOSEN, NOT
   * MEASURED — no file on this rig holds two pages of one planner yet. It is
   * twice SCREEN_AUTO_HOT (rpi/scan_pi.py, 30 s), the spacing of the
   * unpressed reads while the heat guard is on, so the read that follows a
   * scroll can still reach the page before it when the Pi is hot. It was
   * twice SCREEN_AUTO_EVERY (10 s), 20 s, and with the guard on two unpressed
   * pages are never nearer than 30 s: replayed at that spacing, the five
   * fixture sequences that stitch (tests/fixtures/sequences.json) all filed
   * the card's end in place of the planner's. rpi/test_lint.py holds the two
   * constants together.
   *
   * The longer window does not loosen what a stitch needs. Time is the
   * weakest of the guards: two pages a minute apart join only when no other
   * screen was sighted for that app between them (a navigation screen — the
   * epoch), and when every position both show is the same stop by
   * kind, name and "Expected by", with one alignment only: another trip's
   * list would have to repeat this one's stops, names and times to join it.
   * And the planner from the trip before is refused on the Took (refuse()),
   * which the window does not touch.
   *
   * WHAT LIMITS A FALSE STITCH, all three required:
   *   - the same app;
   *   - no other screen type sighted, for that app, between the two pages —
   *     a navigation screen between means the planner was left and came back,
   *     and what is on it now may be another trip (`epoch` below). A sighting
   *     of no app at all is taken as a change of screen for every app;
   *   - an alignment the stops agree on: every position both pages show is
   *     the same key, or the one documented join, a header cut at the foot of
   *     one page (`partial: 'bottom'`) over the address block at the top of
   *     the next (`partial: 'top'`), whose times must be equal where both
   *     print one. Two alignments that both fit are no alignment.
   * Pages need not come in order: a list scrolled up links the same way.
   *
   * WHEN THE LIST COUNTS AS BOUNDED: when a page whose `page.top` is true
   * (the title with the first stop's header straight under it) sits at the
   * top of the linked list, and one whose `page.bottom` is true ("Waybill"
   * after its last header) sits at the foot. Each may be a different page. */
  var STITCH_MS = 60000;
  // How many planner pages are remembered at once. Chosen, not measured: at
  // one unpressed read every 10 s it is two minutes of planner.
  var PAGES_MAX = 12;
  // ...and how many refusals are kept for a test or a status line to read.
  var REFUSED_MAX = 20;

  function keyOf(s) {
    if (!s || !s.kind) return null;
    if (!s.name && (s.expectedBy === null || s.expectedBy === undefined)) return null;
    return s.kind + '|' + (s.name || '') + '|'
      + (s.expectedBy === null || s.expectedBy === undefined ? '' : s.expectedBy);
  }

  function timesAgree(a, b) {
    return a.expectedBy === null || a.expectedBy === undefined
      || b.expectedBy === null || b.expectedBy === undefined
      || a.expectedBy === b.expectedBy;
  }

  /* Whether `lower` fits under `upper` with its first stop at position `k` of
   * upper, and whether that fit rests on something (a shared key or the join). */
  function fits(upper, lower, k) {
    var rests = false;
    for (var j = 0; j < lower.length && k + j < upper.length; j++) {
      var a = upper[k + j], b = lower[j];
      var ka = keyOf(a), kb = keyOf(b);
      if (ka && kb) {
        if (ka !== kb) return false;
        rests = true;
      } else if (j === 0 && b.partial === 'top' && !b.kind) {
        // The address block a page begins with, under a stop the page above
        // showed whole or as a header cut at its foot.
        if (!a.kind || !timesAgree(a, b)) return false;
        if (a.partial === 'bottom' && k + j === upper.length - 1) rests = true;
      } else {
        return false;
      }
    }
    return rests;
  }

  /* Every position `lower` can sit at under `upper`. */
  function placements(upper, lower) {
    var out = [];
    for (var k = 0; k < upper.length; k++) if (fits(upper, lower, k)) out.push(k);
    return out;
  }

  function fuller(a, b) {
    return addressConf(b) > addressConf(a) ? b : a;
  }

  // One stop off two pages: the header's kind, count, name and time from the
  // one that printed a header, the address block whole from whichever read
  // more of it — never a street off one page and a town off the other.
  function mergeStop(a, b) {
    // A stop whose header the reader lost (`partial: 'header'`) has a kind
    // the parser gave it, not one the screen printed: a page that read the
    // header gives the header.
    var real = function (x) { return !!x.kind && x.partial !== 'header'; };
    var head = real(a) ? a : real(b) ? b : a.kind ? a : b;
    var addr = fuller(a, b);
    var out = {};
    Object.keys(a).concat(Object.keys(b)).forEach(function (k) { out[k] = null; });
    ['kind', 'orders', 'name', 'expectedBy', 'label'].forEach(function (k) {
      out[k] = head[k] !== undefined ? head[k] : null;
    });
    if ((out.expectedBy === null || out.expectedBy === undefined) && a !== head) {
      out.expectedBy = a.expectedBy === undefined ? null : a.expectedBy;
    }
    if ((out.expectedBy === null || out.expectedBy === undefined) && b !== head) {
      out.expectedBy = b.expectedBy === undefined ? null : b.expectedBy;
    }
    ADDRESS_KEYS.concat(['place']).forEach(function (k) {
      out[k] = addr[k] === undefined ? null : addr[k];
    });
    // (A stop kept header-lost always has its street and town, so the address
    // here has them too and the last arm never sees its 'header'.)
    out.partial = !real(a) && !real(b) && (a.partial === 'header' || b.partial === 'header')
      ? 'header'
      : out.kind && (out.street || out.city) ? null : (a.partial || b.partial || null);
    return out;
  }

  /* ---------- the planner the order in the car keeps: pages merged ----------
   *
   * The owner's snap of 24 Oct, 03:03-03:04: one Uber trip, ONE pickup
   * ("Pickup • 2 orders") and two dropoffs. Page 1 of the Trip Planner read
   * the pickup with its full door, the first customer's dropoff (by 3:23)
   * and the second's header and nothing else; the next reads, scrolled
   * further, were the second customer's dropoff alone and then both
   * dropoffs. server.js put each read's stops on the hold IN PLACE of the
   * last, so the pickup page 1 had seen — the restaurant's own door — was
   * gone from `holding.planner.stops` before anything asked the NucBox for
   * it, and the map's run had no pickup and no first door.
   *
   * So a planner read landing on a hold that already keeps a planner is
   * MERGED with what it keeps (server.js, the planner branch). `older` the
   * kept stops, `newer` this read's, `page` this read's page as its
   * sighting described it ({top, bottom}, pageOf) or null. Returns the
   * stops, copies, in the planner's order:
   *
   *   - A stop of the newer read and a kept one are the SAME stop by the
   *     key two pages of one list both print (keyOf: kind, name, "Expected
   *     by"), or the same kind and name with times that agree (one read
   *     lost the time), or the same kind and street line (sameStreet) with
   *     times and names that agree (one read lost the name). Once each.
   *   - The same stop is one stop: the header's words (kind, count, name,
   *     time, place, label) from the newer read where it printed them, else
   *     the kept; the address block WHOLE from whichever read more of it
   *     (addressConf, the newer on a tie) — never a street off one read and
   *     a town off the other, as mergeStop keeps a stitched stop.
   *   - A kept stop the newer read does not show is KEPT, where it was:
   *     after the nearest kept stop before it that is still in the list, or
   *     before the nearest after it. A read scrolled down shows the stops
   *     after the pickup without it, and that is the shape of the fault.
   *   - Two reads with no stop in common go in the order their times give
   *     (the kept read's last "Expected by" against the newer's first,
   *     past midnight unwrapped, as byKeys does), else the newer first when
   *     its page shows the list's top, else the kept first — a list is read
   *     scrolling down. Where they meet, a stop one of them read as a header
   *     with nothing under it (no name, no time, no street) and the other's
   *     first stop of the same kind are taken for one stop: the header cut at
   *     the foot of one page over the stop at the top of the next, the one
   *     join linked() makes too. The same between two stops in common,
   *     and there also two stops of one kind and one "Expected by" whose
   *     doors do not differ (slotJoins): one stop, its name misread.
   *   - A kept header with nothing read under it that is still not matched
   *     is left out: it has no name, no time and no door to show, ask or
   *     draw, and could be any stop.
   *   - A newer read that shows the list's TOP has the last word on what is
   *     above its first stop: kept stops that would sit before it are left
   *     out — a pickup swiped in the app, a door already delivered. One
   *     that shows its FOOT ("Waybill") the same below its last. A read
   *     whose page is not known (no sighting of it) leaves both.
   *
   * What this does NOT touch: which stop is the order's end (dropoff(),
   * batchPlan, the label and press rules decide that off the sightings, as
   * before — a page's stops on the hold are not where an end comes from),
   * and a pickup's visit: server.js's plannerVisits is handed the READ's
   * stops, not these, so "the list moved past it" is still the app's own
   * word off one read that shows the top. The merge lives on the hold, so a
   * new order (a Took, the hold going) starts with no planner, and a
   * different offer on the record forgets it as before (forgetPlanner).
   *
   * ...and a read that answers a ⌖ press merges too (`pressed`; the owner,
   * 24 Oct: "Would there be a way to have the scan button also merge?"). It
   * used to replace the kept stops, because the press forgot the planner
   * first, so a press on page 2 lost the pickup page 1 had read — the same
   * fault as above, by the button. The press no longer forgets, and its
   * read is merged by the same rules with ONE difference, PRESS PRECEDENCE:
   * for a stop both show, the pressed read's fields win wherever it read
   * them, its address block included whenever it read one (whole, as
   * always, but not by addressConf's fuller-wins: the driver pressed to have
   * this page read, and its door is the answer they asked for); the kept
   * field stands only where the pressed read has nothing. Stops the pressed
   * page does not show are kept, and its top or foot trims as an
   * unpressed read's does. */
  var PLANNER_COPY = ['kind', 'orders', 'name', 'expectedBy', 'place', 'label'];

  function headerOnly(s) {
    return !keyOf(s) && !s.street && !s.line && !s.city;
  }

  /* A planner name's own words: runs of three or more letters, lowercased,
   * apostrophes dropped ("Dave's" is "daves"). The owner's snaps of 28 Oct:
   * one customer read as "oe jonathan |.", "jonathan. ." and "y © jonathan."
   * and another as "ShaRhandaB" and "ShaRhandas." — the screen's edge, the
   * stop's icon and the initial's dot read as letters and marks round the
   * name — and compared whole, each reading was a stop of its own: the
   * panel listed "7 dropoffs" for a trip of two. The noise is short (one or
   * two letters, a mark); a name's own word is not ("Pat Q." is "pat"). */
  function nameWords(name) {
    return (typeof name === 'string' ? name.toLowerCase().replace(/['\u2019]/g, '') : '')
      .split(/[^a-z]+/).filter(function (w) { return w.length >= 3; });
  }

  // Two words of one name: the same, or one the other with a letter or two
  // more at its end (the initial run on, "sharhandab" for "sharhanda"), or,
  // five letters and more, one letter apart (a letter misread).
  function wordsAlike(x, y) {
    if (x === y) return true;
    var lo = x.length < y.length ? x : y, hi = x.length < y.length ? y : x;
    if (lo.length >= 4 && hi.length - lo.length <= 2 && hi.indexOf(lo) === 0) return true;
    if (lo.length >= 5 && hi.length - lo.length <= 1) {
      var i = 0;
      while (i < lo.length && lo[i] === hi[i]) i += 1;
      return lo.slice(i + (lo.length === hi.length ? 1 : 0)) === hi.slice(i + 1);
    }
    return false;
  }

  // Whether a stop's name says anything: a word of its own. A name read as
  // marks and a letter or two is no name, and clashes with none.
  function named(st) {
    return nameWords(st && st.name).length > 0;
  }

  // The same name, read twice: a word of one is alike a word of the other.
  // Two customers of one first name in one trip would read as one here; the
  // times (timesAgree) and the doors (sameStreet) are asked beside it.
  function sameName(a, b) {
    if (!a.name || !b.name) return false;
    if (norm(a.name) === norm(b.name)) return true;
    var wa = nameWords(a.name), wb = nameWords(b.name);
    return wa.some(function (x) { return wb.some(function (y) { return wordsAlike(x, y); }); });
  }

  function samePlannerStop(a, b) {
    if (!a || !b || !a.kind || a.kind !== b.kind) return false;
    var ka = keyOf(a), kb = keyOf(b);
    if (ka && kb && ka === kb) return true;
    if (!timesAgree(a, b)) return false;
    if (sameName(a, b)) return true;
    return sameDoorStop(a, b);
  }

  // The same kind on the same street with no clashing name: one stop WHATEVER
  // the times say. The app moves a stop's "Expected by" between reads (7:27 →
  // 7:32 as the run slips), and held to timesAgree the one customer was kept
  // twice (review of 27 Oct): the server's planAtOf found two of the end,
  // MV.heldDrops lost D1, the panel listed it twice. mergePlanner asks this
  // only after samePlannerStop has had every pair, so a stop whose times
  // agree is never taken by one that moved.
  function sameDoorStop(a, b) {
    if (!a || !b || !a.kind || a.kind !== b.kind) return false;
    var namesClash = named(a) && named(b) && !sameName(a, b);
    return !namesClash && sameStreet(a.line || a.street, b.line || b.street);
  }

  // How far apart two reads' "Expected by" may be and still be one stop by
  // its name alone (sameNameStop), in minutes. Chosen, not measured: the
  // owner's shift of 28 Oct, 20:36, read one restaurant's pickup due 8:41 and
  // then 8:42, no street on either read, and the hold kept the pickup twice.
  // A run slips a minute or two between reads; five is room for that and
  // still well under the spacing of two stops of one trip.
  var NAME_SLIP_MINUTES = 5;

  // A name's initial, the capital standing alone after a word ("Pat Q." is
  // Q), or null. sameName reads words of three letters and more, so "Pat Q."
  // and "Pat R." are alike there; for a stop matched by its name ALONE, with
  // its time moved, two initials that differ are two customers.
  function initialOf(name) {
    var m = /[A-Za-z]{3,}\s+([A-Z])(?![A-Za-z])/.exec(typeof name === 'string' ? name : '');
    return m ? m[1] : null;
  }

  // The same kind under the same name, its "Expected by" moved by a minute or
  // a few (NAME_SLIP_MINUTES) and no door to go by: one stop. Both names must
  // read (named) and be the one name (sameName), their initials must not
  // differ, and doors both reads have must be one street — so two customers
  // due the same minute under two names stay two (slotJoins' review of 27
  // Oct), and so do two of one first name at two doors. mergePlanner asks
  // this after samePlannerStop has had every pair, as sameDoorStop.
  function sameNameStop(a, b) {
    if (!a || !b || !a.kind || a.kind !== b.kind) return false;
    if (!named(a) || !named(b) || !sameName(a, b)) return false;
    var ia = initialOf(a.name), ib = initialOf(b.name);
    if (ia && ib && ia !== ib) return false;
    var timed = function (x) { return typeof x.expectedBy === 'number' && isFinite(x.expectedBy); };
    if (!timed(a) || !timed(b)) return false;
    var d = Math.abs(a.expectedBy - b.expectedBy) % 1440;
    if (Math.min(d, 1440 - d) > NAME_SLIP_MINUTES) return false;
    var da = a.line || a.street, db = b.line || b.street;
    return !(da && db && !sameStreet(da, db));
  }

  // Whether a header with nothing under it and a stop beside it can be one
  // stop where two reads meet.
  function headerJoins(a, b) {
    return !!a && !!b && a.kind === b.kind && (headerOnly(a) || headerOnly(b))
      && timesAgree(a, b) && !(named(a) && named(b) && !sameName(a, b));
  }

  // Two stops at one place in the list — beside the same stop in common, on
  // the same side — of one kind and one "Expected by", whose doors do not
  // differ and whose names do not clash (one read lost it): one stop. Two
  // names are two customers, though due at the same minute in the same slot
  // (review of 27 Oct: "Mara T." kept and "Jules K., 9 Elm Dr" read were
  // made one, and Mara's stop was gone). The newer read's name stands.
  function slotJoins(a, b) {
    var timed = function (x) { return typeof x.expectedBy === 'number' && isFinite(x.expectedBy); };
    if (!a || !b || a.kind !== b.kind || !timed(a) || !timed(b)
        || a.expectedBy !== b.expectedBy) return false;
    if (named(a) && named(b) && !sameName(a, b)) return false;
    var da = a.line || a.street, db = b.line || b.street;
    return !(da && db && !sameStreet(da, db));
  }

  // Whether a stop read any of its address block.
  function hasAddress(s) {
    return ADDRESS_KEYS.some(function (k) { return !!s[k]; });
  }

  function mergePlannerStop(kept, read, pressed) {
    var out = Object.assign({}, kept, read);
    // Only the fields either read carries: a stop merged with itself is the
    // stop it was, byte for byte, so a planner read that changes nothing
    // writes nothing (server.js plannerVisits' `heldWas`).
    var has = function (k) { return k in kept || k in read; };
    PLANNER_COPY.forEach(function (k) {
      if (!has(k)) return;
      var v = read[k] !== undefined && read[k] !== null ? read[k] : kept[k];
      out[k] = v === undefined ? null : v;
    });
    // The fuller block, or — a pressed read's (press precedence) — the
    // pressed read's own whenever it read one.
    var addr = pressed ? (hasAddress(read) ? read : kept)
      : addressConf(kept) > addressConf(read) ? kept : read;
    ADDRESS_KEYS.forEach(function (k) {
      if (has(k)) out[k] = addr[k] === undefined ? null : addr[k];
    });
    // ...and the order a pickup was given (server.js ownPickups' `of`): this
    // read's answer where it gave one, else the kept.
    if (!read.of && kept.of) out.of = kept.of;
    return out;
  }

  // The first and last "Expected by" of a list, as minutes, or null.
  function firstTime(stops) {
    for (var i = 0; i < stops.length; i++) {
      if (typeof stops[i].expectedBy === 'number' && isFinite(stops[i].expectedBy)) {
        return stops[i].expectedBy;
      }
    }
    return null;
  }

  function lastTime(stops) {
    return firstTime(stops.slice().reverse());
  }

  function mergePlanner(older, newer, page, pressed) {
    pressed = pressed === true;
    var obj = function (s) { return !!s && typeof s === 'object'; };
    var news = (Array.isArray(newer) ? newer : []).filter(obj)
      .map(function (s) { return Object.assign({}, s); });
    var olds = (Array.isArray(older) ? older : []).filter(obj);
    if (!olds.length) return news;
    // Which newer stop each kept one is (-1 for none), in order.
    var match = olds.map(function () { return -1; });
    var used = news.map(function () { return false; });
    olds.forEach(function (o, i) {
      for (var j = 0; j < news.length; j++) {
        if (!used[j] && samePlannerStop(o, news[j])) { match[i] = j; used[j] = true; return; }
      }
    });
    // ...then one whose "Expected by" moved, by its door (sameDoorStop), or
    // by a minute or a few under its name (sameNameStop).
    olds.forEach(function (o, i) {
      if (match[i] !== -1) return;
      for (var j = 0; j < news.length; j++) {
        if (!used[j] && sameDoorStop(o, news[j])) { match[i] = j; used[j] = true; return; }
      }
    });
    olds.forEach(function (o, i) {
      if (match[i] !== -1) return;
      for (var j = 0; j < news.length; j++) {
        if (!used[j] && sameNameStop(o, news[j])) { match[i] = j; used[j] = true; return; }
      }
    });
    // ...a header with nothing under it, beside a stop in common, is the stop
    // the other read shows there — and so is one in the same slot due at the
    // same minute (slotJoins).
    olds.forEach(function (o, i) {
      if (match[i] !== -1) return;
      var before = i > 0 ? match[i - 1] : -1;
      var after = i + 1 < olds.length ? match[i + 1] : -1;
      var j = before !== -1 ? before + 1 : after !== -1 ? after - 1 : -1;
      if (j >= 0 && j < news.length && !used[j]
          && (headerJoins(o, news[j]) || slotJoins(o, news[j]))) {
        match[i] = j; used[j] = true;
      }
    });
    // The list: the newer read's stops, each the merged stop where a kept one
    // is the same; `fromNew` marks them for the trims below.
    var list = news.map(function (s, j) {
      var i = match.indexOf(j);
      return { s: i === -1 ? s : mergePlannerStop(olds[i], s, pressed), fromNew: true, old: i };
    });
    var common = match.some(function (j) { return j !== -1; });
    if (!common) {
      // No stop in common: the two reads side by side, in the order their
      // times give, else the newer first when it shows the list's top, and
      // where they meet a header and the stop beside it are one.
      var lo = lastTime(olds), fn = firstTime(news);
      var oldFirst = !(page && page.top);
      if (lo !== null && fn !== null) {
        var gap = fn - lo;
        if (gap > 720) gap -= 1440;
        if (gap < -720) gap += 1440;
        oldFirst = gap >= 0;
      }
      var a = oldFirst ? olds : news, b = oldFirst ? news : olds;
      var joined = a.length && b.length && headerJoins(a[a.length - 1], b[0]);
      var keptList = olds.map(function (s, i) { return { s: s, fromNew: false, old: i }; });
      if (joined) {
        // The header and its stop as one, standing where the newer read's is.
        var oi = oldFirst ? olds.length - 1 : 0;
        var nj = oldFirst ? 0 : news.length - 1;
        list[nj] = { s: mergePlannerStop(olds[oi], news[nj], pressed), fromNew: true, old: oi };
        keptList.splice(oi, 1);
      }
      list = oldFirst ? keptList.concat(list) : list.concat(keptList);
    } else {
      // Each kept stop not in common, after the nearest kept stop before it
      // still in the list, else before the nearest after it.
      olds.forEach(function (o, i) {
        if (match[i] !== -1) return;
        var at = -1, k;
        for (k = 0; k < list.length; k++) {
          if (list[k].old !== -1 && list[k].old < i && (at === -1 || list[k].old > list[at].old)) {
            at = k;
          }
        }
        var entry = { s: o, fromNew: false, old: i };
        if (at !== -1) { list.splice(at + 1, 0, entry); return; }
        for (k = 0; k < list.length; k++) if (list[k].old > i) break;
        list.splice(k, 0, entry);
      });
    }
    // A read that shows the top has the last word above its first stop, and
    // one that shows the foot below its last; one that shows both (the top
    // and the Waybill under the last stop) is the whole list, and no kept
    // stop it does not show stands (the matched ones are merged above, press
    // precedence and all).
    var whole = !!(page && page.top && page.bottom);
    var firstNew = -1, lastNew = -1;
    list.forEach(function (e, k) {
      if (!e.fromNew) return;
      if (firstNew === -1) firstNew = k;
      lastNew = k;
    });
    return list.filter(function (e, k) {
      if (e.fromNew) return true;
      if (whole || headerOnly(e.s)) return false;
      if (page && page.top && firstNew !== -1 && k < firstNew) return false;
      if (page && page.bottom && lastNew !== -1 && k > lastNew) return false;
      return true;
    }).map(function (e) { return e.fromNew ? e.s : Object.assign({}, e.s); });
  }

  /* `upper` and `lower` as one list, lower's first stop at upper's `k`. Each
   * side carries {stops, top, bottom}: whether a page with that end sits at
   * this side's own start or foot. */
  function join(upper, lower, k) {
    var stops = upper.stops.slice();
    lower.stops.forEach(function (s, j) {
      stops[k + j] = k + j < upper.stops.length ? mergeStop(upper.stops[k + j], s) : s;
    });
    var endU = upper.stops.length, endL = k + lower.stops.length;
    var end = Math.max(endU, endL);
    return {
      stops: stops,
      top: upper.top || (k === 0 && lower.top),
      bottom: (endU === end && upper.bottom) || (endL === end && lower.bottom)
    };
  }

  function pageView(p) {
    return { stops: p.stops.map(function (s) { return Object.assign({}, s); }),
             top: p.top, bottom: p.bottom };
  }

  /* The linked list the newest page belongs to: the pages that join it, each
   * within STITCH_MS of one already in, same app, same epoch, one placement
   * only. Returns {view, pages}. */
  function linked(pages, newest) {
    var inside = [newest];
    var view = pageView(newest);
    var grew = true;
    while (grew) {
      grew = false;
      for (var i = 0; i < pages.length; i++) {
        var p = pages[i];
        if (inside.indexOf(p) !== -1 || p.app !== newest.app || p.epoch !== newest.epoch) {
          continue;
        }
        var near = inside.some(function (q) { return Math.abs(q.at - p.at) <= STITCH_MS; });
        if (!near) continue;
        var pv = pageView(p);
        // Where p's first stop sits against the list's: +k with p under the
        // list from its k-th stop, -k with the list under p. The two searches
        // both find a page that starts level with the list (0), which is one
        // alignment, not two.
        var offsets = [];
        placements(view.stops, pv.stops).forEach(function (k) {
          if (offsets.indexOf(k) === -1) offsets.push(k);
        });
        placements(pv.stops, view.stops).forEach(function (k) {
          if (offsets.indexOf(-k) === -1) offsets.push(-k);
        });
        if (offsets.length !== 1) continue;
        view = offsets[0] >= 0 ? join(view, pv, offsets[0]) : join(pv, view, -offsets[0]);
        inside.push(p);
        grew = true;
      }
    }
    return { view: view, pages: inside };
  }

  /* ---------- the assembler's own state --------------------------------------
   *
   * Process memory, like the server's slot: the pages seen, per app the epoch
   * (bumped by every other screen type), the pending pool, what was refused,
   * and the unprompted candidates already decided for this hold. */
  function fresh() {
    return { pages: [], epoch: {}, holdId: null, said: {}, refused: [], verdicts: [],
             views: [], unowned: [] };
  }

  function holdIdOf(h) {
    return h ? String(h.id) + '@' + String(h.acceptedAt) : null;
  }

  function refuse(st, page, why) {
    st.refused.push({ at: page.at, why: why });
    if (st.refused.length > REFUSED_MAX) st.refused.shift();
  }

  /* The pending pool: the planner pages read while this hold is held that
   * have filed nothing and been refused nothing — a list not yet seen whole,
   * a stop not yet read whole. Kept until the hold ends, retried on each new
   * sighting and at a Took. */
  function pending(st) {
    return st.pages.filter(function (p) { return p.pending; })
      .map(function (p) { return { at: p.at, why: p.why }; });
  }

  /* The hold changed — a Took, a Drop, an order run out. The pool is retried
   * against the new hold, where every page read before its Took is about the
   * order before and is refused; and the unprompted candidates decided for the
   * old hold are forgotten, so the new one is asked afresh. */
  function took(st, held) {
    // A list of orders is the orders it holds: one is that one, none is none,
    // and two are one hold whose pages run from the OLDER card.
    if (Array.isArray(held)) {
      if (held.length < 2) return took(st, held[0] || null);
      var ids = held.map(holdIdOf).join(' ');
      if (ids === st.holdId) return;
      var since = Math.min.apply(null, held.map(function (o) { return o.acceptedAt; }));
      st.holdId = ids;
      st.said = {};
      st.pages = st.pages.filter(function (p) {
        if (p.at >= since) return true;
        if (p.pending) refuse(st, p, 'before the Took');
        return false;
      });
      return;
    }
    var id = holdIdOf(held);
    if (id === st.holdId) return;
    st.holdId = id;
    st.said = {};
    st.pages = st.pages.filter(function (p) {
      if (held && p.at >= held.acceptedAt) return true;
      if (p.pending) refuse(st, p, held ? 'before the Took' : 'the hold ended');
      return false;
    });
  }

  /* One sighting (rpi/scan_pi.py, sighting()): {at, asked, whole, titled, laidOut, framed, app,
   * screen, page: {top, bottom}, stops, orderCount, keep}. Returns
   * {candidates: [dropoff-shaped], why, at} — `why` the reason the planner
   * this page belongs to gives the order no end, for the planner line that
   * follows it (see verdictFor) — and leaves the page in the pool.
   *
   * ONE PAGE ALONE is decided exactly as the scanner decided it:
   *   - read under a press, whole: its one dropoff on a list it shows whole is
   *     the press's answer, `asked`;
   *   - read unpressed, whole, under the "Trip Planner" title (the read the
   *     scanner makes on its own while an order is held): the same address,
   *     label-proven, from 'planner'; and on a list whose end it does not show,
   *     the lone dropoff, `singleCardOnly`;
   *   - any other screen read whole and unpressed while an order is held:
   *     its address under a "Deliver to" or "Dropoff" label, as a navigation
   *     destination (navCandidate);
   *   - anything else: nothing.
   * SEVERAL PAGES, linked as above, with an order held and every page read
   * after its Took: the list's one dropoff once the list is bounded, from
   * 'planner'; else, under a title somewhere on it, the lone dropoff.
   * A card-box read (not whole) with a stop on it is ONE page alone, decided
   * by the same rules and never pooled (see below; the owner's 26 Oct shift).
   *
   * An unprompted candidate already decided for this hold is not offered
   * again: the scanner's `dropoff_said` used to stop a planner up for a whole
   * delivery from being filed every ten seconds, and the planner's address
   * no longer passes through it. */
  function sighting(st, held, s, now) {
    // The orders in the car as a list: one is decided exactly as below, two
    // by sightingMany.
    if (Array.isArray(held)) {
      return held.length < 2 ? sighting(st, held[0] || null, s, now)
        : sightingMany(st, held, s, now);
    }
    var out = { candidates: [], why: null, at: s && typeof s.at === 'number' ? s.at : null };
    if (!s || typeof s !== 'object') return out;
    took(st, held);
    var app = typeof s.app === 'string' ? s.app : null;
    if (s.screen !== 'uber.planner') {
      if (app) st.epoch[app] = (st.epoch[app] || 0) + 1;
      else Object.keys(st.epoch).forEach(function (a) { st.epoch[a] += 1; });
      var nav = navCandidate(st, held ? [held] : [], s, out.at === null ? now : out.at);
      if (nav) out.candidates.push(nav);
      return out;
    }
    // The trip's last stop, its header cropped off (footDropoff), off a
    // card-box read: no page — it saw part of the screen — but the foot
    // under it says which stop it is.
    var foot = footDropoff(held, s, out.at === null ? now : out.at);
    // A CARD-BOX READ OF THE PLANNER IS DECIDED AS A WHOLE-SCREEN PAGE IS, when
    // the planner's grammar read a stop on it (pageStops). The owner, after the
    // 26 Oct shift: order #7's door was on a card-box read 44 s after the Took
    // ("Dropoff • 1 order", the customer, the door, the bar), find_planner read
    // it as the dropoff it is, and this function dropped it here unread
    // because the read was not whole — "a card-box read is no page: it saw
    // part of the screen". A whole-screen read sees part of the list as often:
    // the planner scrolls, and every rule below already asks what the page
    // proves (the title or its layout, the list's two ends, the trip's last
    // stop over the bar) rather than how much glass the read covered. So the
    // box's page is judged by those same rules, one page alone, with the same
    // rules on which order it belongs to (one order held here; two go to
    // sightingMany, which still takes whole reads only).
    //
    // Two things the box cannot say and is not asked: `framed` — the top of a
    // box read is the box's edge, not the list's, so "nothing above the
    // Pickup header" proves nothing there; and the pool — a box read comes
    // every second or two the screen moves, and pooled it would push the
    // whole-screen pages a stitch needs out of PAGES_MAX, and the planner
    // line's verdicts with them. So a box page is never pooled, never stitched,
    // never pending, refused or a verdict: it files on its own or not at all,
    // and a read of no stop is as before (its foot, footDropoff, or nothing).
    var boxed = s.whole !== true;
    if (!pageStops(s.stops)) {
      if (boxed && foot && saidOnce(st, foot)) out.candidates.push(foot);
      return out;
    }
    var page = { at: out.at === null ? now : out.at, app: app,
                 epoch: st.epoch[app] || 0, asked: s.asked === true,
                 titled: s.titled === true,
                 // The layout standing in for a title misread: see below.
                 laidOut: s.laidOut === true,
                 // A Pickup header opening the read, the foot under it: see
                 // framedTrip. Never off the card box (above).
                 framed: !boxed && s.framed === true,
                 top: !!(s.page && s.page.top), bottom: !!(s.page && s.page.bottom),
                 stops: s.stops.filter(function (x) { return x && typeof x === 'object'; }),
                 pending: false, why: null, box: boxed };
    if (!boxed) {
      st.pages.push(page);
      while (st.pages.length > PAGES_MAX) st.pages.shift();
    }

    // Pages for linking: with a hold, only those read after its Took.
    var pool = held ? st.pages.filter(function (p) { return p.at >= held.acceptedAt; })
      : [page];
    var run = pool.indexOf(page) === -1 ? { view: pageView(page), pages: [page] }
      : linked(pool, page);
    var many = run.pages.length > 1;
    var view = many ? run.view : pageView(page);
    var verdict = plannerDestination(view.stops, view.top && view.bottom);
    // A list seen whole with ONE order in the car is remembered for growth
    // too, as sightingMany remembers one with two: it is the "before" an Uber
    // add-on's Took grows by one dropoff (attribute, growthVote). Kept only
    // from sightingMany, the first list with the add-on in it had nothing to
    // grow FROM — no view is ever taken between two Tooks while one order is
    // all there is — and the original's own door, read again beside the
    // add-on's, had no cue at all. Changes nothing filed with one order.
    if (held && !boxed && view.top && view.bottom && !listShort(view.stops)) {
      noteView(st, app, page.at, view.stops);
    }
    // A PLANNER BY ITS LAYOUT, title or not: the owner's decision (16 Oct),
    // after the single trip's planner was read with its title as "ny. mS" and
    // its one dropoff never filed. `laidOut` is offer_parser.planner_laid_out:
    // a Pickup and a Dropoff header each with its "Expected by", "View
    // details" and the "Stop New Requests" bar. It stands in for the title
    // where an UNPRESSED page is asked for one — never for a press, and never
    // to bound a list (the page's `top` still needs the title).
    var titled = run.pages.some(function (p) { return p.titled || p.laidOut; });
    var cand = null;
    if (!many) {
      if (page.asked) {
        if (verdict.address) {
          cand = candidate(verdict.address, verdict.stop, page, true, false);
          // ...with what says whose it is, for a press made while a card is
          // being screened (pressBetween): the app, and the store when the
          // list is ONE pickup and ONE dropoff, as plannerCandidates gives
          // them with two orders held.
          cand.app = page.app;
          var one = headed(view.stops);
          var shops = one.filter(function (x) { return x.kind === 'pickup'; });
          cand.store = shops.length === 1 && one.length === 2 ? (shops[0].name || null) : null;
        }
      } else if (page.titled || page.laidOut) {
        if (verdict.address) cand = candidate(verdict.address, verdict.stop, page, false, false);
        else if (verdict.why === 'list') {
          var lone = plannerLoneDropoff(view.stops);
          if (lone) cand = candidate(lone, verdict.stop, page, false, true);
        }
      }
    } else if (verdict.address) {
      cand = candidate(verdict.address, verdict.stop, page, false, false);
    } else if (verdict.why === 'list' && titled) {
      var lone2 = plannerLoneDropoff(view.stops);
      if (lone2) cand = candidate(lone2, verdict.stop, page, false, true);
    }
    // ...and a single trip's dropoff whose header the reader lost, on the
    // held card's own street (lostHeaderDropoff; the owner's read of 20 Oct).
    // Unprompted only: a press's answer is the press's rule. (Its verdict is
    // always 'list': the stop's count is null, so its one pickup's "1 order"
    // makes the list short, seen whole or not.)
    if (!cand && held && !page.asked) {
      var lost = lostHeaderDropoff(held, view.stops);
      if (lost) cand = candidate(lost, verdict.stop, page, false, true);
    }
    // ...and a lone dropoff off a page that frames the whole trip itself
    // (framedTrip; the owner's read of 21 Oct, 13:57): dropoff() then takes
    // a held card whose legs read 0 as well as 1.
    if (cand && cand.singleCardOnly && !page.asked && framedTrip(held, page, view)) {
      cand.framed = true;
    }
    // A BATCHED TRIP (batchPlan): the owner's decision of 19 Oct 2026. With
    // ONE order held (`held` here is one: sightingMany takes two), an
    // unpressed read under the title or its layout, the list seen whole —
    // top and foot, on one page or stitched, never a list running off the
    // screen — and not short, MORE than one dropoff is that order's trip:
    // its end the LAST door, every door on `batch`. A press's answer stays
    // the press's rule (one dropoff or nothing): the driver asked about the
    // screen, not about the trip.
    var batched = false;
    if (!cand && held && verdict.why === 'dropoffs' && !page.asked && titled
        && view.top && view.bottom && !listShort(view.stops)) {
      var plan = batchPlan(held, view.stops);
      st.batchWhy = { holdId: holdIdOf(held), why: plan.why };
      if (plan.end) {
        cand = candidate(plan.end, plan.endStop, page, false, false);
        cand.batch = { drops: plan.drops };
        batched = true;
      }
    }
    // ...and, read whole, the trip's last stop under a cropped header
    // (footDropoff) where nothing above gave the order an end — or where
    // what did is a lone dropoff rule 1 refuses (loneTaken) only because the
    // card's legs went unread: legs 0, one order. A card that SAID two legs
    // or two orders, or no card, is a refusal on evidence and stands.
    var unread = !!held && !!held.card && held.card.multiOrder === false
      && held.card.legs === 0;
    var refused = !!cand && cand.singleCardOnly === true && unread && !loneTaken(held, cand);
    if ((!cand || refused) && foot && saidOnce(st, foot)) out.candidates.push(foot);
    if (cand && many) cand.pages = run.pages.length;
    // The reads it was made from, so one that files can take them out of the
    // pool (file()): a lone dropoff waits there until it is known to be kept.
    if (cand) cand.pageAts = run.pages.map(function (p) { return p.at; });
    // Its one pickup, read whole on a list seen whole, rides with it.
    if (cand && view.top && view.bottom) {
      var picks = headed(view.stops).filter(function (x) { return x.kind === 'pickup'; });
      if (picks.length === 1 && picks[0].street && picks[0].city) {
        cand.pickupAddr = Object.assign(addressOf(picks[0]), { key: keyOf(picks[0]) });
      }
    }
    var deduped = false;
    // ...and every reading of a planner stop counted toward its most read
    // (plannerVote), before the dedupe; the winner gets past it.
    if (cand && !cand.batch && plannerVote(held, cand)) cand.vote = true;
    if (cand && !cand.asked) {
      // (A framed one is its own: one refused unframed must not hide it.)
      var seen = cand.line + (cand.singleCardOnly ? '|lone' : '')
        + (cand.framed ? '|framed' : '')
        + (cand.batch ? '|batch' + cand.batch.drops.length : '');
      if (st.said[seen] && !cand.vote) { cand = null; deduped = true; }
      else st.said[seen] = true;
    }
    if (cand) out.candidates.push(cand);
    // ...and a batch filed is no 'dropoffs' for the planner line: the order
    // has its end, so the panel's "end not guessed" goes with it.
    var why = batched ? null : verdict.why;
    out.why = why;
    // The pool. With an order held, every page of this run read after its
    // Took waits for the page that may complete it — unless the run gave its
    // address (a lone dropoff still waits: a later page may bound the list),
    // or has two dropoffs, which no page can undo.
    var consumed = deduped || (!!cand && !cand.singleCardOnly);
    // (A box page is not in the pool, and keeps none of its bookkeeping.)
    if (boxed) return out;
    run.pages.forEach(function (p) {
      var was = p.pending;
      p.pending = false;
      if (!held) return;
      if (p.at < held.acceptedAt) {
        if (p === page && !cand) refuse(st, p, 'before the Took');
        return;
      }
      if (why === 'dropoffs') {
        if (was || p === page) refuse(st, p, 'dropoffs');
        p.why = 'dropoffs';
        return;
      }
      if (consumed) {
        p.why = null;
        return;
      }
      p.pending = true;
      p.why = verdict.why || (verdict.address ? 'not titled' : 'no dropoff');
    });
    st.verdicts.push({ at: page.at, why: why });
    while (st.verdicts.length > PAGES_MAX) st.verdicts.shift();
    return out;
  }

  function candidate(address, stop, page, asked, lone) {
    return { found: true, line: address.line, street: address.street, city: address.city,
             state: address.state, zip: address.zip, asked: asked,
             labelled: asked ? null : 'dropoff', singleCardOnly: lone ? true : null,
             planner: true, screen: 'uber.planner', key: keyOf(stop),
             // The stop's place line (the hotel layout), for file().
             place: stop && typeof stop.place === 'string' ? stop.place : null,
             stop: stop ? { name: stop.name || null,
                            expectedBy: stop.expectedBy === undefined ? null : stop.expectedBy }
               : null,
             ms: null, at: page.at };
  }

  /* ---------- a navigation screen, read whole without a press ----------------
   *
   * The driver's ask: while an order is held, the rig reads the navigation
   * screen and the "Deliver to" screen on its own, as it reads the planner,
   * and the destination fills in with no ⌖. The scanner makes the read
   * (rpi/scan_pi.py, auto_read_for and `screen_auto`) and only TYPES what it
   * saw: the one address the frame gave, a dropoff where it sits under a
   * "Deliver to" or "Dropoff" label in its own block (sighting_stops,
   * offer_parser.address_under_dropoff). This decides whether it is a
   * candidate at all; dropoff() then files it as `nav` by outranks().
   *
   * A candidate only when, all of them:
   *   - an order is held — `orders` is every order in the car;
   *   - the read was of the whole screen and nobody pressed: a press's answer
   *     is the dropoff line's, and a card-box read is the dropoff line's too
   *     (rank `label`);
   *   - the screen is not Uber's navigation to a store (uber.pickupNav):
   *     'a pickup screen'; nor DoorDash's place popup (dd.placePopup), which
   *     is the card's being screened: 'a place popup';
   *   - the address is typed a dropoff. Under a Pickup label it is 'a pickup';
   *     under no label at all it is 'no label' — AUDITS.md's Settled rule that
   *     an address nobody asked for and no label proves is not a destination.
   *     The opened navigation sheet's address over "Dropoff type", with the
   *     customer's name above it, is typed a dropoff by the scanner
   *     (offer_parser.sheet_dropoff): the owner's decision of 14 Oct 2026
   *     that the sheet's label, read upwards, is a label;
   *   - it is not a pickup of ANY order in the car by any word on record
   *     (heldPickup): 'a pickup'. With two orders the other one's store is as
   *     wrong an end as this one's.
   * Each refusal is kept (st.refused) with its reason. And once per address
   * for this hold, as a planner's is: a navigation screen sits in front of
   * the camera for a whole delivery and is read every ten seconds.
   *
   * WHAT THE 12 OCT SHIFT SAYS IT WILL FIND, measured by replaying its 1,237
   * `screen` rows through rpi/scan_pi.py's screen_address and sighting() and
   * this, each as if it were the whole-screen read, against the orders the
   * driver ticked. None of the 179 typed uber.nav carries an address under
   * "Deliver to" or "Dropoff": the 36 with "Deliver to" print a name after
   * it. 18 show the opened sheet, and 10 of those read as one (name, a street
   * with a house number, a town); the other 8 lost the number, the name or
   * half the town. 18 ticked orders were held while a navigation screen was
   * read, 4 of them showed a readable sheet, and all 4 were given their
   * destination this way: 4 of 18. One of the 4 read its house number with
   * the first two of four digits lost, twice, and then whole, and ends on the
   * whole one (numberFuller).
   * Those are card-box reads — the shift has no whole-screen read of a
   * navigation screen on file — so this is what the bottom of the screen
   * says, and the rule is held to the shapes the corpus keeps
   * (tests/fixtures/cases.json, navStops and sheets). */
  function navCandidate(st, orders, s, at) {
    if (!orders.length || s.whole !== true || s.asked === true) return null;
    var stops = Array.isArray(s.stops) ? s.stops.filter(function (x) {
      return x && typeof x === 'object';
    }) : [];
    if (stops.length !== 1 || typeof stops[0].line !== 'string' || !stops[0].line) return null;
    var a = stops[0];
    var why = s.screen === 'uber.pickupNav' ? 'a pickup screen'
      // DoorDash's place popup is about the card being screened and never
      // about an order taken (popup(), rule 2): its own line files it on the
      // card. A customer's prints its address under its role label, so the
      // whole-screen read it asks for (rpi/scan_pi.py, auto_read_for 'label')
      // typed it a dropoff, and at b337a44 this made it the HELD order's end
      // as well — one address on both jobs, measured against the real server.
      : s.screen === 'dd.placePopup' ? 'a place popup'
      : a.kind === 'pickup' ? 'a pickup'
      : a.kind !== 'dropoff' ? 'no label'
      : orders.some(function (o) { return heldPickup(o, a); }) ? 'a pickup'
      : null;
    if (why) {
      refuse(st, { at: at }, why);
      return null;
    }
    var seen = a.line + '|nav';
    if (st.said[seen]) return null;
    st.said[seen] = true;
    return { found: true, line: a.line, street: a.street || null, city: a.city || null,
             state: a.state || null, zip: a.zip || null, asked: false, labelled: 'dropoff',
             nav: true, screen: typeof s.screen === 'string' ? s.screen : null,
             app: typeof s.app === 'string' ? s.app : null,
             expectedBy: typeof a.expectedBy === 'number' ? a.expectedBy : null,
             // ...and the sheet's place, when it printed one, for file().
             place: typeof a.place === 'string' ? a.place : null,
             ms: null, at: at };
  }

  /* The reason the planner read at `at` gives the order no end, for the
   * planner line the scanner sends after that read's sighting (both carry the
   * read's `at`); undefined when no sighting of that read was seen. */
  function verdictFor(st, at) {
    for (var i = st.verdicts.length - 1; i >= 0; i--) {
      if (st.verdicts[i].at === at) return st.verdicts[i].why;
    }
    return undefined;
  }

  /* The page the planner read at `at` was, as the sighting before its planner
   * line described it — {top, bottom, app} — or null when no whole planner
   * page of that read was seen. `top` is planner_ends' (rpi/offer_parser.py):
   * the title with the first stop straight under it, so the list is seen
   * from its first stop. server.js asks it before reading a pickup's absence
   * as the app's word that the pickup is behind the car (plannerVisits). */
  function pageOf(st, at) {
    for (var i = st.pages.length - 1; i >= 0; i--) {
      var p = st.pages[i];
      if (p.at === at) return { top: p.top, bottom: p.bottom, app: p.app };
    }
    return null;
  }

  /* ---------- two orders in the car: whose is this address? ------------------
   *
   * Stage 5, behind server.js's `carryTwo`. With two orders held an address
   * read off the screen belongs to one of them, and nothing on a navigation
   * screen or a planner stop names the order it is for. The 3.1 refusal in
   * AUDITS.md is about exactly this: with two jobs in the car the ⌖ press for
   * the second attached to the first. So an address is given to an order on
   * POSITIVE CUES or not at all, and with none the driver is asked (a ⌖ press:
   * the chooser) or nothing is filed (an unprompted sighting: the pool below).
   *
   * HARD RULES, before any cue — an order they rule out cannot be chosen:
   *   - the app must match, where both the screen and the card said one;
   *   - a read older than an order's ✓ Took is not that order's.
   * One order left: `only`. None: nobody's.
   *
   * CUES, each a vote for one order:
   *   name        the store the screen names beside the stop, against each
   *               card's pickup, normalised (storeKey) with one i/l slip
   *   deadline    the stop's "Expected by" against each card's "Deliver by",
   *               within DEADLINE_SLACK_MIN — 2 minutes, CHOSEN, not measured:
   *               no file on this rig holds both readings of one order yet
   *   growth      a whole list read after the newer Took that is a whole list
   *               read before it plus exactly one dropoff: that dropoff is the
   *               newer order's, and the ones it already had are the older's
   *   elimination two orders of one app on a list seen whole with exactly two
   *               dropoffs, one of them already filed as one order's end: the
   *               other is the other order's
   *   filed       ...and the mirror: a dropoff on a list seen whole, all its
   *               orders of one app, that is ONE order's filed end already is
   *               that order's (two orders on one door decide nothing)
   *   cardStreet  the dropoff's street is the one order's own CARD printed
   *               for its end, and elimination's lighter form after it, on
   *               lists not seen whole too: see streetCues, above
   * With three orders — an original and two Uber add-ons, one trip — each of
   * growth and elimination is asked of the list as it stands: the newest
   * order's growth, and every other dropoff one distinct order's filed end.
   * A cue that fits BOTH orders is no vote, and is a TIE: the one place the
   * cards' discs come in. With a tie and no vote the answer is 'tie', and
   * server.js may break it on the map (discBreak): the address searched on the
   * NucBox inside each card's disc, and found inside exactly one. Never alone
   * — an address in one card's reach and not the other's is no reason to give
   * it to either when the screen gave no cue at all. Votes for one order
   * decide, under the first cue in that order of names; votes for both are a
   * conflict and decide nothing. */
  var DEADLINE_SLACK_MIN = 2;
  var VIEWS_MAX = 12;
  var UNOWNED_MAX = 4;

  // The store a name means: the planner's icon letters off its front (as
  // map-view.js plannerName), its " – Town" off its back, case and every mark
  // that is not a letter or a digit ignored.
  function storeKey(t) {
    if (typeof t !== 'string') return '';
    var s = t.replace(/\s+/g, ' ').trim();
    var icon = /^[a-z]{1,2} (?=[A-Z])/.exec(s);
    if (icon) s = s.slice(icon[0].length);
    s = s.split(/ [–—-] /)[0];
    return s.toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  // The same store, or the same with ONE i read as l or l as i — the slip
  // this reader makes most in a name (Tesseract on the rig's font).
  function sameStore(a, b) {
    var x = storeKey(a), y = storeKey(b);
    if (!x || !y) return false;
    if (x === y) return true;
    if (x.length !== y.length) return false;
    var slips = 0;
    for (var i = 0; i < x.length; i++) {
      if (x[i] === y[i]) continue;
      if (!((x[i] === 'i' && y[i] === 'l') || (x[i] === 'l' && y[i] === 'i'))) return false;
      slips += 1;
    }
    return slips === 1;
  }

  /* ---------- the same store as an order in the car -------------------------
   *
   * The owner's decision of 18 Oct 2026: when a new offer's pickup is the same
   * restaurant as an order already in the car, the panel says so in a few
   * words beside the pair line — "same store as ①". A FACT, not a rule or a
   * score: it moves no verdict, no state, no range and no colour, and nothing
   * here is ever a distance on the glass. The evidence: on 17 Oct a DoorDash
   * card "$12.05 · 2 stops (8.4 mi) · <Store> / 113 <Street> NE, <Town>,
   * 30060 GA" came up while an Uber order from that store, "<Store> (113
   * <Street> NW)", was held — the street's quadrant even differs by OCR.
   *
   * WHAT DECIDES "THE SAME PLACE", in this order and no other:
   *
   *   1. The door, when BOTH sides have one (sameDoor): the house number the
   *      same, the street the same once its quadrant (NE/NW/N/Northwest...)
   *      and its type (St/Street/Pkwy...) are set aside, with ONE character
   *      read as its OCR look-alike (i/l/1, o/0, s/5) allowed in a street of
   *      five letters or more. Any door of one side against any of the other:
   *      a hold has several (its card's bracket, DoorDash's stops line, a
   *      tapped popup, its Trip Planner's pickups). Both sides with doors and
   *      none agreeing is NOT the same store, whatever the names say: that is
   *      two branches of one chain, and the door is the better witness. A
   *      chain's name at the same door IS the same store.
   *   2. Otherwise the name, and only where a name can be trusted to mean one
   *      place: sameStore (one i/l slip, as everywhere in this file), the name
   *      distinctive (not a chain, `chainName`: a list of the national names
   *      this driver's metro is full of, a branch label like "Store 3317" or
   *      "- 0020-Kennesaw", or a key under four letters), AND the two pickups
   *      within SAME_STORE_NEAR_MI of each other by what the cards and pins
   *      prove (`apart`, server.js pickupsApart — an UPPER bound, or null when
   *      nothing bounds it). "Chick-fil-A" by name is a hundred restaurants.
   *   3. Nothing else. A side with neither a door nor a bound is "can't tell",
   *      and can't tell draws nothing — the panel never says "not the same".
   *
   * SAME_STORE_NEAR_MI is CHOSEN, not measured: no journal row on file carries
   * two pins of one name, so there is nothing to fit it to. Half a mile is the
   * width of a shopping centre's lot, and a distinctive name with two branches
   * inside it is the case it can get wrong. */
  var SAME_STORE_NEAR_MI = 0.5;

  // The national names, as storeKey writes them. A key that STARTS with one
  // is that chain too ("mcdonalds1155", "chickfilakennesaw"). Not exhaustive
  // and it does not need to be: a chain missing here still has to clear the
  // half-mile bound, which two of its branches seldom both sit inside.
  var CHAINS = ['mcdonalds', 'chickfila', 'wendys', 'burgerking', 'tacobell', 'kfc',
    'popeyes', 'subway', 'starbucks', 'dunkin', 'chipotle', 'panera', 'pizzahut',
    'dominos', 'papajohns', 'littlecaesars', 'arbys', 'sonic', 'dairyqueen', 'zaxbys',
    'raisingcanes', 'wingstop', 'jimmyjohns', 'jerseymikes', 'firehousesubs', 'fiveguys',
    'whataburger', 'checkers', 'rallys', 'jackinthebox', 'wafflehouse', 'ihop', 'dennys',
    'applebees', 'chilis', 'olivegarden', 'outback', 'texasroadhouse', 'crackerbarrel',
    'redlobster', 'buffalowildwings', 'pandaexpress', 'qdoba', 'moes', 'cookout',
    'krispykreme', 'bojangles', 'churchs', 'culvers', 'steaknshake', 'shakeshack',
    'tropicalsmoothie', 'smoothieking', 'jamba', 'marcos', 'hungryhowies', 'cicis',
    'longhorn', 'redrobin', 'tgifridays', 'hardees', 'carlsjr', 'whitecastle', 'crumbl',
    'insomniacookies', 'baskinrobbins', 'coldstone', 'firstwatch', 'mcalisters',
    'potbelly', 'jasonsdeli', 'schlotzskys', 'captainds', 'longjohnsilvers',
    'elpolloloco', 'sweetgreen', 'cava', 'cvs', 'walgreens', 'walmart', 'target',
    'kroger', 'publix', 'aldi', 'costco', 'samsclub', 'dollargeneral', 'familydollar',
    '7eleven', 'circlek', 'quiktrip', 'racetrac', 'petsmart', 'petco', 'homedepot',
    'lowes', 'bestbuy'];

  // The store a pickup NAMES, less the street Uber prints after it in
  // brackets ("<Store> (113 Main St NW)", closed or cut at the card's edge).
  function storeOf(pickup) {
    if (typeof pickup !== 'string') return '';
    return pickup.replace(/\s*\([^()]*\)?\s*$/, '').trim();
  }

  // Whether a name may mean many places: a chain, a branch's label, or too
  // short to be anybody's in particular.
  function chainName(name) {
    var k = storeKey(storeOf(name));
    if (k.length < 4) return true;
    if (/(?:\bstore\s*#?\s*\d|#\s*\d|\s-\s*#?\d)/i.test(String(name))) return true;
    return CHAINS.some(function (c) { return k.indexOf(c) === 0; });
  }

  var QUADRANT = /^(?:n|s|e|w|ne|nw|se|sw|north|south|east|west|northeast|northwest|southeast|southwest)$/;
  var STREET_TYPE = /^(?:st|street|rd|road|ave|av|avenue|blvd|boulevard|pkwy|parkway|dr|drive|ln|lane|ct|court|cir|circle|hwy|highway|way|pl|place|trl|trail|ter|terrace|plz|plaza|pike|sq|square|cv|cove|xing|crossing|loop|run|row|walk|path|ext|pt|point|bnd|bend|ctr|center|centre)$/;

  /* A door out of one pickup text, {house, street}, or null for a text that
   * names none. Uber's bracket after the store's name, else the line before
   * its first comma (DoorDash's stops line, a popup's, a planner stop's). The
   * house number may carry the reader's look-alikes for its digits (O for 0,
   * l or I for 1); the street is its words less a suite, less its quadrant
   * and less its type, run together. A street that is ONLY a quadrant and a
   * type, or a number and nothing else, names no door. */
  function doorOf(text) {
    if (typeof text !== 'string' || !text) return null;
    var br = /\(\s*([^()]*?)\s*\)?\s*$/.exec(text);
    var s = br && /^\S*\d/.test(br[1]) ? br[1] : text;
    s = s.split(',')[0].replace(/\s+/g, ' ').trim();
    var words = s.split(' ');
    var house = (words.shift() || '').replace(/[Oo]/g, '0').replace(/[lI|]/g, '1');
    if (!/^\d+[A-Za-z]?$/.test(house)) return null;
    var street = [];
    for (var i = 0; i < words.length; i++) {
      var w = words[i].toLowerCase().replace(/[^a-z0-9]/g, '');
      if (/^(?:ste|suite|unit|apt|bldg)$/.test(w) || /^#/.test(words[i])) break;
      if (!w || QUADRANT.test(w)) continue;
      street.push(w);
    }
    // The type only where a name is left without it ("Main St" is "main";
    // "Pike" alone stays "pike").
    var named = street.filter(function (w) { return !STREET_TYPE.test(w); });
    var core = (named.length ? named : street).join('');
    return /[a-z]/.test(core) || /^\d+(?:st|nd|rd|th)$/.test(core)
      ? { house: house.toLowerCase(), street: core } : null;
  }

  // ONE character read as its look-alike, in a street long enough that one
  // character is not most of its name.
  var LOOKALIKE = { i: 'l1', l: 'i1', 1: 'il', o: '0', 0: 'o', s: '5', 5: 's' };
  function oneSlip(x, y) {
    if (x.length !== y.length || x.length < 5) return false;
    var slips = 0;
    for (var i = 0; i < x.length; i++) {
      if (x[i] === y[i]) continue;
      if (!LOOKALIKE[x[i]] || LOOKALIKE[x[i]].indexOf(y[i]) < 0) return false;
      slips += 1;
    }
    return slips === 1;
  }

  function sameDoor(a, b) {
    var x = doorOf(a), y = doorOf(b);
    return !!x && !!y && x.house === y.house
      && (x.street === y.street || oneSlip(x.street, y.street));
  }

  /* One side of the question, {name, doors}: an offer line or an order in
   * the car. Every door text it carries — the card's own pickup (Uber's
   * bracket), DoorDash's stops line (`pickupLine`), the door a popup tapped
   * on the card (`pickupAddr`, an offer's own field; a hold's
   * `fields.pickupAddr`), and, for a hold, its Trip Planner's pickups that are
   * its own: marked with its id (`of`, server.js ownPickups) or, unmarked,
   * named as its card names its store. `stops` is the planner the first
   * order in the car keeps; `id` the hold's holdId. Read only: fieldsOf is
   * not asked, it would write the hold. */
  function pickupSide(o, stops, id) {
    var x = o || {};
    var name = storeOf(x.pickup);
    var doors = [x.pickup, x.pickupLine];
    [x.pickupAddr, x.fields && x.fields.pickupAddr].forEach(function (f) {
      if (f && typeof f === 'object' && typeof f.value === 'string') doors.push(f.value);
    });
    var own = (Array.isArray(stops) ? stops : []).filter(function (s) {
      if (!s || s.kind !== 'pickup') return false;
      return s.of ? !!id && s.of === id : !!name && sameStore(s.name, name);
    });
    own.forEach(function (s) { doors.push(s.line || s.street); });
    // ...and those stops themselves, which the server's pins are named by
    // (MV.pickupKey), for the bound on the name's rule.
    return { name: name, stops: own,
             doors: doors.filter(function (d) { return typeof d === 'string' && d; }) };
  }

  /* 'door', 'name' or null — see the block above. `apart` is the bound in
   * miles, or a function giving it (asked only when the names decide), or
   * null. */
  function samePickup(a, b, apart) {
    if (!a || !b) return null;
    var da = a.doors || [], db = b.doors || [];
    var doorsA = da.filter(doorOf), doorsB = db.filter(doorOf);
    if (doorsA.length && doorsB.length) {
      return doorsA.some(function (p) {
        return doorsB.some(function (q) { return sameDoor(p, q); });
      }) ? 'door' : null;
    }
    if (!sameStore(a.name, b.name) || chainName(a.name) || chainName(b.name)) return null;
    var d = typeof apart === 'function' ? apart() : apart;
    return typeof d === 'number' && isFinite(d) && d >= 0 && d <= SAME_STORE_NEAR_MI
      ? 'name' : null;
  }

  // Two clock readings, minutes since midnight, within `slack` round midnight.
  function clockNear(a, b, slack) {
    if (typeof a !== 'number' || typeof b !== 'number') return false;
    var d = Math.abs(a - b) % 1440;
    return Math.min(d, 1440 - d) <= slack;
  }

  function streetKey(line) {
    return norm(typeof line === 'string' ? line.split(',')[0] : '');
  }

  // An order's end as the SCREEN filed it — a press, a label, a planner —
  // never as its card guessed it, which elimination cannot stand on.
  function filedEnd(o) {
    var f = o && o.fields && o.fields.dropoff;
    return f && RANK[f.from] > RANK.card ? f.value : null;
  }

  /* A list seen whole, remembered for growth: when, which app, and the keys of
   * its dropoffs. Called by sighting() for every bounded view. */
  function noteView(st, app, at, stops) {
    st.views = st.views || [];
    var drops = headed(stops).filter(function (s) { return s.kind === 'dropoff'; })
      .map(keyOf);
    if (drops.some(function (k) { return !k; })) return;
    st.views.push({ app: app, at: at, drops: drops });
    while (st.views.length > VIEWS_MAX) st.views.shift();
  }

  /* `older` is the first-taken order, and `alone` whether it is the only one
   * besides `newer`: the list seen whole between their two Tooks, grown by
   * exactly one dropoff, gives that dropoff to `newer` — and the ones it
   * already had to `older` only when `older` is the only order they can be.
   * With three in the car (an original and two Uber add-ons, one trip) a
   * dropoff already on the list is one of the two older orders', and which
   * is not this cue's to say. */
  function growthVote(st, older, newer, d, alone) {
    if (!d.key || !Array.isArray(d.listDrops)) return null;
    var before = (st.views || []).filter(function (v) {
      return v.app === d.app && v.at >= older.tookAt && v.at < newer.tookAt;
    }).pop();
    if (!before || d.at < newer.tookAt) return null;
    var now = d.listDrops;
    var kept = before.drops.every(function (k) { return now.indexOf(k) !== -1; });
    if (!kept || now.length !== before.drops.length + 1) return null;
    if (before.drops.indexOf(d.key) === -1) return newer;
    return alone ? older : null;
  }

  /* ---------- the card's own street: the owner, 20 Oct 19:06–19:08 ----------
   *
   * An Uber order held, its card's end a corner ("<A> Rd NW & <B> Cir NW,
   * <Town>"), and an Uber add-on taken onto its trip. The Trip Planner then
   * showed both doors — "1800 <B> Cir NW, <Town>" and "608 <C> St NW,
   * <Town>" — but only across pages the driver scrolled, never the list
   * whole, so growth and elimination (both a list seen whole) never spoke,
   * and neither door was filed: the order kept the card's corner, 'no house
   * number', and the add-on had no end at all. Two positive cues, asked of
   * every unprompted Trip Planner dropoff with two or more held (attribute)
   * and of the same dropoff waiting in the pool (retryUnowned):
   *
   *   cardStreet   the dropoff's street NAME (streetCore: its house number,
   *                type and quadrant gone) is one the order's OWN CARD
   *                printed for its end (cardStreets: its door, or either side
   *                of its corner), and no other held order's card names that
   *                street. Two cards naming it is no cue at all.
   *   elimination  exactly two orders held, one trip, the read after BOTH
   *                Tooks (the add-on's included); one order's end is a
   *                planner door on its own card's street (as cardStreet
   *                filed it); this dropoff's street is on no held card and is
   *                not that order's door: it is the OTHER order's — only
   *                while that one has no end the screen filed.
   *
   * Never over a ⌖ press (an asked read is the chooser's; elimination's
   * other order must have no screen-filed end, and a pressed end is one),
   * never a pickup of any held order. These are the ONLY cues a dropoff off
   * a list not seen whole (`partial`) is asked: Settled stands, no cue means
   * no filing, and the chooser never times out into a guess. */
  function cardHas(o, core) {
    return cardStreets(cardEndOf(o)).indexOf(core) !== -1;
  }

  function aPickupOfAny(orders, d) {
    return orders.some(function (o) {
      if (plannerPickup(o, d)) return true;
      var f = o.fields && o.fields.pickupAddr;
      return [f ? f.value : null, o.pickup, o.pickupLine, bracketDoor(o.pickup)]
        .some(function (p) { return sameStreet(p, d.line); });
    });
  }

  function streetCues(orders, live, d, out) {
    if (d.asked !== false || d.planner !== true || typeof d.line !== 'string') return;
    var all = (orders || []).filter(Boolean);
    if (all.length < 2 || aPickupOfAny(all, d)) return;
    var core = streetCore(typeof d.street === 'string' && d.street ? d.street
      : d.line.split(',')[0]);
    if (!core) return;
    var naming = all.filter(function (o) { return cardHas(o, core); });
    if (naming.length > 1) return;
    if (naming.length === 1) {
      var f = naming[0].fields && naming[0].fields.dropoff;
      if (live.indexOf(naming[0]) !== -1 && !(f && f.from === 'press')) {
        out.votes.push({ cue: 'cardStreet', order: naming[0] });
      }
      return;
    }
    if (all.length !== 2 || live.length !== 2 || typeof d.at !== 'number') return;
    if (!all.every(function (o) { return typeof o.tookAt === 'number' && d.at >= o.tookAt; })) return;
    var first = all.filter(function (o) {
      var e = o.fields && o.fields.dropoff;
      var c = e && e.from === 'planner' ? streetCore(String(e.value).split(',')[0]) : null;
      return !!c && all.filter(function (x) { return cardHas(x, c); }).length === 1
        && cardHas(o, c);
    });
    if (first.length !== 1) return;
    var other = all[all[0] === first[0] ? 1 : 0];
    // (The first order's own door read again is on its card's street, so
    // cardStreet answered it above and it never reaches here.)
    if (filedEnd(other)) return;
    out.votes.push({ cue: 'elimination', order: other });
  }

  /* `orders` is every order held, first-taken first; `d` a dropoff line or a
   * candidate made off a planner. Returns {order, cue, why, votes}: `order`
   * null when nothing decides, `why` then 'nobody' (the hard rules left none),
   * 'no cue' or 'cues disagree'.
   *
   * `ctx.card`: a card being screened could own this press too
   * (cardCandidate). The hard rules then decide nothing on their own — they
   * rule orders out and never the card, so `only` would be elimination over
   * two owners of three — and the one order they leave is chosen on a cue
   * that names it, or not at all. Measured at 657bc18, carrying two on, ① an
   * Uber order, ② a DoorDash order with its end on record and a DoorDash card
   * screened: ⌖ over that card's customer popup was filed onto ② by `only`,
   * replacing its end, as the popup's own line gave the card the same
   * address. Elimination proper needs a planner's list seen whole, and a
   * planner is never a card's screen, so it does not arise here.
   *
   * A LIST WITH MORE DROPOFFS THAN ORDERS LEFT. The hard rules rule orders
   * out; they say nothing about whose the other dropoffs on a list are. A
   * list seen whole with two dropoffs and one order left standing (the other
   * order DoorDash's, or taken after the read) has a dropoff that is no order
   * of ours, or two of that one order's — a batched card's two customers —
   * and `only` filed the first of them as its end. Measured at f80d0c2,
   * carrying two on, a two-customer Uber card and a DoorDash order held, an
   * unpressed two-dropoff planner: mark row {cue: 'only'} with the first
   * customer's door as the Uber order's end. So `only` is not allowed there,
   * and a cue that names the order (the store, the deadline) still is. */
  function attribute(st, orders, d, ctx) {
    var out = { order: null, cue: null, why: null, votes: [], ties: [] };
    var live = (orders || []).filter(function (o) {
      if (d.app && o.app && d.app !== o.app) return false;
      if (typeof d.at === 'number' && typeof o.tookAt === 'number' && d.at < o.tookAt) {
        return false;
      }
      return true;
    });
    if (!live.length) { out.why = 'nobody'; return out; }
    // A dropoff off a list NOT seen whole (sightingMany's `partial`) is
    // decided by the card's street alone (streetCues): what the screen did
    // not show may be anyone's, so neither `only` nor a cue that reads the
    // list (growth, elimination, filed) nor one that reads a page's lone
    // store stands on it.
    var partial = d.partial === true;
    var crowded = d.bounded === true && Array.isArray(d.others)
      && d.others.length + 1 > live.length;
    if (live.length === 1 && !(ctx && ctx.card) && !crowded && !partial) {
      out.order = live[0];
      out.cue = 'only';
      return out;
    }
    var older = live[0], newer = live[live.length - 1];
    function vote(cue, fits) {
      var hit = live.filter(fits);
      if (hit.length === 1) out.votes.push({ cue: cue, order: hit[0] });
      else if (hit.length > 1) out.ties.push(cue);
    }
    if (d.store && !partial) vote('name', function (o) { return sameStore(d.store, o.pickup); });
    if (typeof d.expectedBy === 'number' && !partial) {
      vote('deadline', function (o) {
        return clockNear(d.expectedBy, o.deliverBy, DEADLINE_SLACK_MIN);
      });
    }
    // Two or more: with three, an original and two Uber add-ons on one trip
    // (server.js, placeTook) — the owner's trip details for 16 Oct show one.
    // Each cue below is the two-order cue asked of the list as it stands; with
    // two it is that cue exactly.
    if (live.length >= 2 && !partial) {
      // (From the first Took on, as with two: a list that grew by exactly one
      // since then names the newest; one seen before the middle Took cannot
      // have grown by one into a list of three.)
      var grown = growthVote(st, older, newer, d, live.length === 2);
      if (grown) out.votes.push({ cue: 'growth', order: grown });
      var oneApp = live.every(function (o) { return o.app && o.app === older.app; });
      // Elimination: every OTHER dropoff on the list is already one distinct
      // order's filed end, and one order is left over — this is its.
      if (d.bounded && Array.isArray(d.others) && d.others.length === live.length - 1
          && oneApp) {
        var owned = [];
        var whole = d.others.every(function (line) {
          var other = streetKey(line);
          var took = live.filter(function (o) {
            var end = filedEnd(o);
            return end && streetKey(end) === other;
          });
          if (took.length !== 1) return false;
          owned.push(took[0]);
          return true;
        });
        var left = live.filter(function (o) { return owned.indexOf(o) === -1; });
        if (whole && left.length === 1) {
          out.votes.push({ cue: 'elimination', order: left[0] });
        }
      }
      // ...and its mirror: a dropoff on a list seen whole that IS one order's
      // filed end — the door the screen already gave that order — is that
      // order's. Without it the older order's own door, read again on the
      // list that now shows both, waited in the pool as "1 dropoff read ·
      // whose?" for as long as both were carried. One order's only: two
      // orders filed to the same door is a tie, and no vote.
      if (d.bounded && oneApp && typeof d.line === 'string') {
        var mine = streetKey(d.line);
        // Not through vote(): two orders on one door is no tie for the map
        // to break (discBreak) — the door is both, and the map cannot say
        // otherwise.
        var filed = live.filter(function (o) {
          var end = filedEnd(o);
          return !!end && streetKey(end) === mine;
        });
        if (filed.length === 1) out.votes.push({ cue: 'filed', order: filed[0] });
      }
    }
    streetCues(orders, live, d, out);
    var picked = [];
    out.votes.forEach(function (v) { if (picked.indexOf(v.order) === -1) picked.push(v.order); });
    if (picked.length === 1) {
      out.order = picked[0];
      out.cue = out.votes[0].cue;
    } else {
      out.why = picked.length ? 'cues disagree' : out.ties.length ? 'tie' : 'no cue';
    }
    return out;
  }

  /* ---------- the pool of addresses nobody owns yet -------------------------
   *
   * An unprompted address that two held orders could each own, and no cue
   * decides: kept in memory (never written — it is a door), said on the panel
   * as "N dropoffs read · whose?", and retried by retryUnowned() when a later
   * read adds a cue. With `among`, the ids held when it was read: if either of
   * them leaves the car the address is dropped, never handed to the one left
   * as `only` — it may be the order just delivered. */
  function park(st, d, orders) {
    st.unowned = (st.unowned || []).filter(function (u) { return u.d.line !== d.line; });
    st.unowned.push({ d: d, among: (orders || []).map(holdIdOf) });
    while (st.unowned.length > UNOWNED_MAX) st.unowned.shift();
  }

  function unowned(st) {
    return (st.unowned || []).length;
  }

  /* An address taken out of the pool, by its line: true when it was there.
   * For a decision made outside the cues (server.js's disc tie-break). */
  function unpark(st, line) {
    var before = (st.unowned || []).length;
    st.unowned = (st.unowned || []).filter(function (u) { return u.d.line !== line; });
    return st.unowned.length !== before;
  }

  /* Each address in the pool asked again against `orders`: returns the ones a
   * cue now decides, as [{d, order, cue}], and takes them out. One whose
   * orders are not both still held is dropped — and that is what keeps `only`
   * out of here: with the same two orders held, the hard rules leave both,
   * as they did when it was parked, so only a cue can decide it. */
  function retryUnowned(st, orders) {
    var ids = (orders || []).map(holdIdOf);
    var out = [];
    st.unowned = (st.unowned || []).filter(function (u) {
      if (!u.among.every(function (id) { return ids.indexOf(id) !== -1; })) return false;
      var a = attribute(st, orders, u.d);
      if (a.order) {
        out.push({ d: u.d, order: a.order, cue: a.cue });
        return false;
      }
      return true;
    });
    return out;
  }

  /* The planner with two orders held: every dropoff a list seen whole shows,
   * read whole (street and town), as a candidate of its own — with what the
   * cues need: its key and time, the store when the list is ONE pickup and
   * ONE dropoff (then the two are one order's), the other dropoffs on the
   * list, and whether the list was bounded. Asked only when the press read
   * one dropoff: two addresses are not one answer. */
  function plannerCandidates(view, page, bounded) {
    var stops = headed(view.stops);
    var drops = stops.filter(function (s) { return s.kind === 'dropoff'; });
    var picks = stops.filter(function (s) { return s.kind === 'pickup'; });
    var keys = drops.map(keyOf);
    var out = [];
    drops.forEach(function (s, i) {
      if (!(s.street && s.city)) return;
      var c = candidate(addressOf(s), s, page, page.asked && drops.length === 1, false);
      c.app = page.app;
      c.expectedBy = typeof s.expectedBy === 'number' ? s.expectedBy : null;
      c.store = picks.length === 1 && drops.length === 1 ? (picks[0].name || null) : null;
      c.others = drops.filter(function (x, j) { return j !== i; })
        .map(function (x) { return x.line || null; });
      c.listDrops = keys.every(Boolean) ? keys : null;
      c.bounded = !!bounded;
      out.push(c);
    });
    return out;
  }

  /* One sighting with two orders held (server.js passes the list when it holds
   * two). A non-planner screen moves the epoch as it does with one, and gives
   * its navigation destination as with one (navCandidate). A planner
   * read whole is linked as with one, over the pages read since the OLDER
   * order's card; a list seen whole gives every dropoff it shows read whole as
   * a candidate of its own (plannerCandidates), for server.js to attribute
   * (attribute), and is remembered for growth (noteView). A list not seen
   * whole gives nothing and waits in the pool, as with one order: its lone
   * dropoff is a single-trip rule, and with two orders in the car there is no
   * single trip. The reason the planner line carries is the planner's own,
   * except that a list whose dropoffs are all handed over gives none — they
   * are the attribution's now, and the panel says what came of them. */
  function sightingMany(st, orders, s, now) {
    var out = { candidates: [], why: null, at: s && typeof s.at === 'number' ? s.at : null };
    if (!s || typeof s !== 'object') return out;
    took(st, orders);
    var app = typeof s.app === 'string' ? s.app : null;
    if (s.screen !== 'uber.planner') {
      if (app) st.epoch[app] = (st.epoch[app] || 0) + 1;
      else Object.keys(st.epoch).forEach(function (a) { st.epoch[a] += 1; });
      // ...and a navigation destination, as with one: whose it is, server.js
      // asks attribute() — the app, the Took, the bar's "Expected by" against
      // each card's "Deliver by" — and with no cue it waits in the pool.
      var nav = navCandidate(st, orders, s, out.at === null ? now : out.at);
      if (nav) out.candidates.push(nav);
      return out;
    }
    if (s.whole !== true || !pageStops(s.stops)) return out;
    var page = { at: out.at === null ? now : out.at, app: app,
                 epoch: st.epoch[app] || 0, asked: s.asked === true,
                 titled: s.titled === true,
                 top: !!(s.page && s.page.top), bottom: !!(s.page && s.page.bottom),
                 stops: s.stops.filter(function (x) { return x && typeof x === 'object'; }),
                 pending: false, why: null };
    st.pages.push(page);
    while (st.pages.length > PAGES_MAX) st.pages.shift();
    var since = Math.min.apply(null, orders.map(function (o) { return o.acceptedAt; }));
    var pool = st.pages.filter(function (p) { return p.at >= since; });
    var run = pool.indexOf(page) === -1 ? { view: pageView(page), pages: [page] }
      : linked(pool, page);
    var view = run.pages.length > 1 ? run.view : pageView(page);
    // Seen whole only with as many dropped off as picked up (listShort): every
    // dropoff below is handed over for attribution, and one the reader lost
    // would leave the others to be told apart by elimination.
    var bounded = view.top && view.bottom && !listShort(view.stops);
    var verdict = plannerDestination(view.stops, bounded);
    var cands = [];
    if (bounded) {
      noteView(st, app, page.at, view.stops);
      cands = plannerCandidates(view, page, true).filter(function (c) {
        if (c.asked) return true;
        var seen = c.line + '|many';
        if (st.said[seen]) return false;
        st.said[seen] = true;
        return true;
      });
    } else if (!page.asked && orders.some(function (o) { return cardStreets(cardEndOf(o)).length; })) {
      // ...and a list NOT seen whole, unprompted, while a held card printed
      // a street for its end: each dropoff read whole, `partial`, for the
      // card's-street cues alone (streetCues; the owner's snap of 20 Oct,
      // both doors seen only on pages scrolled). No store (a page's one
      // pickup need not be its one dropoff's), no list for growth. With no
      // card street there is nothing they could say, and nothing is offered.
      cands = plannerCandidates(view, page, false).filter(function (c) {
        var seen = c.line + '|part';
        if (st.said[seen]) return false;
        st.said[seen] = true;
        return true;
      });
      cands.forEach(function (c) {
        c.partial = true;
        c.store = null;
        c.listDrops = null;
      });
    }
    run.pages.forEach(function (p) {
      p.pending = false;
      p.why = null;
      if (p.at < since || bounded) return;
      p.pending = true;
      p.why = verdict.why || 'list';
    });
    cands.forEach(function (c) {
      if (run.pages.length > 1) c.pages = run.pages.length;
      c.pageAts = run.pages.map(function (p) { return p.at; });
    });
    out.candidates = cands;
    out.why = bounded && verdict.why === 'dropoffs' ? null : verdict.why;
    st.verdicts.push({ at: page.at, why: out.why });
    while (st.verdicts.length > PAGES_MAX) st.verdicts.shift();
    return out;
  }

  /* ---------- the planner row in the journal ----------------------------------
   *
   * ONE ROW FOR ONE PLANNER: the same stops read again inside `sameMs` are not
   * a row of their own. Moved from server.js's recordPlanner, which says why;
   * `written` is the last row's {key, at}, or null. Returns the new `written`
   * when a row is due, else null. */
  function plannerRowDue(written, stops, now, sameMs) {
    var key = JSON.stringify(stops);
    if (written && written.key === key && now - written.at < sameMs) return null;
    return { key: key, at: now };
  }

  /* ---------- the held order's own card, back under a new id ----------------
   *
   * Moved from server.js, where the header above HELD_CARD_MS says why. The
   * figures a card is recognised by: what the offer line carries — or a
   * reading, whose card minutes are `cardMinutes` where rate() found them,
   * else `minutes`, the fallback emit_offer takes. */
  function num(v) {
    return typeof v === 'number' && isFinite(v) ? v : null;
  }

  function cardSeen(c, reading) {
    if (!c) return null;
    var mins = reading ? (c.cardMinutes || c.minutes) : c.minutes;
    return { pay: num(c.pay), miles: num(c.miles), minutes: num(mins),
             pickup: typeof c.pickup === 'string' ? c.pickup : null,
             dropoff: typeof c.dropoff === 'string' ? c.dropoff : null };
  }

  /* `slotHeldCard` is the card on the slot's own heldCard, which says a
   * reading of it was already recognised; `windowMs` is HELD_CARD_MS. */
  function heldOwnCard(held, card, now, reading, windowMs, slotHeldCard) {
    var s = held && held.seenAs;
    var c = cardSeen(card, reading);
    if (!s || !c || s.pay === null || c.pay === null) return false;
    // The window is on the card's ARRIVAL. A reading of a card already
    // recognised (the slot says so) is still that card however long it sits on
    // the phone; a new id after the window is judged as a new offer.
    var recognised = reading && !!slotHeldCard && slotHeldCard === holdIdOf(held);
    if (now - s.tookAt > windowMs && !recognised) return false;
    if (Math.round(s.pay * 100) !== Math.round(c.pay * 100)) return false;
    if (s.miles !== c.miles || s.minutes !== c.minutes) return false;
    return ['pickup', 'dropoff'].every(function (k) {
      var a = norm(s[k]), b = norm(c[k]);
      return !a || !b || a === b;
    });
  }

  /* The card an order in the car was taken from, OFFERED AGAIN at a different
   * pay — the platform re-sending a job with its tip moved, which the driver
   * accepts a second time. Stage 5, with two orders carried: a Took on it
   * replaces that order rather than adding a second one. Stricter than
   * heldOwnCard on purpose, because the cost of a wrong yes is an order
   * thrown out of the car: the same miles and the same card minutes, BOTH
   * ends read on both cards and the same, and a pay that differs — inside
   * `windowMs` (HELD_CARD_MS) of that order's Took. */
  function reOffer(held, card, now, windowMs) {
    var s = held && held.seenAs;
    var c = cardSeen(card, false);
    if (!s || !c || s.pay === null || c.pay === null) return false;
    if (now - s.tookAt > windowMs) return false;
    if (Math.round(s.pay * 100) === Math.round(c.pay * 100)) return false;
    if (s.miles === null || s.miles !== c.miles) return false;
    if (s.minutes === null || s.minutes !== c.minutes) return false;
    return ['pickup', 'dropoff'].every(function (k) {
      var a = norm(s[k]), b = norm(c[k]);
      return !!a && a === b;
    });
  }

  return { RANK: RANK, FIELDS: FIELDS, STITCH_MS: STITCH_MS, PAGES_MAX: PAGES_MAX,
           cardFields: cardFields, fieldsOf: fieldsOf, outranks: outranks,
           plannerPickup: plannerPickup, forgetPlanner: forgetPlanner,
           // ...and the street rule they stand on, for server.js's planAtOf
           // (where on a planner each order's end is).
           sameStreet: sameStreet, VOTE_READS: VOTE_READS, plannerVote: plannerVote,
           dropoff: dropoff, file: file, fileCard: fileCard, cardRank: cardRank,
           pressBetween: pressBetween, ownPopup: ownPopup, cardCandidate: cardCandidate,
           storeScreen: storeScreen, placeOf: placeOf, bracketDoor: bracketDoor,
           popup: popup, filePopup: filePopup, cardNames: cardNames,
           plannerDestination: plannerDestination, plannerLoneDropoff: plannerLoneDropoff,
           lostHeaderDropoff: lostHeaderDropoff, framedTrip: framedTrip,
           footDropoff: footDropoff,
           // ...and a batched trip's doors (the owner's decision of 19 Oct).
           batchPlan: batchPlan, batchWhy: batchWhy, cardStreets: cardStreets,
           streetCore: streetCore,
           keyOf: keyOf, placements: placements, linked: linked,
           // ...and the planner the hold keeps, pages merged (24 Oct).
           mergePlanner: mergePlanner,
           fresh: fresh, took: took, sighting: sighting, pending: pending,
           verdictFor: verdictFor, pageOf: pageOf, plannerRowDue: plannerRowDue,
           cardSeen: cardSeen, heldOwnCard: heldOwnCard, holdIdOf: holdIdOf,
           DEADLINE_SLACK_MIN: DEADLINE_SLACK_MIN, storeKey: storeKey, sameStore: sameStore,
           // ...and the same store as an order in the car (server.js
           // sameStoreOf; the owner's decision of 18 Oct 2026).
           SAME_STORE_NEAR_MI: SAME_STORE_NEAR_MI, chainName: chainName, doorOf: doorOf,
           // ...and the name a store's waits are kept by (server.js storeNameSaid).
           storeOf: storeOf,
           sameDoor: sameDoor, pickupSide: pickupSide, samePickup: samePickup,
           attribute: attribute, park: park, unpark: unpark, unowned: unowned,
           retryUnowned: retryUnowned,
           plannerCandidates: plannerCandidates, reOffer: reOffer };
}));
