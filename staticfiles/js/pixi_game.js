let MAP_SIZE = 100;
const CELL = 8;
const INNER_MASS_THRESHOLD = 2;
const MAP_MARGIN = 20;

let app, world, borderLayer, gridLayer, cellLayer, massLayer, badgeLayer,
    amoebaLayer, selectionLayer, targetLayer, hoverLayer, arrowLayer;
let textures = {};
let pixiReady = false;
let arrowContainer = null;
let resizeObserver = null;
let lastGridZoom = -1;
let selectionGfx = null, selectionStart = 0, hoverGfx = null;

function makeDotPNG(size = 64) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const ctx = c.getContext('2d'); const cx = size / 2, r = size * 0.42;
  const grad = ctx.createRadialGradient(cx - r * 0.3, cx - r * 0.3, r * 0.1, cx, cx, r);
  grad.addColorStop(0, '#ffffff'); grad.addColorStop(0.55, '#efefef'); grad.addColorStop(1, '#b0b0b0');
  ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(cx, cx, r, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineWidth = size * 0.055; ctx.stroke();
  ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.lineWidth = size * 0.03;
  ctx.beginPath(); ctx.arc(cx, cx, r - size * 0.03, 0, Math.PI * 2); ctx.stroke();
  return c.toDataURL('image/png');
}
function makeDotGlowPNG(size = 96) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const ctx = c.getContext('2d'); const cx = size / 2, r = size * 0.4;
  const glow = ctx.createRadialGradient(cx, cx, r * 0.6, cx, cx, size / 2);
  glow.addColorStop(0, 'rgba(255,255,255,0.85)'); glow.addColorStop(0.5, 'rgba(255,255,255,0.35)');
  glow.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(cx, cx, size / 2, 0, Math.PI * 2); ctx.fill();
  const grad = ctx.createRadialGradient(cx, cx, 0, cx, cx, r);
  grad.addColorStop(0, '#ffffff'); grad.addColorStop(1, '#c0c0c0');
  ctx.fillStyle = grad; ctx.beginPath(); ctx.arc(cx, cx, r, 0, Math.PI * 2); ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.4)'; ctx.lineWidth = size * 0.05; ctx.stroke();
  return c.toDataURL('image/png');
}
function makeParticlePNG(size = 32) {
  const c = document.createElement('canvas'); c.width = c.height = size;
  const ctx = c.getContext('2d'); const cx = size / 2;
  const g = ctx.createRadialGradient(cx, cx, 0, cx, cx, cx);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.4, 'rgba(255,255,255,0.9)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cx, cx, 0, Math.PI * 2); ctx.fill();
  return c.toDataURL('image/png');
}

async function initPixi() {
  if (pixiReady) return;
  const container = document.getElementById('canvas-container');
  const rect = container.getBoundingClientRect();
  const w = Math.max(300, Math.floor(rect.width) || 800);
  const h = Math.max(300, Math.floor(rect.height) || 800);

  app = new PIXI.Application({ width: w, height: h, backgroundColor: 0x05050a, antialias: true });
  container.appendChild(app.view);

  world = new PIXI.Container(); app.stage.addChild(world);
  borderLayer = new PIXI.Container();
  gridLayer = new PIXI.Container();
  cellLayer = new PIXI.Container();
  massLayer = new PIXI.Container();
  badgeLayer = new PIXI.Container();
  amoebaLayer = new PIXI.Container();
  selectionLayer = new PIXI.Container();
  targetLayer = new PIXI.Container();
  hoverLayer = new PIXI.Container();
  arrowLayer = new PIXI.Container();
  world.addChild(borderLayer, gridLayer, cellLayer, massLayer, badgeLayer, amoebaLayer, selectionLayer, targetLayer, hoverLayer, arrowLayer);

  app.stage.eventMode = 'static';
  app.stage.hitArea = new PIXI.Rectangle(0, 0, w, h);
  app.stage.on('pointerdown', onStagePointerDown);
  app.stage.on('pointermove', onStagePointerMove);
  app.stage.on('pointerup', onStagePointerUp);
  app.stage.on('pointerupoutside', onStagePointerUp);

  const SPRITE_SOURCES = {
    dot: makeDotPNG(64), dot_glow: makeDotGlowPNG(96), particle: makeParticlePNG(32),
  };
  await PIXI.Assets.load(Object.values(SPRITE_SOURCES));
  for (const [key, url] of Object.entries(SPRITE_SOURCES)) {
    const tex = PIXI.Assets.get(url);
    tex.baseTexture.scaleMode = PIXI.SCALE_MODES.LINEAR;
    textures[key] = tex;
  }
  setupZoom();
  pixiReady = true;

  resizeObserver = new ResizeObserver(() => resizePixi());
  resizeObserver.observe(container);
  window.addEventListener('resize', resizePixi);
}

function resizePixi() {
  if (!app) return;
  const rect = document.getElementById('canvas-container').getBoundingClientRect();
  const w = Math.max(300, Math.floor(rect.width));
  const h = Math.max(300, Math.floor(rect.height));
  if (w <= 0 || h <= 0) return;
  if (app.renderer.width === w && app.renderer.height === h) return;
  app.renderer.resize(w, h);
  app.stage.hitArea = new PIXI.Rectangle(0, 0, w, h);
  clampWorld();
}

