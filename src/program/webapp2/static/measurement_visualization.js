/* Geometry and progress rules shared by the preview and running line view. */
globalThis.MeasurementVisualization = (() => {
  const colors = {pending:'#2474a9', current:'#2474a9', complete:'#159447',
    failed:'#b42318', skipped:'#eca3a3', excluded:'#9aa9b8'};

  function layout(count, length, increment) {
    const left = count > 21 ? 10 : 55;
    // Keep 21 points within a viewport; a 22nd point is more than 640 units away.
    const plotWidth = count > 21 && increment > 0 && length > 0
      ? length / increment * 31 : 530;
    const width = left + plotWidth + left;
    const scale = position => left + (length > 0 ? Math.max(0, Math.min(length, position)) / length : 0) * plotWidth;
    return {left, right:left + plotWidth, width, height:150, lowY:60, scale};
  }

  function scrollTarget(position, viewportWidth, contentWidth, scrollLeft) {
    const margin = Math.min(24, viewportWidth / 4);
    if (position >= scrollLeft + margin && position <= scrollLeft + viewportWidth - margin) return scrollLeft;
    return Math.max(0, Math.min(contentWidth - viewportWidth, position - viewportWidth / 2));
  }

  function pointState(point, state) {
    // Obstacle exclusions take precedence over the operator's point selection.
    if (point.scheduled === false) return point.skip_reason === 'not_selected' ? 'excluded' : 'skipped';
    if (['measured', 'simulation'].includes(point.data?.status)) return 'complete';
    if (point.data?.status != null) return 'failed';
    const current = state.active_point ?? state.measurement_index;
    if (point.point_number === current && state.point_completed === true) {
      return state.last_measurement_success === true ? 'complete' : 'failed';
    }
    // An idle or stopped program does not complete points that were never measured.
    if (['measurements_done', 'end_routine', 'idle', 'error', 'stopped'].includes(state.mode)) return 'pending';
    if (typeof current !== 'number') return 'pending';
    if (point.point_number < current) return 'complete';
    if (point.point_number > current) return 'pending';
    return 'current';
  }

  return {colors, layout, scrollTarget, pointState};
})();
