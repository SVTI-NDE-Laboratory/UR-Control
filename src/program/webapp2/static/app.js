/* Shared status polling never opens a robot connection. */
const $ = id => document.getElementById(id);
let latest = null, options = null, pending = false, flexibleLimits = null;
let activePage = 'manual';
let navigationLock = null;
const configurationFrame = $('configuration-frame');
let configurationObserver = null;
let lastWorkerError = null, statusErrorShown = false;
let waypointConfirmationPending = false, handledWaypointConfirmation = null;
const blockingErrorQueue = [];

function showBlockingError(message) {
  const dialog = $('blocking-error-dialog');
  if ((dialog.open && $('blocking-error-message').textContent === message) || blockingErrorQueue.includes(message)) return;
  blockingErrorQueue.push(message);
  showNextBlockingError();
}

function showNextBlockingError() {
  const dialog = $('blocking-error-dialog');
  if (dialog.open) return;
  if (!blockingErrorQueue.length) {
    led('error', false);
    return;
  }
  const message = blockingErrorQueue.shift();
  led('error', true);
  $('blocking-error-message').textContent = message;
  dialog.showModal();
  $('blocking-error-ok').focus();
}

$('blocking-error-dialog').addEventListener('close', showNextBlockingError);

function reportWorkerError(data) {
  if (!data.error) {
    lastWorkerError = null;
  } else {
    const key = JSON.stringify([data.worker.state_file, data.program_state.notification_id || null, data.error]);
    if (key !== lastWorkerError) {
      lastWorkerError = key;
      showBlockingError(data.error);
    }
  }
  const errorVisible = $('blocking-error-dialog').open || blockingErrorQueue.length > 0;
  led('error', errorVisible);
}

function formatNumber(value) {
  return String(Number(value.toFixed(2)));
}

function positionTuple(position, axes) {
  return `(${axes.map(axis => Number.isFinite(position[axis]) ? formatNumber(position[axis]) : '—').join(', ')})`;
}

function resizeConfiguration() {
  if (activePage !== 'automatic') return;
  const body = configurationFrame.contentDocument?.body;
  if (body) configurationFrame.style.height = Math.ceil(body.getBoundingClientRect().height) + 'px';
}

configurationFrame.addEventListener('load', () => {
  configurationObserver?.disconnect();
  const body = configurationFrame.contentDocument?.body;
  if (!body) return;
  configurationObserver = new ResizeObserver(resizeConfiguration);
  configurationObserver.observe(body);
  resizeConfiguration();
});

function showPage(path) {
  if (navigationLock && path !== '/' + navigationLock) {
    path = '/' + navigationLock;
    history.replaceState(null, '', path);
  }
  activePage = {'/manual':'manual', '/flexible':'flexible', '/automatic':'automatic', '/settings':'settings'}[path] || 'manual';
  for (const name of ['manual', 'flexible', 'automatic', 'settings']) {
    $(name + '-page').hidden = activePage !== name;
    $(name + '-tab').classList.toggle('active', activePage === name);
    if (activePage === name) $(name + '-tab').setAttribute('aria-current', 'page');
    else $(name + '-tab').removeAttribute('aria-current');
  }
  if (activePage === 'automatic' && !$('configuration-frame').getAttribute('src')) $('configuration-frame').src = '/configuration';
  if (activePage === 'automatic') requestAnimationFrame(resizeConfiguration);
  renderGeneral();
}

function lockProgramNavigation(page) {
  navigationLock = page;
  for (const name of ['manual', 'flexible', 'automatic', 'settings']) {
    const link = $(name + '-tab');
    const blocked = page !== null && name !== page;
    link.classList.toggle('navigation-disabled', blocked);
    if (blocked) {
      link.setAttribute('aria-disabled', 'true');
      link.setAttribute('tabindex', '-1');
    } else {
      link.removeAttribute('aria-disabled');
      link.removeAttribute('tabindex');
    }
  }
  if (page && activePage !== page) {
    history.replaceState(null, '', '/' + page);
    showPage('/' + page);
  }
}

