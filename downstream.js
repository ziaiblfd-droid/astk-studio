/* Functional enrichment and enrichment comparison. */
(() => {
  'use strict';

  const state = { parentId: null, ready: false, backend: false, busy: false, results: {} };
  const POLL_MS = 2500;
  const MAX_POLLS = 8640;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const studio = () => window.ASTKStudio || null;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function icons() { window.lucide?.createIcons?.(); }
  function toast(message) { studio()?.showToast?.(message); }
  function fileUrl(jobId, path) {
    return `/api/jobs/${encodeURIComponent(jobId)}/files/${String(path).split('/').map(encodeURIComponent).join('/')}`;
  }

  function refreshContext() {
    const context = studio();
    const parentId = context?.jobId || null;
    if (state.parentId !== parentId) {
      state.results = {};
      $$('[data-result]').forEach((box) => { box.replaceChildren(); });
    }
    state.parentId = parentId;
    state.backend = !!context?.backendAvailable;
    state.ready = !!(state.backend && parentId && context?.jobContext?.status === 'completed');
    const gate = $('#downstream-gate');
    if (gate) {
      gate.className = `downstream-notice ${state.ready ? 'ok' : 'warn'}`;
      gate.querySelector('span').textContent = state.ready
        ? `基础分析已完成 · ${parentId}`
        : state.backend ? '请先完成基础分析。' : '服务器未连接';
      gate.querySelector('i')?.setAttribute('data-lucide', state.ready ? 'check-circle-2' : 'info');
    }
    $('#downstream-cta')?.toggleAttribute('hidden', !state.ready);
    $$('[data-run]').forEach((button) => { button.disabled = !state.ready || state.busy; });
    $$('[data-card-status]').forEach((node) => {
      node.textContent = state.busy ? '运行中' : state.ready ? '就绪 READY' : '等待基础分析';
      node.classList.toggle('ready', state.ready && !state.busy);
    });
    icons();
  }

  function figureItems(results) {
    const jobId = results?.job_id || results?.id;
    if (!jobId) return [];
    const groups = results?.images || {};
    const items = Array.isArray(groups) ? groups : Object.values(groups).flat();
    const seen = new Set();
    return items.flatMap((item) => {
      const path = typeof item === 'string' ? item : item?.path;
      if (!path || seen.has(path)) return [];
      seen.add(path);
      return [{
        ...item,
        label: item?.name || path.split('/').pop(),
        src: fileUrl(jobId, path),
      }];
    });
  }

  function renderGallery(mode) {
    const box = $(`[data-result="${mode}"]`);
    const results = state.results[mode];
    if (!box || !results) return;
    const figures = figureItems(results);
    const comparison = box.querySelector('[data-filter="comparison"]')?.value || '';
    const eventType = box.querySelector('[data-filter="event_type"]')?.value || '';
    const kind = box.querySelector('[data-filter="kind"]')?.value || '';
    const visible = figures.filter((item) => (!comparison || item.comparison === comparison) && (!eventType || item.event_type === eventType) && (!kind || (item.kind || mode) === kind));
    const gallery = box.querySelector('.downstream-figures');
    gallery.innerHTML = visible.map((item) => `
      <figure class="downstream-figure">
        <div class="downstream-figure-head"><figcaption>${esc(item.label)}</figcaption><a class="icon-button" href="${esc(item.src)}" target="_blank" rel="noopener" title="打开原图" aria-label="打开原图"><i data-lucide="maximize-2"></i></a></div>
        <a href="${esc(item.src)}" target="_blank" rel="noopener"><img src="${esc(item.src)}" alt="${esc(item.label)}" loading="lazy" /></a>
      </figure>`).join('');
    box.querySelector('[data-figure-count]').textContent = `${visible.length} / ${figures.length}`;
    icons();
  }

  function renderResult(mode, payload) {
    const box = $(`[data-result="${mode}"]`);
    if (!box) return;
    if (payload.state === 'running') {
      box.innerHTML = `<div class="downstream-status" role="status"><span class="spinner" aria-hidden="true"></span><span>${esc(payload.message)}</span></div>`;
      return;
    }
    if (payload.state === 'error') {
      box.innerHTML = `<div class="downstream-notice error" role="alert">${esc(payload.message)}</div>`;
      return;
    }
    const results = payload.results;
    state.results[mode] = results;
    const figures = figureItems(results);
    const comparisons = [...new Set(figures.map((item) => item.comparison).filter(Boolean))];
    const types = [...new Set(figures.map((item) => item.event_type).filter(Boolean))];
    const filters = `
      <label>比较组<select data-filter="comparison"><option value="">全部比较组</option>${comparisons.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select></label>
      <label>事件类型<select data-filter="event_type"><option value="">全部事件类型</option>${types.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select></label>
      ${mode === 'ora' ? '<label>结果图<select data-filter="kind"><option value="ora">过表达富集</option><option value="clusters">GO 聚类</option><option value="">全部图片</option></select></label>' : ''}`;
    const csv = (results.files || []).filter((item) => (typeof item === 'string' ? item : item.path)?.endsWith('.csv'));
    const aggregate = csv.find((item) => typeof item === 'string' && (/^output\/enrichment_[^/]+\.csv$/.test(item) || /^output\/enrichment_compare\/[^/]+\/comparison\.csv$/.test(item)));
    const download = aggregate ? `<a class="button secondary" href="${esc(fileUrl(results.job_id, aggregate))}" download><i data-lucide="download"></i>下载结果 CSV</a>` : '';
    box.innerHTML = `<div class="downstream-gallery-toolbar">${filters}<span data-figure-count></span>${download}</div><div class="downstream-figures"></div>`;
    if (!figures.length) box.innerHTML += '<div class="downstream-empty">没有可展示的图片</div>';
    renderGallery(mode);
  }

  async function pollJob(jobId, mode, parentId) {
    for (let index = 0; index < MAX_POLLS; index++) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      let job;
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}?t=${Date.now()}`, { cache: 'no-store' });
        if (response.status === 404) throw new Error('任务已过期或被清理');
        if (!response.ok) continue;
        job = await response.json();
      } catch (error) {
        if (error.message === '任务已过期或被清理') throw error;
        continue;
      }
      if (job.status === 'completed' || job.status === 'failed') return job;
      if (parentId === state.parentId) renderResult(mode, { state: 'running', message: job.status === 'queued' ? '排队中' : `正在运行 · ${Number(job.progress) || 0}%` });
    }
    throw new Error('等待结果超时，任务可能仍在服务器运行');
  }

  async function runModule(mode = 'ora') {
    if (mode === 'enrichment') mode = 'ora';
    if (!['ora', 'compare'].includes(mode) || state.busy) return;
    refreshContext();
    if (!state.ready) { toast('请先完成基础分析'); return; }
    const parentId = state.parentId;
    const card = $('[data-module="enrichment"]');
    const params = { mode };
    ['gene_set', 'database', 'pvalue', 'qvalue'].forEach((name) => { params[name] = card.querySelector(`[data-param="${name}"]`).value; });
    for (const name of ['pvalue', 'qvalue']) {
      if (!card.querySelector(`[data-param="${name}"]`).reportValidity()) return;
    }
    state.busy = true;
    refreshContext();
    renderResult(mode, { state: 'running', message: '正在提交任务' });
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(parentId)}/downstream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ module: 'enrichment', params }),
      });
      const job = await response.json();
      if (!response.ok) throw new Error(job.error || `提交失败（HTTP ${response.status}）`);
      const childId = job.id || job.job_id;
      if (!childId) throw new Error('服务器未返回任务 ID');
      const final = await pollJob(childId, mode, parentId);
      if (final.status !== 'completed') throw new Error(final.error || '分析失败');
      const resultResponse = await fetch(`/api/jobs/${encodeURIComponent(childId)}/results?t=${Date.now()}`, { cache: 'no-store' });
      if (!resultResponse.ok) throw new Error('无法读取分析结果');
      const results = await resultResponse.json();
      if (parentId === state.parentId) renderResult(mode, { state: 'done', results });
      toast(mode === 'ora' ? '富集分析完成' : '富集比对完成');
    } catch (error) {
      if (parentId === state.parentId) renderResult(mode, { state: 'error', message: error.message || '分析失败' });
      toast(error.message || '分析失败');
    } finally {
      state.busy = false;
      refreshContext();
    }
  }

  function selectMode(mode) {
    $$('[data-enrichment-mode]').forEach((button) => {
      const active = button.dataset.enrichmentMode === mode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    $$('[data-run]').forEach((button) => { button.hidden = button.dataset.run !== mode; });
    $$('[data-result]').forEach((box) => { box.hidden = box.dataset.result !== mode; });
  }

  function init() {
    if (!$('#downstream-view')) return;
    $$('[data-run]').forEach((button) => button.addEventListener('click', () => runModule(button.dataset.run)));
    $$('[data-enrichment-mode]').forEach((button) => button.addEventListener('click', () => selectMode(button.dataset.enrichmentMode)));
    $$('[data-result]').forEach((box) => box.addEventListener('change', (event) => {
      if (event.target.matches('[data-filter]')) renderGallery(box.dataset.result);
    }));
    $('#downstream-refresh')?.addEventListener('click', refreshContext);
    $('#downstream-cta-button')?.addEventListener('click', () => { $('[data-view="downstream"]')?.click(); });
    document.addEventListener('astk:job-updated', refreshContext);
    document.addEventListener('click', (event) => {
      if (event.target.closest('.nav-item[data-view="downstream"]')) refreshContext();
    });
    selectMode('ora');
    refreshContext();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  window.ASTKDownstream = { refresh: refreshContext, run: runModule };
})();
