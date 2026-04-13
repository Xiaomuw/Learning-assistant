"use client";

import { X, Trash2, Clock, MessageSquare, Plus } from "lucide-react";
import type { ChatSession } from "@/lib/learning-store";
import type { Subject } from "@/lib/api";

interface HistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  subjects: Subject[];
  onSelectSession: (session: ChatSession) => void;
  onDeleteSession: (sessionId: string) => void;
  onNewSession: () => void;
}

export default function HistoryDrawer({
  isOpen,
  onClose,
  sessions,
  subjects,
  onSelectSession,
  onDeleteSession,
  onNewSession,
}: HistoryDrawerProps) {
  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop */}
      <div 
        className="absolute inset-0 z-[100] bg-neo-bg/80 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />
      
      {/* Drawer */}
      <div className="absolute inset-y-0 right-0 z-[110] w-full max-w-sm border-l-[3px] border-neo-ink bg-white shadow-neo animate-in slide-in-from-right flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b-[3px] border-neo-ink bg-neo-secondary px-6 py-4">
          <div className="flex items-center gap-2">
            <Clock size={24} strokeWidth={2.8} className="text-neo-ink" />
            <h2 className="text-xl font-black">最近记录</h2>
          </div>
          <button onClick={onClose} className="hover:-translate-y-1 transition-transform">
            <X size={24} strokeWidth={2.8} className="text-neo-ink" />
          </button>
        </div>

        {/* Action Bar */}
        <div className="p-4 border-b-[3px] border-neo-ink bg-neo-bg">
          <button 
            onClick={onNewSession}
            className="w-full neo-button flex justify-center py-3 bg-white"
          >
            <Plus size={18} strokeWidth={2.8} />
            开启新对话
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {sessions.length === 0 ? (
            <div className="text-center py-10 opacity-50 font-bold">
              <MessageSquare size={32} strokeWidth={2} className="mx-auto mb-2" />
              <p>暂无聊天记录</p>
            </div>
          ) : (
            sessions.map((session) => {
              const subject = subjects.find(s => s.id === session.subjectId);
              const date = new Date(session.updatedAt);
              const dateString = `${date.getMonth() + 1}-${date.getDate()} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;

              return (
                <div 
                  key={session.id} 
                  className="group relative flex items-start gap-3 rounded-[1rem] border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm hover:translate-x-[2px] hover:translate-y-[2px] hover:shadow-none transition-all cursor-pointer"
                  onClick={() => onSelectSession(session)}
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-[3px] border-neo-ink bg-neo-accent text-lg">
                    {subject ? subject.icon : "📚"}
                  </div>
                  
                  <div className="flex-1 min-w-0">
                    <p className="truncate font-black text-[15px]">{session.title}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs font-bold text-neo-ink/70">
                        {subject ? subject.name : "未知 Agent"}
                      </span>
                      <span className="text-[10px] font-bold text-neo-ink/50 bg-neo-bg px-2 py-0.5 rounded-full border-[2px] border-neo-ink/20">
                        {dateString}
                      </span>
                    </div>
                  </div>

                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteSession(session.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-2 hover:bg-neo-accent rounded-full transition-all"
                  >
                    <Trash2 size={16} strokeWidth={2.8} className="text-neo-ink" />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
