import React, { useEffect, useState } from "react";
import { useApp } from "../store.jsx";

const KINDS = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "提及" },
];

const COLS = {
  authors: [
    { key: "Name_CN", label: "中文名" },
    { key: "originalName", label: "原文名" },
    { key: "nationality", label: "国籍" },
    { key: "deletedAt", label: "删除时间" },
  ],
  works: [
    { key: "Title_CN", label: "中文名" },
    { key: "originalTitle", label: "原著标题" },
    { key: "Author", label: "作者" },
    { key: "publicationYear", label: "年份" },
    { key: "deletedAt", label: "删除时间" },
  ],
  edges: [
    { key: "source_work_id", label: "源作品" },
    { key: "target_work_id", label: "目标作品" },
    { key: "reviewStatus", label: "审核" },
    { key: "deletedAt", label: "删除时间" },
  ],
};

export default function Admin() {
  const { state, dispatch } = useApp();
  const [kind, setKind] = useState("authors");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");

  const load = () => {
    setLoading(true);
    fetch("/api/admin/data")
      .then((r) => r.json())
      .then((d) => { setData(d); setLoading(false); })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { load(); }, [kind]);

  if (!state.adminOpen) return null;

  const rows = data ? data[kind] || [] : [];
  const cols = COLS[kind];
  const counts = data ? data.counts || {} : {};

  const doImport = () => {
    if (!window.confirm("将 data/real/*.csv 写入 Neo4j(增量合并),继续?")) return;
    setStatus("导入中…");
    fetch("/api/admin/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ wipe: false, version: "1.1" }),
    })
      .then((r) => r.json())
      .then((d) => {
        setStatus(d.ok ? "导入完成" : (d.detail || "导入失败"));
        setTimeout(() => window.location.reload(), 1200);
      })
      .catch((e) => setStatus("导入失败: " + e.message));
  };

  const doDelete = (id) => {
    if (!window.confirm("确认删除「" + id + "」?(软删除,可恢复)")) return;
    fetch("/api/admin/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
      .then((r) => r.json())
      .then((d) => { setStatus(d.ok ? "已软删除" : (d.detail || "删除失败")); load(); })
      .catch((e) => setStatus("删除失败: " + e.message));
  };

  const doRestore = (id) => {
    const row = rows.find((r) => r.id === id);
    if (!row) return;
    fetch("/api/admin/" + kind + "/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...row, deletedAt: null }),
    })
      .then((r) => r.json())
      .then((d) => { setStatus(d.ok ? "已恢复" : (d.detail || "恢复失败")); load(); })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  const exportJson = () => {
    window.open("/api/admin/export/json", "_blank");
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <h2>数据管理</h2>
          <div className="admin-tabs">
            {KINDS.map((k) => (
              <button
                key={k.key}
                className={"admin-tab" + (kind === k.key ? " active" : "")}
                data-kind={k.key}
                onClick={() => setKind(k.key)}
              >
                {k.label} <span className="cnt">{counts[k.key] != null ? counts[k.key] : (data ? data[k.key].length : "")}</span>
              </button>
            ))}
          </div>
          <div className="admin-actions">
            <button onClick={doImport}>导入到 Neo4j</button>
            <button onClick={exportJson}>导出 JSON</button>
            <button id="admin-close" onClick={() => dispatch({ type: "SET_ADMIN", open: false })}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        <div className="admin-body">
          {loading ? <p>加载中…</p> : (
            <table id="admin-table">
              <thead>
                <tr>
                  {cols.map((c) => <th key={c.key}>{c.label}</th>)}
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id || r.source_work_id + r.target_work_id} className={r.deletedAt ? "deleted" : ""}>
                    {cols.map((c) => <td key={c.key}>{String(r[c.key] ?? "")}</td>)}
                    <td>
                      {r.deletedAt
                        ? <button onClick={() => doRestore(r.id)}>恢复</button>
                        : <button onClick={() => doDelete(r.id)}>删除</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
