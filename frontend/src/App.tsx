/**
 * P0 shell. Screens arrive in P10; this exists so the styled page and the theme
 * tokens are verifiable from the first phase rather than at the end.
 */
export default function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-3 px-6">
      <p className="text-xs uppercase tracking-widest text-ink-muted">Insight Copilot</p>
      <h1 className="text-3xl font-semibold text-ink">KPI intelligence-to-action engine</h1>
      <p className="text-ink-secondary">
        Statistics decide; the model narrates. Scaffold ready — screens land in phase P10.
      </p>
      <p className="text-xs text-ink-muted">All data in this application is simulated.</p>
    </main>
  );
}
