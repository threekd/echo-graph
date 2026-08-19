import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../store";
import iso6391 from "../lib/iso6391.json";
import iso3166 from "../lib/iso3166-1.json";

const iso6391Map = iso6391 as Record<string, string>;
const iso3166Map = iso3166 as Record<string, string>;

type Kind = "authors" | "works" | "edges";

const KINDS: { key: Kind; label: string }[] = [
  { key: "authors", label: "作者" },
  { key: "works", label: "作品" },
  { key: "edges", label: "涟漪" },
];

const COLS: Record<Kind, { key: string; label: string }[]> = {
  authors: [
    { key: "Name_CN", label: "中文名" },
    { key: "originalName", label: "原文名" },
    { key: "nationality", label: "国籍" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  works: [
    { key: "Title_CN", label: "中文名" },
    { key: "originalTitle", label: "原著标题" },
    { key: "Author", label: "作者" },
    { key: "publicationYear", label: "年份" },
    { key: "reviewStatus", label: "审核状态" },
  ],
  edges: [
    { key: "source_work_id", label: "源作品" },
    { key: "target_work_id", label: "目标作品" },
    { key: "reviewStatus", label: "审核" },
    { key: "deletedAt", label: "删除时间" },
  ],
};

// 表单字段配置
const FIELDS: Record<Kind, any[]> = {
  authors: [
    { key: "originalName", label: "原文名", required: true },
    { key: "nationality", label: "国籍", type: "countryPicker" },
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
    { key: "Author", label: "作者", type: "authorPicker" },
    { key: "publicationYear", label: "出版年份", type: "number" },
    { key: "creationYear", label: "创作年份", type: "number" },
    { key: "genre", label: "体裁", type: "select", options: ["Fiction", "Non-fiction", "Poetry", "Drama"] },
    { key: "reviewStatus", label: "审核状态", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
  edges: [
    { key: "source_work_id", label: "源作品", required: true, type: "workPicker" },
    { key: "target_work_id", label: "目标作品", required: true, type: "workPicker" },
    { key: "evidence", label: "原文片段", required: true, type: "textarea" },
    { key: "evidenceSource", label: "出处" },
    { key: "note", label: "备注" },
    { key: "reviewStatus", label: "审核", type: "select", options: ["draft", "reviewed", "rejected"] },
  ],
};

function workLabel(w: any): string {
  return w ? (w.Title_CN || "") + " - " + (w.originalTitle || "") : "";
}

// ISO 639-1 语言选项,格式为「代码-中文名」(如 en-英语)
const LANG_OPTIONS = Object.entries(iso6391Map).map(([code, name]) => ({ value: code, label: code + "-" + name }));

function langLabel(code: string): string {
  if (!code) return "";
  const name = iso6391Map[code];
  return name ? code + "-" + name : code;
}

// ISO 3166-1 国家/地区选项,格式为「代码-中文名」(如 CN-中国)
const COUNTRY_OPTIONS = Object.entries(iso3166Map).map(([code, name]) => ({ value: code, label: code + "-" + name }));

function countryLabel(code: string): string {
  if (!code) return "";
  const name = iso3166Map[code];
  return name ? code + "-" + name : code;
}

// 边有独立 id;source:target 仅作历史数据的兜底复合标识
function edgeKey(r: any): string {
  return (r.source_work_id || "") + ":" + (r.target_work_id || "");
}

// 作品选择器:输入筛选,只能点选/回车选择已存在条目(不接收自由输入)
function WorkPicker({
  value,
  onChange,
  worksList,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  worksList: any[];
  placeholder: string;
}) {
  const [query, setQuery] = useState(() => {
    const w = worksList.find((x) => x.id === value);
    return w ? workLabel(w) : "";
  });
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const lastValue = useRef(value);

  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      const w = worksList.find((x) => x.id === value);
      if (w) setQuery(workLabel(w));
    }
  }, [value, worksList]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? worksList.filter((w) =>
        [w.Title_CN, w.originalTitle, w.Title_EN, w.Author].filter(Boolean).join(" ").toLowerCase().includes(q)
      )
    : worksList;

  const pick = (w: any) => {
    onChange(w.id);
    setQuery(workLabel(w));
    setOpen(false);
  };

  return (
    <div className="work-picker" ref={wrapRef}>
      <input
        type="text"
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          if (value) onChange(""); // 手动编辑即取消已选,必须重新选择已存在条目
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          const w = worksList.find((x) => x.id === value);
          setQuery(w ? workLabel(w) : "");
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && open && filtered.length) {
            e.preventDefault();
            pick(filtered[0]);
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul className="work-picker-results" style={{ display: "block" }}>
          {filtered.slice(0, 80).map((w) => (
            <li
              key={w.id}
              onMouseDown={(e) => {
                e.preventDefault(); // 先于 blur 触发,避免失焦清空
                pick(w);
              }}
            >
              {workLabel(w)}
            </li>
          ))}
        </ul>
      )}
      {open && q && filtered.length === 0 && (
        <div className="work-picker-warn">没有匹配的作品,只能选择已存在条目</div>
      )}
    </div>
  );
}

