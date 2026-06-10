"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { HiArrowRight, HiMicrophone, HiKey, HiClock, HiTrash, HiPlus, HiCheck, HiExclamationTriangle } from "react-icons/hi2";

interface UserProfile {
  id: number;
  email: string;
  role: string;
  balance: number;
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

function useAuth() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("token");
    const u = localStorage.getItem("user");
    if (!t || !u) { router.push("/login"); return; }
    setToken(t);
    setUser(JSON.parse(u));
  }, [router]);

  const api = useCallback(async (path: string, opts: RequestInit = {}) => {
    const res = await fetch(path, {
      ...opts,
      headers: { ...opts.headers, "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    });
    if (res.status === 401) { localStorage.clear(); router.push("/login"); throw new Error("Session expired"); }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.message || data?.detail || `HTTP ${res.status}`);
    return data;
  }, [token, router]);

  return { user, token, api, setUser };
}

export default function DashboardPage() {
  const { user, api, setUser } = useAuth();
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
  const [message, setMessage] = useState("");

  const loadKeys = useCallback(async () => {
    try { setKeys(await api("/api/auth/api-keys")); } catch {}
  }, [api]);

  const loadUsage = useCallback(async () => {
    try {
      const data = await api("/api/auth/usage");
      setUsage(data.records || []);
      setTotalUsed(data.total_used || 0);
    } catch {}
  }, [api]);

  const loadVoices = useCallback(async () => {
    try { setVoices(await api("/api/voices/")); } catch {}
  }, [api]);

  useEffect(() => { if (user) { loadKeys(); } }, [user, loadKeys]);

  const createKey = async () => {
    try {
      const data = await api("/api/auth/api-keys", { method: "POST", body: JSON.stringify({ name: newKeyName || "Default" }) });
      setNewKeyDisplay(data.key);
      setNewKeyName("");
      loadKeys();
    } catch (e: any) { setMessage(e.message); }
  };

  const deactivateKey = async (id: number) => {
    if (!confirm("Deactivate this API key?")) return;
    try { await api(`/api/auth/api-keys/${id}`, { method: "DELETE" }); loadKeys(); }
    catch (e: any) { setMessage(e.message); }
  };

  const submitTts = async () => {
    if (!ttsText.trim() || !ttsVoice) return;
    setTtsLoading(true);
    setTtsResult(null);
    setMessage("");
    try {
      const res = await fetch("/api/tts/text", {
        method: "POST",
        headers: { "Authorization": `Bearer ${localStorage.getItem("token")}`, "Content-Type": "application/json" },
        body: JSON.stringify({ text: ttsText, voice_id: parseInt(ttsVoice) }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 402) setMessage("Không đủ ký tự!");
        else setMessage(err.message || err.detail || `HTTP ${res.status}`);
        return;
      }
      const blob = await res.blob();
      setTtsResult(URL.createObjectURL(blob));
      // Refresh profile for updated balance
      setUser(await api("/api/auth/profile"));
    } catch (e: any) { setMessage(e.message); }
    finally { setTtsLoading(false); }
  };

  const tabs = [
    { id: "overview", label: "Tổng quan", icon: HiMicrophone },
    { id: "keys", label: "API Keys", icon: HiKey },
    { id: "usage", label: "Lịch sử", icon: HiClock },
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

        {message && (
          <div className="flex items-center gap-2 bg-red-950/50 border border-red-900 text-red-400 text-sm rounded-lg px-4 py-2.5 mb-4">
            <HiExclamationTriangle className="w-4 h-4 shrink-0" />
            {message}
            <button onClick={() => setMessage("")} className="ml-auto text-red-600 hover:text-red-400">&times;</button>
          </div>
        )}

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
                  onChange={(e) => { setTtsVoice(e.target.value); loadVoices(); }}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-brand"
                >
                  <option value="">Chọn giọng</option>
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
                <textarea
                  value={ttsText}
                  onChange={(e) => setTtsText(e.target.value)}
                  placeholder="Nhập nội dung cần chuyển giọng nói..."
                  rows={4}
                  className="w-full px-3 py-2 bg-zinc-950 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand resize-vertical"
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
            <div className="flex items-center gap-3">
              <input
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Tên key (vd: Production)"
                className="flex-1 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-brand"
              />
              <button onClick={createKey} className="inline-flex items-center gap-1.5 bg-brand text-black font-semibold px-4 py-2 rounded-lg hover:bg-emerald-400 transition-colors text-sm">
                <HiPlus className="w-3.5 h-3.5" /> Tạo key
              </button>
            </div>

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

            <div className="rounded-xl border border-zinc-800 overflow-hidden">
              <table className="w-full text-sm">
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
                            <button onClick={() => deactivateKey(k.id)} className="text-zinc-500 hover:text-red-400 transition-colors">
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
      </div>
    </div>
  );
}
