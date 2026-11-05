/**
 * pm-AMM LP simulator (Paradigm, Moallemi & Robinson 2024; Solana program GV1FMGHRYBjQLaghE5fnGuYCuCcpdt3GD5xEX3TwN16y).
 *
 * Invariant: (y − x)·Φ((y − x)/L) + L·φ((y − x)/L) − y = 0,  x = YES reserve, y = NO reserve.
 * At YES price P, with u = Φ⁻¹(P):
 *   x = L·(u·P + φ(u) − u),  y = L·(u·P + φ(u)),  pool value V = P·x + (1−P)·y = L·φ(u).
 * Dynamic version: L_eff(t) = L0·√(T − t). As L shrinks, reserves scale down and the released
 * YES+NO tokens go to LPs (the program's dC_t accrual). Theory: LVR_t = V_t / (2(T−t)),
 * E[LVR_t] = V0/(2T) (uniform in time), E[W_T] = W0/2 under Gaussian score dynamics.
 *
 * Per step the simulator records, in USD, as separate lines (never netted):
 *   released  value of tokens released to the LP (valued at the market price when released)
 *   lvr       loss to arbitrageurs when the pool re-prices to the external price
 *   fees      swap fees on the arbitrage volume (feeBps; 0 if the pool charges none)
 *   inventory gain/loss on the pool's YES/NO inventory from the price move, before re-pricing
 * Identity: W0 + inventory − lvr + fees = released + fees + final pool value (= LP wealth).
 * Labels: results on a historical path are SIMULATED (the pool did not exist then), not measured PnL.
 */

// ------------------------------------------------------------- normal distribution
const SQRT2PI = Math.sqrt(2 * Math.PI);
export const phi = (z: number) => Math.exp(-0.5 * z * z) / SQRT2PI;

/** Standard normal CDF (erfc via Chebyshev fit, |error| < 1.2e-7). */
export function Phi(z: number): number {
  const x = Math.abs(z) / Math.SQRT2;
  const t = 1 / (1 + 0.5 * x);
  const erfc = t * Math.exp(-x * x - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
    t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return z >= 0 ? 1 - 0.5 * erfc : 0.5 * erfc;
}

/** Inverse normal CDF (Acklam, relative error < 1.2e-9 after one Newton step). */
export function PhiInv(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  let x: number;
  if (p < lo) {
    const q = Math.sqrt(-2 * Math.log(p));
    x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  } else if (p <= 1 - lo) {
    const q = p - 0.5, r = q * q;
    x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  } else {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const e = Phi(x) - p;                                    // one Newton refinement
  return x - e * SQRT2PI * Math.exp(0.5 * x * x);
}

// ------------------------------------------------------------- pool math
export function reserves(P: number, L: number) {
  const u = PhiInv(P);
  return { x: L * (u * P + phi(u) - u), y: L * (u * P + phi(u)), value: L * phi(u) };
}
export const poolValue = (P: number, L: number) => L * phi(PhiInv(P));

/** L0 so that the first deposit of W0 USD at price P0 with horizon T (any time unit) is fully used. */
export const l0ForDeposit = (W0: number, P0: number, T: number) => W0 / (Math.sqrt(T) * phi(PhiInv(P0)));

// ------------------------------------------------------------- simulation
export type PathPoint = { t: number; p: number };            // t in the same unit as T, from 0 to T
export type SimOptions = { W0: number; T: number; dynamic?: boolean; feeBps?: number; clamp?: number };
export type SimStep = { t: number; p: number; L: number; value: number; released: number; lvr: number; fees: number; volume: number; inventory: number };
export type SimResult = {
  steps: SimStep[];
  W0: number; finalPoolValue: number;          // value still in the pool at the last step (→ 0 at expiry for dynamic)
  released: number; lvr: number; fees: number; volume: number; inventory: number;
  lpWealth: number;                            // released + fees + final pool value (released tokens assumed sold at the time)
  lpReturn: number;                            // lpWealth / W0 − 1
  kind: "simulated";
};

/**
 * Run an LP position through a YES-price path. Arbitrageurs move the pool price to the path price
 * at every step. `clamp` keeps prices inside (clamp, 1−clamp) because Φ⁻¹ is infinite at 0 and 1.
 */
export function simulate(path: PathPoint[], o: SimOptions): SimResult {
  const dynamic = o.dynamic ?? true, fee = (o.feeBps ?? 0) / 1e4, eps = o.clamp ?? 1e-4;
  const cl = (p: number) => Math.min(1 - eps, Math.max(eps, p));
  const L0 = dynamic ? l0ForDeposit(o.W0, cl(path[0].p), o.T) : o.W0 / phi(PhiInv(cl(path[0].p)));
  const Lof = (t: number) => (dynamic ? L0 * Math.sqrt(Math.max(0, o.T - t)) : L0);
  const steps: SimStep[] = [];
  let p = cl(path[0].p), L = Lof(path[0].t), r = reserves(p, L);
  let released = 0, lvr = 0, fees = 0, volume = 0, inventory = 0;
  steps.push({ t: path[0].t, p, L, value: r.value, released: 0, lvr: 0, fees: 0, volume: 0, inventory: 0 });
  for (let i = 1; i < path.length; i++) {
    const pn = cl(path[i].p);
    // 1) arbitrage at the old L: pool re-prices from p to pn
    const after = reserves(pn, L);
    const before = pn * r.x + (1 - pn) * r.y;              // old reserves marked at the new price
    const inv = before - r.value;                          // = (x − y)·(pn − p): price-move gain on inventory
    const lossStep = Math.max(0, before - after.value);
    const vol = Math.abs(after.x - r.x) * (p + pn) / 2;    // YES traded, valued at the average price
    // 2) time passes: L shrinks, the difference is released to the LP (valued at pn)
    const Ln = Lof(path[i].t);
    const scaled = reserves(pn, Ln);
    const rel = Math.max(0, after.value - scaled.value);
    lvr += lossStep; inventory += inv; volume += vol; fees += fee * vol; released += rel;
    p = pn; L = Ln; r = scaled;
    steps.push({ t: path[i].t, p, L, value: r.value, released: rel, lvr: lossStep, fees: fee * vol, volume: vol, inventory: inv });
  }
  const last = path[path.length - 1];
  const finalPoolValue = last.t >= o.T - 1e-12 && dynamic ? 0 : r.value;
  const lpWealth = released + fees + finalPoolValue;
  return { steps, W0: o.W0, finalPoolValue, released, lvr, fees, volume, inventory, lpWealth, lpReturn: lpWealth / o.W0 - 1, kind: "simulated" };
}

/** Gaussian score dynamics from the paper: P_t = Φ(B_t / √(T−t)), B a Brownian motion (for tests / what-if). */
export function gaussianScorePath(T: number, steps: number, rand: () => number, p0 = 0.5): PathPoint[] {
  const dt = T / steps;
  let B = PhiInv(p0) * Math.sqrt(T);
  const out: PathPoint[] = [{ t: 0, p: p0 }];
  for (let i = 1; i <= steps; i++) {
    const u1 = Math.max(1e-12, rand()), u2 = rand();
    B += Math.sqrt(dt) * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    const t = i * dt;
    out.push({ t, p: i === steps ? (B > 0 ? 1 : 0) : Phi(B / Math.sqrt(T - t)) });
  }
  return out;
}

/** Deterministic PRNG for reproducible simulations. */
export function mulberry32(seed: number) {
  return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
