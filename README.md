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

## Running it locally

Any static file server works:

```sh
python3 -m http.server 8000
# then open http://localhost:8000
```

## Files

| Path | |
|---|---|
| `index.html` | Layout |
| `styles.css` | Styling |
| `app.js` | All of the logic |
| `sw.js` | Offline cache — bump `CACHE` when you change files |
| `manifest.webmanifest` | Home-screen install metadata |
| `tools/make_icons.py` | Regenerates the icons in `icons/` |

## Notes

Uber's quoted trip time is the *driving* time. Whether you count the pickup drive
matters more than almost anything else in this calculation — a $9 offer that is
"12 minutes" is often 20 minutes door to door, which is $27/hr on paper and
$16/hr in reality. Pickup padding exists for that; set it to your honest average.
