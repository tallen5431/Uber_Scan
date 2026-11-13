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
 *      day it shows and one entry per trip: when it started, what it paid,
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
  // The pay's parts beside the tip, "$1.25 Surge", and as many as Uber puts
  // on one line ("$6.00 Tip $1.25 Surge", invented; the shape of the owner's 12 Nov
  // screenshots). Read generically, "$X <Word>": Surge is the one seen, and
  // a Promotion, Boost or Adjustment would be printed the same way, so each
  // is kept under its own word rather than guessed into one of a list. A line
  // that starts with an amount and a word, and has no clock on it, is such a
  // part — never a new trip's block.
  var EXTRA = /(?:\$|S(?=\d))\s?(\d{1,4}[.,]\d{2})\s*([A-Za-z]{3,16})\b/g;
  var EXTRA_LINE = /^(?:\$|S(?=\d))\s?\d{1,4}[.,]\d{2}\s*[A-Za-z]{3,16}\b/;
  var EXTRAS_MAX = 4;
  // A canceled trip's line in place of its minutes and miles: "Delivery ·
  // You canceled", "Customer canceled", or the word alone. Who canceled is
  // kept where it is said.
  var CANCELED = /^\s*([A-Za-z][A-Za-z &+'\/-]*?)?\s*[-·•:.,=~]*\s*(?:(you|customer|driver|store|merchant|restaurant)\s+)?cancell?ed\b/i;
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

  /* The trip's line, DETAIL's match or null. A zero before "min" or "sec"
   * read as the letter O ("22 min O sec", tesseract on the drawn 12 Nov
   * layout) is put back first. */
  function detailOf(line) {
    return DETAIL.exec(String(line || '').replace(/\b[Oo](\s*(?:min|sec|s\b))/g, '0$1'));
  }

  /* The pay's parts on one line: {tip: number | 'processing' | undefined,
   * extras: {surge: 1.00, ...}}, each word lower case. */
  function readExtras(line) {
    var out = { tip: undefined, extras: {} };
    if (TIP_PENDING.test(line)) out.tip = 'processing';
    var t = TIP_AMOUNT.exec(line);
    if (t && out.tip === undefined) out.tip = money(t[1] || t[2]);
    var m;
    EXTRA.lastIndex = 0;
    while ((m = EXTRA.exec(line)) !== null) {
      var w = m[2].toLowerCase();
      if (w === 'tip' || w === 'mi' || w === 'min') continue;
      if (out.extras[w] === undefined) out.extras[w] = money(m[1]);
    }
    return out;
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
    var e = { amount: money(first[1]), startedAt: clockOf(first[2]), tip: null, type: null,
              minutes: null, seconds: null, miles: null, pickup: null, dropoff: null,
              status: 'completed', canceledBy: null, extras: null, trip: false };
    var detailAt = -1, dropAt = -1;
    for (var i = 1; i < lines.length; i++) {
      var l = lines[i];
      if (!e.startedAt) e.startedAt = clockOf(l);
      if (detailAt === -1) {
        var d = detailOf(l);
        if (d) {
          detailAt = i;
          e.trip = true;
          e.type = cut(d[1]);
          e.minutes = parseInt(d[2], 10);
          e.seconds = d[3] ? parseInt(d[3], 10) : 0;
          e.miles = money(d[4]);
          continue;
        }
        var c = CANCELED.exec(l);
        if (c) {
          // A canceled trip: no minutes and no miles, its amount what was
          // shown ($0.00, or a cancellation's pay), its map and places as
          // any trip's.
          detailAt = i;
          e.trip = true;
          e.status = 'canceled';
          e.type = c[1] ? cut(c[1]) : null;
          e.canceledBy = c[2] ? c[2].toLowerCase() : null;
          continue;
        }
      }
      if (dropAt === -1 && (isTipLine(l) || EXTRA_LINE.test(l) && !clockOf(l))) {
        var parts = readExtras(l);
        if (parts.tip !== undefined && e.tip === null) e.tip = parts.tip;
        Object.keys(parts.extras).forEach(function (k) {
          e.extras = e.extras || {};
          if (Object.keys(e.extras).length < EXTRAS_MAX && e.extras[k] === undefined) e.extras[k] = parts.extras[k];
        });
        continue;
      }
      if (dropAt === -1 && DROPOFF.test(l)) dropAt = i;
    }
    if (dropAt !== -1) {
      e.dropoff = dropoffOf(lines[dropAt]);
      // The line straight above the dropoff, unless that is one of the block's
      // own lines (a cut-off map can leave nothing between them).
      for (var k = dropAt - 1; k > Math.max(0, detailAt); k--) {
        var above = lines[k];
        if (isTipLine(above) || EXTRA_LINE.test(above) || clockOf(above) === above) continue;
        if (/[A-Za-z]{2}/.test(above)) { e.pickup = pickupOf(above); break; }
      }
    } else {
      // No dropoff line — the screenshot ended inside the block. A line with
      // a bracket after the detail is the pickup, if there is one.
      for (var j = lines.length - 1; j > Math.max(0, detailAt); j--) {
        if (/\(.+\)/.test(lines[j]) && !isTipLine(lines[j]) && !EXTRA_LINE.test(lines[j])) { e.pickup = pickupOf(lines[j]); break; }
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
   *   entries  the trips, each {amount, startedAt 'HH:MM' (the right-hand
   *            time, which is when the trip STARTED: see startMs), tip (number,
   *            'processing' or null), type ('Delivery': the trip's kind, as
   *            Uber names it — `type`, since a journal row's `kind` is the
   *            row's), minutes, seconds, miles,
   *            pickup {name, detail}, dropoff {street, town}, status
   *            ('completed' or 'canceled'), canceledBy ('you', 'customer'
   *            or null), extras ({surge: 1.00, ...} or null: the pay's parts
   *            beside the tip, each under the word Uber printed)};
   *   others   blocks with an amount and no trip line (adjustments and the
   *            like): kept for the notes only;
   *   notes    what was stepped over, in words. */
  function parseUber(text, opts) {
    var o = opts || {};
    var lines = String(text || '').split(/\r?\n/).map(clean).filter(Boolean);
    var out = { app: 'uber', day: dayOf(lines, o.now), entries: [], others: [], notes: [] };
    var starts = [];
    var endAt = lines.length;
    // A pay part ("$1.25 Surge") straight under a trip's line, its tip line
    // or another part is that trip's, not a block of its own. Anything else
    // that starts with an amount opens a block (an adjustment or a quest on
    // its own reads as one, and is kept in `others`).
    var partOk = false;
    for (var i = 0; i < lines.length; i++) {
      var li = lines[i];
      if (END_LINE.test(li)) { endAt = i; break; }
      var part = isTipLine(li) || EXTRA_LINE.test(li) && !clockOf(li) && partOk;
      if (AMOUNT.test(li) && !part) starts.push(i);
      partOk = part || !!detailOf(li) || CANCELED.test(li);
    }
    starts = starts.filter(function (s) { return s < endAt; });
    if (starts.length && starts[0] > 0) {
      // Lines above the first amount that are not the header: the tail of a
      // block whose top was scrolled off. Its amount and time are on another
      // screenshot, or nowhere; it is not guessed at.
      var tail = lines.slice(0, starts[0]).filter(function (l) {
        return DROPOFF.test(l) || !!detailOf(l) || isTipLine(l);
      });
      if (tail.length) out.notes.push('the top of the first trip was scrolled off; its rest was skipped');
    }
    starts.forEach(function (s, k) {
      var e = readBlock(lines.slice(s, k + 1 < starts.length ? starts[k + 1] : endAt));
      if (!e.trip) { out.others.push({ amount: e.amount, type: e.type }); return; }
      if (!e.startedAt) {
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
    // ...or a canceled trip's line, which has no minutes to know it by.
    if (/\b(?:you|customer)\s+cancell?ed\b/i.test(t)) return 'uber';
    if (/\d\s*min\w*\.?\s*(?:\d{1,2}|[Oo])\s*sec/i.test(t) && /\d\s*mi\b/i.test(t)) return 'uber';
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

  /* WHEN A TRIP WAS. The right-hand time on Uber's Earnings Activity is when
   * the trip STARTED — the offer accepted — not when it finished. Compared by
   * hand on the owner's screenshots of one evening against the rig's order
   * records for it (AUDITS.md, in invented terms): six trips each came up on
   * the rig 0 to 9 minutes after Uber's time, one 18 minutes after (a batch
   * the phone accepted before the rig's Took), and Uber's minutes and miles
   * cover the trip itself, ending 9 to 13 minutes before the rig's end. The
   * first build read it as the finish.
   *
   * The entry's field was `finishedAt` in the rows that build wrote; the
   * same clock reading under the old name is read as the start (clockField),
   * so a journal written before keeps its keys and its trips.
   *
   * startMs: the moment, ms, on this machine's clock and zone, off its day
   * and 'HH:MM'. A time before DAY_STARTS_AT (4am) under a day's heading is
   * taken as the small hours after it, the way the offers page and the
   * end-of-shift report count a driver's day; how Uber files a trip that
   * starts at 12:30 AM has not been seen on a screenshot (AUDITS.md, Open).
   * endMs: that plus Uber's own minutes and seconds — the finish Uber's
   * figures imply; null where the trip line gave none (a canceled trip). */
  var DAY_STARTS_AT = 4;
  function clockField(e) {
    if (!e) return null;
    if (typeof e.startedAt === 'string') return e.startedAt;
    return typeof e.finishedAt === 'string' ? e.finishedAt : null;
  }
  function startMs(e) {
    var c = clockField(e);
    if (!e || typeof e.date !== 'string' || c === null) return null;
    var d = /^(\d{4})-(\d\d)-(\d\d)$/.exec(e.date);
    var t = /^(\d\d):(\d\d)$/.exec(c);
    if (!d || !t) return null;
    var h = parseInt(t[1], 10);
    var at = new Date(+d[1], +d[2] - 1, +d[3], h, +t[2]).getTime();
    return h < DAY_STARTS_AT ? at + 86400000 : at;
  }
  function endMs(e) {
    var s = startMs(e);
    if (s === null || typeof e.minutes !== 'number') return null;
    return s + (e.minutes * 60 + (typeof e.seconds === 'number' ? e.seconds : 0)) * 1000;
  }

  /* An entry's identity: its app, its day, its time and its pickup's name,
   * as a string the journal row carries. Not its amount, which changes when a
   * tip settles; a pickup a scroll cut off is "?" and is joined to its whole
   * self by sameEntry, which looks past the key. */
  function keyOf(e) {
    var name = e.pickup && e.pickup.name ? words(e.pickup.name).join('-').slice(0, 24) : '?';
    return [e.app || 'uber', e.date || '?', clockField(e) || '?', name || '?'].join(' ');
  }

  /* Whether two sightings are one trip: the same app, day and minute, and
   * then something more — the pickup alike, or the same amount, or one with
   * its tip still processing for no more than the other (the tip settling
   * raises the amount and never lowers it). The minute alone is not enough: a
   * stacked pair finishes a minute or two apart, and two different trips can
   * share one. */
  var SAME_NAME = 0.6;
  function sameEntry(a, b) {
    if (!a || !b || a.app !== b.app || a.date !== b.date || clockField(a) !== clockField(b)) return false;
    // A canceled trip and a completed one of the same minute are two trips.
    if ((a.status === 'canceled') !== (b.status === 'canceled')) return false;
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
    ['type', 'minutes', 'seconds', 'miles', 'pickup', 'dropoff', 'extras', 'canceledBy'].forEach(function (k) {
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
      return (startMs(a) || 0) - (startMs(b) || 0);
    });
  }

  /* What it paid, as the record block and the CSV say it: the total, the tip
   * (a figure, or null while it is processing or where there is none), its
   * status, the pay's other parts (`extras`, {surge: 1.00}, or null) and
   * the base (the total less a settled tip and those parts; the tip is not
   * taken off while it is processing, since it is not in the total yet), and
   * whether the trip was canceled. */
  function extrasOf(e) {
    var x = e && e.extras && typeof e.extras === 'object' ? e.extras : null;
    if (!x) return null;
    var out = {}, any = false;
    Object.keys(x).forEach(function (k) { if (typeof x[k] === 'number') { out[k] = x[k]; any = true; } });
    return any ? out : null;
  }
  function paidOf(e) {
    if (!e || typeof e.amount !== 'number') return null;
    var st = tipStatus(e);
    var tip = st === 'settled' ? e.tip : null;
    var extras = extrasOf(e), more = 0;
    if (extras) Object.keys(extras).forEach(function (k) { more += extras[k]; });
    return { total: e.amount, tip: tip, tipStatus: st, extras: extras,
             base: Math.round((e.amount - (tip || 0) - more) * 100) / 100,
             canceled: e.status === 'canceled' };
  }

  /* --- which order it was ----------------------------------------------------
   *
   * THE ORDERS. ordersFrom turns what the server has into one shape: each
   * order record (server.js orderRow: `times.offered`/`took`/`ended`, how it
   * ended, its pickups' names and doors, the dropoff as filed, the odometer's
   * miles, the card's pay), and for a day before the records each run the
   * report rebuilds from took/drop rows (server.js takenRuns, with the
   * offer's own pickup, dropoff and first sighting) that no record covers. */
  var RECORD_MATCH_MS = 60000;      // a record is a run's within a minute of its Took (the report's RECORD_MATCH_S)

  // The ends that are a delivery's: the order's end is when it was handed
  // over, and Uber's finish can be held to it. Not 'replaced' (the next
  // Took), 'expiry' (a clock), 'untick'/'offers' (taken back) or 'boot'.
  var DELIVERED = { drop: 1, gps: 1, chooser: 1, screen: 1, 'finished-door': 1, 'finished-area': 1,
                    'finished-stop': 1 };

  function num(v) { return typeof v === 'number' && isFinite(v) ? v : null; }

  function ordersFrom(records, runs, offers) {
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
      var delivered = !!DELIVERED[r.how] && ended !== null;
      // A BATCH: two pickups or two dropoffs on one order (the 12 Nov
      // evening had one, two stores and two doors, and Uber printed it as
      // ONE trip naming one store and one street). Its every pickup is
      // already among `names` and `doors`; its dropoff as filed is only one
      // of its doors, so Uber's street not being that one says nothing.
      var stops = (Array.isArray(r.pickups) ? r.pickups.length : 0);
      var batch = stops >= 2 || (num(card.dropoffs) || 0) >= 2 || (num(card.dropoffOrders) || 0) >= 2
        || (Array.isArray(card.stores) && card.stores.length >= 2)
        || !!(r.links && Array.isArray(r.links.batch) && r.links.batch.length);
      out.push({ offer: r.offer, order: typeof r.id === 'string' ? r.id : null, app: r.app || null, batch: batch,
                 offeredAt: num(t.offered), tookAt: took, endedAt: ended, delivered: delivered,
                 pay: num(card.pay), cardMinutes: num(card.minutes) !== null ? card.minutes : num(card.billedMinutes),
                 cardMiles: num(card.miles),
                 minutes: delivered && took !== null && ended >= took ? (ended - took) / 60000 : null,
                 miles: delivered ? num(r.drive && r.drive.miles) : null, names: names, doors: doors,
                 dropoff: (r.dropoff && r.dropoff.text) || card.dropoff || null,
                 dropoffs: [r.dropoff && r.dropoff.text, card.dropoff].filter(function (x) {
                   return typeof x === 'string' && x;
                 }),
                 how: r.how || null, source: 'record' });
    });
    (runs || []).forEach(function (u) {
      if (!u || typeof u.id !== 'string' || num(u.tookAt) === null) return;
      var covered = out.some(function (c) {
        return c.offer === u.id && c.tookAt !== null && Math.abs(c.tookAt - u.tookAt) <= RECORD_MATCH_MS;
      });
      if (covered) return;
      var delivered = !!DELIVERED[u.by || 'drop'] && num(u.endedAt) !== null;
      out.push({ offer: u.id, order: null, app: u.app || null, offeredAt: num(u.offeredAt), tookAt: u.tookAt,
                 endedAt: num(u.endedAt), delivered: delivered, pay: num(u.pay),
                 cardMinutes: num(u.minutes), cardMiles: num(u.miles),
                 minutes: delivered && u.endedAt >= u.tookAt ? (u.endedAt - u.tookAt) / 60000 : null,
                 miles: null, names: u.pickup ? [u.pickup] : [], doors: u.pickup ? [u.pickup] : [],
                 dropoff: u.dropoff || null, batch: false, how: u.by || null, source: 'rebuilt' });
    });
    // OFFERS NEVER CONFIRMED. A card the rig showed and was never told was
    // taken — the panel left on "Took $9.27?", the phone accepted it — has no
    // order record and no run; Uber's screen is the only word that it was
    // taken. Each offer row (the server's latestPerOffer) no record or run
    // covers is a candidate, `source: 'offer'`, timed by its first sighting
    // alone. Not one the driver passed (`accepted: false`) or hid. SILENCE IS
    // STILL NOT AN ACCEPT (AUDITS.md, Settled): nothing here marks the offer
    // taken or puts it in the car; the match is a record that Uber paid for
    // it, said as "accepted on the phone, no Took".
    var covered = {};
    out.forEach(function (c) { covered[c.offer] = true; });
    (offers || []).forEach(function (o) {
      if (!o || typeof o.id !== 'string' || covered[o.id] || o.accepted === false || o.hidden === true) return;
      if (o.kind !== undefined && o.kind !== null) return;
      var seen = num(o.firstAt) !== null ? o.firstAt : num(o.at);
      if (seen === null) return;
      covered[o.id] = true;
      var pickup = typeof o.pickup === 'string' && o.pickup ? o.pickup : null;
      out.push({ offer: o.id, order: null, app: o.app || null, offeredAt: seen, tookAt: null, endedAt: null,
                 delivered: false, batch: false, pay: num(o.pay), cardMinutes: num(o.minutes), cardMiles: num(o.miles),
                 minutes: null, miles: null, names: pickup ? [pickup] : [], doors: pickup ? [pickup] : [],
                 dropoff: typeof o.dropoff === 'string' && o.dropoff ? o.dropoff : null, how: null, source: 'offer' });
    });
    return out;
  }

  /* THE SCORE. Points for each thing the two agree on, out of 125:
   *
   *   start     40  Uber's time — the trip's START — against the order's
   *                 own start: the moment the rig first saw the card
   *                 (times.offered) or its Took, whichever agrees better,
   *                 after the day's clock offset. The rig sees a card after
   *                 the phone does and the Took comes later still, so the
   *                 band is lopsided: full from START_EARLY_FULL before
   *                 Uber's time to START_LATE_FULL after it, none from
   *                 START_EARLY_ZERO before or START_LATE_ZERO after, and no
   *                 candidate at all past START_GATE_EARLY / START_GATE_LATE.
   *                 Measured: 0 to 9 minutes on six trips of one evening, 18
   *                 on a batch the phone accepted before the rig's Took.
   *   finish    15  Uber's finish (its time plus its own minutes, endMs)
   *                 against the order's end — only where that end is a
   *                 delivery's (DELIVERED), never an expiry's clock or the
   *                 Took that replaced it. Uber's minutes are the trip's and
   *                 the rig's end is the car leaving the door, so the rig
   *                 ends later: measured 9 to 13 minutes on that evening,
   *                 full from FINISH_EARLY_FULL before to FINISH_LATE_FULL
   *                 after, none from FINISH_EARLY_ZERO / FINISH_LATE_ZERO.
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
   *   miles     10  Uber's miles against the odometer's, over a delivery,
   *                 full at the same and none at the larger of 2 mi or 35%
   *                 apart.
   *   pay       10  what Uber paid against the card's pay, full within
   *                 PAY_FULL and none from the larger of PAY_ZERO or
   *                 PAY_ZERO_SHARE of the card; never a penalty (a tip cut
   *                 or added is what the comparison is for, and must not
   *                 keep an order from matching), and not while a tip is
   *                 processing (the amount is not yet what it will be). On
   *                 that evening seven of eight trips were within 25 cents.
   *
   * Uber's own minutes are not compared with the rig's Took-to-end on their
   * own any more: the finish says the same thing against the right moment.
   *
   * An order of another app is no candidate (an Uber entry is never a
   * DoorDash order); an order whose app the rig did not read can be.
   *
   * TUNED ON INVENTED DAYS BUILT LIKE ONE REAL EVENING (tests/earnings.test.js):
   * the owner's screenshots are not in the repository, and one evening is
   * not a fit. AUDITS.md says so. */
  var W = { start: 40, finish: 15, name: 25, street: 10, dropoff: 15, miles: 10, pay: 10 };
  var START_EARLY_FULL = 2;
  var START_LATE_FULL = 10;
  var START_EARLY_ZERO = 8;
  var START_LATE_ZERO = 25;
  var START_GATE_EARLY = 10;
  var START_GATE_LATE = 30;
  var FINISH_EARLY_FULL = 3;
  var FINISH_LATE_FULL = 15;
  var FINISH_EARLY_ZERO = 10;
  var FINISH_LATE_ZERO = 25;
  var NAME_MIN = 0.5;
  var NAME_OTHER = 0.3;
  var NAME_PENALTY = 15;
  var WITHIN_MIN = 0.5;
  var DROP_PENALTY = 10;
  var PAY_FULL = 0.25;
  var PAY_ZERO = 2;
  var PAY_ZERO_SHARE = 0.15;
  // A match is taken alone when it scores ACCEPT or more AND beats the
  // runner-up — the next candidate for this entry, and the next entry for this
  // order — by MARGIN. Neither clock alone can be enough, nor the two clocks
  // together (55): one more thing must agree — a name, the miles, the pay.
  var ACCEPT = 60;
  var MARGIN = 15;
  // An offer never confirmed needs this much besides its clock to be a
  // candidate at all (matchDay).
  var OFFER_MORE = 10;
  // The app's clock against the rig's, taken from the day's confident matches
  // (CONFIDENT or more, at least OFFSET_MIN_N of them) as the median of how
  // far each one's start fell OUTSIDE the full band (zero for one inside it),
  // never more than OFFSET_MAX_MIN either way. The band is the rig's ordinary
  // lag behind the phone and is not a clock fault; what is left over is.
  var CONFIDENT = 75;
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

  // Points on a lopsided band: full from -earlyFull to +lateFull minutes,
  // falling to none at -earlyZero and +lateZero.
  function band(d, earlyFull, lateFull, earlyZero, lateZero) {
    if (d >= -earlyFull && d <= lateFull) return 1;
    if (d < -earlyFull) return d <= -earlyZero ? 0 : (d + earlyZero) / (earlyZero - earlyFull);
    return d >= lateZero ? 0 : (lateZero - d) / (lateZero - lateFull);
  }

  // How far a start gap (minutes, rig less Uber) lies outside the full band.
  function outside(d) {
    return d > START_LATE_FULL ? d - START_LATE_FULL : d < -START_EARLY_FULL ? d + START_EARLY_FULL : 0;
  }

  // The rig's start nearest the band, with its gap in minutes: {at, gap, by}.
  function startOf(e, c, offsetMs) {
    var s = startMs(e);
    if (s === null) return null;
    var best = null;
    [['offered', c.offeredAt], ['took', c.tookAt]].forEach(function (x) {
      if (x[1] === null || x[1] === undefined) return;
      var gap = (x[1] - s - (offsetMs || 0)) / 60000;
      var pts = band(gap, START_EARLY_FULL, START_LATE_FULL, START_EARLY_ZERO, START_LATE_ZERO);
      if (!best || pts > best.pts || (pts === best.pts && Math.abs(gap) < Math.abs(best.gap))) {
        best = { at: x[1], gap: gap, by: x[0], pts: pts };
      }
    });
    return best;
  }

  function score(e, c, offsetMs) {
    if (!e || !c) return null;
    if (e.app && c.app && e.app !== c.app) return null;
    // A canceled trip was never delivered: never a delivered order's, and
    // nothing of a delivery (its finish, miles, pay) is held against it.
    var canceled = e.status === 'canceled';
    if (canceled && c.delivered) return null;
    var st = startOf(e, c, offsetMs);
    if (!st || st.gap < -START_GATE_EARLY || st.gap > START_GATE_LATE) return null;
    var p = { start: W.start * st.pts };
    var fin = endMs(e);
    if (fin !== null && c.delivered && c.endedAt !== null) {
      var h = (c.endedAt - fin - (offsetMs || 0)) / 60000;
      p.finish = W.finish * band(h, FINISH_EARLY_FULL, FINISH_LATE_FULL, FINISH_EARLY_ZERO, FINISH_LATE_ZERO);
    }
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
      var found = bestOf(streets, function (sx) {
        return bestOf(c.doors, function (dr) { return within(sx, dr); });
      });
      if (found >= WITHIN_MIN) p.street = W.street * found;
    }
    var street = e.dropoff && e.dropoff.street;
    if (street && c.dropoff) {
      // Any of its doors on file; a batch's other door is not on file, so
      // a street none of them names costs a batch nothing.
      var drops = c.dropoffs && c.dropoffs.length ? c.dropoffs : [c.dropoff];
      var w = bestOf(drops, function (dx) { return within(street, dx); });
      p.dropoff = w >= WITHIN_MIN ? W.dropoff * w : w === 0 && !c.batch ? -DROP_PENALTY : 0;
    }
    if (typeof e.miles === 'number' && c.miles !== null && c.miles !== undefined) {
      var span = Math.max(2, 0.35 * e.miles);
      p.miles = W.miles * Math.max(0, 1 - Math.abs(e.miles - c.miles) / span);
    }
    if (!canceled && typeof e.amount === 'number' && c.pay !== null && c.pay !== undefined && e.tip !== 'processing') {
      var off = Math.abs(e.amount - c.pay);
      var zero = Math.max(PAY_ZERO, PAY_ZERO_SHARE * c.pay);
      p.pay = off <= PAY_FULL ? W.pay : W.pay * Math.max(0, 1 - (off - PAY_FULL) / (zero - PAY_FULL));
    }
    var total = 0;
    Object.keys(p).forEach(function (k) { total += p[k]; p[k] = Math.round(p[k] * 10) / 10; });
    return { total: Math.round(total * 10) / 10, parts: p, startBy: st.by,
             minutesOff: Math.round(st.gap * 10) / 10, gapMs: st.at - startMs(e) };
  }

  function candKey(c) { return c.offer + '@' + (typeof c.tookAt === 'number' ? c.tookAt : ''); }

  // What the page is shown of a candidate for a one-tap pick: enough to tell
  // them apart and to name the order back.
  var CANDIDATES_SHOWN = 3;
  function candOut(c, s) {
    return { offer: c.offer, order: c.order, offeredAt: c.offeredAt, tookAt: c.tookAt, endedAt: c.endedAt,
             pay: c.pay, pickup: c.names.length ? cut(c.names[0]) : null, source: c.source, score: s.total };
  }

  // What a match to an offer never confirmed says it was (`said`).
  var SAID_PHONE = 'accepted on the phone, no Took';
  function matchOut(c, s, status, by, margin, offsetMs) {
    return { status: status, by: by, offer: c.offer, order: c.order, offeredAt: c.offeredAt,
             tookAt: c.tookAt, endedAt: c.endedAt, how: c.how, cardPay: c.pay, source: c.source,
             said: c.source === 'offer' ? SAID_PHONE : null,
             // THE CARD AS READ, kept beside Uber's figures and never
             // replaced by them (compareOf): its minutes and miles, its
             // pickup and dropoff as the rig had them, and the rig's own
             // minutes and miles where it timed a delivery.
             cardMinutes: c.cardMinutes === undefined ? null : c.cardMinutes,
             cardMiles: c.cardMiles === undefined ? null : c.cardMiles,
             cardPickup: c.names && c.names.length ? cut(c.names[0]) : null,
             cardDropoff: c.dropoff ? cut(c.dropoff) : null,
             rigMinutes: typeof c.minutes === 'number' ? Math.round(c.minutes * 100) / 100 : null,
             rigMiles: typeof c.miles === 'number' ? c.miles : null,
             score: s ? s.total : null, startBy: s ? s.startBy : null,
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
   *   {status: 'none'}                      no order of its app within the
   *                                         start gate: "no order on file"
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
        if (m.status === 'picked' && m.offer) taken[candKey(m)] = true;
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
          // An offer never confirmed is one of many cards seen around any
          // trip's start: a candidate only with OFFER_MORE points of
          // something besides its clock (its name, its door, its pay).
          if (s && c.source === 'offer' && s.total - (s.parts.start || 0) < OFFER_MORE) s = null;
          if (s) list.push({ c: c, s: s });
        });
        list.sort(function (a, b) { return b.s.total - a.s.total; });
        return { e: e, list: list };
      });
    }

    // First pass at no offset; the confident ones say what the clocks differ
    // by beyond the rig's ordinary lag; second pass at that offset.
    var offsetMs = 0;
    var first = scored(0);
    var gaps = [];
    first.forEach(function (x) {
      var b = x.list[0], r = x.list[1];
      if (b && b.s.total >= CONFIDENT && (!r || b.s.total - r.s.total >= MARGIN)) {
        gaps.push(outside(b.s.gapMs / 60000) * 60000);
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

  /* --- an untimed order, timed by Uber ---------------------------------------
   *
   * The owner, 12 Nov: an order the rig never timed — expired on its own
   * clock, replaced by the next Took, never Took'd, marked on the offers
   * page — still has Uber's own minutes and miles once its trip is matched.
   * They are carried onto that order's money as `source: 'uber'` and said so
   * everywhere they show (the records CSV's `timed_by`, the end-of-shift
   * report's notes, the Strategy tab's count); A RIG-MEASURED TIMING IS
   * NEVER OVERWRITTEN. They are not the rig's figure: on the 12 Nov evening
   * Uber's minutes ended each trip 9 to 13 minutes before the rig's end
   * (the walk back, the wait for the next screen), so an order timed by
   * Uber reads a little faster, and its $/hr a little higher, than the
   * rig's would have.
   *
   * uberTimingFor(entries, offer, tookAt): the newest matched or picked,
   * completed entry for that order (its Took within RECORD_MATCH_MS, or no
   * Took on either side) with Uber's minutes: {minutes, miles, source:
   * 'uber', key}, else null. */
  function uberTimingFor(entries, offer, tookAt) {
    var best = null;
    (entries || []).forEach(function (e) {
      var m = e && e.match;
      if (!m || (m.status !== 'matched' && m.status !== 'picked') || m.offer !== offer) return;
      if (e.status === 'canceled' || typeof e.minutes !== 'number') return;
      var t = num(m.tookAt), want = num(tookAt);
      if (t === null ? want !== null : (want === null || Math.abs(t - want) > RECORD_MATCH_MS)) return;
      if (!best || (e.at || 0) >= (best.at || 0)) best = e;
    });
    if (!best) return null;
    return { minutes: Math.round((best.minutes + (best.seconds || 0) / 60) * 100) / 100,
             miles: typeof best.miles === 'number' ? best.miles : null, source: 'uber', key: best.key };
  }

  /* --- the card against what happened ---------------------------------------
   *
   * The owner, 13 Nov: "retain the OCR scanned info from the cards and the
   * actual info at the end of the day to compare and see if the orders were
   * completed on time, faster, or any other helpful comparisons." A matched
   * trip's row keeps both sides apart — the card as read (its pay, minutes
   * and miles, on the match) and Uber's figures (what it paid, its minutes
   * and miles, its start and the finish they imply) — and nothing here ever
   * writes one over the other.
   *
   * DESCRIPTIVE ONLY. These say what the card said and what happened: "faster
   * than the card said", never what should have been taken. No $/mile rule,
   * no floor, nothing re-timed at a pace, nothing on the live card (AUDITS.md,
   * Settled). Nothing on the rig reads any of it.
   *
   * compareOf(e): each comparison only where both sides exist —
   *   pay     paid less the card; `flag` past PAY_FLAG or PAY_FLAG_SHARE of
   *           the card, `word` 'more' / 'less' / 'as carded'; left out while
   *           a tip is processing (the total is not yet what it will be);
   *   time    Uber's minutes against the card's: 'faster' / 'on time'
   *           (within ON_TIME_MIN or ON_TIME_SHARE) / 'slower', and the gap;
   *           where the rig timed the order too, the rig's minutes beside;
   *   miles   Uber's against the card's: 'shorter' / 'as said' (within
   *           MILES_SAME or MILES_SAME_SHARE) / 'longer';
   *   perHour / perMile  the card's (its pay over its minutes or miles)
   *           and the actual (what was paid over Uber's).
   * A canceled trip is {canceled: true} and nothing else. */
  var PAY_FLAG = 0.5;
  var PAY_FLAG_SHARE = 0.03;
  var ON_TIME_MIN = 3;
  var ON_TIME_SHARE = 0.10;
  var MILES_SAME = 0.5;
  var MILES_SAME_SHARE = 0.10;

  function r2(v) { return v === null || v === undefined ? null : Math.round(v * 100) / 100; }

  function compareOf(e) {
    var m = e && e.match;
    if (!m || (m.status !== 'matched' && m.status !== 'picked')) return null;
    if (e.status === 'canceled') return { canceled: true };
    var out = {};
    var paid = num(e.amount), card = num(m.cardPay);
    var pending = e.tip === 'processing' || e.tipStatus === 'pending';
    if (paid !== null && card !== null) {
      if (pending) out.pay = { card: card, paid: paid, pending: true };
      else {
        var d = r2(paid - card);
        out.pay = { card: card, paid: paid, diff: d, word: d > 0.005 ? 'more' : d < -0.005 ? 'less' : 'as carded',
                    flag: Math.abs(d) > Math.max(PAY_FLAG, PAY_FLAG_SHARE * card) };
      }
    }
    var um = typeof e.minutes === 'number' ? r2(e.minutes + (e.seconds || 0) / 60) : null;
    var cm = num(m.cardMinutes);
    if (um !== null && cm !== null && cm > 0) {
      var g = r2(um - cm);
      var tol = Math.max(ON_TIME_MIN, ON_TIME_SHARE * cm);
      out.time = { card: cm, uber: um, diff: g, word: g < -tol ? 'faster' : g > tol ? 'slower' : 'on time' };
      if (num(m.rigMinutes) !== null) out.time.rig = r2(m.rigMinutes);
    }
    var ui = num(e.miles), ci = num(m.cardMiles);
    if (ui !== null && ci !== null && ci > 0) {
      var md = r2(ui - ci);
      var mt = Math.max(MILES_SAME, MILES_SAME_SHARE * ci);
      out.miles = { card: ci, uber: ui, diff: md, word: md < -mt ? 'shorter' : md > mt ? 'longer' : 'as said' };
    }
    if (card !== null && cm !== null && cm > 0) {
      out.perHour = { card: r2(card / (cm / 60)),
                      actual: paid !== null && !pending && um ? r2(paid / (um / 60)) : null };
    }
    if (card !== null && ci !== null && ci >= 0.1) {
      out.perMile = { card: r2(card / ci), actual: paid !== null && !pending && ui >= 0.1 ? r2(paid / ui) : null };
    }
    return out;
  }

  /* A day's card against actual, for /api/earnings and the offers page:
   * over its matched, completed trips with a card's pay and a settled
   * figure — the card's pay and what was paid in all, how many faster, on
   * time and slower (and with no card minutes to say), the median minute gap
   * (Uber's less the card's), and the BIGGEST_GAPS widest pay gaps by their
   * trip's key and start, no place. Canceled and pending counted beside. */
  var BIGGEST_GAPS = 3;
  function daySummary(entries) {
    var out = { trips: 0, matched: 0, needs: 0, none: 0, canceled: 0, pending: 0, compared: 0,
                card: 0, paid: 0, diff: 0, faster: 0, onTime: 0, slower: 0, untimed: 0,
                medianMinutes: null, biggest: [] };
    var gaps = [], pays = [];
    (entries || []).forEach(function (e) {
      out.trips += 1;
      var st = (e.match || {}).status;
      if (st === 'needs') out.needs += 1;
      else if (st === 'none' || !st) out.none += 1;
      else out.matched += 1;
      var c = compareOf(e);
      if (!c) return;
      if (c.canceled) { out.canceled += 1; return; }
      if (!c.pay) return;
      if (c.pay.pending) { out.pending += 1; return; }
      out.compared += 1;
      out.card += c.pay.card;
      out.paid += c.pay.paid;
      pays.push({ key: e.key, startedAt: clockField(e), diff: c.pay.diff });
      if (c.time) { out[c.time.word === 'on time' ? 'onTime' : c.time.word] += 1; gaps.push(c.time.diff); }
      else out.untimed += 1;
    });
    out.card = r2(out.card); out.paid = r2(out.paid); out.diff = r2(out.paid - out.card);
    if (gaps.length) {
      gaps.sort(function (a, b) { return a - b; });
      var h = gaps.length;
      out.medianMinutes = r2(h % 2 ? gaps[(h - 1) / 2] : (gaps[h / 2 - 1] + gaps[h / 2]) / 2);
    }
    out.biggest = pays.filter(function (p) { return Math.abs(p.diff) > 0.005; })
      .sort(function (a, b) { return Math.abs(b.diff) - Math.abs(a.diff); }).slice(0, BIGGEST_GAPS);
    return out;
  }

  return {
    compareOf: compareOf, daySummary: daySummary, PAY_FLAG: PAY_FLAG, PAY_FLAG_SHARE: PAY_FLAG_SHARE,
    ON_TIME_MIN: ON_TIME_MIN, ON_TIME_SHARE: ON_TIME_SHARE, MILES_SAME: MILES_SAME,
    MILES_SAME_SHARE: MILES_SAME_SHARE, BIGGEST_GAPS: BIGGEST_GAPS,
    uberTimingFor: uberTimingFor,
    parse: parse, parseUber: parseUber, parseDoorDash: parseDoorDash, detectApp: detectApp,
    PARSERS: PARSERS, dayOf: dayOf, clockOf: clockOf, yearFor: yearFor,
    words: words, similar: similar, within: within, clockField: clockField, startMs: startMs, endMs: endMs,
    keyOf: keyOf, sameEntry: sameEntry, mergeEntry: mergeEntry, tipStatus: tipStatus, fold: fold, paidOf: paidOf,
    ordersFrom: ordersFrom, score: score, matchDay: matchDay, DELIVERED: DELIVERED,
    W: W, START_EARLY_FULL: START_EARLY_FULL, START_LATE_FULL: START_LATE_FULL,
    START_EARLY_ZERO: START_EARLY_ZERO, START_LATE_ZERO: START_LATE_ZERO,
    START_GATE_EARLY: START_GATE_EARLY, START_GATE_LATE: START_GATE_LATE,
    FINISH_EARLY_FULL: FINISH_EARLY_FULL, FINISH_LATE_FULL: FINISH_LATE_FULL,
    FINISH_EARLY_ZERO: FINISH_EARLY_ZERO, FINISH_LATE_ZERO: FINISH_LATE_ZERO,
    NAME_MIN: NAME_MIN, NAME_OTHER: NAME_OTHER, NAME_PENALTY: NAME_PENALTY, WITHIN_MIN: WITHIN_MIN,
    DROP_PENALTY: DROP_PENALTY, PAY_FULL: PAY_FULL, PAY_ZERO: PAY_ZERO, PAY_ZERO_SHARE: PAY_ZERO_SHARE,
    ACCEPT: ACCEPT, MARGIN: MARGIN, OFFER_MORE: OFFER_MORE, SAID_PHONE: SAID_PHONE,
    CONFIDENT: CONFIDENT, OFFSET_MIN_N: OFFSET_MIN_N, OFFSET_MAX_MIN: OFFSET_MAX_MIN,
    CANDIDATES_SHOWN: CANDIDATES_SHOWN, HISTORY_MAX: HISTORY_MAX, TEXT_MAX: TEXT_MAX,
    SAME_NAME: SAME_NAME, DAY_STARTS_AT: DAY_STARTS_AT, RECORD_MATCH_MS: RECORD_MATCH_MS
  };
}));
