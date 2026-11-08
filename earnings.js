/* What the app actually paid for an order, read off its own earnings screen,
 * and which order on file it was for.
 *
 * The owner, 7 Nov 2026: "For future work it would be a good idea to compare
 * what uber actually paid compared to the expected pay of the order, here is a
 * screen shot of the daily summary page." ... "That is a good idea to upload
 * screenshots as it takes time for it to settle. Can it automatically figure
 * out which order it belongs to in the journal?"
 *
 * The card says what an order will pay; Uber's Earnings Activity says what it
 * did, a while later, and a tip can take hours to land on it. Nothing on the
 * rig can read that screen while driving and nothing needs to: the driver
 * takes screenshots of the day whenever, and uploads them on the offers page
 * (server.js, /api/earnings). This file is the deciding behind that upload,
 * with no I/O, so the server, the reports and the suites share one answer:
 *
 *   1. READ.  parse(text) turns tesseract's text of one screenshot into the
 *      day it shows and one entry per trip: when it finished, what it paid,
 *      the tip (a figure, or still "processing"), the kind, how long and how
 *      far Uber says it was, the pickup as Uber names it and the dropoff's
 *      street and town. App-aware: PARSERS.uber reads Uber's screen, and
 *      PARSERS.doordash is where DoorDash's goes — no DoorDash earnings
 *      screenshot has been seen yet, so it reads nothing and says so.
 *   2. KEEP.  The same trip turns up again and again — screenshots of one day
 *      overlap as it is scrolled, and the day is uploaded again once tips
 *      settle. sameEntry/mergeEntry keep it one entry, its tip's story kept
 *      ("seen pending at 6:10 PM, $4.00 at 9:30 PM").
 *   3. MATCH. matchDay puts each entry against the orders the rig has on file
 *      for that day — the order records server.js writes (orderRow), and for
 *      days before them the runs the report rebuilds from took/drop rows — and
 *      takes a match only when it is clearly the best: a score over a
 *      threshold, a margin over the runner-up, one entry per order. Anything
 *      less is left for the driver to pick from the top few, on the page; an
 *      entry with nothing near it is "no order on file" (the rig was off).
 *
 * DESCRIPTIVE, AND NOTHING ELSE. What an order paid is a record beside its
 * card. Nothing on the rig reads this file: no verdict, line, target or panel
 * changes because Uber paid more or less than the card (the owner's settled
 * decision for this feature: "reports are descriptive; nothing changes what
 * the rig decides").
 *
 * A UMD like advice.js, no browser global touched at load and no dependency,
 * so server.js requires it and the suites run it under plain node. */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Earnings = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* --- reading the screen ---------------------------------------------------
   *
   * What tesseract makes of the owner's screen (rendered from an invented copy
   * of its layout by rpi/testearnings.py, and run with `--psm 4`, which keeps
   * a line's right-hand time on its own line's row):
   *
   *     Sat, Nov 7
   *     $2.00 5:40 PM
   *     Delivery - 39 min 33 sec - 12.30 mi
   *     Tip processing
   *     Mock Rd                          <- whatever the map's labels became
   *     Pretend Pizza (Faketown)
   *     Placeholder Ct, Faketown, GA, USA
   *
   * The middle dot reads as "-", ":" or "." and sometimes as nothing, so the
   * separators below are a class, not a character. */

  var MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var MONTH_RE = '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\\.?';
  var DAY_RE = '(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\\.?';

  // The day heading, "Sat, Nov 7": the screen's own name for the day, and the
  // most reliable of the three ways it says the date (the chip is small and
  // grey, and in a JPEG "11/7" came back as "17").
  var HEADING = new RegExp('^' + DAY_RE + ',?\\s+' + MONTH_RE + '\\s+(\\d{1,2})\\b', 'i');
  // ...the line under the last trip, which alone carries the year.
  var END_LINE = new RegExp('end of activit\\w*\\s+(?:during|on|for)?\\s*' + MONTH_RE
                            + '\\s+(\\d{1,2}),?\\s+(\\d{4})', 'i');
  // ...and the chip at the top, "11/7", taken only when neither is there.
  var CHIP = /^(1[0-2]|0?[1-9])\/([12]\d|3[01]|0?[1-9])$/;

  // An amount at the start of a line opens a trip's block. "$" read as "S" is
  // allowed only before a digit (so "Sat, Nov 7" is no amount), and cents are
  // required, which is the rule offer-parser.js learned the hard way for the
  // same misread. A tip line also starts with an amount, and is told apart by
  // the word "Tip" on it.
  var AMOUNT = /^(?:\$|S(?=\d))\s?(\d{1,4}[.,]\d{2})\b(.*)$/;
  // A clock time with its AM/PM: the status bar's "6:12" has none and is not
  // a trip's time. ":" read as "." is allowed; a space or a lost dot in "P.M."
  // too.
  var CLOCK = /\b(1[0-2]|0?[1-9])[:.]([0-5]\d)\s*([ap])\.?\s*m\b/i;
  // The trip's line: its kind, Uber's minutes and seconds, and its miles.
  var DETAIL = /^\s*([A-Za-z][A-Za-z &+'\/-]*?)\s*[-·•:.,=~]*\s*(\d{1,3})\s*min\w*\.?(?:\s*(\d{1,2})\s*s(?:ec)?\w*\.?)?\s*[-·•:.,=~]*\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*mi\b/i;
  var TIP_PENDING = /\btip\s+(?:is\s+)?(?:processing|pending)\b/i;
  var TIP_AMOUNT = /(?:\$|S(?=\d))\s?(\d{1,4}[.,]\d{2})\s*tip\b|\btip\b[^$\d]{0,12}(?:\$|S(?=\d))\s?(\d{1,4}[.,]\d{2})/i;
  // The dropoff line ends in a state and the country, as Uber prints every
  // dropoff ("Example Ave NE, Notaville, GA, USA"); the pickup is the line
  // straight above it, whatever the map left above that.
  var DROPOFF = /,\s*[A-Z]{2}\s*,?\s*(?:USA|US)\.?\s*$|,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$/i;

  // The text kept of any one place: what a reader made of a phone, cut where
  // server.js cuts an order record's (ORDER_TEXT_MAX is 120; these are
  // shorter, being one name or one street).
  var TEXT_MAX = 80;

  function clean(s) {
    return String(s === null || s === undefined ? '' : s).replace(/\s+/g, ' ').trim();
  }
  function cut(s) {
    var t = clean(s);
    return t ? t.slice(0, TEXT_MAX) : null;
  }
  function money(s) {
    var n = parseFloat(String(s).replace(',', '.'));
    return isFinite(n) ? Math.round(n * 100) / 100 : null;
  }
  function clockOf(line) {
    var m = CLOCK.exec(line || '');
    if (!m) return null;
    var h = parseInt(m[1], 10) % 12 + (m[3].toLowerCase() === 'p' ? 12 : 0);
    return (h < 10 ? '0' : '') + h + ':' + m[2];
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /* The year a month and day without one fall in: the latest such date not
   * more than a day and a half after `now`. A screenshot of earnings is of the
   * past, so 12/31 read on 2 Jan is last year's; the day and a half is a phone
   * a time zone ahead of the server. */
  function yearFor(month, day, now) {
    var d = new Date(typeof now === 'number' ? now : Date.now());
    var y = d.getFullYear();
    var limit = d.getTime() + 36 * 3600000;
    return new Date(y, month - 1, day).getTime() <= limit ? y : y - 1;
  }

  /* The day the screenshot shows, or null: {iso, from}. The end line's year
   * when it is there, the heading next, the chip last. */
  function dayOf(lines, now) {
    var m, i;
    for (i = 0; i < lines.length; i++) {
      m = END_LINE.exec(lines[i]);
      if (m) {
        var y = parseInt(m[3], 10);
        var mo = MONTHS.indexOf(m[1].toLowerCase()) + 1;
        var da = parseInt(m[2], 10);
        if (mo && da >= 1 && da <= 31) return { iso: y + '-' + pad2(mo) + '-' + pad2(da), from: 'end' };
      }
    }
    for (i = 0; i < lines.length; i++) {
      m = HEADING.exec(lines[i]);
      if (m) {
        var hm = MONTHS.indexOf(m[1].toLowerCase()) + 1;
        var hd = parseInt(m[2], 10);
        if (hm && hd >= 1 && hd <= 31) {
          return { iso: yearFor(hm, hd, now) + '-' + pad2(hm) + '-' + pad2(hd), from: 'heading' };
        }
      }
    }
    for (i = 0; i < lines.length; i++) {
      m = CHIP.exec(lines[i]);
      if (m) {
        var cm = parseInt(m[1], 10), cd = parseInt(m[2], 10);
        return { iso: yearFor(cm, cd, now) + '-' + pad2(cm) + '-' + pad2(cd), from: 'chip' };
      }
    }
    return null;
  }

  function isTipLine(line) {
    return TIP_PENDING.test(line) || /\btip\b/i.test(line) && TIP_AMOUNT.test(line);
  }

  /* "Make-Believe Burgers (Sample St NW & Fictional Ct)" -> the store's name
   * and what Uber put in its bracket: a town for a one-off restaurant, a
   * street corner for a branch of a chain — the part that tells two of one
   * chain apart, so it is kept and compared on its own. */
  function pickupOf(line) {
    var t = clean(line);
    if (!t) return null;
    var open = t.indexOf('(');
    if (open > 0) {
      var close = t.lastIndexOf(')');
      return { name: cut(t.slice(0, open)), detail: cut(t.slice(open + 1, close > open ? close : t.length)) };
    }
    return { name: cut(t), detail: null };
  }

  /* "Example Ave NE, Notaville, GA, USA" -> street and town. Uber prints no
   * house number on this screen; the street is what is compared. */
  function dropoffOf(line) {
    var parts = clean(line).split(/\s*,\s*/).filter(Boolean);
    if (!parts.length) return null;
    return { street: cut(parts[0]), town: parts.length >= 3 ? cut(parts[1]) : null };
  }

  /* One block: the lines from an amount to the line before the next. */
  function readBlock(lines) {
    var first = AMOUNT.exec(lines[0]);
    var e = { amount: money(first[1]), finishedAt: clockOf(first[2]), tip: null, type: null,
              minutes: null, seconds: null, miles: null, pickup: null, dropoff: null, trip: false };
    var detailAt = -1, dropAt = -1;
    for (var i = 1; i < lines.length; i++) {
      var l = lines[i];
      if (!e.finishedAt) e.finishedAt = clockOf(l);
      if (detailAt === -1) {
        var d = DETAIL.exec(l);
        if (d) {
          detailAt = i;
          e.trip = true;
          e.type = cut(d[1]);
          e.minutes = parseInt(d[2], 10);
          e.seconds = d[3] ? parseInt(d[3], 10) : 0;
          e.miles = money(d[4]);
          continue;
        }
      }
      if (e.tip === null && TIP_PENDING.test(l)) { e.tip = 'processing'; continue; }
      if (e.tip === null && /\btip\b/i.test(l)) {
        var t = TIP_AMOUNT.exec(l);
        if (t) { e.tip = money(t[1] || t[2]); continue; }
      }
      if (dropAt === -1 && DROPOFF.test(l)) dropAt = i;
    }
    if (dropAt !== -1) {
      e.dropoff = dropoffOf(lines[dropAt]);
      // The line straight above the dropoff, unless that is one of the block's
      // own lines (a cut-off map can leave nothing between them).
      for (var k = dropAt - 1; k > Math.max(0, detailAt); k--) {
        var above = lines[k];
        if (isTipLine(above) || clockOf(above) === above) continue;
        if (/[A-Za-z]{2}/.test(above)) { e.pickup = pickupOf(above); break; }
      }
    } else {
      // No dropoff line — the screenshot ended inside the block. A line with
      // a bracket after the detail is the pickup, if there is one.
      for (var j = lines.length - 1; j > Math.max(0, detailAt); j--) {
        if (/\(.+\)/.test(lines[j]) && !isTipLine(lines[j])) { e.pickup = pickupOf(lines[j]); break; }
      }
    }
    if (!e.trip) {
      // Not a trip: an adjustment, a promotion, a quest. Named by the first
      // line with words, for the notes; never matched to an order.
      for (var n = 1; n < lines.length; n++) {
        if (/[A-Za-z]{3}/.test(lines[n]) && !clockOf(lines[n])) { e.type = cut(lines[n]); break; }
      }
    }
    return e;
  }

  /* Uber's Earnings Activity. Returns {app, day, entries, others, notes}:
   *   day      {iso, from} or null (a screenshot scrolled past the top and
   *            short of the bottom says no date: see the server's batch day);
   *   entries  the trips, each {amount, finishedAt 'HH:MM', tip (number,
   *            'processing' or null), type ('Delivery': the trip's kind, as
   *            Uber names it — `type`, since a journal row's `kind` is the
   *            row's), minutes, seconds, miles,
   *            pickup {name, detail}, dropoff {street, town}};
   *   others   blocks with an amount and no trip line (adjustments and the
   *            like): kept for the notes only;
   *   notes    what was stepped over, in words. */
  function parseUber(text, opts) {
    var o = opts || {};
    var lines = String(text || '').split(/\r?\n/).map(clean).filter(Boolean);
    var out = { app: 'uber', day: dayOf(lines, o.now), entries: [], others: [], notes: [] };
    var starts = [];
    var endAt = lines.length;
    for (var i = 0; i < lines.length; i++) {
      if (END_LINE.test(lines[i])) { endAt = i; break; }
      if (AMOUNT.test(lines[i]) && !isTipLine(lines[i])) starts.push(i);
    }
    starts = starts.filter(function (s) { return s < endAt; });
    if (starts.length && starts[0] > 0) {
      // Lines above the first amount that are not the header: the tail of a
      // block whose top was scrolled off. Its amount and time are on another
      // screenshot, or nowhere; it is not guessed at.
      var tail = lines.slice(0, starts[0]).filter(function (l) {
        return DROPOFF.test(l) || DETAIL.test(l) || isTipLine(l);
      });
      if (tail.length) out.notes.push('the top of the first trip was scrolled off; its rest was skipped');
    }
    starts.forEach(function (s, k) {
      var e = readBlock(lines.slice(s, k + 1 < starts.length ? starts[k + 1] : endAt));
      if (!e.trip) { out.others.push({ amount: e.amount, type: e.type }); return; }
      if (!e.finishedAt) {
        out.notes.push('a $' + e.amount.toFixed(2) + ' trip with no time on it was skipped');
        return;
      }
      delete e.trip;
      out.entries.push(e);
    });
    return out;
  }

  /* DoorDash's earnings screen. No screenshot of it has been seen yet, so
   * there is nothing to write a reader from, and guessing one would only
   * produce confident wrong rows. It reads nothing and says why; a parser
   * written from a real screenshot goes here, returning parseUber's shape
   * with app 'doordash', and everything after reading (keeping, matching, the
   * reports) works for it unchanged — the orders on file already carry their
   * app. */
  function parseDoorDash() {
    return { app: 'doordash', day: null, entries: [], others: [],
             notes: ['DoorDash\'s earnings screen cannot be read yet: no screenshot of it has been seen to '
                     + 'write a reader from'] };
  }

  var PARSERS = { uber: parseUber, doordash: parseDoorDash };

  /* Whose screen it is, off its text. Uber's says "Earnings Activity" or
   * prints Uber's trip line (minutes AND seconds, which DoorDash does not);
   * DoorDash's names itself or the Dasher. Null when neither: a screenshot of
   * something else, which is said rather than read. */
  function detectApp(text) {
    var t = String(text || '');
    if (/door\s*dash|dasher|dash\s+summary/i.test(t)) return 'doordash';
    if (/earnings\s+activit/i.test(t) || /end of activit/i.test(t)) return 'uber';
    if (/\d\s*min\w*\.?\s*\d{1,2}\s*sec/i.test(t) && /\d\s*mi\b/i.test(t)) return 'uber';
    return null;
  }

  function parse(text, opts) {
    var o = opts || {};
    var app = o.app && PARSERS[o.app] ? o.app : detectApp(text);
    if (!app) {
      return { app: null, day: null, entries: [], others: [],
               notes: ['not an earnings screen this reads: no Earnings Activity heading or trip line in it'] };
    }
    return PARSERS[app](text, o);
  }

  /* --- one trip, however many times it is seen ----------------------------- */

  // Words a name or a street is compared on: lower case, "&" as "and", the
  // street types and compass points the way Uber and the cards abbreviate
  // them, so "Sample Street Northwest" and "Sample St NW" are one street.
  var ABBR = {
    street: 'st', avenue: 'ave', av: 'ave', road: 'rd', drive: 'dr', court: 'ct', lane: 'ln',
    boulevard: 'blvd', parkway: 'pkwy', highway: 'hwy', place: 'pl', circle: 'cir', trail: 'trl',
    terrace: 'ter', square: 'sq', north: 'n', south: 's', east: 'e', west: 'w', northeast: 'ne',
    northwest: 'nw', southeast: 'se', southwest: 'sw', mount: 'mt', saint: 'st'
  };
  // ...and the words that say nothing about which place it is.
  var STOP = { the: 1, and: 1, of: 1, at: 1, restaurant: 1, usa: 1 };

  function words(s) {
    return clean(s).toLowerCase().replace(/&/g, ' and ').replace(/['’]/g, '')
      .replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean)
      .map(function (w) { return ABBR[w] || w; })
      .filter(function (w) { return !STOP[w]; });
  }

  function bigrams(s) {
    var t = words(s).join(' ');
    var out = {};
    for (var i = 0; i < t.length - 1; i++) out[t.slice(i, i + 2)] = (out[t.slice(i, i + 2)] || 0) + 1;
    return out;
  }

  /* How alike two names are, 0 to 1: the better of the share of words in
   * common (Dice) and of letter pairs in common, the second a little
   * discounted — it is what forgives an OCR slip ("Make-Belleve"), and on its
   * own it also finds likeness in two different names sharing a word's worth
   * of letters. */
  function similar(a, b) {
    var wa = words(a), wb = words(b);
    if (!wa.length || !wb.length) return 0;
    var common = wa.filter(function (w) { return wb.indexOf(w) !== -1; }).length;
    var wordDice = 2 * common / (wa.length + wb.length);
    var ba = bigrams(a), bb = bigrams(b), na = 0, nb = 0, both = 0;
    Object.keys(ba).forEach(function (k) { na += ba[k]; if (bb[k]) both += Math.min(ba[k], bb[k]); });
    Object.keys(bb).forEach(function (k) { nb += bb[k]; });
    var pairDice = na + nb ? 2 * both / (na + nb) : 0;
    return Math.round(Math.max(wordDice, 0.9 * pairDice) * 1000) / 1000;
  }

  /* How much of street `a` is in text `b`, 0 to 1: the share of a's words
   * found among b's. One way round on purpose — Uber's dropoff is a bare
   * street ("Example Ave NE") and the record's a whole address with a number
   * and a town ("742 Example Ave NE, Notaville"). */
  function within(a, b) {
    var wa = words(a), wb = words(b);
    if (!wa.length || !wb.length) return 0;
    return wa.filter(function (w) { return wb.indexOf(w) !== -1; }).length / wa.length;
  }

  /* The moment a trip finished, ms, on this machine's clock and zone: its day
   * and its 'HH:MM'. A time before DAY_STARTS_AT (4am) under a day's heading
   * is taken as the small hours after it, the way the offers page and the
   * end-of-shift report count a driver's day; how Uber files a trip that ends
   * at 12:30 AM has not been seen on a screenshot (AUDITS.md, Open). */
  var DAY_STARTS_AT = 4;
  function finishMs(e) {
    if (!e || typeof e.date !== 'string' || typeof e.finishedAt !== 'string') return null;
    var d = /^(\d{4})-(\d\d)-(\d\d)$/.exec(e.date);
    var t = /^(\d\d):(\d\d)$/.exec(e.finishedAt);
    if (!d || !t) return null;
    var h = parseInt(t[1], 10);
    var at = new Date(+d[1], +d[2] - 1, +d[3], h, +t[2]).getTime();
    return h < DAY_STARTS_AT ? at + 86400000 : at;
  }

  /* An entry's identity: its app, its day, its time and its pickup's name,
   * as a string the journal row carries. Not its amount, which changes when a
   * tip settles; a pickup a scroll cut off is "?" and is joined to its whole
   * self by sameEntry, which looks past the key. */
  function keyOf(e) {
    var name = e.pickup && e.pickup.name ? words(e.pickup.name).join('-').slice(0, 24) : '?';
    return [e.app || 'uber', e.date || '?', e.finishedAt || '?', name || '?'].join(' ');
  }

  /* Whether two sightings are one trip: the same app, day and minute, and
   * then something more — the pickup alike, or the same amount, or one with
   * its tip still processing for no more than the other (the tip settling
   * raises the amount and never lowers it). The minute alone is not enough: a
   * stacked pair finishes a minute or two apart, and two different trips can
   * share one. */
  var SAME_NAME = 0.6;
  function sameEntry(a, b) {
    if (!a || !b || a.app !== b.app || a.date !== b.date || a.finishedAt !== b.finishedAt) return false;
    var an = a.pickup && a.pickup.name, bn = b.pickup && b.pickup.name;
    if (an && bn) return similar(an, bn) >= SAME_NAME;
    if (a.amount === b.amount) return true;
    if (a.tip === 'processing' && b.amount >= a.amount) return true;
    if (b.tip === 'processing' && a.amount >= b.amount) return true;
    return false;
  }

  function tipStatus(e) {
    return e.tip === 'processing' ? 'pending' : typeof e.tip === 'number' ? 'settled' : 'none';
  }

  // How many changes of amount or tip an entry keeps the story of. A tip
  // settles once; six is room for an adjustment or two after it.
  var HISTORY_MAX = 6;

  /* `old` seen again as `fresh` at `at`: the entry to keep, and whether it
   * changed. A settled tip is never undone by an older screenshot uploaded
   * later (one still saying "processing"); a newer one that settles it, or
   * raises the amount, is kept with the moment it was seen. A field one
   * sighting lacked and the other has (a pickup a scroll cut off) is filled
   * in. */
  function mergeEntry(old, fresh, at) {
    var out = JSON.parse(JSON.stringify(old));
    var changed = false;
    var regress = tipStatus(old) === 'settled' && tipStatus(fresh) === 'pending';
    if (!regress && (fresh.amount !== old.amount || tipStatus(fresh) !== tipStatus(old)
                     || (typeof fresh.tip === 'number' && fresh.tip !== old.tip))) {
      out.amount = fresh.amount;
      out.tip = fresh.tip;
      out.history = (Array.isArray(old.history) ? old.history : [])
        .concat([{ at: at, amount: fresh.amount, tip: fresh.tip }]).slice(-HISTORY_MAX);
      changed = true;
    }
    ['type', 'minutes', 'seconds', 'miles', 'pickup', 'dropoff'].forEach(function (k) {
      if ((out[k] === null || out[k] === undefined) && fresh[k] !== null && fresh[k] !== undefined) {
        out[k] = fresh[k];
        changed = true;
      }
    });
    return { entry: out, changed: changed };
  }

  /* The newest version of each entry among journal rows (`kind: 'earning'`):
   * by key, the latest `at` (then `seq`) winning. A row is a whole entry, its
   * match included, so the newest is the answer and nothing is re-derived;
   * the end-of-shift report folds them by this rule too (tools/). */
  function fold(rows) {
    var by = {};
    (rows || []).forEach(function (r) {
      if (!r || r.kind !== 'earning' || typeof r.key !== 'string' || typeof r.at !== 'number') return;
      var was = by[r.key];
      if (!was || r.at > was.at || (r.at === was.at && (r.seq || 0) >= (was.seq || 0))) by[r.key] = r;
    });
    return Object.keys(by).map(function (k) { return by[k]; }).sort(function (a, b) {
      return (finishMs(a) || 0) - (finishMs(b) || 0);
    });
  }

  /* What it paid, as the record block and the CSV say it: the total, the tip
   * (a figure, or null while it is processing or where there is none), its
   * status, and the base (the total less a settled tip; the total itself
   * while the tip is processing, since the tip is not in it yet). */
  function paidOf(e) {
    if (!e || typeof e.amount !== 'number') return null;
    var st = tipStatus(e);
    var tip = st === 'settled' ? e.tip : null;
    return { total: e.amount, tip: tip, tipStatus: st,
             base: Math.round((e.amount - (tip || 0)) * 100) / 100 };
  }

  /* --- which order it was ----------------------------------------------------
   *
   * THE ORDERS. ordersFrom turns what the server has into one shape: each
   * order record (server.js orderRow: `times.took`/`times.ended`, its
   * pickups' names and doors, the dropoff as filed, the odometer's miles, the
   * card's pay), and for a day before the records each run the report
   * rebuilds from took/drop rows (server.js takenRuns, with the offer's own
   * pickup and dropoff as printed) that no record covers. */
  var RECORD_MATCH_MS = 60000;      // a record is a run's within a minute of its Took (the report's RECORD_MATCH_S)

  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }

  function ordersFrom(records, runs) {
    var out = [];
    (records || []).forEach(function (r) {
      if (!r || r.kind !== 'order' || typeof r.offer !== 'string') return;
      var t = r.times || {}, card = r.card || {};
      var took = num(t.took), ended = num(t.ended);
      var names = [], doors = [];
      (Array.isArray(r.pickups) ? r.pickups : []).forEach(function (p) {
        if (p && p.name) names.push(p.name);
        if (p && p.door) doors.push(p.door);
      });
      (Array.isArray(card.stores) ? card.stores : []).forEach(function (s) { if (s) names.push(s); });
      if (card.pickup) { names.push(card.pickup); doors.push(card.pickup); }
      out.push({ offer: r.offer, order: typeof r.id === 'string' ? r.id : null, app: r.app || null,
                 tookAt: took, endedAt: ended, pay: num(card.pay),
                 minutes: took !== null && ended !== null && ended >= took ? (ended - took) / 60000 : null,
                 miles: num(r.drive && r.drive.miles), names: names, doors: doors,
                 dropoff: (r.dropoff && r.dropoff.text) || card.dropoff || null,
                 how: r.how || null, source: 'record' });
    });
    (runs || []).forEach(function (u) {
      if (!u || typeof u.id !== 'string' || num(u.tookAt) === null) return;
      var covered = out.some(function (c) {
        return c.offer === u.id && c.tookAt !== null && Math.abs(c.tookAt - u.tookAt) <= RECORD_MATCH_MS;
      });
      if (covered) return;
      out.push({ offer: u.id, order: null, app: u.app || null, tookAt: u.tookAt, endedAt: num(u.endedAt),
                 pay: num(u.pay),
                 minutes: num(u.endedAt) !== null && u.endedAt >= u.tookAt ? (u.endedAt - u.tookAt) / 60000 : null,
                 miles: null, names: u.pickup ? [u.pickup] : [], doors: u.pickup ? [u.pickup] : [],
                 dropoff: u.dropoff || null, how: u.by || null, source: 'rebuilt' });
    });
    return out;
  }

  /* THE SCORE. Points for each thing the two agree on, out of about 110:
   *
   *   time      40  Uber's time against the order's end (times.ended), after
   *                 the day's clock offset: full within TIME_FULL_MIN, none
   *                 from TIME_ZERO_MIN, and no candidate at all past
   *                 TIME_GATE_MIN. The strongest single fact — the rig stamps
   *                 an end within a minute or two of the app — and the only
   *                 one every order has.
   *   name      25  the pickup's name against the record's (its stores, the
   *                 card's pickup), by `similar`, from NAME_MIN up; a name
   *                 clearly another restaurant's (both known, under
   *                 NAME_OTHER) costs NAME_PENALTY instead.
   *   street    10  the bracket of a chain's pickup ("Sample St NW & Fictional
   *                 Ct") found in the record's pickup door: what tells two
   *                 branches of one chain apart.
   *   dropoff   15  the dropoff's street found in the record's dropoff as
   *                 filed, from WITHIN_MIN of its words; a different street
   *                 (both known, none of it found) costs DROP_PENALTY.
   *   minutes   10  Uber's minutes against the record's Took-to-end, full at
   *                 the same and none MINUTES_SPAN apart.
   *   miles     10  Uber's miles against the odometer's, full at the same and
   *                 none at the larger of 2 mi or 35% apart.
   *
   * An order of another app is no candidate (an Uber entry is never a
   * DoorDash order); an order whose app the rig did not read can be.
   *
   * CHOSEN, NOT MEASURED: there is one real screenshot and it is not in the
   * repository, so these weights are the reasoning above and the suites' own
   * invented days (tests/earnings.test.js), not a fit. AUDITS.md says so. */
  var W = { time: 40, name: 25, street: 10, dropoff: 15, minutes: 10, miles: 10 };
  var TIME_FULL_MIN = 2;
  var TIME_ZERO_MIN = 15;
  var TIME_GATE_MIN = 20;
  var NAME_MIN = 0.5;
  var NAME_OTHER = 0.3;
  var NAME_PENALTY = 15;
  var WITHIN_MIN = 0.5;
  var DROP_PENALTY = 10;
  var MINUTES_SPAN = 12;
  // A match is taken alone when it scores ACCEPT or more AND beats the
  // runner-up — the next candidate for this entry, and the next entry for this
  // order — by MARGIN. Time alone (40) can never be enough; time with a name,
  // or with Uber's minutes and miles agreeing, can.
  var ACCEPT = 55;
  var MARGIN = 15;
  // The app's clock against the rig's, taken from the day's confident matches
  // (CONFIDENT or more, at least OFFSET_MIN_N of them) as their median gap,
  // and never more than OFFSET_MAX_MIN either way: a phone and a Pi both on
  // network time, an end stamped when the car left the door against Uber's
  // when the driver swiped. Uber's time is to the minute and the rig's to the
  // millisecond, so up to a minute of it is that alone.
  var CONFIDENT = 70;
  var OFFSET_MIN_N = 2;
  var OFFSET_MAX_MIN = 10;

  // The street types a bracket names a street by (ABBR's own short forms).
  var STREET_WORDS = { st: 1, ave: 1, rd: 1, dr: 1, ct: 1, ln: 1, blvd: 1, pkwy: 1, hwy: 1, pl: 1, cir: 1,
                       trl: 1, ter: 1, sq: 1, way: 1 };
  function isStreety(s) {
    return /&/.test(s) || words(s).some(function (w) { return STREET_WORDS[w]; });
  }

  function bestOf(xs, f) {
    var b = 0;
    (xs || []).forEach(function (x) { var v = f(x); if (v > b) b = v; });
    return b;
  }

  function score(e, c, offsetMs) {
    if (!e || !c || c.endedAt === null || c.endedAt === undefined) return null;
    if (e.app && c.app && e.app !== c.app) return null;
    var fin = finishMs(e);
    if (fin === null) return null;
    var dMin = Math.abs(fin + (offsetMs || 0) - c.endedAt) / 60000;
    if (dMin > TIME_GATE_MIN) return null;
    var p = {};
    p.time = dMin <= TIME_FULL_MIN ? W.time : dMin >= TIME_ZERO_MIN ? 0
      : W.time * (TIME_ZERO_MIN - dMin) / (TIME_ZERO_MIN - TIME_FULL_MIN);
    var name = e.pickup && e.pickup.name;
    if (name && c.names.length) {
      var s = bestOf(c.names, function (n) { return similar(name, n); });
      p.name = s >= NAME_MIN ? W.name * s : s < NAME_OTHER ? -NAME_PENALTY : 0;
    }
    var detail = e.pickup && e.pickup.detail;
    // Only a bracket that names a street: a one-off restaurant's bracket is
    // its town ("Pretend Pizza (Faketown)"), and every door in that town
    // would find it.
    if (detail && c.doors.length && isStreety(detail)) {
      // The bracket's streets, split at "&" (a corner names two), each looked
      // for in the doors: a branch is the one whose door is on its corner.
      var streets = detail.split(/\s*(?:&|\band\b|\/)\s*/i).filter(function (x) { return words(x).length; });
      var found = bestOf(streets, function (st) {
        return bestOf(c.doors, function (dr) { return within(st, dr); });
      });
      if (found >= WITHIN_MIN) p.street = W.street * found;
    }
    var street = e.dropoff && e.dropoff.street;
    if (street && c.dropoff) {
      var w = within(street, c.dropoff);
      p.dropoff = w >= WITHIN_MIN ? W.dropoff * w : w === 0 ? -DROP_PENALTY : 0;
    }
    if (typeof e.minutes === 'number' && c.minutes !== null) {
      var um = e.minutes + (e.seconds || 0) / 60;
      p.minutes = W.minutes * Math.max(0, 1 - Math.abs(um - c.minutes) / MINUTES_SPAN);
    }
    if (typeof e.miles === 'number' && c.miles !== null) {
      var span = Math.max(2, 0.35 * e.miles);
      p.miles = W.miles * Math.max(0, 1 - Math.abs(e.miles - c.miles) / span);
    }
    var total = 0;
    Object.keys(p).forEach(function (k) { total += p[k]; p[k] = Math.round(p[k] * 10) / 10; });
    return { total: Math.round(total * 10) / 10, parts: p, minutesOff: Math.round(dMin * 10) / 10 };
  }

  function candKey(c) { return c.offer + '@' + c.tookAt; }

  // What the page is shown of a candidate for a one-tap pick: enough to tell
  // them apart and to name the order back.
  var CANDIDATES_SHOWN = 3;
  function candOut(c, s) {
    return { offer: c.offer, order: c.order, tookAt: c.tookAt, endedAt: c.endedAt, pay: c.pay,
             pickup: c.names.length ? cut(c.names[0]) : null, source: c.source, score: s.total };
  }

  function matchOut(c, s, status, by, margin, offsetMs) {
    return { status: status, by: by, offer: c.offer, order: c.order, tookAt: c.tookAt,
             endedAt: c.endedAt, cardPay: c.pay, source: c.source, score: s ? s.total : null,
             margin: margin === null || margin === undefined ? null : Math.round(margin * 10) / 10,
             offsetS: Math.round((offsetMs || 0) / 1000) };
  }

  /* One day's entries against that day's orders. `entries` carry their match
   * so far; one the driver picked (`match.by === 'you'`, an order or "none")
   * is kept as picked and its order taken out of everyone else's running.
   * Returns a map key -> match, for every entry given:
   *
   *   {status: 'matched', by: 'auto', ...}  clear best (ACCEPT and MARGIN)
   *   {status: 'picked',  by: 'you',  ...}  the driver's pick
   *   {status: 'needs', candidates: [...]}  candidates, none clearly it: the
   *                                         top CANDIDATES_SHOWN for the page
   *   {status: 'none'}                      no order of its app within
   *                                         TIME_GATE_MIN: "no order on file"
   *                                         (or the driver said none, `by`)
   *
   * One-to-one: an order is any one entry's at most, so two of a chain's
   * orders a few minutes apart leave both entries to the driver rather than
   * one guessed and the other forced. */
  function matchDay(entries, orders) {
    var res = {};
    var taken = {};
    var free = [];
    (entries || []).forEach(function (e) {
      var m = e.match;
      if (m && m.by === 'you') {
        res[e.key] = m;
        if (m.status === 'picked' && m.offer) taken[m.offer + '@' + m.tookAt] = true;
      } else {
        free.push(e);
      }
    });
    var cands = (orders || []).filter(function (c) { return !taken[candKey(c)]; });

    function scored(offsetMs) {
      return free.map(function (e) {
        var list = [];
        cands.forEach(function (c) {
          var s = score(e, c, offsetMs);
          if (s) list.push({ c: c, s: s });
        });
        list.sort(function (a, b) { return b.s.total - a.s.total; });
        return { e: e, list: list };
      });
    }

    // First pass at no offset; the confident ones say what the clocks differ
    // by; second pass at that offset.
    var offsetMs = 0;
    var first = scored(0);
    var gaps = [];
    first.forEach(function (x) {
      var b = x.list[0], r = x.list[1];
      if (b && b.s.total >= CONFIDENT && (!r || b.s.total - r.s.total >= MARGIN)) {
        gaps.push(b.c.endedAt - finishMs(x.e));
      }
    });
    if (gaps.length >= OFFSET_MIN_N) {
      gaps.sort(function (a, b) { return a - b; });
      var mid = gaps.length % 2 ? gaps[(gaps.length - 1) / 2] : (gaps[gaps.length / 2 - 1] + gaps[gaps.length / 2]) / 2;
      offsetMs = Math.max(-OFFSET_MAX_MIN * 60000, Math.min(OFFSET_MAX_MIN * 60000, mid));
    }
    var all = offsetMs ? scored(offsetMs) : first;

    // Clear matches first, best first; each takes its order out of the
    // running, and a later entry is judged on what is left.
    var used = {};
    var pending = all.slice().sort(function (a, b) {
      return ((b.list[0] && b.list[0].s.total) || 0) - ((a.list[0] && a.list[0].s.total) || 0);
    });
    pending.forEach(function (x) {
      var left = x.list.filter(function (y) { return !used[candKey(y.c)]; });
      var b = left[0];
      if (!b) return;
      var runner = left[1] ? left[1].s.total : 0;
      // ...and the next ENTRY for the same order, among those not yet settled:
      // a second trip that fits this order nearly as well makes it no clearer
      // which of the two it was.
      var rival = 0;
      all.forEach(function (o) {
        if (o === x || res[o.e.key]) return;
        o.list.forEach(function (y) {
          if (candKey(y.c) === candKey(b.c) && y.s.total > rival) rival = y.s.total;
        });
      });
      var margin = b.s.total - Math.max(runner, rival);
      if (b.s.total >= ACCEPT && margin >= MARGIN) {
        used[candKey(b.c)] = true;
        res[x.e.key] = matchOut(b.c, b.s, 'matched', 'auto', margin, offsetMs);
      }
    });
    all.forEach(function (x) {
      if (res[x.e.key]) return;
      var left = x.list.filter(function (y) { return !used[candKey(y.c)]; });
      if (!left.length && !x.list.length) {
        res[x.e.key] = { status: 'none', by: 'auto', offsetS: Math.round(offsetMs / 1000) };
        return;
      }
      res[x.e.key] = { status: 'needs', by: 'auto', offsetS: Math.round(offsetMs / 1000),
                       candidates: (left.length ? left : x.list).slice(0, CANDIDATES_SHOWN).map(function (y) {
                         return candOut(y.c, y.s);
                       }) };
    });
    return res;
  }

  return {
    parse: parse, parseUber: parseUber, parseDoorDash: parseDoorDash, detectApp: detectApp,
    PARSERS: PARSERS, dayOf: dayOf, clockOf: clockOf, yearFor: yearFor,
    words: words, similar: similar, within: within, finishMs: finishMs, keyOf: keyOf,
    sameEntry: sameEntry, mergeEntry: mergeEntry, tipStatus: tipStatus, fold: fold, paidOf: paidOf,
    ordersFrom: ordersFrom, score: score, matchDay: matchDay,
    W: W, TIME_FULL_MIN: TIME_FULL_MIN, TIME_ZERO_MIN: TIME_ZERO_MIN, TIME_GATE_MIN: TIME_GATE_MIN,
    NAME_MIN: NAME_MIN, NAME_OTHER: NAME_OTHER, NAME_PENALTY: NAME_PENALTY, WITHIN_MIN: WITHIN_MIN,
    DROP_PENALTY: DROP_PENALTY, MINUTES_SPAN: MINUTES_SPAN, ACCEPT: ACCEPT, MARGIN: MARGIN,
    CONFIDENT: CONFIDENT, OFFSET_MIN_N: OFFSET_MIN_N, OFFSET_MAX_MIN: OFFSET_MAX_MIN,
    CANDIDATES_SHOWN: CANDIDATES_SHOWN, HISTORY_MAX: HISTORY_MAX, TEXT_MAX: TEXT_MAX,
    SAME_NAME: SAME_NAME, DAY_STARTS_AT: DAY_STARTS_AT, RECORD_MATCH_MS: RECORD_MATCH_MS
  };
}));
