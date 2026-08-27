import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, RefreshCw } from "lucide-react";
import { post } from "../api";
import { ErrorState, MetricCard, PageHeader, StatusPill, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import { categoryLabel, formatBytes } from "../lib/format";
import type { EventItem } from "../types";

interface Overview {
  tasks?: Record<string, number>;
  last_success_at?: string | null;
  failures_24h?: Record<string, number>;
  raw_archive_pending?: number;
  database_bytes?: number;
  controls?: Record<string, { paused: boolean; reason: string }>;
  egress?: {
    active_slot?: string;
    manual_slot?: string | null;
    slots?: Record<string, { state: string; failure_streak: number; risk_streak: number }>;
  };
  archive?: { spool_ratio?: number; local_only?: number; mirrored?: number };
  operation?: { failure_streak?: number; last_success_at?: string | null };
}

export function OverviewPage() {
  const queryClient = useQueryClient();
  const overview = usePollingQuery<Overview>(["overview"], "/api/overview");
  const events = usePollingQuery<{ events: EventItem[] }>(["events", "recent"], "/api/events?limit=8");
  const mutation = useMutation({
    mutationFn: ({ path, body = {} }: { path: string; body?: unknown }) => post(path, body),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const data = overview.data;
  const paused = Boolean(data?.controls?.all?.paused);
  const failedCount = Object.values(data?.failures_24h ?? {}).reduce((sum, value) => sum + value, 0);

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="运行总览"
        description="先看协议、出口和失败连续性，再决定是否继续放量。"
        actions={
          <>
            <button
              className="button secondary"
              type="button"
              onClick={() => mutation.mutate({
                path: paused ? "/api/controls/all/resume" : "/api/controls/all/pause",
                body: { reason: paused ? "控制台恢复" : "控制台人工暂停" },
              })}
            >
              {paused ? <Play size={15} /> : <Pause size={15} />}
              {paused ? "恢复队列" : "暂停队列"}
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() => mutation.mutate({ path: "/api/sync/all" })}
            >
              <RefreshCw size={15} />立即同步
            </button>
          </>
        }
      />
      {overview.error ? <ErrorState error={overview.error} /> : null}
      {mutation.error ? <ErrorState error={mutation.error} /> : null}
      <section className="metric-grid" aria-label="关键指标">
        <MetricCard
          label="队列状态"
          value={paused ? "已暂停" : "运行中"}
          detail={`${data?.tasks?.queued ?? 0} queued · ${data?.tasks?.running ?? 0} running`}
          tone={paused ? "bad" : "good"}
        />
        <MetricCard
          label="最近成功"
          value={<Time value={data?.operation?.last_success_at ?? data?.last_success_at} />}
          detail={`连续失败 ${data?.operation?.failure_streak ?? 0} 次`}
          tone={(data?.operation?.failure_streak ?? 0) > 0 ? "bad" : "neutral"}
        />
        <MetricCard
          label="24 小时失败"
          value={failedCount}
          detail={Object.entries(data?.failures_24h ?? {}).map(([key, value]) => `${categoryLabel(key)} ${value}`).join(" · ") || "无"}
          tone={failedCount ? "bad" : "good"}
        />
        <MetricCard
          label="热库 / raw 队列"
          value={formatBytes(data?.database_bytes)}
          detail={`${data?.raw_archive_pending ?? 0} 条待冷档`}
          tone="accent"
        />
      </section>

      <div className="content-grid two-thirds">
        <section className="panel">
          <div className="panel-heading">
            <div><p className="eyebrow">Egress</p><h2>出口断路器</h2></div>
            <StatusPill value={data?.egress?.active_slot ?? "unknown"} />
          </div>
          <div className="slot-grid">
            {Object.entries(data?.egress?.slots ?? {}).map(([slot, state]) => (
              <article className="slot-card" key={slot}>
                <div><strong>{slot}</strong><StatusPill value={state.state} /></div>
                <dl>
                  <div><dt>传输连续失败</dt><dd>{state.failure_streak}</dd></div>
                  <div><dt>风控连续拒绝</dt><dd>{state.risk_streak}</dd></div>
                </dl>
              </article>
            ))}
            {!data?.egress?.slots ? <p className="muted">单出口模式，尚无 breaker 槽信息。</p> : null}
          </div>
        </section>
        <section className="panel compact-panel">
          <div className="panel-heading"><div><p className="eyebrow">Archive</p><h2>冷档水位</h2></div></div>
          <div className="progress-track" aria-label="本地归档占用">
            <span style={{ transform: `scaleX(${Math.min(1, data?.archive?.spool_ratio ?? 0)})` }} />
          </div>
          <dl className="detail-list">
            <div><dt>本地占用</dt><dd>{Math.round((data?.archive?.spool_ratio ?? 0) * 100)}%</dd></div>
            <div><dt>NAS 已镜像</dt><dd>{data?.archive?.mirrored ?? 0}</dd></div>
            <div><dt>仅本地</dt><dd>{data?.archive?.local_only ?? 0}</dd></div>
          </dl>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Timeline</p><h2>最近事件</h2></div></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>组件</th><th>事件</th><th>分类</th><th>消息</th></tr></thead>
            <tbody>
              {(events.data?.events ?? []).map((event) => (
                <tr key={event.id}>
                  <td><Time value={event.created_at} /></td>
                  <td>{event.component}</td>
                  <td>{event.event_type}</td>
                  <td>{categoryLabel(event.category)}</td>
                  <td className="truncate-cell" title={event.message}>{event.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
