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
const sidebar = $('#sidebar');
const sidebarOpen = $('#sidebar-open');
const sidebarCollapse = $('#sidebar-collapse');
const drawerLayout = matchMedia('(max-width: 900px)');

function setSidebar(open) {
  sidebar.classList.toggle('collapsed', !open);
  if (!open && sidebar.contains(document.activeElement)) {
    sidebarOpen?.focus({preventScroll: true});
  }
  sidebar.inert = !open;
  sidebarOpen?.setAttribute('aria-expanded', String(open));
}

sidebarCollapse?.addEventListener('click', () => setSidebar(false));
sidebarOpen?.addEventListener('click', () => {
  setSidebar(true);
  sidebarCollapse.focus({preventScroll: true});
});
$('#sidebar-backdrop').addEventListener('click', () => setSidebar(false));

setSidebar(!READONLY && !drawerLayout.matches);
drawerLayout.addEventListener('change', event => setSidebar(!READONLY && !event.matches));

/* ── Task Modal ────────────────────────────────────────────────────────────── */
const taskModal    = $('#task-modal');
const fId          = $('#modal-task-id');
const fTitle       = $('#f-title');
const fDesc        = $('#f-desc');
const fDepartment  = $('#f-department');
const fAssignee    = $('#f-assignee');
const fColumn      = $('#f-column');
const fPriority    = $('#f-priority');
const fDeadline    = $('#f-deadline');
const fTagSelect   = $('#f-tag-select');
const tagPickerSel = $('#tag-picker-selected');
const modalTitleEl = $('#modal-title-text');
const saveTaskBtn  = $('#modal-save');
const taskError    = $('#task-error');

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

function renderAssignees() {
  const editing = Boolean(fId.value);
  const department = editing ? undefined : DEPARTMENTS[fDepartment.value];
  const assignees = department ? department.staff : ASSIGNEES;
  const routed = !editing && !department
    ? new Set(Object.values(DEPARTMENTS).flatMap(({staff}) => Object.keys(staff)))
    : new Set();
  fAssignee.replaceChildren(new Option(department ? T.assignToLead : T.unassigned, ''));
  if (Object.hasOwn(assignees, CURRENT_USER_ID)) fAssignee.add(new Option(T.me, CURRENT_USER_ID));
  for (const [id, username] of Object.entries(assignees).sort(([, a], [, b]) => a.localeCompare(b, LANG))) {
    if (id !== String(CURRENT_USER_ID) && !routed.has(id)) fAssignee.add(new Option(`@${username}`, id));
  }
}

fDepartment?.addEventListener('change', renderAssignees);

function openTaskModal(data = {}) {
  const editing = Boolean(data.id);
  modalTitleEl.textContent = editing ? data.title : T.newTask;
  taskModal.toggleAttribute('data-editing', editing);
  taskError.textContent = '';
  fId.value        = data.id        || '';
  fTitle.value     = data.title     || '';
  fTitle.classList.remove('input-error');
  fDesc.value      = data.description || '';
  $('#f-department-row').hidden = editing;
  $('#f-column-row').hidden = !editing;
  $('#f-sender-row').hidden = !data.sender;
  $('#f-sender').textContent = data.sender ?? '';
  fDepartment.value = '';
  renderAssignees();
  if (data.assignee_id) fAssignee.value = data.assignee_id;
  fAssignee.dataset.original = fAssignee.value;
  fColumn.value    = data.column_id || '';
  fPriority.value  = data.priority  || 'medium';
  fDeadline.value  = data.deadline  ? data.deadline.replace(' ', 'T').slice(0, 16) : '';

  // multi-tag: restore selected tags
  selectedTagIds = (data.tag_ids || []).map(Number).filter(Boolean);
  renderSelectedTags();

  taskModal.showModal();
  taskModal.scrollTop = 0;
  if (!editing) fTitle.focus();
}

function closeTaskModal() { if (!saveTaskBtn.disabled) taskModal.close(); }

