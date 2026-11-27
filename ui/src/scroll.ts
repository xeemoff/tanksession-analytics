import type { Mode } from './contracts';

export const GAMEFACE_SCROLL_STEP = 96;

export interface PanelWheelEvent {
  deltaY: number;
  deltaX?: number;
  deltaMode?: number;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  defaultPrevented?: boolean;
  cancelable?: boolean;
  preventDefault(): void;
}

export interface ScrollPosition {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function scrollPanel(panel: ScrollPosition, distance: number): void {
  if (!Number.isFinite(distance)) return;
  const end = Math.max(0, panel.scrollHeight - panel.clientHeight);
  panel.scrollTop = Math.max(0, Math.min(end, panel.scrollTop + distance));
}

// Compensate the reversed native scrolling reported in the client smoke.
// The embedded deltaY mapping still requires in-game acceptance of this change.
// Normalize small deltas as ticks and Windows-style packets as 120 units per tick.
// Bound one packet so a delayed burst cannot jump across an entire long report.
export function gamefaceWheelDistance(deltaY: number, deltaMode = 0, viewportHeight = 600): number {
  if (!Number.isFinite(deltaY) || deltaY === 0) return 0;
  const magnitude = Math.abs(deltaY);
  let pixels: number;
  if (deltaMode === 2) pixels = magnitude * Math.max(GAMEFACE_SCROLL_STEP, viewportHeight * 0.8);
  else if (deltaMode === 1) pixels = magnitude * 32;
  else pixels = (magnitude <= 4 ? magnitude : magnitude / 120) * GAMEFACE_SCROLL_STEP;
  const limit = Math.max(GAMEFACE_SCROLL_STEP, viewportHeight * 0.8);
  return (deltaY > 0 ? -1 : 1) * Math.min(limit, pixels);
}

export function handlePanelWheel(panel: ScrollPosition, event: PanelWheelEvent, mode: Mode): boolean {
  // Browser previews retain their platform's native direction and speed.
  if (mode !== 'gameface' || event.defaultPrevented || event.cancelable === false
    || event.ctrlKey || event.shiftKey || Math.abs(event.deltaX || 0) > Math.abs(event.deltaY)) return false;
  const distance = gamefaceWheelDistance(event.deltaY, event.deltaMode, panel.clientHeight);
  if (!distance) return false;
  // Cancel even at an edge: the same packet must not reach native scrolling.
  event.preventDefault();
  scrollPanel(panel, distance);
  return true;
}

export function bindPanelWheel(panel: HTMLElement, mode: Mode): () => void {
  if (mode !== 'gameface') return () => {};
  const wheel = (event: WheelEvent) => { handlePanelWheel(panel, event, mode); };
  // A native, non-passive listener is necessary: React delegates wheel passively.
  // The boolean options form also works in the older embedded DOM.
  panel.addEventListener('wheel', wheel, false);
  return () => panel.removeEventListener('wheel', wheel, false);
}
