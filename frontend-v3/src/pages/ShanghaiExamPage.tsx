import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { shanghaiExamApi } from "../api";
import { ExamTimer } from "../components/ExamTimer";
import { useRecorder } from "../hooks/useRecorder";
import { Waveform } from "../components/Waveform";

export function ShanghaiExamPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentTaskIdx, setCurrentTaskIdx] = useState(0);
  const [phase, setPhase] = useState<"prep" | "response" | "done">("prep");
  const [report, setReport] = useState<any>(null);

  const { data: taskTypes } = useQuery({
    queryKey: ["exam-task-types"],
    queryFn: () => shanghaiExamApi.taskTypes().then((r) => r.data),
  });

  const { data: session } = useQuery({
    queryKey: ["exam-session", sessionId],
    queryFn: () => sessionId ? shanghaiExamApi.getSession(sessionId).then((r) => r.data) : null,
    enabled: !!sessionId,
  });

  const createSession = useMutation({
    mutationFn: (mode: "practice" | "exam") =>
      shanghaiExamApi.createSession({ mode, task_count: 5 }).then((r) => r.data),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setCurrentTaskIdx(0);
      setPhase("prep");
      setReport(null);
    },
  });

  const recorder = useRecorder({
    onAudioReady: async (blob) => {
      if (!sessionId || !session) return;
      const task = session.tasks[currentTaskIdx];
      if (!task) return;
      await shanghaiExamApi.submit(sessionId, task.id, {
        audio_blob_size: blob.size,
        score: 75, // 简化：实际需上传音频并评分
        feedback: "已提交",
      });
      if (currentTaskIdx + 1 >= session.tasks.length) {
        await shanghaiExamApi.finish(sessionId);
        const r = await shanghaiExamApi.report(sessionId);
        setReport(r.data);
        setPhase("done");
      } else {
        setCurrentTaskIdx(currentTaskIdx + 1);
        setPhase("prep");
      }
    },
  });

  const currentTask = session?.tasks?.[currentTaskIdx];

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-2">上海听说考试训练</h2>
        <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-sm text-yellow-700 dark:text-yellow-300 mb-4">
          ⚠ 辅助评估，非官方成绩。建议结合教师反馈综合判断。
        </div>

        {!sessionId && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 dark:text-gray-300">
              选择模式开始训练：
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => createSession.mutate("practice")}
                className="btn-primary"
              >
                练习模式（5 题）
              </button>
              <button
                onClick={() => createSession.mutate("exam")}
                className="btn-secondary"
              >
                考试模式（5 题，严格计时）
              </button>
            </div>
          </div>
        )}

        {taskTypes && (
          <div className="mt-4">
            <h3 className="font-medium mb-2 text-sm">支持的任务类型</h3>
            <div className="flex flex-wrap gap-2">
              {taskTypes.task_types.map((t: any) => (
                <span key={t.type} className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                  {t.type} ({t.task_count})
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {session && currentTask && phase !== "done" && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">
              任务 {currentTaskIdx + 1} / {session.tasks.length}
            </span>
            <span className="badge bg-primary-50 text-primary-700 dark:bg-primary-900 dark:text-primary-100">
              {currentTask.type}
            </span>
          </div>

          <div>
            <h3 className="font-semibold">{currentTask.title}</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">{currentTask.prompt}</p>
          </div>

          {currentTask.expected_answer && phase === "prep" && (
            <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded text-sm">
              <strong>题目：</strong> {currentTask.expected_answer}
            </div>
          )}

          {currentTask.timing && (
            <div className="flex items-center justify-between">
              {phase === "prep" ? (
                <>
                  <ExamTimer
                    seconds={currentTask.timing.preparation_sec}
                    variant="prep"
                    onExpire={() => setPhase("response")}
                  />
                  <button
                    onClick={() => setPhase("response")}
                    className="btn-secondary"
                  >
                    跳过准备
                  </button>
                </>
              ) : (
                <ExamTimer
                  seconds={currentTask.timing.response_sec}
                  onExpire={() => recorder.stop()}
                />
              )}
            </div>
          )}

          {phase === "response" && (
            <div className="space-y-3">
              <Waveform
                audioLevel={recorder.audioLevel}
                isRecording={recorder.isRecording}
              />
              {!recorder.isRecording ? (
                <button
                  onClick={recorder.start}
                  disabled={recorder.isInitializing}
                  className="btn-primary"
                >
                  {recorder.isInitializing ? "初始化..." : "开始录音"}
                </button>
              ) : (
                <button onClick={recorder.stop} className="btn-secondary">
                  停止并提交
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {report && (
        <div className="card space-y-4">
          <h3 className="font-semibold text-lg">考试报告</h3>

          <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-sm text-yellow-700 dark:text-yellow-300">
            {report.disclaimer}
          </div>

          <div className="flex items-center gap-6">
            <div className="text-4xl font-bold text-primary-600">
              {report.overall_score.toFixed(0)}
            </div>
            <div>
              <div className="text-sm text-gray-500">总分</div>
              <div className="text-xs text-gray-400">
                用时 {(report.duration_sec / 60).toFixed(1)} 分钟
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(report.dimension_scores).map(([k, v]: any) => (
              <div key={k} className="text-center p-2 bg-gray-50 dark:bg-gray-800 rounded">
                <div className="text-lg font-bold">{v.toFixed(0)}</div>
                <div className="text-xs text-gray-500">{k}</div>
              </div>
            ))}
          </div>

          {report.task_results?.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">各任务详情</h4>
              <div className="space-y-2">
                {report.task_results.map((t: any, i: number) => (
                  <div key={i} className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-800 rounded">
                    <div>
                      <div className="text-sm font-medium">{t.title}</div>
                      <div className="text-xs text-gray-500">{t.task_type}</div>
                    </div>
                    <div className="font-bold">{t.score?.toFixed(0) ?? "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {report.suggestions?.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">建议</h4>
              <ul className="text-sm space-y-1">
                {report.suggestions.map((s: string, i: number) => (
                  <li key={i} className="text-gray-600 dark:text-gray-300">• {s}</li>
                ))}
              </ul>
            </div>
          )}

          <button
            onClick={() => {
              setSessionId(null);
              setReport(null);
            }}
            className="btn-secondary"
          >
            重新开始
          </button>
        </div>
      )}
    </div>
  );
}
