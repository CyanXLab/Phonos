import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { shanghaiExamApi, modelsApi, dataApi, evaluateApi } from "../api";

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"models" | "llm" | "privacy" | "exam" | "download">("models");

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">设置中心</h2>
        <div className="flex gap-2 border-b border-gray-200 dark:border-gray-800 mb-4 overflow-x-auto">
          <TabButton active={activeTab === "models"} onClick={() => setActiveTab("models")}>模型</TabButton>
          <TabButton active={activeTab === "llm"} onClick={() => setActiveTab("llm")}>LLM 评分</TabButton>
          <TabButton active={activeTab === "privacy"} onClick={() => setActiveTab("privacy")}>隐私</TabButton>
          <TabButton active={activeTab === "exam"} onClick={() => setActiveTab("exam")}>上海考试</TabButton>
          <TabButton active={activeTab === "download"} onClick={() => setActiveTab("download")}>下载信息</TabButton>
        </div>

        {activeTab === "models" && <ModelsTab />}
        {activeTab === "llm" && <LLMTab />}
        {activeTab === "privacy" && <PrivacyTab />}
        {activeTab === "exam" && <ExamStructureTab />}
        {activeTab === "download" && <DownloadTab />}
      </div>
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
        active
          ? "border-primary-600 text-primary-600"
          : "border-transparent text-gray-500 hover:text-gray-700"
      }`}
    >
      {children}
    </button>
  );
}

function ModelsTab() {
  const { data: models, isLoading } = useQuery({
    queryKey: ["models"],
    queryFn: () => modelsApi.list().then((r) => r.data),
  });

  if (isLoading) return <div>加载中...</div>;
  if (!models) return <div>加载失败</div>;

  return (
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ModelCard
          name="HuBERT-large INT8"
          desc="音素识别（CTC）"
          path={models.huper?.path}
          available={!!models.huper?.path}
          size="347 MB"
          license="MIT"
        />
        <ModelCard
          name="silero-vad"
          desc="语音活动检测"
          path={models.vad?.model_path}
          available={models.vad?.model_path !== "auto"}
          size="319 KB"
          license="MIT/CC-BY-4.0"
        />
        <ModelCard
          name="faster-whisper"
          desc="听力理解 ASR"
          path={`models/whisper/${models.whisper?.model_size || "base"}`}
          available={models.whisper?.enabled}
          size={models.whisper?.model_size === "small" ? "480 MB" : "141 MB"}
          license="MIT"
        />
        <ModelCard
          name="opus-mt-en-zh"
          desc="英译中"
          path="models/opus_mt_en_zh"
          available={true}
          size="298 MB"
          license="CC-BY-4.0"
        />
        <ModelCard
          name="g2p-en + CMUdict"
          desc="文本转音素"
          path="~/.cache/g2p_en + nltk_data"
          available={models.g2p?.available}
          size="~1 GB"
          license="MIT"
        />
      </div>

      <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
        <h4 className="font-medium mb-2">商业 API（默认全关闭）</h4>
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(models.commercial_apis_enabled || {}).map(([k, v]: any) => (
            <div key={k} className={`p-2 rounded text-xs ${v ? "bg-green-50 text-green-700" : "bg-gray-50 text-gray-500"}`}>
              {k}: {v ? "✓ 启用" : "✗ 关闭"}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ModelCard({ name, desc, path, available, size, license }: any) {
  return (
    <div className="p-3 border border-gray-200 dark:border-gray-800 rounded-lg">
      <div className="flex items-center justify-between mb-1">
        <span className="font-medium">{name}</span>
        <span className={`badge ${available ? "badge-success" : "badge-warning"}`}>
          {available ? "可用" : "缺失"}
        </span>
      </div>
      <div className="text-xs text-gray-500 mb-1">{desc}</div>
      <div className="text-xs text-gray-400">路径: {path || "未配置"}</div>
      <div className="text-xs text-gray-400">大小: {size} | 许可: {license}</div>
    </div>
  );
}

function LLMTab() {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("Qwen/Qwen3.5-122B-A10B");
  const [baseUrl, setBaseUrl] = useState("https://api-inference.modelscope.cn/v1");

  return (
    <div className="space-y-4 text-sm">
      <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded text-blue-700 dark:text-blue-300">
        <strong>LLM 评分说明：</strong>
        <ul className="mt-2 space-y-1 text-xs">
          <li>• 默认使用 ModelScope 云端 Qwen3.5-122B（需 API key）</li>
          <li>• 可选本地 llama.cpp（完全离线）</li>
          <li>• 用于口语应答评分、信息转述评分、听写语义判断</li>
          <li>• 配置后可通过 /api/llm/health 测试连通性</li>
        </ul>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">ModelScope API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="ms-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          className="input"
        />
        <p className="text-xs text-gray-500 mt-1">
          从 https://modelscope.cn 获取，免费额度可用
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Base URL</label>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          className="input"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">模型</label>
        <select value={model} onChange={(e) => setModel(e.target.value)} className="input">
          <option value="Qwen/Qwen3.5-122B-A10B">Qwen3.5-122B-A10B（推荐，ModelScope）</option>
          <option value="Qwen/Qwen2.5-72B-Instruct">Qwen2.5-72B-Instruct（ModelScope）</option>
          <option value="local">local（llama.cpp 本地）</option>
        </select>
      </div>

      <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-yellow-700 dark:text-yellow-300 text-xs">
        <strong>本地 llama.cpp 配置：</strong>
        <ol className="mt-1 list-decimal list-inside space-y-1">
          <li>下载 GGUF 模型（如 Qwen2.5-7B-Instruct-Q4_K_M.gguf）</li>
          <li>运行: llama-server -m model.gguf --port 8080</li>
          <li>设置 LLAMA_CPP_URL=http://127.0.0.1:8080/v1</li>
        </ol>
      </div>

      <button className="btn-primary">保存 LLM 配置</button>
    </div>
  );
}

function PrivacyTab() {
  const { data: privacy } = useQuery({
    queryKey: ["privacy"],
    queryFn: () => dataApi.privacy().then((r) => r.data),
  });

  if (!privacy) return <div>加载中...</div>;

  return (
    <div className="space-y-3 text-sm">
      <div>
        <strong>默认本地模式：</strong>
        <span className="ml-2">{privacy.default_local ? "✓ 是" : "✗ 否"}</span>
      </div>
      <div>
        <strong>上传用户音频：</strong>
        <span className="ml-2">{privacy.upload_user_audio ? "✓ 是（联网）" : "✗ 否（本地）"}</span>
      </div>
      <div className="border-t border-gray-200 dark:border-gray-800 pt-3">
        <strong>用户权利：</strong>
        <ul className="mt-2 space-y-1 text-gray-600 dark:text-gray-300">
          {privacy.user_rights?.map((r: string, i: number) => (
            <li key={i}>• {r}</li>
          ))}
        </ul>
      </div>
      <div className="flex gap-2 pt-3">
        <a href="/api/data/export" className="btn-secondary" download>导出我的数据</a>
      </div>
    </div>
  );
}

function ExamStructureTab() {
  const { data: structure } = useQuery({
    queryKey: ["exam-structure"],
    queryFn: () => shanghaiExamApi.taskTypes().then((r) => r.data),
  });

  if (!structure) return <div>加载中...</div>;

  return (
    <div className="space-y-4 text-sm">
      <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-yellow-700 dark:text-yellow-300 text-xs">
        {structure.disclaimer}
      </div>

      <div>
        <h4 className="font-medium mb-2">考试结构（2025 届起，{structure.total_full_score} 分）</h4>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded">
            <div className="font-medium text-blue-700 dark:text-blue-300">听力部分（25 分，25 分钟）</div>
            <ul className="mt-1 text-xs space-y-1">
              {structure.structure?.listening?.sections?.map((s: string, i: number) => (
                <li key={i}>• {s}</li>
              ))}
            </ul>
          </div>
          <div className="p-3 bg-green-50 dark:bg-green-900/20 rounded">
            <div className="font-medium text-green-700 dark:text-green-300">口语部分（10 分，10 分钟）</div>
            <ul className="mt-1 text-xs space-y-1">
              {structure.structure?.speaking?.tasks?.map((s: string, i: number) => (
                <li key={i}>• {s}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div>
        <h4 className="font-medium mb-2">题型详情</h4>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800">
                <th className="text-left p-2">题型</th>
                <th className="text-left p-2">部分</th>
                <th className="text-right p-2">分值</th>
                <th className="text-right p-2">准备(s)</th>
                <th className="text-right p-2">答题(s)</th>
                <th className="text-right p-2">题数</th>
              </tr>
            </thead>
            <tbody>
              {structure.task_types?.map((t: any) => (
                <tr key={t.type} className="border-b border-gray-100 dark:border-gray-900">
                  <td className="p-2">{t.type}</td>
                  <td className="p-2">{t.section}</td>
                  <td className="p-2 text-right">{t.full_score}</td>
                  <td className="p-2 text-right">{t.timing?.prep || 0}</td>
                  <td className="p-2 text-right">{t.timing?.response || 0}</td>
                  <td className="p-2 text-right">{t.task_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function DownloadTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["download-info"],
    queryFn: () => modelsApi.downloadInfo().then((r) => r.data),
  });

  if (isLoading) return <div>加载中...</div>;
  if (!data) return <div>加载失败</div>;

  return (
    <div className="space-y-4">
      <div>
        <h4 className="font-medium mb-2 text-sm">本地模型（全部开源）</h4>
        <div className="space-y-2">
          {data.models?.map((m: any, i: number) => (
            <div key={i} className="p-3 bg-gray-50 dark:bg-gray-800 rounded text-xs">
              <div className="font-medium">{m.name}</div>
              <div className="text-gray-500 mt-1">
                许可证: {m.license} | 大小: {m.size_mb} | 联网: {m.online ? "是" : "否"}
              </div>
              <div className="text-gray-500">下载: {m.download}</div>
              <div className="text-gray-500">回退: {m.fallback}</div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h4 className="font-medium mb-2 text-sm">商业 API（默认关闭）</h4>
        <div className="space-y-2">
          {data.commercial_apis?.map((m: any, i: number) => (
            <div key={i} className="p-3 bg-gray-50 dark:bg-gray-800 rounded text-xs">
              <div className="font-medium">{m.name}</div>
              <div className="text-gray-500">
                许可: {m.license} | 需要 Key: {m.requires_key ? "是" : "否"} | 默认: {m.default_enabled ? "启用" : "关闭"}
              </div>
              <div className="text-yellow-600 dark:text-yellow-400 mt-1">隐私: {m.privacy}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