function renderGeneral() {
  let status = 'Idle';
  if (latest?.worker.running) {
    if (latest.worker.kind === 'manual') {
      status = latest.program_state.action === 'routine' ? 'Manual: Perform routine' : 'Manual: Go to waypoint';
    } else if (latest.worker.kind === 'flexible') {
      const state = latest.program_state;
      const phase = state.mode === 'command_pending' ? state.action : state.mode;
      const label = {
        starting:'Entry routine', start:'Entry routine', entry_routine:'Entry routine',
        end:'Exit Routine', exit_routine:'Exit Routine', move:'Move in plane',
        force:'Apply force', force_hold:'Apply force', force_return:'Apply force',
        waiting_for_command:'Ready',
      }[phase];
      status = label ? `Flexible: ${label}` : 'Flexible';
    } else {
      if (latest.worker.kind === 'measurement') {
        const state = latest.program_state;
        const phase = state.activity || state.mode;
        const label = {
          starting:'Preparing', checking_home:'Checking Home',
          waiting_for_acquisition_client:'Waiting for acquisition',
          acquisition_client_ready:'Ready', waiting_for_operator_start:'Waiting for confirmation',
          waiting_for_start_first:'Waiting for acquisition',
          start_routine:'Entry routine', entry_routine:'Entry routine',
          obstacle_avoidance:'Obstacle Avoidance',
          end_routine:'Exit Routine', exit_routine:'Exit Routine', measurements_done:'Exit Routine',
          idle:'Finished', measurement_failed:'Measurement failed', error:'Error', unsafe_start:'Unsafe start',
        }[phase];
        const point = state.active_point ?? state.measurement_index;
        status = `Automatic: ${label || (state.in_obstacle ? 'Obstacle Avoidance'
          : point ? `Point ${point}` : 'Preparing')}`;
      }
    }
  }
  $('general').textContent = status;
}

document.querySelectorAll('nav a, #settings-tab').forEach(link => {
  const blockNavigation = event => {
    if (navigationLock && link.getAttribute('href') !== '/' + navigationLock) {
      event.preventDefault();
      return true;
    }
    return false;
  };
  link.addEventListener('auxclick', blockNavigation);
  link.addEventListener('click', event => {
    if (blockNavigation(event)) return;
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    history.pushState(null, '', link.getAttribute('href'));
    showPage(location.pathname);
  });
});
window.addEventListener('popstate', () => showPage(location.pathname));
showPage(location.pathname);

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}

async function perform(path, body) {
  if (pending) return;
  pending = true;
  if (path === '/api/flexible/start') lockProgramNavigation('flexible');
  updateControls();
  try {
    await api(path, body);
  } catch (error) {
    showBlockingError(error.message);
  } finally {
    pending = false;
    await refresh();
  }
}

function led(name, on) {
  const element = $(name + '-led');
  element.className = 'led' + (on ? name === 'error' ? ' error' : ' on' : '');
  const label = {error:'Error', moving:'Moving', force:'Force mode', server:'Acquisition'}[name];
  element.setAttribute('aria-label', `${label} ${on ? 'active' : 'inactive'}`);
}

function updateControls() {
  const busy = !latest || latest.worker.running || pending;
  document.querySelectorAll('.action').forEach(button => button.disabled = busy);
  const session = latest?.worker.running && latest.worker.kind === 'flexible';
  const ready = session && latest.program_state.mode === 'waiting_for_command' && !pending;
  $('start-flexible').disabled = busy || !flexibleLimits;
  $('end-flexible').disabled = !ready;
  $('move-plane').disabled = !ready;
  $('apply-force').disabled = !ready;
  $('stop').disabled = !latest?.worker.running || pending;
}

