import * as THREE from 'three';

// Floating "plugin tile" constellation for the marketplace landing page.
// Everything is procedural: canvas-painted abstract tiles, a particle field,
// and a slow wireframe icosahedron for depth. No network calls, no assets.
// The tiles are deliberately theme-free (varied hues, geometric glyphs) —
// this is a marketplace page, not a single-plugin page.

const canvas = document.getElementById('scene');
let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch {
  // No WebGL (old browser, disabled GPU): drop the backdrop, keep the page.
  canvas.remove();
}
if (!renderer) {
  // Nothing further to animate; UI wiring below is renderer-independent.
} else {
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x0b0e14, 0.07);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
camera.position.set(0, 0.4, 9);

// Muted jewel tones that sit well on the dark background.
const TILE_HUES = ['#ffd60a', '#5eead4', '#a78bfa', '#7dd3fc', '#f9a8d4', '#bef264'];

function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function makeTileTexture(seed) {
  const s = 256;
  const el = document.createElement('canvas');
  el.width = s;
  el.height = s;
  const ctx = el.getContext('2d');
  const hue = TILE_HUES[seed % TILE_HUES.length];
  // Tile body.
  roundRectPath(ctx, 8, 8, s - 16, s - 16, 48);
  ctx.fillStyle = '#151b28';
  ctx.fill();
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 6;
  ctx.strokeStyle = hue;
  ctx.stroke();
  ctx.globalAlpha = 1;
  // Centered abstract glyph, picked by seed.
  ctx.strokeStyle = hue;
  ctx.fillStyle = hue;
  ctx.lineWidth = 14;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  const c = s / 2;
  const r = 52;
  switch (seed % 5) {
    case 0: // ring
      ctx.beginPath();
      ctx.arc(c, c, r, 0, Math.PI * 2);
      ctx.stroke();
      break;
    case 1: // plus
      ctx.beginPath();
      ctx.moveTo(c - r, c);
      ctx.lineTo(c + r, c);
      ctx.moveTo(c, c - r);
      ctx.lineTo(c, c + r);
      ctx.stroke();
      break;
    case 2: // triangle
      ctx.beginPath();
      ctx.moveTo(c, c - r);
      ctx.lineTo(c + r * 0.9, c + r * 0.7);
      ctx.lineTo(c - r * 0.9, c + r * 0.7);
      ctx.closePath();
      ctx.stroke();
      break;
    case 3: // bars
      for (let b = -1; b <= 1; b++) {
        const h = r * (b === 0 ? 1.4 : 0.9);
        ctx.fillRect(c + b * 44 - 11, c - h / 2, 22, h);
      }
      break;
    default: // dot with orbit ring
      ctx.beginPath();
      ctx.arc(c, c, 16, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 0.7;
      ctx.lineWidth = 8;
      ctx.beginPath();
      ctx.arc(c, c, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      break;
  }
  const tex = new THREE.CanvasTexture(el);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

// Fewer cards on small screens: cheaper to render, less visual clutter.
const CARD_COUNT = window.innerWidth < 640 ? 8 : 14;
const cards = [];
const cardGeo = new THREE.PlaneGeometry(1.6, 1.6);
for (let i = 0; i < CARD_COUNT; i++) {
  const mat = new THREE.MeshBasicMaterial({
    map: makeTileTexture(i + 1),
    side: THREE.DoubleSide,
    transparent: true,
    // Dimmed on purpose: backdrop art, not content. The .scrim overlay and
    // the wider orbit below keep the reading column clear.
    opacity: 0.55,
  });
  const mesh = new THREE.Mesh(cardGeo, mat);
  const angle = (i / CARD_COUNT) * Math.PI * 2;
  const radius = 6.0 + (i % 3) * 1.2;
  mesh.position.set(
    Math.cos(angle) * radius,
    (i % 5) * 0.9 - 1.8,
    Math.sin(angle) * radius * 0.6 - 1.5,
  );
  mesh.rotation.set(
    (i % 4) * 0.12 - 0.18,
    angle * 0.5,
    ((i * 29) % 20) * 0.01 - 0.1,
  );
  mesh.userData = {
    baseY: mesh.position.y,
    speed: 0.25 + (i % 5) * 0.07,
    phase: i * 1.3,
    spin: (i % 2 === 0 ? 1 : -1) * (0.05 + (i % 3) * 0.02),
  };
  scene.add(mesh);
  cards.push(mesh);
}

// Particle field.
const starCount = 700;
const starPos = new Float32Array(starCount * 3);
for (let i = 0; i < starCount; i++) {
  starPos[i * 3] = (Math.random() - 0.5) * 30;
  starPos[i * 3 + 1] = (Math.random() - 0.5) * 18;
  starPos[i * 3 + 2] = -4 - Math.random() * 14;
}
const starGeo = new THREE.BufferGeometry();
starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
const stars = new THREE.Points(
  starGeo,
  new THREE.PointsMaterial({ color: 0x8ea2c8, size: 0.035, transparent: true, opacity: 0.5 }),
);
scene.add(stars);

// Slow backdrop gyroscope.
const gyro = new THREE.Mesh(
  new THREE.IcosahedronGeometry(6.5, 1),
  new THREE.MeshBasicMaterial({ color: 0x2a3a5f, wireframe: true, transparent: true, opacity: 0.2 }),
);
gyro.position.set(0, 0, -6);
scene.add(gyro);

// Mouse parallax.
const pointer = { x: 0, y: 0 };
window.addEventListener('pointermove', (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
});

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

// Fade the backdrop as the reader scrolls past the hero, so the long
// reference sections sit on a near-solid background.
function fadeOnScroll() {
  const f = Math.min(1, window.scrollY / (window.innerHeight * 0.85));
  canvas.style.opacity = String(1 - f * 0.85);
}
window.addEventListener('scroll', fadeOnScroll, { passive: true });
fadeOnScroll();

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const clock = new THREE.Clock();

function tick() {
  requestAnimationFrame(tick);
  if (document.hidden) return; // background tab: skip work, resume on focus
  const t = clock.getElapsedTime();
  if (!reduceMotion) {
    for (const card of cards) {
      const u = card.userData;
      card.position.y = u.baseY + Math.sin(t * u.speed + u.phase) * 0.35;
      card.rotation.y += u.spin * 0.016;
    }
    stars.rotation.y = t * 0.008;
    gyro.rotation.x = t * 0.05;
    gyro.rotation.y = t * 0.07;
  }
  camera.position.x += (pointer.x * 0.9 - camera.position.x) * 0.04;
  camera.position.y += (0.4 - pointer.y * 0.6 - camera.position.y) * 0.04;
  camera.lookAt(0, 0, -1);
  renderer.render(scene, camera);
}
tick();
} // end WebGL scene (skipped entirely when WebGL is unavailable)

// Copy install commands (kept in JS so the page needs no inline handlers).
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function flash(btn, ok) {
  const original = btn.dataset.label || btn.textContent;
  btn.dataset.label = original;
  btn.textContent = ok ? 'Copied' : 'Select & copy';
  window.setTimeout(() => {
    btn.textContent = original;
  }, 1600);
}

// Hero tabs: Claude Code vs Other agents.
const tabBtns = document.querySelectorAll('[data-install-tab]');
const claudeCmd = document.getElementById('install-cmd');
const otherCmd = document.getElementById('install-cmd-other');
const hintClaude = document.getElementById('install-hint-claude');
const hintOther = document.getElementById('install-hint-other');

function showTab(name) {
  const isClaude = name !== 'other';
  if (claudeCmd) claudeCmd.hidden = !isClaude;
  if (otherCmd) otherCmd.hidden = isClaude;
  if (hintClaude) hintClaude.hidden = !isClaude;
  if (hintOther) hintOther.hidden = isClaude;
  for (const btn of tabBtns) {
    const active = btn.dataset.installTab === name;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  }
}

for (const btn of tabBtns) {
  btn.addEventListener('click', () => showTab(btn.dataset.installTab));
}

const copyBtn = document.getElementById('copy-btn');
if (copyBtn) {
  copyBtn.addEventListener('click', async () => {
    const visible = otherCmd && !otherCmd.hidden ? otherCmd : claudeCmd;
    const text = visible ? visible.innerText : '';
    flash(copyBtn, await copyText(text));
  });
}

// Per-snippet copy buttons in the Other agents section.
for (const btn of document.querySelectorAll('[data-copy-target]')) {
  btn.addEventListener('click', async () => {
    const target = document.getElementById(btn.dataset.copyTarget);
    const text = target ? target.innerText : '';
    flash(btn, await copyText(text));
  });
}
