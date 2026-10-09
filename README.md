# Uber Scan

A one-screen calculator for ride offers. Type the pay and the time, get **$/hour**
before the offer times out.

Built as an installable web app (PWA): it goes on your home screen like a normal
app, opens instantly, and works with no signal.

## Using it

Three numbers, one thumb:

1. Type the **pay** — the app starts on that field.
2. Tap **NEXT**, type the **minutes**.
3. Tap **NEXT**, type the **miles** (optional — only affects $/mile and cost).

The big number and the color update on every keystroke, so you usually know the
answer before you finish typing:

| Color | Verdict | Meaning |
|---|---|---|
| 🟢 | ACCEPT | at or above your target $/hr |
| 🟠 | CLOSE CALL | within the near-miss band below target |
| 🔴 | PASS | below the band |

A fourth answer, on this keypad as well as on `scan.html` and `live.html`: where
the figures cannot be trusted as a rate, no number is shown at all — the
headline, $/mile, $/min and net pay all read `--` — and the verdict names the
figure to fix instead. Here that is the figure you just typed: **CHECK THE PAY**
(a payout no offer makes), **CHECK THE TIME** (a duration no offer states),
**CHECK THE DISTANCE** (more miles than those minutes can drive) or **CHECK PAY
AND TIME** (the two together are a rate no offer pays — $11.84 typed as $118.40
over 20 minutes is $355/hr). The two camera screens can say two more that
typing cannot: **CHECK THE TIME** on a card whose second leg the camera could
not time, and **NOT AN OFFER** on a screen that is not an offer at all — a
route planner or an idle screen with a payout on it — where there is no figure
to check.

Other keys: **⌫** deletes (and on an empty field jumps back to the previous one),
**CLR** resets, **LOG** saves the offer to history — except an entry showing one
of those four, which it refuses and tells you which figure to fix first.

If haptics are on, each key gives a short buzz and the verdict gives a distinct
one — a double-tap buzz for green, a long buzz for red — so you can feel the
answer without staring at the screen.

## When Uber takes the screen

Uber's offer card is a *system overlay* — it uses the "Display over other apps"
permission, so it can appear on top of whatever you are doing, including this app.
Three things help, in order of how well they work:

**1. Split screen (best, nothing to install).** Open Uber Driver, then Recent Apps,
tap the Uber icon at the top of its card, choose *Split screen*, and pick Uber Scan
for the other half. Put Uber on top and the calculator underneath. Both are live at
once, so you read the offer and type without either app going away. Worth setting up
once at the start of a shift.

**2. Nothing you type is lost.** Every keystroke is saved immediately. If Uber does
take the screen mid-entry, reopening Uber Scan brings your digits back exactly where
they were, with the same field selected. Drafts older than 3 minutes are dropped, so
you never come back to a stale offer's numbers.

**3. Turning off Uber's overlay permission** (Settings → Apps → Uber Driver →
Display over other apps) stops it from covering other apps entirely — but drivers
report Uber demanding that permission before it will let you go online, so this one
may cost you more than it gains. Try split screen first.

## Targets (⚙︎)

| Setting | What it does |
|---|---|
| Target $/hour | The green line. Default $25 — but see **where to draw the line** on the offers page, which works out from your own offers what that line is costing you. |
| Near-miss band | How far below target still counts as amber. Default 15%. |
| Cost per mile | Gas and wear, subtracted from the offer before the rate is figured. Set it to `0` to see gross pay; the 2025 IRS rate is `0.70`. Served by the rig, this is the rig's figure too: the box shows what the rig is costing a mile at, a change is sent to it when you leave the box, and the line under the box says whether it took. |
| Pickup padding | Minutes added to every offer, since the quoted time usually ignores the drive to the rider. |
| Haptics | Buzz on each key. |

There is no account and no tracking. History is kept in the browser. The
settings are too, and change this keypad, not the rig's panel — except cost
per mile, which, served by the rig, is the rig's own figure as described above.
The one thing it talks to is the rig: served by the rig's own server,
**LOG** also hands the offer to the rig's journal so the offers page can count
it, and says so in the history when that did not get through. Served from
anywhere else (GitHub Pages, a file), it asks once whether a rig is there,
hears nothing, and keeps the offer on the phone until one answers.

