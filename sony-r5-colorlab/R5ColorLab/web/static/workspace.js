'use strict';

let workspace, workspaceTimer, workspaceSave, workspaceDirty=false, workspaceActionBusy=false;
let workspaceLoading=false, workspaceCandidate, workspaceCandidateSerial=0, workspaceBatchSubmitting=false;
let workspaceBatchId, workspaceBatchActive=false, workspaceJob, exportPreview, slotComparisonSerial=0;

function trainingName(id,fallback){
  const input=$(id);
  return input.value||input.placeholder||fallback;
}

function suggestTrainingNames(stem){
  const safe=stem.replace(/[\x00-\x1f\x7f-\x9f]/g,'').trim();
  const encoder=new TextEncoder();
  for(const [id,max] of [['trainingShortName',23],['trainingFullName',63]]){
    let name='';
    for(const character of safe){
      if(encoder.encode(name+character).length>max)break;
      name+=character;
    }
    $(id).placeholder=name;
  }
}


const trainingOptions=[
  'targetKind','gamut','endpoint','wbTraining','speedPriority','evaluations','weightRandom',
  'weightPrimaries','weightGray','weightCC24','weightSector16','parameterSmoothing',
  'outputContinuity','searchStarts','adaptiveRounds','gammaColorRounds','perceptualWeight',
  'quantizationSweeps','adamLearningRate','adamSteps','baselineLook'
];

function workspaceTrainingOptions(){
  return Object.fromEntries(trainingOptions.map(id=>{
    const input=$(id);
    if(id==='speedPriority')return [id,fastTraining()];
    return [id,input.type==='checkbox'?input.checked:input.value];
  }));
}

function workspaceTab(id){
  for(const button of document.querySelectorAll('[data-workspace-tab]')){
    const active=button.dataset.workspaceTab===id;
    button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
  }
  for(const panel of document.querySelectorAll('.workspace-panel'))panel.hidden=panel.id!==id;
  if(id==='workspaceTraining')drawTrainingLoss();
}

function layoutWorkspace(){
  const training=$('targetKind').closest('section'), editor=$('add').closest('section');
  const slotsCard=$('looks').closest('section'), oldExport=$('collection').closest('section');
  const comparison=$('before').closest('section'), charts=$('histStatus').closest('section');
  const nameHint=$('lookName').closest('label').nextElementSibling;
  const preview=$('photoPreview'), raw=$('rawExport').closest('section'), log=$('log').closest('section');
  $('workspaceTraining').append(training);
  $('workspaceCompare').append(comparison,$('sector16Cohort'),charts,preview);
  $('workspaceRaw').append(raw);
  $('workspaceRecords').append(log);
  $('workspaceEdit').append(editor);
  for(const id of ['shortName','lookName','baselineLook'])$('workspaceFields').append($(id).closest('label'));
  $('workspaceFields').append(nameHint,$('sourceNote'),$('reset'));
  $('slotHint').textContent='可独立保存每个槽位。未保存修改作为草稿恢复。';
  const inspector=$('workspaceInspector');
  inspector.insertBefore($('moveSlotTarget').closest('label'),$('workspaceCopy'));
  inspector.append($('moveSlot'),$('discardSlot'));
  $('workspaceProjectControls').append($('importBin').closest('label'),$('importProject').closest('label'),$('export'));
  $('workspaceInspector').append($('exportStatus'));
  $('workspaceRecords').append($('collection'),$('saveProject'));
  oldExport.hidden=true;
  $('export').textContent='导出 BIN';
  $('workspaceMerge').hidden=false;
  for(const button of document.querySelectorAll('[data-workspace-tab]')){
    button.onclick=()=>workspaceTab(button.dataset.workspaceTab);
  }
  $('gamma').closest('section').querySelector('h2').textContent='原生参数';
  $('add').textContent='保存本槽';
  $('addCompressed').textContent='载入压缩配方到本槽';
  $('saveProject').textContent='导出已保存参数 JSON';
  $('confirmImport').textContent='导入为新工程';
  $('cancelImport').textContent='取消';
  editor.id='workspaceEditor';
  $('workspaceProjectControls').removeAttribute('hidden');
  $('workspaceShell').classList.add('project-mode');
}

