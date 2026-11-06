import type { VerdictLabel } from "../types";

const STYLES: Record<VerdictLabel, string> = {
  LEGITIMATE: "bg-emerald-100 text-emerald-900 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-700",
  MANIPULATED: "bg-red-100 text-red-900 border-red-300 dark:bg-red-950 dark:text-red-200 dark:border-red-700",
  OUT_OF_SCOPE: "bg-amber-100 text-amber-900 border-amber-300 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-700",
  MERCHANT_MISREPRESENTATION: "bg-orange-100 text-orange-900 border-orange-300 dark:bg-orange-950 dark:text-orange-200 dark:border-orange-700",
  INTEGRITY_FAILURE: "bg-purple-100 text-purple-900 border-purple-300 dark:bg-purple-950 dark:text-purple-200 dark:border-purple-700",
  INCONCLUSIVE: "bg-slate-100 text-slate-800 border-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-600",
};

export function verdictText(verdict: VerdictLabel): string {
  return verdict.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export default function VerdictBadge({ verdict }: { verdict: VerdictLabel }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${STYLES[verdict]}`}
    >
      {verdictText(verdict)}
    </span>
  );
}
