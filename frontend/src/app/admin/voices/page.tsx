"use client";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Search, Play, Square, Plus, Trash2, Upload } from "lucide-react";
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

interface Voice { id: number; name: string; transcript: string; audio_path: string; }

function AudioBars({ seed }: { seed: number }) {
  const bars = useMemo(() => {
    const p = [20, 35, 25, 55, 40, 70, 50, 80, 60, 90, 65, 85, 55, 75, 45, 65, 35, 55, 25, 20];
    return p.map((h, i) => Math.max(8, h + ((seed * (i + 1) * 7) % 20 - 10)));
  }, [seed]);
  return (
    <div className="flex items-end gap-[2px] h-8">
      {bars.map((h, i) => (
        <div key={i} className="w-full bg-signal/25 rounded-t" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

export default function VoicesPage() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [search, setSearch] = useState("");
  const [showPanel, setShowPanel] = useState(false);
  const [newName, setNewName] = useState("");
  const [newFile, setNewFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [playing, setPlaying] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Voice | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);

  const filtered = useMemo(
    () => voices.filter(v => v.name.toLowerCase().includes(search.toLowerCase())),
    [voices, search]
  );

  const loadVoices = useCallback(async () => {
    try { setVoices(await api("/api/voices/")); } catch (e: any) { toast.error(e.message); }
  }, []);

  useEffect(() => { loadVoices(); }, [loadVoices]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && file.type.startsWith("audio/")) setNewFile(file);
    else toast.error("Chọn file audio");
  };

  const addVoice = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFile) return toast.error("Chọn file âm thanh");
    setLoading(true);
    const fd = new FormData();
    fd.append("name", newName);
    fd.append("audio", newFile);
    try {
      await api("/api/voices/", { method: "POST", body: fd });
      toast.success("Đã thêm giọng nói");
      setNewName(""); setNewFile(null); setShowPanel(false);
      loadVoices();
    } catch (e: any) { toast.error(e.message); } finally { setLoading(false); }
  };

  const deleteVoice = async (id: number) => {
    try {
      await api(`/api/voices/${id}`, { method: "DELETE" });
      toast.success("Đã xóa");
      setDeleteTarget(null);
      loadVoices();
    } catch (e: any) { toast.error(e.message); }
  };

  const playSample = async (v: Voice) => {
    if (playing === v.id) {
      audioRef.current?.pause();
      if (blobUrlRef.current) { URL.revokeObjectURL(blobUrlRef.current); blobUrlRef.current = null; }
      setPlaying(null);
      return;
    }
    audioRef.current?.pause();
    if (blobUrlRef.current) { URL.revokeObjectURL(blobUrlRef.current); blobUrlRef.current = null; }
    try {
      const blob = await api(`/api/voices/${v.id}/audio`) as Blob;
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      const audio = new Audio(url);
      audio.onended = () => { setPlaying(null); URL.revokeObjectURL(url); blobUrlRef.current = null; };
      audio.onerror = () => { toast.error("Không thể phát"); setPlaying(null); URL.revokeObjectURL(url); blobUrlRef.current = null; };
      audio.play().then(() => { audioRef.current = audio; setPlaying(v.id); }).catch(() => setPlaying(null));
    } catch {
      toast.error("Không thể phát");
    }
  };

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-vocal">Thư viện giọng nói</h2>
          <p className="text-sm text-echo">Upload mẫu giọng và quản lý.</p>
        </div>
        <button
          onClick={() => setShowPanel(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Thêm giọng nói
        </button>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dimmer" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Tìm kiếm giọng nói..."
          className="w-full bg-console border border-phantom rounded-lg pl-9 pr-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.length === 0 ? (
          <div className="col-span-full border border-dashed border-phantom rounded-lg py-16 text-center">
            <p className="text-sm text-echo font-mono">
              {search ? "Không tìm thấy giọng nói" : "Chưa có giọng mẫu"}
            </p>
          </div>
        ) : filtered.map(v => (
          <div key={v.id} className="bg-console border border-phantom rounded-lg p-4 space-y-3">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-vocal truncate">{v.name}</p>
                <p className="text-xs text-echo truncate mt-0.5 font-mono">{v.transcript || "-"}</p>
              </div>
            </div>
            <AudioBars seed={v.id} />
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={() => playSample(v)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors"
              >
                {playing === v.id ? (
                  <span className="inline-flex items-center gap-[3px]">
                    <span className="w-1 h-1 rounded-full bg-signal animate-pulse" />
                    <span className="w-1 h-1 rounded-full bg-signal animate-pulse" style={{ animationDelay: "0.15s" }} />
                    <span className="w-1 h-1 rounded-full bg-signal animate-pulse" style={{ animationDelay: "0.3s" }} />
                  </span>
                ) : (
                  <Play className="w-3 h-3" />
                )}
                {playing === v.id ? "Đang phát" : "Nghe mẫu"}
              </button>
              <button
                onClick={() => setDeleteTarget(v)}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-mono text-alert/60 hover:text-alert hover:bg-alert/10 transition-colors ml-auto"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Xóa
              </button>
            </div>
          </div>
        ))}
      </div>

      <AlertDialog open={!!deleteTarget} onOpenChange={open => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xóa giọng nói</AlertDialogTitle>
            <AlertDialogDescription>
              Bạn có chắc muốn xóa &ldquo;{deleteTarget?.name}&rdquo;? Hành động này không thể hoàn tác.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setDeleteTarget(null)}>Hủy</AlertDialogCancel>
            <AlertDialogAction onClick={() => deleteTarget && deleteVoice(deleteTarget.id)} variant="destructive">Xóa</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {showPanel && (
        <div className="fixed inset-0 z-50" onClick={() => setShowPanel(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div className="fixed right-0 top-0 h-full w-96 bg-console border-l border-phantom shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-sm font-semibold text-vocal mb-1">Thêm giọng nói</h3>
              <p className="text-xs text-echo mb-6">Upload file âm thanh mẫu giọng mới.</p>
              <form onSubmit={addVoice} className="space-y-5">
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">Tên giọng</label>
                  <input
                    required
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    placeholder="VD: Giọng nam trầm"
                    className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">File âm thanh</label>
                  <div
                    onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    onClick={() => document.getElementById("voice-file-input")?.click()}
                    className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
                      dragOver ? "border-signal bg-signal/5" : "border-phantom hover:border-signal/40"
                    }`}
                  >
                    {newFile ? (
                      <p className="text-xs text-signal font-mono">{newFile.name}</p>
                    ) : (
                      <div className="space-y-2">
                        <Upload className="w-6 h-6 mx-auto text-dimmer" />
                        <p className="text-xs text-echo">Kéo thả hoặc nhấp để chọn file</p>
                      </div>
                    )}
                    <input id="voice-file-input" type="file" accept="audio/*" className="hidden" onChange={e => setNewFile(e.target.files?.[0] || null)} />
                  </div>
                </div>
                <div className="flex items-center gap-2 pt-2">
                  <button
                    type="submit"
                    disabled={loading}
                    className="flex-1 px-3 py-2 rounded text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors disabled:opacity-50 inline-flex items-center justify-center gap-2"
                  >
                    {loading && <span className="w-1.5 h-1.5 rounded-full bg-pitch animate-pulse" />}
                    {loading ? "Đang tải..." : "Thêm"}
                  </button>
                  <button type="button" onClick={() => setShowPanel(false)} className="px-3 py-2 rounded text-sm text-echo hover:text-vocal hover:bg-strip transition-colors">Hủy</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
