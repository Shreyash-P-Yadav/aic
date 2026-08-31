/**
 * Client state: the theme, the persona and the "LLM vs computed" toggle.
 *
 * Deliberately small. The *role* lives on the server, because switching role changes
 * what the compiler returns — putting it in client state would make the entitlement
 * demo a UI trick. What lives here is presentation: which theme, which persona's
 * wording, and whether model-written regions are visibly marked.
 */

import { create } from 'zustand';

export type Theme = 'light' | 'dark';

interface UiState {
  theme: Theme;
  persona: string;
  showProvenance: boolean;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setPersona: (persona: string) => void;
  toggleProvenance: () => void;
}

function applyTheme(theme: Theme): void {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme);
  }
}

export const useUi = create<UiState>((set, get) => ({
  theme: 'light',
  persona: 'analyst',
  showProvenance: false,
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => get().setTheme(get().theme === 'light' ? 'dark' : 'light'),
  setPersona: (persona) => set({ persona }),
  toggleProvenance: () => set({ showProvenance: !get().showProvenance }),
}));
