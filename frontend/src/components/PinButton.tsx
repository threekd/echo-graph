/* 钉住按钮:未钉住时图钉斜置(-45°),钉住后转正(竖直),带旋转过渡。 */

export default function PinButton({
  id,
  pinned,
  title,
  onToggle,
}: {
  id: string;
  pinned: boolean;
  title: string;
  onToggle: () => void;
}) {
  return (
    <button
      id={id}
      className={"pin-btn" + (pinned ? " pinned" : "")}
      title={title}
      onClick={onToggle}
      aria-pressed={pinned}
    >
      <svg
        className="pin-btn-icon"
        viewBox="0 0 24 24"
        width="15"
        height="15"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M16 9V4h1c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1h1v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z" />
      </svg>
    </button>
  );
}
