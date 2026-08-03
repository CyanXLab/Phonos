import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { sentenceApi, dictationApi } from "../api";

export function DictationPage() {
  const [input, setInput] = useState("");
  const [result, setResult] = useState<any>(null);

  const { data: sentence } = useQuery({
    queryKey: ["sentence-dictation"],
    queryFn: () => sentenceApi.random().then((r) => r.data),
  });

  const mutation = useMutation({
    mutationFn: () => dictationApi.check(sentence?.text || "", input).then((r) => r.data),
    onSuccess: setResult,
  });

  if (!sentence) return <div>加载中...</div>;

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-2">听写训练</h2>
        <p className="text-sm text-gray-500 mb-3">
          点击播放按钮听句子，然后逐词听写。听写完成后点击"检查"。
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={() => playTTS(sentence.text)}
            className="btn-secondary"
          >
            播放音频
          </button>
          <select id="tts-speed" className="input max-w-32">
            <option value="0.5">0.5x</option>
            <option value="0.75">0.75x</option>
            <option value="1" selected>1x</option>
          </select>
        </div>
      </div>

      <div className="card">
        <label className="text-sm font-medium mb-2 block">你的听写</label>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="input min-h-24"
          placeholder="在此输入听到的内容..."
        />
        <button
          onClick={() => mutation.mutate()}
          disabled={!input.trim() || mutation.isPending}
          className="btn-primary mt-2"
        >
          {mutation.isPending ? "检查中..." : "检查"}
        </button>
      </div>

      {result && (
        <div className="card space-y-4">
          <div className="flex items-center gap-4">
            <div className="text-3xl font-bold text-primary-600">
              {result.overall_score.toFixed(0)}
            </div>
            <div className="text-sm text-gray-500">总分</div>
          </div>

          <div>
            <h4 className="font-medium mb-2">词级对齐</h4>
            <div className="flex flex-wrap gap-2">
              {result.words?.map((w: any, i: number) => (
                <span
                  key={i}
                  className={`px-2 py-1 rounded text-sm ${
                    w.match_type === "match"
                      ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100"
                      : w.match_type === "near_correct"
                      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100"
                      : w.match_type === "deletion"
                      ? "bg-red-100 text-red-800 line-through dark:bg-red-900 dark:text-red-100"
                      : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-100"
                  }`}
                  title={`类型: ${w.match_type} | 相似度: ${(w.similarity * 100).toFixed(0)}%`}
                >
                  {w.expected || "—"}
                  {w.actual && w.actual !== w.expected && (
                    <span className="ml-1 opacity-70">({w.actual})</span>
                  )}
                </span>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
            <Stat label="正确" value={result.summary?.match || 0} />
            <Stat label="近似" value={result.summary?.near_correct || 0} />
            <Stat label="漏写" value={result.summary?.deletion || 0} />
            <Stat label="多写" value={result.summary?.insertion || 0} />
          </div>

          {result.tips?.length > 0 && (
            <div>
              <h4 className="font-medium mb-2">建议</h4>
              <ul className="text-sm space-y-1">
                {result.tips.map((t: string, i: number) => (
                  <li key={i} className="text-gray-600 dark:text-gray-300">• {t}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center p-2 bg-gray-50 dark:bg-gray-800 rounded">
      <div className="text-lg font-bold">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

function playTTS(text: string) {
  const speed = parseFloat((document.getElementById("tts-speed") as HTMLSelectElement)?.value || "1");
  if ("speechSynthesis" in window) {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "en-US";
    u.rate = speed;
    speechSynthesis.speak(u);
  } else {
    fetch(`/api/tts?text=${encodeURIComponent(text)}`)
      .then((r) => r.blob())
      .then((b) => {
        const audio = new Audio(URL.createObjectURL(b));
        audio.play();
      });
  }
}
