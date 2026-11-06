import { useEffect, useState } from "react";
import { ApiError, getBenchmark } from "../api";
import type { BenchPass, BenchResults } from "../types";

type State =
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error"; message: string }
  | { status: "ready"; data: BenchResults };

const LABEL_ORDER = [
  "LEGITIMATE",
  "MANIPULATED",
  "MERCHANT_MISREPRESENTATION",
  "INTEGRITY_FAILURE",
  "OUT_OF_SCOPE",
  "INCONCLUSIVE",
];

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

function Card({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3">
      <dt className="text-xs text-[var(--muted)]">{label}</dt>
      <dd className="mt-1 text-xl font-semibold break-words">{value}</dd>
      {note && <p className="text-xs text-[var(--muted)]">{note}</p>}
    </div>
  );
}

function Metrics({ title, pass }: { title: string; pass: BenchPass }) {
  return (
    <section aria-label={title} className="mb-6">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Card label="Macro F1" value={pass.macro_f1.toFixed(3)} />
        <Card label="Coverage" value={pct(pass.coverage)} note="decided (not INCONCLUSIVE)" />
        <Card label="False accusation rate" value={pct(pass.false_accusation_rate)} note="LEGITIMATE called MANIPULATED" />
        <Card label="N" value={String(pass.n)} />
      </dl>
    </section>
  );
}

function Matrix({ title, pass }: { title: string; pass: BenchPass }) {
  const cm = pass.confusion_matrix;
  const labels = [
    ...LABEL_ORDER.filter((l) => l in cm || LABEL_ORDER.includes(l)),
    ...Object.keys(cm).filter((l) => !LABEL_ORDER.includes(l)),
  ];
  const max = Math.max(1, ...labels.flatMap((t) => labels.map((p) => cm[t]?.[p] ?? 0)));
  return (
    <section aria-label={title} className="mb-6">
      <h3 className="mb-1 font-semibold">{title}</h3>
      <p className="mb-2 text-xs text-[var(--muted)]">Rows: true label. Columns: predicted.</p>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]" tabIndex={0} role="region" aria-label={`${title} (scrollable)`}>
        <table className="min-w-[640px] w-full border-collapse text-sm">
          <caption className="sr-only">{title}: counts of true label by predicted label</caption>
          <thead>
            <tr>
              <th scope="col" className="p-2 text-left text-xs text-[var(--muted)]">True \ Predicted</th>
              {labels.map((l) => (
                <th key={l} scope="col" className="p-2 text-xs font-medium">{l}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((t) => (
              <tr key={t} className="border-t border-[var(--border)]">
                <th scope="row" className="p-2 text-left text-xs font-medium">{t}</th>
                {labels.map((p) => {
                  const v = cm[t]?.[p] ?? 0;
                  const diag = t === p;
                  return (
                    <td
                      key={p}
                      className="p-2 text-center tabular-nums"
                      style={{
                        background: v
                          ? `color-mix(in srgb, ${diag ? "#16a34a" : "#dc2626"} ${Math.round(8 + (v / max) * 40)}%, transparent)`
                          : undefined,
                      }}
                    >
                      {v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Recall({ pass }: { pass: BenchPass }) {
  const rows = Object.entries(pass.manipulated_recall_by_attack);
  return (
    <section aria-label="MANIPULATED recall by attack type" className="mb-6">
      <h3 className="mb-2 font-semibold">MANIPULATED recall by attack type</h3>
      <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-[var(--muted)]">
              <th scope="col" className="p-2">Attack</th>
              <th scope="col" className="p-2">Caught</th>
              <th scope="col" className="p-2">Recall</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, r]) => (
              <tr key={name} className="border-t border-[var(--border)]">
                <th scope="row" className="p-2 text-left font-normal">{name.replace(/_/g, " ")}</th>
                <td className="p-2 tabular-nums">{r.caught} / {r.support}</td>
                <td className="p-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-24 rounded bg-[var(--border)]" aria-hidden="true">
                      <div className="h-2 rounded bg-[var(--accent)]" style={{ width: pct(r.recall) }} />
                    </div>
                    <span className="whitespace-nowrap tabular-nums">{pct(r.recall)}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PassView({ title, pass }: { title: string; pass: BenchPass }) {
  return (
    <div className="mb-8">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      <Metrics title="Headline metrics" pass={pass} />
      <Matrix title="Confusion matrix" pass={pass} />
      <Recall pass={pass} />
    </div>
  );
}

export default function BenchmarkPage() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    getBenchmark()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setState({ status: "empty" });
        else setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  return (
    <main>
      <h1 className="mb-4 text-xl font-semibold">Benchmark</h1>
      {state.status === "loading" && <p role="status">Loading benchmark results...</p>}
      {state.status === "empty" && (
        <p role="status" className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
          No benchmark results yet. Run <code>intenttrace bench</code> to generate benchmark/results.json.
        </p>
      )}
      {state.status === "error" && (
        <div role="alert" className="rounded-lg border border-red-500 p-4">
          <p>Could not load benchmark: {state.message}</p>
          <button type="button" className="mt-2 rounded border border-[var(--border)] px-3 py-1.5 text-sm" onClick={() => setAttempt((a) => a + 1)}>
            Retry
          </button>
        </div>
      )}
      {state.status === "ready" && <Ready data={state.data} />}
    </main>
  );
}

function Ready({ data }: { data: BenchResults }) {
  const fake = data.pipeline_test_only || data.provider === "fake";
  return (
    <>
      {fake && (
        <div role="note" className="mb-4 rounded-lg border-2 border-amber-500 bg-amber-500/10 p-3 text-sm font-medium">
          Provider is fake: pipeline test, not model accuracy. These numbers do not describe real model performance.
        </div>
      )}
      <dl className="mb-6 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Card label="Provider / model" value={`${data.provider} / ${data.model ?? "n/a"}`} />
        <Card label="N" value={String(data.n)} note={`seed ${data.seed}, prompt v${data.prompt_version}`} />
        <Card label="Replay on, macro F1" value={data.replay_on.macro_f1.toFixed(3)} />
        <Card label="Replay off, macro F1" value={data.replay_off.macro_f1.toFixed(3)} />
      </dl>
      <p className="mb-4 text-xs text-[var(--muted)]">Run date {data.date}</p>
      <PassView title="Replay on" pass={data.replay_on} />
      <PassView title="Replay off" pass={data.replay_off} />
    </>
  );
}
