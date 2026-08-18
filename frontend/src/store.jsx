import React, { createContext, useContext, useReducer } from "react";

const AppContext = createContext(null);

export const initialState = {
  fullData: { nodes: [], edges: [] },
  viewData: { nodes: [], edges: [] },
  currentView: "main",
  rippleCenter: null,
  currentAuthorId: null,
  pathFromId: null,
  pathToId: null,
  hideIslands: false,
  showAuthors: true,
  expandHops: 1,
  panel: { type: "empty" },
  toast: null,
  adminOpen: false,
  guideVisible: false,
};

export function appReducer(state, action) {
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
    case "SET_GUIDE":
      return { ...state, guideVisible: action.value };
    case "NODE_CLICK":
      return state;
    case "NODE_HOVER":
      return state;
    default:
      return state;
  }
}

export function AppProvider({ children }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useApp() {
  return useContext(AppContext);
}
