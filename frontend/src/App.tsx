/**
 * Routing and the query client.
 *
 * Nine screens over a typed API. Retries are off by default because most failures
 * here are *states* rather than transients — a cold start with no warehouse is a real
 * answer, and retrying it three times only delays showing the reader what is wrong.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Navigate, Route, Routes } from 'react-router-dom';

import { Layout } from '@/components/Layout';
import { InsightDetail } from '@/screens/InsightDetail';
import { InsightFeed } from '@/screens/InsightFeed';
import { Admin } from '@/screens/Admin';
import { Actions, Ask } from '@/screens/Interactive';
import { Audit, DataSources, Telemetry } from '@/screens/Simple';
import { TrustCalibration } from '@/screens/Trust';

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 15_000 } },
});

export default function App() {
  return (
    <QueryClientProvider client={client}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<InsightFeed />} />
          <Route path="insights/:insightId" element={<InsightDetail />} />
          <Route path="ask" element={<Ask />} />
          <Route path="actions" element={<Actions />} />
          <Route path="data" element={<DataSources />} />
          <Route path="trust" element={<TrustCalibration />} />
          <Route path="telemetry" element={<Telemetry />} />
          <Route path="admin" element={<Admin />} />
          <Route path="audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </QueryClientProvider>
  );
}