function drawBorder() {
  if (!borderLayer) return;
  borderLayer.removeChildren();
  const W = MAP_SIZE * CELL, H = MAP_SIZE * CELL;
  const dark = new PIXI.Graphics();
  dark.beginFill(0x000000, 0.5);
  dark.drawRect(-20000, -20000, 40000, 20000);
  dark.drawRect(-20000, H, 40000, 20000);
  dark.drawRect(-20000, 0, 20000, H);
  dark.drawRect(W, 0, 20000, H);
  dark.endFill();
  borderLayer.addChild(dark);
  const border = new PIXI.Graphics();
  border.lineStyle(1.5, 0x4477ff, 0.7);
  border.drawRect(0, 0, W, H);
  borderLayer.addChild(border);
}

function drawGridLines(force = false) {
  if (!gridLayer || !world) return;
  const zoom = world.scale.x;
  if (!force && Math.abs(zoom - lastGridZoom) < 0.1) return;
  lastGridZoom = zoom;

  gridLayer.removeChildren();
  if (zoom < 2.5) return;

  const alpha = Math.min(0.10, Math.max(0, (zoom - 2.5) * 0.035));
  if (alpha < 0.005) return;
  const lw = Math.min(0.4, 0.12 + zoom * 0.02);

  const W = MAP_SIZE * CELL, H = MAP_SIZE * CELL;
  const g = new PIXI.Graphics();
  g.lineStyle(lw, 0xffffff, alpha);
  for (let x = 1; x < MAP_SIZE; x++) { g.moveTo(x * CELL, 0); g.lineTo(x * CELL, H); }
  for (let y = 1; y < MAP_SIZE; y++) { g.moveTo(0, y * CELL); g.lineTo(W, y * CELL); }
  gridLayer.addChild(g);
}

function clampWorld() {
  if (!world || !app) return;
  const zoom = world.scale.x;
  const fieldW = MAP_SIZE * CELL * zoom;
  const fieldH = MAP_SIZE * CELL * zoom;
  const vw = app.renderer.width, vh = app.renderer.height;
  const margin = MAP_MARGIN;
  if (fieldW + 2 * margin <= vw) world.x = (vw - fieldW) / 2;
  else world.x = Math.min(margin, Math.max(vw - fieldW - margin, world.x));
  if (fieldH + 2 * margin <= vh) world.y = (vh - fieldH) / 2;
  else world.y = Math.min(margin, Math.max(vh - fieldH - margin, world.y));
}

function setupZoom() {
  const canvas = app.view;
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!world) return;
    const factor = e.deltaY > 0 ? 0.85 : 1.15;
    const rect = canvas.getBoundingClientRect();
    const sx = (e.clientX - rect.left) * (canvas.width / rect.width);
    const sy = (e.clientY - rect.top) * (canvas.height / rect.height);
    const newZoom = Math.max(0.5, Math.min(8, world.scale.x * factor));
    const r = newZoom / world.scale.x;
    world.x = sx - (sx - world.x) * r;
    world.y = sy - (sy - world.y) * r;
    world.scale.set(newZoom);
    clampWorld();
    drawGridLines();
  }, { passive: false });
}

