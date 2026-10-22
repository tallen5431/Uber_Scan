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
`/api/status`. **On your phone over the VPN, `http://<rig>:8080/live.html?route`**
(⤳ Route on the keypad and the offers page) is that screen's Map view alone and
read-only: the order in the car along the road, the live car dot, and the offer
on the panel in teal with its pay, minutes, miles and the pair line above the
map, so you can see while waiting at a restaurant whether a new order fits along
the route. It writes nothing; mark offers on the offers page. **Beside its
▤ Offers, ◷ Shift opens `http://<rig>:8080/shift.html`**, today's shift so far
as the end-of-shift report has it (also linked near the top of the offers
page): the totals (rig on and off, left and back at start, miles, minutes
moving and stopped, the stops and gaps), each order's card against what it
really took and how it ended, and the Pinning section — read-only, upright on
the phone, no address and no coordinate, off `GET /api/shift` (which runs
`tools/shift_report.py --json`, kept 30 s). And a **Drop** pressed by mistake
can be taken back: for ten seconds the same button reads **↶ Undo** (on the
offers page, the In car line's Drop does the same), and a press puts the order
back exactly as it was. See
[rpi/README.md](rpi/README.md). On any other machine, the
copy at home included, set `SCANNER=0` so it does not try.

**If your host tried to run `ui.js` (or the old `app.js`) with Node and died on
`ReferenceError: document is not defined`**, that is the symptom of this project
being executed rather than served. Everything in it except `server.js` is
browser code, and Node has no `document`. Point the host at `server.js`, or let
it read `package.json`, and it will serve instead.

## The NucBox at home: a map search, a road router and a street index

The NucBox that keeps the copy of the journal also runs the map services the
driving panel's **Map view** can use instead of the public ones: its own
Nominatim (place search) and its own OSRM (road routing), both built from the
Georgia extract of OpenStreetMap, and a **street index** made from the same
file and answered by the NucBox's own `server.js` (where two streets meet, and
the stretch of one). The rig reaches them over Tailscale; the browser never
does — `server.js` relays a few narrow questions to them and nothing else.

### What was run on the NucBox

OSRM, car profile, multi-level Dijkstra, port 5000, from the directory holding
the Georgia `.osm.pbf` (Geofabrik names it `georgia-latest.osm.pbf`; use the
name of the file you have):

```sh
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/georgia-latest.osm.pbf
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/georgia-latest.osrm
docker run -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/georgia-latest.osrm
docker run -t -i -p 5000:5000 -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/georgia-latest.osrm
```

Nominatim 4.5, image `mediagis/nominatim:4.5`, `PBF_PATH` pointing at the
extract, `THREADS=4`, its database in the named volume `nominatim-data`,
served on port 8088. It gets **its own copy of the `.pbf` in `~/nominatim`**,
because the image chowns what is mounted at `/nominatim` and doing that to the
directory OSRM reads from is a surprise nobody wants. `--shm-size=1g` is in the
command the driver ran, as in the image README's examples: PostgreSQL inside
the container works in shared memory, and Docker gives a container 64 MB of
it unless told otherwise. The container-side paths below are the image's own README's for 4.5,
not something this repo measured:

```sh
mkdir -p ~/nominatim && cp georgia-latest.osm.pbf ~/nominatim/
docker run -it --shm-size=1g -e PBF_PATH=/nominatim/data/georgia-latest.osm.pbf -e THREADS=4 \
  -v nominatim-data:/var/lib/postgresql/16/main -v ~/nominatim:/nominatim/data \
  -p 8088:8080 --name nominatim mediagis/nominatim:4.5
```

**TIGER (US house numbers) was not imported.** The setting name that turns it
on for this image was not found, and the import ran without it. House numbers
in Cobb County are there anyway, from OSM itself (below); elsewhere a street
may have none.

### What the real install answered

Measured against the driver's NucBox, over its Tailscale address (written
`100.x.y.z` here and below — use your own):

