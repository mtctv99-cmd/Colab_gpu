"use client";
import { useEffect, useState, useCallback } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface SatelliteNode {
  node_id: string;
  capacity: number;
  active_workers: number;
  version: string;
  last_seen: string;
  status: string;
}

export default function NodesPage() {
  const [nodes, setNodes] = useState<SatelliteNode[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setNodes(await api("/api/node/list"));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-vocal">Vệ tinh (Satellite Nodes)</h2>
          <p className="text-sm text-echo">Các node chạy colabcli, sẵn sàng launch worker Colab khi master yêu cầu.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors disabled:opacity-50"
        >
          {loading ? (
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

      {nodes.length === 0 ? (
        <div className="text-center py-16 text-echo font-mono text-xs">
          {loading ? (
            <span className="inline-flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-dimmer animate-pulse" />
              Đang tải...
            </span>
          ) : (
            "Chưa có vệ tinh nào kết nối."
          )}
        </div>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="border-b border-phantom">
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Node ID</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Trạng thái</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Capacity</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Worker đang chạy</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Version</th>
              <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Lần cuối</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((n) => {
              const lastSeen = n.last_seen ? new Date(n.last_seen + "Z") : null;
              const ago = lastSeen ? Math.floor((Date.now() - lastSeen.getTime()) / 1000) : null;
              const isOnline = n.status === "ONLINE" && ago !== null && ago < 120;

              return (
                <tr key={n.node_id} className="border-b border-phantom hover:bg-strip/50 transition-colors">
                  <td className="py-3 px-4 font-mono text-xs text-vocal">{n.node_id}</td>
                  <td className="py-3 px-4">
                    <span className={`inline-flex items-center gap-1.5 font-mono text-xs ${isOnline ? "text-online" : "text-alert"}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${isOnline ? "bg-online" : "bg-alert"}`} />
                      {isOnline ? "ONLINE" : "OFFLINE"}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">{n.capacity}</td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">{n.active_workers}</td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">{n.version || "-"}</td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {ago !== null ? ago < 60 ? `${ago}s` : `${Math.floor(ago / 60)}m` : "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
