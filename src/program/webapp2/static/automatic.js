/* WebApp2 automatic controls; the original webapp keeps its own behavior. */
const form = document.getElementById('config-form');
const configurationControls = document.getElementById('configuration-controls');
const saveDefaultButton = document.getElementById('save-default');
const svg = document.getElementById('line-visualization');
const svgNS = 'http://www.w3.org/2000/svg';
const lineMethod = {value:'point_to_point'};
const obstacleEnabled = document.getElementById('obstacle-enabled');
const totalLengthInput = document.getElementById('line.line_length');
const safeHeightInput = document.getElementById('line.high_low_distance');
const safeHeightRow = document.getElementById('safe-height-row');
const incrementInput = document.getElementById('line.increment');
const measurementCountInput = document.getElementById('measurement-count');
const spacingSourceInput = document.getElementById('spacing-source');
const autoFit = document.getElementById('auto-fit');
const simulationEnabled = document.getElementById('simulation-enabled');
const xStartInput = document.getElementById('line.x_start');
const xEndInput = document.getElementById('line.x_end');
const pointMethodNote = document.getElementById('point-method-note');
const routineFileSelect = document.createElement('select');
const acquisitionServerEnabled = document.getElementById('acquisition-server-enabled');
const runButton = document.getElementById('run-program');
const measurementFolderName = document.getElementById('measurement-folder-name');
const showTerminal = document.getElementById('show-terminal');
const createSessionFolder = document.getElementById('create-session-folder');
const ongoingMeasurement = document.getElementById('ongoing-measurement');
let pointGeometry = null;
let latestMeasurement = null;
let manualFolderName = 'Measurements_01';
let automaticFolderName = null;
const automaticFolderTemplate = 'Date/time format: YYYY-MM-DD_HH-MM-SS-ffffff';
let formDirty = false;
let operationPending = false;
let lastImportantMessage = '';
let pendingStartConfirmation = false;
let handledStartConfirmationSession = null;

function formatNumber(value) {
  return String(Number(value.toFixed(2)));
}

function setNumericInput(input, value) {
  input.value = formatNumber(value);
  input.dataset.rawValue = String(value);
  input.dataset.displayValue = input.value;
}

function inputNumber(input, fallback = 0) {
  const text = input && input.value === input.dataset.displayValue
    ? input.dataset.rawValue : input?.value;
  const value = Number.parseFloat(text);
  return Number.isFinite(value) ? value : fallback;
}

function numberValue(id, fallback = 0) {
  return inputNumber(document.getElementById(id), fallback);
}

function formatMillimetres(millimetres) {
  return `${formatNumber(millimetres)} mm`;
}

function selectedPointLength() {
  const xStart = inputNumber(xStartInput);
  const xEnd = inputNumber(xEndInput, pointGeometry?.line_length || 0);
  if (!Number.isFinite(xStart) || !Number.isFinite(xEnd)) return 0;
  return Math.max(0, xEnd - xStart);
}

function addSvg(tag, attributes, text = '') {
  const element = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text) element.textContent = text;
  svg.appendChild(element);
  return element;
}

function showImportant(message) {
  if (message !== lastImportantMessage) {
    lastImportantMessage = message;
    if (window.parent !== window && typeof window.parent.showBlockingError === 'function') {
      window.parent.showBlockingError(message);
    } else {
      window.showAppMessage(message);
    }
  }
}

function setInactiveParameter(input, inactive) {
  input.readOnly = inactive;
  input.classList.remove('optional-disabled', 'simulation-force');
  input.classList.toggle('inactive-parameter', inactive);
}

