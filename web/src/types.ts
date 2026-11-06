// TypeScript mirrors of the Python models: intenttrace/models.py, pipeline.py, verdict.py,
// evidence.py, forensics/*, checks/*, bench.py. Money is integer cents; times are ISO 8601 UTC.

// --- CaseFile (models.py) ---
export interface Constraint {
  max_total_cents: number | null;
  max_unit_price_cents: number | null;
  allowed_categories: string[] | null;
  allowed_merchants: string[] | null;
  max_quantity: number | null;
  required_attributes: Record<string, string>;
  expires_at: string | null;
}

export interface IntentMandate {
  mandate_id: string;
  user_id: string;
  natural_language: string;
  constraints: Constraint;
  human_present: boolean;
  created_at: string;
  signer: "user";
  signature: string;
}

export interface CartItem {
  product_id: string;
  title: string;
  category: string;
  unit_price_cents: number;
  quantity: number;
  attributes: Record<string, string>;
}

export interface CartMandate {
  mandate_id: string;
  intent_mandate_hash: string;
  merchant_id: string;
  items: CartItem[];
  total_cents: number;
  created_at: string;
  signer: "user" | "agent";
  signature: string;
}

export interface PaymentMandate {
  mandate_id: string;
  cart_mandate_hash: string;
  amount_cents: number;
  payment_method_token: string;
  agent_involved: boolean;
  created_at: string;
  signer: "user" | "agent";
  signature: string;
}

export type TraceKind = "instruction" | "observe" | "think" | "tool_call" | "decide";
export type TraceSource = "user" | "merchant" | "review" | "external_agent" | "agent";

export interface TraceStep {
  step_id: string;
  kind: TraceKind;
  source: TraceSource;
  content: string;
  product_id: string | null;
  timestamp: string;
}

export interface ListingSnapshot {
  product_id: string;
  merchant_id: string;
  title: string;
  description: string;
  unit_price_cents: number;
  category: string;
  attributes: Record<string, string>;
  captured_at: string;
}

export interface DeliveredItem {
  product_id: string;
  attributes: Record<string, string>;
}

export interface AgentConfig {
  agent_type: "scripted" | "llm";
  seed: number;
  susceptibility: Record<string, number>;
  model: string | null;
  system_prompt: string | null;
}

export interface CaseFile {
  case_id: string;
  public_keys: Record<string, string>;
  intent: IntentMandate;
  cart: CartMandate;
  payment: PaymentMandate;
  trace: TraceStep[];
  listings_at_purchase: ListingSnapshot[];
  listing_after: ListingSnapshot | null;
  delivered: DeliveredItem | null;
  agent_config: AgentConfig | null;
}

// --- Findings and spans (models.py) ---
export type DetectionMethod = "rule" | "llm";

export interface Span {
  step_id: string;
  start: number;
  end: number;
  rule_id: string | null;
  reason: string | null;
  method: DetectionMethod | null;
}

export interface Finding {
  kind: string;
  detail: string;
  field: string | null;
  expected: unknown;
  actual: unknown;
  step_ids: string[];
  spans: Span[];
  method: DetectionMethod | "deterministic" | null;
}

// --- Report (pipeline.py, verdict.py) ---
export type VerdictLabel =
  | "LEGITIMATE"
  | "MANIPULATED"
  | "OUT_OF_SCOPE"
  | "MERCHANT_MISREPRESENTATION"
  | "INTEGRITY_FAILURE"
  | "INCONCLUSIVE";

export const VERDICT_LABELS: readonly VerdictLabel[] = [
  "LEGITIMATE",
  "MANIPULATED",
  "OUT_OF_SCOPE",
  "MERCHANT_MISREPRESENTATION",
  "INTEGRITY_FAILURE",
  "INCONCLUSIVE",
];

export type Confidence = "high" | "medium" | "low";

export type ReplayOutcome = "changed" | "unchanged" | "unavailable";

export interface ReplayResult {
  result: ReplayOutcome;
  original_product_id: string | null;
  replay_product_id: string | null;
  removed_span_count: number;
  reason: string | null;
}

export interface RankedProduct {
  product_id: string;
  score: number;
  unit_price_cents: number;
}

export interface DeviationResult {
  top_ranked_product_id: string | null;
  top: RankedProduct[];
  chosen_product_id: string | null;
  deviation: boolean;
  eligible_count: number;
}

export interface InfluenceResult {
  lexical: number;
  llm_score: number | null;
  influence: number;
  evidence_step_ids: string[];
  findings: Finding[];
}

export interface IntegrityResult {
  ok: boolean;
  failures: Finding[];
}

export interface ScopeResult {
  ok: boolean;
  violations: Finding[];
}

export interface MerchantResult {
  ok: boolean;
  material: Finding[];
  non_material: Finding[];
  skipped: string[];
}

export interface StageNote {
  stage: string;
  status: "ran" | "skipped";
  reason: string | null;
}

export interface Report {
  case_id: string;
  verdict: VerdictLabel;
  confidence: Confidence;
  rule_id: string;
  findings: Finding[];
  secondary_findings: Finding[];
  detection_spans: Span[];
  deviation: DeviationResult | null;
  influence: InfluenceResult | null;
  replay: ReplayResult | null;
  integrity: IntegrityResult | null;
  scope: ScopeResult | null;
  merchant: MerchantResult | null;
  stages: StageNote[];
  skipped_notes: string[];
  provider: string | null;
  model: string | null;
  early_exit: boolean;
}

// --- Evidence packet (evidence.py) ---
export interface IntentCartRow {
  field: string;
  intent: string;
  cart: string;
  match: boolean;
}

export interface FlaggedExcerpt {
  step_id: string;
  source: string;
  start: number;
  end: number;
  text: string;
  rule_id: string | null;
  reason: string | null;
  method: string | null;
}

export interface EvidencePacket {
  case_id: string;
  verdict: VerdictLabel;
  confidence: Confidence;
  rule_id: string;
  summary: string;
  findings: Finding[];
  secondary_findings: Finding[];
  intent_vs_cart: IntentCartRow[];
  flagged_excerpts: FlaggedExcerpt[];
  replay: ReplayResult | null;
  generated_at: string;
  tool_version: string;
  notice: string;
}

// --- API responses (api.py) ---
export interface InvestigateResponse {
  case_id: string;
  report: Report;
}

export interface CaseListItem {
  case_id: string;
  verdict: VerdictLabel;
  confidence: Confidence;
  created_at: string;
  summary: string;
}

export interface CaseDetailResponse {
  case: CaseFile;
  report: Report;
}

// --- Benchmark results (bench.py, benchmark/results.json) ---
export interface VerdictMetrics {
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

export interface AttackRecall {
  caught: number;
  recall: number;
  support: number;
}

export interface LatencyMs {
  p50: number;
  p95: number;
}

export interface LlmUsage {
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface BenchPass {
  n: number;
  /** confusion_matrix[truth][predicted] = count */
  confusion_matrix: Record<string, Record<string, number>>;
  coverage: number;
  false_accusation_rate: number;
  macro_f1: number;
  latency_ms: LatencyMs;
  llm: LlmUsage;
  manipulated_recall_by_attack: Record<string, AttackRecall>;
  per_verdict: Record<string, VerdictMetrics>;
}

export interface BenchResults {
  date: string;
  n: number;
  seed: number;
  provider: string;
  model: string | null;
  prompt_version: string;
  /** True when numbers come from the fake provider: pipeline tests, not model accuracy. */
  pipeline_test_only: boolean;
  llm: LlmUsage;
  replay_on: BenchPass;
  replay_off: BenchPass;
}
