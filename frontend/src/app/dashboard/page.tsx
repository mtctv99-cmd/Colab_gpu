"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
  SidebarInset,
  SidebarHeader,
  SidebarFooter,
} from "@/components/ui/sidebar";
import {
  LayoutDashboard,
  Key,
  Clock,
  Settings,
  LogOut,
  Trash2,
  Copy,
  Plus,
  X,
  BookOpen,
  MessageSquare,
  Send,
  StopCircle,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.08 },
  },
} as const;

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { type: "spring" as const, stiffness: 280, damping: 22 },
  },
} as const;

const slidePanelVariants = {
  hidden: { x: "100%" },
  visible: {
    x: 0,
    transition: { type: "spring" as const, stiffness: 300, damping: 30 },
  },
  exit: {
    x: "100%",
    transition: { type: "spring" as const, stiffness: 300, damping: 30 },
  },
} as const;

function PulseDots() {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-signal animate-pulse" />
      <span className="w-1.5 h-1.5 rounded-full bg-signal animate-pulse [animation-delay:150ms]" />
      <span className="w-1.5 h-1.5 rounded-full bg-signal animate-pulse [animation-delay:300ms]" />
    </span>
  );
}

function StatusDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block w-1.5 h-1.5 rounded-full ${
        active
          ? "bg-online shadow-[0_0_6px_rgba(52,184,85,0.5)]"
          : "bg-dimmer"
      }`}
    />
  );
}

interface UserProfile {
  id: number;
  email: string;
  role: string;
  balance: number;
  last_login_at?: string | null;
}

function useUser() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    const t = localStorage.getItem("token");
    const u = localStorage.getItem("user");
    if (!t || !u) { router.push("/login"); return; }
    setUser(JSON.parse(u));

    // Refresh profile every 30s to get updated balance
    const interval = setInterval(async () => {
      try {
        const fresh = await api("/api/auth/profile");
        setUser(fresh);
        localStorage.setItem("user", JSON.stringify(fresh));
      } catch {}
    }, 30000);
    return () => clearInterval(interval);
  }, [router]);

  return { user, setUser };
}

export default function DashboardPage() {
  const { user, setUser } = useUser();
  const router = useRouter();
  const [tab, setTab] = useState("overview");

  const sidebarItems = [
    { id: "overview", label: "Tổng quan", icon: LayoutDashboard },
    { id: "batch", label: "Batch TTS", icon: Plus },
    
    { id: "keys", label: "API Keys", icon: Key },
    { id: "usage", label: "Lịch sử", icon: Clock },
    { id: "docs", label: "Tài liệu API", icon: BookOpen, external: "/docs" },
    { id: "settings", label: "Cài đặt", icon: Settings },
  ];

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon" className="border-r border-phantom">
        <SidebarHeader className="px-4 py-5">
          <span className="text-sm font-medium tracking-tight text-vocal">
            TTS Dubbing
          </span>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarMenu>
                {sidebarItems.map((item) => (
                <SidebarMenuItem key={item.id}>
                  <SidebarMenuButton
                    isActive={tab === item.id}
                    onClick={() => (item as any).external ? router.push((item as any).external) : setTab(item.id)}
                    tooltip={item.label}
                    className="text-sm data-[active=true]:bg-strip data-[active=true]:text-signal"
                  >
                    <item.icon className="w-4 h-4" />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                onClick={() => { localStorage.clear(); router.push("/"); }}
                className="text-echo hover:text-alert transition-colors"
              >
                <LogOut className="w-4 h-4" />
                <span>Đăng xuất</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="flex h-14 items-center px-6 border-b border-phantom bg-pitch">
          <SidebarTrigger className="text-echo hover:text-vocal" />
          <h1 className="ml-4 text-sm font-medium text-vocal">
            {sidebarItems.find((i) => i.id === tab)?.label}
          </h1>
        </header>
        <main className="flex-1 bg-pitch min-h-0 overflow-y-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              variants={containerVariants}
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, y: -8, transition: { duration: 0.12 } }}
              className="max-w-4xl mx-auto px-6 py-8"
            >
              {tab === "overview" && <DashboardOverview user={user} setUser={setUser} />}
              {tab === "batch" && <DashboardBatch />}
              
              {tab === "keys" && <DashboardApiKeys />}
              {tab === "usage" && <DashboardUsage />}
              {tab === "settings" && <DashboardSettings user={user} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

function DashboardOverview({ user, setUser }: { user: UserProfile | null; setUser: (u: any) => void }) {
  const [voices, setVoices] = useState<any[]>([]);
  const [taskStats, setTaskStats] = useState({ completed: 0, processing: 0, failed: 0 });
  const [ttsText, setTtsText] = useState("");
  const [ttsVoice, setTtsVoice] = useState("");
  const [ttsLanguage, setTtsLanguage] = useState("");
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsResult, setTtsResult] = useState<string | null>(null);

  useEffect(() => {
    api("/api/voices/").then(setVoices).catch(() => {});
    api("/api/auth/tasks?limit=100")
      .then((tasks) => {
        const stats = { completed: 0, processing: 0, failed: 0 };
        tasks.forEach((t: any) => {
          if (t.status === "COMPLETED") stats.completed++;
          else if (t.status === "FAILED") stats.failed++;
          else stats.processing++;
        });
        setTaskStats(stats);
      })
      .catch(() => {});
  }, []);

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
      setUser(await api("/api/auth/profile"));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setTtsLoading(false);
    }
  };

  if (!user) return null;

  const stats = [
    { label: "Số dư", value: user.balance ?? 0 },
    { label: "Đã hoàn thành", value: taskStats.completed },
    { label: "Đang xử lý", value: taskStats.processing },
    { label: "Thất bại", value: taskStats.failed },
  ];

  return (
    <motion.div variants={containerVariants} className="space-y-8">
      <motion.div variants={itemVariants} className="flex border-b border-phantom">
        {stats.map((s, i) => (
          <div
            key={s.label}
            className={`flex-1 py-5 px-6 ${i < stats.length - 1 ? "border-r border-phantom" : ""}`}
          >
            <div className="font-mono text-2xl text-signal tabular-nums">
              {s.value.toLocaleString()}
            </div>
            <div className="text-xs uppercase tracking-wider text-echo mt-1">
              {s.label}
            </div>
          </div>
        ))}
      </motion.div>

      <motion.div variants={itemVariants} className="space-y-5">
        <div className="space-y-1.5">
          <Label className="text-xs uppercase tracking-wider text-echo">Chọn giọng</Label>
          <Select
            value={ttsVoice}
            onValueChange={(v) => setTtsVoice(v || "")}
            disabled={ttsLoading}
          >
            <SelectTrigger className="w-full max-w-xs bg-strip border-phantom text-vocal h-9 text-sm">
              <SelectValue placeholder="Chọn giọng đọc...">
                {ttsVoice ? voices.find(v => v.id.toString() === ttsVoice)?.name || ttsVoice : "Chọn giọng đọc..."}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="bg-console border-phantom">
              {voices.map((v) => (
                <SelectItem key={v.id} value={v.id.toString()}>{v.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs uppercase tracking-wider text-echo">Văn bản</Label>
          <Textarea
            value={ttsText}
            disabled={ttsLoading}
            onChange={(e) => setTtsText(e.target.value)}
            placeholder="Nhập nội dung cần chuyển đổi..."
            rows={5}
            className="bg-strip border-phantom text-vocal text-sm placeholder:text-dimmer resize-none"
          />
        </div>

        <div className="flex items-center gap-4">
          <Button
            onClick={submitTts}
            disabled={ttsLoading || !ttsText.trim() || !ttsVoice}
            className="bg-signal text-pitch hover:bg-signal-dark disabled:opacity-40 h-9 px-5 text-sm font-medium"
          >
            {ttsLoading ? <PulseDots /> : "Tạo TTS"}
          </Button>
          <span className="text-xs font-mono text-echo">
            {ttsText.replace(/\s/g, "").length} ký tự
          </span>
        </div>

        {ttsResult && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="pt-2"
          >
            <audio controls src={ttsResult} className="w-full max-w-md h-9" />
          </motion.div>
        )}
      </motion.div>


    </motion.div>
  );
}

function DashboardApiKeys() {
  const [keys, setKeys] = useState<any[]>([]);
  const [slideOpen, setSlideOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newKeyDisplay, setNewKeyDisplay] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const [editingKey, setEditingKey] = useState<any>(null);

  const loadKeys = useCallback(async () => {
    try { setKeys(await api("/api/auth/api-keys")); } catch {}
  }, []);

  useEffect(() => { loadKeys(); }, [loadKeys]);

  const openCreatePanel = () => {
    setNewKeyName("");
    setNewKeyDisplay(null);
    setSlideOpen(true);
  };

  const createKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) { toast.error("Vui lòng nhập tên key"); return; }
    setCreating(true);
    try {
      const data = await api("/api/auth/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: newKeyName }),
      });
      setNewKeyDisplay(data.key);
      toast.success("Tạo API key thành công");
      loadKeys();
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setCreating(false);
    }
  };

  const deactivateKey = async (id: number) => {
    try {
      await api(`/api/auth/api-keys/${id}`, { method: "DELETE" });
      toast.success("Đã xoá API key");
      setDeleteConfirmId(null);
      loadKeys();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  return (
    <motion.div variants={containerVariants} className="space-y-6">
      <motion.div variants={itemVariants} className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-vocal">API Keys</h2>
          <p className="text-xs text-echo mt-0.5">
            Sử dụng API key để xác thực request từ ứng dụng của bạn.
          </p>
        </div>
        <Button
          onClick={openCreatePanel}
          className="bg-signal text-pitch hover:bg-signal-dark h-8 px-4 text-xs font-medium"
        >
          <Plus className="w-3.5 h-3.5 mr-1.5" />
          Tạo key
        </Button>
      </motion.div>

      <motion.div variants={itemVariants}>
        <Table>
          <TableHeader>
            <TableRow className="border-b border-phantom">
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">
                Tên
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">
                Prefix
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">
                Trạng thái
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9 text-right">
                Hành động
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {keys.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-echo text-sm py-12">
                  Chưa có API key nào
                </TableCell>
              </TableRow>
            ) : (
              keys.map((k) => (
                <TableRow key={k.id} className="border-b border-phantom">
                  <TableCell className="text-sm text-vocal py-3">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs text-echo py-3">
                    {k.key_prefix}...
                  </TableCell>
                  <TableCell className="py-3">
                    <span className="inline-flex items-center gap-2 text-xs">
                      <StatusDot active={k.is_active} />
                      <span className={k.is_active ? "text-online" : "text-dimmer"}>
                        {k.is_active ? "Active" : "Inactive"}
                      </span>
                    </span>
                  </TableCell>
                  <TableCell className="text-right py-3">
                    {deleteConfirmId === k.id ? (
                      <span className="inline-flex items-center gap-2">
                        <button
                          onClick={() => deactivateKey(k.id)}
                          className="text-xs text-alert hover:underline"
                        >
                          Xác nhận
                        </button>
                        <button
                          onClick={() => setDeleteConfirmId(null)}
                          className="text-xs text-echo hover:text-vocal"
                        >
                          Huỷ
                        </button>
                      </span>
                    ) : (
                      k.is_active && (
                        <button
                          onClick={() => setDeleteConfirmId(k.id)}
                          className="text-echo hover:text-alert transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </motion.div>

      <AnimatePresence>
        {slideOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/60 z-40"
              onClick={() => setSlideOpen(false)}
            />
            <motion.div
              variants={slidePanelVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="fixed right-0 top-0 bottom-0 w-96 bg-console border-l border-phantom z-50 p-6 overflow-y-auto shadow-2xl"
            >
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-sm font-medium text-vocal">Tạo API Key</h3>
                <button
                  onClick={() => setSlideOpen(false)}
                  className="text-echo hover:text-vocal transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {!newKeyDisplay ? (
                <form onSubmit={createKey} className="space-y-4">
                  <div className="space-y-1.5">
                    <Label className="text-xs uppercase tracking-wider text-echo">
                      Tên key
                    </Label>
                    <Input
                      value={newKeyName}
                      onChange={(e) => setNewKeyName(e.target.value)}
                      placeholder="vd: Production"
                      className="bg-strip border-phantom text-vocal text-sm h-9 placeholder:text-dimmer"
                      autoFocus
                    />
                  </div>
                  <Button
                    type="submit"
                    disabled={creating || !newKeyName.trim()}
                    className="w-full bg-signal text-pitch hover:bg-signal-dark h-9 text-sm font-medium disabled:opacity-40"
                  >
                    {creating ? <PulseDots /> : "Tạo key"}
                  </Button>
                </form>
              ) : (
                <div className="space-y-4">
                  <div className="text-xs text-echo">
                    Key mới (copy ngay, sẽ không hiển thị lại):
                  </div>
                  <div className="bg-strip border border-phantom rounded p-3">
                    <code className="text-xs text-vocal break-all font-mono">
                      {newKeyDisplay}
                    </code>
                  </div>
                  <Button
                    onClick={() => {
                      navigator.clipboard.writeText(newKeyDisplay);
                      toast.success("Đã copy key");
                    }}
                    className="w-full bg-signal text-pitch hover:bg-signal-dark h-9 text-sm font-medium"
                  >
                    <Copy className="w-3.5 h-3.5 mr-1.5" />
                    Copy key
                  </Button>
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function DashboardUsage() {
  const [usage, setUsage] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/api/auth/usage")
      .then((d) => setUsage(d.records || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <motion.div variants={containerVariants} className="space-y-6">
      <motion.div variants={itemVariants}>
        <h2 className="text-sm font-medium text-vocal">Lịch sử sử dụng</h2>
        <p className="text-xs text-echo mt-0.5">
          Chi tiết tiêu hao ký tự của tài khoản.
        </p>
      </motion.div>

      <motion.div variants={itemVariants}>
        <Table>
          <TableHeader>
            <TableRow className="border-b border-phantom">
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">
                Thời gian
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9 text-right">
                Ký tự
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9 text-right">
                Chi phí
              </TableHead>
              <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9 text-right">
                Nguồn
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-12">
                  <PulseDots />
                </TableCell>
              </TableRow>
            ) : usage.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-echo text-sm py-12">
                  Chưa có lịch sử sử dụng
                </TableCell>
              </TableRow>
            ) : (
              usage.map((r) => (
                <TableRow key={r.id} className="border-b border-phantom">
                  <TableCell className="text-sm text-vocal py-3 font-mono tabular-nums">
                    {new Date(r.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-sm text-right text-vocal py-3 font-mono tabular-nums">
                    {r.characters}
                  </TableCell>
                  <TableCell className="text-sm text-right text-alert py-3 font-mono tabular-nums">
                    -{r.cost}
                  </TableCell>
                  <TableCell className="text-right py-3">
                    <span className="inline-block text-xs text-echo bg-strip px-2 py-0.5 rounded border border-phantom font-mono">
                      {r.source}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </motion.div>

      <motion.div variants={itemVariants}>
        <h2 className="text-sm font-medium text-vocal mb-1">Lịch sử TTS</h2>
        <p className="text-xs text-echo mb-4">Các tác vụ TTS đã tạo gần đây.</p>
        <TtsHistory />
      </motion.div>
    </motion.div>
  );
}

function TtsHistory() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const fetchTasks = useCallback(() => {
    api("/api/auth/tasks?limit=20")
      .then(setTasks)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  const togglePlay = (taskId: string) => {
    if (playingId === taskId) {
      audioRef.current?.pause();
      setPlayingId(null);
      return;
    }
    
    if (audioRef.current) {
      audioRef.current.pause();
    }
    
    const audio = new Audio(`/api/tasks/${taskId}/audio`);
    audio.onended = () => setPlayingId(null);
    audio.onerror = () => { toast.error("Không thể phát file âm thanh"); setPlayingId(null); };
    
    audio.play().then(() => {
      audioRef.current = audio;
      setPlayingId(taskId);
    }).catch(() => {
      setPlayingId(null);
    });
  };

  return (
    <Table>
      <TableHeader>
        <TableRow className="border-b border-phantom">
          <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">Nội dung</TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">Trạng thái</TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9">Audio</TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-echo font-normal h-9 text-right">Thời gian</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {loading && tasks.length === 0 ? (
          <TableRow><TableCell colSpan={4} className="text-center py-12"><PulseDots /></TableCell></TableRow>
        ) : tasks.length === 0 ? (
          <TableRow><TableCell colSpan={4} className="text-center text-echo text-sm py-12">Chưa có tác vụ TTS</TableCell></TableRow>
        ) : (
          tasks.map((t) => (
            <TableRow key={t.id} className="border-b border-phantom hover:bg-strip/50 transition-colors">
              <TableCell className="text-sm text-vocal py-3 max-w-[200px] truncate" title={t.text}>{t.text}</TableCell>
              <TableCell className="py-3">
                <span className="inline-flex items-center gap-1.5 text-xs text-echo font-mono">
                  <span className={`w-1.5 h-1.5 rounded-full ${
                    t.status === "COMPLETED" ? "bg-online" :
                    t.status === "FAILED" ? "bg-alert" :
                    t.status === "PROCESSING" ? "bg-signal animate-pulse" : "bg-dimmer"
                  }`} />
                  {t.status}
                </span>
              </TableCell>
              <TableCell className="py-3">
                {t.status === "COMPLETED" && t.result_audio_path ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => togglePlay(t.id)}
                      className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-signal/10 text-signal hover:bg-signal/20 transition-colors"
                    >
                      {playingId === t.id ? (
                         <span className="w-2 h-2 bg-signal" />
                      ) : (
                        <svg className="w-3 h-3 ml-0.5" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                      )}
                    </button>
                    <a
                      href={`/api/tasks/${t.id}/audio`}
                      download={`tts-${t.id}.wav`}
                      className="text-xs text-echo hover:text-vocal font-mono"
                      title="Tải xuống"
                    >
                      ↓
                    </a>
                  </div>
                ) : t.status === "FAILED" ? (
                  <span className="text-xs text-alert font-mono truncate max-w-[150px] inline-block" title={t.error_message}>{t.error_message?.slice(0,30) || "Lỗi"}</span>
                ) : <span className="text-xs text-dimmer">-</span>}
              </TableCell>
              <TableCell className="text-right text-xs text-echo font-mono py-3 tabular-nums">
                {new Date(t.created_at).toLocaleString("vi-VN", {
                  hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit"
                })}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}

function DashboardSettings({ user }: { user: UserProfile | null }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPassword.length < 6) { toast.error("Mật khẩu mới tối thiểu 6 ký tự"); return; }
    if (newPassword !== confirmPassword) { toast.error("Mật khẩu nhập lại không khớp"); return; }
    setLoading(true);
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
      setLoading(false);
    }
  };

  return (
    <motion.div variants={containerVariants} className="space-y-6">
      <motion.div variants={itemVariants}>
        <h2 className="text-sm font-medium text-vocal">Cài đặt</h2>
        <p className="text-xs text-echo mt-0.5">Đổi mật khẩu tài khoản.</p>
      </motion.div>

      <motion.div variants={itemVariants} className="max-w-sm">
        <form onSubmit={changePassword} className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs uppercase tracking-wider text-echo">
              Mật khẩu cũ
            </Label>
            <Input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              className="bg-strip border-phantom text-vocal text-sm h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase tracking-wider text-echo">
              Mật khẩu mới
            </Label>
            <Input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              className="bg-strip border-phantom text-vocal text-sm h-9"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs uppercase tracking-wider text-echo">
              Nhập lại mật khẩu
            </Label>
            <Input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="bg-strip border-phantom text-vocal text-sm h-9"
            />
          </div>
          <Button
            type="submit"
            disabled={loading}
            className="bg-signal text-pitch hover:bg-signal-dark h-9 px-5 text-sm font-medium disabled:opacity-40"
          >
            {loading ? <PulseDots /> : "Đổi mật khẩu"}
          </Button>
        </form>
      </motion.div>
    </motion.div>
  );
}

function DashboardBatch() {
  const [voices, setVoices] = useState<any[]>([]);
  const [ttsVoice, setTtsVoice] = useState("");
  const [texts, setTexts] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api("/api/voices/").then(setVoices).catch(() => {});
  }, []);

  const submitBatch = async () => {
    if (!texts.trim() || !ttsVoice) return;
    const textList = texts.split("\n").filter((t: string) => t.trim().length > 0);
    if (textList.length === 0) return;
    
    setLoading(true);
    try {
      await api("/api/tts/batch", {
        method: "POST",
        body: JSON.stringify({
          voice_id: parseInt(ttsVoice),
          batch: true,
          texts: textList,
          webhook_url: webhookUrl || null,
        }),
      });
      toast.success(`Đã gửi ${textList.length} tác vụ TTS batch`);
      setTexts("");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div variants={containerVariants} className="space-y-6">
      <motion.div variants={itemVariants}>
        <h2 className="text-sm font-medium text-vocal">Batch TTS</h2>
        <p className="text-xs text-echo mt-0.5">Xử lý hàng loạt văn bản cùng lúc. Mỗi dòng là một tác vụ riêng biệt.</p>
      </motion.div>

      <motion.div variants={itemVariants} className="space-y-5 max-w-xl">
        <div className="space-y-1.5">
          <Label className="text-xs uppercase tracking-wider text-echo">Chọn giọng</Label>
          <Select value={ttsVoice} onValueChange={(v) => setTtsVoice(v || "")} disabled={loading}>
            <SelectTrigger className="w-full bg-strip border-phantom text-vocal h-9 text-sm">
              <SelectValue placeholder="Chọn giọng đọc...">
                {ttsVoice ? voices.find(v => v.id.toString() === ttsVoice)?.name || ttsVoice : "Chọn giọng đọc..."}
              </SelectValue>
            </SelectTrigger>
            <SelectContent className="bg-console border-phantom">
              {voices.map((v) => (
                <SelectItem key={v.id} value={v.id.toString()}>{v.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs uppercase tracking-wider text-echo">Danh sách văn bản (mỗi dòng 1 tác vụ)</Label>
          <Textarea
            value={texts}
            disabled={loading}
            onChange={(e) => setTexts(e.target.value)}
            placeholder={"Xin chào, đây là câu 1.\nĐây là câu 2.\nCâu 3..."}
            rows={8}
            className="bg-strip border-phantom text-vocal text-sm placeholder:text-dimmer resize-y font-mono"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs uppercase tracking-wider text-echo">Webhook URL (Tùy chọn)</Label>
          <Input
            value={webhookUrl}
            disabled={loading}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://your-server.com/webhook"
            className="bg-strip border-phantom text-vocal text-sm h-9"
          />
        </div>

        <Button
          onClick={submitBatch}
          disabled={loading || !texts.trim() || !ttsVoice}
          className="bg-signal text-pitch hover:bg-signal-dark disabled:opacity-40 h-9 px-5 text-sm font-medium"
        >
          {loading ? <PulseDots /> : "Tạo Batch TTS"}
        </Button>
      </motion.div>
    </motion.div>
  );
}

