"use client";
import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface AdminTask {
  id: string;
  text: string;
  voice_id: number;
  status: string;
  attempt: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

const FILTERS = ["ALL", "PENDING", "PROCESSING", "COMPLETED", "FAILED"] as const;
const LIMIT = 50;

function StatusDot({ status }: { status: string }) {
  const color: Record<string, string> = {
    COMPLETED: "bg-online",
    FAILED: "bg-alert",
    PROCESSING: "bg-signal animate-pulse",
    PENDING: "bg-signal",
  };
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${color[status] || "bg-dimmer"} mr-2`} />;
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<AdminTask[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeFilter, setActiveFilter] = useState<string>("ALL");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [offset, setOffset] = useState(0);

  const loadTasks = useCallback(async () => {
    setIsRefreshing(true);
    try {
      setTasks(await api(`/api/tasks/?limit=${LIMIT}&offset=${offset}`));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setIsRefreshing(false);
    }
  }, [offset]);


  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const retryTask = async (taskId: string) => {
    try {
      await api(`/api/tasks/${taskId}/retry`, { method: "POST" });
      toast.success("Đã gửi lại tác vụ");
      loadTasks();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const filteredTasks = activeFilter === "ALL"
    ? tasks
    : tasks.filter(t => t.status === activeFilter);

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filteredTasks.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filteredTasks.map(t => t.id)));
    }
  };

  const bulkRetry = async () => {
    const failedSelected = filteredTasks.filter(t => selected.has(t.id) && t.status === "FAILED");
    if (failedSelected.length === 0) {
      toast.error("Không có tác vụ FAILED nào được chọn");
      return;
    }
    
    if (!confirm(`Thử lại ${failedSelected.length} tác vụ thất bại đã chọn?`)) return;
    
    let successCount = 0;
    for (const t of failedSelected) {
      try {
        await api(`/api/tasks/${t.id}/retry`, { method: "POST" });
        successCount++;
      } catch (e) {
        // bỏ qua lỗi từng cái
      }
    }
    
    toast.success(`Đã gửi lại ${successCount}/${failedSelected.length} tác vụ`);
    setSelected(new Set());
    loadTasks();
  };

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-lg font-bold text-vocal">Tác vụ</h2>
          <p className="text-sm text-echo">Lịch sử tác vụ TTS, retry.</p>
        </div>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-echo font-mono">
                {selected.size} đã chọn
              </span>
              <button
                onClick={bulkRetry}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-alert/20 text-alert hover:bg-alert/30 transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Retry hàng loạt
              </button>
            </div>
          )}
          <button
            onClick={loadTasks}
            disabled={isRefreshing}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors disabled:opacity-50"
          >
            {isRefreshing ? (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-dimmer animate-pulse" />
                Đang tải
              </span>
            ) : (
              <>
                <RefreshCw className="w-3.5 h-3.5" />
                Làm mới
              </>
            )}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setActiveFilter(f)}
            className={`px-3 py-1 rounded text-xs font-mono transition-colors ${
              activeFilter === f
                ? "bg-signal/20 text-signal"
                : "text-echo hover:text-vocal hover:bg-strip"
            }`}
          >
            {f === "ALL" ? "Tất cả" : f}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-phantom">
              <th className="py-3 px-3 w-8">
                <input
                  type="checkbox"
                  checked={filteredTasks.length > 0 && selected.size === filteredTasks.length}
                  onChange={toggleSelectAll}
                  className="accent-signal"
                />
              </th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Nội dung</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Voice ID</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Trạng thái</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Lần thử</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Tạo lúc</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Hoàn thành</th>
              <th className="text-right py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Hành động</th>
            </tr>
          </thead>
          <tbody>
            {filteredTasks.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-12 text-echo font-mono text-xs">
                  {isRefreshing ? (
                    <span className="inline-flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-dimmer animate-pulse" />
                      Đang tải...
                    </span>
                  ) : "Chưa có tác vụ TTS nào"}
                </td>
              </tr>
            ) : filteredTasks.map(t => (
              <tr 
                key={t.id} 
                className={`border-b border-phantom transition-colors cursor-pointer ${
                  selected.has(t.id) ? "bg-signal/5" : "hover:bg-strip/50"
                }`}
                onClick={() => toggleSelect(t.id)}
              >
                <td className="py-3 px-3" onClick={e => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selected.has(t.id)}
                    onChange={() => toggleSelect(t.id)}
                    className="accent-signal"
                  />
                </td>
                <td className="py-3 px-4 max-w-xs truncate text-sm text-vocal">{t.text}</td>
                <td className="py-3 px-4 font-mono text-xs text-echo">{t.voice_id}</td>
                <td className="py-3 px-4">
                  <span className="inline-flex items-center text-xs font-mono text-echo">
                    <StatusDot status={t.status} />
                    {t.status}
                  </span>
                </td>
                <td className="py-3 px-4 font-mono text-xs text-echo">{t.attempt}</td>
                <td className="py-3 px-4 font-mono text-xs text-echo">
                  {new Date(t.created_at).toLocaleString("vi-VN", {
                    hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
                  })}
                </td>
                <td className="py-3 px-4 font-mono text-xs text-echo">
                  {t.completed_at
                    ? new Date(t.completed_at).toLocaleString("vi-VN", {
                        hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
                      })
                    : "-"}
                </td>
                <td className="py-3 px-4 text-right" onClick={e => e.stopPropagation()}>
                  {t.status === "FAILED" && (
                    <button
                      onClick={() => retryTask(t.id)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between border-t border-phantom pt-4">
        <span className="text-xs text-echo font-mono">
          Hiển thị {filteredTasks.length} tác vụ
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - LIMIT))}
            disabled={offset === 0}
            className="px-3 py-1.5 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors disabled:opacity-50 disabled:hover:bg-transparent"
          >
            Trước
          </button>
          <span className="text-xs font-mono text-dimmer">
            Trang {Math.floor(offset / LIMIT) + 1}
          </span>
          <button
            onClick={() => setOffset(offset + LIMIT)}
            disabled={tasks.length < LIMIT}
            className="px-3 py-1.5 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors disabled:opacity-50 disabled:hover:bg-transparent"
          >
            Sau
          </button>
        </div>
      </div>
    </div>
  );
}
