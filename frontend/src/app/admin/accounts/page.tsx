"use client";
import { useEffect, useState, useCallback } from "react";
import { Play, Square, LogIn, Trash2, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface WorkerAccount {
  id: number;
  email: string;
  status: string;
  runtime_status: string | null;
  started_at: string | null;
  quota_reset_at: string | null;
  token_ok?: boolean;
  token_expiry?: string | null;
  assigned_node_id?: string | null;
}

function StatusDot({ status }: { status: string }) {
  const color: Record<string, string> = {
    READY: "bg-online",
    IDLE: "bg-online",
    COOLDOWN: "bg-signal",
    BUSY: "bg-signal",
    STARTING: "bg-signal animate-pulse",
    WARMING: "bg-signal animate-pulse",
    LOST: "bg-alert",
    NEEDS_LOGIN: "bg-alert",
    DRAINING: "bg-dimmer",
    DISABLED: "bg-dimmer",
  };
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${color[status] || "bg-dimmer"}`} />;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<WorkerAccount[]>([]);
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [newAccountEmail, setNewAccountEmail] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [stopConfirmId, setStopConfirmId] = useState<number | null>(null);
  const [deleteConfirmAccount, setDeleteConfirmAccount] = useState<WorkerAccount | null>(null);
  const [authAccount, setAuthAccount] = useState<WorkerAccount | null>(null);
  const [authUrl, setAuthUrl] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [isAuthLoading, setIsAuthLoading] = useState(false);

  const loadAccounts = useCallback(async () => {
    setIsRefreshing(true);
    try {
      setAccounts(await api("/api/accounts/"));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => { loadAccounts(); }, [loadAccounts]);

  const addAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await api("/api/accounts/add", { method: "POST", body: JSON.stringify({ email: newAccountEmail }) });
      toast.success("Đã thêm tài khoản và đang mở trình duyệt đăng nhập...");
      setNewAccountEmail("");
      setShowAddPanel(false);
      await loadAccounts();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const startWorker = async (id: number, type: string = "tts") => {
    try {
      await api(`/api/accounts/${id}/start?type=${type}`, { method: "POST" });
      toast.success(`Đang khởi động worker ${type.toUpperCase()}...`);
      loadAccounts();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const stopWorker = async (id: number) => {
    try {
      await api(`/api/accounts/${id}/stop`, { method: "POST" });
      toast.success("Đã dừng worker.");
      loadAccounts();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const reloginAccount = async (id: number) => {
    try {
      toast.info("Đang mở trình duyệt đăng nhập Google trên server...");
      await api(`/api/accounts/${id}/relogin`, { method: "POST" });
      toast.success("Trình duyệt đăng nhập đã mở. Hãy đăng nhập trực tiếp trên cửa sổ trình duyệt đó.");
      loadAccounts();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const deleteAccount = async (id: number) => {
    try {
      await api(`/api/accounts/${id}`, { method: "DELETE" });
      toast.success("Đã xóa tài khoản");
      loadAccounts();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-vocal">Tài khoản Google/Colab</h2>
          <p className="text-sm text-echo">Quản lý worker, đăng nhập lại, xóa tài khoản.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadAccounts}
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
          <button
            onClick={() => setShowAddPanel(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            Thêm tài khoản
          </button>
        </div>
      </div>

      <table className="w-full">
        <thead>
          <tr className="border-b border-phantom">
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Email</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Trạng thái</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Loại</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Uptime</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Cooldown</th>
            <th className="text-right py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Hành động</th>
          </tr>
        </thead>
        <tbody>
          {accounts.length === 0 ? (
            <tr>
              <td colSpan={6} className="text-center py-12 text-echo font-mono text-xs">
                {isRefreshing ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-dimmer animate-pulse" />
                    Đang tải...
                  </span>
                ) : "Chưa có tài khoản"}
              </td>
            </tr>
          ) : accounts.map(a => {
            let uptime = "";
            const isRunning = ["STARTING", "WARMING", "IDLE", "BUSY", "DRAINING"].includes(a.runtime_status ?? "");
            if (isRunning && a.started_at) {
              const diff = Math.floor((Date.now() - new Date(a.started_at).getTime()) / 1000);
              if (diff > 0 && diff < 86400) {
                const h = Math.floor(diff / 3600);
                const m = Math.floor((diff % 3600) / 60);
                uptime = h > 0 ? `${h}h ${m}m` : `${m}m`;
              }
            }

            let cooldownLeft = "";
            let cooldownExpired = false;
            if (a.quota_reset_at) {
              const remaining = Math.floor((new Date(a.quota_reset_at).getTime() - Date.now()) / 1000);
              if (remaining > 0) {
                const h = Math.floor(remaining / 3600);
                const m = Math.floor((remaining % 3600) / 60);
                cooldownLeft = h > 0 ? `${h}h ${m}m` : `${m}m`;
              } else {
                cooldownExpired = true;
                cooldownLeft = "Hết cooldown";
              }
            }

            return (
                <tr key={a.id} className="border-b border-phantom hover:bg-strip/50 transition-colors">
                  <td className="py-3 px-4 font-medium text-vocal text-sm">{a.email}</td>
                  <td className="py-3 px-4">
                    <span className="inline-flex items-center gap-1 text-xs font-mono text-echo">
                      <StatusDot status={a.runtime_status ?? a.status} />
                      {a.runtime_status ?? a.status}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {a.assigned_node_id ? (
                      <span className="text-dimmer">Vệ tinh</span>
                    ) : a.runtime_status ? (
                      <span className="text-signal">Cục bộ</span>
                    ) : (
                      <span className="text-dimmer">-</span>
                    )}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                  {isRunning ? (
                    <span className="text-signal">{uptime || "0m"}</span>
                  ) : (
                    a.started_at ? new Date(a.started_at).toLocaleString() : "-"
                  )}
                </td>
                <td className="py-3 px-4 font-mono text-xs text-echo">
                  {cooldownLeft ? (
                    <span className={cooldownExpired ? "text-signal" : "text-echo"}>{cooldownLeft}</span>
                  ) : "-"}
                </td>
                <td className="py-3 px-4 text-right">
                  <div className="inline-flex items-center gap-1">
                    {!a.runtime_status && (
                      <>
                        <button
                          onClick={() => reloginAccount(a.id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs text-echo hover:text-vocal hover:bg-strip transition-colors"
                        >
                          <LogIn className="w-3.5 h-3.5" />
                          Đăng nhập
                        </button>
                        <button
                          onClick={() => startWorker(a.id, "tts")}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
                        >
                          <Play className="w-3.5 h-3.5" />
                          Khởi động TTS
                        </button>
                      </>
                    )}
                    {a.runtime_status && (
                      <button
                        onClick={() => setStopConfirmId(a.id)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium bg-alert/10 text-alert hover:bg-alert/20 transition-colors"
                      >
                        <Square className="w-3.5 h-3.5" />
                        Stop
                      </button>
                    )}
                    <button
                      onClick={() => setDeleteConfirmAccount(a)}
                      className="p-1.5 rounded text-alert/60 hover:text-alert hover:bg-alert/10 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {showAddPanel && (
        <div className="fixed inset-0 z-50" onClick={() => setShowAddPanel(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="fixed right-0 top-0 h-full w-96 bg-console border-l border-phantom shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="p-6">
              <h3 className="text-sm font-semibold text-vocal mb-1">Thêm tài khoản</h3>
              <p className="text-xs text-echo mb-6">Nhập email Google để thêm worker mới.</p>
              <form onSubmit={addAccount} className="space-y-4">
                <input
                  required
                  type="email"
                  placeholder="email@domain.com"
                  value={newAccountEmail}
                  onChange={e => setNewAccountEmail(e.target.value)}
                  className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
                />
                <div className="flex items-center gap-2">
                  <button
                    type="submit"
                    className="flex-1 px-3 py-2 rounded text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
                  >
                    Thêm
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowAddPanel(false)}
                    className="px-3 py-2 rounded text-sm text-echo hover:text-vocal hover:bg-strip transition-colors"
                  >
                    Hủy
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      <AlertDialog open={stopConfirmId !== null} onOpenChange={(o) => !o && setStopConfirmId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Dừng worker này?</AlertDialogTitle>
            <AlertDialogDescription>Tiến trình tổng hợp hiện tại sẽ bị gián đoạn.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={() => { if (stopConfirmId) stopWorker(stopConfirmId); setStopConfirmId(null); }}>Đồng ý</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={deleteConfirmAccount !== null} onOpenChange={(o) => !o && setDeleteConfirmAccount(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xác nhận xóa tài khoản</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa <span className="font-semibold text-vocal">{deleteConfirmAccount?.email}</span>? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Hủy</AlertDialogCancel>
            <AlertDialogAction className="bg-alert hover:bg-alert/80 text-vocal" onClick={() => { if (deleteConfirmAccount) deleteAccount(deleteConfirmAccount.id); setDeleteConfirmAccount(null); }}>Xóa</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>


    </div>
  );
}
