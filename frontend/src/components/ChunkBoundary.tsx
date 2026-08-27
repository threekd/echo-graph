import { Component, type ReactNode } from "react";

// 懒加载 chunk 渲染异常时降级为空,避免整页白屏(图谱仍可用)
export default class ChunkBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("按需加载模块渲染失败:", error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
