"use client";
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 text-zinc-100 p-8">
      <div className="text-center max-w-md space-y-4">
        <div className="w-16 h-16 mx-auto rounded-2xl bg-red-950/50 border border-red-900 flex items-center justify-center">
          <span className="text-red-400 text-2xl font-bold">!</span>
        </div>
        <h2 className="text-xl font-bold">Có lỗi xảy ra</h2>
        <p className="text-zinc-400 text-sm">{error.message || "Đã có lỗi không mong muốn. Vui lòng thử lại."}</p>
        <div className="flex gap-3 justify-center pt-2">
          <button onClick={() => window.location.href = "/"} className="px-4 py-2 bg-zinc-800 text-zinc-300 rounded-lg text-sm hover:bg-zinc-700">Về trang chủ</button>
          <button onClick={reset} className="px-4 py-2 bg-brand text-black rounded-lg text-sm font-medium hover:bg-emerald-400">Thử lại</button>
        </div>
      </div>
    </div>
  );
}
