/* ── Helpers ───────────────────────────────────────────────────────────────── */
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

/* ── Custom confirm dialog ─────────────────────────────────────────────────── */
const confirmDialog  = document.getElementById('confirm-dialog');
const confirmMsg     = document.getElementById('confirm-msg');
const confirmOkBtn   = document.getElementById('confirm-ok');
const confirmCancel  = document.getElementById('confirm-cancel');
let _confirmResolve  = null;

function showConfirm(message, onOk) {
  confirmMsg.textContent = message;
  confirmOkBtn.textContent = T.delete || 'Delete';
  confirmDialog.style.display = 'flex';
  _confirmResolve = onOk;
}
function closeConfirm() { confirmDialog.style.display = 'none'; _confirmResolve = null; }
confirmOkBtn.addEventListener('click', () => { const fn = _confirmResolve; closeConfirm(); fn?.(); });
confirmCancel.addEventListener('click', closeConfirm);
confirmDialog.addEventListener('click', e => { if (e.target === confirmDialog) closeConfirm(); });

/* ── Toast notification ────────────────────────────────────────────────────── */
function showToast(msg, type = 'info') {
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  document.body.appendChild(t);
  requestAnimationFrame(() => t.classList.add('toast-visible'));
  setTimeout(() => {
    t.classList.remove('toast-visible');
    setTimeout(() => t.remove(), 300);
  }, 3000);
}

/* ── Date helpers ──────────────────────────────────────────────────────────── */
/** 'YYYY-MM-DD HH:MM' → 'DD.MM.YYYY HH:MM' for display */
function fmtDeadline(iso) {
  if (!iso) return '';
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2}))?/);
  if (!m) return iso;
  return m[4] ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}` : `${m[3]}.${m[2]}.${m[1]}`;
}

/* ── Sidebar collapse ──────────────────────────────────────────────────────── */
const sidebar   = $('#sidebar');
const mainArea  = $('.main-area');

function setSidebar(open) {
  sidebar.classList.toggle('collapsed', !open);
  mainArea?.classList.toggle('sidebar-open', open);
  localStorage.setItem('sidebarOpen', open ? '1' : '0');
}

$('#sidebar-collapse')?.addEventListener('click', () => setSidebar(sidebar?.classList.contains('collapsed')));
$('#sidebar-open')?.addEventListener('click', () => setSidebar(true));

// restore state
const savedSidebar = localStorage.getItem('sidebarOpen');
setSidebar(savedSidebar === null ? true : savedSidebar === '1');

/* ── Task Modal ────────────────────────────────────────────────────────────── */
const taskModal    = $('#task-modal');
const fId          = $('#modal-task-id');
const fTitle       = $('#f-title');
const fDesc        = $('#f-desc');
const fColumn      = $('#f-column');
const fPriority    = $('#f-priority');
const fDeadline    = $('#f-deadline');
const fTagSelect   = $('#f-tag-select');
const tagPickerSel = $('#tag-picker-selected');
const modalTitleEl = $('#modal-title-text');

/* ── Tag picker state ─────────────────────────────────────────────────────── */
let selectedTagIds = [];

function renderSelectedTags() {
  tagPickerSel.innerHTML = '';
  selectedTagIds.forEach(id => {
    const tag = TAGS.find(t => t.id === id);
    if (!tag) return;
    const pill = document.createElement('span');
    pill.className = 'tag-picker-pill';
    pill.style.setProperty('--tc', tag.color);
    pill.innerHTML = `${esc(tag.name)}<span class="tag-picker-pill-x" data-tag-id="${id}">✕</span>`;
    tagPickerSel.appendChild(pill);
  });
  // hide already-selected tags from dropdown
  $$('#f-tag-select option').forEach(opt => {
    if (!opt.value) return; // placeholder
    opt.style.display = selectedTagIds.includes(parseInt(opt.value)) ? 'none' : '';
  });
}

tagPickerSel?.addEventListener('click', e => {
  const x = e.target.closest('.tag-picker-pill-x');
  if (!x) return;
  const id = parseInt(x.dataset.tagId);
  selectedTagIds = selectedTagIds.filter(t => t !== id);
  renderSelectedTags();
});

fTagSelect?.addEventListener('change', () => {
  const val = parseInt(fTagSelect.value);
  if (!val || selectedTagIds.includes(val)) { fTagSelect.value = ''; return; }
  selectedTagIds.push(val);
  fTagSelect.value = '';
  renderSelectedTags();
});

function openTaskModal(mode, data = {}) {
  modalTitleEl.textContent = mode === 'edit' ? T.editTask : T.newTask;
  fId.value        = data.id        || '';
  fTitle.value     = data.title     || '';
  fDesc.value      = data.description || '';
  fColumn.value    = data.column_id || (COLUMNS_DATA[0]?.id || '');
  fPriority.value  = data.priority  || 'medium';
  fDeadline.value  = data.deadline  ? data.deadline.replace(' ', 'T').slice(0, 16) : '';

  // multi-tag: restore selected tags
  selectedTagIds = (data.tag_ids || []).map(Number).filter(Boolean);
  renderSelectedTags();

  taskModal.style.display = 'flex';
  fTitle.focus();
}

function closeTaskModal() { taskModal.style.display = 'none'; }

$('#modal-close')?.addEventListener('click', closeTaskModal);
$('#modal-cancel')?.addEventListener('click', closeTaskModal);
taskModal?.addEventListener('click', e => { if (e.target === taskModal) closeTaskModal(); });

$('#modal-save')?.addEventListener('click', async () => {
  const title = fTitle.value.trim();
  if (!title) { fTitle.classList.add('input-error'); fTitle.focus(); return; }
  fTitle.classList.remove('input-error');

  const body = {
    title,
    description: fDesc.value.trim(),
    column_id:   parseInt(fColumn.value),
    priority:    fPriority.value,
    deadline:    fDeadline.value ? fDeadline.value.replace('T', ' ') : null,
    tag_ids:     selectedTagIds,
    board_id:    ACTIVE_BOARD_ID,
  };

  if (fId.value) {
    const res = await fetch(`/api/tasks/${fId.value}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    if (!res.ok) return;
    replaceCard(await res.json());
  } else {
    const res = await fetch('/api/tasks', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
    });
    if (!res.ok) return;
    prependCard(await res.json());
  }
  closeTaskModal();
  updateCounts();
});

