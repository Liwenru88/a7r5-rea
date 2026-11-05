// 执行生产槽位与导入逻辑；DOM替身只提供浏览器节点和文件响应。
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const elements=new Map();
function element(){
  return {children:[],dataset:{},attributes:{},value:'',_text:'',
    get textContent(){return this._text+this.children.map(c=>c.textContent||'').join('');},
    set textContent(v){this._text=String(v);this.children=[];},
    append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this._text='';this.children=[...nodes];},
    setAttribute(k,v){this.attributes[k]=v;},showModal(){this.open=true;},close(){this.open=false;},
    classList:{toggle(){}}};
}
const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
const context=vm.createContext({structuredClone,console,setTimeout:()=>1,clearTimeout(){},
  document:{getElementById:get,createElement:element,querySelectorAll:s=>s==='.looks button'?get('looks').children:[]}});
const staticDir=process.argv[2];
const html=fs.readFileSync(path.join(staticDir,'index.html'),'utf8');
assert.ok(html.includes('id="importBin"'),'页面必须提供BIN导入入口');
vm.runInContext(fs.readFileSync(path.join(staticDir,'app.js'),'utf8').replace('\ninit();\n','\n'),context);
const run=code=>vm.runInContext(code,context);
run(`
  const entry=n=>({number:n,short_name:'TEST'+n,full_name:'测试'+n,cc1_delta:[[0]],block13:[[[0]]],
    gamma_native_129:[0,10],grid_5x9x9:{coefficients:[[[[0]]]]}});
  boot={slot_limit:24,config_schemas:{4:'r5-custom-filter-config/4',5:'r5-custom-filter-config/5'},
    template:{schema:'r5-custom-filter-config/4'},presets:[entry(1),entry(2)],stock_grids:[],max_project_bytes:2097152,token:'test'};
  baselineNote=()=>{};renderEditors=()=>syncRaw();toast=()=>{};
  let responseProject={schema:'r5-custom-filter-config/5',entries:[entry(1),entry(24)],
    export_sources:{'1':{kind:'imported-bin',sha256:'a'.repeat(64),source_number:1},
                    '24':{kind:'imported-bin',sha256:'a'.repeat(64),source_number:24}}};
  let uploadFail=false;
  fetch=async()=>({ok:!uploadFail,json:async()=>uploadFail?{error:'CRC错误'}:{project:responseProject,audit:{format_version:5}}});
  renderSlots();selectLook(1);renderCollection();
`);
const state=n=>get('looks').children[n-1].dataset.state;
(async()=>{
  assert.equal(state(1),'empty');run('selectLook(24);selectLook(1)');
  assert.equal(state(24),'empty','只浏览默认参数不能占用空槽');
  run("$('shortName').value='改名';readNames();syncRaw()");
  assert.equal(state(1),'modified');assert.equal(get('export').disabled,true);
  run('discardSlotChanges()');assert.equal(state(1),'empty');
  await run("importConfiguration({name:'R5NATIVE.BIN',size:5032},'bin')");
  assert.equal(run('collection.length'),0,'导入预览不能提前替换当前内容');
  assert.equal(get('importDialog').open,true);
  run('cancelLibraryImport()');assert.equal(run('collection.length'),0);
  await run("importConfiguration({name:'R5NATIVE.BIN',size:5032},'bin')");
  run('confirmLibraryImport()');
  assert.equal(state(1),'configured');assert.equal(state(24),'configured');assert.equal(state(2),'empty');
  assert.equal(run('projectVersion(collection)'),5);
  run('selectLook(1);selectLook(24);selectLook(1)');
  assert.equal(state(1),'configured','切换槽位不能错误标为未保存');
  run("$('shortName').value='新名称';readNames();syncRaw()");
  assert.equal(state(1),'modified');assert.equal(get('add').disabled,false,'改名可保留BIN来源');
  run('discardSlotChanges();draft.cc1_delta[0][0]++;syncRaw()');
  assert.equal(state(1),'modified');assert.equal(get('add').disabled,true,'色彩修改不能冒用原BIN来源');
  run('discardSlotChanges()');assert.equal(state(1),'configured');
  assert.throws(()=>run('moveConfiguration(24)'),/目标槽/);
  run('selectLook(2);selectLook(1);moveConfiguration(2)');
  assert.equal(state(1),'empty');assert.equal(state(2),'configured');
  assert.equal(run('collectionSources.get(2).source_number'),1,'移动保留原BIN来源槽号');
  run('moveConfiguration(1)');
  run("draftSource={kind:'stock',id:'test-stock'};remember();updateSlotStates()");
  assert.equal(state(1),'modified','来源改变即使参数相同也需保存');
  run('discardSlotChanges()');
  const before=run('JSON.stringify(exportProject())');
  run('uploadFail=true');await run("importConfiguration({name:'broken.bin',size:5032},'bin')");
  assert.equal(run('JSON.stringify(exportProject())'),before,'坏文件不能清空已有配置');
  run('removeConfiguration(1)');assert.equal(state(1),'empty');
  assert.equal(state(24),'configured');
  run("applyImportedProject({schema:'r5-custom-filter-config/4',entries:[],export_sources:{}})");
  assert.equal(state(24),'empty');assert.equal(run('drafts.size'),0,'替换库不能残留旧草稿');
  run("applyImportedProject({schema:'r5-custom-filter-config/5',entries:[],export_sources:{}})");
  assert.equal(run('projectVersion(collection)'),5,'导入v5后不因仅含低槽或空库而静默降级');
  console.log(JSON.stringify({status:'PASS',slots:24,states:['configured','empty','modified']}));
})().catch(e=>{console.error(e);process.exitCode=1;});
