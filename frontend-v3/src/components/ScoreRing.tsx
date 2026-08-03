interface ScoreRingProps {
  score: number;
  size?: number;
  label?: string;
  sublabel?: string;
}

export function ScoreRing({ score, size = 120, label, sublabel }: ScoreRingProps) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const color = score >= 80 ? "#10b981" : score >= 60 ? "#f59e0b" : "#ef4444";

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="#e5e7eb"
          strokeWidth="8"
          fill="none"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={color}
          strokeWidth="8"
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.5s ease" }}
        />
      </svg>
      <div className="flex flex-col items-center -mt-[calc(50%+12px)]">
        <span className="text-2xl font-bold" style={{ color }}>
          {score.toFixed(0)}
        </span>
        {label && <span className="text-xs text-gray-500">{label}</span>}
      </div>
      {sublabel && <span className="text-xs text-gray-400 mt-8">{sublabel}</span>}
    </div>
  );
}
