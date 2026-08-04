import { Routes, Route, NavLink, Link } from "react-router-dom";
import { useAuthStore } from "./stores/auth";
import { HomePage } from "./pages/HomePage";
import { PracticePage } from "./pages/PracticePage";
import { DictationPage } from "./pages/DictationPage";
import { ShanghaiExamPage } from "./pages/ShanghaiExamPage";
import { StatsPage } from "./pages/StatsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LoginPage } from "./pages/LoginPage";
import { AIAssistantPage } from "./pages/AIAssistantPage";
import { DiagnosisPage } from "./pages/DiagnosisPage";

function App() {
  const { user, token } = useAuthStore();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-30 border-b border-gray-200 bg-white/80 backdrop-blur dark:border-gray-800 dark:bg-gray-950/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
          <Link to="/" className="flex items-center gap-2 font-bold text-primary-600">
            <span className="text-xl">Phonos</span>
            <span className="text-xs text-gray-500">v3</span>
          </Link>
          <nav className="flex-1 flex items-center gap-1 text-sm overflow-x-auto">
            <NavItem to="/">首页</NavItem>
            <NavItem to="/practice">练习</NavItem>
            <NavItem to="/dictation">听写</NavItem>
            <NavItem to="/shanghai-exam">上海听说</NavItem>
            <NavItem to="/diagnosis">AI 诊断</NavItem>
            <NavItem to="/assistant">AI 助手</NavItem>
            <NavItem to="/stats">统计</NavItem>
            <NavItem to="/settings">设置</NavItem>
          </nav>
          <div className="text-sm">
            {user ? (
              <span className="text-gray-600 dark:text-gray-300">{user.display_name}</span>
            ) : (
              <Link to="/login" className="btn-secondary">登录</Link>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1 mx-auto max-w-6xl w-full px-4 py-6">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/practice" element={<PracticePage />} />
          <Route path="/dictation" element={<DictationPage />} />
          <Route path="/shanghai-exam" element={<ShanghaiExamPage />} />
          <Route path="/diagnosis" element={<DiagnosisPage />} />
          <Route path="/assistant" element={<AIAssistantPage />} />
          <Route path="/stats" element={<StatsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </main>

      <footer className="border-t border-gray-200 dark:border-gray-800 py-4 text-center text-xs text-gray-500">
        Phonos v3 · 本地优先 · 辅助评估 · 非官方成绩
      </footer>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-3 py-1.5 rounded-md transition-colors ${
          isActive
            ? "bg-primary-50 text-primary-700 dark:bg-primary-900 dark:text-primary-100"
            : "text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export default App;
