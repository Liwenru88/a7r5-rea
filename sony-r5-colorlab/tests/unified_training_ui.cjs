// 执行生产提交与轮询逻辑，验证单入口、防重复提交和失败重试。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const staticDir = process.argv[2];
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
assert.ok(/id="fit"[^>]*>训练并生成滤镜/.test(html), '训练按钮应使用统一名称');
assert.doesNotMatch(html, /id="distillGrid"/);
const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, {value: '', querySelector: () => ({})});
  return elements.get(id);
};
const context = vm.createContext({structuredClone, console, setTimeout: () => 1,
  clearTimeout() {}, document: {getElementById: get}});
vm.runInContext(fs.readFileSync(path.join(staticDir,'workspace.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8').replace('\ninit();\n', '\n'), context);
vm.runInContext(`
  let requests=[], notices=[], pending, fail=false, pollError=false, jobError=false;
  let options={number:24,lut:'cube-A',compression_training:true,pc_options:{response:'shared-C1'}};
  lutText='cube-A';$('gridResponseModel').value='measured';
  remember=()=>{}; fitOptions=compression=>({...structuredClone(options),compression_training:compression});
  const productionShowResult=showResult;
  toast=message=>notices.push(message); showResult=()=>{}; loadDiagnostics=async()=>{};
  // 训练曲线依赖浏览器 DOM，本测试只覆盖提交与轮询状态。
  refreshTrainingTrace=async()=>{};
  setBusy=value=>{busy=value;$('fit').disabled=value||compressionBusy;};
  api=async(url,body)=>{
    requests.push({url,body});
    if(url==='/api/fit'){
      await new Promise(resolve=>pending=resolve);
      if(fail)throw Error('提交失败');
      return {json:async()=>({id:'job-'+requests.length})};
    }
    if(url.endsWith('/grid-training'))return {json:async()=>({status:'done',key:'grid'})};
    if(pollError)throw Error('读取状态失败');
    return {json:async()=>({id:jobId,status:jobError?'error':'done',error:'训练失败',phase:'完成',started:0,
      result:{grid_key:'grid',pc_compensation:{enabled:true}}})};
  };
`, context);
const run = code => vm.runInContext(code, context);
const flush = async () => {for (let i=0;i<12;i++) await Promise.resolve();};
(async () => {
  const first=run('trainAndGenerate()');
  await run('trainAndGenerate()');
  assert.equal(run('requests.length'),1, '提交请求返回前双击只能创建一个任务');
  assert.equal(run('requests[0].body.compression_training'),true);
  assert.equal(run('requests[0].body.pc_compensation'),true);
  assert.equal(run('requests[0].body.pc_options.curve_mode'),'tone-tint');
  run('pending()'); await first; await flush();
  assert.equal(run('busy'),false);
  await run('trainAndGenerate()'); await flush();
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),1,'相同输入复用已完成结果');
  run("options.lut='cube-B'; fail=true");
  const failed=run('trainAndGenerate()');run('pending()');await failed;
  assert.equal(run('busy'),false,'提交失败后允许重试');
  run('fail=false');
  const retry=run('trainAndGenerate()');run('pending()');await retry;await flush();
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),3,'目标变化与失败重试均可提交');
  run("lutText='';jobId='legacy';gridKeys.delete(jobId);pcJobs.add(jobId)");
  await run('trainAndGenerate()');await flush();
  assert.equal(run("requests.filter(r=>r.url==='/api/grid-training').length"),1);
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),3,'历史结果续压缩不能重新拟合');
  await run('trainAndGenerate()');
  assert.equal(run("requests.filter(r=>r.url==='/api/grid-training').length"),1,'已有压缩结果直接复用');
  run("lutText='cube-C';options.lut='cube-C';chartUploading=true");
  await run('trainAndGenerate()');
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),3,'上传中不能提交');
  run('chartUploading=false;pollError=true');
  const disconnected=run('trainAndGenerate()');run('pending()');await disconnected;await flush();
  assert.equal(run('busy'),false);
  run('pollError=false');await run('trainAndGenerate()');await flush();
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),4,'轮询中断后重新连接，不能创建重复任务');
  run("options.lut='cube-D';jobError=true");
  const solverFailure=run('trainAndGenerate()');run('pending()');await solverFailure;await flush();
  run('jobError=false');
  const solverRetry=run('trainAndGenerate()');run('pending()');await solverRetry;await flush();
  assert.equal(run("requests.filter(r=>r.url==='/api/fit').length"),6,'训练失败不能缓存为成功结果');
  run(`let pendingStatus;jobId='old-job';api=async()=>({json:()=>new Promise(resolve=>pendingStatus=resolve)});`);
  const stale=run('poll()');await flush();
  run("jobId=undefined;$('jobStatus').textContent='配置库已导入';pendingStatus({id:'old-job',status:'done',phase:'旧任务',started:0,result:{grid_key:'grid'}})");
  await stale;
  assert.equal(elements.get('jobStatus').textContent,'配置库已导入','切换到导入库后忽略旧任务异步回写');
  run(`
    workspace={id:'active',jobs:{training:24}};
    jobId='training';selected=24;draft={number:24,full_name:'用户草稿'};drafts.set(24,draft);
    palette=()=>{};renderWorkspaceInspector=()=>{};
    $('metrics').replaceChildren=()=>{};$('metrics').append=()=>{};
    document.createElement=()=>({append(){}});
    const metrics={mae_8bit:1,rmse_8bit:2,p95_8bit:3};
    const fitResult={preview:{},heldout:{before:metrics,after:metrics},config:{entries:[{number:24,full_name:'训练结果'}]}};
    productionShowResult(fitResult);
  `);
  assert.equal(run('draft.full_name'),'用户草稿','训练完成后保留当前草稿');
  assert.equal(run('drafts.get(24).full_name'),'用户草稿');
  assert.equal(run('workspaceCandidate.slot'),24,'训练结果绑定为原目标槽的候选');
  console.log(JSON.stringify({status:'PASS',scenarios:11}));
})().catch(error=>{console.error(error);process.exitCode=1;});
