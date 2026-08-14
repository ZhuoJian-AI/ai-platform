/** Shared types for agent platform pages. */

export interface AgentRunRead {
  id: number;
  organization_id: string;
  agent_id: string;
  session_id: string;
  request: string;
  messages: unknown[];
  steps: unknown[];
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  status: string;
  error: string | null;
  judge_score: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
