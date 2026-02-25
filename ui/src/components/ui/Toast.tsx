"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

type ToastLevel = "info" | "success" | "error";
interface ToastItem { id: number; message: string; level: ToastLevel; }
interface ToastContextValue { toast: (message: string, level?: ToastLevel) => void; }

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

const LEVEL_CLS: Record<ToastLevel, string> = {
  info:    "bg-muted border-border text-foreground",
  success: "bg-green-900/80 border-green-700 text-green-200",
  error:   "bg-red-900/80 border-red-700 text-red-200",
};

let _nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const t = timers.current.get(id);
    if (t) { clearTimeout(t); timers.current.delete(id); }
  }, []);

  const toast = useCallback((message: string, level: ToastLevel = "info") => {
    const id = ++_nextId;
    setToasts((prev) => [...prev.slice(-4), { id, message, level }]);
    const t = setTimeout(() => dismiss(id), 3500);
    timers.current.set(id, t);
  }, [dismiss]);

  useEffect(() => {
    const ts = timers.current;
    return () => { ts.forEach(clearTimeout); };
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex max-w-xs items-start gap-2 rounded-lg border px-3 py-2 text-xs shadow-lg ${LEVEL_CLS[t.level]}`}
          >
            <span className="flex-1">{t.message}</span>
            <button onClick={() => dismiss(t.id)} className="shrink-0 opacity-60 hover:opacity-100">✕</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
