// 用内存DOM验证失败任务的恢复按钮；不启动应用、不访问设备或网络。
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
const actualIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));

class Element {
  constructor(tag) {this.tag = tag; this.children = []; this.value = ''; this.dataset = {};}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this.children = children;}
  addEventListener(name, handler) {this[name] = handler;}
  showModal() {this.open = true;}
}

async function render(result, recoveryAvailable, overrides = {}, picked = null) {
  const elements = new Map();
  const calls = [];
  const select = selector => {
    if (selector.startsWith('#')) assert.ok(actualIds.has(selector.slice(1)), `页面缺少元素 ${selector}`);
    if (!elements.has(selector)) elements.set(selector, new Element(selector));
    return elements.get(selector);
  };
  const devices = [...html.matchAll(/data-action="([^"]+)"/g)].map(match => match[1]).map(action => {
    const element = new Element('button'); element.dataset.action = action; return element;
  });
  const pickers = [...html.matchAll(/data-pick="([^"]+)"/g)].map(match => {
    const element = new Element('button'); element.dataset.pick = match[1]; return element;
  });
  const features = [...html.matchAll(/type="checkbox" name="([^"]+)"( checked)?/g)].map(([, name, checked]) => ({
    name, checked: Boolean(checked),
  }));
  const snapshot = {tasks: [{id: 'a'.repeat(32), kind: 'backup', created: 1,
    result, recovery_available: recoveryAvailable}], pending: {id: 'a'.repeat(32)}, ...overrides};
  vm.runInNewContext(readFileSync(new URL('../web/app.js', import.meta.url), 'utf8'), {
    document: {querySelector: select, querySelectorAll: selector => ({
      '.device': devices, '[data-action]': devices, '[data-pick]': pickers, '.feature-grid input': features,
    })[selector] || [], createElement: tag => new Element(tag)},
    window: {__TAURI__: {core: {invoke: async (name, args) => {
      calls.push({name, args: JSON.parse(JSON.stringify(args))}); return name === 'choose_path' ? picked : snapshot;
    }}}},
    setInterval: () => 0, setTimeout: () => 0, clearTimeout: () => {},
  });
  await new Promise(setImmediate);
  function buttons(element) {
    return [...(element.tag === 'button' ? [element] : []), ...element.children.flatMap(buttons)];
  }
  function content(element) {return [element.textContent || '', ...element.children.map(content)].join('\n');}
  return {buttons: buttons(select('#task-list')), calls, devices, pickers, select,
    content: content(select('#task-list')), banner: select('#banner')};
}

test('4.17 整合预设独立提交且保留旧四项选择', async () => {
  const {select, calls} = await render({}, false);
  const preset = select('#firmware-preset');
  select('#source-path').value = '/fixture/official.DAT';
  select('#output-path').value = '/fixture/new/BODYDATA.DAT';
  select('#version').value = '4.06';
  preset.value = 'native24';
  preset.onchange();
  assert.equal(select('#custom-features').hidden, true);
  assert.equal(select('#native24-details').hidden, false);
  await select('#build').onclick();
  preset.value = 'custom';
  preset.onchange();
  assert.equal(select('#custom-version').hidden, false);
  await select('#build').onclick();
  const submitted = calls.filter(call => call.name === 'start_task').map(call => call.args.input);
  assert.deepEqual(submitted, [
    {kind: 'firmware', source: '/fixture/official.DAT', output: '/fixture/new/BODYDATA.DAT',
      version: '4.17', features: {native24: true}},
    {kind: 'firmware', source: '/fixture/official.DAT', output: '/fixture/new/BODYDATA.DAT',
      version: '4.06', features: {fl23: true, looks: true, ntsc: true, sound: true}},
  ]);
});

test('未启动服务的失败任务可以核对MSC，再由用户结束失败状态', async () => {
  const result = {task_complete: false, error: '原始接管失败', USB_recovered: false};
  const first = await render(result, true);
  await first.buttons.find(b => b.textContent === '已选择 MSC，重新检查').onclick();
  assert.ok(first.calls.some(call => call.name === 'recover_task'));
  const recovered = await render({...result, USB_recovered: true}, true);
  await recovered.buttons.find(b => b.textContent === '屏幕正常，结束失败任务').onclick();
  assert.ok(recovered.calls.some(call => call.name === 'confirm_screen'));
  const unknown = await render(result, false);
  assert.deepEqual(unknown.buttons.map(b => b.textContent), ['打开任务记录']);
});

test('历史待恢复标记不显示阻塞横幅，也不禁用新任务', async () => {
  const history = await render({task_complete: false, error: '历史失败'}, false);
  assert.equal(history.banner.hidden, true);
  assert.equal(history.devices.find(b => b.dataset.action === 'update').disabled, false);
  const running = await render({}, false, {busy: true});
  assert.ok(running.devices.every(b => b.disabled));
});

test('SSH 启动与本机实例记录无关，当前执行中的任务仍互斥', async () => {
  for (const busy of [false,true]) {
    for (const ssh_stop_available of [false,true]) {
      const view=await render({},false,{ssh_stop_available,busy});
      assert.equal(view.devices.find(b=>b.dataset.action==='update').disabled,busy);
      assert.equal(view.devices.find(b=>b.dataset.action==='ssh_start').disabled,busy);
      assert.equal(view.devices.find(b=>b.dataset.action==='ssh_stop').disabled,busy||!ssh_stop_available);
    }
  }
  assert.ok(!actualIds.has('ssh-state'));
});

