// @vitest-environment jsdom
/**
 * Render smoke tests. These catch the class of bug unit tests never see: a
 * component that throws on mount, a filter that empties the table, a toggle
 * that does not toggle. They mount the real App against the committed snapshot.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '../src/App.jsx';

const mount = async (search = '') => {
  window.history.replaceState({}, '', `/${search}`);
  const utils = render(<App />);
  await waitFor(() => expect(screen.getByRole('heading', { name: 'AirGrid' })).toBeTruthy());
  return utils;
};

beforeEach(() => {
  vi.spyOn(window, 'matchMedia').mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('App shell', () => {
  it('renders the dashboard for the default city', async () => {
    await mount();
    expect(screen.getByRole('heading', { name: /Chennai, Tamil Nadu/ })).toBeTruthy();
    // The hero renders the index plus the AQI word-mark; both should be present.
    expect(screen.getAllByText('AQI').length).toBeGreaterThan(0);
    // The chart exposes a data table alternative.
    expect(screen.getByText(/View as table \(\d+ rows\)/)).toBeTruthy();
  });

  it('honours ?city= from the URL', async () => {
    await mount('?city=delhi');
    expect(screen.getByRole('heading', { name: /Delhi, Delhi/ })).toBeTruthy();
  });

  it('switches city from the tabs and updates the URL', async () => {
    await mount();
    const tabs = screen.getByRole('navigation', { name: 'Choose a city' });
    fireEvent.click(within(tabs).getByRole('button', { name: /Mumbai/i }));
    await waitFor(() => expect(screen.getByRole('heading', { name: /Mumbai, Maharashtra/ })).toBeTruthy());
    expect(window.location.search).toBe('?city=mumbai');
  });

  it('changes the metric and the range', async () => {
    await mount();
    fireEvent.click(screen.getByRole('button', { name: 'PM2.5', pressed: false }));
    await waitFor(() => expect(screen.getByRole('heading', { name: /PM2\.5 trend/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '7 days' }));
    await waitFor(() => expect(screen.getByText('7 days', { selector: '.segmented button' })).toBeTruthy());
  });

  it('filters the station table and recovers when the query is cleared', async () => {
    await mount();
    const search = screen.getByLabelText(/search stations/i);
    const rowsBefore = screen.getAllByRole('row').length;
    fireEvent.change(search, { target: { value: 'zzzz-no-such-zone' } });
    await waitFor(() => expect(screen.getByText(/No stations match/i)).toBeTruthy());
    fireEvent.change(search, { target: { value: '' } });
    await waitFor(() => expect(screen.getAllByRole('row').length).toBe(rowsBefore));
  });

  it('reports offline state through the live region', async () => {
    await mount();
    const status = screen.getByRole('status');
    expect(status.textContent).toMatch(/Online/);
    window.dispatchEvent(new Event('offline'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Offline/));
  });

  it('shows the data-provenance footer', async () => {
    await mount();
    expect(screen.getByText(/synthetic-snapshot|CPCB-shaped reference series/)).toBeTruthy();
  });
});