function zoomToMyDots(animate = true) {
  if (!world || !app) return;
  const vw = app.renderer.width, vh = app.renderer.height;
  const myCells = [...state.grid.values()].filter(c => c.owner === state.playerId);
  if (!myCells.length) { world.position.set(0, 0); world.scale.set(1); clampWorld(); drawGridLines(true); return; }
  const xs = myCells.map(c => c.x), ys = myCells.map(c => c.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 4;
  const w = (maxX - minX + pad * 2) * CELL;
  const h = (maxY - minY + pad * 2) * CELL;
  const zoom = Math.max(0.5, Math.min(8, Math.min(vw / w, vh / h)));
  const cx = (minX + maxX + 1) / 2 * CELL;
  const cy = (minY + maxY + 1) / 2 * CELL;
  const targetX = vw / 2 - cx * zoom;
  const targetY = vh / 2 - cy * zoom;
  if (animate) animateWorld(targetX, targetY, zoom, 500);
  else { world.position.set(targetX, targetY); world.scale.set(zoom); clampWorld(); drawGridLines(true); }
}

function animateWorld(tx, ty, tzoom, dur) {
  const sx = world.x, sy = world.y, szoom = world.scale.x;
  const start = performance.now();
  const tick = () => {
    const t = Math.min(1, (performance.now() - start) / dur);
    const e = 1 - Math.pow(1 - t, 3);
    world.x = sx + (tx - sx) * e;
    world.y = sy + (ty - sy) * e;
    world.scale.set(szoom + (tzoom - szoom) * e);
    if (t < 1) requestAnimationFrame(tick);
    else { clampWorld(); drawGridLines(true); }
  };
  tick();
}

function screenToCell(gx, gy) {
  const wx = (gx - world.x) / world.scale.x;
  const wy = (gy - world.y) / world.scale.y;
  return { cx: Math.floor(wx / CELL), cy: Math.floor(wy / CELL) };
}

let isDragging = false, dragStart = { x: 0, y: 0 }, worldStart = { x: 0, y: 0 }, hasMoved = false;

function onStagePointerDown(e) {
  if (state.gameOver || !world) return;
  if (e.button !== 0 && e.nativeEvent && e.nativeEvent.button !== 0) return;
  isDragging = true; hasMoved = false;
  dragStart = { x: e.global.x, y: e.global.y };
  worldStart = { x: world.x, y: world.y };
}
function onStagePointerMove(e) {
  if (!world) return;
  if (isDragging) {
    const dx = e.global.x - dragStart.x, dy = e.global.y - dragStart.y;
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) hasMoved = true;
    if (hasMoved) { world.x = worldStart.x + dx; world.y = worldStart.y + dy; clampWorld(); clearHover(); }
    return;
  }
  if (state.gameOver) { clearHover(); return; }
  if (!state.selected || !state.validTargets.length) { if (state.hoveredTarget) clearHover(); return; }
  const { cx, cy } = screenToCell(e.global.x, e.global.y);
  const target = state.validTargets.find(t => t.x === cx && t.y === cy);
  if (!target) { if (state.hoveredTarget) clearHover(); return; }
  if (state.hoveredTarget && state.hoveredTarget.x === cx && state.hoveredTarget.y === cy) return;
  state.hoveredTarget = target;
  drawHoverCell(cx, cy, target.type);
  if (target.type === 'attack' && state.selected) drawAttackArrow(state.selected[0], state.selected[1], cx, cy);
  else clearArrow();
  updateSelectedInfo();
}
function onStagePointerUp(e) {
  if (!isDragging) return;
  isDragging = false;
  if (hasMoved) return;
  if (state.gameOver) return;
  const { cx, cy } = screenToCell(e.global.x, e.global.y);
  if (cx < 0 || cy < 0 || cx >= MAP_SIZE || cy >= MAP_SIZE) return;
  handleCellClick(cx, cy);
}

/* ARROW */
function clearArrow() {
  if (arrowContainer && !arrowContainer.destroyed) arrowContainer.destroy({ children: true });
  arrowContainer = null;
}
function drawAttackArrow(fromX, fromY, toX, toY) {
  clearArrow(); if (!arrowLayer) return;
  const container = new PIXI.Container();
  arrowContainer = container;
  arrowLayer.addChild(container);
  const ax = fromX * CELL + CELL / 2, ay = fromY * CELL + CELL / 2;
  const bx = toX * CELL + CELL / 2, by = toY * CELL + CELL / 2;
  if (ax === bx && ay === by) return;
  const line = new PIXI.Graphics();
  line.lineStyle(1, 0xff5544, 0.55); line.moveTo(ax, ay); line.lineTo(bx, by);
  container.addChild(line);
  const angle = Math.atan2(by - ay, bx - ax);
  const headG = new PIXI.Graphics();
  headG.beginFill(0xff5544, 0.95); headG.moveTo(bx, by);
  headG.lineTo(bx - 4 * Math.cos(angle - 0.4), by - 4 * Math.sin(angle - 0.4));
  headG.lineTo(bx - 4 * Math.cos(angle + 0.4), by - 4 * Math.sin(angle + 0.4));
  headG.closePath(); headG.endFill(); container.addChild(headG);
  const pulses = [];
  for (let i = 0; i < 3; i++) {
    const p = new PIXI.Graphics();
    p.beginFill(0xffaa88, 1); p.drawCircle(0, 0, 1.5); p.endFill();
    p.__offset = i / 3; p.x = ax; p.y = ay;
    container.addChild(p); pulses.push(p);
  }
  const startT = performance.now();
  const tick = () => {
    if (arrowContainer !== container || container.destroyed) return;
    const elapsed = (performance.now() - startT) / 1000;
    const cycle = (elapsed * 0.9) % 1;
    for (const p of pulses) {
      const lt = (cycle + p.__offset) % 1;
      p.x = ax + (bx - ax) * lt; p.y = ay + (by - ay) * lt;
      p.alpha = Math.sin(lt * Math.PI);
    }
    line.alpha = 0.45 + 0.25 * Math.sin(elapsed * Math.PI * 4);
    headG.alpha = 0.7 + 0.25 * Math.sin(elapsed * Math.PI * 4);
    requestAnimationFrame(tick);
  };
  tick();
}

