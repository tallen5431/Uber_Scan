/* Uber Scan — offer rate calculator.
   Everything lives in localStorage and the page works with no rig anywhere
   near it; the one call it makes is to hand each logged offer to the rig's
   journal when there is one to answer — see journalRow and flushUnsent. */

(function () {
  'use strict';

  var SETTINGS_KEY = 'uberscan.settings.v1';
  var HISTORY_KEY = 'uberscan.history.v1';
  var DRAFT_KEY = 'uberscan.draft.v1';
  var HISTORY_MAX = 100;
  var DRAFT_TTL = 3 * 60 * 1000;  // an offer older than this is long gone

  var DEFAULTS = {
    target: 25,      // $/hour that earns a green ACCEPT
    band: 15,        // % below target that still shows amber
    costPerMile: 0,  // gas + wear, subtracted from the offer
    pad: 0,          // minutes added to every offer (pickup drive, waiting)
    haptics: true
  };

  var settings = loadSettings();
  var history = loadHistory();

  var FIELDS = ['pay', 'minutes', 'miles'];
  var entry = { pay: '', minutes: '', miles: '' };
  var active = 'pay';

  var el = {
    verdict: document.getElementById('verdict'),
    verdictLabel: document.getElementById('verdictLabel'),
    perHour: document.getElementById('perHour'),
    perMile: document.getElementById('perMile'),
    perMileLabel: document.getElementById('perMileLabel'),
    perMin: document.getElementById('perMin'),
    rawRate: document.getElementById('rawRate'),
    netPay: document.getElementById('netPay'),
    netLabel: document.getElementById('netLabel'),
    padHint: document.getElementById('padHint'),
    fields: document.getElementById('fields'),
    keypad: document.getElementById('keypad'),
    histStats: document.getElementById('histStats'),
    histList: document.getElementById('histList')
  };

  /* ---------- storage ---------- */

  function loadSettings() {
    var s = {};
    try { s = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch (e) { s = {}; }
    var out = {};
    for (var k in DEFAULTS) {
      out[k] = (typeof s[k] === typeof DEFAULTS[k]) ? s[k] : DEFAULTS[k];
    }
    return out;
  }

  // Read, merge, write. This page knows about the five settings in DEFAULTS,
  // but it shares SETTINGS_KEY with the camera scanner on scan.html, which
  // stores more — secondsPerItem and fullFrame. loadSettings() copies only the
  // keys it recognises, so writing `settings` back wholesale deleted the rest.
  // One keystroke in any field here, or toggling haptics, silently reset the
  // shopping allowance to zero, and scan.html then rated Shop & Deliver offers
  // as if the shopping took no time: at 90s an item, "$26.10, 14 items, 38 min"
  // went from $22.75/hr amber to $33.87/hr green, with the "includes N min of
  // shopping time" note quietly gone. Nothing resyncs the two pages, so it
  // stayed wrong until the driver noticed and typed it again.
  function saveSettings() {
    var stored = {};
    try { stored = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch (e) {}
    for (var k in settings) stored[k] = settings[k];
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(stored)); } catch (e) {}
  }

  function loadHistory() {
    try {
      var h = JSON.parse(localStorage.getItem(HISTORY_KEY));
      return Array.isArray(h) ? h : [];
    } catch (e) { return []; }
  }

  function saveHistory() {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(history)); } catch (e) {}
  }

  // Uber's offer card draws over other apps and can take the screen mid-entry.
  // Every keystroke is saved so coming back does not cost you what you typed.
  function saveDraft() {
    try {
      if (entry.pay === '' && entry.minutes === '' && entry.miles === '') {
        localStorage.removeItem(DRAFT_KEY);
      } else {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({
          entry: entry, active: active, t: Date.now()
        }));
      }
    } catch (e) {}
  }

  function restoreDraft() {
    var d;
    try { d = JSON.parse(localStorage.getItem(DRAFT_KEY)); } catch (e) { return; }
    if (!d || !d.entry || Date.now() - d.t > DRAFT_TTL) return;
    for (var i = 0; i < FIELDS.length; i++) {
      var f = FIELDS[i];
      if (typeof d.entry[f] === 'string') entry[f] = d.entry[f];
    }
    if (FIELDS.indexOf(d.active) !== -1) active = d.active;
  }

  /* ---------- math ---------- */

  function num(str) {
    var n = parseFloat(str);
    return isFinite(n) ? n : 0;
  }

  // The whole app in one function: turn an offer into rates and a verdict.
  function calc() {
    var pay = num(entry.pay);
    var miles = num(entry.miles);
    // The time on the card, kept separate from the time the arithmetic uses.
    // `ready` was tested against the padded total, so with a pickup pad set and
    // nothing typed in the minutes field the app had a complete offer: pay, no
    // time, and a confident rate worked out from the pad alone.
    var typedMinutes = num(entry.minutes);
    var minutes = typedMinutes + settings.pad;

    var ready = pay > 0 && typedMinutes > 0 && minutes > 0;

    // The verdict comes from the same function the two camera screens use, not
    // from a second copy of the rule beside it.
    //
    // This screen worked out `state` itself, and the copy had gone out of step:
    // rate() caps a verdict at CLOSE CALL when a cost per mile is configured
    // and no distance could be charged, because the rate is then an upper bound
    // being compared against a net target. This one had no such branch. Fed the
    // driver's own 1,672 recorded offers at their own settings — target $25,
    // band 15%, $0.30/mi — the two disagreed on 16, and every one of the 16 was
    // this screen showing a green ACCEPT and the ACCEPT buzz where scan.html
    // and live.html show amber. All 16 were cards printing no distance, of
    // which the driver has 124. $18.77 over 25 minutes with the distance blank:
    // ACCEPT $45.0/hr here, CLOSE CALL on the rig.
    //
    // The wrong-ACCEPT direction, on the one screen a driver reaches for
    // precisely when the reader has failed and they cannot cross-check it.
    //
    // `milesChecked: true` because these figures were typed, not read: rate()
    // recovers a lost decimal from a distance it believes came off a camera,
    // and 85 miles typed by hand is 85 miles.
    var judged = { ready: false, state: 'empty' };
    if (ready && typeof OfferParser !== 'undefined' && OfferParser.rate) {
      judged = OfferParser.rate(
        { complete: true, pay: pay, minutes: typedMinutes,
          miles: miles > 0 ? miles : null, milesChecked: true, items: 0 },
        settings) || judged;
    }

    var cost = judged.ready ? judged.cost : miles * settings.costPerMile;
    var net = judged.ready ? judged.net : pay - cost;
    var perHour = judged.ready ? judged.perHour : null;
    // The same offer before the running cost, so this screen can say which of
    // the two numbers it is showing. Over the same denominator as `perHour`,
    // including the pad, because the point of it is to be the *same* sum with
    // one term removed — a raw rate over a different number of minutes is a
    // third figure, and three rates on one screen explain nothing.
    var grossPerHour = judged.ready ? judged.grossPerHour : null;
    var perMin = judged.ready ? judged.perMin : null;
    // Net, like perHour, so the two agree about what a dollar means. This was
    // gross while the rate beside it was net, so the same offer read $1.97/mi
    // here and $1.67/mi on the Pi, and neither screen said why.
    //
    // Worked out here rather than taken from rate() for the one case rate()
    // has no answer to: pay and a distance typed with the minutes still blank.
    // rate() is not ready then and returns nothing, and a driver part way
    // through an entry was already being shown a per-mile figure.
    var perMile = judged.ready ? judged.perMile
      : ((pay > 0 && miles > 0) ? (pay - miles * settings.costPerMile) / miles : null);

    return {
      ready: ready, pay: pay, miles: miles,
      minutes: judged.ready ? judged.minutes : minutes,
      typedMinutes: typedMinutes,
      cost: cost, net: net,
      perHour: perHour, grossPerHour: grossPerHour,
      perMin: perMin, perMile: perMile,
      // The same impossibility test the camera's readings get, on the figures
      // as typed. A slipped decimal point is not only an OCR failure: $1184 is
      // two keys away from $11.84 on this pad, and the app answered it with a
      // green ACCEPT and a congratulatory buzz.
      doubt: judged.ready ? judged.doubt : null,
      // Whether the rate above is the offer or only a ceiling on it — the field
      // this screen had no idea existed.
      uncosted: !!judged.uncosted,
      state: ready ? judged.state : 'empty'
    };
  }

  /* ---------- formatting ---------- */

  function money(n, decimals) {
    if (n === null || !isFinite(n)) return '--';
    var neg = n < 0;
    var v = Math.abs(n).toFixed(decimals);
    return (neg ? '-$' : '$') + v;
  }

  function rateText(perHour) {
    if (perHour === null) return '--';
    // Whole dollars once the number gets wide, so it always fits on one line.
    var decimals = Math.abs(perHour) >= 100 ? 0 : 1;
    return money(perHour, decimals);
  }

  function fieldText(name) {
    var raw = entry[name];
    if (name === 'pay') return raw === '' ? '$0' : '$' + raw;
    return raw === '' ? '0' : raw;
  }

  function ago(ts) {
    var mins = Math.round((Date.now() - ts) / 60000);
    if (mins < 1) return 'now';
    if (mins < 60) return mins + 'm ago';
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    return Math.round(hrs / 24) + 'd ago';
  }

  /* ---------- render ---------- */

  var lastState = 'empty';

  function render() {
    var r = calc();

    // Withheld on a reading that cannot be true, as on the two camera screens.
    // The typed pay, time and distance stay below it — they are what the driver
    // goes back and corrects.
    el.perHour.textContent = r.state === 'doubt' ? '--' : rateText(r.perHour);
    // ...and the raw figure beside it, on the same terms as the two camera
    // screens. The headline here is net and labelled "/hr" whether a mileage
    // cost came off it or not, so a driver typing an offer in to check the rig
    // was comparing two numbers that are only sometimes the same thing. Shown
    // only where they differ: a figure repeated beside itself is noise next to
    // the one number that decides an offer.
    //
    // ...and the other thing this slot has to be able to say. With no distance
    // typed and a cost per mile configured, nothing came off the pay: the
    // figure beside it is a CEILING, and the verdict has just been capped at
    // CLOSE CALL because of it. Without a word here that cap is an amber with
    // no reason on the screen — which is what the driving screen looked like
    // for as long as its own `uncosted` never reached it.
    //
    // The two cannot both apply: gross equals net exactly when nothing was
    // charged, so "$X raw" is hidden in precisely the case this appears.
    var raw = r.state === 'doubt' ? ''
      : r.uncosted ? 'ceiling — no distance'
      : (typeof r.grossPerHour === 'number' && r.grossPerHour !== null
         && Math.round(r.grossPerHour) !== Math.round(r.perHour))
      ? rateText(r.grossPerHour) + ' raw' : '';
    el.rawRate.textContent = raw;
    el.rawRate.hidden = !raw;
    // Withheld on the same terms as the headline above them.
    //
    // The headline blanked to "--" and CHECK THE PAY, and these three carried
    // on printing the same impossible number in smaller type: $1030 over 31
    // minutes gave "$33.23" per minute and "$1030.00" net pay under a refusal,
    // and $1184 over 20 minutes gave "$59.20" and "$148.00" per mile. That is
    // not a refusal, it is a refusal with the answer written underneath it.
    //
    // The driving screen already decided this, in the same words: "Hiding the
    // headline rate and leaving '$303/mi' underneath it withholds nothing: it
    // is the same impossible number, smaller." This screen is the one a driver
    // opens to check the rig against, so it is the last place that should
    // quantify what it just refused.
    var refused = r.state === 'doubt';
    el.perMile.textContent = (refused || r.perMile === null)
      ? '--' : money(r.perMile, 2);
    el.perMin.textContent = (refused || r.perMin === null)
      ? '--' : money(r.perMin, 2);
    el.netPay.textContent = (!refused && r.pay > 0) ? money(r.net, 2) : '--';
    el.netLabel.textContent = settings.costPerMile > 0 ? 'net pay' : 'trip pay';
    el.perMileLabel.textContent = settings.costPerMile > 0 ? 'net per mile' : 'per mile';

    el.verdict.className = 'verdict ' + r.state;
    el.verdictLabel.textContent = r.state === 'doubt'
      ? ({ pay: 'CHECK THE PAY', time: 'CHECK THE TIME',
           speed: 'CHECK THE DISTANCE' }[r.doubt] || 'CHECK THAT AGAIN')
      : ({
          go: 'ACCEPT',
          warn: 'CLOSE CALL',
          no: 'PASS',
          empty: 'ENTER OFFER'
        }[r.state] || '');

    // A distinct buzz the moment the answer flips, so a glance is optional.
    if (r.state !== lastState && r.state !== 'empty') {
      buzz(r.state === 'go' ? [18, 40, 18] : (r.state === 'no' ? [55] : [22]));
    }
    lastState = r.state;

    for (var i = 0; i < FIELDS.length; i++) {
      document.getElementById('f-' + FIELDS[i]).textContent = fieldText(FIELDS[i]);
    }
    var buttons = el.fields.querySelectorAll('.field');
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].classList.toggle('active', buttons[j].dataset.field === active);
    }

    el.padHint.textContent = settings.pad + ' min' +
      (settings.costPerMile > 0 ? '  ·  $' + settings.costPerMile.toFixed(2) + '/mi cost' : '') +
      '  ·  target $' + settings.target + '/hr';
  }

  /* ---------- input ---------- */

  function buzz(pattern) {
    if (settings.haptics && navigator.vibrate) {
      try { navigator.vibrate(pattern); } catch (e) {}
    }
  }

  function press(key) {
    if (key === 'next') {
      active = FIELDS[(FIELDS.indexOf(active) + 1) % FIELDS.length];
    } else if (key === 'clear') {
      entry = { pay: '', minutes: '', miles: '' };
      active = 'pay';
      lastState = 'empty';
    } else if (key === 'back') {
      if (entry[active] === '') {
        // Backspace on an empty field steps back to the previous one.
        var i = FIELDS.indexOf(active);
        active = FIELDS[(i + FIELDS.length - 1) % FIELDS.length];
      } else {
        entry[active] = entry[active].slice(0, -1);
      }
    } else if (key === 'log') {
      logEntry();
      return;
    } else {
      entry[active] = append(entry[active], key);
    }
    buzz(8);
    saveDraft();
    render();
  }

  function append(current, key) {
    if (key === '.') {
      return current.indexOf('.') === -1 ? (current === '' ? '0.' : current + '.') : current;
    }
    var next = current + key;
    var dot = next.indexOf('.');
    if (dot !== -1 && next.length - dot > 3) return current;   // max 2 decimals
    if (next.replace('.', '').length > 6) return current;      // sanity cap
    if (next.length > 1 && next[0] === '0' && next[1] !== '.') next = next.slice(1);
    return next;
  }

  el.keypad.addEventListener('click', function (e) {
    var btn = e.target.closest('.key');
    if (btn) press(btn.dataset.key);
  });

  el.fields.addEventListener('click', function (e) {
    var btn = e.target.closest('.field');
    if (btn) { active = btn.dataset.field; buzz(8); saveDraft(); render(); }
  });

  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT') return;
    if (e.key >= '0' && e.key <= '9') press(e.key);
    else if (e.key === '.') press('.');
    else if (e.key === 'Backspace') press('back');
    else if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); press('next'); }
    else if (e.key === 'Escape') press('clear');
    else return;
    e.preventDefault();
  });

  /* ---------- history ---------- */

  function logEntry() {
    var r = calc();
    if (!r.ready) { toast('Enter pay and minutes first'); return; }
    // A reading this screen has just refused to rate cannot be logged as a
    // rate. `ready` stays true on a doubt — every number is still there,
    // because on the camera side the row has to reach the journal — so this
    // gate let one straight through: twenty offers at $18/hr plus one $1030
    // over 31 minutes turned the summary above the list into "avg $112 / best
    // $1993 / 100%". One mistyped payout, and the only record this screen keeps
    // is worthless until the driver finds and deletes the row.
    //
    // Refused rather than logged-and-excluded, because unlike the journal this
    // list is not evidence about the reader — it is a driver's own note of
    // offers they saw, and the right answer to "$1184?" is to fix the entry.
    if (r.state === 'doubt') {
      toast({ pay: 'Check the pay before logging',
              time: 'Check the time before logging',
              speed: 'Check the distance before logging' }[r.doubt]
            || 'Check that entry before logging');
      buzz([55]);
      return;
    }
    // `logged`, not `entry`: `entry` is the draft this page is typing into,
    // and a local by that name shadowed it — the clear at the end of this
    // function then wrote to the local, and the fields stayed full.
    var logged = {
      t: Date.now(),
      pay: r.pay,
      minutes: r.minutes,
      miles: r.miles,
      perHour: r.perHour,
      state: r.state,
      // The same offer as a journal row, built now while `r` is in hand, and
      // whether it has reached the rig. See sendToJournal.
      row: journalRow(r),
      sent: false
    };
    history.unshift(logged);
    if (history.length > HISTORY_MAX) history.length = HISTORY_MAX;
    saveHistory();
    buzz([12, 30, 12]);
    flushUnsent();
    toast('Logged ' + rateText(r.perHour) + '/hr');
    entry = { pay: '', minutes: '', miles: '' };
    active = 'pay';
    lastState = 'empty';
    saveDraft();
    render();
  }

  /* A typed offer as the journal would have written it.
   *
   * This page kept its own list, in this browser, capped at a hundred, and
   * that was the whole of the record for anything typed here — no journal, no
   * sync to the box at home, no offers page, no shift line, no advice. The
   * night the camera cannot read is the night offers get typed, so the
   * offers most likely to be missing from the record were exactly the ones
   * entered by hand.
   *
   * The row is shaped like a reading so the rest of the program needs no
   * special case for it: an `id` and a `seq` so the sync can tell it from a
   * copy of itself, `whole` and `settled` because a typed figure is complete
   * and still, and NO `kind`, because the offers page drops kinds it has not
   * heard of and a typed offer is an offer. `typed` says what it is. The
   * figures are calc()'s, which are OfferParser.rate()'s — the same arithmetic
   * the camera's rows carry, over the same padded minutes. */
  function journalRow(r) {
    var at = Date.now();
    return {
      v: 1, typed: true,
      id: 'k' + at.toString(36) + Math.random().toString(36).slice(2, 8),
      seq: 1, at: at, firstAt: at,
      pay: r.pay, minutes: r.typedMinutes,
      miles: r.miles > 0 ? r.miles : null,
      perHour: r.perHour, grossPerHour: r.grossPerHour, perMile: r.perMile,
      cost: r.cost, billedMinutes: r.minutes,
      state: r.state, doubt: r.doubt || null,
      target: settings.target, band: settings.band,
      costPerMile: settings.costPerMile,
      legs: 0, whole: true, settled: true, locked: true, suspect: false,
      milesCorrected: false, milesUncertain: false, hasTotal: false
    };
  }

  /* Send every entry that has not reached the rig, oldest first.
   *
   * Through /api/journal/ingest, which is the door the sync uses and which
   * de-duplicates on the row's own id — so a row sent twice is stored once,
   * and this can simply try again. Nothing here waits: an app on a phone
   * with no rig anywhere near it is the normal case for this page, and it
   * must go on working exactly as it did. An entry that never arrives is
   * kept here and says so in the history; the next LOG, or the next open,
   * tries it again. */
  var flushing = false;
  function flushUnsent() {
    if (flushing) return;
    var unsent = history.filter(function (h) { return h.row && h.sent === false; });
    if (!unsent.length) return;
    flushing = true;
    var body = unsent.slice().reverse().map(function (h) {
      return JSON.stringify(h.row);
    }).join('\n') + '\n';
    fetch('/api/journal/ingest', { method: 'POST', body: body,
                                   headers: { 'Content-Type': 'application/x-ndjson' } })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(res.status); })
      .then(function (answer) {
        if (!answer || answer.ok !== true) throw new Error('refused');
        unsent.forEach(function (h) { h.sent = true; });
        saveHistory();
        renderHistory();
      })
      .catch(function () {
        toast(unsent.length === 1 ? 'Kept on this phone — the rig did not answer'
                                  : unsent.length + ' kept on this phone — the rig did not answer');
      })
      .then(function () { flushing = false; });
  }

  function renderHistory() {
    if (!history.length) {
      el.histStats.innerHTML = '';
      el.histList.innerHTML = '<li class="empty-msg">No offers logged yet. Tap LOG on an offer to keep it.</li>';
      return;
    }
    var sum = 0, best = -Infinity, greens = 0;
    for (var i = 0; i < history.length; i++) {
      sum += history[i].perHour;
      if (history[i].perHour > best) best = history[i].perHour;
      if (history[i].state === 'go') greens++;
    }
    el.histStats.innerHTML =
      '<div>' + rateText(sum / history.length) + '<small>average</small></div>' +
      '<div>' + rateText(best) + '<small>best</small></div>' +
      '<div>' + Math.round(greens / history.length * 100) + '%<small>at target</small></div>';

    var html = '';
    for (var j = 0; j < history.length; j++) {
      var h = history[j];
      html += '<li>' +
        '<span class="dot ' + h.state + '"></span>' +
        '<span class="big">' + rateText(h.perHour) + '/hr</span>' +
        '<span class="meta">' + money(h.pay, 2) + ' · ' + round1(h.minutes) + ' min' +
          (h.miles > 0 ? ' · ' + round1(h.miles) + ' mi' : '') +
          // Only the entries that have NOT reached the rig say anything: a
          // list of a hundred rows each saying "on the rig" is a list nobody
          // reads, and the one that is not is the one that matters.
          (h.row && h.sent === false ? ' · <em>kept here only</em>' : '') +
        '</span>' +
        '<span class="when">' + ago(h.t) + '</span>' +
      '</li>';
    }
    el.histList.innerHTML = html;
  }

  function round1(n) {
    return (Math.round(n * 10) / 10).toString();
  }

  document.getElementById('clearHistory').addEventListener('click', function () {
    history = [];
    saveHistory();
    renderHistory();
  });

  /* ---------- sheets ---------- */

  function openSheet(id) {
    document.getElementById(id).hidden = false;
  }

  document.getElementById('openSettings').addEventListener('click', function () {
    document.getElementById('setTarget').value = settings.target;
    document.getElementById('setBand').value = settings.band;
    document.getElementById('setCost').value = settings.costPerMile;
    document.getElementById('setPad').value = settings.pad;
    document.getElementById('setHaptics').checked = settings.haptics;
    openSheet('settingsSheet');
  });

  document.getElementById('openHistory').addEventListener('click', function () {
    renderHistory();
    openSheet('historySheet');
  });

  var closers = document.querySelectorAll('[data-close]');
  for (var c = 0; c < closers.length; c++) {
    closers[c].addEventListener('click', function (e) {
      document.getElementById(e.target.dataset.close).hidden = true;
    });
  }

  var sheets = document.querySelectorAll('.sheet');
  for (var s = 0; s < sheets.length; s++) {
    sheets[s].addEventListener('click', function (e) {
      if (e.target.classList.contains('sheet')) e.target.hidden = true;
    });
  }

  function bindSetting(id, key, parse, min, max) {
    document.getElementById(id).addEventListener('input', function (e) {
      var v = parse(e.target.value);
      if (!isFinite(v)) v = DEFAULTS[key];
      settings[key] = Math.min(max, Math.max(min, v));
      saveSettings();
      render();
    });
  }

  bindSetting('setTarget', 'target', parseFloat, 0, 1000);
  bindSetting('setBand', 'band', parseFloat, 0, 50);
  bindSetting('setCost', 'costPerMile', parseFloat, 0, 10);
  bindSetting('setPad', 'pad', parseInt, 0, 120);

  document.getElementById('setHaptics').addEventListener('change', function (e) {
    settings.haptics = e.target.checked;
    saveSettings();
    buzz(10);
  });

  /* ---------- toast ---------- */

  var toastEl = document.createElement('div');
  toastEl.id = 'toast';
  document.body.appendChild(toastEl);
  var toastTimer;

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, 1600);
  }

  /* ---------- boot ---------- */

  restoreDraft();
  render();
  // Anything logged while the rig was out of reach goes now, if it is back.
  flushUnsent();

  // Show the way to the rig's own screen, but only on the rig. Asked once; a
  // failure to answer leaves the link hidden, which is right for the phone
  // this page mostly runs on — there is no camera there to watch.
  fetch('/api/status')
    .then(function (r) { return r.json(); })
    .then(function (s) {
      var live = document.getElementById('toLive');
      if (live && s && s.scanner && s.scanner.enabled) live.hidden = false;
    })
    .catch(function () {});

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () {});
    });
  }
})();
