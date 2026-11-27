import { decodePayload, getMode, parseSnapshot, Snapshot, SnapshotRequest } from './contracts';

export interface Bridge {
  start(onSnapshot: (snapshot: Snapshot) => void, onError: (error: Error) => void, onReady: () => void): () => void;
  request(request: SnapshotRequest): void;
  close(): void;
}
export interface GamefaceEngine {
  whenReady: PromiseLike<void>;
  on(name: string, callback: (...args: unknown[]) => void): unknown;
  off(name: string, callback: (...args: unknown[]) => void): void;
}
interface GamefaceHost {
  engine?: GamefaceEngine;
  isDomBuilt?: boolean;
  model?: Record<string, unknown>;
  document?: { documentElement: { clientWidth: number; clientHeight: number } };
  viewEnv?: {
    addDataChangedCallback(name: string, index: number, immediate: boolean): number;
    removeDataChangedCallback(id: number, index: number): void;
    resizeViewPx?(width: number, height: number): void;
  };
}
declare global { interface Window extends GamefaceHost {} }

function valueOf(value: unknown): unknown {
  if (value !== null && typeof value === 'object' && 'value' in value) return (value as { value: unknown }).value;
  return value;
}

export class GamefaceBridge implements Bridge {
  private ready = false;
  private latestRequestId = '';
  constructor(private readonly host: GamefaceHost) {}

  start(onSnapshot: (snapshot: Snapshot) => void, onError: (error: Error) => void, onReady: () => void): () => void {
    let disposed = false;
    let callbackId: number | undefined;
    let registered = false;
    const engine = this.host.engine;
    const changed = () => {
      if (disposed || !this.ready) return;
      const raw = valueOf(this.host.model?.payload);
      if (raw === undefined || raw === null || raw === '') return;
      try {
        const decoded = decodePayload(raw);
        if (decoded && typeof decoded === 'object' && 'request_id' in decoded
          && this.latestRequestId && (decoded as { request_id: unknown }).request_id !== 'closed'
          && (decoded as { request_id: unknown }).request_id !== this.latestRequestId) return;
        if (decoded && typeof decoded === 'object' && 'status' in decoded) {
          const envelope = decoded as Record<string, unknown>;
          if (envelope.protocol === 1 && envelope.source === 'game' && envelope.status === 'error'
            && typeof envelope.request_id === 'string' && /^[A-Za-z0-9_.:-]{1,64}$/.test(envelope.request_id)
            && envelope.error === 'data_unavailable') {
            if (envelope.request_id === 'closed') throw new Error('Окно статистики закрыто. Откройте его заново в ангаре.');
            throw new Error('Не удалось подготовить данные. Обновите панель или откройте её заново. Подробности — в журнале TankSession.');
          }
        }
        const snapshot = parseSnapshot(decoded);
        if (snapshot.source !== 'game') throw new Error('Игровое окно получило неподходящий источник данных.');
        onSnapshot(snapshot);
      } catch (error) { onError(asError(error)); }
    };
    const domBuilt = () => {
      if (disposed || registered) return;
      try {
        if (!this.host.viewEnv || !this.host.model || !engine) throw new Error('Игровой интерфейс ещё не предоставляет данные TankSession.');
        registered = true;
        engine.on('viewEnv.onDataChanged', changed);
        callbackId = this.host.viewEnv.addDataChangedCallback('model', 0, true);
        this.ready = true;
        if (typeof this.host.viewEnv.resizeViewPx === 'function') {
          const viewport = this.host.document?.documentElement;
          const width = viewport && viewport.clientWidth > 0 ? Math.min(1120, viewport.clientWidth) : 1120;
          const height = viewport && viewport.clientHeight > 0 ? Math.min(800, viewport.clientHeight) : 800;
          this.host.viewEnv.resizeViewPx(width, height);
        }
        changed();
        onReady();
      } catch (error) { onError(asError(error)); }
    };
    if (!engine || !engine.whenReady || typeof engine.on !== 'function' || typeof engine.off !== 'function') {
      onError(new Error('Подключение к игре недоступно. Откройте TankSession через клиент или запустите демонстрацию отдельно.'));
    } else {
      engine.whenReady.then(() => {
        if (disposed) return;
        engine.on('self.onDomBuilt', domBuilt);
        if (this.host.isDomBuilt) domBuilt();
      }, error => { if (!disposed) onError(asError(error)); });
    }
    return () => {
      disposed = true;
      this.ready = false;
      if (engine) {
        try { engine.off('self.onDomBuilt', domBuilt); } catch { /* Already destroyed by the client. */ }
        if (registered) { try { engine.off('viewEnv.onDataChanged', changed); } catch { /* Already destroyed. */ } }
      }
      if (callbackId !== undefined && this.host.viewEnv) {
        try { this.host.viewEnv.removeDataChangedCallback(callbackId, 0); } catch { /* Native view already gone. */ }
      }
    };
  }

