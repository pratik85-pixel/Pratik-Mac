/**
 * Smoke tests for WaveformChart.
 *
 * The original implementation short-circuited with an early `return` when
 * `points.length < 2`, ABOVE the `useMemo` hook — which crashed whenever the
 * points length crossed the threshold across renders (Rules of Hooks
 * violation). We now fold the empty-state branch into the memo and return
 * lazily, so these tests verify both states render without throwing.
 */
import React from 'react';
import { render } from '@testing-library/react-native';
import WaveformChart from '../WaveformChart';

describe('WaveformChart', () => {
  it('renders the empty state with zero points', () => {
    const { getByText } = render(
      <WaveformChart points={[]} variant="stress" />,
    );
    expect(getByText(/No data yet/i)).toBeTruthy();
  });

  it('renders without throwing when toggled from empty → populated', () => {
    const emptyRender = render(
      <WaveformChart points={[]} variant="stress" />,
    );
    const now = new Date();
    const mk = (offsetMin: number, rmssd: number) => ({
      window_start: new Date(now.getTime() - offsetMin * 60_000).toISOString(),
      rmssd_ms: rmssd,
      context: 'background',
    });
    emptyRender.rerender(
      <WaveformChart
        points={[mk(30, 50), mk(20, 55), mk(10, 60), mk(0, 58)] as any}
        variant="stress"
      />,
    );
    // If hook order was corrupted, React would throw during this rerender.
    expect(emptyRender).toBeTruthy();
  });
});
