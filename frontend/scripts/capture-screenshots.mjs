/**
 * Capture README/demo screenshots from a running local stack.
 *
 * Prerequisites: API on :8000, frontend dev server on :3000, and a seeded
 * database (scripts/seed_demo_data.py + scripts/seed_demo_flagship.py).
 *
 *   cd frontend && npm run screenshots
 *
 * Writes PNGs to docs/screenshots/.
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const OUT = resolve(ROOT, "docs/screenshots");
const BASE = process.env.BASE_URL || "http://localhost:3000";
const EMAIL = process.env.DEMO_EMAIL || "admin@autonomoussdr.com";
const PASSWORD = process.env.DEMO_PASSWORD || "changeme123";

const SHOTS = [
  // The dashboard holds an open SSE stream, so "networkidle" never fires.
  { name: "dashboard", path: "/", wait: 3500, until: "domcontentloaded" },
  { name: "approvals-fact-check", path: "/approvals", wait: 2500 },
  // Each campaign card fires a second, per-campaign detail query for the
  // plan and totals; give it room to land before shooting.
  { name: "campaign-agent", path: "/campaigns", wait: 6000 },
  { name: "backtest-calibration", path: "/backtests", wait: 2500 },
  // Select a lead so the execution trace panel has something in it.
  { name: "pipeline", path: "/pipeline", wait: 3000, clickAfter: "text=Aisha Kamara" },
  // The dev server proxies /leads straight to the API, so a hard navigation
  // there renders JSON. Reach it through in-app routing instead.
  { name: "leads", path: "/leads", wait: 2500, navLink: "Leads" },
  { name: "analytics", path: "/analytics", wait: 2500 },
  { name: "inbox", path: "/inbox", wait: 2500 },
];

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 1000 },
  deviceScaleFactor: 2, // retina — screenshots stay sharp when scaled down
});
const page = await context.newPage();

// --- login ---------------------------------------------------------------
await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await Promise.all([
  page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 20000 }),
  page.click('button[type="submit"]'),
]);
console.log("logged in");

// --- capture -------------------------------------------------------------
for (const shot of SHOTS) {
  try {
    if (shot.navLink) {
      await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(1500);
      await page.click(`nav a:has-text("${shot.navLink}")`);
      await page.waitForURL(`**${shot.path}`, { timeout: 15000 });
    } else {
      await page.goto(`${BASE}${shot.path}`, { waitUntil: shot.until || "networkidle" });
    }
    await page.waitForTimeout(shot.wait);
    if (shot.clickAfter) {
      await page.click(shot.clickAfter);
      await page.waitForTimeout(2500);
    }
    const file = resolve(OUT, `${shot.name}.png`);
    await page.screenshot({ path: file });
    console.log(`captured ${shot.name}`);
  } catch (err) {
    console.error(`FAILED ${shot.name}: ${err.message}`);
  }
}

await browser.close();
console.log(`\nScreenshots written to docs/screenshots/`);
