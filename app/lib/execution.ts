/**
 * EDGEHOG execution cost engine (pure functions, no network).
 *
 * Splits the cost of a prediction-market order into non-overlapping parts, in USD:
 *   spread   = contracts × (best price − mid)        what crossing half the spread costs
 *   slippage = contracts × (average fill − best)     extra cost from walking the book for size
 *   fee      = contracts × fee per contract          Jupiter builder fee + Polymarket platform fee
 *   total    = spread + slippage + fee               cost of ONE entry vs the mid (not round trip)
 *
 * Prices are per contract in $ (0..1). A book is for the YES token; the NO side is derived
 * (NO ask = 1 − YES bid, NO bid = 1 − YES ask).
 */

export type Level = { price: number; size: number }; // size in contracts
export type Book = { bids: Level[]; asks: Level[] };   // YES token
export type Outcome = "YES" | "NO";
export type Action = "BUY" | "SELL";

/** Measured Jupiter fee per contract ($) by price bucket (median of 15 985 fills, 2026-11-04). */
export const MEASURED_FEE_TABLE: number[] = [
  0.0009, 0.0037, 0.0060, 0.0077, 0.0091, 0.0105, 0.0112, 0.0119, 0.0123, 0.0125,
  0.0125, 0.0123, 0.0119, 0.0112, 0.0103, 0.0091, 0.0077, 0.0060, 0.0045, 0.0024,
];

export type FeeModel =
  | { kind: "measured" }                                    // our own median per 0.05 price bucket
  | { kind: "docs"; builderRate?: number; platformFeePerContract?: number } // 2 % builder + platform fee
  | { kind: "quote"; feeUsd: number };                     // exact fee from a Jupiter /orders quote

export function feePerContract(price: number, model: FeeModel, contracts = 1): number {
  switch (model.kind) {
    case "measured":
      return MEASURED_FEE_TABLE[Math.min(19, Math.max(0, Math.floor(price * 20)))];
    case "docs":
      return (model.builderRate ?? 0.02) * price + (model.platformFeePerContract ?? 0);
    case "quote":
      return contracts > 0 ? model.feeUsd / contracts : 0;
  }
}

/** The side of the book you trade against, expressed in the chosen outcome's prices. */
export function sideLevels(book: Book, outcome: Outcome, action: Action): Level[] {
  const flip = (ls: Level[]) => ls.map((l) => ({ price: 1 - l.price, size: l.size }));
  // buying YES hits YES asks; buying NO hits NO asks = flipped YES bids; selling is the mirror
  const raw =
    outcome === "YES" ? (action === "BUY" ? book.asks : book.bids) : action === "BUY" ? flip(book.bids) : flip(book.asks);
  const valid = raw.filter((l) => l.price > 0 && l.price < 1 && l.size > 0);
  return valid.sort((a, b) => (action === "BUY" ? a.price - b.price : b.price - a.price));
}

export function midPrice(book: Book, outcome: Outcome = "YES"): number | null {
  const bid = Math.max(...book.bids.filter((l) => l.size > 0).map((l) => l.price), -Infinity);
  const ask = Math.min(...book.asks.filter((l) => l.size > 0).map((l) => l.price), Infinity);
  if (!isFinite(bid) || !isFinite(ask) || ask < bid) return null;
  const m = (bid + ask) / 2;
  return outcome === "YES" ? m : 1 - m;
}

export type Fill = { contracts: number; avgPrice: number; bestPrice: number; worstPrice: number; filledUsd: number; unfilledUsd: number; levels: number };

