/* Putting the rig's places on a map — the part with no map in it.
 *
 * WHY THIS FILE EXISTS AT ALL
 * `map.html` grew a geocoder, a rate limit, a cache, a box drawn around where
 * the car was, and a test for a pin that cannot be in this shift. All of it
 * was inside one <script> in one page, which was fine while one page wanted
 * it. The offers page now wants the same map beside the log — the driver's
 * own words, "it would be convenient if it could do it in the existing
 * program page" — and copying two hundred lines into a second page is how the
 * same question comes to have two answers that drift apart. So the deciding
 * moved here and the drawing stayed there.
 *
 * The split is by what touches the DOM, not by what feels like a module.
 * Everything here can be run in node with no browser: the geometry, the
 * pacing, the cache, the judging. That is not tidiness — it is what lets
 * rpi/test_mapview.py check the rate limit against a fake clock in
 * milliseconds, where the browser suite has to wait out real seconds and so
 * can only afford to check it once.
 *
 * WHAT THIS FILE IS NOT ALLOWED TO DO
 * advice.js argues at length that this rig must not geocode, and it is right
 * about the thing it is arguing against: a coordinate the rig invented from a
 * misread street, turned into a distance, turned into a number on the panel,
 * is the exact failure this project refuses — confidently wrong, and silent.
 *
 * Nothing computed here reaches the panel. No rate, no verdict, no billed
 * distance is derived from a lookup; `crowMiles` exists to CONTRADICT the
 * card, never to replace what it said. The one number this file produces that
 * a person acts on is "this pin is 600 miles from the others", which is an
 * accusation against the lookup rather than a claim about the job.
 *
 * That asymmetry is the whole safety argument, and it is checked: see
 * `judge()`, where a straight line longer than the card's own stated distance
 * marks the PIN as wrong and never the card.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MapView = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* --- geometry ----------------------------------------------------------- */

  /* The middle, not the mean, everywhere in this file.
   *
   * Every use of it here is a set that is expected to contain an outlier — a
   * GPS fix that was wrong, a geocode four states away — and the mean is
   * dragged by precisely the thing being looked for. A mean would move the
   * box towards the bad fix and move the centre towards the bad pin, so the
   * two tests that exist to catch outliers would be softened by them. */
  function median(values) {
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    if (!sorted.length) return null;
    var mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  }

  function middleOf(points) {
    if (!points || !points.length) return null;
    return { lat: median(points.map(function (p) { return p.lat; })),
             lon: median(points.map(function (p) { return p.lon; })) };
  }

  /* Straight-line miles, which is the only distance this file can compute. It
     is never the driving distance, and that asymmetry is exactly what makes it
     useful as a check: a straight line between two points CANNOT be longer
     than the road between them. Where it is, one of the two pins is wrong. */
  function crowMiles(a, b) {
    var R = 3958.8, toRad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * toRad, dLon = (b.lon - a.lon) * toRad;
    var la = a.lat * toRad, lb = b.lat * toRad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
          + Math.sin(dLon / 2) * Math.sin(dLon / 2) * Math.cos(la) * Math.cos(lb);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  /* How far out of the way a stop is — the driver's own question about a
     second offer, in the one form this file is allowed to answer it.
     Their words: "it would be helpful to see how they may chain together and
     if it makes sense to pickup the second offer since it would be mostly
     along the route I am going anyways."

     Going from `from` to `to` by way of `via`, less going straight there. Zero
     means the stop is on the line already; a big number means it is behind
     you.

     READ THE HEADER OF THIS FILE BEFORE USING THIS. It is a number derived
     from three geocoded points, which is the exact kind of number that must
     never reach the panel's verdict, rate or distance. It may be shown beside
     the pins it was computed from, on a map the driver chose to open, where
     they can see for themselves whether the three pins are in sensible places.
     It may not be shown anywhere it would be read as a fact about the job.

     Null when any of the three is missing, because a detour computed off two
     points is not a smaller detour — it is no answer with a number attached,
     and this one would come out as zero, which reads as "right on your way". */
  function detour(from, via, to) {
    if (!from || !via || !to) return null;
    return crowMiles(from, via) + crowMiles(via, to) - crowMiles(from, to);
  }

  /* Where the car was when a card came up, off the row itself.
   *
   * `isFinite` and not merely `typeof`, because a row whose lat came back as
   * NaN would otherwise be counted as a fix and then poison every median it
   * lands in — one NaN in a sort is enough to make the middle meaningless. */
  function fixOf(o) {
    return (o && typeof o.lat === 'number' && typeof o.lon === 'number'
            && isFinite(o.lat) && isFinite(o.lon)) ? { lat: o.lat, lon: o.lon }
                                                   : null;
  }

  /* --- where the car was, which is the whole of the improvement ------------
   *
   * The driver's own words: "usually the pickup/restaurant is the closest one
   * to me". That is exactly the question a geocoder cannot answer and a
   * coordinate can. Handed "Chipotle" it returns a Chipotle, and handed a
   * misread street it returns a real street somewhere — both with the same
   * confidence, and a hint typed once for a whole week is no help at all to a
   * driver who works more than one side of a metro.
   *
   * Since rpi/gps.py, a row carries the position the car was at when the card
   * came up. So each place can be searched inside a box around where the driver
   * actually was at that moment.
   *
   * Places named only by rows with no position — everything recorded before
   * the rig had a GPS, and every row whose fix had gone stale — get no anchor.
   * The middle of the whole range was tried as a fallback and is deliberately
   * not used: on a journal where only the last week carries positions, it
   * would box a place from eight months and two cities ago to last week's
   * metro and refuse it. A place whose own rows are silent about where they
   * were is a place this page knows nothing new about, and it is asked exactly
   * the way it was asked before any of this existed. */
  function anchorFor(offers, place) {
    var seen = [];
    (offers || []).forEach(function (o) {
      if (o.pickup !== place && o.dropoff !== place) return;
      var at = fixOf(o);
      if (at) seen.push(at);
    });
    return seen.length ? middleOf(seen) : null;
  }

  /* How wide to draw that box.
   *
   * Generous on purpose. The pickup is minutes away and the dropoff can be
   * forty miles, so a box tight enough to be clever would refuse the long
   * deliveries — and the thing being excluded here is not "a bit further than
   * usual", it is another state. Sixty miles is comfortably outside any real
   * job and comfortably inside the nearest place with the same street name.
   *
   * A degree of latitude is about 69 miles everywhere; a degree of longitude is
   * that times the cosine of the latitude, which at 34°N is about 57. Getting
   * that factor wrong would draw a box a fifth too narrow in the direction this
   * driver's metro is widest. */
  var BOX_MILES = 60;

  /* ...and snapped to a grid before it is drawn, which is what makes a place
   * you go back to stay looked up.
   *
   * The box is part of the cache key — it has to be, since the same place
   * asked inside a box and asked wide are two different questions. But the
   * anchor is the MEDIAN of the fixes on whichever rows are loaded, so one
   * more card from the same shop moves it a few hundred feet, and the journal
   * page's 7-day button against the map page's 30 moves it further. Every one
   * of those writes a new key for a place already answered. Measured on three
   * rows of one shop, taking the newest 3, 2 and 1: three keys, three asks.
   *
   * The places this costs are exactly the ones worth caching — the shops you
   * are sent back to. At one question a second, a page of them is a minute of
   * a driver watching an empty map fill in.
   *
   * A quarter degree is about 17 miles, so an anchor moving within one cell
   * asks the same question. The box is then padded by half a step in each
   * direction so the snapped box still CONTAINS every point the true box
   * would have: the answer stays a superset of the one that was wanted, never
   * a narrower search that quietly misses a long delivery.
   *
   * That is also why the cosine is taken at the cell edge furthest from the
   * equator rather than at the snapped centre. Cosine shrinks away from the
   * equator, so the widest the true box could have been anywhere in this cell
   * is at its outer edge; taking it at the centre would let a box near the top
   * of a cell come out narrower than the one it stands in for, and the
   * superset claim above would be false in exactly the direction that loses
   * places.
   *
   * Changing how the key is built strands what is already stored under the old
   * one, so the first map drawn after this lands asks its places again and is
   * slow once. The cache is not versioned out from under it: the answers taken
   * WITHOUT a box are keyed on the place alone, they are still right, and
   * throwing them away to tidy up would make that first map slower than it
   * needs to be. The stranded boxed entries are a few KB that nothing reads. */
  var ANCHOR_STEP = 0.25;

  function boxAround(at, miles) {
    if (!at) return null;
    var wide = miles || BOX_MILES;
    var half = ANCHOR_STEP / 2;
    var lat = Math.round(at.lat / ANCHOR_STEP) * ANCHOR_STEP;
    var lon = Math.round(at.lon / ANCHOR_STEP) * ANCHOR_STEP;
    var edge = Math.abs(lat) + half;
    var dLat = wide / 69.0 + half;
    var dLon = wide / (69.0 * Math.max(0.2, Math.cos(edge * Math.PI / 180)))
             + half;
    // Nominatim wants <left>,<top>,<right>,<bottom> — longitude first.
    return [(lon - dLon).toFixed(4), (lat + dLat).toFixed(4),
            (lon + dLon).toFixed(4), (lat - dLat).toFixed(4)].join(',');
  }

  /* --- pins that cannot be in the same shift as the rest ------------------
   *
   * A geocoder handed a misread street answers anyway, and the answer is a
   * real place somewhere: "Daffodll Ln" becomes a Daffodil Lane four states
   * away, with the same confidence as the right one. Two things go wrong
   * then, and the second is the worse one.
   *
   * It puts a pin in the wrong place — which is what the map is FOR, since a
   * person spots that instantly where the rig never could.
   *
   * And it silently ruins the view for everything else. Fitting the view over
   * a set containing one point eight hundred miles out is a map of the country
   * with the shift as a single dot, so the one bad lookup hides the ninety
   * good ones the driver came to check.
   *
   * A shift happens in one metro. Distance from the MEDIAN of the pins, and
   * the threshold is deliberately generous: a long ride is forty miles and
   * this refuses nothing under seventy-five, so what it catches is another
   * state rather than a longer trip than usual. */
  var FAR_MILES = 75;

  function straysAmong(found, miles) {
    var far = miles || FAR_MILES;
    var names = Object.keys(found || {});
    var points = [];
    names.forEach(function (q) { if (found[q]) points.push(found[q]); });
    var middle = middleOf(points);
    var strays = {};
    if (!middle) return strays;
    names.forEach(function (q) {
      if (!found[q]) return;
      var out = crowMiles(middle, found[q]);
      if (out > far) strays[q] = out;
    });
    return strays;
  }

  /* Every place the loaded offers name, once each, in the order first seen. */
  function placesIn(offers) {
    var wanted = [];
    (offers || []).forEach(function (o) {
      if (o.pickup) wanted.push(o.pickup);
      if (o.dropoff) wanted.push(o.dropoff);
    });
    return wanted.filter(function (v, i, all) { return all.indexOf(v) === i; });
  }

  function jobsIn(offers) {
    return (offers || []).filter(function (o) { return o.pickup || o.dropoff; });
  }

  /* What each job looks like once both its ends have been looked up.
   *
   * The `impossible` test is the one place in this project where a geocoded
   * number is compared with a number off the card, and the direction of the
   * conclusion is the whole of why it is allowed. The card's distance covers
   * getting to the pickup as well as the job, so the straight line between the
   * two ends must be comfortably under it. Where it is over, the PIN is
   * wrong — never the card, never the rate, never the verdict the driver saw.
   * A version of this that trusted the pins would be the rig quietly
   * overruling what the screen actually said, which is the failure this
   * project exists to refuse. */
  function judge(jobs, found, strays) {
    strays = strays || {};
    return (jobs || []).map(function (o) {
      // `|| null` on both, because a place that was never asked about is
      // absent from `found` and comes back undefined, while a place that was
      // asked and not found is stored as null. Those are the same fact to
      // everyone downstream — this end has no pin — and letting one of them
      // be undefined means every caller has to know which is which. The
      // sidebar's "could not find" list was built by testing `!p.from`, which
      // happened to cover both; anything asking `=== null` would not have.
      var a = (o.pickup ? found[o.pickup] : null) || null;
      var b = (o.dropoff ? found[o.dropoff] : null) || null;
      var crow = (a && b) ? crowMiles(a, b) : null;
      var stated = typeof o.miles === 'number' ? o.miles : null;
      return { offer: o, from: a, to: b, crow: crow, stated: stated,
               impossible: (crow !== null && stated !== null
                            && crow > stated + 0.5),
               // How far out of the shift each end landed, when it did. Kept
               // per end rather than as one flag, because which of the two is
               // in another state is the whole of what the driver needs to
               // know to judge it.
               fromStray: o.pickup ? (strays[o.pickup] || null) : null,
               toStray: o.dropoff ? (strays[o.dropoff] || null) : null };
    });
  }

  /* --- one pin per place, not one per offer --------------------------------
   *
   * Every job at the same shop geocodes to the same coordinate, so the map was
   * stacking a marker per offer on the same pixel. On this driver's real
   * traffic that is a handful of merchants and a hundred offers: the map read
   * as a dozen jobs, the popups were unreachable under each other, and how
   * often a place actually came up — which is most of what makes a map of a
   * shift worth looking at — was invisible.
   *
   * Keyed on the place as the CARD wrote it rather than on the coordinate. Two
   * spellings the geocoder happened to resolve to the same point are two things
   * the rig read, and this exists to check what the rig read. */
  function byPlace(placed) {
    var seen = {}, order = [];
    function note(name, point, role, p) {
      if (!name || !point) return;
      if (!seen[name]) {
        seen[name] = { name: name, point: point, roles: {}, jobs: [] };
        order.push(name);
      }
      seen[name].roles[role] = true;
      seen[name].jobs.push(p);
    }
    (placed || []).forEach(function (p) {
      note(p.offer.pickup, p.from, 'pickup', p);
      note(p.offer.dropoff, p.to, 'dropoff', p);
    });
    return order.map(function (k) { return seen[k]; });
  }

  /* --- the shift in the order it happened ----------------------------------
   *
   * Every job already draws its own pickup-to-dropoff line. What nothing drew
   * is the part BETWEEN two jobs: the run from where one ended to where the
   * next began, which no card pays for and no card mentions. That run is the
   * whole of what makes a stack good or bad — two offers can each look fine
   * and still be forty minutes apart in opposite directions — and on a map of
   * unconnected pairs it is invisible.
   *
   * ONLY JOBS THE DRIVER TICKED. A journal is mostly offers that were turned
   * down; joining those in time order would draw a route through places the
   * car never went, which is a picture that looks like evidence and is
   * fiction. So `accepted` is the gate, and a range with nothing ticked gets
   * no chain at all — which the page has to say out loud rather than show as
   * an empty map.
   *
   * A job whose pins are both missing, or both in another state, does not
   * break the chain: it is stepped over and the hop it fell inside carries the
   * count, so the popup can say a job is unaccounted for between these two.
   * Drawing over a gap without saying it is a gap would be the same lie one
   * level down.
   *
   * The times here are when each CARD CAME UP, which is the only clock the rig
   * has. It is not when the job was delivered and must never be worded as
   * though it were. What it does answer exactly is whether the next offer
   * arrived while the last one was still running — `stacked` — and that is the
   * difference between an empty run and a second pickup on the way. */
  function chain(placed) {
    var steps = [];
    (placed || []).forEach(function (p) {
      if (!p.offer.accepted) return;
      if (typeof p.offer.at !== 'number' || !isFinite(p.offer.at)) return;
      // A stray is a bad lookup, not a place. Using one as a chain end would
      // draw the whole evening's route out to it and back, and the deadhead
      // miles quoted in the popup would be off by the width of a state.
      var from = (p.from && !p.fromStray) ? p.from : null;
      var to = (p.to && !p.toStray) ? p.to : null;
      steps.push({
        p: p, at: p.offer.at,
        // Where the chain arrives, and where it leaves. For a job with only
        // one usable end these are the same point, and that is right: the job
        // is one dot on the route rather than a segment of it.
        into: from || to, intoName: from ? p.offer.pickup : p.offer.dropoff,
        outOf: to || from, outName: to ? p.offer.dropoff : p.offer.pickup
      });
    });
    steps.sort(function (a, b) { return a.at - b.at; });

    var hops = [], last = null, missed = 0;
    steps.forEach(function (s) {
      if (!s.into) { missed++; return; }
      if (last) {
        var stated = typeof last.p.offer.minutes === 'number' ? last.p.offer.minutes : null;
        var apart = s.at - last.at;
        hops.push({
          from: last.outOf, to: s.into,
          fromName: last.outName, toName: s.intoName,
          a: last.p, b: s.p,
          miles: crowMiles(last.outOf, s.into),
          ms: apart,
          skipped: missed,
          // Three answers, not two. A card that never stated a duration cannot
          // say whether the next offer interrupted it, and `false` there would
          // read on the map exactly like "we checked, and it did not" — which
          // is the rig claiming to know something it does not. Null is the
          // third answer, and the popup says nothing rather than either.
          stacked: stated === null ? null : apart < stated * 60000
        });
      }
      missed = 0;
      last = s;
    });

    return {
      hops: hops,
      taken: steps.length,
      // Counted over the whole list rather than off `missed`, which resets at
      // every hop and so loses any unplaceable job that came last.
      unplaced: steps.filter(function (s) { return !s.into; }).length
    };
  }

  /* --- the geocoder --------------------------------------------------------
   *
   * Nominatim, which is free, keyless and asks for at most one request a
   * second. That rate is kept deliberately rather than hopefully: a page that
   * hammers it gets the whole project blocked, and there is no hurry here.
   *
   * Answers are cached under the exact string searched, so the second run of a
   * week costs nothing and the driver can re-check a map without asking
   * anybody anything.
   *
   * Everything it needs from the outside is passed in — the clock, the sleep,
   * the fetch, the store. Not for purity: it is what lets the rate limit be
   * checked against a fake clock in a millisecond, and what lets two pages
   * share ONE limiter rather than each keeping its own and between them
   * sending two questions a second under a rule of one. */
  var GAP_MS = 1100;

  function Geocoder(opts) {
    opts = opts || {};
    this.hint = opts.hint || function () { return ''; };
    this.gap = typeof opts.gap === 'number' ? opts.gap : GAP_MS;
    this.now = opts.now || function () { return Date.now(); };
    this.sleep = opts.sleep || function (ms) {
      return new Promise(function (r) { setTimeout(r, ms); });
    };
    this.fetch = opts.fetch || function (url, init) {
      return fetch(url, init);
    };
    this.store = opts.store || null;   // { get(), set(obj) } — localStorage, or nothing
    this.cache = {};
    if (this.store) {
      try { this.cache = JSON.parse(this.store.get() || '{}') || {}; }
      catch (e) { this.cache = {}; }
    }
    // When the last question actually went out, so the rate limit is a
    // property of the GEOCODER rather than of one loop. It was a sleep at the
    // bottom of an asking loop, which is correct for one loop and wrong the
    // moment there are two: the places a box refuses are asked again in a
    // second walk, and the gap between the last question of the first and the
    // first question of the second was nobody's business. Measured against
    // the map suite's stub: 4ms, under a rule of one a second.
    this.lastAsk = 0;
  }

  /* The string actually searched for, in ONE place.
   *
   * It used to be built by hand in three — inside the lookup, in the estimate
   * of how many were left to do, and in the rate limit — and the third copy
   * was consulted at the wrong moment, which is how the rate limit came to
   * apply to nothing at all. A lookup writes its answer into the cache before
   * it returns, so a check made AFTER it always finds the key present and
   * always skipped the wait: six questions went out in 33ms under a rule of
   * one a second. */
  /* The question actually sent, and therefore half the cache key.
   *
   * The hint — the map page's "near" box — applies ONLY to a place with no
   * box around it. That is the case it exists for: a row whose car position
   * was never recorded gets no sixty-mile box, so nothing stops the geocoder
   * answering with a same-named street in another state, and typing "Georgia"
   * is how the driver says which one they meant.
   *
   * Applied to every lookup, as it was, it silently forked the cache. The
   * offers page passes no hint and this page passes whatever is in the box, so
   * one word typed here made every key on this page different from the same
   * place asked there — and both pages share one store. The lookups stopped
   * being shared, and the one-a-second rate limit got paid twice for places
   * already found.
   *
   * A boxed place does not need the hint: the box already says where to look,
   * and it says it more precisely than a town name. */
  Geocoder.prototype.queryFor = function (place, box) {
    if (box) return place;
    var hint = (this.hint() || '').trim();
    return hint ? place + ', ' + hint : place;
  };

  /* The cache key. It has to carry the box: the same place asked inside a box
     and asked without one are two different questions with two different right
     answers, and storing the second under the first's key is how a good answer
     gets overwritten by a worse one. */
  Geocoder.prototype.keyFor = function (place, box) {
    return this.queryFor(place, box) + (box ? ' @' + box : '');
  };

  Geocoder.prototype.knows = function (place, box) {
    return Object.prototype.hasOwnProperty.call(this.cache,
                                                this.keyFor(place, box));
  };

  /* Kept, and merged into what is on the device NOW rather than over it.
   *
   * The cache is read once, in the constructor, and this used to write the
   * whole in-memory copy back on every answer. One page open, that is the same
   * thing. Two pages open — the map and the offers page, which is an ordinary
   * way to use this, and a PWA keeps them both alive — and it is not: each
   * holds a snapshot from the moment it loaded, and whichever answers last
   * writes its own over everything the other learned in between.
   *
   * What that costs is not a wrong answer, it is work. The addresses are gone,
   * nothing says so, and the next press pays the one-a-second rate limit again
   * for places that had already been found — which is precisely the cost the
   * anchor snapping above exists to remove.
   *
   * Re-read, merge, write. Everything the other page learned survives, and the
   * merged result is kept in memory too, so this page GETS the other's work
   * rather than only preserving it.
   *
   * Which side wins a key both hold is deliberately not a rule, because the
   * two cannot disagree: `lookup` answers from the cache without asking when
   * it already knows a key, so a page never produces a second answer for one.
   * A different box or a typed hint makes a different key, not a conflict. The
   * property that matters, and the one the check holds this to, is that no key
   * is lost — which both directions satisfy. A mutation swapping them survives
   * the suite, and that is honest rather than a gap: there is no input that
   * tells them apart.
   *
   * Not a lock, and it does not need to be: two writes racing still each
   * re-read first, so the loser has already merged the winner's entries or
   * will on its next answer. The failure this removes is systematic — one page
   * reliably clobbering the other — not a rare interleaving. */
  Geocoder.prototype.remember = function (key, value) {
    this.cache[key] = value;
    if (!this.store) return;
    try {
      var onDevice = {};
      try { onDevice = JSON.parse(this.store.get() || '{}') || {}; }
      catch (e) { onDevice = {}; }
      var mine = this.cache;
      Object.keys(mine).forEach(function (k) { onDevice[k] = mine[k]; });
      this.cache = onDevice;
      this.store.set(JSON.stringify(onDevice));
    } catch (e) { /* full, or private mode */ }
  };

  Geocoder.prototype.forget = function () {
    this.cache = {};
    if (!this.store) return;
    try { this.store.clear(); } catch (e) { /* private mode */ }
  };

  /* Waiting BEFORE the request rather than after it drops the "except the last
     one" special case — there is no trailing wait to skip, because nothing
     waits except immediately before talking. */
  Geocoder.prototype.paced = function (fn) {
    var self = this;
    var due = this.lastAsk + this.gap - this.now();
    var wait = due > 0 ? this.sleep(due) : Promise.resolve();
    return wait.then(function () {
      self.lastAsk = self.now();
      return fn();
    });
  };

  /* "Nobody there" and "nobody answered" are different answers.
   *
   * This used to turn both into null, and `lookup` below then remembered that
   * null for ever — in localStorage, so across runs, across days, and on the
   * machine at home too. A hotspot that drops for four seconds part way
   * through a paced walk is the ordinary case in a car, and every place asked
   * inside that gap became a permanent "the geocoder could not find this":
   * never asked again, listed on the map page as a misread address, with the
   * only recovery being "Forget lookups", which throws away every good answer
   * as well.
   *
   * The rule is already written down forty lines below, for the Leaflet
   * loader: "A FAILED load is not kept. Being offline once is the ordinary
   * case here, and a page that remembered the failure would refuse to draw a
   * map for the rest of the session after one dead moment at a red light."
   * The geocoder did the opposite, and durably.
   *
   * So a transport failure THROWS and an empty answer returns null. Only the
   * second is a fact about the place. */
  Geocoder.prototype.ask = function (query, box) {
    var url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q='
            + encodeURIComponent(query)
            + (box ? '&viewbox=' + encodeURIComponent(box) + '&bounded=1' : '');
    return this.fetch(url, { headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        // A refusal is not an answer either. 429 and 403 are what Nominatim
        // sends a client it is throttling or has blocked, and caching those as
        // "no such place" would turn a bad minute into a permanent hole.
        if (!r.ok) throw new Error('geocoder said ' + (r.status || '?'));
        return r.json();
      })
      .then(function (hits) {
        var hit = hits && hits[0];
        return hit ? { lat: Number(hit.lat), lon: Number(hit.lon),
                       name: hit.display_name, kind: hit.type || '',
                       bounded: !!box } : null;
      });
  };

  Geocoder.prototype.lookup = function (place, box) {
    var self = this;
    var key = this.keyFor(place, box);
    if (Object.prototype.hasOwnProperty.call(this.cache, key)) {
      return Promise.resolve(this.cache[key]);
    }
    return this.paced(function () {
      return self.ask(self.queryFor(place, box), box);
    }).then(function (found) {
      // Only an answer that actually arrived is remembered. See ask().
      self.remember(key, found);
      return found;
    }, function () {
      // Could not ask. Not stored, so the next run asks again — and answered
      // as `undefined` rather than null, which is what lets a caller tell
      // "asked, nothing there" from "never got to ask". Everything that only
      // wants a pin treats both as falsy and is unaffected.
      return undefined;
    });
  };

  /* One paced walk over a list of places, in ONE place.
   *
   * The pacing used to be inline in the caller, and then a second, unpaced
   * request appeared for the places a box refused — which sent two questions
   * back to back under a rule of one a second. Measured against the map
   * suite's stub: 3ms apart. Being blocked by Nominatim would stop the map
   * working for everyone who pulls the repo, so there is exactly one loop that
   * talks to it and everything goes through this.
   *
   * `onward` is told what is done, what is left and how long that is likely to
   * take, so the page can say it without owning the arithmetic. */
  Geocoder.prototype.walk = async function (list, boxFor, into, onward) {
    var todo = list.filter(function (q) { return !this.knows(q, boxFor(q)); }, this);
    var left = todo.length, done = 0;
    for (var i = 0; i < list.length; i++) {
      var q = list[i];
      // Asked BEFORE the lookup. Afterwards the answer is already in the cache
      // and "did this use the network" can only be answered wrong.
      var wasKnown = this.knows(q, boxFor(q));
      var hit = await this.lookup(q, boxFor(q));          // eslint-disable-line no-await-in-loop
      into[q] = hit;
      done++;
      if (!wasKnown) left--;
      if (onward && (done % 3 === 0 || done === list.length)) {
        onward({ done: done, total: list.length, left: left,
                 seconds: Math.ceil(left * this.gap / 1000) });
      }
    }
    return into;
  };

  /* Every place in one range, looked up near where the car was, judged, and
   * handed back ready to draw. The whole run, with no DOM in it.
   *
   * `say` is handed each step's wording rather than the page polling for it,
   * because the estimates are arithmetic over the rate limit and the cache and
   * belong next to both. */
  async function placeAll(offers, geo, say, opts) {
    opts = opts || {};
    say = say || function () {};
    var jobs = jobsIn(offers);
    var distinct = placesIn(jobs);
    // The box each place will be searched inside, worked out once.
    var boxes = {};
    distinct.forEach(function (q) {
      boxes[q] = boxAround(anchorFor(offers, q), opts.boxMiles);
    });
    var anchored = distinct.filter(function (q) { return !!boxes[q]; }).length;
    var fresh = distinct.filter(function (q) { return !geo.knows(q, boxes[q]); });
    say(distinct.length + ' distinct places, ' + anchored + ' searched near '
        + 'where you were, ' + fresh.length + ' to look up'
        + (fresh.length ? ' (about ' + Math.ceil(fresh.length * geo.gap / 1000) + 's)'
                        : ' — all remembered'));

    var found = {};
    function progress(note) {
      return function (p) {
        say(note + ' ' + p.done + ' of ' + p.total
            + (p.left > 0 ? ' — about ' + p.seconds + 's left' : ''));
      };
    }

    await geo.walk(distinct, function (q) { return boxes[q]; }, found,
                   progress('looked up'));

    /* Places a box refused, asked again without one.
     *
     * A box is a claim that the answer is within sixty miles of where the car
     * was, and almost every empty answer means the address was misread badly
     * enough that nothing near the driver matches — which is worth knowing and
     * is what the "could not find" list is for. But it can also be a genuinely
     * distant one, and a pin LOST to a feature meant to gain pins is the wrong
     * trade. So they are asked wide, through the same paced walk, and what
     * comes back is judged by the stray test like everything else.
     *
     * Only the ones that had a box AND came back empty, so the cost is
     * proportional to the problem rather than to the size of the journal. */
    var refused = distinct.filter(function (q) { return boxes[q] && !found[q]; });
    if (refused.length) {
      say(refused.length + ' were not found near you — asking again without '
          + 'the box (about ' + Math.ceil(refused.length * geo.gap / 1000) + 's)');
      await geo.walk(refused, function () { return null; }, found,
                     progress('asked wide'));
    }

    var strays = straysAmong(found, opts.farMiles);
    var placed = judge(jobs, found, strays);

    // Out of the offers that named BOTH ends, which are the only ones that
    // could ever be drawn end to end. Counting against everything that named
    // anywhere would fold "the card never said where this went" into the same
    // figure as "the geocoder got it wrong", and those are different problems
    // with different answers.
    var couldDraw = jobs.filter(function (o) { return o.pickup && o.dropoff; }).length;
    var drawn = placed.filter(function (p) {
      return p.from && p.to && !p.impossible;
    }).length;
    return { placed: placed, strays: strays, found: found, distinct: distinct,
             couldDraw: couldDraw, drawn: drawn,
             done: drawn + ' of ' + couldDraw + ' drawn end to end' };
  }

  /* --- the library itself --------------------------------------------------
   *
   * Leaflet is fetched from a CDN, which the offers page must not do on load:
   * the rig runs off a phone hotspot in a car and that page has to open with
   * no network at all. So the map is not part of the page until somebody asks
   * for it, and asking for it twice does not fetch it twice — the promise is
   * kept, not the result of the last attempt, so a second caller during the
   * download joins the first rather than starting another.
   *
   * A FAILED load is not kept. Being offline once is the ordinary case here,
   * and a page that remembered the failure would refuse to draw a map for the
   * rest of the session after one dead moment at a red light. */
  var loading = null;

  function needLeaflet(doc, urls) {
    if (typeof doc.defaultView.L !== 'undefined') return Promise.resolve(true);
    if (loading) return loading;
    loading = new Promise(function (done) {
      var css = doc.createElement('link');
      css.rel = 'stylesheet';
      css.href = urls.css;
      doc.head.appendChild(css);
      var s = doc.createElement('script');
      s.src = urls.js;
      s.onload = function () { done(typeof doc.defaultView.L !== 'undefined'); };
      s.onerror = function () { loading = null; done(false); };
      doc.head.appendChild(s);
    }).then(function (got) {
      if (!got) loading = null;
      return got;
    });
    return loading;
  }

  return { median: median, middleOf: middleOf, crowMiles: crowMiles,
           detour: detour, fixOf: fixOf, anchorFor: anchorFor, boxAround: boxAround,
           straysAmong: straysAmong, placesIn: placesIn, jobsIn: jobsIn,
           judge: judge, byPlace: byPlace, chain: chain,
           Geocoder: Geocoder, placeAll: placeAll, needLeaflet: needLeaflet,
           BOX_MILES: BOX_MILES, ANCHOR_STEP: ANCHOR_STEP,
           FAR_MILES: FAR_MILES, GAP_MS: GAP_MS };
}));