/* ── Quick-add ─────────────────────────────────────────────────────────────── */
document.addEventListener('click', e => {
  const addBtn = e.target.closest('.col-add-card-btn');
  if (addBtn) {
    openTaskModal('new', { column_id: parseInt(addBtn.dataset.colId) });
  }
});

/* ── Card edit / delete via delegation ────────────────────────────────────── */
document.addEventListener('click', async e => {
  const editBtn = e.target.closest('.btn-edit');
  const delBtn  = e.target.closest('.btn-delete');

  if (editBtn) {
    const card = editBtn.closest('.card');
    openTaskModal('edit', extractCardData(card));
    return;
  }

  if (delBtn) {
    const card  = delBtn.closest('.card');
    const id    = card.dataset.id;
    showConfirm(T.confirmDelete, async () => {
      const res = await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
      if (!res.ok) return;
      card.style.transition = 'opacity .15s, transform .15s';
      card.style.opacity    = '0';
      card.style.transform  = 'scale(.96)';
      setTimeout(() => { card.remove(); updateCounts(); }, 150);
    });
  }
});

function extractCardData(card) {
  let tagIds = [];
  try { tagIds = JSON.parse(card.dataset.tagIds || '[]'); } catch(e) {}
  return {
    id:          card.dataset.id,
    title:       card.querySelector('.card-title')?.textContent.trim() || '',
    description: card.querySelector('.card-desc')?.textContent.trim()  || '',
    column_id:   parseInt(card.dataset.colId),
    tag_ids:     tagIds,
    priority:    (() => {
      const bar = card.querySelector('.card-prio-bar');
      if (!bar) return 'medium';
      if (bar.classList.contains('prio-high'))   return 'high';
      if (bar.classList.contains('prio-low'))    return 'low';
      return 'medium';
    })(),
    deadline:    card.dataset.deadline || '',  // ISO 'YYYY-MM-DD HH:MM'
  };
}

