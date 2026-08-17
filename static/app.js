/* Echo Graph 3D demo frontend (Three.js, no build step) */
(function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  var MENTION_COLOR = 0x67e8f9; // 提及连线:青色星光

  var fullData = { nodes: [], edges: [] }; // full dataset (lookups, panels)
  var viewData = { nodes: [], edges: [] }; // current 3D view
  var currentView = "main";
  var workLookup = {};

  // ---- Three.js state ----
  var scene, camera, renderer, labelRenderer, raycaster, mouse;
  var nodeGroups = {};   // id -> THREE.Group
  var nodeLabels = {};   // id -> CSS2DObject
  var edgeLines = [];    // line with userData.edge
  var positions = {};    // id -> THREE.Vector3
  var cameraState = { radius: 1500, theta: -Math.PI / 2 + 0.4, phi: Math.PI / 2 - 0.18 };
  var center = new THREE.Vector3(0, 0, 0); // 相机注视点(平移时移动它)
  var lastInteraction = 0;
  var dragging = false, dragButton = 0, dragMoved = false, lastX = 0, lastY = 0;
  var glowTexture = null;

  // =============================== Three.js core ===============================

  function initThree() {
    var container = el("graph");
    var w = container.clientWidth || 900;
    var h = container.clientHeight || 600;

    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x05060f, 0.00030);

    camera = new THREE.PerspectiveCamera(55, w / h, 1, 12000);
    applyCamera();

    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
    renderer.domElement.style.position = "absolute";
    renderer.domElement.style.top = "0";
    renderer.domElement.style.left = "0";
    renderer.domElement.style.zIndex = "1";
    renderer.domElement.style.cursor = "grab";
    container.appendChild(renderer.domElement);

    labelRenderer = new THREE.CSS2DRenderer();
    labelRenderer.setSize(w, h);
    labelRenderer.domElement.style.position = "absolute";
    labelRenderer.domElement.style.top = "0";
    labelRenderer.domElement.style.left = "0";
    labelRenderer.domElement.style.pointerEvents = "none";
    labelRenderer.domElement.style.zIndex = "2";
    container.appendChild(labelRenderer.domElement);

    addBackgroundStars();

    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    bindControls(container);
    window.addEventListener("resize", onResize);
    animate();
  }

  function applyCamera() {
    var r = cameraState.radius;
    var th = cameraState.theta;
    var ph = cameraState.phi;
    var offset = new THREE.Vector3(
      r * Math.sin(ph) * Math.cos(th),
      r * Math.cos(ph),
      r * Math.sin(ph) * Math.sin(th)
    );
    camera.position.copy(center).add(offset);
    camera.lookAt(center);
  }

  function addBackgroundStars() {
    var count = 1400;
    var posArr = new Float32Array(count * 3);
    for (var i = 0; i < count; i++) {
      var u = Math.random() * 2 - 1;
      var th = Math.random() * Math.PI * 2;
      var s = Math.sqrt(Math.max(0, 1 - u * u));
      var r = 2200 + Math.random() * 2300;
      posArr[i * 3] = r * s * Math.cos(th);
      posArr[i * 3 + 1] = r * u;
      posArr[i * 3 + 2] = r * s * Math.sin(th);
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(posArr, 3));
    var mat = new THREE.PointsMaterial({
      color: 0xffffff,
      size: 1.7,
      transparent: true,
      opacity: 0.6,
      sizeAttenuation: true,
      fog: false,
    });
    var stars = new THREE.Points(geo, mat);
    stars.frustumCulled = false;
    scene.add(stars);
  }

  function makeGlowTexture() {
    var c = document.createElement("canvas");
    c.width = c.height = 128;
    var ctx = c.getContext("2d");
    var g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.25, "rgba(255,255,255,0.55)");
    g.addColorStop(0.6, "rgba(255,255,255,0.14)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  function createNodeGroup(n, pos) {
    var isAuthor = n.type === "author";
    var color = isAuthor ? 0x9cc7ff : 0xffd166; // 作者星:蓝白 / 作品星:金色
    var r = isAuthor ? 6 : 8.5;
    if (!glowTexture) glowTexture = makeGlowTexture();

    var core = new THREE.Mesh(
      new THREE.SphereGeometry(r, 14, 14),
      new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: 0.95, fog: false })
    );
    core.userData.node = n;
    core.userData.baseR = r;

    var sprite = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glowTexture,
        color: color,
        transparent: true,
        opacity: 0.55,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        fog: false,
      })
    );
    sprite.scale.set(r * 9, r * 9, 1);
    sprite.userData.phase = Math.random() * Math.PI * 2;

    var group = new THREE.Group();
    group.add(core);
    group.add(sprite);
    group.position.copy(pos);
    group.userData.core = core;
    group.userData.sprite = sprite;

    var div = document.createElement("div");
    div.className = "nodelabel";
    div.textContent = n.label;
    var label = new THREE.CSS2DObject(div);
    label.position.set(0, r + 12, 0);
    group.add(label);

    scene.add(group);
    nodeGroups[n.id] = group;
    nodeLabels[n.id] = label;
  }

  function createEdgeLine(e) {
    var isAuthored = e.type === "authored";
    var mat = new THREE.LineBasicMaterial({
      color: isAuthored ? 0x7b88b8 : MENTION_COLOR,
      transparent: true,
      opacity: isAuthored ? 0.28 : 0.55,
      blending: isAuthored ? THREE.NormalBlending : THREE.AdditiveBlending,
      depthWrite: false,
      fog: true,
    });
    var geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(),
      new THREE.Vector3(),
    ]);
    var line = new THREE.Line(geo, mat);
    line.userData.edge = e;
    scene.add(line);
    edgeLines.push(line);
  }

  function updateEdgeLines() {
    edgeLines.forEach(function (line) {
      var e = line.userData.edge;
      var pa = positions[e.source];
      var pb = positions[e.target];
      if (!pa || !pb) { line.visible = false; return; }
      line.visible = true;
      var attr = line.geometry.attributes.position;
      attr.setXYZ(0, pa.x, pa.y, pa.z);
      attr.setXYZ(1, pb.x, pb.y, pb.z);
      attr.needsUpdate = true;
    });
  }

  // =============================== Layouts ===============================

  function layoutFor(kind, data) {
    if (kind === "ripple") return rippleLayout(data);
    if (kind === "path") return pathLayout(data);
    if (kind === "author") return authorLayout(data);
    return forceLayout(data.nodes.map(function (n) { return n.id; }), data.edges);
  }

  function forceLayout(ids, edges) {
    var positions = {};
    ids.forEach(function (id) {
      var u = Math.random() * 2 - 1;
      var th = Math.random() * Math.PI * 2;
      var s = Math.sqrt(Math.max(0, 1 - u * u));
      var r = 320 + Math.random() * 320;
      positions[id] = new THREE.Vector3(r * s * Math.cos(th), r * u, r * s * Math.sin(th));
    });

    var k = 850 / Math.sqrt(ids.length || 1);
    var temp = 0.62;
    var iters = 260;
    for (var it = 0; it < iters; it++) {
      var disp = {};
      ids.forEach(function (id) { disp[id] = new THREE.Vector3(); });
      for (var i = 0; i < ids.length; i++) {
        for (var j = i + 1; j < ids.length; j++) {
          var a = ids[i], b = ids[j];
          var delta = positions[a].clone().sub(positions[b]);
          var d = Math.max(delta.length(), 0.01);
          var force = (k * k) / d;
          var dir = delta.normalize();
          disp[a].add(dir.clone().multiplyScalar(force));
          disp[b].sub(dir.clone().multiplyScalar(force));
        }
      }
      edges.forEach(function (e) {
        var pa = positions[e.source], pb = positions[e.target];
        if (!pa || !pb) return;
        var delta = pa.clone().sub(pb);
        var d = Math.max(delta.length(), 0.01);
        var force = (d * d) / k;
        var dir = delta.normalize();
        disp[e.source].sub(dir.clone().multiplyScalar(force));
        disp[e.target].add(dir.clone().multiplyScalar(force));
      });
      ids.forEach(function (id) {
        var dl = disp[id].length();
        if (dl < 0.0001) return;
        positions[id].add(disp[id].clone().normalize().multiplyScalar(Math.min(dl, 220) * temp));
        positions[id].multiplyScalar(1 - 0.0035); // gentle pull to center (cluster shape)
      });
      temp = Math.max(0.02, temp * 0.965);
    }

    var meanR = 0;
    ids.forEach(function (id) { meanR += positions[id].length(); });
    meanR = meanR / Math.max(ids.length, 1);
    var scale = 520 / Math.max(meanR, 1);
    ids.forEach(function (id) { positions[id].multiplyScalar(scale); });
    return positions;
  }

  function rippleLayout(data) {
    var positions = {};
    var centerId = data.centerId;
    var workNodes = data.nodes.filter(function (n) { return n.type === "work"; });

    positions[centerId] = new THREE.Vector3(0, 0, 0);
    var R = 300;
    workNodes.forEach(function (n, i) {
      if (n.id === centerId) return;
      var y = 1 - (i / Math.max(workNodes.length - 1, 1)) * 2;
      var rr = Math.sqrt(Math.max(0, 1 - y * y));
      var th = i * 2.399963;
      positions[n.id] = new THREE.Vector3(R * rr * Math.cos(th), R * y, R * rr * Math.sin(th));
    });
    return positions;
  }

  function authorLayout(data) {
    var positions = {};
    var authorNode = data.nodes.filter(function (n) { return n.type === "author"; })[0];
    var works = data.nodes.filter(function (n) { return n.type === "work"; });
    if (authorNode) positions[authorNode.id] = new THREE.Vector3(0, 0, 0);
    var R = 320;
    works.forEach(function (w, i) {
      var y = 1 - (i / Math.max(works.length - 1, 1)) * 2;
      var rr = Math.sqrt(Math.max(0, 1 - y * y));
      var th = i * 2.399963;
      positions[w.id] = new THREE.Vector3(R * rr * Math.cos(th), R * y, R * rr * Math.sin(th));
    });
    return positions;
  }

  function pathLayout(data) {
    var positions = {};
    var order = data.pathOrder || [];
    var n = order.length;
    order.forEach(function (id, i) {
      positions[id] = new THREE.Vector3(
        (i - (n - 1) / 2) * 300,
        Math.sin(i * 1.2) * 50,
        Math.cos(i * 1.2) * 50
      );
    });
    return positions;
  }

  // =============================== View management ===============================

  function clearScene() {
    // CSS2DRenderer 不会自动移除已离开场景的标签 DOM,需手动清理,否则旧书名残留
    Object.keys(nodeLabels).forEach(function (id) {
      var elm = nodeLabels[id].element;
      if (elm && elm.parentNode) elm.parentNode.removeChild(elm);
    });
    Object.keys(nodeGroups).forEach(function (id) {
      var g = nodeGroups[id];
      scene.remove(g);
      g.traverse(function (obj) {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map = null;
          obj.material.dispose();
        }
      });
    });
    edgeLines.forEach(function (l) {
      scene.remove(l);
      l.geometry.dispose();
      l.material.dispose();
    });
    nodeGroups = {};
    nodeLabels = {};
    edgeLines = [];
    positions = {};
  }

  function renderView(kind, data) {
    viewData = data;
    clearScene();
    positions = layoutFor(kind, data);
    data.nodes.forEach(function (n) {
      if (!positions[n.id]) {
        positions[n.id] = new THREE.Vector3(
          Math.random() * 120 - 60,
          Math.random() * 120 - 60,
          Math.random() * 120 - 60
        );
      }
      createNodeGroup(n, positions[n.id]);
    });
    data.edges.forEach(createEdgeLine);

    if (kind === "main") {
      cameraState.radius = 1500; cameraState.theta = -Math.PI / 2 + 0.4; cameraState.phi = Math.PI / 2 - 0.18;
    } else if (kind === "ripple") {
      cameraState.radius = 1150; cameraState.theta = -Math.PI / 2; cameraState.phi = Math.PI / 2 - 0.12;
    } else if (kind === "author") {
      cameraState.radius = 1200; cameraState.theta = -Math.PI / 2 + 0.3; cameraState.phi = Math.PI / 2 - 0.15;
    } else {
      cameraState.radius = 1250; cameraState.theta = -Math.PI / 2 + 0.35; cameraState.phi = Math.PI / 2 - 0.15;
    }
    center.set(0, 0, 0); // 切换视图时重置平移
    applyCamera();
    lastInteraction = Date.now();
    currentView = kind;
    el("btn-back-main").style.display = kind === "main" ? "none" : "block";
  }

  // =============================== Interaction ===============================

  function bindControls(container) {
    var dom = renderer.domElement;
    dom.addEventListener("pointerdown", function (e) {
      dragging = true;
      dragButton = e.button; // 0=左键(平移/选择),2=右键(旋转)
      dragMoved = false;
      lastX = e.clientX; lastY = e.clientY;
      lastInteraction = Date.now();
      if (dom.setPointerCapture) dom.setPointerCapture(e.pointerId);
      dom.style.cursor = "grabbing";
    });
    dom.addEventListener("pointermove", function (e) {
      if (dragging) {
        var dx = e.clientX - lastX;
        var dy = e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        if (Math.abs(dx) + Math.abs(dy) > 2) dragMoved = true;
        if (dragButton === 2) {
          // 右键拖拽:旋转视角
          cameraState.theta -= dx * 0.005;
          cameraState.phi -= dy * 0.005;
          cameraState.phi = Math.max(0.15, Math.min(Math.PI - 0.15, cameraState.phi));
        } else {
          // 左键拖拽:平移视角
          panBy(dx, dy);
        }
        applyCamera();
      } else {
        hoverPick(e);
      }
    });
    dom.addEventListener("pointerup", function (e) {
      dragging = false;
      dom.style.cursor = "grab";
      lastInteraction = Date.now();
      if (dragButton === 0 && !dragMoved) clickPick(e);
    });
    dom.addEventListener("contextmenu", function (e) {
      e.preventDefault(); // 屏蔽右键菜单,右键用于旋转
    });
    container.addEventListener("wheel", function (e) {
      e.preventDefault();
      cameraState.radius *= 1 + e.deltaY * 0.0011;
      cameraState.radius = Math.max(50, Math.min(8000, cameraState.radius));
      lastInteraction = Date.now();
      applyCamera();
    }, { passive: false });
  }

  function panBy(dx, dy) {
    var forward = new THREE.Vector3().subVectors(center, camera.position).normalize();
    var right = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0)).normalize();
    var up = new THREE.Vector3().crossVectors(right, forward).normalize();
    var scale = cameraState.radius * 0.0016;
    center.add(right.clone().multiplyScalar(-dx * scale));
    center.add(up.clone().multiplyScalar(dy * scale));
  }

  function pickMesh(e) {
    var rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    var meshes = Object.keys(nodeGroups).map(function (id) {
      return nodeGroups[id].userData.core;
    });
    var hits = raycaster.intersectObjects(meshes, false);
    return hits.length ? hits[0].object : null;
  }

  function hoverPick(e) {
    var mesh = pickMesh(e);
    var id = mesh && mesh.userData.node ? mesh.userData.node.id : null;
    Object.keys(nodeLabels).forEach(function (nid) {
      nodeLabels[nid].element.classList.toggle("active", nid === id);
    });
    renderer.domElement.style.cursor = mesh ? "pointer" : "grab";
  }

  function clickPick(e) {
    var mesh = pickMesh(e);
    if (mesh && mesh.userData && mesh.userData.node) {
      selectNode(mesh.userData.node.id);
    }
  }

  function onResize() {
    var container = el("graph");
    var w = container.clientWidth;
    var h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    labelRenderer.setSize(w, h);
  }

  function animate() {
    requestAnimationFrame(animate);
    var now = Date.now();
    if (now - lastInteraction > 3500) {
      cameraState.theta += 0.0016;
      applyCamera();
    }
    var t = now * 0.001;
    Object.keys(nodeGroups).forEach(function (id) {
      var g = nodeGroups[id];
      var sprite = g.userData.sprite;
      var phase = sprite.userData.phase;
      sprite.material.opacity = 0.42 + 0.25 * (0.5 + 0.5 * Math.sin(t * 2.1 + phase));
      var core = g.userData.core;
      core.scale.setScalar(1 + 0.07 * Math.sin(t * 1.4 + phase));
    });
    updateEdgeLines();
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
  }

  // =============================== Data & panels ===============================

  function loadGraph() {
    return fetch("/api/graph")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        fullData = data;
        renderView("main", data);
        fillWorkDatalist();
        showEmptyPanel();
      });
  }

  function fillWorkDatalist() {
    var dl = el("works");
    dl.innerHTML = "";
    workLookup = {};
    fullData.nodes.filter(function (n) { return n.type === "work"; }).forEach(function (w) {
      var key = w.label + " - " + (w.author || "");
      workLookup[key] = w.id;
      var opt = document.createElement("option");
      opt.value = key;
      dl.appendChild(opt);
    });
  }

  function selectNode(id) {
    var node = fullData.nodes.filter(function (n) { return n.id === id; })[0];
    if (!node) return;
    if (node.type === "work") {
      fetch("/api/work/" + encodeURIComponent(id))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          renderRipple(d);     // 自动进入涟漪视图
          renderWorkPanel(d);  // 侧边栏显示详情
        });
    } else {
      renderAuthorView(node);  // 3D:该作者 + 他的书
      renderAuthorPanel(node);
    }
  }

  function renderAuthorView(author) {
    var nodes = [author];
    var edges = [];
    fullData.nodes.filter(function (n) {
      return n.type === "work" && n.author_id === author.id;
    }).forEach(function (w) {
      nodes.push(w);
      edges.push({ source: w.id, target: author.id, type: "authored" });
    });
    renderView("author", { nodes: nodes, edges: edges });
  }

  function renderAuthorPanel(author) {
    var works = fullData.nodes.filter(function (n) {
      return n.type === "work" && n.author_id === author.id;
    });
    var years = String(author.birthYear != null ? author.birthYear : "?") + " – " + String(author.deathYear != null ? author.deathYear : "?");
    var meta = [author.originalName || author.label_en, author.nationality, years, author.primaryLanguage ? "语言 " + author.primaryLanguage : ""]
      .filter(Boolean).join(" · ");
    var html =
      "<h2>" + esc(author.label) + "</h2>" +
      "<div class='meta'>" + esc(meta) + "</div>" +
      (author.bio ? "<p style='font-size:12px;color:#93a4c8;line-height:1.7'>" + esc(author.bio) + "</p>" : "") +
      "<h3>作品(" + works.length + ")</h3><ul>" +
      works.map(function (w) {
        return "<li class='work-item' data-id='" + esc(w.id) + "'><strong>" + esc(w.label) + "</strong> <small>(" + (w.year || "?") + " · " + esc(w.language || "") + ")</small></li>";
      }).join("") +
      "</ul><p style='font-size:12px;color:#93a4c8'>点击书籍可查看它的涟漪。</p>";
    el("panel-content").innerHTML = html;
    Array.prototype.forEach.call(el("panel-content").querySelectorAll(".work-item"), function (li) {
      li.addEventListener("click", function () {
        selectNode(li.getAttribute("data-id"));
      });
    });
  }

  function renderWorkPanel(d) {
    var w = d.work, a = d.author;
    var html =
      "<h2>" + esc(w.title) + "</h2>" +
      "<div class='meta'>" + esc(w.originalTitle || w.title_en) + " · " + esc(a.name) + " · " + (w.year || "?") + " · " + esc(w.language) + "</div>";
    if (w.summary) {
      html += "<p style='font-size:12px;color:#93a4c8;line-height:1.7'>" + esc(w.summary) + "</p>";
    }

    if (d.mentioned_by.length) {
      html += "<h3>谁提及了这本书(回声来源)</h3><ul>";
      d.mentioned_by.forEach(function (e) {
        html += "<li><span class='tag-mention'>提及</span>" +
          "<strong>" + esc(e.source_title) + "</strong> <small>(" + esc(e.source_author) + ")</small>" +
          "<div class='quote'>" + esc(e.evidence) + "</div>" +
          "<div class='quote' style='opacity:0.75'>" + esc(e.note || "") + "</div></li>";
      });
      html += "</ul>";
    }
    if (d.mentions.length) {
      html += "<h3>这本书提及了(涟漪扩散)</h3><ul>";
      d.mentions.forEach(function (e) {
        html += "<li><span class='tag-mention'>提及</span>" +
          "<strong>" + esc(e.target_title) + "</strong> <small>(" + esc(e.target_author) + ")</small>" +
          "<div class='quote'>" + esc(e.evidence) + "</div>" +
          "<div class='quote' style='opacity:0.75'>" + esc(e.note || "") + "</div></li>";
      });
      html += "</ul>";
    }
    if (!d.mentioned_by.length && !d.mentions.length) {
      html += "<p class='no-path'>这本书没有被其他书提及,也未提及别的书(孤岛星)。</p>";
    }
    el("panel-content").innerHTML = html;
  }

  function renderRipple(detail) {
    var center = detail.work.id;
    var ids = {};
    ids[center] = true;
    var nodes = [];
    var edges = [];

    detail.mentioned_by.forEach(function (e) {
      ids[e.source] = true;
      edges.push({ source: e.source, target: center, type: "echo", evidence: e.evidence, note: e.note });
    });
    detail.mentions.forEach(function (e) {
      ids[e.target] = true;
      edges.push({ source: center, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
    });
    Object.keys(ids).forEach(function (id) {
      var n = fullData.nodes.filter(function (x) { return x.id === id; })[0];
      if (!n) return;
      nodes.push(n);
    });

    renderView("ripple", { nodes: nodes, edges: edges, centerId: center });
  }

  function findPath() {
    var f = el("from").value.trim();
    var t = el("to").value.trim();
    var fromId = workLookup[f];
    var toId = workLookup[t];
    if (!fromId || !toId) {
      el("panel-content").innerHTML = "<p class='no-path'>请从下拉列表中选择两部作品。</p>";
      return;
    }
    fetch("/api/path?from=" + encodeURIComponent(fromId) + "&to=" + encodeURIComponent(toId))
      .then(function (r) { return r.status === 404 ? null : r.json(); })
      .then(function (result) {
        if (!result) {
          el("panel-content").innerHTML = "<p class='no-path'>未找到「" + esc(f) + " → " + esc(t) + "」的提及链。</p>";
          return;
        }
        renderPath(result, f, t);
      });
  }

  function renderPath(result, f, t) {
    var nodes = [];
    var edges = [];
    var ids = {};
    result.nodes.forEach(function (id) {
      var n = fullData.nodes.filter(function (x) { return x.id === id; })[0];
      if (n) { nodes.push(n); ids[id] = true; }
    });
    result.edges.forEach(function (e) {
      edges.push({ source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
      [e.source, e.target].forEach(function (id) {
        if (!ids[id]) {
          var n = fullData.nodes.filter(function (x) { return x.id === id; })[0];
          if (n) { nodes.push(n); ids[id] = true; }
        }
      });
    });
    renderView("path", { nodes: nodes, edges: edges, pathOrder: result.nodes });

    var html =
      "<h2>提及链(3D)</h2><div class='meta'>" + esc(f) + " → " + esc(t) + " · " + result.nodes.length + " 本书 / " + result.edges.length + " 次提及</div>";
    for (var i = 0; i < result.edges.length; i++) {
      var e = result.edges[i];
      var sn = fullData.nodes.filter(function (x) { return x.id === e.source; })[0];
      var tn = fullData.nodes.filter(function (x) { return x.id === e.target; })[0];
      html += "<div class='path-step'><strong>" + esc(sn ? sn.label : e.source) + "</strong> → " +
        "<strong>" + esc(tn ? tn.label : e.target) + "</strong>" +
        "<div class='edge'>提及 · " + esc(e.note || "") + "</div>" +
        "<div class='quote'>" + esc(e.evidence || "") + "</div></div>";
    }
    el("panel-content").innerHTML = html;
  }

  function showEmptyPanel() {
    el("panel-content").innerHTML =
      "<div id='panel-empty'><p>点击任意星星,自动展开它的涟漪;</p><p>右键拖拽旋转 · 左键拖拽平移 · 滚轮缩放。</p><p>顶部可搜索作品、查找提及链。</p></div>";
  }

  // =============================== UI wiring ===============================

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

  function wireEvents() {
    el("btn-path").onclick = findPath;
    el("btn-reset").onclick = function () { loadGraph(); showEmptyPanel(); };
    el("btn-back-main").onclick = function () { loadGraph(); };
    el("btn-example").onclick = function () {
      el("from").value = "伊利亚特 - 荷马";
      el("to").value = "活着 - 余华";
      findPath();
    };

    var qInput = el("q");
    qInput.addEventListener("input", function () {
      var q = qInput.value.trim();
      if (!q) { el("q-results").style.display = "none"; return; }
      fetch("/api/search?q=" + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var ul = el("q-results");
          ul.innerHTML = "";
          if (!data.hits.length) { ul.style.display = "none"; return; }
          data.hits.forEach(function (h) {
            var li = document.createElement("li");
            li.innerHTML = "<strong>" + esc(h.label) + "</strong> <small>" + esc(h.sub || h.type) + "</small>";
            li.onclick = function () {
              ul.style.display = "none";
              qInput.value = h.label;
              selectNode(h.id);
            };
            ul.appendChild(li);
          });
          ul.style.display = "block";
        });
    });
    document.addEventListener("click", function (e) {
      if (e.target.id !== "q") el("q-results").style.display = "none";
    });
  }

  // Deep links: #path=workA,workB  /  #ripple=workId
  function handleHash() {
    var h = location.hash.replace(/^#/, "");
    if (!h) return;
    if (h.indexOf("path=") === 0) {
      var parts = h.slice(5).split(",");
      if (parts.length === 2) {
        var f = fullData.nodes.filter(function (n) { return n.id === parts[0]; })[0];
        var t = fullData.nodes.filter(function (n) { return n.id === parts[1]; })[0];
        if (f && t) {
          el("from").value = f.label + " - " + (f.author || "");
          el("to").value = t.label + " - " + (t.author || "");
          findPath();
        }
      }
    } else if (h.indexOf("ripple=") === 0) {
      fetch("/api/work/" + encodeURIComponent(h.slice(7)))
        .then(function (r) { return r.json(); })
        .then(renderRipple);
    } else if (h.indexOf("author=") === 0) {
      selectNode(h.slice(7));
    }
  }

  // =============================== Boot ===============================

  initThree();
  initStarfield();
  wireEvents();
  loadGraph().catch(function (err) {
    el("graph").innerHTML = "<p style='padding:20px;color:#f87171'>加载图谱失败:" + esc(err.message) + "</p>";
  }).then(function () {
    handleHash();
  });
})();