The phone holds the most recent 1,000 of those — about six days of heavy
scanning with no rig ever reachable, and roughly a third of what a browser
gives one site. Past that the oldest come off, and the scanner's status line
says how many and back to when. It says so too when the browser will not store
a row at all, which is a setting rather than a full disk and happens on the
first offer rather than the thousandth.

## The math

```
minutes = entered minutes + pickup padding
net     = pay - (miles x cost per mile)

$/hour  = net / (minutes / 60)
$/min   = net / minutes
$/mile  = net / miles
```

The driving panel is the one exception, and deliberately: its `$/mi` is
`pay / miles`, because it sits in a row whose job is to match the card on the
phone, between the two boxes that divide to it. The working line under the
headline shows the deduction, so nothing is hidden by it.

## Installing on a phone

The app needs to be served over HTTPS to install. The quickest route is GitHub
Pages:

1. In this repo: **Settings → Pages**.
2. Under **Source**, pick **Deploy from a branch**, choose this branch and the
   `/ (root)` folder, then **Save**.
3. Wait a minute, then open `https://<your-username>.github.io/Uber_Scan/` on your
   phone.

Then add it to your home screen:

- **iPhone (Safari):** Share button → *Add to Home Screen*. Must be Safari;
  Chrome on iOS cannot install it.
- **Android (Chrome):** the *Install app* prompt, or ⋮ → *Add to Home screen*.

Launched from the home screen it runs full screen with no browser chrome, and it
works in a parking garage with no bars.

## Running it on a server

```sh
npm start          # or: node server.js
```

Then open `http://localhost:8080`. `PORT=3000 npm start` to move it. There are
no dependencies to install — `server.js` is plain Node with a zero-install
static file server, and it is what `package.json` points `main` and `start` at.

The home-screen install needs HTTPS, because browsers gate service workers
behind a secure context. From the project directory:

```sh
npm run cert       # writes ./ssl, then restart the server
```

The certificate is found on disk rather than configured, so this works even when
a process manager is the one running `npm start` and there is no shell to set an
environment variable in. https then serves on 8443 *alongside* http on 8080 —
nothing pointing at the old address breaks — and startup prints the URL to open
on the phone.

Accepting the browser's warning is enough for the camera but **not** for the
offline install; for that, install `ssl/ca.pem` on the phone.
[SCANNING.md](SCANNING.md) has the details and the per-platform steps.

On a Raspberry Pi with a camera, `npm start` also runs the rig's autopilot —
which aims, calibrates and then reads offers — wherever `rpi/autopilot.py`
exists, serving the live verdict at `/live.html` and its state at
`/api/status`. See [rpi/README.md](rpi/README.md). On any other machine, the
copy at home included, set `SCANNER=0` so it does not try.

**If your host tried to run `ui.js` (or the old `app.js`) with Node and died on
`ReferenceError: document is not defined`**, that is the symptom of this project
being executed rather than served. Everything in it except `server.js` is
browser code, and Node has no `document`. Point the host at `server.js`, or let
it read `package.json`, and it will serve instead.

## Files

