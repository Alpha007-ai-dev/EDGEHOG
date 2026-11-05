# What do Solana prediction-market traders actually pay?

**EDGEHOG research, November 2026.** Statistical estimates from public data (Jupiter Prediction API,
Polymarket and Kalshi public APIs). Not investment advice and not a rating of any person.

> We tried to find alpha. We couldn't prove it. So we measured what traders actually pay.

## Data
- **16,683 fills** of 125 Jupiter Predict leaderboard wallets and 7 ordinary wallets (snapshot 2026-11-04).
- **8,701 Polymarket trades routed by Jupiter**, 1–4 Nov 2026 (all Jupiter flow, any wallet).
- Polymarket trade tapes and order books for the same markets; Kalshi order books for 44 matched games.
- Four hypotheses were tested; three of them with a protocol written down **before** the run (in `HANDOFF.md`).

## The headline: execution cost
| | fills | value at mid | spread + slippage | Jupiter fee | **total** | % of value |
|---|---:|---:|---:|---:|---:|---:|
| all measured fills | 10,487 | $1,443,281 | $29,132 | $37,544 | **$66,676** | **4.62 %** |
| live (in-play) | 8,727 | $1,130,172 | $25,308 | $30,329 | $55,637 | 4.92 % |
| pre-match | 1,760 | $313,109 | $3,825 | $7,214 | $11,039 | 3.53 % |
| contracts priced < $0.20 | 1,926 | $49,776 | $2,254 | $3,588 | $5,842 | **11.74 %** |

- This is the cost of **one entry** versus the Polymarket mid just before the fill, not a round trip.
- Across 102 wallets (≥ 10 measured fills): median **4.26 %**, 10th–90th percentile 2.0 %–7.0 %.
- **Jupiter adds no price markup:** 537 of 600 sampled Jupiter fills were matched to their own
  Polymarket execution (median 2 s apart) at exactly the same price. All routed flow goes through
  one Polymarket proxy wallet. The price cost is Polymarket's spread; on top comes Jupiter's fee
  (measured ≈ 0.05 · p · (1 − p) per contract at the median, about 2.3 % of volume on average).
- Order to Polymarket execution: median **5 s** (10–90 %: 4–7 s).

## What did NOT hold up
| Hypothesis | Test | Result |
|---|---|---|
| Leaderboard P&L shows skill | CLV per wallet, market-clustered errors | P&L vs CLV correlation **≈ 0.02**. 2 of ~71 decidable wallets look positive, ≈ 1.6 expected by chance |
| Jupiter flow is less informed than Polymarket's own flow | Pre-registered, 4,136 live trades, matched controls | **+0.34 ± 0.19 pp** at 5 min → inconclusive; the sign flips with the control window. Jupiter flow's own 5-min markout ≈ 0 |
| Cheapest-venue routing (Polymarket vs Kalshi) | 44 matched games, $50–$2,000 | Liquid markets: median difference **0.5 pp** (≈ the fee gap); thin markets: big gaps but ~85 % one way (Jupiter cheaper). **No arbitrage after fees** |
| Order flow predicts price (absorption, pre-event signals) | Pre-registered, 169 live markets, 21k one-minute bars | Absorption → 15 min: **−0.28 ± 0.69 pp** (274 vs 254, a coin flip). Delta continuation +0.21 ± 0.06 pp / 5 min — real but far below the cost of a trade. Score jumps are not visible in the flow beforehand |

## So what
- The leaderboard measures luck over short windows; execution cost is a sure, measurable drag.
- Cheap longshots are the most expensive place to trade (fee + spread ≈ 12 % per entry).
- Live trading costs more than pre-match.
- Jupiter is usually the cheaper Solana route to the same game than Kalshi-based apps.

**EDGEHOG** turns this into a tool: a pre-trade cost preview in dollars, a post-trade execution report
and replay per wallet, and an LP desk for the pm-AMM.

## Method notes and limits
- Mid = average of the last taker buy and sell on Polymarket in the 5 minutes before the fill; the
  minute price series lags in live markets and is used only pre-match.
- Error bars are cluster-robust by market; ~95 % = 2 errors. Medians reported where tails dominate.
- Spread and slippage are measured together after the fact (no book snapshot at fill time); the
  pre-trade preview splits them from the live book.
- The Kalshi side used Kalshi's book and taker fee; DFlow's own fee is not included (lower bound).
- One snapshot day for the wallet data; a weekly out-of-sample check is planned.
