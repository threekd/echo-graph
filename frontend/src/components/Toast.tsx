import { useEffect } from "react";
import { useApp } from "../store";

export default function Toast() {
  const { state, dispatch } = useApp();
  const t = state.toast;
  useEffect(() => {
    if (!t) return;
    const timer = setTimeout(() => dispatch({ type: "SET_TOAST", msg: null }), 2200);
    return () => clearTimeout(timer);
  }, [t, dispatch]);
  return <div id="toast" className={t ? "show " + t.kind : ""}>{t ? t.msg : ""}</div>;
}