function workspaceSnapshot(){
  remember();
  return {
    entries:clone(collection),
    sources:Object.fromEntries(collection.filter(e=>collectionSources.has(e.number) &&
      collectionSources.get(e.number)).map(e=>[e.number,collectionSources.get(e.number)])),
    drafts:Object.fromEntries(modifiedSlots().map(number=>[number,{
      entry:clone(drafts.get(number)),source:clone(draftSources.get(number))||null
    }])),
    selected,
    settings:{...workspaceTrainingOptions(),
      ...(workspaceBatchId?{batchId:workspaceBatchId}:{})},
    jobs:{...workspace.jobs}
  };
}

function queueWorkspaceSave(){
  if(!workspace||workspaceLoading)return;
  workspaceDirty=true;$('workspaceStatus').textContent='保存草稿中…';
  clearTimeout(workspaceTimer);
  workspaceTimer=setTimeout(()=>flushWorkspace().catch(error=>toast(error.message)),350);
}

async function flushWorkspace(){
  clearTimeout(workspaceTimer);
  if(workspaceSave)await workspaceSave;
  while(workspaceDirty){
    if(workspaceSave){await workspaceSave;continue;}
    const state=workspaceSnapshot(), {id,revision}=workspace;
    workspaceDirty=false;
    workspaceSave=(async()=>{
      try{
        workspace=await (await api('/api/projects/save',{id,revision,...state})).json();
        if(!workspaceDirty)$('workspaceStatus').textContent='已写入本机';
        renderWorkspaceInspector();
      }catch(error){
        workspaceDirty=true;$('workspaceStatus').textContent='保存失败 · '+error.message;throw error;
      }finally{workspaceSave=undefined;}
    })();
    await workspaceSave;
  }
}

async function workspaceCommand(task, flush=true){
  if(workspaceActionBusy)return;
  workspaceActionBusy=true;
  $('workspaceShell').inert=$('workspaceToolbar').inert=true;
  try{
    if(flush)await flushWorkspace();
    await task();
  }catch(error){toast(error.message);}
  finally{$('workspaceShell').inert=$('workspaceToolbar').inert=false;workspaceActionBusy=false;}
}

function canOpenWorkspace(){
  if(busy||compressionBusy||submittedTraining||chartUploading||libraryImportBusy||workspaceBatchSubmitting){
    toast('请等待当前训练、压缩或导入完成后再切换工程。');
    return false;
  }
  return true;
}

async function workspaceRequest(action, extra={}){
  const base=workspace?{id:workspace.id,revision:workspace.revision}:{};
  return api('/api/projects/'+action,{...base,...extra});
}

async function refreshWorkspaceList(){
  const values=await (await api('/api/projects')).json();
  $('workspacePicker').replaceChildren(...values.map(value=>new Option(value.name,value.id)));
  $('workspacePicker').value=workspace.id;
}

function resetWorkspaceInputs(){
  lutText='';chartTargetId=undefined;photoFile=undefined;rawFile=undefined;photoId=undefined;photoSlotRequest=undefined;photoShownSlot=undefined;
  photoUploadSerial++;
  $('photoSourceMode').value='slot';
  clearTimeout(photoTimer);photoBusy=false;clearActual();submittedTraining=completedTraining=undefined;
  workspaceCandidate=undefined;workspaceCandidateSerial++;
  workspaceJob=undefined;
  clearTrainingTrace();
  for(const id of ['trainingShortName','trainingFullName'])$(id).value='';
  suggestTrainingNames('');
  renderWorkspaceJob();
  invalidateSlotComparison();
  for(const id of ['lut','chartTarget','rawInput','photoInput','targetFolder'])$(id).value='';
  for(const id of ['lutLabel','chartTargetStatus','rawName','photoName','rawStatus'])$(id).textContent='';
  $('targetFolder').dispatchEvent(new Event('change'));
  for(const id of ['history','trainedFilter'])$(id).value='';
  $('log').textContent='请选择工程记录或本机历史任务。';
  $('addCompressed').hidden=true;
  for(const id of ['tonalMetrics','sector16Details'])$(id).replaceChildren();
  for(const id of ['histMean','anchorStatus','cc24Status','sector16Status','datasetStatus'])$(id).textContent='请载入训练任务查看结果。';
  for(const canvas of $('workspaceCompare').querySelectorAll('canvas'))
    canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
}

