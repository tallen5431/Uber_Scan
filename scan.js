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
  var MAX_OCR_WIDTH = 1400;   // beyond this the engine slows with no gain

  var settings = load();
  var worker = null;
  var running = false, frozen = false, busy = false;
  var lastSig = null, agree = 0, misses = 0, locked = false;
  var lastResult = null;

  var el = {};
  ['video', 'frame', 'reticle', 'verdict', 'verdictLabel', 'perHour', 'vPay', 'vMin',
   'vMile', 'warn', 'statusline', 'btnFreeze', 'photo', 'btnSettings', 'engineNote'
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  var ctx = el.frame.getContext('2d', { willReadFrequently: true });

  /* ---------- settings ---------- */

  function load() {
    var s = {};
    try { s = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch (e) {}
    var out = {};
    for (var k in DEFAULTS) out[k] = (typeof s[k] === typeof DEFAULTS[k]) ? s[k] : DEFAULTS[k];
    return out;
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
  function grab(source, rect) {
    var sw = rect ? rect.w : source.videoWidth || source.width;
    var sh = rect ? rect.h : source.videoHeight || source.height;
    var scale = Math.min(2, MAX_OCR_WIDTH / sw);
    if (!isFinite(scale) || scale <= 0) scale = 1;

    el.frame.width = Math.round(sw * scale);
    el.frame.height = Math.round(sh * scale);
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
    locked = agree >= AGREE_TO_LOCK;
    lastResult = parsed;
    if (locked && !wasLocked) buzz(OfferParser.rate(parsed, settings).state === 'go' ? [18, 40, 18] : [45]);
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
        status('read failed: ' + e.message);
      }
      busy = false;
      await sleep(30);
    }
  }

  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* ---------- render ---------- */

  function money(n, d) { return n === null || !isFinite(n) ? '--' : '$' + n.toFixed(d); }

  function render(ms) {
    var p = lastResult;
    var r = p ? OfferParser.rate(p, settings) : { ready: false, state: 'empty' };

    el.verdict.className = 'verdict ' + r.state;
    document.body.classList.toggle('locked', locked);

    el.verdictLabel.textContent = !r.ready
      ? 'POINT AT THE OFFER'
      : ({ go: 'ACCEPT', warn: 'CLOSE CALL', no: 'PASS' }[r.state] + (locked ? '' : ' ?'));

    el.perHour.textContent = r.ready
      ? '$' + (Math.abs(r.perHour) >= 100 ? Math.round(r.perHour) : r.perHour.toFixed(1))
      : '--';

    el.vPay.textContent = p && p.pay !== null ? money(p.pay, 2) : '--';
    el.vMin.textContent = r.ready ? Math.round(r.minutes) : (p && p.minutes ? p.minutes : '--');
    el.vMile.textContent = p && p.miles !== null ? p.miles.toFixed(1) : '--';

    // A read can warrant more than one note at once — a recovered decimal and
    // added shopping time are independent facts and both change the number.
    var notes = [];
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
    var img = new Image();
    img.onload = async function () {
      frozen = true;
      document.body.classList.add('frozen');
      el.btnFreeze.textContent = '▶ Scan';
      status('reading photo…');
      // A still has no successive frames to agree with, so trust one good read.
      var out = await readOnce(img, null);
      lastResult = out.parsed;
      locked = out.parsed.complete;
      render(out.ms);
      URL.revokeObjectURL(img.src);
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
    save();
    if (worker) applyPsm();
  });

  /* ---------- boot ---------- */

  (async function () {
    el.reticle.classList.toggle('full', settings.fullFrame);
    try {
      await startEngine();
    } catch (e) {
      status('reader failed to load: ' + e.message);
      return;
    }
    try {
      await startCamera();
      running = true;
      loop();
    } catch (e) {
      // No camera is not a dead end — the photo button runs the same pipeline.
      status('no camera (' + e.name + ') — use 📷 Photo, or ⌨ Type');
    }
  })();

  // Exposed so the test harness can drive the same pipeline headlessly.
  window.__scan = {
    readImage: async function (src) {
      var img = new Image();
      await new Promise(function (r, j) { img.onload = r; img.onerror = j; img.src = src; });
      var out = await readOnce(img, null);
      lastResult = out.parsed;
      locked = out.parsed.complete;
      render(out.ms);
      return { parsed: out.parsed, ms: out.ms, rate: OfferParser.rate(out.parsed, settings) };
    },
    ready: function () { return !!worker; }
  };
})();
