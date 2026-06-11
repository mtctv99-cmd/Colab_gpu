export async function api(path: string, opts: RequestInit = {}) {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const headers: HeadersInit = { ...opts.headers };

  if (!("Content-Type" in headers) && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(path, { ...opts, headers });

  if (res.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/login";
    throw new Error("Phiên đăng nhập hết hạn");
  }

  const isJson = res.headers.get("content-type")?.includes("application/json");
  const isAudio = res.headers.get("content-type")?.includes("audio/");

  if (!res.ok) {
    let errorMsg = `HTTP ${res.status}`;
    if (isJson) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 402) {
        errorMsg = "Không đủ ký tự!";
      } else {
        errorMsg = err.message || err.detail || errorMsg;
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
