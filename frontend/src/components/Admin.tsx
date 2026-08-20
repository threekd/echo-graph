import { useCallback, useEffect, useState } from "react";
import { useApp } from "../store";
import { clearAdminToken, getAdminToken, setAdminToken } from "../lib/adminAuth";
import type { AdminData, AdminTab } from "../lib/adminTypes";
import AdminTable from "./admin/AdminTable";
import AuditPanel from "./admin/AuditPanel";
import ContributionsPanel from "./admin/ContributionsPanel";
import SnapshotsPanel from "./admin/SnapshotsPanel";
import {
  AuthorPicker,
  CodePicker,
  COUNTRY_OPTIONS,
  countryLabel,
  LANG_OPTIONS,
  langLabel,
  authorLabelOf,
  workLabel,
  WorkPicker,
} from "./admin/pickers";
import { authorDisplayNames, edgeDisplayLabel } from "./admin/query";

// 从 URL 中移除 admin 入口参数/片段,恢复到普通页面状态
function stripAdminFromUrl(): void {
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete("admin");
    if (url.hash.indexOf("admin") !== -1) url.hash = "#v=main";
    history.replaceState(null, "", url.toString());
  } catch { /* ignore */ }
}

const KINDS: { key: AdminTab; label: string }[] = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
  { key: "contributions", label: "贡献" },
  { key: "audit", label: "审计" },
  { key: "snapshots", label: "快照" },
];