async function refresh() {
  try {
    latest = await api('/api/status');
    statusErrorShown = false;
    lockProgramNavigation(latest.worker.running
      ? {flexible:'flexible', measurement:'automatic'}[latest.worker.kind] || null : null);
    const f = latest.feedback, s = latest.program_state;
    renderGeneral();
    const routineName = latest.routine_file.replace(/\.json$/i, '');
    $('routine-file').textContent = routineName;
    $('routine-file').title = routineName;
    $('position').textContent = f.waypoint || '—';
    $('coordinates').textContent = f.tcp_position ? positionTuple(f.tcp_position, ['X','Y','Z']) : '—';
    reportWorkerError(latest);
    const forceActive = latest.worker.running && f.force_mode === true;
    led('moving', latest.worker.running && (forceActive || f.moving === true));
    led('force', forceActive);
    led('server', f.acquisition_connected === true);
    const xy = f.measurement_xy;
    const entryOrExit = ['starting','start_routine','end_routine','measurements_done','entry_routine','exit_routine'].includes(s.mode)
      || ['entry_routine','exit_routine','obstacle_avoidance'].includes(s.activity)
      || (s.mode === 'command_pending' && ['start','end'].includes(s.action));
    const planeText = xy && f.in_measurement_plane === true && !entryOrExit && !f.feedback_error
      ? positionTuple(xy, ['X','Y']) : '—';
    $('plane-coordinates').textContent = planeText;
    $('flexible-position').textContent = planeText;
    $('flexible-state').textContent = latest.worker.kind === 'flexible' ? (!latest.worker.running && s.mode === 'idle' ? 'Finished' : (s.mode || 'starting').replaceAll('_', ' ')) : 'Not started';
    renderWaypointChoices();
    updateControls();
    await maybeConfirmWaypoint(latest);
  } catch (error) {
    latest = null;
    ['moving','force','server'].forEach(name => led(name, false));
    if (!statusErrorShown) {
      statusErrorShown = true;
      showBlockingError(`Status unavailable: ${error.message}`);
    }
    $('position').textContent = '—';
    $('coordinates').textContent = '—';
    $('plane-coordinates').textContent = '—';
    renderGeneral();
    updateControls();
  }
}

function confirmWaypointSafety(message, title = 'Check waypoint safety') {
  const dialog = $('waypoint-safety-dialog');
  $('waypoint-safety-title').textContent = title;
  $('waypoint-safety-message').textContent = message;
  dialog.returnValue = 'no';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'yes'), {once:true});
    dialog.showModal();
    $('waypoint-safety-no').focus();
  });
}

async function maybeConfirmWaypoint(data) {
  if (!data.worker.running || data.worker.kind !== 'manual'
      || data.program_state.mode !== 'waiting_for_waypoint_confirmation'
      || waypointConfirmationPending || handledWaypointConfirmation === data.worker.state_file) return;
  waypointConfirmationPending = true;
  try {
    const proceed = await confirmWaypointSafety(data.program_state.message);
    await api('/api/manual/confirm-waypoint', {state_file:data.worker.state_file, proceed});
    handledWaypointConfirmation = data.worker.state_file;
  } catch (error) {
    showBlockingError(error.message);
  } finally {
    waypointConfirmationPending = false;
  }
}

function renderWaypointChoices() {
  if (!options) return;
  for (const item of $('waypoint').options) {
    const point = options.waypoints.find(w => w.name === item.value);
    item.disabled = !point?.linear && !point?.joint;
    item.textContent = item.value;
  }
  if ($('waypoint').selectedOptions[0]?.disabled) {
    $('waypoint').value = [...$('waypoint').options].find(o => !o.disabled)?.value || '';
  }
  const selected = options.waypoints.find(point => point.name === $('waypoint').value);
  if (!selected || (!selected.linear && !selected.joint)) return;
  for (const item of $('motion').options) {
    item.disabled = !selected[item.value === 'l' ? 'linear' : 'joint'];
  }
  if (!selected[$('motion').value === 'l' ? 'linear' : 'joint']) {
    $('motion').value = selected.linear ? 'l' : 'j';
    motionChanged();
  }
}

function motionChanged() {
  const linear = $('motion').value === 'l';
  $('speed-label').textContent = linear ? 'Speed [mm/s]' : 'Speed [rad/s]';
  $('acceleration-label').textContent = linear ? 'Acceleration [mm/s²]' : 'Acceleration [rad/s²]';
  $('speed').value = linear ? 50 : 0.05;
  $('acceleration').value = linear ? 100 : 0.1;
  $('speed').max = linear ? 150 : 0.5;
  $('acceleration').max = linear ? 150 : 0.5;
  renderWaypointChoices();
}

function waypointChanged() {
  const selected = options?.waypoints.find(point => point.name === $('waypoint').value);
  if (!selected) return;
  const taughtModes = new Set((options.transitions || [])
    .filter(step => step.target === selected.name && selected[step.motion === 'l' ? 'linear' : 'joint'])
    .map(step => step.motion));
  if (taughtModes.size === 1 && !taughtModes.has($('motion').value)) {
    $('motion').value = [...taughtModes][0];
    motionChanged();
  } else {
    renderWaypointChoices();
  }
}