| Asked | Answered |
|---|---|
| route Marietta Square (-84.5499,33.9526) → Five Points (-84.3880,33.7490) | 31307.4 m (19.5 road mi); OSRM's 1659.8 s is free-flow and is never used |
| `q=McDonald's`, `viewbox=-84.65,34.04,-84.45,33.87`, `bounded=1`, `limit=10` | 10 branches, all inside the box, each with a house number and street ("McDonald's, 2700, Windy Hill Road Southeast, Cumberland, Marietta, Cobb County, 30067") |
| `q=Shadowood Pkwy SE, Atlanta, GA` | nothing |
| `street=Shadowood Parkway Southeast` in a bounded box, no town | 2, in Cumberland, Cobb County |
| `street=1985 Cobb Parkway` in a bounded box | 3, at "1985, Cobb Parkway, Kennesaw" |
| `q=Dave's Hot Chicken` | nothing — it is not in OSM |
| Cobb Parkway NW | one point for the whole street |

So: Uber's abbreviations (Pkwy, SE) are fine, and Uber's **town is the postal
town**, which often is not OSM's (Atlanta against Cumberland; Marietta against
Kennesaw for 1985 Cobb Parkway). A place is therefore searched **inside an
area and never by its town**, and the town is not used to choose among what
comes back either: as a tie-break it pinned a namesake 1.35 mi from the right
street because its OSM address said the card's postal town. And because a
street comes back as one point, "the stretch of a street inside the circle"
and cross streets ("A & B, Town") are not answerable this way — they are the
street index's (below). Without it the panel says "no pin for … — no street
index to ask" rather than pinning one of the two.

### The street index

Uber prints most dropoffs as a corner — 403 of the week's 1,166, 390 different
ones ("Foothill Trl & Northwoods Dr, Marietta") — to keep the customer's
address off the card. Where two streets meet is a question about the street
graph, which is in the Georgia file, so it is answered from that: once, on the
NucBox, `tools/street_index.py` keeps every **named** way a car is driven on
(motorway down to residential and living_street, the `_link`s, and named
`service` drives — an apartment complex's or a shopping centre's own drive,
where dropoffs often are; never a footway, path, track or building) inside the
driver's metro, `-85.00,33.50,-83.95,34.40` (every town the week's cards name,
Cartersville and White to Suwanee, Lithonia and Union City, with a margin),
and writes one JSON file. `osmium-tool` cuts the file (apt, 1.16.0 on Ubuntu
24.04); the rest is Python's standard library. Run from the repo on the
NucBox:

```sh
sudo apt install osmium-tool
python3 tools/street_index.py ~/osrm/georgia-latest.osm.pbf ~/streets.json
```

It prints what it kept and dropped, how long osmium and the index took, and
the file's size; `--bbox W,S,E,N` takes another area. Then the NucBox's own
server loads it at start:

```sh
NUCBOX_STREETS_FILE=~/streets.json npm start      # on the NucBox
```

(under systemd, an `Environment=NUCBOX_STREETS_FILE=` line with the full
path — systemd does not expand `~`) and prints "Street index: N names, W
ways, M nodes from …, loaded in X ms,
heap Y MB" — the real figures, which nobody has yet read off the NucBox.
`curl localhost:8080/api/streets` says the same. A file that is set and cannot
be read is said at start and on every question, never as "no such street".

What it answers, `GET /api/streets/cross?a=&b=&box=`,
`/api/streets/stretch?name=&box=`, `/api/streets/named?name=&box=` and
`/api/streets/whole?name=&box=` (box `left,top,right,bottom`, optional but for
`named` and `whole`):

* **Where two streets meet** — ways that share a node meet there, and ways
  that cross without one (a bridge) where their segments cross. Points within
  100 m of each other are one meeting, so a road across a dual carriageway is
  one corner, not two, and each meeting says how far its points spread: two
  names carried by one road meet along all of it.
* **A street's stretch** — the polylines of its ways inside the box, cut at
  the box's edge, at most 8000 points (or none, said as cut).
