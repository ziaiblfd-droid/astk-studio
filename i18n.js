/* UI copy only. Scientific data, identifiers, and submitted form values stay unchanged. */
(() => {
  const entries = [
    ['主导航', 'Main navigation'], ['分析工作台', 'Analysis workspace'], ['事件浏览器', 'Event browser'],
    ['分析流程', 'Pipeline'], ['论文数据集', 'Paper datasets'], ['ASTK 方法说明', 'ASTK methods'],
    ['结果与下载', 'Results & downloads'], ['正在检测运行模式', 'Checking engine'],
    ['私有服务器模式', 'Private server mode'], ['通知', 'Notifications'],
    ['可变剪切分析工作台', 'Alternative splicing workspace'],
    ['从转录本定量到七类事件结果，一次完成发现、筛选与可视化。', 'From transcript quantification to seven classes of splicing events, analysis and visualization in one workflow.'],
    ['重置工作台', 'Reset workspace'], ['运行分析', 'Run analysis'], ['配置一次分析', 'Configure analysis'],
    ['配置已保存', 'Configuration saved'], ['数据来源', 'Data source'], ['物种', 'Species'],
    ['实验设计', 'Study design'], ['参考注释', 'Reference annotation'],
    ['显著性阈值', 'Significance threshold'], ['最小变化幅度', 'Minimum change'],
    ['高低 PSI 定义', 'High/low PSI thresholds'],
    ['只影响序列特征模块的 High / Low 事件筛选。', 'Only affects high/low event selection in the sequence feature module.'],
    ['多时间点发育序列', 'Developmental time series'], ['两组比较', 'Two-group comparison'],
    ['多组比较', 'Multiple-group comparison'], ['自定义注释文件', 'Custom annotation file'],
    ['拖入 quant.zip 与 CSV 样本表', 'Drop quant.zip and a CSV sample sheet'],
    ['CSV 文件名无需修改 · ZIP 内保留每个样本的 quant.sf 目录 · 单次最大 512 MB', 'Keep the quant.sf folders in the ZIP · Maximum 512 MB per upload'],
    ['选择文件', 'Choose files'], ['样本与分组', 'Samples & groups'],
    ['上传 CSV 后，可以为每个样本单独修改分组名称。', 'Edit each sample group after selecting the CSV.'],
    ['对照分组', 'Control group'], ['样本名', 'Sample'], ['分组', 'Group'],
    ['生成全部七类事件', 'Generate all seven event classes'], ['输出交互式报告', 'Generate interactive report'],
    ['运行序列特征模块', 'Run sequence feature module'], ['下载 ASTK samples.csv 模板', 'Download ASTK samples.csv template'],
    ['运行状态', 'Run status'], ['分析进度', 'Analysis progress'], ['上传进度', 'Upload progress'],
    ['演示任务', 'Demo run'], ['服务器任务', 'Server job'], ['任务已排队', 'Job queued'],
    ['ASTK 正在分析', 'ASTK is analyzing'], ['下载完整分析报告', 'Download full report'],
    ['结果概览', 'Results overview'], ['全部事件', 'All events'], ['仅显著事件', 'Significant only'],
    ['导出当前事件表', 'Export current event table'],
    ['事件类型分布', 'Event distribution'], ['七类事件', 'Seven event classes'],
    ['PSI 样本结构', 'PSI sample structure'], ['显著事件热图', 'Significant-event heatmap'],
    ['差异可变剪切', 'Differential splicing'], ['查看全部事件', 'View all events'],
    ['比较组补充图表', 'Additional comparison figures'], ['序列特征分析', 'Sequence feature analysis'],
    ['完成真实分析后，可下载完整报告和结果 JSON。', 'Complete an analysis to download the full report and results JSON.'],
    ['完整报告 ZIP', 'Full report ZIP'], ['结果 JSON', 'Results JSON'],
    ['在所有可变剪切事件中定位值得关注的基因与调控模式。', 'Explore genes and regulatory patterns across splicing events.'],
    ['导出当前结果', 'Export current results'], ['全部显著性', 'All directions'],
    ['dPSI 上升', 'dPSI increase'], ['dPSI 下降', 'dPSI decrease'],
    ['每一步都保留输入、输出和版本信息，便于复现与发表。', 'Input, output, and version information is retained for reproducibility.'],
    ['固定版本，完整记录', 'Pinned versions, complete records'],
    ['查看完整运行命令', 'View full command'], ['阅读方法', 'Read methods'],
    ['加载到工作台', 'Load into workspace'], ['浏览数据集', 'Browse dataset'],
    ['心脏 E11.5–P0 发育阶段的 RNA-seq、ATAC-seq 与 ChIP-seq 多组学数据。', 'RNA-seq, ATAC-seq, and ChIP-seq data across mouse heart development (E11.5–P0).'],
    ['人、小鼠、果蝇、线虫与拟南芥的七类事件分布与序列特征比较。', 'Splicing events and sequence features across five species.'],
    ['ATAC 与八种组蛋白修饰信号，展示不同事件类型的调控特征。', 'ATAC and eight histone marks across splicing event types.'],
    ['从论文中的跨物种与发育数据开始探索 ASTK 的分析能力。', 'Explore ASTK using published cross-species and developmental datasets.'],
    ['图表放大预览', 'Enlarged figure'], ['关闭', 'Close'], ['复制任务 ID', 'Copy job ID'],
    ['放大图表', 'Enlarge figure'], ['搜索 gene / event ID', 'Search gene / event ID'],
    ['删除', 'Remove'], ['查看事件', 'View event'], ['已载入', 'Loaded'], ['已提交', 'Submitted'],
    ['分析任务已提交', 'Analysis submitted'], ['运行中', 'Running'], ['提交中', 'Submitting'],
    ['运行失败', 'Run failed'], ['分析完成', 'Analysis complete'], ['演示完成', 'Demo complete'],
    ['分析引擎在线', 'Analysis engine online'], ['演示模式 · 后端未连接', 'Demo mode · backend offline'],
    ['GitHub Pages 演示模式', 'GitHub Pages demo mode'], ['正在提交分析任务', 'Submitting analysis'],
    ['正在创建分析任务', 'Creating analysis job'], ['上传完成，正在创建分析任务', 'Upload complete; creating job'],
    ['上传中，正在估算剩余时间', 'Uploading; estimating time remaining'],
    ['上传即将完成', 'Upload nearly complete'], ['ASTK analysis complete', 'ASTK analysis complete'],
    ['排队中', 'Queued'], ['已完成', 'Completed'], ['已失败', 'Failed'],
    ['输入校验', 'Input validation'], ['事件生成', 'Event generation'],
    ['PSI 与差异剪接', 'PSI & differential splicing'],
    ['序列特征', 'Sequence features'], ['报告生成', 'Report generation'],
    ['完成', 'DONE'], ['执行中', 'RUNNING'], ['等待中', 'WAITING'],
    ['失败', 'FAILED'],
    ['七类事件', 'Seven event classes'], ['High 与 Low PSI 特征比对', 'High vs low PSI feature comparison'],
    ['当前组合没有图像。可能未达到 PSI 阈值，或该步骤未成功。', 'No figure for this selection. No events passed the threshold, or the step failed.'],
    ['查看统计结果', 'View statistics'], ['Low PSI', 'Low PSI'], ['High PSI', 'High PSI'],
    ['演示数据集', 'Demo dataset'],
    ['本地分析', 'Local analysis'], ['静态演示', 'Static demo'],
    ['ASTK 任务', 'ASTK job'], ['演示', 'DEMO'], ['演示就绪', 'DEMO READY'],
    ['正在生成演示结果', 'Generating demo results'],
    ['比较组', 'Comparison'], ['时期 / 条件', 'Time point / condition'],
    ['事件数量', 'Event counts'], ['事件交集', 'Event intersection'],
    ['显著事件', 'Significant events'], ['全部 dPSI 事件', 'All dPSI events'],
    ['剪接位点强度', 'Splice-site strength'], ['GC 含量', 'GC content'],
    ['元件长度', 'Element length'], ['特征', 'Feature'], ['视图', 'View'],
    ['状态', 'Status'], ['筛选事件', 'Selected events'], ['参考 FASTA', 'Reference FASTA'],
    ['服务器配置', 'Server configured'], ['High / Low 比对', 'High / Low comparison'],
    ['显著事件数量与方向', 'Significant-event counts and direction'],
    ['全部 dPSI 事件数量与方向', 'All dPSI event counts and direction'],
    ['显著事件的比较组交集', 'Significant-event intersection across comparisons'],
    ['当前筛选没有生成图像。', 'No figure was generated for this selection.'],
    ['High PSI 事件的单组特征图', 'Single-group features of high-PSI events'],
    ['Low PSI 事件的单组特征图', 'Single-group features of low-PSI events'],
    ['High/Low 按每个时期或条件中全部有效样本的平均 PSI 筛选全部事件，与 ASTK pf 一致；总数为各条件和事件类型的筛选次数之和，并非去重事件数。High/Low 比对使用 Mann-Whitney 检验；GC 使用 150 bp 窗口按剪接位点分面。', 'High/Low selects all events by mean PSI across valid samples at each time point or condition, as in ASTK pf. Counts sum selections across conditions and event types, not unique events. Comparisons use the Mann-Whitney test; GC uses a 150 bp window faceted by splice site.'],
    ['High/Low 表示显著事件在对照与处理的全部有效样本中 PSI 均达到当前阈值；组间高低切换的事件不会进入这两类。比对采用 Mann-Whitney 检验与 BH 校正；GC 比对先按剪接位点的外显子/内含子区域取平均。', 'High/Low includes significant events whose PSI meets the threshold in all valid control and treatment samples; events switching between high and low are excluded. Comparisons use the Mann-Whitney test with BH correction; GC is averaged by exonic/intronic splice-site region.'],
    ['研究工作台', 'Research workspace'], ['工作台', 'Workspace'],
    ['资源', 'RESOURCES'], ['工作区', 'WORKSPACE'],
    ['按事件类型统计的全部事件', 'All detected events by event class'],
    ['按事件类型统计的显著事件', 'Significant events by event class'],
    ['全部事件组成', 'All event composition'],
    ['显著事件组成', 'Significant event composition'],
    ['PSI 主成分分析', 'PSI principal component analysis'],
    ['显著事件 PSI 热图', 'Significant-event PSI heatmap'],
    ['分析结果尚未生成', 'Results are not ready'],
    ['已载入真实 ASTK 分析结果', 'Loaded real ASTK analysis results'],
    ['任务仍在服务器运行', 'The job is still running on the server'],
    ['ASTK 任务已完成，结果已更新', 'ASTK analysis complete; results updated'],
    ['请等待分析任务完成', 'Wait for the analysis to complete'],
    ['无法读取任务状态', 'Unable to load job status'],
    ['任务已进入服务器队列', 'Job is in the server queue'],
    ['ASTK 正在处理数据', 'ASTK is processing data'],
    ['此次分析通常需要约 25–40 分钟，请耐心等待。', 'This analysis usually takes about 25–40 minutes. Thank you for your patience.'],
    ['此次分析通常需要约 10–20 分钟，请耐心等待。', 'This analysis usually takes about 10–20 minutes. Thank you for your patience.'],
    ['排队时间另计。', 'Queueing time is additional.'],
    ['实际耗时随数据量和服务器负载变化。', 'Actual time varies with data size and server load.'],
  ];
  const dictionary = new Map(entries.map(([zh, en]) => [zh, {zh, en}]));
  const reverse = new Map(entries.map(([zh, en]) => [en, {zh, en}]));
  const aliases = new Map([
    ['Composition of all events', ['全部事件组成', 'Composition of all events']],
    ['Composition of significant events', ['显著事件组成', 'Composition of significant events']],
    ['SUPPA2 runner', ['SUPPA2 计算', 'SUPPA2 runner']],
    ['Metadata generation', ['元数据生成', 'Metadata generation']],
    ['Seven-class event generation', ['七类事件生成', 'Seven-class event generation']],
    ['PSI quantification', ['PSI 定量', 'PSI quantification']],
    ['Differential splicing', ['差异剪接', 'Differential splicing']],
    ['Sequence features: selecting events', ['序列特征：筛选事件', 'Sequence features: selecting events']],
    ['Sequence features: figures AF', ['序列特征：AF 绘图', 'Sequence features: figures AF']],
    ['Sequence features: figures SE', ['序列特征：SE 绘图', 'Sequence features: figures SE']],
    ['Input validation', ['输入校验', 'Input validation']],
    ['Report generation', ['报告生成', 'Report generation']],
    ['Local analysis', ['本地分析', 'Local analysis']],
    ['Static demo', ['静态演示', 'Static demo']],
    ['ASTK job', ['ASTK 任务', 'ASTK job']],
    ['DEMO', ['演示', 'DEMO']],
    ['DEMO READY', ['演示就绪', 'DEMO READY']],
  ]);
  const originals = new WeakMap();
  const attributes = new WeakMap();
  let language = 'zh';

  function dynamic(source, lang) {
    if (aliases.has(source)) return aliases.get(source)[lang === 'zh' ? 0 : 1];
    if (lang === 'zh') {
      return source
        .replace(/^Sequence features: extracting (\d+\/\d+)$/, '序列特征：提取 $1')
        .replace(/^Sequence features: comparisons (\d+\/\d+)$/, '序列特征：比对 $1')
        .replace(/^Sequence features: figures (.+)$/, '序列特征：$1 绘图')
        .replace(/^(\d+) files · metadata validation$/, '$1 个文件 · 元数据校验')
        .replace(' · seven event classes', ' · 七类事件')
        .replace(' significant events', ' 个显著事件')
        .replace(' figures · downloadable ZIP', ' 张图 · 可下载 ZIP');
    }
    const patterns = [
      [/^上传预计还需约 (\d+) 分钟（基于当前速度）$/, (_, n) => `Upload: about ${n} min remaining at the current speed`],
      [/^正在上传 (.+) · (\d+)%$/, (_, file, percent) => `Uploading ${file} · ${percent}%`],
      [/^任务 (.+) 的结果可下载；报告包含图表、序列特征及比对产物。$/, (_, id) => `Results for ${id} are ready; the report includes figures, sequence features, and comparisons.`],
      [/^已读取 (\d+) 个样本，可修改分组$/, (_, n) => `Loaded ${n} samples; groups can be edited`],
      [/^已添加 (\d+) 个文件$/, (_, n) => `Added ${n} files`],
      [/^已删除 (.+)$/, (_, name) => `Removed ${name}`],
      [/^已载入 · (.+)$/, (_, size) => `Loaded · ${size}`],
      [/^已提交 · (.+)$/, (_, size) => `Submitted · ${size}`],
      [/^将对 (.+) 与其余 (\d+) 个分组分别比较：(.+)$/, (_, control, count, groups) => `Comparing ${control} with ${count} other groups: ${groups.replaceAll('、', ', ')}`],
      [/^至少需要两个分组，并选择一个对照分组。$/, () => 'Set at least two groups and select a control group.'],
      [/^分组 (.+) 的样本少于 2 个；常用 empirical 比较建议每组至少 2 个样本。$/, (_, groups) => `Groups ${groups} have fewer than two samples; empirical comparisons work best with at least two per group.`],
      [/^(.+) 的分组$/, (_, name) => `Group for ${name}`],
      [/^运行耗时 (\d+:\d+)$/, (_, value) => `Elapsed ${value}`],
      [/^已导出 ([\d,]+) 条事件$/, (_, n) => `Exported ${n} events`],
      [/^Showing ([\d,]+) of ([\d,]+) significant events$/, (_, shown, total) => `Showing ${shown} of ${total} significant events`],
      [/^(.+) 个事件$/, (_, n) => `${n} events`],
      [/^(\d+) High \/ (\d+) Low 个事件$/, (_, high, low) => `${high} high / ${low} low events`],
    ];
    for (const [pattern, output] of patterns) {
      if (pattern.test(source)) return source.replace(pattern, output);
    }
    return source
      .replaceAll('此次分析通常需要约 25–40 分钟，请耐心等待。', 'This analysis usually takes about 25–40 minutes. Thank you for your patience.')
      .replaceAll('此次分析通常需要约 10–20 分钟，请耐心等待。', 'This analysis usually takes about 10–20 minutes. Thank you for your patience.')
      .replaceAll('排队时间另计。', 'Queueing time is additional.')
      .replaceAll('实际耗时随数据量和服务器负载变化。', 'Actual time varies with data size and server load.')
      .replaceAll(' 个事件', ' events')
      .replaceAll(' 个分组', ' groups')
      .replaceAll(' 个分析或比对单元失败', ' analyses or comparisons failed')
      .replaceAll(' 个分析单元完成 · ', ' analyses completed · ')
      .replaceAll(' 张比对图', ' comparison figures')
      .replaceAll('序列特征', 'Sequence features')
      .replaceAll('正在分析', 'Analyzing');
  }

  function translate(source, lang) {
    const whitespace = source.match(/^(\s*)([\s\S]*?)(\s*)$/);
    if (!whitespace) return source;
    const [, before, content, after] = whitespace;
    const entry = dictionary.get(content) || reverse.get(content);
    return before + (entry ? entry[lang] : dynamic(content, lang)) + after;
  }

  function translateNode(node) {
    if (!node.parentElement || node.parentElement.closest('script,style,svg,textarea,[contenteditable="true"]')) return;
    const prior = originals.get(node);
    const source = prior && node.nodeValue === prior.rendered ? prior.source : node.nodeValue;
    const rendered = translate(source, language);
    originals.set(node, {source, rendered});
    if (node.nodeValue !== rendered) node.nodeValue = rendered;
  }

  function translateElement(element) {
    if (element.tagName === 'OPTION' && !element.hasAttribute('value')) {
      element.value = element.textContent;
    }
    for (const name of ['title', 'placeholder', 'aria-label']) {
      if (!element.hasAttribute(name)) continue;
      let state = attributes.get(element);
      if (!state) { state = {}; attributes.set(element, state); }
      const prior = state[name];
      const current = element.getAttribute(name);
      const source = prior && current === prior.rendered ? prior.source : current;
      const rendered = translate(source, language);
      state[name] = {source, rendered};
      if (current !== rendered) element.setAttribute(name, rendered);
    }
  }

  function scan(root) {
    if (root.nodeType === Node.TEXT_NODE) { translateNode(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    translateElement(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.nodeType === Node.TEXT_NODE) translateNode(walker.currentNode);
      else translateElement(walker.currentNode);
    }
  }

  function setLanguage(value) {
    language = value === 'en' ? 'en' : 'zh';
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
    document.querySelector('#language-select').value = language;
    try { localStorage.setItem('astk-language', language); } catch {}
    scan(document.body);
    document.title = language === 'en' ? 'ASTK Studio | Splicing Analysis' : 'ASTK Studio | 可变剪切分析';
  }

  const selector = document.querySelector('#language-select');
  try { language = localStorage.getItem('astk-language') === 'en' ? 'en' : 'zh'; } catch {}
  selector.addEventListener('change', () => setLanguage(selector.value));
  setLanguage(language);
  new MutationObserver(mutations => {
    for (const mutation of mutations) {
      if (mutation.type === 'characterData') translateNode(mutation.target);
      else for (const node of mutation.addedNodes) scan(node);
    }
  }).observe(document.body, {subtree: true, childList: true, characterData: true});
  window.ASTKI18N = {setLanguage, get language() { return language; }};
})();
