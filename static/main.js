/* 入口:初始化渲染器、绑定交互、加载数据 */

import { el, esc } from "./util.js";
import { initThree, setOnNodeClick } from "./renderer.js";
import { loadGraph, wireEvents, handleHash, selectNode } from "./actions.js";
import { setOnSelect } from "./panels.js";

function initStarfield() {
  var wrap = el("stars");
  if (!wrap || wrap.children.length > 2) return;
  for (var i = 0; i < 150; i++) {
    var s = document.createElement("div");
    s.className = "star";
    var size = (Math.random() * 1.7 + 0.6).toFixed(1);
    s.style.width = size + "px";
    s.style.height = size + "px";
    s.style.left = (Math.random() * 100).toFixed(2) + "%";
    s.style.top = (Math.random() * 100).toFixed(2) + "%";
    var hue = Math.random() < 0.72 ? "255,255,255" : (Math.random() < 0.5 ? "170,205,255" : "255,225,170");
    s.style.background = "rgba(" + hue + ",0.95)";
    s.style.boxShadow = "0 0 " + (Math.random() * 4 + 2).toFixed(1) + "px rgba(" + hue + ",0.8)";
    s.style.setProperty("--d", (Math.random() * 4 + 2.5).toFixed(1) + "s");
    s.style.setProperty("--delay", (Math.random() * 6).toFixed(1) + "s");
    wrap.appendChild(s);
  }
}

initThree();
initStarfield();
setOnNodeClick(selectNode);
setOnSelect(selectNode);
wireEvents();
loadGraph().catch(function (err) {
  el("graph").innerHTML = "<p style='padding:20px;color:#f87171'>加载图谱失败:" + esc(err.message) + "</p>";
}).then(function () {
  handleHash();
});
