/* 侧边栏「设置」Tab:账号信息、星云可见性与退出入口。

   退出确认弹窗见 LogoutModal.tsx;本组件只负责展示与发起退出请求。 */

import type { AppAction, AppState } from "../../store";

interface SettingsTabProps {
  state: AppState;
  dispatch: (a: AppAction) => void;
  setSpaceVisibility: (next: "public" | "private") => void;
  onRequestLogout: () => void;
}

export default function SettingsTab(props: SettingsTabProps) {
  const { state, dispatch, setSpaceVisibility, onRequestLogout } = props;

  return (
    <div className="settings-pane">
      {state.user ? (
        <>
          <div className="settings-section">
            <h3>账号</h3>
            <div className="auth-username">用户名:{state.user.username || "—"}</div>
            <button
              id="btn-logout"
              className="side-btn"
              onClick={onRequestLogout}
            >
              退出登录
            </button>
          </div>
          <div className="settings-section">
            <h3>星云可见性</h3>
            <p className="settings-hint">
            </p>
            <label className="settings-field">
              <select
                value={(state.user.space_visibility ?? "public") === "private" ? "private" : "public"}
                onChange={(e) => setSpaceVisibility(e.target.value as "public" | "private")}
              >
                <option value="public">公开(可被访问)</option>
                <option value="private">仅自己可见</option>
              </select>
            </label>
          </div>
        </>
      ) : (
        <div className="settings-section">
          <h3>设置</h3>
          <p className="settings-hint">请先登录,即可管理账号与星云可见性。</p>
          <button
            id="btn-settings-login"
            className="side-btn"
            onClick={() => dispatch({ type: "SET_AUTH", open: true })}
          >
            登录 / 注册
          </button>
        </div>
      )}
    </div>
  );
}
