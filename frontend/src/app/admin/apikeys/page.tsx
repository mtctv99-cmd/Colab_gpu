"use client";
import { useEffect, useState, useCallback, useMemo } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface AdminUser {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
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
  expires_at: string | null;
  rate_limit: number | null;
  allowed_ips: string | null;
  notes: string | null;
}

interface UsageStats {
  total_requests: number;
  total_characters: number;
  user_id: number;
}

/* ── Helpers ──────────────────────────────────────────────── */
function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "-";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Vừa xong";
  if (mins < 60) return `${mins}ph trước`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h trước`;
  const days = Math.floor(hrs / 24);
  return `${days} ngày trước`;
}

function fmtDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleDateString("vi-VN", {
    year: "numeric", month: "2-digit", day: "2-digit",
  });
}

/* ── Status filter tabs ───────────────────────────────────── */
type StatusFilter = "all" | "active" | "inactive" | "expired";

const FILTER_TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "active", label: "Đang hoạt động" },
  { key: "inactive", label: "Vô hiệu" },
  { key: "expired", label: "Hết hạn" },
];

/* ── Main Page ────────────────────────────────────────────── */
export default function ApiKeysPage() {
  const [apiKeys, setApiKeys] = useState<AdminApiKey[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);

  // Filter/search
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");

  // Sort
  const [sortCol, setSortCol] = useState<string>("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  // Selected rows
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Create panel
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyUserId, setNewKeyUserId] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyDisplay, setNewKeyDisplay] = useState<string | null>(null);

  // Detail panel
  const [detailKey, setDetailKey] = useState<AdminApiKey | null>(null);
  const [detailUsage, setDetailUsage] = useState<UsageStats | null>(null);

  // Confirm deactivate
  const [confirmDeactivate, setConfirmDeactivate] = useState<number | null>(null);

  // Inline edit name
  const [editingName, setEditingName] = useState<{ id: number; name: string } | null>(null);

  const loadApiKeys = useCallback(async () => {
    try {
      setApiKeys(await api("/api/auth/admin/api-keys"));
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    try {
      setUsers(await api("/api/auth/admin/users"));
    } catch (e: any) {
      toast.error(e.message);
    }
  }, []);

  useEffect(() => {
    loadApiKeys();
    loadUsers();
  }, [loadApiKeys, loadUsers]);

  /* ── Filter + sort logic ──────────────────────────────── */
  const filteredKeys = useMemo(() => {
    let keys = [...apiKeys];

    // Status filter
    if (statusFilter === "active") keys = keys.filter((k) => k.is_active);
    else if (statusFilter === "inactive") keys = keys.filter((k) => !k.is_active);
    else if (statusFilter === "expired")
      keys = keys.filter(
        (k) => k.expires_at && new Date(k.expires_at) < new Date()
      );

    // Search
    if (search.trim()) {
      const q = search.toLowerCase();
      keys = keys.filter(
        (k) =>
          k.user_email.toLowerCase().includes(q) ||
          k.name.toLowerCase().includes(q) ||
          k.key_prefix.toLowerCase().includes(q)
      );
    }

    // Sort
    keys.sort((a, b) => {
      let aVal: any = (a as any)[sortCol];
      let bVal: any = (b as any)[sortCol];
      if (sortCol === "created_at" || sortCol === "last_used_at") {
        aVal = aVal ? new Date(aVal).getTime() : 0;
        bVal = bVal ? new Date(bVal).getTime() : 0;
      }
      if (typeof aVal === "string") {
        return sortDir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      return sortDir === "asc" ? (aVal || 0) - (bVal || 0) : (bVal || 0) - (aVal || 0);
    });

    return keys;
  }, [apiKeys, statusFilter, search, sortCol, sortDir]);

  /* ── Actions ───────────────────────────────────────────── */
  const createKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyUserId) return toast.error("Chọn user");
    try {
      const data = await api("/api/auth/admin/api-keys", {
        method: "POST",
        body: JSON.stringify({
          user_id: parseInt(newKeyUserId),
          name: newKeyName || "Default",
        }),
      });
      setNewKeyDisplay(data.key);
      toast.success("Tạo key thành công");
      setNewKeyName("");
      loadApiKeys();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const deactivateKey = async (id: number) => {
    try {
      await api(`/api/auth/admin/api-keys/${id}`, { method: "DELETE" });
      toast.success("Đã xóa key");
      setConfirmDeactivate(null);
      loadApiKeys();
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const updateKey = async (
    id: number,
    data: Record<string, any>
  ) => {
    try {
      const res = await api(`/api/auth/admin/api-keys/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
      // The PATCH returns {"detail": "Updated"}, not the full object
      if (res && (res as any).detail === "Updated") {
        // Refresh to get latest data
        await loadApiKeys();
      }
      toast.success("Đã cập nhật");
      // Refresh detail if open
      if (detailKey?.id === id) {
        loadDetail(id);
      }
    } catch (e: any) {
      toast.error(e.message);
    }
  };

  const loadDetail = async (id: number) => {
    try {
      const usage = await api(`/api/auth/admin/api-keys/${id}/usage`);
      setDetailUsage(usage);
    } catch {
      setDetailUsage(null);
    }
  };

  const openDetail = (key: AdminApiKey) => {
    setDetailKey(key);
    setDetailUsage(null);
    loadDetail(key.id);
  };

  const toggleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  };

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filteredKeys.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filteredKeys.map((k) => k.id)));
    }
  };

  const bulkDeactivate = async () => {
    if (!confirm("Xóa " + selected.size + " key đã chọn?")) return;
    for (const id of selected) {
      try {
        await api(`/api/auth/admin/api-keys/${id}`, { method: "DELETE" });
      } catch {}
    }
    toast.success(`Đã xóa ${selected.size} key`);
    setSelected(new Set());
    loadApiKeys();
  };

  const sortIcon = (col: string) => {
    if (sortCol !== col) return "↕";
    return sortDir === "asc" ? "↑" : "↓";
  };

  const isExpired = (k: AdminApiKey) =>
    k.expires_at && new Date(k.expires_at) < new Date();

  /* ── Render ────────────────────────────────────────────── */
  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-lg font-bold text-vocal">API Keys</h2>
          <p className="text-sm text-echo">
            Quản lý tất cả API keys. Tổng cộng: {apiKeys.length}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {selected.size > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-echo font-mono">
                {selected.size} đã chọn
              </span>
              <button
                onClick={bulkDeactivate}
                className="px-3 py-1.5 rounded text-xs font-medium bg-alert/20 text-alert hover:bg-alert/30 transition-colors"
              >
                Xóa hàng loạt
              </button>
            </div>
          )}
          <button
            onClick={() => {
              setShowCreate(true);
              setNewKeyDisplay(null);
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Tạo key
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1 bg-console rounded-lg border border-phantom p-0.5">
          {FILTER_TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setStatusFilter(t.key)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-all ${
                statusFilter === t.key
                  ? "bg-signal text-pitch"
                  : "text-echo hover:text-vocal"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Tìm kiếm key..."
          className="w-64 bg-pitch border border-phantom rounded-lg px-3 py-1.5 text-xs text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
        />
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-phantom">
              <th className="py-3 px-3 w-8">
                <input
                  type="checkbox"
                  checked={
                    filteredKeys.length > 0 &&
                    selected.size === filteredKeys.length
                  }
                  onChange={toggleSelectAll}
                  className="accent-signal"
                />
              </th>
              <th
                className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer cursor-pointer hover:text-vocal select-none"
                onClick={() => toggleSort("name")}
              >
                Tên {sortIcon("name")}
              </th>
              <th
                className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer cursor-pointer hover:text-vocal select-none"
                onClick={() => toggleSort("user_email")}
              >
                User {sortIcon("user_email")}
              </th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">
                Key prefix
              </th>
              <th
                className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer cursor-pointer hover:text-vocal select-none"
                onClick={() => toggleSort("is_active")}
              >
                Trạng thái {sortIcon("is_active")}
              </th>
              <th
                className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer cursor-pointer hover:text-vocal select-none"
                onClick={() => toggleSort("created_at")}
              >
                Ngày tạo {sortIcon("created_at")}
              </th>
              <th
                className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer cursor-pointer hover:text-vocal select-none"
                onClick={() => toggleSort("last_used_at")}
              >
                Lần cuối {sortIcon("last_used_at")}
              </th>
              <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-dimmer">
                Rate limit
              </th>
              <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-dimmer">
                Hành động
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={9} className="text-center py-12 text-echo font-mono text-xs">
                  Đang tải...
                </td>
              </tr>
            ) : filteredKeys.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center py-12 text-echo font-mono text-xs">
                  Không tìm thấy API key
                </td>
              </tr>
            ) : (
              filteredKeys.map((k) => (
                <tr
                  key={k.id}
                  className={`border-b border-phantom transition-colors ${
                    selected.has(k.id)
                      ? "bg-signal/5"
                      : "hover:bg-strip/50"
                  } cursor-pointer`}
                  onClick={() => openDetail(k)}
                >
                  <td
                    className="py-3 px-3"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(k.id)}
                      onChange={() => toggleSelect(k.id)}
                      className="accent-signal"
                    />
                  </td>
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2">
                      {editingName?.id === k.id ? (
                        <input
                          value={editingName.name}
                          onChange={(e) =>
                            setEditingName({ id: k.id, name: e.target.value })
                          }
                          onBlur={() => {
                            if (editingName.name !== k.name) {
                              updateKey(k.id, { name: editingName.name });
                            }
                            setEditingName(null);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              (e.target as HTMLInputElement).blur();
                            }
                            if (e.key === "Escape") setEditingName(null);
                          }}
                          className="bg-pitch border border-signal/50 rounded px-1.5 py-0.5 text-sm text-vocal w-32"
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span
                          className="text-sm text-vocal hover:text-signal cursor-text"
                          onClick={(e) => {
                            e.stopPropagation();
                            setEditingName({ id: k.id, name: k.name });
                          }}
                        >
                          {k.name}
                        </span>
                      )}
                      {k.notes && (
                        <span className="text-[10px] text-dimmer" title={k.notes}>
                          📝
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {k.user_email}
                  </td>
                  <td className="py-3 px-4">
                    <code className="text-xs font-mono text-echo bg-strip/50 px-1.5 py-0.5 rounded">
                      {k.key_prefix}...
                    </code>
                  </td>
                  <td className="py-3 px-4">
                    <span className="inline-flex items-center text-xs font-mono text-echo">
                      <span
                        className={`w-1.5 h-1.5 rounded-full inline-block mr-2 ${
                          !k.is_active
                            ? "bg-dimmer"
                            : isExpired(k)
                            ? "bg-alert"
                            : "bg-online"
                        }`}
                      />
                      {!k.is_active
                        ? "Inactive"
                        : isExpired(k)
                        ? "Hết hạn"
                        : "Active"}
                      {k.expires_at && (
                        <span className="ml-1.5 text-[10px] text-dimmer">
                          (hết {fmtDate(k.expires_at)})
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {fmtDate(k.created_at)}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {timeAgo(k.last_used_at)}
                  </td>
                  <td className="py-3 px-4 font-mono text-xs text-echo">
                    {k.rate_limit ? `${k.rate_limit}/h` : "-"}
                  </td>
                  <td
                    className="py-3 px-4 text-right"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex justify-end gap-2">
                      {confirmDeactivate === k.id ? (
                        <div className="inline-flex items-center gap-1">
                          <button
                            onClick={() => deactivateKey(k.id)}
                            className="px-2 py-1 rounded text-xs font-mono bg-alert text-vocal hover:bg-alert/80 transition-colors"
                          >
                            Xác nhận xóa
                          </button>
                          <button
                            onClick={() => setConfirmDeactivate(null)}
                            className="px-2 py-1 rounded text-xs text-echo hover:text-vocal hover:bg-strip transition-colors"
                          >
                            Hủy
                          </button>
                        </div>
                      ) : (
                        <>
                          {k.is_active ? (
                            <button
                              onClick={() => updateKey(k.id, { is_active: false })}
                              className="px-2 py-1 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors"
                            >
                              Vô hiệu
                            </button>
                          ) : (
                            <button
                              onClick={() => updateKey(k.id, { is_active: true })}
                              className="px-2 py-1 rounded text-xs font-mono text-online hover:bg-online/10 transition-colors"
                            >
                              Kích hoạt
                            </button>
                          )}
                          <button
                            onClick={() => setConfirmDeactivate(k.id)}
                            className="px-2 py-1 rounded text-xs font-mono text-alert hover:bg-alert/10 transition-colors"
                          >
                            Xóa
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* ── Create panel (slide-over) ─────────────────────── */}
      {showCreate && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => setShowCreate(false)}
        >
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="fixed right-0 top-0 h-full w-96 bg-console border-l border-phantom shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-semibold text-vocal">
                  Tạo API key
                </h3>
                <button
                  onClick={() => setShowCreate(false)}
                  className="text-dimmer hover:text-vocal transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <p className="text-xs text-echo mb-6">
                Cấp key mới cho người dùng.
              </p>

              <form onSubmit={createKey} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider font-medium">
                    User
                  </label>
                  <select
                    value={newKeyUserId}
                    onChange={(e) => setNewKeyUserId(e.target.value)}
                    className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal focus:outline-none focus:border-signal/50 transition-colors"
                  >
                    <option value="">-- Chọn user --</option>
                    {users
                      .filter((u) => u.is_active)
                      .map((u) => (
                        <option key={u.id} value={u.id.toString()}>
                          {u.email} ({u.role})
                        </option>
                      ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider font-medium">
                    Tên key
                  </label>
                  <input
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="Tên để nhận diện"
                    className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
                  />
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <button
                    type="submit"
                    className="flex-1 px-3 py-2 rounded-lg text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
                  >
                    Tạo
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    className="px-3 py-2 rounded-lg text-sm text-echo hover:text-vocal hover:bg-strip transition-colors"
                  >
                    Hủy
                  </button>
                </div>
              </form>

      {newKeyDisplay && (
        <div className="mt-5 p-4 border border-signal/30 bg-signal/5 rounded-xl space-y-2">
          <p className="text-xs text-signal font-semibold">
            🎉 Key mới (Copy ngay, không xem lại được):
          </p>
          <div className="flex gap-2">
            <code className="flex-1 block text-xs text-echo break-all bg-pitch p-2 rounded-lg font-mono">
              {newKeyDisplay}
            </code>
            <button
              onClick={() => {
                navigator.clipboard.writeText(newKeyDisplay);
                toast.success("Đã copy");
              }}
              className="shrink-0 flex items-center justify-center px-4 rounded-lg text-xs font-medium text-pitch bg-signal hover:bg-signal/90 transition-colors"
              type="button"
            >
              Copy
            </button>
          </div>
        </div>
      )}
            </div>
          </div>
        </div>
      )}

      {/* ── Detail panel (slide-over) ─────────────────────── */}
      {detailKey && (
        <div
          className="fixed inset-0 z-50"
          onClick={() => {
            setDetailKey(null);
            setDetailUsage(null);
          }}
        >
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="fixed right-0 top-0 h-full w-[480px] bg-console border-l border-phantom shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              {/* Header */}
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        detailKey.is_active ? "bg-online" : "bg-dimmer"
                      }`}
                    />
                    <h3 className="text-base font-semibold text-vocal">
                      {detailKey.name}
                    </h3>
                  </div>
                  <code className="text-xs text-echo font-mono bg-strip/50 px-1.5 py-0.5 rounded">
                    {detailKey.key_prefix}...
                  </code>
                  <span className="text-xs text-dimmer ml-2">
                    ID: {detailKey.id}
                  </span>
                </div>
                <button
                  onClick={() => {
                    setDetailKey(null);
                    setDetailUsage(null);
                  }}
                  className="text-dimmer hover:text-vocal transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Tabs: Info / Settings */}
              <DetailTabs
                keyData={detailKey}
                usage={detailUsage}
                onUpdate={(data) => updateKey(detailKey.id, data)}
                onRefresh={() => loadDetail(detailKey.id)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Detail Tabs ──────────────────────────────────────────── */
function DetailTabs({
  keyData,
  usage,
  onUpdate,
  onRefresh,
}: {
  keyData: AdminApiKey;
  usage: UsageStats | null;
  onUpdate: (data: Record<string, any>) => void;
  onRefresh: () => void;
}) {
  const [tab, setTab] = useState<"info" | "settings">("info");

  // Local state for settings form
  const [expiresAt, setExpiresAt] = useState(keyData.expires_at?.split("T")[0] || "");
  const [rateLimit, setRateLimit] = useState(keyData.rate_limit?.toString() || "");
  const [allowedIps, setAllowedIps] = useState(
    keyData.allowed_ips ? JSON.parse(keyData.allowed_ips).join(", ") : ""
  );
  const [notes, setNotes] = useState(keyData.notes || "");

  const saveSettings = () => {
    const data: Record<string, any> = {};
    data.expires_at = expiresAt ? new Date(expiresAt).toISOString() : null;
    data.rate_limit = rateLimit ? parseInt(rateLimit) : null;
    data.allowed_ips = allowedIps
      ? allowedIps.split(",").map((s: string) => s.trim()).filter(Boolean)
      : [];
    data.notes = notes || null;
    onUpdate(data);
  };

  return (
    <div>
      {/* Tab buttons */}
      <div className="flex gap-1 bg-pitch rounded-lg p-0.5 border border-phantom mb-6">
        {[
          { key: "info", label: "Thông tin" },
          { key: "settings", label: "Cấu hình" },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as "info" | "settings")}
            className={`flex-1 px-3 py-1.5 rounded text-xs font-medium transition-all ${
              tab === t.key
                ? "bg-signal text-pitch"
                : "text-echo hover:text-vocal"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "info" && (
        <div className="space-y-4">
          <InfoRow label="User" value={keyData.user_email} />
          <InfoRow label="Trạng thái" value={keyData.is_active ? "Active" : "Inactive"} />
          <InfoRow label="Ngày tạo" value={keyData.created_at ? new Date(keyData.created_at).toLocaleString("vi-VN") : "-"} />
          <InfoRow label="Lần cuối" value={keyData.last_used_at ? new Date(keyData.last_used_at).toLocaleString("vi-VN") : "Chưa dùng"} />
          <InfoRow label="Hết hạn" value={keyData.expires_at ? new Date(keyData.expires_at).toLocaleString("vi-VN") : "Không"} />

          {/* Usage stats */}
          <div className="border-t border-phantom pt-4 mt-4">
            <h4 className="text-xs font-semibold text-vocal uppercase tracking-wider mb-3">
              Usage
            </h4>
            {usage ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-pitch rounded-xl border border-phantom p-4 text-center">
                  <div className="text-xl font-bold text-signal">
                    {usage.total_requests.toLocaleString()}
                  </div>
                  <div className="text-[10px] text-echo mt-1 font-mono uppercase tracking-wider">
                    Requests
                  </div>
                </div>
                <div className="bg-pitch rounded-xl border border-phantom p-4 text-center">
                  <div className="text-xl font-bold text-signal">
                    {usage.total_characters.toLocaleString()}
                  </div>
                  <div className="text-[10px] text-echo mt-1 font-mono uppercase tracking-wider">
                    Characters
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-xs text-echo">Đang tải...</p>
            )}
          </div>
        </div>
      )}

      {tab === "settings" && (
        <div className="space-y-5">
          {/* Expiry */}
          <div className="space-y-1.5">
            <label className="text-xs text-echo uppercase tracking-wider font-medium">
              Ngày hết hạn
            </label>
            <input
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal focus:outline-none focus:border-signal/50 transition-colors"
            />
            {expiresAt && (
              <p className="text-[10px] text-dimmer">
                Key sẽ tự động vô hiệu sau ngày này
              </p>
            )}
          </div>

          {/* Rate limit */}
          <div className="space-y-1.5">
            <label className="text-xs text-echo uppercase tracking-wider font-medium">
              Rate limit (requests/hour)
            </label>
            <input
              type="number"
              min="0"
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
              placeholder="Không giới hạn"
              className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
            />
          </div>

          {/* Allowed IPs */}
          <div className="space-y-1.5">
            <label className="text-xs text-echo uppercase tracking-wider font-medium">
              IP được phép
            </label>
            <input
              value={allowedIps}
              onChange={(e) => setAllowedIps(e.target.value)}
              placeholder="192.168.1.1, 10.0.0.0/24"
              className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors"
            />
            <p className="text-[10px] text-dimmer">
              Cách nhau bằng dấu phẩy. Để trống nếu không giới hạn.
            </p>
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <label className="text-xs text-echo uppercase tracking-wider font-medium">
              Ghi chú
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Ghi chú nội bộ về key này"
              className="w-full bg-pitch border border-phantom rounded-lg px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors resize-none"
            />
          </div>

          <button
            onClick={saveSettings}
            className="w-full px-4 py-2 rounded-lg text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
          >
            Lưu cấu hình
          </button>
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-phantom/50">
      <span className="text-xs text-echo">{label}</span>
      <span className="text-xs text-vocal font-mono">{value}</span>
    </div>
  );
}