async function openWorkspace(value){
  workspaceLoading=true;
  try{
    workspace=value;
    resetWorkspaceInputs();
    applyImportedProject({...boot.template,schema:boot.config_schemas[value.format],
                          entries:value.entries,export_sources:value.sources});
    for(const [key,item] of Object.entries(value.drafts)){
      drafts.set(+key,clone(item.entry));
      if(item.source)draftSources.set(+key,clone(item.source));
    }
    draft=undefined;
    for(const id of trainingOptions){
      const input=$(id), setting=value.settings[id];
      const defaultInput=workspaceDefaults[id];
      if(id==='speedPriority')input.value=(typeof setting==='boolean'?setting:defaultInput)?'fast':'standard';
      else if(input.type==='checkbox')input.checked=typeof setting==='boolean'?setting:defaultInput;
      else input.value=typeof setting==='string'?setting:defaultInput;
    }
    $('targetKind').onchange();$('parameterSmoothing').oninput();trainingModeHint();
    selectLook(value.selected);renderCollection();
    await openWorkspaceBatch();
    $('jobStatus').textContent='请选择训练目标，或从任务记录查看已有结果。';
    $('workspaceTitle').textContent=value.name;
    $('workspaceStatus').textContent='已读取本机工程';
    workspaceDirty=false;
    try{localStorage.setItem('r5-active-project',value.id);}catch{}
    await refreshWorkspaceList();
  }finally{workspaceLoading=false;}
}

function renderWorkspaceInspector(){
  if(!workspace)return;
  const state=slotState(selected).state;
  const versionList=workspace.history[String(selected)]||[];
  const labels={'imported-bin':'导入 BIN',compressed:'压缩任务',stock:'原厂网格',manual:'手动编辑'};
  $('workspaceSlotTitle').textContent='槽位 '+String(selected).padStart(2,'0');
  $('workspaceSlotState').textContent={empty:'空槽',configured:'已保存',modified:'未保存修改'}[state];
  $('workspaceSource').textContent=state==='empty'?'可创建配方、载入训练结果或从 BIN 导入。':
    (labels[draftSource?.kind]||'手动编辑')+(draftSource?.sha256?' · '+draftSource.sha256.slice(0,12):'');
  $('workspaceCandidate').hidden=!workspaceCandidate;
  if(workspaceCandidate){
    const slot=workspaceCandidate.slot;
    $('workspaceCandidateLabel').textContent='任务 '+workspaceCandidate.id.slice(0,8)+' · 目标槽位 '+slot;
    $('workspaceSaveCandidate').textContent='保存训练结果到第 '+slot+' 槽';
    $('workspaceSaveCandidate').disabled=!gridKeys.has(workspaceCandidate.id);
  }
  $('trainingSlotNote').textContent='训练目标槽位 '+selected+'。训练名称用于新结果。';
  $('compareSlot').disabled=!collection.some(e=>e.number===selected);
  $('compareSlot').textContent=state==='modified'?'比较已保存与当前草稿':'比较色卡基线与当前槽位';
  photoReady();

  $('workspaceCreateSlot').hidden=state!=='empty';
  $('workspaceEditor').hidden=$('workspaceFields').hidden=state==='empty';
  $('workspaceClear').disabled=state==='empty';
  $('workspaceCopy').disabled=$('moveSlot').disabled;
  const previousVersion=$('workspaceVersions').value;
  const sameSlot=$('workspaceVersions').dataset.slot===String(selected);
  $('workspaceVersions').dataset.slot=String(selected);
  $('workspaceVersions').replaceChildren(new Option('选择已保存版本…',''),
    ...versionList.map((v,i)=>new Option(v.entry.full_name+' · '+new Date(v.at).toLocaleString(),String(i))));
  if(sameSlot&&previousVersion!==''&&versionList[+previousVersion])$('workspaceVersions').value=previousVersion;
  $('workspaceRestoreVersion').disabled=!versionList.length;
  const previousJob=$('workspaceJobList').value;
  $('workspaceJobList').replaceChildren(new Option('查看本工程任务…',''),
    ...Object.entries(workspace.jobs).reverse().map(([id,n])=>new Option('槽位 '+n+' · '+id.slice(0,8),id)));
  if(workspace.jobs[previousJob])$('workspaceJobList').value=previousJob;
  $('workspaceExports').textContent=workspace.exports.length?workspace.exports.map(e=>
    new Date(e.at).toLocaleString()+' · v'+e.format+' · '+e.slots.length+' 槽 · '+e.sha256.slice(0,12)).join('\n'):'尚无工程导出记录';
}

