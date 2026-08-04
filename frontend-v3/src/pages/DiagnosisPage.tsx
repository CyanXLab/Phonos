import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { llmApi } from "../api";

export function DiagnosisPage() {
  const [diagnosis, setDiagnosis] = useState<any>(null);

  // 模拟用户数据（实际应从 /api/stats 获取）
  const mockStats = {
    total_practice: 45,
    avg_score: 72.5,
    recent_trend: "稳定",
    days_active: 12,
  };
  const mockEvaluations = [
    { score: 68, task_type: "read_sentence", date: "2026-08-01" },
    { score: 75, task_type: "quick_response", date: "2026-08-02" },
    { score: 65, task_type: "retell_and_answer", date: "2026-08-03" },
    { score: 80, task_type: "read_passage", date: "2026-08-03" },
  ];
  const mockErrorPhonemes = [
    { phoneme: "TH", error_rate: 0.75, count: 15 },
    { phoneme: "R", error_rate: 0.60, count: 12 },
    { phoneme: "L", error_rate: 0.45, count: 9 },
    { phoneme: "AE", error_rate: 0.40, count: 8 },
  ];
  const mockErrorWords = ["thought", "through", "weather", "library", "comfortable"];
  const mockWeakTasks = ["retell_and_answer", "picture_description"];

  const diagnose = useMutation({
    mutationFn: () =>
      llmApi.diagnoseLearning({
        user_stats: mockStats,
        recent_evaluations: mockEvaluations,
        error_phonemes: mockErrorPhonemes,
        error_words: mockErrorWords,
        weak_task_types: mockWeakTasks,
      }).then((r) => r.data),
    onSuccess: setDiagnosis,
  });

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-2">AI 学习诊断</h2>
        <p className="text-sm text-gray-500 mb-4">
          LLM 分析你的学习数据，给出错误模式、弱项、提分路径和优先行动项。
        </p>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-sm">
          <Stat label="总练习次数" value={mockStats.total_practice} />
          <Stat label="平均分" value={mockStats.avg_score} />
          <Stat label="活跃天数" value={mockStats.days_active} />
          <Stat label="近期趋势" value={mockStats.recent_trend} />
        </div>

        <button
          onClick={() => diagnose.mutate()}
          disabled={diagnose.isPending}
          className="btn-primary"
        >
          {diagnose.isPending ? "AI 诊断中（约 10-30 秒）..." : "生成 AI 诊断报告"}
        </button>
      </div>

      {diagnose.isError && (
        <div className="card bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm">
          诊断失败：{(diagnose.error as any)?.response?.data?.detail || "未知错误"}
        </div>
      )}

      {diagnosis && (
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold mb-2">学习模式分析</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {diagnosis.learning_pattern}
            </p>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">弱项清单</h3>
            <ul className="text-sm space-y-1">
              {diagnosis.weak_areas?.map((a: string, i: number) => (
                <li key={i} className="text-gray-600 dark:text-gray-300">• {a}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">错误根因</h3>
            <ul className="text-sm space-y-1">
              {diagnosis.error_root_causes?.map((c: string, i: number) => (
                <li key={i} className="text-gray-600 dark:text-gray-300">• {c}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">提分路径</h3>
            <div className="space-y-3">
              {diagnosis.improvement_path?.map((stage: any, i: number) => (
                <div key={i} className="p-3 bg-gray-50 dark:bg-gray-800 rounded">
                  <div className="font-medium text-sm">{stage.stage}</div>
                  <div className="text-sm text-gray-600 dark:text-gray-300 mt-1">
                    目标：{stage.goal}
                  </div>
                  <ul className="text-xs mt-1 space-y-0.5">
                    {stage.actions?.map((a: string, j: number) => (
                      <li key={j}>• {a}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">提分潜力</h3>
            <p className="text-sm text-primary-600 font-medium">
              {diagnosis.estimated_potential}
            </p>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-2">本周优先行动</h3>
            <ul className="text-sm space-y-1">
              {diagnosis.priority_actions?.map((a: string, i: number) => (
                <li key={i} className="text-gray-600 dark:text-gray-300">
                  <span className="inline-block w-5 h-5 bg-primary-600 text-white rounded-full text-xs text-center mr-1">
                    {i + 1}
                  </span>
                  {a}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div className="text-center p-2 bg-gray-50 dark:bg-gray-800 rounded">
      <div className="text-xl font-bold">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}
