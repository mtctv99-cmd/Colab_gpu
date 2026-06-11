"use client";
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html>
      <body className="bg-zinc-950 text-zinc-100">
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="text-center max-w-md space-y-4">
            <h2 className="text-xl font-bold">Lỗi hệ thống</h2>
            <p className="text-zinc-400 text-sm">Vui lòng tải lại trang.</p>
            <button onClick={reset} className="px-4 py-2 bg-brand text-black rounded-lg text-sm font-medium">Tải lại</button>
          </div>
        </div>
      </body>
    </html>
  );
}