function renderGrid(){
  if(!workspace)return;
  const grid=draft.grid_5x9x9.coefficients[+$('gridPlane').value][+$('gridLuma').value], table=$('gridTable');
  header(table,['U ／ V',...Array.from({length:9},(_,i)=>String(i))]);
  grid.forEach((row,u)=>{
    const tr=table.insertRow();tr.insertCell().textContent=String(u);
    row.forEach((v,index)=>tr.append(cell(v,-64,63,next=>{row[index]=next;})));
  });
}

function editWorkspaceSlot(entry, source){
  draft={...clone(entry),number:selected};draftSource=clone(source)||{kind:'manual'};
  showNames();renderEditors();queueWorkspaceSave();
}

function saveWorkspaceSlots(numbers){
  const snapshot=workspaceSnapshot(), entries=new Map(collection.map(e=>[e.number,e]));
  for(const n of numbers){
    const item=snapshot.drafts[n];
    if(!item)continue;
    entries.set(n,item.entry);snapshot.sources[n]=item.source||{kind:'manual'};
    delete snapshot.drafts[n];
  }
  return {...snapshot,entries:[...entries.values()]};
}

function applyWorkspaceSlots(value){
  workspace=value;
  libraryVersion=value.format;
  collection=clone(value.entries);
  collectionSources.clear();for(const [n,source] of Object.entries(workspace.sources))collectionSources.set(+n,source);
  drafts.clear();draftSources.clear();
  for(const [n,item] of Object.entries(workspace.drafts)){
    drafts.set(+n,item.entry);if(item.source)draftSources.set(+n,item.source);
  }
  workspaceLoading=true;
  try{draft=undefined;selectLook(workspace.selected);renderCollection();}
  finally{workspaceLoading=false;}
  $('workspaceStatus').textContent='已写入本机';
}

async function writeWorkspaceState(state){
  applyWorkspaceSlots(await (await workspaceRequest('save',state)).json());
}

function registerWorkspaceJob(id, number){
  if(!workspace)return;
  workspace.jobs=Object.fromEntries([...Object.entries(workspace.jobs).slice(-95),[id,number]]);
  queueWorkspaceSave();
}

function showWorkspaceCandidate(result){
  workspaceCandidate={id:jobId,slot:workspace.jobs[jobId]||result.config.entries[0].number};
  workspaceCandidateSerial++;
  renderWorkspaceInspector();
  toast('训练结果可保存到第 '+workspaceCandidate.slot+' 槽，也可载入为草稿。');
}