function synchronizeFields() {
  if (!autoFit.checked) {
    const count = inputNumber(measurementCountInput, NaN);
    const increment = inputNumber(incrementInput, NaN);
    const start = inputNumber(xStartInput, NaN);
    if (Number.isInteger(count) && count >= 1 && increment > 0 && Number.isFinite(start)) {
      setNumericInput(xEndInput, start + (count - 1) * increment);
    }
  }
  setInactiveParameter(xEndInput, !autoFit.checked);
  for (const key of ['target_force']) {
    const input = document.getElementById(`measurement.${key}`);
    setInactiveParameter(input, simulationEnabled.checked);
  }
  const holdDuration = document.getElementById('measurement.hold_duration');
  setInactiveParameter(holdDuration, acquisitionServerEnabled.checked);
  const method = lineMethod.value;
  const pointToPoint = method === 'point_to_point';
  pointMethodNote.classList.toggle('hidden', method !== 'point_to_point');
  totalLengthInput.readOnly = pointToPoint;
  safeHeightInput.readOnly = pointToPoint;
  safeHeightInput.disabled = pointToPoint;
  totalLengthInput.classList.toggle('optional-disabled', pointToPoint);
  safeHeightRow?.classList.toggle('optional-disabled', pointToPoint);
  if (pointToPoint && pointGeometry) {
    setNumericInput(totalLengthInput, selectedPointLength());
    setNumericInput(safeHeightInput, pointGeometry.safe_height);
  }
  for (const element of document.querySelectorAll('[data-line-method]')) {
    const active = element.dataset.lineMethod === method;
    element.classList.remove('optional-disabled');
    if (element.matches('input, select')) {
      setInactiveParameter(element, !active);
      element.disabled = !active;
      element.required = active && element.type !== 'hidden';
    }
  }
  for (const element of document.querySelectorAll('[data-optional-group="obstacle-position"]')) {
    const active = obstacleEnabled.checked;
    element.classList.remove('optional-disabled');
    if (element.matches('input, select')) {
      setInactiveParameter(element, !active);
      element.disabled = !active;
      element.required = active;
    }
  }
}

function updateMeasurementCount() {
  if (!autoFit.checked) return;
  if (!totalLengthInput || !incrementInput || !measurementCountInput) return;
  const length = lineMethod.value === 'point_to_point'
    ? selectedPointLength()
    : inputNumber(totalLengthInput);
  const increment = inputNumber(incrementInput);
  if (length > 0 && increment > 0) {
    const ratio = length / increment;
    const nearestInteger = Math.round(ratio);
    const exactDivision = Math.abs(nearestInteger * increment - length) <= 1e-9;
    const intervals = exactDivision
      ? nearestInteger
      : Math.floor(ratio);
    measurementCountInput.value = String(intervals + 1);
  }
}

function updateIncrement() {
  if (!autoFit.checked) return;
  if (!totalLengthInput || !incrementInput || !measurementCountInput) return;
  const length = lineMethod.value === 'point_to_point'
    ? selectedPointLength()
    : inputNumber(totalLengthInput);
  const count = inputNumber(measurementCountInput);
  if (length > 0 && Number.isInteger(count) && count >= 2) {
    setNumericInput(incrementInput, length / (count - 1));
  }
}

function synchronizeSpacingFromSource() {
  if (lineMethod.value === 'point_to_point' && spacingSourceInput.value === 'count') {
    updateIncrement();
  } else {
    updateMeasurementCount();
  }
}

