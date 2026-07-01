"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "motion/react";
import { api } from "@/lib/api";
import { toast } from "sonner";

function AuthWaveform() {
  return (
    <div className="flex items-end justify-center gap-[2px] opacity-40">
      {[8, 20, 14, 32, 10, 24, 6, 28, 16, 36, 12, 22].map((h, i) => (
        <motion.div
          key={i}
          className="w-[3px] rounded-full bg-signal"
          initial={{ height: 0 }}
          animate={{ height: h }}
          transition={{
            duration: 1.2,
            delay: i * 0.08,
            ease: [0.16, 1, 0.3, 1],
            repeat: Infinity,
            repeatType: "reverse",
            repeatDelay: 0.3,
          }}
        />
      ))}
    </div>
  );
}

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user", JSON.stringify(data.user));
      toast.success("Đăng ký thành công");
      router.push("/dashboard");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[100dvh] flex">
      {/* Brand column */}
      <div className="hidden md:flex w-[40%] bg-pitch border-r border-phantom flex-col items-center justify-center gap-6 p-12">
        <Link href="/" className="text-2xl font-bold tracking-tight text-vocal">
          clone<span className="text-signal">.</span>tts
        </Link>
        <p className="text-sm text-echo text-center max-w-[24ch] leading-relaxed">
          Đăng ký tài khoản và bắt đầu tổng hợp giọng nói AI ngay
        </p>
        <AuthWaveform />
      </div>

      {/* Form column */}
      <div className="flex-1 flex items-center justify-center p-6 bg-console">
        <div className="w-full max-w-sm border-l-2 border-signal pl-6">
          <h1 className="text-xl font-bold text-vocal mb-1">Đăng ký</h1>
          <p className="text-sm text-echo mb-8">Tạo tài khoản mới</p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="email" className="block text-sm text-vocal mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                className="w-full h-9 rounded-md bg-strip border border-phantom px-3 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:ring-2 focus:ring-signal transition-all"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm text-vocal mb-1.5">
                Mật khẩu
              </label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full h-9 rounded-md bg-strip border border-phantom px-3 text-sm text-vocal placeholder:text-dimmer focus:outline-none focus:ring-2 focus:ring-signal transition-all"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full h-9 rounded-md bg-signal text-pitch text-sm font-medium hover:bg-signal/80 active:translate-y-px transition-all disabled:opacity-50 flex items-center justify-center"
            >
              {loading ? (
                <span className="w-3 h-3 rounded-full bg-pitch/40 animate-pulse" />
              ) : (
                "Đăng ký"
              )}
            </button>
            <p className="text-center text-sm text-echo">
              Đã có tài khoản?{" "}
              <Link href="/login" className="text-signal hover:text-signal/80 transition-colors">
                Đăng nhập
              </Link>
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