/* VISUAL */
function isDimmed(x, y, cell) {
  const owner = state.players[cell.owner];
  if (!owner) return false;
  if (owner.surrendered) return true;
  if (cell.acted) return true;
  if (owner.moves_used >= 3) return true;
  return false;
}
function isInner(x, y, owner) {
  for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
    const nc = state.grid.get(`${x+dx},${y+dy}`);
    if (!nc || nc.owner !== owner) return false;
  }
  return true;
}
function makeSprite(x, y, owner, strength) {
  const player = state.players[owner]; if (!player) return null;
  const cell = state.grid.get(`${x},${y}`);
  const colorNum = parseInt(player.color.slice(1), 16);
  const container = new PIXI.Container();
  container.x = x * CELL + CELL / 2; container.y = y * CELL + CELL / 2;
  container.__key = `${x},${y}`;
  const dim = cell ? isDimmed(x, y, cell) : false;
  const surrendered = player.surrendered === true;

  let hasNeighbor = false;
  for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
    const nc = state.grid.get(`${x+dx},${y+dy}`);
    if (nc && nc.owner === owner) { hasNeighbor = true; break; }
  }
  if (strength >= 3 && !hasNeighbor && !surrendered) {
    const glow = new PIXI.Sprite(textures.dot_glow);
    glow.anchor.set(0.5);
    const glowSize = CELL * Math.min(3.5, 1.8 + strength * 0.25);
    glow.width = glowSize; glow.height = glowSize; glow.tint = colorNum;
    glow.alpha = (dim ? 0.15 : 0.45) + Math.min(0.35, (strength - 3) * 0.1);
    container.addChild(glow);
  }
  const dot = new PIXI.Sprite(textures.dot);
  dot.anchor.set(0.5); dot.width = CELL * 0.85; dot.height = CELL * 0.85;
  dot.tint = colorNum;
  dot.alpha = surrendered ? 0.35 : (dim ? 0.5 : 0.85);
  container.addChild(dot);

  if (surrendered) {
    const frozenRing = new PIXI.Graphics();
    frozenRing.lineStyle(0.8, 0x888888, 0.7);
    frozenRing.drawCircle(0, 0, CELL * 0.48);
    container.addChild(frozenRing);
  }
  return container;
}
function makeBadge(x, y, owner, strength) {
  const player = state.players[owner];
  if (!player || strength <= 1) return null;
  const cell = state.grid.get(`${x},${y}`);
  const dim = cell ? isDimmed(x, y, cell) : false;
  const colorNum = parseInt(player.color.slice(1), 16);
  const container = new PIXI.Container();
  container.x = x * CELL + CELL / 2; container.y = y * CELL + CELL / 2;
  const alpha = dim ? 0.5 : 0.9;

  const r_vis = 0.42 * CELL * 0.85;
  const s = 0.8;

  const tw = 0.60 * r_vis * s;
  const th = 0.80 * r_vis * s;
  const bh = 0.95 * r_vis * s;

  const shield = new PIXI.Graphics();
  shield.beginFill(0x000000, alpha * 0.85);
  shield.lineStyle(0.5, colorNum, alpha);
  shield.moveTo(-tw, -th); shield.lineTo(tw, -th); shield.lineTo(tw, 0);
  shield.quadraticCurveTo(tw, bh * 0.6, 0, bh);
  shield.quadraticCurveTo(-tw, bh * 0.6, -tw, 0);
  shield.closePath();

  const cy = 0.05 * r_vis;
  const r_circ = 0.45 * r_vis;
  shield.lineStyle(0.4, colorNum, alpha);
  shield.drawCircle(0, cy, r_circ);
  shield.endFill();
  container.addChild(shield);

  const text = new PIXI.Text(String(strength), {
    fontFamily: 'Arial, sans-serif', fontSize: 22, fontWeight: 'bold',
    fill: colorNum, align: 'center',
  });
  text.anchor.set(0.5);
  text.scale.set(0.09);
  text.y = cy;
  container.addChild(text);

  if (player.surrendered) container.alpha = 0.4;
  return container;
}
function updateSprite(key, cell) {
  const old = state.sprites.get(key);
  const [x, y] = key.split(',').map(Number);
  if (old) { cellLayer.removeChild(old); old.destroy({ children: true }); }
  const s = makeSprite(x, y, cell.owner, cell.strength);
  if (s) {
    cellLayer.addChild(s); state.sprites.set(key, s);
    if (!old && !cell.__animateFrom) animateScale(s, 0, 1, 300);
    else if (!old && cell.__animateFrom) { s.scale.set(0.4); s.alpha = 0.7; }
    else s.scale.set(1);
  } else state.sprites.delete(key);
  const oldB = state.badges.get(key);
  if (oldB) { badgeLayer.removeChild(oldB); oldB.destroy({ children: true }); }
  const b = makeBadge(x, y, cell.owner, cell.strength);
  if (b) { badgeLayer.addChild(b); state.badges.set(key, b); }
  else state.badges.delete(key);
  state.strengthMap.set(key, cell.strength);
}
function refreshAround(x, y) {
  for (const [cx, cy] of [[x,y],[x+1,y],[x-1,y],[x,y+1],[x,y-1]]) {
    const key = `${cx},${cy}`; const c = state.grid.get(key);
    if (c) updateSprite(key, c);
  }
}
function refreshPlayerCells(ownerId) {
  for (const [key, c] of state.grid) if (c.owner === ownerId) updateSprite(key, c);
}
function clearPixi() {
  if (!cellLayer) return;
  for (const s of state.sprites.values()) if (!s.destroyed) s.destroy({ children: true });
  cellLayer.removeChildren(); state.sprites.clear();
  for (const b of state.badges.values()) if (!b.destroyed) b.destroy({ children: true });
  badgeLayer.removeChildren(); state.badges.clear(); state.strengthMap.clear();
  if (massLayer) massLayer.removeChildren();
  if (amoebaLayer) amoebaLayer.removeChildren();
  if (selectionGfx && !selectionGfx.destroyed) selectionGfx.destroy();
  selectionGfx = null; selectionStart = 0;
}

