'use strict';
const $=s=>document.querySelector(s);
const invoke=(command,args={})=>window.__TAURI__.core.invoke(command,args);
const names={backup:'备份更新器',update:'更新信任环境',update_force:'强制安装研究签名信任',ssh_start:'上传并开启 SSH',ssh_stop:'停止本次 SSH',firmware:'封装更新包'};
let snapshot={tasks:[]}, operation=null, toastTimer;
function toast(message){$('#toast').textContent=String(message);$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,8500);}
function page(name){document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('selected',b.dataset.page===name));$('#breadcrumb').textContent=$(`nav [data-page="${name}"] span`).textContent;}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>page(b.dataset.page));
document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=async()=>{try{const value=await invoke('choose_path',{kind:b.dataset.pick});if(value)$(`#${b.dataset.pick==='backup'?'backup':b.dataset.pick}-path`).value=value;}catch(e){toast(e);}});
function text(tag,value,className){const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;return e;}
function button(label,handler,primary=false){const b=text('button',label,primary?'primary':'');b.onclick=async()=>{b.disabled=true;try{await handler();await refresh();}catch(e){toast(e);}finally{b.disabled=false;}};return b;}
async function refresh(){
  snapshot=await invoke('overview');
  $('#pending-dot').hidden=true;
  const banner=$('#banner');banner.hidden=!snapshot.busy;banner.textContent='任务正在执行，请保持连接与供电。点击查看任务记录。';banner.onclick=()=>page('history');
  $('#ssh-state').textContent=snapshot.active_ssh?'已记录本应用启动的 SSH 实例':'没有本应用记录的活动实例';
  document.querySelectorAll('.device').forEach(b=>b.disabled=!!snapshot.busy||(b.dataset.action==='ssh_stop'?!snapshot.active_ssh:b.dataset.action==='ssh_start'&&!!snapshot.active_ssh));
  $('#build').disabled=!!snapshot.busy;
  $('#data-path').textContent='记录保存于：'+snapshot.data;
  const list=$('#task-list');list.replaceChildren();
  if(!snapshot.tasks.length){list.append(text('div','还没有任务。选择左侧功能开始。','empty'));return;}
  snapshot.tasks.forEach(t=>{
    const el=text('div','','task'),head=text('div','','task-head');head.append(text('b',names[t.kind]||t.kind),text('small',new Date(t.created*1000).toLocaleString('zh-CN')));el.append(head);
    const r=t.result||{};
    if(r.force_install||r.report?.force_install)el.append(text('p','本次为强制安装：已跳过原厂备份记录和前像匹配限制。','warning'));
    let message=t.running?t.message:(r.error|| (t.kind==='firmware'?'更新包已生成，签名与输出帧核对完成；请阅读卡刷说明。':r.task_complete?(r.USB_recovered?(r.screen_confirmation_pending?'机内任务及 MSC 恢复已核实，请确认相机屏幕正常。':'已完成，并由用户确认相机屏幕正常。'):'机内任务已核实完成，正在等待 MSC 恢复；如机身无模式选项，可重新拔插并选择 MSC。'):'任务结果未核实，请保留连接与现场，不自动重试。'));
    el.append(text('p',message,r.error?'error':r.task_complete||r.output?'success':''));
    if(r.report?.trust_resource_check_failed&&!r.task_complete)el.append(text('p',
      '本次在写入前停止，未写更新器分区。请先排查资源或工作目录，不要重复安装。','warning'));
    else if(r.report?.native_write_complete&&!r.task_complete)el.append(text('p',
      '机内写入已完成，电脑端核验或退出尚未完成。'+(r.force_install||r.report?.force_install?'不要重复强制安装。':'不要重复安装。')+'请保留连接与现场。','warning'));
    else if(r.report?.partition_write_may_have_started&&!r.task_complete)el.append(text('p',
      '机内任务已触发，分区可能已修改，完成状态尚未核实。'+(r.force_install||r.report?.force_install?'不要重复强制安装。':'不要重复安装。')+'请保留连接与现场。','warning'));
    if(Number.isInteger(r.report?.trust_readback_completed_chunks)&&Number.isInteger(r.report?.trust_readback_total_chunks))
      el.append(text('p','电脑端回读进度：'+r.report.trust_readback_completed_chunks+' / '+r.report.trust_readback_total_chunks+' 块。'));
    if(r.report?.planned_sector_readback_verified)el.append(text('p','全部258个计划扇区已由电脑逐字节核对；整分区摘要与重开校验由机内完成。','success'));
    if(r.backup_complete && r.backup_file)el.append(text('p','完整备份已保存，长度与摘要校验通过。'+(r.task_complete?'':'退出状态尚未核实，原错误记录保留。'),'success'));
    if(r.backup_export_directory)el.append(text('p','备份已另存到：'+r.backup_export_directory,'backup-location success'));
    if(r.backup_export_error)el.append(text('p','备份另存失败：'+r.backup_export_error+'。原任务中的完整备份仍保留。','error'));
    if(r.report?.capture_cleanup_verified)el.append(text('p','本次机内临时备份已清理。','success'));
    else if(r.backup_complete && r.report?.capture_cleanup_required)el.append(text('p','机内临时备份清理未确认，本机完整备份已保留。'));
    if(!r.task_complete&&!r.report?.native_write_complete&&!r.report?.partition_write_may_have_started&&!r.report?.trust_resource_check_failed)el.append(text('p','失败记录已保留。新任务会重新识别当前 USB 连接；需要时可单独核对当前 MSC 状态。'));
    if(r.recovery_resolved)el.append(text('p','连接与屏幕已确认，失败任务已结束；本次操作仍未成功。'));
    if(!t.running){const actions=text('div','','task-actions');actions.append(button('打开任务记录',()=>invoke('reveal_task',{id:t.id,guide:false})));
      if(r.backup_complete && r.backup_file)actions.append(button('打开备份目录',()=>invoke('reveal_backup',{id:t.id})));
      if(r.guide)actions.append(button('阅读卡刷说明',()=>invoke('reveal_task',{id:t.id,guide:true}),true));
      if(t.recovery_available && !r.recovery_resolved && r.screen_confirmation_pending!==false){
        if(!r.USB_recovered)actions.append(button('已选择 MSC，重新检查',async()=>{await invoke('recover_task',{id:t.id});},true));
        else actions.append(button(r.task_complete?'我已确认相机屏幕正常':'屏幕正常，结束失败任务',()=>invoke('confirm_screen',{id:t.id}),true));
      }
      if(t.kind==='backup'&&r.task_complete&&r.trust_state==='original')actions.append(button('用于信任更新',async()=>{$('#backup-path').value=t.directory+'/result.json';page('camera');}));
      el.append(actions);
    }list.append(el);
  });
}
document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>{
  try{
    const kind=b.dataset.action;
    if(kind==='update'&&!$('#backup-path').value)throw '请先选择已完成的原厂备份记录。';
    if(kind==='ssh_start'){
      const password=$('#password').value;
      if([...password].length<8||[...password].length>128||/[\x00-\x1f\x7f]/.test(password))throw 'SSH 密码需要 8–128 个非控制字符。';
      if(password!==$('#password-again').value)throw '两次 SSH 密码不一致。';
    }
    operation=kind;$('#operation-title').textContent=names[kind];
    $('#operation-auth').textContent='继续后会打开终端，请在那里输入这台 Mac 的登录密码；它不是相机 SSH 密码。输入时不会显示字符；密码不会保存到任务记录。授权前可按 Control+C 取消，执行开始后请等待客户端返回结果。';
    $('#operation-go').textContent='继续并打开终端授权';
    $('#operation-risk').textContent=kind==='update_force'?'本次跳过成功原厂备份记录和原厂前像匹配限制，强制覆盖更新器内固定258个计划扇区。现有修改可能被覆盖，未知内容的兼容性无法保证，中断可能导致更新器不可用；没有自动回滚。机内完成整分区摘要和重开校验，电脑回读并逐字节核对全部258个计划扇区；不另存完整分区备份。':kind==='update'?'本次将修改相机更新器分区的信任身份。写入不是原子操作；中断可能导致更新器不可用。工具会重新验证当前完整前像并完整回读，但不能保证任意故障下可恢复。':kind==='backup'?'本次读取完整更新器分区并保存备份，不修改信任身份。本机完整备份落盘并复核后，将删除本次机内 RAM 临时副本；下载失败时保留副本。USB 服务会临时切换连接模式。':'本次对机内临时目录执行固定 SSH 服务操作，不写入持久预加载。上传与启动之间不会退出 USB 服务；仅在全部回执通过后统一退出。';
    $('#operation-dialog').showModal();
  }catch(e){toast(e);}
});
$('#operation-dialog').addEventListener('close',async()=>{
  if($('#operation-dialog').returnValue!=='go'){operation=null;return;}
  const kind=operation;operation=null;if(!kind)return;
  const input={kind:kind==='update_force'?'update':kind};if(kind==='update_force')input.force_install=true;if(kind==='update')input.backup_manifest=$('#backup-path').value;
  if(kind==='backup' && $('#backup-output-path').value)input.output=$('#backup-output-path').value;
  if(kind==='ssh_start'){input.password=$('#password').value;$('#password').value='';$('#password-again').value='';}
  try{await invoke('start_task',{input});page('history');await refresh();}catch(e){toast(e);}finally{input.password='';}
});
$('#build').onclick=async()=>{try{const source=$('#source-path').value,output=$('#output-path').value;if(!source||!output)throw '请选择官方固件与新的输出位置。';const features={};document.querySelectorAll('.feature-grid input').forEach(c=>features[c.name]=c.checked);$('#build').disabled=true;await invoke('start_task',{input:{kind:'firmware',source,output,features,version:$('#version').value.trim()}});page('history');await refresh();}catch(e){toast(e);$('#build').disabled=false;}};
refresh().catch(e=>toast('客户端初始化失败：'+e));setInterval(()=>refresh().catch(()=>{}),1600);
