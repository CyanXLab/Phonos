import { useEffect, useRef } from "react";

interface WaveformProps {
  audioLevel: number;
  isRecording: boolean;
  color?: string;
  height?: number;
}

export function Waveform({
  audioLevel,
  isRecording,
  color = "#4f46e5",
  height = 60,
}: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const historyRef = useRef<number[]>(new Array(60).fill(0));

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf: number;

    const render = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      // 更新历史
      historyRef.current.shift();
      historyRef.current.push(isRecording ? audioLevel : 0);

      // 绘制柱状图
      const barWidth = w / historyRef.current.length;
      historyRef.current.forEach((level, i) => {
        const barHeight = Math.max(2, level * h * 0.9);
        const x = i * barWidth;
        const y = (h - barHeight) / 2;
        ctx.fillStyle = isRecording ? color : "#cbd5e1";
        ctx.fillRect(x + 1, y, barWidth - 2, barHeight);
      });

      raf = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(raf);
  }, [audioLevel, isRecording, color]);

  return (
    <canvas
      ref={canvasRef}
      width={300}
      height={height}
      className="w-full"
      style={{ height }}
    />
  );
}
