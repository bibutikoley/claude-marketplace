import * as THREE from 'three';

// Floating "note cards" hero for the marketplace landing page.
// Everything is procedural: canvas-painted note textures, a particle field,
// and a slow wireframe icosahedron for depth. No network calls, no assets.

const canvas = document.getElementById('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x0b0e14, 0.055);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
camera.position.set(0, 0.4, 9);

function makeNoteTexture(seed) {
  const w = 256;
  const h = 340;
  const el = document.createElement('canvas');
  el.width = w;
  el.height = h;
  const ctx = el.getContext('2d');
  // Paper.
  ctx.fillStyle = '#fef9c3';
  ctx.fillRect(0, 0, w, h);
  // Red margin line.
  ctx.fillStyle = 'rgba(220, 80, 80, 0.55)';
  ctx.fillRect(34, 0, 2, h);
  // Title bar.
  ctx.fillStyle = '#3a3a2a';
  ctx.fillRect(48, 26, 150 + ((seed * 37) % 40), 16);
  // Ruled lines.
  ctx.fillStyle = 'rgba(90, 110, 160, 0.5)';
  for (let y = 66; y < h - 20; y += 26) {
    const len = w - 60 - ((seed * (y + 13)) % 70);
    ctx.fillRect(48, y, len, 3);
  }
  const tex = new THREE.CanvasTexture(el);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

const CARD_COUNT = 14;
const cards = [];
const cardGeo = new THREE.PlaneGeometry(1.5, 2.0);
for (let i = 0; i < CARD_COUNT; i++) {
  const mat = new THREE.MeshBasicMaterial({
    map: makeNoteTexture(i + 1),
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.92,
  });
  const mesh = new THREE.Mesh(cardGeo, mat);
  const angle = (i / CARD_COUNT) * Math.PI * 2;
  const radius = 4.2 + (i % 3) * 1.1;
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
  new THREE.PointsMaterial({ color: 0x8ea2c8, size: 0.035, transparent: true, opacity: 0.8 }),
);
scene.add(stars);

// Slow backdrop gyroscope.
const gyro = new THREE.Mesh(
  new THREE.IcosahedronGeometry(6.5, 1),
  new THREE.MeshBasicMaterial({ color: 0x2a3a5f, wireframe: true, transparent: true, opacity: 0.35 }),
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

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const clock = new THREE.Clock();

function tick() {
  requestAnimationFrame(tick);
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
