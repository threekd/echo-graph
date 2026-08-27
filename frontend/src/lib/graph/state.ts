// 图谱视图编排:共享状态注入与只读访问(由 App 注入 ref,各视图模块共用)
import { initialState, type AppAction, type AppState, type GraphData, type GraphNode } from "../../store";
import type { Space } from "../api";
import { workAuthorIds } from "../graphData";

interface StateRef {
  current: { state: AppState; dispatch: (a: AppAction) => void } | null;
}

let stateRef: StateRef | null = null; // 由 App 注入 ref(始终指向最新 { state, dispatch })

export function setStateRef(ref: StateRef) {
  stateRef = ref;
}

export function getState(): AppState {
  return stateRef && stateRef.current ? stateRef.current.state : initialState;
}

export function currentSpace(): Space {
  return getState().space || "public";
}

export function dispatch(a: AppAction) {
  if (stateRef && stateRef.current) stateRef.current.dispatch(a);
}

export function failToast(err: { message?: string }) {
  dispatch({ type: "SET_TOAST", msg: "请求失败:" + (err && err.message ? " " + err.message : "") });
}

export function findNode(id: string, fullData?: GraphData): GraphNode | undefined {
  const fd = fullData || getState().fullData;
  return fd.nodes.filter((n) => n.id === id)[0];
}

export function countWorks(authorId: string): number {
  return getState().fullData.nodes.filter(
    (n) => n.type === "work" && workAuthorIds(n).includes(authorId)
  ).length;
}
