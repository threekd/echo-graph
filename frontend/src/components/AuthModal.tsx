/* 登录/注册弹窗:邮箱+密码;注册页含 Cloudflare Turnstile 人机验证。 */

import { useEffect, useRef, useState } from "react";
import { useApp } from "../store";
import { fetchAuthConfig, login, register, type AuthUser } from "../lib/auth";

type Mode = "login" | "register";

const TURNSTILE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js";

export default function AuthModal() {
  const { state, dispatch } = useApp();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [siteKey, setSiteKey] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [captchaState, setCaptchaState] = useState<"idle" | "loading" | "ready" | "failed">("idle");
  const [captchaRetry, setCaptchaRetry] = useState(0);
  const widgetRef = useRef<string | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);

  // 打开弹窗时拉取 Turnstile 站点密钥(后端未配置则注册时跳过人机验证)
  useEffect(() => {
    if (!state.authOpen) return;
    setError("");
    setCaptchaToken("");
    setCaptchaState("idle");
    fetchAuthConfig().then((cfg) => setSiteKey(cfg.turnstileSiteKey));
  }, [state.authOpen]);

  // 注册页按需加载 Turnstile 脚本并渲染组件;加载失败/超时给出明确提示
  useEffect(() => {
    const removeWidget = () => {
      if (widgetRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetRef.current);
        } catch {
          /* 组件已不存在时忽略 */
        }
        widgetRef.current = null;
      }
    };
    if (!state.authOpen || mode !== "register" || !siteKey) {
      removeWidget();
      setCaptchaState("idle");
      setCaptchaToken("");
      return;
    }
    let cancelled = false;
    let timeoutId = 0;
    setCaptchaState("loading");
    setCaptchaToken("");
    const renderWidget = () => {
      if (cancelled || !window.turnstile || !boxRef.current) return;
      removeWidget();
      widgetRef.current = window.turnstile.render(boxRef.current, {
        sitekey: siteKey,
        theme: "dark",
        callback: (token: string) => {
          setCaptchaToken(token);
          setCaptchaState("ready");
        },
        "expired-callback": () => {
          setCaptchaToken("");
          setCaptchaState("ready");
        },
        "error-callback": () => {
          setCaptchaToken("");
          setCaptchaState("ready");
        },
      });
      setCaptchaState("ready");
    };
    if (document.querySelector('script[data-turnstile]')) {
      renderWidget();
    } else {
      const s = document.createElement("script");
      s.src = TURNSTILE_SCRIPT;
      s.dataset.turnstile = "1";
      s.async = true;
      s.defer = true;
      s.onload = renderWidget;
      s.onerror = () => { if (!cancelled) setCaptchaState("failed"); };
      document.head.appendChild(s);
      // 8 秒未加载完成视为失败(网络受限/被墙时给出明确提示)
      timeoutId = window.setTimeout(() => {
        if (!window.turnstile && !cancelled) setCaptchaState("failed");
      }, 8000);
    }
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      removeWidget();
    };
  }, [state.authOpen, mode, siteKey, captchaRetry]);

  const retryCaptcha = () => {
    const old = document.querySelector('script[data-turnstile]');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    setCaptchaRetry((r) => r + 1);
  };

  if (!state.authOpen) return null;

  const switchMode = (m: Mode) => {
    setMode(m);
    setError("");
    setCaptchaToken("");
  };

  const finish = (user: AuthUser | null, msg: string) => {
    dispatch({ type: "SET_USER", user });
    dispatch({ type: "SET_AUTH", open: false });
    dispatch({ type: "SET_TOAST", msg, kind: "success" });
  };

  const doSubmit = () => {
    setError("");
    const em = email.trim();
    if (!em || !password) {
      setError("请输入邮箱/用户名和密码");
      return;
    }
    if (mode === "register") {
      if (siteKey && !captchaToken) {
        setError(
          captchaState === "failed"
            ? "人机验证组件加载失败,请检查网络后重试"
            : "请先完成人机验证"
        );
        return;
      }
      const usernameVal = username.trim();
      // 用户名必填(与后端 normalize_username 一致,不再自动推导)
      if (!usernameVal) {
        setError("请填写用户名");
        return;
      }
      if (usernameVal.length < 5) {
        setError("用户名至少 5 个字符");
        return;
      }
      if (password.length < 8) {
        setError("密码至少 8 位");
        return;
      }
      if (password !== confirm) {
        setError("两次输入的密码不一致");
        return;
      }
    }
    setBusy(true);
    const req =
      mode === "register"
        ? register(em, password, captchaToken, username.trim(), nickname.trim() || null)
        : login(em, password);
    req
      .then((r) => {
        if (r.error) {
          setError(r.error);
          return;
        }
        finish(r.user, mode === "register" ? "注册成功,欢迎加入" : "登录成功");
      })
      .catch((e) => setError("请求失败: " + e.message))
      .finally(() => setBusy(false));
  };

  const submitOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") doSubmit();
  };

  return (
    <div id="auth-modal">
      <div className="auth-modal-card">
        <h3>{mode === "login" ? "登录" : "注册账号"}</h3>
        <div className="auth-tabs">
          <button
            type="button"
            className={"auth-tab" + (mode === "login" ? " active" : "")}
            onClick={() => switchMode("login")}
          >
            登录
          </button>
          <button
            type="button"
            className={"auth-tab" + (mode === "register" ? " active" : "")}
            onClick={() => switchMode("register")}
          >
            注册
          </button>
        </div>
        <label>
          <span>{mode === "login" ? "邮箱 / 用户名" : "邮箱"}</span>
          <input
            type={mode === "login" ? "text" : "email"}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={submitOnEnter}
            placeholder={mode === "login" ? "you@example.com 或用户名" : "you@example.com"}
            autoComplete={mode === "login" ? "username" : "email"}
          />
        </label>
        {mode === "register" && (
          <label>
            <span>用户名 <span className="req">*</span></span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="5-32 位英文字母/数字/下划线"
              maxLength={32}
            />
          </label>
        )}
        {mode === "register" && (
          <label>
            <span>昵称</span>
            <input
              type="text"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              placeholder="展示用昵称(可选,默认用用户名)"
              maxLength={32}
            />
          </label>
        )}
        <label>
          <span>密码</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={submitOnEnter}
            placeholder={mode === "register" ? "至少 8 位" : ""}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </label>
        {mode === "register" && (
          <>
            <label>
              <span>确认密码</span>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                onKeyDown={submitOnEnter}
                placeholder="再次输入密码"
                autoComplete="new-password"
              />
            </label>
            <div className="captcha-box">
              {siteKey ? (
                <>
                  <div ref={boxRef} />
                  {captchaState === "loading" && (
                    <p className="auth-hint">人机验证加载中…</p>
                  )}
                  {captchaState === "failed" && (
                    <div>
                      <p className="auth-hint">
                        人机验证组件加载失败,请检查网络后重试。
                      </p>
                      <button type="button" onClick={retryCaptcha}>
                        重新加载验证
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <p className="auth-hint">
                  人机验证未配置,注册可能被拒绝(需后端配置密钥;仅本地开发可临时放行)
                </p>
              )}
            </div>
          </>
        )}
        {error && <div className="auth-error">{error}</div>}
        <div className="admin-modal-actions">
          <button type="button" onClick={doSubmit} disabled={busy}>
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册"}
          </button>
          <button type="button" onClick={() => dispatch({ type: "SET_AUTH", open: false })}>
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
