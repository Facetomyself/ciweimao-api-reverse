import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { post } from "../api";
import { ErrorState, PageHeader, StatusPill, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import { categoryLabel } from "../lib/format";
import type { EventItem, Task } from "../types";

const statuses = ["all", "queued", "deferred", "running", "succeeded", "failed", "cancelled"];

export function TasksPage() {
  const [status, setStatus] = useState("all");
  const queryClient = useQueryClient();
  const tasks = usePollingQuery<{ tasks: Task[] }>(
    ["tasks", status],
    `/api/tasks?limit=200${status === "all" ? "" : `&status=${status}`}`,
  );
  const events = usePollingQuery<{ events: EventItem[] }>(["events", "task-page"], "/api/events?limit=100");
  const mutation = useMutation({
    mutationFn: (path: string) => post(path),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tasks"] }),
  });
  return (
    <>
      <PageHeader
        eyebrow="Durable queue"
        title="任务与事件"
        description="出口全断时任务进入 deferred；恢复后由 poller 自动拾取，不会直接判永久失败。"
        actions={
          <label className="select-control">
            <span>状态</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              {statuses.map((value) => <option value={value} key={value}>{value}</option>)}
            </select>
          </label>
        }
      />
      {tasks.error ? <ErrorState error={tasks.error} /> : null}
      {mutation.error ? <ErrorState error={mutation.error} /> : null}
      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Tasks</p><h2>持久任务</h2></div><span className="count-label">{tasks.data?.tasks.length ?? 0} 条</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>创建</th><th>类型</th><th>状态</th><th>尝试</th><th>故障分类</th><th>错误</th><th /></tr></thead>
            <tbody>
              {tasks.data?.tasks.map((task) => {
                const effective = task.effective_status ?? task.status;
                return (
                  <tr key={task.id}>
                    <td><Time value={task.created_at} /></td>
                    <td><strong>{task.task_type}</strong><small className="cell-sub">{task.id.slice(0, 10)}</small></td>
                    <td><StatusPill value={effective} /></td>
                    <td>{task.attempts}</td>
                    <td>{categoryLabel(task.failure_category)}</td>
                    <td className="truncate-cell" title={task.error ?? ""}>{task.error || "—"}</td>
                    <td className="align-right action-cell">
                      {["failed", "cancelled"].includes(task.status) ? (
                        <button className="icon-button" type="button" aria-label="重试任务" onClick={() => mutation.mutate(`/api/tasks/${task.id}/retry`)}>
                          <RotateCcw size={15} />
                        </button>
                      ) : null}
                      {task.status === "queued" ? (
                        <button className="icon-button danger" type="button" aria-label="取消任务" onClick={() => mutation.mutate(`/api/tasks/${task.id}/cancel`)}>
                          <X size={15} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Events</p><h2>故障与操作事件</h2></div></div>
        <div className="event-stream">
          {events.data?.events.map((event) => (
            <article key={event.id}>
              <span className={`event-marker ${event.category ? "has-error" : ""}`} />
              <div>
                <div><strong>{event.event_type}</strong><Time value={event.created_at} /></div>
                <p>{event.message || event.component}</p>
                {event.category ? <small>{categoryLabel(event.category)} · {event.code || "no-code"}</small> : null}
              </div>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
