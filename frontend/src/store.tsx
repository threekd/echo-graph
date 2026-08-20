import { createContext, useContext, useReducer, type Dispatch, type ReactNode } from "react";

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
  panel: PanelState;
  toast: string | null;
  adminOpen: boolean;
  adminReady: boolean; // 令牌有效时置 true,驱动"数据管理"按钮显隐
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
  panel: { type: "empty" },
  toast: null,
  adminOpen: false,
  adminReady: false,
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
    case "SET_PANEL":
      return { ...state, panel: action.panel };
    case "SET_TOAST":
      return { ...state, toast: action.msg };
    case "SET_ADMIN":
      return { ...state, adminOpen: action.open };
    case "SET_ADMIN_READY":
      return { ...state, adminReady: action.value };
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
