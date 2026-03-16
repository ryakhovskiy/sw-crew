/** Typed API client for the AI Dev Crew Gateway. */

const BASE = '';  // Same origin, proxied by Vite in dev

function headers(): HeadersInit {
  const token = localStorage.getItem('crew_token') || 'change-me';
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { ...init, headers: headers() });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

// --- Types ---

export interface Task {
  id: string;
  title: string;
  phase: string;
  status: string;
  agent: string | null;
  created_at: number;
  updated_at: number;
  debug_attempts: number;
  total_cost_usd: number;
}

export interface TaskDetail extends Task {
  body: string;
  artifacts: { name: string; path: string; created_at: number }[];
  gates: GateInfo[];
}

export interface GateInfo {
  id: string;
  task_id?: string;
  type: string;
  status: string;
  artifact: string | null;
  question: string | null;
  answer: string | null;
  comment: string | null;
  reason: string | null;
  created_at: number;
  resolved_at: number | null;
}

export interface HealthStatus {
  status: string;
  gateway: boolean;
  orchestrator: boolean;
  database: boolean;
  queue_depth: number;
  active_agents: string[];
  circuit_breakers: Record<string, string>;
  total_cost_usd: number;
  tasks_completed: number;
  tasks_failed: number;
  uptime_seconds: number;
}

// --- API methods ---

export const api = {
  listTasks: (status?: string) =>
    request<Task[]>(status ? `/tasks?status=${status}` : '/tasks'),

  getTask: (id: string) =>
    request<TaskDetail>(`/tasks/${id}`),

  createTask: (body: string, title?: string) =>
    request<{ task_id: string }>('/tasks', {
      method: 'POST',
      body: JSON.stringify({ body, title: title || undefined }),
    }),

  getArtifact: async (taskId: string, name: string): Promise<string> => {
    const resp = await fetch(`${BASE}/tasks/${taskId}/artifacts/${name}`, {
      headers: headers(),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    return resp.text();
  },

  listGates: (status?: string) =>
    request<GateInfo[]>(status ? `/gates?status=${status}` : '/gates'),

  approveGate: (gateId: string, comment?: string) =>
    request<{ ok: boolean }>(`/gates/${gateId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ comment: comment || null }),
    }),

  rejectGate: (gateId: string, reason: string) =>
    request<{ ok: boolean }>(`/gates/${gateId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  answerGate: (gateId: string, message: string) =>
    request<{ ok: boolean }>(`/gates/${gateId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  health: () => request<HealthStatus>('/health'),

  taskCosts: (taskId: string) =>
    request<{ task_id: string; total_usd: number; agents: { agent: string; input_tokens: number; output_tokens: number; cost_usd: number }[] }>(`/tasks/${taskId}/costs`),

  searchTasks: (params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString();
    return request<Task[]>(`/tasks/search?${qs}`);
  },
};
