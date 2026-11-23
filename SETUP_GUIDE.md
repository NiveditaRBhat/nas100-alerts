# NAS100 Alerts — Setup Guide (about 15 minutes, all free)

> **Already installed for you.** Your topic is `niv-nas100-dff2840e` — just install ntfy and subscribe to it. Steps 2–4 below are done.

You need 3 files: `monitor.py`, `requirements.txt`, `monitor.yml`.

## Step 1 — Install the ntfy app (your notifications)
1. Install **ntfy** from the App Store (free).
2. Tap **+** to subscribe to a topic. Make up a long, hard-to-guess name, e.g. `niv-nas100-k7q29x`.
   (Anyone who knows the name could read your alerts, so don't use something simple.)
3. Keep this name — it's your **topic**.

## Step 2 — Create a GitHub account and repository
1. Go to github.com and sign up (free). In Safari, tap **aA → Request Desktop Website** to see every button.
2. Tap **+ → New repository**.
3. Name: `nas100-alerts`. Choose **Public** (public repos get unlimited free run time; your topic stays hidden as a secret).
4. Tick **Add a README file**, then **Create repository**.

## Step 3 — Add the 3 files
For each file: tap **Add file → Create new file**, type the name, paste the contents, tap **Commit changes**.

| Type this as the file name | Paste contents of |
|---|---|
| `monitor.py` | monitor.py |
| `requirements.txt` | requirements.txt |
| `.github/workflows/monitor.yml` | monitor.yml |

Typing the `/` in the third name creates the folders automatically — type it exactly, including the dot at the start.

## Step 4 — Add your ntfy topic as a secret
1. In the repo: **Settings → Secrets and variables → Actions**.
2. **New repository secret** → Name: `NTFY_TOPIC` → Secret: your topic name → **Add secret**.
3. Optional — only get alerts during certain Dubai hours: open the **Variables** tab →
   **New repository variable** → Name: `ACTIVE_HOURS_DUBAI` → Value: e.g. `17-1` (5 PM to 1 AM, the US session).
   Leave it out to get alerts around the clock.

## Step 5 — Send a test alert
1. Open the **Actions** tab. If asked, tap **I understand my workflows, go ahead and enable them**.
2. Tap **NAS100 alerts → Run workflow**, tick **Send a test notification**, tap **Run workflow**.
3. Within about a minute your phone should get "NAS100 alerts are working".
4. Run it again *without* the tick to do a real market check. Green tick = working.

That's it. It now checks every 5 minutes, Sunday night to Friday night.

## What the alerts mean
- **HIGH VOLATILITY** — moves are 1.8x bigger than normal, or one huge candle
- **BUYING / SELLING PRESSURE** — candles keep closing near their highs/lows on volume, on the same side of VWAP
- **VOLUME SPIKE** — a 5-minute candle traded 2x+ normal volume
- **SQUEEZE BREAKOUT UP / DOWN** — the market was unusually quiet, then broke out
- **VXN FEAR SPIKE** — Nasdaq volatility index up 8%+ vs yesterday (max once a day)

Each alert shows the futures price (NQ — close to your US100 CFD but not identical), how volatile it is vs normal, the pressure score (-1 to +1) and volume vs average.

## Tuning
Open `monitor.py` → tap the pencil icon → change the numbers in the SETTINGS block → Commit.
- Too many alerts: raise `ATR_MULT`, `PRESSURE_THRESH`, `VOL_MULT`, or `COOLDOWN_MIN`.
- Too few: lower them.

## Good to know
- GitHub's timer can run a few minutes late, especially at busy times. Treat alerts as "look at the chart now", not as exact entry signals.
- Data comes from Yahoo Finance for free. If Yahoo blocks a run, it just tries again 5 minutes later; GitHub may email you about failed runs.
- To pause: **Actions → NAS100 alerts → ⋯ → Disable workflow**.
