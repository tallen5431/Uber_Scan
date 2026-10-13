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
   *   label    unprompted, printed under a Dropoff label in its own block
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
  var RANK = { seen: 0, card: 1, planner: 2, label: 3, press: 4 };
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
   *     which a second label-proven address does not get past. */
  function outranks(next, cur) {
    if (!next) return null;
    if (!cur) return 'blank';
    if (next.from === 'press') return 'press';
    // (A press already there falls through to null: nothing below lets a
    // label, a planner or a sighting past one.)
    if (cur.from === 'card') return RANK[next.from] > RANK.card ? 'over the card' : null;
    if (next.from === cur.from && next.key && next.key === cur.key && next.conf > cur.conf) {
      return 'fuller';
    }
    return null;
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
   *   4. Not one of the hold's own planner pickups, when label-proven: a
   *      restaurant's door filed as where the customer lives is the
   *      confidently wrong direction, so it is refused outright, blank or not.
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
    var aPickup = labelled && plannerPickup(held, d);
    out.asked = wasAsked;
    out.labelled = labelled;
    out.from = wasAsked ? 'press'
      : labelled ? (d.planner === true || d.singleCardOnly === true ? 'planner' : 'label')
      : 'seen';
    out.tally = !wasAsked && !!held;
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
   * twice PLANNER_AUTO_EVERY (rpi/scan_pi.py), so the unpressed read that
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
    return { pages: [], epoch: {}, holdId: null, said: {}, refused: [], verdicts: [] };
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
    var out = { candidates: [], why: null, at: s && typeof s.at === 'number' ? s.at : null };
    if (!s || typeof s !== 'object') return out;
    took(st, held);
    var app = typeof s.app === 'string' ? s.app : null;
    if (s.screen !== 'uber.planner') {
      if (app) st.epoch[app] = (st.epoch[app] || 0) + 1;
      else Object.keys(st.epoch).forEach(function (a) { st.epoch[a] += 1; });
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

  /* The reason the planner read at `at` gives the order no end, for the
   * planner line the scanner sends after that read's sighting (both carry the
   * read's `at`); undefined when no sighting of that read was seen. */
  function verdictFor(st, at) {
    for (var i = st.verdicts.length - 1; i >= 0; i--) {
      if (st.verdicts[i].at === at) return st.verdicts[i].why;
    }
    return undefined;
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

  return { RANK: RANK, FIELDS: FIELDS, STITCH_MS: STITCH_MS, PAGES_MAX: PAGES_MAX,
           cardFields: cardFields, fieldsOf: fieldsOf, outranks: outranks,
           plannerPickup: plannerPickup, forgetPlanner: forgetPlanner,
           dropoff: dropoff, file: file, fileCard: fileCard,
           plannerDestination: plannerDestination, plannerLoneDropoff: plannerLoneDropoff,
           keyOf: keyOf, placements: placements, linked: linked,
           fresh: fresh, took: took, sighting: sighting, pending: pending,
           verdictFor: verdictFor, plannerRowDue: plannerRowDue,
           cardSeen: cardSeen, heldOwnCard: heldOwnCard, holdIdOf: holdIdOf };
}));
