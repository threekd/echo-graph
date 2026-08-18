/* 共享状态 */

export const state = {
  fullData: { nodes: [], edges: [] }, // 全量数据集(查找、面板)
  viewData: { nodes: [], edges: [] }, // 当前 3D 视图
  currentView: "main",                // main / ripple / path / author
  workLookup: {},                     // "书名 - 作者" -> work id
  workById: {},                       // work id -> work node
};
