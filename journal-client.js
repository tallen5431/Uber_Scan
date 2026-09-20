/* One door to the journal for the offers a browser makes.
 *
 * Two pages produce offers without the rig's camera: the keypad, where the
 * driver types one, and the phone's own scanner, where the phone's camera
 * reads one. Both kept what they made in the browser and nowhere else — the
 * keypad in a list capped at a hundred, the scanner not at all — and the
 * night the rig cannot read is the night those two get used. So the offers
 * most likely to be missing from the record were the ones made by hand.
 *
 * This is the shared piece: the row, shaped like a reading so nothing
 * downstream needs a special case for it; a queue of rows that have not yet
 * reached a server; and one flush through /api/journal/ingest, the door the
 * sync uses, which stores a row once however often it is sent. An app on a
 * phone with no rig near it is the normal case for both pages, and nothing
 * here waits on the network when it is absent.
 *
 * It used to say "or loses anything", and that was a claim the code did not
 * honour. The queue had no ceiling of its own and `save` swallowed every
 * storage failure, so the queue grew until the browser refused it and then
 * every further offer vanished — `keep` still handed the caller back a row,
 * `pending` still said the row was not waiting, and the phone buzzed for a
 * card that had gone nowhere. Both ends of that are fixed below: there is a
 * ceiling, chosen from the owner's own week rather than picked, and when a row
 * cannot be kept the caller is told so rather than reassured. What the pages
 * do with being told is theirs; what is no longer possible is not being told.
 *
 * Browser only, like ui.js and scan.js: served, never run under Node. */
