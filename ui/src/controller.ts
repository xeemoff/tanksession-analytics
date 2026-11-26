import { asError, Bridge } from './bridge';
import { Selection, Snapshot, SnapshotRequest, UserCommand } from './contracts';

export interface ViewState {
  phase: 'connecting' | 'loading' | 'ready' | 'error' | 'closed';
  snapshot: Snapshot | null;
  selection: Selection;
  message: string;
}
type Timer = ReturnType<typeof setTimeout>;
export class SnapshotController {
  state: ViewState = { phase: 'connecting', snapshot: null, selection: { vehicle: '', window: 10 }, message: '' };
  private sequence = 0;
  private latest = '';
  private timer: Timer | undefined;
  private disposeBridge: (() => void) | null = null;
  private disposed = false;
  private connected = false;
  private commandPending = false;

  constructor(private readonly bridge: Bridge, private readonly changed: (state: ViewState) => void,
    private readonly timeoutMs = 12000) {}

  start(): void {
    this.armTimeout();
    this.disposeBridge = this.bridge.start(snapshot => this.receive(snapshot), error => this.error(error), () => {
      if (this.disposed) return;
      this.connected = true;
      this.send(this.state.selection, { action: 'initialize' });
    });
  }
  request(selection: Selection = this.state.selection): void {
    if (this.commandPending) return;
    this.send(selection);
  }
  command(command: UserCommand): void {
    if (command.action === 'initialize' || this.commandPending || this.state.phase !== 'ready' || !this.state.snapshot?.workspace?.can_edit) return;
    this.send(this.state.selection, command);
  }
  private send(selection: Selection, command?: UserCommand): void {
    if (this.disposed || !this.connected || this.state.phase === 'closed') return;
    const id = 'ui-' + (++this.sequence);
    this.latest = id;
    this.commandPending = !!command && command.action !== 'initialize';
    this.publish({ phase: 'loading', snapshot: this.commandPending ? this.state.snapshot : null, selection: { ...selection }, message: '' });
    this.armTimeout();
    const request: SnapshotRequest = { protocol: 1, request_id: id, page: 0, ...selection, ...command };
    try { this.bridge.request(request); } catch (error) { this.error(asError(error)); }
  }
  private receive(snapshot: Snapshot): void {
    if (this.disposed || this.state.phase === 'closed' || (this.latest && snapshot.request_id !== this.latest)) return;
    this.clearTimeout();
    this.commandPending = false;
    this.publish({ phase: 'ready', snapshot, selection: snapshot.selection, message: '' });
  }
  private error(error: Error): void {
    if (this.disposed || this.state.phase === 'closed') return;
    this.clearTimeout();
    this.commandPending = false;
    this.publish({ ...this.state, phase: 'error', snapshot: null, message: error.message });
  }
  private publish(state: ViewState): void { this.state = state; this.changed(state); }
  private armTimeout(): void {
    this.clearTimeout();
    this.timer = setTimeout(() => this.error(new Error('Ответ не получен вовремя. Проверьте подключение и повторите запрос.')), this.timeoutMs);
  }
  private clearTimeout(): void { if (this.timer !== undefined) clearTimeout(this.timer); this.timer = undefined; }
  close(): void {
    if (this.disposed) return;
    try { this.bridge.close(); } catch (error) { this.error(asError(error)); return; }
    this.clearTimeout();
    this.disposeBridge?.();
    this.disposeBridge = null;
    this.publish({ ...this.state, phase: 'closed', snapshot: null, message: '' });
  }
  dispose(): void {
    this.disposed = true;
    this.clearTimeout();
    this.disposeBridge?.();
    this.disposeBridge = null;
  }
}
