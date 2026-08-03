interface TimerProps {
  seconds: number;
  onExpire?: () => void;
  autoStart?: boolean;
  variant?: "prep" | "response" | "warning";
}

import { useEffect, useState, useRef } from "react";

export function ExamTimer({ seconds, onExpire, autoStart = true, variant = "response" }: TimerProps) {
  const [remaining, setRemaining] = useState(seconds);
  const [isRunning, setIsRunning] = useState(autoStart);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    if (!isRunning) return;
    if (remaining <= 0) {
      setIsRunning(false);
      onExpireRef.current?.();
      return;
    }
    const t = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(t);
  }, [remaining, isRunning]);

  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const colorClass =
    variant === "prep"
      ? "text-blue-600"
      : remaining <= 5
      ? "text-red-600 recording-pulse"
      : remaining <= 10
      ? "text-yellow-600"
      : "text-gray-900 dark:text-gray-100";

  return (
    <div className="flex items-center gap-2">
      <span className={`text-2xl font-mono font-bold ${colorClass}`}>
        {mins.toString().padStart(2, "0")}:{secs.toString().padStart(2, "0")}
      </span>
      {variant === "prep" && (
        <span className="text-xs text-gray-500">准备中</span>
      )}
    </div>
  );
}
