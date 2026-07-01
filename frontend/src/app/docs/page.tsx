"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import Link from "next/link";

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.04, delayChildren: 0.08 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: { type: "spring" as const, stiffness: 280, damping: 22 } },
};

function Section({ id, title, desc, children }: { id?: string; title: string; desc?: string; children: React.ReactNode }) {
  return (
    <motion.section variants={itemVariants} id={id} className="scroll-mt-24">
      <h2 className="text-lg font-bold text-vocal tracking-tight mb-1">{title}</h2>
      {desc && <p className="text-sm text-echo mb-5 max-w-2xl">{desc}</p>}
      <div className="space-y-4">{children}</div>
    </motion.section>
  );
}

function CodeBlock({ code, lang = "bash" }: { code: string; lang?: string }) {
  return (
    <div className="relative group">
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity z-10">
        <button
          onClick={() => { navigator.clipboard.writeText(code); }}
          className="text-[10px] font-mono text-echo bg-strip border border-phantom px-2 py-1 rounded hover:text-vocal transition-colors"
        >
          Copy
        </button>
      </div>
      <pre className="bg-console border border-phantom rounded-lg p-4 overflow-x-auto text-xs leading-relaxed font-mono">
        <code className="text-echo">{code}</code>
      </pre>
    </div>
  );
}