/* MASS */
function computeInnerComponents() {
  const inner = new Set();
  for (const [key, c] of state.grid) {
    const [x, y] = key.split(',').map(Number);
    if (isInner(x, y, c.owner)) inner.add(key);
  }
  const visited = new Set(); const result = [];
  for (const startKey of inner) {
    if (visited.has(startKey)) continue;
    const owner = state.grid.get(startKey).owner;
    const queue = [startKey]; const comp = new Set([startKey]);
    visited.add(startKey);
    while (queue.length) {
      const k = queue.shift(); const [x, y] = k.split(',').map(Number);
      for (const [dx, dy] of [[1,0],[-1,0],[0,1],[0,-1]]) {
        const nk = `${x+dx},${y+dy}`;
        if (!inner.has(nk) || visited.has(nk)) continue;
        visited.add(nk); comp.add(nk); queue.push(nk);
      }
    }
    result.push({ owner, cells: comp });
  }
  return result;
}
function buildContour(cells) {
  const edges = [];
  for (const key of cells) {
    const [x, y] = key.split(',').map(Number);
    if (!cells.has(`${x + 1},${y}`)) edges.push({ x1: x + 1, y1: y, x2: x + 1, y2: y + 1 });
    if (!cells.has(`${x},${y + 1}`)) edges.push({ x1: x + 1, y1: y + 1, x2: x, y2: y + 1 });
    if (!cells.has(`${x - 1},${y}`)) edges.push({ x1: x, y1: y + 1, x2: x, y2: y });
    if (!cells.has(`${x},${y - 1}`)) edges.push({ x1: x, y1: y, x2: x + 1, y2: y });
  }
  const pointKey = (x, y) => `${x},${y}`;
  const edgeStarts = new Map();
  edges.forEach((e, i) => {
    const k = pointKey(e.x1, e.y1);
    if (!edgeStarts.has(k)) edgeStarts.set(k, []);
    edgeStarts.get(k).push(i);
  });
  const used = new Set(); const contours = [];
  for (let i = 0; i < edges.length; i++) {
    if (used.has(i)) continue;
    const contour = []; let cur = i; used.add(i);
    contour.push([edges[i].x1, edges[i].y1]);
    let safety = 0;
    while (safety++ < 100000) {
      const e = edges[cur]; contour.push([e.x2, e.y2]);
      const candidates = edgeStarts.get(pointKey(e.x2, e.y2)) || [];
      let next = -1;
      for (const c of candidates) if (!used.has(c)) { next = c; break; }
      if (next === -1) break;
      used.add(next); cur = next;
      if (edges[cur].x1 === contour[0][0] && edges[cur].y1 === contour[0][1]) break;
    }
    if (contour.length < 3) continue;
    if (contour.length > 1 && contour[0][0] === contour[contour.length - 1][0] && contour[0][1] === contour[contour.length - 1][1]) contour.pop();
    contours.push(contour.map(([cx, cy]) => [cx * CELL, cy * CELL]));
  }
  return contours;
}
function buildSmoothPath(g, pts) {
  if (pts.length > 1) {
    const first = pts[0]; const last = pts[pts.length - 1];
    if (first[0] === last[0] && first[1] === last[1]) pts = pts.slice(0, -1);
  }
  const n = pts.length; if (n < 3) return;
  const mx0 = (pts[0][0] + pts[1][0]) / 2;
  const my0 = (pts[0][1] + pts[1][1]) / 2;
  g.moveTo(mx0, my0);
  for (let i = 1; i <= n; i++) {
    const curr = pts[i % n]; const next = pts[(i + 1) % n];
    g.quadraticCurveTo(curr[0], curr[1], (curr[0] + next[0]) / 2, (curr[1] + next[1]) / 2);
  }
  g.closePath();
}
function drawInnerMass(contourPts, colorNum, dim, surrendered) {
  const fillAlpha = dim ? 0.20 : 0.52;
  const outlineAlpha = dim ? 0.18 : 0.48;
  const fillG = new PIXI.Graphics();
  fillG.beginFill(colorNum, surrendered ? 0.10 : fillAlpha);
  buildSmoothPath(fillG, contourPts); fillG.endFill();
  massLayer.addChild(fillG);
  const outline = new PIXI.Graphics();
  outline.lineStyle(1.1, colorNum, surrendered ? 0.15 : outlineAlpha);
  buildSmoothPath(outline, contourPts); massLayer.addChild(outline);
}
function redrawMasses() {
  if (!massLayer) return;
  massLayer.removeChildren();
  const comps = computeInnerComponents();
  for (const { owner, cells } of comps) {
    if (cells.size < INNER_MASS_THRESHOLD) continue;
    const player = state.players[owner]; if (!player) continue;
    const colorNum = parseInt(player.color.slice(1), 16);
    const me = state.players[owner];
    const playerOut = me && me.moves_used >= 3;
    let allActed = true;
    for (const k of cells) { const c = state.grid.get(k); if (c && !c.acted) { allActed = false; break; } }
    const dim = playerOut || allActed || player.surrendered;
    const contours = buildContour(cells);
    for (const contourPts of contours) drawInnerMass(contourPts, colorNum, dim, player.surrendered);
  }
}

