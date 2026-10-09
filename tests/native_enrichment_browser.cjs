'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'data/native-enrichment-validation');
const groups = [12, 13, 14, 15].map((age) => `facial_11.5_${age}`);
const types = ['A3', 'A5', 'AF', 'AL', 'MX', 'RI', 'SE'];
const fixtures = {};
for (const mode of ['ora', 'compare']) {
  const images = groups.flatMap((group) => types.map((type) => ({
    name: `${group} / ${type}`, path: `output/${mode}/${group}_${type}.png`,
    comparison: group, event_type: type, kind: mode,
  })));
  if (mode === 'ora') {
    images.push(...images.filter((item) => !item.path.includes('_MX.')).map((item) => ({
      ...item, path: item.path.replace('.png', '_clusters.png'), kind: 'clusters',
    })));
  }
  fixtures[mode] = {
    job_id: `CHILD-${mode}`, images: { [mode]: images },
    files: [mode === 'ora' ? 'output/enrichment_GO_BP.csv' : 'output/enrichment_compare/GO_BP/comparison.csv'],
  };
}

(async () => {
  for (const mode of ['ora', 'compare']) assert.ok(fs.existsSync(path.join(output, `${mode}-A3.png`)));
  const server = http.createServer((request, response) => {
    const relative = request.url.split('?')[0] === '/' ? 'index.html' : request.url.split('?')[0].slice(1);
    const file = path.resolve(root, relative);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404); response.end(); return;
    }
    const mime = { '.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.png': 'image/png' };
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    fs.createReadStream(file).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport });
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/api/**', async (route) => {
        const request = route.request();
        const pathname = new URL(request.url()).pathname;
        if (pathname === '/api/health') return route.fulfill({ json: { status: 'ok', execution_mode: 'command' } });
        if (pathname.endsWith('/downstream')) {
          const mode = request.postDataJSON().params.mode;
          assert.equal(request.postDataJSON().params.database, 'GO_BP');
          return route.fulfill({ status: 202, json: { id: `CHILD-${mode}`, status: 'queued' } });
        }
        if (pathname.includes('/files/') && pathname.endsWith('.png')) {
          const mode = pathname.includes('CHILD-ora') ? 'ora' : 'compare';
          return route.fulfill({ contentType: 'image/png', body: fs.readFileSync(path.join(output, `${mode}-A3.png`)) });
        }
        if (pathname.includes('/files/') && pathname.endsWith('.csv')) {
          return route.fulfill({ contentType: 'text/csv', body: 'comparison,event_type,ID,GeneRatio,BgRatio\nsample,A3,GO:0043484,17/449,198/24292\n' });
        }
        if (pathname.endsWith('/results')) {
          return route.fulfill({ json: fixtures[pathname.includes('CHILD-ora') ? 'ora' : 'compare'] });
        }
        if (/\/api\/jobs\/CHILD-/.test(pathname)) return route.fulfill({ json: { status: 'completed' } });
        return route.fulfill({ status: 404, json: { error: 'Job not found' } });
      });
      await page.goto(`http://127.0.0.1:${server.address().port}`, { waitUntil: 'networkidle' });
      await page.evaluate(() => {
        window.ASTKStudio = { jobId: 'PARENT', jobContext: { status: 'completed' }, backendAvailable: true, showToast() {} };
        window.ASTKDownstream.refresh();
        document.querySelector('[data-view="downstream"]').click();
      });
      assert.equal(await page.locator('[data-param="database"] option').count(), 1);
      for (const mode of ['ora', 'compare']) {
        await page.locator(`[data-enrichment-mode="${mode}"]`).click();
        await page.locator(`[data-run="${mode}"]`).click();
        const result = page.locator(`[data-result="${mode}"]`);
        await result.locator('.downstream-figure').nth(27).waitFor();
        assert.equal(await result.locator('.downstream-figure').count(), 28);
        assert.equal(await result.locator('table').count(), 0);
        await result.locator('[data-filter="comparison"]').selectOption(groups[0]);
        assert.equal(await result.locator('.downstream-figure').count(), 7);
        await result.locator('[data-filter="event_type"]').selectOption('A3');
        assert.equal(await result.locator('.downstream-figure').count(), 1);
        if (mode === 'ora') {
          await result.locator('[data-filter="kind"]').selectOption('clusters');
          assert.equal(await result.locator('.downstream-figure').count(), 1);
          await result.locator('[data-filter="kind"]').selectOption('ora');
        }
        await result.locator('img').scrollIntoViewIfNeeded();
        await page.waitForFunction((m) => [...document.querySelectorAll(`[data-result="${m}"] img`)].every((img) => img.complete && img.naturalWidth > 0), mode);
        const csv = await result.locator('a[download]').evaluate(async (a) => {
          const response = await fetch(a.href);
          return { ok: response.ok, text: await response.text() };
        });
        assert.ok(csv.ok && csv.text.includes('GeneRatio'));
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        assert.equal(overflow, false, `overflow at ${viewport.width} in ${mode}`);
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
        await page.screenshot({ path: path.join(output, `${mode}-browser-${viewport.width}.png`), fullPage: true });
      }
      assert.deepEqual(errors, []);
      console.log(JSON.stringify({ viewport, primaryPlotsPerMode: 28, groupFilter: 7, eventFilter: 1, clustersLoaded: true, pageErrors: errors }));
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
