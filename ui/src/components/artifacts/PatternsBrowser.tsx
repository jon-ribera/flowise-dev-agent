"use client";
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { PatternSummary } from "@/lib/types";

export function PatternsBrowser() {
  const [patterns, setPatterns] = useState<PatternSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");

  // Debounce search input 300ms
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  const load = useCallback((q?: string) => {
    setLoading(true);
    api
      .listPatterns(q || undefined)
      .then(setPatterns)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load(debounced);
  }, [debounced, load]);

  return (
    <div className="space-y-3">
      <input
        type="search"
        placeholder="Search patterns…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      />

      {loading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
      {!loading && !error && patterns.length === 0 && (
        <p className="text-xs text-muted-foreground">No patterns saved yet.</p>
      )}

      {patterns.map((p) => (
        <div key={p.id} className="rounded-md border border-border p-3 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold">{p.name}</span>
            {p.success_count > 0 && (
              <span className="shrink-0 rounded bg-green-600/20 px-1.5 py-0.5 text-[10px] text-green-400">
                ✓ {p.success_count}
              </span>
            )}
          </div>
          {p.description && (
            <p className="text-[11px] text-muted-foreground leading-snug">{p.description}</p>
          )}
          {p.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {p.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          {p.category && (
            <p className="text-[10px] text-muted-foreground capitalize">{p.category}</p>
          )}
        </div>
      ))}
    </div>
  );
}