/* SELECTION / HOVER */
function lightenPixi(color, amt) {
  const r = (color >> 16) & 0xff, g = (color >> 8) & 0xff, b = color & 0xff;
  return (Math.round(r + (255 - r) * amt) << 16) | (Math.round(g + (255 - g) * amt) << 8) | Math.round(b + (255 - b) * amt);
}
function clearTargets() {
  if (targetLayer) targetLayer.removeChildren();
  clearHover(); clearArrow();
  state.validTargets = [];
}
function fadeOutAndDestroy(g, dur) {
  const initAlpha = g.alpha; const start = performance.now();
  const tick = () => {
    if (g.destroyed) return;
    const t = Math.min(1, (performance.now() - start) / dur);
    g.alpha = initAlpha * (1 - t);
    if (t < 1) requestAnimationFrame(tick);
    else if (!g.destroyed) g.destroy();
  };
  tick();
}
function clearHover() {
  state.hoveredTarget = null;
  if (hoverGfx && !hoverGfx.destroyed) { const g = hoverGfx; hoverGfx = null; fadeOutAndDestroy(g, 120); }
  clearArrow(); updateSelectedInfo();
}
function renderSelection() {
  if (!selectionLayer) return;
  if (!state.selected) {
    if (selectionGfx && !selectionGfx.destroyed) selectionGfx.destroy();
    selectionGfx = null; selectionStart = 0; return;
  }
  const [x, y] = state.selected;
  if (selectionGfx && !selectionGfx.destroyed && selectionGfx.__cx === x && selectionGfx.__cy === y) return;
  if (selectionGfx && !selectionGfx.destroyed) selectionGfx.destroy();
  const player = state.players[state.playerId];
  if (!player) { selectionGfx = null; return; }
  const g = new PIXI.Graphics();
  g.x = x * CELL + CELL / 2; g.y = y * CELL + CELL / 2;
  g.__cx = x; g.__cy = y;
  selectionLayer.addChild(g); selectionGfx = g; selectionStart = performance.now();
  const r = CELL * 0.42;
  const baseColor = parseInt(player.color.slice(1), 16);
  const lightColor = lightenPixi(baseColor, 0.4);
  const tick = () => {
    if (selectionGfx !== g || g.destroyed) return;
    const elapsed = (performance.now() - selectionStart) / 1000;
    const pulse = 0.5 + 0.5 * Math.sin(elapsed * Math.PI * 0.75);
    g.clear();
    g.lineStyle(1.3, lightColor, 0.45 + 0.55 * pulse);
    g.drawCircle(0, 0, r);
    requestAnimationFrame(tick);
  };
  tick();
}
function drawHoverCell(x, y, type) {
  if (hoverGfx && !hoverGfx.destroyed && hoverGfx.__cx === x && hoverGfx.__cy === y) return;
  if (hoverGfx && !hoverGfx.destroyed) { const old = hoverGfx; hoverGfx = null; fadeOutAndDestroy(old, 100); }
  const g = new PIXI.Graphics();
  g.x = x * CELL + CELL / 2; g.y = y * CELL + CELL / 2;
  g.__cx = x; g.__cy = y;
  hoverLayer.addChild(g); hoverGfx = g;
  const start = performance.now();
  const r = CELL * 0.5;
  const tick = () => {
    if (g.destroyed) return;
    const t = Math.min(1, (performance.now() - start) / 200);
    const elapsed = (performance.now() - start) / 1000;
    const pulse = 0.5 + 0.5 * Math.sin(elapsed * Math.PI * 1.0);
    g.clear();
    g.lineStyle(1.0, 0xffffff, (0.15 + 0.85 * pulse) * t);
    g.drawCircle(0, 0, r);
    g.alpha = t; requestAnimationFrame(tick);
  };
  tick();
}
function updateTargets() {
  if (!targetLayer) return;
  clearTargets();
  if (!state.selected || state.gameOver) return;
  const me = state.players[state.playerId];
  if (!me || me.surrendered) return;
  const [sx, sy] = state.selected;
  const cell = state.grid.get(`${sx},${sy}`);
  if (!cell || cell.owner !== state.playerId || cell.acted) return;
  if (me.moves_used >= 3) return;
  for (const [dx, dy] of [[0,1],[0,-1],[1,0],[-1,0]]) {
    const nx = sx + dx, ny = sy + dy;
    if (nx < 0 || ny < 0 || nx >= MAP_SIZE || ny >= MAP_SIZE) continue;
    const ncell = state.grid.get(`${nx},${ny}`);
    let type = null;
    if (!ncell) type = 'expand';
    else if (ncell.owner !== state.playerId) type = 'attack';
    if (!type) continue;
    state.validTargets.push({ x: nx, y: ny, type });
  }
}

