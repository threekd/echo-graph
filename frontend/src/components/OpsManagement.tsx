/* 运维管理窗口(仅 admin):快照(备份恢复) + 日志(审计)。
   与「星云工坊 / 用户管理」同款窗口样式;子 Tab 为 快照 / 日志。 */

import { useState } from "react";
import AuditPanel from "./admin/AuditPanel";
import SnapshotsPanel from "./admin/SnapshotsPanel";

const TABS = [
  { key: "snapshots", label: "快照" },
  { key: "audit", label: "日志" },
] as const;

type OpsTab = (typeof TABS)[number]["key"];

const authFetch = (url: string, options?: RequestInit): Promise<Response> =>
  fetch(url, options);

export default function OpsManagement({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<OpsTab>("snapshots");
  // 日志表排序/筛选状态(与星云工坊页同款)
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2 className="admin-title">运维管理</h2>
            <div className="admin-tabs">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  className={"admin-tab" + (tab === t.key ? " active" : "")}
                  onClick={() => setTab(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div className="admin-actions">
            <button id="admin-close" onClick={onClose}>关闭</button>
          </div>
        </div>
        <div className="admin-body">
          {tab === "audit" ? (
            <AuditPanel
              authFetch={authFetch}
              sort={sort}
              filters={filters}
              textFilters={textFilters}
              onSort={(k) =>
                setSort((prev) =>
                  prev && prev.key === k ? (prev.dir === 1 ? { key: k, dir: -1 } : null) : { key: k, dir: 1 }
                )
              }
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
            />
          ) : (
            <SnapshotsPanel authFetch={authFetch} />
          )}
        </div>
      </div>
    </div>
  );
}
