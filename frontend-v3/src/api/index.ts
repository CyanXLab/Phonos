import axios from "axios";
import { useAuthStore } from "../stores/auth";

export const api = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  }
);

// ============= API 函数 =============

export const authApi = {
  register: (username: string, password: string, display_name: string) =>
    api.post("/auth/register", { username, password, display_name }),
  login: (username: string, password: string) =>
    api.post("/auth/login", { username, password }),
  logout: () => api.post("/auth/logout"),
  me: () => api.get("/auth/me"),
};

export const sentenceApi = {
  random: () => api.get("/sentence"),
  list: () => api.get("/sentences"),
  byId: (id: number) => api.get(`/sentence/${id}`),
};

export const evaluateApi = {
  v2: (audio: Blob, text: string, provider = "auto", mode = "balanced") => {
    const form = new FormData();
    form.append("audio", audio);
    form.append("sentence_text", text);
    form.append("provider", provider);
    form.append("mode", mode);
    return api.post("/v2/evaluate", form, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 60000,
    });
  },
  providers: () => api.get("/v2/providers"),
};

export const dictationApi = {
  check: (expected: string, actual: string, keywords: string[] = []) =>
    api.post("/v2/dictation/check", { expected, actual, keywords }),
};

export const shanghaiExamApi = {
  taskTypes: () => api.get("/shanghai-exam/task-types"),
  tasks: (params?: Record<string, any>) => api.get("/shanghai-exam/tasks", { params }),
  createSession: (data: { mode: string; task_count?: number; task_types?: string[]; full_exam?: boolean }) =>
    api.post("/shanghai-exam/sessions", data),
  getSession: (id: string) => api.get(`/shanghai-exam/sessions/${id}`),
  submit: (sessionId: string, taskId: string, response: any) =>
    api.post(`/shanghai-exam/sessions/${sessionId}/submit`, { task_id: taskId, response }),
  finish: (sessionId: string) => api.post(`/shanghai-exam/sessions/${sessionId}/finish`),
  report: (sessionId: string) => api.get(`/shanghai-exam/sessions/${sessionId}/report`),
  disclaimer: () => api.get("/shanghai-exam/disclaimer"),
  structure: () => api.get("/shanghai-exam/structure"),
};

export const llmApi = {
  health: () => api.get("/llm/health"),
  score: (data: any) => api.post("/llm/score", data),
};

export const modelsApi = {
  list: () => api.get("/models/"),
  downloadInfo: () => api.get("/models/download-info"),
};

export const dataApi = {
  export: () => api.get("/data/export"),
  purge: () => api.delete("/data/purge"),
  privacy: () => api.get("/data/privacy"),
};

export const healthApi = {
  basic: () => api.get("/health"),
  v2: () => api.get("/health/v2"),
  readiness: () => api.get("/readiness"),
  liveness: () => api.get("/liveness"),
};
