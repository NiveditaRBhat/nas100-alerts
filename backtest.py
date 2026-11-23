"""
Backtest: how would the BUY/SELL rules have done over the last ~60 days?
Runs on GitHub (where market data is reachable) and writes BACKTEST.md.

Assumptions: enter at the close of the signal candle; if stop and target are both touched in
the same candle, count it as a loss; subtract spread/slippage ("cost" in signals.py) on every trade.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd

import signals as S
from monitor import fetch


def trades_for(b, cost):
    out = []
    idx = np.flatnonzero(b["signal"].values != "")
    for i in idx:
        row = b.iloc[i]
        res = S.outcome(b, i, row["signal"], row["Close"], row["stop"], row["target"])
        if res is None:
            continue
        status, exit_price, _ = res
        out.append({"time": b.index[i], "side": row["signal"], "status": status,
                    "r": S.r_multiple(row["signal"], row["Close"], row["stop"], exit_price, cost)})
    return pd.DataFrame(out)


def stats(t):
    if t.empty:
        return {"Trades": 0, "Win rate": "-", "Avg R": "-", "Total R": "-", "Profit factor": "-", "Worst run": "-"}
    gains, losses = t.loc[t.r > 0, "r"].sum(), -t.loc[t.r <= 0, "r"].sum()
    equity = t["r"].cumsum()
    drawdown = (equity - equity.cummax()).min()
    return {
        "Trades": len(t),
        "Win rate": f"{(t.r > 0).mean():.0%}",
        "Avg R": f"{t.r.mean():+.2f}",
        "Total R": f"{t.r.sum():+.1f}",
        "Profit factor": f"{gains / losses:.2f}" if losses > 0 else "inf",
        "Worst run": f"{drawdown:.1f}R",
    }


def table(rows):
    cols = list(rows[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def main():
    rows_on, rows_off, all_on = [], [], []
    period = None
    for key, mk in S.MARKETS.items():
        try:
            bars = fetch(mk["symbol"], "60d", "15m")
            hourly = fetch(mk["symbol"], "1y", "1h")
        except Exception as e:
            print(f"{key}: {e}")
            continue
        ctx = S.daily_context(S.daily_from_hourly(hourly))
        period = f"{bars.index[0]:%d %b} – {bars.index[-1]:%d %b %Y}"
        t_on = trades_for(S.build(bars, ctx, use_range_filter=True), mk["cost"])
        t_off = trades_for(S.build(bars, ctx, use_range_filter=False), mk["cost"])
        rows_on.append({"Market": mk["name"], **stats(t_on)})
        rows_off.append({"Market": mk["name"], **stats(t_off)})
        if not t_on.empty:
            all_on.append(t_on.assign(market=mk["name"]))

    combined = pd.concat(all_on).sort_values("time") if all_on else pd.DataFrame(columns=["r"])
    rows_on.append({"Market": "**All**", **stats(combined)})

    md = [
        "# Backtest results",
        f"_Period: {period} (15-min candles) · run {datetime.now(timezone.utc):%d %b %Y %H:%M} UTC_",
        "",
        "**R** = profit measured in units of risk. +2R = target hit, −1R = stopped out.",
        "If you risk 1% of your account per trade, +10R ≈ +10%.",
        "",
        "## Rules as live (with daily-range filter)",
        table(rows_on),
        "",
        "## Same rules without the daily-range filter",
        table(rows_off),
        "",
        "_Costs included: NAS100 2 pts, Gold 0.4, Brent 0.04 per trade. "
        "60 days is a short sample — treat this as a first check, not proof._",
    ]
    with open("BACKTEST.md", "w") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
