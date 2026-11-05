# EDGEHOG

Execution intelligence for Solana prediction markets (Jupiter Predict) — built for the Solana
Foundation "Perps and Prediction Markets" hackathon.

> We tried to find alpha. We couldn't prove it. So we built a tool to measure what traders actually pay.

**Start here:** [`HANDOFF.md`](HANDOFF.md) — the full project log: idea, every measurement, results,
rejected directions, the current product decision and next steps.

## Research (Python, in the repo root)
| Script | What it measures | Result file |
|---|---|---|
| `probe.py` + `score.py` | Per-wallet CLV with market-clustered error bars, gross vs net of Jupiter fee | `research/probe_report.txt` |
| `verify_premium.py` | Jupiter fill vs its own Polymarket execution; spread; minute-price lag | `research/premium_report.txt` |
| `midclv.py` | Mid-price markouts vs similar Polymarket trades (small sample) | `research/midclv_report.txt` |
| `flow.py` | Pre-registered flow test: all Jupiter-routed flow vs matched controls | `research/flow_report.txt` |
| `venue_probe.py` | Polymarket/Jupiter vs Kalshi all-in cost on the same games | `research/venue_report.txt` |
| `of_test.py` | Pre-registered order-flow test: absorption, pre-event signals | `research/orderflow_report.txt` |
| `collect.py` | Jupiter global trade feed collector (Windows scheduled task, every 2 min) | — |

The Jupiter API key is read from the `JUPITER_API_KEY` environment variable (or a local, git-ignored
`.jupkey` file). Never commit it.
