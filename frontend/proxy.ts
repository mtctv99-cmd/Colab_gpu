import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;

  // Proxy API and WebSocket requests to FastAPI backend
  if (pathname.startsWith("/api/") || pathname.startsWith("/ws/")) {
    return NextResponse.rewrite(
      new URL(`http://localhost:8001${pathname}${search}`, request.url)
    );
  }
}

export const config = {
  matcher: ["/api/:path*", "/ws/:path*"],
};
