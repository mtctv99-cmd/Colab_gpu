"use client";
import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, LogOut, BookOpen } from "lucide-react";

const navItems = [
  { label: "Tổng quan", path: "/admin" },
  { label: "Tài khoản", path: "/admin/accounts" },
  { label: "Workers", path: "/admin/workers" },
  { label: "Tác vụ", path: "/admin/tasks" },
  { label: "Giọng nói", path: "/admin/voices" },
  { label: "Người dùng", path: "/admin/users" },
  { label: "API Keys", path: "/admin/apikeys" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const token = localStorage.getItem("token");
    const userStr = localStorage.getItem("user");

    if (!token || !userStr) {
      router.push("/login");
      return;
    }

    try {
      const user = JSON.parse(userStr);
      if (user.role !== "admin") {
        router.push("/dashboard");
      }
    } catch {
      router.push("/login");
    }
  }, [router]);

  return (
    <div className="flex h-screen bg-pitch">
      <aside className="w-56 bg-console border-r border-phantom flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-phantom">
          <Link href="/admin" className="font-bold text-lg text-vocal tracking-tight">
            TTS Dubbing
          </Link>
        </div>

        <nav className="flex-1 py-3">
          {navItems.map((item) => {
            const active = pathname === item.path;
            return (
              <Link
                key={item.path}
                href={item.path}
                className={`flex items-center h-9 px-5 text-sm transition-colors ${
                  active
                    ? "border-l-2 border-signal text-vocal bg-strip/50"
                    : "border-l-2 border-transparent text-echo hover:text-vocal hover:bg-strip"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-phantom py-2">
          <Link
            href="/docs"
            className="flex items-center h-9 px-5 text-sm text-echo hover:text-vocal hover:bg-strip transition-colors"
          >
            <BookOpen className="w-3.5 h-3.5 mr-2 shrink-0" />
            Tài liệu API
          </Link>
          <Link
            href="/dashboard"
            className="flex items-center h-9 px-5 text-sm text-echo hover:text-vocal hover:bg-strip transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5 mr-2 shrink-0" />
            Về Dashboard
          </Link>
          <button
            onClick={() => { localStorage.clear(); router.push("/"); }}
            className="flex items-center h-9 px-5 text-sm text-echo hover:text-alert hover:bg-strip transition-colors w-full"
          >
            <LogOut className="w-3.5 h-3.5 mr-2 shrink-0" />
            Đăng xuất
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <div className="p-8 max-w-6xl">{children}</div>
      </main>
    </div>
  );
}
