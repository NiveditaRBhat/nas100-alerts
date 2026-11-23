"""
Live monitor: runs every 5 minutes on GitHub and sends clean notifications to ntfy.

You receive:
  • BUY / SELL signals with entry, stop and target
  • The result of each signal (target hit, stopped out, or closed after 6 hours)
  • A daily brief at ~10:00 Dubai: trend for each market + last 7 days' scorecard
  • Big-move warnings when a 15-min candle is unusually large
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

import signals as S

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
STATE_FILE, LOG_FILE = "state.json", "signals.csv"
LOG_FIELDS = ["time", "market", "side", "entry", "stop", "target", "status", "exit", "exit_time", "r"]
DUBAI = timezone(timedelta(hours=4))
BRIEF_HOUR = 10
BIG_MOVE_COOLDOWN = timedelta(hours=1)
ARROW = {"UP": "UP ↑", "DOWN": "DOWN ↓", "SIDEWAYS": "SIDEWAYS →"}


# ───────── helpers ─────────
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_log():
    try:
        with open(LOG_FILE, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def save_log(rows):
    with open(LOG_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)


def notify(title, body, tags="", priority="default"):
    print(f"--- {title}\n{body}\n")
    if DRY_RUN or not NTFY_TOPIC:
        return
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
                      headers={"Title": title, "Tags": tags, "Priority": priority},
                      timeout=15).raise_for_status()
    except Exception as e:
        print(f"notify failed: {e}")


def fetch(symbol, period, interval, tries=3):
    import yfinance as yf
    err = None
    for i in range(tries):
        try:
            df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and not df.empty:
                return df.tz_convert("UTC")
        except Exception as e:
            err = e
        time.sleep(4 * (i + 1))
    raise RuntimeError(f"no data for {symbol}: {err}")


def load_market(key, intraday_period="5d", hourly_period="6mo"):
    sym = S.MARKETS[key]["symbol"]
    bars = fetch(sym, intraday_period, "15m")
    hourly = fetch(sym, hourly_period, "1h")
    ctx = S.daily_context(S.daily_from_hourly(hourly))
    return S.build(bars, ctx)


def f(key, x):
    return S.MARKETS[key]["fmt"].format(x)


# ───────── messages ─────────
def signal_message(key, row):
    side, entry, stop, target = row["signal"], row["Close"], row["stop"], row["target"]
    risk, reward = abs(entry - stop), abs(target - entry)
    name = S.MARKETS[key]["name"]
    title = f"{side} {name}"
    body = (
        f"Entry   {f(key, entry)}\n"
        f"Stop    {f(key, stop)}   (risk {f(key, risk)})\n"
        f"Target  {f(key, target)}   (reward {f(key, reward)})\n\n"
        f"Trend {row['trend'].lower()} · pullback {'bought' if side == 'BUY' else 'sold'} · "
        f"{row['range_used']:.0%} of a normal day used\n"
        f"Good for ~30 min. Keep risk to 1% of your account."
    )
    tags = "green_circle" if side == "BUY" else "red_circle"
    return title, body, tags


def result_message(key, trade):
    name = S.MARKETS[key]["name"]
    r = float(trade["r"])
    word = {"TARGET": "hit target", "STOP": "stopped out", "TIME": "closed after 6h"}[trade["status"]]
    title = f"{name} {trade['side']} {word}"
    body = (f"{r:+.1f}R   ({f(key, float(trade['entry']))} → {f(key, float(trade['exit']))})")
    tags = "white_check_mark" if r > 0 else "x"
    return title, body, tags


def scorecard(rows, now, days=7):
    cutoff = now - timedelta(days=days)
    done = [r for r in rows if r["status"] not in ("OPEN", "") and
            datetime.fromisoformat(r["time"]) >= cutoff]
    if not done:
        return "No closed trades in the last 7 days yet."
    wins = sum(float(r["r"]) > 0 for r in done)
    total = sum(float(r["r"]) for r in done)
    return f"Last 7 days: {len(done)} trades · {wins} wins · {total:+.1f}R"


# ───────── main loop ─────────
def run(data=None, now=None):
    now = now or datetime.now(timezone.utc)
    now_dubai = now.astimezone(DUBAI)
    state = load_json(STATE_FILE, {})
    log = load_log()
    brief_lines = []

    for key in S.MARKETS:
        ms = state.setdefault(key, {})
        try:
            b = data[key] if data else load_market(key)
        except Exception as e:
            print(f"{key}: skipped ({e})")
            continue
        closed = b[b.index + S.BAR <= now]
        if closed.empty:
            continue

        # 1) New signals and big moves on candles closed since the last check
        last = ms.get("last_bar")
        new = closed[closed.index > pd.Timestamp(last)] if last else closed.tail(1)
        new = new[new.index >= now - timedelta(minutes=45)]   # ignore stale candles
        for ts, row in new.iterrows():
            if row["signal"]:
                notify(*signal_message(key, row), priority="high")
                log.append({"time": ts.isoformat(), "market": key, "side": row["signal"],
                            "entry": row["Close"], "stop": row["stop"], "target": row["target"],
                            "status": "OPEN", "exit": "", "exit_time": "", "r": ""})
            elif row["big_move"]:
                prev = ms.get("last_big_move")
                if not prev or now - datetime.fromisoformat(prev) >= BIG_MOVE_COOLDOWN:
                    direction = "up" if row["Close"] > row["Open"] else "down"
                    notify(f"{S.MARKETS[key]['name']} big move {direction}",
                           f"15-min candle {row['move_x']:.1f}x normal size. Price {f(key, row['Close'])}.\n"
                           f"Today has used {row['range_used']:.0%} of a normal day's range.",
                           tags="zap")
                    ms["last_big_move"] = now.isoformat()
        ms["last_bar"] = closed.index[-1].isoformat()

        # 2) Follow open trades to their result
        for t in log:
            if t["market"] != key or t["status"] != "OPEN":
                continue
            ts = pd.Timestamp(t["time"])
            if ts not in closed.index:
                continue
            i = closed.index.get_loc(ts)
            res = S.outcome(closed, i, t["side"], float(t["entry"]), float(t["stop"]), float(t["target"]))
            if res:
                status, exit_price, exit_time = res
                t.update(status=status, exit=exit_price, exit_time=exit_time.isoformat(),
                         r=round(S.r_multiple(t["side"], float(t["entry"]), float(t["stop"]), exit_price), 2))
                notify(*result_message(key, t))

        # 3) Line for the daily brief
        lr = closed.iloc[-1]
        trend = lr["trend"] if isinstance(lr["trend"], str) else "SIDEWAYS"
        note = "" if trend != "SIDEWAYS" else " — no signals"
        brief_lines.append(f"{S.MARKETS[key]['name']:<10}{ARROW[trend]}  · normal day {f(key, lr['adr'])}{note}")

    # 4) Daily brief once a day
    today = now_dubai.date().isoformat()
    if now_dubai.hour >= BRIEF_HOUR and state.get("brief_day") != today and brief_lines:
        notify("Daily brief", "\n".join(brief_lines) + "\n\n" + scorecard(log, now), tags="sunrise")
        state["brief_day"] = today

    with open(STATE_FILE, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    save_log(log)


if __name__ == "__main__":
    if "--test" in sys.argv:
        notify("NAS100 alerts are working", "Test notification from your GitHub monitor.", "white_check_mark")
    else:
        run()