$('#modal-close')?.addEventListener('click', closeTaskModal);
$('#modal-cancel')?.addEventListener('click', closeTaskModal);
taskModal?.addEventListener('cancel', e => { if (saveTaskBtn.disabled) e.preventDefault(); });

$('#task-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  if (saveTaskBtn.disabled) return;
  taskError.textContent = '';
  const title = fTitle.value.trim();
  if (!title) { fTitle.classList.add('input-error'); fTitle.focus(); return; }
  fTitle.classList.remove('input-error');

  const editing = Boolean(fId.value);
  const body = {
    title,
    description: fDesc.value.trim(),
    priority:    fPriority.value,
    deadline:    fDeadline.value ? fDeadline.value.replace('T', ' ') : null,
    tag_ids:     selectedTagIds,
    board_id:    ACTIVE_BOARD_ID,
  };
  if (editing) {
    body.column_id = Number(fColumn.value);
    if (fAssignee.value !== fAssignee.dataset.original) {
      body.assignee_id = fAssignee.value ? Number(fAssignee.value) : null;
    }
  } else {
    if (fAssignee.value) body.assignee_id = Number(fAssignee.value);
    if (fDepartment.value) body.department_id = Number(fDepartment.value);
  }

  saveTaskBtn.disabled = true;
  try {
    const res = await fetch(editing ? `/api/tasks/${fId.value}` : '/api/tasks', {
      method: editing ? 'PATCH' : 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    if (!res.ok || res.redirected) {
      const error = await res.json().catch(() => ({}));
      taskError.textContent = error.error || T.taskSaveError;
      return;
    }
    const task = await res.json();
    if (!editing && task.board_id !== ACTIVE_BOARD_ID) {
      if (task.can_open_board) location.href = `/?board_id=${task.board_id}`;
      else {
        taskModal.close();
        showToast(T.taskRouted, 'success');
      }
      return;
    }
    taskModal.close();
    if (editing) {
      replaceCard(task)?.querySelector('.card-title').focus({preventScroll: true});
    } else {
      prependCard(task);
      updateCounts();
    }
  } catch {
    taskError.textContent = T.taskSaveError;
  } finally {
    saveTaskBtn.disabled = false;
  }
});

/* ── Card actions ─────────────────────────────────────────────────────────── */
const taskDetails = $('#task-details');
document.addEventListener('click', async e => {
  const card = e.target.closest('.card');
  if (!card) return;

  if (e.target.closest('.btn-delete')) {
    showConfirm(T.confirmDelete, async () => {
      const res = await fetch(`/api/tasks/${card.dataset.id}`, { method: 'DELETE' });
      if (!res.ok) return;
      card.style.transition = 'opacity .15s, transform .15s';
      card.style.opacity    = '0';
      card.style.transform  = 'scale(.96)';
      setTimeout(() => { card.remove(); updateCounts(); }, 150);
    });
    return;
  }

  const task = extractCardData(card);
  $('.card-title', card).focus({preventScroll: true});
  if (!READONLY) {
    openTaskModal(task);
    return;
  }
  $('#task-details-title').textContent = task.title;
  $('#task-details-description').textContent = task.description || T.noDescription;
  $('#task-details-status').textContent = $('.column-title', card.closest('.column')).textContent;
  $('#task-details-priority').textContent = T.prio[task.priority];
  $('#task-details-deadline').textContent = task.deadline ? fmtDeadline(task.deadline) : T.noDeadline;
  const tags = $$('.card-tags-row .tag-badge', card);
  $('#task-details-tags-row').hidden = !tags.length;
  $('#task-details-tags').replaceChildren(...tags.map(tag => tag.cloneNode(true)));
  taskDetails.showModal();
  taskDetails.scrollTop = 0;
});

function extractCardData(card) {
  let tagIds = [];
  try { tagIds = JSON.parse(card.dataset.tagIds || '[]'); } catch(e) {}
  return {
    id:          card.dataset.id,
    title:       card.querySelector('.card-title')?.textContent.trim() || '',
    description: card.querySelector('.card-desc')?.textContent.trim()  || '',
    sender:      card.querySelector('.card-sender strong')?.textContent,
    assignee_id: card.dataset.assigneeId || '',
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
  const assignee = ASSIGNEES[task.assignee_id];

  const tagsHTML = taskTags.length
    ? `<div class="card-tags-row">${taskTags.map(t =>
        `<span class="tag-badge" style="--tc:${esc(t.color)}">${esc(t.name)}</span>`
      ).join('')}</div>`
    : '';

  return `
    <div class="card" data-id="${task.id}" data-col-id="${task.column_id}" data-tag-ids="${esc(JSON.stringify(tagIds))}" data-deadline="${esc(dl||'')}" data-assignee-id="${task.assignee_id ?? ''}" draggable="true">
      <div class="card-prio-bar prio-${esc(prio)}"></div>
      <div class="card-inner">
        ${tagsHTML}
        <button type="button" class="card-title" aria-haspopup="dialog">${esc(task.title)}</button>
        ${task.description ? `<p class="card-desc">${esc(task.description)}</p>` : ''}
        ${task.sender_name ? `<p class="card-sender">${esc(T.taskFrom)} <strong>${esc(task.sender_name)}</strong></p>` : ''}
        <div class="card-meta-row">
          ${assignee ? `<span class="card-assignee">${esc(T.taskTo)} @${esc(assignee)}</span>` : ''}
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
    targetList.prepend(newCard);
  } else {
    old.replaceWith(newCard);
  }
  initDrag(newCard);
  updateCounts();
  return newCard;
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

$$('.card[draggable="true"]').forEach(initDrag);

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

function initCardDrop(list) {
  list.addEventListener('dragover', e => {
    if (!draggedCard || !placeholder) return;
    e.preventDefault();
    list.classList.add('drag-over');
    const after = getDragAfterElement(list, e.clientY);
    after ? list.insertBefore(placeholder, after) : list.appendChild(placeholder);
  });
  list.addEventListener('dragleave', () => list.classList.remove('drag-over'));
  list.addEventListener('drop', async e => {
    if (!draggedCard) return;
    e.preventDefault();
    list.classList.remove('drag-over');
    const newColId = parseInt(list.dataset.colId);
    const taskId   = draggedCard.dataset.id;
    list.insertBefore(draggedCard, placeholder?.parentElement === list ? placeholder : null);
    placeholder?.remove();
    draggedCard.dataset.colId = newColId;
    await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ column_id: newColId }),
    });
    updateCounts();
  });
}

if (!READONLY) $$('.cards-list').forEach(initCardDrop);

function getDragAfterElement(container, y) {
  return $$('.card:not(.dragging)', container).reduce((closest, child) => {
    const box    = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    return (offset < 0 && offset > closest.offset) ? { offset, element: child } : closest;
  }, { offset: Number.NEGATIVE_INFINITY }).element;
}

/* ── Column order ──────────────────────────────────────────────────────────── */
const columnBoard = $('#board');
const columnScroller = columnBoard.parentElement;
const addColumnPlaceholder = $('#add-column-btn-col');
let columnDrag = null;
let savingColumnOrder = false;

function boardColumns() {
  return $$('.column[data-col-id]', columnBoard);
}

async function saveColumnMove(column, before) {
  if (savingColumnOrder) return;
  const columns = boardColumns();
  const reordered = columns.filter(item => item !== column);
  const index = before ? reordered.indexOf(before) : reordered.length;
  if (index < 0 || columns.indexOf(column) === index) return;
  reordered.splice(index, 0, column);
  const columnIds = reordered.map(item => Number(item.dataset.colId));

  savingColumnOrder = true;
  try {
    const response = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/columns/order`, {
      method: 'PUT',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        previous_column_ids: columns.map(item => Number(item.dataset.colId)),
        column_ids: columnIds,
      }),
    });
    if (!response.ok || response.redirected) {
      showToast(response.status === 409 ? T.columnOrderConflict : T.columnOrderError, 'error');
      return;
    }

    const active = document.activeElement;
    columnBoard.insertBefore(column, before || addColumnPlaceholder);
    if (column.contains(active)) active.focus({preventScroll: true});
    column.scrollIntoView({block: 'nearest', inline: 'nearest'});

    const positions = new Map(columnIds.map((id, position) => [id, position]));
    COLUMNS_DATA.sort((a, b) => positions.get(a.id) - positions.get(b.id));
    COLUMNS_DATA.forEach(item => { item.position = positions.get(item.id); });
    const selected = fColumn.value;
    for (const id of columnIds) {
      const option = fColumn.querySelector(`option[value="${id}"]`);
      if (option) fColumn.appendChild(option);
    }
    fColumn.value = selected;
  } catch {
    showToast(T.columnOrderError, 'error');
  } finally {
    savingColumnOrder = false;
  }
}

