/* What the offer card says, in the words both panels use — the full rig's
 * live.html and the lite edition's lite/lite.html.
 *
 * WHY A FILE OF ITS OWN. The two pages are drawn apart on purpose (lite's
 * header says why: a Zero 2 W should not parse ten thousand lines of map to
 * paint one card), and until this file each carried its own copy of the few
 * sentences they share. They had drifted: lite knew "pay, no time" and the
 * clipped payout but not "no pay read", so a card whose payout the box cut
 * off was WAITING FOR AN OFFER on lite with "camera ok · no card" under it,
 * while the full panel at least said the reason in small type. CLAUDE.md's
 * rule for lite is that it may turn things off and never gets its own copy of
 * anything that decides what an offer pays; the same goes for what the card
 * says about it. So the words and the two raw figures are worked out here,
 * once, and both pages ask.
 *
 * WHAT IS NOT HERE. Nothing in this file decides anything. The verdict, the
 * rate, the doubts and every money rule (CENTS_LOST, unsure_payout,
 * money_is_clipped, the rescue rules) are the scanner's, and arrive on the
 * wire finished. These functions read a finished reading and say what of it
 * may be shown. The raw $/hr and $/mi are display figures for checking the
 * card against the phone; they feed no verdict, colour, state or rule
 * (AUDITS.md, Settled: no $/mile rules and no payout floors).
 *
 * A UMD like advice.js and map-view.js, touching no browser global at load,
 * so rpi/test_lite.py and the node suites can ask it directly.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CardWords = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // What a reading with nothing offer-like on it is said as. Named, because
  // live.html's render() asks whether that is what the last reading came to:
  // a read starting over a screen that has just read as no offer is the rig
  // looking again, not a card being priced.
  var NO_OFFER_SAID = 'scanner running, no offer on screen';
  // The screens a phone shows for an order it has taken, as OP.screen_type
  // names them: never an offer card. See noVerdictSaid.
  var TAKEN_SCREENS = ['uber.nav', 'uber.planner', 'uber.pickupNav', 'dd.deliver', 'dd.pickup'];

  // The card's word when a reading has part of an offer on it and no payout
  // the rig will price. Not WAITING FOR AN OFFER, which is what the card said
  // there and what it says over a blank phone: the panel audit of Nov 2026
  // measured the two screens identical but for a 19px grey line under the
  // card, so a glance read "waiting" and did not look at the phone with an
  // offer on it. Not a verdict either — no fill, no rate, no figures, nothing
  // recorded — only where to look. Silence is still never an accept; this is
  // the opposite of reading it as one.
  var CHECK_THE_PHONE = 'CHECK THE PHONE';

  // After the verdict word while the read is not settled (`locked` and
  // `whole`, live.html's `settled`). It was " ?", and "?" was then three
  // things on one panel: this, the doubt mark of CHECK THE PAY, and the
  // question on the Took button. "?" is now the panel's mark for "check this"
  // (CHECK …, PAY ?); this says the read is still coming in, as "…" already
  // says it on the Took and Drop buttons while their press is under way.
  // A mark and not the word READING, which the panel audit proposed: one
  // character, as the "?" was, because "≈ CLOSE CALL ?" was measured at 201px
  // of the 3.5" hat's 208px card, and lite's word at 480x320 has no room for
  // seven more letters either. The notice under it says it in words whenever
  // the journey may be short (STILL READING · may look better than it is).
  var UNSETTLED = ' …';

  // The two figures' labels, the same on both panels, so a driver who has
  // seen both reads the box one way. Lite said "net / mile" here while the
  // full panel said "$/mi" for pay ÷ miles: both true, and the same box read
  // two ways.
  var RAW_HOUR_LABEL = 'raw $/hr';
  var PER_MILE_LABEL = '$/mi';

  // What a reading with no verdict in it DID read, in words and no figures.
  //
  // Every one of them used to get "scanner running, no offer on screen", which
  // is a claim about the phone this page has no way to know. On 8 Oct an Uber
  // Est. delivery card sat square in front of the camera: the card box cut
  // its payout in half, the reader got "Includes expected tip", the deadline,
  // the distance and both addresses, and the panel told the driver there was
  // no offer. A reading carries what it got — `pay`, `minutes`, `deliverBy`,
  // `miles`, `places` and `clipped` are all on every message emit() sends —
  // so this says what was got, and the one thing the driver can do about it.
  //
  // `clipped` first, because it is the one case where the rig KNOWS the box
  // cut a card: the reader found a payout flush against the box's top edge
  // and threw the whole parse away for it (pipeline.money_is_clipped), so the
  // reading arrives as empty as one of a blank screen. A payout is the rig's
  // own test for a card (`card_on_screen` in rpi/scan_pi.py), so "pay" is said
  // outright here.
  //
  // NOT "a card is in view" for the rest, which is the obvious sentence and
  // is not true either. Of the corpus's 19 texts that read no payout, 18 read
  // a time, a distance or a place, and 12 of those are not cards at all: the
  // app's zone prompt (5) and Uber's map screen (7). The panel cannot tell a
  // card missing its pay from a screen that never had one, so it says the
  // half it knows, with the remedy hedged on the half it does not, and the
  // hedge is what keeps it true over the map.
  //
  // A pay with no verdict has no time to divide it by: every reading that
  // reaches this with a pay read no time at all, but for a deadline rate()
  // could not count down, and "no time" is the truth about those as well. An
  // unsure payout (scan_pi.unsure_payout) reaches the panel with its payout
  // taken off, so it is "no pay read" here, which is true of it.
  //
  // No figure, in any: no verdict was reached, and a number on this line is
  // one the driver would read as the reading's. The box, not the card box: a
  // driver who pressed No card box reads the whole screen box, and the
  // control that fixes either is ▣ Set box.
  //
  // Each sentence is no wider than the one it replaced, in the page's own
  // font on every panel (rpi/test_layout.py), because live.html's trackNote()
  // appends to the line under the card.
  //
  // `ends` is map-view.js's MV.ends where the page has it (live.html, whose
  // rule for what a reading named it is; rpi/test_lint.py holds the page to
  // it). Only whether anything was named is asked here, and MV.ends answers
  // the two ends or else every name, so a page without map-view.js (lite)
  // gets the same answer from the names themselves.
  function noVerdictSaid(r, ends) {
    if (!r) return NO_OFFER_SAID;
    if (r.clipped) return 'pay at the box edge — not trusted';
    // The app's own idle screen, by its own words (OP.NOT_AN_OFFER, sent as
    // `notAnOffer`). Whatever else the read picked off the map is not part of
    // a card: the corpus's Uber online frame reads the day's takings as a
    // payout and said "pay, no time". Before the pay test, which it overrules.
    if (r.notAnOffer) return NO_OFFER_SAID;
    // ...and a screen of an order already taken, by the reader's own type of
    // it (`screen`, OP.screen_type): Uber's navigation and Trip Planner,
    // DoorDash's deliver and pickup screens. Without this the map's "3 min ·
    // 1.1 mi" and "Expected by" said "no pay read — box may cut it off" for
    // the whole of every delivery (the owner's snaps of 12 Nov). No payout
    // only: a figure read off one of these is still said as one.
    var paid = typeof r.pay === 'number' && r.pay > 0;
    if (!paid && TAKEN_SCREENS.indexOf(r.screen) !== -1) return NO_OFFER_SAID;
    if (paid) return 'pay, no time — box may cut it off';
    var named = typeof ends === 'function' ? ends(r)
      : (r.places || []).filter(Boolean);
    if ((typeof r.minutes === 'number' && r.minutes > 0)
        || (r.deliverBy !== null && r.deliverBy !== undefined)
        || typeof r.miles === 'number'
        || (named && named.length)) {
      return 'no pay read — box may cut it off';
    }
    return NO_OFFER_SAID;
  }

  // The reason to look at the phone, or null when there is none. The card
  // says CHECK THE PHONE over it and this line under it.
  //
  // Not every sentence above but the no-offer one: only those with something
  // of an OFFER CARD in them — a payout the box cut (`clipped`), a payout with
  // no time, or no payout but a deadline or a place, which are an offer's own
  // words. A time or a distance alone is not: that is what Uber's map screen
  // reads as (its route chips, "3 min (1.0 mi)") and what the app's zone
  // prompt reads as (its average wait as minutes), and a CHECK THE PHONE over
  // a turn arrow would send the driver to the phone for nothing, every few
  // seconds of every delivery. Those keep the hedged sentence in small type
  // under the card, where it was. A card that lost its payout AND its places
  // reads the same as a map; it is WAITING FOR AN OFFER as it always was, so
  // nothing that said CHECK before says less now.
  function phoneSaid(r, ends) {
    var said = noVerdictSaid(r, ends);
    if (said === NO_OFFER_SAID) return null;
    if (r.clipped || (typeof r.pay === 'number' && r.pay > 0)) return said;
    var named = typeof ends === 'function' ? ends(r)
      : (r.places || []).filter(Boolean);
    return ((r.deliverBy !== null && r.deliverBy !== undefined) || (named && named.length))
      ? said : null;
  }

  function num(n) { return typeof n === 'number' && isFinite(n); }

  // The card's pay over its time, nothing taken off: the raw $/hr. The
  // scanner's own `grossPerHour` (offer_parser rate(): pay over the minutes
  // the net rate is divided by, so the net headline and this are the same
  // division with and without the car's cost), else pay over the card's own
  // minutes for an older payload.
  //
  // null — drawn "--" — where it cannot honestly be had:
  //   - no verdict, or a withheld one (`state` 'doubt', every reason): the
  //     headline is blanked there because the pay or the time is the one the
  //     reader does not believe, and a raw rate is the same division of the
  //     same two figures. Not even CHECK THE TIME, which $/mi survives: this
  //     figure is divided BY the time the reader refused.
  //   - no minutes on the reading, whatever `grossPerHour` says: never a time
  //     estimated from the distance, nor the other way.
  function rawPerHour(r) {
    if (!r || !r.ready || r.state === 'doubt') return null;
    var over = num(r.cardMinutes) ? r.cardMinutes : r.minutes;
    var billed = num(r.billedMinutes) ? r.billedMinutes : over;
    if (!num(over) || !(over > 0) || !num(billed) || !(billed > 0) || !num(r.pay)) return null;
    var v = num(r.grossPerHour) ? r.grossPerHour : r.pay / (over / 60);
    return num(v) ? v : null;
  }

  // The card's pay over its miles, nothing taken off: journal.html's
  // payPerMile, the same rule (a distance of at least a tenth of a mile).
  // RAW, because this box is checked against the phone, where $14.00 over
  // 7.0 mi divides to $2.00 — the reading's own `perMile` is net of the car's
  // cost and printed $1.70 between those two boxes.
  //
  // It survives ONE of the six doubts, because `doubt` names which figure
  // the reader cannot believe and only one leaves this one standing:
  //   pay    the payout is outside SANE_PAY: the same impossible number,
  //          divided.
  //   rate   pay over time is impossible and either half could be the liar.
  //   speed  miles over time is impossible; the miles could be the liar.
  //   leg    part of the journey was never timed, so the distance is partial.
  //   screen not an offer at all.
  //   time   the MINUTES are outside SANE_MINUTES — the one case where the
  //          pay and the distance have each passed their own test, and this
  //          is built from those two and nothing else.
  // `milesUncertain` refuses it whatever the verdict (CEILING · miles
  // unreadable), for the reason `perMile` is null there: a rate off a
  // distance the reader itself doubts is a confident number with nothing
  // behind it. No distance on the card (DoorDash's deadline cards) is none.
  function rawPerMile(r) {
    if (!r || !r.ready) return null;
    if (r.state === 'doubt' && r.doubt !== 'time') return null;
    if (r.milesUncertain) return null;
    if (!num(r.pay) || !num(r.miles) || !(r.miles >= 0.1)) return null;
    var v = r.pay / r.miles;
    return num(v) ? v : null;
  }

  // "incl. $2.93 Boost" (Uber's Boost+) or "incl. $2.00 Peak Pay" (DoorDash),
  // under the pay: the part of the payout the card says came from the app's
  // own top-up, off the parser's `boost` (offer_parser boost_of). The owner's
  // request of Nov 2026, from the evening's Boost+ cards. Display only: it
  // is part of the PAY figure beside it, never added to it, and reaches no
  // verdict, rate or rule.
  //
  // null — nothing drawn — where there is no verdict, on every withheld one
  // (the pay or the time it would qualify is the one the reader refused, as
  // for the raw $/hr; CHECK THE TIME too, which has no figure to sit beside
  // honestly once the headline is blanked), with no payout, and where the
  // amount is not less than the payout it is said to be part of.
  function boostSaid(r) {
    if (!r || !r.ready || r.state === 'doubt') return null;
    if (!num(r.boost) || !(r.boost > 0) || !num(r.pay) || !(r.boost < r.pay)) return null;
    return 'incl. $' + r.boost.toFixed(2) + (r.app === 'doordash' ? ' Peak Pay' : ' Boost');
  }

  // "target $25": what the verdict word was judged against, the driver's own
  // target off the reading (rate()'s `target`, echoed with `band` so a verdict
  // carries the line it was held to). Said beside the word on ACCEPT, CLOSE
  // CALL and PASS alike (the owner, Nov 2026); null on a withheld verdict,
  // which was judged against nothing, and with no verdict. Whole dollars
  // where the target is whole, as the driver typed it; cents where it is not.
  function targetSaid(r) {
    if (!r || !r.ready || r.state === 'doubt') return null;
    if (r.state !== 'go' && r.state !== 'warn' && r.state !== 'no') return null;
    if (!num(r.target) || !(r.target > 0)) return null;
    return 'target $' + (r.target % 1 === 0 ? String(r.target) : r.target.toFixed(2));
  }

  return {
    NO_OFFER_SAID: NO_OFFER_SAID,
    TAKEN_SCREENS: TAKEN_SCREENS,
    CHECK_THE_PHONE: CHECK_THE_PHONE,
    UNSETTLED: UNSETTLED,
    RAW_HOUR_LABEL: RAW_HOUR_LABEL,
    PER_MILE_LABEL: PER_MILE_LABEL,
    noVerdictSaid: noVerdictSaid,
    phoneSaid: phoneSaid,
    rawPerHour: rawPerHour,
    rawPerMile: rawPerMile,
    boostSaid: boostSaid,
    targetSaid: targetSaid
  };
}));