/* ── Build card HTML ───────────────────────────────────────────────────────── */
function buildCardHTML(task) {
  const taskTags = (task.tags || []).map(t => {
    if (typeof t === 'object') return t;
    const found = TAGS.find(tg => tg.id === t);
    return found || null;
  }).filter(Boolean);
  const tagIds = taskTags.map(t => t.id);
  const prio     = task.priority || 'medium';
  const prioLabel = T.prio?.[prio] || prio;
  const dl = task.deadline ? task.deadline.replace('T', ' ') : null;
  const now = new Date().toISOString().slice(0,16).replace('T',' ');
  const overdue = dl && dl < now ? ' overdue' : '';
  const dlDisplay = dl ? fmtDeadline(dl) : '';

  const tagsHTML = taskTags.length
    ? `<div class="card-tags-row">${taskTags.map(t =>
        `<span class="tag-badge" style="--tc:${esc(t.color)}">${esc(t.name)}</span>`
      ).join('')}</div>`
    : '';

  return `
    <div class="card" data-id="${task.id}" data-col-id="${task.column_id}" data-tag-ids="${esc(JSON.stringify(tagIds))}" data-deadline="${esc(dl||'')}" draggable="true">
      <div class="card-prio-bar prio-${esc(prio)}"></div>
      <div class="card-inner">
        ${tagsHTML}
        <p class="card-title">${esc(task.title)}</p>
        ${task.description ? `<p class="card-desc">${esc(task.description)}</p>` : ''}
        <div class="card-meta-row">
          ${dl ? `<span class="card-deadline${overdue}"><svg width="11" height="11" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>${esc(dlDisplay)}</span>` : ''}
          <span class="prio-badge prio-badge-${esc(prio)}">${esc(prioLabel)}</span>
        </div>
      </div>
      <div class="card-actions">
        <button class="card-action-btn btn-edit"><svg width="13" height="13" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4z"/></svg></button>
        <button class="card-action-btn btn-delete"><svg width="13" height="13" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>
      </div>
    </div>`;
}

function prependCard(task) {
  const list = $(`#col-${task.column_id}`);
  if (!list) return;
  list.insertAdjacentHTML('afterbegin', buildCardHTML(task));
  initDrag(list.firstElementChild);
}

function replaceCard(task) {
  const old = $(`.card[data-id="${task.id}"]`);
  if (!old) return;
  const targetList = $(`#col-${task.column_id}`);
  const temp = document.createElement('div');
  temp.innerHTML = buildCardHTML(task);
  const newCard = temp.firstElementChild;
  if (old.dataset.colId !== String(task.column_id) && targetList) {
    old.remove();
    targetList.insertAdjacentHTML('afterbegin', buildCardHTML(task));
    initDrag(targetList.firstElementChild);
  } else {
    old.replaceWith(newCard);
    initDrag(newCard);
  }
  updateCounts();
}

/* ── Drag & Drop ───────────────────────────────────────────────────────────── */
let draggedCard = null;
let placeholder = null;

function initDrag(card) {
  if (!card || card.dataset.dragging === '1') return;
  card.dataset.dragging = '1';
  card.addEventListener('dragstart', onDragStart);
  card.addEventListener('dragend',   onDragEnd);
}

$$('.card').forEach(initDrag);

function onDragStart(e) {
  draggedCard = this;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  placeholder = document.createElement('div');
  placeholder.className = 'card-placeholder';
}

function onDragEnd() {
  this.classList.remove('dragging');
  placeholder?.remove();
  placeholder  = null;
  draggedCard  = null;
  $$('.cards-list').forEach(l => l.classList.remove('drag-over'));
}

$$('.cards-list').forEach(list => {
  list.addEventListener('dragover', e => {
    e.preventDefault();
    list.classList.add('drag-over');
    const after = getDragAfterElement(list, e.clientY);
    after ? list.insertBefore(placeholder, after) : list.appendChild(placeholder);
  });
  list.addEventListener('dragleave', () => list.classList.remove('drag-over'));
  list.addEventListener('drop', async e => {
    e.preventDefault();
    list.classList.remove('drag-over');
    if (!draggedCard) return;
    const newColId = parseInt(list.dataset.colId);
    const taskId   = draggedCard.dataset.id;
    list.insertBefore(draggedCard, placeholder);
    placeholder?.remove();
    draggedCard.dataset.colId = newColId;
    await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ column_id: newColId }),
    });
    updateCounts();
  });
});