async function loadWorkspaceCandidate(compressed, save=false){
  if(!workspaceCandidate||workspaceCandidate.id!==jobId)throw Error('请先选定已完成的训练任务');
  const candidate=workspaceCandidate, n=save?candidate.slot:selected, project=workspace.id;
  const serial=workspaceCandidateSerial;
  if(n!==candidate.slot||slotState(n).state!=='empty'){
    const action=save?'保存训练结果到':'载入训练结果为草稿到';
    if(!confirm(action+'第 '+n+' 槽？现有草稿将被替换，已保存版本可从历史恢复。'))return;
  }
  const key=gridKeys.get(candidate.id);
  if(compressed&&!key)throw Error('当前任务尚未生成可用压缩网格');
  const useGrid=Boolean(key);
  const value=await(await api('/api/jobs/'+candidate.id+(useGrid?'/grid-firmware-config?key='+key:''))).json();
  if(project!==workspace.id||(!save&&n!==selected)||serial!==workspaceCandidateSerial)return;
  const entry=useGrid?value.entries[0]:value.result.config.entries[0];
  const source=useGrid?value.export_sources[String(entry.number)]:{kind:'manual',job:candidate.id};
  if(save){
    await saveTrainingEntries([{entry:{...entry,number:n},source}],n);
    toast('训练结果已保存到第 '+n+' 槽');
  }else{
    editWorkspaceSlot(entry,source);
    toast('训练配方已载入为草稿，请检查后保存本槽。');
  }
  workspaceTab('workspaceEdit');
}

async function saveTrainingEntries(items, selectedSlot=selected){
  const state=workspaceSnapshot();
  const entries=new Map(state.entries.map(entry=>[entry.number,entry]));
  for(const {entry,source} of items){
    entries.set(entry.number,entry);
    state.sources[entry.number]=source;
    delete state.drafts[entry.number];
  }
  state.entries=[...entries.values()];
  state.selected=selectedSlot;
  await writeWorkspaceState(state);
}

async function saveBatchResults(jobs){
  const slots=jobs.map(job=>job.number);
  const occupied=slots.filter(number=>slotState(number).state!=='empty');
  if(occupied.length&&!confirm('保存将替换第 '+occupied.join('、')+' 槽的当前配方或草稿。继续吗？'))return;
  const items=[];
  for(const job of jobs){
    const value=await(await api('/api/jobs/'+job.id+'/grid-firmware-config?key='+job.grid_key)).json();
    const entry=value.entries[0];
    if(entry.number!==job.number)throw Error('批量结果的槽号与任务不一致');
    items.push({entry,source:value.export_sources[String(entry.number)]});
  }
  await saveTrainingEntries(items);
  toast('已保存 '+items.length+' 个批量结果');
}

function renderWorkspaceJob(job){
  workspaceJob=job;
  const linked=job&&workspace?.jobs[job.id];
  $('workspaceJobStatus').textContent=linked?'第 '+linked+' 槽 · '+(job.name?job.name+' · ':'')+job.phase:'';
  $('workspaceViewJob').hidden=!(linked&&job.status==='done');
  $('workspaceViewTrace').hidden=!(linked&&job.training_trace_available);
  const trainingLog=$('workspaceTrainingLog');
  trainingLog.hidden=!(linked&&job.training_log_available);
  if(!trainingLog.hidden)trainingLog.href='/api/jobs/'+job.id+'/training-log';
  $('workspaceRetryJob').hidden=!(linked&&job.retry_available&&['done','error'].includes(job.status));
  const fitting=linked?job.result?.fitting:undefined;
  const settings=$('workspaceJobSettings');
  settings.hidden=!fitting?.search_options;
  if(settings.hidden)settings.open=false;
  const options=fitting?.search_options||{};
  const weights=fitting?.group_total_weights||{};
  const rows=[
    ['训练模式',typeof fitting?.speed_priority==='boolean'?(fitting.speed_priority?'快速':'标准'):undefined],
    ['参数平滑',options.parameter_smoothing],['输出连续性强度',options.output_continuity],
    ['感知色差权重',options.perceptual_weight],['搜索起点',options.starts],
    ['MPS Adam 学习率',options.adam_learning_rate],
    ['MPS Adam 步数',options.adam_steps],
    ['默认候选筛选',linked&&job.result?.guarded_adam
      ? (job.result.guarded_adam.selected==='candidate'?'采用 2000 步筛选配方':'保留 600 步基准') : undefined],
    ['色彩交替轮数',options.gamma_color_rounds],['动态权重轮数',options.adaptive_rounds],
    ['原生参数量化微调轮数',options.quantization_sweeps],
    ['随机色权重',weights.random],['正色权重',weights.primaries],['灰阶权重',weights.gray],
    ['标准 24 色权重',weights.colorchecker24],['矩阵 16 色相权重',weights.sector16]
  ];
  $('workspaceJobSettingsText').textContent=rows.filter(([,value])=>value!==undefined)
    .map(([label,value])=>label+'  '+value).join('\n');
  $('trainingSnapshotNote').textContent=job?.status==='done'?'任务 '+job.id.slice(0,8)+' · 训练快照按该任务参数生成。':'选择训练任务查看该次结果。';
}

