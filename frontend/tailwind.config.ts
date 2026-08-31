import type { Config } from 'tailwindcss';

/**
 * Colour is defined once, in src/styles/theme.css, as CSS custom properties.
 * Tailwind references those variables by ROLE so no hex ever appears outside
 * the theme file — light and dark are then a variable swap, not a filter.
 */
const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: 'var(--surface-page)',
        card: 'var(--surface-card)',
        ink: {
          DEFAULT: 'var(--ink-primary)',
          secondary: 'var(--ink-secondary)',
          muted: 'var(--ink-muted)',
        },
        hairline: {
          grid: 'var(--hairline-grid)',
          axis: 'var(--hairline-axis)',
          border: 'var(--hairline-border)',
        },
        status: {
          good: 'var(--status-good)',
          warning: 'var(--status-warning)',
          serious: 'var(--status-serious)',
          critical: 'var(--status-critical)',
        },
      },
      borderRadius: { card: '12px' },
      boxShadow: { card: 'var(--shadow-card)' },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      },
      transitionDuration: { DEFAULT: '150ms' },
    },
  },
  plugins: [],
};

export default config;
