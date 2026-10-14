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
   *   card     what the offer card said, at ✓ Took
   *   seen     unprompted, off the screen with no label to stand on — or a
   *            screening read whose asking was not kept on the card
   *
   * `seen` is below `card` because that is today's rule for it: an address
   * nobody asked for and no label proves fills a blank and moves nothing. It is
   * not in the plan's list of four, and naming it `card` would have been a
   * provenance that lies.
   *
   * `conf` is how much of the value read: for an address, how many of its
   * street, town and ZIP; for a name or a time, 1. `at` is the scanner's clock
   * when it read the screen (the Took for `card`), `screen` the screen type off
   * the sighting, or null where the line carried none.
   *
   * The hold's older fields — `dropoff`, `dropoffScanned` — are kept in step by
   * file() below, so the stack line, the pair rows, the map and the GPS drop
   * read exactly what they read before. */
  var RANK = { seen: 0, card: 1, planner: 2, nav: 3, label: 4, press: 5 };
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

  /* The fields a hold starts with, at ✓ Took: what the card said, or — when
   * the card already carried an address read off the screen while it was
   * being screened — that, with the provenance the screening branch kept on
   * the card (`dropoffFrom`), else `seen`. */
  function cardFields(offer, at) {
    var o = offer || {};
    var from = o.dropoffScanned ? (RANK[o.dropoffFrom] !== undefined ? o.dropoffFrom : 'seen')
      : 'card';
    return {
      dropoff: field(o.dropoff || null, from, 0, at, null),
      pickupAddr: field(o.pickup || null, 'card', 0, at, null),
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
   *     screen has only its street. */
  function outranks(next, cur) {
    if (!next) return null;
    if (!cur) return 'blank';
    if (next.from === 'press') return 'press';
    // (A press already there falls through to null: nothing below lets a
    // label, a planner, a navigation screen or a sighting past one.)
    if (cur.from === 'card') return RANK[next.from] > RANK.card ? 'over the card' : null;
    if (next.from === 'nav' && cur.from === 'seen') return 'over a sighting';
    if (next.from === cur.from && next.key && next.key === cur.key && next.conf > cur.conf) {
      return 'fuller';
    }
    if (next.from === 'nav' && cur.from !== 'press' && next.conf > cur.conf
        && sameStreet(next.value, cur.value)) {
      return 'fuller';
    }
    return null;
  }

  /* Two address lines on the same street: the part before the first comma,
   * case, commas and spacing ignored, and something there to compare. */
  function sameStreet(a, b) {
    var x = streetKey(a), y = streetKey(b);
    return !!x && x === y;
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
   * destination that is any held order's pickup is refused outright. */
  function heldPickup(held, dropoff) {
    if (!held || !dropoff) return false;
    if (plannerPickup(held, dropoff)) return true;
    var f = fieldsOf(held).pickupAddr;
    return [f ? f.value : null, held.pickup].some(function (p) {
      return typeof p === 'string' && sameStreet(p, dropoff.line);
    });
  }

  /* The Trip Planner's stops come off the order in the car at the moments the
   * driving screen forgets them (live.html's forgetDest): a ⌖ press and a
   * different offer on the record. See forgetPlanner in server.js, which says
   * why, and which now asks this. */
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
   *      scanner too old to say is refused — and `legs` must be 1. Refused,
   *      it is dropped whole (`drop`), as it always was.
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
   *   5. Onto the hold when outranks() says so; held and not outranked is
   *      nothing, and nothing said.
   *   6. With nothing held, onto the card being screened when it is asked, or
   *      when that card names no end.
   *
   * `tally` is whether the journal's `kind: 'sighting'` count row is owed:
   * every unprompted address that arrives while an order is carried. */
  function dropoff(held, d, screening) {
    var out = { to: null, kept: false, asked: true, labelled: false, from: null,
                why: null, tally: false, drop: false };
    if (!d) return out;
    if (d.singleCardOnly === true) {
      var oneTrip = !!held && !!held.card && held.card.legs === 1
        && held.card.multiOrder === false;
      if (!oneTrip) {
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
    if (held) {
      if (aPickup) {
        out.why = 'a pickup';
        return out;
      }
      var cur = fieldsOf(held).dropoff;
      var why = outranks(field(d.line, out.from, addressConf(d), d.at, d.screen, d.key), cur);
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
    if (d.singleCardOnly === true) {
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

  /* ...and onto the card being screened. `dropoffFrom` rides with it, so the
   * hold made from this card at ✓ Took knows a press from a sighting. */
  function fileCard(card, d, said) {
    if (!card || !said || said.to !== 'card') return;
    card.dropoff = d.line;
    card.dropoffScanned = true;
    card.dropoffFrom = said.from;
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

  function plannerDestination(stops, bounded) {
    var drops = headed(stops).filter(function (s) { return s.kind === 'dropoff'; });
    if (!drops.length) return { address: null, why: null, stop: null };
    if (drops.length > 1) return { address: null, why: 'dropoffs', stop: null };
    if (!bounded) return { address: null, why: 'list', stop: drops[0] };
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
    if (!(drops[0].street && drops[0].city)) return null;
    return addressOf(drops[0]);
  }

  /* ---------- the Trip Planner: several pages --------------------------------
   *
   * A stop's key is its kind, name and time, `kind|name|expectedBy`: what two
   * pages of one list both print for the same stop. A stop with neither a
   * name nor a time has no key — two such stops would match on the kind
   * alone — and nor does the stop a page begins in the middle of, which has
   * no kind.
   *
   * HOW LONG A PAGE WAITS FOR ITS NEIGHBOUR: STITCH_MS, 20 s. CHOSEN, NOT
   * MEASURED — no file on this rig holds two pages of one planner yet. It is
   * twice SCREEN_AUTO_EVERY (rpi/scan_pi.py), so the unpressed read that
   * follows a scroll can still reach the page before it.
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
  var STITCH_MS = 20000;
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
    var head = a.kind ? a : b;
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
    out.partial = out.kind && (out.street || out.city) ? null
      : (a.partial || b.partial || null);
    return out;
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

  /* One sighting (rpi/scan_pi.py, sighting()): {at, asked, whole, titled, app,
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
   * A card-box read (not whole) is no page: it saw part of the screen.
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
    if (s.whole !== true || !Array.isArray(s.stops) || !headed(s.stops).length) return out;
    var page = { at: out.at === null ? now : out.at, app: app,
                 epoch: st.epoch[app] || 0, asked: s.asked === true,
                 titled: s.titled === true,
                 top: !!(s.page && s.page.top), bottom: !!(s.page && s.page.bottom),
                 stops: s.stops.filter(function (x) { return x && typeof x === 'object'; }),
                 pending: false, why: null };
    st.pages.push(page);
    while (st.pages.length > PAGES_MAX) st.pages.shift();

    // Pages for linking: with a hold, only those read after its Took.
    var pool = held ? st.pages.filter(function (p) { return p.at >= held.acceptedAt; })
      : [page];
    var run = pool.indexOf(page) === -1 ? { view: pageView(page), pages: [page] }
      : linked(pool, page);
    var many = run.pages.length > 1;
    var view = many ? run.view : pageView(page);
    var verdict = plannerDestination(view.stops, view.top && view.bottom);
    var titled = run.pages.some(function (p) { return p.titled; });
    var cand = null;
    if (!many) {
      if (page.asked) {
        if (verdict.address) cand = candidate(verdict.address, verdict.stop, page, true, false);
      } else if (page.titled) {
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
    if (cand && !cand.asked) {
      var seen = cand.line + (cand.singleCardOnly ? '|lone' : '');
      if (st.said[seen]) { cand = null; deduped = true; }
      else st.said[seen] = true;
    }
    if (cand) out.candidates.push(cand);
    out.why = verdict.why;
    // The pool. With an order held, every page of this run read after its
    // Took waits for the page that may complete it — unless the run gave its
    // address (a lone dropoff still waits: a later page may bound the list),
    // or has two dropoffs, which no page can undo.
    var consumed = deduped || (!!cand && !cand.singleCardOnly);
    run.pages.forEach(function (p) {
      var was = p.pending;
      p.pending = false;
      if (!held) return;
      if (p.at < held.acceptedAt) {
        if (p === page && !cand) refuse(st, p, 'before the Took');
        return;
      }
      if (verdict.why === 'dropoffs') {
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
    st.verdicts.push({ at: page.at, why: verdict.why });
    while (st.verdicts.length > PAGES_MAX) st.verdicts.shift();
    return out;
  }

  function candidate(address, stop, page, asked, lone) {
    return { found: true, line: address.line, street: address.street, city: address.city,
             state: address.state, zip: address.zip, asked: asked,
             labelled: asked ? null : 'dropoff', singleCardOnly: lone ? true : null,
             planner: true, screen: 'uber.planner', key: keyOf(stop),
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
   *     'a pickup screen';
   *   - the address is typed a dropoff. Under a Pickup label it is 'a pickup';
   *     under no label at all it is 'no label' — AUDITS.md's Settled rule that
   *     an address nobody asked for and no label proves is not a destination;
   *   - it is not a pickup of ANY order in the car by any word on record
   *     (heldPickup): 'a pickup'. With two orders the other one's store is as
   *     wrong an end as this one's.
   * Each refusal is kept (st.refused) with its reason. And once per address
   * for this hold, as a planner's is: a navigation screen sits in front of
   * the camera for a whole delivery and is read every ten seconds.
   *
   * WHAT THE 12 OCT SHIFT SAYS IT WILL FIND, measured by putting each of its
   * 1,237 `screen` rows through rpi/scan_pi.py's sighting() and this: no
   * candidate at all, and none of the 179 typed uber.nav carries an address
   * under either label. The 36 that print "Deliver to" print a customer's
   * name after it and no address; the 18 that show the opened sheet print the
   * street and town under the name (14 with a house number read), never with
   * a ZIP, and the sheet's one label, "Dropoff type", BELOW them; 10 read as
   * an offer, the bar taken for a card's leg. Those are card-box reads — the
   * shift has no whole-screen read of a navigation screen on file — so this
   * is what the bottom of the screen says, and the rule is held to the shapes
   * the corpus keeps (tests/fixtures/cases.json, navStops). */
  function navCandidate(st, orders, s, at) {
    if (!orders.length || s.whole !== true || s.asked === true) return null;
    var stops = Array.isArray(s.stops) ? s.stops.filter(function (x) {
      return x && typeof x === 'object';
    }) : [];
    if (stops.length !== 1 || typeof stops[0].line !== 'string' || !stops[0].line) return null;
    var a = stops[0];
    var why = s.screen === 'uber.pickupNav' ? 'a pickup screen'
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

  function growthVote(st, older, newer, d) {
    if (!d.key || !Array.isArray(d.listDrops)) return null;
    var before = (st.views || []).filter(function (v) {
      return v.app === d.app && v.at >= older.tookAt && v.at < newer.tookAt;
    }).pop();
    if (!before || d.at < newer.tookAt) return null;
    var now = d.listDrops;
    var kept = before.drops.every(function (k) { return now.indexOf(k) !== -1; });
    if (!kept || now.length !== before.drops.length + 1) return null;
    return before.drops.indexOf(d.key) === -1 ? newer : older;
  }

  /* `orders` is every order held, first-taken first; `d` a dropoff line or a
   * candidate made off a planner. Returns {order, cue, why, votes}: `order`
   * null when nothing decides, `why` then 'nobody' (the hard rules left none),
   * 'no cue' or 'cues disagree'. */
  function attribute(st, orders, d) {
    var out = { order: null, cue: null, why: null, votes: [], ties: [] };
    var live = (orders || []).filter(function (o) {
      if (d.app && o.app && d.app !== o.app) return false;
      if (typeof d.at === 'number' && typeof o.tookAt === 'number' && d.at < o.tookAt) {
        return false;
      }
      return true;
    });
    if (!live.length) { out.why = 'nobody'; return out; }
    if (live.length === 1) {
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
    if (d.store) vote('name', function (o) { return sameStore(d.store, o.pickup); });
    if (typeof d.expectedBy === 'number') {
      vote('deadline', function (o) {
        return clockNear(d.expectedBy, o.deliverBy, DEADLINE_SLACK_MIN);
      });
    }
    if (live.length === 2) {
      var grown = growthVote(st, older, newer, d);
      if (grown) out.votes.push({ cue: 'growth', order: grown });
      if (d.bounded && Array.isArray(d.others) && d.others.length === 1
          && older.app && older.app === newer.app) {
        var other = streetKey(d.others[0]);
        var took = live.filter(function (o) {
          var end = filedEnd(o);
          return end && streetKey(end) === other;
        });
        if (took.length === 1) {
          out.votes.push({ cue: 'elimination', order: live[1 - live.indexOf(took[0])] });
        }
      }
    }
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
    if (s.whole !== true || !Array.isArray(s.stops) || !headed(s.stops).length) return out;
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
    var bounded = view.top && view.bottom;
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
           dropoff: dropoff, file: file, fileCard: fileCard,
           plannerDestination: plannerDestination, plannerLoneDropoff: plannerLoneDropoff,
           keyOf: keyOf, placements: placements, linked: linked,
           fresh: fresh, took: took, sighting: sighting, pending: pending,
           verdictFor: verdictFor, plannerRowDue: plannerRowDue,
           cardSeen: cardSeen, heldOwnCard: heldOwnCard, holdIdOf: holdIdOf,
           DEADLINE_SLACK_MIN: DEADLINE_SLACK_MIN, storeKey: storeKey, sameStore: sameStore,
           attribute: attribute, park: park, unpark: unpark, unowned: unowned,
           retryUnowned: retryUnowned,
           plannerCandidates: plannerCandidates, reOffer: reOffer };
}));