| Path | |
|---|---|
| `index.html` | Layout |
| `styles.css` | Styling |
| `ui.js` | All of the app logic — browser only, never run under Node |
| `journal-client.js` | Hands an offer typed here, or read by the phone's scanner, to the rig's journal when there is one to answer |
| `server.js` | Zero-dependency static server; the Node entry point |
| `journal.html` | Every offer the scanner kept, and what it adds up to |
| `map.html` | Puts a whole range of places on a map, to check whether the rig is right about where the work happened — one pin per place, with the pins that landed in another state drawn in red and listed rather than allowed to set the view, and a toggle for the positions the rig's own GPS recorded. Needs a network; asks nothing until you press the button |
| `map-view.js` | The deciding behind both maps with no map in it — the geocoder, its one-request-a-second rule, the box drawn around where the car was, and the test for a pin that cannot be in this shift. Runs under Node, which is what lets the rate limit be checked against a fake clock |
| `live.html` | The driving screen: the rig's verdict, the phone as the camera sees it, and the controls used while moving |
| `snaps.html` | Every **📷 Snap** the rig has kept, newest first, with a link to open or save each file. The control is on the driving screen, in the row with the connection dot; one press keeps a screenshot of the rig's own display, the camera's last picture with its age, and what `/api/status` said, and says which of those it could not keep and why. **⤓ one file** saves a snap as a single `.html` to share — the pictures inside it, the records as text and as the files themselves, nothing it needs a network for; tick several, or take one **with the newer** ones (the series it starts), and they are one file, oldest first. A snap can carry a short note ("trip planner"), typed here so the press on the driving screen stays one click. Linked from the offers page. See [rpi/README.md](rpi/README.md) for the screenshot tool it needs |
| `scan.html`, `scan.js`, `scan.css` | The phone's own scanner — a photo of the offer card, read on the phone; see [SCANNING.md](SCANNING.md) |
| `offer-parser.js` | Turns the text off a card into pay, minutes and miles — one corpus, shared with the Pi's port |
| `vendor/` | The OCR engine the phone's scanner runs, kept here so the page works with no signal |
| `advice.js` | What target the offers themselves argue for — shared, and tested on its own |
| `sw.js` | Offline cache — stale-while-revalidate, so a changed file is picked up on the next open. `SHELL` is a convenience to bump when a page changes; `BLOB` is the OCR engine, bumped only when that changes |
| `manifest.webmanifest` | Home-screen install metadata |
| `tools/make_icons.py` | Regenerates the icons in `icons/` |
| `tools/make-cert.sh` | `npm run cert` — local certificate authority for https |
| `tools/install-sync.sh` | Puts the rig's journal on a timer to the machine at home; see the rig's README |
| [`AUDITS.md`](AUDITS.md) | What has already been looked at: what was fixed, what is known and still open, and — the point of the file — proposals that were checked against the code and found to be wrong, so the same ground is not dug twice. Read it before starting anything that sounds like an improvement |

## Looking at a shift afterwards

The verdict on screen answers one question and then it is gone. The questions
that need a season of offers behind them cannot be answered that way: what a
typical offer round here actually pays, whether Saturday evening is worth more
than Tuesday lunchtime, whether shop orders earn their shopping time, and
whether the target you set is the right line to be drawing.

So the Pi scanner keeps one line per offer it was confident about, in
`rpi/journal.jsonl`. **Offers ▤** in the live view opens the page that reads it:

* the **middle of the distribution in $/hr** — a quarter of offers below, the
  typical one, a quarter above. Every figure on the page is a rate, never the
  payout on the card: the total flatters a long job and punishes a short one,
  which is the whole reason this rig exists. Percentiles rather than an average, because $/hour is a
  ratio with a small noisy denominator and one misread leg produces exactly the
  long tail an average cannot survive.
* what share of offers your target would have had you take.
* **where to draw the line.** A target is not a wage — it is a decision about how
  long to wait, and setting it too high fails silently, because a screen full of
  PASS looks like discipline. This works out from your own journal what each
  candidate line would actually have earned, once the waiting between offers is
  counted, and says what your current target is costing. It shows its working, it
  leans deliberately low, and it says nothing at all until there is enough behind
  it to be worth acting on.
* **by time of day**, in three-hour blocks, each bar drawn on the same scale so
  the halfway mark is always your target.
* **rides against shop orders**.
* **every offer**, grouped by day, with the day's count, median and total
  offered. Tap one and it opens to the whole record: what was on the card, what
  the rate was divided by and why it differs from the card's own minutes, what
  came off for the car, the verdict and the target it was judged against, and
  how the reading was made — which is what you need to hold an offer up against
  what the shift actually paid.
