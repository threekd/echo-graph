/* 侧边栏「我的」Tab:个人资料编辑 + 关注/粉丝列表。

   登录态判定与列表加载由 Sidebar 容器负责,本组件只负责渲染与表单交互。 */

import type { Dispatch, SetStateAction } from "react";
import type { FollowUser } from "../../lib/api";
import type { AppAction, AppState } from "../../store";

interface MineTabProps {
  state: AppState;
  dispatch: (a: AppAction) => void;
  profileForm: { nickname: string; bio: string };
  setProfileForm: Dispatch<SetStateAction<{ nickname: string; bio: string }>>;
  profileError: string;
  profileBusy: boolean;
  saveProfile: () => void;
  following: FollowUser[];
  followers: FollowUser[];
  jumpToSpace: (userId: string, displayName: string) => void;
}

export default function MineTab(props: MineTabProps) {
  const {
    state, dispatch, profileForm, setProfileForm,
    profileError, profileBusy, saveProfile, following, followers, jumpToSpace,
  } = props;

  return (
    <div className="settings-pane">
      {state.user ? (
        <>
          <div className="settings-section">
            <h3>个人资料</h3>
            <label className="settings-field">
              <span>昵称</span>
              <input
                type="text"
                value={profileForm.nickname}
                maxLength={32}
                onChange={(e) => setProfileForm((f) => ({ ...f, nickname: e.target.value }))}
                placeholder=""
              />
            </label>
            <label className="settings-field">
              <span>简介</span>
              <textarea
                value={profileForm.bio}
                maxLength={500}
                rows={4}
                onChange={(e) => setProfileForm((f) => ({ ...f, bio: e.target.value }))}
                placeholder="介绍一下自己"
              />
            </label>
            {profileError && <div className="auth-error">{profileError}</div>}
            <button
              id="btn-save-profile"
              className="side-btn"
              onClick={saveProfile}
              disabled={profileBusy}
            >
              {profileBusy ? "保存中…" : "保存个人资料"}
            </button>
          </div>
          <div className="settings-section">
            <h3>关注 <span className="follow-count">{following.length}</span></h3>
            {following.length === 0 ? (
              <p className="settings-hint">还没有关注任何人,去他人星云点「关注」吧。</p>
            ) : (
              <ul className="follow-list">
                {following.map((u) => (
                  <li key={u.id} className="follow-item">
                    <button
                      className="follow-name"
                      title="跃迁到 TA 的星云"
                      onClick={() => jumpToSpace(u.id, u.displayName)}
                    >
                      {u.displayName}
                    </button>
                    <button className="follow-jump" onClick={() => jumpToSpace(u.id, u.displayName)}>
                      跃迁
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="settings-section">
            <h3>粉丝 <span className="follow-count">{followers.length}</span></h3>
            {followers.length === 0 ? (
              <p className="settings-hint">还没有粉丝。</p>
            ) : (
              <ul className="follow-list">
                {followers.map((u) => (
                  <li key={u.id} className="follow-item">
                    <button
                      className="follow-name"
                      title="跃迁到 TA 的星云"
                      onClick={() => jumpToSpace(u.id, u.displayName)}
                    >
                      {u.displayName}
                    </button>
                    <button className="follow-jump" onClick={() => jumpToSpace(u.id, u.displayName)}>
                      跃迁
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : (
        <div className="settings-section">
          <h3>我的</h3>
          <p className="settings-hint">请先登录,即可编辑个人资料。</p>
          <button
            id="btn-mine-login"
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
