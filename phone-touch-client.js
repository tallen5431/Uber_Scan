'use strict';

/* Manual-input capture for the phone-touch experiment.
 *
 * This module does not know about OCR, offers, verdicts, or Android.  Its only
 * input is a real PointerEvent delivered over the visible phone image.  The
 * caller chooses what to do with the emitted diagnostic events.  Keeping the
 * capture layer separate from transport is deliberate: a future HID sender can
 * consume these events, while scanner/advice code has no path into this module.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PhoneTouch = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function clamp01(n) { return Math.max(0, Math.min(1, n)); }

  function pointInImage(event, image) {
    var r = image.getBoundingClientRect();
    if (!r.width || !r.height) return null;

    /* The phone image uses object-fit: contain. naturalWidth/naturalHeight let
     * us remove the letterbox before normalizing, so (0,0) means the actual
     * phone picture rather than the edge of an empty strip around it. */
    var iw = image.naturalWidth || r.width;
    var ih = image.naturalHeight || r.height;
    var scale = Math.min(r.width / iw, r.height / ih);
    var shownW = iw * scale;
    var shownH = ih * scale;
    var left = r.left + (r.width - shownW) / 2;
    var top = r.top + (r.height - shownH) / 2;
    var x = event.clientX - left;
    var y = event.clientY - top;
    if (x < 0 || y < 0 || x > shownW || y > shownH) return null;
    return { x: clamp01(x / shownW), y: clamp01(y / shownH) };
  }

  function Capture(image, emit) {
    if (!image || typeof image.addEventListener !== 'function') {
      throw new TypeError('phone image element is required');
    }
    this.image = image;
    this.emit = typeof emit === 'function' ? emit : function () {};
    this.armed = false;
    this.pointer = null;
    this.listeners = [];
    this._bind();
  }

  Capture.prototype._on = function (name, fn) {
    this.image.addEventListener(name, fn);
    this.listeners.push([name, fn]);
  };

  Capture.prototype._bind = function () {
    var self = this;
    function send(kind, e) {
      if (!self.armed) return;
      var p = pointInImage(e, self.image);
      if (!p) return;
      self.emit({ kind: kind, x: p.x, y: p.y,
                  pointerId: e.pointerId, pointerType: e.pointerType || 'unknown',
                  when: typeof e.timeStamp === 'number' ? e.timeStamp / 1000 : 0 });
    }
    this._on('pointerdown', function (e) {
      if (!self.armed || self.pointer !== null) return;
      if (!pointInImage(e, self.image)) return;
      self.pointer = e.pointerId;
      if (self.image.setPointerCapture) self.image.setPointerCapture(e.pointerId);
      e.preventDefault();
      send('down', e);
    });
    this._on('pointermove', function (e) {
      if (!self.armed || self.pointer !== e.pointerId) return;
      e.preventDefault();
      send('move', e);
    });
    function finish(kind, e) {
      if (self.pointer !== e.pointerId) return;
      if (self.armed) { e.preventDefault(); send(kind, e); }
      self.pointer = null;
    }
    this._on('pointerup', function (e) { finish('up', e); });
    this._on('pointercancel', function (e) { finish('cancel', e); });
    this._on('lostpointercapture', function () {
      if (self.pointer !== null) {
        self.emit({ kind: 'cancel', pointerId: self.pointer });
        self.pointer = null;
      }
    });
  };

  Capture.prototype.setArmed = function (on) {
    on = !!on;
    if (this.armed && !on && this.pointer !== null) {
      this.emit({ kind: 'cancel', pointerId: this.pointer });
      this.pointer = null;
    }
    this.armed = on;
    this.image.classList.toggle('phone-control-armed', on);
    this.image.style.touchAction = on ? 'none' : '';
    return this.armed;
  };

  Capture.prototype.disarm = function () { return this.setArmed(false); };

  Capture.prototype.destroy = function () {
    this.disarm();
    for (var i = 0; i < this.listeners.length; i++) {
      this.image.removeEventListener(this.listeners[i][0], this.listeners[i][1]);
    }
    this.listeners = [];
  };

  return { clamp01: clamp01, pointInImage: pointInImage, Capture: Capture };
}));
