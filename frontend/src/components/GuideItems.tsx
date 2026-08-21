import { Fragment } from "react";

/* 操作说明(与新手导引同源):按桌面/手机分别展示。
 * Guide(首次导引弹层)与主视图详情栏空状态共用本组件,保证内容一致。 */

interface Seg {
  b?: string; // 加粗高亮片段
  t?: string; // 普通文本片段
}

type Item = Seg[];

const DESKTOP: Item[] = [
  [{ b: "右键拖拽", t: "旋转 · " }, { b: "左键拖拽", t: "平移 · " }, { b: "滚轮", t: "缩放" }],
  [{ t: "鼠标移到屏幕" }, { b: "左右边缘", t: "呼出工具栏 / 详情栏" }],
  [{ b: "悬停", t: "节点 → 暂停旋转，右侧显示详情" }],
  [{ b: "点击", t: "作品星 → 展开涟漪；点击作者星 → 该作者与全部作品" }],
];

const MOBILE: Item[] = [
  [{ b: "单指", t: "拖动平移 · " }, { b: "双指", t: "旋转 / 缩放" }],
  [{ t: "底部" }, { b: "左侧上划", t: "打开功能栏，" }, { b: "右侧上划", t: "打开详情栏" }],
  [{ t: "点击栏外或返回收起面板" }],
  [{ b: "点击", t: "作品星 → 展开涟漪；点击作者星 → 该作者与全部作品" }],
];

export default function GuideItems({ mobile }: { mobile: boolean }) {
  const items = mobile ? MOBILE : DESKTOP;
  return (
    <ul>
      {items.map((segs, i) => (
        <li key={i}>
          {segs.map((s, j) => (
            <Fragment key={j}>
              {s.b ? <b>{s.b}</b> : null}
              {s.t}
            </Fragment>
          ))}
        </li>
      ))}
    </ul>
  );
}