* **Names** are matched in four steps, the first that finds anything winning:
  exactly, after case, punctuation and the USPS abbreviations both ways
  (Trl/Trail, Pkwy/Parkway, NW/Northwest …); with a directional on one side
  only (two names each with one the other lacks never match, wherever they
  stand — in Atlanta NW and SE are different streets, and "Main St NW" is not
  "S Main St"; one on one side only is the rule's own risk: 18 of its 112
  pairs on the week's card names put a leading N, S, E or W against none, West
  Barrett Pkwy against Barrett Pkwy, which can be another street, and only
  the disc then tells them apart); the same after dropping the OCR's litter — one- and two-letter
  tokens after the street's type printed short ("Ct re ou NW"), never a word
  before the type, which is the name ("Ol Canton Rd" is not Canton Road), and
  never a digit; and with one letter misread in one word — only i for l
  or l for i ("Tri" for Trl, "PI" for Pl, "Biue" for Blue), which is 177 of
  the 190 one-letter-for-another differences between two frames of one card
  on the week's address lines, while any letter for any letter matched Beach
  St (Acworth) to Beech St (Marietta), both on the cards; never in a word under
  four letters unless it is a street word; only among the names inside the
  card's disc; and only when no rule before it found the name anywhere. So
  12th St NW and 17th St NW, and Parliament Ct and Parliament St, all on the
  cards, stay apart. A type the reader misreads the same way in every frame
  is refused: "Cedar Ridge Or" (for Dr) is on the cards and finds nothing.
  Each of the week's 722 cross-street
  halves, asked of an index holding every other half, matched another in 29
  cases: 28 the same street by reading, and bare "Peachtree St", which
  matched both Peachtree St NE and Peachtree St SW — two streets, and where
  each meets the other name is what decides between them. The card's town is
  never sent and never used.
* **The one street a name as read is** (`named`, asked only inside a card's
  box) — for a held order's door the NucBox's search found nothing for: the
  names above, counted among the streets inside the box, and then a read that
  lost the street's type and cut its last word short ("…r" for "…ns Ln", at
  least four letters before the cut read right). A street only when exactly
  one inside the box fits; two are none. The rig asks it (relayed as
  `/api/nbx/named`) and then the door by that street's own name. **The
  NucBox's copy of server.js answers this, so the NucBox needs a `git pull`
  and a restart before the rig can ask it.**