function getDragAfterElement(container, y) {
  return $$('.card:not(.dragging)', container).reduce((closest, child) => {
    const box    = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    return (offset < 0 && offset > closest.offset) ? { offset, element: child } : closest;
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

/* ── Update counts ─────────────────────────────────────────────────────────── */
function updateCounts() {
  $$('.column').forEach(col => {
    const count = $$('.card', col).filter(c => c.style.display !== 'none').length;
    const badge = col.querySelector('.column-count');
    if (badge) badge.textContent = count;
  });
}

/* ── Column rename modal ───────────────────────────────────────────────────── */
const colModal     = $('#col-modal');
const colModalId   = $('#col-modal-id');
const colNameInput = $('#col-name-input');

function openColModal(id, name) {
  colModalId.value   = id;
  colNameInput.value = name;
  colModal.style.display = 'flex';
  colNameInput.focus();
}
function closeColModal() { colModal.style.display = 'none'; }

$('#col-modal-close')?.addEventListener('click', closeColModal);
$('#col-modal-cancel')?.addEventListener('click', closeColModal);
colModal?.addEventListener('click', e => { if (e.target === colModal) closeColModal(); });

$('#col-modal-save')?.addEventListener('click', async () => {
  const id   = colModalId.value;
  const name = colNameInput.value.trim();
  if (!name) return;
  const res = await fetch(`/api/columns/${id}`, {
    method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name }),
  });
  if (!res.ok) return;
  // update DOM
  const col = $(`#column-${id}`);
  if (col) {
    const titleEl = col.querySelector('.column-title');
    if (titleEl) titleEl.textContent = name;
    // update rename btn data-name
    const renameBtn = col.querySelector('.col-rename-btn');
    if (renameBtn) renameBtn.dataset.name = name;
    // update modal select option
    const opt = fColumn.querySelector(`option[value="${id}"]`);
    if (opt) opt.textContent = name;
    // update COLUMNS_DATA
    const cd = COLUMNS_DATA.find(c => c.id === parseInt(id));
    if (cd) cd.name = name;
  }
  closeColModal();
});

document.addEventListener('click', e => {
  const renBtn = e.target.closest('.col-rename-btn');
  if (renBtn) { openColModal(renBtn.dataset.id, renBtn.dataset.name); return; }
});

/* ── Column delete ─────────────────────────────────────────────────────────── */
document.addEventListener('click', async e => {
  const delBtn = e.target.closest('.col-delete-btn');
  if (!delBtn) return;
  const id = delBtn.dataset.id;
  showConfirm(T.confirmDelCol, async () => {
    const res = await fetch(`/api/columns/${id}`, { method: 'DELETE' });
    if (!res.ok) { showToast((await res.json()).error, 'error'); return; }
    const col = $(`#column-${id}`);
    if (col) col.remove();
    fColumn.querySelector(`option[value="${id}"]`)?.remove();
    const idx = COLUMNS_DATA.findIndex(c => c.id === parseInt(id));
    if (idx !== -1) COLUMNS_DATA.splice(idx, 1);
  });
});

/* ── Add column ────────────────────────────────────────────────────────────── */
const addColModal      = $('#add-col-modal');
const addColNameInput  = $('#add-col-name-input');

function showAddColumnUI() {
  addColNameInput.value = '';
  addColModal.style.display = 'flex';
  addColNameInput.focus();
}
function closeAddColModal() { addColModal.style.display = 'none'; }

$('#add-col-modal-close')?.addEventListener('click', closeAddColModal);
$('#add-col-modal-cancel')?.addEventListener('click', closeAddColModal);
addColModal?.addEventListener('click', e => { if (e.target === addColModal) closeAddColModal(); });

$('#add-col-modal-save')?.addEventListener('click', async () => {
  const name = addColNameInput.value.trim();
  if (!name) { addColNameInput.classList.add('input-error'); addColNameInput.focus(); return; }
  addColNameInput.classList.remove('input-error');
  closeAddColModal();
  await createColumn(name);
});

async function createColumn(name) {
  const res = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/columns`, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name }),
  });
  if (!res.ok) return;
  const col = await res.json();
  COLUMNS_DATA.push(col);

  // insert before phantom column
  const phantom = $('#add-column-btn-col');
  phantom.insertAdjacentHTML('beforebegin', buildColumnHTML(col));
  initColumnDrag($(`#column-${col.id}`));

  // add option to modal select
  const opt = document.createElement('option');
  opt.value       = col.id;
  opt.textContent = col.name;
  fColumn.appendChild(opt);
}

function buildColumnHTML(col) {
  const renLabel = LANG === 'ru' ? 'Переименовать' : 'Rename';
  const delLabel = LANG === 'ru' ? 'Удалить столбец' : 'Delete column';
  const addLabel = LANG === 'ru' ? 'Добавить задачу' : 'Add task';
  return `
    <div class="column" data-col-id="${col.id}" id="column-${col.id}">
      <div class="column-header">
        <div class="column-header-left">
          <span class="column-title" data-col-id="${col.id}">${esc(col.name)}</span>
          <span class="column-count badge">0</span>
        </div>
        <div class="column-header-right">
          <button class="icon-btn col-rename-btn" data-id="${col.id}" data-name="${esc(col.name)}" title="${renLabel}">
            <svg width="12" height="12" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4z"/></svg>
          </button>
          <button class="icon-btn col-delete-btn" data-id="${col.id}" title="${delLabel}">
            <svg width="12" height="12" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>
          </button>
          <button class="icon-btn col-add-card-btn" data-col-id="${col.id}" title="${addLabel}">
            <svg width="14" height="14" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-width="2.5" stroke-linecap="round" d="M12 5v14M5 12h14"/></svg>
          </button>
        </div>
      </div>
      <div class="cards-list" id="col-${col.id}" data-col-id="${col.id}"></div>
    </div>`;
}

function initColumnDrag(colEl) {
  const list = colEl.querySelector('.cards-list');
  if (!list) return;
  list.addEventListener('dragover', e => {
    e.preventDefault();
    list.classList.add('drag-over');
    const after = getDragAfterElement(list, e.clientY);
    after ? list.insertBefore(placeholder, after) : list.appendChild(placeholder);
  });
  list.addEventListener('dragleave', () => list.classList.remove('drag-over'));
  list.addEventListener('drop', async e => {
    e.preventDefault();
    list.classList.remove('drag-over');
    if (!draggedCard) return;
    const newColId = parseInt(list.dataset.colId);
    list.insertBefore(draggedCard, placeholder);
    placeholder?.remove();
    draggedCard.dataset.colId = newColId;
    await fetch(`/api/tasks/${draggedCard.dataset.id}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ column_id: newColId }),
    });
    updateCounts();
  });
}

$('#btn-add-column')?.addEventListener('click', showAddColumnUI);
$('#btn-add-column-inline')?.addEventListener('click', showAddColumnUI);
$('#btn-add-task-topbar')?.addEventListener('click', () => openTaskModal('new'));

/* ── Board modal ───────────────────────────────────────────────────────────── */
const boardModal      = $('#board-modal');
const boardModalId    = $('#board-modal-id');
const boardNameInput  = $('#board-name-input');
const boardColorVal   = $('#board-color-val');
const boardDeleteRow  = $('#board-delete-row');
const boardModalTitle = $('#board-modal-title');

function openBoardModal(mode, data = {}) {
  boardModalTitle.textContent = mode === 'edit'
    ? (LANG === 'ru' ? 'Редактировать доску' : 'Edit board')
    : (LANG === 'ru' ? 'Новая доска' : 'New board');
  boardModalId.value   = data.id    || '';
  boardNameInput.value = data.name  || '';
  boardColorVal.value  = data.color || '#5b6af0';
  boardDeleteRow.style.display = mode === 'edit' ? 'block' : 'none';
  // update swatches
  $$('.color-swatch').forEach(s => s.classList.toggle('selected', s.dataset.color === boardColorVal.value));
  boardModal.style.display = 'flex';
  boardNameInput.focus();
}
function closeBoardModal() { boardModal.style.display = 'none'; }

$('#board-modal-close')?.addEventListener('click', closeBoardModal);
$('#board-modal-cancel')?.addEventListener('click', closeBoardModal);
boardModal?.addEventListener('click', e => { if (e.target === boardModal) closeBoardModal(); });

$$('.color-swatch').forEach(btn => {
  btn.addEventListener('click', () => {
    boardColorVal.value = btn.dataset.color;
    $$('.color-swatch').forEach(s => s.classList.remove('selected'));
    btn.classList.add('selected');
  });
});

$('#btn-add-board')?.addEventListener('click', () => openBoardModal('new'));

document.addEventListener('click', e => {
  const editBtn = e.target.closest('.board-nav-edit');
  if (editBtn) {
    e.preventDefault();
    openBoardModal('edit', {
      id:    editBtn.dataset.id,
      name:  editBtn.dataset.name,
      color: editBtn.dataset.color,
    });
  }
});

$('#board-modal-save')?.addEventListener('click', async () => {
  const name  = boardNameInput.value.trim();
  const color = boardColorVal.value;
  if (!name) return;
  const id = boardModalId.value;

  if (id) {
    // update
    await fetch(`/api/boards/${id}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, color }),
    });
    // reload to reflect changes
    location.href = `/?board_id=${id}`;
  } else {
    const res = await fetch('/api/boards', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, color }),
    });
    if (!res.ok) return;
    const board = await res.json();
    location.href = `/?board_id=${board.id}`;
  }
});

