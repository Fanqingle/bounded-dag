/** Pure event-to-view transforms. No DOM access and no requests. */

export interface RunEvent {
  seq: number;
  ts: number;
  type: string;
  run_id: string;
  step_id: string | null;
  attempt: number | null;
  payload: Record<string, unknown>;
}

export type SegmentKind =
  | "queued"
  | "running"
  | "retry_wait"
  | "failed"
  | "skipped"
  | "cancelled";

export interface Segment {
  kind: SegmentKind;
  start: number;
  end: number;
  attempt: number | null;
  startTs: number;
  endTs: number;
}

export interface Row {
  step_id: string;
  segments: Segment[];
  terminal: string | null;
}

export interface ConcurrencyPoint {
  seq: number;
  count: number;
}

function ordered(events: RunEvent[]): RunEvent[] {
  return [...events].sort((a, b) => a.seq - b.seq);
}

/**
 * Build one row per step. Segment bounds use seq because it is strictly monotonic;
 * ts values are retained for display. A succeeded step ends its running segment
 * without adding a separate segment kind.
 */
export function parseRows(events: RunEvent[]): Row[] {
  const grouped = new Map<string, RunEvent[]>();
  for (const event of ordered(events)) {
    if (!event.step_id) {
      continue;
    }
    const list = grouped.get(event.step_id) ?? [];
    list.push(event);
    grouped.set(event.step_id, list);
  }

  const rows: Row[] = [];
  for (const [step_id, list] of grouped) {
    const segments: Segment[] = [];
    let terminal: string | null = null;

    for (let index = 0; index < list.length; index += 1) {
      const event = list[index];
      const next = list[index + 1];
      const endSeq = next ? next.seq : event.seq + 1;
      const endTs = next ? next.ts : event.ts;
      const add = (kind: SegmentKind, attempt: number | null): void => {
        segments.push({
          kind,
          start: event.seq,
          end: Math.max(endSeq, event.seq + 1),
          attempt,
          startTs: event.ts,
          endTs,
        });
      };

      switch (event.type) {
        case "step_queued":
          add("queued", null);
          break;
        case "step_started":
          add("running", event.attempt);
          break;
        case "step_retry_scheduled":
          add("retry_wait", event.attempt);
          break;
        case "step_failed":
          add("failed", event.attempt);
          terminal = "FAILED";
          break;
        case "step_skipped":
          add("skipped", null);
          terminal = "SKIPPED";
          break;
        case "step_cancelled":
          add("cancelled", null);
          terminal = "CANCELLED";
          break;
        case "step_succeeded":
          terminal = "SUCCEEDED";
          break;
        default:
          break;
      }
    }
    rows.push({ step_id, segments, terminal });
  }
  return rows;
}

/** Count RUNNING steps after each step event. A step is active between
 * step_started and the first of succeeded / failed / retry_scheduled / cancelled. */
export function concurrentSeries(events: RunEvent[]): ConcurrencyPoint[] {
  const active = new Set<string>();
  let count = 0;
  const points: ConcurrencyPoint[] = [];

  for (const event of ordered(events)) {
    if (!event.step_id) {
      continue;
    }
    if (event.type === "step_started") {
      if (!active.has(event.step_id)) {
        active.add(event.step_id);
        count += 1;
      }
    } else if (
      event.type === "step_succeeded" ||
      event.type === "step_failed" ||
      event.type === "step_retry_scheduled" ||
      event.type === "step_cancelled"
    ) {
      if (active.delete(event.step_id)) {
        count -= 1;
      }
    }
    points.push({ seq: event.seq, count });
  }
  return points;
}
