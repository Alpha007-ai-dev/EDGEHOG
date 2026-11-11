// EDGEHOG LP Desk – devnet end-to-end on the PREDICT pm-AMM (2026-11-11).
//
//   npm install && node lp_devnet.cjs        (run_devnet.bat does both)
//
// Devnet only: mock USDC (mUSDC) from the pm-AMM faucet, a throwaway keypair in ./devnet-wallet.json
// (git-ignored, never reuse on mainnet). Steps, each logged with its Solscan link:
//   1. wallet + faucet (1,000 mUSDC; devnet SOL from the faucet or a public airdrop)
//   2. create a 2-hour binary market at 50% with 50 mUSDC (we are its first LP and its authority)
//   3. second LP deposit of 100 mUSDC – shares vs the SDK's simulateLpDeposit prediction
//   4. three trades (buy YES 20, buy NO 10, buy YES 15): quoted vs received, price impact, 2% fee
//   5. wait, accrue, claim LP residuals (the dC_t release)
//   6. withdraw half the shares, redeem YES+NO pairs back to mUSDC
// Writes ../../output/devnet_lp.json (everything measured) and prints a readable log.

const fs = require("fs");
const path = require("path");
const { Connection, Keypair, PublicKey, LAMPORTS_PER_SOL } = require("@solana/web3.js");
const { AnchorProvider, Wallet, BN } = require("@anchor-lang/core");
const { getAssociatedTokenAddressSync } = require("@solana/spl-token");
const { PmAmmClient } = require("@pm-amm/sdk");
const M = require("@pm-amm/sdk/math");

const RPC = process.env.RPC_URL || "https://api.devnet.solana.com";
const APP = "https://pm-amm-devnet.vercel.app";
const PROGRAM_ID = new PublicKey("GV1FMGHRYBjQLaghE5fnGuYCuCcpdt3GD5xEX3TwN16y");
const USDC_MINT = new PublicKey("3WQ8hCqTNwjrh8WzE2XyoZoUrd1miPcwWfMkmFPUMEWZ");
const WALLET_FILE = path.join(__dirname, "devnet-wallet.json");
const OUT_FILE = path.join(__dirname, "..", "..", "output", "devnet_lp.json");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const tx = (sig) => `https://solscan.io/tx/${sig}?cluster=devnet`;

const report = { started: new Date().toISOString(), rpc: RPC, steps: [] };
function save() {
  fs.mkdirSync(path.dirname(OUT_FILE), { recursive: true });
  fs.writeFileSync(OUT_FILE, JSON.stringify(report, null, 1));
}
function step(name, data) {
  report.steps.push({ name, at: new Date().toISOString(), ...data });
  console.log(`\n## ${name}`);
  for (const [k, v] of Object.entries(data)) console.log(`   ${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`);
  save();
}

function loadWallet() {
  if (fs.existsSync(WALLET_FILE)) {
    return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(WALLET_FILE, "utf8"))));
  }
  const kp = Keypair.generate();
  fs.writeFileSync(WALLET_FILE, JSON.stringify(Array.from(kp.secretKey)));
  return kp;
}

async function tokenBal(conn, mint, owner) {
  try {
    const r = await conn.getTokenAccountBalance(getAssociatedTokenAddressSync(mint, owner));
    return Number(r.value.uiAmount);
  } catch {
    return 0;
  }
}

async function balances(conn, client, market, owner) {
  const b = {
    sol: (await conn.getBalance(owner)) / LAMPORTS_PER_SOL,
    usdc: await tokenBal(conn, USDC_MINT, owner),
  };
  if (market) {
    b.yes = await tokenBal(conn, client.yesMint(market), owner);
    b.no = await tokenBal(conn, client.noMint(market), owner);
  }
  return b;
}