/* ANIMATIONS */
function animateScale(obj, from, to, dur) {
  obj.scale.set(from); const start = performance.now();
  const tick = () => {
    if (obj.destroyed) return;
    const t = Math.min(1, (performance.now() - start) / dur);
    const e = 1 - Math.pow(1 - t, 3);
    obj.scale.set(from + (to - from) * e);
    if (t < 1) requestAnimationFrame(tick);
  };
  tick();
}
function animateAmoebaFull(targetX, targetY, fromX, fromY, colorNum) {
  if (!amoebaLayer) return;
  const cellSprite = state.sprites.get(`${targetX},${targetY}`);
  if (!cellSprite || cellSprite.destroyed) return;
  const startX = fromX * CELL + CELL / 2, startY = fromY * CELL + CELL / 2;
  const endX = targetX * CELL + CELL / 2, endY = targetY * CELL + CELL / 2;
  const dur = 600, start = performance.now();
  cellSprite.x = startX; cellSprite.y = startY;
  cellSprite.scale.set(0.4); cellSprite.alpha = 0.6;
  const N = 4, bubbles = [];
  for (let i = 0; i < N; i++) {
    const b = new PIXI.Graphics();
    b.beginFill(colorNum, 0.85); b.drawCircle(0, 0, 2.2); b.endFill();
    b.x = startX; b.y = startY; b.alpha = 0;
    b.__delay = i * 0.11; b.__dur = 0.45;
    amoebaLayer.addChild(b); bubbles.push(b);
  }
  const tick = () => {
    const cellAlive = !cellSprite.destroyed;
    const elapsed = (performance.now() - start) / 1000;
    if (cellAlive) {
      const t = Math.min(1, elapsed / (dur / 1000));
      const e = 1 - Math.pow(1 - t, 3);
      cellSprite.x = startX + (endX - startX) * e;
      cellSprite.y = startY + (endY - startY) * e;
      let sc;
      if (t < 0.7) sc = 0.4 + (1.12 - 0.4) * (t / 0.7);
      else sc = 1.12 - 0.12 * ((t - 0.7) / 0.3);
      cellSprite.scale.set(sc); cellSprite.alpha = 0.6 + 0.4 * t;
      if (t >= 1) { cellSprite.scale.set(1); cellSprite.alpha = 1; }
    }
    let anyBubble = false;
    for (const b of bubbles) {
      if (b.destroyed) continue;
      const bt0 = elapsed - b.__delay;
      if (bt0 < 0) { anyBubble = true; continue; }
      const bt = Math.min(1, bt0 / b.__dur);
      const be = bt * bt;
      b.x = startX + (endX - startX) * be;
      b.y = startY + (endY - startY) * be;
      b.alpha = Math.sin(bt * Math.PI) * 0.85;
      b.scale.set(1 - bt * 0.4);
      if (bt >= 1) b.destroy(); else anyBubble = true;
    }
    if (anyBubble || (cellAlive && cellSprite.scale.x !== 1)) requestAnimationFrame(tick);
  };
  tick();
}
function animateFade(obj, dur) {
  const start = performance.now(); const s0 = obj.scale.x;
  const tick = () => {
    if (obj.destroyed) return;
    const t = Math.min(1, (performance.now() - start) / dur);
    obj.alpha = 1 - t; obj.scale.set(s0 * (1 - t * 0.5));
    if (t < 1) requestAnimationFrame(tick);
    else if (!obj.destroyed) obj.destroy({ children: true });
  };
  tick();
}
function animateColorFlash(x, y, colorHex) {
  const flash = new PIXI.Graphics();
  flash.beginFill(parseInt(colorHex.slice(1), 16), 1);
  flash.drawCircle(0, 0, CELL * 1.2); flash.endFill();
  flash.x = x * CELL + CELL / 2; flash.y = y * CELL + CELL / 2;
  flash.alpha = 0.9; cellLayer.addChild(flash);
  const start = performance.now();
  const tick = () => {
    if (flash.destroyed) return;
    const t = Math.min(1, (performance.now() - start) / 300);
    flash.alpha = 0.9 * (1 - t); flash.scale.set(1 + t * 1.5);
    if (t < 1) requestAnimationFrame(tick);
    else if (!flash.destroyed) flash.destroy();
  };
  tick();
}
function burstParticles(x, y, colorHex) {
  if (!textures.particle) return;
  const colorNum = parseInt(colorHex.slice(1), 16);
  for (let i = 0; i < 10; i++) {
    const p = new PIXI.Sprite(textures.particle);
    p.anchor.set(0.5); p.tint = colorNum;
    p.width = p.height = 3 + Math.random() * 4;
    p.x = x * CELL + CELL / 2; p.y = y * CELL + CELL / 2;
    cellLayer.addChild(p);
    const ang = Math.random() * Math.PI * 2;
    const sp = 0.7 + Math.random() * 2;
    const vx = Math.cos(ang) * sp, vy = Math.sin(ang) * sp;
    let life = 1;
    const tick = () => {
      if (p.destroyed) return;
      p.x += vx; p.y += vy; p.alpha = life; life -= 0.045;
      if (life > 0) requestAnimationFrame(tick);
      else if (!p.destroyed) p.destroy();
    };
    tick();
  }
}