function invalidateSlotComparison(){
  slotComparisonSerial++;
  $('compareSlotResults').hidden=true;
  $('compareSlotStatus').textContent=$('compareSlot').disabled?'请选择已保存的槽位。':'';
}

async function compareWorkspaceSlot(){
  const saved=collection.find(entry=>entry.number===selected);
  if(!saved)return;
  const modified=slotState(selected).state==='modified';
  invalidateSlotComparison();
  const serial=slotComparisonSerial;
  const endpoint=Number($('compareSlotEndpoint').value);
  $('compareSlotStatus').textContent='正在计算同一组色块…';
  $('compareSlot').disabled=true;
  try{
    const value=await(await api('/api/compare-slot',{saved:modified?saved:null,draft:modified?draft:saved,endpoint})).json();
    if(serial!==slotComparisonSerial)return;
    palette('savedSlotColors',value.saved);
    palette('draftSlotColors',value.draft);
    $('compareSlotReference').textContent=modified?'已保存配方':'色卡 PT 基线';
    $('compareSlotSubject').textContent=modified?'当前草稿':'当前槽位';
    $('compareSlotResults').hidden=false;
    $('compareSlotStatus').textContent=value.samples+' 色块 · 平均差 '+value.mae.toFixed(2)+
      ' · 均方根差 '+value.rmse.toFixed(2)+'（8 位码值）'+(value.gamma_tail_changed?' · Gamma 第 129 点有变化，色块模拟使用前 128 点。':'');
  }catch(error){
    if(serial===slotComparisonSerial)$('compareSlotStatus').textContent=error.message;
  }finally{
    if(serial===slotComparisonSerial)$('compareSlot').disabled=false;
  }
}

function renderExportPreview(){
  if(!exportPreview)return;
  const reference=$('exportReference').value;
  const numbers=slots=>slots.map(slot=>slot.number).join('、')||'无';
  const summaries=[['只导出已保存槽位',exportPreview.saved]];
  if(exportPreview.draft_slots.length)summaries.push(['保存全部草稿并导出',exportPreview.with_drafts]);
  $('exportPreview').replaceChildren(...summaries.map(([label,summary],index)=>{
    const group=document.createElement('section'), title=document.createElement('strong'), details=document.createElement('p');
    title.textContent=label+' · v'+summary.format;
    const lines=['导出槽位 '+numbers(summary.slots),
      ...summary.slots.map(slot=>slot.number+' · '+slot.name)];
    if(!index&&exportPreview.draft_slots.length)lines.push('未纳入的草稿 '+exportPreview.draft_slots.join('、'));
    if(!summary.slots.length)lines.push('空 BIN 导入机内后会清空配方库。');
    const diff=summary.differences[reference];
    if(diff)lines.push('相比所选原始 BIN · 新增 '+(diff.added.join('、')||'无')+
      ' · 修改 '+(diff.changed.join('、')||'无')+' · 移除 '+(diff.removed.join('、')||'无'));
    details.textContent=lines.join('\n');
    group.append(title,details);
    return group;
  }));
}

