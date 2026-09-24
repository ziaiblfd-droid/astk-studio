const eventTypes = ['ALL', 'A3', 'A5', 'AF', 'AL', 'MX', 'RI', 'SE'];
const eventNames = { A3: 'Alternative 3\'', A5: 'Alternative 5\'', AF: 'Alternative first', AL: 'Alternative last', MX: 'Mutually exclusive', RI: 'Retained intron', SE: 'Skipped exon' };
const eventColors = { A3: '#4fb78c', A5: '#78b0ee', AF: '#e9b84f', AL: '#ef786c', MX: '#8f88db', RI: '#7bc6a4', SE: '#c4d2cc' };
const sampleEvents = [
  ['ENSMUSG00000025900.13;SE:chr1:4293012-4311270', 'Ttn', 'SE', 'E11.5 → E16.5', '0.82', '+0.46', '2.1e-08'],
  ['ENSMUSG00000033845.7;AF:chr7:127883-130112', 'Mef2c', 'AF', 'E11.5 → E16.5', '0.18', '-0.39', '8.4e-07'],
  ['ENSMUSG00000067274.6;RI:chr5:991233-994814', 'Ryr2', 'RI', 'E12.5 → P0', '0.67', '+0.34', '1.7e-05'],
  ['ENSMUSG00000037742.8;A3:chr9:214221-216087', 'Actc1', 'A3', 'E11.5 → E13.5', '0.41', '-0.31', '3.2e-05'],
  ['ENSMUSG00000029661.12;SE:chr2:663102-667720', 'Nrxn1', 'SE', 'E13.5 → E16.5', '0.75', '+0.29', '6.8e-05'],
  ['ENSMUSG00000022514.10;AL:chr8:772891-776230', 'Pkm', 'AL', 'E11.5 → P0', '0.29', '-0.28', '9.4e-05'],
  ['ENSMUSG00000022454.14;A5:chr11:401992-405381', 'Srsf3', 'A5', 'E12.5 → E15.5', '0.63', '+0.25', '1.2e-04'],
  ['ENSMUSG00000020186.9;MX:chr3:918221-923145', 'Mbnl1', 'MX', 'E13.5 → E16.5', '0.52', '-0.22', '2.7e-04'],
  ['ENSMUSG00000031972.11;AF:chr4:112221-114090', 'Tpm1', 'AF', 'E11.5 → E15.5', '0.71', '+0.21', '3.2e-04'],
  ['ENSMUSG00000028864.8;RI:chr6:331902-339412', 'Cacna1c', 'RI', 'E12.5 → P0', '0.22', '-0.20', '4.5e-04']
];

let selectedFiles = [];
let currentJobId = null;
let currentJobContext = null;
let backendAvailable = false;
let resultEventTotal = 1824;
let loadedResults = null;
let currentResultScope = 'all';
let sampleTable = null;
let sampleSheetFile = null;
let sampleSheetSource = '';
let baselineGroup = '';

