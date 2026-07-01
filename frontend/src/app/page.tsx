"use client";

import {
  motion,
  useScroll,
  useTransform,
  useSpring,
  AnimatePresence,
} from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Microphone,
  Waves,
  Rocket,
  GearSix,
  ShieldCheck,
  MagicWand,
  Sparkle,
  ArrowRight,
  PlayCircle,
  Waveform,
  Clock,
  Cube,
  Translate,
} from "@phosphor-icons/react";

/* ── design_plan ──────────────────────────────────────────────
   Palette:  #0A0A0B pitch / #D4A853 signal / #F4F4F5 vocal / #787880 echo
   Hero:     Cinematic Center + animated waveform bar graph
   Bento:    3 cards, asymmetric col-span layout, hover parallax images
   Scroll:   Pinning split + scrubbing counter reveal
   Stacking: Depth with backdrop-blur + offset shadows
   CTA:      Gradient glow ring + double-CTA layout
   AIDA:     Nav → Hero → Marquee → Bento → Scroll → Stack → CTA → Footer
   Font:     Geist (via next/font)
────────────────────────────────────────────────────────── */

function useScrollProgress() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  return { ref, scrollYProgress };
}

/* ── Waveform bars (Hero bg) ──────────────────────────────── */
function WaveformBars() {
  const bars = Array.from({ length: 48 }, (_, i) => ({
    h: 0.15 + Math.sin(i * 0.45) * 0.35 + Math.random() * 0.2,
    delay: i * 0.04,
  }));
  return (
    <div className="absolute inset-0 flex items-center justify-center gap-[3px] opacity-[0.04] pointer-events-none overflow-hidden">
      {bars.map((b, i) => (
        <motion.div
          key={i}
          className="w-[3px] bg-[#D4A853] rounded-full origin-bottom"
          style={{ height: "40%" }}
          animate={{
            scaleY: [0.3, b.h * 2, 0.3],
            opacity: [0.2, 0.8, 0.2],
          }}
          transition={{
            duration: 2.5 + Math.random() * 2,
            repeat: Infinity,
            delay: b.delay,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
}

/* ── Floating particles ───────────────────────────────────── */
function Particles({ count = 18 }: { count?: number }) {
  const particles = Array.from({ length: count }, (_, i) => ({
    x: Math.random() * 100,
    y: Math.random() * 100,
    size: 1.5 + Math.random() * 2.5,
    duration: 6 + Math.random() * 8,
    delay: Math.random() * 5,
  }));
  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      {particles.map((p, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full bg-[#D4A853]"
          style={{
            width: p.size,
            height: p.size,
            left: `${p.x}%`,
            top: `${p.y}%`,
          }}
          animate={{
            y: [0, -30, 0],
            opacity: [0.15, 0.5, 0.15],
            scale: [1, 1.3, 1],
          }}
          transition={{
            duration: p.duration,
            repeat: Infinity,
            delay: p.delay,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
}

/* ── Navbar (glass pill, refined) ──────────────────────────── */
function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className="fixed top-4 inset-x-0 z-50 flex justify-center px-4">
      <motion.div
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className={`w-full max-w-5xl flex items-center justify-between px-5 h-14 rounded-2xl border transition-all duration-700 ${
          scrolled
            ? "bg-[#0A0A0B]/80 backdrop-blur-2xl border-[rgba(255,255,255,0.08)] shadow-2xl shadow-black/30"
            : "bg-[#0A0A0B]/40 backdrop-blur-sm border-transparent"
        }`}
      >
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-[#D4A853]/10 text-[#D4A853]">
            <Waveform size={18} weight="fill" />
          </span>
          <span className="text-lg font-bold tracking-tight text-[#F4F4F5]">
            TTS Dubbing
          </span>
        </Link>

        <div className="hidden md:flex items-center gap-1">
          <NavLink href="#features">Tính năng</NavLink>
          <NavLink href="#how-it-works">Cách hoạt động</NavLink>
          <NavLink href="#developers">API</NavLink>
          <NavLink href="/docs">Tài liệu</NavLink>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/login"
            className="inline-flex items-center justify-center text-sm font-medium transition-all h-8 px-3.5 text-[#787880] hover:text-[#F4F4F5] rounded-lg hover:bg-white/5"
          >
            Đăng nhập
          </Link>
          <Link
            href="/signup"
            className="inline-flex items-center justify-center rounded-lg text-sm font-semibold transition-all h-8 px-4 bg-[#D4A853] text-[#0A0A0B] hover:bg-[#C49A3E] active:translate-y-px shadow-lg shadow-[#D4A853]/15"
          >
            Bắt đầu
          </Link>
        </div>
      </motion.div>
    </nav>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="px-3 py-1.5 text-sm text-[#787880] hover:text-[#F4F4F5] rounded-lg hover:bg-white/5 transition-all duration-300"
    >
      {children}
    </a>
  );
}

/* ── Infinite Marquee ──────────────────────────────────────── */
function Marquee() {
  const logos = [
    "Tiếng Việt", "OmniVoice", "FastAPI", "Colab T4",
    "WebSocket", "REST API", "AI Clone", "PyTorch",
  ];
  return (
    <div className="relative overflow-hidden py-8 border-y border-[rgba(255,255,255,0.04)]">
      <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-[#0A0A0B] to-transparent z-10 pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-[#0A0A0B] to-transparent z-10 pointer-events-none" />
      <motion.div
        className="flex gap-16 text-xs font-mono tracking-[0.15em] uppercase items-center"
        animate={{ x: ["0%", "-50%"] }}
        transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
      >
        {[...logos, ...logos].map((l, i) => (
          <span key={i} className="shrink-0 flex items-center gap-4 text-[#787880]/30">
            <span className="w-1.5 h-1.5 rounded-full bg-[#D4A853]/20" />
            {l}
          </span>
        ))}
      </motion.div>
    </div>
  );
}

/* ── Hero ──────────────────────────────────────────────────── */
function Hero() {
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-32 pb-20 overflow-hidden">
      {/* Background layers */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(212,168,83,0.06)_0%,transparent_60%)]" />
      <WaveformBars />
      <Particles count={20} />

      {/* Glow orb */}
      <div className="pointer-events-none absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full bg-[#D4A853] opacity-[0.02] blur-3xl" />

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] text-xs text-[#787880] font-mono tracking-wider mb-8"
      >
        <span className="w-2 h-2 rounded-full bg-[#34B855] animate-pulse" />
        AI Voice Cloning Platform
      </motion.div>

      <motion.h1
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
        className="text-center max-w-5xl mx-auto font-bold tracking-tighter leading-[1.06] text-[#F4F4F5]"
        style={{ fontSize: "clamp(2.8rem, 7vw, 5.5rem)" }}
      >
        Tổng hợp giọng nói AI{" "}
        <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#D4A853] via-[#E8C86A] to-[#D4A853]">
          siêu thực
        </span>
        <br />
        cho tiếng Việt
      </motion.h1>

      <motion.p
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className="text-center text-lg text-[#787880] max-w-2xl mx-auto mt-6 leading-relaxed"
      >
        Tạo giọng nói AI chất lượng cao từ văn bản — nhân bản giọng nói, xử lý batch,
        webhook callback. Hỗ trợ tiếng Việt đầu tiên trên OmniVoice.
      </motion.p>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="flex flex-wrap items-center justify-center gap-4 mt-10"
      >
        <Link
          href="/signup"
          className="group inline-flex items-center gap-2.5 rounded-xl text-sm font-semibold transition-all h-13 px-8 bg-[#D4A853] text-[#0A0A0B] hover:bg-[#C49A3E] active:translate-y-px shadow-lg shadow-[#D4A853]/20 hover:shadow-[#D4A853]/30"
        >
          <Rocket size={18} weight="bold" />
          Bắt đầu dùng thử
          <ArrowRight size={16} className="transition-transform duration-300 group-hover:translate-x-1" />
        </Link>
        <Link
          href="/login"
          className="group inline-flex items-center gap-2 rounded-xl text-sm font-medium transition-all h-13 px-8 border border-[rgba(255,255,255,0.1)] text-[#F4F4F5] hover:bg-white/5 active:translate-y-px"
        >
          <PlayCircle size={18} />
          Dùng thử trực tiếp
        </Link>
      </motion.div>

      {/* Stats row */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="flex items-center gap-8 md:gap-12 mt-16 pt-12 border-t border-[rgba(255,255,255,0.04)]"
      >
        {[
          { value: "5-15s", label: "TTS Speed" },
          { value: "Việt Nam", label: "Region" },
          { value: "99.9%", label: "Uptime" },
        ].map((s) => (
          <div key={s.label} className="text-center">
            <div className="text-sm font-bold text-[#F4F4F5]">{s.value}</div>
            <div className="text-xs text-[#787880] mt-0.5 font-mono">{s.label}</div>
          </div>
        ))}
      </motion.div>
    </section>
  );
}

/* ── Bento Grid (asymmetric, gapless) ──────────────────────── */
function BentoGrid() {
  const cards = [
    {
      title: "Nhân bản giọng nói",
      desc: "Tải lên 5 giây âm thanh mẫu, AI tái tạo chính xác. Giữ nguyên sắc thái, cảm xúc và ngữ điệu.",
      icon: Microphone,
      col: "col-span-1",
      row: "row-span-2",
      img: "voice-clone",
    },
    {
      title: "Xử lý hàng loạt",
      desc: "Gửi hàng ngàn request qua API, webhook callback khi hoàn thành. Queue thông minh, auto-retry.",
      icon: Waves,
      col: "col-span-1",
      row: "row-span-1",
      img: "batch",
    },
    {
      title: "Bảo mật & Quản lý",
      desc: "JWT auth, API key SHA-256, prepaid balance, dashboard real-time. Kiểm soát toàn bộ hệ thống.",
      icon: ShieldCheck,
      col: "col-span-1",
      row: "row-span-1",
      img: "security",
      highlight: true,
    },
  ];

  return (
    <section id="features" className="py-32 px-6">
      <div className="max-w-6xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="mb-6"
        >
          <span className="text-xs uppercase tracking-[0.2em] text-[#D4A853]/60 font-mono">
            Features
          </span>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#F4F4F5] mt-3">
            Mọi thứ bạn cần để tạo{" "}
            <span className="text-[#D4A853]">giọng nói AI</span>
          </h2>
        </motion.div>

        <div className="grid grid-cols-2 auto-rows-[220px] gap-4">
          {cards.map((c, i) => {
            const Icon = c.icon;
            return (
              <motion.div
                key={c.title}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: i * 0.1, ease: [0.16, 1, 0.3, 1] }}
                className={`${c.col} ${c.row} group relative overflow-hidden rounded-2xl border ${
                  c.highlight
                    ? "border-[#D4A853]/15 bg-[#D4A853]/[0.03]"
                    : "border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.015)]"
                } p-7 transition-all duration-500 hover:border-[#D4A853]/25`}
              >
                {/* Hover image layer */}
                <div className="absolute inset-0 overflow-hidden opacity-0 group-hover:opacity-100 transition-all duration-700">
                  <div className="absolute inset-0 bg-gradient-to-t from-[#0A0A0B] via-[#0A0A0B]/60 to-transparent z-10" />
                  <motion.div
                    className="absolute inset-0 bg-cover bg-center"
                    style={{
                      backgroundImage: `url(https://picsum.photos/seed/${c.img}/800/600)`,
                      filter: "grayscale(0.7) contrast(1.15) brightness(0.5)",
                    }}
                    initial={{ scale: 1.05 }}
                    whileHover={{ scale: 1.1 }}
                    transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                  />
                </div>

                <div className="relative z-10 flex flex-col h-full">
                  <div className="flex items-center gap-2.5 mb-3">
                    <div
                      className={`flex items-center justify-center w-9 h-9 rounded-xl ${
                        c.highlight
                          ? "bg-[#D4A853]/15 text-[#D4A853]"
                          : "bg-white/5 text-[#787880]"
                      }`}
                    >
                      <Icon size={17} weight="bold" />
                    </div>
                    <span className="text-sm font-semibold text-[#F4F4F5]">
                      {c.title}
                    </span>
                  </div>
                  <p className="text-sm text-[#787880] leading-relaxed max-w-xs mt-auto">
                    {c.desc}
                  </p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

/* ── Scroll Feature (pinning + scrubbing) ─────────────────── */
function ScrollFeature() {
  const { ref, scrollYProgress } = useScrollProgress();
  const opacity = useTransform(scrollYProgress, [0, 0.25, 0.6, 1], [0, 1, 1, 0]);
  const scale = useTransform(scrollYProgress, [0, 0.4, 1], [0.9, 1, 0.95]);
  const count = useTransform(scrollYProgress, [0, 0.6, 1], [0, 100, 100]);

  return (
    <section id="how-it-works" ref={ref} className="relative py-32 px-6 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(212,168,83,0.03)_0%,transparent_60%)]" />
      <div className="max-w-6xl mx-auto">
        <div className="grid lg:grid-cols-2 gap-16 items-start">
          {/* Left: sticky text */}
          <div className="lg:sticky lg:top-1/4 lg:-translate-y-1/4">
            <motion.div style={{ opacity, scale }}>
              <span className="text-xs uppercase tracking-[0.2em] text-[#D4A853]/60 font-mono">
                Infrastructure
              </span>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#F4F4F5] mt-3">
                Hạ tầng{" "}
                <span className="text-[#D4A853]">tự động mở rộng</span>
              </h2>
              <p className="text-base text-[#787880] leading-relaxed mt-4 max-w-md">
                Hệ thống tự động quản lý worker Colab. Scale theo nhu cầu,
                rotation 3h45m, cooldown 1h. GPU Tesla T4 luôn sẵn sàng.
              </p>
            </motion.div>
          </div>

          {/* Right: scrollable stats */}
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: "Worker tối đa", value: "4" },
                { label: "Thời gian chạy", value: "3h45m" },
                { label: "TTS Speed", value: "5-15s" },
                { label: "GPU", value: "Tesla T4" },
              ].map((s, i) => (
                <motion.div
                  key={s.label}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: 0.3 + i * 0.08 }}
                  className="group rounded-xl border border-[rgba(255,255,255,0.06)] p-5 bg-[rgba(255,255,255,0.015)] hover:border-[#D4A853]/20 transition-all duration-500"
                >
                  <motion.div
                    className="text-3xl font-bold text-[#D4A853]"
                    whileHover={{ scale: 1.05 }}
                    transition={{ type: "spring", stiffness: 400, damping: 15 }}
                  >
                    {s.value}
                  </motion.div>
                  <div className="text-xs text-[#787880] mt-1.5 font-mono tracking-wide uppercase">
                    {s.label}
                  </div>
                </motion.div>
              ))}
            </div>

            {/* How it works steps */}
            <div className="space-y-3 mt-8">
              {[
                { step: "01", title: "Upload voice sample (5s)", desc: "Tải lên file âm thanh mẫu để AI học giọng nói." },
                { step: "02", title: "Chọn model & xử lý", desc: "Hệ thống tự động chọn worker Colab phù hợp, xử lý TTS trong 5-15 giây." },
                { step: "03", title: "Nhận kết quả", desc: "Kết quả trả về qua webhook callback hoặc download trực tiếp." },
              ].map((s, i) => (
                <motion.div
                  key={s.step}
                  initial={{ opacity: 0, x: 20 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: 0.5 + i * 0.1 }}
                  className="flex gap-4 p-4 rounded-xl border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.01)] hover:border-[rgba(255,255,255,0.08)] transition-all duration-300"
                >
                  <span className="text-xs font-mono font-bold text-[#D4A853] mt-0.5 shrink-0">
                    {s.step}
                  </span>
                  <div>
                    <div className="text-sm font-medium text-[#F4F4F5]">
                      {s.title}
                    </div>
                    <div className="text-xs text-[#787880] mt-0.5">
                      {s.desc}
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Card Stacking ─────────────────────────────────────────── */
function CardStackingSection() {
  const stacks = [
    {
      title: "Tích hợp API mạnh mẽ",
      desc: "RESTful API với JWT authentication. Gửi request TTS, quản lý voices, webhook callback. SDK hỗ trợ Python, JavaScript.",
      color: "rgba(255,255,255,0.015)",
    },
    {
      title: "Voice Clone chính xác",
      desc: "Chỉ cần 5 giây âm thanh mẫu, AI tái tạo chính xác giọng nói gốc. Hỗ trợ tiếng Việt và nhiều ngôn ngữ khác.",
      color: "rgba(255,255,255,0.025)",
    },
    {
      title: "Dashboard real-time",
      desc: "Theo dõi balance, lịch sử usage, quản lý API keys. Tự động nạp ký tự, cảnh báo khi sắp hết hạn mức.",
      color: "rgba(255,255,255,0.035)",
    },
  ];

  return (
    <section id="developers" className="py-32 px-6 relative overflow-hidden">
      <div className="max-w-5xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="mb-4"
        >
          <span className="text-xs uppercase tracking-[0.2em] text-[#D4A853]/60 font-mono">
            Developers
          </span>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-[#F4F4F5] mt-3">
            Dành cho <span className="text-[#D4A853]">nhà phát triển</span>
          </h2>
        </motion.div>

        <div className="relative mt-12">
          {stacks.map((s, i) => (
            <motion.div
              key={s.title}
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.6, delay: i * 0.12, ease: [0.16, 1, 0.3, 1] }}
              style={{
                backgroundColor: s.color,
                zIndex: stacks.length - i,
              }}
              className="relative rounded-2xl border border-[rgba(255,255,255,0.06)] p-8 mb-4 backdrop-blur-sm hover:border-[#D4A853]/20 transition-all duration-500 group"
            >
              <div className="flex items-start gap-5">
                <div className="flex items-center justify-center w-11 h-11 rounded-xl bg-[#D4A853]/10 text-[#D4A853] shrink-0 group-hover:bg-[#D4A853]/20 transition-colors duration-500">
                  {i === 0 ? (
                    <Cube size={20} weight="bold" />
                  ) : i === 1 ? (
                    <MagicWand size={20} weight="bold" />
                  ) : (
                    <GearSix size={20} weight="bold" />
                  )}
                </div>
                <div>
                  <h3 className="text-lg font-bold text-[#F4F4F5] mb-1.5">
                    {s.title}
                  </h3>
                  <p className="text-sm text-[#787880] leading-relaxed max-w-lg">
                    {s.desc}
                  </p>
                </div>
              </div>
            </motion.div>
          ))}

          {/* Stack shadows */}
          <div className="absolute -bottom-4 left-8 right-8 h-4 rounded-b-2xl border border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.01)]" />
          <div className="absolute -bottom-8 left-16 right-16 h-4 rounded-b-2xl border border-[rgba(255,255,255,0.02)] bg-[rgba(255,255,255,0.005)]" />
        </div>
      </div>
    </section>
  );
}

/* ── CTA ───────────────────────────────────────────────────── */
function CtaSection() {
  return (
    <section className="py-32 px-6 relative overflow-hidden">
      {/* Glow background */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_bottom,rgba(212,168,83,0.06)_0%,transparent_60%)]" />
      <div className="pointer-events-none absolute bottom-0 left-1/2 -translate-x-1/2 w-[500px] h-[200px] bg-[#D4A853] opacity-[0.03] blur-3xl rounded-full" />

      <div className="max-w-4xl mx-auto text-center relative">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className="text-xs uppercase tracking-[0.2em] text-[#D4A853]/60 font-mono">
            Get Started
          </span>
          <h2 className="text-4xl sm:text-5xl font-bold tracking-tight text-[#F4F4F5] leading-[1.1] mt-3">
            Sẵn sàng{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#D4A853] to-[#E8C86A]">
              dùng thử?
            </span>
          </h2>
          <p className="text-lg text-[#787880] mt-4 mb-10 max-w-lg mx-auto">
            Đăng ký tài khoản, nạp ký tự và bắt đầu tổng hợp giọng nói ngay.
            Miễn phí 10.000 ký tự cho người dùng mới.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="flex flex-wrap items-center justify-center gap-4"
        >
          <Link
            href="/signup"
            className="group inline-flex items-center gap-2.5 rounded-xl text-base font-semibold transition-all h-14 px-10 bg-[#D4A853] text-[#0A0A0B] hover:bg-[#C49A3E] active:translate-y-px shadow-lg shadow-[#D4A853]/20 hover:shadow-[#D4A853]/30"
          >
            <Rocket size={20} weight="bold" />
            Đăng ký miễn phí
            <ArrowRight
              size={18}
              className="transition-transform duration-300 group-hover:translate-x-1"
            />
          </Link>
          <Link
            href="/login"
            className="group inline-flex items-center gap-2 rounded-xl text-sm font-medium transition-all h-14 px-9 border border-[rgba(255,255,255,0.1)] text-[#F4F4F5] hover:bg-white/5 active:translate-y-px"
          >
            <PlayCircle size={18} />
            Xem demo
          </Link>
        </motion.div>
      </div>
    </section>
  );
}

/* ── Footer ────────────────────────────────────────────────── */
function FooterSection() {
  return (
    <footer className="border-t border-[rgba(255,255,255,0.06)] py-12 px-4">
      <div className="max-w-6xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-10">
          <div className="col-span-2 md:col-span-1">
            <Link href="/" className="flex items-center gap-2.5 mb-3">
              <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-[#D4A853]/10 text-[#D4A853]">
                <Waveform size={15} weight="fill" />
              </span>
              <span className="text-base font-bold text-[#F4F4F5]">
                TTS Dubbing
              </span>
            </Link>
            <p className="text-xs text-[#787880] leading-relaxed max-w-[180px]">
              Nền tảng tổng hợp giọng nói AI hàng đầu cho tiếng Việt.
            </p>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-[#F4F4F5] uppercase tracking-wider mb-3">
              Sản phẩm
            </h4>
            <div className="flex flex-col gap-2">
              <Link href="#features" className="text-xs text-[#787880] hover:text-[#F4F4F5] transition-colors">
                Tính năng
              </Link>
              <Link href="#developers" className="text-xs text-[#787880] hover:text-[#F4F4F5] transition-colors">
                API
              </Link>
              <Link href="/docs" className="text-xs text-[#787880] hover:text-[#F4F4F5] transition-colors">
                Tài liệu API
              </Link>
            </div>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-[#F4F4F5] uppercase tracking-wider mb-3">
              Tài nguyên
            </h4>
            <div className="flex flex-col gap-2">
              <Link href="/login" className="text-xs text-[#787880] hover:text-[#F4F4F5] transition-colors">
                Đăng nhập
              </Link>
              <Link href="/signup" className="text-xs text-[#787880] hover:text-[#F4F4F5] transition-colors">
                Đăng ký
              </Link>
            </div>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-[#F4F4F5] uppercase tracking-wider mb-3">
              Công nghệ
            </h4>
            <div className="flex flex-col gap-2">
              <span className="text-xs text-[#787880]">OmniVoice</span>
              <span className="text-xs text-[#787880]">Colab T4</span>
            </div>
          </div>
        </div>
        <div className="border-t border-[rgba(255,255,255,0.04)] pt-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#787880]">
          <span>TTS Dubbing &copy; {new Date().getFullYear()}</span>
          <span className="font-mono text-[10px] text-[#787880]/30">
            Built with FastAPI + OmniVoice + Colab T4
          </span>
        </div>
      </div>
    </footer>
  );
}

/* ── Page ──────────────────────────────────────────────────── */
export default function Home() {
  return (
    <div className="w-full max-w-full overflow-x-hidden bg-pitch text-vocal min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1">
        <Hero />
        <Marquee />
        <BentoGrid />
        <ScrollFeature />
        <CardStackingSection />
        <CtaSection />
      </main>
      <FooterSection />
    </div>
  );
}