* **Every street of a name reaching into the box, whole** (`whole`, asked
  only inside a card's box) — each street's ways joined where they share a
  node, its whole length in metres (not cut at the box), and its polylines up
  to 2 km. The rig asks it when a held order's door is a house the NucBox's
  search does not hold on a street it does ('no house number') and no place
  was found: exactly one such street touching the card's disc, 600 m long at
  most, arms the GPS drop on the street ("● armed by street"). **The NucBox
  needs a `git pull` and a restart before the rig can ask this one too.**

Measured: the suite's synthetic streets load in 1 ms. The real metro's size
is **not known** here, and every figure that follows is for a synthetic grid
of an **estimated** size — an estimate of about 84,000 named ways and 800,000
nodes (itself from an estimate of roughly 21,000 road miles at a node every
40 m), not a count. A grid that size took the exporter 3.8 s (OPL to index)
at 286 MB, made a 10.5 MB file, and loaded in 0.6 s at a 139 MB heap (243 MB
resident); three times that estimate took 12.4 s at 809 MB, 31.8 MB, and 1.8
s at 401 MB heap (543 MB resident) — all in the container this was written
in, not on the NucBox. The osmium steps on the real 341 MB file were not
measured; the exporter and the server print the real figures when run.

### Setting it on the rig

Three settings in the server's environment, beside `PORT` and `JOURNAL`,
empty by default — and **empty is exactly the old behaviour**: the panel asks
the server whether any is set, hears no, and searches the public geocoder at
one a second as it always has.

```sh
NUCBOX_SEARCH=http://100.x.y.z:8088 NUCBOX_ROUTER=http://100.x.y.z:5000 \
  NUCBOX_STREETS=http://100.x.y.z:8080 npm start
```

`NUCBOX_STREETS` is the NucBox's own `server.js` (its `PORT`), the one with
`NUCBOX_STREETS_FILE` set. **It is asked only alongside `NUCBOX_SEARCH`**:
the panel asks the street index from inside its NucBox search, so with
`NUCBOX_SEARCH` empty every place — corners and streets too — goes to the
public geocoder as before, and `NUCBOX_STREETS` alone does nothing. Under
systemd they are more `Environment=` lines in the unit (`sudo systemctl
edit uberscan`, then under `[Service]`); on the owner's rig they go on the
line in `Start.sh` that starts the server. The server prints all three at
startup when any is set, and `curl
localhost:8080/api/nbx` says which it has. On the NucBox itself the same
settings point at `http://127.0.0.1:8088`, `:5000` and its own port.
`NUCBOX_TIMEOUT_MS` (3000) is how long
the server waits for any of them before saying the NucBox did not answer — the
whole question, connecting included, so a NucBox whose address routes
nowhere is given up on in that time too. Before that was so, a listener
that never accepted held the server 5 s on Node 22 and was still being waited
on at 15 s with an HTTP agent of Node 18's kind.

### What the panel does with them

Only after **⛶ Map**, the same press that is the consent to look places up at
all:

* **Search.** Each place is searched inside its card's **disc** — where the
  car was when that card came up (its GPS fix), out to the card's own
  distance plus half a mile — for up to ten candidates. A pin is used only if
  exactly one candidate is inside the disc, or every one inside is the same
  place, and only from a list that did not stop at ten: a cut list cannot
  show there is only one ("no pin for Starbucks — too many to be sure · the
  NucBox lists 10 at most"). A merchant is searched by name; a bracketed door
  ("Jimmy John's (1985 Cobb Parkway NW)") by that street address; "Street,
  Town" and the Trip Planner's door line by the street. The town is never
  sent and never used. An address with a house number is pinned only where
  the answer carries that number — asked for a door it does not hold,
  Nominatim answers the street ("no pin for 4821 Kestrel Dr — street found,
  not that door"). Every refusal is said under the map, refusal first: "no
  pin for McDonald's — 2 fit the card and disagree · within 9.4 mi of you",
  "...none fit the card · within 0.6 mi of you, nearest 1.2 mi". A card with
  no yardstick is searched within sixty miles, one with no fix across
  Georgia, under the same rules.
* **Road.** "+N mi out of your way" becomes **"+N road mi out of your way"**:
  the road from the car by the new pickup to where the order in the car is
  going, less the road from the car straight there. Never minutes — OSRM's
  durations have no traffic in them and the server drops them before a page
  can see them — and never a route through where the new job ends. Every
  refusal the straight line makes still stands; the router is asked only
  where the straight figure would have been printed. Two road figures are not
  printed, and the straight line stands with the reason: one below zero by
  more than the 0.05 mi the figure rounds away (OSRM routes the fastest road,
  not the shortest, so going by the pickup can come out shorter than the
  road it chose direct — "· router took different roads"), and one where
  OSRM had to move a point more than 0.2 mi to reach a road ("· a pin over
  0.2 mi off road").
* **The order in the car's restaurant.** While its Trip Planner still lists
  a pickup, the figure is measured against the run the car is committed to —
  the car, that restaurant, then the order's end — with the new pickup put
  before the restaurant or after it, whichever adds less, less the run
  without it; in road miles or straight lines alike, and the line says so in
  place of "out of your way": "+1.2 road mi incl. restaurant", "on your way
  by road incl. restaurant". Asked of the router gap by gap, two or three
  points a question. A restaurant with no pin, a pin its card refuses, or one
  that is a street with no number is said, never measured past: a figure to
  the end alone is the one that left the restaurant out. This card's own
  job, pickup to dropoff, is drawn along the road too; no figure comes of it.
* **Corners and streets, with the street index set.** A corner the card
  prints is asked as its two streets inside the card's disc, and pinned where
  they meet when one meeting is inside it, or every one inside is the same
  place (a fifth of a mile, as for any candidates). Otherwise it is refused,
  refusal first: "no pin for Juniper Cir… — 2 corners fit the card · within
  3 mi of you", "...none fit the card", "...its streets run together"
  (two names carried by one road), "...a street name not on the NucBox",
  "...not two street names". A corner is read as one only from the part
  before the card's comma: the 63 of the week's 403 corner dropoffs that
  came off the card with no comma (the reader lost it, and a town or the
  OCR's litter often runs on after the second street: "...& Maple Dr NE
  Atlanta ll O Gok") are asked of Nominatim as a name, as before — the
  NucBox's inside the card's disc — and never of the street index. A
  street with no number is its stretch inside the disc — refused as "2 fit
  the card and disagree" when it is two streets of one name more than a
  mile apart — and its pin goes at the point
  of the stretch nearest the car, as a mark only: the card names the street,
  not where on it, so **no figure is measured to that point**. The figure
  is the straight line's at every point of the stretch, and it is stated
  only when that is one answer: "this pickup is on your way" when it is
  under half a mile everywhere, or the range when it is past half a mile
  everywhere and less than half a mile from least to most ("+3.7–4.2 mi out
  of your way — straight lines, not roads · whole street, no road figure").
  Otherwise it is refused, with how long the street runs there: "no figure
  for Northgate… — the street runs 1.4 mi in its card". Measured to the
  point nearest the car, a street running 8 mi past the car showed a true
  +1.5 as +0.6 and a true +0.4 as +5.1. The router is not asked: it
  measures one point. A street the index does not hold (outside its metro,
  say) is asked of Nominatim as before.
* **When the NucBox does not answer**, the panel falls back to the public
  geocoder for the places it could not ask, and to straight lines for the
  figure, and says which: "· NucBox down, public map used", "· NucBox router
  down" — and "· NucBox down, public map for the rest" when it answered some
  places first, whose pins are still its own. A router that answers there is no road between the points (OSRM's
  NoRoute, and only that) leaves the straight line too, with "· no road
  found"; any other refusal from OSRM is the router down. A question the
  rig's own server refuses is a bug in the page, said as one ("no pin for X
  — a bug: the rig refused the question"), and is never handed to the public
  map instead.
* **How each place was found, drawn under the pins.** The card's disc as a
  faint dashed circle round its fix (blue, the car's colour; the order in
  the car's own card's disc in amber): the card's distance plus half a mile.
  It is what the PICKUP pin is refused past (red), and the order in the
  car's end past its own card's disc; the dropoff pin is held to no disc.
  With the NucBox answering, each of the card's places is searched inside
  it and a candidate past it is never used; with no NucBox, or one that
  could not be asked, the places go to the public geocoder in the 60 mi box
  round the car and then with no box, and only the pickup's refusal holds.
  Every candidate the NucBox sent is a small grey dot, a corner's every
  meeting the same; one past the disc's edge a hollow dashed ring; a
  numberless street's stretch inside the disc a line, solid when pinned and
  grey when refused, nothing of it outside the disc drawn. A refused place
  has no pin and its candidates say the caption's own refusal: pointed at or
  tapped, a mark's words show in one box across the map's foot, wrapped to
  the map's width, never in a tooltip beside the mark that the map would
  clip. A key across the map's foot names the marks that are on the map and
  no others, from "◯ card's reach · ● pin · ● also found · ○ outside" ("◯
  reach · ● pin · ● found · ○ outside" on the 3.5" hat); if drawing them
  failed it says "how each was found: not drawn", and the car, pins, runs
  and line under the map are drawn the same. It is drawn off the answers
  the walk already holds and asks nothing. The view is fitted to the car
  and the pins, never to the discs, which run past its edge when they are
  bigger: at each draw of the card (the car at once, again as each place
  lands, and once all are in), whenever the server sends a message while
  that card is on the glass and Map view is up (the same fit again, so a
  pan lasts until the next message), when ⛶ Map is pressed round to it,
  and once to take in the "you are here" dot if there is one when Map view
  opens; the dot moving never moves it. A card with no yardstick has no
  disc drawn: its sixty miles are not the card's reach. The public
  geocoder's one answer has no list behind it, so with no NucBox answering
  only the discs are drawn.

`map.html` and the offers page still use the public geocoder: they place a
whole window of offers rather than one card's disc, and choosing among
candidates there is a different question that has not been answered. What
`map.html` can show of how a place was found is its own walk: each pin's
popup says whether it was found inside the box searched round where the car
was (its size read off the box: the 60 miles widened by half a grid step,
about 137 mi north–south by 134 east–west in Atlanta), asked with no box, or
asked wide because the box found nothing — and a place answered wide and
outside its box is RINGED, a dashed ring round its filled dot: it was used.
Not hollow, which on the panel's Map view means a candidate that was not
used. A one-line key across the map's foot names the marks on it.

## Files

| Path | |
|---|---|
| `index.html` | Layout |
| `styles.css` | Styling |
| `ui.js` | All of the app logic — browser only, never run under Node |
| `journal-client.js` | Hands an offer typed here, or read by the phone's scanner, to the rig's journal when there is one to answer |
| `server.js` | Zero-dependency static server; the Node entry point |
| `journal.html` | Every offer the scanner kept, and what it adds up to |
| `map.html` | Puts a whole range of places on a map, to check whether the rig is right about where the work happened — one pin per place, with the pins that landed in another state drawn in red and listed rather than allowed to set the view, a toggle for the positions the rig's own GPS recorded — only those its one fix-quality gate passed, with the refused ones counted — and a dot for where the car is now, with a circle the size of the GPS's own error. Needs a network; asks nothing until you press the button |
| `map-view.js` | The deciding behind both maps with no map in it — the geocoder, its one-request-a-second rule, the box drawn around where the car was, the test for a pin that cannot be in this shift, and the panel's NucBox search inside a card's disc and its road detour (see *The NucBox at home*). Runs under Node, which is what lets the rate limit be checked against a fake clock |
| `streets.js` | The NucBox's street index: where two named streets meet, and the stretch of one street inside a box, answered by the NucBox's own `server.js` from the file `tools/street_index.py` makes, and relayed by the rig's (see *The NucBox at home*) |
| `live.html` | The driving screen: the rig's verdict, the phone as the camera sees it, and the controls used while moving |
| `snaps.html` | Every **📷 Snap** the rig has kept, newest first, with a link to open or save each file. The control is on the driving screen, in the row with the connection dot; one press keeps a screenshot of the rig's own display, the camera's last picture with its age, and what `/api/status` said, and says which of those it could not keep and why. **⤓ one file** saves a snap as a single `.html` to share — the pictures inside it, the records as text and as the files themselves, nothing it needs a network for; tick several, or take one **with the newer** ones (the series it starts), and they are one file, oldest first. A snap can carry a short note ("trip planner"), typed here so the press on the driving screen stays one click. Linked from the offers page. See [rpi/README.md](rpi/README.md) for the screenshot tool it needs |
| `shift.html` | Today's shift on the phone, read-only: what `tools/shift_report.py` says about it — the totals off the GPS log, each order's card against what it really took, how each order's end was pinned — through `GET /api/shift`. No address, no coordinate, no control but the way back. Linked from the route view (**◷ Shift**) and the offers page |
| `scan.html`, `scan.js`, `scan.css` | The phone's own scanner — a photo of the offer card, read on the phone; see [SCANNING.md](SCANNING.md) |
| `offer-parser.js` | Turns the text off a card into pay, minutes and miles — one corpus, shared with the Pi's port |
| `vendor/` | The OCR engine the phone's scanner runs, kept here so the page works with no signal |
| `advice.js` | What target the offers themselves argue for — shared, and tested on its own |
| `assemble.js` | Where the order in the car ends: an address the scanner read, a Trip Planner over one page or several, a lone dropoff on a single-trip card — each value on the hold with where it came from (press, label, planner, card, seen). No I/O; `server.js` writes and says what it decides. Tested on its own over `tests/fixtures/sequences.json` |
| `sw.js` | Offline cache — stale-while-revalidate, so a changed file is picked up on the next open. `SHELL` is a convenience to bump when a page changes; `BLOB` is the OCR engine, bumped only when that changes |
| `manifest.webmanifest` | Home-screen install metadata |
| `tools/make_icons.py` | Regenerates the icons in `icons/` |
| `tools/make-cert.sh` | `npm run cert` — local certificate authority for https |
| `tools/street_index.py` | Makes the street index once, on the NucBox, from the Georgia extract it already holds — osmium-tool for the cutting, Python's standard library for the rest |
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
  press **⌖ Scan** on the driving screen while the card is up, and the
  address goes on that offer's row — labelled as read off the phone rather
  than printed on the card, because the two are different kinds of evidence.
  It is also what puts the job on the map.
* **the stops on Uber's Trip Planner.** Press **⌖ Scan** with the planner
  up on the phone and the driving screen lists its stops in order, one line
  each — `▸ Dropoff by 4:18 · Pat Q. · 4821 Kestrel Dr, Marietta` — between
  offers, until you press again, the order is put down or the next offer is
  recorded, which is when a read destination goes too; a panel reloaded in
  between shows the same. A notice on the card (the journal not saving, the
  phone too bright) comes first: the stops give way to it a line at a time and
  say how many they are. The planner prints no ZIP, so it is read by its own
  layout (the stop header, the name, “Expected by”, and the street and town
  under “Address”). With an order marked taken it is also read without a
  press whenever the card box shows a planner, at most once every ten seconds,
  off a whole screen whose title reads “Trip Planner” — the stops only, never a
  destination. When you press and the trip has exactly one
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
  setting — and that is open. A 📷 Snap keeps the card's places and the car's
  position whatever it says too: it is a picture of what the panel showed,
  kept on the Pi and not synced home. `--no-journal` keeps no record at all. Either way
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
