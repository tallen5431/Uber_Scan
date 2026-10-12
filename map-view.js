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
 * `judge()`, where a straight line longer than the reading's own stated
 * distance marks the PIN as wrong and never the card — and only where the
 * reading vouches for that distance. A reading the rig would not finish or
 * would not trust is no yardstick, so the pair is reported as unchecked
 * instead of accused; see the yardstick note at `judge()`.
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
   * lands in — one NaN in a sort is enough to make the middle meaningless.
   *
   * And only a fix the gate passed. Whether a position is good enough to show
   * or compare is asked ONCE, by rpi/gps.py's usable(), and its answer is on
   * the row as `gpsOk` — a mode-3 fix gpsd itself put at 129 m and a clear
   * sky's were otherwise the same two numbers here. Read, never worked out
   * again in this file: a second copy of the rule in JavaScript would be a
   * second answer the first time either moved. A row with no answer at all —
   * written before the gate existed, or by anything but the rig — is not a
   * position either; nobody judged it. Every box, accusation, trail dot and
   * the panel's detour anchor asks this function, so all of them refuse
   * together. fixRefused says which rows that was, so it is never silent. */
  function fixOf(o) {
    return (o && o.gpsOk === true && typeof o.lat === 'number'
            && typeof o.lon === 'number' && isFinite(o.lat) && isFinite(o.lon))
      ? { lat: o.lat, lon: o.lon } : null;
  }

  /* Why a row that carries a coordinate is not a position, or null.
   *
   * The gate's own word (`gpsWhy`: unrated, nomode, rough, frozen or stale) or
   * 'unjudged' for a coordinate nobody judged. Null for a row with no
   * coordinate at all, which is the ordinary "did not know" and not a refusal.
   * For the counts beside what fixOf lets through, so a refused fix is a
   * number on the page rather than a dot that quietly is not there. */
  function fixRefused(o) {
    if (!o || typeof o.lat !== 'number' || typeof o.lon !== 'number'
        || !isFinite(o.lat) || !isFinite(o.lon) || o.gpsOk === true) return null;
    return o.gpsWhy || 'unjudged';
  }

  /* --- you are here --------------------------------------------------------
   *
   * The heartbeat's newest fix, drawn as a dot with a circle the size of its
   * own error, on both maps. What this decides and the pages only draw: one
   * rule for the dot, the circle, the label and the refusal, rather than two
   * pages each with their own idea of when a dot is too old.
   *
   * `fix` is the beat's `gps.fix` — the journal's own fields (lat, lon,
   * gpsAge, gpsErr, gpsMode, gpsOk, gpsWhy) and `freshFor`, the seconds
   * rpi/gps.py said this fix had left inside its staleness rule when the beat
   * was sent. `sinceMs` is how long ago, on the page's own clock, the beat
   * carrying it arrived.
   *
   * Three answers:
   *   null                     no fix: nothing drawn, nothing said. A rig run
   *                            without --gps is the driver's choice, and the
   *                            connection row already says a GPS that stopped.
   *   { line }                 the gate refused it for its QUALITY: nothing
   *                            drawn, and the reason said — a dot that quietly
   *                            is not there reads as a car that is nowhere.
   *   { lat, lon, err, grey,   a dot, grey once it is older than the rule: the
   *     label }                gate said `stale`, or the beat stopped coming
   *                            and the time since it outran `freshFor`. Grey
   *                            rather than gone, because "where the car WAS"
   *                            is still worth seeing beside the words saying
   *                            how long ago that was.
   *
   * The age in the label is the fix's age when the beat left plus the time
   * since it arrived — two durations, never two machines' clocks subtracted —
   * so a beat that stopped coming does not leave "2 s old" on the glass. */
  /* One line for each word rpi/gps.py's usable() refuses with except
     `stale`, which is a grey dot rather than none. Short, because they sit in
     the map's corner on a 228px column on the 3.5" hat; rpi/test_layout.py
     measures every one there, and rpi/test_lint.py holds this table to the
     gate's own words. `frozen` is a receiver repeating one position while
     the car moves — the owner's VK-162 under gpsd's binary mode did it for a
     whole shift — and is no dot, because the dot would be where the car was
     minutes ago drawn as where it is. */
  var GPS_REFUSED = {
    unrated: 'GPS gives no accuracy here',
    nomode: 'GPS reports no 2D/3D fix',
    rough: 'GPS too rough here',
    frozen: 'GPS stuck on one spot'
  };

  function spellSeconds(s) {
    if (s < 60) return Math.round(s) + ' s';
    if (s < 3600) return Math.floor(s / 60) + ' min';
    return Math.floor(s / 3600) + ' h';
  }

  function hereDot(fix, sinceMs) {
    if (!fix || typeof fix.lat !== 'number' || typeof fix.lon !== 'number'
        || !isFinite(fix.lat) || !isFinite(fix.lon)) return null;
    var since = Math.max(0, Number(sinceMs) || 0) / 1000;
    if (fix.gpsOk !== true && fix.gpsWhy !== 'stale') {
      // `stale` is the one refusal that still has a position worth drawing:
      // usable() judges quality before age, so a stale fix was a good one.
      var why = GPS_REFUSED[fix.gpsWhy] || 'GPS fix not judged';
      return { line: fix.gpsWhy === 'rough' && typeof fix.gpsErr === 'number'
        ? why + ' (±' + Math.round(fix.gpsErr) + ' m)' : why };
    }
    // A fix the gate passed always has an error figure — usable() refuses one
    // without — so `err` is the circle's radius and the label's figure.
    var err = fix.gpsErr;
    var age = typeof fix.gpsAge === 'number' ? fix.gpsAge + since : null;
    // No `freshFor` is no time left: a fix that does not say how long it stays
    // inside the rule is grey from the moment it lands, never bright by default.
    var fresh = typeof fix.freshFor === 'number' ? fix.freshFor : 0;
    return {
      lat: fix.lat, lon: fix.lon, err: err,
      grey: fix.gpsOk !== true || since > fresh,
      label: '±' + Math.round(err) + ' m · '
        + (age === null ? 'age unknown' : spellSeconds(age) + ' old')
    };
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
  /* The town this window's cards keep naming, or null.
   *
   * What a place is asked WITH when nothing can box it. `anchorFor` above
   * answers null for every place on a journal whose rows carry no position —
   * which, measured on the owner's own week, is all 1,166 of them — and a place
   * with no box and no hint is asked of a world-wide geocoder as a bare string.
   * Handed "McDonald's" that way it returns a real McDonald's, confidently,
   * 4,801 miles away. 50.3% of this driver's distinct places have no comma in
   * them at all, so there is nothing in the string itself to locate them by.
   *
   * The cards already know the answer. Across that week the place names carry a
   * trailing town 517 times — Atlanta 119, Marietta 85, Kennesaw 68, Acworth
   * 40 — and every one of them is the same metro. So this is not a guess about
   * geography: it is reading back the town the rig already parsed off the
   * driver's own cards.
   *
   * Counted over DISTINCT place strings rather than over offers, so one
   * restaurant the driver is sent to forty times does not decide where the
   * whole window is searched.
   *
   * Requires a lowercase letter in the chunk, which is what keeps OCR wreckage
   * out: "ies, LAS" is one of the strings that actually produced a stray pin,
   * and "LAS" is not a town. */
  /* The town in one place name, or null — the rule above, on its own.
   *
   * Lifted out of localityOf rather than written a second time, because the
   * area ranking needs exactly this judgement and two copies of "what counts
   * as a town" would answer differently the first time either was touched.
   * Every word of the paragraph above applies here: the comma, the shape, and
   * the lowercase letter that keeps "ies, LAS" out.
   *
   * It is the card's own words and nothing else. No lookup, no coordinate, no
   * answer a geocoder gave — see the head of this file for why that line is
   * where it is. */
  function townOf(name, rule) {
    var v = (name == null ? '' : String(name)).trim();
    if (!v || typeof rule !== 'function') return null;
    var got = rule(v);
    var town = got && got.town;
    if (!town) return null;
    // The lowercase test, kept — and moved onto the SOURCE, because the rule
    // hands back a lowercased town and every answer would pass it otherwise.
    // It is what keeps "ies, LAS" out: an all-capitals tail is an abbreviation
    // or a fragment of a road name, not a place anybody lives. `rule` does not
    // make that distinction — it reads `LAS` as a town quite happily — so this
    // is the one piece of the old judgement that is still map-view's.
    var at = v.toLowerCase().lastIndexOf(town);
    if (at < 0) return null;
    var asWritten = v.slice(at, at + town.length);
    if (!/[a-z]/.test(asWritten)) return null;
    // Title case, because this is what the ranking prints and the rule
    // lowercases to compare. "Powder Springs", not "powder springs".
    return town.replace(/(^|[\s'-])([a-z])/g, function (_, before, c) {
      return before + c.toUpperCase();
    });
  }

  /* Whichever end of this job named a town. The dropoff first: it is a street
   * address on a card that prints one, where the pickup is usually a merchant
   * with no town in it at all. Measured on the owner's week, the dropoff
   * yields a town on 35% of counted offers and the pickup on 12%; taking
   * either reaches 41%, and the ranking is real on all three separately. */
  function townEndFor(offer, rule) {
    if (!offer) return null;
    if (townOf(offer.dropoff, rule)) return 'dropoff';
    if (townOf(offer.pickup, rule)) return 'pickup';
    return null;
  }

  /* ...and townFor is derived from it rather than restating the order.
   *
   * Written the other way round first — `townOf(dropoff) || townOf(pickup)`
   * here and a second function repeating that precedence — which is two
   * copies of one rule, and the first edit to either would have made the
   * ranking's rows disagree with the ranking. Which END a town came off is
   * not a footnote on this page: 86% of the placed rows come off the dropoff,
   * so a panel headed "where the money is" is mostly describing where jobs
   * END. */
  function townFor(offer, rule) {
    var end = townEndFor(offer, rule);
    return end ? townOf(offer[end], rule) : null;
  }

  function localityOf(offers, rule) {
    var seen = {}, tally = {};
    (offers || []).forEach(function (o) {
      ['pickup', 'dropoff'].forEach(function (k) {
        var v = (o && o[k] ? String(o[k]) : '').trim();
        if (!v || seen[v]) return;
        seen[v] = true;
        var tail = townOf(v, rule);
        if (!tail) return;
        tally[tail] = (tally[tail] || 0) + 1;
      });
    });
    var best = null;
    Object.keys(tally).forEach(function (t) {
      if (!best || tally[t] > tally[best]) best = t;
    });
    return best;
  }

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

  /* The same accusation, made against a point that was MEASURED.
   *
   * straysAmong takes the middle of the pins and asks which are far from it,
   * which works on a whole shift and cannot work on two or three places: with a
   * pickup and a dropoff the middle IS the midpoint, both ends come out equally
   * far, and it accuses whichever it likes. The panel's map has exactly that
   * many places, so it had no stray test at all — a misread street answered by
   * a real one two states away was drawn, framed, and then used as one end of
   * the "out of your way" figure.
   *
   * What the panel has that a whole-shift map does not is an anchor that is not
   * a guess: the GPS fix the scanner put on THIS card's offer line when the
   * card came up (cardFix, below). Distance from THAT is
   * a claim about one lookup rather than a vote among lookups, and it is the
   * same argument map.html already makes for drawing the trail — the measured
   * thing is the only one that can contradict a pin without being the same kind
   * of thing as the pin.
   *
   * No anchor, no accusation. A card that came up with no fix knows nothing
   * new about these places and must not start guessing on thinner evidence. */
  function farFrom(anchor, found, miles) {
    var far = miles || FAR_MILES;
    var out = {};
    if (!anchor) return out;
    Object.keys(found || {}).forEach(function (q) {
      if (!found[q]) return;
      var away = crowMiles(anchor, found[q]);
      if (away > far) out[q] = away;
    });
    return out;
  }

  /* --- the card's own disc -------------------------------------------------
   *
   * live.html's Map view states one figure, "+N mi out of your way", and it
   * was measured from the newest journal row that carried a position — up to
   * twenty minutes old, cached two minutes more — with nothing asking whether
   * the map had found the right branch. A same-brand pin 21.8 miles from the
   * car on a job whose whole trip was 9.4 printed "+31.3 mi out of your way":
   * farFrom's 75 miles cannot see a wrong McDonald's in the next town.
   *
   * The CARD can. Its distance counts the drive from the car to the pickup and
   * on to the end, and a straight line cannot beat the road, so a pin farther
   * from where the car was when the card came up than the card's own distance
   * plus SLACK_MI is a pin the map got wrong. The same argument judge() makes
   * about the two ends of one job, made from the car — so the same rule,
   * `vouches`, decides whether the figure is one the rig stands behind, and the
   * same slack. Nothing here becomes a rate, a verdict or a distance on the
   * panel: it decides only whether the one figure Map view states may be
   * stated, and says why when it may not.
   *
   * The fix is the CARD's: the one the scanner captured once when the card
   * landed and put on the offer line, which is also the point the platform
   * measured the card's distance from (give or take the seconds between). Only
   * one rpi/gps.py's gate passed, through fixOf. A fix the gate refused says
   * why, in words, rather than reading as no fix at all. */
  var SLACK_MI = 0.5;

  /* judge()'s yardstick rule, stated once for both of its users: a figure the
     reader finished (`whole`), did not doubt (`milesUncertain`) and did not
     set aside (`suspect`). See the long note at judge(). */
  function vouches(o) {
    return !!o && !o.milesUncertain && o.whole !== false && !o.suspect;
  }

  /* Where the car was when this card came up, or why there is nothing to
     measure from. `why` is null for a card that carried no coordinate at all
     (no --gps, no answer, or a fix gone stale before the card landed —
     Phone.fix() hands out none of those), else the gate's own word. */
  function cardFix(o) {
    // No card at all is not a card without a fix: a hold read back from a
    // holding.json written before the server kept the card has none, and
    // "came up without a GPS fix" said of it is a claim nobody measured.
    if (!o) return { at: null, why: 'nocard', err: null };
    var at = fixOf(o);
    if (at) return { at: at };
    return { at: null, why: fixRefused(o),
             err: (o && typeof o.gpsErr === 'number') ? o.gpsErr : null };
  }

  /* Whether this card's distance may be held against a pin measured from the
   * car, and if not, which of four reasons. The verifier's corrections to the
   * design study, each a clause:
   *
   *   none       the card stated no distance.
   *   untrusted  judge()'s rule refuses it, or rate() doubted one of its
   *              figures (`doubt`). The offer line carries no `suspect`;
   *              journal.py sets it whenever `doubt` is set, so `doubt` is the
   *              same refusal read off the line.
   *   early      "Early look - Order in progress": 27 of the week's 1,166
   *              cards. Offered inside a job, and nothing says whether the
   *              figure starts at the car or at that job's end — counted from
   *              the end, a right pin is refused.
   *   shape      neither a printed total (`hasTotal`) nor two legs the rig
   *              summed. 528 of the week's cards stop here, every one a
   *              card of one leg, as in "$7 Guaranteed · 7.8 mi + 24 min" —
   *              DoorDash, by AUDITS.md's own reading — and whether that
   *              figure counts the drive to the restaurant is not known until
   *              it is seen. "No yardstick yet", not a guess.
   *
   * The SUMMED figure, never `toPickupMiles`: the approach leg alone leaves
   * only the half mile to absorb the car moving between the platform's
   * measurement and the rig's fix, and that motion has not been measured.
   * Measured over the week's 1,166 cards in this order: 10 none, 17
   * untrusted, 27 early, 528 shape, and 584 yardsticks — 577 of them naming
   * a pickup, 267 of them carrying a decimal the rig put back. */
  function cardYardstick(o) {
    if (!o || typeof o.miles !== 'number' || !isFinite(o.miles) || o.miles <= 0) {
      return { why: 'none' };
    }
    if (!vouches(o) || o.doubt) return { why: 'untrusted' };
    if (o.earlyLook) return { why: 'early' };
    if (!(o.hasTotal || (o.legs || 0) >= 2)) return { why: 'shape' };
    return { miles: o.miles, corrected: !!o.milesCorrected };
  }

  /* A pin the card contradicts, or null. `yard` is cardYardstick's answer
     with a figure in it. */
  function outsideCard(fix, pin, yard) {
    var crow = crowMiles(fix, pin);
    return crow > yard.miles + SLACK_MI ? { crow: crow } : null;
  }

  /* Whether this card refuses this pin, as a fact rather than a sentence:
     null for a pin it allows AND for a card that is no yardstick (that is a
     figure withheld, not a pin refused). live.html asks this once per pin and
     uses the one answer twice — the pin's colour and the line under the map —
     so the map and its caption cannot keep two rules for "this pin is
     wrong". */
  function cardRefuses(o, fix, pin) {
    if (!fix || !pin) return null;
    var yard = cardYardstick(o);
    if (!yard.miles) return null;
    var out = outsideCard(fix, pin, yard);
    return out ? { crow: out.crow, miles: yard.miles,
                   corrected: yard.corrected } : null;
  }

  /* --- searching inside the disc, on the NucBox ----------------------------
   *
   * The disc above refuses a wrong pin AFTER a geocoder chose it. With the
   * NucBox's own Nominatim there is no rate limit to ration questions by, so
   * the choosing can happen inside the disc instead: ask for several
   * candidates in a box round the card's disc, keep the ones inside it, and
   * use one only when exactly one fits or every one that fits is the same
   * place. Measured on the real install (Georgia, 4.5): McDonald's in a box
   * round Marietta answered ten branches, every one inside the box with a
   * house number and a street. Handed limit=1, as the public path is, it
   * would have pinned whichever of the ten came first.
   *
   * WHAT IS ASKED, by the shape of the place string (searchPlan):
   *
   *   "Jimmy John's (1985 Cobb Parkway NW)"  a door in the bracket: the
   *        street= search for "1985 Cobb Parkway NW". The name is not asked:
   *        the address is the more exact of the two.
   *   "Shadowood Pkwy SE, Atlanta"            street= "Shadowood Pkwy SE";
   *   "4821 Kestrel Dr, Marietta"             the town is NOT sent, and NOT
   *        the Trip Planner's door line too.   used. Measured: q=Shadowood
   *                                            Pkwy SE, Atlanta, GA found 0
   *        and the street alone in the box found 2, in Cumberland. Uber's
   *        town is the postal town and OSM's is the place (Atlanta against
   *        Cumberland; Marietta against Kennesaw for 1985 Cobb Parkway). It
   *        was kept as a tie-break among candidates inside the disc, and that
   *        is the same mistake one step later. Probed: Shadowood Parkway in
   *        Cumberland and a namesake 1.35 mi off whose OSM address said
   *        Atlanta, both inside a 3.0 mi card's disc, and the card's
   *        "Atlanta" pinned the namesake — chosen by the one word the real
   *        install showed disagrees with OSM. Two that fit and disagree are
   *        a refusal, whatever the card's town says.
   *        A street with a house number is a door: it is pinned only where
   *        the answer HAS that number (see hasDoor) — Nominatim asked for
   *        a door it does not hold answers the street instead, at the same
   *        confidence, and that was pinned as the door.
   *   "A & B, Town"                           cross streets: a and b, asked of
   *        the NucBox's street index (NbxSearch.corner), never of Nominatim,
   *        which answers ONE point for a whole street (Cobb Parkway NW came
   *        back as one result), so the corner of two cannot be asked of it.
   *        With no street index set this says so rather than pinning one
   *        street; three names, or an empty one, are not a corner.
   *   "Street, Town" with no number, when the street index is set: its
   *        stretch inside the disc (NbxSearch.stretch), not Nominatim's one
   *        point for it.
   *   anything else                           the merchant's name, q=, with
   *        a trailing "(Plaza)" or "(Town)" dropped — "Kroger (Shiloh
   *        Square)" is asked as Kroger, and the disc chooses among them.
   *
   * "Uber's abbreviations are fine" is measured too: Pkwy and SE are matched
   * by the real install, so the string goes as the card printed it. */
  /* What is SEARCHED for a place, which is not always what was read.
   *
   * A ⌖ read off a navigation screen can come back with OCR litter in front of
   * the door: the rig held "ss be 4 1610 Ridenour Blvd, Kennesaw, GA 30144"
   * as the end of the order in the car (the coordinator's /api/status, taken
   * on shift after the pins went). searchPlan cut that at the comma and asked
   * for a street called "ss be 4 1610 Ridenour Blvd" with no door, which no
   * NucBox holds, and the public map was handed the whole string; either way
   * the held end had no pin, and the next card took off the glass the one
   * pin that had stood for it (see heldForPanel in server.js).
   *
   * The rule is a shape, not a place: a run of short tokens that do not
   * start with a capital ("ss", "be", "4", "•"), at most three characters
   * each, in front of a house number and a capitalised word, is dropped. A
   * street that has a number in its NAME keeps it — "Hwy 92 Bypass", "US 41",
   * "Old 41 Hwy" all start with a capital, so nothing is in front to drop.
   * Applied to the search only: the place keeps its text as read, in the
   * journal, on the hold and in the caption, and every place is searched by
   * this one rule, the card's and the held order's alike. */
  function searchText(place) {
    var s = String(place == null ? '' : place).replace(/\s+/g, ' ').trim();
    var m = /^((?:[^A-Z\s]\S{0,2} )+)(\d+[A-Za-z]? [A-Z])/.exec(s);
    return m ? s.slice(m[1].length) : s;
  }

  function searchPlan(place) {
    var s = searchText(place);
    if (!s) return null;
    // A bracket that opens with a house number, closed or cut off by the
    // card's edge ("Culver's (1275 Hwy" is how the reader often leaves it).
    var br = /\(\s*(\d+[A-Za-z]?\s+[^()]*?)\s*\)?\s*$/.exec(s);
    if (br && /[A-Za-z]{3}/.test(br[1])) {
      return streetPlan(br[1].replace(/[\s,.]+$/, ''));
    }
    var comma = s.indexOf(',');
    if (comma > 0 && s.slice(0, comma).indexOf('(') < 0) {
      var street = s.slice(0, comma).trim();
      if (/&/.test(street)) {
        var two = street.split('&').map(function (x) { return x.trim(); });
        return two.length === 2 && two[0] && two[1]
          ? { kind: 'cross', a: two[0], b: two[1] } : { kind: 'cross', a: null, b: null };
      }
      return streetPlan(street);
    }
    return { kind: 'name', q: s.replace(/\s*\([^()]*\)?\s*$/, '').trim() || s };
  }

  // A street, and its house number when it opens with one ("1985", "12A").
  function streetPlan(street) {
    var no = /^(\d+[A-Za-z]?)\b/.exec(street);
    return { kind: 'street', street: street, door: !!no, house: no ? no[1] : null };
  }

  /* Whether an answer is the door asked for, not just its street. Nominatim
     writes a house number as its own part of display_name, first for a bare
     address ("1985, Cobb Parkway, Kennesaw, ..." — the real install's three
     answers for 1985 Cobb Parkway) and second after a named place
     ("McDonald's, 1155, Roswell Street Northeast, ..."); a street answered
     for a door it does not hold has no number there ("Kestrel Drive,
     Marietta, ..."). Only those first two parts are read: the postcode is a
     bare number too, and always after the town and county. */
  function hasDoor(hit, house) {
    var parts = String(hit.name || '').toLowerCase().split(/\s*,\s*/).slice(0, 2);
    return parts.indexOf(String(house).toLowerCase()) >= 0;
  }

  /* The disc a place is searched in: the card's fix, and the card's own
   * distance plus SLACK_MI — the same edge cardRefuses holds a pin to, so a
   * pin chosen here is never then refused there. A card with a fix and no
   * yardstick is searched in the sixty-mile radius the public path's box
   * stands for (`card` null says so), and a card with no fix in nothing:
   * the NucBox holds Georgia, and a candidate is used only if it is alone or
   * every one agrees. */
  function discFor(card) {
    var fix = cardFix(card);
    if (!fix.at) return null;
    var yard = cardYardstick(card);
    return yard.miles
      ? { at: fix.at, miles: yard.miles + SLACK_MI, card: yard.miles,
          corrected: yard.corrected }
      : { at: fix.at, miles: BOX_MILES, card: null, corrected: false };
  }

  /* Nominatim's viewbox round a disc, widened outward to the next hundredth
     of a degree. Widened, never narrowed, so the box still holds the whole
     disc; rounded, so two cards a few hundred feet apart ask the NucBox one
     question and the server's small cache answers the second. */
  function discBox(disc) {
    if (!disc) return null;
    var dLat = disc.miles / 69.0;
    var dLon = disc.miles / (69.0 * Math.max(0.2, Math.cos(
      (Math.abs(disc.at.lat) + dLat) * Math.PI / 180)));
    function out(v, up) { return (up ? Math.ceil(v * 100) : Math.floor(v * 100)) / 100; }
    return [out(disc.at.lon - dLon, false).toFixed(2), out(disc.at.lat + dLat, true).toFixed(2),
            out(disc.at.lon + dLon, true).toFixed(2), out(disc.at.lat - dLat, false).toFixed(2)]
      .join(',');
  }

  /* When candidates are the same place. A door or a branch is one point, and
     a building and its node can both come back, a few yards apart: a fifth of
     a mile. A street with no number is answered as its pieces — Shadowood
     Parkway came back twice, both in Cumberland — and its pin stands for the
     street, not a door: a mile. Both are chosen, not measured; the real
     install's two Shadowood answers were not recorded with their spacing. */
  var AGREE_MI = 0.2;
  var STREET_AGREE_MI = 1.0;

  function agreeing(list, within) {
    for (var i = 0; i < list.length; i++) {
      for (var j = i + 1; j < list.length; j++) {
        if (crowMiles(list[i], list[j]) > within) return false;
      }
    }
    return true;
  }

  /* Which candidate, if any. `hits` is what the NucBox answered ({lat, lon,
   * name}); `disc` is discFor's answer or null; `plan` is searchPlan's;
   * `cutAt` is the server's limit when the list stopped at it, else null.
   *
   *   { at, n }                    one fits, or every one that fits agrees
   *                                (the middle of them is the pin)
   *   { why: 'capped', n }         the list was cut at n, the limit: neither
   *                                "only one fits" nor "none fits" is proven
   *                                of it, whatever is inside
   *   { why: 'nodoor', n }         a door was asked and only its street came
   *                                back
   *   { why: 'none', nearest, n }  none inside the disc; `nearest` is how
   *                                far the closest one the box held was, or
   *                                null when it held none at all
   *   { why: 'several', n }        n fit and they are not one place
   *   { why: 'together', n }       a corner (`plan.kind` 'cross') whose two
   *                                streets run together inside the disc
   *
   * CAPPED, refused outright. The other honest rule was to ask again in a
   * tighter box — but the box asked is already the disc's own (discBox), so
   * there is no tighter box that still holds the whole disc, and asking a
   * smaller one would leave part of the card's distance unsearched. One rule,
   * one question, and the driver is told it was too many. */
  // The candidates that are points at all. pickInDisc chooses among these and
  // Map view draws these (`seen`, below), so the two cannot be two lists.
  function pointsAmong(hits) {
    return (hits || []).filter(function (h) {
      return h && typeof h.lat === 'number' && typeof h.lon === 'number'
        && isFinite(h.lat) && isFinite(h.lon);
    });
  }

  function pickInDisc(hits, disc, plan, cutAt) {
    var all = pointsAmong(hits);
    if (cutAt) return { at: null, why: 'capped', n: cutAt };
    if (plan && plan.door && all.length) {
      var doors = all.filter(function (h) { return hasDoor(h, plan.house); });
      if (!doors.length) return { at: null, why: 'nodoor', n: all.length };
      all = doors;
    }
    var inside = disc ? all.filter(function (h) {
      return crowMiles(disc.at, h) <= disc.miles;
    }) : all;
    if (!inside.length) {
      var nearest = null;
      if (disc) {
        all.forEach(function (h) {
          var d = crowMiles(disc.at, h);
          if (nearest === null || d < nearest) nearest = d;
        });
      }
      return { at: null, why: 'none', nearest: nearest, n: 0 };
    }
    // A corner is a few tens of metres across. Two names carried by one road
    // share every node of it, and the street index answers that as ONE
    // meeting as long as the road (`spanM`): not a corner anybody can pin,
    // and its middle is somewhere along the road, not where the card meant.
    if (plan && plan.kind === 'cross' && inside.some(function (h) {
      return h.spanM > AGREE_MI * METRES_PER_MILE;
    })) return { at: null, why: 'together', n: inside.length };
    var within = (plan && plan.kind === 'street' && !plan.door) ? STREET_AGREE_MI : AGREE_MI;
    if (agreeing(inside, within)) {
      var mid = middleOf(inside);
      return { at: { lat: mid.lat, lon: mid.lon, name: inside[0].name || '' },
               n: inside.length };
    }
    return { at: null, why: 'several', n: inside.length };
  }

  /* --- the stretch of a street inside the disc ------------------------------
   *
   * The street index answers a numberless street ("Shadowood Pkwy SE,
   * Atlanta") as its polylines inside the disc's box, each [[lat, lon], ...];
   * these keep the parts inside the disc itself and choose a point on them.
   * Flat geometry in miles round one origin for the projections — over a
   * disc a few miles across that is well under a hundredth of a mile from
   * crowMiles — and crowMiles itself for every in-or-out decision, so a point
   * kept here is inside by the same rule pickInDisc holds a pin to. */
  function flat(o) {
    var k = 69.0 * Math.cos(o.lat * Math.PI / 180);
    return function (p) { return { x: (p.lon - o.lon) * k, y: (p.lat - o.lat) * 69.0 }; };
  }

  function lerp(a, b, t) {
    return { lat: a.lat + (b.lat - a.lat) * t, lon: a.lon + (b.lon - a.lon) * t };
  }

  // Where along a-b (0..1) is nearest `o`, flat.
  function nearestT(a, b, o, xy) {
    var A = xy(a), B = xy(b), O = xy(o);
    var dx = B.x - A.x, dy = B.y - A.y, len = dx * dx + dy * dy;
    return len ? Math.max(0, Math.min(1, ((O.x - A.x) * dx + (O.y - A.y) * dy) / len)) : 0;
  }

  // The last point from `inP` towards `outP` that is inside the disc.
  function edgeOf(inP, outP, disc) {
    var lo = 0, hi = 1;
    for (var i = 0; i < 40; i++) {
      var mid = (lo + hi) / 2;
      if (crowMiles(disc.at, lerp(inP, outP, mid)) <= disc.miles) lo = mid; else hi = mid;
    }
    return lerp(inP, outP, lo);
  }

  /* The parts of `lines` inside the disc, as runs of {lat, lon}: a line that
     leaves the disc and comes back is two runs, each ending at the edge. */
  function clipToDisc(lines, disc) {
    var xy = flat(disc.at), runs = [];
    (lines || []).forEach(function (line) {
      var run = null;
      for (var i = 0; i + 1 < line.length; i++) {
        var a = { lat: line[i][0], lon: line[i][1] }, b = { lat: line[i + 1][0], lon: line[i + 1][1] };
        var ina = crowMiles(disc.at, a) <= disc.miles, inb = crowMiles(disc.at, b) <= disc.miles;
        var from = null, to = null;
        if (ina && inb) { from = a; to = b; }
        else if (ina) { from = a; to = edgeOf(a, b, disc); }
        else if (inb) { from = edgeOf(b, a, disc); to = b; }
        else {
          // Both ends out: the segment may still pass through.
          var m = lerp(a, b, nearestT(a, b, disc.at, xy));
          if (crowMiles(disc.at, m) <= disc.miles) { from = edgeOf(m, a, disc); to = edgeOf(m, b, disc); }
        }
        if (!from) continue;
        // A run goes on only through a point inside the disc: a segment that
        // starts outside starts a new run, so no run ever bridges the outside.
        if (!ina || !run) { run = [from]; runs.push(run); }
        run.push(to);
      }
    });
    return runs;
  }

  // The nearest point of `runs` to `o`, and how far it is.
  function nearestOn(runs, o) {
    var xy = flat(o), best = null;
    runs.forEach(function (run) {
      for (var i = 0; i + 1 < run.length; i++) {
        var p = lerp(run[i], run[i + 1], nearestT(run[i], run[i + 1], o, xy));
        var d = crowMiles(o, p);
        if (!best || d < best.miles) best = { at: p, miles: d };
      }
    });
    return best;
  }

  /* How many streets the runs are: runs closer than STREET_AGREE_MI, chained,
     are one — the rule that already says when Nominatim's pieces of a street
     are one street. One street split into many ways shares its nodes, so its
     runs touch; a dual carriageway's two are tens of metres apart; two
     Church Streets in two towns are miles apart. */
  function streetsAmong(runs) {
    var group = runs.map(function (r, i) { return i; });
    function root(i) { while (group[i] !== i) i = group[i]; return i; }
    // Each run's box, flat, so two runs whose boxes are farther apart than
    // the rule are told apart without measuring every point of both.
    var xy = flat(runs[0][0]);
    var boxes = runs.map(function (r) {
      var b = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
      r.forEach(function (p) {
        var q = xy(p);
        b.x0 = Math.min(b.x0, q.x); b.y0 = Math.min(b.y0, q.y);
        b.x1 = Math.max(b.x1, q.x); b.y1 = Math.max(b.y1, q.y);
      });
      return b;
    });
    for (var i = 0; i < runs.length; i++) {
      for (var j = i + 1; j < runs.length; j++) {
        if (root(i) === root(j)) continue;
        var bi = boxes[i], bj = boxes[j];
        var gx = Math.max(0, bi.x0 - bj.x1, bj.x0 - bi.x1);
        var gy = Math.max(0, bi.y0 - bj.y1, bj.y0 - bi.y1);
        // A margin of a hundredth of a mile for the flat measure against
        // crowMiles; past it, no point of one is within the rule of the other.
        if (Math.sqrt(gx * gx + gy * gy) > STREET_AGREE_MI + 0.01) continue;
        var near = runs[i].some(function (p) {
          var hit = nearestOn([runs[j]], p);
          return hit && hit.miles <= STREET_AGREE_MI;
        }) || runs[j].some(function (p) {
          var hit = nearestOn([runs[i]], p);
          return hit && hit.miles <= STREET_AGREE_MI;
        });
        if (near) group[root(i)] = root(j);
      }
    }
    return runs.filter(function (r, i) { return root(i) === i; }).length;
  }

  /* A numberless street's pin from its stretch: pickInDisc's answers, the
   * same refusals in the same words ('none' with how far the nearest part
   * was, 'several' for streets of one name that are not one street).
   *
   * THE PIN IS THE POINT OF THE STRETCH NEAREST THE CAR (`car`, or the
   * disc's own centre when there is none) — a choice, not a finding: the
   * card names the street, not where on it. It is where the map puts the
   * mark, and nothing more: no figure is measured to it (stretchSpan says
   * why, and what the figure is instead). The pin carries the kept stretch
   * as `stretch`, [[lat, lon], ...] per run, and `nearestOf: true`. */
  function stretchInDisc(lines, disc, car, name) {
    var runs = clipToDisc(lines, disc);
    if (!runs.length) {
      var all = (lines || []).map(function (l) {
        return l.map(function (p) { return { lat: p[0], lon: p[1] }; });
      });
      var near = nearestOn(all, disc.at);
      return { at: null, why: 'none', nearest: near ? near.miles : null, n: 0 };
    }
    var streets = streetsAmong(runs);
    if (streets > 1) return { at: null, why: 'several', n: streets };
    var pin = nearestOn(runs, car || disc.at).at;
    return { at: { lat: pin.lat, lon: pin.lon, name: name || '', nearestOf: true,
                   stretch: runs.map(function (r) {
                     return r.map(function (p) { return [p.lat, p.lon]; });
                   }) },
             n: runs.length };
  }

  /* How far out of the way, when an end is a numberless street: the figure
   * at EVERY point of its stretch inside the card's disc, because the card
   * says the street and not where on it. `lo` and `hi` are the least and
   * most of MV.detour over those points (over both stretches when both ends
   * are streets), and the figure is `stated` only when it is ONE answer
   * wherever on the street the stop is: under ON_WAY_MI everywhere ("on
   * your way" is true of all of it), or past it everywhere and less than
   * ON_WAY_MI from least to most, said as the range. Anything else is
   * refused, with how long the street runs in the disc (spanRefusal).
   *
   * Every point means every vertex and a point every SPAN_STEP_MI between
   * (wider on a long street, so no stretch is more than SPAN_POINTS points
   * and its own vertices): along a straight piece the detour is greatest at
   * one of its ends, so `hi` is exact, and `lo` is within a step of the
   * least.
   *
   * It replaced a figure measured to the pin, the point nearest the car,
   * hedged on the line as "street pinned nearest you" — and nearest the car
   * is not even the point that makes the figure smallest. On a street
   * running 8 mi north-south a mile east of the car, in a 6.5 mi disc
   * (tests/mapview.test.js holds these), true +1.5 was shown as +0.6, true
   * +0.7 as "on your way", true +0.4 as +5.1. */
  var ON_WAY_MI = 0.5;
  var SPAN_STEP_MI = 0.02;
  var SPAN_POINTS = 400;

  // A pin as the points it may stand for, and how long its stretch is.
  function spanPoints(pin) {
    if (!pin.stretch) return { points: [pin], miles: 0 };
    var runs = pin.stretch.map(function (r) {
      return r.map(function (p) { return { lat: p[0], lon: p[1] }; });
    });
    var miles = 0;
    runs.forEach(function (r) {
      for (var i = 0; i + 1 < r.length; i++) miles += crowMiles(r[i], r[i + 1]);
    });
    var step = Math.max(SPAN_STEP_MI, miles / SPAN_POINTS), out = [];
    runs.forEach(function (r) {
      out.push(r[0]);
      for (var i = 0; i + 1 < r.length; i++) {
        var k = Math.max(1, Math.ceil(crowMiles(r[i], r[i + 1]) / step));
        for (var j = 1; j <= k; j++) out.push(lerp(r[i], r[i + 1], j / k));
      }
    });
    return { points: out, miles: miles };
  }

  function stretchSpan(car, pick, held) {
    if (!car || !pick || !held || !(pick.stretch || held.stretch)) return null;
    var ps = spanPoints(pick), hs = spanPoints(held);
    var lo = Infinity, hi = -Infinity;
    ps.points.forEach(function (p) {
      hs.points.forEach(function (h) {
        var d = detour(car, p, h);
        if (d < lo) lo = d;
        if (d > hi) hi = d;
      });
    });
    return { lo: lo, hi: hi, miles: Math.max(ps.miles, hs.miles),
             whose: ps.miles >= hs.miles ? 'new' : 'held',
             stated: hi < ON_WAY_MI || (lo >= ON_WAY_MI && hi - lo < ON_WAY_MI) };
  }

  /* --- how each place was found, to draw ------------------------------------
   *
   * The driver's ask: "show on the map how the rig located each place, so I
   * can see at a glance that it is working (or why it refused)". Everything
   * below DRAWS what was already decided and decides nothing: the answers are
   * the ones NbxSearch kept beside its choice (`seen` — the NucBox's own list,
   * the corner's meetings, the street's lines), so drawing them asks nobody
   * anything, and the words are nbxRefusal's, the same the caption says.
   *
   * The card's disc, as Map view draws it: the card's fix and its distance
   * plus SLACK_MI (discFor) — what NbxSearch searches the card's places in,
   * and what cardRefuses holds the pickup pin to. Not every pin: the dropoff
   * is held to none, and with no NucBox the places are asked in the public
   * box (BOX_MILES round the car) and then wide. Null for a card with no fix, and for one with no
   * yardstick — that card's search is the sixty miles the public box stands
   * for, which is not the card's reach, and a sixty-mile circle round the car
   * would say nothing. It is drawn, never fitted to: Map view's view is the car
   * and the pins (see drawHow). */
  function discShape(disc) {
    if (!disc || disc.card === null || disc.card === undefined) return null;
    return { lat: disc.at.lat, lon: disc.at.lon, miles: disc.miles,
             metres: disc.miles * METRES_PER_MILE };
  }

  /* What to draw of how ONE place was found, as plain data: `res` is what
   * NbxSearch.place answered for it, `disc` the disc it was searched in, `name`
   * the place as the caption shows it, `whose` 'new' or 'held'.
   *
   *   marks  every candidate the NucBox sent (a corner: every meeting), each
   *          { lat, lon, kind, tip }: kind 'outside' past the disc's edge —
   *          crowMiles against disc.miles, pickInDisc's own test — else
   *          'candidate'. The pin itself is not here: the page already draws
   *          it, in colour, and a second copy would be a second rule for
   *          where it is.
   *   lines  a numberless street's stretch INSIDE the disc, { pts, kind,
   *          tip }: kind 'chosen' when it was pinned (the very runs the pin
   *          carries), 'candidate' when it was refused. What lies outside the
   *          disc is not drawn — it is not where the card can mean.
   *
   * `tip` says what the mark is in words: for a refused place, the refusal
   * the caption gives (nbxRefusal), so the mark and the line under the map
   * cannot disagree; for a pinned one, whether the candidate counted.
   *
   * Nothing for an answer with no `seen` — the public geocoder's one answer,
   * a NucBox that could not be asked, a question the relay refused, a cross
   * street with no index, a stretch past the index's cap (which sends no
   * lines for one): there is no list behind those to show, and drawing
   * nothing says no more than that. */
  function located(res, disc, name, whose) {
    var out = { marks: [], lines: [] };
    if (!res || !res.seen) return out;
    // A refusal nbxRefusal has no words for is still no pin, and is never
    // drawn as "pinned".
    var why = res.at ? null : (nbxRefusal(res, disc, name, whose) || 'no pin for ' + name);
    var edge = disc ? ' the ' + disc.miles.toFixed(1) + ' mi searched' : '';
    var hits = res.seen.hits || [];
    var door = res.seen.door || null;
    // For a pin, pickInDisc's `n` is how many candidates went into it.
    var counted = res.n || 0;
    hits.forEach(function (h) {
      var away = disc ? crowMiles(disc.at, h) : null;
      var outside = away !== null && away > disc.miles;
      var notDoor = door && !hasDoor(h, door);
      var said = outside ? away.toFixed(1) + ' mi from the card\'s fix, outside' + edge
               : notDoor ? 'its street, not door ' + door
               : null;
      var tip = why !== null ? why + (said ? ' · this one ' + said : '')
              : said ? name + ' — ' + said + ', not used'
              : name + ' — ' + (counted > 1 ? 'one of ' + counted + ' that agree, pinned at their middle'
                                            : disc ? 'the one inside' + edge + ', pinned'
                                                   : 'pinned, with no card fix to hold it to');
      out.marks.push({ lat: h.lat, lon: h.lon, kind: outside ? 'outside' : 'candidate',
                       tip: tip });
    });
    if (res.at && res.at.stretch) {
      res.at.stretch.forEach(function (run) {
        out.lines.push({ pts: run, kind: 'chosen',
                         tip: name + ' — its stretch inside' + edge
                              + '; the pin is its point nearest you' });
      });
    } else if (res.seen.lines && disc && why !== null) {
      clipToDisc(res.seen.lines, disc).forEach(function (run) {
        out.lines.push({ pts: run.map(function (p) { return [p.lat, p.lon]; }),
                         kind: 'candidate', tip: why });
      });
    }
    return out;
  }

  /* The words, for the two cards Map view measures with: this one ('new')
     and the one the order in the car came from ('held'). Each is the reason
     the figure is withheld, said instead of it, and each is reached by a
     fixture in tests/mapview.test.js. Load-bearing end first, because the
     caption is clamped at two rows (three on the 3.5" hat) and the clamp cuts
     the tail. */
  var FIX_WORDS = {
    'new': {
      none: 'this card came up without a GPS fix',
      rough: 'GPS fix on this card too rough to measure from',
      unrated: 'GPS on this card gave no accuracy to measure from',
      nomode: 'GPS on this card had no 2D/3D fix to measure from',
      frozen: 'GPS on this card was stuck on one spot, so nothing to measure '
        + 'from',
      other: 'GPS fix on this card was never judged, so nothing to measure from'
    },
    held: {
      nocard: 'the rig kept no card for the order in your car, so its end '
        + 'cannot be checked',
      none: 'the order in your car came up without a GPS fix, so its end '
        + 'cannot be checked',
      rough: 'GPS fix on the order in your car too rough to check its end',
      unrated: 'GPS on the order in your car gave no accuracy to check its end',
      nomode: 'GPS on the order in your car had no 2D/3D fix to check its end',
      frozen: 'GPS on the order in your car was stuck on one spot, so its end '
        + 'cannot be checked',
      other: 'GPS fix on the order in your car was never judged, so its end '
        + 'cannot be checked'
    }
  };

  function fixLine(fix, whose) {
    var words = FIX_WORDS[whose];
    var line = words[fix.why === null ? 'none' : fix.why] || words.other;
    return fix.why === 'rough' && fix.err !== null
      ? line + ' (±' + Math.round(fix.err) + ' m)' : line;
  }

  var YARD_WORDS = {
    'new': {
      none: 'this card states no distance to check the pickup pin against',
      untrusted: 'the rig does not trust this card\'s distance, so the pickup '
        + 'pin cannot be checked',
      early: 'an Early look card may not measure from your car — no yardstick '
        + 'yet',
      shape: 'this kind of card may not count the drive to the pickup — no '
        + 'yardstick yet'
    },
    held: {
      none: 'the order in your car stated no distance to check its end against',
      untrusted: 'the rig did not trust the distance on the order in your car, '
        + 'so its end cannot be checked',
      early: 'the order in your car was an Early look card — no yardstick yet '
        + 'for its end',
      shape: 'the order in your car is a kind of card with no yardstick yet '
        + 'for its end'
    }
  };

  /* The line for a pin this card contradicts, or null when it does not —
     and, before that, the line for a card that cannot be held against a pin
     at all. `name` is the place as the panel shows it (live.html cuts it to
     what fits); `fix` is cardFix's `at`.

     The refusal blames the MAP and makes no claim about the world: the
     geocoder is asked for one answer, so "no McDonald's within 9.4 mi of you"
     would be a sentence nobody measured — there may well be one 2 miles away
     that the map did not return. And "(rig-corrected)" where check_distance
     put a decimal back, as statedBy() says on the map pages: the figure is
     the rig's repair, not what the screen printed.

     THE REFUSAL LEADS. This read "the map's McDonald's is 21.8 mi from you,
     so past the card's 9.4 mi", and the 3.5" hat's clamp may eat what follows
     the comma, which left "the map's McDonald's is 21.8 mi from you": a
     distance with nothing saying the pin is refused, read at a glance as a
     pickup 21.8 mi away. "wrong pin" is now the first two words, so whatever
     a clamp keeps says the pin is wrong (rpi/test_layout.py). */
  function againstCard(o, fix, pin, name, whose) {
    var yard = cardYardstick(o);
    if (!yard.miles) return YARD_WORDS[whose][yard.why];
    var out = cardRefuses(o, fix, pin);
    if (!out) return null;
    var said = out.miles + ' mi' + (out.corrected ? ' (rig-corrected)' : '');
    return 'wrong pin for ' + name + ' — ' + out.crow.toFixed(1) + ' mi from '
      + (whose === 'new'
         ? 'you, past the card\'s ' + said
         : 'your order\'s card, past its ' + said);
  }

  /* Why the NucBox gave no pin, in words, or null when it gave one. `res` is
     pickInDisc's answer (or searchPlan's cross-street one), `disc` the disc
     it was searched in, `name` the place cut to fit, `whose` 'new' or 'held'
     as above. Like againstCard, the refusal leads — "no pin for" is the first
     three words, so whatever the hat's clamp keeps says there is no pin, and
     why in a few words ("none fit the card", "2 fit the card and disagree").
     The disc's figures follow as the declared tail, " · within 9.4 mi of
     you, nearest 1.2 mi": measured by rpi/test_layout.py, with the figure
     and the rig's repair inside the sentence six of these ran past the
     hat's three rows at the widest name, so they go together after the
     refusal instead. It blames the search, never the world: "none fit the
     card" is a fact about what the NucBox holds, not a claim that no
     McDonald's exists there. These kinds reach here — none, several (`n`),
     and their two for a corner, `nomeet` and `corners` ("2 corners fit
     the card"; none inside is "none fit the card" as for any candidates, and
     "its streets do not meet" with no card to measure by); a cross street with
     no street index to ask, or that is not two names, or that names a
     street the index does not hold, or two that run together; a list cut
     at the limit, a stretch too long to send, a street answered for a door,
     and the rig's own server refusing the question — and anything else is
     no line at all. The last is a bug in this page, said as one: the server
     refuses only questions shaped wrong, and falling back to the public map
     for it would hide the bug behind an answer. */
  // The refusals that say the same whatever the disc, keyed on
  // pickInDisc's and NbxSearch.place's `why`. The bug's reason (the server's
  // `error`) is not on the panel: with it, the line ran past two rows at
  // 800x480 (rpi/test_layout.py), and a driver cannot act on it.
  var NBX_WORDS = {
    cross: function () { return 'no street index to ask'; },
    notwo: function () { return 'not two street names'; },
    nostreet: function () { return 'a street name not on the NucBox'; },
    together: function () { return 'its streets run together'; },
    capped: function (res) {
      return 'too many to be sure · the NucBox lists ' + res.n + ' at most';
    },
    long: function (res) {
      return 'street too long to be sure · the NucBox sends ' + res.n + ' points at most';
    },
    nodoor: function () { return 'street found, not that door'; },
    refused: function () { return 'a bug: the rig refused the question'; }
  };

  /* pickInDisc's two answers that are worded against the disc — nothing
     inside it, or several that are not one place — for candidates, and for
     the meetings of a corner's two streets ("2 corners fit the card", "no
     corner fits the card"). Worded "corners" because "its streets meet in 2
     places in the card" ran past two rows at 800x480 (rpi/test_layout.py). */
  var DISC_KINDS = { none: { none: true }, nomeet: { none: true, corner: true },
                     several: {}, corners: { corner: true } };

  function nbxRefusal(res, disc, name, whose) {
    if (!res || res.at) return null;
    var lead = 'no pin for ' + name + ' — ';
    if (Object.prototype.hasOwnProperty.call(NBX_WORDS, res.why)) {
      return lead + NBX_WORDS[res.why](res);
    }
    var kind = Object.prototype.hasOwnProperty.call(DISC_KINDS, res.why)
      ? DISC_KINDS[res.why] : null;
    if (!kind || (!kind.none && !res.n)) return null;
    var none = !!kind.none, corner = !!kind.corner;
    var mine = whose === 'new';
    if (!disc) {
      return none ? lead + (corner ? 'its streets do not meet' : 'the NucBox found nothing for it')
        : lead + res.n + (corner ? ' corners' : '') + ' found · no GPS fix '
          + (mine ? '' : 'on your order\'s card ') + 'to choose between them';
    }
    var where = mine ? ' of you' : ' of your order\'s card';
    var near = (none && res.nearest !== null && res.nearest !== undefined)
      ? ', nearest ' + res.nearest.toFixed(1) + ' mi' : '';
    if (disc.card === null) {
      return lead + (none ? (corner ? 'its streets do not meet' : 'none found')
                          : res.n + (corner ? ' corners found' : ' found and they disagree'))
        + ' · within ' + BOX_MILES + ' mi' + where + near;
    }
    // "its card" is the order in the car's, and says whose distance it is;
    // " of your order's card" after it as well ran past two rows at 800x480.
    var card = mine ? 'the card' : 'its card';
    // A corner with no meeting inside the card is said as any candidates
    // are: "no corner in the card" with the disc's tail ran past two rows at
    // 800x480 (rpi/test_layout.py), and "none fit the card" is as true of it.
    return lead + (none ? 'none fit ' + card
                        : res.n + (corner ? ' corners fit ' + card
                                          : ' fit ' + card + ' and disagree'))
      + ' · within ' + disc.card + ' mi' + (disc.corrected ? ' (rig-corrected)' : '')
      + (mine ? where : '') + near;
  }

  /* Why a figure to a numberless street is not stated (stretchSpan): where
     on it the stop is changes the answer, and the card does not say. The
     refusal leads, as the disc's own lines do, and says how much street
     there is to be anywhere on; `name` is the place cut to fit, `whose`
     'new' (this card's disc) or 'held' (the held card's). */
  function spanRefusal(span, name, whose) {
    if (!span || span.stated) return null;
    return 'no figure for ' + name + ' — the street runs ' + span.miles.toFixed(1)
      + ' mi in ' + (whose === 'new' ? 'the card' : 'its card');
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
   * project exists to refuse.
   *
   * ...but only against a distance the rig itself stands behind. The
   * accusation is made out of two things, and the argument above establishes
   * only one of them: a straight line cannot beat the road, so IF the card's
   * figure is the whole journey, a longer line means a pin is wrong. Where the
   * reading holds a FRACTION of the journey the inequality still comes out
   * true and means nothing at all — the straight line beat a number that was
   * never the road. The pins are then accused of a shortfall the reader
   * produced, in the words "This cannot be right", on the one page whose job
   * is to say whether the rig is right about where the work happened.
   *
   * The row says whether it is a whole journey, in flags every consumer of
   * the journal already reads. `whole === false` is the reader saying it did
   * not finish — a leg that lost its distance leaves the sum short, which is exactly the shape that manufactures this accusation
   * (offer_parser.legs_short_a_distance measured one at 1.1 miles of a card
   * that printed 8.4). `suspect` is the reader saying the row is not to be
   * leaned on at all.
   *
   * ...and `milesUncertain`, which is the flag this was first written against
   * and is NOT covered by the other two. rpi/test_journal.py asserts as a
   * property that every route to it also trips `suspect` or `whole === false`,
   * and that is true of the rig — but journal-client.js writes `whole: true,
   * suspect: false` as literals while reporting `milesUncertain` honestly off
   * rate(). So a card read by the PHONE's scanner can reach here uncertain and
   * otherwise spotless. Put through the real journal-client, the corpus's own
   * damaged card `$16.05 3 min (1.1 mi) away 20 min (7.3 m1) trip` writes a row
   * of 1.1 miles — the approach leg alone, where the card's own trip leg is
   * 7.3 — flagged uncertain, whole and not suspect. Any two pins more than
   * 1.6 miles apart are then accused, which is every pair on a real card.
   *
   * All three clauses are load-bearing and each dies to its own mutation. On
   * the owner's week 14 of the 578 pairs that name both ends and state a
   * distance fail this rule: one on `suspect` alone (56.6 miles over 25
   * minutes), ten on `whole` alone, three on both — and those three say how
   * much is missing, holding 5.6 miles of a card that printed 56, 7.9 of one
   * that printed 24.6, and 3.9 of one that printed 273.
   *
   * `whole !== false` and not `whole === true`: rows written before the flag
   * existed do not carry it, and they were only ever written when whole. Same
   * convention as advice.js's `trustworthy`, for the same reason.
   *
   * The pair is not silently dropped when the yardstick fails. `unjudged` says
   * so, and the three surfaces that draw this say it in words — an accusation
   * withdrawn with nothing in its place is the second fault class wearing the
   * clothes of a fix. */
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
      // A figure, and whether that figure is a YARDSTICK. See above.
      var yardstick = stated !== null && vouches(o);
      return { offer: o, from: a, to: b, crow: crow, stated: stated,
                        // Whether `stated` is the card's own figure or the rig's
               // repair of it. check_distance divides by ten to put back a
               // decimal the read lost, so on 328 of the owner's 1,166 offers
               // — 262 of the 579 that name both ends — "card said 9.5 mi"
               // was the page attributing the rig's arithmetic to the screen.
               corrected: !!o.milesCorrected,
               impossible: (crow !== null && yardstick
                            && crow > stated + SLACK_MI),
               // Placed at both ends, holding a figure, and that figure is not
               // one a straight line can contradict. Said rather than left
               // out: a pair that quietly stops being checked looks exactly
               // like a pair that passed.
               unjudged: (crow !== null && stated !== null && !yardstick),
               // How far out of the shift each end landed, when it did. Kept
               // per end rather than as one flag, because which of the two is
               // in another state is the whole of what the driver needs to
               // know to judge it.
               fromStray: o.pickup ? (strays[o.pickup] || null) : null,
               toStray: o.dropoff ? (strays[o.dropoff] || null) : null };
    });
  }

  /* Where `stated` came from, in words.
   *
   * Three surfaces print this figure — map.html's line popup, map.html's
   * sidebar, and the offer log's map sheet in journal.html — and all three
   * said "card said N mi". On a corrected row the card said ten times N: the
   * reader lost the decimal in "9.5 mi", read 95, computed a speed no car
   * makes and divided by ten. That is a good repair and rate() is right to use
   * it, but it is the rig's number, not the screen's, and this page exists to
   * let a driver check the rig against the screen. A driver who goes back to
   * the card and finds 95 has been told the page is broken.
   *
   * Written once and asked four times rather than worded four times, which is
   * how one fact comes to have four answers that drift — the line popup, the
   * two sidebar sections that list these pairs, and the offer log's map sheet.
   * The first pass at this reached two of the four; the accusation row and the
   * withheld row still put the rig's repaired figure in the card's mouth. */
  /* The two ends of one offer, in the order the journey runs.

     Three surfaces were drawing them out of `places` joined with an arrow —
     live.html's address row, the offers page's log row, and its detail row —
     and `places` is the accumulator's union in the order the FRAMES arrived,
     which is not journey order. The two-ends fix gave `pickup` and `dropoff`
     that order and deliberately left the list alone, so the arrow kept
     claiming one the list does not have. The offers page's own detail SHEET
     already drew `[pickup, dropoff]`, so that one page answered "which end is
     which" two ways at once, a few hundred lines apart.

     Measured through the real accumulator over the owner's week: 12 of 1,166
     readings drew the arrow backwards — `Happy Hawg BBQ (Hiram)` as the
     destination of a delivery that starts there — and 182 drew a three- or
     four-stop chain for a job with two ends, because the union holds every
     reading of every name.

     REORDERS what the card printed; it never adds to it. Both ends have to be
     in `places` for the pair to be used, and where they are not the list comes
     back untouched. That is not fussiness — the offers page keeps a dropoff
     the DRIVER revealed on their phone in a row of its own, under its own
     label, and says why: "folding it into Where would hide that a card
     printing 'Customer dropoff' now has an address at all." A rule that
     returned `[pickup, dropoff]` whatever their source would do exactly that
     folding, and quietly put a phone reading in the card's mouth.

     So the sheet at the bottom of that page does NOT ask this. It wants the
     two points to draw a map between, whichever way each was learned, which
     is a different question with a different right answer. */
  /* Whether this pair is an accusation rather than a drawing.

     map.html draws such a pair as a RED DASHED line captioned "This cannot be
     right". Three places decided that separately and two of them disagreed:
     render() and the sidebar's heading counted `impossible || fromStray ||
     toStray`, while placeAll's own `drawn` — the figure in the status line
     under the map — left the stray ends out of the test and so counted an
     accusation as a success. Same words on one screen, "drawn end to end",
     two different numbers behind them.

     The stray half is not covered by `impossible`, which needs a second pin to
     argue against. A stray is a pin nowhere near the rest of the shift, and
     there are 15 such pairs in the owner's 579 both-ended ones. */
  /* The figure that leads a town's row in "Where the money is", and the one
   * thing it must never be is a number the page invented.
   *
   * Three cases and they are genuinely different questions:
   *
   *   the ranking is not held still  the town's own median, what it PAID
   *   held still, town comparable    what it paid over the same hours elsewhere
   *   held still, nothing to compare a dash, because there is no answer
   *
   * The third exists because `Advice.areas` reports `matched: null` for a town
   * whose every hour held no other town — there is nothing it can be said to
   * have paid more or less THAN. `null >= 0` is true in JavaScript, so the
   * obvious formatter prints "+$NaN/hr" there, which is this project's first
   * fault class arriving through a comparison operator.
   *
   * Here rather than inline in `map.html` so it can be driven without a browser
   * and a server: the dash is unreachable on the owner's week, where the
   * thinnest three-hour block holds six towns, and reachable on the journal a
   * new rig has. `unit` is returned separately because a dash takes none — a
   * bare "—/hr" reads as a rate that failed to print rather than as a question
   * with no answer. */
  function rankLead(group, heldStill) {
    var g = group || {};
    if (!heldStill) {
      return { text: '$' + Number(g.median).toFixed(2), unit: true };
    }
    if (g.matched === null || g.matched === undefined) {
      return { text: '—', unit: false };
    }
    return { text: (g.matched >= 0 ? '+' : '−')
                   + '$' + Math.abs(g.matched).toFixed(2), unit: true };
  }

  /* Where each town stands, as the line a pin's popup quotes, keyed on the
   * town's name. Empty when the ranking did not beat chance: a pin must not
   * quote a position in a list the page has just called a coin toss.
   *
   * It printed "<town> is N of M towns here, median $X/hr" — the POSITION from
   * the hour-held order and the NUMBER from the raw one, in one clause, under
   * a sidebar that spends a paragraph saying those are different questions.
   * On the owner's week, "any time", the default view: Kennesaw is 3rd at
   * $15.32 and Woodstock 4th at $15.80, Acworth 5th at $14.01 and Marietta 6th
   * at $14.62. Two of the 36 pairs read backwards, and a driver tapping two
   * pins to compare towns reads an ordinal and a figure as one fact. (Six of
   * 36 before the ranking's baseline stopped including the town itself; the
   * pairing was wrong either way.)
   *
   * So the position is quoted with the figure it was ranked by — `rankLead`,
   * the same one the sidebar's row leads with, so the popup cannot disagree
   * with the list it is quoting — and the median beside it as what was earned,
   * as the sidebar's row does. A town with no hour-held figure is not in the
   * order at all (`Advice.areas` sorts it last because it has no place, not
   * because it is worst), so it gets no ordinal, and M counts only the towns
   * that have one.
   *
   * Looked up by the PIN's own town, not by the town its offers were counted
   * under (`townFor` takes the dropoff first). Decided, not overlooked: the
   * line is a claim about the town named on the pin, and it is true of that
   * town whichever end put this pin's offers in some other group — which is
   * what "that is the town, not this place" is there to say. */
  function standings(rank) {
    var out = {};
    if (!rank || !rank.real || !rank.groups) return out;
    var held = !!rank.matched;
    var inOrder = rank.groups.filter(function (g) {
      return !held || (g.matched !== null && g.matched !== undefined);
    });
    rank.groups.forEach(function (g) {
      var lead = rankLead(g, held);
      var median = '$' + Number(g.median).toFixed(2);
      var at = inOrder.indexOf(g);
      out[g.name] = at < 0
        ? g.name + ' had no other town in its hours to be ranked against; '
          + median + ' median'
        : held
          ? g.name + ' is ' + (at + 1) + ' of ' + inOrder.length + ' towns here at '
            + lead.text + '/hr once the hour is held still; ' + median + ' median'
          : g.name + ' is ' + (at + 1) + ' of ' + inOrder.length + ' towns here, '
            + 'median ' + median + '/hr';
    });
    return out;
  }

  function accused(p) {
    return !!(p && (p.impossible || p.fromStray || p.toStray));
  }

  function ends(row) {
    if (!row) return [];
    var have = (row.places || []).filter(Boolean);
    var pu = row.pickup, dr = row.dropoff;
    if (pu && dr && pu !== dr
        && have.indexOf(pu) !== -1 && have.indexOf(dr) !== -1) return [pu, dr];
    return have;
  }

  function statedBy(p) {
    if (!p || p.stated === null) return '';
    // "a lost decimal put back" would say THIS figure is the repair, and the
    // flag does not mean that. rpi/accumulate.py ORs milesCorrected across the
    // window and its own comment calls it advisory — "if any frame needed a
    // decimal put back, the distance is worth a glance" — so the published
    // figure may be one no frame ever divided. What is true of both the rig's
    // ORed flag and the phone's exact one is that a decimal had to be put back
    // somewhere while this card was read, which is a reason to check the
    // screen and not a claim about this number.
    return p.corrected
      ? 'read as ' + p.stated + ' mi total — a decimal had to be put back '
        + 'while reading this card, so check it against the screen'
      : 'card said ' + p.stated + ' mi total';
  }

  /* ...and why a pair with two pins and a figure is not being checked against
     it, or '' when it is. The reason matters and the two are different: one is
     a reading that stopped early, the other is a reading the rig refused. */
  function unchecked(p) {
    if (!p || !p.unjudged) return '';
    // Asked first because it is the most specific: the reader is not refusing
    // the reading, it is refusing this one figure.
    if (p.offer.milesUncertain) {
      return 'the rig would not trust the distance on this card, so its '
        + p.stated + ' mi is not something a straight line can be measured '
        + 'against';
    }
    return p.offer.whole === false
      ? 'only part of this card was read, so its ' + p.stated
        + ' mi is a fraction of the journey and nothing here can be measured '
        + 'against it'
      : 'the rig marked this reading suspect, so its ' + p.stated
        + ' mi is not a distance a straight line can contradict';
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
  /* ...and a tally of what those offers actually WERE.
   *
   * `jobs` counts offers, and most offers are turned down. A pin reading 12 on
   * a Chipotle the driver took two jobs from says they worked there twelve
   * times, in the largest glyph on the page. That is a fact about the rig's
   * scanning, presented as a fact about the driver's evening.
   *
   * Three states, kept apart, because `accepted` is a tri-state and folding it
   * to a boolean tells a different lie: a range where nothing was ever ticked
   * would report "0 taken" of twelve, which reads as twelve refusals. Not
   * marked is not the same as not taken, and the page has wording for that. */
  function byPlace(placed) {
    var seen = {}, order = [];
    function note(name, point, role, p) {
      if (!name || !point) return;
      if (!seen[name]) {
        seen[name] = { name: name, point: point, roles: {}, jobs: [],
                       took: 0, passed: 0, unmarked: 0 };
        order.push(name);
      }
      seen[name].roles[role] = true;
      seen[name].jobs.push(p);
      if (p.offer.accepted === true) seen[name].took += 1;
      else if (p.offer.accepted === false) seen[name].passed += 1;
      else seen[name].unmarked += 1;
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
    // The public map is asked by the same rule as the NucBox: see searchText.
    var q = searchText(place);
    if (box) return q;
    var hint = (this.hint() || '').trim();
    return hint ? q + ', ' + hint : q;
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
      // The ONE key just answered, not every key this page happens to hold.
      //
      // Writing back the whole in-memory cache made any still-open page undo
      // "Forget lookups" on the next place it looked up. Measured: a panel with
      // five answers in memory, the desk page presses Forget and the device
      // empties, the panel answers one more place and all five are back on the
      // device — and a page opened after that believes them again. Which is the
      // one button that can throw away a bad geocode, defeated by the page the
      // driver has open in the car.
      //
      // The merge it was for still happens, because `onDevice` was just re-read
      // and is adopted below: this page still GETS the other page's work. What
      // it no longer does is push its own history back over a device that has
      // deliberately moved on.
      onDevice[key] = value;
      // Written first, adopted second, and the order is the whole of it. If the
      // store refuses — site data blocked, or a full quota — the throw skips
      // the line below and this page keeps the answers it has accumulated in
      // memory for the rest of the session. Adopting first would replace them
      // with a device snapshot that the write then failed to update, so every
      // answer would be dropped as soon as the next one arrived and a second
      // press would re-ask every place at a second apiece.
      this.store.set(JSON.stringify(onDevice));
      this.cache = onDevice;
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
      // Every place, not every third. How OFTEN to say something is the
      // caller's business; this loop only knows what happened.
      //
      // The `% 3` was calibrated for placeAll's whole-journal list, where it
      // is a sensible throttle. On the driving panel a decision asks about two
      // or three places, and `done % 3 === 0 || done === list.length` then
      // collapses to "once, at the end" — so a caller that wanted to draw each
      // pin as it landed was handed the whole set at once and could not.
      // Measured on the panel's own shapes: callbacks were [[2701ms, 3]] and
      // [[1602ms, 2]]; without the throttle they are [[502,1],[1603,2],
      // [2704,3],[3805,'wide']].
      //
      // Cost to placeAll, the only other caller: its `say` is one textContent
      // write, now once per second or so of paced waiting instead of once per
      // three, and N writes in one await-chain on a fully cached walk
      // (measured: 3 writes, 0ms, for 3 cached places).
      if (onward) {
        onward({ done: done, total: list.length, left: left,
                 seconds: Math.ceil(left * this.gap / 1000) });
      }
    }
    return into;
  };

  /* --- the NucBox, through this rig's own server ---------------------------
   *
   * server.js relays two questions to the NucBox at home (/api/nbx/search and
   * /api/nbx/route) and says whether either is set (/api/nbx). The browser
   * never talks to the NucBox itself. Nothing here is used unless the server
   * says the search is set, so a rig with neither setting draws exactly what
   * it drew before.
   *
   * No one-a-second rule: that is the public server's, and this one is the
   * driver's own. Still paced, at NBX_GAP_MS, so a page that one day loops by
   * mistake cannot flood a NucBox that is also serving the copy of the
   * journal. A card asks at most five questions — three places and two
   * routes — so the pacing costs a card at most four gaps, 0.4 s.
   *
   * Answers are kept in memory for the page's life, keyed on the question
   * actually sent. Not in the device's store and not in /api/places: those
   * hold the PUBLIC geocoder's one-answer-per-string, and a pin chosen inside
   * one card's disc is a different answer to a different question. */
  var NBX_GAP_MS = 100;

  function NbxSearch(opts) {
    opts = opts || {};
    this.gap = typeof opts.gap === 'number' ? opts.gap : NBX_GAP_MS;
    this.now = opts.now || function () { return Date.now(); };
    this.sleep = opts.sleep || function (ms) {
      return new Promise(function (r) { setTimeout(r, ms); });
    };
    this.fetch = opts.fetch || function (u, init) { return fetch(u, init); };
    this.base = opts.base || '/api/nbx';
    this.cache = {};
    this.lastAsk = 0;
  }

  // One limiter, the Geocoder's, at this object's own gap.
  NbxSearch.prototype.paced = Geocoder.prototype.paced;

  /* Ask, or say why not. Never rejects. Resolves:
       the answer        { ok, ... }, kept for the page's life; OSRM's
                         { noRoute } too (an answer about the points)
       { unreachable }   the server's `unreachable: true` (the NucBox did not
                         answer) or `configured: false` (none is set any
                         more), or this rig's server not answering at all —
                         the cases the page falls back to the public map for
       { refused }       anything else: the relay refused the question as
                         this page put it (a 400, a 404 for a path it does
                         not have). That is a bug here, not a NucBox that is
                         down, and is said as one rather than quietly asked
                         of the public map instead. */
  NbxSearch.prototype.get = function (path) {
    var self = this;
    if (Object.prototype.hasOwnProperty.call(this.cache, path)) {
      return Promise.resolve(this.cache[path]);
    }
    return this.paced(function () {
      return self.fetch(self.base + path, { headers: { 'Accept': 'application/json' } });
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (r.ok && body && body.ok !== undefined) {
          self.cache[path] = body;
          return body;
        }
        var why = (body && body.error) || ('the server said ' + r.status);
        if (body && (body.unreachable === true || body.configured === false)) {
          return { unreachable: why };
        }
        return { refused: why };
      });
    }, function (e) {
      return { unreachable: 'this rig\'s server did not answer (' + ((e && e.message) || e) + ')' };
    });
  };

  /* One place, inside its disc: pickInDisc's answer, or { why: 'cross' },
     { why: 'unreachable', error } or { why: 'refused', error }.
     `opts.streets` is whether this rig's server has the NucBox's street
     index set (nbxSettings): with it a cross street is asked as a corner
     and a numberless street as its stretch; without it, as before. And
     `opts.car` is where the car is, for the point of a stretch nearest it
     (stretchInDisc). The card's town is never sent and never used. */
  NbxSearch.prototype.place = function (place, disc, opts) {
    opts = opts || {};
    var plan = searchPlan(place);
    if (!plan) return Promise.resolve({ at: null, why: 'none', nearest: null, n: 0 });
    if (plan.kind === 'cross') {
      return opts.streets ? this.corner(plan, disc)
        : Promise.resolve({ at: null, why: 'cross', n: 0 });
    }
    if (plan.kind === 'street' && !plan.door && opts.streets && disc) {
      var self = this;
      // A street the index does not hold — a name outside the metro it was
      // cut to, or one with no drivable way of that name — is asked of the
      // search as it always was, under the same disc.
      return this.stretch(plan, disc, opts.car).then(function (res) {
        return res.why === 'nostreet' ? self.search(plan, disc) : res;
      });
    }
    return this.search(plan, disc);
  };

  // A refusal from the relay, or null when `body` is an answer.
  function nbxDown(body) {
    if (body.unreachable) return { at: null, why: 'unreachable', error: body.unreachable };
    if (body.refused) return { at: null, why: 'refused', error: body.refused };
    return null;
  }

  /* Where the two streets of a corner meet, inside the disc, chosen by
     pickInDisc as any other candidates are: one meeting inside, or several
     that are one place (AGREE_MI — a dual carriageway's corners the index
     did not already join), is the pin; meetings that are not one place are
     `corners`, none inside is `nomeet` with how far the nearest was, and a
     name the index does not hold at all is `nostreet`. */
  NbxSearch.prototype.corner = function (plan, disc) {
    if (!plan.a) return Promise.resolve({ at: null, why: 'notwo', n: 0 });
    var box = discBox(disc);
    var path = '/cross?a=' + encodeURIComponent(plan.a) + '&b=' + encodeURIComponent(plan.b)
             + (box ? '&box=' + encodeURIComponent(box) : '');
    return this.get(path).then(function (body) {
      var down = nbxDown(body);
      if (down) return down;
      if (!body.a.names.length || !body.b.names.length) return { at: null, why: 'nostreet', n: 0 };
      var called = body.a.names[0] + ' & ' + body.b.names[0];
      function meetsOf() {
        return body.meets.map(function (m) {
          return { lat: m.lat, lon: m.lon, spanM: m.spanM, name: called };
        });
      }
      // Every meeting the index sent, kept beside the answer for Map view to
      // draw (`seen`, see located): the same list, never asked for again.
      if (body.cutAt) {
        return { at: null, why: 'capped', n: body.cutAt,
                 seen: { hits: pointsAmong(body.meets ? meetsOf() : []), corner: true } };
      }
      var meets = meetsOf();
      var seen = { hits: pointsAmong(meets), corner: true };
      var res = pickInDisc(meets, disc, plan, null);
      if (res.why === 'several') res.why = 'corners';
      else if (res.why === 'none') res.why = 'nomeet';
      res.seen = seen;
      return res;
    });
  };

  /* A numberless street as its stretch inside the disc (stretchInDisc), or
     `nostreet` for a name the index does not hold, or `long` for a stretch
     the NucBox would not send whole. */
  NbxSearch.prototype.stretch = function (plan, disc, car) {
    var path = '/stretch?name=' + encodeURIComponent(plan.street)
             + '&box=' + encodeURIComponent(discBox(disc));
    return this.get(path).then(function (body) {
      var down = nbxDown(body);
      if (down) return down;
      if (!body.names.length) return { at: null, why: 'nostreet', n: 0 };
      // Refused as too long to judge. Nothing of it to draw: past its cap
      // the index sends no lines at all (streets.js stretch).
      if (body.cutAt) return { at: null, why: 'long', n: body.cutAt };
      var res = stretchInDisc(body.lines, disc, car, body.names[0]);
      res.seen = { lines: body.lines };
      return res;
    });
  };

  // Nominatim, inside the disc: the search this page always made.
  NbxSearch.prototype.search = function (plan, disc) {
    var box = discBox(disc);
    var path = '/search?' + (plan.kind === 'name' ? 'q=' + encodeURIComponent(plan.q)
                                                  : 'street=' + encodeURIComponent(plan.street))
             + (box ? '&viewbox=' + encodeURIComponent(box) : '');
    return this.get(path).then(function (body) {
      var down = nbxDown(body);
      if (down) return down;
      var res = pickInDisc(body.hits, disc, plan, body.cutAt);
      // What the NucBox answered, beside what was chosen from it, for Map view
      // to draw — and the door asked for, so a street answered for a door is
      // drawn as what it is (located).
      res.seen = { hits: pointsAmong(body.hits), door: plan.door ? plan.house : null };
      return res;
    });
  };

  /* Road metres along points [{lat, lon}, ...] and how far OSRM moved each
     point to reach a road ({ metres, snaps }), or { why } — never minutes:
     server.js drops OSRM's duration before it reaches a page. */
  NbxSearch.prototype.road = function (points) {
    var path = '/route?points=' + points.map(function (p) {
      return Number(p.lon).toFixed(5) + ',' + Number(p.lat).toFixed(5);
    }).join(';');
    return this.get(path).then(function (body) {
      if (body.unreachable) return { why: 'unreachable', error: body.unreachable };
      if (body.refused) return { why: 'refused', error: body.refused };
      if (body.noRoute) return { why: 'noroute', error: body.error };
      return { metres: body.metres, snaps: body.snaps };
    });
  };

  var METRES_PER_MILE = 1609.344;

  /* How far OSRM may move a point to reach a road before the road figure is
     not about that point: a fifth of a mile, AGREE_MI — the distance within
     which this file already calls two answers one place. A pin moved farther
     than that is routed from somewhere else (the far side of a mall, the
     motorway beside a field). Chosen, not measured, the same as AGREE_MI. */
  var SNAP_MI = AGREE_MI;

  /* How far below zero the road detour may come before it is not believed.
     OSRM routes the FASTEST road, not the shortest, so car -> pickup -> end
     can come out shorter in miles than the car -> end it chose: the pickup
     pulled it onto a shorter, slower road, and "on your way" would hide a
     real detour (in time, which this panel may not state). A pickup on the
     very road OSRM chose direct gives the same metres both ways, so the only
     slack needed is the panel's own rounding: anything above -0.05 mi is
     "0.0" to one decimal, which is what the figure is written to. */
  var ROAD_SAME_MI = 0.05;

  /* The detour by road: car -> pickup -> where the order in the car is
     going, less car -> that end. The same three points and the same
     subtraction as detour() above, and nothing else: no minutes (a distance
     turned into time is a pace — Settled), and never a route through where
     the new job ends (Settled). Resolves { miles } or { why }:
       'snap'        a point was moved more than SNAP_MI to reach a road
       'otherroads'  the figure came out below -ROAD_SAME_MI (see above)
     besides the road's own unreachable / refused / noroute. */
  NbxSearch.prototype.detour = function (from, via, to) {
    if (!from || !via || !to) return Promise.resolve({ why: 'missing' });
    var self = this;
    return this.road([from, via, to]).then(function (by) {
      if (by.why) return by;
      return self.road([from, to]).then(function (direct) {
        if (direct.why) return direct;
        // Five snaps, one per point asked; server.js answers no route
        // without them, so a short list is a server from before this.
        var snaps = (by.snaps || []).concat(direct.snaps || []);
        if (snaps.length !== 5) {
          return { why: 'unreachable', error: 'the router did not say how far it moved each point' };
        }
        if (!(Math.max.apply(null, snaps) / METRES_PER_MILE <= SNAP_MI)) return { why: 'snap' };
        var miles = (by.metres - direct.metres) / METRES_PER_MILE;
        if (miles < -ROAD_SAME_MI) return { why: 'otherroads' };
        return { miles: miles };
      });
    });
  };

  /* Whether this rig's server has the NucBox set, as { search, route,
     streets }; all false when it says so, when it is a server from before
     this existed, or when it cannot be reached. Asked once per walk, at the
     press. */
  function nbxSettings(fetchFn) {
    var f = fetchFn || function (u) { return fetch(u); };
    return Promise.resolve().then(function () { return f('/api/nbx'); })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (b) {
        return { search: !!(b && b.search), route: !!(b && b.route),
                 streets: !!(b && b.streets) };
      }, function () { return { search: false, route: false, streets: false }; });
  }

  /* How map.html found one place, for its pin: `point` the answer, `how` the
   * walk's `asked` entry for it. map.html asks the PUBLIC geocoder for one
   * answer a place, inside a box round where the car was when the rows naming
   * it came up (boxAround, anchorFor) — never a card's disc, and there is no
   * candidate list behind its pin to draw. So what it can show of how a place
   * was found is that box, and whether the box found it:
   *
   *   { outside: false, line }  found inside its box, or asked with none
   *   { outside: true,  line }  the box found nothing, it was asked wide, and
   *                             the answer is outside the box — the case the
   *                             box exists to refuse, drawn ringed (map.html)
   *
   * The box is said as it was searched: boxAround widens BOX_MILES by half a
   * grid step and centres it on the grid point nearest the car, so "the 60
   * mi box" was not the box. Its size in miles is read off the box itself,
   * north–south and east–west (at its middle latitude).
   *
   * A box found nothing and the wide answer is inside it is possible (a
   * bounded search and an unbounded one rank differently) and is said as
   * asked wide, not as outside. Null for a place this walk did not ask. */
  function howFound(point, how) {
    if (!point || !how) return null;
    if (!how.box) {
      return { outside: false,
               line: 'asked with no box — no row naming it knows where the car was' };
    }
    var b = how.box.split(',').map(Number);   // left, top, right, bottom
    var ns = Math.abs(b[1] - b[3]) * 69.0;
    var ew = Math.abs(b[2] - b[0]) * 69.0 * Math.cos((b[1] + b[3]) / 2 * Math.PI / 180);
    var miles = 'box searched round where the car was, ' + Math.round(ns)
              + ' mi north–south by ' + Math.round(ew) + ' east–west';
    if (!how.wide) return { outside: false, line: 'found inside the ' + miles };
    var outside = !(point.lon >= Math.min(b[0], b[2]) && point.lon <= Math.max(b[0], b[2])
                    && point.lat >= Math.min(b[1], b[3]) && point.lat <= Math.max(b[1], b[3]));
    return { outside: outside,
             line: 'nothing inside the ' + miles + ', so asked without it'
                   + (outside ? ' — and found outside it' : '') };
  }

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

    // How each place was asked, kept for the drawing (howFound): the box it
    // was searched in and whether that box found nothing so it was asked
    // wide. What this walk already decided, and no question more.
    var asked = {};
    distinct.forEach(function (q) {
      asked[q] = { box: boxes[q], wide: refused.indexOf(q) >= 0 };
    });

    // Out of the offers that named BOTH ends, which are the only ones that
    // could ever be drawn end to end. Counting against everything that named
    // anywhere would fold "the card never said where this went" into the same
    // figure as "the geocoder got it wrong", and those are different problems
    // with different answers.
    var couldDraw = jobs.filter(function (o) { return o.pickup && o.dropoff; }).length;
    var drawn = placed.filter(function (p) {
      return p.from && p.to && !accused(p);
    }).length;
    return { placed: placed, strays: strays, found: found, distinct: distinct,
             asked: asked, couldDraw: couldDraw, drawn: drawn,
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
           detour: detour, fixOf: fixOf, fixRefused: fixRefused,
           cardFix: cardFix, fixLine: fixLine, cardYardstick: cardYardstick,
           againstCard: againstCard, cardRefuses: cardRefuses,
           SLACK_MI: SLACK_MI,
           hereDot: hereDot, GPS_REFUSED: GPS_REFUSED,
           anchorFor: anchorFor, boxAround: boxAround,
           localityOf: localityOf, townOf: townOf, townFor: townFor,
    townEndFor: townEndFor,
           straysAmong: straysAmong, farFrom: farFrom, placesIn: placesIn, jobsIn: jobsIn,
           judge: judge, statedBy: statedBy, unchecked: unchecked, ends: ends,
           rankLead: rankLead, standings: standings,
           accused: accused,
           byPlace: byPlace, chain: chain,
           Geocoder: Geocoder, placeAll: placeAll, needLeaflet: needLeaflet,
           BOX_MILES: BOX_MILES, ANCHOR_STEP: ANCHOR_STEP,
           FAR_MILES: FAR_MILES, GAP_MS: GAP_MS,
           searchPlan: searchPlan, searchText: searchText, discFor: discFor, discBox: discBox,
           pickInDisc: pickInDisc, nbxRefusal: nbxRefusal,
           clipToDisc: clipToDisc, stretchInDisc: stretchInDisc, nearestOn: nearestOn,
           stretchSpan: stretchSpan, spanRefusal: spanRefusal, ON_WAY_MI: ON_WAY_MI,
           SPAN_STEP_MI: SPAN_STEP_MI,
           NbxSearch: NbxSearch, nbxSettings: nbxSettings,
           AGREE_MI: AGREE_MI, STREET_AGREE_MI: STREET_AGREE_MI,
           NBX_GAP_MS: NBX_GAP_MS, SNAP_MI: SNAP_MI, ROAD_SAME_MI: ROAD_SAME_MI,
           hasDoor: hasDoor, discShape: discShape, located: located,
           howFound: howFound };
}));