let workspaceDefaults;
async function initWorkspace(){
  layoutWorkspace();
  workspaceDefaults=workspaceTrainingOptions();
  const values=await(await api('/api/projects')).json();
  let previous;
  try{previous=localStorage.getItem('r5-active-project');}catch{}
  const saved=values.find(p=>p.id===previous)||values[0];
  const load=id=>api('/api/projects/open?id='+encodeURIComponent(id)).then(response=>response.json());
  await openWorkspace(saved?await load(saved.id):await(await workspaceRequest('create',{name:'未命名工程'})).json());
  $('workspacePicker').onchange=()=>{
    const key=$('workspacePicker').value;
    $('workspacePicker').value=workspace.id;
    if(canOpenWorkspace())workspaceCommand(async()=>openWorkspace(await load(key)));
  };
  for(const [id,action] of [['workspaceNew','create'],['workspaceRename','rename'],['workspaceDuplicate','duplicate']]){
    $(id).onclick=()=>{
      if(!canOpenWorkspace())return;
      const label=prompt('工程名称',action==='create'?'未命名工程':workspace.name+(action==='duplicate'?' 副本':''));
      if(!label?.trim())return;
      workspaceCommand(async()=>{
        const value=await(await workspaceRequest(action,{name:label})).json();
        if(action==='rename'){
          workspace=value;$('workspaceTitle').textContent=value.name;await refreshWorkspaceList();
        }else await openWorkspace(value);
      });
    };
  }
  $('workspaceBackup').onclick=()=>workspaceCommand(async()=>{
    const response=await workspaceRequest('backup');
    download(await response.blob(),workspace.name+'.r5proj');toast('已备份工程和草稿');
  });
  $('workspaceRestore').onchange=e=>{
    const file=e.target.files[0];e.target.value='';
    if(!file||!canOpenWorkspace())return;
    workspaceCommand(async()=>{
      const response=await fetch('/api/projects/restore',{method:'POST',headers:{
        'Content-Type':'application/octet-stream','X-R5-Token':boot.token},body:file});
      const value=await response.json();if(!response.ok)throw Error(value.error);
      await openWorkspace(value);toast('备份已恢复为独立工程');
    });
  };
  $('workspaceMerge').onclick=()=>finishWorkspaceImport(true);
  $('workspaceCreate').onclick=()=>editWorkspaceSlot(freshConfiguration(selected),{kind:'manual'});
  $('workspaceLoadCandidate').onclick=()=>workspaceCommand(()=>loadWorkspaceCandidate(false));
  $('workspaceSaveCandidate').onclick=()=>workspaceCommand(()=>loadWorkspaceCandidate(true,true));
  $('compareSlot').onclick=compareWorkspaceSlot;
  $('compareSlotEndpoint').onchange=()=>{
    renderWorkspaceInspector();
    invalidateSlotComparison();
  };
  $('workspaceClear').onclick=()=>{
    if(!confirm('清空当前槽位？已保存版本可从工程记录恢复。'))return;
    workspaceCommand(async()=>{
      const state=workspaceSnapshot();
      state.entries=state.entries.filter(e=>e.number!==selected);
      delete state.sources[selected];delete state.drafts[selected];
      await writeWorkspaceState(state);
    });
  };
  for(const [id,move] of [['workspaceCopy',false],['moveSlot',true]]){
    $(id).onclick=()=>workspaceCommand(async()=>{
      const n=Number($('moveSlotTarget').value), source=collection.find(e=>e.number===selected);
      if(!source||!Number.isInteger(n)||n<1||n>24||slotState(n).state!=='empty')throw Error('请选择 1～24 的空槽');
      const state=workspaceSnapshot();
      state.entries.push({...clone(source),number:n});
      if(state.sources[selected])state.sources[n]=clone(state.sources[selected]);
      if(move){state.entries=state.entries.filter(e=>e.number!==selected);delete state.sources[selected];}
      state.selected=n;await writeWorkspaceState(state);
    });
  }
  $('workspaceRestoreVersion').onclick=()=>{
    const index=$('workspaceVersions').value;
    if(index==='')return;
    const version=workspace.history[String(selected)]?.[+index];
    if(version&&confirm('把此版本恢复为当前草稿？'))editWorkspaceSlot(version.entry,version.source);
  };
  $('workspaceJobList').onchange=()=>{
    if(busy||compressionBusy){toast('请等待当前任务完成');return;}
    if($('workspaceJobList').value){jobId=$('workspaceJobList').value;poll();}
  };
  $('workspaceViewJob').onclick=()=>{ $('photoSourceMode').value='job';$('photoSourceMode').onchange();workspaceTab('workspaceCompare'); };
  $('workspaceViewTrace').onclick=()=>workspaceTab('workspaceTraining');
  $('workspaceRetryJob').onclick=()=>workspaceCommand(async()=>{
    if(busy||compressionBusy||workspaceBatchSubmitting||workspaceBatchActive||!workspaceJob)return;
    const response=await(await api('/api/fit/retry',{id:workspaceJob.id})).json();
    jobId=response.id;
    registerWorkspaceJob(jobId,response.number);
    setBusy(true);
    workspaceTab('workspaceTraining');
    clearTimeout(timer);
    poll();
  });
  $('add').onclick=()=>workspaceCommand(async()=>{
    if(slotState(selected).state!=='modified')return;
    await writeWorkspaceState(saveWorkspaceSlots([selected]));toast('本槽已保存');
  });
  $('addCompressed').onclick=()=>workspaceCommand(()=>loadWorkspaceCandidate(true));
  $('exportReference').onchange=renderExportPreview;
  $('export').onclick=()=>workspaceCommand(async()=>{
    exportPreview=await(await workspaceRequest('export-preview')).json();
    const references=Object.keys(exportPreview.saved.differences);
    $('exportReference').replaceChildren(...references.map((sha,index)=>new Option('原始 BIN '+(index+1)+' · '+sha.slice(0,12),sha)));
    $('exportReferenceLabel').hidden=!references.length;
    $('workspaceSaveAndExport').hidden=!exportPreview.draft_slots.length;
    renderExportPreview();
    $('workspaceExportDialog').showModal();
  });
  for(const [id,save] of [['workspaceExportSaved',false],['workspaceSaveAndExport',true]]){
    $(id).onclick=()=>{
      $('workspaceExportDialog').close();
      if(!collection.length&&(!save||!modifiedSlots().length)&&!confirm('空 BIN 会清空机内自定义滤镜。确认导出？'))return;
      workspaceCommand(async()=>{
        if(save&&modifiedSlots().length)await writeWorkspaceState(saveWorkspaceSlots(modifiedSlots()));
        const response=await workspaceRequest('export',{allow_saved:!save,allow_empty:!collection.length});
        const revision=Number(response.headers.get('X-R5-Project-Revision'));
        const archive=await response.blob();
        workspace.revision=revision;
        download(archive,'r5-native-config.zip');
        const updated=await load(workspace.id);
        if(updated.revision===revision)workspace=updated;
        renderWorkspaceInspector();toast('已导出 R5NATIVE.BIN、参数 JSON 与校验回执');
      });
    };
  }
  $('applyRaw').onclick=()=>workspaceCommand(async()=>{
    const value=JSON.parse($('rawEditor').value);
    if(value.number!==selected)throw Error('序号必须与当前配置一致');
    await api('/api/validate',project([value]));
    editWorkspaceSlot(value,draftSource);
  },false);
  $('saveProject').onclick=()=>download(new Blob([JSON.stringify(project(),null,2)],{type:'application/json'}),'native_config.json');
  for(const id of ['gridPlane','gridLuma'])$(id).onchange=renderGrid;
  for(const id of trainingOptions)$(id).addEventListener('change',queueWorkspaceSave);
  window.addEventListener('beforeunload',event=>{
    if(workspaceDirty||workspaceSave){event.preventDefault();event.returnValue='';}
  });
}

function finishWorkspaceImport(merge){
  if(!pendingImport)return;
  const imported=pendingImport;
  if(!canOpenWorkspace())return;
  if(merge&&!imported.sha256){toast('配置 JSON 请导入为独立工程');return;}
  cancelLibraryImport();
  workspaceCommand(async()=>{
    const action=merge?'merge':'create';
    const body=imported.sha256?{sha256:imported.sha256}:{config:imported.config};
    if(!merge)body.name=imported.name.replace(/\.[^.]+$/,'').slice(0,80)||'导入配方';
    const result=await(await workspaceRequest(action,body)).json();
    if(merge){
      // 合并只更新空槽，保留当前训练目标及预览。
      applyWorkspaceSlots(result);toast('已合并到空槽');
    }else{await openWorkspace(result);toast('已建立独立导入工程');}
  });
}
