// 主图谱视图:默认过滤(单作者作品/孤岛/是否展示作者)后提交渲染
import { filterSingleWorkAuthors, filterIslands, filterAuthorsWith } from "../graphData";
import type { GraphData } from "../../store";
import { dispatch, getState } from "./state";
import { commitView, syncUrl, type ViewOpts } from "./view";

export function renderMain(opts: any, dataOverride?: GraphData | null, overrides?: ViewOpts) {
  const st = getState();
  // dataOverride 用于首次加载(此时 state 尚未更新),同样经过默认过滤
  let data = filterSingleWorkAuthors(dataOverride || st.fullData);
  const hideIslands = overrides && typeof overrides.hideIslands === "boolean" ? overrides.hideIslands : st.hideIslands;
  const showAuthors = overrides && typeof overrides.showAuthors === "boolean" ? overrides.showAuthors : st.showAuthors;
  if (hideIslands) data = filterIslands(data);
  data = filterAuthorsWith(data, showAuthors);
  commitView("main", data, opts || {});
  syncUrl({ view: "main", hideIslands, showAuthors, space: opts && opts.space });
  // 详情栏内容取决于当前视图:主视图无中心节点,一律清空
  dispatch({ type: "SET_PANEL", panel: { type: "empty" } });
}
