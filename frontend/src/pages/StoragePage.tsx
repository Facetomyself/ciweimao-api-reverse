import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Archive, DatabaseBackup, Download, HardDrive, RefreshCw, Trash2, X } from "lucide-react";
import { useState } from "react";
import { post } from "../api";
import { ErrorState, MetricCard, PageHeader, StatusPill, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import { formatBytes, shortHash } from "../lib/format";
import type { ArchiveItem } from "../types";

interface StorageStatus {
  root: string;
  spool_bytes: number;
  spool_limit_bytes: number;
  spool_ratio: number;
  pending_raw_records: number;
  remote_configured: boolean;
  archives: number;
  mirrored: number;
  local_only: number;
}

interface PublicConfig {
  protocol: { profile: string; app_version: string; transport_profile: string };
  scheduler: { enabled: boolean; timezone: string; sync_interval_minutes: number };
  auto_download: { enabled: boolean; batch_size: number; free_only: boolean };
  egress: { mode: string; provider?: string; fallback_provider?: string; risk_threshold: number; failure_threshold: number };
  storage: { database_path: string; output_dir: string; archive_dir: string; semantic_retention_days: number; nas_mirror_configured: boolean };
}

interface MaintenancePreview {
  confirmation_token: string;
  expires_at: string;
  legacy_raw_records: number;
  pending_raw_records: number;
  semantic_cutoff: string;
  database_bytes: number;
  requested: { compact: boolean };
}

export function StoragePage() {
  const queryClient = useQueryClient();
  const storage = usePollingQuery<StorageStatus>(["storage"], "/api/storage");
  const archives = usePollingQuery<{ archives: ArchiveItem[] }>(["archives"], "/api/storage/archives?limit=200");
  const config = usePollingQuery<PublicConfig>(["config"], "/api/config");
  const [previewData, setPreviewData] = useState<MaintenancePreview | null>(null);
  const action = useMutation({
    mutationFn: (path: string) => post(path),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const preview = useMutation({
    mutationFn: () => post<MaintenancePreview>("/api/storage/maintenance/preview", { compact: true }),
    onSuccess: setPreviewData,
  });
  const maintenance = useMutation({
    mutationFn: (value: MaintenancePreview) => post("/api/storage/maintenance/run", {
      compact: value.requested.compact,
      confirmation_token: value.confirmation_token,
    }),
    onSuccess: () => {
      setPreviewData(null);
      queryClient.invalidateQueries();
    },
  });

  return (
    <>
      <PageHeader
        eyebrow="Retention"
        title="存储与设置"
        description="语义热库保留 400 天；raw 与一致性备份落本地 spool，再镜像 NAS。"
        actions={
          <>
            <button className="button secondary" type="button" onClick={() => action.mutate("/api/storage/archive-pending")}><Archive size={15} />归档 pending</button>
            <button className="button primary" type="button" onClick={() => action.mutate("/api/storage/backup")}><DatabaseBackup size={15} />创建备份</button>
          </>
        }
      />
      {storage.error ? <ErrorState error={storage.error} /> : null}
      {action.error ? <ErrorState error={action.error} /> : null}
      {preview.error ? <ErrorState error={preview.error} /> : null}
      {maintenance.error ? <ErrorState error={maintenance.error} /> : null}

      <section className="metric-grid">
        <MetricCard label="本地 spool" value={formatBytes(storage.data?.spool_bytes)} detail={`上限 ${formatBytes(storage.data?.spool_limit_bytes)}`} tone={(storage.data?.spool_ratio ?? 0) > 0.8 ? "bad" : "accent"} />
        <MetricCard label="raw 待归档" value={storage.data?.pending_raw_records ?? 0} detail="采集不中断，NAS 故障时留本地" />
        <MetricCard label="NAS 镜像" value={storage.data?.mirrored ?? 0} detail={`${storage.data?.local_only ?? 0} 份仅本地`} tone={(storage.data?.local_only ?? 0) > 0 ? "bad" : "good"} />
        <MetricCard label="语义保留" value={`${config.data?.storage.semantic_retention_days ?? 400} 天`} detail="到期按 snapshot / event / probe 清理" />
      </section>

      <div className="content-grid equal">
        <section className="panel compact-panel">
          <div className="panel-heading"><div><p className="eyebrow">Paths</p><h2>存储落点</h2></div><HardDrive size={18} /></div>
          <dl className="detail-list path-list">
            <div><dt>SQLite</dt><dd>{config.data?.storage.database_path ?? "—"}</dd></div>
            <div><dt>TXT</dt><dd>{config.data?.storage.output_dir ?? "—"}</dd></div>
            <div><dt>Archive</dt><dd>{config.data?.storage.archive_dir ?? storage.data?.root ?? "—"}</dd></div>
            <div><dt>NAS</dt><dd><StatusPill value={storage.data?.remote_configured ?? false} /></dd></div>
          </dl>
        </section>
        <section className="panel compact-panel">
          <div className="panel-heading"><div><p className="eyebrow">Runtime</p><h2>只读配置</h2></div></div>
          <dl className="detail-list">
            <div><dt>协议</dt><dd>{config.data?.protocol.profile ?? "—"}</dd></div>
            <div><dt>调度</dt><dd>{config.data?.scheduler.sync_interval_minutes ?? "—"} 分钟</dd></div>
            <div><dt>出口</dt><dd>{config.data?.egress.mode ?? "—"}</dd></div>
            <div><dt>DPS 备援</dt><dd>{config.data?.egress.fallback_provider ?? "—"}</dd></div>
          </dl>
          <p className="muted note">控制台不提供密钥编辑；凭据只通过运行时 secret 注入。</p>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Archive catalog</p><h2>归档目录</h2></div>
          <div className="panel-tools">
            <button className="button small secondary" type="button" onClick={() => action.mutate("/api/storage/retry-mirrors")}><RefreshCw size={14} />重试镜像</button>
            <button className="button small danger" type="button" onClick={() => preview.mutate()}><Trash2 size={14} />维护与瘦身</button>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>周期</th><th>类型</th><th>状态</th><th>记录</th><th>大小</th><th>SHA-256</th><th>更新</th><th /></tr></thead>
            <tbody>
              {archives.data?.archives.map((item) => (
                <tr key={item.id}>
                  <td>{item.period}</td>
                  <td>{item.archive_type}</td>
                  <td><StatusPill value={item.status} /></td>
                  <td>{item.record_count}</td>
                  <td>{formatBytes(item.file_size)}</td>
                  <td><code>{shortHash(item.sha256)}</code></td>
                  <td><Time value={item.updated_at} /></td>
                  <td className="align-right"><a className="icon-button" href={`/api/storage/archives/${item.id}/file`} aria-label="下载归档"><Download size={15} /></a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Dialog.Root open={Boolean(previewData)} onOpenChange={(open) => { if (!open) setPreviewData(null); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content wide-dialog">
            <Dialog.Close className="dialog-close" aria-label="关闭"><X size={17} /></Dialog.Close>
            <Dialog.Title>确认归档维护与数据库瘦身</Dialog.Title>
            <Dialog.Description>任务会先用 SQLite backup API 创建一致性备份，再归档 raw、清理 400 天外语义历史，并按预览选择执行 observations 换表。</Dialog.Description>
            <div className="warning-grid">
              <div><span>当前数据库</span><strong>{formatBytes(previewData?.database_bytes)}</strong></div>
              <div><span>legacy raw</span><strong>{previewData?.legacy_raw_records ?? 0}</strong></div>
              <div><span>pending raw</span><strong>{previewData?.pending_raw_records ?? 0}</strong></div>
              <div><span>Compact</span><strong>{previewData?.requested.compact ? "是" : "否"}</strong></div>
            </div>
            <p className="muted">语义截止：<Time value={previewData?.semantic_cutoff} /> · 确认令牌过期：<Time value={previewData?.expires_at} /></p>
            <div className="dialog-actions">
              <Dialog.Close className="button secondary">取消</Dialog.Close>
              <button className="button danger" type="button" disabled={!previewData || maintenance.isPending} onClick={() => previewData && maintenance.mutate(previewData)}>确认执行</button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