export default function DocsPage() {
  const [origin, setOrigin] = useState("");
  useEffect(() => {
    const defaultOrigin = window.location.origin;
    setOrigin(defaultOrigin);
    fetch("/api/config")
      .then(r => r.json())
      .then(cfg => {
        if (cfg.public_url && cfg.public_url.includes("trycloudflare.com")) {
          setOrigin(cfg.public_url);
        }
      })
      .catch(() => {});
  }, []);

  const API = `${origin}/api`;
  const baseUrlBlock = origin || "https://api.ttsdubbing.com";

  return (
    <div className="min-h-screen bg-pitch">
      <nav className="sticky top-0 z-50 border-b border-phantom bg-pitch/90 backdrop-blur-xl">
        <div className="max-w-5xl mx-auto flex items-center justify-between h-14 px-6">
          <Link href="/" className="font-bold text-sm text-vocal tracking-tight">TTS Dubbing</Link>
          <div className="flex items-center gap-4">
            <Link href="/" className="text-xs text-echo hover:text-vocal transition-colors">Trang chủ</Link>
            <Link href="/login" className="text-xs text-echo hover:text-vocal transition-colors">Đăng nhập</Link>
            <Link
              href="/signup"
              className="text-xs font-semibold bg-signal text-pitch px-3 py-1.5 rounded-lg hover:bg-signal-dark transition-colors"
            >
              Bắt đầu
            </Link>
          </div>
        </div>
      </nav>

      <div className="max-w-5xl mx-auto px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className="text-xs uppercase tracking-[0.2em] text-signal/60 font-mono">API Reference</span>
          <h1 className="text-3xl font-bold tracking-tight text-vocal mt-2 mb-2">Tài liệu API</h1>
          <p className="text-sm text-echo max-w-2xl">
            Hướng dẫn tích hợp API TTS Dubbing vào ứng dụng của bạn.
          </p>
        </motion.div>

        <div className="flex gap-12 mt-12">
          <aside className="hidden lg:block w-52 shrink-0">
            <nav className="sticky top-24 space-y-1">
              {[
                { id: "quickstart", label: "Quickstart" },
                { id: "base-url", label: "Base URL" },
                { id: "auth", label: "Xác thực" },
                { id: "voices", label: "Danh sách giọng đọc" },
                { id: "tts-text", label: "TTS — văn bản" },
                { id: "tts-batch", label: "TTS — batch" },
                { id: "webhook", label: "Webhook callback" },
                { id: "admin", label: "Admin endpoints" },
                { id: "errors", label: "Mã lỗi" },
              ].map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className="block text-xs text-echo hover:text-vocal transition-colors py-1.5 border-l-2 border-transparent hover:border-signal pl-3"
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>

          <motion.div
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            className="flex-1 min-w-0 space-y-14"
          >
            {/* ── Quickstart ── */}
            <Section id="quickstart" title="Quickstart" desc="Tạo giọng nói AI chỉ với 3 bước:">
              <div className="space-y-6">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-signal/20 text-signal text-xs font-bold">1</span>
                    <h3 className="text-sm font-medium text-vocal">Đăng ký tài khoản</h3>
                  </div>
                  <p className="text-xs text-echo mb-2 ml-8">Truy cập <Link href="/signup" className="text-signal hover:underline">/signup</Link>, tạo tài khoản. Bạn nhận ngay 10.000 ký tự miễn phí.</p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-signal/20 text-signal text-xs font-bold">2</span>
                    <h3 className="text-sm font-medium text-vocal">Lấy API key</h3>
                  </div>
                  <p className="text-xs text-echo mb-2 ml-8">Sau khi đăng nhập, vào Dashboard &gt; API Keys, tạo key mới.</p>
                </div>
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-signal/20 text-signal text-xs font-bold">3</span>
                    <h3 className="text-sm font-medium text-vocal">Gửi request TTS đầu tiên</h3>
                  </div>
                  <p className="text-xs text-echo mb-2 ml-8">Copy API key, chạy lệnh curl sau:</p>
                  <div className="ml-8">
                    <CodeBlock code={`curl -X POST ${API}/tts/text \\
  -H "Authorization: Bearer <API_KEY_CUA_BAN>" \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Xin chào thế giới", "voice_id": 1}' \\
  --output output.wav`} />
                  </div>
                  <p className="text-xs text-echo mt-2 ml-8">File <code className="text-vocal font-mono">output.wav</code> chứa giọng nói tổng hợp.</p>
                </div>
              </div>
            </Section>

            {/* ── Base URL ── */}
            <Section id="base-url" title="Base URL">
              <p className="text-xs text-echo mb-2">Server của bạn đang chạy tại:</p>
              <CodeBlock code={baseUrlBlock} />
              <p className="text-xs text-echo mt-1">Ghép với <code className="text-vocal font-mono">/api</code> để có base URL cho tất cả endpoints:</p>
              <CodeBlock code={`${API}`} />
              <p className="text-xs text-echo mt-3">Ví dụ full URL:</p>
              <CodeBlock code={`${API}/tts/text`} />
            </Section>

            {/* ── Auth ── */}
            <Section id="auth" title="Xác thực (Authentication)">
              <p className="text-xs text-echo mb-4">Hai cách xác thực. Chọn 1 trong 2:</p>
              <div className="border border-phantom rounded-lg divide-y divide-phantom">
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Cách 1: JWT Token</h3>
                  <p className="text-xs text-echo mb-2">Gọi login để lấy token, sau đó gắn vào header.</p>
                  <p className="text-xs text-echo mb-2">Login:</p>
                  <CodeBlock code={`curl -X POST ${API}/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"email": "user@example.com", "password": "matkhau123"}'`} />
                  <p className="text-xs text-echo mt-2 mb-2">Response (chứa token):</p>
                  <CodeBlock lang="json" code={`{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {"id": 1, "email": "user@example.com", "role": "user", "balance": 10000}
}`} />
                  <p className="text-xs text-echo mt-2">Dùng token trong request:</p>
                  <CodeBlock code={`curl -X POST ${API}/tts/text \\
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Xin chào", "voice_id": 1}' \\
  --output output.wav`} />
                  <p className="text-xs text-echo mt-2">Token hết hạn sau <span className="text-vocal font-mono">7 ngày</span>.</p>
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Cách 2: API Key (khuyên dùng)</h3>
                  <p className="text-xs text-echo mb-2">Tạo API key trong Dashboard &gt; API Keys. Gửi key trong header Authorization.</p>
                  <CodeBlock code={`curl -X POST ${API}/tts/text \\
  -H "Authorization: Bearer tts_abc123xyz..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Xin chào thế giới", "voice_id": 1}' \\
  --output output.wav`} />
                  <p className="text-xs text-echo mt-2">API key <span className="text-alert font-mono">không có hạn</span>, có thể thu hồi bất kỳ lúc nào.</p>
                </div>
              </div>
            </Section>

            {/* ── Voices ── */}
            <Section id="voices" title="Danh sách giọng đọc (Voices)">
              <p className="text-xs text-echo mb-3">Endpoints <span className="text-online">public</span>, không cần auth.</p>
              <CodeBlock code={`# Lấy tất cả voices
curl ${API}/voices/

# Chi tiết 1 voice
curl ${API}/voices/1

# Tải file audio mẫu
curl ${API}/voices/1/audio --output voice_sample.wav`} />
              <p className="text-xs text-echo mt-3 mb-2">Response:</p>
              <CodeBlock lang="json" code={`[
  {
    "id": 1,
    "name": "Ngọc Huyền",
    "audio_url": "/api/voices/1/audio",
    "transcript": "Xin chào, tôi là giọng đọc Ngọc Huyền.",
    "language": "vi"
  }
]`} />
              <p className="text-xs text-echo mt-1">Lấy <code className="text-vocal font-mono">id</code> của voice muốn dùng, truyền vào request TTS.</p>
            </Section>

            {/* ── TTS Text ── */}
            <Section id="tts-text" title="TTS — Chuyển văn bản thành giọng nói">
              <p className="text-xs text-echo mb-3"><span className="text-alert">Yêu cầu auth</span> (JWT hoặc API key).</p>
              <div className="border border-phantom rounded-lg divide-y divide-phantom">
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Request</h3>
                  <p className="text-xs text-echo mb-2">
                    <span className="inline-block bg-signal/20 text-signal font-mono text-[10px] px-1.5 py-0.5 rounded mr-1">POST</span>
                    <code className="text-vocal font-mono text-xs">{API}/tts/text</code>
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-xs mb-3 border border-phantom rounded overflow-hidden">
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Trường</div>
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Kiểu</div>
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Bắt buộc</div>
                    <div className="px-3 py-1.5 text-signal font-mono">text</div>
                    <div className="px-3 py-1.5 text-echo font-mono">string</div>
                    <div className="px-3 py-1.5 text-alert">Có</div>
                    <div className="px-3 py-1.5 text-signal font-mono">voice_id</div>
                    <div className="px-3 py-1.5 text-echo font-mono">int</div>
                    <div className="px-3 py-1.5 text-alert">Có</div>
                    <div className="px-3 py-1.5 text-signal font-mono">language</div>
                    <div className="px-3 py-1.5 text-echo font-mono">string</div>
                    <div className="px-3 py-1.5 text-dimmer">Không</div>
                  </div>
                  <div className="text-xs text-echo space-y-1 mb-3">
                    <p><span className="text-signal font-mono">text</span>: Văn bản cần chuyển đổi (tối đa 2000 từ)</p>
                    <p><span className="text-signal font-mono">voice_id</span>: ID của giọng đọc</p>
                    <p><span className="text-signal font-mono">language</span>: (tùy chọn) Mã ngôn ngữ, vd <code className="text-vocal font-mono">"vi"</code></p>
                  </div>
                  <p className="text-xs text-echo mb-1">Ví dụ request body:</p>
                  <CodeBlock lang="json" code={`{
  "text": "Xin chào, tôi là giọng nói tổng hợp từ AI.",
  "voice_id": 1
}`} />
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Ví dụ đầy đủ</h3>
                  <p className="text-xs text-echo mb-1">curl:</p>
                  <CodeBlock code={`# Dùng API key
curl -X POST ${API}/tts/text \\
  -H "Authorization: Bearer tts_abc123xyz..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Xin chào thế giới", "voice_id": 1}' \\
  --output output.wav

# Dùng JWT token
curl -X POST ${API}/tts/text \\
  -H "Authorization: Bearer eyJhbGciOiJI..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Xin chào thế giới", "voice_id": 1}' \\
  --output output.wav`} />
                  <p className="text-xs text-echo mt-3 mb-1">Python (requests):</p>
                  <CodeBlock lang="python" code={`import requests

API_KEY = "tts_abc123xyz..."
API = "${API}"

resp = requests.post(
    f"{API}/tts/text",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    json={"text": "Xin chào thế giới", "voice_id": 1},
)

with open("output.wav", "wb") as f:
    f.write(resp.content)

print("OK — file output.wav đã được tạo")`} />
                  <p className="text-xs text-echo mt-3 mb-1">JavaScript (fetch):</p>
                  <CodeBlock lang="javascript" code={`const API_KEY = "tts_abc123xyz...";
const API = "${API}";

const resp = await fetch(\`\${API}/tts/text\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ text: "Xin chào thế giới", voice_id: 1 }),
});

const blob = await resp.blob();
const audioUrl = URL.createObjectURL(blob);`} />
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Response</h3>
                  <p className="text-xs text-echo">
                    Thành công: HTTP <code className="text-online font-mono">200</code> — file audio WAV.<br />
                    Lỗi: HTTP <code className="text-alert font-mono">402</code> (hết balance), <code className="text-alert font-mono">429</code> (quá 1 concurrent).
                  </p>
                </div>
              </div>
            </Section>

            {/* ── TTS Batch ── */}
            <Section id="tts-batch" title="TTS — Xử lý hàng loạt (Batch)">
              <p className="text-xs text-echo mb-3">Gửi nhiều văn bản cùng lúc, xử lý bất đồng bộ. Có webhook callback.</p>
              <div className="border border-phantom rounded-lg divide-y divide-phantom">
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Request</h3>
                  <p className="text-xs text-echo mb-2">
                    <span className="inline-block bg-signal/20 text-signal font-mono text-[10px] px-1.5 py-0.5 rounded mr-1">POST</span>
                    <code className="text-vocal font-mono text-xs">{API}/tts/batch</code>
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-xs mb-3 border border-phantom rounded overflow-hidden">
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Trường</div>
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Kiểu</div>
                    <div className="col-span-1 bg-strip/50 px-3 py-1.5 text-echo font-medium">Bắt buộc</div>
                    <div className="px-3 py-1.5 text-signal font-mono">voice_id</div>
                    <div className="px-3 py-1.5 text-echo font-mono">int</div>
                    <div className="px-3 py-1.5 text-alert">Có</div>
                    <div className="px-3 py-1.5 text-signal font-mono">texts</div>
                    <div className="px-3 py-1.5 text-echo font-mono">string[]</div>
                    <div className="px-3 py-1.5 text-alert">Có</div>
                    <div className="px-3 py-1.5 text-signal font-mono">batch</div>
                    <div className="px-3 py-1.5 text-echo font-mono">true</div>
                    <div className="px-3 py-1.5 text-alert">Có</div>
                    <div className="px-3 py-1.5 text-signal font-mono">language</div>
                    <div className="px-3 py-1.5 text-echo font-mono">string</div>
                    <div className="px-3 py-1.5 text-dimmer">Không</div>
                    <div className="px-3 py-1.5 text-signal font-mono">webhook_url</div>
                    <div className="px-3 py-1.5 text-echo font-mono">string</div>
                    <div className="px-3 py-1.5 text-dimmer">Không</div>
                  </div>
                  <p className="text-xs text-echo mb-1">Ví dụ:</p>
                  <CodeBlock code={`curl -X POST ${API}/tts/batch \\
  -H "Authorization: Bearer tts_abc123xyz..." \\
  -H "Content-Type: application/json" \\
  -d '{
    "voice_id": 1,
    "texts": ["Xin chào", "Tạm biệt", "Bạn khỏe không?"],
    "batch": true,
    "webhook_url": "https://webhook.site/abc-xyz"
  }'`} />
                </div>
                <div className="p-4">
                  <h3 className="text-sm font-medium text-vocal mb-2">Response</h3>
                  <p className="text-xs text-echo mb-1">Trả về ngay danh sách task IDs:</p>
                  <CodeBlock lang="json" code={`{
  "batch": true,
  "voice_id": 1,
  "tasks": [
    {"text": "Xin chào", "task_id": "uuid-1", "status": "PENDING"},
    {"text": "Tạm biệt", "task_id": "uuid-2", "status": "PENDING"},
    {"text": "Bạn khỏe không?", "task_id": "uuid-3", "status": "PENDING"}
  ]
}`} />
                  <p className="text-xs text-echo mt-2">Tra cứu trạng thái từng task:</p>
                  <CodeBlock code={`# Kiểm tra trạng thái
curl ${API}/tasks/uuid-1

# Download audio khi hoàn thành
curl ${API}/tasks/uuid-1/audio --output result.wav`} />
                </div>
              </div>
            </Section>

            {/* ── Webhook ── */}
            <Section id="webhook" title="Webhook Callback">
              <p className="text-xs text-echo mb-3">
                Khi tất cả tasks trong batch hoàn thành, hệ thống gửi POST đến <code className="text-vocal font-mono">webhook_url</code>.
              </p>
              <p className="text-xs text-echo mb-2">Payload gửi đến webhook:</p>
              <CodeBlock lang="json" code={`{
  "batch_id": "batch-uuid",
  "voice_id": 1,
  "status": "COMPLETED",
  "tasks": [
    {
      "task_id": "uuid-1",
      "text": "Xin chào",
      "status": "COMPLETED",
      "audio_url": "/api/tasks/uuid-1/audio"
    },
    {
      "task_id": "uuid-2",
      "text": "Tạm biệt",
      "status": "FAILED",
      "error_message": "Out of balance"
    }
  ]
}`} />
              <p className="text-xs text-echo mt-2">Webhook cần trả về HTTP <code className="text-online font-mono">200</code> để xác nhận.</p>
            </Section>

            {/* ── Admin ── */}
            <Section id="admin" title="Admin endpoints">
              <p className="text-xs text-echo mb-3">Yêu cầu role <code className="text-vocal font-mono">admin</code>.</p>
              <div className="border border-phantom rounded-lg divide-y divide-phantom">
                {[
                  { m: "GET", p: "/auth/admin/users", d: "Danh sách users" },
                  { m: "POST", p: "/auth/admin/users", d: "Tạo user. Body: {email, password, role?}" },
                  { m: "PUT", p: "/auth/admin/users/{id}", d: "Cập nhật user" },
                  { m: "DELETE", p: "/auth/admin/users/{id}", d: "Xoá user" },
                  { m: "POST", p: "/auth/admin/topup", d: "Nạp ký tự. Body: {email, amount}" },
                  { m: "GET", p: "/auth/admin/api-keys", d: "DS tất cả API keys" },
                  { m: "POST", p: "/auth/admin/api-keys", d: "Tạo key cho user" },
                  { m: "PATCH", p: "/auth/admin/api-keys/{id}", d: "Cập nhật key" },
                  { m: "DELETE", p: "/auth/admin/api-keys/{id}", d: "Xoá key" },
                  { m: "GET", p: "/auth/admin/api-keys/{id}/usage", d: "Usage của key" },
                ].map((ep) => {
                  const c =
                    ep.m === "GET" ? "text-online" :
                    ep.m === "POST" ? "text-signal" :
                    ep.m === "DELETE" ? "text-alert" :
                    "text-[#60A5FA]";
                  return (
                    <div key={ep.p} className="flex items-start gap-3 px-4 py-2.5">
                      <span className={`font-mono text-[10px] font-bold leading-5 shrink-0 ${c}`}>{ep.m}</span>
                      <div>
                        <code className="text-xs text-vocal font-mono">{ep.p}</code>
                        <p className="text-[11px] text-echo mt-0.5">{ep.d}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-4">
                <p className="text-xs text-echo mb-2">Ví dụ tạo user + nạp ký tự:</p>
                <CodeBlock code={`# Tạo user
curl -X POST ${API}/auth/admin/users \\
  -H "Authorization: Bearer eyJhbGciOiJI..." \\
  -H "Content-Type: application/json" \\
  -d '{"email": "newuser@example.com", "password": "abc123"}'

# Nạp ký tự
curl -X POST ${API}/auth/admin/topup \\
  -H "Authorization: Bearer eyJhbGciOiJI..." \\
  -H "Content-Type: application/json" \\
  -d '{"email": "user@example.com", "amount": 50000}'`} />
              </div>
            </Section>

            {/* ── Errors ── */}
            <Section id="errors" title="Mã lỗi (Error Codes)">
              <div className="border border-phantom rounded-lg divide-y divide-phantom">
                {[
                  { c: "400", d: "Dữ liệu không hợp lệ. Thiếu field, sai định dạng, email đã tồn tại." },
                  { c: "401", d: "Token/API key không hợp lệ hoặc hết hạn." },
                  { c: "402", d: "Không đủ balance. Nạp thêm ký tự." },
                  { c: "403", d: "Không có quyền. Admin endpoint nhưng user thường gọi." },
                  { c: "404", d: "Voice/task/key không tồn tại." },
                  { c: "429", d: "Quá nhiều request. TTS: 1 concurrent. Auth: 5 lần/5 phút." },
                  { c: "500", d: "Lỗi server nội bộ." },
                  { c: "504", d: "TTS timeout quá 120 giây." },
                ].map((e) => (
                  <div key={e.c} className="flex items-start gap-4 px-4 py-2.5">
                    <span className="font-mono text-sm font-bold text-alert shrink-0 w-10">{e.c}</span>
                    <p className="text-xs text-echo">{e.d}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-echo mt-3 mb-1">Format response lỗi:</p>
              <CodeBlock lang="json" code={`{
  "detail": "Insufficient balance",
  "error_code": "INSUFFICIENT_BALANCE"
}`} />
            </Section>
          </motion.div>
        </div>
      </div>

      <footer className="border-t border-phantom py-8 px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between text-xs text-echo">
          <span>TTS Dubbing &copy; {new Date().getFullYear()}</span>
          <Link href="/" className="hover:text-vocal transition-colors">Trang chủ</Link>
        </div>
      </footer>
    </div>
  );
}
