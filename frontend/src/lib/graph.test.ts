import { describe, expect, it } from "vitest";
import { resolveViewCamera } from "./graph";

const mainDefault = { theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18, radius: 1500, cx: 0, cy: 0, cz: 0 };

describe("resolveViewCamera", () => {
  it("无 opts 时返回各视图默认相机", () => {
    expect(resolveViewCamera("main", {})).toEqual(mainDefault);
    expect(resolveViewCamera("ripple", {})?.radius).toBe(1150);
    expect(resolveViewCamera("author", {})?.radius).toBe(1200);
    expect(resolveViewCamera("path", {})?.radius).toBe(1250);
  });

  it("preserveCamera 时不改相机(返回 undefined)", () => {
    expect(resolveViewCamera("ripple", { preserveCamera: true })).toBeUndefined();
  });

  it("显式 camera 优先于默认相机(深链恢复)", () => {
    const cam = { theta: 1, phi: 2, radius: 3, cx: 4, cy: 5, cz: 6 };
    expect(resolveViewCamera("main", { camera: cam })).toEqual(cam);
    expect(resolveViewCamera("ripple", { preserveCamera: true, camera: cam })).toEqual(cam);
  });

  it("未知视图无默认相机", () => {
    expect(resolveViewCamera("unknown", {})).toBeUndefined();
  });
});
