function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}
const csrftoken = getCookie('csrftoken');

// --- Drag source: nomor tanding chips ---
document.querySelectorAll('.nt-chip').forEach(chip => {
  chip.addEventListener('dragstart', e => {
    e.dataTransfer.setData('nt-id', chip.dataset.ntId);
    e.dataTransfer.setData('nt-name', chip.dataset.ntName);
  });
});

// --- Drop target: cells ---
document.getElementById('timetable-body').addEventListener('dragover', e => {
  if (e.target.closest('.tt-cell')) e.preventDefault();
});

document.getElementById('timetable-body').addEventListener('drop', e => {
  const cell = e.target.closest('.tt-cell');
  if (!cell) return;
  e.preventDefault();

  const ntId = e.dataTransfer.getData('nt-id');
  const ntName = e.dataTransfer.getData('nt-name');
  if (!ntId) return;

  cell.dataset.ntId = ntId;
  cell.querySelector('.cell-content').textContent = ntName;
});

document.getElementById('timetable-body').addEventListener('input', e => {
  if (e.target.classList.contains('cell-content')) {
    delete e.target.closest('.tt-cell').dataset.ntId;
  }
});

// --- Add slot row: builds one <td> per CURRENT tatami column ---
function buildSlotRowCells() {
  let html = `<td style="border:1px solid #ccc; padding:6px;"><input type="text" class="time-label-input" placeholder="08:00 - 08:30" style="width:100%; border:none;"></td>`;
  document.querySelectorAll('#timetable-header-row th[data-tatami-id]').forEach(th => {
    html += `<td class="tt-cell" data-tatami-id="${th.dataset.tatamiId}" style="border:1px solid #ccc; padding:6px; min-width:140px; height:44px; vertical-align:top;">
      <div class="cell-content" contenteditable="true" style="min-height:24px; outline:none;"></div>
    </td>`;
  });
  html += `<td style="border:1px solid #ccc;"><button class="remove-row-btn" type="button">✕</button></td>`;
  return html;
}

document.getElementById('add-slot-row-btn').addEventListener('click', () => {
  const tr = document.createElement('tr');
  tr.className = 'tt-row';
  tr.dataset.rowType = 'slot';
  tr.innerHTML = buildSlotRowCells();
  document.getElementById('timetable-body').appendChild(tr);
});

document.getElementById('add-label-row-btn').addEventListener('click', () => {
  const tatamiCount = document.querySelectorAll('#timetable-header-row th[data-tatami-id]').length;
  const tr = document.createElement('tr');
  tr.className = 'tt-row';
  tr.dataset.rowType = 'label';
  tr.innerHTML = `
    <td class="label-cell" colspan="${tatamiCount + 1}" style="border:1px solid #ccc; padding:6px; background:#f5f5f5; font-weight:bold; text-align:center;">
      <input type="text" class="label-text-input" placeholder="ISHOMA / Break" style="width:90%; text-align:center; border:none; background:transparent; font-weight:bold;">
    </td>
    <td style="border:1px solid #ccc;"><button class="remove-row-btn" type="button">✕</button></td>
  `;
  document.getElementById('timetable-body').appendChild(tr);
});

document.getElementById('timetable-body').addEventListener('click', e => {
  if (e.target.classList.contains('remove-row-btn')) {
    e.target.closest('tr').remove();
  }
});

// --- Add tatami column ---
document.getElementById('add-tatami-btn').addEventListener('click', () => {
  const name = prompt('Nama / nomor tatami baru:');
  if (!name) return;

  fetch(ADD_TATAMI_URL, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrftoken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ tatami_number: name }),
  })
    .then(res => res.json())
    .then(data => {
      if (!data.success) {
        alert('Gagal menambah tatami: ' + (data.message || ''));
        return;
      }
      addTatamiColumn(data.id, data.tatami_number);
    })
    .catch(() => alert('Gagal menambah tatami.'));
});

function addTatamiColumn(tatamiId, tatamiName) {
  // 1. Insert header cell before the last (blank/remove-button) <th>
  const headerRow = document.getElementById('timetable-header-row');
  const th = document.createElement('th');
  th.style.cssText = 'border:1px solid #ccc; padding:6px;';
  th.dataset.tatamiId = tatamiId;
  th.textContent = tatamiName;
  headerRow.insertBefore(th, headerRow.lastElementChild);

  // 2. Insert a matching cell into every existing SLOT row (label rows use colspan, skip them)
  document.querySelectorAll('#timetable-body tr.tt-row').forEach(tr => {
    if (tr.dataset.rowType !== 'slot') {
      // widen the label row's colspan by 1 to keep it spanning the full width
      const labelCell = tr.querySelector('.label-cell');
      if (labelCell) labelCell.colSpan = parseInt(labelCell.colSpan, 10) + 1;
      return;
    }
    const td = document.createElement('td');
    td.className = 'tt-cell';
    td.dataset.tatamiId = tatamiId;
    td.style.cssText = 'border:1px solid #ccc; padding:6px; min-width:140px; height:44px; vertical-align:top;';
    td.innerHTML = `<div class="cell-content" contenteditable="true" style="min-height:24px; outline:none;"></div>`;
    tr.insertBefore(td, tr.lastElementChild);
  });
}

// --- Save ---
document.getElementById('save-timetable-btn').addEventListener('click', () => {
  const statusEl = document.getElementById('save-status');
  statusEl.textContent = ' Menyimpan...';

  const rows = [];
  document.querySelectorAll('#timetable-body .tt-row').forEach(tr => {
    if (tr.dataset.rowType === 'label') {
      rows.push({ row_type: 'label', label_text: tr.querySelector('.label-text-input').value });
    } else {
      const cells = [];
      tr.querySelectorAll('.tt-cell').forEach(td => {
        const ntId = td.dataset.ntId || null;
        const text = td.querySelector('.cell-content').textContent.trim();
        if (ntId || text) {
          cells.push({ tatami_id: td.dataset.tatamiId, nomor_tanding_id: ntId, custom_text: ntId ? '' : text });
        }
      });
      rows.push({ row_type: 'slot', time_label: tr.querySelector('.time-label-input').value, cells });
    }
  });

  fetch(SAVE_URL, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrftoken, 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows }),
  })
    .then(res => res.json())
    .then(data => { statusEl.textContent = data.success ? ' ✅ Tersimpan' : ' ❌ Gagal'; })
    .catch(() => { statusEl.textContent = ' ❌ Gagal'; });
});