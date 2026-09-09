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
 * here waits on the network or loses anything when it is absent.
 *
 * Browser only, like ui.js and scan.js: served, never run under Node. */
var JournalClient = (function () {
  'use strict';

  var KEY = 'uberscan.unsent.v1';

  function load() {
    try {
      var q = JSON.parse(localStorage.getItem(KEY));
      return Array.isArray(q) ? q : [];
    } catch (e) { return []; }
  }

  function save(q) {
    try { localStorage.setItem(KEY, JSON.stringify(q)); } catch (e) {}
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
      minutes: parsed.minutes,
      miles: parsed.miles > 0 ? parsed.miles : null,
      items: parsed.items || null,
      shop: parsed.shop ? true : null,
      legs: parsed.legs || 0,
      hasTotal: !!parsed.hasTotal,
      places: parsed.places && parsed.places.length ? parsed.places : undefined,
      text: parsed.text || undefined,
      perHour: rate.perHour, grossPerHour: rate.grossPerHour, perMile: rate.perMile,
      cost: rate.cost, billedMinutes: rate.minutes,
      state: rate.state, doubt: rate.doubt || null,
      target: settings.target, band: settings.band, costPerMile: settings.costPerMile,
      whole: true, settled: true, locked: true, suspect: false,
      milesCorrected: false, milesUncertain: false
    };
    for (var k in extra) {
      if (k !== 'prefix' && Object.prototype.hasOwnProperty.call(extra, k)) out[k] = extra[k];
    }
    return out;
  }

  /* Remember a row until a server has it. */
  function keep(r) {
    var q = load();
    q.push(r);
    save(q);
    return r;
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
        // in flight stays for the next flush.
        save(load().filter(function (r) { return ids.indexOf(r.id) === -1; }));
        return { ok: true, sent: ids };
      })
      .catch(function () { return { ok: false, sent: [] }; })
      .then(function (result) { flying = null; return result; });
    return flying;
  }

  return { row: row, keep: keep, pending: pending, flush: flush, KEY: KEY };
})();
