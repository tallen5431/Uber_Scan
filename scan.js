/* Camera scanner: point a second phone at the driving phone, read the offer
   card, show the rate. All processing is local — the OCR engine, its model and
   every frame stay on the device. Nothing is uploaded, nothing is recorded. */

(function () {
  'use strict';

  var SETTINGS_KEY = 'uberscan.settings.v1';
  var DEFAULTS = {
    target: 25, band: 15, costPerMile: 0, pad: 0,
    secondsPerItem: 0, fullFrame: false, haptics: true
  };

  // Two readings that agree is the difference between acting on a number and
  // acting on a glitch. Cheap to require when a read takes ~200ms.
  var AGREE_TO_LOCK = 2;
  var MISSES_TO_RESET = 3;

  // How big a picture the reader is handed, which is not a detail and is not
  // only about speed.
  //
  // This used to be a width: scale to 1400 across, and — because the scale was
  // Math.min(2, 1400 / width) — *upscale* anything narrower, by up to double. A
  // reticle on a phone frames something around 700 to 1200px wide, so in
  // practice the reader was handed two to three megapixels of interpolated
  // card. Tesseract does not like that, and it does not fail quietly: measured
  // on this project's own shop-order render, scaled to a range of widths and
  // read with the same engine and the same contrast step,
  //
  //     0.45 MP  no payout        1.26 MP  no payout
  //     0.80 MP  $7.09            1.47 MP  no payout
  //     1.02 MP  $7.09            2.46 MP  no payout   <- what the browser did
  //
  // The payout is the largest text on the card, which is why it is the first
  // thing to go: past about a megapixel its glyphs outgrow the range the
  // recogniser was trained on, and on a shop order that line stands alone with
  // no neighbours to give it context. The whole rest of the card kept reading
  // perfectly, so the failure looked like "the payout is missing" rather than
  // like a bad picture — and every Uber Eats shop order the phone app was
  // pointed at came back unreadable.
  //
  // So the same rule the Pi uses, and the same two numbers: lift a small card
  // to a height worth reading, then hold the whole thing inside a pixel budget.
  // See pipeline.fit_for_ocr, whose comment is about cost and whose real value
  // turns out to be this.
  var OCR_CARD_HEIGHT = 900;
  var MAX_OCR_PIXELS = 1000000;

  // Smallest box worth reading, as a fraction of the preview. Below this there
  // is no room for a payout at a size the engine can resolve, and a box that
  // small is a stray tap rather than an intention.
  var MIN_BOX = 0.08;
  // How near a corner counts as grabbing it rather than the box itself. A
  // finger is about 10mm across on glass; 44px is the smallest target that does
  // not need a second attempt.
  var GRAB = 44;

  var settings = load();
  var worker = null;
  var running = false, frozen = false, busy = false;
  var lastSig = null, agree = 0, misses = 0, locked = false;
  var lastResult = null;

  var el = {};
  ['video', 'frame', 'reticle', 'verdict', 'verdictLabel', 'perHour', 'rawRate', 'vPay', 'vMin',
   'vMile', 'warn', 'statusline', 'btnFreeze', 'photo', 'btnSettings', 'engineNote',
   'stage', 'btnBox', 'adjustNote'
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  var ctx = el.frame.getContext('2d', { willReadFrequently: true });

  /* The settings, with the time of day attached.
   *
   * A DoorDash card gives a deadline where an Uber card gives a duration —
   * "Deliver by 7:15 PM" — and rate() turns that into minutes only if something
   * tells it what time it is. The parser deliberately will not read the clock
   * itself, so that it can be held to a fixed corpus. Without this every
   * delivery card read here came back unjudgeable while the status line said
   * "confirmed", which is the worst pairing available: a card the reader
   * understood perfectly, showing no rate, next to a claim of confidence.
   *
   * Unlike the Pi, a browser has a real clock, so there is nothing to earn. */
  function judged(parsed) {
    var now = new Date();
    var withClock = {};
    for (var k in settings) withClock[k] = settings[k];
    withClock.nowMinutes = now.getHours() * 60 + now.getMinutes();
    return OfferParser.rate(parsed, withClock);
  }

  /* Whether the reading is finished, as opposed to merely repeatable. The
     parser owns the rule — see OfferParser.isWhole — because it was written out
     here and again in the Pi's loop, both said "a total or two legs", and a
     delivery card has neither. */
  function isWhole(parsed) { return OfferParser.isWhole(parsed); }

  /* ---------- settings ---------- */

  function load() {
    var s = {};
    try { s = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch (e) {}
    var out = {};
    for (var k in DEFAULTS) out[k] = (typeof s[k] === typeof DEFAULTS[k]) ? s[k] : DEFAULTS[k];
    // Kept out of DEFAULTS because its absence is meaningful — no box saved
    // means the one in the stylesheet — and because `typeof null` is 'object',
    // which would let any old object through the check above.
    out.box = validBox(s.box);
    return out;
  }

  // A box as [x, y, w, h] fractions of the preview, or null. Anything that is
  // not four usable numbers is treated as no box at all rather than repaired:
  // a half-understood crop reads half a card, which looks like a bad camera.
  function validBox(b) {
    if (!Array.isArray(b) || b.length !== 4) return null;
    for (var i = 0; i < 4; i++) {
      if (typeof b[i] !== 'number' || !isFinite(b[i])) return null;
    }
    if (b[2] < MIN_BOX || b[3] < MIN_BOX) return null;
    if (b[0] < 0 || b[1] < 0 || b[0] + b[2] > 1.001 || b[1] + b[3] > 1.001) return null;
    return [b[0], b[1], b[2], b[3]];
  }

  function save() {
    try {
      var merged = {};
      try { merged = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch (e) {}
      for (var k in settings) merged[k] = settings[k];
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(merged));
    } catch (e) {}
  }

  function buzz(p) {
    if (settings.haptics && navigator.vibrate) { try { navigator.vibrate(p); } catch (e) {} }
  }

  /* ---------- engine ---------- */

  function status(msg) { el.statusline.textContent = msg; }

  async function startEngine() {
    status('loading reader…');
    worker = await Tesseract.createWorker('eng', 1, {
      workerPath: 'vendor/worker.min.js',
      corePath: 'vendor/core',
      langPath: 'vendor/lang',
      gzip: true
    });
    await applyPsm();
    return worker;
  }

  function applyPsm() {
    // A tight crop is a single block of text; a whole phone screen is not.
    return worker.setParameters({ tessedit_pageseg_mode: settings.fullFrame ? '3' : '6' });
  }

  /* ---------- camera ---------- */

  // Browsers only expose a camera on HTTPS or localhost. Over plain http on a
  // LAN address navigator.mediaDevices is simply absent, which surfaces as an
  // unhelpful TypeError unless it is named for what it is.
  function cameraBlockedReason() {
    if (window.isSecureContext === false) return 'insecure';
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'unsupported';
    return null;
  }

  function explainNoCamera(reason) {
    if (reason === 'insecure') {
      el.verdictLabel.textContent = 'CAMERA NEEDS HTTPS';
      el.warn.textContent = 'You are on ' + location.protocol + '//' + location.host +
        '. Browsers only allow camera access over HTTPS or on localhost. ' +
        'The 📷 Photo button below still works — it runs the same reader on a screenshot.';
    } else {
      el.verdictLabel.textContent = 'NO CAMERA';
      el.warn.textContent = 'This browser exposes no camera. Use 📷 Photo, or ⌨ Type.';
    }
    el.warn.hidden = false;
    status('camera unavailable — 📷 Photo still works');
  }

  // These failures need different answers, and calling them all "permission"
  // sends you to a settings page that cannot help.
  function explainCameraError(e) {
    var label = 'CAMERA UNAVAILABLE';
    var msg;
    if (e.name === 'NotFoundError' || e.name === 'DevicesNotFoundError') {
      label = 'NO CAMERA ON THIS DEVICE';
      msg = 'The browser found no camera at all, so this is not a permission ' +
        'problem. If you are on a Raspberry Pi, a CSI camera on libcamera is ' +
        'invisible to browsers — run rpi/scan_pi.py instead, which drives it ' +
        'directly. Otherwise open this page on the phone you want to scan with.';
    } else if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
      label = 'CAMERA PERMISSION DENIED';
      msg = 'This site was refused the camera. Allow it in the browser\'s site ' +
        'settings and reload.';
    } else if (e.name === 'NotReadableError' || e.name === 'TrackStartError') {
      label = 'CAMERA IN USE';
      msg = 'Another app already holds the camera. Close it and reload.';
    } else {
      msg = 'The camera could not start (' + e.name + ': ' + e.message + ').';
    }
    el.verdictLabel.textContent = label;
    el.warn.textContent = msg + ' 📷 Photo below still works on any device.';
    el.warn.hidden = false;
    status('camera unavailable — 📷 Photo still works');
  }

  async function startCamera() {
    status('starting camera…');
    var stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 }, height: { ideal: 1080 }
      },
      audio: false
    });
    el.video.srcObject = stream;
    await el.video.play();
    await new Promise(function (r) {
      if (el.video.videoWidth) return r();
      el.video.onloadedmetadata = r;
    });
  }

  /* ---------- frame capture ---------- */

  // Maps the on-screen reticle back to pixels in the camera's own frame,
  // undoing the object-fit: cover crop the preview applies.
  function sourceRect() {
    var vw = el.video.videoWidth, vh = el.video.videoHeight;
    var box = el.video.getBoundingClientRect();
    var scale = Math.max(box.width / vw, box.height / vh);
    var offX = (vw * scale - box.width) / 2;
    var offY = (vh * scale - box.height) / 2;

    var r = el.reticle.getBoundingClientRect();
    var x = (r.left - box.left + offX) / scale;
    var y = (r.top - box.top + offY) / scale;
    var w = r.width / scale;
    var h = r.height / scale;

    return {
      x: Math.max(0, Math.min(vw, x)),
      y: Math.max(0, Math.min(vh, y)),
      w: Math.max(8, Math.min(vw, w)),
      h: Math.max(8, Math.min(vh, h))
    };
  }

  // Upscale and flatten to high-contrast grey: a decimal point is only a pixel
  // or two through a lens, and it is the character that matters most.
  /* The size to hand the reader, as pipeline.fit_for_ocr decides it: a card
     shorter than OCR_CARD_HEIGHT is lifted to it, and then whatever comes out
     is held inside MAX_OCR_PIXELS. Exported below so a test can check this
     agrees with the Pi's, which is the thing that went wrong. */
  function fitForOcr(w, h) {
    if (!isFinite(w) || !isFinite(h) || w <= 0 || h <= 0) return { w: 1, h: 1 };
    var scale = h < OCR_CARD_HEIGHT ? OCR_CARD_HEIGHT / h : 1;
    var pixels = (w * scale) * (h * scale);
    if (pixels > MAX_OCR_PIXELS) scale *= Math.sqrt(MAX_OCR_PIXELS / pixels);
    return { w: Math.max(1, Math.round(w * scale)),
             h: Math.max(1, Math.round(h * scale)) };
  }

  function grab(source, rect) {
    var sw = rect ? rect.w : source.videoWidth || source.width;
    var sh = rect ? rect.h : source.videoHeight || source.height;
    var fit = fitForOcr(sw, sh);

    el.frame.width = fit.w;
    el.frame.height = fit.h;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';

    if (rect) ctx.drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, el.frame.width, el.frame.height);
    else ctx.drawImage(source, 0, 0, el.frame.width, el.frame.height);

    var img = ctx.getImageData(0, 0, el.frame.width, el.frame.height);
    var p = img.data;
    for (var i = 0; i < p.length; i += 4) {
      var v = p[i] * 0.299 + p[i + 1] * 0.587 + p[i + 2] * 0.114;
      v = (v - 128) * 1.5 + 128;
      p[i] = p[i + 1] = p[i + 2] = v < 0 ? 0 : v > 255 ? 255 : v;
    }
    ctx.putImageData(img, 0, 0);
    return el.frame;
  }

  /* ---------- scanning ---------- */

  async function readOnce(source, rect) {
    var canvas = grab(source, rect);
    var t = performance.now();
    var res = await worker.recognize(canvas);
    var ms = Math.round(performance.now() - t);
    var parsed = OfferParser.parse(res.data.text);
    return { parsed: parsed, ms: ms };
  }

  function consider(parsed) {
    if (!parsed.complete) {
      misses++;
      if (misses >= MISSES_TO_RESET) { locked = false; agree = 0; lastSig = null; lastResult = null; }
      return;
    }
    misses = 0;
    var sig = parsed.pay + '|' + parsed.minutes + '|' + parsed.miles;
    agree = (sig === lastSig) ? agree + 1 : 1;
    lastSig = sig;

    var wasLocked = locked;
    // Agreement is not enough on its own, and the driving screen has known that
    // for a while: two frames that both lose the pickup leg to the same glare
    // agree perfectly with each other, so a fragment can be locked. A card
    // missing a leg is the same pay over less time and therefore always reads
    // *better* than the offer is, which makes an unqualified ACCEPT on half a
    // card the one mistake this screen must not make. Whole means finished — a
    // total, or both legs of a two-leg card — and it is what clears the "?"
    // and what earns the accept buzz.
    locked = agree >= AGREE_TO_LOCK && isWhole(parsed);
    lastResult = parsed;
    if (locked && !wasLocked) buzz(judged(parsed).state === 'go' ? [18, 40, 18] : [45]);
  }

  /* A failed read is a read that found nothing, not a read that did not happen.
   *
   * Neither consider() nor render() used to run on a throw, so every value on
   * the screen kept whatever it had. An engine that throws every cycle — a
   * phone that has run its worker out of memory, a half-cached core — therefore
   * held a green ACCEPT and a dollar figure from an offer that was already
   * gone, indefinitely, admitted to only by 11px of grey status text. That is
   * the worst state this page can reach, and one exception reaches it.
   *
   * The decay machinery already exists and is the whole fix: an incomplete
   * reading counts as a miss, and MISSES_TO_RESET of them clear the verdict.
   * Named rather than inlined so the test can drive this path rather than a
   * second copy of it. */
  function readFailed(e) {
    consider({ complete: false });
    render(0);
    status('read failed: ' + (e && e.message ? e.message : e));
  }

  async function loop() {
    while (running) {
      if (frozen || busy || el.video.readyState < 2) { await sleep(80); continue; }
      busy = true;
      try {
        var out = await readOnce(el.video, settings.fullFrame ? null : sourceRect());
        consider(out.parsed);
        render(out.ms);
      } catch (e) {
        readFailed(e);
      }
      busy = false;
      await sleep(30);
    }
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ---------- render ---------- */

  function money(n, d) { return n === null || !isFinite(n) ? '--' : '$' + n.toFixed(d); }

  function rateText(n) {
    if (typeof n !== 'number' || !isFinite(n)) return '--';
    var big = Math.abs(n) >= 100;
    return (n < 0 ? '-$' : '$') + (big ? Math.round(Math.abs(n))
                                       : Math.abs(n).toFixed(1));
  }

  function render(ms) {
    var p = lastResult;
    var r = p ? judged(p) : { ready: false, state: 'empty' };

    el.verdict.className = 'verdict ' + r.state;
    document.body.classList.toggle('locked', locked);

    // A reading that cannot be true gets no verdict, and names the figure to
    // look at instead. Indexing the three-verdict map with anything else put
    // the word "undefined" on screen where ACCEPT or PASS belongs.
    el.verdictLabel.textContent = !r.ready
      ? 'POINT AT THE OFFER'
      : r.state === 'doubt'
      ? ({ pay: 'CHECK THE PAY', time: 'CHECK THE TIME',
           speed: 'CHECK THE DISTANCE' }[r.doubt] || 'READ AGAIN')
      : ({ go: 'ACCEPT', warn: 'CLOSE CALL', no: 'PASS' }[r.state] + (locked ? '' : ' ?'));

    // The headline is withheld on a reading that cannot be true, exactly as on
    // the Pi's screen. This page is the same decision made on a phone, and it
    // was printing the $3548/hr the other one had just been taught to hide —
    // which is worse than never having hidden it, because a driver checking one
    // screen against the other would believe the one showing a number.
    // "-$12.50", not "$-12.5". The minus belongs outside the currency: wedged
    // between the dollar and the digits it reads as a dash at arm's length,
    // and the keypad and the offers page already write it the other way — so
    // the same offer read as a loss on two screens and as a number on two.
    el.perHour.textContent = (r.ready && r.state !== 'doubt')
      ? rateText(r.perHour) : '--';
    // ...and the same offer before running costs, beside it.
    //
    // The headline is net, and it is labelled "/hr" whether a mileage cost came
    // off it or not — so this screen and the rig's showed two numbers that are
    // only sometimes the same thing, with nothing on either saying which. Shown
    // only where the two actually differ, which is exactly where the difference
    // is worth a driver's attention: repeating a figure beside itself is noise
    // next to the one number that decides an offer.
    var raw = (r.ready && r.state !== 'doubt'
               && typeof r.grossPerHour === 'number'
               && Math.round(r.grossPerHour) !== Math.round(r.perHour))
      ? rateText(r.grossPerHour) + ' raw' : '';
    el.rawRate.textContent = raw;
    el.rawRate.hidden = !raw;

    el.vPay.textContent = p && p.pay !== null ? money(p.pay, 2) : '--';
    // The card's own minutes, not the billed ones. `r.minutes` has the pickup
    // pad and the shopping allowance added, so with either of those set this
    // screen and the rig's showed different numbers under the same label for
    // the same card — and this row exists to be checked against the phone.
    var shownMinutes = (typeof r.cardMinutes === 'number') ? r.cardMinutes
      : (p && typeof p.minutes === 'number' ? p.minutes : null);
    el.vMin.textContent = shownMinutes === null ? '--' : Math.round(shownMinutes);
    el.vMile.textContent = p && p.miles !== null ? p.miles.toFixed(1) : '--';

    // A read can warrant more than one note at once — a recovered decimal and
    // added shopping time are independent facts and both change the number.
    var notes = [];
    // Half a card, said in words. The label above already softens to "ACCEPT ?"
    // when the reading is not whole — and the headline underneath it does not
    // soften at all, which is the wrong way round: the number is the thing being
    // read. A single leg is the same pay over less time, so it always reads
    // *better* than the offer is: "$16.00 3 min away" is a confident green
    // $320/hr for a card whose truth is $35.30. doubt() cannot catch that (3
    // minutes and $16 are both perfectly ordinary) and the distance is not
    // uncertain, so without this there is nothing on the screen to argue with.
    //
    // The same sentence as live.html, deliberately. The two screens are the
    // same decision made in two places and a driver checking one against the
    // other has to find them saying the same thing.
    if (r.ready && p && !isWhole(p)) {
      notes.push('Still reading this card — the journey may not be all there '
                 + 'yet, which makes it look better than it is.');
    }
    if (r.milesUncertain) notes.push('Distance unreadable — showing pay before mileage cost.');
    else if (r.milesCorrected) notes.push('Recovered a decimal in the distance — check the miles.');
    if (r.ready && r.shopMinutes) notes.push('Includes ' + Math.round(r.shopMinutes) + ' min of shopping time.');
    el.warn.textContent = notes.join(' ');
    el.warn.hidden = !notes.length;

    status(ms + 'ms · ' + (locked ? 'confirmed' : (r.ready ? 'confirming…' : 'searching…')) +
      (settings.fullFrame ? ' · whole frame' : ' · in box'));
  }

  /* ---------- controls ---------- */

  el.btnFreeze.addEventListener('click', function () {
    frozen = !frozen;
    document.body.classList.toggle('frozen', frozen);
    el.btnFreeze.textContent = frozen ? '▶ Scan' : '⏸ Hold';
  });

  el.photo.addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    // The reader is about 15MB and loads in the background; on a cold start
    // over a phone connection that is a good few seconds, and this button is
    // live the whole time. Pressed early, `readOnce` reached for a `worker`
    // that was still null and threw inside an async `onload` — where there is
    // no caller to catch it. Nothing appeared on screen at all: the picture
    // was picked, the file dialog closed, and the page went on saying
    // "loading reader…" as though the press had never happened.
    if (!worker) {
      status('still loading the reader — try that photo again in a moment');
      e.target.value = '';
      return;
    }
    var img = new Image();
    img.onload = async function () {
      frozen = true;
      document.body.classList.add('frozen');
      el.btnFreeze.textContent = '▶ Scan';
      status('reading photo…');
      try {
        // A still has no successive frames to agree with, so one good read is
        // all the agreement there can be — but it still has to be a *whole*
        // card, for the same reason a live one does.
        var out = await readOnce(img, null);
        lastResult = out.parsed;
        locked = isWhole(out.parsed);
        render(out.ms);
      } catch (err) {
        // Same rule as the live loop: a read that failed must not leave the
        // last card's numbers standing as though they were this photo's.
        readFailed(err);
      }
      URL.revokeObjectURL(img.src);
      // Or the same file picked twice in a row fires no `change` at all.
      e.target.value = '';
    };
    img.onerror = function () {
      status('could not open that picture');
      URL.revokeObjectURL(img.src);
      e.target.value = '';
    };
    img.src = URL.createObjectURL(file);
  });

  el.btnSettings.addEventListener('click', function () {
    document.getElementById('setTarget').value = settings.target;
    document.getElementById('setBand').value = settings.band;
    document.getElementById('setCost').value = settings.costPerMile;
    document.getElementById('setPad').value = settings.pad;
    document.getElementById('setItemSecs').value = settings.secondsPerItem;
    document.getElementById('setFullFrame').checked = settings.fullFrame;
    document.getElementById('settingsSheet').hidden = false;
  });

  document.querySelectorAll('[data-close]').forEach(function (b) {
    b.addEventListener('click', function () { document.getElementById(b.dataset.close).hidden = true; });
  });

  function bind(id, key, parse, min, max) {
    document.getElementById(id).addEventListener('input', function (e) {
      var v = parse(e.target.value);
      settings[key] = isFinite(v) ? Math.min(max, Math.max(min, v)) : DEFAULTS[key];
      save();
      if (lastResult) render(0);
    });
  }
  bind('setTarget', 'target', parseFloat, 0, 1000);
  bind('setBand', 'band', parseFloat, 0, 50);
  bind('setCost', 'costPerMile', parseFloat, 0, 10);
  bind('setPad', 'pad', parseInt, 0, 120);
  bind('setItemSecs', 'secondsPerItem', parseInt, 0, 600);

  document.getElementById('setFullFrame').addEventListener('change', function (e) {
    settings.fullFrame = e.target.checked;
    el.reticle.classList.toggle('full', settings.fullFrame);
    applyBox();
    save();
    if (worker) applyPsm();
  });

  document.getElementById('setResetBox').addEventListener('click', function () {
    settings.box = null;
    applyBox();
    save();
    status('box back to its default');
  });

  /* ---------- the box ----------
   *
   * The reticle decides what gets read, and until now it was 7% in from each
   * side, 34% down — a rectangle that suits one phone at one distance and
   * cannot be argued with. A card that does not sit inside it is not read at
   * all: the crop is what the engine sees, so a box on the wrong part of the
   * screen returns the wrong text, or none, with nothing on screen to say the
   * box is why. Every other knob in here is adjustable and this was the one
   * that decides whether any of them get a number to work on.
   *
   * Stored as fractions of the preview rather than pixels, because the same
   * phone rotated is a different pixel size and the box means the same thing in
   * both. sourceRect() already maps the reticle's own rectangle back through
   * the object-fit: cover crop, so moving the element is all this has to do.
   */
  function applyBox() {
    var custom = settings.box && !settings.fullFrame;
    ['left', 'top', 'width', 'height'].forEach(function (prop, i) {
      el.reticle.style[prop] = custom ? (settings.box[i] * 100) + '%' : '';
    });
  }

  function stageRect() { return el.stage.getBoundingClientRect(); }

  // Where the box is now, in fractions — read off the element so the CSS
  // default and a stored box are the same kind of thing to drag.
  function currentBox() {
    if (settings.box && !settings.fullFrame) return settings.box.slice();
    var s = stageRect(), r = el.reticle.getBoundingClientRect();
    return [(r.left - s.left) / s.width, (r.top - s.top) / s.height,
            r.width / s.width, r.height / s.height];
  }

  function adjusting() { return document.body.classList.contains('adjusting'); }

  function setAdjusting(on) {
    document.body.classList.toggle('adjusting', on);
    el.adjustNote.hidden = !on;
    el.btnBox.textContent = on ? '▣ Done' : '▣ Box';
    if (on) {
      el.adjustNote.textContent = settings.fullFrame
        ? 'Whole-frame scanning is on, so the box is not used. Turn it off in ⚙︎ to read a box.'
        : 'Drag the box onto the offer card, or a corner to resize. Reading carries on.';
    }
  }

  el.btnBox.addEventListener('click', function () { setAdjusting(!adjusting()); });

  var drag = null;

  el.reticle.addEventListener('pointerdown', function (e) {
    if (!adjusting() || settings.fullFrame) return;
    e.preventDefault();
    el.reticle.setPointerCapture(e.pointerId);
    var r = el.reticle.getBoundingClientRect();
    // Which corner, if any, is being held. Nearest wins, and only within
    // reach — anywhere else in the box moves the whole thing.
    var edgeX = (e.clientX - r.left < GRAB) ? -1 : (r.right - e.clientX < GRAB) ? 1 : 0;
    var edgeY = (e.clientY - r.top < GRAB) ? -1 : (r.bottom - e.clientY < GRAB) ? 1 : 0;
    drag = {
      id: e.pointerId, x: e.clientX, y: e.clientY,
      box: currentBox(), edgeX: edgeX, edgeY: edgeY
    };
    buzz(8);
  });

  el.reticle.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    var s = stageRect();
    var dx = (e.clientX - drag.x) / s.width;
    var dy = (e.clientY - drag.y) / s.height;
    var b = drag.box;
    var next;

    if (!drag.edgeX && !drag.edgeY) {
      // Moving: the size is fixed, so the position is simply clamped to the
      // preview rather than allowed to run off it.
      next = [Math.min(1 - b[2], Math.max(0, b[0] + dx)),
              Math.min(1 - b[3], Math.max(0, b[1] + dy)), b[2], b[3]];
    } else {
      var x0 = b[0], y0 = b[1], x1 = b[0] + b[2], y1 = b[1] + b[3];
      if (drag.edgeX < 0) x0 = Math.min(x1 - MIN_BOX, Math.max(0, x0 + dx));
      if (drag.edgeX > 0) x1 = Math.max(x0 + MIN_BOX, Math.min(1, x1 + dx));
      if (drag.edgeY < 0) y0 = Math.min(y1 - MIN_BOX, Math.max(0, y0 + dy));
      if (drag.edgeY > 0) y1 = Math.max(y0 + MIN_BOX, Math.min(1, y1 + dy));
      next = [x0, y0, x1 - x0, y1 - y0];
    }
    settings.box = next;
    applyBox();
  });

  function endDrag(e) {
    if (!drag || (e && e.pointerId !== drag.id)) return;
    drag = null;
    // Saved on release rather than on every move: a drag is one decision, and
    // localStorage is synchronous.
    settings.box = validBox(settings.box) || null;
    applyBox();
    save();
  }
  el.reticle.addEventListener('pointerup', endDrag);
  el.reticle.addEventListener('pointercancel', endDrag);

  /* ---------- boot ---------- */

  // A Pi running its own scanner has a camera this page can never reach, so
  // sending the driver to the browser camera API only produces NotFoundError.
  //
  // Asked *after* this device's own camera has failed, never before. Asked
  // first, it answers a question about the server rather than about the browser
  // in front of the driver: a phone opening this page over https has a working
  // camera of its own and was being redirected away from it, so the browser
  // scanner was unreachable from any device as soon as the rig existed. A
  // NotFoundError with a Pi scanner on the other end is the one combination
  // that actually means "you want the other page".
  async function piScannerPresent() {
    try {
      var res = await fetch('/api/status', { cache: 'no-store' });
      if (!res.ok) return false;
      var status = await res.json();
      return !!(status.scanner && status.scanner.enabled);
    } catch (e) {
      return false;      // no server API here: this is a plain phone browser
    }
  }

  (async function () {
    el.reticle.classList.toggle('full', settings.fullFrame);
    applyBox();
    try {
      await startEngine();
    } catch (e) {
      status('reader failed to load: ' + e.message);
      return;
    }
    var blocked = cameraBlockedReason();
    if (blocked) {
      explainNoCamera(blocked);
      return;
    }
    try {
      await startCamera();
      running = true;
      loop();
    } catch (e) {
      // No camera here and a rig on the other end: the driver wants the page
      // that shows what the rig can see. Anything else — permission refused,
      // camera busy — is this device's own problem and is explained in place,
      // because sending them away would hide the one message that can fix it.
      var noCameraHere = (e.name === 'NotFoundError'
                          || e.name === 'DevicesNotFoundError');
      if (noCameraHere && await piScannerPresent()) {
        location.replace('live.html');
        return;
      }
      explainCameraError(e);
    }
  })();

  // Exposed so the test harness can drive the same pipeline headlessly.
  window.__scan = {
    readImage: async function (src) {
      var img = new Image();
      await new Promise(function (r, j) { img.onload = r; img.onerror = j; img.src = src; });
      var out = await readOnce(img, null);
      lastResult = out.parsed;
      locked = isWhole(out.parsed);
      render(out.ms);
      return { parsed: out.parsed, ms: out.ms, rate: judged(out.parsed) };
    },
    fitForOcr: fitForOcr,
    /* Drive the read-failed path without breaking the engine to do it: this is
       the branch where a screen full of last offer's numbers can survive an
       exception, and it is only reachable by throwing. */
    failRead: function (times) {
      for (var i = 0; i < (times || 1); i++) {
        readFailed(new Error('forced'));
      }
    },
    ready: function () { return !!worker; }
  };
})();