$('#board-delete-btn')?.addEventListener('click', async () => {
  showConfirm(T.confirmDelBoard, async () => {
    const id = boardModalId.value;
    const res = await fetch(`/api/boards/${id}`, { method: 'DELETE' });
    if (!res.ok) { showToast((await res.json()).error, 'error'); return; }
    location.href = '/';
  });
});

/* ── Tags ──────────────────────────────────────────────────────────────────── */
$('#tag-add-form')?.addEventListener('submit', async e => {
  e.preventDefault();
  const nameInput  = $('#tag-name-input');
  const colorInput = $('#tag-color-input');
  const name = nameInput.value.trim();
  if (!name) return;
  const res = await fetch('/api/tags', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name, color: colorInput.value }),
  });
  if (!res.ok) return;
  const tag = await res.json();
  TAGS.push(tag);

  $('#tags-empty')?.remove();
  const row = document.createElement('div');
  row.className = 'tag-pill';
  row.style.setProperty('--tc', tag.color);
  row.dataset.id = tag.id;
  row.innerHTML = `<span class="tag-dot" style="background:${tag.color}"></span><span>${esc(tag.name)}</span><button class="tag-del-btn" data-id="${tag.id}">✕</button>`;
  $('#sidebar-tags-list').appendChild(row);

  const opt = document.createElement('option');
  opt.value = tag.id; opt.textContent = tag.name; opt.dataset.color = tag.color;
  fTagSelect.appendChild(opt);
  nameInput.value = '';
});

