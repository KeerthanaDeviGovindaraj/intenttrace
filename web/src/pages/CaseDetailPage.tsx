import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, evidenceUrl, getCase } from "../api";
import VerdictBadge from "../components/VerdictBadge";
import { intentVsCart, segment, summarize } from "../lib/caseView";
import type { CaseDetailResponse, Finding, ReplayResult, Span, TraceSource, TraceStep } from "../types";

type State =
  | { status: "loading" }
  | { status: "notfound" }
  | { status: "error"; message: string }
  | { status: "ready"; data: CaseDetailResponse };

const SOURCES: Record<TraceSource, { icon: string; label: string; untrusted: boolean }> = {
  user: { icon: "👤", label: "User", untrusted: false },
  agent: { icon: "🤖", label: "Agent", untrusted: false },
  merchant: { icon: "🏪", label: "Merchant", untrusted: true },
  review: { icon: "💬", label: "Review", untrusted: true },
  external_agent: { icon: "🛰️", label: "External agent", untrusted: true },
};

const card = "rounded border border-[var(--border)] bg-[var(--surface)] p-3";
const h2 = "mb-2 text-base font-semibold";

function spanLabel(s: Span): string {
  const why = s.reason ?? s.rule_id ?? "flagged";
  const by = s.method === "llm" ? "LLM" : s.method === "rule" ? "Rule" : "Detector";
  const rule = s.rule_id && s.reason ? ` (${s.rule_id})` : "";
  return `${by}: ${why}${rule}`;
}

function StepText({ step, spans }: { step: TraceStep; spans: Span[] }) {
  const mine = spans.filter((s) => s.step_id === step.step_id);
  return (
    <p className="mt-1 whitespace-pre-wrap break-words text-sm">
      {segment(step.content, mine).map((seg, i) =>
        seg.spans.length === 0 ? (
          <span key={i}>{seg.text}</span>
        ) : (
          <mark
            key={i}
            tabIndex={0}
            title={seg.spans.map(spanLabel).join("; ")}
            aria-label={`Flagged text: ${seg.text}. ${seg.spans.map(spanLabel).join("; ")}`}
            className="rounded-sm bg-yellow-200 px-0.5 text-black underline decoration-red-600 decoration-wavy underline-offset-2 focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          >
            <span aria-hidden="true">⚑</span>
            {seg.text}
          </mark>
        ),
      )}
    </p>
  );
}

