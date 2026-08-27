import * as Tooltip from "@radix-ui/react-tooltip";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Archive,
  BookOpen,
  Compass,
  Fingerprint,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { pollingInterval } from "../hooks";
import { StatusPill } from "./ui";

const navigation = [
  { to: "/", label: "运行总览", icon: Activity },
  { to: "/books", label: "书籍与下载", icon: BookOpen },
  { to: "/discovery", label: "榜单与新书", icon: Compass },
  { to: "/tasks", label: "任务与事件", icon: ListChecks },
  { to: "/identity", label: "身份与出口", icon: Fingerprint },
  { to: "/storage", label: "存储与设置", icon: Archive },
];

interface ReadyState {
  status: string;
  ready: boolean;
  protocol?: { app_version?: string };
  proxy?: { active_slot?: string; provider?: string };
}

export function Layout() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const response = await fetch("/health/ready");
      return (await response.json()) as ReadyState;
    },
    refetchInterval: pollingInterval,
    refetchIntervalInBackground: true,
  });
  return (
    <Tooltip.Provider delayDuration={300}>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand-block">
            <span className="brand-mark"><ShieldCheck size={19} /></span>
            <div>
              <strong>Ciweimao</strong>
              <span>Collector Console</span>
            </div>
          </div>
          <nav aria-label="主导航">
            {navigation.map(({ to, label, icon: Icon }) => (
              <Tooltip.Root key={to}>
                <Tooltip.Trigger asChild>
                  <NavLink
                    to={to}
                    end={to === "/"}
                    className={({ isActive }) => isActive ? "nav-link is-active" : "nav-link"}
                  >
                    <Icon size={17} aria-hidden="true" />
                    <span>{label}</span>
                  </NavLink>
                </Tooltip.Trigger>
                <Tooltip.Portal>
                  <Tooltip.Content className="tooltip-content" side="right" sideOffset={10}>
                    {label}
                  </Tooltip.Content>
                </Tooltip.Portal>
              </Tooltip.Root>
            ))}
          </nav>
          <div className="sidebar-foot">
            <span>仅游客态 · 仅免费内容</span>
            <small>本地 / SSH tunnel</small>
          </div>
        </aside>
        <div className="main-column">
          <header className="topbar">
            <div className="topbar-context">
              <span className="live-dot" aria-hidden="true" />
              <span>协议 {health.data?.protocol?.app_version ?? "—"}</span>
              <span className="topbar-divider" />
              <span>出口 {health.data?.proxy?.active_slot ?? health.data?.proxy?.provider ?? "—"}</span>
            </div>
            <StatusPill value={health.data?.ready ? "ready" : "not_ready"} />
          </header>
          <main className="page-content">
            <Outlet />
          </main>
        </div>
      </div>
    </Tooltip.Provider>
  );
}