$('#sidebar-tags-list')?.addEventListener('click', async e => {
  // Delete tag button
  const btn = e.target.closest('.tag-del-btn');
  if (btn) {
    e.stopPropagation();
    const id = parseInt(btn.dataset.id);
    const res = await fetch(`/api/tags/${id}`, { method: 'DELETE' });
    if (!res.ok) return;
    btn.closest('.tag-pill').remove();
    const idx = TAGS.findIndex(t => t.id === id);
    if (idx !== -1) TAGS.splice(idx, 1);
    fTagSelect.querySelector(`option[value="${id}"]`)?.remove();
    selectedTagIds = selectedTagIds.filter(t => t !== id);
    renderSelectedTags();
    // clear filter if active tag was deleted
    if (activeFilterTagId === id) { activeFilterTagId = null; applyTagFilter(); }
    return;
  }

  // Tag filter — click on the pill itself
  const pill = e.target.closest('.tag-pill');
  if (pill) {
    const id = parseInt(pill.dataset.id);
    if (activeFilterTagId === id) {
      activeFilterTagId = null;
    } else {
      activeFilterTagId = id;
    }
    applyTagFilter();
  }
});

/* ── Tag filter logic ──────────────────────────────────────────────────────── */
let activeFilterTagId = null;
const filterChip     = $('#filter-chip');
const filterChipDot  = $('#filter-chip-dot');
const filterChipName = $('#filter-chip-name');

