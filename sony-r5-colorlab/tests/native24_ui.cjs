// 执行生产网页函数；DOM替身仅提供节点，不替代配方或批量校验逻辑。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
function element() {
  return {children: [], dataset: {}, setAttribute() {}, append(...nodes) { this.children.push(...nodes); }, replaceChildren(...nodes) { this.children = nodes; }};
}
const context = vm.createContext({structuredClone, TextEncoder, console,
  document: {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); }, createElement: element}});
let source = fs.readFileSync(process.argv[2], 'utf8');
assert.equal(source.split('\ninit();\n').length, 2);
source = source.replace('\ninit();\n', '\n');
vm.runInContext(source, context);
vm.runInContext(`boot={slot_limit:24,config_schemas:{4:'r5-custom-filter-config/4',5:'r5-custom-filter-config/5'},template:{schema:'r5-custom-filter-config/4'},presets:[{},{}]}; renderSlots();`, context);
assert.equal(elements.get('looks').children.length, 24);
assert.equal(elements.get('looks').children[23].textContent, '24');
assert.equal(vm.runInContext("project([{number:12}]).schema", context), 'r5-custom-filter-config/4');
assert.equal(vm.runInContext("project([{number:24}]).schema", context), 'r5-custom-filter-config/5');
assert.equal(vm.runInContext("freshConfiguration(24).short_name", context), 'F24');
assert.equal(vm.runInContext("folderTargets(Array.from({length:24},(_,i)=>({name:'test'+i+'.jpg',size:100}))).length", context), 24);
assert.throws(()=>vm.runInContext("folderTargets(Array.from({length:25},(_,i)=>({name:'test'+i+'.jpg',size:100})))", context), /1–24/);
assert.equal(vm.runInContext('names.length', context), 12);
console.log(JSON.stringify({status:'PASS',slots:24,stock_baselines:12}));
