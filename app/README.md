# EDGEHOG app

- `lib/execution.ts` — execution cost engine: mid, spread, slippage (book walk), fee (measured table,
  docs formula, or exact quote), all in USD, non-overlapping; post-trade realized cost and markouts.
- `lib/execution.test.ts` — `npm test` (Node ≥ 22.18 runs TypeScript directly, no install needed).
- `scripts/preview.ts` — `npm run preview -- POLY-<gamma id>-<0|1>`: live 100/500/1000 USD ladder for a
  Jupiter market from the Polymarket book, plus the raw Jupiter `/orderbook` response if
  `JUPITER_API_KEY` is set. Written offline; first live run is part of the spike.

The 4–5 % figure in the research is the cost of ONE entry versus the mid, not a round trip.