$('motion').addEventListener('change', motionChanged);
$('waypoint').addEventListener('change', waypointChanged);
$('routine').addEventListener('change', () => {
  const routine = options.routines.find(r => r.name === $('routine').value);
  $('routine-first').textContent = routine?.first || '—';
});
$('waypoint-form').addEventListener('submit', event => {
  event.preventDefault();
  perform('/api/manual/start', {action:'waypoint', waypoint:$('waypoint').value, motion:$('motion').value,
    speed:Number($('speed').value), acceleration:Number($('acceleration').value)});
});
$('routine-form').addEventListener('submit', event => {
  event.preventDefault();
  perform('/api/manual/start', {action:'routine', routine:$('routine').value});
});
$('force-form').addEventListener('submit', event => {
  event.preventDefault();
  perform('/api/flexible/command', {action:'force', threshold:Number($('threshold').value), force:Number($('force').value), duration:Number($('force-duration').value), simulation:$('force-simulation').checked});
});
$('force-simulation').addEventListener('change', () => {
  for (const id of ['threshold', 'force']) {
    $(id).readOnly = $('force-simulation').checked;
    $(id).classList.toggle('simulation-force', $('force-simulation').checked);
  }
});
async function moveInPlane() {
  if (pending) return;
  if (!flexibleLimits) {
    showBlockingError('The movement range is not available. Try again once the flexible settings have loaded.');
    return;
  }
  const x = Number($('plane-x').value), y = Number($('plane-y').value);
  const outside = x < flexibleLimits.x_min || x > flexibleLimits.x_max
    || y < flexibleLimits.y_min || y > flexibleLimits.y_max;
  let confirmed = false;
  if (outside) {
    pending = true;
    updateControls();
    try {
      confirmed = await confirmWaypointSafety(
        `X = ${x} mm, Y = ${y} mm is outside the configured movement range.\n\n`
        + `X range: ${formatNumber(flexibleLimits.x_min)} to ${formatNumber(flexibleLimits.x_max)} mm\n`
        + `Y range: ${flexibleLimits.y_min} to ${flexibleLimits.y_max} mm\n\n`
        + 'This move could reach a singularity or cause unexpected movements. Are you sure you want to move forward?',
        'Check movement range');
    } catch (error) {
      showBlockingError(error.message);
      return;
    } finally {
      pending = false;
      updateControls();
    }
    if (!confirmed) return;
  }
  await perform('/api/flexible/command', {action:'move', x, y, outside_range_confirmed:confirmed});
}

$('plane-form').addEventListener('submit', event => {
  event.preventDefault();
  moveInPlane();
});
$('start-flexible').addEventListener('click', () => perform('/api/flexible/start', {}));
$('end-flexible').addEventListener('click', () => perform('/api/flexible/command', {action:'end'}));
$('stop').addEventListener('click', () => perform('/api/worker/stop', {}));
$('close').addEventListener('click', async () => {
  try { await api('/api/close', {}); document.body.textContent = 'WebApp 2.0 closed. You can close this tab.'; }
  catch(error) { showBlockingError(error.message); }
});
async function initialize() {
  try {
    options = await api('/api/manual/options');
    options.waypoints.forEach(point => $('waypoint').add(new Option(point.name, point.name)));
    options.routines.forEach(routine => $('routine').add(new Option(routine.name, routine.name)));
    motionChanged();
    $('routine').dispatchEvent(new Event('change'));
  } catch(error) { showBlockingError(error.message); }
  try {
    flexibleLimits = await api('/api/flexible/options');
  } catch(error) { showBlockingError(error.message); }
  await refresh();
  // Schedule after completion so slow requests cannot pile up.
  async function poll() {
    await refresh();
    const movingInPlane = latest?.worker.running && (latest.worker.kind === 'measurement'
      || (latest.worker.kind === 'flexible' && latest.program_state.mode === 'move'));
    setTimeout(poll, movingInPlane ? 200 : 500);
  }
  setTimeout(poll, 500);
}
initialize();
