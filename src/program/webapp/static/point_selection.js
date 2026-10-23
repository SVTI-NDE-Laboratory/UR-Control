/* Point selection shares original point IDs with the measurement plan. */
const pointMode = document.getElementById('points-selection-mode');
const pointFrom = document.getElementById('points-selection-from');
const pointIds = document.getElementById('points-selection-ids');
const pointDialog = document.getElementById('points-selection-dialog');
const editPoints = document.getElementById('edit-selected-points');
let customPointsInitialized = pointMode.value === 'custom' || pointIds.value !== '';

function previewPoints() {
  const count = Number(document.getElementById('measurement-count').value);
  const origin = numberValue('line.x_start');
  const increment = numberValue('line.increment');
  const start = numberValue('obstacle.start');
  const end = numberValue('obstacle.end');
  const blocked = document.getElementById('obstacle-enabled').checked;
  if (!Number.isInteger(count) || count < 1 || increment <= 0) return [];
  return Array.from({length:count}, (_, index) => {
    const x = origin + index * increment;
    return {id:index+1, x, blocked:blocked && x >= start-1e-9 && x <= end+1e-9};
  });
}

function selectedPointIds() {
  return new Set(pointIds.value.split(',').filter(Boolean).map(Number));
}

function isPreviewPointSelected(id) {
  if (pointMode.value === 'from_point') return id >= Number(pointFrom.value);
  if (pointMode.value === 'custom') return selectedPointIds().has(id);
  return true;
}

function synchronizePointControls() {
  // The browser displays endpoints; the server independently recomputes them.
  const center = numberValue('obstacle.position');
  const width = numberValue('obstacle-width');
  setNumericInput(document.getElementById('obstacle.start'), center-width/2);
  setNumericInput(document.getElementById('obstacle.end'), center+width/2);
  const summary = document.getElementById('obstacle-summary');
  summary.hidden = !document.getElementById('obstacle-enabled').checked;
  summary.textContent = `Width: ${formatNumber(width)}mm, Start: ${formatNumber(center-width/2)}mm, End: ${formatNumber(center+width/2)}mm`;
  pointFrom.hidden = pointMode.value !== 'from_point';
  editPoints.hidden = pointMode.value !== 'custom';
  const points = previewPoints();
  pointFrom.max = String(points.length);
}

function openPointSelection() {
  const points = previewPoints();
  if (!customPointsInitialized) {
    pointIds.value = points.filter(point => !point.blocked).map(point => point.id).join(',');
    customPointsInitialized = true;
  }
  const selected = selectedPointIds();
  const list = document.getElementById('points-selection-list');
  list.replaceChildren();
  for (const point of points) {
    const label = document.createElement('label');
    label.className = 'point-choice';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = String(point.id);
    checkbox.checked = !point.blocked && selected.has(point.id);
    checkbox.disabled = point.blocked;
    const text = document.createElement('span');
    text.textContent = `Point ${point.id}: X = ${formatNumber(point.x)} mm, Y = ${formatNumber(numberValue('line.offset_y'))} mm${point.blocked ? ' (obstacle)' : ''}`;
    label.append(checkbox, text);
    list.appendChild(label);
  }
  pointDialog.showModal();
}

pointMode.addEventListener('change', () => {
  if (pointMode.value === 'custom') openPointSelection();
  synchronizePointControls();
  pointIds.dispatchEvent(new Event('input', {bubbles:true}));
});
editPoints.addEventListener('click', openPointSelection);
document.getElementById('points-selection-apply').addEventListener('click', () => {
  pointIds.value = Array.from(pointDialog.querySelectorAll('input:checked:not(:disabled)'), input => input.value).join(',');
  pointDialog.close();
  pointIds.dispatchEvent(new Event('input', {bubbles:true}));
});
document.getElementById('points-selection-cancel').addEventListener('click', () => pointDialog.close());
for (const [id, checked] of [['points-select-all', true], ['points-select-none', false]]) {
  document.getElementById(id).addEventListener('click', () => {
    for (const checkbox of pointDialog.querySelectorAll('input:not(:disabled)')) checkbox.checked = checked;
  });
}

// List every point without changing the current selection.
document.getElementById('show-points-list').addEventListener('click', () => {
  synchronizeFields();
  synchronizeSpacingFromSource();
  synchronizePointControls();
  const body = document.getElementById('points-list-body');
  body.replaceChildren();
  for (const point of previewPoints()) {
    const row = document.createElement('tr');
    const status = point.blocked ? 'Obstacle' : isPreviewPointSelected(point.id) ? 'Selected' : 'Not selected';
    for (const value of [point.id, formatNumber(point.x), formatNumber(numberValue('line.offset_y')), status]) {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
  document.getElementById('points-list-dialog').showModal();
});
document.getElementById('close-points-list').addEventListener('click', () => document.getElementById('points-list-dialog').close());
