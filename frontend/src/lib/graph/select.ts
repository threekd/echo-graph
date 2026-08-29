// 节点选择与数据刷新:点击节点打开涟漪/作者视图;数据写入后刷新当前星云
import { flushSync } from "react-dom";
import { workDetail, loadGraphData, type Space } from "../api";
import { isAnonymousAuthor } from "../graphData";
import { dispatch, findNode, getState, failToast, currentSpace, countWorks } from "./state";
import { renderMain } from "./main";
import { renderRipple, reRenderRipple } from "./ripple";
import { renderAuthorView, reRenderAuthor } from "./author";

// 详情请求序号:快速悬停/点击多个节点时,后发请求会递增序号,
// 过期响应(先发的请求后返回)直接丢弃,避免旧节点详情覆盖新节点。
let detailSeq = 0;

function fetchWorkDetail(id: string, space: Space) {
  const seq = ++detailSeq;
  return { seq, promise: workDetail(id, space) };
}

// 数据写入(星云工坊/点亮星空)后刷新当前星云图谱并重绘当前视图,无需整页刷新
export function refreshSpaceGraph(): void {
  const st = getState();
  const space = st.space || "mine";
  loadGraphData(space)
    .then((data) => {
      flushSync(() => {
        dispatch({ type: "SET_DATA", data });
        dispatch({ type: "SET_SPACE_PROFILE", profile: (data as any).owner || null });
      });
      const view = getState().currentView;
      if (view === "main") {
        renderMain({ preserveCamera: true }, data);
      } else if (view === "ripple") {
        reRenderRipple();
      } else if (view === "author") {
        reRenderAuthor();
      }
    })
    .catch(() => { /* 刷新失败不影响写入结果,下次进入空间时会加载最新数据 */ });
}

export function selectNode(id: string) {
  const node = findNode(id);
  if (!node) return;
  if (isAnonymousAuthor(node)) {
    dispatch({ type: "SET_TOAST", msg: "佚名(Anonymous)节点已隐藏,可直接搜索具体作品" });
    return;
  }
  if (node.type === "work") {
    const { seq, promise } = fetchWorkDetail(id, currentSpace());
    promise.then((d) => {
      if (seq !== detailSeq) return; // 已有更新的详情请求,丢弃过期响应
      renderRipple(d);
      // 手机端也保存节点信息供右侧上划查看,但不自动呼出(Panel 按 isMobileLayout 控制)
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
      dispatch({ type: "SET_TOAST", msg: "已展开《" + node.label + "》的涟漪", kind: "info" });
    }).catch((e) => {
      if (seq === detailSeq) failToast(e);
    });
  } else {
    renderAuthorView(node);
    dispatch({
      type: "SET_TOAST",
      msg: "视图:作者 · " + node.label + "(" + countWorks(node.id) + " 部作品)",
      kind: "info",
    });
  }
}

export function showNodeDetail(id: string) {
  const node = findNode(id);
  if (!node) return;
  if (node.type === "work") {
    const { seq, promise } = fetchWorkDetail(id, currentSpace());
    promise.then((d) => {
      if (seq !== detailSeq) return; // 悬停已移到其他节点,丢弃过期详情
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
    }).catch((e) => {
      if (seq === detailSeq) failToast(e);
    });
  } else {
    dispatch({ type: "SET_PANEL", panel: { type: "author", author: node } });
  }
}
