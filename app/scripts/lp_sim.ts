/**
 * LP Desk what-if: a pm-AMM LP position simulated on a real Polymarket price history.
 *   node scripts/lp_sim.ts <poly_hist.json> [depositUsd=1000] [feeBps=0]
 * poly_hist.json = [{t, p}, …] (Polymarket prices-history, as cached by probe.py).
 * The pool did not exist on that market: results are SIMULATED, not measured PnL.
 */
import { readFileSync } from "node:fs";
import { simulate, gaussianScorePath, mulberry32 } from "../lib/pmamm.ts";

const [file, dep = "1000", fee = "0"] = process.argv.slice(2);
const hist: { t: number; p: number }[] = JSON.parse(readFileSync(file, "utf8")).map((h: any) => ({ t: Number(h.t), p: Number(h.p) }));
hist.sort((a, b) => a.t - b.t);
const t0 = hist[0].t, T = (hist[hist.length - 1].t - t0) / 3600;          // hours
const path = hist.map((h) => ({ t: (h.t - t0) / 3600, p: h.p }));
const W0 = Number(dep), feeBps = Number(fee);
const usd = (x: number) => (x < 0 ? "−$" : "$") + Math.abs(x).toFixed(2);

console.log(`Piac-ártörténet: ${path.length} pont, ${T.toFixed(1)} óra, ár ${path[0].p.toFixed(3)} → ${path[path.length - 1].p.toFixed(3)}`);
console.log(`Befizetés: ${usd(W0)}, díj: ${feeBps} bps  (SZIMULÁCIÓ – a pool ezen a piacon nem létezett)\n`);
for (const dynamic of [true, false]) {
  const r = simulate(path, { W0, T, dynamic, feeBps });
  console.log(`${dynamic ? "Dinamikus pm-AMM (L = L0·√(T−t))" : "Statikus pm-AMM (L állandó)     "}:  ` +
    `ármozgás a készleten ${usd(r.inventory)} | LVR −${usd(r.lvr)} | díj ${usd(r.fees)} → visszaadott ${usd(r.released)} + maradék ${usd(r.finalPoolValue)} = ` +
    `LP vagyon ${usd(r.lpWealth)} (${(100 * r.lpReturn).toFixed(1)}%)`);
}
// what-if: same horizon, 300 Gaussian-score paths from the same start price
const rand = mulberry32(1);
const ws = Array.from({ length: 300 }, () => simulate(gaussianScorePath(T, 300, rand, path[0].p), { W0, T, feeBps }).lpWealth).sort((a, b) => a - b);
console.log(`\nÖsszevetés: 300 véletlen pálya ugyanebből az árból (Gaussian score): LP vagyon medián ${usd(ws[150])}, ` +
  `10%: ${usd(ws[30])}, 90%: ${usd(ws[270])}; elmélet: E[W_T] = W0/2 = ${usd(W0 / 2)} díj nélkül.`);
