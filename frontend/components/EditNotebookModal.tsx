"use client";

import { useEffect, useState } from "react";
import { Loader2, NotebookPen, X, UploadCloud, Link as LinkIcon } from "lucide-react";
import { updateSubject, type Subject, uploadPDFWithSubject, ingestUrls } from "@/lib/api";

interface EditNotebookModalProps {
  subject: Subject;
  onClose: () => void;
  onSuccess: (subject: Subject) => void;
}

export default function EditNotebookModal({
  subject,
  onClose,
  onSuccess,
}: EditNotebookModalProps) {
  const [name, setName] = useState(subject.name);
  const [description, setDescription] = useState(subject.description);
  
  const [files, setFiles] = useState<File[]>([]);
  const [urls, setUrls] = useState("");
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setName(subject.name);
    setDescription(subject.description);
  }, [subject]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setError("必须输入笔记本名称");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const updated = await updateSubject(subject.id, {
        name: name.trim(),
        icon: subject.icon,
        description: description.trim(),
      });
      
      // Upload Files if any
      for (const file of files) {
        await uploadPDFWithSubject(file, subject.id);
      }
      
      // Upload URLs if any
      const urlList = urls.split("\n").map(u => u.trim()).filter(u => u.length > 0);
      if (urlList.length > 0) {
        await ingestUrls(subject.id, urlList);
      }
      
      onSuccess(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新笔记本失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="absolute inset-0 z-[100] flex items-center justify-center bg-neo-bg/80 p-4 backdrop-blur-sm">
      <div className="flex w-full max-h-full max-w-md flex-col overflow-hidden rounded-[2rem] border-[3px] border-neo-ink bg-white shadow-neo animate-in fade-in zoom-in-95 duration-200">
        <div className="flex shrink-0 items-center justify-between rounded-t-[calc(2rem-3px)] border-b-[3px] border-neo-ink bg-neo-muted px-6 py-4">
          <div className="flex items-center gap-2">
            <NotebookPen size={24} strokeWidth={2.8} className="text-neo-ink" />
            <h2 className="text-xl font-black">编辑笔记本</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="transition-transform hover:-translate-y-1"
          >
            <X size={24} strokeWidth={2.8} className="text-neo-ink" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="overflow-y-auto space-y-5 p-6">
          {error && (
            <div className="rounded-2xl border-[3px] border-neo-ink bg-neo-accent p-3 text-sm font-bold shadow-neo-sm">
              {error}
            </div>
          )}

          <div className="flex gap-4">
            <div className="min-w-0 flex-1">
              <label className="neo-label mb-2 block">笔记本名称</label>
              <input
                type="text"
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="neo-input"
                placeholder="例如：数据库索引"
                required
              />
            </div>
          </div>

          <div>
            <label className="neo-label mb-2 block">笔记本简介</label>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="neo-input min-h-[120px] resize-none text-sm placeholder:text-sm"
              placeholder="写一句话说明这个笔记本主要存什么内容。"
            />
          </div>

          <div className="space-y-4 pt-2 border-t-[3px] border-neo-ink border-dashed">
            <p className="neo-label">追加知识源 (可选)</p>
            
            <div className="space-y-2">
              <label className="flex flex-col items-center justify-center p-4 border-[3px] border-neo-ink border-dashed rounded-2xl bg-neo-bg cursor-pointer hover:bg-neo-secondary transition-colors">
                <UploadCloud size={24} strokeWidth={2.8} className="text-neo-ink mb-2" />
                <span className="text-sm font-bold">{files.length > 0 ? `已选 ${files.length} 个 PDF` : "点击追加上传 PDF 文件"}</span>
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
                <label className="neo-label">抓取网页链接 (每行一个 URL)</label>
              </div>
              <textarea
                value={urls}
                onChange={(e) => setUrls(e.target.value)}
                className="neo-input min-h-[80px] text-xs resize-none"
                placeholder="https://example.com/article&#10;https://example.com/another"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={onClose}
              className="neo-button-ghost w-full justify-center"
              disabled={isSubmitting}
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="neo-button w-full justify-center"
            >
              {isSubmitting ? (
                <Loader2 className="animate-spin" size={18} strokeWidth={2.8} />
              ) : (
                "保存修改"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
