// 涟漪视图:以作品详情为中心的单跳波及多层扩散
import { workDetail, expansion } from "../api";
import { isAnonymousAuthor, workAuthorIds, maxEchoHops } from "../graphData";
import type { GraphData, GraphNode } from "../../store";
import { dispatch, findNode, getState, failToast, currentSpace } from "./state";
import { commitView, syncUrl, type ViewOpts } from "./view";

function addAuthorsTo(data: GraphData, opts?: ViewOpts): GraphData {
  const st = getState();
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : st.showAuthors;
  const showIslands = opts && typeof opts.showIslands === "boolean" ? opts.showIslands : st.showIslands;
  const fullData = opts?.fullData || st.fullData;
  if (!showAuthors) return data;
  const nodes = data.nodes.slice();
  const edges = data.edges.slice();
  const out: GraphData = { nodes, edges };
  Object.keys(data).forEach((k) => {
    if (k !== "nodes" && k !== "edges") out[k] = data[k];
  });
  const have: Record<string, boolean> = {};
  nodes.forEach((n) => { have[n.id] = true; });
  nodes.filter((n) => n.type === "work").forEach((w) => {
    workAuthorIds(w).forEach((aid) => {
      const an = findNode(aid, fullData);
      if (an && isAnonymousAuthor(an)) return; // 佚名节点不加入涟漪/扩散子图
      edges.push({ source: w.id, target: aid, type: "authored" });
      if (!have[aid] && an) {
        nodes.push(an);
        have[aid] = true;
      }
    });
  });
  // 勾选"孤岛节点"(显示)时:把当前视图里每位作者名下的全部作品也展示出来(取消勾选后回到仅涟漪节点的行为)
  if (showIslands) {
    nodes.filter((n) => n.type === "author").forEach((a) => {
      fullData.nodes.filter((w) => w.type === "work" && workAuthorIds(w).includes(a.id)).forEach((w) => {
        if (have[w.id]) return;
        nodes.push({ ...w, __extra: true }); // 作者名下额外作品:环绕作者形成隐约星云
        have[w.id] = true;
        edges.push({ source: w.id, target: a.id, type: "authored" });
      });
    });
  }
  return out;
}

export function renderRipple(detail: any, hops?: number | string, opts?: ViewOpts) {
  const center = detail.work.id;
  const showIslands = opts && typeof opts.showIslands === "boolean" ? opts.showIslands : getState().showIslands;
  const showAuthors = opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors;
  const fullData = opts?.fullData || getState().fullData;
  // 动态上限:该作品实际可达的最远跳数(无人工上限,后端同样不限)
  const expandMax = Math.max(1, maxEchoHops(fullData, [center]));
  const expandHops = Math.min(Math.max(1, parseInt(String(hops || 1), 10) || 1), expandMax);
  dispatch({ type: "SET_RIPPLE_CENTER", id: center });
  dispatch({ type: "SET_EXPAND_MAX", value: expandMax });
  dispatch({ type: "SET_EXPAND", value: expandHops });
  const ids: Record<string, boolean> = { [center]: true };
  const nodes: GraphNode[] = [];
  const edges: any[] = [];
  detail.mentioned_by.forEach((e: any) => {
    ids[e.source] = true;
    edges.push({ source: e.source, target: center, type: "echo", evidence: e.evidence, note: e.note });
  });
  detail.mentions.forEach((e: any) => {
    ids[e.target] = true;
    edges.push({ source: center, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
  });
  Object.keys(ids).forEach((id) => {
    const n = findNode(id, fullData);
    if (n) nodes.push(n);
  });
  const data = addAuthorsTo({ nodes, edges, centerId: center }, { showIslands, showAuthors, fullData });
  commitView("ripple", data, opts || {});
  syncUrl({
    view: "ripple", id: center, hops: expandHops,
    showIslands, showAuthors,
  });
}

// 涟漪视图下切换"孤岛节点"等状态时,按当前设置重新渲染(保持相机)
export function reRenderRipple() {
  const st = getState();
  if (st.currentView !== "ripple" || !st.rippleCenter) return;
  const hops = st.expandHops || 1;
  workDetail(st.rippleCenter, currentSpace()).then((d: any) => {
    renderRipple(d, hops, { preserveCamera: true });
    if (hops > 1) expandRippleDebounced(hops);
  }).catch(failToast);
}

export function expandRippleDebounced(hops: number, centerId?: string, fullData?: GraphData) {
  const center = centerId || getState().rippleCenter;
  if (!center) return;
  expansion(center, hops, currentSpace())
    .then((data: any) => {
      const st = getState();
      const viewData = addAuthorsTo(data, {
        showIslands: st.showIslands,
        showAuthors: st.showAuthors,
        fullData: fullData || st.fullData,
      });
      dispatch({ type: "SET_VIEW_DATA", data: viewData });
      const works = viewData.nodes.filter((n) => n.type === "work").length;
      dispatch({ type: "SET_TOAST", msg: hops + " 级扩散 · " + works + " 本书" });
      syncUrl({
        view: "ripple", id: viewData.centerId, hops,
        showIslands: st.showIslands, showAuthors: st.showAuthors,
      });
    })
    .catch(failToast);
}
