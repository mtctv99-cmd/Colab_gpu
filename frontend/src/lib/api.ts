export async function api(path: string, opts: RequestInit = {}) {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: Record<string, string> = { ...opts.headers as Record<string, string> };

  if (!("Content-Type" in headers) && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, { ...opts, headers });

  if (res.status === 401 && typeof window !== "undefined") {
    // Ensure we don't end up in an infinite redirect loop if login itself fails
    if (window.location.pathname !== "/login") {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      window.location.href = "/login?expired=true";
    }
    throw new Error("Phiên đăng nhập hết hạn");
  }

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const isAudio = res.headers.get("content-type")?.includes("audio/");

  if (!res.ok) {
    let errorMsg = `HTTP ${res.status}`;
    if (isJson) {
      const err = await res.json().catch(() => ({}));
      const msg = err.message || err.detail || "";
      if (res.status === 402) {
        errorMsg = msg || "Không đủ ký tự!";
      } else if (res.status === 429) {
        errorMsg = msg || "Quá nhiều yêu cầu. Thử lại sau.";
      } else if (res.status === 403) {
        errorMsg = msg || "Không có quyền truy cập.";
      } else if (res.status === 500) {
        errorMsg = msg || "Lỗi server nội bộ.";
      } else {
        errorMsg = msg || errorMsg;
      }
    }
    throw new Error(errorMsg);
  }

  if (isAudio) {
    return res.blob();
  }

  if (isJson) {
    return res.json();
  }

  return res;
}
