/* 入口:初始化渲染器、绑定交互、加载数据 */

import { el, esc } from "./util.js";
import {
  initThree,
  setOnNodeClick,
  setOnNodeHover,
  toggleAuthorsInView,
  sceneNodeCount,
} from "./renderer.js";
import { loadGraph, wireEvents, handleHash, selectNode, showNodeDetail } from "./actions.js";
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

function initSidebar() {
  var lastPointer = { x: 0, y: 0, valid: false };
  document.addEventListener("mousemove", function (e) {
    lastPointer.x = e.clientX;
    lastPointer.y = e.clientY;
    lastPointer.valid = true;
  }, { passive: true });

  function pointerOver(panel) {
    if (!lastPointer.valid) return false;
    var target = document.elementFromPoint(lastPointer.x, lastPointer.y);
    return !!target && panel.contains(target);
  }

  function bind(zoneId, panelId) {
    var zone = el(zoneId);
    var panel = el(panelId);
    if (!zone || !panel) return null;

    var composing = false;
    panel.addEventListener("compositionstart", function () { composing = true; }, true);
    panel.addEventListener("compositionend", function () { composing = false; }, true);
    panel.addEventListener("keydown", function (e) {
      if (e.isComposing) composing = true;
    }, true);
    panel.addEventListener("keyup", function (e) {
      if (!e.isComposing) composing = false;
    }, true);

    function keepOpen() {
      var ae = document.activeElement;
      return composing || (ae && panel.contains(ae));
    }

    zone.addEventListener("mouseenter", function () {
      panel.classList.add("show");
    });
    panel.addEventListener("mouseleave", function (e) {
      if (keepOpen()) return; // 输入法候选框/输入聚焦时禁止隐藏
      if (!panel.contains(e.relatedTarget)) {
        panel.classList.remove("show");
      }
    });
    panel.addEventListener("focusout", function (e) {
      if (composing) return;
      if (e.relatedTarget && panel.contains(e.relatedTarget)) return;
      if (!pointerOver(panel)) {
        panel.classList.remove("show");
      }
    });
    return { panel: panel, keepOpen: keepOpen };
  }

  var left = bind("sidebar-zone-left", "sidebar-left");
  var right = bind("sidebar-zone-right", "panel");
  document.addEventListener("mouseleave", function () {
    if (left && !left.keepOpen()) left.panel.classList.remove("show");
    if (right && !right.keepOpen()) right.panel.classList.remove("show");
  });
}

function initGuide() {
  var guide = el("guide");
  if (!guide) return;
  var seen = false;
  try { seen = !!localStorage.getItem("echo_graph_guide_seen"); } catch (e) { /* ignore */ }
  if (seen || location.search.indexOf("skipguide") !== -1) {
    return;
  }
  guide.style.display = "flex"; // 首次访问才显示
  el("guide-close").addEventListener("click", function () {
    guide.style.display = "none";
    try { localStorage.setItem("echo_graph_guide_seen", "1"); } catch (e) { /* ignore */ }
  });
}

initThree();
initStarfield();
initSidebar();
initGuide();
setOnNodeClick(selectNode);
setOnNodeHover(showNodeDetail);
setOnSelect(selectNode);
wireEvents();

loadGraph().catch(function (err) {
  el("graph").innerHTML = "<p style='padding:20px;color:#f87171'>加载图谱失败:" + esc(err.message) + "</p>";
}).then(function () {
  handleHash();
  // 测试参数:authortoggle=1 即时隐藏作者;=2 即时显示
  var toggle = location.search.indexOf("authortoggle=1") !== -1 ? true
    : (location.search.indexOf("authortoggle=2") !== -1 ? false : null);
  var cycle = location.search.indexOf("authortoggle=3") !== -1;
  if (toggle !== null) {
    var iv = setInterval(function () {
      if (sceneNodeCount() > 0) {
        clearInterval(iv);
        toggleAuthorsInView(toggle);
      }
    }, 50);
  } else if (cycle) {
    var iv2 = setInterval(function () {
      if (sceneNodeCount() > 0) {
        clearInterval(iv2);
        toggleAuthorsInView(true);       // 先隐藏
        setTimeout(function () {
          toggleAuthorsInView(false);    // 再显示
        }, 500);
      }
    }, 50);
  }
});