function Timeline({ trace, spans }: { trace: TraceStep[]; spans: Span[] }) {
  return (
    <ol className="space-y-3 border-l-2 border-[var(--border)] pl-4">
      {trace.map((step) => {
        const src = SOURCES[step.source];
        const flagged = spans.filter((s) => s.step_id === step.step_id);
        return (
          <li
            key={step.step_id}
            className={`relative rounded border p-2 ${
              src.untrusted
                ? "border-dashed border-amber-500 bg-amber-50 text-slate-900 dark:bg-amber-950 dark:text-amber-50"
                : "border-[var(--border)] bg-[var(--surface)]"
            }`}
          >
            <div className="flex flex-wrap items-center gap-x-2 text-xs">
              <span aria-hidden="true">{src.icon}</span>
              <span className="font-semibold">{src.label}</span>
              <span className="text-[var(--muted)]">{step.kind}</span>
              {src.untrusted && <span className="rounded border border-amber-600 px-1 font-semibold">Untrusted</span>}
              {flagged.length > 0 && <span className="rounded border border-red-600 px-1 font-semibold">⚑ {flagged.length} flagged</span>}
              {step.product_id && <span className="break-all text-[var(--muted)]">{step.product_id}</span>}
            </div>
            <StepText step={step} spans={spans} />
            {flagged.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-xs text-[var(--muted)]">
                {flagged.map((s, i) => (
                  <li key={i}>{spanLabel(s)}</li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function ReplayCard({ replay }: { replay: ReplayResult | null }) {
  const label = replay?.result ?? "unavailable";
  const icon = label === "changed" ? "⚠" : label === "unchanged" ? "✓" : "?";
  return (
    <section className={card} aria-labelledby="replay-h">
      <h2 id="replay-h" className={h2}>Counterfactual replay</h2>
      <p className="font-semibold">
        <span aria-hidden="true">{icon} </span>
        {label.charAt(0).toUpperCase() + label.slice(1)}
      </p>
      {replay ? (
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-sm">
          <dt className="text-[var(--muted)]">Original choice</dt>
          <dd className="break-all">{replay.original_product_id ?? "none"}</dd>
          <dt className="text-[var(--muted)]">Replay choice</dt>
          <dd className="break-all">{replay.replay_product_id ?? "none"}</dd>
          <dt className="text-[var(--muted)]">Spans removed</dt>
          <dd>{replay.removed_span_count}</dd>
          {replay.reason && (
            <>
              <dt className="text-[var(--muted)]">Reason</dt>
              <dd className="break-words">{replay.reason}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="text-sm text-[var(--muted)]">No replay was run for this case.</p>
      )}
    </section>
  );
}

function FindingsList({ title, findings }: { title: string; findings: Finding[] }) {
  if (findings.length === 0) return null;
  return (
    <section className={card}>
      <h2 className={h2}>{title}</h2>
      <ul className="space-y-2">
        {findings.map((f, i) => (
          <li key={i} className="text-sm">
            <span className="font-semibold">{f.kind}</span>
            {f.method && <span className="text-[var(--muted)]"> · {f.method}</span>}
            <p className="break-words">{f.detail}</p>
            {f.field && <p className="break-words text-xs text-[var(--muted)]">Field: {f.field}</p>}
            {f.step_ids.length > 0 && <p className="break-words text-xs text-[var(--muted)]">Steps: {f.step_ids.join(", ")}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Detail({ data }: { data: CaseDetailResponse }) {
  const { case: c, report: r } = data;
  const rows = intentVsCart(c);
  return (
    <div className="space-y-4">
      <section className={card} aria-labelledby="verdict-h">
        <h1 id="verdict-h" className="sr-only">Case {c.case_id}</h1>
        <div className="flex flex-wrap items-center gap-2">
          <VerdictBadge verdict={r.verdict} />
          <span className="text-sm">Confidence: <strong>{r.confidence}</strong></span>
          <span className="text-sm">Rule: <code>{r.rule_id}</code></span>
        </div>
        <p className="mt-2 break-words">{summarize(r)}</p>
        <p className="mt-1 break-all text-xs text-[var(--muted)]">{c.case_id}</p>
        <a
          href={evidenceUrl(c.case_id)}
          download
          className="mt-3 inline-block rounded bg-[var(--accent-bg)] px-4 py-2 text-sm font-semibold text-[var(--on-accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
        >
          Download evidence
        </a>
      </section>

      <section className={card} aria-labelledby="ivc-h">
        <h2 id="ivc-h" className={h2}>Intent versus cart</h2>
        <p className="mb-2 break-words text-sm italic">“{c.intent.natural_language}”</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[20rem] text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th scope="col" className="py-1 pr-2">Field</th>
                <th scope="col" className="py-1 pr-2">Intent</th>
                <th scope="col" className="py-1 pr-2">Cart</th>
                <th scope="col" className="py-1 whitespace-nowrap">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.field}
                  className={`border-b border-[var(--border)] align-top ${
                    row.match ? "" : "bg-red-100 font-semibold text-red-900 dark:bg-red-950 dark:text-red-200"
                  }`}
                >
                  <th scope="row" className="py-1 pr-2 font-medium break-words">{row.field}</th>
                  <td className="py-1 pr-2 break-words">{row.intent}</td>
                  <td className="py-1 pr-2 break-words">{row.cart}</td>
                  <td className="py-1 whitespace-nowrap">{row.match ? "✓ OK" : "✗ Violation"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="trace-h">
        <h2 id="trace-h" className={h2}>Agent trace</h2>
        <p className="mb-2 text-xs text-[var(--muted)]">
          Dashed amber steps come from untrusted sources. ⚑ marks flagged text; hover or focus it for the reason.
        </p>
        {c.trace.length === 0 ? (
          <p className="text-sm text-[var(--muted)]">No trace recorded.</p>
        ) : (
          <Timeline trace={c.trace} spans={r.detection_spans} />
        )}
      </section>

      <ReplayCard replay={r.replay} />
      <FindingsList title="Findings" findings={r.findings} />
      <FindingsList title="Secondary findings" findings={r.secondary_findings} />
      {r.findings.length === 0 && r.secondary_findings.length === 0 && (
        <section className={card}>
          <h2 className={h2}>Findings</h2>
          <p className="text-sm text-[var(--muted)]">No findings.</p>
        </section>
      )}
    </div>
  );
}

export default function CaseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setState({ status: "loading" });
    getCase(id)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setState({ status: "notfound" });
        else setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [id, attempt]);

  return (
    <div>
      <Link to="/" className="mb-3 inline-block text-sm text-[var(--accent)] underline">← All cases</Link>
      <div aria-live="polite">
        {state.status === "loading" && <p className="text-[var(--muted)]">Loading case…</p>}
        {state.status === "notfound" && (
          <div role="alert" className="rounded border border-[var(--border)] p-3">
            <h1 className="text-lg font-semibold">Case not found</h1>
            <p className="break-all">No case with id {id} exists.</p>
          </div>
        )}
        {state.status === "error" && (
          <div role="alert" className="rounded border border-red-400 p-3">
            <p className="mb-2">Could not load case: {state.message}</p>
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-sm"
              onClick={() => setAttempt((n) => n + 1)}
            >
              Retry
            </button>
          </div>
        )}
      </div>
      {state.status === "ready" && <Detail data={state.data} />}
    </div>
  );
}
