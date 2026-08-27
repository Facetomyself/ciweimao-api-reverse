import type { ReactNode } from "react";
import { AlertCircle, CheckCircle2, LoaderCircle } from "lucide-react";
import { formatTime } from "../lib/format";

export function StatusPill({ value }: { value?: string | boolean | null }) {
  const normalized = String(value ?? "unknown");
  const good = ["true", "ready", "succeeded", "closed", "mirrored", "valid", "downloaded", "free-index"].includes(normalized);
  const waiting = ["queued", "deferred", "running", "half_open", "unvalidated", "local_only", "paid-index", "not_downloaded"].includes(normalized);
  return (
    <span className={`status-pill ${good ? "is-good" : waiting ? "is-waiting" : "is-bad"}`}>
      {good ? <CheckCircle2 size={13} /> : waiting ? <LoaderCircle size={13} /> : <AlertCircle size={13} />}
      {normalized}
    </span>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "good" | "bad" | "accent";
}) {
  return (
    <article className={`metric-card tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </article>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "请求失败";
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={17} />
      {message}
    </div>
  );
}

export function Time({ value }: { value?: string | null }) {
  return <time dateTime={value ?? undefined}>{formatTime(value)}</time>;
}
