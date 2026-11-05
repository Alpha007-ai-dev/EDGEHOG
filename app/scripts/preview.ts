/**
 * Live pre-trade preview for one Jupiter Predict market (Polymarket-sourced).
 *   node scripts/preview.ts POLY-6575126-0            (or a Polymarket gamma market id)
 * Fetches the Polymarket order book behind the Jupiter market (Jupiter fills at the Polymarket
 * price, see research/premium_report.txt), runs the cost engine for 100 / 500 / 1000 USD, and —
 * if JUPITER_API_KEY is set — prints the raw Jupiter /orderbook response for comparison.
 * Not tested against live endpoints yet (written offline on 2026-11-05).
 */
import { estimate, type Book, type Outcome } from "../lib/execution.ts";

const arg = process.argv[2] ?? "";
const m = /^POLY-(\d+)(?:-(\d))?$/.exec(arg) ?? /^(\d+)$/.exec(arg);
if (!m) {
  console.error("Használat: node scripts/preview.ts POLY-<gamma id>-<0|1>");
  process.exit(1);
}
const gid = m[1];
const idx = Number(m[2] ?? 0);

const meta = await (await fetch(`https://gamma-api.polymarket.com/markets/${gid}`)).json();
const tokens: string[] = typeof meta.clobTokenIds === "string" ? JSON.parse(meta.clobTokenIds) : meta.clobTokenIds;
const outcomes: string[] = typeof meta.outcomes === "string" ? JSON.parse(meta.outcomes) : meta.outcomes;
const raw = await (await fetch(`https://clob.polymarket.com/book?token_id=${tokens[idx]}`)).json();
const book: Book = {
  bids: (raw.bids ?? []).map((l: any) => ({ price: Number(l.price), size: Number(l.size) })),
  asks: (raw.asks ?? []).map((l: any) => ({ price: Number(l.price), size: Number(l.size) })),
};

console.log(`${meta.question}  —  kimenet: ${outcomes?.[idx]}  (YES = ez a kimenet)\n`);
const usd = (x: number) => `$${x.toFixed(2)}`;
for (const outcome of ["YES", "NO"] as Outcome[]) {
  console.log(`${outcome} vétel`);
  console.log("  méret     kontr.   közép  átl.ár  spread   csúszás  díj     összesen  % a középhez");
  for (const size of [100, 500, 1000]) {
    const e = estimate(book, outcome, "BUY", size);
    if (!e) { console.log(`  $${size}: nincs elég adat a könyvben`); continue; }
    console.log(`  $${String(size).padEnd(7)} ${e.contracts.toFixed(0).padStart(6)}   ${e.mid.toFixed(3)}  ${e.avgFill.toFixed(3)}  ` +
      `${usd(e.spreadUsd).padStart(7)}  ${usd(e.slippageUsd).padStart(7)}  ${usd(e.feeUsd).padStart(6)}  ${usd(e.totalUsd).padStart(8)}  ` +
      `${(100 * e.totalPctOfNotional).toFixed(2)}%${e.unfilledUsd > 0 ? `  (nem teljesíthető: ${usd(e.unfilledUsd)})` : ""}`);
  }
  console.log();
}

const key = process.env.JUPITER_API_KEY;
if (key && /^POLY-/.test(arg)) {
  const r = await fetch(`https://api.jup.ag/prediction/v1/orderbook/${arg}`, { headers: { "x-api-key": key } });
  console.log(`Jupiter /orderbook/${arg}: HTTP ${r.status}`);
  console.log((await r.text()).slice(0, 1500));
}