// 代码选择器(语言/国家/地区):输入中文或代码筛选,只能点选/回车选择列表项(不接收自由输入)
function CodePicker({
  value,
  onChange,
  options,
  getLabel,
  placeholder,
  emptyWarn,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  getLabel: (code: string) => string;
  placeholder: string;
  emptyWarn: string;
}) {
  const [query, setQuery] = useState(() => getLabel(value));
  const [open, setOpen] = useState(false);
  const [dir, setDir] = useState("down");
  const [maxH, setMaxH] = useState(220);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const lastValue = useRef(value);

  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      const label = getLabel(value);
      if (label) setQuery(label);
    }
  }, [value, getLabel]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? options.filter((o) => o.label.toLowerCase().includes(q))
    : options;

  const pick = (opt: { value: string; label: string }) => {
    onChange(opt.value);
    setQuery(opt.label);
    setOpen(false);
  };

  // 按可用空间决定下拉展开方向与高度,避免溢出弹窗卡片产生滚动条
  const openList = () => {
    const el = wrapRef.current;
    if (!el) {
      setOpen(true);
      return;
    }
    const rect = el.getBoundingClientRect();
    const card = el.closest(".admin-modal-card");
    const cardRect = card ? card.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const below = cardRect.bottom - rect.bottom;
    const above = rect.top - cardRect.top;
    const useUp = above > below;
    setDir(useUp ? "up" : "down");
    setMaxH(Math.max(110, Math.min(220, (useUp ? above : below) - 8)));
    setOpen(true);
  };

  return (
    <div className="work-picker" ref={wrapRef}>
      <input
        type="text"
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          if (value) onChange(""); // 手动编辑即取消已选,必须重新选择已存在条目
          setOpen(true);
        }}
        onFocus={openList}
        onBlur={() => {
          setQuery(getLabel(value));
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Enter" && open && filtered.length) {
            e.preventDefault();
            pick(filtered[0]);
          }
        }}
      />
      {open && filtered.length > 0 && (
        <ul
          className={"work-picker-results" + (dir === "up" ? " up" : "")}
          style={{ display: "block", maxHeight: maxH }}
        >
          {filtered.map((o) => (
            <li
              key={o.value}
              onMouseDown={(e) => {
                e.preventDefault(); // 先于 blur 触发,避免失焦清空
                pick(o);
              }}
            >
              {o.label}
            </li>
          ))}
        </ul>
      )}
      {open && q && filtered.length === 0 && (
        <div className="work-picker-warn">{emptyWarn}</div>
      )}
    </div>
  );
}

function authorLabelOf(a: any): string {
  const name = a.Name_CN || a.originalName || "";
  return a.birthYear ? name + "-" + a.birthYear : name;
}

