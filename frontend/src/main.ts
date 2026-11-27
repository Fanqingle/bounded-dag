import {
  concurrentSeries,
  parseRows,
  type ConcurrencyPoint,
  type Row,
  type RunEvent,
} from "./timeline";

type Json = Record<string, unknown>;

interface Snapshot {
  run_id: string;
  status: string;
  n: number;
  steps: Array<{
    id: string;
    state: string;
    attempts: number;
    next_attempt_at: number | null;
  }>;
  final_text: string | null;
  last_seq: number;
}

interface RunRecord {
  run_id: string;
  n: number;
  status: string;
  duration_ms: number | null;
}

const TOOLS = ["search", "summarize", "generate_image"] as const;
const FINISHED = new Set(["SUCCEEDED", "FAILED", "PARTIAL", "CANCELLED"]);

const byId = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) {
    throw new Error(`missing element: ${id}`);
  }
  return node as T;
};

const ui = {
  plan: byId<HTMLTextAreaElement>("plan-input"),
  loadExample: byId<HTMLButtonElement>("load-example"),
  concurrency: byId<HTMLInputElement>("concurrency"),
  run: byId<HTMLButtonElement>("run-button"),
  cancel: byId<HTMLButtonElement>("cancel-button"),
  errors: byId<HTMLPreElement>("errors"),
  status: byId<HTMLDivElement>("status"),
  final: byId<HTMLDivElement>("final-text"),
  chart: byId<HTMLDivElement>("concurrency-chart"),
  timeline: byId<HTMLDivElement>("timeline"),
  eventTable: byId<HTMLTableSectionElement>("event-table"),
  history: byId<HTMLTableSectionElement>("run-history"),
};

let runId: string | null = null;
let events: RunEvent[] = [];
let lastSeq = 0;
let currentN = 2;
let source: EventSource | null = null;
const runs: RunRecord[] = [];

async function fetchJson<T>(url: string, init?: RequestInit): Promise<{ status: number; body: T }> {
  const response = await fetch(url, init);
  const text = await response.text();
  let body = {} as T;
  if (text) {
    try {
      body = JSON.parse(text) as T;
    } catch {
      body = {} as T;
    }
  }
  return { status: response.status, body };
}

function showErrors(status: number, payload: unknown): void {
  const data = (payload ?? {}) as Json;
  const items: Json[] = [];
  if (Array.isArray(data.errors)) {
    items.push(...(data.errors as Json[]));
  }
  if (items.length === 0 && Array.isArray(data.detail)) {
    items.push(...(data.detail as Json[]));
  }
  const lines = items.map((item) => {
    const code = String(item.error ?? item.type ?? item.msg ?? "invalid_request");
    const step = typeof item.step_id === "string" ? ` step_id=${item.step_id}` : "";
    const path = Array.isArray(item.path)
      ? ` path=${(item.path as unknown[]).join("→")}`
      : "";
    const missing = typeof item.missing === "string" ? ` missing=${item.missing}` : "";
    return `HTTP ${status} ${code}${step}${path}${missing}`;
  });
  ui.errors.textContent = lines.length > 0 ? lines.join("\n") : `HTTP ${status}`;
}

function clearErrors(): void {
  ui.errors.textContent = "";
}

function buildBody(): Json {
  const body = JSON.parse(ui.plan.value) as Json;
  const tools: Record<string, Json> = {};
  for (const tool of TOOLS) {
    tools[tool] = {
      latency_ms: Number(byId<HTMLInputElement>(`latency-${tool}`).value),
      failure_rate: Number(byId<HTMLInputElement>(`rate-${tool}`).value),
    };
  }
  return {
    ...body,
    n: Number(ui.concurrency.value),
    tools,
    time_scale: typeof body.time_scale === "number" ? body.time_scale : 1,
  };
}

async function loadExample(): Promise<void> {
  const { status, body } = await fetchJson<Json>("/api/example");
  if (status !== 200) {
    showErrors(status, body);
    return;
  }
  clearErrors();
  ui.plan.value = JSON.stringify(body, null, 2);
  if (typeof body.n === "number") {
    ui.concurrency.value = String(body.n);
  }
  const tools = body.tools as Record<string, Json> | undefined;
  if (tools) {
    for (const tool of TOOLS) {
      const config = tools[tool];
      if (!config) {
        continue;
      }
      const latency = byId<HTMLInputElement>(`latency-${tool}`);
      const rate = byId<HTMLInputElement>(`rate-${tool}`);
      if (typeof config.latency_ms === "number") {
        latency.value = String(config.latency_ms);
      }
      if (typeof config.failure_rate === "number") {
        rate.value = String(config.failure_rate);
      }
      latency.dispatchEvent(new Event("input"));
      rate.dispatchEvent(new Event("input"));
    }
  }
}