function drawVisualization() {
  synchronizeFields();
  synchronizeSpacingFromSource();
  const translation = lineMethod.value === 'translation';
  const requestedCount = Number(measurementCountInput?.value || '1');
  const count = Number.isInteger(requestedCount) && requestedCount >= 1 ? requestedCount : 1;
  const length = translation
    ? numberValue('line.line_length')
    : selectedPointLength();
  const requestedIncrement = numberValue('line.increment');
  const increment = autoFit.checked && !translation && spacingSourceInput.value === 'count' && count >= 2 && length > 0
    ? length / (count - 1)
    : requestedIncrement;
  const origin = translation ? 0 : numberValue('line.x_start');
  const obstacleStart = numberValue('obstacle.start') - origin;
  const obstacleEnd = numberValue('obstacle.end') - origin;
  const hasObstacle = obstacleEnabled.checked && obstacleStart + origin >= 0 && obstacleEnd >= obstacleStart;
  const left = 55, right = 585, lowY = 170;
  const obstacleHeight = 62, obstacleBottomY = lowY - 3;
  const width = right - left;
  const scale = value => left + (length > 0 ? value / length : 0) * width;

  svg.replaceChildren();
  addSvg('line', {x1:left, y1:lowY, x2:length > 0 ? right : left, y2:lowY, stroke:'#17212b', 'stroke-width':5});

  if (hasObstacle && length > 0 && obstacleEnd >= 0 && obstacleStart <= length) {
    const start = Math.max(0, Math.min(length, obstacleStart));
    const end = Math.max(start, Math.min(length, obstacleEnd));
    addSvg('rect', {x:scale(start), y:obstacleBottomY-obstacleHeight, width:Math.max(2, scale(end)-scale(start)), height:obstacleHeight, rx:5, fill:'#e05252', opacity:.72});
    addSvg('text', {x:(scale(start)+scale(end))/2, y:obstacleBottomY-32, 'text-anchor':'middle', fill:'white', 'font-size':14}, 'Obstacle');
  }

  for (let index = 0; index < count; index++) {
    const position = index * increment;
    if (position > length + 1e-9) break;
    const blocked = hasObstacle && position >= obstacleStart - 1e-9 && position <= obstacleEnd + 1e-9;
    addSvg('circle', {cx:scale(position), cy:lowY, r:6, fill:blocked ? '#b85b5b' : '#2474a9', stroke:'white', 'stroke-width':2});
    addSvg('text', {x:scale(position), y:lowY+25, 'text-anchor':'middle', fill:'#334e60', 'font-size':12}, String(index + 1));
  }
  addSvg('text', {x:left, y:285, fill:'#334e60', 'font-size':14}, translation ? '0 mm' : `X Start: ${formatMillimetres(numberValue('line.x_start'))}`);
  addSvg('text', {x:right, y:285, 'text-anchor':'end', fill:'#334e60', 'font-size':14}, translation ? formatMillimetres(length) : `X End: ${formatMillimetres(numberValue('line.x_end'))}`);
  if (!translation) addSvg('text', {x:(left+right)/2, y:55, 'text-anchor':'middle', fill:'#334e60', 'font-size':14}, `Y Offset: ${formatMillimetres(numberValue('line.offset_y'))}`);

}

async function loadPointGeometry(resetLineEnd = autoFit.checked) {
  try {
    const response = await fetch('/api/configuration/geometry', {cache:'no-store'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    pointGeometry = result;
    pointMethodNote.textContent = 'Fixed: p_start_l → p_end_l';
    if (resetLineEnd && autoFit.checked && lineMethod.value === 'point_to_point' && xEndInput) {
      setNumericInput(xStartInput, 0);
      setNumericInput(xEndInput, pointGeometry.line_length);
      spacingSourceInput.value = 'increment';
    }
    synchronizeSpacingFromSource();
    drawVisualization();
  } catch (error) {
    pointGeometry = null;
    pointMethodNote.textContent = 'Fixed: p_start_l → p_end_l (not defined in selected routine file)';
    if (lineMethod.value === 'point_to_point') showImportant(error.message);
  }
}

async function loadRoutineFiles() {
  const response = await fetch('/api/configuration/routine-files', {cache:'no-store'});
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
  routineFileSelect.replaceChildren();
  for (const filename of result.files) {
    const option = document.createElement('option');
    option.value = filename;
    option.textContent = filename;
    option.selected = filename === result.default;
    routineFileSelect.appendChild(option);
  }
  await loadPointGeometry();
}

function selectedServerProfile() {
  return acquisitionServerEnabled?.checked ? 'server' : 'timer';
}

function submittedFields() {
  const fields = {};
  for (const [name, value] of new FormData(form).entries()) {
    if (!fields[name]) fields[name] = [];
    const input = form.elements.namedItem(name);
    const raw = input?.dataset.rawValue;
    fields[name].push(raw !== undefined && input.value === input.dataset.displayValue ? raw : String(value));
  }
  fields['acquisition.server_profile'] = [selectedServerProfile()];
  fields['line.auto_fit'] = [String(autoFit.checked)];
  fields['measurement.simulation'] = [String(simulationEnabled.checked)];
  fields['measurement.stop_method'] = [acquisitionServerEnabled.checked ? 'client_feedback' : 'timer'];
  return fields;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  runButton.click();
});

async function checkConfiguration(endpoint) {
  drawVisualization();
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({fields: submittedFields()}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
  formDirty = false;
  return result;
}

function confirmLineScope(message) {
  if (window.parent !== window && typeof window.parent.confirmWaypointSafety === 'function') {
    return window.parent.confirmWaypointSafety(message, 'Measurement outside the taught line');
  }
  const dialog = document.getElementById('line-scope-dialog');
  document.getElementById('line-scope-message').textContent = message;
  dialog.returnValue = 'no';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'yes'), {once:true});
    dialog.showModal();
    document.getElementById('line-scope-no').focus();
  });
}

