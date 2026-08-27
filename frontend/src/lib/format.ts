export function formatBytes(value?: number | null): string {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(
    units.length - 1,
    Math.floor(Math.log(bytes) / Math.log(1024)),
  );
  const amount = bytes / 1024 ** index;
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

export function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function shortHash(value?: string | null): string {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 12)}…` : value;
}

export function categoryLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    credential_expired: "游客身份过期",
    risk_rejected: "风控拒绝",
    protocol_incompatible: "协议不兼容",
    proxy_supply_failed: "代理供应失败",
    transport_failed: "传输失败",
    content_unavailable: "无免费内容",
    internal: "内部错误",
  };
  return value ? labels[value] ?? value : "—";
}
