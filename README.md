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

Other keys: **⌫** deletes (and on an empty field jumps back to the previous one),
**CLR** resets, **LOG** saves the offer to history.

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
| Target $/hour | The green line. Default $25. |
| Near-miss band | How far below target still counts as amber. Default 15%. |
| Cost per mile | Gas and wear, subtracted from the offer before the rate is figured. Set it to `0` to see gross pay; the 2025 IRS rate is `0.70`. |
| Pickup padding | Minutes added to every offer, since the quoted time usually ignores the drive to the rider. |
| Haptics | Buzz on each key. |

Settings and history are stored on the phone only. The app makes no network
requests after it loads — there is no account, no server, no tracking.

## The math

```
minutes = entered minutes + pickup padding
net     = pay - (miles x cost per mile)

$/hour  = net / (minutes / 60)
$/min   = net / minutes
$/mile  = pay / miles
```

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

On a Raspberry Pi with a camera, `npm start` also runs the offer scanner once
`rpi/config.json` exists, serving the live verdict at `/live.html` and its state
at `/api/status`. See [rpi/README.md](rpi/README.md); `SCANNER=0` turns it off.

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
| `server.js` | Zero-dependency static server; the Node entry point |
| `sw.js` | Offline cache — bump `CACHE` when you change files |
| `manifest.webmanifest` | Home-screen install metadata |
| `tools/make_icons.py` | Regenerates the icons in `icons/` |
| `tools/make-cert.sh` | `npm run cert` — local certificate authority for https |

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