  private invoke(name: string, args: Record<string, unknown>): void {
    if (!this.ready || !this.host.model) throw new Error('Дождитесь подключения игрового интерфейса.');
    const callback = valueOf(this.host.model[name]);
    if (typeof callback !== 'function') throw new Error('Клиент не предоставляет команду панели.');
    callback.call(this.host.model, args);
  }
  request(request: SnapshotRequest): void {
    this.latestRequestId = request.request_id;
    this.invoke('onRequest', { payload: JSON.stringify(request) });
  }
  close(): void { this.invoke('onClose', {}); }
}

export class HttpBridge implements Bridge {
  private receive: ((snapshot: Snapshot) => void) | null = null;
  private report: ((error: Error) => void) | null = null;
  private active: XMLHttpRequest | null = null;
  constructor(private readonly expectedSource: 'game' | 'demo') {}

  start(onSnapshot: (snapshot: Snapshot) => void, onError: (error: Error) => void, onReady: () => void): () => void {
    this.receive = onSnapshot;
    this.report = onError;
    onReady();
    return () => { this.active?.abort(); this.active = null; this.receive = null; this.report = null; };
  }
  request(request: SnapshotRequest): void {
    this.active?.abort();
    const xhr = new XMLHttpRequest();
    this.active = xhr;
    const query = 'window=' + request.window + '&vehicle=' + encodeURIComponent(request.vehicle)
      + '&request_id=' + encodeURIComponent(request.request_id) + '&page=' + (request.page || 0)
      + (request.history_query === undefined ? '' : '&history_query=' + encodeURIComponent(request.history_query))
      + (request.history_sort === undefined ? '' : '&history_sort=' + encodeURIComponent(request.history_sort));
    const command = !!request.action;
    xhr.open(command ? 'POST' : 'GET', command ? '/api/command' : '/api/snapshot?' + query, true);
    xhr.timeout = 10000;
    xhr.setRequestHeader('Accept', 'application/json');
    if (command) {
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.setRequestHeader('X-TankSession-Request', '1');
    }
    xhr.onload = () => {
      if (xhr !== this.active) return;
      this.active = null;
      if (xhr.status !== 200) { this.report?.(new Error('Не удалось прочитать локальную историю. Проверьте сообщение сервера и повторите запрос.')); return; }
      try {
        const snapshot = parseSnapshot(xhr.responseText);
        if (snapshot.source !== this.expectedSource) throw new Error('Режим страницы не совпадает с источником сервера. Откройте адрес, показанный при запуске.');
        this.receive?.(snapshot);
      } catch (error) { this.report?.(asError(error)); }
    };
    xhr.onerror = xhr.ontimeout = () => {
      if (xhr !== this.active) return;
      this.active = null;
      this.report?.(new Error('Локальный сервер не отвечает. Проверьте, запущена ли панель.'));
    };
    xhr.send(command ? JSON.stringify(request) : null);
  }
  close(): void { this.active?.abort(); this.active = null; }
}
export function asError(value: unknown): Error { return value instanceof Error ? value : new Error('Не удалось получить данные панели.'); }
export function createBridge(host: Window = window): Bridge {
  const mode = getMode(host.location.search);
  return mode === 'gameface' ? new GamefaceBridge(host) : new HttpBridge(mode === 'demo' ? 'demo' : 'game');
}
