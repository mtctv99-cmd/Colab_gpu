"use client";

import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { HiArrowRight, HiMicrophone, HiLockClosed, HiBolt, HiCodeBracket, HiChartBar, HiCube } from "react-icons/hi2";

function FadeIn({ children, delay = 0 }: { children: React.ReactNode; delay?: number }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${scrolled ? "bg-zinc-950/80 backdrop-blur-xl border-b border-zinc-800" : "bg-transparent"}`}>
      <div className="max-w-7xl mx-auto flex items-center justify-between px-6 h-16">
        <Link href="/" className="text-lg font-bold tracking-tight text-white">
          clone<span className="text-brand">.</span>tts
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-sm text-zinc-400 hover:text-white transition-colors">Đăng nhập</Link>
          <Link href="/signup" className="inline-flex items-center gap-1.5 bg-brand text-black text-sm font-semibold px-4 py-2 rounded-full hover:bg-emerald-400 transition-colors">
            Bắt đầu <HiArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </nav>
  );
}

export default function Home() {
  return (
    <>
      <Navbar />

      <main>
        {/* Hero */}
        <section className="min-h-[100dvh] flex items-center pt-24 pb-16 px-6">
          <div className="max-w-7xl mx-auto w-full grid lg:grid-cols-2 gap-12 lg:gap-20 items-center">
            <div>
              <motion.p
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                className="text-xs uppercase tracking-[0.18em] text-brand font-mono mb-4"
              >
                AI Voice Cloning
              </motion.p>
              <motion.h1
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
                className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tighter leading-none mb-5"
              >
                Chuyển văn bản thành <br />
                <span className="text-brand">giọng nói AI</span>
              </motion.h1>
              <motion.p
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
                className="text-lg text-zinc-400 max-w-[65ch] leading-relaxed mb-8"
              >
                Nhân bản giọng nói với AI, hỗ trợ tiếng Việt. API cho ứng dụng, xử lý hàng loạt, webhook callback.
              </motion.p>
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.45, ease: [0.16, 1, 0.3, 1] }}
                className="flex flex-wrap gap-3"
              >
                <Link href="/signup" className="inline-flex items-center gap-2 bg-brand text-black font-semibold px-6 py-3 rounded-full hover:bg-emerald-400 transition-colors text-sm">
                  Bắt đầu dùng thử <HiArrowRight className="w-4 h-4" />
                </Link>
                <Link href="#features" className="inline-flex items-center gap-2 border border-zinc-700 text-zinc-300 font-medium px-6 py-3 rounded-full hover:border-zinc-500 transition-colors text-sm">
                  Tìm hiểu thêm
                </Link>
              </motion.div>
            </div>
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className="hidden lg:block"
            >
              <div className="relative aspect-[4/3] rounded-2xl overflow-hidden bg-gradient-to-br from-emerald-900/40 via-zinc-900 to-zinc-950 border border-zinc-800">
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="text-center p-8">
                    <div className="w-20 h-20 mx-auto mb-4 rounded-2xl bg-brand/20 border border-brand/30 flex items-center justify-center">
                      <HiMicrophone className="w-10 h-10 text-brand" />
                    </div>
                    <p className="text-zinc-400 text-sm font-mono">Đang xử lý giọng nói...</p>
                    <div className="mt-4 flex justify-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-brand animate-pulse" />
                      <span className="w-2 h-2 rounded-full bg-brand/60 animate-pulse [animation-delay:0.2s]" />
                      <span className="w-2 h-2 rounded-full bg-brand/30 animate-pulse [animation-delay:0.4s]" />
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="py-24 px-6 border-t border-zinc-800">
          <div className="max-w-7xl mx-auto">
            <FadeIn>
              <p className="text-xs uppercase tracking-[0.18em] text-brand font-mono mb-3">Tính năng</p>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-16">
                Mọi thứ bạn cần để tạo <span className="text-brand">giọng nói AI</span>
              </h2>
            </FadeIn>

            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                { icon: HiMicrophone, title: "Nhân bản giọng nói", desc: "Tải lên file mẫu, AI tổng hợp theo giọng đó. Chỉ cần 5 giây âm thanh tham chiếu." },
                { icon: HiBolt, title: "Xử lý nhanh", desc: "TTS trong 5-15 giây nhờ GPU Colab. Worker luôn sẵn sàng, không chờ load model." },
                { icon: HiCube, title: "Xử lý hàng loạt", desc: "Gửi nhiều text cùng lúc qua batch API. Webhook callback khi hoàn thành." },
                { icon: HiCodeBracket, title: "REST API & API Key", desc: "Tích hợp qua REST API. API key cho phép gọi trực tiếp từ ứng dụng." },
                { icon: HiChartBar, title: "Dashboard quản lý", desc: "Theo dõi số dư ký tự, lịch sử sử dụng, quản lý API key." },
                { icon: HiLockClosed, title: "Bảo mật", desc: "JWT auth, API key SHA-256, prepaid balance. Kiểm soát chi phí." },
              ].map((f, i) => (
                <motion.div
                  key={f.title}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.2 }}
                  transition={{ duration: 0.5, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  className="group rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 hover:border-zinc-700 transition-colors"
                >
                  <f.icon className="w-8 h-8 text-brand mb-4" />
                  <h3 className="font-semibold text-base mb-2">{f.title}</h3>
                  <p className="text-sm text-zinc-400 leading-relaxed">{f.desc}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-24 px-6 border-t border-zinc-800">
          <div className="max-w-3xl mx-auto text-center">
            <FadeIn>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">
                Sẵn sàng dùng thử?
              </h2>
              <p className="text-zinc-400 text-lg mb-8">
                Đăng ký tài khoản, nạp ký tự và bắt đầu tổng hợp giọng nói ngay.
              </p>
              <Link
                href="/signup"
                className="inline-flex items-center gap-2 bg-brand text-black font-semibold px-8 py-3.5 rounded-full hover:bg-emerald-400 transition-colors text-base"
              >
                Đăng ký miễn phí <HiArrowRight className="w-4 h-4" />
              </Link>
            </FadeIn>
          </div>
        </section>

        {/* Footer */}
        <footer className="border-t border-zinc-800 py-8 px-6">
          <div className="max-w-7xl mx-auto flex items-center justify-between text-sm text-zinc-500">
            <span>clone<span className="text-brand">.</span>tts &copy; 2026</span>
            <span className="font-mono text-xs">Built with FastAPI + OmniVoice</span>
          </div>
        </footer>
      </main>
    </>
  );
}
