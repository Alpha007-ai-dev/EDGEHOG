import { test } from "node:test";
import assert from "node:assert/strict";
import { Phi, PhiInv, phi, reserves, simulate, gaussianScorePath, mulberry32, l0ForDeposit } from "./pmamm.ts";

const near = (a: number, b: number, eps: number, msg = "") => assert.ok(Math.abs(a - b) <= eps, `${msg} ${a} vs ${b}`);

test("normal functions are consistent", () => {
  for (const p of [0.001, 0.02, 0.2, 0.5, 0.77, 0.99]) near(Phi(PhiInv(p)), p, 1e-7, `p=${p}`);
  near(phi(0), 0.3989422804, 1e-9);
});

test("reserves satisfy the invariant and V = L·φ(u)", () => {
  for (const P of [0.1, 0.35, 0.5, 0.8]) {
    const L = 1234, { x, y, value } = reserves(P, L);
    const u = (y - x) / L;
    near((y - x) * Phi(u) + L * phi(u) - y, 0, 1e-6, "invariant");
    near(P * x + (1 - P) * y, value, 1e-6, "value");
    near(Phi(u), P, 1e-7, "marginal price");
  }
});

test("constant price: no LVR, the whole deposit is released back over time", () => {
  const T = 1, path = Array.from({ length: 1001 }, (_, i) => ({ t: (i / 1000) * T, p: 0.6 }));
  const r = simulate(path, { W0: 1000, T });
  near(r.lvr, 0, 1e-6, "lvr");
  near(r.lpWealth, 1000, 1e-6, "wealth");
});

test("paper property: E[W_T] ≈ W0/2 under Gaussian score dynamics (Monte Carlo)", () => {
  const rand = mulberry32(42), T = 1, runs = 400;
  let w = 0;
  for (let k = 0; k < runs; k++) w += simulate(gaussianScorePath(T, 400, rand), { W0: 1, T }).lpWealth;
  near(w / runs, 0.5, 0.05, "E[W_T]/W0");
});

test("paper property: expected LVR is uniform in time", () => {
  const rand = mulberry32(7), T = 1, runs = 300, n = 400;
  const halves = [0, 0];
  for (let k = 0; k < runs; k++) {
    const s = simulate(gaussianScorePath(T, n, rand), { W0: 1, T }).steps;
    for (const st of s) if (st.t > 0 && st.t < T * 0.98) halves[st.t < T * 0.49 ? 0 : 1] += st.lvr;
  }
  near(halves[1] / halves[0], 1, 0.15, "LVR second half / first half");
});

test("fees are a separate line and scale with feeBps", () => {
  const rand = mulberry32(3), path = gaussianScorePath(1, 200, rand);
  const a = simulate(path, { W0: 1000, T: 1, feeBps: 0 }), b = simulate(path, { W0: 1000, T: 1, feeBps: 30 });
  near(a.fees, 0, 1e-12); assert.ok(b.fees > 0);
  near(b.lpWealth - a.lpWealth, b.fees, 1e-9);
  near(a.lvr, b.lvr, 1e-9);
});

test("L0 for a deposit reproduces the deposit value", () => {
  const L0 = l0ForDeposit(500, 0.3, 4);
  near(L0 * Math.sqrt(4) * phi(PhiInv(0.3)), 500, 1e-9);
});

test("accounting identity: W0 + inventory − LVR + fees = LP wealth", () => {
  const rand = mulberry32(11);
  for (const dynamic of [true, false]) {
    const path = gaussianScorePath(2, 300, rand, 0.4).slice(0, 250);   // stop before expiry too
    const r = simulate(path, { W0: 1000, T: 2, dynamic, feeBps: 25 });
    near(r.W0 + r.inventory - r.lvr + r.fees, r.lpWealth, 1e-6, `dynamic=${dynamic}`);
  }
});