var JournalClient = (function () {
  'use strict';

  var KEY = 'uberscan.unsent.v1';

  /* How much of a reading is kept, matching rpi/journal.py's TEXT_KEPT.
   *
   * The second copy of a number, which is normally the thing this project
   * refuses — but the two ends cannot import from each other and the
   * alternative is no cap at all on this end, which is what was here. The
   * original and the twenty lines of reasoning behind the value are at
   * rpi/journal.py:707-725; in short, 220 was tried and 99 of 309 cards sat
   * exactly on it, cut off at the end where the pickup, the dropoff and the
   * second leg live. rpi/test_lint.py holds the two in step.
   *
   * Inert on an ordinary card: over the 152-card corpus the stored text runs
   * to a median of 63 characters and a maximum of 240. It is there for the
   * frame whose crop takes in the screen behind the card, where a reading can
   * run to two thousand characters — and where, uncapped, the phone wrote 1,998
   * of them into a row the rig would have written 600 of. */
  var TEXT_KEPT = 600;

  /* The Pi's `_round`, in the language the phone is written in.
   *
   * Kept to the same two places for money and one for minutes as
   * rpi/journal.py, so that a row written on the phone and a row written on the
   * rig are the same shape in the same file. Null, undefined and the non-finite
   * come back untouched: rounding a missing figure is arithmetic on nothing,
   * and arithmetic on nothing is NaN — which JSON turns into `null` on the way
   * to disk, so a row carrying it reads afterwards as a row that simply had no
   * distance. A guard here is the only place that can tell those apart.
   *
   * Math.round is not Python's round() — Python rounds a half to even, so
   * round(0.125, 2) is 0.12 — but rpi/offer_parser.py's round2 does not use it
   * either: it uses floor(v * 100 + 0.5) / 100, which is what Math.round does
   * to a positive number. On a negative half they still part company, and a
   * half-cent on a rate nobody reads past two places is not worth a second
   * implementation of rounding to keep in step. */
  function places(v, by) {
    if (typeof v !== 'number' || !isFinite(v)) return v;
    return Math.round(v * by) / by;
  }

  function money(v) { return places(v, 100); }
  function tenths(v) { return places(v, 10); }

  function load() {
    try {
      var q = JSON.parse(localStorage.getItem(KEY));
      return Array.isArray(q) ? q : [];
    } catch (e) { return []; }
  }

  /* How many rows may wait here.
   *
   * There was no ceiling, which is only sane if the store has none either, and
   * it has: localStorage is about 5MB an origin and charges for UTF-16, so
   * roughly 2.6 million characters — shared with the map page's geocode cache,
   * the keypad's own hundred-entry list and the settings, all on this origin.
   *
   * Measured on the owner's real week — 1,166 offers, 13-20 Sep 2026, put
   * through row() one at a time — a stored row is 831 bytes of JSON at the
   * mean and 987 at the ninetieth. So the old, uncapped queue met its ceiling
   * at about 3,100 rows, and met it the way this project's second fault class
   * describes: everything after that disappeared with nothing saying so.
   * (Ingest's own MAX_SYNC_BODY of 8MB is a further ceiling at about 10,100
   * rows, and is never reached, because the browser's refusal comes first.
   * Worth knowing before anyone raises one of the two on its own.)
   *
   * A thousand is 811KiB serialised, about 1.6MB once the store doubles it —
   * a third of the budget, which leaves the cache and the rest their share.
   * In offers it is six days of the owner's heaviest scanning with a rig that
   * is never once reachable, on the page that exists for the night the rig
   * cannot read. Nothing real gets near it; the ceiling is a backstop, and the
   * point of having one is that the backstop says what it did. */
  var QUEUE_CAP = 1000;

  /* What the queue could not do, for the pages to say out loud.
   *
   * `dropped` is deliberate: rows shed at the ceiling above, oldest first,
   * with `through` the time of the newest one shed, so a page can name the
   * moment the record now starts at rather than just a number. `lost` is the
   * store refusing a row outright, and is the row the driver was looking at
   * when it happened.
   *
   * That refusal is nearer than the ceiling is. The ceiling is weeks of
   * driving away; a browser told to block site data refuses the very first
   * row, today, with the rig up and answering. Neither `file://` nor a
   * private window reaches it — both of those have a working localStorage —
   * so nothing here or on the glass names a cause. It says what is true of
   * this phone and lets the driver find out why.
   *
   * In memory only, on purpose: the case this reports is a store that will not
   * take a write, and a counter written to that same store would be the first
   * thing to go. The page is open in front of the driver when it matters. */
  var shed = 0, shedThrough = 0, refused = 0;

  /* Whether the last flush reached a server: null until one has been tried.
   *
   * This is what makes a backlog readable. A row waiting because the flush it
   * started is still in the air is Tuesday; the same row waiting because the
   * rig did not answer is the thing worth a word on screen, and the count
   * alone cannot tell them apart. */
  var landed = null;

  /* The queue's length without parsing the queue to find out.
   *
   * scan.js asks on every rendered frame, and load() at the ceiling is 811KiB
   * of JSON.parse — per frame, on a phone, on the path that has to keep up
   * with the camera. Counted once on the first ask and kept in step by the two
   * places that write, both of which already hold the array. A second tab
   * writing underneath this one would leave it stale; that is a page refresh
   * away from right and is not what the number is for. */
  var count = null;

  function save(q) {
    // Reports rather than swallows. Everything above depends on this being
    // the truth about whether the write landed.
    try { localStorage.setItem(KEY, JSON.stringify(q)); return true; }
    catch (e) { return false; }
  }

  /* An offer as the journal would have written it.
   *
   * `parsed` is the card as read or typed — what OfferParser.parse returns,
   * or the keypad's three figures in the same shape — and `rate` is what
   * OfferParser.rate made of it, which is the same arithmetic the rig's rows
   * carry. An `id` and a `seq` so the ingest door can tell it from a copy of
   * itself; `whole` and `settled` because a typed figure is complete and
   * still and a locked reading has been agreed on; and NO `kind`, because the
   * offers page drops kinds it has not heard of and this is an offer. `extra`
   * says what made it — `typed: true` or `browser: true` — and `prefix`
   * keeps their ids apart from the rig's. */
  function row(parsed, rate, settings, extra) {
    extra = extra || {};
    var at = Date.now();
    var out = {
      v: 1,
      id: (extra.prefix || 'b') + at.toString(36) + Math.random().toString(36).slice(2, 8),
      seq: 1, at: at, firstAt: at,
      pay: parsed.pay,
      // The minutes and the miles the VERDICT was reached with, not the ones
      // the parse came out with. rpi/journal.py:735-743 takes both from rate()
      // and says why; this was the second copy of that rule and it had drifted
      // on exactly those fields.
      //
      // They are not the same numbers. On a real DoorDash card — $41.11,
      // "98 mi", "Deliver by 7:15 PM", read at 18:57 — the phone showed
      // $127.23/hr over 18 minutes and 9.8 miles, having recovered the lost
      // decimal and worked the duration out from the deadline. The row stored
      // minutes null and miles 98: a 98-mile job with no duration, at a rate
      // neither figure produces. A row that cannot be reconciled with itself is
      // the one thing the journal exists to avoid.
      minutes: (typeof rate.cardMinutes === 'number') ? rate.cardMinutes
                                                      : parsed.minutes,
      miles: (typeof rate.miles === 'number' && rate.miles > 0) ? rate.miles
             : (parsed.miles > 0 ? parsed.miles : null),
      // Which of the two the minutes above are, so a reader months later can
      // tell a stated duration from the time left on a deadline. journal.html
      // prints its "Time from" line off this.
      //
      // `cardMinutes` used to sit here as well, and this comment sat over it
      // saying journal.html printed one or the other off it. journal.html
      // contains no occurrence of `cardMinutes` at all — it reads
      // `fromDeadline`, which is what the sentence is actually about — and the
      // key's expression was character-for-character the `minutes` expression
      // eight lines up, so no input could ever make the two differ. A second
      // answer to a question nothing asked, under a comment naming a reader
      // that does not exist.
      //
      // It also made the two writers of one append-only file disagree about
      // the row's shape: rpi/journal.py folds cardMinutes INTO `minutes` (see
      // the "minutes the verdict was actually made over" comment there) and
      // writes no such key.
      //
      // On the READING payload the distinction is real and must stay —
      // scan_pi.emit() sends `minutes` and `cardMinutes` as different claims,
      // and they diverge on every deadline card. This is the stored row, which
      // has already chosen between them one line up.
      fromDeadline: !!rate.fromDeadline,
      items: parsed.items || null,
      shop: parsed.shop ? true : null,
      legs: parsed.legs || 0,
      hasTotal: !!parsed.hasTotal,
      places: parsed.places && parsed.places.length ? parsed.places : undefined,
      // ...and which of them is which END, which the Pi's own rows carry and
      // these did not.
      //
      // `places` is the list; `pickup` and `dropoff` are the two facts anything
      // downstream actually asks for. Both map surfaces filter on them — the
      // offers page puts a row's map controls behind `r.pickup`/`r.dropoff`,
      // and map.html's whole working set is `o.pickup || o.dropoff` — so every
      // offer read on the PHONE was invisible to both, with its places sitting
      // in the row all along.
      //
      // Which is the worst half to lose: the phone's scanner exists for the
      // nights the rig cannot read, so the rows that only it produced are the
      // ones with no other record of where the job went.
      //
      // parse() already decides this, and the Pi calls the same two functions
      // on the same field. Taken from `parsed` rather than recomputed here, so
      // there is no second rule to drift.
      pickup: parsed.pickup || undefined,
      dropoff: parsed.dropoff || undefined,
      // What the reader read, with its line breaks, the way the rig writes it.
      //
      // This was `parsed.text` — the FLATTENED form, and uncapped. Three
      // separate things wrong with one expression, all of them the same shape
      // as the drift the comment below this one describes.
      //
      // `rawText` first, because flattening is irreversible and throws away
      // which line each figure was on. offer-parser.js keeps `rawText` beside
      // `text` deliberately and says so; rpi/journal.py:886 stores it for the
      // same reason, recorded there as "the last two parser fixes had to
      // rediscover [line structure] from punctuation because it had been
      // discarded before anything could look at it". Measured on one card:
      // rawText carries 4 newlines, `text` carries 0, and journal.html renders
      // this column inside a <pre> — the one element whose whole job is to keep
      // them. So rig rows showed the card and phone rows showed one run-on
      // line, in the same file, on the same page. server.js's CSV says of this
      // column "It is what the reader read, line breaks and all", which was
      // false for every phone row.
      //
      // Safe to change: re-parsing either form gives identical results in every
      // field but `rawText` itself, measured across the corpus, so nothing
      // computed from a stored row moves. Ingest de-duplicates on id and seq
      // (server.js key()), not on content, so an already-stored row cannot come
      // back looking new.
      //
      // ...and capped, because the phone's scanner exists for the nights the
      // rig cannot read and its rows are the ones with no second copy.
      text: (parsed.rawText || parsed.text || '').slice(0, TEXT_KEPT) || undefined,
      // Rounded, because rpi/journal.py rounds. The same field, written by the
      // same project, into the same file, under two rules — and the second rule
      // was simply absent rather than different, which is the shape that drifts
      // without anybody noticing. Measured on one card ($8.83, 23 min, 4.6 mi):
      // the Pi wrote 19.43 and the phone wrote 19.434782608695652 into the
      // column beside it. The pages hide it, because they round for display, so
      // the only place a person meets the stored figure is the CSV the README
      // calls "a CSV of everything" — and anything that later groups or diffs
      // on those values gets two populations that never compare equal.
      //
      // Two decimals for money and one for minutes, matching _round()'s callers
      // on the Python side field for field.
      perHour: money(rate.perHour), grossPerHour: money(rate.grossPerHour),
      perMile: money(rate.perMile), cost: money(rate.cost),
      billedMinutes: tenths(rate.minutes),
      state: rate.state, doubt: rate.doubt || null,
      target: settings.target, band: settings.band, costPerMile: settings.costPerMile,
      whole: true, settled: true, locked: true, suspect: false,
      // Reported, not asserted. These were hardcoded false, which is a claim
      // about the reading made without looking at it: the card above really
      // did have its decimal recovered, and the row said it had not.
      milesCorrected: !!rate.milesCorrected,
      milesUncertain: !!rate.milesUncertain
    };
    for (var k in extra) {
      if (k !== 'prefix' && Object.prototype.hasOwnProperty.call(extra, k)) out[k] = extra[k];
    }
    return out;
  }

  /* Remember a row until a server has it. Returns the row, or null if this
     browser would not take it — which the caller has to look at, because the
     only other thing that knows is the driver, and only if a page says so.

     The ceiling sheds from the front, so what survives is the most recent
     QUEUE_CAP offers. Two reasons for that direction rather than refusing the
     new one: the recent rows are the ones the offers page's medians and the
     shift advice are actually about, and an offer disappearing from the record
     while the driver watches it be judged is the worse surprise of the two.
     Either way it is counted and said.

     A store that refuses the write sheds nothing. `save` not landing means the
     queue on disk is exactly as it was, so the rows are all still there and
     only the row in hand is lost — the honest account of what happened, and it
     keeps the promise the header makes about rows that did reach the queue.
     Shedding to make room would trade a stretch of the record that cannot be
     rebuilt for one more row, in a situation the driver has to act on anyway.

     Nothing here reports a save that fails AFTER a send, in flush below. That
     write is strictly smaller than what the store already holds, so a store
     that takes the one takes the other. A store that refuses everything
     refuses both, and there the queue is empty and there is nothing to
     report. A check that cannot fail is not a check. */
  function keep(r) {
    var q = load();
    q.push(r);
    var over = [];
    while (q.length > QUEUE_CAP) over.push(q.shift());
    if (!save(q)) { refused++; return null; }
    count = q.length;
    for (var i = 0; i < over.length; i++) {
      shed++;
      var at = over[i] && over[i].at;
      if (typeof at === 'number' && isFinite(at) && at > shedThrough) shedThrough = at;
    }
    return r;
  }

  /* How many rows are waiting for a server. */
  function waiting() {
    if (count === null) count = load().length;
    return count;
  }

  /* Whether the last flush reached a server. Null until one has been tried. */
  function reachable() { return landed; }

  /* What the queue could not do, or null when it has done everything asked of
     it — so a page can lead with this and say nothing on an ordinary night. */
  function trouble() {
    if (!shed && !refused) return null;
    return { lost: refused, dropped: shed, through: shedThrough || null };
  }

  function pending(id) {
    return load().some(function (r) { return r.id === id; });
  }

  /* Send everything kept, oldest first. Resolves to { ok, sent: [ids] } and
     never rejects: a rig out of reach is not an error here, it is Tuesday.
     One flight at a time, so two pages' worth of LOG presses do not race
     each other into sending the same rows twice — harmless at the far end,
     which stores them once, but not worth the bytes. */
  var flying = null;

  function flush() {
    if (flying) return flying;
    var q = load();
    if (!q.length) return Promise.resolve({ ok: true, sent: [] });
    var body = q.map(function (r) { return JSON.stringify(r); }).join('\n') + '\n';
    flying = fetch('/api/journal/ingest', {
      method: 'POST', body: body,
      headers: { 'Content-Type': 'application/x-ndjson' }
    })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(res.status); })
      .then(function (answer) {
        if (!answer || answer.ok !== true) throw new Error('refused');
        var ids = q.map(function (r) { return r.id; });
        // Only what was sent comes off the queue: a row kept while this was
        // in flight is still there for the flight below.
        var left = load().filter(function (r) { return ids.indexOf(r.id) === -1; });
        save(left);
        count = left.length;
        landed = true;
        return { ok: true, sent: ids };
      })
      .catch(function () { landed = false; return { ok: false, sent: [] }; })
      .then(function (result) {
        flying = null;
        // A row kept while that was in flight used to wait for the next
        // flush — which is the next lock, or the next time the page opens,
        // and on a phone in the car that is the next card or tomorrow. The
        // rig was answering the whole time. It goes now, and the one answer
        // names it too, so a page marking rows sent sees it go. Only after a
        // flight that landed: after one that did not, the rig is out of
        // reach and the next lock is the right time to try again.
        if (result.ok && load().length) {
          return flush().then(function (more) {
            return { ok: more.ok, sent: result.sent.concat(more.sent) };
          });
        }
        return result;
      });
    return flying;
  }

  return { row: row, keep: keep, pending: pending, flush: flush, KEY: KEY,
           waiting: waiting, reachable: reachable, trouble: trouble,
           QUEUE_CAP: QUEUE_CAP };
})();
