'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.SMOKE_URL || 'http://127.0.0.1:4180';
  const out = path.resolve(process.env.SMOKE_OUTPUT || 'data/enrichment-browser');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(base, { waitUntil: 'networkidle' });
      await page.evaluate(() => {
        window.ASTKStudio = { jobId: 'PARENT', jobContext: { status: 'completed' }, backendAvailable: true, showToast() {} };
        window.ASTKDownstream.refresh();
        document.querySelector('[data-view="downstream"]').click();
      });
      const ora = page.locator('[data-result="ora"]');
      await page.locator('[data-run="ora"]').click();
      await ora.locator('.downstream-figure').nth(13).waitFor({ timeout: 90000 });
      assert.equal(await ora.locator('table').count(), 0);
      assert.equal(await ora.locator('.downstream-figure').count(), 14);
      for (const img of await ora.locator('img').all()) {
        const response = await page.request.get(new URL(await img.getAttribute('src'), base).toString());
        assert.equal(response.status(), 200);
        assert.ok((await response.body()).length > 1000);
      }
      assert.equal(await page.locator('[data-module="motif"]').count(), 0);
      await ora.locator('[data-filter="comparison"]').selectOption('facial_11.5_12');
      assert.equal(await ora.locator('.downstream-figure').count(), 7);
      await ora.locator('[data-filter="event_type"]').selectOption('SE');
      assert.equal(await ora.locator('.downstream-figure').count(), 1);
      const image = ora.locator('img');
      await image.scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll('[data-result="ora"] img')].every((img) => img.complete && img.naturalWidth > 0));
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.screenshot({ path: path.join(out, `ora-${viewport.width}.png`), fullPage: true });
      const csv = await page.request.get(new URL(await ora.locator('a[download]').getAttribute('href'), base).toString());
      assert.equal(csv.status(), 200);
      assert.ok((await csv.text()).includes('significant'));
      await page.locator('[data-enrichment-mode="compare"]').click();
      await page.locator('[data-run="compare"]').click();
      const compare = page.locator('[data-result="compare"]');
      await compare.locator('.downstream-figure').nth(1).waitFor({ timeout: 90000 });
      for (const img of await compare.locator('img').all()) await img.scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll('[data-result="compare"] img')].every((img) => img.complete && img.naturalWidth > 0));
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.screenshot({ path: path.join(out, `compare-${viewport.width}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      assert.equal(overflow, false, `horizontal overflow at ${viewport.width}`);
      const clipped = await page.evaluate(() => [...document.querySelectorAll('#downstream-view button, #downstream-view figcaption')].filter((el) => el.getClientRects().length && el.scrollWidth > el.clientWidth + 2).map((el) => el.textContent));
      assert.deepEqual(clipped, []);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ viewport, oraFigures: 14, filteredFigures: 1, compareFigures: 2, imagesLoaded: true, overflow, pageErrors: errors }));
      await page.close();
    }
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
