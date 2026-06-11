"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { HiArrowRight, HiUsers, HiMicrophone, HiServerStack, HiKey, HiTrash, HiChartBar, HiArrowPath, HiArrowLeftOnRectangle } from "react-icons/hi2";
import { motion, AnimatePresence } from "motion/react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface AdminUser {
  id: number;
  email: string;
  role: string;
  balance: number;
  is_active: boolean;
  created_at: string;
}

interface WorkerAccount {
  id: number;
  email: string;
  status: string;
  started_at: string | null;
  quota_reset_at: string | null;
}

interface Voice {
  id: number;
  name: string;
  transcript: string;
  audio_path: string;
}

interface AdminApiKey {
  id: number;
  key_prefix: string;
  name: string;
  is_active: boolean;
  user_id: number;
  user_email: string;
  created_at: string | null;
  last_used_at: string | null;
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

interface Stats {
  total_tasks: number;
  completed: number;
  failed: number;
  pending: number;
  active_workers: number;
}

interface ConfirmModal {
  message: string;
  onConfirm: () => void;
}

export default function AdminPage() {
  const router = useRouter();
  const [tab, setTab] = useState("overview");
  const [accounts, setAccounts] = useState<WorkerAccount[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [apiKeys, setApiKeys] = useState<AdminApiKey[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [overviewTasks, setOverviewTasks] = useState<AdminTask[]>([]);

  // Form states
  const [newAccountEmail, setNewAccountEmail] = useState("");
  const [newVoiceName, setNewVoiceName] = useState("");
  const [newVoiceTranscript, setNewVoiceTranscript] = useState("");
  const [newVoiceFile, setNewVoiceFile] = useState<File | null>(null);

  // New user form
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserRole, setNewUserRole] = useState("user");

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<ConfirmModal | null>(null);

  // Balance inline edit state
  const [editingBalance, setEditingBalance] = useState<{ userId: number; value: string } | null>(null);
  const balanceInputRef = useRef<HTMLInputElement>(null);

  // Auth check
  useEffect(() => {
    const t = localStorage.getItem("token");
    const uStr = localStorage.getItem("user");
    if (!t || !uStr) { router.push("/login"); return; }
    try {
      const u = JSON.parse(uStr);
      if (u.role !== "admin") { router.push("/dashboard"); return; }
    } catch { router.push("/login"); }
  }, [router]);

  const loadAccounts = useCallback(async () => {
    try { setAccounts(await api("/api/accounts/")); } catch (e: any) { toast.error(e.message); }
  }, []);

  const loadUsers = useCallback(async () => {
    try { setUsers(await api("/api/auth/admin/users")); } catch (e: any) { toast.error(e.message); }
  }, []);

  const loadVoices = useCallback(async () => {
    try { setVoices(await api("/api/voices/")); } catch (e: any) { toast.error(e.message); }
  }, []);

  const loadApiKeys = useCallback(async () => {
    try { setApiKeys(await api("/api/auth/admin/api-keys")); } catch (e: any) { toast.error(e.message); }
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const [healthRes, statsRes] = await Promise.all([
        api("/api/health/") as Promise<any>,
        api("/api/health/stats") as Promise<Stats>,
      ]);
      setStats({ ...statsRes, active_workers: healthRes.workers?.active_connections ?? statsRes.active_workers });
    } catch (e: any) { toast.error(e.message); }
  }, []);

  const loadOverviewTasks = useCallback(async () => {
    try {
      setOverviewTasks(await api("/api/tasks/?limit=10"));
    } catch (e: any) { toast.error(e.message); }
  }, []);

  const retryTask = async (taskId: string) => {
    try {
      await api(`/api/tasks/${taskId}/retry`, { method: "POST" });
      toast.success("Đã gửi lại task");
      loadOverviewTasks();
      loadStats();
    } catch (e: any) { toast.error(e.message); }
  };

  useEffect(() => {
    if (tab === "overview") { loadStats(); loadOverviewTasks(); }
    if (tab === "accounts") loadAccounts();
    if (tab === "users") loadUsers();
    if (tab === "voices") loadVoices();
    if (tab === "apikeys") { loadApiKeys(); loadUsers(); }
  }, [tab, loadAccounts, loadUsers, loadVoices, loadApiKeys, loadStats, loadOverviewTasks]);

  // Focus balance input when it appears
  useEffect(() => {
    if (editingBalance) balanceInputRef.current?.focus();
  }, [editingBalance]);

  // ── Account actions ──
  const addAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/accounts/add", { method: "POST", body: JSON.stringify({ email: newAccountEmail }) });
      toast.success("Đã mở browser đăng nhập Google");
      setNewAccountEmail("");
      loadAccounts();
    } catch (e: any) { toast.error(e.message); }
  };

  const startWorker = async (id: number) => {
    try { await api(`/api/accounts/${id}/start`, { method: "POST" }); toast.success("Đang khởi động worker..."); loadAccounts(); }
    catch (e: any) { toast.error(e.message); }
  };

  const stopWorker = (id: number) => {
    setConfirmModal({
      message: "Dừng worker này?",
      onConfirm: async () => {
        try { await api(`/api/accounts/${id}/stop`, { method: "POST" }); toast.success("Đã dừng worker."); loadAccounts(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  const reloginAccount = async (id: number, email: string) => {
    try {
      await api(`/api/accounts/${id}/relogin`, { method: "POST" });
      toast.info(`Đang mở browser đăng nhập cho ${email}...`);
      loadAccounts();
    } catch (e: any) { toast.error(e.message); }
  };

  const deleteAccount = (id: number, email: string) => {
    setConfirmModal({
      message: `Xoá tài khoản ${email}?`,
      onConfirm: async () => {
        try { await api(`/api/accounts/${id}`, { method: "DELETE" }); toast.success("Đã xoá tài khoản"); loadAccounts(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  // ── User actions ──
  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/auth/admin/users", { method: "POST", body: JSON.stringify({ email: newUserEmail, password: newUserPassword, role: newUserRole }) });
      toast.success("Tạo user thành công");
      setNewUserEmail(""); setNewUserPassword(""); setNewUserRole("user");
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  const deleteUser = (id: number, email: string) => {
    setConfirmModal({
      message: `Xoá user ${email}?`,
      onConfirm: async () => {
        try { await api(`/api/auth/admin/users/${id}`, { method: "DELETE" }); toast.success("Đã xoá user"); loadUsers(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  const updateUserBalance = async (id: number, value: string) => {
    const amount = parseInt(value);
    if (isNaN(amount)) { toast.error("Balance không hợp lệ"); return; }
    try {
      await api(`/api/auth/admin/users/${id}`, { method: "PUT", body: JSON.stringify({ balance: amount }) });
      toast.success("Đã cập nhật balance");
      setEditingBalance(null);
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  const toggleUserActive = async (id: number, current: boolean) => {
    try {
      await api(`/api/auth/admin/users/${id}`, { method: "PUT", body: JSON.stringify({ is_active: !current }) });
      toast.success(current ? "Đã vô hiệu hoá user" : "Đã kích hoạt user");
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  // ── Voice actions ──
  const addVoice = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newVoiceFile) return toast.error("Vui lòng chọn file âm thanh");
    const fd = new FormData();
    fd.append("name", newVoiceName);
    fd.append("transcript", newVoiceTranscript);
    fd.append("audio", newVoiceFile);
    try {
      await api("/api/voices/", { method: "POST", body: fd });
      toast.success("Thêm giọng nói thành công");
      setNewVoiceName(""); setNewVoiceTranscript(""); setNewVoiceFile(null);
      loadVoices();
    } catch (e: any) { toast.error(e.message); }
  };

  const deleteVoice = (id: number) => {
    setConfirmModal({
      message: "Xoá giọng nói này?",
      onConfirm: async () => {
        try { await api(`/api/voices/${id}`, { method: "DELETE" }); toast.success("Đã xoá giọng nói"); loadVoices(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  // ── API Key actions ──
  const [newKeyUserId, setNewKeyUserId] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyDisplay, setNewKeyDisplay] = useState<string | null>(null);

  const createApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyUserId) return toast.error("Chọn user");
    try {
      const data = await api("/api/auth/admin/api-keys", { method: "POST", body: JSON.stringify({ user_id: parseInt(newKeyUserId), name: newKeyName || "Default" }) });
      setNewKeyDisplay(data.key);
      toast.success("Tạo key thành công");
      setNewKeyName("");
      loadApiKeys();
    } catch (e: any) { toast.error(e.message); }
  };

  const deactivateApiKey = (id: number) => {
    setConfirmModal({
      message: "Vô hiệu hoá API key này?",
      onConfirm: async () => {
        try { await api(`/api/auth/api-keys/${id}`, { method: "DELETE" }); toast.success("Đã vô hiệu hoá key"); loadApiKeys(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  const deleteApiKey = (id: number) => {
    setConfirmModal({
      message: "Xoá API key này vĩnh viễn?",
      onConfirm: async () => {
        try { await api(`/api/auth/admin/api-keys/${id}`, { method: "DELETE" }); toast.success("Đã xoá key"); loadApiKeys(); }
        catch (e: any) { toast.error(e.message); }
      },
    });
  };

  // ── Status color helper ──
  const statusStyle = (s: string) => {
    const map: Record<string, string> = {
      ACTIVE: "bg-brand/10 text-brand",
      BUSY: "bg-blue-950/50 text-blue-400",
      IDLE: "bg-brand/10 text-brand",
      LOADING: "bg-yellow-950/50 text-yellow-400 animate-pulse",
      OFFLINE: "bg-zinc-800 text-zinc-400",
      NEEDS_LOGIN: "bg-red-950/50 text-red-400",
      CONNECTING: "bg-yellow-950/50 text-yellow-400",
      COOLDOWN: "bg-orange-950/50 text-orange-400",
    };
    return map[s] || "bg-zinc-800 text-zinc-400";
  };

  const tabs = [
    { id: "overview", label: "Tổng quan", icon: HiChartBar },
    { id: "accounts", label: "Colab Workers", icon: HiServerStack },
    { id: "users", label: "Người dùng", icon: HiUsers },
    { id: "apikeys", label: "API Keys", icon: HiKey },
    { id: "voices", label: "Giọng nói", icon: HiMicrophone },
  ];

  return (
    <div className="min-h-[100dvh] bg-zinc-950 flex flex-col md:flex-row">
      {/* Sidebar */}
      <aside className="w-full md:w-64 border-r border-zinc-800 bg-zinc-900/50 flex-shrink-0">
        <div className="p-6">
          <Link href="/dashboard" className="font-bold tracking-tight">
            clone<span className="text-brand">.</span>tts
            <span className="ml-2 text-xs font-mono text-zinc-500 uppercase tracking-wider">ADMIN</span>
          </Link>
        </div>
        <nav className="flex md:flex-col gap-1 px-4 overflow-x-auto pb-4">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-colors whitespace-nowrap ${tab === t.id ? "bg-brand/10 text-brand font-medium" : "text-zinc-400 hover:bg-zinc-800/50 hover:text-white"}`}
            >
              <t.icon className="w-4 h-4" />
              {t.label}
            </button>
          ))}
        </nav>

        <div className="p-4 border-t border-zinc-800 mt-auto">
          <button
            onClick={() => { localStorage.clear(); router.push("/"); }}
            className="flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-zinc-400 hover:bg-red-950/30 hover:text-red-400 transition-colors w-full"
          >
            <HiArrowLeftOnRectangle className="w-4 h-4" />
            Đăng xuất
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 p-6 lg:p-8 max-w-6xl">

        {/* ═══════ OVERVIEW ═══════ */}
        {tab === "overview" && (
          <div className="space-y-8">
            <div>
              <h2 className="text-xl font-bold mb-1">Tổng quan hệ thống</h2>
              <p className="text-sm text-zinc-500">Thống kê hoạt động và tác vụ gần đây.</p>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Tổng Worker", value: stats?.active_workers ?? 0, color: "text-brand" },
                { label: "Task thành công", value: stats?.completed ?? 0, color: "text-emerald-400" },
                { label: "Task đang chờ", value: stats?.pending ?? 0, color: "text-yellow-400" },
                { label: "Task thất bại", value: stats?.failed ?? 0, color: "text-red-400" },
              ].map(s => (
                <div key={s.label} className="bg-zinc-900/50 border border-zinc-800 p-5 rounded-xl">
                  <div className="text-xs text-zinc-500 uppercase tracking-wider mb-1">{s.label}</div>
                  <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
                </div>
              ))}
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Tác vụ gần đây</h3>
                <button onClick={loadOverviewTasks} className="text-zinc-500 hover:text-white transition-colors">
                  <HiArrowPath className="w-4 h-4" />
                </button>
              </div>

              <div className="border border-zinc-800 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-zinc-900/50 border-b border-zinc-800">
                      <th className="px-4 py-3 text-left font-medium text-zinc-500">Nội dung</th>
                      <th className="px-4 py-3 text-left font-medium text-zinc-500">Trạng thái</th>
                      <th className="px-4 py-3 text-left font-medium text-zinc-500">Thời gian</th>
                      <th className="px-4 py-3 text-right"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/50">
                    {overviewTasks.length === 0 ? (
                      <tr><td colSpan={4} className="text-center py-12 text-zinc-600">Chưa có tác vụ nào</td></tr>
                    ) : overviewTasks.map(t => (
                      <tr key={t.id} className="hover:bg-zinc-900/30 transition-colors">
                        <td className="px-4 py-3 max-w-[300px] truncate">
                          <span className="text-zinc-300">{t.text}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase tracking-tight ${
                            t.status === "COMPLETED" ? "bg-emerald-950/50 text-emerald-400" :
                            t.status === "FAILED" ? "bg-red-950/50 text-red-400" :
                            t.status === "PROCESSING" ? "bg-blue-950/50 text-blue-400 animate-pulse" :
                            "bg-zinc-800 text-zinc-500"
                          }`}>
                            {t.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-zinc-500 text-xs">
                          {new Date(t.created_at).toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {t.status === "FAILED" && (
                            <button
                              onClick={() => retryTask(t.id)}
                              className="inline-flex items-center gap-1 text-xs text-brand hover:underline"
                              title="Thử lại"
                            >
                              <HiArrowPath className="w-3 h-3" />
                              Retry
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ═══════ ACCOUNTS ═══════ */}
        {tab === "accounts" && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold mb-1">Tài khoản Google/Colab</h2>
              <p className="text-sm text-zinc-500">Quản lý worker, đăng nhập lại Google, xoá tài khoản.</p>
            </div>
            <form onSubmit={addAccount} className="flex gap-3">
              <input required type="email" placeholder="Nhập email Google mới..." value={newAccountEmail}
                onChange={e => setNewAccountEmail(e.target.value)}
                className="flex-1 px-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand" />
              <button type="submit" className="bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200">
                + Thêm tài khoản
              </button>
            </form>
            <div className="border border-zinc-800 rounded-xl overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-zinc-900/50 border-b border-zinc-800">
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Email</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Status</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Thời gian chạy</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Cooldown</th>
                    <th className="px-4 py-3 text-right font-medium text-zinc-500">Hành động</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.length === 0 ? (
                    <tr><td colSpan={5} className="text-center py-8 text-zinc-600">Chưa có tài khoản</td></tr>
                  ) : accounts.map(a => {
                    // Tính thời gian đã chạy — chỉ tính cho ACTIVE/CONNECTING/BUSY/LOADING
                    let uptime = "";
                    const isRunning = ["ACTIVE", "CONNECTING", "BUSY", "LOADING", "IDLE"].includes(a.status);
                    if (isRunning && a.started_at) {
                      const start = new Date(a.started_at).getTime();
                      const now = Date.now();
                      const diff = Math.floor((now - start) / 1000);
                      if (diff > 0 && diff < 3600 * 24) { // tránh overflow
                        const h = Math.floor(diff / 3600);
                        const m = Math.floor((diff % 3600) / 60);
                        uptime = h > 0 ? `${h}h ${m}m` : `${m}m`;
                      }
                    }
                    // Tính cooldown còn lại
                    let cooldownLeft = "";
                    let cooldownExpired = false;
                    if (a.quota_reset_at) {
                      const reset = new Date(a.quota_reset_at).getTime();
                      const now = Date.now();
                      const remaining = Math.floor((reset - now) / 1000);
                      if (remaining > 0) {
                        const h = Math.floor(remaining / 3600);
                        const m = Math.floor((remaining % 3600) / 60);
                        cooldownLeft = h > 0 ? `Còn ${h}h ${m}m` : `Còn ${m}m`;
                      } else {
                        cooldownExpired = true;
                        cooldownLeft = "Hết cooldown";
                      }
                    }
                    return (
                    <tr key={a.id} className="border-b border-zinc-800/50">
                      <td className="px-4 py-3 font-medium">{a.email}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${statusStyle(a.status)}`}>{a.status}</span>
                      </td>
                      <td className="px-4 py-3 text-zinc-500 text-xs">
                        {isRunning ? (
                          <span className="text-brand font-medium">{uptime || "0m"}</span>
                        ) : (
                          a.started_at ? new Date(a.started_at).toLocaleString() : '-'
                        )}
                      </td>
                      <td className="px-4 py-3 text-zinc-500 text-xs">
                        {cooldownLeft ? (
                          <span className={cooldownExpired ? "text-brand" : "text-yellow-400"}>{cooldownLeft}</span>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {a.status === "NEEDS_LOGIN" && (
                            <button onClick={() => reloginAccount(a.id, a.email)}
                              className="text-xs px-2.5 py-1 rounded bg-yellow-950/50 text-yellow-400 hover:bg-yellow-900/50">Login lại</button>
                          )}
                          {a.status === "OFFLINE" && !cooldownLeft && (
                            <button onClick={() => startWorker(a.id)}
                              className="text-xs px-2.5 py-1 rounded bg-brand/10 text-brand hover:bg-brand/20">Start</button>
                          )}
                          {(a.status === "ACTIVE" || a.status === "CONNECTING") && (
                            <button onClick={() => stopWorker(a.id)}
                              className="text-xs px-2.5 py-1 rounded bg-red-950/50 text-red-400 hover:bg-red-900/50">Stop</button>
                          )}
                          <button onClick={() => deleteAccount(a.id, a.email)}
                            className="text-zinc-500 hover:text-red-400 transition-colors">
                            <HiTrash className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ═══════ USERS ═══════ */}
        {tab === "users" && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold mb-1">Người dùng</h2>
              <p className="text-sm text-zinc-500">Thêm, xoá, nạp ký tự, vô hiệu hoá user.</p>
            </div>

            <form onSubmit={createUser} className="flex gap-3 items-end flex-wrap">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-xs text-zinc-500 mb-1">Email</label>
                <input required type="email" value={newUserEmail} onChange={e => setNewUserEmail(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand" />
              </div>
              <div className="flex-1 min-w-[150px]">
                <label className="block text-xs text-zinc-500 mb-1">Mật khẩu</label>
                <input required type="password" value={newUserPassword} onChange={e => setNewUserPassword(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand" />
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Role</label>
                <select value={newUserRole} onChange={e => setNewUserRole(e.target.value)}
                  className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand">
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </div>
              <button type="submit" className="bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200">
                Tạo user
              </button>
            </form>

            <div className="border border-zinc-800 rounded-xl overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-zinc-900/50 border-b border-zinc-800">
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Email</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Role</th>
                    <th className="px-4 py-3 text-right font-medium text-zinc-500">Balance</th>
                    <th className="px-4 py-3 text-center font-medium text-zinc-500">Active</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Đã tạo</th>
                    <th className="px-4 py-3 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {users.length === 0 ? (
                    <tr><td colSpan={6} className="text-center py-8 text-zinc-600">Chưa có user</td></tr>
                  ) : users.map(u => (
                    <tr key={u.id} className="border-b border-zinc-800/50">
                      <td className="px-4 py-3 font-medium">{u.email}</td>
                      <td className="px-4 py-3">
                        <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">{u.role}</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        {editingBalance?.userId === u.id ? (
                          <div className="inline-flex items-center gap-1">
                            <input
                              ref={balanceInputRef}
                              type="number"
                              value={editingBalance.value}
                              onChange={e => setEditingBalance({ userId: u.id, value: e.target.value })}
                              onKeyDown={e => {
                                if (e.key === "Enter") updateUserBalance(u.id, editingBalance.value);
                                if (e.key === "Escape") setEditingBalance(null);
                              }}
                              onBlur={() => setEditingBalance(null)}
                              className="w-24 px-2 py-1 bg-zinc-800 border border-brand/50 rounded text-sm text-white text-right font-mono focus:outline-none"
                              autoFocus
                            />
                          </div>
                        ) : (
                          <button
                            onClick={() => setEditingBalance({ userId: u.id, value: String(u.balance) })}
                            className="font-mono text-brand hover:underline cursor-pointer"
                          >
                            {u.balance.toLocaleString()}
                          </button>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button onClick={() => toggleUserActive(u.id, u.is_active)}
                          className={`text-xs px-2 py-0.5 rounded-full cursor-pointer ${u.is_active ? "bg-brand/10 text-brand" : "bg-red-950/50 text-red-400"}`}>
                          {u.is_active ? "Active" : "Inactive"}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-zinc-500 text-xs">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString() : '-'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => deleteUser(u.id, u.email)} className="text-zinc-500 hover:text-red-400 transition-colors">
                          <HiTrash className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ═══════ API KEYS ═══════ */}
        {tab === "apikeys" && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold mb-1">API Keys</h2>
              <p className="text-sm text-zinc-500">Tạo key cho user, vô hiệu hoá hoặc xoá key.</p>
            </div>

            <form onSubmit={createApiKey} className="flex gap-3 items-end flex-wrap">
              <div className="min-w-[200px] flex-1">
                <label className="block text-xs text-zinc-500 mb-1">User</label>
                <select value={newKeyUserId} onChange={e => setNewKeyUserId(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand">
                  <option value="">-- Chọn user --</option>
                  {users.filter(u => u.is_active).map(u => (
                    <option key={u.id} value={u.id}>{u.email} ({u.role})</option>
                  ))}
                </select>
              </div>
              <div className="min-w-[150px] flex-1">
                <label className="block text-xs text-zinc-500 mb-1">Tên key</label>
                <input value={newKeyName} onChange={e => setNewKeyName(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand" />
              </div>
              <button type="submit" className="bg-white text-black px-4 py-2 rounded-lg text-sm font-medium hover:bg-zinc-200">Tạo key</button>
            </form>

            {newKeyDisplay && (
              <div className="rounded-lg border border-brand/30 bg-brand/5 p-4">
                <p className="text-xs text-zinc-400 mb-2">Key mới — copy ngay, sẽ không hiển thị lại:</p>
                <code className="text-sm text-brand break-all">{newKeyDisplay}</code>
                <button onClick={() => { navigator.clipboard.writeText(newKeyDisplay); setNewKeyDisplay(null); toast.success("Đã copy"); }}
                  className="mt-2 inline-flex items-center gap-1 text-xs text-brand hover:underline">Đã copy</button>
              </div>
            )}

            <div className="border border-zinc-800 rounded-xl overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-zinc-900/50 border-b border-zinc-800">
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">User</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Tên</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Key Prefix</th>
                    <th className="px-4 py-3 text-center font-medium text-zinc-500">Trạng thái</th>
                    <th className="px-4 py-3 text-right font-medium text-zinc-500">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.length === 0 ? (
                    <tr><td colSpan={5} className="text-center py-8 text-zinc-600">Chưa có API key nào</td></tr>
                  ) : apiKeys.map(k => (
                    <tr key={k.id} className="border-b border-zinc-800/50">
                      <td className="px-4 py-3 text-zinc-400 text-xs">{k.user_email}</td>
                      <td className="px-4 py-3">{k.name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-zinc-500">{k.key_prefix}...</td>
                      <td className="px-4 py-3 text-center">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${k.is_active ? "bg-brand/10 text-brand" : "bg-zinc-800 text-zinc-500"}`}>
                          {k.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {k.is_active && (
                            <button onClick={() => deactivateApiKey(k.id)}
                              className="text-xs px-2.5 py-1 rounded bg-yellow-950/50 text-yellow-400 hover:bg-yellow-900/50">Deactivate</button>
                          )}
                          <button onClick={() => deleteApiKey(k.id)}
                            className="text-zinc-500 hover:text-red-400 transition-colors">
                            <HiTrash className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ═══════ VOICES ═══════ */}
        {tab === "voices" && (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold mb-1">Thư viện giọng nói</h2>
              <p className="text-sm text-zinc-500">Upload mẫu giọng và quản lý.</p>
            </div>
            <form onSubmit={addVoice} className="bg-zinc-900/50 border border-zinc-800 rounded-xl p-5 space-y-4">
              <div className="grid md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">Tên giọng</label>
                  <input required value={newVoiceName} onChange={e => setNewVoiceName(e.target.value)}
                    className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded text-sm text-white focus:outline-none focus:border-brand" />
                </div>
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">File âm thanh</label>
                  <input required type="file" accept="audio/*" onChange={e => setNewVoiceFile(e.target.files?.[0] || null)}
                    className="w-full text-sm text-zinc-400 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-zinc-800 file:text-zinc-300" />
                </div>
                <div className="flex items-end">
                  <button type="submit"
                    className="w-full bg-white text-black px-4 py-2 rounded text-sm font-medium hover:bg-zinc-200">Upload</button>
                </div>
              </div>
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Transcript</label>
                <textarea rows={2} value={newVoiceTranscript} onChange={e => setNewVoiceTranscript(e.target.value)}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded text-sm text-white focus:outline-none focus:border-brand" />
              </div>
            </form>
            <div className="border border-zinc-800 rounded-xl overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-zinc-900/50 border-b border-zinc-800">
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Tên</th>
                    <th className="px-4 py-3 text-left font-medium text-zinc-500">Transcript</th>
                    <th className="px-4 py-3 text-right"></th>
                  </tr>
                </thead>
                <tbody>
                  {voices.length === 0 ? (
                    <tr><td colSpan={3} className="text-center py-8 text-zinc-600">Chưa có giọng mẫu</td></tr>
                  ) : voices.map(v => (
                    <tr key={v.id} className="border-b border-zinc-800/50">
                      <td className="px-4 py-3 font-medium">{v.name}</td>
                      <td className="px-4 py-3 text-zinc-400 truncate max-w-xs">{v.transcript || "-"}</td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => deleteVoice(v.id)} className="text-red-400 hover:underline">Xóa</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* ── Confirm Modal ── */}
      <AnimatePresence>
        {confirmModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={() => setConfirmModal(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={e => e.stopPropagation()}
              className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-sm w-full mx-4"
            >
              <h3 className="font-semibold text-sm mb-2">Xác nhận</h3>
              <p className="text-sm text-zinc-400 mb-5">{confirmModal.message}</p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setConfirmModal(null)}
                  className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                >
                  Huỷ
                </button>
                <button
                  onClick={() => { const fn = confirmModal.onConfirm; setConfirmModal(null); fn(); }}
                  className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-500 transition-colors"
                >
                  Xác nhận
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}