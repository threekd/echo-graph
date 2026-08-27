/* 退出登录确认弹窗(与 AuthModal 同用 #auth-modal 容器样式)。 */

interface LogoutModalProps {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function LogoutModal({ open, onCancel, onConfirm }: LogoutModalProps) {
  if (!open) return null;
  return (
    <div id="auth-modal">
      <div className="auth-modal-card">
        <h3>退出登录</h3>
        <p>确定退出当前账号吗?</p>
        <div className="admin-modal-actions">
          <button className="del" onClick={onConfirm}>
            确认退出
          </button>
          <button onClick={onCancel}>取消</button>
        </div>
      </div>
    </div>
  );
}
