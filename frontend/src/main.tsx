import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App.tsx';
import './index.css';

/**
 * An unhandled rejection is a promise nobody is watching, and in this app that means a
 * panel that will sit on its skeleton forever with no error to show for it. React Query
 * owns every request, so a rejection escaping to `window` is a bug rather than a normal
 * condition — it is logged loudly here and marked handled so it cannot become a silent
 * console entry that a demo scrolls past.
 *
 * An `AbortError` is exempt: navigating away from a slow screen aborts its request by
 * design, and reporting a cancellation as a failure would train a reader to ignore this
 * exact channel.
 */
window.addEventListener('unhandledrejection', (event) => {
  const reason: unknown = event.reason;
  if (reason instanceof DOMException && reason.name === 'AbortError') {
    event.preventDefault();
    return;
  }
  console.error('[insight-copilot] unhandled promise rejection', reason);
});

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element #root is missing from index.html');
}

createRoot(rootElement).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
