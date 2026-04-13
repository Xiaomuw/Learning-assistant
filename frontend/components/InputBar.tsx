"use client";

import { useRef, useState } from "react";
import { LoaderCircle, Paperclip, Send } from "lucide-react";

interface InputBarProps {
  onSend: (message: string) => void;
  onUpload?: (file: File) => Promise<void> | void;
  disabled?: boolean;
  isUploading?: boolean;
  placeholder?: string;
}

export default function InputBar({
  onSend,
  onUpload,
  disabled = false,
  isUploading = false,
  placeholder = "输入你的问题...",
}: InputBarProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function resizeTextarea() {
    const element = textareaRef.current;
    if (!element) {
      return;
    }

    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 168)}px`;
  }

  function handleSend() {
    const trimmed = value.trim();
    if (!trimmed || disabled) {
      return;
    }

    onSend(trimmed);
    setValue("");

    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !onUpload) {
      return;
    }

    await onUpload(file);
    event.target.value = "";
  }

  return (
    <div className="neo-card bg-white p-2">
      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          hidden
          onChange={handleFileChange}
        />

        <button
          type="button"
          aria-label="上传 PDF"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading || !onUpload}
          className="neo-icon-button shrink-0 bg-neo-secondary"
        >
          {isUploading ? (
            <LoaderCircle size={22} strokeWidth={2.8} className="animate-spin" />
          ) : (
            <Paperclip size={22} strokeWidth={2.8} />
          )}
        </button>

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            resizeTextarea();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              handleSend();
            }
          }}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="neo-input min-h-[56px] max-h-40 resize-none leading-snug"
        />

        <button
          type="button"
          aria-label="发送消息"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          className="neo-icon-button shrink-0 bg-neo-accent"
        >
          <Send size={22} strokeWidth={2.8} />
        </button>
      </div>

      <p className="mt-3 px-2 text-center text-[11px] font-black uppercase tracking-[0.16em] text-neo-ink/60">
        PDF 上传 · Enter 发送 · Shift + Enter 换行
      </p>
    </div>
  );
}
