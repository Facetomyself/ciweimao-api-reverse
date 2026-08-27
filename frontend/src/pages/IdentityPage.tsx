import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, Network, RefreshCw, RotateCcw, X } from "lucide-react";
import { useState } from "react";
import { post } from "../api";
import { ErrorState, PageHeader, StatusPill, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import { categoryLabel } from "../lib/format";
import type { IdentitySlot } from "../types";

interface EgressSnapshot {
  active_slot?: string;
  manual_slot?: string | null;
  next_retry_at?: string | null;
  slots?: Record<string, {
    state: string;
    provider: string;
    active: boolean;
    generation: number;
    failure_streak: number;
    risk_streak: number;
    opened_until?: string | null;
  }>;
}

interface Probe {
  id: string;
  slot_id: string;
  endpoint: string;
  ok: boolean;
  category?: string;
  code?: string;
  latency_ms?: number;
  created_at: string;
}

interface Confirmation {
  confirmation_token: string;
  expires_at: string;
  warning: string;
  slot_id: string;
}

export function IdentityPage() {
  const queryClient = useQueryClient();
  const identity = usePollingQuery<{ slots: IdentitySlot[] }>(["identity"], "/api/identity");
  const egress = usePollingQuery<EgressSnapshot>(["egress"], "/api/egress");
  const probes = usePollingQuery<{ probes: Probe[] }>(["probes"], "/api/protocol/probes");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const action = useMutation({
    mutationFn: ({ path, body = {} }: { path: string; body?: unknown }) => post(path, body),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const preview = useMutation({
    mutationFn: (slot: string) => post<Confirmation>(`/api/identity/${slot}/rotate/preview`),
    onSuccess: setConfirmation,
  });
  const rotate = useMutation({
    mutationFn: (value: Confirmation) => post(`/api/identity/${value.slot_id}/rotate`, {
      confirmation_token: value.confirmation_token,
    }),
    onSuccess: () => {
      setConfirmation(null);
      queryClient.invalidateQueries();
    },
  });

  return (
    <>
      <PageHeader
        eyebrow="Fingerprint boundary"
        title="身份与出口"
        description="每个出口持有独立稳定 UUID 与游客身份；风控拒绝只切出口，不自动轮换身份。"
        actions={
          <button className="button primary" type="button" onClick={() => action.mutate({ path: "/api/egress/probe", body: {} })}>
            <Network size={15} />探测当前出口
          </button>
        }
      />
      {identity.error ? <ErrorState error={identity.error} /> : null}
      {action.error ? <ErrorState error={action.error} /> : null}
      {preview.error ? <ErrorState error={preview.error} /> : null}
      {rotate.error ? <ErrorState error={rotate.error} /> : null}

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Identity slots</p><h2>游客身份槽</h2></div><span className="count-label">不回显 token / account</span></div>
        <div className="identity-grid">
          {identity.data?.slots.map((slot) => (
            <article className="identity-card" key={slot.slot_id}>
              <div className="identity-icon"><Fingerprint size={19} /></div>
              <div className="identity-title"><strong>{slot.slot_id}</strong><StatusPill value={slot.identity_status ?? (slot.has_identity ? "unvalidated" : "missing")} /></div>
              <dl className="detail-list">
                <div><dt>Profile</dt><dd title={slot.profile_id}>{slot.profile_id?.slice(0, 18) ?? "—"}</dd></div>
                <div><dt>App</dt><dd>{slot.app_version ?? "—"}</dd></div>
                <div><dt>来源</dt><dd>{slot.origin ?? "—"}</dd></div>
                <div><dt>最近验证</dt><dd><Time value={slot.last_validated_at} /></dd></div>
              </dl>
              <div className="card-actions">
                <button className="button small secondary" type="button" onClick={() => action.mutate({ path: `/api/identity/${slot.slot_id}/validate` })}>
                  <RefreshCw size={14} />验证
                </button>
                <button className="button small danger" type="button" onClick={() => preview.mutate(slot.slot_id)}>
                  <RotateCcw size={14} />轮换
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Egress slots</p><h2>出口状态</h2></div>
          <div className="segmented-actions">
            {["automatic", "nas-primary", "dps-fallback"].map((mode) => (
              <button
                key={mode}
                className={(mode === "automatic" ? !egress.data?.manual_slot : egress.data?.manual_slot === mode) ? "segment is-selected" : "segment"}
                type="button"
                onClick={() => action.mutate({ path: "/api/egress/mode", body: { mode, reset_breaker: mode === "nas-primary" } })}
              >{mode}</button>
            ))}
          </div>
        </div>
        <div className="slot-grid">
          {Object.entries(egress.data?.slots ?? {}).map(([slotId, slot]) => (
            <article className={`slot-card ${egress.data?.active_slot === slotId ? "is-active" : ""}`} key={slotId}>
              <div><strong>{slotId}</strong><StatusPill value={slot.state} /></div>
              <dl>
                <div><dt>Provider</dt><dd>{slot.provider}</dd></div>
                <div><dt>Generation</dt><dd>{slot.generation}</dd></div>
                <div><dt>传输失败</dt><dd>{slot.failure_streak}</dd></div>
                <div><dt>风控拒绝</dt><dd>{slot.risk_streak}</dd></div>
              </dl>
              {slot.opened_until ? <small>冷却至 <Time value={slot.opened_until} /></small> : null}
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><p className="eyebrow">Protocol probes</p><h2>最近协议探针</h2></div></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>出口</th><th>端点</th><th>结果</th><th>延迟</th><th>分类</th></tr></thead>
            <tbody>
              {probes.data?.probes.map((probe) => (
                <tr key={probe.id}>
                  <td><Time value={probe.created_at} /></td>
                  <td>{probe.slot_id}</td>
                  <td>{probe.endpoint}</td>
                  <td><StatusPill value={probe.ok} /></td>
                  <td>{probe.latency_ms ? `${Math.round(probe.latency_ms)} ms` : "—"}</td>
                  <td>{categoryLabel(probe.category)} {probe.code || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Dialog.Root open={Boolean(confirmation)} onOpenChange={(open) => { if (!open) setConfirmation(null); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content">
            <Dialog.Close className="dialog-close" aria-label="关闭"><X size={17} /></Dialog.Close>
            <Dialog.Title>确认轮换游客身份</Dialog.Title>
            <Dialog.Description>{confirmation?.warning}</Dialog.Description>
            <div className="warning-box">
              <strong>{confirmation?.slot_id}</strong>
              <span>旧 profile 与 token 将停止使用；新身份会经同一出口重新注册并验证。</span>
              <small>令牌过期：<Time value={confirmation?.expires_at} /></small>
            </div>
            <div className="dialog-actions">
              <Dialog.Close className="button secondary">取消</Dialog.Close>
              <button className="button danger" type="button" disabled={!confirmation || rotate.isPending} onClick={() => confirmation && rotate.mutate(confirmation)}>
                确认轮换
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
