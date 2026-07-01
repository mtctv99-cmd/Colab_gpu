"use client";
import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { toast } from "sonner";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token) return toast.error("Link không hợp lệ");
    if (password.length < 6) return toast.error("Mật khẩu tối thiểu 6 ký tự");
    if (password !== confirm) return toast.error("Mật khẩu nhập lại không khớp");
    setLoading(true);
    try {
      await api("/api/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      toast.success("Đặt lại mật khẩu thành công");
      router.push("/login");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label htmlFor="password" className="block text-sm text-[#F4F4F5] mb-1.5">Mật khẩu mới</label>
        <input id="password" type="password" required value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full h-9 rounded-md bg-[#1C1C20] border border-[rgba(255,255,255,0.06)] px-3 text-sm text-[#F4F4F5] placeholder:text-[#3D3D44] focus:outline-none focus:ring-2 focus:ring-[#D4A853] transition-all"
        />
      </div>
      <div>
        <label htmlFor="confirm" className="block text-sm text-[#F4F4F5] mb-1.5">Nhập lại mật khẩu</label>
        <input id="confirm" type="password" required value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className="w-full h-9 rounded-md bg-[#1C1C20] border border-[rgba(255,255,255,0.06)] px-3 text-sm text-[#F4F4F5] placeholder:text-[#3D3D44] focus:outline-none focus:ring-2 focus:ring-[#D4A853] transition-all"
        />
      </div>
      <button type="submit" disabled={loading}
        className="w-full h-9 rounded-md bg-[#D4A853] text-[#0A0A0B] text-sm font-medium hover:bg-[#B8923E] active:translate-y-px transition-all disabled:opacity-50"
      >
        {loading ? <span className="w-3 h-3 rounded-full bg-[#0A0A0B]/40 animate-pulse" /> : "Đặt lại mật khẩu"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="min-h-[100dvh] flex items-center justify-center p-6 bg-[#141416]">
      <div className="w-full max-w-sm border-l-2 border-[#D4A853] pl-6">
        <Link href="/" className="text-2xl font-bold tracking-tight text-[#F4F4F5] mb-6 block">
          clone<span className="text-[#D4A853]">.</span>tts
        </Link>
        <h1 className="text-xl font-bold text-[#F4F4F5] mb-1">Đặt lại mật khẩu</h1>
        <p className="text-sm text-[#787880] mb-8">Nhập mật khẩu mới</p>
        <Suspense fallback={<div className="text-sm text-[#787880]">Đang tải...</div>}>
          <ResetPasswordForm />
        </Suspense>
      </div>
    </div>
  );
}
