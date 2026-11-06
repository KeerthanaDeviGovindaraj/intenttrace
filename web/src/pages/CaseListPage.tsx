import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listCases } from "../api";
import VerdictBadge, { verdictText } from "../components/VerdictBadge";
import { VERDICT_LABELS } from "../types";
import type { CaseListItem, VerdictLabel } from "../types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; cases: CaseListItem[] };

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function CaseListPage() {
  const [filter, setFilter] = useState<VerdictLabel | undefined>(undefined);
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    listCases(filter)
      .then((cases) => {
        if (!cancelled) setState({ status: "ready", cases });
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setState({ status: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [filter, attempt]);

  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1.5 text-sm ${
      active
        ? "border-[var(--accent-bg)] bg-[var(--accent-bg)] text-[var(--on-accent)]"
        : "border-[var(--border)] bg-[var(--surface)]"
    }`;

  return (
    <section>
      <h1 className="mb-3 text-xl font-semibold">Cases</h1>
      <div role="group" aria-label="Filter by verdict" className="mb-4 flex flex-wrap gap-2">
        <button type="button" aria-pressed={filter === undefined} className={chip(filter === undefined)} onClick={() => setFilter(undefined)}>
          All
        </button>
        {VERDICT_LABELS.map((v) => (
          <button key={v} type="button" aria-pressed={filter === v} className={chip(filter === v)} onClick={() => setFilter(v)}>
            {verdictText(v)}
          </button>
        ))}
      </div>

      <div aria-live="polite">
        {state.status === "loading" && <p className="text-[var(--muted)]">Loading cases…</p>}
        {state.status === "error" && (
          <div role="alert" className="rounded border border-red-400 p-3">
            <p className="mb-2">Could not load cases: {state.message}</p>
            <button type="button" className={chip(false)} onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          </div>
        )}
        {state.status === "ready" && state.cases.length === 0 && (
          <p className="text-[var(--muted)]">
            {filter ? `No ${verdictText(filter)} cases found.` : "No cases yet."}
          </p>
        )}
        {state.status === "ready" && state.cases.length > 0 && (
          <ul className="space-y-2">
            {state.cases.map((c) => (
              <li key={c.case_id}>
                <Link
                  to={`/cases/${encodeURIComponent(c.case_id)}`}
                  className="block rounded border border-[var(--border)] bg-[var(--surface)] p-3 hover:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <VerdictBadge verdict={c.verdict} />
                    <span className="text-xs text-[var(--muted)]">Confidence: {c.confidence}</span>
                    <time dateTime={c.created_at} className="text-xs text-[var(--muted)] sm:ml-auto">
                      {formatDate(c.created_at)}
                    </time>
                  </div>
                  <p className="mt-2 break-words text-sm">{c.summary}</p>
                  <p className="mt-1 break-all text-xs text-[var(--muted)]">{c.case_id}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
