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
  // clientHeight was added to Gameface in 1.54.0. Older embedded versions
  // expose offsetHeight/getBoundingClientRect but may omit clientHeight.
  // https://docs.coherent-labs.com/cpp-gameface/releases/release_1540/
  clientHeight?: number;
  offsetHeight?: number;
  getBoundingClientRect?(): { height: number };
}

export function panelViewportHeight(panel: ScrollPosition): number {
  for (const size of [panel.clientHeight, panel.offsetHeight]) {
    if (typeof size === 'number' && Number.isFinite(size) && size > 0) return size;
  }
  const height = panel.getBoundingClientRect?.().height;
  return typeof height === 'number' && Number.isFinite(height) && height > 0 ? height : 0;
}

export function scrollPanel(panel: ScrollPosition, distance: number): boolean {
  const before = panel.scrollTop;
  if (!Number.isFinite(distance) || !Number.isFinite(before)) return false;
  const viewport = panelViewportHeight(panel);
  // If no geometry API is available yet, the native scrollTop setter can still
  // clamp the requested position. Never send NaN from an absent DOM property.
  const end = viewport > 0 && Number.isFinite(panel.scrollHeight)
    ? Math.max(0, panel.scrollHeight - viewport) : Infinity;
  const target = Math.max(0, Math.min(end, before + distance));
  if (!Number.isFinite(target) || target === before) return false;
  try { panel.scrollTop = target; } catch { return false; }
  return Number.isFinite(panel.scrollTop) && panel.scrollTop !== before;
}

export function handlePanelKey(panel: ScrollPosition, key: string): boolean {
  const page = (panelViewportHeight(panel) || 600) * 0.8;
  const distance = key === 'PageDown' ? page : key === 'PageUp' ? -page
    : key === 'Home' ? -panel.scrollTop : key === 'End' ? panel.scrollHeight : 0;
  return distance !== 0 && scrollPanel(panel, distance);
}

// Compensate the reversed native scrolling reported in the client smoke.
// The embedded deltaY mapping still requires in-game acceptance of this change.
// Normalize small deltas as ticks and Windows-style packets as 120 units per tick.
// Bound one packet so a delayed burst cannot jump across an entire long report.
export function gamefaceWheelDistance(deltaY: number, deltaMode = 0, viewportHeight = 600): number {
  if (!Number.isFinite(deltaY) || deltaY === 0) return 0;
  if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) viewportHeight = 600;
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
  const viewport = panelViewportHeight(panel);
  const distance = gamefaceWheelDistance(event.deltaY, event.deltaMode, viewport);
  if (!distance) return false;
  const end = panel.scrollHeight - viewport;
  const knownEdge = viewport > 0 && Number.isFinite(end) && end > 0 && Number.isFinite(panel.scrollTop)
    && (distance < 0 ? panel.scrollTop <= 0 : panel.scrollTop >= end);
  // Do not swallow native input if a missing API or a no-op setter prevented
  // the custom movement. At a known edge consume the normalized packet too:
  // passing it on would let the opposite native direction bounce back inward.
  if (!knownEdge && !scrollPanel(panel, distance)) return false;
  event.preventDefault();
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
