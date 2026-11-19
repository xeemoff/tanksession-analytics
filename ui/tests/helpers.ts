import { Snapshot, SnapshotRequest, Summary } from '../src/contracts';
import { Bridge } from '../src/bridge';

export const summary: Summary = { battles: 20, known_outcomes: 19, wins: 11, losses: 7, draws: 1,
  win_rate: 57.9, avg_damage: 2010, avg_xp: 610, damage_samples: 18 };
export function snapshot(id = 'initial'): Snapshot {
  return { protocol: 1, request_id: id, source: 'game', status: 'ready',
    selection: { vehicle: '', window: 10 }, vehicles: [{ name: 'IS-7', battles: 20 }],
    summary: { ...summary }, comparison: { window: 10,
      current: { ...summary, battles: 10, known_outcomes: 9, wins: 6, losses: 3, draws: 0, win_rate: 66.7, avg_damage: 2160, damage_samples: 9 },
      previous: { ...summary, battles: 10, known_outcomes: 10, wins: 5, losses: 4, draws: 1, win_rate: 50, avg_damage: 1860, damage_samples: 9 },
      enough_current: true, enough_previous: true, damage_delta: 300, win_rate_delta_pp: 16.7 },
    series: [{ battle: 10, avg_damage: 1900, known_damage: 9 }, { battle: 11, avg_damage: null, known_damage: 6 },
      { battle: 12, avg_damage: 2200, known_damage: 10 }],
    goals: [{ vehicle: 'IS-7', target: 2500, window: 10, battles: 10, known_damage: 9, avg_damage: 2160, status: 'not_achieved' }],
    history: [{ timestamp: 1800000000, vehicle: 'IS-7', outcome: 'win', damage: 0, xp: null }],
    quality: { total_records: 20, incomplete_records: 2, invalid_records: 0, conflicts: 0 }, updated_at: 1800003600 };
}
export class FakeBridge implements Bridge {
  requests: SnapshotRequest[] = [];
  receive: (snapshot: Snapshot) => void = () => {};
  report: (error: Error) => void = () => {};
  ready: () => void = () => {};
  disposed = 0;
  closed = 0;
  start(receive: (snapshot: Snapshot) => void, report: (error: Error) => void, ready: () => void): () => void {
    this.receive = receive; this.report = report; this.ready = ready;
    return () => { this.disposed += 1; };
  }
  request(request: SnapshotRequest) { this.requests.push(request); }
  close() { this.closed += 1; }
}
