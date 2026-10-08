/* ASTK Studio — Downstream analysis framework (enrichment / motif). 2026-10-08
 *
 * Frontend framework for the "富集分析" (enrichment) workspace. It wires
 * the documented downstream API contract and provides the module UI. Real
 * results require the downstream backend:
 *
 *   POST /api/jobs/{parent_id}/downstream   {module, params}  -> 202 {id,status}
 *   GET  /api/jobs/{id}                       -> {status: queued|running|completed|failed, progress, error}
 *   GET  /api/jobs/{id}/results               -> {module, job_id, parent_job_id, params, summary, table, images, files}
 *   GET  /api/jobs/{id}/files/{path}          -> result figure (PNG)
 *
 * The framework stays honest: when no completed base analysis / backend is
 * available it disables execution and offers a clearly-labelled sample preview
 * of the result layout instead of inventing data.
 */
(() => {
  'use strict';

  const state = { parentId: null, ready: false, busy: {}, backend: false, poll: {} };
  const POLL_MS = 2500;
  const MAX_POLLS = 600; // ~25 min ceiling

  const MODULES = {
    enrichment: {
      params: (card) => ({
        gene_set: card.querySelector('[data-param="gene_set"]')?.value || 'significant',
        database: card.querySelector('[data-param="database"]')?.value || 'GO_BP',
        pvalue: card.querySelector('[data-param="pvalue"]')?.value || '0.05',
        qvalue: card.querySelector('[data-param="qvalue"]')?.value || '0.05',
      }),
    },
    motif: {
      params: (card) => ({
        event_type: card.querySelector('[data-param="event_type"]')?.value || 'SE',
        region: card.querySelector('[data-param="region"]')?.value || 'flank-200',
      }),
    },
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function studio() { return window.ASTKStudio || null; }
  function icons() { try { window.lucide?.createIcons?.(); } catch (_) {} }
  function toast(msg) { const s = studio(); if (s?.showToast) s.showToast(msg); }
  function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function num(v) { const n = Number(v); return Number.isFinite(n) ? n.toLocaleString() : String(v ?? ''); }

  /* ---- context / gate ---------------------------------------------------- */

  function refreshContext() {
    const s = studio();
    const jobId = s?.jobId || null;
    const status = s?.jobContext?.status || null;
    state.backend = !!s?.backendAvailable;
    state.parentId = jobId;
    state.ready = !!(state.backend && jobId && status === 'completed');
    renderGate(status, jobId);
    const cta = $('#downstream-cta');
    if (cta) cta.hidden = !state.ready;
  }

  function renderGate(status, jobId) {
    const gate = $('#downstream-gate');
    let cls = 'warn';
    let icon = 'info';
    let msg;
    if (!state.backend) {
      msg = '当前为演示模式：连接私有服务器并完成一次基础分析后，即可启用富集与 motif 分析。';
    } else if (!jobId) {
      msg = '尚未提交基础分析任务，请先在「分析工作台」运行一次分析。';
    } else if (status !== 'completed') {
      msg = '基础分析任务尚未完成，完成后即可继续富集分析。';
    } else {
      cls = 'ok';
      icon = 'check-circle-2';
      msg = `基础分析已完成 · 任务 ${jobId}，可继续运行富集与 motif 分析。`;
    }
    if (gate) {
      gate.className = `downstream-notice ${cls}`;
      const span = gate.querySelector('span');
      if (span) span.textContent = msg;
      const i = gate.querySelector('i');
      if (i) i.setAttribute('data-lucide', icon);
    }
    $$('[data-run]').forEach((b) => { b.disabled = !state.ready || !!state.busy[b.dataset.run]; });
    $$('[data-card-status]').forEach((node) => {
      node.textContent = state.ready ? '就绪 READY' : '等待基础分析';
      node.classList.toggle('ready', state.ready);
    });
    icons();
  }

  /* ---- result rendering -------------------------------------------------- */

  function summaryEntries(summary) {
    if (!summary) return [];
    if (Array.isArray(summary)) return summary.map((it) => [it.label ?? it.key ?? '', it.value ?? '']);
    if (typeof summary === 'object') return Object.entries(summary);
    return [];
  }

  function figureItems(results) {
    const out = [];
    const imgs = results?.images || {};
    const jid = results?.job_id || results?.id || state.busy.__activeId;
    if (!jid) return out;
    const push = (arr, label) => {
      if (!arr) return;
      const list = Array.isArray(arr) ? arr : [arr];
      list.forEach((it) => {
        const path = typeof it === 'string' ? it : (it?.path || it?.name);
        if (!path) return;
        const name = (typeof it === 'object' && it?.name) || label || 'figure';
        out.push({ label: name, src: `/api/jobs/${encodeURIComponent(jid)}/files/${path}` });
      });
    };
    if (Array.isArray(imgs)) push(imgs, 'figure');
    else Object.entries(imgs).forEach(([k, v]) => push(v, k));
    return out;
  }

  function tableData(results) {
    const t = results?.table;
    if (!t) return null;
    if (Array.isArray(t)) {
      if (!t.length) return null;
      const rows = t.map((r) => (Array.isArray(r) ? r : [r]));
      return { header: rows[0], rows: rows.slice(1) };
    }
    if (Array.isArray(t.rows)) return { header: t.header || t.columns || null, rows: t.rows };
    return null;
  }

  function renderSummary(summary) {
    const entries = summaryEntries(summary);
    if (!entries.length) return '';
    return `<div class="downstream-summary">${entries.map(([k, v]) =>
      `<div><span>${esc(k)}</span><strong>${esc(num(v))}</strong></div>`).join('')}</div>`;
  }

  function renderFigures(results) {
    const figs = figureItems(results);
    if (!figs.length) return '';
    return `<div class="downstream-figures">${figs.map((f) =>
      `<figure class="downstream-figure"><img src="${esc(f.src)}" alt="${esc(f.label)}" loading="lazy" /><span>${esc(f.label)}</span></figure>`).join('')}</div>`;
  }

  function renderTable(results) {
    const data = tableData(results);
    if (!data || !data.rows.length) return '';
    const head = data.header
      ? `<thead><tr>${data.header.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>`
      : '';
    const rows = data.rows.slice(0, 100).map((r) =>
      `<tr>${(Array.isArray(r) ? r : [r]).map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('');
    return `<div class="downstream-table-wrap"><table>${head}<tbody>${rows}</tbody></table></div>`;
  }

  function downloadItems(results) {
    const out = [];
    const jid = results?.job_id || results?.id || state.busy.__activeId;
    if (!jid) return out;
    const files = results?.files;
    if (!files) return out;
    const list = Array.isArray(files) ? files : [files];
    const base = results?.module === 'motif' ? 'motif' : 'enrichment';
    list.forEach((it, i) => {
      const path = typeof it === 'string' ? it : (it?.path || it?.name);
      if (!path) return;
      const label = (typeof it === 'object' && it?.name) || `${base} 结果表`;
      out.push({ label, href: `/api/jobs/${encodeURIComponent(jid)}/files/${path}` });
    });
    return out;
  }

  function renderDownloads(results) {
    const items = downloadItems(results);
    if (!items.length) return '';
    return `<div class="downstream-downloads">${items.map((d) =>
      `<a class="button secondary downstream-download" href="${esc(d.href)}" download><span class="downstream-download-icon" aria-hidden="true">⭳</span>${esc(d.label)}</a>`).join('')}</div>`;
  }

  function renderResult(moduleId, payload) {
    const box = $(`[data-result="${moduleId}"]`);
    if (!box) return;
    box.classList.toggle('is-preview', payload.state === 'preview');
    if (payload.state === 'running') {
      box.innerHTML = `<div class="downstream-status"><span class="spinner" aria-hidden="true"></span><span>${esc(payload.message || '正在运行…')}</span></div>`;
      return;
    }
    if (payload.state === 'error') {
      box.innerHTML = `<div class="downstream-notice error"><span>${esc(payload.message || '分析失败')}</span></div>`;
      return;
    }
    const badge = payload.state === 'preview'
      ? `<div class="downstream-badge-sample"><span>●</span> 示例预览 · EXAMPLE</div>`
      : '';
    const results = payload.results || {};
    const downloads = payload.state === 'done' ? renderDownloads(results) : '';
    const body = renderSummary(results.summary) + renderFigures(results) + renderTable(results) + downloads;
    box.innerHTML = badge + (body || `<div class="downstream-empty">${esc(payload.message || '结果将在此处显示。')}</div>`);
    icons();
  }

  /* ---- run --------------------------------------------------------------- */

  async function runModule(moduleId) {
    const card = $(`.downstream-card[data-module="${moduleId}"]`);
    if (!card) return;
    if (!state.ready) { toast('请先完成基础分析'); return; }
    state.busy[moduleId] = true;
    renderGate(null, state.parentId);
    renderResult(moduleId, { state: 'running', message: '正在提交富集分析任务…' });
    try {
      const params = MODULES[moduleId].params(card);
      const res = await fetch(`/api/jobs/${encodeURIComponent(state.parentId)}/downstream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module: moduleId, params }),
      });
      if (!res.ok) {
        let detail = '';
        try { detail = (await res.json())?.error || ''; } catch (_) {}
        throw new Error(detail || `提交失败（HTTP ${res.status}）`);
      }
      const job = await res.json();
      const childId = job.id || job.job_id;
      state.busy.__activeId = childId;
      renderResult(moduleId, { state: 'running', message: `任务已排队 · ${childId}` });
      const final = await pollJob(childId, moduleId);
      if (final.status !== 'completed') throw new Error(final.error || '任务失败');
      const rres = await fetch(`/api/jobs/${encodeURIComponent(childId)}/results?t=${Date.now()}`, { cache: 'no-store' });
      if (!rres.ok) throw new Error('结果尚未生成');
      const results = await rres.json();
      renderResult(moduleId, { state: 'done', results });
      toast('富集分析完成');
    } catch (err) {
      renderResult(moduleId, { state: 'error', message: err.message || '分析失败' });
      toast(err.message || '分析失败');
    } finally {
      state.busy[moduleId] = false;
      renderGate(null, state.parentId);
    }
  }

  async function pollJob(jobId, moduleId) {
    for (let i = 0; i < MAX_POLLS; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      let job;
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}?t=${Date.now()}`, { cache: 'no-store' });
        if (!res.ok) continue;
        job = await res.json();
      } catch (_) { continue; }
      if (job.status === 'completed' || job.status === 'failed') return job;
      renderResult(moduleId, { state: 'running', message: job.stage || (job.status === 'queued' ? '排队中…' : '正在运行…') });
    }
    return { status: 'failed', error: '分析超时' };
  }

  /* ---- sample preview (labelled) ----------------------------------------- */

  const SAMPLE = {
    enrichment: {
      summary: { '输入基因数': 181, '显著通路数': 24, '数据库': 'GO_BP', 'FDR 阈值': '0.05' },
      images: { 'go_bp_bubble.png': 'GO 富集气泡图（示例）' },
      table: {
        header: ['term', 'description', 'overlap', 'p_value', 'fdr'],
        rows: [
          ['GO:0008380', 'RNA splicing', '42/320', '1.2e-11', '3.4e-09'],
          ['GO:0000398', 'mRNA splicing, via spliceosome', '31/210', '5.8e-09', '6.1e-07'],
          ['GO:0006397', 'mRNA processing', '48/560', '2.3e-07', '1.7e-05'],
        ],
      },
    },
    motif: {
      summary: { '事件类型': 'SE', '序列区域': 'flank-200', '扫描事件': 181, '富集 motif': 6 },
      images: { 'motif_bar.png': 'RBP motif 富集柱状图（示例）' },
      table: {
        header: ['motif', 'rbp', 'foreground', 'background', 'p_value'],
        rows: [
          ['UGCAUGU', 'RBFOX2', '38/181', '210/52118', '4.1e-12'],
          ['CUGCCUG', 'PTBP1', '27/181', '305/52118', '8.7e-08'],
          ['UUGUUU', 'hnRNPA1', '22/181', '412/52118', '6.0e-06'],
        ],
      },
    },
  };

  function previewModule(moduleId) {
    renderResult(moduleId, {
      state: 'preview',
      message: '示例预览：真实结果需在私有服务器模式完成基础分析后运行。',
      results: SAMPLE[moduleId],
    });
    toast('已载入示例预览（非真实结果）');
  }

  /* ---- wiring ------------------------------------------------------------ */

  function bind() {
    $$('[data-run]').forEach((b) =>
      b.addEventListener('click', () => runModule(b.dataset.run)));
    $$('[data-preview]').forEach((b) =>
      b.addEventListener('click', () => previewModule(b.dataset.preview)));
    $('#downstream-refresh')?.addEventListener('click', () => { refreshContext(); toast('已刷新分析上下文'); });
    $('#downstream-cta-button')?.addEventListener('click', () => { $('[data-view="downstream"]')?.click(); });

    // Keep the gate fresh: base analysis updates, and returning to the view.
    document.addEventListener('astk:job-updated', () => refreshContext());
    document.addEventListener('click', (e) => {
      const nav = e.target.closest('.nav-item[data-view="downstream"]');
      if (nav) refreshContext();
    });
  }

  function init() {
    if (!$('#downstream-view')) return;
    bind();
    refreshContext();
    icons();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  // Expose for debugging / manual refresh.
  window.ASTKDownstream = { refresh: refreshContext, run: runModule };
})();
