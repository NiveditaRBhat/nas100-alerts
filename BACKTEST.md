# Backtest results
_Period: 15 Sep – 23 Nov 2026 (15-min candles) · run 23 Nov 2026 12:28 UTC_

**R** = profit measured in units of risk. +2R = target hit, −1R = stopped out.
If you risk 1% of your account per trade, +10R ≈ +10%.

## Rules as live (with daily-range filter)
| Market | Trades | Win rate | Avg R | Total R | Profit factor | Worst run |
|---|---|---|---|---|---|---|
| NAS100 | 37 | 43% | +0.10 | +3.7 | 1.19 | -7.2R |
| Gold | 44 | 43% | +0.04 | +1.7 | 1.07 | -9.2R |
| Brent oil | 42 | 43% | -0.10 | -4.0 | 0.81 | -6.9R |
| **All** | 123 | 43% | +0.01 | +1.4 | 1.02 | -15.1R |

## Same rules without the daily-range filter
| Market | Trades | Win rate | Avg R | Total R | Profit factor | Worst run |
|---|---|---|---|---|---|---|
| NAS100 | 50 | 46% | +0.12 | +6.2 | 1.24 | -5.1R |
| Gold | 64 | 45% | +0.12 | +7.8 | 1.24 | -9.4R |
| Brent oil | 54 | 44% | -0.04 | -2.0 | 0.93 | -11.5R |

_Costs included: NAS100 2 pts, Gold 0.4, Brent 0.04 per trade. 60 days is a short sample — treat this as a first check, not proof._
