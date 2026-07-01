import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TTS Dubbing — AI Voice Dubbing",
  description: "Chuyển văn bản thành giọng nói AI chất lượng cao. Hỗ trợ tiếng Việt, nhân bản giọng nói, API cho ứng dụng.",
  openGraph: {
    title: "TTS Dubbing — AI Voice Dubbing",
    description: "Tạo giọng nói AI chất lượng cao từ văn bản. Hỗ trợ tiếng Việt.",
    type: "website",
    siteName: "TTS Dubbing",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi" className={`dark ${geistSans.variable} ${geistMono.variable}`}>
      <head>
        <meta httpEquiv="Content-Security-Policy"
          content="default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self' ws: wss: http://localhost:8090 http://host.docker.internal:8090; media-src 'self' blob: data:; img-src 'self' data: https://picsum.photos https://*.picsum.photos;" />
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='28' font-size='28'>🎙️</text></svg>" />
      </head>
      <body className="min-h-screen bg-pitch text-vocal font-sans antialiased">
        {children}
        <Toaster richColors closeButton position="top-right" />
      </body>
    </html>
  );
}
