'use strict';

(function () {
  const MAX_SLOTS = 24;
  const STORAGE_KEY = 'r5_filter_library_selection_v1';

  const state = {
    loaded: false,
    loading: false,
    categories: [],
    filters: [],
    baseSamples: [],
    byKey: new Map(),
    activeCategory: '__all__',
    query: '',
    selectedKeys: [],
    busy: false,
    detailItem: null,
    detailPhotoIdx: 0,
    detailMode: 'split',
    detailSplitPct: 50,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function showMsg(msg) {
    if (typeof toast === 'function') {
      toast(msg);
    } else {
      const status = el('libPackStatus');
      if (status) status.textContent = msg;
    }
  }

  function loadSavedSelection() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        state.selectedKeys = parsed.filter((k) => typeof k === 'string').slice(0, MAX_SLOTS);
      }
    } catch (_) {}
  }

  function saveSelection() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.selectedKeys));
    } catch (_) {}
  }

  function formatErrorText(item) {
    const te = item.training_error;
    if (!te || te.status !== 'available' || typeof te.mean !== 'number') {
      return item.series || item.category;
    }
    const mean = te.mean.toFixed(3);
    const p95 = typeof te.p95 === 'number' ? ` · P95 ${te.p95.toFixed(3)}` : '';
    return `ΔE00 ${mean}${p95}`;
  }

  function switchAppView(viewName) {
    const isLib = viewName === 'library';
    const wb = el('workbenchView');
    const lib = el('filterLibraryView');
    if (wb) wb.hidden = isLib;
    if (lib) lib.hidden = !isLib;
    for (const btn of document.querySelectorAll('[data-app-view]')) {
      const active = btn.dataset.appView === viewName;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', String(active));
    }
    if (isLib && !state.loaded && !state.loading) {
      fetchLibrary();
    }
  }

  async function fetchLibrary() {
    state.loading = true;
    const status = el('libGridStatus');
    if (status) status.textContent = '正在扫描全部滤镜…';
    try {
      const res = await fetch('/api/filter-library', { cache: 'no-store' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '加载滤镜库失败');
      state.categories = data.categories || [];
      state.filters = data.filters || [];
      state.baseSamples = data.base_samples || [];
      state.byKey = new Map(state.filters.map((f) => [f.key, f]));
      state.selectedKeys = state.selectedKeys.filter((k) => state.byKey.has(k));
      state.loaded = true;
      const badge = el('navLibraryCount');
      if (badge) badge.textContent = String(state.filters.length);
      renderAll();
    } catch (err) {
      if (status) status.textContent = err.message || '加载失败';
      showMsg(err.message || '加载滤镜库失败');
    } finally {
      state.loading = false;
    }
  }

  function filteredItems() {
    const q = state.query.trim().toLowerCase();
    return state.filters.filter((item) => {
      if (state.activeCategory !== '__all__' && item.category !== state.activeCategory) {
        return false;
      }
      if (!q) return true;
      return (
        item.short_name.toLowerCase().includes(q) ||
        item.name.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q) ||
        item.series.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q)
      );
    });
  }

  function renderCategories() {
    const nav = el('libCategoryList');
    if (!nav) return;
    nav.innerHTML = '';

    const allBtn = document.createElement('button');
    allBtn.type = 'button';
    allBtn.className = 'lib-cat-btn' + (state.activeCategory === '__all__' ? ' active' : '');
    allBtn.innerHTML = `<span>全部滤镜</span><span class="lib-cat-count">${state.filters.length}</span>`;
    allBtn.onclick = () => {
      state.activeCategory = '__all__';
      renderCategories();
      renderCards();
    };
    nav.appendChild(allBtn);

    for (const cat of state.categories) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lib-cat-btn' + (state.activeCategory === cat.name ? ' active' : '');
      btn.innerHTML = `<span>${escapeHtml(cat.name)}</span><span class="lib-cat-count">${cat.count}</span>`;
      btn.onclick = () => {
        state.activeCategory = cat.name;
        renderCategories();
        renderCards();
      };
      nav.appendChild(btn);
    }
  }

  function createCard(item) {
    const slotIdx = state.selectedKeys.indexOf(item.key);
    const selected = slotIdx !== -1;
    const card = document.createElement('article');
    card.className = 'lib-film-card' + (selected ? ' selected' : '');

    const perf = document.createElement('div');
    perf.className = 'lib-film-perf';
    for (let i = 0; i < 10; i++) {
      perf.appendChild(document.createElement('span'));
    }

    const body = document.createElement('div');
    body.className = 'lib-film-body';

    const left = document.createElement('div');
    left.className = 'lib-film-left';
    left.innerHTML = `
      <span class="lib-film-tag">R5 FILM</span>
      <strong class="lib-film-short" title="${escapeHtml(item.short_name)}">${escapeHtml(item.short_name)}</strong>
    `;

    const infoBtn = document.createElement('button');
    infoBtn.type = 'button';
    infoBtn.className = 'lib-info-btn';
    infoBtn.title = '查看滤镜详情';
    infoBtn.textContent = 'i';
    infoBtn.onclick = () => openDetailDialog(item);
    left.appendChild(infoBtn);

    const right = document.createElement('div');
    right.className = 'lib-film-right';
    const titleBtn = document.createElement('button');
    titleBtn.type = 'button';
    titleBtn.className = 'lib-film-title-btn';
    titleBtn.title = `${item.name}（点击查看详情与样片）`;
    titleBtn.textContent = item.name;
    titleBtn.onclick = () => openDetailDialog(item);
    const metaDiv = document.createElement('div');
    metaDiv.className = 'lib-film-meta';
    metaDiv.textContent = formatErrorText(item);
    right.append(titleBtn, metaDiv);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'lib-add-btn' + (selected ? ' added' : '');
    addBtn.textContent = selected ? `✓ 槽位 ${String(slotIdx + 1).padStart(2, '0')}（点击移除）` : '+ 加入资源栏';
    addBtn.onclick = () => toggleSelection(item.key);
    right.appendChild(addBtn);

    body.append(left, right);

    const footer = document.createElement('div');
    footer.className = 'lib-film-footer';
    footer.innerHTML = `
      <span>${escapeHtml(item.category)}</span>
      <span>R5 · V${item.format_version || 4}</span>
      <span>${item.updated ? escapeHtml(item.updated) : escapeHtml(item.id)}</span>
    `;

    card.append(perf, body, perf.cloneNode(true), footer);
    return card;
  }

  function renderCards() {
    const container = el('libCardContainer');
    const heading = el('libMainTitle');
    const countText = el('libMainCount');
    const status = el('libGridStatus');
    if (!container) return;

    const items = filteredItems();
    if (heading) {
      heading.textContent = state.activeCategory === '__all__' ? '全部滤镜' : state.activeCategory;
    }
    if (countText) {
      countText.textContent = `${items.length} 款滤镜`;
    }
    if (status) {
      status.textContent = items.length ? '' : '没有匹配的滤镜，请尝试其他关键词。';
    }

    container.innerHTML = '';
    if (!items.length) return;

    if (state.activeCategory === '__all__' && !state.query.trim()) {
      const grouped = new Map();
      for (const item of items) {
        if (!grouped.has(item.category)) grouped.set(item.category, []);
        grouped.get(item.category).push(item);
      }
      for (const [catName, catItems] of grouped.entries()) {
        const section = document.createElement('section');
        section.className = 'lib-group';
        const header = document.createElement('div');
        header.className = 'lib-group-head';
        header.innerHTML = `<h3>${escapeHtml(catName)}</h3><span>${catItems.length} 款</span>`;
        const grid = document.createElement('div');
        grid.className = 'lib-cards-grid';
        for (const item of catItems) {
          grid.appendChild(createCard(item));
        }
        section.append(header, grid);
        container.appendChild(section);
      }
    } else {
      const grid = document.createElement('div');
      grid.className = 'lib-cards-grid';
      for (const item of items) {
        grid.appendChild(createCard(item));
      }
      container.appendChild(grid);
    }
  }

  function toggleSelection(key) {
    const idx = state.selectedKeys.indexOf(key);
    if (idx !== -1) {
      state.selectedKeys.splice(idx, 1);
    } else {
      if (state.selectedKeys.length >= MAX_SLOTS) {
        showMsg(`最多只能选择 ${MAX_SLOTS} 个相机槽位`);
        return;
      }
      state.selectedKeys.push(key);
    }
    saveSelection();
    renderCards();
    renderResourceBar();
  }

  function moveSelection(index, delta) {
    const next = index + delta;
    if (next < 0 || next >= state.selectedKeys.length) return;
    const copy = [...state.selectedKeys];
    const [item] = copy.splice(index, 1);
    copy.splice(next, 0, item);
    state.selectedKeys = copy;
    saveSelection();
    renderCards();
    renderResourceBar();
  }

  function renderResourceBar() {
    const countEl = el('libSlotCount');
    const meterEl = el('libSlotMeter');
    const listEl = el('libSelectedList');
    const emptyEl = el('libEmptyState');
    const clearBtn = el('libClearAll');
    const downloadBinBtn = el('libDownloadBin');
    const downloadZipBtn = el('libDownloadZip');
    const importProjectBtn = el('libImportToProject');
    const formatNote = el('libFormatNote');

    const count = state.selectedKeys.length;
    if (countEl) countEl.textContent = `${count} / ${MAX_SLOTS}`;
    if (clearBtn) clearBtn.disabled = count === 0 || state.busy;
    if (downloadBinBtn) downloadBinBtn.disabled = count === 0 || state.busy;
    if (downloadZipBtn) downloadZipBtn.disabled = count === 0 || state.busy;
    if (importProjectBtn) importProjectBtn.disabled = count === 0 || state.busy;

    if (formatNote) {
      const ver = count > 12 ? 'v5（13–24 槽）' : 'v4（1–12 槽）';
      formatNote.textContent = count > 0 ? `R5NATIVE.BIN · 自动格式 ${ver}` : `R5NATIVE.BIN · 最多 ${MAX_SLOTS} 槽`;
    }

    if (meterEl) {
      meterEl.innerHTML = '';
      for (let i = 0; i < MAX_SLOTS; i++) {
        const seg = document.createElement('span');
        seg.className = 'lib-slot-seg' + (i < count ? ' filled' : '') + (i >= 12 ? ' high' : '');
        seg.title = `槽位 ${i + 1}`;
        meterEl.appendChild(seg);
      }
    }

    if (emptyEl) emptyEl.hidden = count > 0;
    if (!listEl) return;
    listEl.innerHTML = '';

    state.selectedKeys.forEach((key, index) => {
      const item = state.byKey.get(key);
      if (!item) return;
      const row = document.createElement('div');
      row.className = 'lib-slot-row';
      row.innerHTML = `
        <span class="lib-slot-num">${String(index + 1).padStart(2, '0')}</span>
        <div class="lib-slot-info">
          <strong>${escapeHtml(item.short_name)} · ${escapeHtml(item.name)}</strong>
          <small>${escapeHtml(item.category)}</small>
        </div>
      `;

      const actions = document.createElement('div');
      actions.className = 'lib-slot-actions';

      const upBtn = document.createElement('button');
      upBtn.type = 'button';
      upBtn.title = '上移槽位';
      upBtn.textContent = '↑';
      upBtn.disabled = index === 0;
      upBtn.onclick = () => moveSelection(index, -1);

      const downBtn = document.createElement('button');
      downBtn.type = 'button';
      downBtn.title = '下移槽位';
      downBtn.textContent = '↓';
      downBtn.disabled = index === count - 1;
      downBtn.onclick = () => moveSelection(index, 1);

      const rmBtn = document.createElement('button');
      rmBtn.type = 'button';
      rmBtn.title = '从资源栏移除';
      rmBtn.textContent = '×';
      rmBtn.onclick = () => toggleSelection(key);

      actions.append(upBtn, downBtn, rmBtn);
      row.appendChild(actions);
      listEl.appendChild(row);
    });
  }

  function updateDetailSlotButton() {
    const btn = el('libDetailToggleSlot');
    const item = state.detailItem;
    if (!btn || !item) return;
    const idx = state.selectedKeys.indexOf(item.key);
    if (idx !== -1) {
      btn.textContent = `✓ 已在槽位 ${String(idx + 1).padStart(2, '0')}（移出）`;
      btn.className = 'primary';
    } else {
      btn.textContent = '+ 加入资源栏';
      btn.className = 'secondary';
    }
    btn.onclick = () => {
      toggleSelection(item.key);
      updateDetailSlotButton();
    };
  }

  function renderDetailCompare() {
    const item = state.detailItem;
    const toolbar = el('libDetailToolbar');
    const photoTabs = el('libDetailPhotoTabs');
    const modeTabs = el('libDetailModeTabs');
    const holdBtn = el('libDetailHoldOrig');
    const stage = el('libDetailStage');
    if (!item || !toolbar || !photoTabs || !modeTabs || !stage) return;

    const samples = Array.isArray(item.samples) ? item.samples : [];
    if (!samples.length) {
      toolbar.hidden = true;
      stage.hidden = true;
      stage.innerHTML = '';
      return;
    }
    if (state.detailPhotoIdx >= samples.length) state.detailPhotoIdx = 0;
    const filterUrl = samples[state.detailPhotoIdx];
    const baseUrl = state.baseSamples[state.detailPhotoIdx] || '';
    const hasBase = Boolean(baseUrl);
    if (!hasBase && state.detailMode !== 'single') state.detailMode = 'single';

    toolbar.hidden = false;
    stage.hidden = false;

    photoTabs.innerHTML = '';
    samples.forEach((_, idx) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = state.detailPhotoIdx === idx ? 'active' : '';
      b.textContent = `样片 ${idx + 1}`;
      b.onclick = () => {
        state.detailPhotoIdx = idx;
        renderDetailCompare();
      };
      photoTabs.appendChild(b);
    });

    modeTabs.innerHTML = '';
    const modes = hasBase
      ? [
          ['split', '分割线对比'],
          ['side', '全片并排对比'],
          ['single', '仅看样片'],
        ]
      : [['single', '仅看样片']];
    for (const [m, label] of modes) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = state.detailMode === m ? 'active' : '';
      b.textContent = label;
      b.onclick = () => {
        state.detailMode = m;
        renderDetailCompare();
      };
      modeTabs.appendChild(b);
    }

    if (holdBtn) {
      holdBtn.hidden = !(hasBase && state.detailMode === 'single');
    }

    stage.innerHTML = '';
    if (state.detailMode === 'split' && hasBase) {
      const wrap = document.createElement('div');
      wrap.className = 'lib-split-wrap';
      wrap.tabIndex = 0;
      wrap.setAttribute('aria-label', '拖动分割线对比原片与滤镜效果');

      const baseImg = document.createElement('img');
      baseImg.className = 'lib-split-base';
      baseImg.src = baseUrl;
      baseImg.alt = `原片 ${state.detailPhotoIdx + 1}`;

      const overImg = document.createElement('img');
      overImg.className = 'lib-split-over';
      overImg.src = filterUrl;
      overImg.alt = `${item.name} 样片 ${state.detailPhotoIdx + 1}`;

      const divider = document.createElement('div');
      divider.className = 'lib-split-divider';
      const handle = document.createElement('span');
      handle.className = 'lib-split-handle';
      handle.textContent = '⇄';
      divider.appendChild(handle);

      const leftBadge = document.createElement('span');
      leftBadge.className = 'lib-badge left';
      leftBadge.textContent = '原片 (ST)';

      const rightBadge = document.createElement('span');
      rightBadge.className = 'lib-badge right';
      rightBadge.textContent = item.short_name;

      const applyPct = (pct) => {
        const clamped = Math.max(0, Math.min(100, pct));
        state.detailSplitPct = clamped;
        overImg.style.clipPath = `inset(0 0 0 ${clamped}%)`;
        divider.style.left = `${clamped}%`;
      };
      applyPct(state.detailSplitPct);

      let dragging = false;
      const updateFromEvent = (ev) => {
        const rect = wrap.getBoundingClientRect();
        if (rect.width <= 0) return;
        applyPct(((ev.clientX - rect.left) / rect.width) * 100);
      };
      wrap.addEventListener('pointerdown', (ev) => {
        dragging = true;
        wrap.setPointerCapture(ev.pointerId);
        updateFromEvent(ev);
      });
      wrap.addEventListener('pointermove', (ev) => {
        if (dragging) updateFromEvent(ev);
      });
      wrap.addEventListener('pointerup', (ev) => {
        dragging = false;
        if (wrap.hasPointerCapture(ev.pointerId)) wrap.releasePointerCapture(ev.pointerId);
      });
      wrap.addEventListener('keydown', (ev) => {
        if (ev.key === 'ArrowLeft') applyPct(state.detailSplitPct - 3);
        if (ev.key === 'ArrowRight') applyPct(state.detailSplitPct + 3);
      });

      wrap.append(baseImg, overImg, divider, leftBadge, rightBadge);
      stage.appendChild(wrap);
    } else if (state.detailMode === 'side' && hasBase) {
      const grid = document.createElement('div');
      grid.className = 'lib-side-grid';
      const pairs = [
        [baseUrl, '原片 (ST)'],
        [filterUrl, `${item.short_name} · ${item.name}`],
      ];
      for (const [url, label] of pairs) {
        const fig = document.createElement('figure');
        fig.className = 'lib-sample-fig';
        const link = document.createElement('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener';
        const img = document.createElement('img');
        img.src = url;
        img.alt = label;
        link.appendChild(img);
        const cap = document.createElement('figcaption');
        cap.innerHTML = `<span>${escapeHtml(label)}</span><span class="hint" style="margin:0">点击看大图 ↗</span>`;
        fig.append(link, cap);
        grid.appendChild(fig);
      }
      stage.appendChild(grid);
    } else {
      const wrap = document.createElement('div');
      wrap.className = 'lib-single-wrap';
      const img = document.createElement('img');
      img.src = filterUrl;
      img.alt = `${item.name} 样片 ${state.detailPhotoIdx + 1}`;
      const badge = document.createElement('span');
      badge.className = 'lib-badge left';
      badge.textContent = hasBase ? `${item.short_name}（按住画面看原片）` : item.short_name;
      const showOrig = () => {
        if (!hasBase) return;
        img.src = baseUrl;
        badge.textContent = '原片 (ST)';
      };
      const showFilter = () => {
        img.src = filterUrl;
        badge.textContent = hasBase ? `${item.short_name}（按住画面看原片）` : item.short_name;
      };
      if (hasBase) {
        img.addEventListener('pointerdown', showOrig);
        img.addEventListener('pointerup', showFilter);
        img.addEventListener('pointerleave', showFilter);
        img.addEventListener('pointercancel', showFilter);
        if (holdBtn) {
          holdBtn.onpointerdown = showOrig;
          holdBtn.onpointerup = showFilter;
          holdBtn.onpointerleave = showFilter;
          holdBtn.onpointercancel = showFilter;
        }
      }
      wrap.append(img, badge);
      stage.appendChild(wrap);
    }
  }

  function openDetailDialog(item) {
    const dlg = el('libDetailDialog');
    const body = el('libDetailBody');
    const title = el('libDetailTitle');
    if (!dlg || !body || !title) return;
    state.detailItem = item;
    state.detailMode = state.baseSamples.length ? 'split' : 'single';
    state.detailSplitPct = 50;
    title.textContent = `${item.short_name} · ${item.name}`;
    updateDetailSlotButton();
    renderDetailCompare();
    const te = item.training_error;
    const errLines =
      te && te.status === 'available'
        ? `平均色差：ΔE00 ${Number(te.mean).toFixed(3)} / P95 ${Number(te.p95).toFixed(3)} / 最大 ${Number(te.maximum).toFixed(3)}\n测试集：${te.label || te.protocol || '-'} (${te.samples || '-'} 样本)`
        : '暂无训练误差记录';
    body.textContent = [
      `分类目录：${item.category}`,
      `系列名称：${item.series}`,
      `菜单简写：${item.entry_short_name}`,
      `菜单全称：${item.entry_full_name}`,
      `更新时间：${item.updated || '-'}`,
      `文件格式：v${item.format_version || 4}`,
      `SHA256：${item.sha256}`,
      errLines,
      item.description ? `说明：${item.description}` : '',
    ]
      .filter(Boolean)
      .join('\n');
    dlg.showModal();
  }

  async function packAndDownload(format) {
    if (!state.selectedKeys.length || state.busy) return;
    state.busy = true;
    renderResourceBar();
    const status = el('libPackStatus');
    if (status) status.textContent = format === 'project' ? '正在导入到工作台工程…' : '正在打包 R5NATIVE.BIN…';

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (typeof TOKEN !== 'undefined' && TOKEN) {
        headers['X-R5-Token'] = TOKEN;
      }
      const res = await fetch('/api/filter-library/pack', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          format,
          items: state.selectedKeys.map((key) => ({ key })),
        }),
      });

      if (format === 'project') {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || '导入工程失败');
        if (typeof workspaceImportBinary === 'function') {
          await workspaceImportBinary(data, { replace: true });
        } else if (typeof importProjectData === 'function') {
          importProjectData(data.project);
        }
        switchAppView('workbench');
        showMsg(`已将 ${state.selectedKeys.length} 款滤镜写入当前工程`);
        if (status) status.textContent = `已导入 ${state.selectedKeys.length} 槽到工程。`;
        return;
      }

      if (!res.ok) {
        let msg = '打包失败';
        try {
          const err = await res.json();
          msg = err.error || msg;
        } catch (_) {}
        throw new Error(msg);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = format === 'zip' ? 'r5-native-config.zip' : 'R5NATIVE.BIN';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showMsg(`已生成 ${state.selectedKeys.length} 槽 ${a.download}`);
      if (status) status.textContent = `已下载 ${a.download}（${state.selectedKeys.length} 槽）。`;
    } catch (err) {
      showMsg(err.message || '操作失败');
      if (status) status.textContent = err.message || '操作失败';
    } finally {
      state.busy = false;
      renderResourceBar();
    }
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderAll() {
    renderCategories();
    renderCards();
    renderResourceBar();
  }

  function init() {
    loadSavedSelection();
    for (const btn of document.querySelectorAll('[data-app-view]')) {
      btn.addEventListener('click', () => switchAppView(btn.dataset.appView));
    }
    const search = el('libSearch');
    if (search) {
      search.addEventListener('input', () => {
        state.query = search.value;
        renderCards();
      });
    }
    const clearBtn = el('libClearAll');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        state.selectedKeys = [];
        saveSelection();
        renderCards();
        renderResourceBar();
      });
    }
    const dlBin = el('libDownloadBin');
    if (dlBin) dlBin.addEventListener('click', () => packAndDownload('bin'));
    const dlZip = el('libDownloadZip');
    if (dlZip) dlZip.addEventListener('click', () => packAndDownload('zip'));
    const impProj = el('libImportToProject');
    if (impProj) impProj.addEventListener('click', () => packAndDownload('project'));

    fetchLibrary();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