saveDefaultButton.addEventListener('click', async () => {
  if (!await window.confirmAppAction('Replace the shared measurement defaults with the values currently shown?', 'Save measurement defaults', 'Save as default')) return;
  saveDefaultButton.disabled = true;
  try {
    await checkConfiguration('/api/configuration/default');
    await refreshMeasurement();
  } catch (error) {
    showImportant(error.message);
  } finally {
    saveDefaultButton.disabled = false;
  }
});
document.getElementById('reset-default').addEventListener('click', async () => {
  await fetch('/api/configuration/reset', {method:'POST'});
  window.location.href = `/configuration?defaults=true&server_profile=${encodeURIComponent(selectedServerProfile())}`;
});

acquisitionServerEnabled?.addEventListener('change', () => {
  formDirty = true;
  synchronizeFields();
  drawVisualization();
});
routineFileSelect.addEventListener('change', async () => {
  try {
    const response = await fetch('/api/configuration/routine-file', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({routine_file:routineFileSelect.value}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    formDirty = true;
    await loadPointGeometry(true);
    await refreshMeasurement();
  } catch (error) {
    showImportant(error.message);
  }
});
obstacleEnabled.addEventListener('change', drawVisualization);
autoFit.addEventListener('change', async () => {
  formDirty = true;
  if (autoFit.checked) await loadPointGeometry(true);
  drawVisualization();
});
simulationEnabled.addEventListener('change', () => {
  formDirty = true;
  drawVisualization();
});
form.addEventListener('input', event => {
  delete event.target.dataset.rawValue;
  delete event.target.dataset.displayValue;
  formDirty = true;
  lastImportantMessage = '';
  drawVisualization();
});
form.addEventListener('focusout', event => {
  const input = event.target;
  if (input.matches('input:not([type="hidden"])') && input.value.trim() && Number.isFinite(Number(input.value))) {
    setNumericInput(input, inputNumber(input));
    drawVisualization();
  }
});
form.addEventListener('reset', () => setTimeout(() => {
  for (const input of form.querySelectorAll('input[data-initial-raw-value]')) {
    setNumericInput(input, Number(input.dataset.initialRawValue));
  }
  drawVisualization();
}, 0));
totalLengthInput?.addEventListener('input', updateMeasurementCount);
for (const input of [xStartInput, xEndInput]) {
  input?.addEventListener('input', () => {
    synchronizeSpacingFromSource();
    drawVisualization();
  });
}
incrementInput?.addEventListener('input', () => {
  spacingSourceInput.value = 'increment';
  updateMeasurementCount();
  drawVisualization();
});
incrementInput?.addEventListener('change', drawVisualization);
measurementCountInput?.addEventListener('input', () => {
  spacingSourceInput.value = 'count';
  updateIncrement();
  drawVisualization();
});
document.getElementById('close-app').addEventListener('click', async () => {
  await fetch('/api/close', {method: 'POST'});
  document.body.innerHTML = '<main><h1>Application closed</h1><p>You can close this tab.</p></main>';
});

function completedState(point, programState, points) {
  if (point.measured === false) return 'skipped';
  if (point.data?.force_reached === true) return 'complete';
  if (point.data?.force_reached === false) return 'failed';
  const mode = programState.mode || '';
  const current = programState.active_point ?? programState.measurement_index;
  if (['measurements_done', 'end_routine', 'idle'].includes(mode)) return 'complete';
  if (typeof current !== 'number') return 'pending';
  if (point.measurement_index < current) return 'complete';
  if (point.measurement_index > current) return 'pending';
  if (programState.last_measurement_success === false) return 'failed';
  if (
    programState.last_measurement_success === true
    && programState.point_completed === true
    && !points.some(nextPoint =>
      nextPoint.measured !== false && nextPoint.measurement_index > current
    )
  ) {
    return 'complete';
  }
  const reachedPosition = programState.line_position;
  const isReached = typeof reachedPosition === 'number'
    && Math.abs(reachedPosition - point.line_position) < 1e-6;
  return isReached || point.measurement_index === current ? 'current' : 'pending';
}

function humanizePhase(mode) {
  const text = String(mode || 'running').replaceAll('_', ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function activePlanPoint(points, programState) {
  const mode = programState.mode || '';
  const current = programState.active_point ?? programState.measurement_index;
  if (['measurements_done', 'end_routine', 'idle'].includes(mode)) return null;
  if (typeof current !== 'number') return null;
  return points.find(point =>
    point.measured !== false && point.measurement_index === current
  ) || null;
}

function drawProgress(data) {
  const config = data.config;
  const plan = data.plan;
  const programState = data.program_state || {};
  const points = plan?.points || [];
  const parameters = config?.line || {};
  const pointToPoint = true;
  const origin = pointToPoint ? (parameters.x_start || 0) : 0;
  const configuredLength = pointToPoint ? parameters.x_end - origin : parameters.line_length;
  const lastPosition = points.length ? Math.max(...points.map(point => point.line_position)) : 0;
  const length = Number.isFinite(configuredLength) && configuredLength >= 0 ? configuredLength : lastPosition;
  const reachedPosition = typeof programState.line_position === 'number' ? programState.line_position : null;
  const activePoint = activePlanPoint(points, programState);
  const currentPosition = activePoint ? activePoint.line_position : reachedPosition;
  const obstacle = config?.obstacle;
  const left = 55, right = 585, lowY = 170;
  const obstacleHeight = 62, obstacleBottomY = lowY - 3;
  const scale = value => left + (length > 0 ? Math.max(0, Math.min(1, value / length)) : 0) * (right - left);

  svg.replaceChildren();
  addSvg('line', {x1:left, y1:lowY, x2:length > 0 ? right : left, y2:lowY, stroke:'#17212b', 'stroke-width':5});
  if (obstacle && obstacle.end >= obstacle.start && obstacle.end >= origin && obstacle.start <= origin + length) {
    const start = obstacle.start - origin, end = obstacle.end - origin;
    addSvg('rect', {x:scale(start), y:obstacleBottomY-obstacleHeight, width:Math.max(2, scale(end)-scale(start)), height:obstacleHeight, rx:5, fill:'#e05252', opacity:.72});
    addSvg('text', {x:(scale(start)+scale(end))/2, y:obstacleBottomY-32, 'text-anchor':'middle', fill:'white', 'font-size':14}, 'Obstacle');
  }

  let complete = 0;
  const measuredTotal = points.filter(point => point.measured !== false).length;
  for (const point of points) {
    const pointState = completedState(point, programState, points);
    if (pointState === 'complete') complete += 1;
    const colors = {pending:'#9aa9b8', current:'#1769aa', complete:'#159447', failed:'#b42318', skipped:'#b85b5b'};
    addSvg('circle', {cx:scale(point.line_position), cy:lowY, r:pointState === 'current' ? 10 : 7, fill:colors[pointState], stroke:'white', 'stroke-width':2});
    addSvg('text', {x:scale(point.line_position), y:lowY+25, 'text-anchor':'middle', fill:'#334e60', 'font-size':12}, String(point.measurement_index));
  }
  if (currentPosition !== null) {
    addSvg('text', {x:scale(currentPosition), y:lowY-20, 'text-anchor':'middle', fill:'#1769aa', 'font-size':14, 'font-weight':700}, `Current: ${formatMillimetres(origin + currentPosition)}`);
  }
  addSvg('text', {x:left, y:285, fill:'#334e60', 'font-size':14}, `X Start: ${formatMillimetres(origin)}`);
  addSvg('text', {x:right, y:285, 'text-anchor':'end', fill:'#334e60', 'font-size':14}, `X End: ${formatMillimetres(origin + length)}`);

  document.getElementById('ongoing-mode').textContent = humanizePhase(programState.mode);
  document.getElementById('ongoing-current').textContent = currentPosition === null ? '—' : formatNumber(origin + currentPosition);
  document.getElementById('ongoing-progress').textContent = `${complete} / ${measuredTotal}`;
}

function synchronizeFolderName() {
  const automatic = createSessionFolder.checked;
  measurementFolderName.readOnly = automatic;
  measurementFolderName.placeholder = automatic ? automaticFolderTemplate : 'e.g. Measurements_01';
  measurementFolderName.value = automatic
    ? automaticFolderName || '' : manualFolderName;
}

measurementFolderName.addEventListener('input', () => {
  manualFolderName = measurementFolderName.value;
});
createSessionFolder.addEventListener('change', () => {
  automaticFolderName = null;
  synchronizeFolderName();
});

function showMeasurement(data) {
  latestMeasurement = data;
  const running = data.worker.running === true;
  const controlsLocked = running || operationPending;
  configurationControls.inert = controlsLocked;
  routineFileSelect.disabled = true;
  measurementFolderName.disabled = controlsLocked;
  showTerminal.disabled = controlsLocked;
  createSessionFolder.disabled = controlsLocked;
  runButton.disabled = operationPending;
  runButton.textContent = running ? 'Stop program' : 'Start program';
  runButton.classList.toggle('danger', running);
  runButton.classList.toggle('primary', !running);
  if (running && createSessionFolder.checked && data.measurement_folder_name) {
    automaticFolderName = data.measurement_folder_name;
  }
  synchronizeFolderName();
  if (running || (data.validated && !formDirty)) drawProgress(data);
  else drawVisualization();
  maybeConfirmMovementStart(data);
}

async function maybeConfirmMovementStart(data) {
  const programState = data.program_state || {};
  const sessionKey = data.session_id || data.worker?.state_file || 'active';
  if (
    data.worker?.running !== true ||
    programState.mode !== 'waiting_for_operator_start' ||
    pendingStartConfirmation ||
    handledStartConfirmationSession === sessionKey
  ) {
    return;
  }

  pendingStartConfirmation = true;
  handledStartConfirmationSession = sessionKey;
  try {
    const confirmed = await window.confirmAppAction('Start robot motion? Confirm that the workspace is clear, tooling is secure, the robot is in Remote Control, and the emergency stop is accessible.', 'Start robot motion', 'Start program');
    if (!confirmed) {
      const stopResponse = await fetch('/api/worker/stop', {method:'POST'});
      const stopResult = await stopResponse.json();
      if (!stopResponse.ok) throw new Error(stopResult.detail || `HTTP ${stopResponse.status}`);
      return;
    }
    const response = await fetch('/api/measurement/start-movement', {method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
  } catch (error) {
    showImportant(error.message);
  } finally {
    pendingStartConfirmation = false;
    await refreshMeasurement();
  }
}

async function refreshMeasurement() {
  try {
    const response = await fetch(`/api/measurement?time=${Date.now()}`, {cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showMeasurement(await response.json());
  } catch (error) {
    showImportant(`State unavailable: ${error.message}`);
  }
}

runButton.addEventListener('click', async () => {
  const running = latestMeasurement?.worker?.running === true;
  operationPending = true;
  runButton.disabled = true;
  try {
    if (running) {
      const response = await fetch('/api/worker/stop', {method:'POST'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    } else {
      const folderSelection = {
        automatic_folder_name: createSessionFolder.checked,
        folder_name: createSessionFolder.checked ? '' : measurementFolderName.value,
      };
      if (!folderSelection.automatic_folder_name) {
        const check = await fetch('/api/measurement/folder', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(folderSelection),
        });
        const checked = await check.json();
        if (!check.ok) throw new Error(checked.detail || `HTTP ${check.status}`);
      }
      const validated = await checkConfiguration('/api/configuration/validate');
      let outsideLineConfirmed = false;
      if (validated.scope_warning) {
        outsideLineConfirmed = await confirmLineScope(validated.scope_warning);
        if (!outsideLineConfirmed) return;
      }
      const response = await fetch('/api/measurement/start', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          ...folderSelection,
          show_terminal:showTerminal.checked,
          outside_line_confirmed:outsideLineConfirmed,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
      if (folderSelection.automatic_folder_name) automaticFolderName = result.folder_name;
      synchronizeFolderName();
    }
  } catch (error) {
    showImportant(error.message);
  } finally {
    operationPending = false;
    await refreshMeasurement();
  }
});

synchronizeFolderName();
spacingSourceInput.value = 'increment';
loadRoutineFiles().catch(error => showImportant(error.message));
drawVisualization();
refreshMeasurement();
setInterval(refreshMeasurement, 500);
