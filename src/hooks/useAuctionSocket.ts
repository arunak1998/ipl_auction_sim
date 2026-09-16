import { useEffect, useRef, useState, useCallback } from 'react';

export interface SocketMessage<T = unknown> {
  type: string;
  payload: T;
}

export type ConnectionStatus = 'CONNECTING' | 'OPEN' | 'CLOSED';

const BACKEND_WS_URL = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/auction';

// Step 1: connection plumbing only. No auction event handling wired in yet.
export function useAuctionSocket() {
  const [status, setStatus] = useState<ConnectionStatus>('CONNECTING');
  const [lastMessage, setLastMessage] = useState<SocketMessage | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const socket = new WebSocket(BACKEND_WS_URL);
    socketRef.current = socket;

    socket.onopen = () => setStatus('OPEN');
    socket.onclose = () => setStatus('CLOSED');
    socket.onmessage = (event) => setLastMessage(JSON.parse(event.data));

    return () => socket.close();
  }, []);

  const sendMessage = useCallback((type: string, payload: unknown) => {
    socketRef.current?.send(JSON.stringify({ type, payload }));
  }, []);

  return { status, lastMessage, sendMessage };
}