function markColumnTarget() {
  const {column, x} = columnDrag;
  const target = boardColumns().find(item => {
    if (item === column) return false;
    const box = item.getBoundingClientRect();
    return x < box.left + box.width / 2;
  }) || addColumnPlaceholder;
  if (target === columnDrag.target) return;
  columnDrag.target?.classList.remove('column-drop-before');
  target.classList.add('column-drop-before');
  columnDrag.target = target;
}

function scrollColumnDrag() {
  if (!columnDrag?.active) return;
  const box = columnScroller.getBoundingClientRect();
  const scroll = columnScroller.scrollLeft;
  if (columnDrag.x < box.left + 44) columnScroller.scrollLeft -= 12;
  if (columnDrag.x > box.right - 44) columnScroller.scrollLeft += 12;
  if (columnScroller.scrollLeft !== scroll) markColumnTarget();
  columnDrag.frame = requestAnimationFrame(scrollColumnDrag);
}

columnBoard.addEventListener('pointerdown', e => {
  const handle = e.target.closest('.column-move-handle');
  if (!handle || e.button !== 0 || columnDrag || savingColumnOrder || boardColumns().length < 2) return;
  columnDrag = {pointerId: e.pointerId, column: handle.closest('.column'), startX: e.clientX};
  handle.setPointerCapture(e.pointerId);
});

