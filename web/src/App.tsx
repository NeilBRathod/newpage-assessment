import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "./api";

/**
 * Phase 1 placeholder. The real three-pane application arrives in phase 5;
 * for now this exists to prove the container, the API and the browser are
 * actually talking to each other, and to surface the health report — which is
 * the fastest way to spot a missing model or a truncated context window.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-10 font-sans">
      <h1 className="text-2xl font-semibold tracking-tight">
        Meeting Intelligence
      </h1>
      <p className="mt-1 text-sm text-neutral-400">
        Scaffold running. The application UI lands in phase 5.
      </p>

      <section className="mt-8 max-w-2xl">
        <h2 className="text-xs uppercase tracking-widest text-neutral-500">
          System health
        </h2>

        {error && (
          <p className="mt-3 text-sm text-red-400">API unreachable: {error}</p>
        )}

        {health && (
          <ul className="mt-3 divide-y divide-neutral-800 border border-neutral-800 rounded-lg">
            {Object.entries(health.checks).map(([name, check]) => (
              <li key={name} className="flex gap-3 p-3 text-sm">
                <span aria-hidden className={check.ok ? "text-emerald-400" : "text-red-400"}>
                  {check.ok ? "●" : "●"}
                </span>
                <span className="w-36 shrink-0 text-neutral-300">{name}</span>
                <span className="text-neutral-500">{check.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
