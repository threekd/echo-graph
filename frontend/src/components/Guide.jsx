import React, { useEffect } from "react";
import { useApp } from "../store.jsx";

export default function Guide() {
  const { state, dispatch } = useApp();
  const seen = (() => {
    try { return !!localStorage.getItem("echo_graph_guide_seen"); } catch (e) { return false; }
  })();
  useEffect(() => {
    if (!seen && location.search.indexOf("skipguide") === -1) {
      dispatch({ type: "SET_GUIDE", value: true });
    }
  }, []);
  if (!state.guideVisible) return null;
  return (
    <div id="guide">
      <div className="guide-card">
        <h3>回声图谱 · 快速上手</h3>
        <ul>
          <li><b>悬停</b>节点 → 暂停旋转，右侧显示详情</li>
          <li><b>点击</b>作品星 → 展开涟漪；点击作者星 → 该作者与全部作品</li>
          <li><b>右键拖拽</b>旋转 · <b>左键拖拽</b>平移 · <b>滚轮</b>缩放</li>
          <li>鼠标移到屏幕<b>左右边缘</b>呼出工具栏 / 详情栏</li>
          <li><b>Esc</b> 返回全图谱</li>
        </ul>
        <button
          onClick={() => {
            try { localStorage.setItem("echo_graph_guide_seen", "1"); } catch (e) { /* ignore */ }
            dispatch({ type: "SET_GUIDE", value: false });
          }}
        >
          开始探索
        </button>
      </div>
    </div>
  );
}
