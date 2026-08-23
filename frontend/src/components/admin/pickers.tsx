/* 数据管理页的表单选择器组件与选项数据(从 Admin.tsx 拆出,降低单体体积) */

import { useEffect, useMemo, useRef, useState } from "react";
import type { AuthorRow, WorkRow } from "../../lib/adminTypes";
import iso6391 from "../../lib/iso6391.json";
import iso3166 from "../../lib/iso3166-1.json";

const iso6391Map = iso6391 as Record<string, string>;
const iso3166Map = iso3166 as Record<string, string>;

export function workLabel(w: WorkRow | null | undefined): string {
  return w ? (w.Title_CN || "") + " - " + (w.originalTitle || "") : "";
}

// ISO 639-1 语言选项,格式为「代码-中文名」(如 en-英语)
export const LANG_OPTIONS = Object.entries(iso6391Map).map(([code, name]) => ({ value: code, label: code + "-" + name }));

export function langLabel(code: string): string {
  if (!code) return "";
  const name = iso6391Map[code];
  return name ? code + "-" + name : code;
}

// ISO 3166-1 国家/地区选项,格式为「代码-中文名」(如 CN-中国)
export const COUNTRY_OPTIONS = Object.entries(iso3166Map).map(([code, name]) => ({ value: code, label: code + "-" + name }));

export function countryLabel(code: string): string {
  if (!code) return "";
  const name = iso3166Map[code];
  return name ? code + "-" + name : code;
}

// 作品选择器:输入筛选,只能点选/回车选择已存在条目(不接收自由输入)
export function WorkPicker({
  value,
  onChange,
  worksList,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  worksList: WorkRow[];
  placeholder: string;
}) {
  // 软删除行不可作为引用目标(与后端 validate_row 的 deletedAt 过滤一致)
  const activeWorks = useMemo(() => worksList.filter((w) => !w.deletedAt), [worksList]);
  const [query, setQuery] = useState(() => {
    const w = activeWorks.find((x) => x.id === value);
    return w ? workLabel(w) : "";
  });
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const lastValue = useRef(value);

  useEffect(() => {
    if (value !== lastValue.current) {
      lastValue.current = value;
      const w = activeWorks.find((x) => x.id === value);
      if (w) setQuery(workLabel(w));
    }
  }, [value, activeWorks]);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? activeWorks.filter((w) =>
        [w.Title_CN, w.originalTitle, w.Title_EN].filter(Boolean).join(" ").toLowerCase().includes(q)
      )
    : activeWorks;

  const pick = (w: WorkRow) => {
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
          const w = activeWorks.find((x) => x.id === value);
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
export function CodePicker({
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

export function authorLabelOf(a: AuthorRow): string {
  const name = a.Name_CN || a.originalName || "";
  return a.birthYear ? name + "-" + a.birthYear : name;
}

// 把逗号分隔的 author_id 字符串解析为 [{ value: id, label: 显示名 }]
function parseAuthorIds(value: string, authorsList: AuthorRow[]): { value: string; label: string }[] {
  const active = authorsList.filter((a) => !a.deletedAt);
  return String(value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .flatMap((id) => {
      const a = active.find((x) => x.id === id);
      return a ? [{ value: a.id, label: authorLabelOf(a) }] : [];
    });
}

// 作者多选选择器:从作者表筛选,可添加多个作者(存储为逗号分隔的原文名)
export function AuthorPicker({
  value,
  onChange,
  authorsList,
  placeholder,
  onAddNew,
}: {
  value: string;
  onChange: (v: string) => void;
  authorsList: AuthorRow[];
  placeholder: string;
  onAddNew?: (query: string) => void;
}) {
  // 软删除行不可作为引用目标(与后端 validate_row 的 deletedAt 过滤一致)
  const activeAuthors = authorsList.filter((a) => !a.deletedAt);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [dir, setDir] = useState("down");
  const [maxH, setMaxH] = useState(220);
  const [selected, setSelected] = useState(() => parseAuthorIds(value, authorsList));
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const lastValue = useRef(value);

  useEffect(() => {
    // value 变化或作者列表更新(如新增作者回填后)都重新解析已选作者;
    // 列表刷新后才能把刚新增的作者 id 解析成标签显示
    const valueChanged = value !== lastValue.current;
    lastValue.current = value;
    setSelected(parseAuthorIds(value, authorsList));
    if (valueChanged) setQuery(""); // 外部值变化时清空输入,让位给已选标签
  }, [value, authorsList]);

  const rawQuery = query.trim();
  const q = rawQuery.toLowerCase();
  const filtered = q
    ? activeAuthors.filter((a) =>
        (authorLabelOf(a) + " " + (a.originalName || "") + " " + (a.Name_EN || "")).toLowerCase().includes(q)
      )
    : activeAuthors;
  const available = filtered.filter((a) => !selected.some((s) => s.value === a.id));
  // 搜不到任何作者时给出「添加新作者」入口(与点亮星空一致);搜到但都已选中的不提供
  const showAdd = Boolean(onAddNew && q && filtered.length === 0);

  const commit = (next: { value: string; label: string }[]) => {
    setSelected(next);
    onChange(next.map((s) => s.value).join(","));
  };

  const addAuthor = (a: AuthorRow) => {
    if (selected.some((s) => s.value === a.id)) return;
    commit([...selected, { value: a.id, label: authorLabelOf(a) }]);
    setQuery("");
    setOpen(false); // 填入作者后自动收起下拉框(再点输入框可继续添加合著者)
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
      {/* 已选作者以标签形式内嵌在输入框中,不占用额外行 */}
      <div
        className="author-picker-inner"
        onClick={() => inputRef.current && inputRef.current.focus()}
      >
        {selected.map((s) => (
          <span key={s.value} className="author-chip">
            {s.label}
            <button type="button" title="移除" onClick={() => removeAuthor(s.value)}>×</button>
          </span>
        ))}
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder={selected.length ? "" : placeholder}
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
            if (showAdd && e.key === "Enter") {
              e.preventDefault();
              setOpen(false);
              onAddNew!(rawQuery);
              return;
            }
            if (e.key === "Enter" && open && available.length) {
              e.preventDefault();
              addAuthor(available[0]);
            }
          }}
        />
      </div>
      {open && (available.length > 0 || showAdd) && (
        <ul
          className={"work-picker-results" + (dir === "up" ? " up" : "")}
          style={{ display: "block", maxHeight: maxH }}
        >
          {showAdd && (
            <li
              className="add-option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                setOpen(false);
                onAddNew!(rawQuery);
              }}
            >
              ＋ 添加新作者「{rawQuery}」
            </li>
          )}
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
      {open && q && available.length === 0 && !showAdd && (
        <div className="work-picker-warn">没有匹配的作者,只能选择已存在的作者</div>
      )}
    </div>
  );
}
