'use strict';

const photoColorMetrics = (() => {
  const get = id => document.getElementById(id);
  const lanes = [
    ['model', 'photoModel', '原 RAW 预览'],
    ['calibrated', 'photoCalibrated', '校准后 RAW 预览'],
    ['camera', 'photoCamera', '机内直出 JPEG'],
  ];
  const loaded = image => !image.hidden && image.complete && image.naturalWidth && image.currentSrc === image.src;
  const full = [0, 0, 1, 1];
  let frame, target, token, sourceFormat, region, drag, request;
  let selecting = false;

  function setSelecting(value) {
    selecting = value;
    drag = undefined;
    frame.classList.toggle('selecting', value);
    get('photoSelectRegion').setAttribute('aria-pressed', String(value));
    get('photoSelectRegion').textContent = value ? '取消框选' : '框选区域';
    drawBox(region);
  }

  function drawBox(area) {
    const box = get('photoRegionBox');
    box.hidden = !area;
    if (!area) return;
    const [left, top, right, bottom] = area;
    Object.assign(box.style, {
      left: left*100+'%', top: top*100+'%', width: (right-left)*100+'%', height: (bottom-top)*100+'%',
    });
  }

  function coordinates(event) {
    const rect = target.getBoundingClientRect();
    const clamp = value => Math.min(1, Math.max(0, value));
    return [clamp((event.clientX-rect.left)/rect.width), clamp((event.clientY-rect.top)/rect.height)];
  }

  function bounds(start, end) {
    return [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
      Math.max(start[0], end[0]), Math.max(start[1], end[1])];
  }

  function sameAspect(image, reference) {
    const {naturalWidth: w, naturalHeight: h} = image;
    const {naturalWidth: rw, naturalHeight: rh} = reference;
    // 允许缩放后取整导致的一个像素偏差。
    return Math.abs(w*rh-rw*h) <= Math.max(w,h,rw,rh);
  }

  function renderRows(rows) {
    const nodes = rows.map(row => {
      const tr = document.createElement('tr');
      tr.dataset.lane = row.name;
      const label = document.createElement('th');
      label.scope = 'row';
      label.textContent = row.label;
      tr.append(label);
      if (row.metrics) {
        for (const key of ['rgb_rmse','delta_e00_mean','delta_e00_p95']) {
          const td = document.createElement('td');
          td.textContent = row.metrics[key].toFixed(2);
          tr.append(td);
        }
      } else {
        const td = document.createElement('td');
        td.colSpan = 3;
        td.textContent = row.note;
        tr.append(td);
      }
      return tr;
    });
    get('photoMetricsRows').replaceChildren(...nodes);
  }

  function sample(images, area) {
    const [x, y, right, bottom] = area;
    const sw = right-x, sh = bottom-y;
    const reference = images[0], w = reference.naturalWidth, h = reference.naturalHeight;
    const scale = Math.min(512/Math.max(sw*w, sh*h),
      ...images.map(image => Math.min(image.naturalWidth/w, image.naturalHeight/h)));
    const width = Math.max(1, Math.round(sw*w*scale)), height = Math.max(1, Math.round(sh*h*scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d', {colorSpace:'srgb', willReadFrequently:true});
    context.imageSmoothingEnabled = false;
    const payload = new Uint8Array(width*height*3*images.length);
    let offset = 0;
    for (const image of images) {
      const iw = image.naturalWidth, ih = image.naturalHeight;
      context.drawImage(image, x*iw, y*ih, sw*iw, sh*ih, 0, 0, width, height);
      const rgba = context.getImageData(0, 0, width, height).data;
      for (let i=0; i<rgba.length; i+=4) {
        payload[offset++] = rgba[i];
        payload[offset++] = rgba[i+1];
        payload[offset++] = rgba[i+2];
      }
    }
    return {width, height, payload};
  }

  async function calculate(rows, candidates, area, controller) {
    try {
      const {width, height, payload} = sample([target, ...candidates.map(row => row.image)], area);
      const query = new URLSearchParams({width, height, rows:candidates.map(row => row.name).join(',')});
      const response = await fetch('/api/preview-color-metrics?'+query, {
        method:'POST', headers:{'Content-Type':'application/octet-stream','X-R5-Token':token},
        body:payload, signal:controller.signal,
      });
      const value = await response.json();
      if (controller.signal.aborted) return;
      if (!response.ok) throw Error(value.error);
      for (const row of candidates) row.metrics = value[row.name];
      renderRows(rows);
      get('photoMetricsStatus').textContent =
        (region ? '框选区域' : '整图')+' · '+width+' × '+height+' 个采样像素';
    } catch (error) {
      if (controller.signal.aborted) return;
      for (const row of candidates) row.note = '统计失败';
      renderRows(rows);
      get('photoMetricsStatus').textContent = '统计失败，可点击“查看整图”重试。'+error.message;
    }
  }

  function refresh(format) {
    if (!frame) return;
    if (typeof format === 'string') sourceFormat = format;
    request?.abort();
    if (get('photoResults').hidden || selecting) return;
    const ready = loaded(target);
    const status = get('photoMetricsStatus');
    get('photoSelectRegion').disabled = !ready;
    get('photoWholeImage').disabled = !ready;
    const rows = lanes.map(([name, id, label]) => {
      const image = get(id);
      if (name === 'model' && sourceFormat && sourceFormat !== 'arw') label = '配方预览';
      let note;
      if (name === 'calibrated' && get('photoCalibratedPanel').hidden) note = '未生成校准预览';
      else if (name === 'camera' && image.hidden) note = '未导入机内 JPEG';
      else if (!ready) note = '等待目标图';
      else if (!loaded(image)) note = '等待图像加载';
      else if (!sameAspect(image, target)) note = '画幅比例不同，请核对方向与裁切';
      else note = '计算中…';
      return {name, image, label, note};
    });
    renderRows(rows);
    const candidates = rows.filter(row => row.note === '计算中…');
    if (!ready) status.textContent = '导入目标图后显示统计。';
    else if (!candidates.length) status.textContent = '等待画幅匹配的对比图。';
    else {
      status.textContent = (region ? '框选区域' : '整图')+' · 正在计算…';
      const controller = new AbortController();
      request = controller;
      requestAnimationFrame(() => {
        if (!controller.signal.aborted) calculate(rows, candidates, region || full, controller);
      });
    }
  }

  function resetRegion() {
    if (!frame) return;
    region = undefined;
    setSelecting(false);
    refresh();
  }

  function init(sessionToken) {
    token = sessionToken;
    frame = get('photoTargetFrame');
    target = get('photoActual');
    get('photoSelectRegion').onclick = () => {
      setSelecting(!selecting);
      if (selecting) {
        request?.abort();
        get('photoMetricsStatus').textContent = '在目标图上拖动，松开后统计框内色差。';
        frame.scrollIntoView({block:'nearest'});
      } else refresh();
    };
    get('photoWholeImage').onclick = resetRegion;
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && selecting) {
        setSelecting(false);
        refresh();
      }
    });
    for (const id of ['photoModel','photoCalibrated']) {
      for (const type of ['load','error']) get(id).addEventListener(type, refresh);
    }
    frame.addEventListener('pointerdown', event => {
      if (!selecting || drag || event.button !== 0 || !loaded(target)) return;
      event.preventDefault();
      drag = {pointer:event.pointerId, start:coordinates(event)};
      frame.setPointerCapture(event.pointerId);
    });
    frame.addEventListener('pointermove', event => {
      if (drag?.pointer === event.pointerId) drawBox(bounds(drag.start, coordinates(event)));
    });
    frame.addEventListener('pointerup', event => {
      if (drag?.pointer !== event.pointerId) return;
      const area = bounds(drag.start, coordinates(event));
      if ((area[2]-area[0])*target.naturalWidth >= 2 && (area[3]-area[1])*target.naturalHeight >= 2) {
        region = area;
      }
      setSelecting(false);
      refresh();
    });
    frame.addEventListener('pointercancel', event => {
      if (drag?.pointer !== event.pointerId) return;
      setSelecting(false);
      refresh();
    });
  }

  return {init, refresh, resetRegion};
})();
