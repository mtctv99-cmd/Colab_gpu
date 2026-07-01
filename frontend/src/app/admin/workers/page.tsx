"use client";
import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Server, Activity, Clock } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface WorkerSession {
  id: number;
  email: string;
  worker_session_id: string;
  status: string;
  started_at: string | null;
  last_alive_at: string | null;
}

interface WorkerHealthEntry {
  email: string;
  gpu: string;
  type: string;
  status: string;
  connected_at: string | null;
  uptime_seconds: number;
  expiring: boolean;
  remaining_seconds: number;
}

export default function WorkersPage() {
  const [workers, setWorkers] = useState<WorkerHealthEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const loadWorkers = useCallback(async () => {
    setLoading(true);
    try {
      const data: WorkerHealthEntry[] = await api("/api/health/workers");
      setWorkers(data || []);
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadWorkers(); }, [loadWorkers]);

  const StatusDot = ({ status }: { status: string }) => {
    const color = status === "ACTIVE" ? "bg-online" : "bg-alert";
    return <span className={`inline-block w-2 h-2 rounded-full ${color} mr-2`} />;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-vocal">Worker Sessions</h2>
          <p className="text-sm text-echo">Danh sách các worker Colab đang kết nối qua WebSocket.</p>
        </div>
        <button
          onClick={loadWorkers}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-signal text-pitch text-sm font-medium disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Làm mới
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6">
        <div className="border border-phantom bg-console rounded-xl p-5">
          <div className="flex items-center gap-3 text-echo mb-2">
            <Activity className="w-5 h-5" />
            <h3 className="text-sm uppercase tracking-wider font-semibold">Active Workers</h3>
          </div>
          <p className="text-3xl font-mono text-vocal">{workers.length}</p>
        </div>
      </div>

      <div className="border border-phantom rounded-xl overflow-hidden bg-console">
        <table className="w-full">
          <thead>
            <tr className="border-b border-phantom bg-pitch/50">
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">Email</th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">Status</th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">GPU</th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">Uptime</th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">Connected</th>
            </tr>
          </thead>
          <tbody>
            {workers.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-echo text-sm font-mono">
                  {loading ? "Đang tải..." : "Không có worker nào kết nối"}
                </td>
              </tr>
            ) : (
              workers.map((w) => (
                <tr key={w.email} className="border-b border-phantom hover:bg-strip/50 transition-colors">
                  <td className="py-3 px-4 text-sm text-echo">{w.email}</td>
                  <td className="py-3 px-4 text-sm">
                    <StatusDot status={w.status === "IDLE" ? "ACTIVE" : w.status} />
                    <span className="font-mono text-xs text-echo">{w.status}</span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">{w.gpu || "-"}</td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {w.uptime_seconds > 0 ? `${Math.floor(w.uptime_seconds / 60)}m` : "-"}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {w.connected_at ? new Date(w.connected_at).toLocaleString() : "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