function marketState(m) {
  const now = Math.floor(Date.now() / 1000);
  const remaining = Math.max(m.endTs.toNumber() - now, 1);
  const lZero = M.i80f48ToNumber(m.lZero);
  const lEff = lZero * Math.sqrt(remaining);
  const x = M.i80f48ToNumber(m.reserveYes);
  const y = M.i80f48ToNumber(m.reserveNo);
  const price = M.priceFromReserves(x, y, lEff);
  return {
    price, x, y, lZero, lEff, remainingSecs: remaining,
    poolValueMicro: M.poolValue(price, lEff),
    totalShares: m.totalLpShares.toString(),
    expectedDailyLvrMicro: M.expectedDailyLvr(price, lEff, remaining),
  };
}

async function position(client, market, owner) {
  const p = await client.fetchLpPosition(market, owner);
  if (!p) return null;
  return {
    shares: p.shares.toString(),
    collateralDeposited: Number(p.collateralDeposited.toString()) / 1e6,
    excessYes: Number((p.excessYes ?? 0).toString()) / 1e6,
    excessNo: Number((p.excessNo ?? 0).toString()) / 1e6,
  };
}

async function fund(conn, owner) {
  const out = {};
  if ((await tokenBal(conn, USDC_MINT, owner)) < 200) {
    const res = await fetch(`${APP}/api/faucet`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ wallet: owner.toBase58() }),
    });
    const body = await res.json().catch(() => ({}));
    out.faucet = { status: res.status, ...body };
    if (res.ok && body.signature) await conn.confirmTransaction(body.signature, "confirmed");
  }
  if ((await conn.getBalance(owner)) < 0.06 * LAMPORTS_PER_SOL) {
    try {
      const sig = await conn.requestAirdrop(owner, 1 * LAMPORTS_PER_SOL);
      await conn.confirmTransaction(sig, "confirmed");
      out.airdrop = tx(sig);
    } catch (e) {
      out.airdrop = `refused: ${String(e.message).split("\n")[0]}`;
    }
  }
  return out;
}

async function trade(conn, client, market, owner, direction, usdc) {
  const side = direction === "usdcToYes" ? "yes" : "no";
  const before = await balances(conn, client, market, owner);
  const s0 = marketState(await client.fetchMarket(market));
  const amountIn = Math.round(usdc * 1e6);
  // estimateSwapOutput is fee-unaware: quote on 98% of the input (2% fee on the USDC leg)
  const q = M.estimateSwapOutput(s0.x, s0.y, s0.lEff, amountIn * 0.98, side);
  const quoted = Number(q.output) / 1e6;
  const sig = await client.send.swap(market, direction, amountIn, Math.floor(Number(q.output) * 0.98));
  await sleep(1500);
  const after = await balances(conn, client, market, owner);
  const s1 = marketState(await client.fetchMarket(market));
  const received = after[side] - before[side];
  const mid = side === "yes" ? s0.price : 1 - s0.price;
  const avg = usdc / received;
  return {
    tx: tx(sig), direction, usdcIn: usdc,
    quotedTokens: quoted, receivedTokens: received,
    midBefore: mid, avgPrice: avg, priceAfterYes: s1.price,
    // cost vs mid, the same definition as the Jupiter research: contracts × (avg − mid)
    costVsMidUsdc: received * (avg - mid),
    costVsMidPct: (100 * (avg - mid)) / mid,
    feeUsdc: usdc * 0.02,
    note: "half of the fee goes to the creator (= this wallet here), half to the protocol DAO",
  };
}

