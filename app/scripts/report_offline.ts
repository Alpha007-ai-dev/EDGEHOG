/**
 * Offline execution report from the research data (no network).
 *   node scripts/report_offline.ts <fills_clv.csv> <flow_rows.csv> <wallet|ALL> [out.md]
 * fills_clv.csv (probe.py): price, contracts, Jupiter fee per fill.
 * flow_rows.csv (flow.py, samples S1L/S1P): the Polymarket mid just before each fill and the
 * mid 1/5/15 min later, both for the side the trader bought (selling YES = buying NO).
 * Cost vs mid here = spread + slippage together (no book snapshot at fill time) + Jupiter fee.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { realizedCost, markout } from "../lib/execution.ts";

function parseCsv(path: string): Record<string, string>[] {
  const text = readFileSync(path, "utf8").replace(/^﻿/, "");
  const rows: string[][] = [];
  let row: string[] = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') q = false;
      else cell += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...body] = rows;
  return body.filter((r) => r.length === head.length).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i]])));
}

const num = (x: string | undefined) => (x === undefined || x === "" || x === "None" ? NaN : Number(x));
const [fillsPath, flowPath, wallet = "ALL", outPath] = process.argv.slice(2);
if (!fillsPath || !flowPath) {
  console.error("Használat: node scripts/report_offline.ts fills_clv.csv flow_rows.csv <tárca|ALL> [kimenet.md]");
  process.exit(1);
}

type Row = {
  owner: string; market: string; t: number; phase: string; contracts: number;
  sidePrice: number; sideMid: number; feeUsd: number;
  m1: number; m5: number; m15: number; latency: number;
};

// join: same owner + market + contracts, nearest time (flow t0 = Polymarket execution time)
const fills = parseCsv(fillsPath);
const byKey = new Map<string, Record<string, string>[]>();
for (const f of fills) {
  const k = `${f.owner}|${f.market}|${num(f.n).toFixed(2)}`;
  (byKey.get(k) ?? byKey.set(k, []).get(k)!).push(f);
}
const rows: Row[] = [];
for (const r of parseCsv(flowPath)) {
  if (!["S1L", "S1P"].includes(r.sample) || r.measurable !== "1") continue;
  if (wallet !== "ALL" && r.owner !== wallet) continue;
  const cands = byKey.get(`${r.owner}|${r.market}|${num(r.n).toFixed(2)}`) ?? [];
  const t0 = num(r.t0);
  const f = cands.sort((a, b) => Math.abs(num(a.t) - t0) - Math.abs(num(b.t) - t0))[0];
  if (!f || Math.abs(num(f.t) - t0) > 120) continue;
  rows.push({
    owner: r.owner, market: r.market, t: num(f.t), phase: r.phase, contracts: num(r.n),
    sidePrice: num(r.side_price), sideMid: num(r.side_mid0), feeUsd: num(f.fee) || 0,
    m1: num(r.jup_pp_1m), m5: num(r.jup_pp_5m), m15: num(r.jup_pp_15m), latency: num(r.lat_pm),
  });
}
if (!rows.length) { console.error("Nincs mérhető kötés ehhez a tárcához."); process.exit(1); }

// every fill is a "buy" of the side the trader ended up holding, so BUY formulas apply
const per = rows.map((r) => {
  const c = realizedCost({ price: r.sidePrice, contracts: r.contracts, feeUsd: r.feeUsd, action: "BUY" }, r.sideMid);
  return {
    ...r, notional: r.contracts * r.sideMid, priceCost: c.priceCostUsd, total: c.totalUsd,
    mk5: Number.isFinite(r.m5) ? markout("BUY", r.sideMid, r.sideMid + r.m5, r.contracts).usd : NaN,
  };
});
const sum = (xs: number[]) => xs.filter(Number.isFinite).reduce((a, b) => a + b, 0);
const usd = (x: number) => (x < 0 ? "−" : "") + "$" + Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 });
const pct = (x: number) => (100 * x).toFixed(2) + "%";
const median = (xs: number[]) => { const s = xs.filter(Number.isFinite).sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : NaN; };

function block(label: string, xs: typeof per) {
  const notional = sum(xs.map((x) => x.notional));
  const pc = sum(xs.map((x) => x.priceCost)), fee = sum(xs.map((x) => x.feeUsd)), tot = pc + fee;
  return `| ${label} | ${xs.length} | ${usd(notional)} | ${usd(pc)} | ${usd(fee)} | **${usd(tot)}** | ${pct(tot / notional)} | ${usd(sum(xs.map((x) => x.mk5)))} |`;
}

const short = (w: string) => (w === "ALL" ? "összes vizsgált tárca" : `${w.slice(0, 4)}…${w.slice(-4)}`);
const lines: string[] = [];
lines.push(`# EDGEHOG végrehajtási riport – ${short(wallet)}`, "");
lines.push("Statisztikai becslés nyilvános adatokból. A költség EGY belépés költsége a kötés előtti Polymarket-középárhoz képest", "(spread + csúszás együtt, mert a kötés pillanatáról nincs könyv-pillanatkép), plusz a Jupiter díja. Nem oda-vissza költség.", "");
lines.push("| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |");
lines.push("|---|---:|---:|---:|---:|---:|---:|---:|");
lines.push(block("mind", per));
lines.push(block("élő", per.filter((x) => x.phase === "live")));
lines.push(block("meccs előtt", per.filter((x) => x.phase === "pre")));
lines.push("", "**Ár szerint** (a kötött oldal középára):", "");
lines.push("| | kötés | érték a középáron | spread + csúszás | Jupiter-díj | összesen | a forgalom %-a | 5 perces markout |");
lines.push("|---|---:|---:|---:|---:|---:|---:|---:|");
for (const [lo, hi] of [[0, 0.2], [0.2, 0.4], [0.4, 0.6], [0.6, 0.8], [0.8, 1]]) {
  const xs = per.filter((x) => x.sideMid >= lo && x.sideMid < hi);
  if (xs.length) lines.push(block(`${lo.toFixed(1)}–${hi.toFixed(1)}`, xs));
}
const lat = median(per.map((x) => x.latency));
lines.push("", `Végrehajtási idő (Jupiter-megbízás → Polymarket-kötés), medián: ${Number.isFinite(lat) ? lat.toFixed(0) + " mp" : "n.a."}.`);
if (wallet !== "ALL") {
  lines.push("", "**A 5 legdrágább kötés** (összes költség):", "", "| idő (UTC) | piac | fázis | kontraktus | ár | közép | spread + csúszás | díj | 5p markout |", "|---|---|---|---:|---:|---:|---:|---:|---:|");
  for (const x of [...per].sort((a, b) => b.total - a.total).slice(0, 5)) {
    lines.push(`| ${new Date(x.t * 1000).toISOString().slice(0, 16).replace("T", " ")} | ${x.market} | ${x.phase === "live" ? "élő" : "előtte"} | ${x.contracts.toFixed(0)} | ${x.sidePrice.toFixed(3)} | ${x.sideMid.toFixed(3)} | ${usd(x.priceCost)} | ${usd(x.feeUsd)} | ${usd(x.mk5)} |`);
  }
} else {
  // distribution across wallets
  const byW = new Map<string, typeof per>();
  for (const x of per) (byW.get(x.owner) ?? byW.set(x.owner, []).get(x.owner)!).push(x);
  const shares = [...byW.values()].filter((xs) => xs.length >= 10).map((xs) => (sum(xs.map((x) => x.priceCost)) + sum(xs.map((x) => x.feeUsd))) / sum(xs.map((x) => x.notional))).sort((a, b) => a - b);
  const q = (p: number) => shares[Math.min(shares.length - 1, Math.floor(p * shares.length))];
  lines.push("", `**Tárcák közötti eloszlás** (legalább 10 mérhető kötés, ${shares.length} tárca): a forgalom %-ában fizetett költség`, `10%: ${pct(q(0.1))}, medián: ${pct(q(0.5))}, 90%: ${pct(q(0.9))}.`);
}
lines.push("", `_Forrás: ${rows.length} mérhető kötés a 2026-11-04-i probe-ból (flow.py S1L/S1P), Polymarket-középár a saját kötéslistájából._`);
const md = lines.join("\n") + "\n";
if (outPath) writeFileSync(outPath, md);
console.log(md);
