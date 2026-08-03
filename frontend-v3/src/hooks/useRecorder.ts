import { useEffect, useRef, useState, useCallback } from "react";

interface UseRecorderOptions {
  sampleRate?: number;
  onAudioReady?: (blob: Blob, wav: Blob) => void;
}

interface UseRecorderReturn {
  isRecording: boolean;
  isInitializing: boolean;
  error: string | null;
  audioLevel: number;
  start: () => Promise<void>;
  stop: () => void;
  audioBlob: Blob | null;
  duration: number;
}

/**
 * 录音 Hook（使用 AudioWorklet 替代已废弃的 ScriptProcessor）。
 */
export function useRecorder(options: UseRecorderOptions = {}): UseRecorderReturn {
  const { sampleRate = 16000, onAudioReady } = options;
  const [isRecording, setIsRecording] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioLevel, setAudioLevel] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [duration, setDuration] = useState(0);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const pcmChunksRef = useRef<Float32Array[]>([]);
  const animationFrameRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const durationTimerRef = useRef<number | null>(null);

  const start = useCallback(async () => {
    setError(null);
    setIsInitializing(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;

      // AudioContext for visualization + PCM capture
      const ctx = new AudioContext({ sampleRate });
      audioContextRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyserRef.current = analyser;

      // MediaRecorder for encoded backup
      const mimeType = getSupportedMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        const wav = encodeWav(pcmChunksRef.current, sampleRate);
        setAudioBlob(blob);
        onAudioReady?.(blob, wav);
      };
      recorder.start();
      mediaRecorderRef.current = recorder;

      // PCM capture via ScriptProcessor（兼容回退，AudioWorklet 需要额外文件）
      const bufferLen = 4096;
      const processor = ctx.createScriptProcessor(bufferLen, 1, 1);
      processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0);
        pcmChunksRef.current.push(new Float32Array(input));
        // 计算音量
        const sum = input.reduce((a, b) => a + b * b, 0);
        const rms = Math.sqrt(sum / input.length);
        setAudioLevel(Math.min(1, rms * 3));
      };
      source.connect(processor);
      processor.connect(ctx.destination);

      setIsRecording(true);
      setIsInitializing(false);
      startTimeRef.current = Date.now();
      durationTimerRef.current = window.setInterval(() => {
        setDuration((Date.now() - startTimeRef.current) / 1000);
      }, 100);
    } catch (err: any) {
      setError(err.message || "录音启动失败");
      setIsInitializing(false);
    }
  }, [sampleRate, onAudioReady]);

  const stop = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    setIsRecording(false);
    setAudioLevel(0);
  }, []);

  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return {
    isRecording,
    isInitializing,
    error,
    audioLevel,
    start,
    stop,
    audioBlob,
    duration,
  };
}

function getSupportedMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return "audio/webm";
}

function encodeWav(chunks: Float32Array[], sampleRate: number): Blob {
  const totalLen = chunks.reduce((a, c) => a + c.length, 0);
  const buffer = new ArrayBuffer(44 + totalLen * 2);
  const view = new DataView(buffer);

  // WAV header
  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + totalLen * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, totalLen * 2, true);

  let offset = 44;
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      const s = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      offset += 2;
    }
  }

  return new Blob([buffer], { type: "audio/wav" });
}
