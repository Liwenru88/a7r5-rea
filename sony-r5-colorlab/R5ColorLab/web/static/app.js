function gridResponseName(response){return Array.isArray(response)?'旧版 5×9×9 · BT.601 + 固定响应':({'r5-paired-20261102-shared-c1-c50':'R5 无专家共享 C1 · 曲率50%','r5-paired-20261102-three-experts':'R5 共享 C1＋三色相专家 · 2026-11-02','r5-paired-20261102-nonlinear':'历史 R5 非线性坐标＋二阶响应 · 2026-11-02','r5-paired-20261024-v2':'历史 R5 实拍响应 v2 · 2026-10-24','r5-paired-20261024':'历史 R5 实拍响应 v1 · 2026-10-24'}[response?.preset]||'历史实测代理');}

'use strict';
const $ = id => document.getElementById(id);
const clone = value => structuredClone(value);
let boot, draft, selected = 1, collection = [], lutText = '', jobId, timer, busy = false;
let chartTargetId, chartUploading=false;
// 仅复用本页已成功完成且输入完全一致的任务；失败或输入变化仍可重新提交。
let submittedTraining, completedTraining;
let libraryVersion=4,libraryImportBusy=false,pendingImport;
const imageTarget=()=>$('targetKind').value==='chart-image';
const fastTraining=()=>$('speedPriority').value==='fast';

function trainingModeHint(){
  $('trainingModeHint').textContent=fastTraining()
    ?'减少拟合搜索和交替轮次。默认响应仍执行纯整数网格微调及导出验收。'
    :'使用完整搜索。默认响应执行纯整数网格微调及灰阶、饱和度过渡验收。';
}
const chartJob=()=>diagnosticData?.dataset?.target_kind==='chart-image';
const targetReady=()=>imageTarget()?Boolean(chartTargetId):Boolean(lutText);
const names = ['ST','PT','NT','VV','VV2','FL','FL2','FL3','IN','SH','BW','SE'];
const chineseNames = ['标准','人像','中性','鲜艳','鲜艳二','胶片','胶片二','胶片三','即时','柔和高调','黑白','棕褐'];
let validationJob, rawFile, rawBusy = false, diagnosticData;
let photoFile, photoBusy=false, photoId, photoTimer, photoSlotRequest, photoShownSlot;
let photoUploadSerial=0;
let actualUrl,photoSourceSha;
const pcView=()=>$('resultMode').value!=='native';
const gridKeys=new Map();
let diagnosticSerial=0,compressionTimer,compressionBusy=false;
const beforeGrayKeys=new Map();
const selectedGrid=()=>$('resultMode').value==='compressed'?($('grayRefinementView').value==='before'?beforeGrayKeys.get(jobId)||gridKeys.get(jobId):gridKeys.get(jobId)):undefined;
const algorithmName=()=>$('resultMode').value==='compressed'?('压缩后单网格'+(beforeGrayKeys.has(jobId)?($('grayRefinementView').value==='before'?' · 灰阶微调前':' · 灰阶微调后'):'')):pcView()?'压缩前完整补偿':'原生参数';
const pcJobs=new Set();
const photoGridEffect=()=>$('photoGridEffect').checked;
const photoGridMatches=r=>(r.grid_effect_enabled!==false)===photoGridEffect();
function clearActual(){if(actualUrl)URL.revokeObjectURL(actualUrl);actualUrl=undefined;$('photoActual').removeAttribute('src');$('photoActual').hidden=true;$('photoActualEmpty').hidden=false;$('photoActualClear').hidden=true;$('photoActualName').textContent='此栏为实际软件输出，不由模拟函数生成。';$('photoActualInput').value='';}
function slotPhotoMode(){return projectMode()&&$('photoSourceMode').value==='slot';}
function photoSlot(){
  if(!slotPhotoMode())return;
  const entry=collection.find(e=>e.number===selected);
  if(entry)return {project:workspace.id,slot:selected,key:JSON.stringify([workspace.id,entrySignature(entry)])};
}
function photoReady(){
  const slotMode=slotPhotoMode(), slot=photoSlot();
  $('photoSourceModeLabel').hidden=!projectMode();
  $('photoSourceMode').disabled=photoBusy;
  $('photoRender').disabled=photoBusy||!photoFile||!(slotMode?slot:validationJob);
  $('photoInput').disabled=photoBusy;
  $('photoGridEffect').disabled=photoBusy||(!slotMode&&!pcView());
  $('photoGridHint').textContent=slotMode
    ?'读取当前槽位已保存的配方和 B 基准照明端点。调整网格开关后可重新生成。'
    :'选择“压缩后单网格”可预览导出配方。原生参数相同时，切换网格可复用照片缓存。';
  if(slotMode&&photoShownSlot!==slot?.key)$('photoResults').hidden=true;
  if(slotMode&&!photoBusy&&$('photoResults').hidden)
    $('photoStatus').textContent=slot?'选择照片后可预览当前已保存槽位。':'请选择已保存的槽位。';
}
function showPhoto(value){
  const slotMode=slotPhotoMode(), r=value.result;
  if(slotMode){
    const slot=photoSlot();
    if(!slot||slot.key!==photoSlotRequest?.key||value.project!==slot.project||value.slot!==slot.slot||!photoGridMatches(r))return;
    photoShownSlot=slot.key;
  }else{
    if(value.project||value.job!==validationJob)return;
    if(Boolean(r.pc_compensation_enabled)!==pcView()||!photoGridMatches(r))return;
    if((r.grid_key||undefined)!==selectedGrid())return;
    if(r.grid_key&&r.grid_sha256!==diagnosticData?.grid_sha256)return;
    if(r.pc_compensation_enabled && r.pc_compensation_sha256!==diagnosticData?.pc_sha256)return;
  }
  photoSourceSha=value.result.source_sha256;
  const base='/api/previews/'+value.id+'/';
  $('photoResults').hidden=false;
  const reference={baseline:'任务基线 · 同一张 RAW','slot-baseline':'色卡 PT 基线 · 同一张 RAW','source-image':'输入参考 · 原图',lut:'目标颜色 · LUT'}[r.reference_kind]||'目标颜色 · LUT';
  $('photoReferenceTitle').textContent=reference;
  $('photoLut').alt=reference;
  $('photoLutDownload').download=reference+'.png';
  const name=slotMode?'槽位配方 · '+r.slot_name:algorithmName();
  $('photoModel').alt=name+'照片预览';$('photoModelTitle').textContent='效果 · '+name+((slotMode||pcView())?(photoGridEffect()?' · 网格开启':' · 网格关闭'):'');
  for(const [key,file]of[['Lut','lut.png'],['Model','model.png']]){ $('photo'+key).src=base+file;$('photo'+key+'Download').href=base+file; }
  $('photoAudit').href=base+'result.json';
  const origin=slotMode?`槽位 ${r.slot} · B 基准端点 · 配方 ${r.slot_bin_sha256.slice(0,12)}…`:`任务 ${value.job}`;
  $('photoProvenance').textContent=`${origin} · ${(r.source_format||'ARW').toUpperCase()} · ${r.width} × ${r.height} · 照片 SHA256 ${r.source_sha256.slice(0,16)}…`;
  $('photoStatus').textContent=r.reference_kind==='source-image'
    ? '已按 sRGB 输入近似模拟滤镜，第三栏可导入实际导出图。'
    : '两张图使用同一张 RAW，颜色前端为近似。第三栏可导入实际导出图。';
}
async function pollPhoto(){
  const id=photoId;
  try{const value=await(await api('/api/previews/'+id)).json();
    if(id!==photoId)return;
    const slot=photoSlot();
    const current=value.project?slot&&slot.key===photoSlotRequest?.key
      :!slotPhotoMode()&&value.job===validationJob;
    if(value.status==='done'||value.status==='error'){
      photoBusy=false;photoReady();
      if(value.status==='done'){showPhoto(value);if(current&&!value.project&&((value.result.grid_key||undefined)!==selectedGrid()||Boolean(value.result.pc_compensation_enabled)!==pcView()||!photoGridMatches(value.result)))loadDiagnostics(validationJob);}else if(current)$('photoStatus').textContent='预览失败：'+value.error;
      return;
    }
    if(current)$('photoStatus').textContent=value.phase;
    photoTimer=setTimeout(pollPhoto,2000);
  }catch(e){if(id!==photoId)return;photoBusy=false;photoReady();$('photoStatus').textContent='读取预览失败：'+e.message;}
}
const drafts = new Map();
const draftSources=new Map(), collectionSources=new Map();
let draftSource;
const parameterSignature=e=>JSON.stringify([e.cc1_delta,e.block13,e.gamma_native_129,e.grid_5x9x9]);
let compressedSignature;
function exportProject(entries=collection,sources=collectionSources){return {...project(entries),export_sources:Object.fromEntries(entries.filter(e=>sources.has(e.number)).map(e=>[String(e.number),clone(sources.get(e.number))]))};}
const projectMode=()=>typeof workspace!=='undefined'&&Boolean(workspace);
function gridSourceStatus(){
  if(projectMode()){
    const source=draftSource?.kind;
    $('stockGrid').value=source==='stock'?draftSource.id:'';
    $('gridSourceStatus').textContent='可编辑全部原生参数与网格。保存时校验原生范围。训练对比仍对应任务的原始配方。';
    $('add').disabled=slotState(selected).state!=='modified';
    return;
  }
  if(draftSource?.kind==='compressed'&&parameterSignature(draft)!==compressedSignature)draftSource=undefined;
  if(draftSource?.kind==='stock'){const p=boot.stock_grids.find(p=>p.id===draftSource.id);if(!p||JSON.stringify(p.grid_5x9x9)!==JSON.stringify(draft.grid_5x9x9))draftSource=undefined;}
  $('stockGrid').value=draftSource?.kind==='stock'?draftSource.id:'';
  const importedValid=draftSource?.kind==='imported-bin'&&parameterSignature(draft)===compressedSignature;
  $('gridSourceStatus').textContent=draftSource?.kind==='stock'?'已选择原厂网格；保留当前 CC1、block13 与 Gamma。':draftSource?.kind==='compressed'?'已绑定完成的压缩网格与本任务原生参数。':importedValid?'已绑定导入 BIN；可以改名称和槽号，色彩参数保持原样。':draftSource?.kind==='imported-bin'?'色彩参数已偏离导入 BIN；恢复原参数、选择原厂网格或重新训练后才能保存。':'尚未选择网格：选择原厂网格、导入 BIN 或完成压缩后才能加入导出集。';
  $('add').disabled=!draftSource||(draftSource.kind==='imported-bin'&&!importedValid);
}