* readings the scanner was not sure of are **in that list too**, greyed and
  tagged, with the reason on each. They are left out of the figures above, but
  an offer missing from the record with nothing saying why is exactly what makes
  a record impossible to check.
* **the destination you revealed on your phone, on the row.** An offer card
  often prints “Customer dropoff” and no address, so where the job ends is
  unknown at the moment it matters most. Tap the dropoff on your phone and
  press **⌖ Dropoff** on the driving screen while the card is up, and the
  address goes on that offer's row — labelled as read off the phone rather
  than printed on the card, because the two are different kinds of evidence.
  It is also what puts the job on the map.
* **the stops on Uber's Trip Planner.** Press **⌖ Dropoff** with the planner
  up on the phone and the driving screen lists its stops in order, one line
  each — `▸ Dropoff by 4:18 · Pat Q. · 4821 Kestrel Dr, Marietta` — between
  offers, until you press again, the order is put down or the next offer is
  recorded, which is when a read destination goes too; a panel reloaded in
  between shows the same. A notice on the card (the journal not saving, the
  phone too bright) comes first: the stops give way to it a line at a time and
  say how many they are. The planner prints no ZIP, so it is read by its own
  layout (the stop header, the name, “Expected by”, and the street and town
  under “Address”), and only when you press. When the trip has exactly one
  dropoff — one on the screen, and both ends of the list in view: the title
  over the first stop and “Waybill” under the last — and its street and town
  read, that address becomes the order in the car's destination as any other
  read one does. Otherwise the rig does not guess: it says why under the stops
  (two dropoffs, the list cut off, the address unread) and leaves the order's
  destination as it was, and ⌖ over the navigation screen reads it as before.
  Each planner is also written to the journal as a row of its own, for the
  record only — nothing on the offers page reads it, and not at all with
  `"keepPlaces": false`. The stops are not put on the map; only the one
  dropoff it files is, as any read destination is.
* **tick the ones you took.** The scanner cannot see the Accept button and never
  touches it, so it cannot know — but you can tell it, and once you do the page
  shows what you actually worked against what you were offered, per day and
  overall.
* **close the shift.** One line at the top of the list — *Close the shift · Sun,
  Sep 20 — 1 ticked, 0 passed, 6 still unlabelled · 185 more on 4 other days*
  — that opens into the newest day's ACCEPT and CLOSE CALL cards nobody has
  answered for, newest first, each with **Took** and **Passed**. A card you
  passed on and never marked looks exactly like a job you took and never
  ticked, so the advice further down has to allow for every mix of them; each
  card answered here is one fewer. Press an answer again to take it back. The
  day is the list's own day, starting at 4am, and a night that runs past 4am
  is two of them: on that week Saturday ran to 4:43am, so the newest day is
  its last 29 offers. Two buttons under the line step to the day before or
  after, each naming that day and how many it still has unlabelled (*‹ Sat,
  Sep 19 · 86 unlabelled*), and the section stays on the day you stepped to
  while you answer. "Ticked" is the same count as the ✓ on that day's header
  in the list, a PASS card you took included.
* **hide the ones that were not offers.** The test card you present to check the
  rig still works is not a job you were given, and left in it drags every median
  toward whatever that card says. Hide one, or hide *every* reading of that card
  — now and in future — so checking the rig costs nothing.
* **see where one went, without leaving the list.** The map controls on a row
  open a sheet over the bottom of this page rather than a new tab, so three
  offers checked is three taps and not three tabs with the log lost behind
  them. Green is the pickup, amber the dropoff, and the caption measures the
  straight line between them against the distance the READING carries — and
  says whose figure that is, because on nearly half of these a decimal had to
  be put back while the card was read and the number is not the one on the
  screen. A straight line cannot beat the road, so a longer one means a pin is
  in the wrong place — but only where the reading vouches for the distance. A
  reading the rig would not finish or would not trust is no yardstick, and
  those pairs are reported as unchecked rather than accused. Driving time with real traffic is the one thing a pin cannot
  give, and the link to it is inside the sheet.

  Nothing is looked up until you press one of those controls. Some of these
  places are where customers live, and the rig never sends any of them
  anywhere by itself; the lookup happens in your browser, when you ask. Nor
  does anything that comes back change a figure on the page: every number here
  is still the one the card printed. A pin is for looking at, and what it is
  good for is being visibly in the wrong state.

