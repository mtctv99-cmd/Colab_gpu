"use client";

import { useEffect, useState, useRef } from "react";

interface DashboardMessage {
  type: string;
  data: any;
  [key: string]: any;
}

export function useDashboardWs() {
  const [lastMessage, setLastMessage] = useState<DashboardMessage | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    let isMounted = true;

    const connect = () => {
      // Determine WS URL based on current origin or fallback to localhost:8001
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      // Use the same host:port as the current page — works for both
      // localhost dev, Docker frontend→backend, and production
      let wsHost = window.location.host;
      if (window.location.port === "3000") {
        wsHost = "localhost:8090";
      } else if (window.location.port === "3355") {
        // Docker: frontend on 3355, backend on 8090 — use backend port
        wsHost = "localhost:8090";
      }
      const wsUrl = `${protocol}//${wsHost}/ws/dashboard`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // Keepalive ping setup for frontend
      let pingInterval: NodeJS.Timeout;

      ws.onopen = () => {
        if (!isMounted) return;
        setIsConnected(true);
        console.log("[DashboardWS] Connected");
        
        // Send a ping every 30 seconds
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === "pong") return; // Ignore heartbeat responses
          setLastMessage(data);
        } catch (err) {
          console.error("[DashboardWS] Parse error", err);
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setIsConnected(false);
        if (pingInterval) clearInterval(pingInterval);
        console.log("[DashboardWS] Disconnected. Reconnecting in 5s...");
        reconnectTimeoutRef.current = setTimeout(connect, 5000);
      };

      ws.onerror = (error) => {
        console.error("[DashboardWS] Error", error);
        ws.close(); // Force close to trigger reconnect
      };
    };

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return { lastMessage, isConnected };
}
