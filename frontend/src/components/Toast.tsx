import { useEffect } from "react";
import { useApp } from "../store";

export default function Toast() {
  const { state, dispatch } = useApp();
  useEffect(() => {
    if (!state.toast) return;
    const t = setTimeout(() => dispatch({ type: "SET_TOAST", msg: null }), 2200);
    return () => clearTimeout(t);
  }, [state.toast, dispatch]);
  return <div id="toast" className={state.toast ? "show" : ""}>{state.toast || ""}</div>;
}