function applyTagFilter() {
  // highlight active pill in sidebar
  $$('#sidebar-tags-list .tag-pill').forEach(p => {
    p.classList.toggle('tag-pill-active', parseInt(p.dataset.id) === activeFilterTagId);
  });

  // update filter chip in topbar
  if (activeFilterTagId) {
    const tag = TAGS.find(t => t.id === activeFilterTagId);
    if (tag) {
      filterChipDot.style.background = tag.color;
      filterChipName.textContent = tag.name;
      filterChip.style.display = '';
    }
  } else {
    filterChip.style.display = 'none';
  }

  // show/hide cards
  $$('.card').forEach(card => {
    if (!activeFilterTagId) {
      card.style.display = '';
      return;
    }
    let tagIds = [];
    try { tagIds = JSON.parse(card.dataset.tagIds || '[]'); } catch(e) {}
    card.style.display = tagIds.includes(activeFilterTagId) ? '' : 'none';
  });

  updateCounts();
}

$('#filter-chip-clear')?.addEventListener('click', () => {
  activeFilterTagId = null;
  applyTagFilter();
});

/* ── ESC ───────────────────────────────────────────────────────────────────── */
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeTaskModal();
    closeBoardModal();
    closeColModal();
    closeAddColModal();
    closeConfirm();
  }
});

/* ── Enter key in add-col modal ────────────────────────────────────────────── */
addColNameInput?.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); $('#add-col-modal-save').click(); }
});

/* ── Share Modal ───────────────────────────────────────────────────────────── */
if (typeof IS_OWNER !== 'undefined' && IS_OWNER && !READONLY) {
  const shareModal     = $('#share-modal');
  const shareToggle    = $('#share-toggle');
  const shareLinkRow   = $('#share-link-row');
  const shareLinkInput = $('#share-link-input');
  const membersList    = $('#members-list');

  function openShareModal()  { shareModal.style.display = 'flex'; }
  function closeShareModal() { shareModal.style.display = 'none'; }

  $('#btn-share')?.addEventListener('click', openShareModal);
  $('#share-modal-close')?.addEventListener('click', closeShareModal);
  $('#share-modal-done')?.addEventListener('click', closeShareModal);
  shareModal?.addEventListener('click', e => { if (e.target === shareModal) closeShareModal(); });

  // toggle public link
  shareToggle?.addEventListener('change', async () => {
    const enable = shareToggle.checked;
    const res = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/share`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ enable }),
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data.share_url) {
      shareLinkInput.value = data.share_url;
      shareLinkRow.style.display = '';
    } else {
      shareLinkInput.value = '';
      shareLinkRow.style.display = 'none';
    }
  });

  // copy link
  $('#share-copy-btn')?.addEventListener('click', () => {
    shareLinkInput.select();
    navigator.clipboard.writeText(shareLinkInput.value).then(() => {
      showToast(LANG === 'ru' ? 'Ссылка скопирована' : 'Link copied', 'success');
    });
  });

  // invite member
  $('#invite-btn')?.addEventListener('click', async () => {
    const input = $('#invite-username');
    const username = input.value.trim();
    if (!username) return;
    const res = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/members`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ username }),
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.error || 'Error', 'error');
      return;
    }
    const member = await res.json();
    $('#members-empty')?.remove();
    const row = document.createElement('div');
    row.className = 'member-row';
    row.dataset.userId = member.user_id;
    row.innerHTML = `<span class="member-name">@${esc(member.username || 'user')}</span><button class="btn-ghost btn-sm member-remove-btn" data-user-id="${member.user_id}">${LANG === 'ru' ? 'Удалить' : 'Remove'}</button>`;
    membersList.appendChild(row);
    input.value = '';
    showToast(LANG === 'ru' ? 'Участник добавлен' : 'Member added', 'success');
  });

  // remove member
  membersList?.addEventListener('click', async e => {
    const btn = e.target.closest('.member-remove-btn');
    if (!btn) return;
    const userId = btn.dataset.userId;
    const res = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/members/${userId}`, { method: 'DELETE' });
    if (!res.ok) return;
    btn.closest('.member-row').remove();
    if (!membersList.querySelector('.member-row')) {
      const empty = document.createElement('p');
      empty.className = 'share-empty';
      empty.id = 'members-empty';
      empty.textContent = LANG === 'ru' ? 'Нет участников' : 'No members yet';
      membersList.appendChild(empty);
    }
    showToast(LANG === 'ru' ? 'Участник удалён' : 'Member removed', 'success');
  });

  // ESC for share modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && shareModal?.style.display === 'flex') closeShareModal();
  });
}