let toastTimer;
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 6500); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-R5-Token':boot.token}, body:JSON.stringify(body)});
  if (!response.ok) { let value; try { value = await response.json(); } catch { value = {error:response.statusText}; } throw Error(value.error || '请求失败'); }
  return response;
}
function projectVersion(entries) { return entries.some(e=>e.number>12)?5:libraryVersion; }
function project(entries = collection) { return {...boot.template,schema:boot.config_schemas[String(projectVersion(entries))],entries:clone(entries)}; }
function readNames() { draft.short_name=$('shortName').value;draft.full_name=$('lookName').value; }
function showNames() { $('shortName').value=draft.short_name;$('lookName').value=draft.full_name; }
function remember() { if (draft) { readNames();drafts.set(selected, clone(draft));if(draftSource)draftSources.set(selected,clone(draftSource));else draftSources.delete(selected); } }
function syncRaw() {
  gridSourceStatus();$('rawEditor').value=JSON.stringify(draft,null,2);
  $('editStatus').textContent=projectMode()?'点击“保存本槽”后，参数将进入 BIN 导出。':'参数已更新；点击“加入导出集”保存本项。';
  updateSlotStates();if(projectMode()){invalidateSlotComparison();queueWorkspaceSave();}
}
function freshConfiguration(number) { return {...clone(boot.presets[1]),number,short_name:'F'+String(number).padStart(2,'0'),full_name:'自定义滤镜 '+number}; }
const entrySignature=e=>JSON.stringify([e.number,e.short_name,e.full_name,parameterSignature(e)]);
function slotState(number){
  const saved=collection.find(e=>e.number===number);
  const working=selected===number&&draft?draft:drafts.get(number);
  const source=selected===number&&draft?draftSource:draftSources.get(number);
  const changed=working&&(entrySignature(working)!==entrySignature(saved||freshConfiguration(number))||
    JSON.stringify(source)!==JSON.stringify(saved?collectionSources.get(number):undefined));
  const state=changed?'modified':saved?'configured':'empty';
  return {state,entry:working||saved};
}
function modifiedSlots(){return Array.from({length:boot.slot_limit},(_,i)=>i+1).filter(n=>slotState(n).state==='modified');}
function updateSlotStates(){
  let configured=0,empty=0,modified=0;
  for(const button of $('looks').children){
    const number=+button.dataset.number,{state,entry}=slotState(number);
    const label={configured:projectMode()?'已保存':'已配置',empty:'空槽',modified:'未保存修改'}[state];
    if(state==='configured')configured++;else if(state==='empty')empty++;else modified++;
    button.dataset.state=state;button.className='slot-button '+state+(number===selected?' active':'');
    const num=document.createElement('strong'),name=document.createElement('span'),status=document.createElement('small');
    num.textContent=String(number);name.className='slot-name';name.textContent=state==='empty'?'—':entry.short_name;
    status.textContent=label;button.replaceChildren(num,name,status);
    button.title=`槽位 ${number} · ${label}`+(state==='empty'?'':` · ${entry.full_name}`);
    button.setAttribute('aria-label',button.title);button.setAttribute('aria-pressed',number===selected?'true':'false');
  }
  $('slotSummary').textContent=`${projectMode()?'已保存':'已配置'} ${configured} · 空槽 ${empty} · 未保存修改 ${modified}`;
  $('discardSlot').disabled=slotState(selected).state!=='modified';
  $('moveSlot').disabled=!collection.some(e=>e.number===selected)||slotState(selected).state==='modified';
  // 工程模式由导出对话框明确决定是否纳入草稿。
  $('export').disabled=!projectMode()&&modified>0;$('saveProject').disabled=!projectMode()&&modified>0;
  if(projectMode())renderWorkspaceInspector();
}
function discardSlotChanges(){
  drafts.delete(selected);draftSources.delete(selected);draft=undefined;selectLook(selected);
}
function removeConfiguration(number){
  if(projectMode()){selectLook(number);$('workspaceClear').click();return;}
  collection=collection.filter(e=>e.number!==number);collectionSources.delete(number);
  drafts.delete(number);draftSources.delete(number);
  if(selected===number){draft=undefined;selectLook(number);}
  renderCollection();
}
function moveConfiguration(target){
  const entry=collection.find(e=>e.number===selected);
  if(!entry||slotState(selected).state==='modified')throw Error('请先将本槽修改加入导出集，再移动配置');
  if(!Number.isInteger(target)||target<1||target>boot.slot_limit)throw Error('目标槽号必须是1～24的整数');
  if(target===selected)return;
  if(slotState(target).state!=='empty')throw Error('目标槽已有配置或未保存修改，请选择空槽');
  const source=clone(collectionSources.get(selected)),number=selected;
  collection=collection.filter(e=>e.number!==number);collection.push({...clone(entry),number:target});
  collectionSources.delete(number);collectionSources.set(target,source);
  drafts.delete(number);draftSources.delete(number);drafts.delete(target);draftSources.delete(target);
  draft=undefined;selected=target;renderCollection();selectLook(target);toast(`配置已移到 ${target} 号，原 ${number} 号为空槽`);
}
function applyImportedProject(value){
  // BIN不带训练目标；切断旧任务的异步回写，避免旧预览被误认为导入配方的结果。
  jobId=undefined;validationJob=undefined;diagnosticData=undefined;diagnosticSerial++;
  clearTimeout(timer);clearTimeout(compressionTimer);
  $('trainingResult').hidden=true;$('jobDownload').hidden=true;$('photoResults').hidden=true;
  $('rawExport').disabled=true;photoReady();
  $('jobStatus').textContent='配置库已导入；仅载入最终配方，不包含目标图、LUT 或训练记录。';
  $('previewBadge').textContent='导入配方 · 无训练预览';
  $('histStatus').textContent='载入训练任务后生成对比；BIN不包含训练目标。';
  $('rawTask').textContent='请载入训练任务后再验证 RAW。';
  if(!slotPhotoMode())$('photoStatus').textContent='请载入训练任务后再验证照片。';
  for(const canvas of document.querySelectorAll('.palettes canvas,.histograms canvas,.probe-grid canvas,#sector16Cohort canvas'))canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
  for(const metric of document.querySelectorAll('#metrics strong'))metric.textContent='—';
  collection=clone(value.entries);libraryVersion=value.schema===boot.config_schemas['5']?5:4;
  collectionSources.clear();for(const entry of collection)collectionSources.set(entry.number,clone(value.export_sources[String(entry.number)]));
  drafts.clear();draftSources.clear();draft=undefined;renderCollection();selectLook(collection[0]?.number||1);
}
function cancelLibraryImport(){pendingImport=undefined;$('importDialog').close();}
function confirmLibraryImport(){
  if(!pendingImport)return;
  if(projectMode()){finishWorkspaceImport(false);return;}
  applyImportedProject(pendingImport);pendingImport=undefined;$('importDialog').close();toast('配置库已载入，导出集已替换');
}
async function importConfiguration(file,kind){
  if(!file)return;
  if(busy||compressionBusy||chartUploading||libraryImportBusy){toast('请等待当前任务完成后导入配置库');return;}
  libraryImportBusy=true;$('importBin').disabled=true;$('importProject').disabled=true;$('fit').disabled=true;
  try{
    let value,sha256;
    if(kind==='bin'){
      if(!/\.bin$/i.test(file.name)||file.size<128||file.size>58976)throw Error('请选择128～58976字节的 R5NATIVE.BIN（v4／v5）');
      const response=await fetch('/api/import-bin',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:file});
      const result=await response.json();if(!response.ok)throw Error(result.error);value=result.project;sha256=result.audit?.binary_sha256;
    }else{
      if(file.size>boot.max_project_bytes)throw Error('配置 JSON 超过 2 MiB');
      value=JSON.parse(await file.text());if(!value.export_sources&&!projectMode())throw Error('旧配置缺少网格来源，请重新选择原厂网格或重新压缩');
      await api('/api/validate',value);
    }
    const slots=value.entries.map(e=>e.number);
    if(projectMode()){
      const conflicts=slots.filter(n=>slotState(n).state!=='empty');
      $('importPreview').textContent=`${file.name} · ${slots.length} 项配方
槽位 ${slots.join('、')||'无'}
`+
        (conflicts.length?'与当前工程冲突的槽位 '+conflicts.join('、')+'。请选择导入为新工程。':'可建立独立工程'+(sha256?'，或按原槽号合并到空槽。':'。'));
      pendingImport={config:value,sha256,name:file.name};
      $('workspaceMerge').disabled=!sha256||conflicts.length>0;
      $('importDialog').showModal();return;
    }
    $('importPreview').textContent=`${file.name} · ${value.schema===boot.config_schemas['5']?'v5／二十四槽':'v4／十二槽'}\n已配置 ${slots.length} 项：${slots.join('、')||'无'}\n其余 ${boot.slot_limit-slots.length} 个槽位为空。\n确认后替换当前页面的整个配置库及草稿；当前 ${collection.length} 项配置、${modifiedSlots().length} 个未保存槽位将被替换。原始 BIN 文件不修改。`;
    pendingImport=value;$('importDialog').showModal();
  }catch(error){toast(error.message);}
  finally{libraryImportBusy=false;$('importBin').disabled=busy||compressionBusy;$('importProject').disabled=busy||compressionBusy;$('fit').disabled=busy||compressionBusy||chartUploading;}
}
function renderSlots() {
  $('looks').replaceChildren();
  Array.from({length:boot.slot_limit},(_,i)=>{const b=document.createElement('button');b.textContent=String(i+1);b.title='自定义配置 '+(i+1);b.dataset.number=i+1;b.onclick=()=>selectLook(i+1);$('looks').append(b);});
}
function baselineNote() {
  const i=+$('baselineLook').value,p=boot.provenance[i];
  $('sourceNote').textContent=`编辑基线：${chineseNames[i]}（${names[i]}）。配置编号独立；机内原厂创意外观另行选择，其附加处理仍保留。`;
  $('sourceNote').title=JSON.stringify(p);
}
function selectLook(number) {
  remember(); selected = number;
  draft = clone(drafts.get(number) || collection.find(e => e.number === number) || freshConfiguration(number));
  draftSource=clone(drafts.has(number)?draftSources.get(number):collectionSources.get(number));
  compressedSignature=draftSource?.kind==='compressed'?parameterSignature(draft):draftSource?.kind==='imported-bin'?parameterSignature(collection.find(e=>e.number===number)||draft):undefined;
  showNames();
  $('moveSlotTarget').value=number;
  document.querySelectorAll('.looks button').forEach(b => { b.classList.toggle('active', +b.dataset.number === number); b.setAttribute('aria-pressed', +b.dataset.number === number ? 'true' : 'false'); });
  baselineNote();renderEditors();
}
function renderEditors() { renderGamma(); renderCC(); renderMatrix(); if(projectMode())renderGrid();syncRaw(); }
function cell(value, low, high, change) {
  const td = document.createElement('td'), input = document.createElement('input');
  input.type = 'number'; input.step = '1'; input.min = low; input.max = high; input.value = value;
  input.addEventListener('change', () => { const v = Number(input.value); if (input.value === '' || !Number.isInteger(v) || v < low || v > high) { input.classList.add('invalid'); toast(`请输入 ${low}…${high} 的整数`); return; } input.classList.remove('invalid'); change(v); syncRaw(); });
  td.append(input); return td;
}
function header(table, values) { table.replaceChildren(); const tr = document.createElement('tr'); for (const text of values) { const th = document.createElement('th'); th.textContent = text; tr.append(th); } table.append(tr); }
function renderCC() {
  const table = $('ccTable'); header(table,['端点','色度混合一','色度混合二','色度混合三','色度混合四','色度增益一','色度增益二','色度增益三','色度增益四']);
  ['基准值','照明一差值','照明二差值'].forEach((label,g)=>{const tr=document.createElement('tr'), title=document.createElement('td'); title.textContent=label;tr.append(title);draft.cc1_delta[g].forEach((v,i)=>tr.append(cell(v,-32768,32767,n=>draft.cc1_delta[g][i]=n)));table.append(tr);});
}
function renderMatrix() {
  const table=$('matrixTable'), g=+$('matrixEndpoint').value;header(table,['色相','红减绿','红减蓝','绿减红','绿减蓝','蓝减红','蓝减绿']);
  draft.block13[g].forEach((row,s)=>{const tr=document.createElement('tr'), title=document.createElement('td');title.textContent=String(s).padStart(2,'0');tr.append(title);row.forEach((v,i)=>tr.append(cell(v,-8192,8191,n=>draft.block13[g][s][i]=n)));table.append(tr);});
}
function renderGamma() {
  let point=Math.max(0,Math.min(128,+$('gammaIndex').value || 0));$('gammaIndex').value=point;$('gammaValue').value=draft.gamma_native_129[point];
  const canvas=$('gammaChart'), ctx=canvas.getContext('2d'), w=canvas.width,h=canvas.height,pad={l:52,r:16,t:20,b:28}, iw=w-pad.l-pad.r,ih=h-pad.t-pad.b;
  ctx.clearRect(0,0,w,h);ctx.font='12px system-ui';
  for(let i=0;i<=4;i++){const y=pad.t+ih*i/4;ctx.strokeStyle='#e9ede4';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillStyle='#87917f';ctx.fillText(Math.round(131071*(1-i/4)).toLocaleString(),0,y+4);}
  for(let i=0;i<=4;i++){const x=pad.l+iw*i/4;ctx.fillStyle='#87917f';ctx.fillText(String(i*32),x-7,h-5);}
  const plot=(values,color,width)=>{ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();values.forEach((v,i)=>{const x=pad.l+iw*i/128,y=pad.t+ih*(1-v/131071);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();};
  plot(boot.presets[+$('baselineLook').value].gamma_native_129,'#ced6c6',2);plot(draft.gamma_native_129,'#31583f',2.8);
  ctx.fillStyle='#31583f';ctx.beginPath();ctx.arc(pad.l+iw*point/128,pad.t+ih*(1-draft.gamma_native_129[point]/131071),5,0,Math.PI*2);ctx.fill();
}
function renderCollection() {
  const node=$('collection');node.replaceChildren();collection.sort((a,b)=>a.number-b.number);
  if(!collection.length){const p=document.createElement('p');p.className='empty';p.textContent='导出空配置可清空机内自定义滤镜';node.append(p);}
  for(const entry of collection){const row=document.createElement('div');row.className='collection-row';const n=document.createElement('span');n.className='number';n.textContent=entry.number;const info=document.createElement('div'),name=document.createElement('strong'),sub=document.createElement('small');name.textContent=entry.full_name;sub.textContent=`${entry.short_name} · 独立配置 ${entry.number} · 5×9×9 网格`;info.append(name,sub);const edit=document.createElement('button');edit.textContent='编辑';edit.onclick=()=>selectLook(entry.number);const remove=document.createElement('button');remove.textContent='×';remove.setAttribute('aria-label','从导出集移除 '+entry.full_name);remove.onclick=()=>removeConfiguration(entry.number);row.append(n,info,edit,remove);node.append(row);}
  const version=projectVersion(collection);
  $('exportStatus').textContent=`${collection.length} / ${boot.slot_limit} 项 · v${version} · ${version===5?'需本地24槽固件':'兼容原十二槽格式'} · 完整替换${collection.length?'':'，清空全部自定义滤镜'}`;
  updateSlotStates();
}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function palette(id,colors){const canvas=$(id),ctx=canvas.getContext('2d'),cols=24,rows=4;ctx.clearRect(0,0,canvas.width,canvas.height);for(let i=0;i<cols*rows;i++){const c=colors[Math.floor(i*colors.length/(cols*rows))];ctx.fillStyle=`rgb(${c.map(v=>Math.round(v*255)).join(',')})`;ctx.fillRect(i%cols*canvas.width/cols,Math.floor(i/cols)*canvas.height/rows,canvas.width/cols+1,canvas.height/rows+1);}}
function showResult(result){
  for(const id of ['before','target','after'])palette(id,result.preview[id]);
  const b=result.heldout.before,a=result.heldout.after;
  $('metrics').replaceChildren();for(const [key,title]of[['mae_8bit','平均绝对误差 / 8位'],['rmse_8bit','均方根误差 / 8位'],['p95_8bit','95%误差分位 / 8位']]){const div=document.createElement('div'),label=document.createElement('span'),value=document.createElement('strong'),sub=document.createElement('small');label.textContent=title;value.textContent=a[key].toFixed(2);sub.textContent=`基线 ${b[key].toFixed(2)}`;div.append(label,value,sub);$('metrics').append(div);}
  $('previewBadge').textContent=result.white_balance?.enabled?'实验白平衡模型 · BIN 不含白平衡':'模型结果 · 实拍待验收';
  if(projectMode()){showWorkspaceCandidate(result);return;}
  const entry=clone(result.config.entries[0]);drafts.set(entry.number,entry);draftSources.delete(entry.number);
  if(selected===entry.number){draftSource=undefined;draft=entry;showNames();renderEditors();}else toast('拟合结果已保存到对应外观，点击该外观查看。');
  toast(result.grid_key?'滤镜已生成；检查压缩后结果，再将原生参数与网格加入导出集。':'拟合完成；结果已载入编辑器，检查后加入导出集。');
  updateSlotStates();
}
function setBusy(value){busy=value;for(const id of ['targetKind','chartVersion','chartTarget','lut','gamut','speedPriority','evaluations','endpoint','wbTraining','trainingShortName','trainingFullName','weightRandom','weightPrimaries','weightGray','weightCC24','weightSector16','resetWeights','parameterSmoothing','outputContinuity','searchStarts','adaptiveRounds','gammaColorRounds','perceptualWeight','quantizationSweeps','adamLearningRate','adamSteps'])$(id).disabled=value;$('pcTraining').disabled=true;$('pcCurveMode').disabled=true;$('pcGridEnabled').disabled=true;$('fit').disabled=value||compressionBusy||chartUploading;$('cancel').hidden=!value;if(value){validationJob=undefined;$('rawExport').disabled=true;$('rawTask').textContent='拟合运行中，等待当前任务配方。';photoReady();$('photoResults').hidden=true;$('photoStatus').textContent='拟合运行中，等待当前任务配方。';}}
function histogram(canvas, target, after, color) {
  const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,left=54,top=15,bottom=h-30,iw=w-left-12,ih=bottom-top;
  const peak=Math.max(...target,...after,1e-9);
  ctx.clearRect(0,0,w,h);ctx.font='12px system-ui';ctx.lineWidth=1;ctx.setLineDash([]);
  for(let i=0;i<=4;i++){const y=top+ih*i/4;ctx.strokeStyle='#e3e8de';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(w-12,y);ctx.stroke();ctx.fillStyle='#74816e';ctx.fillText((peak*(1-i/4)*100).toFixed(1)+'%',0,y+4);}
  ctx.fillStyle=color+'30';for(let i=0;i<256;i++){const v=Math.min(target[i],after[i]);ctx.fillRect(left+iw*i/256,bottom-ih*v/peak,iw/256+1,ih*v/peak);}
  for(const [values,dash,stroke]of[[target,[],color],[after,[7,4],'#263b30']]){ctx.strokeStyle=stroke;ctx.lineWidth=1.8;ctx.setLineDash(dash);ctx.beginPath();values.forEach((v,i)=>{const x=left+iw*i/255,y=bottom-ih*v/peak;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}ctx.setLineDash([]);
  for(const i of [0,64,128,192,255]){ctx.fillStyle='#74816e';ctx.fillText(String(i),left+iw*i/255-7,h-8);}
}
function strip(id, colors){const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);colors.forEach((rgb,i)=>{ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(Math.min(1,Math.max(0,v))*255)).join(',')})`;ctx.fillRect(i*c.width/colors.length,0,c.width/colors.length+1,c.height);});}
function chart24(id,colors){const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);colors.forEach((rgb,i)=>{ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(Math.max(0,Math.min(1,v))*255)).join(',')})`;ctx.fillRect(i%6*120,Math.floor(i/6)*120,118,118);});}
function renderComparison(){
  if(!diagnosticData)return;
  const groups=diagnosticData.tonal.groups,key=$('comparisonMode').value,g=groups[key],h=g.histogram;
  $('tonalMetrics').replaceChildren();
  const table=document.createElement('table');header(table,['分区','样本数','平均绝对误差','均方根误差','95%误差分位','平均 ΔE00','亮度 L* RMSE','染色 a*b* RMSE']);
  for(const item of Object.values(groups)){const tr=document.createElement('tr');for(const value of [item.label,item.samples,...(item.metrics?[item.metrics.mae,item.metrics.rmse,item.metrics.p95,item.metrics.perceptual?.delta_e00_mean,item.metrics.perceptual?.lightness_rmse,item.metrics.perceptual?.ab_rmse].map(v=>v===undefined?'—':v.toFixed(2)):Array(6).fill('—'))]){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}$('tonalMetrics').append(table);
  ['Red','Green','Blue'].forEach((c,i)=>{if(h){histogram($('hist'+c),h.target[i],h.after[i],['#be4f4b','#4e8958','#4a73b7'][i]);$('hist'+c+'Title').textContent=['红色','绿色','蓝色'][i]+'通道 · 重合 '+h.overlap_percent[i].toFixed(2)+'% · RMSE '+g.metrics.channel_rmse[i].toFixed(2);}else{const canvas=$('hist'+c);canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);$('hist'+c+'Title').textContent=['红色','绿色','蓝色'][i]+'通道 · 无样本';}});
  $('histMean').textContent=h?'平均重合 '+h.mean_overlap_percent.toFixed(2)+'%':'无样本';
  $('histStatus').textContent=`${g.label}：${g.samples} 个独立测试样本。表格误差为真实 8 位整数 RGB 的码值误差；不扣黑。`;
  const m=groups.all.metrics,values=[m.mae,m.rmse,m.p95];
  document.querySelectorAll('#metrics strong').forEach((el,i)=>el.textContent=values[i].toFixed(2));
  document.querySelectorAll('#metrics small').forEach(el=>el.textContent='双方量化为 8 位后计算');
}

