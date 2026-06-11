"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { HiArrowRight, HiMicrophone, HiKey, HiClock, HiTrash, HiPlus, HiCheck, HiCog6Tooth } from "react-icons/hi2";
import { toast } from "sonner";
import { motion, AnimatePresence } from "motion/react";

import { api } from "@/lib/api";

interface UserProfile {
  id: number;
  email: string;
  role: string;
  balance: number;
  last_login_at?: string | null;
}

interface ApiKey {
  id: number;
  key_prefix: string;
  name: string;
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
}

interface UsageRecord {
  id: number;
  characters: number;
  cost: number;
  source: string;
  created_at: string | null;
}

interface Voice {
  id: number;
  name: string;
}

function useUser() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("token");
    const u = localStorage.getItem("user");
    if (!t || !u) { router.push("/login"); return; }
    setUser(JSON.parse(u));
  }, [router]);

  return { user, setUser };
}

export default function DashboardPage() {
  const { user, setUser } = useUser();
  const router = useRouter();
  const [tab, setTab] = useState("overview");
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [totalUsed, setTotalUsed] = useState(0);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [ttsText, setTtsText] = useState("");
  const [ttsVoice, setTtsVoice] = useState("");
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsResult, setTtsResult] = useState<string | null>(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyDisplay, setNewKeyDisplay] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState<number | null>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  const loadKeys = useCallback(async () => {
    try { setKeys(await api("/api/auth/api-keys")); } catch {}
  }, []);

  const loadUsage = useCallback(async () => {
    try {
      const data = await api("/api/auth/usage");
      setUsage(data.records || []);
      setTotalUsed(data.total_used || 0);
    } catch {}
  }, []);

  const loadVoices = useCallback(async () => {
    try { setVoices(await api("/api/voices/")); } catch {}
  }, []);

  useEffect(() => {
    if (user) {
      loadKeys();
      loadVoices();
    }
  }, [user, loadKeys, loadVoices]);

  const createKey = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    try {
      const data = await api("/api/auth/api-keys", { method: "POST", body: JSON.stringify({ name: newKeyName || "Default" }) });
      setNewKeyDisplay(data.key);
      setNewKeyName("");
      toast.success("Tạo API key thành công");
      loadKeys();
    } catch (e: any) { toast.error(e.message); }
  };

  const deactivateKey = async (id: number) => {
    try {
      await api(`/api/auth/api-keys/${id}`, { method: "DELETE" });
      toast.success("Đã xoá API key");
      loadKeys();
    } catch (e: any) { toast.error(e.message); }
  };

  const submitTts = async () => {
    if (!ttsText.trim() || !ttsVoice) return;
    setTtsLoading(true);
    setTtsResult(null);
    try {
      const blob = await api("/api/tts/text", {
        method: "POST",
        body: JSON.stringify({ text: ttsText, voice_id: parseInt(ttsVoice) }),
      });
      setTtsResult(URL.createObjectURL(blob));
      toast.success("Tạo giọng nói thành công");
      // Refresh profile for updated balance
      setUser(await api("/api/auth/profile"));
    } catch (e: any) { toast.error(e.message); }
    finally { setTtsLoading(false); }
  };

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 6) {
      toast.error("Mật khẩu mới phải từ 6 ký tự");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("Mật khẩu nhập lại không khớp");
      return;
    }

    setChangingPassword(true);
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      toast.success("Đổi mật khẩu thành công");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setChangingPassword(false);
    }
  };

  const tabs = [
    { id: "overview", label: "Tổng quan", icon: HiMicrophone },
    { id: "keys", label: "API Keys", icon: HiKey },
    { id: "usage", label: "Lịch sử", icon: HiClock },
    { id: "settings", label: "Cài đặt", icon: HiCog6Tooth },
  ];

  return (
    <div className="min-h-[100dvh] bg-zinc-950">
      {/* Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-5xl mx-auto flex items-center justify-between px-6 h-14">
          <Link href="/" className="font-bold tracking-tight text-sm">
            clone<span className="text-brand">.</span>tts
          </Link>
          <div className="flex items-center gap-3">
            <nav className="hidden sm:flex items-center gap-1">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => { setTab(t.id); if (t.id === "usage") loadUsage(); }}
                  className={`text-xs px-3 py-1.5 rounded-md transition-colors ${tab === t.id ? "bg-zinc-800 text-white" : "text-zinc-500 hover:text-zinc-300"}`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
            <button
              onClick={() => { localStorage.clear(); router.push("/"); }}
              className="text-xs text-zinc-500 hover:text-zinc-300"
            >
              Đăng xuất
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Mobile tabs */}
        <div className="flex sm:hidden gap-2 mb-6 overflow-x-auto">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`text-xs px-3 py-1.5 rounded-md whitespace-nowrap transition-colors ${tab === t.id ? "bg-zinc-800 text-white" : "bg-zinc-900 text-zinc-500"}`}
            >
              <t.icon className="w-3.5 h-3.5 inline mr-1.5" />
              {t.label}
            </button>
          ))}
        </div>

        {/* Overview */}
        {tab === "overview" && user && (
          <div className="space-y-6">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
              <p className="text-sm text-zinc-500 mb-1">Số dư ký tự</p>
              <p className="text-4xl font-bold tracking-tight text-brand">{user.balance.toLocaleString()}</p>
              <p className="text-xs text-zinc-600 mt-1">1 ký tự = 1, không tính khoảng trắng</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
                <p className="text-xs text-zinc-500 mb-1">Đã dùng</p>
                <p className="text-xl font-semibold">{totalUsed.toLocaleString()}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
                <p className="text-xs text-zinc-500 mb-1">Email</p>
                <p className="text-sm font-medium truncate">{user.email}</p>
              </div>
            </div>

            {/* TTS Form */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
              <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                <HiMicrophone className="w-4 h-4 text-brand" />
                Tạo giọng nói
              </h3>
              <div className="space-y-3">
                <select
                  value={ttsVoice}
                  disabled={ttsLoading}
                  onChange={(e) => { setTtsVoice(e.target.value); loadVoices(); }}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand disabled:opacity-50"
                >
                  <option value="">Chọn giọng</option>
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
                <textarea
                  value={ttsText}
                  disabled={ttsLoading}
                  onChange={(e) => setTtsText(e.target.value)}
                  placeholder="Nhập nội dung cần chuyển giọng nói..."
                  rows={4}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand resize-vertical disabled:opacity-50"
                />
                <div className="flex items-center gap-3">
                  <button
                    onClick={submitTts}
                    disabled={ttsLoading || !ttsText.trim() || !ttsVoice}
                    className="inline-flex items-center gap-2 bg-brand text-black font-semibold px-5 py-2 rounded-lg hover:bg-emerald-400 transition-colors text-sm disabled:opacity-50"
                  >
                    {ttsLoading ? (
                      <span className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                    ) : (
                      <>Tạo TTS <HiArrowRight className="w-3.5 h-3.5" /></>
                    )}
                  </button>
                  <span className="text-xs text-zinc-600">
                    {ttsText.replace(/\s/g, "").length} ký tự
                  </span>
                </div>
                {ttsResult && (
                  <audio controls src={ttsResult} className="w-full mt-3" />
                )}
              </div>
            </div>
          </div>
        )}

        {/* API Keys */}
        {tab === "keys" && (
          <div className="space-y-4">
            <form onSubmit={createKey} className="flex items-center gap-3">
              <input
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Tên key (vd: Production)"
                className="flex-1 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand"
              />
              <button type="submit" className="inline-flex items-center gap-1.5 bg-brand text-black font-semibold px-4 py-2 rounded-lg hover:bg-emerald-400 transition-colors text-sm">
                <HiPlus className="w-3.5 h-3.5" /> Tạo key
              </button>
            </form>

            {newKeyDisplay && (
              <div className="rounded-lg border border-brand/30 bg-brand/5 p-4">
                <p className="text-xs text-zinc-400 mb-2">Key mới — copy ngay, sẽ không hiển thị lại:</p>
                <code className="text-sm text-brand break-all">{newKeyDisplay}</code>
                <button
                  onClick={() => { navigator.clipboard.writeText(newKeyDisplay); setNewKeyDisplay(null); }}
                  className="mt-2 inline-flex items-center gap-1 text-xs text-brand hover:underline"
                >
                  <HiCheck className="w-3 h-3" /> Đã copy
                </button>
              </div>
            )}

            <div className="rounded-xl border border-zinc-800 overflow-x-auto">
              <table className="w-full text-sm min-w-[500px]">
                <thead>
                  <tr className="border-b border-zinc-800 bg-zinc-900/50">
                    <th className="text-left px-4 py-3 text-zinc-500 font-medium">Tên</th>
                    <th className="text-left px-4 py-3 text-zinc-500 font-medium hidden sm:table-cell">Key</th>
                    <th className="text-left px-4 py-3 text-zinc-500 font-medium hidden sm:table-cell">Trạng thái</th>
                    <th className="text-right px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {keys.length === 0 ? (
                    <tr><td colSpan={4} className="text-center text-zinc-600 py-8 text-sm">Chưa có API key nào</td></tr>
                  ) : (
                    keys.map((k) => (
                      <tr key={k.id} className="border-b border-zinc-800/50">
                        <td className="px-4 py-3">{k.name}</td>
                        <td className="px-4 py-3 font-mono text-xs text-zinc-500 hidden sm:table-cell">{k.key_prefix}...</td>
                        <td className="px-4 py-3 hidden sm:table-cell">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${k.is_active ? "bg-brand/10 text-brand" : "bg-red-950/50 text-red-400"}`}>
                            {k.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {k.is_active && (
                            <button onClick={() => setShowConfirm(k.id)} className="text-zinc-500 hover:text-red-400 transition-colors">
                              <HiTrash className="w-4 h-4" />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <AnimatePresence>
              {showConfirm !== null && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                  onClick={() => setShowConfirm(null)}
                >
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.9, opacity: 0 }}
                    onClick={(e) => e.stopPropagation()}
                    className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 max-w-sm w-full mx-4"
                  >
                    <h3 className="font-semibold text-sm mb-2">Xác nhận xoá</h3>
                    <p className="text-sm text-zinc-400 mb-5">Bạn có chắc muốn xoá API key này? Hành động này không thể hoàn tác.</p>
                    <div className="flex gap-3 justify-end">
                      <button
                        onClick={() => setShowConfirm(null)}
                        className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                      >
                        Huỷ
                      </button>
                      <button
                        onClick={() => { const id = showConfirm; setShowConfirm(null); deactivateKey(id); }}
                        className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-500 transition-colors"
                      >
                        Xoá
                      </button>
                    </div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* Usage */}
        {tab === "usage" && (
          <div className="rounded-xl border border-zinc-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/50">
                  <th className="text-left px-4 py-3 text-zinc-500 font-medium">Thời gian</th>
                  <th className="text-right px-4 py-3 text-zinc-500 font-medium">Ký tự</th>
                  <th className="text-right px-4 py-3 text-zinc-500 font-medium hidden sm:table-cell">Chi phí</th>
                  <th className="text-right px-4 py-3 text-zinc-500 font-medium hidden sm:table-cell">Nguồn</th>
                </tr>
              </thead>
              <tbody>
                {usage.length === 0 ? (
                  <tr><td colSpan={4} className="text-center text-zinc-600 py-8 text-sm">Chưa có lịch sử sử dụng</td></tr>
                ) : (
                  usage.map((r) => (
                    <tr key={r.id} className="border-b border-zinc-800/50">
                      <td className="px-4 py-3 text-zinc-400 text-xs">{r.created_at ? new Date(r.created_at).toLocaleString() : ""}</td>
                      <td className="px-4 py-3 text-right">{r.characters}</td>
                      <td className="px-4 py-3 text-right text-brand hidden sm:table-cell">-{r.cost}</td>
                      <td className="px-4 py-3 text-right hidden sm:table-cell">
                        <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">{r.source}</span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Settings */}
        {tab === "settings" && user && (
          <div className="space-y-6">
            {/* User info */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
              <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                <HiCog6Tooth className="w-4 h-4 text-brand" />
                Thông tin tài khoản
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-zinc-500">ID</p>
                  <p className="text-sm">{user.id}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Email</p>
                  <p className="text-sm">{user.email}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Vai trò</p>
                  <p className="text-sm capitalize">{user.role}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Số dư ký tự</p>
                  <p className="text-sm">{user.balance.toLocaleString()}</p>
                </div>
                <div className="sm:col-span-2">
                  <p className="text-xs text-zinc-500">Lần cuối đăng nhập</p>
                  <p className="text-sm">
                    {user.last_login_at
                      ? new Date(user.last_login_at).toLocaleString("vi-VN", {
                          year: "numeric", month: "2-digit", day: "2-digit",
                          hour: "2-digit", minute: "2-digit",
                        })
                      : "Chưa có dữ liệu"}
                  </p>
                </div>
              </div>
            </div>

            {/* Change password form */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
              <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
                <HiCog6Tooth className="w-4 h-4 text-brand" />
                Đổi mật khẩu
              </h3>
              <form onSubmit={changePassword} className="space-y-3 max-w-sm">
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Mật khẩu cũ"
                  required
                  disabled={changingPassword}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand disabled:opacity-50"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Mật khẩu mới"
                  required
                  disabled={changingPassword}
                  minLength={6}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand disabled:opacity-50"
                />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Nhập lại mật khẩu mới"
                  required
                  disabled={changingPassword}
                  minLength={6}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={changingPassword || !currentPassword || !newPassword || !confirmPassword}
                  className="inline-flex items-center gap-2 bg-brand text-black font-semibold px-5 py-2 rounded-lg hover:bg-emerald-400 transition-colors text-sm disabled:opacity-50"
                >
                  {changingPassword ? (
                    <span className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                  ) : (
                    "Đổi mật khẩu"
                  )}
                </button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