async function main() {
  const conn = new Connection(RPC, "confirmed");
  const kp = loadWallet();
  const owner = kp.publicKey;
  report.wallet = owner.toBase58();
  console.log(`wallet ${report.wallet} (devnet)`);

  step("1. funding", { ...(await fund(conn, owner)), balances: await balances(conn, null, null, owner) });
  if ((await conn.getBalance(owner)) < 0.05 * LAMPORTS_PER_SOL) {
    step("STOP", { reason: "no devnet SOL – paste the wallet into https://faucet.solana.com, then run again", wallet: report.wallet });
    return;
  }

  const provider = new AnchorProvider(conn, new Wallet(kp), { commitment: "confirmed" });
  const client = PmAmmClient.fromProvider(provider, PROGRAM_ID, USDC_MINT);

  const created = await client.send.createMarket({
    name: `EDGEHOG LP test ${new Date().toISOString().slice(0, 16)}`,
    durationSecs: 7200,
    initialPriceBps: 5000,
    depositUsdc: 50,
  });
  const market = new PublicKey(created.marketPda);
  report.market = { pda: created.marketPda, id: String(created.marketId), app: `${APP}/market/${created.marketId}` };
  step("2. market created + first LP deposit (50 mUSDC)", {
    market: report.market, tx: created.signature ? tx(created.signature) : "(see wallet history)",
    state: marketState(await client.fetchMarket(market)), position: await position(client, market, owner),
    balances: await balances(conn, client, market, owner),
  });

  const s = marketState(await client.fetchMarket(market));
  const posBefore = await position(client, market, owner);
  const sim = M.simulateLpDeposit(100e6, s.price, s.lEff, Number(s.totalShares), s.remainingSecs, s.lZero);
  const sigDep = await client.send.depositLiquidity(market, 100);
  await sleep(1500);
  const posAfter = await position(client, market, owner);
  step("3. second LP deposit (100 mUSDC)", {
    tx: tx(sigDep), predictedNewSharesRatio: sim.newShares / Number(s.totalShares),
    actualNewSharesRatio: Number(BigInt(posAfter.shares) - BigInt(posBefore.shares)) / Number(BigInt(posBefore.shares)),
    position: posAfter, state: marketState(await client.fetchMarket(market)),
    balances: await balances(conn, client, market, owner),
  });

  const trades = [];
  for (const [dir, usd] of [["usdcToYes", 20], ["usdcToNo", 10], ["usdcToYes", 15]]) {
    try {
      trades.push(await trade(conn, client, market, owner, dir, usd));
    } catch (e) {
      trades.push({ direction: dir, usdcIn: usd, error: String(e.message).split("\n")[0] });
    }
  }
  step("4. trades", { trades, state: marketState(await client.fetchMarket(market)) });

  console.log("\nwaiting 90 s so the pool releases some liquidity (dC_t)…");
  await sleep(90_000);
  const b0 = await balances(conn, client, market, owner);
  let accrueTx = null, claimTx = null, claimErr = null;
  try {
    accrueTx = tx(await client.send.accrue(market));
    claimTx = tx(await client.send.claimLpResiduals(market));
  } catch (e) {
    claimErr = String(e.message).split("\n")[0];
  }
  await sleep(1500);
  const b1 = await balances(conn, client, market, owner);
  step("5. accrue + claim LP residuals", {
    accrueTx, claimTx, error: claimErr,
    releasedYes: b1.yes - b0.yes, releasedNo: b1.no - b0.no,
    state: marketState(await client.fetchMarket(market)),
  });

  const pos = await client.fetchLpPosition(market, owner);
  const half = pos.shares.div(new BN(2));
  const w0 = await balances(conn, client, market, owner);
  const sigW = await client.send.withdrawLiquidity(market, half);
  await sleep(1500);
  const w1 = await balances(conn, client, market, owner);
  const pairs = Math.floor(Math.min(w1.yes, w1.no) * 1e6);
  let redeemTx = null;
  if (pairs > 0) redeemTx = tx(await client.send.redeemPair(market, pairs));
  await sleep(1500);
  const w2 = await balances(conn, client, market, owner);
  step("6. withdraw half the shares + redeem pairs", {
    tx: tx(sigW), redeemTx,
    withdrawnYes: w1.yes - w0.yes, withdrawnNo: w1.no - w0.no, withdrawnUsdc: w1.usdc - w0.usdc,
    redeemedUsdc: w2.usdc - w1.usdc, position: await position(client, market, owner),
    balances: w2, state: marketState(await client.fetchMarket(market)),
  });
  report.finished = new Date().toISOString();
  save();
  console.log(`\nKESZ – ${OUT_FILE}`);
}

main().catch((e) => {
  report.error = String(e && e.stack ? e.stack : e);
  save();
  console.error(e);
  process.exit(1);
});