function iconRefresh(){ if(window.lucide) lucide.createIcons(); }
function showToast(message){ const toast=document.querySelector('#toast'); toast.querySelector('span').textContent=message; toast.classList.add('show'); setTimeout(()=>toast.classList.remove('show'),2600); }
function setRunLoader(active,message=''){const loader=document.querySelector('#run-loader');if(!loader)return;loader.classList.toggle('active',active);const text=document.querySelector('#run-loader-text');if(text&&message)text.textContent=message;}
function setButtonLoading(button,label){if(!button)return;button.disabled=true;button.innerHTML=`<i data-lucide="loader-circle"></i>${label}`;iconRefresh();}
function resetRunButton(button){if(!button)return;button.disabled=false;button.innerHTML='<i data-lucide="play"></i>运行分析';iconRefresh();}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));}
function setSelectValue(selector,value){const select=document.querySelector(selector);if(!select||!value)return;const option=[...select.options].find(item=>item.value===value||item.textContent===value);if(option)select.value=option.value;}
function parseCsv(text){const rows=[];let row=[];let field='';let quoted=false;const value=String(text||'').replace(/^\uFEFF/,'');for(let index=0;index<value.length;index++){const character=value[index];if(quoted){if(character==='"'){if(value[index+1]==='"'){field+='"';index++;}else{quoted=false;}}else{field+=character;}}else if(character==='"'){quoted=true;}else if(character===','){row.push(field);field='';}else if(character==='\n'){row.push(field);rows.push(row);row=[];field='';}else if(character!=='\r'){field+=character;}}if(field||row.length){row.push(field);rows.push(row);}return rows.filter(item=>item.some(cell=>String(cell).trim()));}
function headerIndex(headers,names,required=true){const normalized=headers.map(value=>String(value||'').trim().toLowerCase());for(const name of names){const index=normalized.indexOf(name.toLowerCase());if(index>=0)return index;}if(required)throw new Error(`CSV 缺少列：${names.join('/')}`);return -1;}
function truthyValue(value){return ['1','true','yes','y','baseline','control'].includes(String(value||'').trim().toLowerCase());}
function inferStageGroup(name){const clean=String(name||'').replace(/(?:\.|_|-)?(?:rep|replicate)\.?\d+$/i,'');const match=clean.match(/(\d+(?:[._]\d+)?)/);return match?match[1].replace('_','.'):'';}
function parseSampleSheet(text){const rows=parseCsv(text);if(rows.length<2)throw new Error('CSV 样本表没有可用数据');const headers=rows[0].map(value=>String(value||'').trim());const body=rows.slice(1);const astkName=headerIndex(headers,['name'],false);const astkPath=headerIndex(headers,['path'],false);const studioId=headerIndex(headers,['sample_id'],false);const studioPath=headerIndex(headers,['quant_path'],false);if(studioId>=0&&studioPath>=0){const condition=headerIndex(headers,['condition']);const baseline=headerIndex(headers,['baseline'],false);return {format:'studio',rows:body.map((row,index)=>({name:String(row[studioId]||`sample-${index+1}`).trim(),group:String(row[condition]||'').trim(),quantPath:String(row[studioPath]||'').trim(),baseline:baseline>=0&&truthyValue(row[baseline])}))};}if(astkName>=0&&astkPath>=0){const condition=headerIndex(headers,['condition'],false);const group=headerIndex(headers,['group'],false);const path=astkPath;const name=astkName;return {format:'astk',rows:body.map((row,index)=>{const sampleName=String(row[name]||`sample-${index+1}`).trim();const rawGroup=String((group>=0?row[group]:'')||(condition>=0?row[condition]:'')).trim();const stage=inferStageGroup(sampleName);return {name:sampleName,group:stage||rawGroup||`group-${index+1}`,quantPath:String(row[path]||'').trim(),baseline:false};})};}throw new Error('无法识别 CSV 样本表，请使用 name/path 或 sample_id/quant_path 列');}
function clearSampleGroups(){sampleTable=null;sampleSheetFile=null;sampleSheetSource='';baselineGroup='';const panel=document.querySelector('#sample-group-panel');if(panel)panel.hidden=true;}
function renderSampleGroups(){const panel=document.querySelector('#sample-group-panel');const body=document.querySelector('#sample-group-rows');const groups=document.querySelector('#baseline-group');if(!panel||!body||!groups)return;if(!sampleTable||!sampleTable.rows.length){clearSampleGroups();return;}panel.hidden=false;body.innerHTML=sampleTable.rows.map((sample,index)=>`<tr><td class="sample-name" title="${escapeHtml(sample.name)}">${escapeHtml(sample.name)}</td><td><input class="sample-group-input" data-sample-index="${index}" value="${escapeHtml(sample.group)}" aria-label="${escapeHtml(sample.name)} 的分组" /></td></tr>`).join('');body.querySelectorAll('.sample-group-input').forEach(input=>input.addEventListener('input',()=>{const index=Number(input.dataset.sampleIndex);sampleTable.rows[index].group=input.value.trim();updateBaselineOptions();updateSampleGroupHint();}));updateBaselineOptions();updateSampleGroupHint();iconRefresh();}
function updateBaselineOptions(){const select=document.querySelector('#baseline-group');if(!select||!sampleTable)return;const groups=[...new Set(sampleTable.rows.map(sample=>sample.group).filter(Boolean))];if(!groups.length)groups.push('group-1');if(!groups.includes(baselineGroup))baselineGroup=groups[0];select.innerHTML=groups.map(group=>`<option value="${escapeHtml(group)}">${escapeHtml(group)}</option>`).join('');select.value=baselineGroup;select.onchange=()=>{baselineGroup=select.value;updateSampleGroupHint();};}
function updateSampleGroupHint(){const hint=document.querySelector('#sample-group-hint');if(!hint||!sampleTable)return;const groups=[...new Set(sampleTable.rows.map(sample=>sample.group).filter(Boolean))];const counts=Object.fromEntries(groups.map(group=>[group,sampleTable.rows.filter(sample=>sample.group===group).length]));const invalid=groups.filter(group=>counts[group]<2);const comparisons=groups.filter(group=>group!==baselineGroup);if(groups.length<2||!comparisons.length){hint.className='sample-group-hint error';hint.textContent='至少需要两个分组，并选择一个对照分组。';return;}if(invalid.length){hint.className='sample-group-hint error';hint.textContent=`分组 ${invalid.join('、')} 的样本少于 2 个；常用 empirical 比较建议每组至少 2 个样本。`;return;}hint.className='sample-group-hint';hint.textContent=`将对 ${baselineGroup} 与其余 ${comparisons.length} 个分组分别比较：${comparisons.map(group=>`${baselineGroup} → ${group}`).join('、')}`;}
function dedupeSampleRows(rows){const seen=new Set();return rows.filter(sample=>{const key=`${String(sample.quantPath||'').replace(/\\/g,'/')}::${String(sample.name||'')}`;if(seen.has(key))return false;seen.add(key);return true;});}
function defaultBaselineGroup(rows){const groups=[...new Set(rows.map(sample=>sample.group).filter(Boolean))];const numeric=groups.map(group=>({group,value:Number.parseFloat(group)})).filter(item=>Number.isFinite(item.value));if(numeric.length===groups.length&&groups.length){numeric.sort((a,b)=>a.value-b.value);return numeric[0].group;}return groups[0]||'';}
async function refreshSampleGroups(){
  const csv=selectedFiles.find(file=>file.name.toLowerCase().endsWith('.csv'));
  if(!csv){clearSampleGroups();return;}
  const key=`${csv.name}:${csv.size}:${csv.lastModified}`;
  if(key===sampleSheetSource&&sampleTable)return;
  try{
    const parsed=parseSampleSheet(await csv.text());
    const rows=dedupeSampleRows(parsed.rows);
    sampleSheetFile=csv;sampleSheetSource=key;sampleTable={...parsed,rows};
    const baselineRow=rows.find(sample=>sample.baseline);
    baselineGroup=(baselineRow&&baselineRow.group)||defaultBaselineGroup(rows);
    renderSampleGroups();
    showToast(`已读取 ${rows.length} 个样本，可修改分组`);
  }catch(error){clearSampleGroups();showToast(error.message);}
}
function renderFileList(files,state='已载入',removable=false) {const list=document.querySelector('#file-list');list.innerHTML='';files.forEach((file,index)=>{const name=typeof file==='string'?file:file.name;const size=typeof file==='string'?'':` · ${(file.size/1024/1024).toFixed(1)} MB`;const ext=name.split('.').pop().toUpperCase();const action=removable?`<button class="file-remove" type="button" data-file-index="${index}" title="删除 ${escapeHtml(name)}" aria-label="删除 ${escapeHtml(name)}"><i data-lucide="x"></i></button>`:`<span class="file-state"><i data-lucide="check"></i></span>`;list.insertAdjacentHTML('beforeend',`<div class="file-row"><div class="file-type ${ext==='CSV'?'csv':''}">${escapeHtml(ext)}</div><div class="file-info"><strong>${escapeHtml(name)}</strong><span>${escapeHtml(state)}${size}</span></div>${action}</div>`);});if(removable)list.querySelectorAll('.file-remove').forEach(button=>button.addEventListener('click',()=>{const index=Number(button.dataset.fileIndex);const removed=selectedFiles[index];selectedFiles.splice(index,1);renderFileList(selectedFiles,'已载入',true);void refreshSampleGroups();showToast(`已删除 ${removed.name}`);}));iconRefresh();}
function validateSampleTable(){if(!sampleTable||!sampleTable.rows.length)throw new Error('样本分组表尚未读取，请重新上传 CSV');const groups=[...new Set(sampleTable.rows.map(sample=>sample.group.trim()).filter(Boolean))];if(groups.length<2)throw new Error('请至少设置两个样本分组');if(!groups.includes(baselineGroup))throw new Error('请选择一个对照分组');return groups;}
function readPsiThresholds(){const high=Number(document.querySelector('input[aria-label="high psi threshold"]')?.value??0.75);const low=Number(document.querySelector('input[aria-label="low psi threshold"]')?.value??0.25);if(!Number.isFinite(high)||!Number.isFinite(low)||low<0||high>1||low>=high)throw new Error('请设置有效的 PSI 阈值：0 ≤ Low < High ≤ 1');return {high,low};}
function csvLine(values){return values.map(value=>{const text=String(value??'');return /[",\r\n]/.test(text)?`"${text.replaceAll('"','""')}"`:text;}).join(',');}
function buildGroupedSampleFile(){if(!sampleTable)return sampleSheetFile;const lines=['sample_id,condition,quant_path,baseline'];sampleTable.rows.forEach(sample=>{lines.push(csvLine([sample.name,sample.group.trim(),sample.quantPath,String(sample.group.trim()===baselineGroup).toLowerCase()]));});return new File([`${lines.join('\n')}\n`],'samples.grouped.csv',{type:'text/csv'});}
function submissionFiles(){const grouped=buildGroupedSampleFile();const files=selectedFiles.filter(file=>!file.name.toLowerCase().endsWith('.csv'));if(grouped)files.push(grouped);return files;}

function validateUpload(){const zipFiles=selectedFiles.filter(file=>file.name.toLowerCase().endsWith('.zip'));const sampleSheets=selectedFiles.filter(file=>file.name.toLowerCase().endsWith('.csv'));if(!selectedFiles.length)throw new Error('请先选择一个 quant.zip 和一个 CSV 样本表');if(zipFiles.length!==1)throw new Error('每个任务需要且只能上传一个 ZIP 数据包');if(sampleSheets.length!==1)throw new Error('请上传且只能上传一个 CSV 样本表');if(selectedFiles.length!==2)throw new Error('当前版本仅接收一个 ZIP 数据包和一个 CSV 样本表');validateSampleTable();}
function formatDuration(job){const start=new Date(job.created_at);const end=new Date(job.updated_at);if(Number.isNaN(start.getTime())||Number.isNaN(end.getTime()))return '任务时间已记录';const seconds=Math.max(0,Math.round((end-start)/1000));const minutes=Math.floor(seconds/60);return `运行耗时 ${String(minutes).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}
function renderJobStages(job,results=null){const progress=Math.max(0,Math.min(100,Number(job.progress)||0));const figures=Object.values(results?.images||{}).reduce((sum,items)=>sum+items.length,0);const stages=[['Input validation',`${job.config?.files?.length||0} files · metadata validation`,10],['Event generation',`${job.config?.event_type||'ALL'} · seven event classes`,45],['PSI & differential splicing',results?`${Number(results.metrics.significant_events).toLocaleString()} significant events`:'ASTK differential analysis',85]];if(job.config?.sequence_features){const featureData=results?.sequence_features;stages.push(['Sequence features',featureData?`${Number(featureData.selected_events||0).toLocaleString()} high/low events`:'splice score · GC · length',95]);}stages.push(['Report generation',results?`${figures} figures · downloadable ZIP`:'results and figures',100]);document.querySelector('#stage-list').innerHTML=stages.map(([name,detail,threshold])=>{const done=job.status==='completed'||progress>=threshold;const active=!done&&job.status==='running';return `<div class="stage ${done?'done':''}"><span class="stage-icon"><i data-lucide="${done?'check':active?'loader-circle':'circle'}"></i></span><div><strong>${name}</strong><span>${escapeHtml(detail)}</span></div><time>${done?'DONE':active?'RUNNING':'WAITING'}</time></div>`;}).join('');iconRefresh();}
function updateJobStatus(job,results=null){currentJobContext=job;const progress=Math.max(0,Math.min(100,Number(job.progress)||0));const statusTag=document.querySelector('.status-tag');const running=job.status==='queued'||job.status==='running';document.querySelector('#progress-label').textContent='分析进度';document.querySelector('#progress-fill').style.width=`${progress}%`;document.querySelector('#progress-value').textContent=`${progress}%`;document.querySelector('#progress-text').textContent=job.status==='completed'?'ASTK analysis complete':job.status==='failed'?(job.error||'ASTK analysis failed'):(job.stage||'Queued');document.querySelector('#run-duration').textContent=job.status==='completed'?formatDuration(job):'服务器任务';const estimate=document.querySelector('#run-estimate');estimate.textContent=running?(job.config?.sequence_features?'此次分析通常需要约 25–40 分钟，请耐心等待。':'此次分析通常需要约 10–20 分钟，请耐心等待。')+(job.status==='queued'?'排队时间另计。':'实际耗时随数据量和服务器负载变化。'):'';if(statusTag)statusTag.innerHTML=`<span></span> ${job.status==='completed'?'COMPLETED':job.status==='failed'?'FAILED':job.status==='queued'?'QUEUED':'RUNNING'}`;setRunLoader(running,job.status==='queued'?'任务已进入服务器队列':(job.stage||'ASTK 正在处理数据'));renderJobStages(job,results);updateDownloads();}
async function detectBackend(){const status=document.querySelector('#engine-status');const dot=document.querySelector('.version-top .status-dot');const offlineLabel=window.location.hostname.endsWith('github.io')?'GitHub Pages 演示模式':'演示模式 · 后端未连接';try{const response=await fetch('/api/health',{cache:'no-store'});if(!response.ok)throw new Error('unavailable');const health=await response.json();backendAvailable=health.status==='ok';status.textContent=backendAvailable?'分析引擎在线':offlineLabel;dot.classList.toggle('demo-mode',!backendAvailable);}catch{backendAvailable=false;status.textContent=offlineLabel;dot.classList.add('demo-mode');}const demo=document.querySelector('.demo-pill');if(demo)demo.lastChild.textContent=backendAvailable?' Local analysis':' Static demo';}

function makeBarChart(){
  const values=[[42,33,25,31,22,18,27],[34,28,22,27,19,16,25],[48,40,35,39,32,27,34],[27,25,21,24,17,15,20],[62,48,42,46,39,35,44],[54,41,37,43,31,28,39],[70,57,50,54,48,44,56]];
  document.querySelector('#bar-chart').innerHTML=values.map((group)=>`<div class="bar-group">${group.map((v,i)=>`<span class="bar ${i===0?'main':''}" style="height:${v*2.05}px"></span>`).join('')}</div>`).join('');
}
function makeDonutLegend(){
  const data=[['SE',31],['AF',23],['RI',14],['AL',10],['A3',9],['A5',8],['MX',5]];
  document.querySelector('#donut-legend').innerHTML=data.map(([type,value])=>`<div class="donut-item"><i style="background:${eventColors[type]}"></i><span>${type}</span><strong>${value}%</strong></div>`).join('');
}
function makeScatter(){
  const points=[[22,62,'#4a7cf0'],[28,54,'#4a7cf0'],[32,70,'#4a7cf0'],[39,45,'#4a7cf0'],[44,58,'#4a7cf0'],[49,36,'#eab64b'],[54,45,'#eab64b'],[58,29,'#eab64b'],[61,52,'#eab64b'],[68,34,'#ef786c'],[72,45,'#ef786c'],[77,23,'#ef786c'],[81,32,'#ef786c'],[87,18,'#ef786c'],[89,38,'#ef786c']];
  document.querySelector('#pca-chart').innerHTML=points.map(([x,y,c])=>`<i class="scatter-point" style="left:${x}%;top:${y}%;background:${c}"></i>`).join('');
}
function makeHeatmap(){
  const cells=[]; for(let row=0;row<8;row++){for(let col=0;col<20;col++){let score=(Math.sin(row*1.7+col*.57)+Math.cos(col*.31-row)+2)/4; const colors=['#eef5f1','#d5e9df','#aed8c5','#78c19e','#4fb78c','#247e5d']; cells.push(`<i class="heat-cell" style="background:${colors[Math.min(5,Math.floor(score*6))]}"></i>`);}} document.querySelector('#heatmap').innerHTML=cells.join('');
}
function makeVolcano(){
  let html=''; for(let i=0;i<98;i++){const left=5+Math.random()*90, top=55+Math.random()*38, color=i%2?'#4a7cf0':'#b3c6bc'; html+=`<i class="volcano-point" style="left:${left}%;top:${top}%;background:${color}"></i>`;} for(let i=0;i<52;i++){const left=5+Math.random()*44, top=7+Math.random()*39; html+=`<i class="volcano-point" style="left:${left}%;top:${top}%;background:#4a7cf0"></i>`;} for(let i=0;i<58;i++){const left=53+Math.random()*42, top=5+Math.random()*40; html+=`<i class="volcano-point" style="left:${left}%;top:${top}%;background:#ef786c"></i>`;} [[18,17,'Ptbp1'],[78,15,'Ttn'],[86,28,'Mef2c'],[30,28,'Ryr2']].forEach(([x,y,gene])=>html+=`<i class="volcano-point highlight" title="${gene}" style="left:${x}%;top:${y}%;background:${x>50?'#ef786c':'#4a7cf0'}"></i>`); document.querySelector('#volcano-chart').innerHTML=html;
}
function renderEventTabs(){ document.querySelector('#event-tabs').innerHTML=eventTypes.map(t=>`<button class="event-tab ${t==='ALL'?'active':''}" data-type="${t}">${t}</button>`).join(''); document.querySelectorAll('.event-tab').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.event-tab').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); renderTable(btn.dataset.type);})); }
function renderTable(type='ALL'){
  const search=(document.querySelector('#event-search')?.value||'').toLowerCase(); const direction=document.querySelector('#event-filter')?.value||'all';
  const rows=sampleEvents.filter(row=>(type==='ALL'||row[2]===type)&&(!search||row.join(' ').toLowerCase().includes(search))&&(direction==='all'||(direction==='up'?row[5].startsWith('+'):row[5].startsWith('-'))));
  document.querySelector('#events-table').innerHTML=rows.map(r=>`<tr><td class="event-id">${r[0]}</td><td class="gene">${r[1]}</td><td><span class="type-badge">${r[2]}</span></td><td>${r[3]}</td><td>${r[4]}</td><td class="${r[5].startsWith('+')?'dpsi-up':'dpsi-down'}">${r[5]}</td><td class="pval">${r[6]}</td><td><button class="row-action" title="查看事件"><i data-lucide="arrow-up-right"></i></button></td></tr>`).join(''); document.querySelector('#event-count').textContent=`Showing ${rows.length} of ${Number(resultEventTotal).toLocaleString()} significant events`; iconRefresh(); }
function bindNavigation(){ document.querySelectorAll('.nav-item[data-view]').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.nav-item[data-view]').forEach(b=>b.classList.remove('active'));btn.classList.add('active');document.querySelectorAll('.page-view').forEach(v=>v.classList.remove('active'));document.querySelector(`#${btn.dataset.view}-view`).classList.add('active');window.scrollTo({top:0,behavior:'smooth'});})); }
function bindUpload(){
  const zone=document.querySelector('#upload-zone'), input=document.querySelector('#file-input');
  const loadFiles=(files)=>{
    const additions=[...files];
    if(!additions.length)return;
    const existing=new Set(selectedFiles.map(file=>`${file.name}:${file.size}:${file.lastModified}`));
    const newFiles=additions.filter(file=>!existing.has(`${file.name}:${file.size}:${file.lastModified}`));
    if(!newFiles.length){showToast('这些文件已在项目栏中');input.value='';return;}
    selectedFiles.push(...newFiles);
    renderFileList(selectedFiles,'已载入',true);
    void refreshSampleGroups();
    showToast(`已添加 ${newFiles.length} 个文件`);
    input.value='';
  };
  document.querySelector('#browse-files').addEventListener('click',()=>input.click());
  zone.addEventListener('click',(e)=>{if(e.target.closest('button'))return;input.click();});
  input.addEventListener('change',()=>loadFiles(input.files));
  ['dragenter','dragover'].forEach(event=>zone.addEventListener(event,e=>{e.preventDefault();zone.style.borderColor='#1d8b65';}));
  zone.addEventListener('dragleave',()=>zone.style.borderColor='');
  zone.addEventListener('drop',e=>{e.preventDefault();zone.style.borderColor='';loadFiles(e.dataTransfer.files);});
  const typeSelector=document.querySelector('#heatmap-type');
  if(typeSelector)typeSelector.addEventListener('change',event=>{if(loadedResults)renderHeatmapImage(loadedResults,event.target.value);});
}
const uploadChunkRetries=4;
const uploadConcurrency=3;
const uploadChunkTimeout=90000;
function wait(milliseconds){return new Promise(resolve=>setTimeout(resolve,milliseconds));}
function displayUploadProgress(uploaded,total,started,fileName){
  const percent=Math.min(100,Math.round(uploaded/Math.max(1,total)*100));
  const elapsed=(performance.now()-started)/1000;
  const remaining=uploaded&&elapsed>2?Math.ceil((total-uploaded)/(uploaded/elapsed)/60):null;
  document.querySelector('#progress-label').textContent='上传进度';
  document.querySelector('#progress-fill').style.width=`${percent}%`;
  document.querySelector('#progress-value').textContent=`${percent}%`;
  document.querySelector('#progress-text').textContent=`${(uploaded/1048576).toFixed(1)} / ${(total/1048576).toFixed(1)} MB`;
  document.querySelector('#run-estimate').textContent=remaining===null?'上传中，正在估算剩余时间':remaining>0?`上传预计还需约 ${remaining} 分钟（基于当前速度）`:'上传即将完成';
  setRunLoader(true,`正在上传 ${fileName} · ${percent}%`);
}
async function responseError(response,fallback){try{const payload=await response.json();return payload.error||fallback;}catch{return fallback;}}
async function uploadChunk(uploadId,fileIndex,chunkIndex,blob,onRetry){
  let lastError=null;
  for(let attempt=1;attempt<=uploadChunkRetries;attempt++){
    try{
      const response=await fetch(`/api/uploads/${encodeURIComponent(uploadId)}/files/${fileIndex}/chunks/${chunkIndex}`,{method:'POST',headers:{'content-type':'application/octet-stream'},body:blob,signal:AbortSignal.timeout(uploadChunkTimeout)});
      if(response.ok)return;
      const message=await responseError(response,`分块 ${chunkIndex+1} 上传失败`);
      if(response.status>=400&&response.status<500&&response.status!==408&&response.status!==429){
        throw Object.assign(new Error(message),{retryable:false});
      }
      throw new Error(message);
    }catch(error){
      lastError=error;
      if(error.retryable===false)break;
      if(attempt===uploadChunkRetries)break;
      onRetry(attempt+1);
      await wait(1000*attempt);
    }
  }
  throw new Error(`分块 ${chunkIndex+1} 上传失败：${lastError?.message||'网络连接中断'}`);
}
async function createJob(){
  validateUpload();
  const files=submissionFiles();
  const psi=readPsiThresholds(); const config={data_source:document.querySelector('#data-source').value,species:document.querySelector('#species').value,design:document.querySelector('#design').value,comparison_mode:'baseline',event_type:'ALL',method:'empirical',p_value:Number(document.querySelector('input[aria-label="p value threshold"]').value),abs_dpsi:Number(document.querySelector('input[aria-label="absolute dpsi threshold"]').value),sequence_features:Boolean(document.querySelector('#sequence-features')?.checked),psi_high_threshold:psi.high,psi_low_threshold:psi.low,demo:false,files:files.map(file=>file.name)};
  const sessionResponse=await fetch('/api/uploads',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({files:files.map(file=>({name:file.name,size:file.size,type:file.type}))})});
  if(!sessionResponse.ok)throw new Error(await responseError(sessionResponse,'无法创建上传任务'));
  const session=await sessionResponse.json();
  const chunkSize=Number(session.chunk_size)||1024*1024;
  const totalBytes=files.reduce((sum,file)=>sum+file.size,0);
  let uploadedBytes=0;
  const started=performance.now();
  const queue=[];
  for(let fileIndex=0;fileIndex<files.length;fileIndex++){
    const file=files[fileIndex];
    const chunks=Math.ceil(file.size/chunkSize);
    for(let chunkIndex=0;chunkIndex<chunks;chunkIndex++){
      const start=chunkIndex*chunkSize;
      queue.push({file,fileIndex,chunkIndex,start});
    }
  }
  displayUploadProgress(0,totalBytes,started,files[0].name);
  let next=0;
  let failure=null;
  async function worker(){
    while(next<queue.length&&!failure){
      const task=queue[next++];
      const blob=task.file.slice(task.start,Math.min(task.file.size,task.start+chunkSize));
      try{
        await uploadChunk(session.id,task.fileIndex,task.chunkIndex,blob,attempt=>{
          document.querySelector('#run-estimate').textContent=`网络不稳定，正在重试第 ${task.chunkIndex+1} 块（第 ${attempt}/${uploadChunkRetries} 次）`;
        });
        uploadedBytes+=blob.size;
        displayUploadProgress(uploadedBytes,totalBytes,started,task.file.name);
      }catch(error){failure=error;break;}
    }
  }
  await Promise.all(Array.from({length:Math.min(uploadConcurrency,queue.length)},()=>worker()));
  if(failure)throw failure;
  document.querySelector('#progress-label').textContent='分析进度';
  document.querySelector('#progress-value').textContent='0%';
  document.querySelector('#progress-fill').style.width='0%';
  document.querySelector('#progress-text').textContent='正在创建分析任务';
  document.querySelector('#run-estimate').textContent='';
  setRunLoader(true,'上传完成，正在创建分析任务');
  return fetch('/api/jobs',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({upload_id:session.id,config})});
}
function pickImage(items=[],token=''){const matches=items.filter(item=>item.name.toUpperCase().includes(token.toUpperCase()));return matches[matches.length-1]||items[0]||null;}
function renderResultImage(containerId,item){if(!item||!currentJobId)return;const container=document.querySelector(containerId);if(!container)return;const source=encodeURI(`/api/jobs/${currentJobId}/files/${item.path}`);container.classList.add('result-image-frame');container.innerHTML=`<img class="result-plot" src="${source}" alt="${item.name}" loading="lazy" />`;}
function resultCountsForScope(results){const all=results.event_counts||{};if(currentResultScope==='all'){return Object.fromEntries(eventTypes.slice(1).map(kind=>[kind,Number(all[kind]||0)]));}return Object.fromEntries(eventTypes.slice(1).map(kind=>[kind,Number((results.significant_event_counts||{})[kind]||0)]));}
function renderCounts(results){const counts=resultCountsForScope(results);const kinds=eventTypes.slice(1);const total=kinds.reduce((sum,kind)=>sum+counts[kind],0);const max=Math.max(1,...kinds.map(kind=>counts[kind]));const bar=document.querySelector('#bar-chart');bar.classList.remove('result-image-frame');bar.innerHTML=kinds.map(kind=>`<div class="bar-group result-count-bar" title="${kind}: ${counts[kind].toLocaleString()}"><span class="bar main" style="height:${Math.max(4,counts[kind]/max*180)}px"></span></div>`).join('');document.querySelector('.chart-axis').innerHTML=kinds.map(kind=>`<span>${kind}</span>`).join('');document.querySelector('.chart-axis').style.display='flex';let cursor=0;const stops=kinds.map(kind=>{const start=cursor;cursor+=total?counts[kind]/total*100:0;return `${eventColors[kind]} ${start}% ${cursor}%`;});const donut=document.querySelector('.donut');donut.style.background=`conic-gradient(${stops.join(',')})`;donut.querySelector('strong').textContent=total>=1000?`${(total/1000).toFixed(1)}k`:String(total);document.querySelector('#donut-legend').innerHTML=kinds.map(kind=>`<div class="donut-item"><i style="background:${eventColors[kind]}"></i><span>${kind}</span><strong>${total?Math.round(counts[kind]/total*100):0}%</strong></div>`).join('');}
function comparisonDisplayName(results,name){const group=name.replace(/_bar\((?:sig01|dpsi)\)$/,'');const comparison=(results.comparisons||[]).find(item=>item.group===group);return comparison?.label||group;}
function resultImageSource(item){return encodeURI(`/api/jobs/${currentJobId}/files/${item.path}`);}
function updateDownloads(){
  const ready=backendAvailable&&currentJobId&&currentJobContext?.status==='completed';
  const status=document.querySelector('#downloads-status');
  if(status)status.textContent=ready?`任务 ${currentJobId} 的结果可下载；报告包含图表、序列特征及比对产物。`:'完成真实分析后，可下载完整报告和结果 JSON。';
  for(const [id,suffix] of [['download-zip','download'],['download-json','results']]){
    const link=document.querySelector(`#${id}`);
    if(!link)continue;
    link.setAttribute('aria-disabled',String(!ready));
    if(ready)link.href=`/api/jobs/${encodeURIComponent(currentJobId)}/${suffix}`;
    else link.removeAttribute('href');
  }
}
function renderSupplementalImages(results){
  const heading=document.querySelector('#supplemental-heading'),panel=document.querySelector('#supplemental-charts');
  if(!heading||!panel)return;
  const bars=results.images?.bar||[],upsets=results.images?.upset||[];
  if(!currentJobId||(!bars.length&&!upsets.length)){heading.hidden=true;panel.hidden=true;return;}
  const groups=[...new Set(bars.map(item=>item.name.replace(/_bar\((?:sig01|dpsi)\)$/,'')))];
  panel.innerHTML=`<div class="figure-toolbar"><div class="figure-mode"><button type="button" class="active" data-figure-mode="bar">事件数量</button><button type="button" data-figure-mode="upset">事件交集</button></div><div class="figure-fields"><label id="supplemental-group-field">比较组<select id="supplemental-group">${groups.map(group=>`<option value="${escapeHtml(group)}">${escapeHtml(comparisonDisplayName(results,group))}</option>`).join('')}</select></label><label id="supplemental-scope-field">范围<select id="supplemental-scope"><option value="sig01">显著事件</option><option value="dpsi">全部 dPSI 事件</option></select></label><label id="supplemental-type-field" hidden>事件类型<select id="supplemental-type">${upsets.map(item=>`<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join('')}</select></label></div></div><div class="figure-heading"><div><h3 id="supplemental-title"></h3><p id="supplemental-description"></p></div><button class="more-button" type="button" title="放大图表" data-zoom-target="#supplemental-image"><i data-lucide="maximize-2"></i></button></div><div class="figure-image" id="supplemental-image"></div>`;
  function update(){
    const mode=panel.querySelector('.figure-mode button.active')?.dataset.figureMode||'bar';
    panel.querySelector('#supplemental-group-field').hidden=mode!=='bar';
    panel.querySelector('#supplemental-scope-field').hidden=mode!=='bar';
    panel.querySelector('#supplemental-type-field').hidden=mode!=='upset';
    const group=panel.querySelector('#supplemental-group').value,scope=panel.querySelector('#supplemental-scope').value,type=panel.querySelector('#supplemental-type').value;
    const item=mode==='bar'?bars.find(image=>image.name===`${group}_bar(${scope})`):upsets.find(image=>image.name===type);
    const title=mode==='bar'?comparisonDisplayName(results,group):`${type} · 比较组交集`;
    panel.querySelector('#supplemental-title').textContent=title;
    panel.querySelector('#supplemental-description').textContent=mode==='bar'?(scope==='sig01'?'显著事件数量与方向':'全部 dPSI 事件数量与方向'):'显著事件的比较组交集';
    panel.querySelector('#supplemental-image').innerHTML=item?`<img src="${escapeHtml(resultImageSource(item))}" alt="${escapeHtml(title)}" loading="lazy" />`:'<span class="figure-empty">当前筛选没有生成图像。</span>';
  }
  panel.querySelectorAll('.figure-mode button').forEach(button=>button.addEventListener('click',()=>{panel.querySelectorAll('.figure-mode button').forEach(node=>node.classList.toggle('active',node===button));update();}));
  panel.querySelectorAll('select').forEach(select=>select.addEventListener('change',update));
  heading.hidden=false;panel.hidden=false;update();bindZoomButtons(panel);iconRefresh();
}
function renderSequenceFeatures(results){
  const heading=document.querySelector('#sequence-heading'),panel=document.querySelector('#sequence-features-results'),data=results.sequence_features||{};
  if(!heading||!panel)return;
  if(!data.enabled){heading.hidden=true;panel.hidden=true;panel.innerHTML='';return;}
  const groups=Array.isArray(data.groups)?data.groups:[],comparisons=Array.isArray(data.comparisons)?data.comparisons:[];
  const groupNames=[...new Set(groups.map(item=>item.group))];
  const statusText=data.failed?`${data.failed} 个分析或比对单元失败`:`${Number(data.completed||0)} 个分析单元完成 · ${comparisons.filter(item=>item.status==='completed').length} 张比对图`; const highCutoff=Number(data.high_threshold??0.75); const lowCutoff=Number(data.low_threshold??0.25);
  const byCondition=data.selection_mode==='condition_mean_all_events';
  const note=byCondition?'High/Low 按每个时期或条件中全部有效样本的平均 PSI 筛选全部事件，与 ASTK pf 一致；总数为各条件和事件类型的筛选次数之和，并非去重事件数。High/Low 比对使用 Mann-Whitney 检验；GC 使用 150 bp 窗口按剪接位点分面。':'High/Low 表示显著事件在对照与处理的全部有效样本中 PSI 均达到当前阈值；组间高低切换的事件不会进入这两类。比对采用 Mann-Whitney 检验与 BH 校正；GC 比对先按剪接位点的外显子/内含子区域取平均。';
  panel.innerHTML=`<div class="sequence-summary"><div><span>状态</span><strong>${escapeHtml(statusText)}</strong></div><div><span>筛选事件</span><strong>${Number(data.selected_events||0).toLocaleString()}</strong></div><div><span>High / Low</span><strong>≥ ${highCutoff} / ≤ ${lowCutoff}</strong></div><div><span>参考 FASTA</span><strong>${escapeHtml(data.fasta||'服务器配置')}</strong></div></div><p class="sequence-note">${note}</p><div class="figure-toolbar"><div class="figure-fields"><label>${byCondition?'时期 / 条件':'比较组'}<select id="sequence-group">${groupNames.map(group=>`<option value="${escapeHtml(group)}">${escapeHtml(byCondition?group:comparisonDisplayName(results,group))}</option>`).join('')}</select></label><label>事件类型<select id="sequence-kind"></select></label><label>特征<select id="sequence-feature"><option value="splice_score">剪接位点强度</option><option value="gc">GC 含量</option><option value="element_length">元件长度</option></select></label><label>视图<select id="sequence-view"><option value="high">High PSI</option><option value="low">Low PSI</option><option value="comparison">High / Low 比对</option></select></label></div></div><div class="figure-heading"><div><h3 id="sequence-title">序列特征</h3><p id="sequence-description"></p></div><button class="more-button" type="button" title="放大图表" data-zoom-target="#sequence-image"><i data-lucide="maximize-2"></i></button></div><div class="figure-image" id="sequence-image"></div><div class="sequence-meta" id="sequence-meta"></div>`;
  const groupSelect=panel.querySelector('#sequence-group'),kindSelect=panel.querySelector('#sequence-kind'),featureSelect=panel.querySelector('#sequence-feature'),viewSelect=panel.querySelector('#sequence-view');
  function updateKinds(){
    const kinds=[...new Set(groups.filter(item=>item.group===groupSelect.value).map(item=>item.kind))];
    kindSelect.innerHTML=kinds.map(kind=>`<option value="${escapeHtml(kind)}">${escapeHtml(kind)}</option>`).join('');
    update();
  }
  function update(){
    const group=groupSelect.value,kind=kindSelect.value,feature=featureSelect.value,view=viewSelect.value;
    const entry=groups.find(item=>item.group===group&&item.kind===kind&&item.stratum===view);
    const comparison=comparisons.find(item=>item.group===group&&item.kind===kind&&item.feature===feature);
    const files=entry?.outputs?.[feature]||[];
    const image=view==='comparison'?comparison?.image:files.find(file=>file.toLowerCase().endsWith('.png'));
    const title=`${byCondition?group:comparisonDisplayName(results,group)} · ${kind} · ${featureSelect.selectedOptions[0]?.textContent||feature}`;
    panel.querySelector('#sequence-title').textContent=title;
    panel.querySelector('#sequence-description').textContent=view==='comparison'?'High 与 Low PSI 特征比对':`${view==='high'?'High':'Low'} PSI 事件的单组特征图`;
    panel.querySelector('#sequence-image').innerHTML=image?`<img src="${escapeHtml(resultImageSource({path:image}))}" alt="${escapeHtml(title)}" loading="lazy" />`:'<span class="figure-empty">当前组合没有图像。可能未达到 PSI 阈值，或该步骤未成功。</span>';
    const count=view==='comparison'?`${comparison?.high_events??0} High / ${comparison?.low_events??0} Low 个事件`:`${entry?.selected_events??0} 个事件`;
    const error=view==='comparison'?comparison?.error:Object.values(entry?.errors||{}).join('; ');
    const stats=view==='comparison'&&comparison?.statistics?` · <a href="${escapeHtml(resultImageSource({path:comparison.statistics}))}" target="_blank" rel="noreferrer">查看统计结果</a>`:'';
    panel.querySelector('#sequence-meta').innerHTML=`${escapeHtml(count)}${stats}${error?` · ${escapeHtml(error)}`:''}`;
  }
  groupSelect.addEventListener('change',updateKinds);
  [kindSelect,featureSelect,viewSelect].forEach(select=>select.addEventListener('change',update));
  heading.hidden=false;panel.hidden=false;updateKinds();bindZoomButtons(panel);iconRefresh();
}
function renderHeatmapImage(results,kind='SE'){renderResultImage('#heatmap',pickImage(results.images?.heatmap||[],kind));}
function renderResultImages(results){const images=results.images||{};const bar=pickImage(images.bar||[],'sig01');if(bar){renderResultImage('#bar-chart',bar);document.querySelector('.chart-axis').style.display='none';}renderResultImage('#pca-chart',pickImage(images.pca||[],'SE'));renderHeatmapImage(results,document.querySelector('#heatmap-type')?.value||'SE');renderResultImage('#volcano-chart',pickImage(images.volcano||[],'SE'));renderSupplementalImages(results);renderSequenceFeatures(results);}
function updateResultsContext(results){const comparisons=(results.comparisons||[]).map(item=>`${item.control} → ${item.treatment}`);const label=comparisons.length?comparisons.join(' · '):currentJobId;document.querySelector('#workspace-name').textContent=label;const setChartSubtitle=(chartSelector,text)=>{const chart=document.querySelector(chartSelector);const subtitle=chart?.closest('.chart-panel')?.querySelector('.chart-header > div > span');if(subtitle)subtitle.textContent=text;};setChartSubtitle('#bar-chart',currentResultScope==='all'?'All detected events by event class':'Significant events by event class');setChartSubtitle('.donut',currentResultScope==='all'?'All event composition':'Significant event composition');setChartSubtitle('#pca-chart','PSI principal component analysis');setChartSubtitle('#heatmap','Significant-event PSI heatmap');const volcanoSubtitle=document.querySelector('.volcano-panel .chart-header > div > span');if(volcanoSubtitle)volcanoSubtitle.textContent=comparisons.join(' · ')||'ΔPSI vs statistical significance';const legend=document.querySelector('.scatter-legend');if(legend)legend.style.display='none';const methods=document.querySelectorAll('.methods-grid strong');const config=currentJobContext?.config||{};const engine=String(results.engine||results.mode||'suppa2').toLowerCase();if(methods[0])methods[0].textContent=engine.includes('astk')?'ASTK native':'SUPPA2 2.4';if(methods[1])methods[1].textContent='Python 3.12 · Pinned';if(methods[2])methods[2].textContent=(config.method||'empirical').replace(/^./,letter=>letter.toUpperCase());if(methods[3])methods[3].textContent=results.reference?.id||config.species||'Configured server reference';const feet=document.querySelectorAll('.metric-foot');if(feet[0])feet[0].innerHTML='<span class="neutral-dot"></span><span>across seven event classes</span>';if(feet[1])feet[1].innerHTML=`<span class="neutral-dot"></span><span>p ≤ ${escapeHtml(config.p_value??0.05)} · |dPSI| ≥ ${escapeHtml(config.abs_dpsi??0.1)}</span>`;if(feet[2])feet[2].innerHTML='<span class="neutral-dot"></span><span>from uploaded samples.csv</span>';if(feet[3])feet[3].innerHTML='<span class="neutral-dot"></span><span>among significant events</span>';}
async function loadResults(jobId){const response=await fetch(`/api/jobs/${jobId}/results?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error('分析结果尚未生成');const results=await response.json();loadedResults=results;const numbers=document.querySelectorAll('.metric-number');numbers[0].textContent=Number(results.metrics.total_events).toLocaleString();numbers[1].textContent=Number(results.metrics.significant_events).toLocaleString();numbers[2].textContent=String(results.metrics.sample_count).padStart(2,'0');numbers[3].textContent=Number(results.metrics.median_abs_dpsi).toFixed(2);resultEventTotal=Number(results.metrics.significant_events)||0;renderCounts(results);updateResultsContext(results);if(currentJobContext)renderJobStages(currentJobContext,results);const directions=results.direction_counts||{};const summary=document.querySelector('.volcano-summary');if(summary)summary.innerHTML=`<span><i class="legend-dot coral"></i>Up ${Number(directions.up||0).toLocaleString()}</span><span><i class="legend-dot blue"></i>Down ${Number(directions.down||0).toLocaleString()}</span><button class="button mini secondary" id="show-all-events">查看全部事件</button>`;document.querySelector('#show-all-events')?.addEventListener('click',()=>{document.querySelector('[data-view="events"]')?.click();});if(Array.isArray(results.events)){sampleEvents.splice(0,sampleEvents.length,...results.events.map(row=>row.map(value=>String(value).replace(' -> ',' → '))));renderTable(document.querySelector('.event-tab.active')?.dataset.type||'ALL');}renderResultImages(results);bindZoomButtons(document);return results;}
async function loadJobContext(jobId){const response=await fetch(`/api/jobs/${jobId}`,{cache:'no-store'});if(!response.ok)throw new Error('无法读取任务状态');const job=await response.json();currentJobId=job.id;currentJobContext=job;document.querySelector('#workspace-name').textContent=job.id;document.querySelector('#workspace-run-label').textContent=`ANALYSIS WORKSPACE / ${job.id}`;const idNode=document.querySelector('.run-id strong');if(idNode)idNode.textContent=job.id;const demo=document.querySelector('.demo-pill');if(demo)demo.lastChild.textContent=' ASTK job';const config=job.config||{};setSelectValue('#data-source',config.data_source);setSelectValue('#species',config.species);setSelectValue('#design',config.design);const featureToggle=document.querySelector('#sequence-features');if(featureToggle)featureToggle.checked=Boolean(config.sequence_features);const threshold=document.querySelector('input[aria-label="p value threshold"]');if(threshold&&config.p_value!==undefined)threshold.value=config.p_value;const dpsiThreshold=document.querySelector('input[aria-label="absolute dpsi threshold"]');if(dpsiThreshold&&config.abs_dpsi!==undefined)dpsiThreshold.value=config.abs_dpsi;const highPsi=document.querySelector('input[aria-label="high psi threshold"]');if(highPsi&&config.psi_high_threshold!==undefined)highPsi.value=config.psi_high_threshold;const lowPsi=document.querySelector('input[aria-label="low psi threshold"]');if(lowPsi&&config.psi_low_threshold!==undefined)lowPsi.value=config.psi_low_threshold;if(Array.isArray(config.files))renderFileList(config.files,'已提交');updateJobStatus(job);return job;}
async function pollJob(jobId){const job=await loadJobContext(jobId);if(job.status==='completed'){await loadResults(jobId);return job;}if(job.status==='failed')throw new Error(job.error||'ASTK 任务失败');await new Promise(resolve=>setTimeout(resolve,2000));return pollJob(jobId);}
async function runStaticDemo(){const fill=document.querySelector('#progress-fill'),value=document.querySelector('#progress-value'),text=document.querySelector('#progress-text'),statusTag=document.querySelector('.status-tag');setRunLoader(true,'正在生成演示结果');for(const [progress,stage] of [[12,'Input validation'],[26,'Metadata generation'],[48,'Seven-class event generation'],[68,'PSI quantification'],[88,'Differential splicing'],[100,'Report generation']]){fill.style.width=`${progress}%`;value.textContent=`${progress}%`;text.textContent=stage;setRunLoader(true,stage);if(statusTag)statusTag.innerHTML='<span></span> DEMO';await new Promise(resolve=>setTimeout(resolve,260));}text.textContent='7 / 7 demo stages complete';setRunLoader(false);if(statusTag)statusTag.innerHTML='<span></span> DEMO READY';}
function bindRun(){document.querySelector('#run-analysis').addEventListener('click',async()=>{const button=document.querySelector('#run-analysis');button.disabled=true;button.innerHTML='<i data-lucide="loader-circle"></i>提交中';setRunLoader(true,'正在提交分析任务');iconRefresh();try{if(!backendAvailable){await runStaticDemo();button.innerHTML='<i data-lucide="check"></i>演示完成';showToast(window.location.hostname.endsWith('github.io')?'GitHub Pages 仅展示演示结果':'未连接计算服务，请配置云端 ASTK 后端');return;}validateUpload();document.querySelector('#progress-fill').style.width='0%';document.querySelector('#progress-value').textContent='0%';const response=await createJob();if(!response.ok){const error=await response.json();throw new Error(error.error||'任务提交失败');}const job=await response.json();currentJobId=job.id;currentJobContext=job;history.replaceState(null,'',`?job=${encodeURIComponent(job.id)}`);updateJobStatus(job);const idNode=document.querySelector('.run-id strong');if(idNode)idNode.textContent=job.id;button.innerHTML='<i data-lucide="loader-circle"></i>运行中';iconRefresh();await pollJob(job.id);button.innerHTML='<i data-lucide="check"></i>分析完成';showToast('ASTK 任务已完成，结果已更新');}catch(error){setRunLoader(false);if(document.querySelector('#progress-label').textContent==='上传进度'){document.querySelector('#run-estimate').textContent=`上传失败：${error.message}`;document.querySelector('#progress-text').textContent='上传中断，请重试';}button.innerHTML='<i data-lucide="triangle-alert"></i>运行失败';showToast(error.message);}finally{button.disabled=false;iconRefresh();setTimeout(()=>{button.innerHTML='<i data-lucide="play"></i>运行分析';iconRefresh();},2400);}});document.querySelector('#reset-demo').addEventListener('click',()=>{history.replaceState(null,'',window.location.pathname);window.location.reload();});}
function csvCell(value){const text=String(value??'');return `"${text.replaceAll('"','""')}"`;}
function exportRows(rows,filename){if(!rows.length){showToast('当前没有可导出的结果');return;}const header=['Event ID','Gene','Type','Condition','PSI','dPSI','p-value'];const content='\ufeff'+[header,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n');const blob=new Blob([content],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);showToast(`已导出 ${rows.length.toLocaleString()} 条事件`);}
function filteredEvents(scope=currentResultScope){const search=(document.querySelector('#event-search')?.value||'').toLowerCase();const direction=document.querySelector('#event-filter')?.value||'all';const activeType=document.querySelector('.event-tab.active')?.dataset.type||'ALL';return sampleEvents.filter(row=>(activeType==='ALL'||row[2]===activeType)&&(!search||row.join(' ').toLowerCase().includes(search))&&(direction==='all'||(direction==='up'?row[5].startsWith('+'):row[5].startsWith('-'))));}
function setResultScope(scope){currentResultScope=scope;document.querySelectorAll('[data-result-scope]').forEach(button=>button.classList.toggle('active',button.dataset.resultScope===scope));if(loadedResults){renderCounts(loadedResults);updateResultsContext(loadedResults);}renderTable(document.querySelector('.event-tab.active')?.dataset.type||'ALL');}
function bindResultControls(){document.querySelectorAll('[data-result-scope]').forEach(button=>button.addEventListener('click',()=>setResultScope(button.dataset.resultScope)));document.querySelector('#export-results').addEventListener('click',()=>exportRows(filteredEvents(),`astk-${currentJobId||'demo'}-${currentResultScope}.csv`));}
function bindZoomButtons(root=document){root.querySelectorAll('.more-button[data-zoom-target]').forEach(button=>{if(button.dataset.zoomBound)return;button.dataset.zoomBound='1';button.addEventListener('click',()=>openLightbox(button.dataset.zoomTarget));});}
function openLightbox(selector){const source=document.querySelector(selector);const lightbox=document.querySelector('#image-lightbox');const content=document.querySelector('#lightbox-content');if(!source||!lightbox||!content)return;const clone=source.cloneNode(true);clone.removeAttribute('id');clone.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));clone.classList.add('lightbox-plot');content.innerHTML='';content.appendChild(clone);lightbox.hidden=false;document.body.style.overflow='hidden';iconRefresh();}
function closeLightbox(){const lightbox=document.querySelector('#image-lightbox');const content=document.querySelector('#lightbox-content');if(!lightbox||!content)return;lightbox.hidden=true;content.innerHTML='';document.body.style.overflow='';}
function bindLightbox(){const lightbox=document.querySelector('#image-lightbox');lightbox?.querySelector('.lightbox-close')?.addEventListener('click',closeLightbox);lightbox?.addEventListener('click',event=>{if(event.target===lightbox)closeLightbox();});document.addEventListener('keydown',event=>{if(event.key==='Escape')closeLightbox();});bindZoomButtons(document);}
function bindExports(){document.querySelector('#download-report').addEventListener('click',()=>{if(!backendAvailable){showToast('请连接真实 ASTK 服务后下载报告');return;}if(!currentJobId||currentJobContext?.status!=='completed'){showToast('请等待分析任务完成');return;}window.location.href=`/api/jobs/${currentJobId}/download`;});document.querySelector('#sidebar-download')?.addEventListener('click',event=>{event.preventDefault();document.querySelector('[data-view="dashboard"]')?.click();document.querySelector('#downloads')?.scrollIntoView({behavior:'smooth',block:'start'});});document.querySelector('#export-events').addEventListener('click',()=>exportRows(filteredEvents(),`astk-${currentJobId||'demo'}-events.csv`));document.querySelector('#load-heart').addEventListener('click',()=>{document.querySelector('[data-view="dashboard"]').click();showToast('Heart development 已加载到工作台');});}
async function init(){makeBarChart();makeDonutLegend();makeScatter();makeHeatmap();makeVolcano();renderEventTabs();renderTable();bindNavigation();bindUpload();bindRun();bindExports();bindResultControls();bindLightbox();document.querySelector('#event-search').addEventListener('input',()=>{const active=document.querySelector('.event-tab.active');renderTable(active?.dataset.type||'ALL');});document.querySelector('#event-filter').addEventListener('change',()=>{const active=document.querySelector('.event-tab.active');renderTable(active?.dataset.type||'ALL');});iconRefresh();await detectBackend();const requestedJob=new URLSearchParams(window.location.search).get('job');if(backendAvailable&&requestedJob){try{const job=await loadJobContext(requestedJob);if(job.status==='completed'){await loadResults(requestedJob);showToast('已载入真实 ASTK 分析结果');}else if(job.status==='failed'){showToast(job.error||'ASTK 任务失败');}else{showToast('任务仍在服务器运行');await pollJob(requestedJob);}}catch(error){showToast(error.message);}}}
init();
