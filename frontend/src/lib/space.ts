/* 空间切换公共载荷分发:进入一个星云 = 写 fullData/space/spaceOwner/spaceProfile + 渲染。
 * App.applyHashSpace 与 Sidebar.switchSpace / doJump / jumpToSpace 此前四处重复,
 * 统一收敛到这里;flush/render 按调用方需要开关。
 */

import { flushSync } from "react-dom";
import { renderMain } from "./graph";
import type { Space } from "./api";
import type { AppAction, GraphData } from "../store";

export function enterSpace(
  dispatch: (a: AppAction) => void,
  space: Space,
  data: GraphData,
  owner: string,
  profile: Record<string, unknown> | null | undefined = null,
  opts: { flush?: boolean; render?: boolean } = {}
): void {
  const commit = () => {
    dispatch({ type: "SET_DATA", data });
    dispatch({ type: "SET_SPACE", space });
    dispatch({ type: "SET_SPACE_OWNER", owner });
    dispatch({ type: "SET_SPACE_PROFILE", profile: profile || null });
  };
  if (opts.flush) flushSync(commit);
  else commit();
  if (opts.render) renderMain({ space }, data);
}
