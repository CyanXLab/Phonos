import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authApi } from "../api";
import { useAuthStore } from "../stores/auth";

export function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const r = mode === "register"
        ? await authApi.register(username, password, displayName)
        : await authApi.login(username, password);
      setAuth(r.data.user, r.data.token);
      navigate("/");
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto">
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">
          {mode === "login" ? "登录" : "注册"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-sm font-medium block mb-1">用户名</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="input"
              required
              minLength={3}
              maxLength={20}
            />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input"
              required
              minLength={mode === "register" ? 8 : 1}
            />
            {mode === "register" && (
              <p className="text-xs text-gray-500 mt-1">至少 8 位，包含大小写字母和数字</p>
            )}
          </div>
          {mode === "register" && (
            <div>
              <label className="text-sm font-medium block mb-1">显示名（可选）</label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="input"
              />
            </div>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" disabled={loading} className="btn-primary w-full">
            {loading ? "处理中..." : (mode === "login" ? "登录" : "注册")}
          </button>
        </form>
        <div className="text-center mt-4 text-sm">
          <button
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="text-primary-600 hover:underline"
          >
            {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
          </button>
        </div>
      </div>
    </div>
  );
}
