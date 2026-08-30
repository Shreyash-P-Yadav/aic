/**
 * The shell: a sticky top bar carrying the role switcher, the persona, the theme
 * toggle and a persistent simulated-clock readout.
 *
 * The role switcher is in the top bar because it **is** the entitlement demonstration:
 * changing it calls the API, which changes what the contract compiler returns on the
 * next query. What the reader sees change is data, not a label.
 */

import { NavLink, Outlet } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { useUi } from '@/lib/store';

const SCREENS = [
  { to: '/', label: 'Feed', end: true },
  { to: '/ask', label: 'Ask' },
  { to: '/actions', label: 'Actions' },
  { to: '/data', label: 'Data & sources' },
  { to: '/trust', label: 'Trust' },
  { to: '/telemetry', label: 'Telemetry' },
  { to: '/admin', label: 'Admin' },
  { to: '/audit', label: 'Audit' },
];

const PERSONAS = ['cfo', 'analyst', 'rsm', 'marketing_lead'];

export function Layout() {
  const { theme, toggleTheme, persona, setPersona, showProvenance, toggleProvenance } = useUi();
  const client = useQueryClient();
  const roles = useQuery({ queryKey: ['roles'], queryFn: ({ signal }) => api.roles(signal) });
  const session = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => api.session(signal) });

  return (
    <div className="min-h-screen bg-page">
      <header className="sticky top-0 z-20 border-b border-hairline-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <span className="text-sm font-semibold text-ink">Insight Copilot</span>
          <nav className="order-3 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto">
            {SCREENS.map((screen) => (
              <NavLink
                key={screen.to}
                to={screen.to}
                end={screen.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded px-2.5 py-1 text-xs transition ${
                    isActive ? 'bg-page text-ink' : 'text-ink-secondary hover:text-ink'
                  }`
                }
              >
                {screen.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <label className="sr-only" htmlFor="role">
              Role
            </label>
            <select
              id="role"
              aria-label="Role"
              className="rounded border border-hairline-border bg-card px-2 py-1 text-xs text-ink"
              value={session.data?.role ?? 'analyst'}
              onChange={(event) => {
                // Fire-and-forget with an explicit void: the select is a control, not
                // a form, and eslint is right that an async handler here would swallow
                // a rejection where nobody would see it.
                void api
                  .setRole(event.target.value)
                  .then(() => client.invalidateQueries())
                  .catch(() => undefined);
              }}
            >
              {(roles.data ?? []).map((role) => (
                <option key={role.name} value={role.name}>
                  {role.display_name}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="persona">
              Persona
            </label>
            <select
              id="persona"
              aria-label="Persona"
              className="rounded border border-hairline-border bg-card px-2 py-1 text-xs text-ink"
              value={persona}
              onChange={(event) => setPersona(event.target.value)}
            >
              {PERSONAS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={toggleProvenance}
              aria-pressed={showProvenance}
              className="rounded border border-hairline-border px-2 py-1 text-xs text-ink-secondary"
              title="Mark which regions of the page were written by a model"
            >
              {showProvenance ? 'Provenance on' : 'Provenance off'}
            </button>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label="Toggle theme"
              className="rounded border border-hairline-border px-2 py-1 text-xs text-ink-secondary"
            >
              {theme === 'light' ? 'Dark' : 'Light'}
            </button>
          </div>
          <p className="w-full text-[11px] text-ink-muted">
            Simulated clock: 29 Mar 2026 · all data is simulated · Meridian Consumer Brands is a
            fictional company
          </p>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
