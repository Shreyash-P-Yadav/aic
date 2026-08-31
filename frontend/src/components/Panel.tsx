/** A fetch-shaped card: skeleton, error, empty, rows — the same four states everywhere. */

import { ApiError } from '@/lib/api';
import { Card, EmptyState, SectionTitle, Skeleton } from './primitives';

export function Panel<T>({
  title,
  hint,
  query,
  empty,
  children,
}: {
  title: string;
  hint?: string;
  query: { isPending: boolean; isError: boolean; error: unknown; data: T[] | undefined };
  empty: string;
  children: (rows: T[]) => React.ReactNode;
}) {
  return (
    <Card>
      <SectionTitle hint={hint}>{title}</SectionTitle>
      {query.isPending ? <Skeleton rows={3} /> : null}
      {query.isError ? (
        <EmptyState
          title={empty}
          detail={
            query.error instanceof ApiError
              ? (query.error.problem.detail ?? query.error.problem.title)
              : String(query.error)
          }
        />
      ) : null}
      {query.data?.length === 0 ? <EmptyState title={empty} /> : null}
      {query.data && query.data.length > 0 ? children(query.data) : null}
    </Card>
  );
}
