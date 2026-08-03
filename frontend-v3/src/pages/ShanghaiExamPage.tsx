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

  const { data: structure } = useQuery({
    queryKey: ["exam-structure"],
    queryFn: () => shanghaiExamApi.taskTypes().then((r) => r.data),
  });

  const { data: session } = useQuery({
    queryKey: ["exam-session", sessionId],
    queryFn: () => sessionId ? shanghaiExamApi.getSession(sessionId).then((r) => r.data) : null,
    enabled: !!sessionId,
  });

  const createFullExam = useMutation({
    mutationFn: (mode: "practice" | "exam") =>
      shanghaiExamApi.createSession({ mode, full_exam: true }).then((r) => r.data),
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setCurrentTaskIdx(0);
      setPhase("prep");
      setReport(null);
    },
  });

  const createPractice = useMutation({
    mutationFn: (mode: "practice" | "exam") =>
      shanghaiExamApi.createSession({ mode, full_exam: false, task_count: 5 }).then((r) => r.data),
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
        score: 75,
        feedback: "已提交（评分待接入）",
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
        <h2 className="text-lg font-semibold mb-2">上海高考英语听说考试训练</h2>
        <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-sm text-yellow-700 dark:text-yellow-300 mb-4">
          ⚠ 辅助评估，非官方成绩。2025 届起执行新结构（35 分）。建议结合教师反馈综合判断。
        </div>

        {structure && (
          <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-800 rounded text-sm">
            <div className="font-medium mb-2">考试结构（2025 届起）</div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <strong>听力部分（25 分 / 25 分钟）</strong>
                <ul className="mt-1 space-y-0.5 text-gray-600 dark:text-gray-300">
                  {structure.structure?.listening?.sections?.map((s: string, i: number) => (
                    <li key={i}>• {s}</li>
                  ))}
                </ul>
              </div>
              <div>
                <strong>口语部分（10 分 / 10 分钟）</strong>
                <ul className="mt-1 space-y-0.5 text-gray-600 dark:text-gray-300">
                  {structure.structure?.speaking?.tasks?.map((s: string, i: number) => (
                    <li key={i}>• {s}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {!sessionId && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600 dark:text-gray-300">选择模式开始训练：</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => createFullExam.mutate("exam")}
                disabled={createFullExam.isPending}
                className="btn-primary"
              >
                {createFullExam.isPending ? "创建中..." : "完整套卷（35 分，模拟高考）"}
              </button>
              <button
                onClick={() => createPractice.mutate("practice")}
                disabled={createPractice.isPending}
                className="btn-secondary"
              >
                {createPractice.isPending ? "创建中..." : "练习模式（5 题，按题型）"}
              </button>
            </div>
          </div>
        )}
      </div>

      {session && currentTask && phase !== "done" && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">
              任务 {currentTaskIdx + 1} / {session.tasks.length}（{currentTask.section === "listening" ? "听力" : "口语"}）
            </span>
            <div className="flex items-center gap-2">
              <span className="badge bg-primary-50 text-primary-700 dark:bg-primary-900 dark:text-primary-100">
                {currentTask.type}
              </span>
              <span className="text-xs text-gray-500">满分 {currentTask.full_score} 分</span>
            </div>
          </div>

          <div>
            <h3 className="font-semibold">{currentTask.title}</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">{currentTask.prompt}</p>
            {currentTask.year && (
              <p className="text-xs text-gray-400 mt-1">来源: {currentTask.year}</p>
            )}
          </div>

          {currentTask.expected_answer && phase === "prep" && currentTask.section === "speaking" && (
            <div className="bg-blue-50 dark:bg-blue-900/20 p-3 rounded text-sm">
              <strong>题目内容：</strong> {currentTask.expected_answer}
            </div>
          )}

          {currentTask.options && (
            <div className="space-y-2">
              {currentTask.options.map((opt: string, i: number) => (
                <div key={i} className="p-2 border border-gray-200 dark:border-gray-800 rounded text-sm">
                  {String.fromCharCode(65 + i)}. {opt}
                </div>
              ))}
            </div>
          )}

          {currentTask.timing && (
            <div className="flex items-center justify-between">
              {phase === "prep" ? (
                <>
                  <ExamTimer
                    seconds={currentTask.timing.prep}
                    variant="prep"
                    onExpire={() => setPhase("response")}
                  />
                  <button onClick={() => setPhase("response")} className="btn-secondary">跳过准备</button>
                </>
              ) : (
                <ExamTimer
                  seconds={currentTask.timing.response}
                  onExpire={() => recorder.stop()}
                />
              )}
            </div>
          )}

          {phase === "response" && currentTask.section === "speaking" && (
            <div className="space-y-3">
              <Waveform audioLevel={recorder.audioLevel} isRecording={recorder.isRecording} />
              {!recorder.isRecording ? (
                <button onClick={recorder.start} disabled={recorder.isInitializing} className="btn-primary">
                  {recorder.isInitializing ? "初始化..." : "开始录音"}
                </button>
              ) : (
                <button onClick={recorder.stop} className="btn-secondary">停止并提交</button>
              )}
            </div>
          )}

          {phase === "response" && currentTask.section === "listening" && currentTask.options && (
            <div className="space-y-2">
              <p className="text-sm text-gray-500">选择正确答案：</p>
              {currentTask.options.map((opt: string, i: number) => (
                <button
                  key={i}
                  onClick={async () => {
                    await shanghaiExamApi.submit(sessionId, currentTask.id, {
                      selected_option: i,
                      score: i === currentTask.correct_option ? 100 : 0,
                      feedback: i === currentTask.correct_option ? "正确" : "错误",
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
                  }}
                  className="block w-full text-left p-2 border border-gray-200 dark:border-gray-800 rounded hover:bg-gray-50 dark:hover:bg-gray-800 text-sm"
                >
                  {String.fromCharCode(65 + i)}. {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {report && (
        <div className="card space-y-4">
          <h3 className="font-semibold text-lg">考试报告（35 分制）</h3>

          <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-sm text-yellow-700 dark:text-yellow-300">
            {report.disclaimer}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <ScoreBox label="总分" value={report.total_score} full={report.full_score} highlight />
            <ScoreBox label="听力" value={report.listening_score} full={report.listening_full} />
            <ScoreBox label="口语" value={report.speaking_score} full={report.speaking_full} />
            <ScoreBox label="用时(分)" value={Math.round(report.duration_sec / 60)} full={35} />
          </div>

          {Object.keys(report.dimension_scores).length > 0 && (
            <div>
              <h4 className="font-medium mb-2">口语维度评分</h4>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {Object.entries(report.dimension_scores).map(([k, v]: any) => (
                  <div key={k} className="text-center p-2 bg-gray-50 dark:bg-gray-800 rounded">
                    <div className="text-lg font-bold">{v.toFixed(0)}</div>
                    <div className="text-xs text-gray-500">{k}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {report.task_results?.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">各任务详情</h4>
              <div className="space-y-2">
                {report.task_results.map((t: any, i: number) => (
                  <div key={i} className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-800 rounded">
                    <div>
                      <div className="text-sm font-medium">{t.title}</div>
                      <div className="text-xs text-gray-500">{t.task_type} · {t.year}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-bold">{t.earned_score}/{t.full_score}</div>
                      <div className="text-xs text-gray-500">{t.score_pct}%</div>
                    </div>
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
            onClick={() => { setSessionId(null); setReport(null); }}
            className="btn-secondary"
          >
            重新开始
          </button>
        </div>
      )}
    </div>
  );
}

function ScoreBox({ label, value, full, highlight }: { label: string; value: number; full: number; highlight?: boolean }) {
  return (
    <div className={`text-center p-3 rounded ${highlight ? "bg-primary-50 dark:bg-primary-900/20" : "bg-gray-50 dark:bg-gray-800"}`}>
      <div className={`text-2xl font-bold ${highlight ? "text-primary-600" : ""}`}>
        {value}<span className="text-sm text-gray-400">/{full}</span>
      </div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}
