// Client-side derivations for the case detail page. GET /api/cases/{id} returns only {case, report},
// so the summary and intent-vs-cart rows are rebuilt here, mirroring src/intenttrace/evidence.py.
import type { CaseFile, IntentCartRow, Report, Span } from "../types";

const money = (cents: number | null): string => (cents === null ? "none" : `$${(cents / 100).toFixed(2)}`);
const list = (v: string[] | null): string => (v === null ? "any" : [...v].sort().join(", ") || "none");

export function intentVsCart(c: CaseFile): IntentCartRow[] {
  const k = c.intent.constraints;
  const cart = c.cart;
  const rows: IntentCartRow[] = [
    {
      field: "total",
      intent: `max ${money(k.max_total_cents)}`,
      cart: money(cart.total_cents),
      match: k.max_total_cents === null || cart.total_cents <= k.max_total_cents,
    },
  ];
  if (k.max_unit_price_cents !== null) {
    const top = Math.max(0, ...cart.items.map((i) => i.unit_price_cents));
    rows.push({ field: "unit price", intent: `max ${money(k.max_unit_price_cents)}`, cart: money(top), match: top <= k.max_unit_price_cents });
  }
  if (k.max_quantity !== null) {
    const qty = cart.items.reduce((s, i) => s + i.quantity, 0);
    rows.push({ field: "quantity", intent: `max ${k.max_quantity}`, cart: String(qty), match: qty <= k.max_quantity });
  }
  if (k.allowed_categories !== null) {
    const allowed = k.allowed_categories;
    const cats = [...new Set(cart.items.map((i) => i.category))].sort();
    rows.push({ field: "category", intent: list(allowed), cart: list(cats), match: cats.every((x) => allowed.includes(x)) });
  }
  if (k.allowed_merchants !== null) {
    rows.push({ field: "merchant", intent: list(k.allowed_merchants), cart: cart.merchant_id, match: k.allowed_merchants.includes(cart.merchant_id) });
  }
  for (const [key, want] of Object.entries(k.required_attributes).sort(([a], [b]) => (a < b ? -1 : 1))) {
    const got = cart.items.map((i) => i.attributes[key]);
    rows.push({
      field: `attribute:${key}`,
      intent: want,
      cart: got.map((g) => g ?? "missing").join(", ") || "no items",
      match: got.length > 0 && got.every((g) => g === want),
    });
  }
  if (k.expires_at !== null) {
    rows.push({ field: "expires_at", intent: k.expires_at, cart: cart.created_at, match: cart.created_at <= k.expires_at });
  }
  return rows;
}

export function summarize(r: Report): string {
  const detail = (r.findings.find((f) => f.detail)?.detail ?? "").replace(/\.+$/, "");
  const n = r.findings.length;
  switch (r.verdict) {
    case "INTEGRITY_FAILURE":
      return `The mandate chain failed ${n} integrity check(s), so the record cannot be relied on as submitted.${detail ? ` First failure: ${detail}.` : ""} Later analysis stages were not run.`;
    case "OUT_OF_SCOPE":
      return `The cart or payment exceeded the limits set in the signed intent mandate (${n} violation(s)).${detail ? ` First violation: ${detail}.` : ""} Later analysis stages were not run.`;
    case "MERCHANT_MISREPRESENTATION":
      return `The delivered item or later listing differs from the listing shown at purchase in ${n} material way(s).${detail ? ` First difference: ${detail}.` : ""} Later analysis stages were not run.`;
    case "MANIPULATED": {
      let s = `${r.detection_spans.length} span(s) of untrusted content were flagged in the agent's trace.`;
      if (r.replay?.result === "changed")
        s += ` When they were removed and the decision was replayed, the agent chose ${r.replay.replay_product_id} instead of ${r.replay.original_product_id}.`;
      else s += " The purchase differs from the top-ranked eligible product and the influence score is high.";
      return `${s} Confidence is ${r.confidence}.`;
    }
    case "LEGITIMATE": {
      let s = "The mandate chain, scope and listing checks found no problems.";
      if (r.replay?.result === "unchanged") s += " Replaying the decision without flagged content produced the same choice.";
      else if (r.detection_spans.length) s += " Some flagged content was present, but the purchase is not explained by it.";
      else s += " No untrusted content was flagged and the choice matches the top-ranked product.";
      if (r.confidence === "low") s += " The choice differs from the best match, but no cause was found.";
      return `${s} Confidence is ${r.confidence}.`;
    }
    default:
      return "The available evidence did not meet the criteria for any other verdict. Manual review of the findings is needed.";
  }
}

export interface Segment {
  text: string;
  spans: Span[];
}

/** Split content into segments by span boundaries. Offsets are Python code points, so use Array.from. */
export function segment(content: string, spans: Span[]): Segment[] {
  const chars = Array.from(content);
  const len = chars.length;
  const cuts = new Set<number>([0, len]);
  const clamped = spans.map((s) => ({ s, a: Math.max(0, Math.min(s.start, len)), b: Math.max(0, Math.min(s.end, len)) }));
  for (const { a, b } of clamped) {
    cuts.add(a);
    cuts.add(b);
  }
  const pts = [...cuts].sort((x, y) => x - y);
  const out: Segment[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const from = pts[i];
    const to = pts[i + 1];
    if (to <= from) continue;
    out.push({
      text: chars.slice(from, to).join(""),
      spans: clamped.filter(({ a, b }) => a <= from && b >= to && b > a).map(({ s }) => s),
    });
  }
  return out;
}
