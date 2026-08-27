// 节点选择与数据刷新:点击节点打开涟漪/作者视图;数据写入后刷新当前星云
import { flushSync } from "react-dom";
import { workDetail, loadGraphData } from "../api";
import { isAnonymousAuthor } from "../graphData";
import { dispatch, findNode, getState, failToast, currentSpace, countWorks } from "./state";
import { renderMain } from "./main";
import { renderRipple, reRenderRipple } from "./ripple";
import { renderAuthorView, reRenderAuthor } from "./author";

// 数据写入(数据管理/点亮星空)后刷新当前星云图谱并重绘当前视图,无需整页刷新
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
    workDetail(id, currentSpace()).then((d) => {
      renderRipple(d);
      // 手机端也保存节点信息供右侧上划查看,但不自动呼出(Panel 按 isMobileLayout 控制)
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
      dispatch({ type: "SET_TOAST", msg: "已展开《" + node.label + "》的涟漪", kind: "info" });
    }).catch(failToast);
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
    workDetail(id, currentSpace()).then((d) => {
      dispatch({ type: "SET_PANEL", panel: { type: "work", d } });
    }).catch(failToast);
  } else {
    dispatch({ type: "SET_PANEL", panel: { type: "author", author: node } });
  }
}
