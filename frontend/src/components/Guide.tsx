import { useEffect } from "react";
import { useApp } from "../store";
import { isMobileLayout } from "../lib/mobileGestures";
import GuideItems from "./GuideItems";

export default function Guide() {
  const { state, dispatch } = useApp();
  const mobile = isMobileLayout();
  useEffect(() => {
    let seen = false;
    try { seen = !!localStorage.getItem("echo_graph_guide_seen"); } catch { seen = false; }
    if (!seen && location.search.indexOf("skipguide") === -1) {
      dispatch({ type: "SET_GUIDE", value: true });
    }
  }, [dispatch]);
  if (!state.guideVisible) return null;
  return (
    <div id="guide">
      <div className="guide-card">
        <h3>Litnebula · 快速上手</h3>
        <GuideItems mobile={mobile} />
        <button
          onClick={() => {
            try { localStorage.setItem("echo_graph_guide_seen", "1"); } catch { /* ignore */ }
            dispatch({ type: "SET_GUIDE", value: false });
          }}
        >
          开始探索
        </button>
      </div>
    </div>
  );
}
