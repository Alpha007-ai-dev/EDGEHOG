import { test } from "node:test";
import assert from "node:assert/strict";
import { estimate, midPrice, sideLevels, sizeLadder, feePerContract, realizedCost, markout, type Book } from "./execution.ts";

const book: Book = {
  bids: [{ price: 0.48, size: 500 }, { price: 0.47, size: 1000 }, { price: 0.45, size: 5000 }],
  asks: [{ price: 0.52, size: 400 }, { price: 0.53, size: 600 }, { price: 0.56, size: 5000 }],
};
const near = (a: number, b: number, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("mid and NO-side mid", () => {
  near(midPrice(book)!, 0.5);
  near(midPrice(book, "NO")!, 0.5);
});

test("NO asks are flipped YES bids, cheapest first", () => {
  const l = sideLevels(book, "NO", "BUY");
  near(l[0].price, 0.52); near(l[1].price, 0.53); near(l[2].price, 0.55);
});

test("small buy: only spread + fee, no slippage", () => {
  const e = estimate(book, "YES", "BUY", 100, { kind: "docs", builderRate: 0.02 })!;
  near(e.contracts, 100 / 0.52);
  near(e.spreadUsd, e.contracts * 0.02);
  near(e.slippageUsd, 0);
  near(e.feeUsd, e.contracts * 0.02 * 0.52);
  near(e.totalUsd, e.spreadUsd + e.slippageUsd + e.feeUsd);
});

test("large buy walks the book: slippage > 0 and parts add up", () => {
  const e = estimate(book, "YES", "BUY", 1000)!;
  assert.ok(e.slippageUsd > 0);
  near(e.totalUsd, e.spreadUsd + e.slippageUsd + e.feeUsd);
  assert.ok(e.avgFill > 0.52 && e.avgFill < 0.56);
});

test("sell: costs are positive when selling below mid", () => {
  const e = estimate(book, "YES", "SELL", 300)!;
  near(e.spreadUsd, 300 * 0.02);
  assert.ok(e.totalUsd > 0);
});

test("measured fee: current formula vs legacy table", () => {
  near(feePerContract(0.5, { kind: "measured" }), 0.0181 * 0.5 + 0.052 * 0.25);
  near(feePerContract(0.5, { kind: "measured-legacy" }), 0.0125);
  assert.ok(feePerContract(0.9, { kind: "measured" }) > 4 * feePerContract(0.9, { kind: "measured-legacy" }));
});

test("ladder returns three sizes and cost grows with size", () => {
  const l = sizeLadder(book, "YES");
  assert.equal(l.length, 3);
  assert.ok(l[2]!.totalUsd > l[0]!.totalUsd);
});

test("post-trade realized cost and markout", () => {
  const r = realizedCost({ price: 0.52, contracts: 100, feeUsd: 1.25, action: "BUY" }, 0.5);
  near(r.priceCostUsd, 2); near(r.totalUsd, 3.25);
  near(markout("BUY", 0.5, 0.55, 100).usd, 5);
  near(markout("SELL", 0.5, 0.55, 100).usd, -5);
});
