"use client";

import React, { useState } from "react";

interface AiEditCommandPanelProps {
  projectId: string;
  sectionId: string | null;
  backendUrl?: string;
  headers?: Record<string, string>;
  onUpdateSuccess?: () => void;
  onApplyCommand?: (commandType: string, instruction: string, scope: string) => Promise<void>;
  isProcessing?: boolean;
}

const PRESET_COMMANDS = [
  "제목을 더 강하게 바꿔줘",
  "문구를 더 짧고 자연스럽게 정리해줘",
  "과장 표현을 줄여줘",
  "사용 장면이 떠오르게 설명을 보강해줘",
  "초보 셀러가 쓰기 좋은 톤으로 다듬어줘",
  "구매 전 불안을 줄이는 문장을 추가해줘",
];

export default function AiEditCommandPanel({
  projectId,
  sectionId,
  backendUrl,
  headers,
  onUpdateSuccess,
  onApplyCommand,
  isProcessing = false,
}: AiEditCommandPanelProps) {
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleSendCommand = async (commandText: string) => {
    if (!sectionId) {
      setMessage({ type: "error", text: "먼저 수정할 섹션을 선택해 주세요." });
      return;
    }
    if (!commandText.trim()) return;

    if (onApplyCommand) {
      try {
        setLoading(true);
        setMessage(null);
        await onApplyCommand("custom", commandText, "section");
        setMessage({ type: "success", text: "수정 요청이 반영되었습니다." });
        setInputText("");
      } catch {
        setMessage({ type: "error", text: "수정 요청에 실패했습니다." });
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      setLoading(true);
      setMessage(null);
      const res = await fetch(`${backendUrl}/projects/${projectId}/pages/ai-edit`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...headers,
        },
        body: JSON.stringify({
          section_id: sectionId,
          command: commandText,
        }),
      });

      if (!res.ok) throw new Error("AI 편집 요청에 실패했습니다.");
      setMessage({ type: "success", text: "수정 요청이 반영되었습니다." });
      setInputText("");
      onUpdateSuccess?.();
    } catch (err) {
      console.error(err);
      setMessage({ type: "error", text: "수정 처리 중 오류가 발생했습니다." });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-5 text-slate-800">
      <div>
        <p className="text-xs font-bold text-emerald-700">AI 문구 수정</p>
        <h3 className="text-lg font-extrabold text-slate-950">선택한 섹션 다듬기</h3>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          빠른 수정 지시를 선택하거나, 원하는 수정 방향을 직접 입력해 주세요.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs">
        <span className="font-bold text-slate-500">선택한 섹션</span>
        <p className="mt-1 font-mono text-slate-800">{sectionId || "선택 없음"}</p>
      </div>

      <div className="grid grid-cols-1 gap-2">
        {PRESET_COMMANDS.map((command) => (
          <button
            key={command}
            type="button"
            disabled={loading || isProcessing || !sectionId}
            onClick={() => handleSendCommand(command)}
            className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-left text-xs font-bold text-slate-700 transition-all hover:border-emerald-200 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {command}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        <label className="text-xs font-bold text-slate-600" htmlFor="ai-edit-command">
          직접 요청하기
        </label>
        <textarea
          id="ai-edit-command"
          disabled={loading || isProcessing || !sectionId}
          value={inputText}
          onChange={(event) => setInputText(event.target.value)}
          placeholder="예: 이 문구를 더 믿음직하고 구매하고 싶게 바꿔줘"
          className="min-h-28 w-full resize-none rounded-2xl border border-slate-200 bg-white p-3 text-sm outline-none transition-all placeholder:text-slate-400 focus:border-emerald-400 disabled:bg-slate-50"
        />
        <button
          type="button"
          disabled={loading || isProcessing || !sectionId || !inputText.trim()}
          onClick={() => handleSendCommand(inputText)}
          className="w-full rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-extrabold text-white shadow-lg shadow-emerald-600/15 transition-all hover:bg-emerald-700 disabled:bg-slate-200 disabled:text-slate-400 disabled:shadow-none"
        >
          {loading ? "수정 중..." : "AI 수정 반영"}
        </button>
      </div>

      {message ? (
        <div
          className={`rounded-2xl border p-3 text-xs font-bold ${
            message.type === "success"
              ? "border-emerald-100 bg-emerald-50 text-emerald-700"
              : "border-rose-100 bg-rose-50 text-rose-700"
          }`}
        >
          {message.text}
        </div>
      ) : null}
    </div>
  );
}
