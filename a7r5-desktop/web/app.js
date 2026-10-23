'use strict';
const $=s=>document.querySelector(s);
const invoke=(command,args={})=>window.__TAURI__.core.invoke(command,args);
const names={backup:'备份更新器',update:'更新信任环境',ssh_start:'上传并开启 SSH',ssh_stop:'停止本次 SSH',firmware:'封装更新包'};
let snapshot={tasks:[]}, operation=null, toastTimer;
function toast(message){$('#toast').textContent=String(message);$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,8500);}
function page(name){document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==name);document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('selected',b.dataset.page===name));$('#breadcrumb').textContent=$(`nav [data-page="${name}"] span`).textContent;}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>page(b.dataset.page));
document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=async()=>{try{const value=await invoke('choose_path',{kind:b.dataset.pick});if(value)$(`#${b.dataset.pick==='backup'?'backup':b.dataset.pick}-path`).value=value;}catch(e){toast(e);}});
function text(tag,value,className){const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;return e;}
function button(label,handler,primary=false){const b=text('button',label,primary?'primary':'');b.onclick=async()=>{b.disabled=true;try{await handler();await refresh();}catch(e){toast(e);}finally{b.disabled=false;}};return b;}
async function refresh(){
  snapshot=await invoke('overview');
  $('#pending-dot').hidden=!snapshot.pending;
  const banner=$('#banner');banner.hidden=!snapshot.pending&&!snapshot.busy;banner.textContent=snapshot.busy?'任务正在执行，请保持连接与供电。点击查看任务记录。':'有设备任务尚未确认结束。请先核对 MSC 和相机屏幕，再进行下一次操作。';banner.onclick=()=>page('history');
  $('#ssh-state').textContent=snapshot.active_ssh?'已记录本应用启动的 SSH 实例':'没有本应用记录的活动实例';
  document.querySelectorAll('.device').forEach(b=>b.disabled=!!snapshot.busy||!!snapshot.pending||(b.dataset.action==='ssh_stop'?!snapshot.active_ssh:!!snapshot.active_ssh));
  $('#build').disabled=!!snapshot.busy;
  $('#data-path').textContent='记录保存于：'+snapshot.data;
  const list=$('#task-list');list.replaceChildren();
  if(!snapshot.tasks.length){list.append(text('div','还没有任务。选择左侧功能开始。','empty'));return;}
  snapshot.tasks.forEach(t=>{
    const el=text('div','','task'),head=text('div','','task-head');head.append(text('b',names[t.kind]||t.kind),text('small',new Date(t.created*1000).toLocaleString('zh-CN')));el.append(head);
    const r=t.result||{};
    let message=t.running?t.message:(r.error|| (t.kind==='firmware'?'更新包已生成，签名与输出帧核对完成；请阅读卡刷说明。':r.task_complete?(r.USB_recovered?(r.screen_confirmation_pending?'机内任务及 MSC 恢复已核实，请确认相机屏幕正常。':'已完成，并由用户确认相机屏幕正常。'):'机内任务已核实完成，正在等待 MSC 恢复；如机身无模式选项，可重新拔插并选择 MSC。'):'任务结果未核实，请保留连接与现场，不自动重试。'));
    el.append(text('p',message,r.error?'error':r.task_complete||r.output?'success':''));
    if(!t.running){const actions=text('div','','task-actions');actions.append(button('打开任务记录',()=>invoke('reveal_task',{id:t.id,guide:false})));
      if(r.guide)actions.append(button('阅读卡刷说明',()=>invoke('reveal_task',{id:t.id,guide:true}),true));
      if(snapshot.pending?.id===t.id && r.task_complete){
        if(!r.USB_recovered)actions.append(button('已选择 MSC，重新检查',async()=>{await invoke('recover_task',{id:t.id});},true));
        else actions.append(button('我已确认相机屏幕正常',()=>invoke('confirm_screen',{id:t.id}),true));
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
    $('#operation-risk').textContent=kind==='update'?'本次将修改相机更新器分区的信任身份。写入不是原子操作；中断可能导致更新器不可用。工具会重新验证当前完整前像并完整回读，但不能保证任意故障下可恢复。':kind==='backup'?'本次读取完整更新器分区并保存备份，不修改信任身份。USB 服务会临时切换连接模式。':'本次对机内临时目录执行固定 SSH 服务操作，不写入持久预加载。上传与启动之间不会退出 USB 服务；仅在全部回执通过后统一退出。';
    $('#operation-dialog').showModal();
  }catch(e){toast(e);}
});
$('#operation-dialog').addEventListener('close',async()=>{
  if($('#operation-dialog').returnValue!=='go'){operation=null;return;}
  const kind=operation;operation=null;if(!kind)return;
  const input={kind};if(kind==='update')input.backup_manifest=$('#backup-path').value;
  if(kind==='ssh_start'){input.password=$('#password').value;$('#password').value='';$('#password-again').value='';}
  try{await invoke('start_task',{input});page('history');await refresh();}catch(e){toast(e);}finally{input.password='';}
});
$('#build').onclick=async()=>{try{const source=$('#source-path').value,output=$('#output-path').value;if(!source||!output)throw '请选择官方固件与新的输出位置。';const features={};document.querySelectorAll('.feature-grid input').forEach(c=>features[c.name]=c.checked);$('#build').disabled=true;await invoke('start_task',{input:{kind:'firmware',source,output,features,version:$('#version').value.trim()}});page('history');await refresh();}catch(e){toast(e);$('#build').disabled=false;}};
refresh().catch(e=>toast('客户端初始化失败：'+e));setInterval(()=>refresh().catch(()=>{}),1600);