If a line in that file is ever unreadable — a power cut mid-write, or a card
going bad — the offers page says so and says plainly that those offers cannot be
got back, and `rpi/doctor.py` fails on more than one with the instruction to
copy the journal off the card now. One is what a power cut costs; a number that
grows is the card.

Nothing is ever deleted. Ticking and hiding are appended as their own lines, the
same way the offers are, so a mis-tap on a phone in a moving car costs an entry
in a list rather than a row of data that took a shift to collect. Hidden offers
are out of every figure and every export; **show hidden offers** at the foot of
the list brings them back, and an **Undo** bar follows every tick, every answer
and every hide for a minute, for the mis-tap. Undo puts back exactly what was
there, which for a card nobody had answered for is no answer at all — not a
pass.
* a **CSV** of everything, for a spreadsheet.

Two things it is careful about:

* **it is a record of offers, not of trips.** The scanner cannot see the Accept
  button and never touches it, so nothing it writes knows which offers you took.
  What you ticked or marked passed yourself is kept separately, as its own line
  naming the offer and which screen it was pressed on — the driving screen, the
  offers list, or Close the shift — and is the only thing here that claims to
  know.
* **it stores where an offer went, and you can turn that off.** The merchant
  behind a "Pickup" label and the address printed after a leg are kept, because
  an offer read months ago is otherwise a row of figures that cannot be matched
  to any job you remember — and checking the record is the point of having one.
  Only what the card itself printed, never free text off the map behind it. They
  are in `/api/journal` and in the CSV.

  Uber writes that pair two ways. Sometimes the merchant has its branch in
  brackets and the destination follows, and the closing bracket is the seam.
  Sometimes there is nothing between them but a map-pin icon, which the camera
  reads as `7`, `9`, `©` or nothing at all — and on those the reader splits at
  the junction instead, because the destination is `<street> & <street>` and
  the merchant is not. Where there are two junctions and no bracket it stores
  neither half rather than guess which ampersand is the seam: a card with no
  destination is a gap, and a card claiming the job ended at the restaurant it
  started from is a wrong answer.

  It is a real trade: this is a record of where you were and when, it lives on a
  card in a vehicle, and it is copied to the machine at home. `"keepPlaces":
  false` alongside the other settings in `rpi/config.json` turns it off and
  changes nothing else, and the Trip Planner's stops follow it too. A
  destination read off the phone is still written on the `mark` and `pair`
  rows server.js writes whatever it says — the server does not read that
  setting — and that is open. `--no-journal` keeps no record at all. Either way
  `rpi/journal.jsonl` is gitignored and, like everything under `rpi/`, the
  server refuses to serve the file itself.

## What the server will not serve

`server.js` sits on a LAN, on plain http, with no authentication — every file
under the project root is one GET away from anyone on the same wifi. That is
fine for a page of HTML and was not fine for `ssl/`, which holds the **private
key of the certificate authority** `make-cert.sh` asks you to install on your
phone as a trust anchor. Anyone who fetched it could mint a certificate your
phone would believe, for any site. It was served with a 200.

`ssl/`, `rpi/`, `node_modules/`, dotfiles and anything ending `.pem`/`.key`/
`.crt` are now refused outright, and paths are re-checked after following
symlinks rather than only being resolved lexically — resolving a path proves
nothing about where a link inside the root actually points.

If you ran an earlier version on an untrusted network, regenerate the CA
(`rm -rf ssl && npm run cert`) and re-install the new one on the phone.

## Notes

Uber's quoted trip time is the *driving* time. Whether you count the pickup drive
matters more than almost anything else in this calculation — a $9 offer that is
"12 minutes" is often 20 minutes door to door, which is $27/hr on paper and
$16/hr in reality. Pickup padding exists for that; set it to your honest average.
