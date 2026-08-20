/* 快照/备份恢复面板:列出可恢复的 SQLite 快照,支持一键恢复(恢复前自动安全备份)。 */

import { useCallback, useEffect, useState } from "react";

interface SnapshotItem {
  name: string;
  size: number;
  mtime: string;
}

function fmtSize(n: number): string {
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return n + " B";
}

export default function SnapshotsPanel({
  authFetch,
}: {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}) {
  const [items, setItems] = useState<SnapshotItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [confirm, setConfirm] = useState<SnapshotItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/backups")
      .then((r) => r.json())
      .then((d) => {
        setItems((d && d.items) || []);
        setLoading(false);
      })
      .catch((e) => {
        setStatus("加载快照失败: " + e.message);
        setLoading(false);
      });
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const doCreate = () => {
    setCreating(true);
    setStatus("创建快照中…");
    authFetch("/api/admin/backups/create", { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        if (!d || !d.ok) {
          setStatus((d && d.detail) || "创建快照失败");
        } else {
          setStatus("已创建快照「" + d.name + "」");
        }
        setCreating(false);
        load();
      })
      .catch((e) => {
        setStatus("创建快照失败: " + e.message);
        setCreating(false);
      });
  };

  const doRestore = () => {
    if (!confirm) return;
    setBusy(true);
    setStatus("恢复中…");
    authFetch("/api/admin/backups/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: confirm.name }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (!d || !d.ok) {
          setStatus((d && d.detail) || "恢复失败");
          setBusy(false);
          return;
        }
        setStatus("已恢复「" + d.restored + "」,刷新页面加载新数据");
        setConfirm(null);
        setTimeout(() => window.location.reload(), 1500);
      })
      .catch((e) => {
        setStatus("恢复失败: " + e.message);
        setBusy(false);
      });
  };

  return (
    <div className="snapshots-panel">
      <p className="panel-hint">
        快照来源:deploy.sh 的 SQLite 备份(backups/)与历史版本目录(data/versions/)。恢复前会自动备份当前库;恢复成功后公开视图立即使用恢复的数据。
      </p>
      <div id="admin-status">{status}</div>
      <div className="admin-modal-actions" style={{ justifyContent: "flex-start", margin: "0 0 8px" }}>
        <button onClick={doCreate} disabled={creating}>{creating ? "创建中…" : "＋ 创建快照"}</button>
      </div>
      {loading ? (
        <p>加载中…</p>
      ) : items.length === 0 ? (
        <p>暂无快照。部署端运行 deploy.sh 生成备份,或查看 data/versions/ 历史目录。</p>
      ) : (
        <table id="admin-table">
          <thead>
            <tr>
              <th>快照文件</th>
              <th>大小</th>
              <th>修改时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.name}>
                <td>{it.name}</td>
                <td>{fmtSize(it.size)}</td>
                <td>{it.mtime}</td>
                <td>
                  <button className="del" onClick={() => setConfirm(it)} disabled={busy}>恢复</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirm && (
        <div id="auth-modal">
          <div className="admin-modal-card">
            <h3>恢复快照</h3>
            <p>确认用「{confirm.name}」覆盖当前数据?(恢复前会自动备份当前库)</p>
            <div className="admin-modal-actions">
              <button className="del" onClick={doRestore} disabled={busy}>
                {busy ? "恢复中…" : "确认恢复"}
              </button>
              <button onClick={() => setConfirm(null)} disabled={busy}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
