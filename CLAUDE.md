# Working on this repository

Read first: [AUDITS.md](AUDITS.md) — **Done** (fixed, with the commit), **Settled**
(proposals checked and refused: do not re-propose), **Open** (known, not done).
The rig itself is explained in [rpi/README.md](rpi/README.md); the site and the
NucBox in [README.md](README.md).

## The lite edition

**The decision (the owner, Nov 2026).** Some drivers want this program without
the experimental half: the camera reads the phone, one big card says whether
the offer is worth it, a display with nothing to touch, on at boot. Lite is a
**mode of this repository**, not a separate repository and not a fork, so that
every reading and money-safety fix — `CENTS_LOST`, `unsure_payout`,
`money_is_clipped`, the rescue rules, the card finder, DoorDash's raise and
evened read, the remembered crop — reaches both the day it is made.

Where it lives:

- `lite/` — its panel (`lite/lite.html`), its server switch (`lite/lite.js`),
  `lite/install.sh` and `lite/kiosk.sh`, and its own README with the parts list.
- The flag: `LITE=1` in the environment (the unit lite/install.sh writes), or
  `"lite": true` in `rpi/config.json`'s `settings`. Read once at boot by
  `server.js` (via `lite/lite.js`) and `rpi/scan_pi.py` (via `rpi/lite.py`),
  and asked by name at a few seams only. `rpi/test_lite.py` holds both ways.
- A `lite` branch that receives only builds that passed the gate; an SD image
  later, through releases. If lite is ever shared publicly while this repo
  stays private: a small public wrapper repo that pulls from this one — never
  a copy.

Rules:

- New features go in behind the full mode. Lite stays minimal: if a change
  needs the NucBox, a touch screen, an upload or a report, lite turns it off.
- The reader, the parsers and every money-safety rule are SHARED and must
  never fork. Lite may turn things off; it never gets its own copy of
  anything that decides what an offer pays.
- Lite must stay lean enough that a Pi Zero 2 W has a chance: no heavy
  optional threads when `LITE` is on.

## Standing conventions

- **Twin parsers.** `rpi/offer_parser.py` and `offer-parser.js` read the same
  cards the same way, over one corpus, `tests/fixtures/cases.json`. A change to
  one is a change to both, with a case.
- **Comments say why**, in the existing voice: what was measured, what broke,
  what was refused. AUDITS.md entries in its existing style
  (`rpi/test_lint.py` rejects an entry whose opening is too like another's).
- **Commits** are signed (`git commit -S`). No model names anywhere in the
  repo.
- **Privacy.** Never commit real addresses, names, coordinates, hostnames or
  Tailscale IPs. Invented fixtures only (the suites' invented places).
- **Branches.** Work lands on experimental; `main` moves only through the
  release gate. Do not commit to `main` directly.
- **Tests.** `bash tools/test.sh` runs everything and must end "all N suites
  passed". It sets `TZ=America/New_York`, the rig's zone.

## Settled — binding, do not re-propose

- No `$/mile` rules and no payout floors.
- No re-timing an offer at a pace.
- No heat map on the rig.
- Silence is never read as an accept.
- No seventh control on the driving bar.
- The rig never presses the phone (no Decline, no remapped button, no taps).
- DoorDash's map label is approximate drawing only (≈): never a pin, a GPS
  drop or a figure.

Each has its reasons in AUDITS.md under Settled.