columnBoard.addEventListener('pointermove', e => {
  if (columnDrag?.pointerId !== e.pointerId) return;
  columnDrag.x = e.clientX;
  if (!columnDrag.active) {
    if (Math.abs(e.clientX - columnDrag.startX) < 6) return;
    columnDrag.active = true;
    columnDrag.column.classList.add('column-moving');
    columnDrag.frame = requestAnimationFrame(scrollColumnDrag);
  }
  markColumnTarget();
});

function finishColumnDrag(e) {
  if (columnDrag?.pointerId !== e.pointerId) return;
  const {column, active, target, frame} = columnDrag;
  columnDrag = null;
  cancelAnimationFrame(frame);
  column.classList.remove('column-moving');
  target?.classList.remove('column-drop-before');
  const box = columnScroller.getBoundingClientRect();
  if (active && e.type === 'pointerup' &&
      e.clientX >= box.left && e.clientX <= box.right &&
      e.clientY >= box.top && e.clientY <= box.bottom) {
    saveColumnMove(column, target === addColumnPlaceholder ? null : target);
  }
}

['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => {
  columnBoard.addEventListener(type, finishColumnDrag);
});

columnBoard.addEventListener('keydown', e => {
  const handle = e.target.closest('.column-move-handle');
  if (!handle || !['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  if (savingColumnOrder || columnDrag) return;
  const column = handle.closest('.column');
  const columns = boardColumns();
  const index = columns.indexOf(column);
  const direction = e.key === 'ArrowLeft' ? -1 : 1;
  const next = index + direction;
  if (next < 0 || next >= columns.length) return;
  saveColumnMove(column, direction < 0 ? columns[next] : (columns[next + 1] || null));
});

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
    if (savingColumnOrder || columnDrag) return;
    savingColumnOrder = true;
    try {
      const res = await fetch(`/api/columns/${id}`, { method: 'DELETE' });
      if (!res.ok) { showToast((await res.json()).error, 'error'); return; }
      const col = $(`#column-${id}`);
      if (col) col.remove();
      fColumn.querySelector(`option[value="${id}"]`)?.remove();
      const idx = COLUMNS_DATA.findIndex(c => c.id === parseInt(id));
      if (idx !== -1) COLUMNS_DATA.splice(idx, 1);
    } finally {
      savingColumnOrder = false;
    }
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
  if (savingColumnOrder || columnDrag) return;
  savingColumnOrder = true;
  try {
    const res = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/columns`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name }),
    });
    if (!res.ok) return;
    const col = await res.json();
    COLUMNS_DATA.push(col);

    addColumnPlaceholder.insertAdjacentHTML('beforebegin', buildColumnHTML(col));
    initCardDrop($(`#col-${col.id}`));
    fColumn.appendChild(new Option(col.name, col.id));
  } finally {
    savingColumnOrder = false;
  }
}

function buildColumnHTML(col) {
  const renLabel = LANG === 'ru' ? 'Переименовать' : 'Rename';
  const delLabel = LANG === 'ru' ? 'Удалить столбец' : 'Delete column';
  return `
    <div class="column" data-col-id="${col.id}" id="column-${col.id}">
      <div class="column-header">
        <div class="column-header-left">
          ${COLUMN_MOVE_HANDLE}
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
        </div>
      </div>
      <div class="cards-list" id="col-${col.id}" data-col-id="${col.id}"></div>
    </div>`;
}

$('#btn-add-column')?.addEventListener('click', showAddColumnUI);
$('#btn-add-column-inline')?.addEventListener('click', showAddColumnUI);
$('#btn-add-task-topbar')?.addEventListener('click', () => openTaskModal());

/* ── Column templates ─────────────────────────────────────────────────────── */
const templateModal = $('#column-template-modal');
const boardTemplate = $('#board-template');

if (templateModal) {
  const select = $('#column-template-select');
  const name = $('#column-template-name');
  const names = $('#column-template-names');
  const submit = $('#column-template-submit');

  function renderTemplate() {
    const custom = select.value === 'custom';
    $('#column-template-name-row').hidden = !custom;
    $('#column-template-note').hidden = custom;
    $('#column-template-custom-note').hidden = !custom;
    name.required = custom;
    names.readOnly = !custom;
    names.value = (custom ? COLUMNS_DATA.map(col => col.name) : COLUMN_TEMPLATES[select.value].columns).join('\n');
    submit.textContent = custom ? T.saveTemplate : T.applyTemplate;
  }

  $('#btn-column-templates').addEventListener('click', () => {
    closeAddColModal();
    renderTemplate();
    templateModal.style.display = 'flex';
    select.focus();
  });
  select.addEventListener('change', renderTemplate);
  $('#column-template-close').addEventListener('click', () => {
    templateModal.style.display = 'none';
    $('#btn-add-column').focus();
  });
  templateModal.addEventListener('click', event => {
    if (event.target === templateModal) $('#column-template-close').click();
  });

  $('#column-template-form').addEventListener('submit', async event => {
    event.preventDefault();
    const custom = select.value === 'custom';
    if (submit.disabled || savingColumnOrder || columnDrag) return;
    const body = custom
      ? {name: name.value.trim(), columns: names.value.split('\n').map(col => col.trim()).filter(Boolean)}
      : {template_id: select.value};
    submit.disabled = true;
    select.disabled = true;
    try {
      const response = await fetch(custom ? '/api/column-templates' : `/api/boards/${ACTIVE_BOARD_ID}/column-template`, {
        method: custom ? 'POST' : 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body),
      });
      if (response.redirected) throw new Error();
      const data = await response.json();
      if (!response.ok) {
        showToast({invalid_template: T.templateInvalid, template_name_taken: T.templateNameTaken}[data.error] || T.templateError, 'error');
      } else if (custom) {
        COLUMN_TEMPLATES[data.id] = data;
        select.add(new Option(data.name, data.id), select.options.length - 1);
        boardTemplate.add(new Option(data.name, data.id));
        select.value = data.id;
        name.value = '';
        renderTemplate();
        showToast(T.templateSaved, 'success');
      } else {
        location.href = `/?board_id=${ACTIVE_BOARD_ID}`;
      }
    } catch {
      showToast(T.templateError, 'error');
    } finally {
      submit.disabled = false;
      select.disabled = false;
    }
  });
}

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
  boardTemplate.value = '';
  $('#board-template-row').style.display = mode === 'edit' ? 'none' : '';
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
      body: JSON.stringify({ name, color, template_id: boardTemplate.value }),
    });
    if (!res.ok) { showToast(T.templateError, 'error'); return; }
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
  const tag = TAGS.find(t => t.id === activeFilterTagId);
  filterChip.hidden = !tag;
  if (tag) {
    filterChipDot.style.background = tag.color;
    filterChipName.textContent = tag.name;
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
  if (e.key === 'Escape' && !taskModal?.open && !taskDetails?.open) {
    if (drawerLayout.matches && !sidebar.inert) setSidebar(false);
    closeBoardModal();
    closeColModal();
    closeAddColModal();
    if (templateModal?.style.display === 'flex') $('#column-template-close').click();
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
  const departmentLead = $('#department-lead');
  const departmentStaff = $('#department-staff');

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
    const usernameLabel = member.username || `#${member.user_id}`;
    ASSIGNEES[member.user_id] = usernameLabel;
    const label = `@${usernameLabel}`;
    departmentLead.add(new Option(label, member.user_id));
    departmentStaff.insertAdjacentHTML('beforeend', `<label class="department-staff-item"><input type="checkbox" name="staff_ids" value="${member.user_id}"/><span>${esc(label)}</span></label>`);
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
    if (departmentLead.dataset.saved === userId) {
      location.reload();
      return;
    }
    btn.closest('.member-row').remove();
    delete ASSIGNEES[userId];
    delete DEPARTMENTS[ACTIVE_BOARD_ID]?.staff[userId];
    departmentLead.querySelector(`option[value="${userId}"]`)?.remove();
    departmentStaff.querySelector(`input[value="${userId}"]`)?.closest('label').remove();
    $$(`.card[data-assignee-id="${userId}"]`).forEach(card => {
      card.dataset.assigneeId = '';
      card.querySelector('.card-assignee')?.remove();
    });
    if (!membersList.querySelector('.member-row')) {
      const empty = document.createElement('p');
      empty.className = 'share-empty';
      empty.id = 'members-empty';
      empty.textContent = LANG === 'ru' ? 'Нет участников' : 'No members yet';
      membersList.appendChild(empty);
    }
    showToast(LANG === 'ru' ? 'Участник удалён' : 'Member removed', 'success');
  });

  $('#department-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const button = event.submitter;
    button.disabled = true;
    try {
      const response = await fetch(`/api/boards/${ACTIVE_BOARD_ID}/department`, {
        method: 'PUT', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({lead_id: departmentLead.value ? Number(departmentLead.value) : null, staff_ids: form.getAll('staff_ids').map(Number)}),
      });
      if (!response.ok || response.redirected) throw new Error();
      location.reload();
    } catch {
      showToast(T.departmentError, 'error');
    } finally {
      button.disabled = false;
    }
  });

  // ESC for share modal
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && shareModal?.style.display === 'flex') closeShareModal();
  });
}
