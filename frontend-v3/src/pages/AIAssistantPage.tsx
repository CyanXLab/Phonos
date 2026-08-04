import { useState, useRef, useEffect } from "react";
import { llmApi } from "../api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export function AIAssistantPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "你好！我是 Phonos AI 助手，专门帮你准备上海高考英语听说考试。你可以问我：\n\n• 如何发好 /θ/ 音（think 中的 th）\n• 情景提问怎么拿高分\n• 听力 Section B 长对话技巧\n• 朗读短文注意事项\n• 我的弱项是流利度，怎么提升？",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setInput("");
    setLoading(true);

    try {
      const r = await llmApi.chat(userMsg);
      setMessages((m) => [...m, { role: "assistant", content: r.data.response }]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `抱歉，响应失败：${e.response?.data?.detail || e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const quickQuestions = [
    "如何发好 /θ/ 音？",
    "情景提问怎么拿高分？",
    "听力长对话技巧",
    "朗读短文注意事项",
    "快速应答怎么练？",
  ];

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="text-lg font-semibold mb-2">AI 学习助手</h2>
        <p className="text-sm text-gray-500">
          基于 Qwen3.5-122B 大模型，解答英语学习问题，提供个性化指导。
        </p>
      </div>

      <div className="card flex flex-col" style={{ height: "60vh" }}>
        <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 p-2">
          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-lg p-3 text-sm whitespace-pre-wrap ${
                  m.role === "user"
                    ? "bg-primary-600 text-white"
                    : "bg-gray-100 dark:bg-gray-800"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-gray-100 dark:bg-gray-800 rounded-lg p-3 text-sm">
                <span className="inline-block animate-pulse">AI 思考中...</span>
              </div>
            </div>
          )}
        </div>

        <div className="border-t border-gray-200 dark:border-gray-800 p-2">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="输入你的问题..."
              className="input flex-1"
              disabled={loading}
            />
            <button onClick={send} disabled={loading || !input.trim()} className="btn-primary">
              发送
            </button>
          </div>
          <div className="flex gap-1 mt-2 flex-wrap">
            {quickQuestions.map((q) => (
              <button
                key={q}
                onClick={() => setInput(q)}
                className="text-xs px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
