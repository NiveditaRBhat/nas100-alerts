"""
USTECH100 / NAS100 volatility & buying/selling pressure monitor.
Runs on GitHub Actions every ~5 minutes and pushes alerts to your phone via ntfy.

Signals (on 5-minute Nasdaq-100 futures, NQ=F, which has real traded volume):
  1. Volatility spike   - ATR jumps far above normal, or one huge candle
  2. Buying pressure    - candles keep closing near their highs on volume, price above VWAP
  3. Selling pressure   - candles keep closing near their lows on volume, price below VWAP
  4. Volume spike       - a candle trades far more volume than usual
  5. Squeeze breakout   - Bollinger Bands at their tightest, then price breaks out
  6. VXN fear spike     - Nasdaq volatility index up sharply vs yesterday
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

# ───────────────────────── SETTINGS (tune these) ─────────────────────────
SYMBOL = "NQ=F"            # Nasdaq-100 futures (moves with your US100 CFD)
VXN_SYMBOL = "^VXN"        # Nasdaq volatility index
INTERVAL = "5m"
BAR_MINUTES = 5

ATR_LEN = 14
BASELINE_LEN = 100         # bars that define "normal" volatility
ATR_MULT = 1.8             # high-vol regime when ATR >= 1.8x normal
BIG_BAR_MULT = 2.5         # one candle >= 2.5x ATR

PRESSURE_LEN = 10          # bars used to measure pressure
PRESSURE_THRESH = 0.35     # 0..1, higher = stricter
VOL_LEN = 20
VOL_MULT = 2.0             # volume spike when volume >= 2x average

BB_LEN = 20
BB_MULT = 2.0
SQUEEZE_LOOKBACK = 120

VXN_JUMP_PCT = 8.0         # VXN up >= 8% vs yesterday's close

COOLDOWN_MIN = 30          # don't repeat the same alert type within 30 minutes

# Only send alerts between these Dubai hours (24h clock). "0-24" = always.
# Example: "17-1" = 5 PM to 1 AM Dubai (US session).
ACTIVE_HOURS_DUBAI = os.environ.get("ACTIVE_HOURS_DUBAI", "0-24")

STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
DUBAI = timezone(timedelta(hours=4))
# ─────────────────────────────────────────────────────────────────────────


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def in_active_hours(now_dubai):
    try:
        start, end = (int(x) for x in ACTIVE_HOURS_DUBAI.split("-"))
    except ValueError:
        return True
    h = now_dubai.hour
    if start == end or (start == 0 and end == 24):
        return True
    return start <= h < end if start < end else (h >= start or h < end)


def fetch(symbol, period, interval, tries=3):
    import yfinance as yf
    last_err = None
    for i in range(tries):
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and not df.empty:
                return df
        except Exception as e:  # network hiccups / rate limits
            last_err = e
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"Could not download {symbol}: {last_err}")


def compute(df):
    """Add indicator and signal columns to a 5m OHLCV DataFrame."""
    d = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    h, l, c, v = d["High"], d["Low"], d["Close"], d["Volume"].fillna(0)
    prev_c = c.shift(1)

    # 1. Volatility
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_LEN, adjust=False).mean()
    normal = tr.rolling(BASELINE_LEN).mean()
    d["vol_ratio"] = atr / normal
    d["high_vol"] = d["vol_ratio"] >= ATR_MULT
    rng = h - l
    d["big_bar"] = rng >= BIG_BAR_MULT * atr.shift(1)
    d["sig_volatility"] = (d["high_vol"] & ~d["high_vol"].shift(1, fill_value=False)) | d["big_bar"]

    # 2/3. Pressure: where candles close inside their range, weighted by volume
    clv = np.where(rng > 0, ((c - l) - (h - c)) / rng.replace(0, np.nan), 0.0)
    clv = pd.Series(clv, index=d.index).fillna(0)
    w = v.where(v > 0, 1.0)
    d["pressure"] = (clv * w).rolling(PRESSURE_LEN).sum() / w.rolling(PRESSURE_LEN).sum()

    # Session VWAP (futures session starts 18:00 New York = 6h shift)
    idx = d.index.tz_convert("America/New_York")
    session = (idx + pd.Timedelta(hours=6)).date
    tp = (h + l + c) / 3
    cum_pv = (tp * v).groupby(session).cumsum()
    cum_v = v.groupby(session).cumsum()
    d["vwap"] = (cum_pv / cum_v.replace(0, np.nan)).fillna(c.ewm(span=50).mean())

    buy = (d["pressure"] >= PRESSURE_THRESH) & (c > d["vwap"])
    sell = (d["pressure"] <= -PRESSURE_THRESH) & (c < d["vwap"])
    d["sig_buy"] = buy & ~buy.shift(1, fill_value=False)
    d["sig_sell"] = sell & ~sell.shift(1, fill_value=False)

    # 4. Volume spike
    avg_v = v.rolling(VOL_LEN).mean()
    d["vol_x"] = v / avg_v.replace(0, np.nan)
    d["sig_volume"] = (v > 0) & (d["vol_x"] >= VOL_MULT)

    # 5. Squeeze -> breakout
    mid = c.rolling(BB_LEN).mean()
    sd = c.rolling(BB_LEN).std(ddof=0)
    up, lo = mid + BB_MULT * sd, mid - BB_MULT * sd
    bbw = (up - lo) / mid
    squeeze = bbw <= bbw.rolling(SQUEEZE_LOOKBACK).min() * 1.05
    recent_sq = squeeze.astype(int).rolling(6, min_periods=1).max().astype(bool)
    d["sig_squeeze_up"] = recent_sq & (c > up)
    d["sig_squeeze_dn"] = recent_sq & (c < lo)
    return d


LABELS = {
    "sig_volatility": ("HIGH VOLATILITY", "zap", "high"),
    "sig_buy": ("BUYING PRESSURE", "green_circle", "high"),
    "sig_sell": ("SELLING PRESSURE", "red_circle", "high"),
    "sig_volume": ("VOLUME SPIKE", "bar_chart", "default"),
    "sig_squeeze_up": ("SQUEEZE BREAKOUT UP", "rocket", "high"),
    "sig_squeeze_dn": ("SQUEEZE BREAKOUT DOWN", "boom", "high"),
}


def notify(title, body, tag, priority="default"):
    if DRY_RUN or not NTFY_TOPIC:
        print(f"[would notify] {title} | {body}")
        return
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers={"Title": title, "Tags": tag, "Priority": priority},
        timeout=15,
    )
    r.raise_for_status()


def run(df5=None, vxn=None, now=None):
    now = now or datetime.now(timezone.utc)
    state = load_state()

    if df5 is None:
        df5 = fetch(SYMBOL, "5d", INTERVAL)
    d = compute(df5)

    # Only use fully closed candles
    closed = d[d.index + pd.Timedelta(minutes=BAR_MINUTES) <= now]
    if closed.empty:
        print("No closed bars yet.")
        return []

    last_checked = state.get("last_bar")
    if last_checked:
        new = closed[closed.index > pd.Timestamp(last_checked)]
    else:
        new = closed.tail(1)
    new = new.tail(6)  # never look back more than 30 minutes
    state["last_bar"] = closed.index[-1].isoformat()

    now_dubai = now.astimezone(DUBAI)
    active = in_active_hours(now_dubai)
    sent = []
    last = closed.iloc[-1]
    price = last["Close"]
    footer = (
        f"NQ {price:,.2f} | vol {last['vol_ratio']:.1f}x normal | "
        f"pressure {last['pressure']:+.2f} | volume {last['vol_x']:.1f}x avg\n"
        f"{now_dubai:%a %H:%M} Dubai"
    )

    cooldowns = state.setdefault("last_alert", {})
    for col, (name, tag, prio) in LABELS.items():
        hits = new[new[col].fillna(False)]
        if hits.empty:
            continue
        prev = cooldowns.get(col)
        if prev and now - datetime.fromisoformat(prev) < timedelta(minutes=COOLDOWN_MIN):
            continue
        if active:
            notify(f"NAS100: {name}", footer, tag, prio)
            sent.append(name)
        cooldowns[col] = now.isoformat()

    # 6. VXN fear spike (once per day)
    try:
        if vxn is None:
            vxn = fetch(VXN_SYMBOL, "5d", "1d")
        if len(vxn) >= 2:
            chg = (vxn["Close"].iloc[-1] / vxn["Close"].iloc[-2] - 1) * 100
            today = now_dubai.date().isoformat()
            if chg >= VXN_JUMP_PCT and state.get("vxn_alert_day") != today:
                if active:
                    notify("NAS100: VXN FEAR SPIKE",
                           f"VXN up {chg:.1f}% vs yesterday ({vxn['Close'].iloc[-1]:.2f})\n" + footer,
                           "scream", "high")
                    sent.append("VXN FEAR SPIKE")
                state["vxn_alert_day"] = today
    except Exception as e:
        print(f"VXN check skipped: {e}")

    save_state(state)
    print(f"Checked {len(new)} new bar(s). Sent: {sent or 'nothing'}. {footer}")
    return sent


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify("NAS100 alerts are working",
               "Test notification from your GitHub monitor.", "white_check_mark")
        print("Test sent.")
    else:
        run()