const COLS: Record<AdminTab, { key: string; label: string }[]> = {
  authors: [
    { key: "Name_CN", label: "中文名" },
    { key: "originalName", label: "原文名" },
    { key: "nationality", label: "国家" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  works: [
    { key: "Title_CN", label: "中文名" },
    { key: "originalTitle", label: "原著标题" },
    { key: "author_id", label: "作者" },
    { key: "publicationYear", label: "年份" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  edges: [
    { key: "source_work_id", label: "源作品" },
    { key: "target_work_id", label: "目标作品" },
    { key: "reviewStatus", label: "审核" },
    { key: "evidenceSource", label: "出处" },
  ],
  contributions: [],
  audit: [],
  snapshots: [],
};

// 表单字段配置
const FIELDS: Record<AdminTab, any[]> = {
  authors: [
    { key: "originalName", label: "原文名", required: true },
    { key: "nationality", label: "国家", type: "countryPicker" },
    { key: "Name_CN", label: "中文名", required: true },
    { key: "Name_EN", label: "英文名" },
    { key: "birthYear", label: "出生年份", type: "number", min: -9999, max: 9999 },
    { key: "deathYear", label: "去世年份", type: "number", min: -9999, max: 9999 },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  works: [
    { key: "language", label: "原著语言", required: true, type: "languagePicker" },
    { key: "originalTitle", label: "原著标题", required: true },
    { key: "Title_CN", label: "中文名", required: true },
    { key: "Title_EN", label: "英文名" },
    { key: "Title_Other", label: "其他标题" },
    { key: "author_id", label: "作者", type: "authorPicker" },
    { key: "publicationYear", label: "出版年份", type: "number" },
    { key: "creationYear", label: "创作年份", type: "number" },
    { key: "genre", label: "体裁", type: "select", options: ["Fiction", "Non-fiction", "Poetry", "Drama"] },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  edges: [
    { key: "source_work_id", label: "源作品", required: true, type: "workPicker" },
    { key: "target_work_id", label: "目标作品", required: true, type: "workPicker" },
    { key: "evidence", label: "原文片段", required: true, type: "textarea" },
    { key: "evidenceSource", label: "出处", required: true },
    { key: "note", label: "备注" },
    { key: "reviewStatus", label: "审核", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  contributions: [],
  audit: [],
  snapshots: [],
};

function contributionStatusLabel(s: string): string {
  return s === "approved" ? "已通过" : s === "rejected" ? "已驳回" : "待审核";
}

export default function Admin() {
  const { state, dispatch } = useApp();
  const [kind, setKind] = useState<AdminTab>("authors");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [contribs, setContribs] = useState<any[]>([]);
  const [contribsLoading, setContribsLoading] = useState(false);
  const [contribCount, setContribCount] = useState(0);
  const [viewContrib, setViewContrib] = useState<any>(null);
  const [confirmState, setConfirmState] = useState<{
    title: string;
    message: string;
    danger?: boolean;
    onConfirm: () => void;
  } | null>(null);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<any>(null);
  const [dupHints, setDupHints] = useState<Record<string, string>>({});
  const [modal, setModal] = useState<any>(null); // { mode: "add" | "edit", row: {} }
  const [form, setForm] = useState<any>({});
  const [formError, setFormError] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [authInput, setAuthInput] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [token, setToken] = useState(() => getAdminToken());

  // 未授权时自动弹出令牌授权弹窗(深链 #v=admin / ?admin 进入的场景)
  useEffect(() => {
    if (state.adminOpen && !token) setAuthOpen(true);
  }, [state.adminOpen, token]);

  const authFetch = useCallback((url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", "Bearer " + token);
    return fetch(url, { ...options, headers });
  }, [token]);

  const handleAuthError = (r: Response): boolean => {
    if (r.status === 401 || r.status === 403) {
      // 清除失效令牌,自动重新弹出授权框(token 置空后下方 effect 会打开)
      clearAdminToken();
      setToken("");
      setStatus("管理令牌无效或缺失,请重新授权");
      return true;
    }
    return false;
  };

  // 取消授权:有令牌时仅关弹窗;未授权用户(误入)直接退出管理页并清理 URL
  const cancelAuth = () => {
    setAuthOpen(false);
    if (!token) {
      stripAdminFromUrl();
      dispatch({ type: "SET_ADMIN", open: false });
    }
  };

  // 校验令牌:有效则保存并授权,「获取授权」变为「已授权」
  const doAuthorize = () => {
    const value = authInput.trim();
    if (!value) {
      setAuthError("请输入令牌");
      return;
    }
    setAuthBusy(true);
    fetch("/api/admin/data", { headers: { Authorization: "Bearer " + value } })
      .then((r) => {
        if (r.status === 401 || r.status === 403) {
          setAuthError("令牌无效,请重试");
          return null;
        }
        if (!r.ok) {
          setAuthError("校验失败(状态码 " + r.status + ")");
          return null;
        }
        return r.json();
      })
      .then((d) => {
        if (!d) return;
        setAdminToken(value);
        setToken(value); // token 变化后 load() 会随 useEffect 自动重新拉取数据
        setAuthOpen(false);
        setAuthInput("");
        setStatus("已授权");
        dispatch({ type: "SET_ADMIN_READY", value: true }); // 授权后显示"数据管理"按钮
      })
      .catch((e) => setAuthError("校验失败: " + e.message))
      .finally(() => setAuthBusy(false));
  };

  const doLogout = () => {
    setLogoutOpen(false);
    clearAdminToken();
    setToken("");
    dispatch({ type: "SET_ADMIN_READY", value: false });
    closeAdmin();
    setStatus("已退出授权");
  };

  const openLogoutConfirm = () => setLogoutOpen(true);

  // 关闭管理页;同时清理 URL 中的 admin 入口参数/片段
  const closeAdmin = () => {
    stripAdminFromUrl();
    dispatch({ type: "SET_ADMIN", open: false });
  };

  const load = useCallback(() => {
    setLoading(true);
    authFetch("/api/admin/data")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          setLoading(false);
          return null;
        }
        return r.json();
      })
      .then((d) => {
        if (d) {
          setData(d);
          setWarnings(d.warnings || null);
          setLoading(false);
        }
      })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  // 贡献收件箱:按状态拉取列表(供"贡献"Tab 使用)
  const loadContribs = useCallback(() => {
    setContribsLoading(true);
    authFetch("/api/admin/contributions?limit=500")
      .then((r) => r.json())
      .then((d) => {
        const items = d.items || [];
        setContribs(items);
        // Tab 角标保持"待审核"数(筛选/排序由表格内完成)
        setContribCount(items.filter((c: any) => c.status === "pending").length);
        setContribsLoading(false);
      })
      .catch((e) => { setStatus("加载贡献失败: " + e.message); setContribsLoading(false); });
  }, [authFetch]);

  useEffect(() => {
    if (kind === "contributions") loadContribs();
  }, [kind, loadContribs]);

  // 打开管理页即加载待审核数,让"贡献"Tab 角标未切换过去时也显示正确数字
  useEffect(() => {
    loadContribs();
  }, [loadContribs]);

  if (!state.adminOpen) return null;

  const allRows: any[] = data ? data[kind] || [] : [];
  const cols = COLS[kind];
  const counts = data ? data.counts || {} : {};

  // Tab 角标计数:贡献/审计为特殊 Tab,避免对不存在的 data[k] 取值
  const tabCount = (k: AdminTab): string => {
    if (k === "contributions") return String(contribCount);
    if (k === "audit" || k === "snapshots") return "";
    return counts[k] != null ? String(counts[k]) : (data ? String((data[k] || []).length) : "");
  };

  // 每类数据的可筛选列:select 为精确下拉,text 为按列搜索框
  const filterCols: Record<AdminTab, { key: string; type: "select" | "text" }[]> = {
    authors: [
      { key: "reviewStatus", type: "select" },
      { key: "nationality", type: "select" },
      { key: "Name_CN", type: "text" },
      { key: "originalName", type: "text" },
    ],
    works: [
      { key: "reviewStatus", type: "select" },
      { key: "genre", type: "select" },
      { key: "language", type: "select" },
      { key: "Title_CN", type: "text" },
      { key: "originalTitle", type: "text" },
      { key: "author_id", type: "text" },
      { key: "publicationYear", type: "text" },
    ],
    edges: [
      { key: "reviewStatus", type: "select" },
      { key: "source_work_id", type: "text" },
      { key: "target_work_id", type: "text" },
      { key: "evidenceSource", type: "text" },
    ],
    contributions: [],
    audit: [],
    snapshots: [],
  };
  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(allRows.map((r) => String(r[key] || "")).filter(Boolean))).sort((a, b) => a.localeCompare(b));

  const toggleSort = (key: string) => {
    setSort((prev) => {
      if (prev && prev.key === key) return prev.dir === 1 ? { key, dir: -1 } : null;
      return { key, dir: 1 };
    });
  };

  const switchKind = (k: AdminTab) => {
    setKind(k);
    setModal(null);
    setFilters({});
    setTextFilters({});
    setSort(null);
  };

  const openAdd = () => {
    setForm({ reviewStatus: "draft" }); // 新增默认草稿(表单中不展示该字段)
    setFormError("");
    setModal({ mode: "add", row: {} });
  };

  const openEdit = (row: any) => {
    setForm({ ...row });
    setFormError("");
    setModal({ mode: "edit", row });
  };

  // 乐观更新:成功后直接改本地 data,不再整页重拉(仅刷新同步状态)
  const applyLocal = (updater: (prev: AdminData) => AdminData) => {
    if (data) setData(updater(data));
  };

  const doDelete = (row: any) => {
    const id = row.id;
    setConfirmState({
      title: "确认删除",
      message: `确认删除「${rowLabel(row)}」?(软删除,可恢复,关联的作品/涟漪将一并软删除)`,
      danger: true,
      onConfirm: () => {
        authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
          .then((r) => r.json())
          .then((d) => {
            const cascade = d.cascade || {};
            const parts: string[] = [];
            if (cascade.works && cascade.works.length) parts.push(cascade.works.length + " 部作品");
            if (cascade.edges && cascade.edges.length) parts.push(cascade.edges.length + " 条涟漪");
            setStatus(
              d.ok
                ? `已软删除「${rowLabel(row)}」${parts.length ? ",连带 " + parts.join(" / ") : ""}`
                : (d.detail || "删除失败")
            );
            if (d.ok) {
              setModal(null); // 从编辑弹窗删除后关闭弹窗
              const key = kind as "authors" | "works" | "edges";
              applyLocal((prev) => ({
                ...prev,
                [key]: (prev[key] || []).map((r: any) =>
                  r.id === id ? { ...r, deletedAt: d.deletedAt } : r
                ),
              }));
            }
          })
          .catch((e) => setStatus("删除失败: " + e.message));
      },
    });
  };

  const doRestore = (id: string) => {
    const row = allRows.find((r) => r.id === id);
    if (!row) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id) + "/restore", { method: "POST" })
      .then((r) => r.json())
      .then((d) => {
        const cascade = d.cascade || {};
        const parts: string[] = [];
        if (cascade.works && cascade.works.length) parts.push(cascade.works.length + " 部作品");
        if (cascade.edges && cascade.edges.length) parts.push(cascade.edges.length + " 条涟漪");
        setStatus(
          d.ok
            ? `已恢复「${rowLabel(row)}」${parts.length ? ",连带恢复 " + parts.join(" / ") : ""}`
            : (d.detail || "恢复失败")
        );
        if (d.ok) {
          const key = kind as "authors" | "works" | "edges";
          applyLocal((prev) => ({
            ...prev,
            [key]: (prev[key] || []).map((r: any) =>
              r.id === id ? { ...r, deletedAt: null } : r
            ),
          }));
        }
      })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  const saveForm = () => {
    // 前端必填校验
    const fields = FIELDS[kind];
    for (const f of fields) {
      if (f.required && !String(form[f.key] || "").trim()) {
        setFormError("请填写「" + f.label + "」");
        return;
      }
      if (f.type === "number" && (f.min != null || f.max != null) && form[f.key] !== "" && form[f.key] != null) {
        const n = Number(form[f.key]);
        if (!Number.isInteger(n) || n < f.min || n > f.max) {
          setFormError("「" + f.label + "」需为 " + f.min + "–" + f.max + " 之间的整数");
          return;
        }
      }
    }
    setFormError("");
    // 基础清洗:字符串去首尾空白,空串统一归一为 null
    // (同时避免数字/日期字段清空后发送 "" 触发后端 int 解析失败)
    const payload = Object.fromEntries(
      Object.entries(form).map(([k, v]) => [k, typeof v === "string" ? (v.trim() || null) : v])
    );
    const url = modal.mode === "edit"
      ? "/api/admin/" + kind + "/" + encodeURIComponent(modal.row.id)
      : "/api/admin/" + kind;
    authFetch(url, {
      method: modal.mode === "edit" ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, status: r.status, data: d })))
      .then((res) => {
        if (!res.ok) {
          if (res.status === 409) {
            setFormError(res.data.detail || "数据已被其他人修改");
            setConfirmState({
              title: "版本冲突",
              message: "数据已被其他人修改,是否重新加载最新数据?(你的修改将丢失)",
              onConfirm: () => { setModal(null); load(); },
            });
            return;
          }
          setFormError(res.data.detail || "保存失败");
          return;
        }
        setModal(null);
        setStatus(modal.mode === "edit" ? "已更新" : "已新增");
        const key = kind as "authors" | "works" | "edges";
        applyLocal((prev) => {
          const list = (prev[key] || []) as any[];
          if (modal.mode === "edit") {
            return { ...prev, [key]: list.map((r: any) => (r.id === res.data.row.id ? res.data.row : r)) };
          }
          return { ...prev, [key]: [...list, res.data.row] };
        });
      })
      .catch((e) => setFormError("请求失败: " + e.message));
  };

  const worksList = data ? data.works || [] : [];
  const authorsList = data ? data.authors || [] : [];
  const worksById: Record<string, any> = {};
  const authorsById: Record<string, any> = {};
  worksList.forEach((w: any) => { worksById[w.id] = w; });
  authorsList.forEach((a: any) => { authorsById[a.id] = a; });

  // 行显示名(删除确认/状态提示用):作者名 / 作品标题 / 涟漪 A → B
  const rowLabel = (row: any): string => {
    if (kind === "authors") return authorLabelOf(row);
    if (kind === "works") return workLabel(row);
    return edgeDisplayLabel(row, worksById, workLabel);
  };

  // 单元格显示值(与表格渲染一致,排序/筛选共用)
  const cellValue = (r: any, key: string): string => {
    if (kind === "edges" && (key === "source_work_id" || key === "target_work_id")) {
      const w = worksById[r[key]];
      return w ? workLabel(w) : String(r[key] ?? "");
    }
    if (kind === "works" && key === "author_id") {
      return authorDisplayNames(r, authorsById, authorLabelOf);
    }
    const v = r[key];
    return v == null ? "" : String(v);
  };

  // ---- 去重即时提示(L2):表单字段失焦 / 涟漪对选定后本地比对 ----
  const dupFields: Record<AdminTab, string[]> = {
    authors: ["Name_CN", "originalName"],
    works: ["Title_CN", "originalTitle"],
    edges: [],
    contributions: [],
    audit: [],
    snapshots: [],
  };
  const selfId = modal?.mode === "edit" ? modal.row.id : undefined;
  const fieldHasDup = (field: string, value: string): boolean => {
    const list = kind === "authors" ? authorsList : worksList;
    const v = String(value || "").trim().toLowerCase();
    if (!v) return false;
    return list.some((r: any) => r.id !== selfId && String(r[field] || "").trim().toLowerCase() === v);
  };
  const edgePairHasDup = (s: string, t: string): boolean => {
    if (!s || !t || !data) return false;
    return data.edges.some((r: any) => r.id !== selfId && r.source_work_id === s && r.target_work_id === t);
  };
  const edgeDupMsg =
    kind === "edges" && modal && edgePairHasDup(form.source_work_id, form.target_work_id)
      ? "该涟漪关系已存在"
      : "";

  const clearDupHint = (key: string) => {
    setDupHints((h) => {
      if (!h[key]) return h;
      const next = { ...h };
      delete next[key];
      return next;
    });
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2
              className={"admin-title" + (token ? " clickable" : "")}
              title={token ? "点击退出授权" : undefined}
              onClick={token ? openLogoutConfirm : undefined}
            >
              数据管理
            </h2>
            <div className="admin-tabs">
              {KINDS.map((k) => (
                <button
                  key={k.key}
                  className={"admin-tab" + (kind === k.key ? " active" : "")}
                  data-kind={k.key}
                  onClick={() => switchKind(k.key)}
                >
                  {k.label} <span className="cnt">{tabCount(k.key)}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="admin-actions">
            {kind !== "contributions" && kind !== "audit" && kind !== "snapshots" && <button onClick={openAdd}>＋ 新增</button>}
            <button id="admin-close" onClick={closeAdmin}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        {warnings && Boolean(warnings.duplicateAuthorNames?.length || warnings.duplicateWorkTitles?.length || warnings.duplicateEdgePairs?.length) && (
          <div id="admin-warnings">
            ⚠ 重复提醒:
            {warnings.duplicateAuthorNames?.length ? " 作者名:" + warnings.duplicateAuthorNames.join("、") : ""}
            {warnings.duplicateWorkTitles?.length ? " 作品标题:" + warnings.duplicateWorkTitles.join("、") : ""}
            {warnings.duplicateEdgePairs?.length ? " 涟漪对:" + warnings.duplicateEdgePairs.join("、") : ""}
          </div>
        )}
        {authOpen && (
          <div id="auth-modal">
            <div className="auth-modal-card">
              <h3>请输入令牌</h3>
              <input
                type="password"
                placeholder="管理令牌"
                value={authInput}
                autoFocus
                onChange={(e) => {
                  setAuthInput(e.target.value);
                  setAuthError("");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") doAuthorize();
                  if (e.key === "Escape") cancelAuth();
                }}
              />
              {authError && <div className="auth-error">{authError}</div>}
              <div className="admin-modal-actions">
                <button onClick={doAuthorize} disabled={authBusy}>{authBusy ? "校验中…" : "确认"}</button>
                <button onClick={cancelAuth}>取消</button>
              </div>
            </div>
          </div>
        )}
        {logoutOpen && (
          <div id="auth-modal">
            <div className="auth-modal-card">
              <h3>退出授权</h3>
              <p>确定退出授权吗?</p>
              <div className="admin-modal-actions">
                <button className="del" onClick={doLogout}>确认</button>
                <button onClick={() => setLogoutOpen(false)}>取消</button>
              </div>
            </div>
          </div>
        )}
        {confirmState && (
          <div id="auth-modal">
            <div className="auth-modal-card">
              <h3>{confirmState.title}</h3>
              <p>{confirmState.message}</p>
              <div className="admin-modal-actions">
                <button
                  className={confirmState.danger ? "del" : undefined}
                  onClick={() => {
                    const run = confirmState.onConfirm;
                    setConfirmState(null);
                    run();
                  }}
                >
                  确认
                </button>
                <button onClick={() => setConfirmState(null)}>取消</button>
              </div>
            </div>
          </div>
        )}
        <div className="admin-body">
          {kind === "contributions" ? (
            <ContributionsPanel
              items={contribs}
              loading={contribsLoading}
              sort={sort}
              filters={filters}
              textFilters={textFilters}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
              onView={setViewContrib}
            />
          ) : kind === "audit" ? (
            <AuditPanel
              authFetch={authFetch}
              sort={sort}
              filters={filters}
              textFilters={textFilters}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
            />
          ) : kind === "snapshots" ? (
            <SnapshotsPanel authFetch={authFetch} />
          ) : loading ? <p>加载中…</p> : (
            <AdminTable
              kind={kind}
              cols={cols}
              rows={allRows}
              filterCols={filterCols[kind]}
              filters={filters}
              textFilters={textFilters}
              sort={sort}
              cellValue={cellValue}
              uniqueValues={uniqueValues}
              onSort={toggleSort}
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
              renderActions={(r) =>
                r.deletedAt
                  ? <button onClick={() => doRestore(r.id)}>恢复</button>
                  : <button onClick={() => openEdit(r)}>编辑</button>
              }
            />
          )}
        </div>
        {viewContrib && (
          <div id="admin-modal" style={{ display: "flex" }}>
            <div className="admin-modal-card">
              <h3>贡献详情</h3>
              <div id="admin-form">
                <label>
                  <span>源作品(提及方)</span>
                  <input readOnly value={viewContrib.source_work || ""} />
                </label>
                <label>
                  <span>源作品作者</span>
                  <input readOnly value={viewContrib.source_author || ""} />
                </label>
                <label>
                  <span>目标作品(被提及方)</span>
                  <input readOnly value={viewContrib.target_work || ""} />
                </label>
                <label>
                  <span>目标作品作者</span>
                  <input readOnly value={viewContrib.target_author || ""} />
                </label>
                <label className="full">
                  <span>原文片段</span>
                  <textarea readOnly value={viewContrib.evidence || ""} />
                </label>
                <label>
                  <span>出处(章节/页码/译本)</span>
                  <input readOnly value={viewContrib.evidence_source || ""} />
                </label>
                <label className="full">
                  <span>备注</span>
                  <textarea readOnly value={viewContrib.note || ""} />
                </label>
                <label>
                  <span>联系方式</span>
                  <input readOnly value={viewContrib.contact || ""} />
                </label>
                <label>
                  <span>提交时间</span>
                  <input readOnly value={viewContrib.created_at || ""} />
                </label>
                <label>
                  <span>审核状态</span>
                  <input readOnly value={contributionStatusLabel(viewContrib.status || "")} />
                </label>
              </div>
              <div className="admin-modal-actions">
                <button onClick={() => setViewContrib(null)}>关闭</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {modal && (
        <div id="admin-modal" style={{ display: "flex" }}>
          <div className="admin-modal-card">
            <h3>{modal.mode === "edit" ? "编辑" : "新增"} {KINDS.find((k) => k.key === kind)!.label}</h3>
            <div id="admin-form">
              {FIELDS[kind].map((f) => {
                if (modal.mode === "add" && f.key === "reviewStatus") return null; // 新增弹窗不显示审核状态
                if (f.type === "workPicker") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <WorkPicker
                        value={form[f.key] || ""}
                        onChange={(v) => {
                          setForm({ ...form, [f.key]: v });
                          clearDupHint(f.key);
                        }}
                        worksList={worksList}
                        placeholder="输入筛选并选择…"
                      />
                      {edgeDupMsg && <div className="dup-hint">{edgeDupMsg}</div>}
                    </label>
                  );
                }
                if (f.type === "authorPicker") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <AuthorPicker
                        value={form[f.key] || ""}
                        onChange={(v) => setForm({ ...form, [f.key]: v })}
                        authorsList={authorsList}
                        placeholder="输入筛选作者,可多选…"
                      />
                    </label>
                  );
                }
                if (f.type === "languagePicker") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <CodePicker
                        value={form[f.key] || ""}
                        onChange={(v) => setForm({ ...form, [f.key]: v })}
                        options={LANG_OPTIONS}
                        getLabel={langLabel}
                        placeholder="输入中文或代码筛选…"
                        emptyWarn="没有匹配的语言,只能选择列表中的语言"
                      />
                    </label>
                  );
                }
                if (f.type === "countryPicker") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <CodePicker
                        value={form[f.key] || ""}
                        onChange={(v) => setForm({ ...form, [f.key]: v })}
                        options={COUNTRY_OPTIONS}
                        getLabel={countryLabel}
                        placeholder="输入中文或代码筛选…"
                        emptyWarn="没有匹配的国家/地区,只能选择列表中的国家/地区"
                      />
                    </label>
                  );
                }
                if (f.type === "textarea") {
                  return (
                    <label key={f.key} className="full">
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <textarea
                        value={form[f.key] || ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      />
                    </label>
                  );
                }
                if (f.type === "select") {
                  return (
                    <label key={f.key}>
                      <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                      <select
                        value={form[f.key] || ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      >
                        <option value="">请选择…</option>
                        {f.options.map((o: any) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    </label>
                  );
                }
                return (
                  <label key={f.key}>
                    <span>{f.label}{f.required && <span className="req"> *</span>}</span>
                    <input
                      type={f.type === "number" ? "number" : "text"}
                      min={f.min}
                      max={f.max}
                      step={f.type === "number" ? (f.step != null ? f.step : 1) : undefined}
                      value={form[f.key] ?? ""}
                      onChange={(e) => {
                        setForm({ ...form, [f.key]: e.target.value });
                        clearDupHint(f.key);
                      }}
                      onBlur={() => {
                        if (!dupFields[kind].includes(f.key)) return;
                        const msg = fieldHasDup(f.key, form[f.key]) ? "该「" + f.label + "」已存在" : "";
                        setDupHints((h) => {
                          const next = { ...h };
                          if (msg) next[f.key] = msg;
                          else delete next[f.key];
                          return next;
                        });
                      }}
                    />
                    {dupHints[f.key] && <div className="dup-hint">{dupHints[f.key]}</div>}
                  </label>
                );
              })}
            </div>
            {formError && <div id="admin-form-errors">{formError}</div>}
            <div className="admin-modal-actions">
              {modal.mode === "edit" && (
                <button className="del" onClick={() => doDelete(modal.row)}>删除</button>
              )}
              <div className="admin-modal-actions-right">
                <button onClick={saveForm}>保存</button>
                <button onClick={() => setModal(null)}>取消</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
