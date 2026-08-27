import * as Tabs from "@radix-ui/react-tabs";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, PageHeader, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import type { Book } from "../types";

interface Snapshot {
  id: string;
  source_key: string;
  captured_at: string;
  item_count: number;
  items?: Book[];
}

interface HistoryItem {
  snapshot_id: string;
  captured_at: string;
  book_id: string;
  book_name: string;
  position: number;
}

function RankBars({ items }: { items: Book[] }) {
  const visible = items.slice(0, 8);
  const max = Math.max(1, visible.length);
  return (
    <div className="rank-bars" aria-label="榜单前八名位置图">
      {visible.map((book, index) => (
        <div key={book.book_id} title={`${index + 1}. ${book.book_name}`}>
          <span>{index + 1}</span>
          <i style={{ transform: `scaleX(${(max - index) / max})` }} />
          <strong>{book.book_name}</strong>
        </div>
      ))}
    </div>
  );
}

export function DiscoveryPage() {
  const rankings = usePollingQuery<{ snapshots: Snapshot[] }>(["rankings", "latest"], "/api/rankings/latest");
  const newBooks = usePollingQuery<Snapshot>(["new-books", "latest"], "/api/new-books/latest");
  const [source, setSource] = useState("");
  useEffect(() => {
    if (!source && rankings.data?.snapshots[0]) setSource(rankings.data.snapshots[0].source_key);
  }, [rankings.data, source]);
  const history = usePollingQuery<{ history: HistoryItem[] }>(
    ["ranking-history", source],
    source ? `/api/rankings/${encodeURIComponent(source)}/history?limit=300` : "/api/rankings/__pending__/history?limit=1",
  );
  const selected = rankings.data?.snapshots.find((item) => item.source_key === source);
  const latestPositions = useMemo(() => {
    const seen = new Set<string>();
    return (history.data?.history ?? []).filter((item) => {
      if (seen.has(item.book_id)) return false;
      seen.add(item.book_id);
      return true;
    }).sort((a, b) => a.position - b.position).slice(0, 20);
  }, [history.data]);
  const selectedBooks = (selected?.items ?? latestPositions) as Book[];

  return (
    <>
      <PageHeader
        eyebrow="Discovery"
        title="榜单与新书"
        description="快照保留 400 天语义历史，raw 响应转入冷档；这里展示的是可查询语义层。"
      />
      {rankings.error ? <ErrorState error={rankings.error} /> : null}
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Rankings</p><h2>榜单快照</h2></div><span className="count-label">{rankings.data?.snapshots.length ?? 0} 类</span></div>
        {(rankings.data?.snapshots.length ?? 0) === 0 ? (
          <EmptyState>暂无榜单快照。</EmptyState>
        ) : (
          <Tabs.Root className="tabs-root" value={source} onValueChange={setSource}>
            <Tabs.List className="tabs-list" aria-label="榜单类型">
              {rankings.data?.snapshots.map((snapshot) => (
                <Tabs.Trigger className="tabs-trigger" value={snapshot.source_key} key={snapshot.source_key}>
                  {snapshot.source_key}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            {rankings.data?.snapshots.map((snapshot) => (
              <Tabs.Content className="tabs-content" value={snapshot.source_key} key={snapshot.source_key}>
                <div className="snapshot-meta">
                  <span>最近采集 <Time value={snapshot.captured_at} /></span>
                  <span>{snapshot.item_count} 条</span>
                </div>
                <RankBars items={selectedBooks} />
                <div className="book-card-grid">
                  {selectedBooks.slice(0, 12).map((book, index) => (
                    <article className="book-card" key={book.book_id}>
                      <span className="rank-number">{book.position ?? index + 1}</span>
                      <div><strong>{book.book_name}</strong><small>{book.author_name || book.book_id}</small></div>
                    </article>
                  ))}
                </div>
              </Tabs.Content>
            ))}
          </Tabs.Root>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">New books</p><h2>最新入库</h2></div><span className="count-label"><Time value={newBooks.data?.captured_at} /></span></div>
        {(newBooks.data?.items?.length ?? 0) === 0 ? (
          <EmptyState>暂无新书快照。</EmptyState>
        ) : (
          <div className="book-card-grid">
            {newBooks.data?.items?.slice(0, 24).map((book, index) => (
              <article className="book-card" key={book.book_id}>
                <span className="rank-number">{index + 1}</span>
                <div><strong>{book.book_name}</strong><small>{book.author_name || "未知作者"}</small></div>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