function renderChart(n: number): void {
  const points: ConcurrencyPoint[] = concurrentSeries(events);
  if (points.length === 0) {
    ui.chart.innerHTML = '<svg viewBox="0 0 600 180"></svg>';
    return;
  }
  const first = points[0].seq;
  const last = points[points.length - 1].seq;
  const span = Math.max(1, last - first);
  const peak = points.reduce((max, point) => Math.max(max, point.count), 0);
  const scale = Math.max(n, peak, 1);
  const x = (seq: number): number => 40 + ((seq - first) / span) * 540;
  const y = (count: number): number => 150 - (count / scale) * 120;
  const line = points
    .map((point) => `${x(point.seq).toFixed(1)},${y(point.count).toFixed(1)}`)
    .join(" ");
  const baseline = y(n).toFixed(1);
  const dots = points
    .map(
      (point) =>
        `<circle cx="${x(point.seq).toFixed(1)}" cy="${y(point.count).toFixed(1)}" r="2" fill="#2563eb" />`,
    )
    .join("");
  ui.chart.innerHTML = `
    <svg viewBox="0 0 600 180" role="img" aria-label="concurrency">
      <line x1="40" y1="150" x2="580" y2="150" stroke="#94a3b8" />
      <line x1="40" y1="${baseline}" x2="580" y2="${baseline}" stroke="#dc2626" stroke-dasharray="6 4" />
      <text x="4" y="${baseline}" font-size="11" fill="#b91c1c">n=${n}</text>
      <polyline fill="none" stroke="#2563eb" stroke-width="2" points="${line}" />
      ${dots}
      <text x="40" y="170" font-size="11" fill="#64748b">seq ${first}</text>
      <text x="580" y="170" font-size="11" fill="#64748b" text-anchor="end">seq ${last}</text>
    </svg>`;
}

function renderTimeline(): void {
  const rows: Row[] = parseRows(events);
  if (rows.length === 0) {
    ui.timeline.textContent = "no events";
    return;
  }
  const first = Math.min(...events.map((event) => event.seq));
  const last = Math.max(...events.map((event) => event.seq));
  const span = Math.max(1, last - first);
  ui.timeline.innerHTML = "";
  for (const row of rows) {
    const line = document.createElement("div");
    line.className = "timeline-row";
    const name = document.createElement("span");
    name.textContent = row.step_id;
    const track = document.createElement("div");
    track.className = "track";
    for (const segment of row.segments) {
      const node = document.createElement("div");
      node.className = `seg ${segment.kind}`;
      node.style.left = `${((segment.start - first) / span) * 100}%`;
      node.style.width = `${Math.max(0.8, ((segment.end - segment.start) / span) * 100)}%`;
      node.title = `${segment.kind} attempt=${segment.attempt ?? "-"} ts=${segment.startTs}..${segment.endTs}`;
      node.textContent = segment.kind === "running" && segment.attempt ? `a${segment.attempt}` : "";
      track.appendChild(node);
    }
    const terminal = document.createElement("span");
    terminal.textContent = row.terminal ?? "";
    line.append(name, track, terminal);
    ui.timeline.appendChild(line);
  }
}