/** Walk the book for a USD amount (buy) or a contract amount (sell). */
export function walk(levels: Level[], amount: number, action: Action): Fill | null {
  if (!levels.length || amount <= 0) return null;
  let left = amount, n = 0, usd = 0, used = 0, worst = levels[0].price;
  for (const l of levels) {
    if (left <= 1e-9) break;
    const take = action === "BUY" ? Math.min(l.size, left / l.price) : Math.min(l.size, left);
    n += take;
    usd += take * l.price;
    left -= action === "BUY" ? take * l.price : take;
    worst = l.price;
    used++;
  }
  if (n <= 0) return null;
  const unfilled = Math.max(0, left) * (action === "BUY" ? 1 : levels[levels.length - 1].price);
  return { contracts: n, avgPrice: usd / n, bestPrice: levels[0].price, worstPrice: worst, filledUsd: usd, unfilledUsd: unfilled, levels: used };
}

export type Estimate = {
  outcome: Outcome; action: Action; requestedUsd: number;
  mid: number; best: number; avgFill: number; contracts: number;
  notionalAtMid: number;            // contracts × mid
  spreadUsd: number; slippageUsd: number; feeUsd: number; totalUsd: number;
  totalPctOfNotional: number;       // total / notionalAtMid
  effectivePrice: number;           // average all-in price per contract (buy: higher is worse)
  unfilledUsd: number;              // part of the order the visible book could not fill
  feeModel: FeeModel["kind"];
};

/**
 * Pre-trade estimate. For BUY, `amount` is USD to spend; for SELL, `amount` is contracts to sell.
 * Costs are always positive numbers = money lost versus trading at the mid.
 */
export function estimate(book: Book, outcome: Outcome, action: Action, amount: number, model: FeeModel = { kind: "measured" }): Estimate | null {
  const mid = midPrice(book, outcome);
  const levels = sideLevels(book, outcome, action);
  const f = walk(levels, amount, action);
  if (mid === null || !f) return null;
  const sgn = action === "BUY" ? 1 : -1;               // selling: lower price = worse
  const spreadUsd = f.contracts * sgn * (f.bestPrice - mid);
  const slippageUsd = f.contracts * sgn * (f.avgPrice - f.bestPrice);
  const feePc = feePerContract(f.avgPrice, model, f.contracts);
  const feeUsd = f.contracts * feePc;
  const totalUsd = spreadUsd + slippageUsd + feeUsd;
  const notional = f.contracts * mid;
  return {
    outcome, action, requestedUsd: action === "BUY" ? amount : amount * mid,
    mid, best: f.bestPrice, avgFill: f.avgPrice, contracts: f.contracts,
    notionalAtMid: notional, spreadUsd, slippageUsd, feeUsd, totalUsd,
    totalPctOfNotional: notional > 0 ? totalUsd / notional : NaN,
    effectivePrice: f.avgPrice + sgn * feePc,
    unfilledUsd: f.unfilledUsd, feeModel: model.kind,
  };
}

/** The 100 / 500 / 1 000 USD ladder from the spec. */
export function sizeLadder(book: Book, outcome: Outcome, sizes = [100, 500, 1000], model: FeeModel = { kind: "measured" }) {
  return sizes.map((usd) => estimate(book, outcome, "BUY", usd, model));
}

/** Post-trade: what an executed fill actually cost versus the mid at that moment. */
export function realizedCost(fill: { price: number; contracts: number; feeUsd: number; action: Action }, midAtFill: number) {
  const sgn = fill.action === "BUY" ? 1 : -1;
  const priceCostUsd = fill.contracts * sgn * (fill.price - midAtFill); // spread + slippage together
  return { priceCostUsd, feeUsd: fill.feeUsd, totalUsd: priceCostUsd + fill.feeUsd, pctOfNotional: (priceCostUsd + fill.feeUsd) / (fill.contracts * midAtFill) };
}

/** Markout: how the mid moved in the trader's favour after h seconds (in $ per contract and total). */
export function markout(action: Action, midAtFill: number, midLater: number, contracts: number) {
  const sgn = action === "BUY" ? 1 : -1;
  const perContract = sgn * (midLater - midAtFill);
  return { perContract, usd: perContract * contracts };
}