function renderNativeStages(fitting){
  const area=$('nativeStages');area.replaceChildren();
  if(!fitting?.training_pipeline){area.textContent='历史任务未使用新版分阶段原生训练；重新拟合后生效。';return;}
  const table=document.createElement('table');header(table,['训练阶段','灰阶训练 RMSE','验证 RMSE','验证 ΔE00','固定评分']);
  const labels={'baseline':'原厂基线','monotone-seed':'初始单调曲线','native-gray-tone-gamma-only':'① 仅 Gamma · 灰阶明暗','train-precondition':'② 原生颜色初始化','train-precondition-tone':'② 明暗曲线后的颜色初始化','gray-first':'③ 历史灰阶优先','gray-refinement-candidate':'③ 灰阶专项候选（等权选优）','native-chroma-cc1-block13-gamma-frozen':'④ 固定 Gamma · CC1 / block13','gray-priority-joint':'⑤ 历史灰阶优先联合优化','balanced-joint':'⑤ 四组等权联合优化','weighted-joint':'⑤ 按设置权重联合优化'};
  for(const row of fitting.history){const [stage,strategy]=row.label.split(' / ');if(!labels[stage]&&!/^(integrated-native-PC-|multi-start-|adaptive-round-|integer-refinement|PC-integer-refinement)/.test(stage))continue;const tr=document.createElement('tr');const suffix=strategy==='dense-compressed'?' · 大网格压缩':strategy==='direct'?' · 直接小网格':'';for(const value of [(labels[stage]||(stage.startsWith('multi-start-')?'多起点 '+stage.split('-').at(-1):stage.startsWith('adaptive-round-')?'动态权重第 '+stage.split('-').at(-1)+' 轮':stage.includes('integer-refinement')?'量化后微调':'⑥ 原生与 PC 交替 '+stage.split('-').at(-1)))+suffix+(row.label===fitting.selected?' · 已选':''),row.gray_training?.rmse_8bit?.toFixed(3)??'—',row.validation.rmse_8bit.toFixed(3),row.perceptual_validation?.delta_e00_mean?.toFixed(3)??'—',row.selection_score?.toFixed(3)??'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);}
  const note=document.createElement('p');note.className='hint';note.textContent=(fitting.pc_compensation_training?'阶段指标按原生参数 + PC 残差整链评估。':'阶段指标按原生参数评估。')+(fitting.group_total_weights?`本任务总权重：随机色 ${fitting.group_total_weights.random} / 正色 ${fitting.group_total_weights.primaries} / 灰阶 ${fitting.group_total_weights.gray} / 24色 ${fitting.group_total_weights.colorchecker24}${fitting.group_total_weights.sector16!=null?' / 矩阵16色相 '+fitting.group_total_weights.sector16:''}。`:'')+'验证集只参与候选选择；独立测试不参与求解或选择。';area.append(table,note);if(fitting.tonal_balance){const tone=document.createElement('p');tone.className='hint';const c=fitting.tonal_balance.counts.random;tone.textContent=`已启用亮度分层平衡：以固定 ST 基线分区，组内阴影／中间调／高光等总权重；随机训练样本原始覆盖 ${c.train.join(' / ')}，验证 ${c.valid.join(' / ')}，独立测试 ${c.test.join(' / ')}。上述为完整数据分组计数，求解保留既有随机子采样；缺失分区不虚构样本。上方输出分区统计仍按 LUT 目标划分。`;area.append(tone);}if(fitting.search_options){const extra=document.createElement('p');extra.className='hint';extra.textContent=`本任务平滑 ${fitting.search_options.parameter_smoothing ?? 0} / 输出连续性 ${fitting.search_options.output_continuity ?? 0} / ${fitting.search_options.starts} 个搜索起点 / 动态权重 ${fitting.search_options.adaptive_rounds} 轮 / Gamma与色彩交替 ${fitting.search_options.gamma_color_rounds ?? 0} 轮 / 感知权重 ${fitting.search_options.perceptual_weight} / 量化微调 ${fitting.search_options.quantization_sweeps} 轮。`;area.append(extra);if(fitting.adaptive_history?.length){const log=document.createElement('p');log.className='hint';log.textContent=fitting.adaptive_history.map(r=>`第 ${r.round} 轮权重：`+Object.values(r.weights).map(v=>v.toFixed(2)).join(' / ')).join('；');area.append(log);}}
  renderOutputContinuity(area,fitting.output_continuity);
}
function renderOutputContinuity(area,report){
  if(!report?.enabled)return;
  const title=document.createElement("p");title.className="hint";title.textContent=`输出连续性探针：${report.probes} 个颜色、${report.triplets} 组局部邻点。检查实际整数输出；数值越低表示局部色度变化越平顺。`;
  const table=document.createElement("table");header(table,["连续变化方向","色度二阶差分 P95","最大值"]);
  const names={"dark-exposure":"暗部明暗","full-exposure":"全范围明暗","hue":"局部色相","saturation":"局部饱和度"};
  for(const [name,m] of Object.entries(report.axes)){const tr=document.createElement("tr");for(const value of [(name.startsWith("native-")?"预矩阵 · "+names[name.slice(7)]:"色卡 · "+(names[name]||name)),m.chroma_second_difference_p95.toFixed(3),m.chroma_second_difference_max.toFixed(3)]){const td=document.createElement("td");td.textContent=value;tr.append(td);}table.append(tr);}
  area.append(title,table);
}
function renderPCReport(report){
  const area=$('pcStages');area.replaceChildren();area.hidden=!report;$('pcCurves').hidden=!report?.curves;
  if(!report)return;
  const qaqMode=report.curves?.mode==='qaq-grid';
  const rgbMode=report.curves?.mode==='rgb-independent';
  if(qaqMode)$('pcCurves').hidden=true;
  const table=document.createElement('table');header(table,['阶段','灰阶训练 RMSE','独立测试 RMSE','独立测试 ΔE00']);
  for(const [key,label]of [['native','原生模型'],['tone',rgbMode?'① RGB 独立曲线':'① 灰阶明暗'],['tint',rgbMode?'RGB 曲线输出':'② 灰阶染色'],['compensated',report.curves?(report.fitting?.strategy==='none'?'最终输出（未启用网格）':(qaqMode?gridResponseName(report.response):'③ 彩色网格（保护灰阶）')):'旧版单网格']]){
    if(qaqMode&&['tone','tint'].includes(key))continue;const gray=report.metrics.gray_training[key],test=report.metrics.test[key];if(!gray||!test)continue;
    const tr=document.createElement('tr');for(const value of [label,gray.rmse.toFixed(3),test.rmse.toFixed(3),test.perceptual?.delta_e00_mean?.toFixed(3)??'—']){const td=document.createElement('td');td.textContent=value;tr.append(td);}table.append(tr);
  }area.append(table);
  if(report.fitting?.strategy){const note=document.createElement("p");note.className="hint";note.textContent=report.fitting.strategy==='none'?'仅独立曲线／曲线阶段，未启用三维网格。':report.fitting.strategy==="dense-compressed"?"已选：17×33×33 大网格 → 密集采样压缩 → 5×9×9 / 7位。":"已选：直接拟合 5×9×9 小网格。";area.append(note);}
  if(qaqMode){const note=document.createElement("p");note.className="hint";note.textContent="网格响应："+JSON.stringify(report.response)+"。"+(Array.isArray(report.response)?"BT.601 暂定坐标 → 三线性插值 / 256 → 固定响应 → 加回原生输出。":"按任务保存的实测坐标与响应预测；覆盖范围以任务绑定模型报告为准，未覆盖区域为外推。");area.append(note);return;}
  if(!report.curves)return;
  const v=report.curves;
  function plot(id,series,low,high){
    const canvas=$(id),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,p=30;
    ctx.clearRect(0,0,w,h);ctx.strokeStyle='#d7dce2';ctx.lineWidth=1;
    for(let i=0;i<=4;i++){const y=p+(h-2*p)*i/4;ctx.beginPath();ctx.moveTo(p,y);ctx.lineTo(w-p,y);ctx.stroke();ctx.fillStyle='#667085';ctx.font='12px sans-serif';ctx.fillText(((high-(high-low)*i/4)*255).toFixed(0),1,y+4);}
    if(low<0){const y=p+high/(high-low)*(h-2*p);ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(p,y);ctx.lineTo(w-p,y);ctx.stroke();ctx.setLineDash([]);}
    for(const [values,color]of series){ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=2;values.forEach((y,i)=>{const x=p+v.axis[i]*(w-2*p),yy=p+(high-y)/(high-low)*(h-2*p);if(i)ctx.lineTo(x,yy);else ctx.moveTo(x,yy);});ctx.stroke();}
    ctx.fillStyle='#667085';ctx.fillText('0',p,h-5);ctx.fillText('255',w-p-22,h-5);
  }
  $('pcToneTitle').textContent=rgbMode?'RGB 独立曲线 · 各通道输入 → 输出':'灰阶亮度曲线';$('pcTintTitle').textContent=rgbMode?'RGB 独立曲线 · 相对恒等映射偏移':'灰阶染色曲线 · 红 / 绿 / 蓝通道偏移';
  if(rgbMode){const colors=['#be4f4b','#4e8958','#4a73b7'];plot('pcToneCurve',[0,1,2].map(c=>[v.rgb.map(row=>row[c]),colors[c]]),0,1);const offset=v.rgb.map((row,i)=>row.map(x=>x-v.axis[i]));const range=Math.max(8/255,...offset.flat().map(Math.abs))*1.15;plot('pcTintCurve',[0,1,2].map(c=>[offset.map(row=>row[c]),colors[c]]),-range,range);return;}
  plot('pcToneCurve',[[v.tone,'#5e6977']],0,1);
  const bound=Math.max(8/255,...v.tint.flat().map(Math.abs))*1.15;
  plot('pcTintCurve',[0,1,2].map((c)=>[v.tint.map(row=>row[c]),['#be4f4b','#4e8958','#4a73b7'][c]]),-bound,bound);
}

async function loadDiagnostics(identifier){
  $('resultMode').disabled=true;
  const request=++diagnosticSerial;const changingJob=validationJob!==identifier;
  let compression;
  try{compression=await(await api('/api/jobs/'+identifier+'/grid-training')).json();}
  catch(e){if(request===diagnosticSerial){$('resultMode').disabled=false;$('histStatus').textContent='压缩状态读取失败：'+e.message;}return;}
  if(request!==diagnosticSerial||identifier!==jobId)return;
  if(compression.key)gridKeys.set(identifier,compression.key);else gridKeys.delete(identifier);
  if(compression.report?.before_gray_refinement_key)beforeGrayKeys.set(identifier,compression.report.before_gray_refinement_key);else beforeGrayKeys.delete(identifier);
  $('grayRefinementViewFields').hidden=!beforeGrayKeys.has(identifier);
  $('grayRefinementView').disabled=$('resultMode').value!=='compressed';
  if(changingJob)$('grayRefinementView').value='after';
  $('resultMode').querySelector('option[value=compressed]').disabled=!compression.key;

  if(['queued','running'].includes(compression.status)){compressionBusy=true;pollCompression(identifier);}

  $('fit').disabled=busy||compressionBusy||chartUploading;$('distillStatus').textContent='';$('distillMetrics').replaceChildren();$('distillGray').hidden=true;$('distillDownload').hidden=true;$('gridFirmwareDownload').hidden=true;$('addCompressed').hidden=true;
  if(changingJob){photoSourceSha=undefined;clearActual();$('resultMode').value=gridKeys.has(identifier)?'compressed':pcJobs.has(identifier)?'pc':'native';}
  if($('resultMode').value==='compressed'&&!gridKeys.has(identifier))$('resultMode').value=pcJobs.has(identifier)?'pc':'native';
  $('resultMode').querySelector('option[value=pc]').disabled=!pcJobs.has(identifier);$('pcDownload').hidden=!pcJobs.has(identifier);$('pcDownload').href='/api/jobs/'+identifier+'/pc-download';$('trainingResult').hidden=false;
  $('grayRefinementView').disabled=$('resultMode').value!=='compressed';
  if(compression.report)renderCompression(compression.report,compression.key,identifier);
  if(selectedGrid()&&selectedGrid()!==compression.key){
    try{const before=await(await api('/api/jobs/'+identifier+'/grid-training?key='+selectedGrid())).json();
      if(request===diagnosticSerial&&before.report)strip('distillStudentGray',before.report.samples.gray_grid);
    }catch(e){if(request===diagnosticSerial)$('histStatus').textContent=e.message;}
  }
  if(request!==diagnosticSerial||identifier!==jobId)return;
  validationJob=undefined;$('rawExport').disabled=true;$('rawTask').textContent='正在读取当前任务配方…';
  photoReady();
  if(!slotPhotoMode()){$('photoResults').hidden=true;$('photoStatus').textContent='正在载入任务配方…';}
  $('histStatus').textContent='正在计算测试集直方图与必拟合色卡…';
  try{const data=await(await api('/api/jobs/'+identifier+'/diagnostics?pc='+(pcView()?'1':'0')+'&grid='+(selectedGrid()||''))).json();if(identifier!==jobId||request!==diagnosticSerial)return;
    diagnosticData=data;$('datasetStatus').textContent=data.dataset?.dataset_id?.startsWith('v4.5-')?'v4.5 · 5300K · 99,372 色块 · 中心5点均值（'+(data.dataset?.edit_validated?'Edit实采验证：模拟输入全部一致，最终PT输出1块微差':'PT模拟派生上下文，按任务保存的验证状态')+'）':data.dataset?.dataset_id==='v4-sony100mp-unity-sim-center5-20261027'?'v4 · unity-WB · 99,372 色块 · Edit PT 已验证 · 中心5点均值':'历史任务：按保存的色卡和基线显示';if(chartJob())$('datasetStatus').textContent+=' · 软件处理色卡目标（'+data.dataset.bits_per_channel+' 位 '+data.dataset.file_format.toUpperCase()+'）';renderComparison();renderNativeStages(data.training_fitting);if(data.training_fitting?.convergence?.length){const rows=data.training_fitting.convergence;$('convergenceNote')?.remove();const note=document.createElement('p');note.id='convergenceNote';note.className='hint';note.textContent='求解诊断：'+rows.map(r=>r.stage+'：'+(r.budget_exhausted?'达到评估上限':r.converged?'已满足收敛条件':'未收敛')+'（'+r.evaluations+'次，最优性 '+r.optimality.toExponential(2)+'）').join('；');$('trainingPolicy').after(note);}renderPCReport(data.grid_key?null:data.pc_report);$('trainingPolicy').textContent=data.fitting_policy+(data.white_balance?.enabled?` 白平衡联合训练（实验）：冷暖 ${data.white_balance.parameters.temperature_shift} K，绿／洋红 ${data.white_balance.parameters.tint}；LUT 目标固定，前端动态响应近似。BIN 不含白平衡。`:'');$('trainingBadge').textContent=pcJobs.has(identifier)?'含 PC 补偿':'仅原生参数';
    if(data.pc_enabled){palette('after',data.test_preview);$('previewBadge').textContent=algorithmName()+' · 非机内';}else{const native=await(await api('/api/jobs/'+identifier)).json();if(identifier!==jobId||request!==diagnosticSerial)return;palette('after',native.result.preview.after);$('previewBadge').textContent='原生参数模型 · 实拍待验收';}
    const n=data.native_tonal.groups.all.metrics,c=data.tonal.groups.all.metrics;
    $('pcStatus').textContent=data.pc_enabled?`${algorithmName()} · 独立测试 RMSE：原生 ${n.rmse.toFixed(2)} → 当前 ${c.rmse.toFixed(2)}；灰阶色卡已显示补偿后结果。导出需选择原厂网格或完成压缩。`:'当前显示原生结果；新任务可在导入目标后开启 PC 补偿整体训练。';
    if(data.colorchecker24){
      for(const [key,title]of[['before','Before'],['target','Target'],['after','After']])chart24('cc24'+title,data.colorchecker24[key]);
      $('cc24Status').textContent='24 色全部参与优化 · 训练 RMSE / 8位：'+data.colorchecker24.metrics.after.rmse_8bit.toFixed(2)+'；顺序：'+data.colorchecker24.names.join('、');
    }else{
      for(const id of ['cc24Before','cc24Target','cc24After']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('cc24Status').textContent='此历史任务未包含标准 24 色，请重新拟合。';
    }
    if(data.sector16){
      const sector=data.sector16;
      for(const [key,title]of[['before','Before'],['target','Target'],['after','After']]){
        const canvas=$('sector16'+title),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
        sector[key].forEach((rgb,i)=>{const row=i<48?i%3:3,col=i<48?Math.floor(i/3):i-48;ctx.fillStyle=`rgb(${rgb.map(v=>Math.round(v*255)).join(',')})`;ctx.fillRect(col*48,row*30,48,30);});
      }
      $('sector16Status').textContent=`64 个实采训练代表色 · RMSE / 8位 ${sector.metrics.after.rmse_8bit.toFixed(2)}（基线 ${sector.metrics.before.rmse_8bit.toFixed(2)}）。前三行为每节点三种明暗，末行为过渡色。基准最大坐标偏差 ${sector.audit.maximum_sector_error}/1024 圈。`;
      const table=document.createElement('table');header(table,['节点','目标坐标','基准实测坐标','当前实测坐标','RMSE / 8位']);
      for(let i=0;i<16;i++){const row=table.insertRow();for(const value of [i+1,sector.audit.knots[i],sector.audit.records.slice(i*3,i*3+3).map(r=>r.measured_sector).join(' / '),sector.current_sectors.slice(i*3,i*3+3).join(' / '),sector.nodes[i].metrics.rmse_8bit.toFixed(2)])row.insertCell().textContent=String(value);}
      $('sector16Details').replaceChildren(table);
    }else{
      for(const id of ['sector16Before','sector16Target','sector16After']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('sector16Details').replaceChildren();$('sector16Status').textContent='历史任务未启用矩阵16色相训练分组，请重新拟合。';
    }
    if(data.anchors){
      for(const [key,title]of[['input','Input'],['target','Target'],['after','After']]){strip('primary'+title,data.anchors[key].slice(0,4));strip('gray'+title,data.anchors[key].slice(4,260));}
      const m=data.anchors.metrics;
      $('anchorStatus').textContent=`${data.fitting_policy||'历史任务；请重新拟合以应用当前四组等权设置。'} 全部 ${data.anchors.input.length} 个色块参与优化${data.white_balance?.enabled?'，白平衡前端使用实验近似':data.dataset?.dataset_id?.startsWith('v4.5-')?'，前端为5300K模拟派生上下文':'，前端为已验证的 unity-WB 模拟数据'}。正色训练 RMSE / 8位：${m.primaries.after.rmse_8bit.toFixed(2)}（基线 ${m.primaries.before.rmse_8bit.toFixed(2)}）；灰阶训练 RMSE / 8位：${m.gray.after.rmse_8bit.toFixed(2)}（基线 ${m.gray.before.rmse_8bit.toFixed(2)}）。`;
    }else{
      for(const id of ['primaryInput','primaryTarget','primaryAfter','grayInput','grayTarget','grayAfter']){const c=$(id);c.getContext('2d').clearRect(0,0,c.width,c.height);}
      $('anchorStatus').textContent='旧任务未使用正色与完整灰阶训练。请使用原 LUT 重新拟合；旧结果不会自动变成新版结果。';
      $('histStatus').textContent=`旧任务独立测试集 ${data.histogram.samples} 个样本；该任务未纳入新增色卡。`;
    }
    validationJob=identifier;const wbActive=data.white_balance&&Object.values(data.white_balance.parameters).some(v=>v!==0);$('rawTask').textContent=wbActive?'此任务含实验白平衡，验证 ARW 暂不能完整复现；请使用浏览器预览。':'配方任务：'+identifier+'；写入 RAW 的'+(data.dataset?.look==='PT'?'人像（PT）':'标准（ST）')+'外观。';$('rawExport').disabled=wbActive||!rawFile||rawBusy;
    photoReady();
    if(slotPhotoMode())return;
    $('photoStatus').textContent=chartJob()?'选择照片后可预览本任务的拟合效果。ARW 的参考图使用任务基线。':'选择照片后可生成参考图和拟合效果图。';
    const saved=await(await api('/api/jobs/'+identifier)).json();
    if(!slotPhotoMode()&&identifier===validationJob&&request===diagnosticSerial){
      const previews=saved.photo_previews|| (saved.photo_preview?[saved.photo_preview]:[]);
      const sourceSha=photoSourceSha||previews.at(-1)?.result.source_sha256;
      const currentPreviews=previews.filter(p=>p.result.source_sha256===sourceSha&&p.result.preview_long_edge===3840);
      if(!currentPreviews.length&&previews.some(p=>p.result.source_sha256===sourceSha))$('photoStatus').textContent='历史预览为低分辨率，请重新导入照片';
      const matching=currentPreviews.filter(p=>Boolean(p.result.pc_compensation_enabled)===pcView()&&photoGridMatches(p.result)&&(p.result.grid_key||undefined)===selectedGrid()&&(!pcView()||p.result.pc_compensation_sha256===data.pc_sha256)&&(!selectedGrid()||p.result.grid_sha256===data.grid_sha256));
      if(matching.length)showPhoto(matching.at(-1));
      else if(currentPreviews.length&&!photoBusy){
        try{
          const r=await(await api('/api/preview-reuse',{job:identifier,preview:currentPreviews.at(-1).id,pc:pcView(),grid:selectedGrid(),grid_effect:photoGridEffect()})).json();
          if(slotPhotoMode()||request!==diagnosticSerial||photoBusy)return;
          photoBusy=true;photoReady();photoId=r.id;pollPhoto();
        }catch(e){
          if(slotPhotoMode()||request!==diagnosticSerial)return;
          if(photoFile)$('photoRender').click();else $('photoStatus').textContent=e.message;
        }
      }
    }
  }catch(e){if(identifier!==jobId)return;$('histStatus').textContent='诊断生成失败：'+e.message;}
  finally{if(request===diagnosticSerial)$('resultMode').disabled=false;}
}

function renderCompression(r,key,identifier){
        const table=document.createElement('table'),head=table.createTHead().insertRow();
        for(const text of ['样本','原组合→LUT RMSE','单网格→LUT RMSE','压缩损失 RMSE']){const th=document.createElement('th');th.textContent=text;head.append(th);}
        const labels={gray_training:'灰阶（训练）',primaries_training:'正色（训练）',colorchecker24_training:'24色（训练）',validation:'验证集',test:'独立测试',unseen_synthetic:'独立合成探针'};
        for(const [name,m]of Object.entries(r.metrics)){const row=table.insertRow();for(const text of [labels[name]||name,m.combined_vs_lut?.groups.all.metrics.rmse.toFixed(3)??'—',m.grid_vs_lut?.groups.all.metrics.rmse.toFixed(3)??'—',m.grid_vs_combined.groups.all.metrics.rmse.toFixed(3)])row.insertCell().textContent=text;}
        $('distillMetrics').replaceChildren(table);
        renderOutputContinuity($('distillMetrics'),r.fitting?.output_continuity?.final_grid);
        const grayPolish=r.fitting?.post_gray_refinement;
        if(grayPolish?.enabled){
          const note=document.createElement('p');note.className='hint';
          note.textContent='已进行压缩后灰阶微调：'+grayPolish.accepted_moves+' 次整数更新。以下列出微调前后RMSE；预览和BIN均采用最终网格。';
          const comparison=document.createElement('table');comparison.innerHTML='<tr><th>分组</th><th>微调前RMSE</th><th>微调后RMSE</th></tr>';
          for(const [name,m]of Object.entries(r.metrics)){if(!m.before_gray_refinement_vs_lut)continue;const row=comparison.insertRow();for(const text of [labels[name]||name,m.before_gray_refinement_vs_lut.groups.all.metrics.rmse.toFixed(3),m.grid_vs_lut.groups.all.metrics.rmse.toFixed(3)])row.insertCell().textContent=text;}
          $('distillMetrics').append(note,comparison);
        }
        strip('distillTeacherGray',r.samples.gray_combined);strip('distillStudentGray',r.samples.gray_grid);$('distillGray').hidden=false;
        $('distillStatus').textContent=`已压缩为 405×3 个7位系数（1215 字节），触及幅度边界 ${(r.fitting.limit_fraction*100).toFixed(2)}%。所有 RMSE 均为实际 8 位码值。本次网格模型：${gridResponseName(r.identity.response)}；尚非 R5 实机验收。${r.white_balance?.enabled?' 白平衡仍在网格前单独运算，未压入网格；BIN 不含白平衡。':''}`;
        $('distillDownload').href='/api/jobs/'+identifier+'/grid-distillation-download?key='+key;$('distillDownload').hidden=false;$('gridFirmwareDownload').href='/api/jobs/'+identifier+'/grid-firmware-download?key='+key;$('gridFirmwareDownload').hidden=false;$('addCompressed').hidden=false;

}

function trainingProgressText(p){
  if(!p)return '';
  let text=` · ${p.stage} · 求解轮 ${p.round}/${p.total_rounds}`;
  if(p.gradient_workers)text+=` · CPU ${p.gradient_workers}线程`;
  if(p.gpu_backend)text+=` · ${p.gpu_backend}`;
  if(p.iteration!=null && p.stage!=='压缩网格求解')text+=` · 迭代 ${p.iteration}（评估 ${p.evaluations}/${p.max_evaluations} 上限）`;
  if(p.candidate)text+=` · 候选 ${p.candidate}`;
  if(p.sweep!=null)text+=` · 微调 ${p.sweep}/${p.total_sweeps} 轮`;
  if(p.point!=null)text+=` · ${p.family||'网格'} 点位 ${p.point}/${p.total_points}`;
  return text;
}

let trainingTrace;

function clearTrainingTrace(){
  trainingTrace=undefined;
  $('trainingTrace').hidden=true;
  $('trainingLossStage').replaceChildren(new Option('跟随当前阶段',''));
}

function drawTrainingLoss(){
  const stages=trainingTrace?.stages;
  if(!stages?.size)return;
  const samples=stages.get($('trainingLossStage').value)||[...stages.values()].at(-1);
  const latest=samples.at(-1);
  // 用阶段起始量级统一缩放，刷新时曲线和读数沿用同一倍率。
  const reference=samples.find(sample=>sample.current>0)?.current;
  const power=reference>0&&reference<.01?Math.min(300,-Math.floor(Math.log10(reference))):0;
  const format=value=>(value*10**power).toPrecision(5);
  const unit=power?' · 显示倍率 ×10^'+power:'';
  const axis=['MPS FISTA','MPS Adam'].includes(latest.solver)?'迭代':'评估';
  $('trainingLossValues').textContent=latest.stage+' · '+latest.solver+
    ' · '+axis+' '+latest.evaluations+' · 当前 Loss '+format(latest.current)+' · 最佳 Loss '+format(latest.best)+unit;
  const canvas=$('trainingLossChart');
  if(!canvas.clientWidth)return;
  canvas.width=canvas.clientWidth;
  canvas.height=canvas.clientHeight;
  const ctx=canvas.getContext('2d');
  const {width,height}=canvas;
  const left=96,right=width-24,top=22,bottom=height-42;
  const values=samples.flatMap(sample=>[sample.current,sample.best]);
  const low=Math.min(...values), high=Math.max(...values);
  const first=samples[0].evaluations, last=latest.evaluations;
  const x=value=>left+(right-left)*(value-first)/Math.max(last-first,1);
  const y=value=>high===low?(top+bottom)/2:bottom-(bottom-top)*(value-low)/(high-low);
  ctx.clearRect(0,0,width,height);
  ctx.font='15px system-ui';
  ctx.fillStyle='#64705f';
  ctx.strokeStyle='#dce4d8';
  ctx.lineWidth=1;
  ctx.beginPath();
  ctx.moveTo(left,top);ctx.lineTo(left,bottom);ctx.lineTo(right,bottom);ctx.stroke();
  ctx.textAlign='right';
  if(power)ctx.fillText('×10^'+power,left-8,14);
  ctx.fillText(format(high),left-8,top+5);
  if(low!==high)ctx.fillText(format(low),left-8,bottom);
  ctx.textAlign='left';
  ctx.fillText(String(first),left,bottom+20);
  ctx.textAlign='right';
  if(last!==first)ctx.fillText(String(last),right,bottom+20);
  ctx.textAlign='center';
  ctx.fillText(axis+'次数',(left+right)/2,bottom+30);
  for(const [key,color,dash] of [['best','#30583f',[]],['current','#b36f39',[5,4]]]){
    ctx.strokeStyle=ctx.fillStyle=color;
    ctx.lineWidth=2.5;
    ctx.setLineDash(dash);
    ctx.beginPath();
    samples.forEach((sample,index)=>ctx[index?'lineTo':'moveTo'](x(sample.evaluations),y(sample[key])));
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x(latest.evaluations),y(latest[key]),3,0,Math.PI*2);ctx.fill();
  }
  ctx.setLineDash([]);
  ctx.textAlign='right';
  ctx.fillStyle='#b36f39';ctx.fillText('当前',right-52,16);
  ctx.fillStyle='#30583f';ctx.fillText('最佳',right,16);
}

async function refreshTrainingTrace(id){
  if(trainingTrace?.id!==id){
    clearTrainingTrace();
    trainingTrace={id,offsets:{native:0,grid:0},stages:new Map(),rounds:[],pending:false};
    $('trainingLoss').hidden=true;
    $('trainingGridRounds').hidden=true;
    $('trainingGridRoundRows').replaceChildren();
  }
  const trace=trainingTrace;
  if(trace.pending){trace.refresh=true;return;}
  trace.pending=true;
  try{
    const response=await api('/api/jobs/'+id+'/training-trace?'+new URLSearchParams(trace.offsets));
    const data=await response.json();
    if(trainingTrace!==trace)return;
    $('trainingTraceStatus').hidden=true;
    const events=[];
    for(const [kind, stream] of Object.entries(data)){
      trace.offsets[kind]=stream.offset;
      const candidate=kind.startsWith('candidate_');
      for(const event of stream.events){
        events.push(candidate?{...event,stage:'2000 步候选 · '+event.stage}:event);
      }
    }
    for(const event of events){
      if(event.kind!=='loss')continue;
      const key=[event.run,event.round,event.solver].join('/');
      if(!trace.stages.has(key)){
        trace.stages.set(key,[]);
        $('trainingLossStage').add(new Option(event.round+' · '+event.stage+' · '+event.solver,key));
      }
      trace.stages.get(key).push(event);
    }
    for(const event of data.grid.events){
      if(event.kind!=='integer')continue;
      if(trace.gridRun!==event.run){trace.gridRun=event.run;trace.rounds=[];}
      trace.rounds.push(event);
    }
    $('trainingLoss').hidden=!trace.stages.size;
    $('trainingGridRounds').hidden=!trace.rounds.length;
    $('trainingTrace').hidden=!trace.stages.size&&!trace.rounds.length;
    if(events.some(event=>event.kind==='loss'))drawTrainingLoss();
    if(data.grid.events.length){
      $('trainingGridRoundRows').replaceChildren(...trace.rounds.map(event=>{
        const row=document.createElement('tr');
        const {metrics}=event;
        const blocked=count=>count?'（拦下 '+count+'）':'';
        for(const value of [event.sweep,event.proposed_moves,event.applied_moves,
          metrics.rgb_rmse.toFixed(5),metrics.delta_e00_mean.toFixed(5),
          (event.gray_passed?'通过':'失败')+' · '+metrics.gray_rmse.toFixed(5)+blocked(event.gray_rejections),
          (event.saturation_passed?'通过':'失败')+blocked(event.saturation_rejections),event.rejected_candidates]){
          row.insertCell().textContent=value;
        }
        return row;
      }));
    }
  }catch(error){
    if(trainingTrace!==trace)return;
    $('trainingTrace').hidden=false;
    $('trainingTraceStatus').hidden=false;
    $('trainingTraceStatus').textContent='暂时无法读取训练日志 · '+error.message;
  }finally{
    trace.pending=false;
    if(trace.refresh&&trainingTrace===trace){trace.refresh=false;refreshTrainingTrace(id);}
  }
}

async function pollCompression(identifier){
  clearTimeout(compressionTimer);
  try{
    const state=await(await api('/api/jobs/'+identifier+'/grid-training')).json();
    if(identifier!==jobId){compressionBusy=false;return;}
    refreshTrainingTrace(identifier);
    $('compressionTrainingStatus').textContent=(state.phase||'准备压缩训练')+trainingProgressText(state.training_progress);
    if(state.status==='done'||state.status==='error'){
      compressionBusy=false;$('fit').disabled=busy||chartUploading;
      if(state.status==='error')throw Error(state.error);
      gridKeys.set(identifier,state.key);$('resultMode').querySelector('option[value=compressed]').disabled=false;
      $('resultMode').value='compressed';await loadDiagnostics(identifier);return;
    }
    compressionTimer=setTimeout(()=>pollCompression(identifier),1500);
  }catch(e){compressionBusy=false;$('fit').disabled=busy||chartUploading;$('compressionTrainingStatus').textContent='压缩训练：'+e.message;}
}
async function trainAndGenerate(){
  if(busy||compressionBusy||chartUploading||libraryImportBusy)return;
  if(projectMode()&&(workspaceBatchSubmitting||workspaceBatchActive)){
    toast('请等待批量训练结束');
    return;
  }
  try{
    if(submittedTraining){
      jobId=submittedTraining.id;setBusy(true);clearTimeout(timer);poll();
      toast('正在重新连接已提交的任务');return;
    }
    if(!targetReady()){
      if(!jobId||!pcJobs.has(jobId))throw Error('请先导入目标，或选择已完成的 PC 补偿任务');
      if(gridKeys.has(jobId)){await loadDiagnostics(jobId);toast('已复用当前滤镜，无需重复训练');return;}
      const response=boot.grid_response;
      compressionBusy=true;$('fit').disabled=true;
      try{
        await api('/api/grid-training',{job:jobId,response,post_gray_refinement:false});
      }catch(error){compressionBusy=false;$('fit').disabled=busy;throw error;}
      pollCompression(jobId);return;
    }
    remember();
    const body=fitOptions(true);
    if(projectMode())body.project_id=workspace.id;
    // 压缩流程固定使用完整 PC 补偿，与后端的规范化保持一致。
    body.pc_compensation=true;
    body.pc_options={curve_mode:'tone-tint',grid_enabled:true,response:body.pc_options.response};
    const signature=JSON.stringify(body);
    if(completedTraining?.signature===signature){
      jobId=completedTraining.id;setBusy(true);clearTimeout(timer);poll();
      toast('已复用相同输入的滤镜，无需重复训练');return;
    }
    setBusy(true);$('cancel').hidden=true;
    try{
      const response=await(await api('/api/fit',body)).json();
      jobId=response.id;submittedTraining={id:jobId,signature};
      if(projectMode())registerWorkspaceJob(jobId,body.number);
      if(response.reused)toast('已载入同一目标和设置的训练结果');
    }catch(error){setBusy(false);throw error;}
    $('cancel').hidden=false;$('jobDownload').hidden=true;
    $('jobStatus').textContent='任务已提交：拟合 → PC 补偿 → 网格压缩';
    clearTimeout(timer);poll();
  }catch(error){toast(error.message);}
}
async function poll(){
  const identifier=jobId;
  if(projectMode()&&workspaceCandidate?.id!==identifier){workspaceCandidate=undefined;workspaceCandidateSerial++;renderWorkspaceInspector();}
  try{const job=await(await api('/api/jobs/'+identifier)).json();if(identifier!==jobId)return;if(projectMode())renderWorkspaceJob(job);refreshTrainingTrace(identifier);$('jobStatus').textContent=job.phase+trainingProgressText(job.training_progress)+` · ${Math.round(((job.finished||Date.now()/1000)-job.started)/60)} 分钟`;$('log').textContent=job.log||'正在校验输入资料…';
    if(job.status==='done'||job.status==='error'){setBusy(false);$('jobDownload').hidden=false;$('jobDownload').href='/api/jobs/'+jobId+'/download';$('jobDownload').download='r5-fit.zip';if(job.status==='done'){if(job.result.pc_compensation?.enabled)pcJobs.add(job.id);if(job.result.grid_key){gridKeys.set(job.id,job.result.grid_key);if(submittedTraining?.id===job.id)completedTraining=submittedTraining;}showResult(job.result);}else{$('jobStatus').textContent=job.error;toast(job.error);}if(submittedTraining?.id===job.id)submittedTraining=undefined;if(job.status==='done')loadDiagnostics(jobId);return;}
    timer=setTimeout(poll,2000);
  }catch(e){if(identifier!==jobId)return;setBusy(false);$('jobStatus').textContent='连接中断：'+e.message+'。重载页面可重新连接运行中任务。';}
}
async function loadLut(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.cube')||file.size>64*1024*1024){toast('请选择 64 MiB 内的 .cube 文件');return;}lutText=await file.text();$('lutLabel').textContent=file.name;$('jobStatus').textContent=`已导入 ${(file.size/1024).toFixed(1)} KiB；请选择正确的输入色域。`;}
function fitOptions(compression){
  const endpoint = $('endpoint').value === '' ? null : Number($('endpoint').value);
  if(endpoint !== null && (!Number.isInteger(endpoint) || endpoint < 0 || endpoint > 131071)){
    throw Error('伽马最后一点必须为 0–131071 的整数，或留空');
  }
  const group_weights = {
    random: +$('weightRandom').value,
    primaries: +$('weightPrimaries').value,
    gray: +$('weightGray').value,
    colorchecker24: +$('weightCC24').value,
    sector16: +$('weightSector16').value
  };
  if(Object.values(group_weights).some(value => !Number.isFinite(value) || value < .05 || value > 64)){
    throw Error('训练权重需在 0.05–64 之间');
  }
  const adamLearningRate = Number($('adamLearningRate').value);
  if(!Number.isFinite(adamLearningRate) || adamLearningRate < .0001 || adamLearningRate > .1){
    throw Error('Adam 学习率需在 0.0001–0.1 之间');
  }
  const adamSteps = Number($('adamSteps').value);
  if(!Number.isInteger(adamSteps) || adamSteps < 1 || adamSteps > 2000){
    throw Error('Adam 步数需为 1–2000 的整数');
  }
  const search_options = {
    adam_learning_rate: adamLearningRate,
    adam_steps: adamSteps,
    output_continuity: +$('outputContinuity').value,
    parameter_smoothing: +$('parameterSmoothing').value,
    starts: +$('searchStarts').value,
    adaptive_rounds: +$('adaptiveRounds').value,
    gamma_color_rounds: +$('gammaColorRounds').value,
    perceptual_weight: +$('perceptualWeight').value,
    quantization_sweeps: +$('quantizationSweeps').value
  };
  const curveMode = $('pcCurveMode').value;
  return {
    speed_priority: fastTraining(),
    target_kind: $('targetKind').value,
    dataset_id: $('chartVersion').value,
    target_id: chartTargetId,
    white_balance: $('wbTraining').checked,
    compression_training: compression,
    post_gray_refinement: false,
    pc_options: {
      curve_mode: curveMode,
      grid_enabled: curveMode === 'qaq-grid' || $('pcGridEnabled').checked,
      response: boot.grid_response
    },
    search_options,
    group_weights,
    pc_compensation: $('pcTraining').checked,
    lut: lutText,
    gamut: $('gamut').value,
    evaluations: +$('evaluations').value,
    number: selected,
    short_name: projectMode() ? trainingName('trainingShortName',draft.short_name) : draft.short_name,
    full_name: projectMode() ? trainingName('trainingFullName',draft.full_name) : draft.full_name,
    gamma_endpoint128: endpoint
  };
}
async function initTrainedFilters(){
  const select=$('trainedFilter'),status=$('trainedFilterStatus');
  select.replaceChildren(new Option('选择已完成的滤镜…',''));
  if(!boot.latest_batch){status.textContent='暂无已保存的批量训练。';return;}
  try{
    const batch=await(await api('/api/batches/'+boot.latest_batch)).json();
    const completed=batch.jobs.filter(job=>job.status==='done');
    for(const job of completed)select.append(new Option(job.name,job.id));
    select.disabled=!completed.length;
    select.value=new URLSearchParams(location.search).get('job')||'';
    status.textContent=`最近一批训练 · ${completed.length} / ${batch.jobs.length} 个滤镜已完成；选择后加载对应色块、指标与参数。`;
    select.onchange=()=>{
      if(!select.value)return;
      if(busy){select.value=jobId||'';toast('当前任务运行中，请完成后查看其他结果');return;}
      if(projectMode()){jobId=select.value;clearTimeout(timer);poll();return;}
      const url=new URL(location.href);url.searchParams.set('job',select.value);location.assign(url.href);
    };
  }catch(e){status.textContent='训练列表加载失败：'+e.message;}
}

async function init(){
  try{boot=await(await api('/api/bootstrap')).json();
    $('computeBackend').textContent=boot.compute_backend?.available?`Apple Metal/MPS：浮点拟合、Gamma／色彩交替、网格优化与批量色差；原生整数验收：${boot.compute_backend.native_integer_backend==='Metal'?'Metal＋CPU校验':'CPU参考实现'}。`:'CPU 8线程：当前服务未启用 Metal 训练；已运行任务保持原计算方式。';
    renderSlots();
    for(const preset of boot.stock_grids){const o=document.createElement('option');o.value=preset.id;o.textContent=preset.label;o.title=JSON.stringify(preset.provenance);$('stockGrid').append(o);}
    names.forEach((name,i)=>{const o=document.createElement('option');o.value=i;o.textContent=chineseNames[i]+'（'+name+'）';$('baselineLook').append(o);});
    $('baselineLook').value='1';selectLook(1);renderCollection();
    initChartVersions();
    initFolderTraining();
    $('stockGrid').onchange=()=>{const preset=boot.stock_grids.find(p=>p.id===$('stockGrid').value);draftSource=preset?{kind:'stock',id:preset.id}:undefined;if(preset)draft.grid_5x9x9=clone(preset.grid_5x9x9);syncRaw();};
    $('baselineLook').onchange=()=>{baselineNote();renderGamma();};
    for(const id of ['shortName','lookName'])$(id).oninput=()=>{readNames();syncRaw();};
    $('reset').onclick=()=>{remember();const names={short_name:draft.short_name,full_name:draft.full_name};draftSource=undefined;draft={...clone(boot.presets[+$('baselineLook').value]),...names,number:selected};showNames();drafts.set(selected,clone(draft));renderEditors();};
    $('matrixEndpoint').onchange=renderMatrix;
    $('comparisonMode').onchange=renderComparison;
    $('grayRefinementView').onchange=()=>{if(validationJob)loadDiagnostics(validationJob);};
    $('resultMode').onchange=()=>{if(validationJob)loadDiagnostics(validationJob);};
    $('photoSourceMode').onchange=()=>{
      $('photoResults').hidden=true;photoShownSlot=undefined;photoReady();
      if(!slotPhotoMode()){
        if(validationJob)loadDiagnostics(validationJob);
        else $('photoStatus').textContent='请先载入已完成的训练任务。';
      }
    };
    $('photoGridEffect').onchange=()=>{
      $('photoResults').hidden=true;
      if(slotPhotoMode())photoReady();
      else if(validationJob)loadDiagnostics(validationJob);
    };
    $('photoInput').onchange=e=>{const file=e.target.files[0];if(!file)return;if(!/\.(arw|jpe?g|png|tiff?)$/i.test(file.name)||!file.size||file.size>512*1024*1024){toast('请选择 512 MiB 内的 ARW、JPG、PNG 或 TIFF');e.target.value='';return;}photoFile=file;photoSourceSha=undefined;clearActual();$('photoResults').hidden=true;$('photoName').textContent=file.name+' · '+(file.size/1024/1024).toFixed(1)+' MiB';photoReady();};
    $('photoRender').onclick=async()=>{
      const slot=photoSlot();
      if(photoBusy||!photoFile||!(slotPhotoMode()?slot:validationJob))return;
      const serial=++photoUploadSerial;
      photoBusy=true;photoReady();photoSlotRequest=slot;$('photoResults').hidden=true;$('photoStatus').textContent='正在上传照片，随后进行本地解码和渲染…';
      const source=slot?{project:slot.project,slot:slot.slot}:{job:validationJob,pc:pcView()?'1':'0',grid:selectedGrid()||''};
      const query=new URLSearchParams({...source,
        grid_effect:photoGridEffect()?'1':'0',input:/\.arw$/i.test(photoFile.name)?'raw':'image'});
      try{
        const response=await fetch('/api/preview?'+query,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:photoFile});
        const value=await response.json();
        if(serial!==photoUploadSerial)return;
        if(!response.ok)throw Error(value.error);
        photoId=value.id;clearTimeout(photoTimer);pollPhoto();
      }catch(e){if(serial===photoUploadSerial){photoBusy=false;photoReady();$('photoStatus').textContent='预览失败：'+e.message;}}
    };
    $('photoZoom').onchange=()=>{for(const id of ['photoLut','photoModel','photoActual'])$(id).style.width=(+$('photoZoom').value*100)+'%';};
    $('photoActualInput').onchange=e=>{const file=e.target.files[0];if(!file)return;if(!['image/jpeg','image/png'].includes(file.type)||file.size>65*1024*1024){toast('请选择 65 MiB 内的 JPG / PNG');return;}clearActual();actualUrl=URL.createObjectURL(file);$('photoActual').onload=()=>{$('photoActual').hidden=false;$('photoActualEmpty').hidden=true;$('photoActualClear').hidden=false;$('photoActualName').textContent=file.name+' · '+$('photoActual').naturalWidth+' × '+$('photoActual').naturalHeight+'；请确认是同一 RAW、同一配方，裁切和方向一致。';};$('photoActual').onerror=()=>{clearActual();toast('软件导出图无法解码');};$('photoActual').src=actualUrl;};
    $('photoActualClear').onclick=clearActual;
    const panes=document.querySelectorAll('.photo-scroll');let syncing=false;panes.forEach(pane=>pane.onscroll=()=>{if(syncing)return;syncing=true;for(const other of panes){if(other===pane)continue;other.scrollLeft=pane.scrollLeft;other.scrollTop=pane.scrollTop;}requestAnimationFrame(()=>syncing=false);});
    $('gammaIndex').onchange=renderGamma;
    $('gammaLast').onclick=()=>{$('gammaIndex').value=128;renderGamma();$('gammaValue').focus();};
    $('gammaValue').onchange=()=>{const i=+$('gammaIndex').value,v=+$('gammaValue').value;if($('gammaValue').value===''||!Number.isInteger(v)||v<0||v>131071){toast('Gamma 必须为 0–131071 的整数');return;}draft.gamma_native_129[i]=v;renderGamma();syncRaw();};
    $('gammaChart').onclick=e=>{const rect=e.target.getBoundingClientRect();$('gammaIndex').value=Math.max(0,Math.min(128,Math.round(((e.clientX-rect.left)/rect.width*1000-52)/932*128)));renderGamma();};
    $('gammaReset').onclick=()=>{draft.gamma_native_129=clone(boot.presets[+$('baselineLook').value].gamma_native_129);renderGamma();syncRaw();};
    document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));document.querySelectorAll('.tab-panel').forEach(panel=>panel.hidden=panel.id!==button.dataset.tab);});
    $('applyRaw').onclick=async()=>{try{const value=JSON.parse($('rawEditor').value);if(value.number!==selected)throw Error('序号必须与当前配置一致');await api('/api/validate',project([value]));draft=value;showNames();renderEditors();toast('JSON 已应用');}catch(e){toast(e.message);}};
    $('add').onclick=async()=>{try{remember();const response=await(await api('/api/validate',exportProject([draft],new Map(draftSource?[[selected,draftSource]]:[])))).json();collection=collection.filter(e=>e.number!==selected);collection.push(clone(draft));collectionSources.set(selected,clone(draftSource));renderCollection();$('editStatus').textContent=`已加入导出集 · 文件检查通过 · 单项 ${response.bytes} 字节`;}catch(e){$('editStatus').textContent=e.message;toast(e.message);}};
    $('addCompressed').onclick=async()=>{try{const key=gridKeys.get(jobId);if(!jobId||!key)throw Error('请先完成压缩训练');const value=await(await api('/api/jobs/'+jobId+'/grid-firmware-config?key='+key)).json();const entry=value.entries[0];collection=collection.filter(e=>e.number!==entry.number);collection.push(clone(entry));collectionSources.set(entry.number,clone(value.export_sources[String(entry.number)]));draftSources.set(entry.number,clone(value.export_sources[String(entry.number)]));drafts.set(entry.number,clone(entry));renderCollection();draft=undefined;selectLook(entry.number);toast('本任务原生参数与压缩网格已一起加入导出集');}catch(e){toast(e.message);}};
    $('export').onclick=async()=>{try{const response=await api('/api/export',exportProject());download(await response.blob(),'r5-native-config.zip');toast('已导出 BIN、JSON 与校验回执');}catch(e){toast(e.message);}};
    $('saveProject').onclick=()=>download(new Blob([JSON.stringify(exportProject(),null,2)],{type:'application/json'}),'native_config.json');
    $('discardSlot').onclick=discardSlotChanges;
    $('moveSlot').onclick=()=>{try{moveConfiguration(Number($('moveSlotTarget').value));}catch(error){toast(error.message);}};
    $('confirmImport').onclick=confirmLibraryImport;$('cancelImport').onclick=cancelLibraryImport;
    $('importDialog').oncancel=cancelLibraryImport;
    for(const [id,kind] of [['importBin','bin'],['importProject','json']])$(id).onchange=async e=>{try{await importConfiguration(e.target.files[0],kind);}finally{e.target.value='';}};
    $('targetKind').onchange=()=>{
      $('chartTargetFields').hidden=!imageTarget();
      $('dropzone').hidden=imageTarget();
      $('gamut').closest('label').hidden=imageTarget();
      $('batchTraining').hidden=!imageTarget();
      if(projectMode()){
        const file=imageTarget()&&chartTargetId?$('chartTarget').files[0]:null;
        suggestTrainingNames(file?file.name.replace(/\.[^.]+$/,''):'');
      }
    };
    $('targetKind').onchange();
    $('chartTarget').onchange=async e=>{
      const file=e.target.files[0];chartTargetId=undefined;
      if(projectMode())suggestTrainingNames('');
      if(!file)return;
      if(!/\.(tif|tiff|jpg|jpeg)$/i.test(file.name)||file.size>1024*1024*1024){$('chartTargetStatus').textContent='请选择 1 GiB 内的 TIFF 或 JPG';e.target.value='';return;}
      chartUploading=true;$('chartVersion').disabled=true;$('targetKind').disabled=true;$('chartTarget').disabled=true;$('fit').disabled=true;
      $('chartTargetStatus').textContent='上传并检查色卡布局、位深及色域…';
      try{
        const response=await fetch('/api/chart-target?dataset_id='+encodeURIComponent($('chartVersion').value),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:file});
        const value=await response.json();if(!response.ok)throw Error(value.error);
        chartTargetId=value.id;
        if(projectMode()){
          suggestTrainingNames(file.name.replace(/\.[^.]+$/,''));
        }else if(slotState(selected).state==='empty'){
          const name=file.name.replace(/\.[^.]+$/,'');
          $('shortName').value=name;$('lookName').value=name;readNames();syncRaw();
        }$('chartTargetStatus').textContent=file.name+' · '+value.audit.bits_per_channel+' 位 · '+value.audit.samples+' 个目标色块已就绪';
      }catch(error){$('chartTargetStatus').textContent='导入失败：'+error.message;}
      finally{chartUploading=false;$('chartVersion').disabled=busy;$('targetKind').disabled=busy;$('chartTarget').disabled=busy;$('fit').disabled=busy||compressionBusy;}
    };
    $('lut').onchange=e=>loadLut(e.target.files[0]);
    $('dropzone').ondragover=e=>{e.preventDefault();$('dropzone').classList.add('drag');};$('dropzone').ondragleave=()=>$('dropzone').classList.remove('drag');$('dropzone').ondrop=e=>{e.preventDefault();$('dropzone').classList.remove('drag');loadLut(e.dataTransfer.files[0]);};
    $('speedPriority').onchange=trainingModeHint;
    $('resetWeights').onclick=()=>{
      for(const input of $('trainingAdvanced').querySelectorAll('input'))input.value=input.defaultValue;
      $('parameterSmoothing').oninput();
      if(projectMode())queueWorkspaceSave();
    };
    $('parameterSmoothing').oninput=()=>{$('parameterSmoothingValue').textContent=$('parameterSmoothing').value;};
    $('fit').onclick=trainAndGenerate;
    $('trainingLossStage').onchange=drawTrainingLoss;
    window.addEventListener('resize',drawTrainingLoss);
    $('cancel').onclick=async()=>{try{await api('/api/cancel',{id:jobId});$('jobStatus').textContent='正在取消…';}catch(e){toast(e.message);}};
    $('rawInput').onchange=e=>{const f=e.target.files[0];if(!f)return;if(!/\.arw$/i.test(f.name)||f.size>512*1024*1024){toast('请选择 512 MiB 内的 R5 ARW');return;}rawFile=f;$('rawName').textContent=f.name+' · '+(f.size/1024/1024).toFixed(1)+' MiB';$('rawExport').disabled=!validationJob||rawBusy||Boolean(diagnosticData?.white_balance&&Object.values(diagnosticData.white_balance.parameters).some(v=>v!==0));};
    $('rawExport').onclick=async()=>{if(!rawFile||!validationJob||rawBusy)return;const identifier=validationJob;rawBusy=true;$('rawExport').disabled=true;$('rawStatus').textContent='正在本地上传、校验并生成 ARW 副本，请稍候…';try{const response=await fetch('/api/raw-export?job='+identifier,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:rawFile});if(!response.ok){const error=await response.json();throw Error(error.error);}download(await response.blob(),rawFile.name.replace(/\.arw$/i,'')+'-Edit验证.zip');$('rawStatus').textContent='验证包已下载。打开包内 fitted-PT.ARW（新PT任务）或 fitted-ST.ARW（历史ST任务），在 Edit 显式选择对应外观。内嵌预览未重绘；请以实际渲染为准。';}catch(e){$('rawStatus').textContent='生成失败：'+e.message;toast(e.message);}finally{rawBusy=false;$('rawExport').disabled=!rawFile||!validationJob||Boolean(diagnosticData?.white_balance&&Object.values(diagnosticData.white_balance.parameters).some(v=>v!==0));}};
    for(const job of boot.history){if(job.pc_available)pcJobs.add(job.id);const option=document.createElement('option');option.value=job.id;option.textContent=new Date(job.started*1000).toLocaleString()+' · '+(job.target_kind==='chart-image'?'色卡目标 · ':'')+job.phase;$('history').append(option);}
    $('history').onchange=()=>{if(!$('history').value)return;if(busy){toast('当前任务运行中，请完成后查看历史');return;}jobId=$('history').value;$('trainedFilter').value=jobId;clearTimeout(timer);poll();};
    $('history').addEventListener('focus',async()=>{try{const value=await(await api('/api/bootstrap')).json();for(const job of value.history){if([...$('history').options].some(o=>o.value===job.id))continue;const option=document.createElement('option');option.value=job.id;option.textContent=new Date(job.started*1000).toLocaleString()+' · '+(job.target_kind==='chart-image'?'色卡目标 · ':'')+job.phase;$('history').append(option);}}catch{}});
    document.querySelector('.brand').onclick=e=>{e.preventDefault();document.querySelector('header').scrollIntoView({behavior:'smooth'});};
    await initTrainedFilters();
    if(typeof initWorkspace==='function')await initWorkspace();
    const requestedJob=new URLSearchParams(location.search).get('job');
    const active=projectMode()?boot.jobs.find(id=>workspace.jobs[id]&&!workspaceBatchActive):boot.jobs[0];
    if(active){jobId=active;setBusy(true);poll();}
    else {
      const completed=boot.history.find(j=>j.status==='done');
      const restore=requestedJob&&boot.history.some(j=>j.id===requestedJob)?requestedJob:projectMode()?undefined:completed?.id;
      if(restore){jobId=restore;$('history').value=restore;await poll();}
    }
  }catch(e){$('jobStatus').textContent=e.message;toast('初始化失败：'+e.message);}
}
init();