function renderEvents(): void {
  ui.eventTable.innerHTML = "";
  for (const event of events) {
    const tr = document.createElement("tr");
    const values = [
      String(event.seq),
      event.type,
      event.step_id ?? "",
      event.attempt === null ? "" : String(event.attempt),
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    ui.eventTable.appendChild(tr);
  }
}

function renderHistory(): void {
  ui.history.innerHTML = "";
  for (const record of runs) {
    const tr = document.createElement("tr");
    const values = [
      record.run_id,
      String(record.n),
      record.status,
      record.duration_ms === null ? "-" : String(record.duration_ms),
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    ui.history.appendChild(tr);
  }
}

function render(): void {
  renderChart(currentN);
  renderTimeline();
  renderEvents();
}

function recordRun(snapshot: Snapshot): void {
  const started = events.find((event) => event.type === "run_started");
  const finished = events.find((event) => event.type === "run_finished");
  const duration = started && finished ? finished.ts - started.ts : null;
  const existing = runs.find((record) => record.run_id === snapshot.run_id);
  if (existing) {
    if (existing.duration_ms === null && duration !== null) {
      existing.duration_ms = duration;
      renderHistory();
    }
    return;
  }
  runs.unshift({
    run_id: snapshot.run_id,
    n: snapshot.n,
    status: snapshot.status,
    duration_ms: duration,
  });
  if (runs.length > 8) {
    runs.pop();
  }
  renderHistory();
}

function showSnapshot(snapshot: Snapshot): void {
  currentN = snapshot.n;
  ui.status.textContent = `${snapshot.run_id} | ${snapshot.status} | seq=${snapshot.last_seq}`;
  if (snapshot.final_text) {
    ui.final.textContent = snapshot.final_text;
  }
  if (FINISHED.has(snapshot.status)) {
    ui.cancel.disabled = true;
  }
  recordRun(snapshot);
  render();
}

async function loadSnapshot(run: string): Promise<Snapshot | null> {
  const { status, body } = await fetchJson<Snapshot>(`/api/runs/${run}`);
  if (status !== 200 || typeof body.run_id !== "string") {
    return null;
  }
  showSnapshot(body);
  return body;
}

function acceptEvent(event: RunEvent): void {
  if (event.seq <= lastSeq) {
    return;
  }
  events.push(event);
  lastSeq = event.seq;
  render();
  if (event.type === "run_finished") {
    source?.close();
    source = null;
    void loadSnapshot(runId as string);
  }
}

async function backfill(run: string): Promise<void> {
  const response = await fetch(`/api/runs/${run}/events`, {
    headers: { "Last-Event-ID": String(lastSeq) },
  });
  if (!response.ok) {
    return;
  }
  const text = await response.text();
  for (const block of text.split("\n\n")) {
    const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
    if (!dataLine) {
      continue;
    }
    try {
      acceptEvent(JSON.parse(dataLine.slice(6)) as RunEvent);
    } catch {
      // Ignore malformed SSE frames from a partial response.
    }
  }
}

function openStream(run: string): void {
  source?.close();
  source = new EventSource(`/api/runs/${run}/events`);
  source.onmessage = (message: MessageEvent<string>) => {
    acceptEvent(JSON.parse(message.data) as RunEvent);
  };
  source.onerror = () => {
    source?.close();
    source = null;
    void recover(run);
  };
}

/** On disconnect, fetch the snapshot first, then replay the missing tail.
 * EventSource resends the last received id as Last-Event-ID on reconnect. */
async function recover(run: string): Promise<void> {
  try {
    const snapshot = await loadSnapshot(run);
    if (!snapshot) {
      return;
    }
    if (FINISHED.has(snapshot.status)) {
      if (snapshot.last_seq > lastSeq) {
        await backfill(run);
      }
    } else {
      openStream(run);
    }
  } catch (error) {
    ui.status.textContent = `reconnect failed: ${String(error)}`;
  }
}

async function startRun(): Promise<void> {
  let body: Json;
  try {
    body = buildBody();
  } catch (error) {
    showErrors(0, { errors: [{ error: "invalid_json", detail: String(error) }] });
    return;
  }
  const response = await fetchJson<Json>("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status !== 202) {
    showErrors(response.status, response.body);
    return;
  }
  clearErrors();
  const id = String(response.body.run_id);
  runId = id;
  events = [];
  lastSeq = 0;
  currentN = Number(body.n ?? 2);
  ui.status.textContent = `${id} | RUNNING`;
  ui.final.textContent = "";
  ui.cancel.disabled = false;
  render();
  openStream(id);
}

async function cancelRun(): Promise<void> {
  if (!runId) {
    return;
  }
  const response = await fetchJson<Json>(`/api/runs/${runId}/cancel`, {
    method: "POST",
  });
  if (response.status !== 200) {
    showErrors(response.status, response.body);
    return;
  }
  ui.status.textContent = `${runId} | CANCELLED`;
  await recover(runId);
}

for (const tool of TOOLS) {
  const latency = byId<HTMLInputElement>(`latency-${tool}`);
  const rate = byId<HTMLInputElement>(`rate-${tool}`);
  const latencyOut = byId<HTMLOutputElement>(`latency-${tool}-out`);
  const rateOut = byId<HTMLOutputElement>(`rate-${tool}-out`);
  const sync = (): void => {
    latencyOut.value = latency.value;
    rateOut.value = Number(rate.value).toFixed(2);
  };
  latency.addEventListener("input", sync);
  rate.addEventListener("input", sync);
  sync();
}

ui.loadExample.addEventListener("click", () => {
  void loadExample();
});
ui.run.addEventListener("click", () => {
  void startRun();
});
ui.cancel.addEventListener("click", () => {
  void cancelRun();
});

render();
