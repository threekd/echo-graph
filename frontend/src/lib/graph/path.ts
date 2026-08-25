// 路径视图:两节点间的提及链(API 返回节点序,前端补全边与节点数据)
import { findPath } from "../api";
import type { GraphNode } from "../../store";
import { dispatch, findNode, getState, failToast, currentSpace } from "./state";
import { commitView, syncUrl, type ViewOpts } from "./view";

export function renderPath(fromId: string, toId: string, opts?: ViewOpts): Promise<any> {
  const fullData = opts?.fullData || getState().fullData;
  dispatch({ type: "SET_PATH", from: fromId, to: toId });
  const fromNode = findNode(fromId, fullData);
  const toNode = findNode(toId, fullData);
  dispatch({
    type: "SET_PATH_INPUTS",
    inputs: {
      from: fromNode ? fromNode.label + " - " + (fromNode.author || "") : "",
      to: toNode ? toNode.label + " - " + (toNode.author || "") : "",
    },
  });
  return findPath(fromId, toId, currentSpace()).then((result: any) => {
    if (!result || !result.nodes || !result.nodes.length) return null;
    const nodes = result.nodes.map((id: string) => findNode(id, fullData)).filter(Boolean) as GraphNode[];
    const edges = result.edges.map((e: any) => ({
      source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note,
    }));
    commitView("path", { nodes, edges, pathOrder: result.nodes }, opts || {});
    syncUrl({
      view: "path", from: fromId, to: toId,
      hideIslands: opts && typeof opts.hideIslands === "boolean" ? opts.hideIslands : getState().hideIslands,
      showAuthors: opts && typeof opts.showAuthors === "boolean" ? opts.showAuthors : getState().showAuthors,
    });
    dispatch({ type: "SET_TOAST", msg: `提及链 · ${result.nodes.length} 本书 / ${result.edges.length} 次提及` });
    return result;
  }).catch((err) => {
    failToast(err);
    return undefined; // 网络错误与"未找到链"区分开,调用方通过 undefined 判断
  });
}
