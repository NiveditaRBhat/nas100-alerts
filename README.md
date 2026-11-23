# Trading alerts — NAS100 · Gold · Brent oil

Sends BUY / SELL notifications to your phone (ntfy topic **`niv-nas100-dff2840e`**). Runs on GitHub every 5 minutes, free.

## What you get
| Notification | Meaning |
|---|---|
| **BUY Gold** / **SELL NAS100** | A trade idea with entry, stop and target |
| **… hit target / stopped out / closed after 6h** | How that idea turned out, in R (+2R = won 2x the risk) |
| **Daily brief** (~10:00 Dubai) | Trend for each market, its normal daily range, last 7 days' score |
| **… big move** | A 15-min candle 2.5x bigger than normal — look at the chart |

## The rules (in `signals.py`)
1. **Trend** — daily chart: up, down or sideways. Sideways = no trades.
2. **Daily range** — skip if the market already moved 80%+ of a normal day.
3. **Entry** — 15-min chart: price pulls back to its average, then resumes in the trend direction.
4. **Risk** — stop beyond the pullback, target 2x the risk. Signals only 10:00–01:00 Dubai.

## Files
- `signals.py` — the rules (tune the numbers at the top)
- `monitor.py` — live alerts
- `backtest.py` → `BACKTEST.md` — how the rules did over the last ~60 days
- `signals.csv` — every live signal and its result

Data: Yahoo Finance futures (NQ, GC, BZ), about 10 minutes delayed. Futures prices differ slightly from CFD prices — use the stop/target distances, not the exact levels.
