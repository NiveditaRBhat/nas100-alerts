"""
Signal engine: the trading rules, shared by the live monitor and the backtest.

The idea in plain words
-----------------------
1. TREND (daily): Is the market trending up, down, or sideways?
   Up   = yesterday's close above the 20-day average, and the 20-day above the 50-day.
   Down = the opposite. Anything else = sideways -> no trades.
2. DAILY RANGE: How far does this market usually move in a day (average daily range)?
   If today has already used up most of its normal range, the move is probably done -> don't chase.
3. ENTRY (15-minute chart): Trade WITH the trend after a pullback.
   BUY  = uptrend, price dipped to its 15-min average, then a candle closes back above it
          and above the previous candle's high (buyers stepping back in).
   SELL = the mirror image in a downtrend.
4. RISK: Stop just beyond the pullback's low/high. Target = 2x the risk.
"""

import numpy as np
import pandas as pd

MARKETS = {
    "NAS100": {"symbol": "NQ=F", "name": "NAS100", "fmt": "{:,.0f}", "cost": 2.0},
    "GOLD": {"symbol": "GC=F", "name": "Gold", "fmt": "{:,.1f}", "cost": 0.4},
    "OIL": {"symbol": "BZ=F", "name": "Brent oil", "fmt": "{:,.2f}", "cost": 0.04},
}
# "cost" = assumed spread + slippage per trade, in price points (used in the backtest)

# ───────── Rules (tune here) ─────────
EMA_FAST_D, EMA_SLOW_D = 20, 50   # daily trend averages
ADR_LEN = 14                      # days for average daily range
EMA_15 = 20                       # 15-min average used for pullbacks
PULLBACK_BARS = 4                 # pullback must touch the average within the last 4 candles
MIN_PRESSURE = 0.10               # candles closing in the upper (buy) / lower (sell) part of their range
MAX_RANGE_USED = 0.80             # skip if today already moved >= 80% of a normal day
MIN_RISK_ADR, MAX_RISK_ADR = 0.10, 0.40   # stop distance must be 10%-40% of a normal day
REWARD_RISK = 2.0                 # target = 2x risk
COOLDOWN_BARS = 8                 # at least 2 hours between signals on the same market
MAX_SIGNALS_PER_DAY = 2
TRADE_HOURS_DUBAI = (10, 1)       # only signal 10:00 -> 01:00 Dubai (London + New York)
MAX_HOLD_BARS = 24                # close the trade after 6 hours if neither stop nor target hit
BIG_MOVE_MULT = 2.5               # "big move" alert: 15-min candle >= 2.5x normal size
BAR = pd.Timedelta(minutes=15)


def session_key(index):
    """Futures trading day: 18:00 New York to 17:00 next day, labelled by the closing date."""
    ny = index.tz_convert("America/New_York")
    return pd.to_datetime((ny + pd.Timedelta(hours=6)).date)


def daily_from_hourly(hourly):
    key = session_key(hourly.index)
    g = hourly.groupby(key)
    return pd.DataFrame({
        "High": g["High"].max(),
        "Low": g["Low"].min(),
        "Close": g["Close"].last(),
    }).sort_index()


def daily_context(daily):
    c = daily["Close"]
    ema_f = c.ewm(span=EMA_FAST_D, adjust=False).mean()
    ema_s = c.ewm(span=EMA_SLOW_D, adjust=False).mean()
    trend = np.where((c > ema_f) & (ema_f > ema_s), "UP",
                     np.where((c < ema_f) & (ema_f < ema_s), "DOWN", "SIDEWAYS"))
    return pd.DataFrame({
        "trend": trend,
        "adr": (daily["High"] - daily["Low"]).rolling(ADR_LEN).mean(),
        "prev_high": daily["High"],
        "prev_low": daily["Low"],
    }, index=daily.index)


