/* Run with Node, or supply visualizationSource/automaticSource in a JS runtime. */
(() => {
  const fs = typeof require === 'function' ? require('fs') : null;
  const source = fs ? fs.readFileSync(`${__dirname}/../src/program/webapp2/static/measurement_visualization.js`, 'utf8') : globalThis.visualizationSource;
  const automatic = fs ? fs.readFileSync(`${__dirname}/../src/program/webapp2/static/automatic.js`, 'utf8') : globalThis.automaticSource;
  new Function(source)();
  new Function(automatic);
  const view = MeasurementVisualization;
  let assertions = 0;
  function assert(condition, message) {
    if (!condition) throw new Error(message);
    assertions++;
  }

  // A long line shows its first 21 points and never compresses all points into one window.
  for (const count of [1, 21, 22, 100, 1000]) {
    const length = Math.max(0, count - 1) * 100;
    const layout = view.layout(count, length, 100);
    assert(count > 21 ? layout.width > 640 : layout.width === 640, `Width for ${count} points`);
    const windows = [0, 15, 31, Math.max(0, layout.width - 640)];
    for (const start of windows) {
      const visible = Array.from({length:count}, (_, index) => layout.scale(index * 100))
        .filter(x => x >= start && x <= start + 640).length;
      assert(visible <= 21, `No more than 21 points at scroll ${start}`);
      if (count > 21 && start === 0) assert(visible === 21, 'First window contains 21 points');
    }
  }

  // Scrolling follows distant points, leaves visible ones alone, and respects both ends.
  assert(view.scrollTarget(900, 640, 2000, 0) > 0, 'Follow a point to the right');
  assert(view.scrollTarget(100, 640, 2000, 0) === 0, 'Keep an already visible point');
  assert(view.scrollTarget(30, 640, 2000, 800) === 0, 'Follow back to the start');
  assert(view.scrollTarget(1990, 640, 2000, 0) === 1360, 'Clamp to the final window');

  const point = {point_number:5, scheduled:true, data:{status:null}};
  assert(view.pointState(point, {mode:'idle'}) === 'pending', 'Idle unmeasured points remain blue');
  assert(view.pointState(point, {mode:'error', active_point:9}) === 'pending', 'Stopping does not complete unmeasured points');
  assert(view.pointState({...point, data:{status:'measured'}}, {}) === 'complete', 'Successful results are green');
  assert(view.pointState({...point, data:{status:'simulation'}}, {}) === 'complete', 'Simulation results are green');
  assert(view.pointState({...point, scheduled:false, skip_reason:'not_selected'}, {}) === 'excluded', 'Unselected points are grey');
  assert(view.pointState({...point, scheduled:false, skip_reason:'obstacle'}, {}) === 'skipped', 'Obstacle points are red');
  assert(view.pointState(point, {mode:'measuring', active_point:5}) === 'current', 'Identify the current point');
  assert(view.pointState(point, {mode:'measuring', active_point:5, point_completed:true, last_measurement_success:true}) === 'complete', 'Completed current points turn green immediately');
  assert(view.colors.pending === view.colors.current && view.colors.pending !== view.colors.excluded, 'Pending and current are blue, separate from grey exclusions');

  // Exercise the actual renderer with a small DOM adapter, including its summary and obstacle geometry.
  const elements = {};
  const document = {getElementById:id => elements[id] ||= {textContent:'', hidden:false}};
  const svg = {style:{}, setAttribute() {}, replaceChildren() { nodes.length = 0; }};
  const viewport = {clientWidth:640, scrollLeft:0};
  const nodes = [];
  const addSvg = (tag, attributes, text = '') => nodes.push({tag, attributes, text});
  const renderSource = automatic.slice(automatic.indexOf('function renderLine('), automatic.indexOf('\nfunction drawVisualization'));
  const render = new Function('document', 'svg', 'lineViewport', 'lineView', 'formatNumber', 'formatMillimetres', 'addSvg',
    `let followedPoint = null; ${renderSource}; return renderLine;`)(document, svg, viewport, view, String, value => `${value} mm`, addSvg);
  const points = Array.from({length:100}, (_, index) => ({id:index + 1, position:index * 100, state:'pending'}));
  points[3].state = 'skipped';
  points[4].state = 'excluded';
  const parameters = {points, length:9900, increment:100, origin:1200, end:11100, y:600,
    obstacle:{start:300, end:500}, activePoint:points[59], followKey:'run:60'};
  render(parameters);
  assert(elements['summary-line'].textContent === '(1200, 600) → (11100, 600) mm', 'Summary shows both endpoints in wall coordinates');
  assert(elements['summary-point-count'].textContent === '98 (2 discarded)', 'Count excludes obstacle and unselected points');
  assert(elements['line-scroll-note'].hidden === false, 'Explain scrolling for a long line');
  const rectangle = nodes.find(node => node.tag === 'rect').attributes;
  const lineY = nodes.find(node => node.tag === 'line').attributes.y1;
  assert(rectangle.y < lineY && rectangle.y + rectangle.height > lineY, 'Obstacle extends above and below the line');
  assert(nodes.findIndex(node => node.tag === 'rect') < nodes.findIndex(node => node.tag === 'line'), 'Obstacle is behind the line');
  assert(nodes.find(node => node.tag === 'circle' && node.attributes.cx === view.layout(100, 9900, 100).scale(300)).attributes.fill === rectangle.fill, 'Obstacle points match the background red');
  assert(nodes.find(node => node.tag === 'text' && node.text === '60').attributes['font-weight'] === 700, 'Current point number is bold');
  assert(nodes.some(node => node.tag === 'text' && node.text === '7100 mm'), 'Active point shows its wall position without a Current prefix');
  assert(nodes.find(node => node.tag === 'text' && node.text === '59').attributes['font-weight'] === 400, 'Other point numbers remain regular');
  assert(viewport.scrollLeft > 0, 'Renderer follows the current point');
  viewport.scrollLeft = 0;
  render(parameters);
  assert(viewport.scrollLeft === 0, 'Polling preserves manual scrolling while the same point is active');
  render({...parameters, activePoint:points[60], followKey:'run:61'});
  assert(viewport.scrollLeft > 0, 'Advance the view when the active point changes');
  globalThis.visualizationTestResult = `${assertions} visualization checks passed.`;
  if (typeof console !== 'undefined') console.log(globalThis.visualizationTestResult);
})();
