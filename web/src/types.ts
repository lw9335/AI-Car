export type Role =
  | "admin"
  | "information_officer"
  | "expert"
  | "dispatcher"
  | "parts_manager"
  | "technician"
  | "operations";

export type User = {
  user_id: string;
  username: string;
  role: Role;
  region: string;
};

export type Evidence = {
  evidence_id: string;
  title: string;
  section: string;
  excerpt: string;
  score: number;
};

export type Approval = {
  approval_id: string;
  action: string;
  requested_role: Role;
  status: string;
  token: string;
};

export type DispatchCandidate = {
  resource_id: string;
  display_name: string;
  eta_minutes: number;
  workload: number;
  score: number;
};

export type PartCandidate = {
  part_code: string;
  name: string;
  source: string;
  stock: number;
  unit_price: number;
  is_oem: boolean;
};

export type TaskItem = {
  task_id: string;
  domain: string;
  action: string;
  status: string;
  depends_on: string[];
};

export type WorkOrder = {
  service_request_id: string;
  thread_id: string;
  version: number;
  status: string;
  degraded_mode: boolean;
  vehicle: {
    brand: string;
    model: string;
    vin: string;
    power_type: string;
  };
  dtc_codes: string[];
  symptom: string;
  diagnosis?: {
    diagnosis_id: string;
    hypotheses: { code: string; title: string; confidence: number }[];
    evidence: Evidence[];
    confirmed_code?: string | null;
  };
  task_plan?: {
    plan_version: number;
    tasks: TaskItem[];
  };
  approvals: Approval[];
  dispatch_candidates: DispatchCandidate[];
  parts_candidates: PartCandidate[];
  selected_resource_id?: string | null;
  reserved_part_codes: string[];
};

export type TraceSpan = {
  span_id: string;
  name: string;
  kind: string;
  status: string;
};

export type OpsResult = Record<string, unknown>;

export type AssistantExecution = {
  capability: string;
  operation: string;
  result: Record<string, unknown>;
};

export type AssistantChatResponse = {
  conversation_id: string;
  turn_id: string;
  mode: "deterministic" | "deep_agents";
  intent: string;
  content: string;
  available_capabilities: string[];
  executed_actions: AssistantExecution[];
  requires_follow_up: boolean;
};
