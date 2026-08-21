import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from "react";
import type { Space } from "./lib/api";
import type { AuthUser } from "./lib/auth";

export interface CameraState {
  theta: number;
  phi: number;
  radius: number;
  cx: number;
  cy: number;
  cz: number;
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  [key: string]: any;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  [key: string]: any;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  [key: string]: any;
}

export interface PanelState {
  type: string;
  [key: string]: any;
}

export type ToastKind = "success" | "info" | "error";

export interface ToastPayload {
  msg: string;
  kind: ToastKind;
}

export interface AppState {
  fullData: GraphData;
  // 当前视图的绘制数据(受控化的单一事实来源):由 graph.ts 计算后 dispatch,
  // GraphCanvas 的 effect 驱动渲染器执行绘制
  viewData: GraphData;
  currentView: string;
  camera: CameraState;
  rippleCenter: string | null;
  currentAuthorId: string | null;
  pathFromId: string | null;
  pathToId: string | null;
  // 深链 #v=path:... 打开后回填到侧边栏路径输入框的显示文本(书名 - 作者)
  pathInputs: { from: string; to: string };
  storeName: string;
  hideIslands: boolean;
  showAuthors: boolean;
  expandHops: number;
  expandMax: number; // 当前节点视图的扩散上限(动态:该节点实际可达的最远跳数,无人工上限)
  panel: PanelState;
  toast: ToastPayload | null;
  adminOpen: boolean;
  contributeOpen: boolean; // "贡献数据"弹窗
  authOpen: boolean; // 登录/注册弹窗
  user: AuthUser | null; // 当前登录用户(未登录为 null)
  space: Space; // 当前浏览空间:public = 公共星云,mine = 我的星云(私有)
  spaceOwner: string; // 数据源显示:公共星云为 "public",个人/跃迁星云为账号
  guideVisible: boolean;
}

export type AppAction = { type: string; [key: string]: any };

export const initialState: AppState = {
  fullData: { nodes: [], edges: [] },
  viewData: { nodes: [], edges: [] },
  currentView: "main",
  // 相机快照:渲染器在视图切换/交互结束时回传(实时相机仍以渲染器为准)
  camera: { theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18, radius: 1500, cx: 0, cy: 0, cz: 0 },
  rippleCenter: null,
  currentAuthorId: null,
  pathFromId: null,
  pathToId: null,
  pathInputs: { from: "", to: "" },
  storeName: "",
  hideIslands: false,
  showAuthors: true,
  expandHops: 1,
  expandMax: 8, // 初始兜底(数据未就绪/非节点视图时,进入视图后按实际可达跳数更新)
  panel: { type: "empty" },
  toast: null,
  adminOpen: false,
  contributeOpen: false,
  authOpen: false,
  user: null,
  space: "public",
  spaceOwner: "public",
  guideVisible: false,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "SET_DATA":
      return { ...state, fullData: action.data };
    case "SET_VIEW_DATA":
      return { ...state, viewData: action.data };
    case "SET_VIEW":
      return { ...state, currentView: action.view };
    case "SET_RIPPLE_CENTER":
      return { ...state, rippleCenter: action.id };
    case "SET_AUTHOR":
      return { ...state, currentAuthorId: action.id };
    case "SET_PATH":
      return { ...state, pathFromId: action.from, pathToId: action.to };
    case "SET_PATH_INPUTS":
      return { ...state, pathInputs: action.inputs };
    case "SET_STORE":
      return { ...state, storeName: action.name };
    case "SET_CAMERA":
      return { ...state, camera: action.camera };
    case "SET_HIDE_ISLANDS":
      return { ...state, hideIslands: action.value };
    case "SET_SHOW_AUTHORS":
      return { ...state, showAuthors: action.value };
    case "SET_EXPAND":
      return { ...state, expandHops: action.value };
    case "SET_EXPAND_MAX":
      return { ...state, expandMax: action.value };
    case "SET_PANEL":
      return { ...state, panel: action.panel };
    case "SET_TOAST":
      // 所有 toast 统一顶部展示(Toast 组件按 kind 区分配色);未指定类型时按 info 处理
      return {
        ...state,
        toast: action.msg ? { msg: action.msg, kind: action.kind || "info" } : null,
      };
    case "SET_ADMIN":
      return { ...state, adminOpen: action.open };
    case "SET_CONTRIBUTE":
      return { ...state, contributeOpen: action.open };
    case "SET_AUTH":
      return { ...state, authOpen: action.open };
    case "SET_USER":
      return { ...state, user: action.user || null };
    case "SET_SPACE":
      return { ...state, space: action.space };
    case "SET_SPACE_OWNER":
      return { ...state, spaceOwner: action.owner };
    case "SET_GUIDE":
      return { ...state, guideVisible: action.value };
    default:
      return state;
  }
}

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp 必须在 AppProvider 内使用");
  return ctx;
}