def build(bars, ctx, use_range_filter=True):
    """Return 15-min bars with indicators and a 'signal' column (BUY / SELL / '')."""
    b = bars[["Open", "High", "Low", "Close"]].copy()
    b["session"] = session_key(b.index)

    # Attach YESTERDAY's daily context to every 15-min bar (no peeking at today)
    left = pd.DataFrame({"session": b["session"].values})
    right = ctx.reset_index().rename(columns={"index": "day"})
    right.columns = ["day"] + list(ctx.columns)
    m = pd.merge_asof(left, right.sort_values("day"), left_on="session", right_on="day",
                      allow_exact_matches=False)
    for col in ctx.columns:
        b[col] = m[col].values

    h, l, c = b["High"], b["Low"], b["Close"]
    b["day_high"] = b.groupby("session")["High"].cummax()
    b["day_low"] = b.groupby("session")["Low"].cummin()
    b["range_used"] = (b["day_high"] - b["day_low"]) / b["adr"]

    b["ema"] = c.ewm(span=EMA_15, adjust=False).mean()
    rng = h - l
    clv = (((c - l) - (h - c)) / rng.replace(0, np.nan)).fillna(0)
    b["pressure"] = clv.rolling(8).mean()
    tr = pd.concat([rng, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    b["big_move"] = rng >= BIG_MOVE_MULT * atr.shift(1)
    b["move_x"] = rng / atr.shift(1)

    hour = b.index.tz_convert("Asia/Dubai").hour
    start, end = TRADE_HOURS_DUBAI
    in_hours = (hour >= start) | (hour < end) if start > end else (hour >= start) & (hour < end)
    room = (b["range_used"] < MAX_RANGE_USED) if use_range_filter else pd.Series(True, index=b.index)

    touched_up = (l <= b["ema"]).astype(int).rolling(PULLBACK_BARS, min_periods=1).max().astype(bool)
    touched_dn = (h >= b["ema"]).astype(int).rolling(PULLBACK_BARS, min_periods=1).max().astype(bool)

    buy = ((b["trend"] == "UP") & touched_up & (c > b["ema"]) & (c > h.shift(1))
           & (b["pressure"] > MIN_PRESSURE) & room & in_hours)
    sell = ((b["trend"] == "DOWN") & touched_dn & (c < b["ema"]) & (c < l.shift(1))
            & (b["pressure"] < -MIN_PRESSURE) & room & in_hours)

    buy_stop = l.rolling(PULLBACK_BARS + 1).min() - 0.05 * b["adr"]
    sell_stop = h.rolling(PULLBACK_BARS + 1).max() + 0.05 * b["adr"]
    lo_r, hi_r = MIN_RISK_ADR * b["adr"], MAX_RISK_ADR * b["adr"]
    buy &= (c - buy_stop).between(lo_r, hi_r)
    sell &= (sell_stop - c).between(lo_r, hi_r)

    # Throttle: cooldown + max signals per day
    sig = np.array([""] * len(b), dtype=object)
    stop = np.full(len(b), np.nan)
    target = np.full(len(b), np.nan)
    last_i, per_day = -10_000, {}
    buy_a, sell_a = buy.fillna(False).values, sell.fillna(False).values
    sess, close = b["session"].values, c.values
    bs, ss = buy_stop.values, sell_stop.values
    for i in range(len(b)):
        side = "BUY" if buy_a[i] else "SELL" if sell_a[i] else ""
        if not side or i - last_i < COOLDOWN_BARS or per_day.get(sess[i], 0) >= MAX_SIGNALS_PER_DAY:
            continue
        s = bs[i] if side == "BUY" else ss[i]
        risk = abs(close[i] - s)
        sig[i], stop[i] = side, s
        target[i] = close[i] + REWARD_RISK * risk if side == "BUY" else close[i] - REWARD_RISK * risk
        last_i, per_day[sess[i]] = i, per_day.get(sess[i], 0) + 1
    b["signal"], b["stop"], b["target"] = sig, stop, target
    return b


def outcome(b, i, side, entry, stop, target, max_bars=MAX_HOLD_BARS):
    """Follow a trade forward. Returns (status, exit_price, exit_time) or None if still open."""
    for j in range(i + 1, min(i + 1 + max_bars, len(b))):
        hi, lo = b["High"].iloc[j], b["Low"].iloc[j]
        if side == "BUY":
            if lo <= stop:
                return "STOP", stop, b.index[j]
            if hi >= target:
                return "TARGET", target, b.index[j]
        else:
            if hi >= stop:
                return "STOP", stop, b.index[j]
            if lo <= target:
                return "TARGET", target, b.index[j]
    if i + max_bars < len(b):
        j = i + max_bars
        return "TIME", b["Close"].iloc[j], b.index[j]
    return None


def r_multiple(side, entry, stop, exit_price, cost=0.0):
    risk = abs(entry - stop)
    move = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    return (move - cost) / risk