async function enterGameWithPreloader(msg) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.body.classList.remove('in-game');
  document.getElementById('game-preloader').classList.add('active');

  await initPixi();
  setReconnectOverlay(false);

  if (msg.game_id && msg.game_id !== state.gameId) {
    state.gameId = msg.game_id;
    const logEl = document.getElementById('log');
    if (logEl) logEl.innerHTML = '';
    state.lastAdTurn = 0;
  }
  syncFull(msg);

  await new Promise(r => setTimeout(r, 2500));

  document.getElementById('game-preloader').classList.remove('active');
  showScreen('game-screen');
}

function syncFull(msg) {
  MAP_SIZE = msg.map_size || 100;
  state.mapSize = MAP_SIZE;
  state.gameName = msg.game_name || null;
  state.grid.clear();
  state.players = msg.players;
  state.turn = msg.turn;
  state.turnEndsAt = msg.turn_ends_at;
  state.gameOver = false;
  state.selected = null;
  state.warned10Sec = false;
  state.warned20Pct = false;
  clearTargets();
  state.disconnected = {};
  for (const p of Object.values(state.players)) {
    if (p.disconnected) state.disconnected[p.id] = Date.now();
  }
  clearPixi();
  drawBorder();
  drawGridLines(true);
  for (const c of msg.grid) {
    const key = `${c.x},${c.y}`;
    state.grid.set(key, c);
    state.strengthMap.set(key, c.strength);
    const s = makeSprite(c.x, c.y, c.owner, c.strength);
    if (s) { cellLayer.addChild(s); state.sprites.set(key, s); animateScale(s, 0, 1, 300); }
    const b = makeBadge(c.x, c.y, c.owner, c.strength);
    if (b) { badgeLayer.addChild(b); state.badges.set(key, b); }
  }
  for (const c of msg.grid) updateSprite(`${c.x},${c.y}`, c);
  redrawMasses(); renderAll();
  resizePixi();
  setTimeout(() => zoomToMyDots(true), 50);
  setTimeout(checkFieldThresholds, 100);

  if (msg.prize_pool > 0) {
    document.getElementById('field-prize').style.display = 'flex';
    document.getElementById('prize-val').innerHTML = `${ICONS.dts(28)} ${msg.prize_pool}`;
  } else {
    document.getElementById('field-prize').style.display = 'none';
  }
}

function applyChanges(msg) {
  const touched = [];
  let captured = false;

  for (const c of msg.changes) {
    const key = `${c.x},${c.y}`;
    if (c.owner === null) {
      const s = state.sprites.get(key); if (s) animateFade(s, 250);
      state.sprites.delete(key); state.strengthMap.delete(key); state.grid.delete(key);
      const b = state.badges.get(key);
      if (b) { badgeLayer.removeChild(b); b.destroy({ children: true }); }
      state.badges.delete(key); touched.push([c.x, c.y]);
    } else {
      const prev = state.grid.get(key);
      state.grid.set(key, c);
      if (prev && prev.owner !== c.owner) {
        const pl = state.players[c.owner];
        if (pl) { animateColorFlash(c.x, c.y, pl.color); captured = true; }
      }
      touched.push([c.x, c.y]);
    }
  }
  state.players = msg.players;
  if (captured) playSound('capture');
  for (const [x, y] of touched) refreshAround(x, y);
  if (msg.actor && msg.players[msg.actor]) refreshPlayerCells(msg.actor);

  if (msg.action_type === 'expand' && msg.action_from && msg.action_to) {
    const [fx, fy] = msg.action_from;
    const [tx, ty] = msg.action_to;
    const tkey = `${tx},${ty}`;
    const tcell = state.grid.get(tkey);
    if (tcell && tcell.owner === msg.actor) {
      const colorNum = state.players[msg.actor] ? parseInt(state.players[msg.actor].color.slice(1), 16) : 0xffffff;
      animateAmoebaFull(tx, ty, fx, fy, colorNum);
    }
  }

  if (state.selected) {
    const [sx, sy] = state.selected;
    const selCell = state.grid.get(`${sx},${sy}`);
    if (!selCell || selCell.owner !== state.playerId) { state.selected = null; clearTargets(); }
    else updateTargets();
  }
  if (msg.dts_gained) {
    for (const [pid, amount] of Object.entries(msg.dts_gained)) {
      const p = msg.players[pid];
      if (p) {
        if (pid === state.playerId) { playSound('income'); log(`+${amount} ${ICONS.dts(18)}`); }
        else log(`${p.name} +${amount} ${ICONS.dts(18)}`);
      }
    }
  }
  redrawMasses(); renderAll();
  checkFieldThresholds();
}