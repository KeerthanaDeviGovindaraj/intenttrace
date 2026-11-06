type DecisionLabel = "ALLOW" | "BLOCK" | "ASK_HUMAN";

const STYLES: Record<DecisionLabel, string> = {
  ALLOW: "bg-emerald-100 text-emerald-900 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-700",
  BLOCK: "bg-red-100 text-red-900 border-red-300 dark:bg-red-950 dark:text-red-200 dark:border-red-700",
  ASK_HUMAN: "bg-amber-100 text-amber-900 border-amber-300 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-700",
};

export function decisionText(decision: DecisionLabel): string {
  return decision.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export default function DecisionBadge({ decision }: { decision: DecisionLabel }) {
  return (
    <span
      className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${STYLES[decision]}`}
    >
      {decisionText(decision)}
    </span>
  );
}
