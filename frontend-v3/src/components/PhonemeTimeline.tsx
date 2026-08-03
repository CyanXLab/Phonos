interface PhoneSegment {
  expected_phone: string;
  recognized_phone: string | null;
  score: number;
  confidence: number;
  start_time: number;
  end_time: number;
  error_type: string;
  suggestion?: string;
}

interface PhonemeTimelineProps {
  phonemes: PhoneSegment[];
  onPhonemeClick?: (phoneme: string) => void;
}

const errorTypeClass: Record<string, string> = {
  match: "phoneme-match",
  substitution: "phoneme-substitution",
  deletion: "phoneme-deletion",
  insertion: "phoneme-insertion",
  minimal_pair_confusion: "phoneme-substitution",
  vowel_length_error: "phoneme-substitution",
  stress_error: "phoneme-substitution",
  intonation_error: "phoneme-substitution",
  unnatural_pause: "phoneme-substitution",
};

export function PhonemeTimeline({ phonemes, onPhonemeClick }: PhonemeTimelineProps) {
  if (!phonemes.length) {
    return <div className="text-sm text-gray-500">暂无音素数据</div>;
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-gray-700 dark:text-gray-300">
        音素时间轴（{phonemes.length} 个音素）
      </div>
      <div className="flex flex-wrap gap-1">
        {phonemes.map((p, i) => {
          const cls = errorTypeClass[p.error_type] || "phoneme-match";
          return (
            <button
              key={i}
              onClick={() => p.expected_phone && onPhonemeClick?.(p.expected_phone)}
              className={`phoneme-chip ${cls} hover:opacity-80 transition-opacity`}
              title={`${p.start_time.toFixed(2)}s - ${p.end_time.toFixed(2)}s | 置信度: ${(p.confidence * 100).toFixed(0)}% | ${p.suggestion || ""}`}
            >
              {p.expected_phone || "-"}
              {p.recognized_phone && p.recognized_phone !== p.expected_phone && (
                <span className="ml-1 opacity-70">→{p.recognized_phone}</span>
              )}
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-gray-500">
        <span><span className="phoneme-chip phoneme-match">●</span> 正确</span>
        <span><span className="phoneme-chip phoneme-substitution">●</span> 替换</span>
        <span><span className="phoneme-chip phoneme-deletion">●</span> 漏读</span>
        <span><span className="phoneme-chip phoneme-insertion">●</span> 多读</span>
      </div>
    </div>
  );
}
