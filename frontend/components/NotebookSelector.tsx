"use client";

import { useEffect, useRef, useState } from "react";
import { BookMarked, ChevronDown, Database } from "lucide-react";
import type { Notebook } from "@/lib/api";

interface NotebookSelectorProps {
  notebooks: Notebook[];
  selectedId: string;
  onSelect: (notebookId: string) => void;
}

export default function NotebookSelector({
  notebooks,
  selectedId,
  onSelect,
}: NotebookSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: PointerEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", handleClickOutside);
    return () => document.removeEventListener("pointerdown", handleClickOutside);
  }, []);

  const selectedNotebook = notebooks.find((notebook) => notebook.id === selectedId);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="flex w-full items-center gap-3 border-[3px] border-neo-ink bg-white px-4 py-4 text-left shadow-neo-sm transition-all duration-100 ease-linear active:translate-x-[4px] active:translate-y-[4px] active:shadow-none"
      >
        <div className="flex h-11 w-11 items-center justify-center border-[3px] border-neo-ink bg-neo-muted shadow-neo-sm">
          <BookMarked size={18} strokeWidth={2.8} />
        </div>

        <div className="min-w-0 flex-1">
          <p className="neo-label">辅助知识库</p>
          <p className="mt-1 truncate text-lg font-black">
            {selectedNotebook?.icon ?? "📚"} {selectedNotebook?.name ?? "选择知识库"}
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          <span className="neo-badge bg-neo-secondary">
            {selectedNotebook?.doc_count ?? 0} 条来源
          </span>
          <ChevronDown
            size={18}
            strokeWidth={2.8}
            className={`transition-transform duration-100 ${
              isOpen ? "rotate-180" : ""
            }`}
          />
        </div>
      </button>

      {isOpen && (
        <div className="absolute inset-x-0 top-full z-40 mt-3 animate-stamp-in rounded-[1.5rem] border-[3px] border-neo-ink bg-white shadow-neo-lg">
          <div className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-3">
            <p className="neo-label">选择知识库</p>
            <p className="mt-1 text-lg font-black">只作为回答时的辅助参考</p>
          </div>

          <div className="max-h-80 overflow-y-auto">
            {notebooks.map((notebook) => {
              const isActive = notebook.id === selectedId;

              return (
                <button
                  key={notebook.id}
                  type="button"
                  onClick={() => {
                    onSelect(notebook.id);
                    setIsOpen(false);
                  }}
                  className={`flex w-full items-start gap-3 border-b-[3px] border-neo-ink px-4 py-4 text-left last:border-b-0 ${
                    isActive ? "bg-neo-accent" : "bg-white hover:bg-neo-muted"
                  }`}
                >
                  <div className="flex h-11 w-11 items-center justify-center border-[3px] border-neo-ink bg-white shadow-neo-sm text-xl">
                    {notebook.icon}
                  </div>

                  <div className="min-w-0 flex-1">
                    <p className="text-base font-black">{notebook.name}</p>
                    <p className="mt-1 text-sm font-bold leading-snug text-neo-ink/70">
                      {notebook.description || "暂无描述"}
                    </p>
                  </div>

                  <div className="shrink-0">
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border-[3px] border-neo-ink px-3 py-1 text-[11px] font-black uppercase tracking-[0.16em] shadow-neo-sm ${
                        notebook.doc_count > 0
                          ? "bg-neo-secondary"
                          : "bg-neo-muted"
                      }`}
                    >
                      <Database size={12} strokeWidth={2.6} />
                      {notebook.doc_count}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {selectedNotebook && selectedNotebook.doc_count === 0 && (
            <div className="border-t-[3px] border-neo-ink bg-neo-bg p-4 text-xs font-black leading-relaxed text-neo-ink/70">
              知识库只作为辅助参考。普通概念和解题会优先由模型直接讲解，只有资料强相关或你明确要求时才引用。
            </div>
          )}
        </div>
      )}
    </div>
  );
}
