'use strict';

const assert = require('assert');
const PT = require('../phone-touch-client.js');

assert.strictEqual(PT.clamp01(-1), 0);
assert.strictEqual(PT.clamp01(.4), .4);
assert.strictEqual(PT.clamp01(2), 1);

function fakeImage(rect, naturalWidth, naturalHeight) {
  return {
    naturalWidth, naturalHeight,
    getBoundingClientRect: () => rect,
    addEventListener() {}, removeEventListener() {},
    classList: { toggle() {} }, style: {}
  };
}

// 100x200 phone image contained in a 200x200 element => 50px letterbox each side.
const image = fakeImage({ left: 10, top: 20, width: 200, height: 200 }, 100, 200);
let p = PT.pointInImage({ clientX: 110, clientY: 120 }, image);
assert(Math.abs(p.x - .5) < 1e-9);
assert(Math.abs(p.y - .5) < 1e-9);
assert.strictEqual(PT.pointInImage({ clientX: 20, clientY: 120 }, image), null);

// Disarming an active gesture must emit cancel so a future HID transport can
// never inherit a held button from a mode switch or lost connection.
let listeners = {};
let emitted = [];
const interactive = {
  naturalWidth: 100, naturalHeight: 200,
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 100, height: 200 }),
  addEventListener: (name, fn) => { listeners[name] = fn; },
  removeEventListener() {}, setPointerCapture() {},
  classList: { toggle() {} }, style: {}
};
const cap = new PT.Capture(interactive, e => emitted.push(e));
cap.setArmed(true);
listeners.pointerdown({ pointerId: 7, pointerType: 'touch', clientX: 50, clientY: 100,
                        timeStamp: 1000, preventDefault() {} });
assert.strictEqual(emitted[0].kind, 'down');
assert.strictEqual(emitted[0].x, .5);
assert.strictEqual(emitted[0].y, .5);
cap.disarm();
assert.strictEqual(emitted[1].kind, 'cancel');
assert.strictEqual(cap.armed, false);

console.log('phone-touch-client tests passed');
