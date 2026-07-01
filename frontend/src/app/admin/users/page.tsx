"use client";
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";

interface AdminUser { id: number; email: string; role: string; balance: number; is_active: boolean; created_at: string; }

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [showAddPanel, setShowAddPanel] = useState(false);
  const [showTopupPanel, setShowTopupPanel] = useState<AdminUser | null>(null);
  const [topupAmount, setTopupAmount] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("user");
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const loadUsers = useCallback(async () => {
    try { setUsers(await api("/api/auth/admin/users")); } catch (e: any) { toast.error(e.message); }
  }, []);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/api/auth/admin/users", { method: "POST", body: JSON.stringify({ email: newEmail, password: newPassword, role: newRole }) });
      toast.success("Tạo user thành công");
      setNewEmail(""); setNewPassword(""); setNewRole("user"); setShowAddPanel(false);
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  const deleteUser = async (id: number) => {
    try { await api(`/api/auth/admin/users/${id}`, { method: "DELETE" }); toast.success("Đã xóa"); setConfirmDelete(null); loadUsers(); }
    catch (e: any) { toast.error(e.message); }
  };

  const topupBalance = async (e: React.FormEvent) => {
    e.preventDefault();
    const amount = parseInt(topupAmount);
    if (isNaN(amount) || amount <= 0) return toast.error("Số lượng không hợp lệ");
    if (!showTopupPanel) return;
    try {
      await api(`/api/auth/admin/users/${showTopupPanel.id}`, { method: "PUT", body: JSON.stringify({ balance: showTopupPanel.balance + amount }) });
      toast.success("Đã nạp ký tự");
      setShowTopupPanel(null); setTopupAmount("");
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  const toggleActive = async (id: number, current: boolean) => {
    try {
      await api(`/api/auth/admin/users/${id}`, { method: "PUT", body: JSON.stringify({ is_active: !current }) });
      toast.success(current ? "Đã vô hiệu hóa" : "Đã kích hoạt");
      loadUsers();
    } catch (e: any) { toast.error(e.message); }
  };

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-vocal">Người dùng</h2>
          <p className="text-sm text-echo">Thêm, xóa, nạp ký tự, vô hiệu hóa user.</p>
        </div>
        <button
          onClick={() => setShowAddPanel(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
          Thêm user
        </button>
      </div>

      <table className="w-full">
        <thead>
          <tr className="border-b border-phantom">
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Email</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Role</th>
            <th className="text-right py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Balance</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Ngày tạo</th>
            <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Trạng thái</th>
            <th className="text-right py-3 px-4 text-xs font-semibold uppercase tracking-wider text-dimmer">Hành động</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 ? (
            <tr>
              <td colSpan={6} className="text-center py-12 text-echo font-mono text-xs">Chưa có user</td>
            </tr>
          ) : users.map(u => (
            <tr key={u.id} className="border-b border-phantom hover:bg-strip/50 transition-colors">
              <td className="py-3 px-4 text-sm text-vocal">{u.email}</td>
              <td className="py-3 px-4">
                <span className="text-xs font-mono text-echo uppercase">{u.role}</span>
              </td>
              <td className="py-3 px-4 text-right font-mono text-xs text-signal">{u.balance.toLocaleString()}</td>
              <td className="py-3 px-4 font-mono text-xs text-echo">
                {u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}
              </td>
              <td className="py-3 px-4">
                <button
                  onClick={() => toggleActive(u.id, u.is_active)}
                  className="inline-flex items-center text-xs font-mono transition-colors cursor-pointer"
                >
                  <span className={`w-1.5 h-1.5 rounded-full inline-block mr-2 ${u.is_active ? "bg-online" : "bg-dimmer"}`} />
                  <span className={u.is_active ? "text-online" : "text-echo"}>{u.is_active ? "Active" : "Disabled"}</span>
                </button>
              </td>
              <td className="py-3 px-4 text-right">
                {confirmDelete === u.id ? (
                  <div className="inline-flex items-center gap-1">
                    <button onClick={() => deleteUser(u.id)} className="px-2 py-1 rounded text-xs font-mono bg-alert text-vocal hover:bg-alert/80 transition-colors">Xác nhận</button>
                    <button onClick={() => setConfirmDelete(null)} className="px-2 py-1 rounded text-xs text-echo hover:text-vocal hover:bg-strip transition-colors">Hủy</button>
                  </div>
                ) : (
                  <div className="inline-flex items-center gap-1">
                    <button onClick={() => setShowTopupPanel(u)} className="px-2 py-1 rounded text-xs font-mono text-echo hover:text-vocal hover:bg-strip transition-colors">Nạp</button>
                    <button onClick={() => setConfirmDelete(u.id)} className="p-1.5 rounded text-alert/60 hover:text-alert hover:bg-alert/10 transition-colors">
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {showAddPanel && (
        <div className="fixed inset-0 z-50" onClick={() => setShowAddPanel(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div className="fixed right-0 top-0 h-full w-96 bg-console border-l border-phantom shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-sm font-semibold text-vocal mb-1">Thêm user</h3>
              <p className="text-xs text-echo mb-6">Tạo tài khoản người dùng mới.</p>
              <form onSubmit={createUser} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">Email</label>
                  <input required type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} placeholder="user@domain.com" className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">Mật khẩu</label>
                  <input required type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors" />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">Role</label>
                  <select value={newRole} onChange={e => setNewRole(e.target.value)} className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal focus:outline-none focus:border-signal/50 transition-colors">
                    <option value="user">user</option>
                    <option value="admin">admin</option>
                  </select>
                </div>
                <div className="flex items-center gap-2 pt-2">
                  <button type="submit" className="flex-1 px-3 py-2 rounded text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors">Tạo</button>
                  <button type="button" onClick={() => setShowAddPanel(false)} className="px-3 py-2 rounded text-sm text-echo hover:text-vocal hover:bg-strip transition-colors">Hủy</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {showTopupPanel && (
        <div className="fixed inset-0 z-50" onClick={() => setShowTopupPanel(null)}>
          <div className="absolute inset-0 bg-black/40" />
          <div className="fixed right-0 top-0 h-full w-96 bg-console border-l border-phantom shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-sm font-semibold text-vocal mb-1">Nạp ký tự</h3>
              <p className="text-xs text-echo mb-2">User: <span className="text-vocal font-mono">{showTopupPanel.email}</span></p>
              <p className="text-xs text-echo mb-6">Balance hiện tại: <span className="text-signal font-mono">{showTopupPanel.balance.toLocaleString()}</span></p>
              <form onSubmit={topupBalance} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-echo uppercase tracking-wider">Số lượng</label>
                  <input required type="number" min="1" value={topupAmount} onChange={e => setTopupAmount(e.target.value)} placeholder="Nhập số ký tự" className="w-full bg-pitch border border-phantom rounded px-3 py-2 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:border-signal/50 transition-colors font-mono" />
                </div>
                <div className="flex items-center gap-2 pt-2">
                  <button type="submit" className="flex-1 px-3 py-2 rounded text-sm font-medium bg-signal text-pitch hover:bg-signal/90 transition-colors">Nạp</button>
                  <button type="button" onClick={() => setShowTopupPanel(null)} className="px-3 py-2 rounded text-sm text-echo hover:text-vocal hover:bg-strip transition-colors">Hủy</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
