"use client";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { toast } from "sonner";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      setSent(true);
      toast.success("Kiểm tra email để đặt lại mật khẩu");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[100dvh] flex items-center justify-center p-6 bg-[#141416]">
      <div className="w-full max-w-sm border-l-2 border-[#D4A853] pl-6">
        <Link href="/" className="text-2xl font-bold tracking-tight text-[#F4F4F5] mb-6 block">
          clone<span className="text-[#D4A853]">.</span>tts
        </Link>
        {sent ? (
          <div>
            <h1 className="text-xl font-bold text-[#F4F4F5] mb-1">Đã gửi email</h1>
            <p className="text-sm text-[#787880] mb-8">
              Nếu email tồn tại, chúng tôi đã gửi hướng dẫn đặt lại mật khẩu.
            </p>
            <Link
              href="/login"
              className="text-sm text-[#D4A853] hover:text-[#B8923E] transition-colors"
            >
              Quay lại đăng nhập
            </Link>
          </div>
        ) : (
          <>
            <h1 className="text-xl font-bold text-[#F4F4F5] mb-1">Quên mật khẩu</h1>
            <p className="text-sm text-[#787880] mb-8">Nhập email để nhận hướng dẫn</p>
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label htmlFor="email" className="block text-sm text-[#F4F4F5] mb-1.5">Email</label>
                <input id="email" type="email" required value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="w-full h-9 rounded-md bg-[#1C1C20] border border-[rgba(255,255,255,0.06)] px-3 text-sm text-[#F4F4F5] placeholder:text-[#3D3D44] focus:outline-none focus:ring-2 focus:ring-[#D4A853] transition-all"
                />
              </div>
              <button type="submit" disabled={loading}
                className="w-full h-9 rounded-md bg-[#D4A853] text-[#0A0A0B] text-sm font-medium hover:bg-[#B8923E] active:translate-y-px transition-all disabled:opacity-50"
              >
                {loading ? <span className="w-3 h-3 rounded-full bg-[#0A0A0B]/40 animate-pulse" /> : "Gửi email"}
              </button>
              <p className="text-center text-sm text-[#787880]">
                Nhớ mật khẩu?{" "}
                <Link href="/login" className="text-[#D4A853] hover:text-[#B8923E] transition-colors">
                  Đăng nhập
                </Link>
              </p>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
