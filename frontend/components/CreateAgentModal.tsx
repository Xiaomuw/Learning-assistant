"use client";

import { useState } from "react";
import { X, UploadCloud, Link as LinkIcon, Loader2, Bot } from "lucide-react";
import { createSubject, uploadPDFWithSubject, ingestUrls } from "@/lib/api";

interface CreateAgentModalProps {
  onClose: () => void;
  onSuccess: (subjectId: string) => void;
}

export default function CreateAgentModal({ onClose, onSuccess }: CreateAgentModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState("");
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("必须输入笔记本名称");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // 1. 创建新的笔记本
      const subject = await createSubject(name.trim(), "🤖", description.trim());
      
      // 2. Upload Files if any
      for (const file of files) {
        await uploadPDFWithSubject(file, subject.id);
      }
      
      // 3. Upload URLs if any
      const urlList = urls.split("\n").map(u => u.trim()).filter(u => u.length > 0);
      if (urlList.length > 0) {
        await ingestUrls(subject.id, urlList);
      }

      onSuccess(subject.id);
    } catch (err: any) {
      setError(err.message || "创建笔记本失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="absolute inset-0 z-[100] flex items-center justify-center bg-neo-bg/80 backdrop-blur-sm p-4">
      <div className="flex w-full max-w-md max-h-full flex-col overflow-hidden rounded-[2rem] border-[3px] border-neo-ink bg-white shadow-neo animate-in fade-in zoom-in-95 duration-200">
        <div className="flex shrink-0 items-center justify-between border-b-[3px] border-neo-ink bg-neo-secondary px-6 py-4 rounded-t-[calc(2rem-3px)]">
          <div className="flex items-center gap-2">
            <Bot size={24} strokeWidth={2.8} className="text-neo-ink" />
            <h2 className="text-xl font-black">创建知识笔记本</h2>
          </div>
          <button onClick={onClose} disabled={isSubmitting} className="hover:-translate-y-1 transition-transform">
            <X size={24} strokeWidth={2.8} className="text-neo-ink" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="rounded-2xl border-[3px] border-neo-ink bg-neo-accent p-3 text-sm font-bold shadow-neo-sm">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="neo-label mb-2 block">笔记本名称</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="neo-input"
                  placeholder="例如：数据库索引 / 计算机网络 / 面试八股"
                  required
                />
              </div>
            </div>

            <div>
              <label className="neo-label mb-2 block">笔记本简介</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="neo-input min-h-[100px] resize-none text-sm placeholder:text-sm"
                placeholder="描述这个笔记本主要存什么内容、适合学什么。例如：'收录数据库索引、事务与 SQL 优化相关资料，用于面试复习和概念梳理。'"
              />
            </div>
          </div>

          <div className="space-y-4 pt-2 border-t-[3px] border-neo-ink border-dashed">
            <p className="neo-label">注入知识源 (可选)</p>
            
            <div className="space-y-2">
              <label className="flex flex-col items-center justify-center p-4 border-[3px] border-neo-ink border-dashed rounded-2xl bg-neo-bg cursor-pointer hover:bg-neo-secondary transition-colors">
                <UploadCloud size={24} strokeWidth={2.8} className="text-neo-ink mb-2" />
                <span className="text-sm font-bold">{files.length > 0 ? `已选 ${files.length} 个 PDF` : "点击上传 PDF 文件"}</span>
                <input
                  type="file"
                  accept="application/pdf"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    if (e.target.files) {
                      setFiles(Array.from(e.target.files));
                    }
                  }}
                />
              </label>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <LinkIcon size={14} strokeWidth={2.8} className="text-neo-ink" />
                <label className="neo-label">网页链接 (每行一个 URL)</label>
              </div>
              <textarea
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
                className="neo-input min-h-[80px] text-xs resize-none"
                placeholder="https://example.com/article&#10;https://example.com/another"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full neo-button flex justify-center py-4 text-base"
          >
            {isSubmitting ? (
              <Loader2 className="animate-spin" size={20} strokeWidth={2.8} />
            ) : (
              "创建笔记本"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
