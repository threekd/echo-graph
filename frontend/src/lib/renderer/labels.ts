/* 标签自然遮挡:按观看者视角,以「标签自身的遮挡程度」决定隐藏。

   判定对象是标签本身:按节点离相机由近到远排序,前面的标签会盖住后面的
   标签;对每个标签计算其屏幕矩形被已保留(更近)标签覆盖的面积占比,
   达到 LABEL_OCCLUSION_COVER_RATIO(默认 0.5)即视为被遮挡,打上 .culled
   类隐藏(opacity:0,保留布局,相机/布局变化后可自动恢复)。
   隐藏用透明度而非 visible,标签始终可量出真实包围盒,不会闪烁。
   节流执行;孤岛默认隐藏标签(hiddenByDefault)不参与。 */

import { R } from "./state";

// 检查节流间隔(ms):getBoundingClientRect 触发 layout,不宜每帧执行
const LABEL_CULL_INTERVAL_MS = 250;

let lastCheck = 0;

// 遮挡阈值:标签矩形被更近标签覆盖的面积占比 >= 该值即隐藏(0~1,越大越宽松)
export const LABEL_OCCLUSION_COVER_RATIO = 0.1;

interface LabelEntry {
  elm: HTMLElement;
  rect: DOMRect;
  depth: number;
}

function intersectionArea(a: DOMRect, b: DOMRect): number {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

export function updateLabelCulling(now: number): void {
  if (now - lastCheck < LABEL_CULL_INTERVAL_MS) return;
  lastCheck = now;
  const camera = R.camera;
  if (!camera) return;

  const entries: LabelEntry[] = [];
  for (const id of Object.keys(R.nodeLabels)) {
    const label = R.nodeLabels[id];
    if (label.userData && label.userData.hiddenByDefault) continue;
    const elm = label.element;
    const pos = R.positions[id];
    if (!elm || !pos) continue;
    const rect = elm.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    entries.push({ elm, rect, depth: pos.distanceTo(camera.position) });
  }
  // 近 → 远:前面节点的标签自然遮挡后面节点的标签
  entries.sort((a, b) => a.depth - b.depth);

  const kept: DOMRect[] = [];
  for (const e of entries) {
    let covered = 0;
    for (const k of kept) covered += intersectionArea(e.rect, k);
    const area = e.rect.width * e.rect.height;
    const ratio = area ? covered / area : 1;
    const culled = ratio >= LABEL_OCCLUSION_COVER_RATIO;
    e.elm.classList.toggle("culled", culled);
    if (!culled) kept.push(e.rect);
  }
}
