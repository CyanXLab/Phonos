import { useQuery } from "@tanstack/react-query";
import { modelsApi, dataApi } from "../api";

export function SettingsPage() {
  const { data: models } = useQuery({
    queryKey: ["models"],
    queryFn: () => modelsApi.list().then((r) => r.data),
  });

  const { data: privacy } = useQuery({
    queryKey: ["privacy"],
    queryFn: () => dataApi.privacy().then((r) => r.data),
  });

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-4">模型与 Provider</h2>
        {models && (
          <div className="space-y-3 text-sm">
            <div>
              <strong>HuPER 模型：</strong>
              <span className="text-gray-600 dark:text-gray-300 ml-2">
                {models.huper?.path || "未找到"}
              </span>
            </div>
            <div>
              <strong>Whisper：</strong>
              <span className="text-gray-600 dark:text-gray-300 ml-2">
                {models.whisper?.enabled ? `${models.whisper.model_size} (${models.whisper.compute_type})` : "未启用"}
              </span>
            </div>
            <div>
              <strong>VAD：</strong>
              <span className="text-gray-600 dark:text-gray-300 ml-2">
                {models.vad?.model_path || "自动"}
              </span>
            </div>
            <div>
              <strong>商业 API：</strong>
              <div className="ml-4 mt-1">
                {Object.entries(models.commercial_apis_enabled || {}).map(([k, v]: any) => (
                  <div key={k} className="text-xs">
                    {k}: {v ? "✓ 启用" : "✗ 关闭"}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-4">隐私</h2>
        {privacy && (
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
              <a href="/api/data/export" className="btn-secondary" download>
                导出我的数据
              </a>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold mb-4">下载信息</h2>
        <DownloadInfo />
      </div>
    </div>
  );
}

function DownloadInfo() {
  const { data } = useQuery({
    queryKey: ["download-info"],
    queryFn: () => modelsApi.downloadInfo().then((r) => r.data),
  });

  if (!data) return <div>加载中...</div>;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-medium mb-2 text-sm">本地模型</h3>
        <div className="space-y-2">
          {data.models?.map((m: any, i: number) => (
            <div key={i} className="p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs">
              <div className="font-medium">{m.name}</div>
              <div className="text-gray-500">
                许可证: {m.license} | 大小: {m.size_mb} | 联网: {m.online ? "是" : "否"}
              </div>
              <div className="text-gray-500">下载: {m.download}</div>
              <div className="text-gray-500">回退: {m.fallback}</div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3 className="font-medium mb-2 text-sm">商业 API</h3>
        <div className="space-y-2">
          {data.commercial_apis?.map((m: any, i: number) => (
            <div key={i} className="p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs">
              <div className="font-medium">{m.name}</div>
              <div className="text-gray-500">
                许可证: {m.license} | 需要 Key: {m.requires_key ? "是" : "否"} | 默认启用: {m.default_enabled ? "是" : "否"}
              </div>
              <div className="text-yellow-600 dark:text-yellow-400">隐私: {m.privacy}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
