/* 独立用户管理窗口(仅 admin):与「数据管理」同款窗口样式,含用户列表与
   禁用/启用、角色、星云可见性、VIP 维护。后端保护规则:不能修改自己的
   角色/状态;引导管理员不可禁用/降级;系统至少保留一名可用管理员。 */

import { useCallback, useEffect, useState } from "react";
import type { UserRow } from "../lib/adminTypes";
import AdminTable from "./admin/AdminTable";

const COLS = [
  { key: "username", label: "用户名" },
  { key: "nickname", label: "昵称" },
  { key: "email", label: "邮箱" },
  { key: "role", label: "角色" },
  { key: "status", label: "状态" },
  { key: "space_visibility", label: "星云可见性" },
  { key: "vip", label: "VIP" },
  { key: "counts", label: "星云数据(作/书/边)" },
  { key: "createdAt", label: "注册时间" },
];

const FILTER_COLS: { key: string; type: "select" | "text" }[] = [
  { key: "role", type: "select" },
  { key: "status", type: "select" },
  { key: "space_visibility", type: "select" },
  { key: "vip", type: "select" },
  { key: "username", type: "text" },
  { key: "nickname", type: "text" },
  { key: "email", type: "text" },
];

const ROLE_LABEL: Record<string, string> = { admin: "管理员", user: "普通用户" };
const STATUS_LABEL: Record<string, string> = { active: "正常", disabled: "已禁用" };
const VIS_LABEL: Record<string, string> = { public: "公开", private: "仅自己" };

interface Props {
  onClose: () => void;
  meId: string;
}

function displayName(row: UserRow): string {
  return (row.nickname || "").trim() || row.username || row.email;
}

export default function UserAdmin({ onClose, meId }: Props) {
  const [items, setItems] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>({ key: "createdAt", dir: -1 });
  const [confirm, setConfirm] = useState<{ title: string; message: string; run: () => void } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d: { items: UserRow[] }) => {
        setItems(d.items || []);
        setLoading(false);
      })
      .catch((e: Error) => {
        setStatus("用户列表加载失败: " + e.message);
        setLoading(false);
      });
  }, []);

  useEffect(() => { load(); }, [load, reloadKey]);

  const patch = (row: UserRow, patchBody: Record<string, unknown>, okMsg: string) => {
    fetch("/api/admin/users/" + encodeURIComponent(row.id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patchBody),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || "操作失败");
        setStatus(okMsg);
        setReloadKey((k) => k + 1);
      })
      .catch((e: Error) => setStatus(e.message));
  };

  const askConfirm = (title: string, message: string, run: () => void) => {
    setConfirm({ title, message, run });
  };

  const cellValue = (r: UserRow, key: string): string => {
    if (key === "role") return ROLE_LABEL[r.role] || r.role;
    if (key === "status") return STATUS_LABEL[r.status] || r.status;
    if (key === "space_visibility") return VIS_LABEL[r.space_visibility] || r.space_visibility;
    if (key === "vip") return r.vip ? "是" : "否";
    if (key === "counts") {
      const c = r.counts || { authors: 0, works: 0, edges: 0 };
      return c.authors + " / " + c.works + " / " + c.edges;
    }
    return String(r[key as keyof UserRow] ?? "");
  };

  const uniqueValues = (key: string): string[] =>
    Array.from(new Set(items.map((r) => cellValue(r, key)).filter(Boolean))).sort();

  const renderActions = (row: UserRow) => {
    const isSelf = row.id === meId;
    return (
      <span className="llm-actions">
        {row.status === "active" ? (
          <button
            className="del"
            disabled={isSelf}
            title={isSelf ? "不能禁用自己" : undefined}
            onClick={() =>
              askConfirm(
                "禁用用户",
                "确定禁用「" + displayName(row) + "」?其登录会话立即失效、星云不可访问,可随时重新启用。",
                () => patch(row, { status: "disabled" }, "已禁用用户")
              )
            }
          >
            禁用
          </button>
        ) : (
          <button onClick={() => patch(row, { status: "active" }, "已重新启用")}>启用</button>
        )}
        {row.role === "admin" ? (
          <button
            className="del"
            disabled={isSelf}
            title={isSelf ? "不能取消自己的管理员" : undefined}
            onClick={() =>
              askConfirm(
                "取消管理员",
                "确定取消「" + displayName(row) + "」的管理员角色?",
                () => patch(row, { role: "user" }, "已取消管理员")
              )
            }
          >
            取消管理员
          </button>
        ) : (
          <button onClick={() => patch(row, { role: "admin" }, "已设为管理员")}>设为管理员</button>
        )}
        {row.space_visibility === "public" ? (
          <button onClick={() => patch(row, { space_visibility: "private" }, "已设为仅自己可见")}>
            设私密
          </button>
        ) : (
          <button onClick={() => patch(row, { space_visibility: "public" }, "已设为公开")}>设公开</button>
        )}
        {row.vip ? (
          <button onClick={() => patch(row, { vip: false }, "已取消 VIP")}>取消 VIP</button>
        ) : (
          <button onClick={() => patch(row, { vip: true }, "已设为 VIP")}>设为 VIP</button>
        )}
      </span>
    );
  };

  return (
    <div id="admin-overlay">
      <div className="admin-shell">
        <div className="admin-head">
          <div className="admin-head-left">
            <h2 className="admin-title">用户管理</h2>
          </div>
          <div className="admin-actions">
            <button id="admin-close" onClick={onClose}>关闭</button>
          </div>
        </div>
        <div id="admin-status">{status}</div>
        <div className="admin-body">
          <p className="llm-tip">
            用户管理:可禁用/启用账号、调整角色与星云可见性、维护 VIP。禁用后该用户会话立即失效;
            不能修改自己的角色/状态,引导管理员不可禁用或降级,系统至少保留一名可用管理员。
          </p>
          {loading && items.length === 0 ? (
            <p>加载中…</p>
          ) : (
            <AdminTable
              kind="users"
              cols={COLS}
              rows={items}
              filterCols={FILTER_COLS}
              filters={filters}
              textFilters={textFilters}
              sort={sort}
              cellValue={cellValue}
              uniqueValues={uniqueValues}
              onSort={(k) =>
                setSort((prev) => {
                  if (prev && prev.key === k) return prev.dir === 1 ? { key: k, dir: -1 } : null;
                  return { key: k, dir: 1 };
                })
              }
              onFilter={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
              onTextFilter={(k, v) => setTextFilters((f) => ({ ...f, [k]: v }))}
              renderActions={renderActions}
            />
          )}
        </div>
      </div>
      {confirm && (
        <div id="auth-modal">
          <div className="admin-modal-card">
            <h3>{confirm.title}</h3>
            <p>{confirm.message}</p>
            <div className="admin-modal-actions">
              <button
                className="del"
                onClick={() => {
                  const run = confirm.run;
                  setConfirm(null);
                  run();
                }}
              >
                确认
              </button>
              <button onClick={() => setConfirm(null)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