// 把逗号分隔的 Author 字符串解析为 [{ value: 原文名, label: 显示名 }]
function parseAuthors(value: string, authorsList: any[]): { value: string; label: string }[] {
  return String(value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((name) => {
      const a = authorsList.find((x) => x.originalName === name || x.Name_CN === name || x.Name_EN === name);
      return a ? { value: a.originalName, label: authorLabelOf(a) } : { value: name, label: name };
    });
}

// 作者多选选择器:从作者表筛选,可添加多个作者(存储为逗号分隔的原文名)
function AuthorPicker({
  value,
  onChange,
  authorsList,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  authorsList: any[];
  placeholder: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [dir, setDir] = useState("down");
  const [maxH, setMaxH] = useState(220);
  const [selected, setSelected] = useState(() => parseAuthors(value, authorsList));
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const lastValue = useRef(value);

  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      setSelected(parseAuthors(value, authorsList));
    }
  }, [value, authorsList]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? authorsList.filter((a) =>
        (authorLabelOf(a) + " " + (a.originalName || "") + " " + (a.Name_EN || "")).toLowerCase().includes(q)
      )
    : authorsList;
  const available = filtered.filter((a) => !selected.some((s) => s.value === a.originalName));

  const commit = (next: { value: string; label: string }[]) => {
    setSelected(next);
    onChange(next.map((s) => s.value).join(", "));
  };

  const addAuthor = (a: any) => {
    if (selected.some((s) => s.value === a.originalName)) return;
    commit([...selected, { value: a.originalName, label: authorLabelOf(a) }]);
    setQuery("");
  };

  const removeAuthor = (v: string) => commit(selected.filter((s) => s.value !== v));

  // 按可用空间决定下拉展开方向与高度,避免溢出弹窗卡片产生滚动条
  const openList = () => {
    const el = wrapRef.current;
    if (!el) {
      setOpen(true);
      return;
    }
    const rect = el.getBoundingClientRect();
    const card = el.closest(".admin-modal-card");
    const cardRect = card ? card.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const below = cardRect.bottom - rect.bottom;
    const above = rect.top - cardRect.top;
    const useUp = above > below;
    setDir(useUp ? "up" : "down");
    setMaxH(Math.max(110, Math.min(220, (useUp ? above : below) - 8)));
    setOpen(true);
  };

  return (
    <div className="work-picker author-picker" ref={wrapRef}>
      {selected.length > 0 && (
        <div className="author-picker-selected">
          {selected.map((s) => (
            <span key={s.value} className="author-chip">
              {s.label}
              <button type="button" title="移除" onClick={() => removeAuthor(s.value)}>×</button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={openList}
        onBlur={() => {
          setQuery("");
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
          if (e.key === "Backspace" && !query && selected.length) removeAuthor(selected[selected.length - 1].value);
          if (e.key === "Enter" && open && available.length) {
            e.preventDefault();
            addAuthor(available[0]);
          }
        }}
      />
      {open && available.length > 0 && (
        <ul
          className={"work-picker-results" + (dir === "up" ? " up" : "")}
          style={{ display: "block", maxHeight: maxH }}
        >
          {available.map((a) => (
            <li
              key={a.id}
              onMouseDown={(e) => {
                e.preventDefault(); // 先于 blur 触发,避免失焦关闭
                addAuthor(a);
              }}
            >
              {authorLabelOf(a)}
            </li>
          ))}
        </ul>
      )}
      {open && q && available.length === 0 && (
        <div className="work-picker-warn">没有匹配的作者,只能选择已存在的作者</div>
      )}
    </div>
  );
}

export default function Admin() {
  const { state, dispatch } = useApp();
  const [kind, setKind] = useState<Kind>("authors");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState<any>(null); // { mode: "add" | "edit", row: {} }
  const [form, setForm] = useState<any>({});
  const [formError, setFormError] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const [authInput, setAuthInput] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [token, setToken] = useState(() => {
    try { return sessionStorage.getItem("echo_graph_admin_token") || ""; } catch { return ""; }
  });

  const authFetch = useCallback((url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) headers.set("Authorization", "Bearer " + token);
    return fetch(url, { ...options, headers });
  }, [token]);

  const handleAuthError = (r: Response): boolean => {
    if (r.status === 401 || r.status === 403) {
      setStatus("管理令牌无效或缺失,请点击「获取授权」重新授权");
      return true;
    }
    return false;
  };

  // 打开授权对话框
  const openAuth = () => {
    setAuthInput("");
    setAuthError("");
    setAuthOpen(true);
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
        try { sessionStorage.setItem("echo_graph_admin_token", value); } catch { /* ignore */ }
        setToken(value); // token 变化后 load() 会随 useEffect 自动重新拉取数据
        setAuthOpen(false);
        setAuthInput("");
        setStatus("已授权");
      })
      .catch((e) => setAuthError("校验失败: " + e.message))
      .finally(() => setAuthBusy(false));
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
      .then((d) => { if (d) { setData(d); setLoading(false); } })
      .catch((e) => { setStatus("加载失败: " + e.message); setLoading(false); });
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  if (!state.adminOpen) return null;

  const allRows: any[] = data ? data[kind] || [] : [];
  const rows = search.trim()
    ? allRows.filter((r) => Object.values(r).some((v) => v != null && String(v).toLowerCase().includes(search.toLowerCase())))
    : allRows;
  const cols = COLS[kind];
  const counts = data ? data.counts || {} : {};

  const switchKind = (k: Kind) => {
    setKind(k);
    setSearch("");
    setModal(null);
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

  const doDelete = (id: string) => {
    if (!window.confirm("确认删除「" + id + "」?(软删除,可恢复)")) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), { method: "DELETE" })
      .then((r) => r.json())
      .then((d) => { setStatus(d.ok ? "已软删除" : (d.detail || "删除失败")); load(); })
      .catch((e) => setStatus("删除失败: " + e.message));
  };

  const doRestore = (id: string) => {
    const row = allRows.find((r) => (r.id || edgeKey(r)) === id);
    if (!row) return;
    authFetch("/api/admin/" + kind + "/" + encodeURIComponent(id), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...row, deletedAt: null }),
    })
      .then((r) => r.json())
      .then((d) => {
        setStatus(d.ok ? "已恢复,需重新导入 Neo4j 后生效" : (d.detail || "恢复失败"));
        load();
      })
      .catch((e) => setStatus("恢复失败: " + e.message));
  };

  const doImport = () => {
    if (!window.confirm("将 data/real/*.csv 写入 Neo4j(增量合并),继续?")) return;
    setStatus("导入中…");
    authFetch("/api/admin/import", {
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

  const exportJson = () => {
    authFetch("/api/admin/export/json")
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          return null;
        }
        return r.blob();
      })
      .then((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "echo-graph-data.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setStatus("导出失败: " + e.message));
  };

  const exportCsv = () => {
    authFetch("/api/admin/export/csv/" + kind)
      .then((r) => {
        if (!r.ok) {
          handleAuthError(r);
          return null;
        }
        return r.blob();
      })
      .then((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = kind + ".csv";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setStatus("导出失败: " + e.message));
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
    const url = modal.mode === "edit"
      ? "/api/admin/" + kind + "/" + encodeURIComponent(modal.row.id || edgeKey(modal.row))
      : "/api/admin/" + kind;
    authFetch(url, {
      method: modal.mode === "edit" ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    })
      .then((r) => r.json().then((d) => ({ ok: r.ok, data: d })))
      .then((res) => {
        if (!res.ok) {
          setFormError(res.data.detail || "保存失败");
          return;
        }
        setModal(null);
        setStatus(modal.mode === "edit" ? "已更新" : "已新增");
        load();
      })
      .catch((e) => setFormError("请求失败: " + e.message));
  };

  const worksList = data ? data.works || [] : [];
  const authorsList = data ? data.authors || [] : [];
  const worksById: Record<string, any> = {};
  worksList.forEach((w: any) => { worksById[w.id] = w; });

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
                onClick={() => switchKind(k.key)}
              >
                {k.label} <span className="cnt">{counts[k.key] != null ? counts[k.key] : (data ? data[k.key].length : "")}</span>
              </button>
            ))}
          </div>
          <div className="admin-actions">
            <input
              placeholder="搜索…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button id="btn-auth" className={token ? "authed" : ""} onClick={openAuth}>
              {token ? "已授权" : "获取授权"}
            </button>
            <button onClick={openAdd}>＋ 新增</button>
            <button onClick={doImport}>导入到 Neo4j</button>
            <button onClick={exportJson}>导出 JSON</button>
            <button onClick={exportCsv}>导出 CSV</button>
            <button id="admin-close" onClick={() => dispatch({ type: "SET_ADMIN", open: false })}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
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
                  if (e.key === "Escape") setAuthOpen(false);
                }}
              />
              {authError && <div className="auth-error">{authError}</div>}
              <div className="admin-modal-actions">
                <button onClick={doAuthorize} disabled={authBusy}>{authBusy ? "校验中…" : "确认"}</button>
                <button onClick={() => setAuthOpen(false)}>取消</button>
              </div>
            </div>
          </div>
        )}
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
                  <tr key={r.id || edgeKey(r)} className={r.deletedAt ? "deleted" : ""}>
                    {cols.map((c) => {
                      let val = r[c.key] ?? "";
                      if (kind === "edges" && (c.key === "source_work_id" || c.key === "target_work_id")) {
                        const w = worksById[r[c.key]];
                        val = w ? workLabel(w) : String(val);
                      }
                      return <td key={c.key}>{String(val)}</td>;
                    })}
                    <td>
                      {r.deletedAt
                        ? <button onClick={() => doRestore(r.id || edgeKey(r))}>恢复</button>
                        : (
                          <>
                            <button onClick={() => openEdit(r)}>编辑</button>
                            <button className="del" onClick={() => doDelete(r.id || edgeKey(r))}>删除</button>
                          </>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
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
                        onChange={(v) => setForm({ ...form, [f.key]: v })}
                        worksList={worksList}
                        placeholder="输入筛选并选择…"
                      />
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
                      onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    />
                  </label>
                );
              })}
            </div>
            {formError && <div id="admin-form-errors">{formError}</div>}
            <div className="admin-modal-actions">
              <button onClick={saveForm}>保存</button>
              <button onClick={() => setModal(null)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
