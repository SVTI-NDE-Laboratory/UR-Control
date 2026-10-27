/* Run with Node, or supply appSource in a JS runtime. */
(() => {
  const fs = typeof require === 'function' ? require('fs') : null;
  const source = fs ? fs.readFileSync(`${__dirname}/../src/program/webapp2/static/app.js`, 'utf8') : globalThis.appSource;
  new Function(source);
  const helper = source.slice(source.indexOf('function renderFeedbackIndicators('), source.indexOf('\nasync function refresh()'));
  const elements = {}, indicators = {};
  const element = id => elements[id] ||= {textContent:''};
  const render = new Function('$', 'led', 'positionTuple', `${helper}; return renderFeedbackIndicators;`)(
    element, (name, enabled) => indicators[name] = enabled,
    (xy, axes) => `(${axes.map(axis => xy[axis]).join(', ')})`);
  let assertions = 0;
  function assert(condition, message) {
    if (!condition) throw new Error(message);
    assertions++;
  }
  const feedback = {force_mode:true, moving:false, in_measurement_plane:false, measurement_xy:{X:1200, Y:800}};
  render(feedback, {mode:'force_hold'}, true);
  assert(elements['plane-coordinates'].textContent === '(1200, 800)', 'Plane values stay visible while force moves the TCP off the plane');
  assert(elements['flexible-position'].textContent === '(1200, 800)', 'Flexible status keeps the same wall values');
  assert(indicators.force === true && indicators.moving === false, 'Stationary force only enables the Force LED');
  render({...feedback, moving:true}, {mode:'force'}, true);
  assert(indicators.force === true && indicators.moving === true, 'Actual motion during force enables both LEDs');
  render({...feedback, force_mode:false}, {mode:'waiting_for_command'}, true);
  assert(elements['plane-coordinates'].textContent !== '(1200, 800)', 'An off-plane pose remains hidden outside force mode');
  render(feedback, {mode:'entry_routine'}, true);
  assert(elements['plane-coordinates'].textContent !== '(1200, 800)', 'Entry and exit still hide plane coordinates');
  render({...feedback, feedback_error:'RTDE unavailable'}, {mode:'force'}, true);
  assert(elements['plane-coordinates'].textContent !== '(1200, 800)', 'Feedback errors do not show stale force coordinates');
  render({...feedback, force_mode:false, in_measurement_plane:true}, {mode:'waiting_for_command'}, true);
  assert(elements['plane-coordinates'].textContent === '(1200, 800)', 'Normal plane coordinates remain visible');
  globalThis.statusDisplayTestResult = `${assertions} status display checks passed.`;
  if (typeof console !== 'undefined') console.log(globalThis.statusDisplayTestResult);
})();