test('设备操作均指引终端授权，打开确认框不启动事务', async () => {
  for (const kind of ['update', 'ssh_start', 'ssh_stop']) {
    const view = await render({}, false);
    view.select('#password').value = view.select('#password-again').value = 'fixture-password';
    view.devices.find(button => button.dataset.action === kind).onclick();
    assert.equal(view.select('#operation-dialog').open, true);
    assert.match(view.select('#operation-auth').textContent, /终端/);
    assert.match(view.select('#operation-go').textContent, /终端/);
    if (kind.startsWith('ssh_')) assert.match(view.select('#operation-auth').textContent, /不是相机 SSH 密码/);
    assert.ok(!view.calls.some(call => call.name === 'start_task'));
  }
});

test('完整备份独立展示，退出失败时不开放信任更新', async () => {
  const view = await render({task_complete: false, backup_complete: true,
    backup_file: '/fixture/partition.bin', trust_state: 'original', error: '退出未确认'}, false);
  assert.match(view.content, /完整备份已保存/);
  assert.match(view.content, /退出未确认/);
  assert.ok(!view.buttons.some(button => button.textContent === '用于信任更新'));
});

test('清理回执单独展示，失败时仍保留完整备份提示', async () => {
  for (const verified of [true, false]) {
    const view = await render({task_complete: verified, backup_complete: true,
      backup_file: '/fixture/partition.bin', report: {
        capture_cleanup_required: true, capture_cleanup_verified: verified,
      }}, false);
    assert.match(view.content, /完整备份已保存/);
    assert.match(view.content, verified ? /本次机内临时备份已清理/ : /清理未确认，本机完整备份已保留/);
  }
});

test('已有备份继续提供目录入口，维护页面无备份和记录选择', async () => {
  const view = await render({task_complete:true,backup_complete:true,
    backup_file:'/fixture/partition.bin',trust_state:'original'}, false);
  assert.deepEqual(view.devices.map(button => button.dataset.action), ['update','ssh_start','ssh_stop']);
  assert.ok(!view.pickers.some(button => button.dataset.pick.startsWith('backup')));
  assert.ok(!view.buttons.some(button => button.textContent === '用于信任更新'));
  await view.buttons.find(button => button.textContent === '打开备份目录').onclick();
  assert.ok(view.calls.some(call => call.name === 'reveal_backup'));
});

test('另存失败明确展示，同时保留已校验的原始备份', async () => {
  const view = await render({task_complete: true, backup_complete: true,
    backup_file: '/fixture/internal.bin', backup_export_error: '目标磁盘不可写'}, false);
  assert.match(view.content, /完整备份已保存/);
  assert.match(view.content, /目标磁盘不可写/);
});


test('直接更新经确认后仅提交无备份依赖的请求', async () => {
  for (const choice of ['cancel', 'go']) {
    const view = await render({}, false);
    const dialog = view.select('#operation-dialog');
    dialog.returnValue = 'go';
    view.devices.find(button => button.dataset.action === 'update').onclick();
    assert.equal(dialog.open, true);
    assert.equal(dialog.returnValue, '');
    assert.match(view.select('#operation-risk').textContent, /固定的 258/);
    assert.match(view.select('#operation-risk').textContent, /没有自动回滚/);
    assert.ok(!view.calls.some(call => call.name === 'start_task'));
    dialog.returnValue = choice; await dialog.close();
    const requests = view.calls.filter(call => call.name === 'start_task');
    assert.equal(requests.length, choice === 'go' ? 1 : 0);
    if (choice === 'go') assert.deepEqual(requests[0].args.input, {kind:'update',force_install:true});
  }
});

test('强制写入完成但电脑核验失败时明确显示阶段和进度，保留原错误', async () => {
  const view=await render({task_complete:false,error:'USBTimeoutError: fixture',report:{
    force_install:true,native_write_complete:true,trust_readback_completed_chunks:2,
    trust_readback_total_chunks:9,planned_sector_readback_verified:false,
  }},false,{tasks:[{id:'a'.repeat(32),kind:'update',created:1,result:{
    task_complete:false,error:'USBTimeoutError: fixture',report:{force_install:true,native_write_complete:true,
    trust_readback_completed_chunks:2,trust_readback_total_chunks:9,planned_sector_readback_verified:false}}}]});
  assert.match(view.content,/机内写入已完成/);
  assert.match(view.content,/2\s*\/\s*9/);
  assert.match(view.content,/USBTimeoutError/);
  assert.match(view.content,/不要重复强制安装/);
  assert.doesNotMatch(view.content,/新任务会重新识别/);
  assert.ok(!view.calls.some(call=>call.name==='start_task'));
});

test('旧回执仅确认触发写入时保留未知状态，不显示完成或鼓励重装', async () => {
  const view=await render({task_complete:false,error:'原始超时',report:{
    force_install:true,partition_write_may_have_started:true,
  }},false);
  assert.match(view.content,/分区可能已修改/);
  assert.match(view.content,/不要重复强制安装/);
  assert.doesNotMatch(view.content,/机内写入已完成|新任务会重新识别/);
});

test('写前资源失败明确显示本次未写分区，不鼓励重试或误报可能已修改', async () => {
  const view=await render({task_complete:false,error:'写入前资源检查失败：可用内存不足',report:{
    force_install:true,trust_resource_check_failed:true,partition_write_may_have_started:false,partition_writes:0,
  }},false);
  assert.match(view.content,/本次在写入前停止，未写更新器分区/);
  assert.doesNotMatch(view.content,/分区可能已修改|新任务会重新识别/);
});
