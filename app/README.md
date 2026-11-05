# EDGEHOG app

- `lib/execution.ts` — execution cost engine: mid, spread, slippage (book walk), fee (measured table,
  docs formula, or exact quote), all in USD, non-overlapping; post-trade realized cost and markouts.
- `lib/execution.test.ts` — `npm test` (Node ≥ 22.18 runs TypeScript directly, no install needed).
- `scripts/preview.ts` — `npm run preview -- POLY-<gamma id>-<0|1>`: live 100/500/1000 USD ladder for a
  Jupiter market from the Polymarket book, plus the raw Jupiter `/orderbook` response if
  `JUPITER_API_KEY` is set. Written offline; first live run is part of the spike.

The 4–5 % figure in the research is the cost of ONE entry versus the mid, not a round trip.
- `lib/pmamm.ts` — pm-AMM LP simulator (Paradigm dynamic pm-AMM, same math as the Solana program):
  reserves, pool value, L0 for a deposit, simulation on any price path with released liquidity, LVR,
  fees and inventory P&L as separate lines (identity tested), Gaussian-score paths for what-ifs.
  Tests reproduce the paper: E[W_T] ≈ W0/2, uniform expected LVR in time.
- `scripts/lp_sim.ts` — `node scripts/lp_sim.ts <poly_hist.json> 1000 0`: dynamic vs static pm-AMM on a
  real Polymarket price history (SIMULATED, the pool did not exist there).
- `scripts/report_offline.ts` — per-wallet / all-wallet execution report from the research data;
  examples in `reports/`.
