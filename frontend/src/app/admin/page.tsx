"use client";
import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { motion } from "motion/react";

interface Stats {
  total_tasks: number;
  completed: number;
  failed: number;
  pending: number;
  active_workers: number;
}

interface SatelliteInfo {
  healthy_nodes: number;
  total_capacity: number;
  active_workers: number;
}

interface AdminTask {
  id: string;
  text: string;
  voice_id: number;
  status: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "COMPLETED" ? "bg-online" :
    status === "FAILED" ? "bg-alert" :
    status === "PROCESSING" ? "bg-signal animate-pulse" :
    "bg-dimmer";
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${color} mr-2`} />;
}

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [overviewTasks, setOverviewTasks] = useState<AdminTask[]>([]);
  const [loading, setLoading] = useState(false);

  const [satellites, setSatellites] = useState<SatelliteInfo | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const [healthRes, statsRes, nodeList] = await Promise.all([
        api("/api/health/") as Promise<any>,
        api("/api/health/stats") as Promise<Stats>,
        api("/api/node/list") as Promise<any[]>,
      ]);
      setStats({ ...statsRes, active_workers: statsRes.active_workers ?? healthRes.active_workers ?? healthRes.workers?.active_connections ?? 0 });
      const sat = healthRes.satellites || { healthy_nodes: 0, total_capacity: 0, active_workers: 0 };
      setSatellites({
        healthy_nodes: sat.healthy_nodes ?? nodeList.filter((n: any) => n.status === "ONLINE").length,
        total_capacity: sat.total_capacity ?? 0,
        active_workers: sat.active_workers ?? 0,
      });
    } catch (e: any) {
      toast.error(e.message);
    }
  }, []);

  const loadOverviewTasks = useCallback(async () => {
    setLoading(true);
    try {
      setOverviewTasks(await api("/api/tasks/?limit=10"));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadStats(); loadOverviewTasks(); }, [loadStats, loadOverviewTasks]);

  const retryTask = async (taskId: string) => {
    try {
      await api(`/api/tasks/${taskId}/retry`, { method: "POST" });
      toast.success("Đã gửi lại task");
      loadOverviewTasks();
      loadStats();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const statItems = [
    { label: "Workers", value: stats?.active_workers ?? 0 },
    { label: "Vệ tinh", value: satellites?.healthy_nodes ?? 0 },
    { label: "Capacity", value: satellites?.total_capacity ?? 0 },
    { label: "Chờ xử lý", value: stats?.pending ?? 0 },
    { label: "Hoàn thành", value: stats?.completed ?? 0 },
    { label: "Thất bại", value: stats?.failed ?? 0 },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div className="mb-8">
        <h1 className="text-lg font-bold text-vocal">Tổng quan hệ thống</h1>
        <p className="text-sm text-echo">Thống kê hoạt động và tác vụ gần đây.</p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6 mb-8">
        {statItems.map((s, i) => (
          <motion.div
            key={s.label}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.08, ease: [0.25, 0.1, 0.25, 1] }}
            className="border-b border-phantom py-6"
          >
            <p className="text-xs uppercase tracking-wider text-echo mb-1">{s.label}</p>
            <p className="font-mono font-bold text-3xl text-signal">{s.value}</p>
          </motion.div>
        ))}
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-echo">Tác vụ gần đây</h2>
          <button
            onClick={loadOverviewTasks}
            disabled={loading}
            className="p-1.5 rounded-md text-echo hover:text-vocal hover:bg-strip transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div>
          <div className="grid grid-cols-[1fr_120px_140px_100px] gap-4 px-4 py-2 text-xs uppercase tracking-wider text-dimmer border-b border-phantom">
            <span>Nội dung</span>
            <span>Trạng thái</span>
            <span>Thời gian</span>
            <span className="text-right">Hành động</span>
          </div>

          {overviewTasks.length === 0 ? (
            <div className="text-center py-12 text-echo font-mono text-xs">
              {loading ? (
                <span className="inline-flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-dimmer animate-pulse" />
                  Đang tải...
                </span>
              ) : "Chưa có tác vụ nào"}
            </div>
          ) : (
            overviewTasks.map((t) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="grid grid-cols-[1fr_120px_140px_100px] gap-4 px-4 py-3 border-b border-phantom hover:bg-strip/50 transition-colors text-xs"
              >
                <span className="truncate text-vocal">{t.text}</span>
                <span className="flex items-center text-echo font-mono">
                  <StatusDot status={t.status} />
                  {t.status}
                </span>
                <span className="font-mono text-echo">
                  {new Date(t.created_at).toLocaleString("vi-VN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    day: "2-digit",
                    month: "2-digit",
                  })}
                </span>
                <span className="text-right">
                  {t.status === "FAILED" && (
                    <button
                      onClick={() => retryTask(t.id)}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded text-echo hover:text-vocal hover:bg-strip transition-colors font-mono text-xs"
                    >
                      <RefreshCw className="w-3 h-3" />
                      Retry
                    </button>
                  )}
                </span>
              </motion.div>
            ))
          )}
        </div>
      </div>
    </motion.div>
  );
}
