import { useEffect, useState } from "react";
import { decisionEvidenceUrl, getChainStatus, listDecisions } from "../api";
import DecisionBadge, { decisionText } from "../components/DecisionBadge";
import type { ChainStatus, DecisionLabel, DecisionRecordItem } from "../types";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; records: DecisionRecordItem[]; chain: ChainStatus | null };

const DECISIONS: DecisionLabel[] = ["ALLOW", "BLOCK", "ASK_HUMAN"];

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export default function DecisionsPage() {
  const [filter, setFilter] = useState<DecisionLabel | undefined>(undefined);
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Promise.all([listDecisions(filter), getChainStatus().catch(() => null)])
      .then(([records, chain]) => {
        if (!cancelled) setState({ status: "ready", records, chain });
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
      <h1 className="mb-3 text-xl font-semibold">Decisions</h1>

      {state.status === "ready" && state.chain && (
        <p
          role="status"
          className={`mb-4 rounded border p-3 text-sm ${
            state.chain.valid
              ? "border-emerald-300 bg-emerald-100 text-emerald-900 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
              : "border-red-300 bg-red-100 text-red-900 dark:border-red-700 dark:bg-red-950 dark:text-red-200"
          }`}
        >
          {state.chain.valid
            ? `Log verified (${state.chain.count} records)`
            : `Log tampered, first bad record: ${state.chain.first_invalid_id ?? "unknown"}`}
        </p>
      )}

      <div role="group" aria-label="Filter by decision" className="mb-4 flex flex-wrap gap-2">
        <button type="button" aria-pressed={filter === undefined} className={chip(filter === undefined)} onClick={() => setFilter(undefined)}>
          ALL
        </button>
        {DECISIONS.map((d) => (
          <button key={d} type="button" aria-pressed={filter === d} className={chip(filter === d)} onClick={() => setFilter(d)}>
            {d}
          </button>
        ))}
      </div>

      <div aria-live="polite">
        {state.status === "loading" && <p className="text-[var(--muted)]">Loading decisions…</p>}
        {state.status === "error" && (
          <div role="alert" className="rounded border border-red-400 p-3">
            <p className="mb-2">Could not load decisions: {state.message}</p>
            <button type="button" className={chip(false)} onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          </div>
        )}
        {state.status === "ready" && state.records.length === 0 && (
          <p className="text-[var(--muted)]">
            {filter ? `No ${decisionText(filter)} decisions found.` : "No PayGate decisions yet."}
          </p>
        )}
        {state.status === "ready" && state.records.length > 0 && (
          <ul className="space-y-2">
            {state.records.map((r) => {
              const open = expanded === r.record_id;
              const panelId = `decision-${r.record_id}`;
              return (
                <li key={r.record_id} className="rounded border border-[var(--border)] bg-[var(--surface)]">
                  <button
                    type="button"
                    aria-expanded={open}
                    aria-controls={panelId}
                    onClick={() => setExpanded(open ? null : r.record_id)}
                    className="block w-full p-3 text-left hover:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <DecisionBadge decision={r.decision} />
                      <span className="break-words text-xs text-[var(--muted)]">{r.reason_codes.join(", ")}</span>
                      <time dateTime={r.created_at} className="text-xs text-[var(--muted)] sm:ml-auto">
                        {formatDate(r.created_at)}
                      </time>
                    </div>
                    <p className="mt-2 break-words text-sm">{r.explanation}</p>
                  </button>
                  {open && (
                    <div id={panelId} className="border-t border-[var(--border)] p-3 text-sm">
                      {r.spans.length === 0 ? (
                        <p className="text-[var(--muted)]">No highlighted spans.</p>
                      ) : (
                        <ul className="space-y-1">
                          {r.spans.map((s, i) => (
                            <li key={i} className="break-all">
                              <code>
                                {s.item_id} [{s.start}:{s.end}] {s.rule_id}
                              </code>
                            </li>
                          ))}
                        </ul>
                      )}
                      <p className="mt-2 break-all text-xs text-[var(--muted)]">{r.record_id}</p>
                      <a
                        href={decisionEvidenceUrl(r.record_id)}
                        download
                        className="mt-3 inline-block rounded bg-[var(--accent-bg)] px-4 py-2 text-sm font-semibold text-[var(--on-accent)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                      >
                        Download evidence
                      </a>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
