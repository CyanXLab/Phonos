import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { sentenceApi, evaluateApi } from "../api";
import { useRecorder } from "../hooks/useRecorder";
import { Waveform } from "../components/Waveform";
import { ScoreRing } from "../components/ScoreRing";
import { PhonemeTimeline } from "../components/PhonemeTimeline";

export function PracticePage() {
  const [result, setResult] = useState<any>(null);
  const [evaluating, setEvaluating] = useState(false);

  const { data: sentence } = useQuery({
    queryKey: ["sentence"],
    queryFn: () => sentenceApi.random().then((r) => r.data),
  });

  const recorder = useRecorder({
    onAudioReady: async (_blob, wav) => {
      if (!sentence?.text) return;
      setEvaluating(true);
      try {
        const r = await evaluateApi.v2(wav, sentence.text);
        setResult(r.data);
      } catch (e: any) {
        alert("评测失败: " + (e.response?.data?.detail || e.message));
      } finally {
        setEvaluating(false);
      }
    },
  });

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-2">发音练习</h2>
        {sentence && (
          <div className="space-y-2">
            <p className="text-xl">{sentence.text}</p>
            {sentence.translation && (
              <p className="text-sm text-gray-500">{sentence.translation}</p>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="font-medium mb-3">录音</h3>
        <Waveform audioLevel={recorder.audioLevel} isRecording={recorder.isRecording} />
        <div className="flex items-center gap-3 mt-3">
          {!recorder.isRecording ? (
            <button
              onClick={recorder.start}
              disabled={recorder.isInitializing || evaluating}
              className="btn-primary"
            >
              {recorder.isInitializing ? "初始化..." : "开始录音"}
            </button>
          ) : (
            <button onClick={recorder.stop} className="btn-secondary">
              停止录音 ({recorder.duration.toFixed(1)}s)
            </button>
          )}
          {evaluating && <span className="text-sm text-gray-500">评测中...</span>}
        </div>
        {recorder.error && (
          <p className="text-sm text-red-600 mt-2">{recorder.error}</p>
        )}
      </div>

      {result && (
        <div className="card space-y-4">
          <h3 className="font-medium">评测结果</h3>

          <div className="flex items-center gap-6">
            <ScoreRing score={result.scores.overall} label="总分" />
            <div className="grid grid-cols-3 gap-3 flex-1">
              <ScoreItem label="音素准确度" score={result.scores.phoneme_accuracy} />
              <ScoreItem label="完整度" score={result.scores.completeness} />
              <ScoreItem label="流利度" score={result.scores.fluency} />
              <ScoreItem label="韵律" score={result.scores.prosody} />
              <ScoreItem label="重音" score={result.scores.stress} />
              <ScoreItem label="语调" score={result.scores.intonation} />
              <ScoreItem label="停顿合理性" score={result.scores.pause_appropriateness} />
              <ScoreItem label="语速" score={result.scores.speaking_rate} />
              <ScoreItem label="音质" score={result.scores.audio_quality} />
            </div>
          </div>

          {result.audio_quality_warning && (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 p-3 rounded text-sm text-yellow-700 dark:text-yellow-300">
              ⚠ {result.audio_quality_warning}
            </div>
          )}

          <PhonemeTimeline phonemes={result.phonemes || []} />

          {result.tips?.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">改进建议</h4>
              <ul className="space-y-2">
                {result.tips.slice(0, 5).map((tip: any, i: number) => (
                  <li key={i} className={`p-2 rounded text-sm ${
                    tip.severity === "high"
                      ? "bg-red-50 dark:bg-red-900/20"
                      : tip.severity === "medium"
                      ? "bg-yellow-50 dark:bg-yellow-900/20"
                      : "bg-gray-50 dark:bg-gray-800"
                  }`}>
                    <span className="font-medium">{tip.description}</span>
                    {tip.solution && <p className="text-gray-600 mt-1">{tip.solution}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="text-xs text-gray-400">
            Provider: {result.provider} | 推理耗时: {result.inference_ms?.toFixed(0)}ms
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreItem({ label, score }: { label: string; score: number }) {
  const color = score >= 80 ? "text-green-600" : score >= 60 ? "text-yellow-600" : "text-red-600";
  return (
    <div className="text-center">
      <div className={`text-lg font-bold ${color}`}>{score?.toFixed(0)}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}
