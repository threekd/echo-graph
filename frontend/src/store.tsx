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

// 阅读状态筛选:全部 / 已读(read) / 待读(reading,系统内为「在读」) / 未读(unread)
export type ReadingFilter = "all" | "read" | "reading" | "unread";

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
  hideIslands: boolean;
  showAuthors: boolean;
  showWorkLabels: boolean; // 是否显示作品节点的文字标签
  readingFilter: ReadingFilter; // 作品阅读状态筛选(默认全部)
  expandHops: number;
  expandMax: number; // 当前节点视图的扩散上限(动态:该节点实际可达的最远跳数,无人工上限)
  panel: PanelState;
  toast: ToastPayload | null;
  adminOpen: boolean;
  userAdminOpen: boolean; // 独立用户管理窗口(仅 admin)
  opsOpen: boolean; // 独立运维管理窗口(日志/快照,仅 admin)
  contributeOpen: boolean; // "点亮星空(添加到我的星云)"弹窗
  authOpen: boolean; // 登录/注册弹窗
  user: AuthUser | null; // 当前登录用户(未登录为 null)
  space: Space; // 当前浏览空间:mine(我的星云) | "space:<userId>"(星际跃迁)
  spaceOwner: string; // 数据源显示:我的星云/跃迁星云为账号
  pinLeft: boolean; // 左侧功能栏钉住(不再自动隐藏)
  pinRight: boolean; // 右侧详情栏钉住(不再自动隐藏)
  spaceProfile: { username?: string; nickname?: string | null; bio?: string | null } | null; // 当前星云所有者的公开资料
  guideVisible: boolean;
}

export type AppAction =
  | { type: "SET_DATA"; data: GraphData }
  | { type: "SET_VIEW_DATA"; data: GraphData }
  | { type: "SET_VIEW"; view: string }
  | { type: "SET_RIPPLE_CENTER"; id: string | null }
  | { type: "SET_AUTHOR"; id: string | null }
  | { type: "SET_PATH"; from: string | null; to: string | null }
  | { type: "SET_PATH_INPUTS"; inputs: { from: string; to: string } }
  | { type: "SET_CAMERA"; camera: CameraState }
  | { type: "SET_HIDE_ISLANDS"; value: boolean }
  | { type: "SET_SHOW_AUTHORS"; value: boolean }
  | { type: "SET_SHOW_WORK_LABELS"; value: boolean }
  | { type: "SET_READING_FILTER"; value: ReadingFilter }
  | { type: "SET_EXPAND"; value: number }
  | { type: "SET_EXPAND_MAX"; value: number }
  | { type: "SET_PANEL"; panel: PanelState }
  | { type: "SET_TOAST"; msg: string | null; kind?: ToastKind }
  | { type: "SET_ADMIN"; open: boolean }
  | { type: "SET_USER_ADMIN"; open: boolean }
  | { type: "SET_OPS"; open: boolean }
  | { type: "SET_CONTRIBUTE"; open: boolean }
  | { type: "SET_AUTH"; open: boolean }
  | { type: "SET_USER"; user: AuthUser | null }
  | { type: "SET_SPACE"; space: Space }
  | { type: "SET_SPACE_OWNER"; owner: string }
  | { type: "SET_PIN_LEFT"; value: boolean }
  | { type: "SET_PIN_RIGHT"; value: boolean }
  | { type: "SET_SPACE_PROFILE"; profile: AppState["spaceProfile"] }
  | { type: "SET_GUIDE"; value: boolean };

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
  hideIslands: false,
  showAuthors: true,
  showWorkLabels: true,
  readingFilter: "all",
  expandHops: 1,
  expandMax: 8, // 初始兜底(数据未就绪/非节点视图时,进入视图后按实际可达跳数更新)
  panel: { type: "empty" },
  toast: null,
  adminOpen: false,
  userAdminOpen: false,
  opsOpen: false,
  contributeOpen: false,
  authOpen: false,
  user: null,
  space: "mine",
  spaceOwner: "我的星云",
  pinLeft: false,
  pinRight: false,
  spaceProfile: null,
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
    case "SET_CAMERA":
      return { ...state, camera: action.camera };
    case "SET_HIDE_ISLANDS":
      return { ...state, hideIslands: action.value };
    case "SET_SHOW_AUTHORS":
      return { ...state, showAuthors: action.value };
    case "SET_SHOW_WORK_LABELS":
      return { ...state, showWorkLabels: action.value };
    case "SET_READING_FILTER":
      return { ...state, readingFilter: action.value };
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
    case "SET_USER_ADMIN":
      return { ...state, userAdminOpen: action.open };
    case "SET_OPS":
      return { ...state, opsOpen: action.open };
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
    case "SET_PIN_LEFT":
      return { ...state, pinLeft: action.value };
    case "SET_PIN_RIGHT":
      return { ...state, pinRight: action.value };
    case "SET_SPACE_PROFILE":
      return { ...state, spaceProfile: action.profile || null };
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
