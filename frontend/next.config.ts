import type { NextConfig } from "next";

const API_HOST = process.env.API_HOST || "localhost";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://${API_HOST}:8090/api/:path*`,
      },
      {
        source: "/v1/:path*",
        destination: `http://${API_HOST}:8090/v1/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `http://${API_HOST}:8090/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