function folderTargets(files){
  const selected=[...files].filter(f=>/\.(jpe?g|tiff?)$/i.test(f.name)).sort((a,b)=>a.name.localeCompare(b.name,'en',{numeric:true}) || (a.webkitRelativePath||a.name).localeCompare(b.webkitRelativePath||b.name));
  if(!selected.length||selected.length>boot.slot_limit)throw Error('需要 1–24 张 JPG／TIFF，当前 '+selected.length+' 张；请分文件夹处理。');
  const seen=new Set();
  return selected.map((file,i)=>{
    const name=file.name.replace(/\.[^.]+$/,'');
    if(!name.trim()||new TextEncoder().encode(name).length>23)throw Error(file.name+'：简称超过 23 个 UTF-8 字节或为空，请先重命名。');
    if(seen.has(name.toLowerCase()))throw Error('名称重复：'+name+'；请先重命名。');
    if(file.size>1024*1024*1024)throw Error(file.name+' 超过 1 GiB');
    seen.add(name.toLowerCase());return {file,name,number:i+1};
  });
}
let openWorkspaceBatch=()=>{};

function initFolderTraining(){
  let targets=[], active=false, batch, pollSerial=0;

  function clearBatchActions(){
    for(const id of ['batchDownloads','batchSaveProject','batchRetry'])$(id).hidden=true;
  }

  async function pollBatch(id, serial, legacy=false){
    try{
      const state=await(await api('/api/batches/'+id)).json();
      if(serial!==pollSerial)return;
      if(legacy){
        if(!state.jobs.length||!state.jobs.every(job=>workspace.jobs[job.id]===job.number))return;
        workspaceBatchId=id;
      }
      batch=state;
      active=['queued','running'].includes(state.status);
      if(projectMode())workspaceBatchActive=active;
      $('batchStatus').textContent=state.jobs.map(job=>
        '第 '+job.number+' 槽 · '+job.name+' · '+job.phase+trainingProgressText(job.training_progress)).join('\n')+
        (state.error?'\n'+state.error:'');
      $('batchStatus').style.whiteSpace='pre-line';
      $('batchSaveProject').hidden=active||!projectMode()||!state.jobs.some(job=>job.status==='done'&&job.grid_key);
      $('batchRetry').hidden=active||state.status!=='error'||!state.jobs.some(job=>job.status==='error');
      $('batchDownloads').hidden=state.status!=='done';
      if(state.status==='done'){
        for(const [element,file] of [['batchBin','R5NATIVE.BIN'],['batchConfig','native_config.json'],['batchAudit','export_audit.json']]){
          $(element).href='/api/batches/'+id+'/'+file;
        }
      }
      if(active)setTimeout(()=>{if(serial===pollSerial)pollBatch(id,serial);},2000);
    }catch(error){
      if(serial!==pollSerial)return;
      active=false;
      if(projectMode())workspaceBatchActive=false;
      $('batchStatus').textContent='无法读取批量任务 · '+error.message+'。可刷新重连。';
    }finally{
      if(serial===pollSerial){
        $('targetFolder').disabled=active;
        $('batchStart').disabled=active||!targets.length;
      }
    }
  }

  openWorkspaceBatch=()=>{
    const serial=++pollSerial;
    batch=undefined;
    workspaceBatchId=workspace.settings.batchId;
    workspaceBatchActive=active=false;
    clearBatchActions();
    $('targetFolder').disabled=false;
    $('batchStatus').textContent='选择目标文件夹后可分配槽位。';
    if(workspaceBatchId)return pollBatch(workspaceBatchId,serial);
    if(boot.latest_batch&&Object.keys(workspace.jobs).length)return pollBatch(boot.latest_batch,serial,true);
  };

  $('targetFolder').onchange=event=>{
    targets=[];
    $('batchStart').disabled=true;
    $('folderFiles').replaceChildren();
    if(!event.target.files.length)return;
    try{
      targets=folderTargets(event.target.files);
      const slots=Array.from({length:boot.slot_limit},(_,index)=>index+1);
      const occupied=number=>projectMode()&&slotState(number).state!=='empty';
      const preferred=slots.filter(number=>!occupied(number)).concat(slots.filter(occupied));
      targets.forEach((target,index)=>{
        const label=document.createElement('label'), select=document.createElement('select');
        label.textContent=target.file.webkitRelativePath||target.file.name;
        select.replaceChildren(...slots.map(number=>new Option('第 '+number+' 槽'+(occupied(number)?' · 已占用':''),String(number))));
        target.number=preferred[index];select.value=target.number;
        select.onchange=()=>{target.number=Number(select.value);};
        label.append(select);
        $('folderFiles').append(label);
      });
      $('batchStart').disabled=active;
    }catch(error){$('folderFiles').textContent=error.message;}
  };

  async function startBatch(request){
    if(active||busy||compressionBusy||libraryImportBusy||chartUploading)return;
    if(projectMode())workspaceBatchSubmitting=true;
    active=true;
    $('batchStart').disabled=$('targetFolder').disabled=true;
    for(const select of $('folderFiles').querySelectorAll('select'))select.disabled=true;
    $('batchRetry').disabled=$('batchSaveProject').disabled=true;
    try{
      const state=await request();
      clearBatchActions();
      if(projectMode()){
        workspaceBatchId=state.id;
        for(const job of state.jobs)registerWorkspaceJob(job.id,job.number);
      }
      await pollBatch(state.id,++pollSerial);
    }catch(error){
      active=false;
      $('batchStatus').textContent='批量未启动 · '+error.message;
      $('batchStart').disabled=!targets.length;
      $('targetFolder').disabled=false;
    }finally{
      if(projectMode())workspaceBatchSubmitting=false;
      for(const select of $('folderFiles').querySelectorAll('select'))select.disabled=false;
      $('batchRetry').disabled=$('batchSaveProject').disabled=false;
    }
  }

  $('batchStart').onclick=()=>startBatch(async()=>{
    if(!targets.length)throw Error('请先选择目标文件夹');
    if(new Set(targets.map(target=>target.number)).size!==targets.length)throw Error('每张目标图须对应不同槽位');
    const options=fitOptions(true), files=[];
    for(const target of targets){
      $('batchStatus').textContent='上传并检查第 '+target.number+' 槽 · '+target.name;
      const response=await fetch('/api/chart-target?dataset_id='+encodeURIComponent($('chartVersion').value),
        {method:'POST',headers:{'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:target.file});
      const value=await response.json();
      if(!response.ok)throw Error(target.file.name+' · '+value.error);
      files.push({filename:target.file.name,target_id:value.id,number:target.number});
    }
    return (await api('/api/batches',{files,options,concurrency:2})).json();
  });
  $('batchRetry').onclick=()=>startBatch(async()=>(await api('/api/batches/retry',{id:batch.id})).json());
  $('batchSaveProject').onclick=()=>workspaceCommand(async()=>{
    if(batch?.id!==workspaceBatchId)return;
    const completed=batch.jobs.filter(job=>job.status==='done'&&job.grid_key);
    if(completed.length)await saveBatchResults(completed);
  });
  if(typeof initWorkspace!=='function'&&boot.latest_batch)pollBatch(boot.latest_batch,++pollSerial);
}

function initChartVersions(){
  const select=$('chartVersion');
  for(const version of boot.chart_versions.filter(v=>v.id===boot.default_chart.schema)){const option=document.createElement('option');option.value=version.id;option.textContent=version.label;select.append(option);}
  select.value=boot.default_chart.schema;
  const update=()=>{
    const query='?dataset_id='+encodeURIComponent(select.value);
    $('chartRafDownload').href='/api/chart-original'+query;
    for(const [id,format]of [['chartArwDownload','arw'],['chartDngDownload','dng']]){
      $(id).hidden=!select.value.startsWith('v4.5-');$(id).href='/api/chart-file'+query+'&format='+format;
    }
    $('chartVersionStatus').textContent=select.value.startsWith('v4.5-')?'v4.5 色卡 · 5300K。请保留拍摄白平衡，并使用本版色卡导出目标图。':'v4历史色卡：unity-WB；仅用于旧版目标和旧任务。';
  };
  select.onchange=()=>{
    chartTargetId=undefined;$('chartTarget').value='';$('chartTargetStatus').textContent='色卡版本已切换，请上传该版本的导出图';
    $('targetFolder').value='';$('targetFolder').dispatchEvent(new Event('change'));update();
  };
  update();
}
