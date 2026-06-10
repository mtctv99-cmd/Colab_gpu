import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8001/api/:path*",
      },
      {
        source: "/ws/:path*",
        destination: "http://localhost:8001/ws/:path*",
      },
      {
        source: "/admin",
        destination: "http://localhost:8001/admin/",
      },
      {
        source: "/admin/:path*",
        destination: "http://localhost:8001/admin/:path*",
      },
      {
        source: "/style.css",
        destination: "http://localhost:8001/style.css",
      },
      {
        source: "/app.js",
        destination: "http://localhost:8001/app.js",
      },
    ];
  },
};

export default nextConfig;
