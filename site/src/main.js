import * as THREE from 'three';

// ---------------------------------------------------------------------------
// Preferences
// ---------------------------------------------------------------------------
const reduceMotion = window.matchMedia(
  '(prefers-reduced-motion: reduce)',
).matches;

// ---------------------------------------------------------------------------
// WebGL backdrop — a slow-drifting field of glowing points ("digital ocean").
// Procedural, additive, and deliberately dim: backdrop art, not content.
// Everything degrades gracefully: no WebGL → plain CSS aurora remains.
// ---------------------------------------------------------------------------
const canvas = document.getElementById('scene');
let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: 'low-power',
  });
} catch {
  renderer = null; // old browser / disabled GPU
}

if (!renderer) {
  canvas.remove();
} else {
  try {
    initBackdrop(renderer);
  } catch {
    canvas.remove();
  }
}

function initBackdrop(gl) {
  gl.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  gl.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 80);
  camera.position.set(0, 0.7, 9);
  camera.lookAt(0, 0, 0);

  // Point grid, slightly jittered so the lattice feels organic.
  const COLS = 140;
  const ROWS = 76;
  const count = COLS * ROWS;
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  let i = 0;
  for (let x = 0; x < COLS; x++) {
    for (let y = 0; y < ROWS; y++) {
      positions[i * 3] = (x / (COLS - 1) - 0.5) * 36 + (Math.random() - 0.5) * 0.09;
      positions[i * 3 + 1] = (y / (ROWS - 1) - 0.5) * 21 + (Math.random() - 0.5) * 0.09;
      positions[i * 3 + 2] = 0;
      seeds[i] = Math.random() * Math.PI * 2;
      i++;
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));

  const uniforms = {
    uTime: { value: 0 },
    uPixelRatio: { value: gl.getPixelRatio() },
    uPointer: { value: new THREE.Vector2(0, 0) },
    uColorA: { value: new THREE.Color('#ffcf3f') },
    uColorB: { value: new THREE.Color('#5ec8ff') },
  };

  const material = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      attribute float aSeed;
      uniform float uTime;
      uniform float uPixelRatio;
      uniform vec2 uPointer;
      varying float vFade;
      varying float vMix;

      void main() {
        vec3 pos = position;
        float wave = sin(pos.x * 0.30 + uTime * 0.32 + aSeed)
                   * cos(pos.y * 0.40 + uTime * 0.22 + aSeed * 0.6);
        float swell = sin((pos.x + pos.y * 1.4) * 0.14 + uTime * 0.18);
        pos.z += wave * 1.15 + swell * 0.55;
        pos.x += uPointer.x * 0.6;
        pos.y += uPointer.y * 0.4;

        vec4 mv = modelViewMatrix * vec4(pos, 1.0);
        float radial = length(pos.xy / vec2(17.5, 10.5));
        vFade = smoothstep(1.12, 0.12, radial) * (0.62 + 0.38 * (wave * 0.5 + 0.5));
        vMix = clamp(0.5 + wave * 0.42 + pos.x * 0.014, 0.0, 1.0);

        gl_PointSize = uPixelRatio * (1.0 + wave * 0.5) * (11.0 / max(4.0, -mv.z));
        gl_PointSize = max(gl_PointSize, 0.8);
        gl_Position = projectionMatrix * mv;
      }
    `,
    fragmentShader: /* glsl */ `
      precision mediump float;
      uniform vec3 uColorA;
      uniform vec3 uColorB;
      varying float vFade;
      varying float vMix;

      void main() {
        float d = length(gl_PointCoord - 0.5);
        float alpha = smoothstep(0.5, 0.08, d);
        vec3 color = mix(uColorA, uColorB, vMix);
        gl_FragColor = vec4(color, alpha * vFade * 0.68);
      }
    `,
  });

  const field = new THREE.Points(geometry, material);
  field.position.z = -1.5;
  scene.add(field);

  // Pointer parallax, heavily smoothed.
  const pointer = { x: 0, y: 0 };
  const target = { x: 0, y: 0 };
  window.addEventListener(
    'pointermove',
    (e) => {
      target.x = (e.clientX / window.innerWidth) * 2 - 1;
      target.y = (e.clientY / window.innerHeight) * 2 - 1;
    },
    { passive: true },
  );

  function resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    gl.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    gl.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    uniforms.uPixelRatio.value = gl.getPixelRatio();
  }
  window.addEventListener('resize', resize);
  resize();

  // Fade the artwork out as the reader scrolls into the reference sections.
  function fadeOnScroll() {
    const f = Math.min(1, window.scrollY / (window.innerHeight * 0.9));
    canvas.style.opacity = String(1 - f * 0.88);
  }
  window.addEventListener('scroll', fadeOnScroll, { passive: true });
  fadeOnScroll();

  function render() {
    camera.position.x = pointer.x * 0.6;
    camera.position.y = 0.7 - pointer.y * 0.35;
    camera.lookAt(0, 0, 0);
    gl.render(scene, camera);
  }

  if (reduceMotion) {
    render(); // one static frame; no loop, no parallax
    window.addEventListener('resize', render);
    return;
  }

  const clock = new THREE.Clock();
  function tick() {
    requestAnimationFrame(tick);
    if (document.hidden) return; // background tab: skip work, resume on focus
    uniforms.uTime.value = clock.getElapsedTime();
    pointer.x += (target.x - pointer.x) * 0.045;
    pointer.y += (target.y - pointer.y) * 0.045;
    uniforms.uPointer.value.set(pointer.x, pointer.y);
    render();
  }
  tick();
}

// ---------------------------------------------------------------------------
// Top navigation — solid backdrop once the page scrolls.
// ---------------------------------------------------------------------------
const topnav = document.querySelector('.topnav');
function onScroll() {
  if (topnav) topnav.classList.toggle('is-scrolled', window.scrollY > 8);
}
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();

// ---------------------------------------------------------------------------
// Scroll reveal — staggered, one-way, retired after it plays so hover
// transitions on the same elements stay snappy. No JS → nothing hidden.
// ---------------------------------------------------------------------------
const revealEls = Array.from(document.querySelectorAll('[data-reveal]'));
if ('IntersectionObserver' in window && !reduceMotion) {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const el = entry.target;
        el.classList.add('is-visible');
        observer.unobserve(el);

        const retire = () => {
          el.classList.remove('reveal-init', 'is-visible');
          el.style.removeProperty('--reveal-delay');
        };
        el.addEventListener('transitionend', retire, { once: true });
        window.setTimeout(retire, 1600);
      }
    },
    { rootMargin: '0px 0px -8% 0px', threshold: 0.05 },
  );

  for (const el of revealEls) {
    el.classList.add('reveal-init');
    const siblings = Array.from(el.parentElement?.children || []).filter(
      (child) => child.hasAttribute('data-reveal'),
    );
    const index = siblings.indexOf(el);
    if (index > 0) {
      el.style.setProperty(
        '--reveal-delay',
        `${Math.min(index, 5) * 70}ms`,
      );
    }
    observer.observe(el);
  }
}

// ---------------------------------------------------------------------------
// Card spotlight — pointer position piped into CSS variables.
// ---------------------------------------------------------------------------
for (const card of document.querySelectorAll('.card')) {
  card.addEventListener(
    'pointermove',
    (e) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${e.clientX - rect.left}px`);
      card.style.setProperty('--my', `${e.clientY - rect.top}px`);
    },
    { passive: true },
  );
}

// ---------------------------------------------------------------------------
// Syntax highlighting — tiny, dependency-free tokenizers. Copy buttons read
// textContent, so the markup is presentation only.
// ---------------------------------------------------------------------------
const escapeHtml = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function highlightJson(src) {
  const pattern =
    /("(?:[^"\\]|\\.)*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?)/g;
  let out = '';
  let last = 0;
  src.replace(pattern, (match, str, colon, bool, num, offset) => {
    out += escapeHtml(src.slice(last, offset));
    if (str) {
      out += colon
        ? `<span class="tok-key">${escapeHtml(str)}</span>${escapeHtml(colon)}`
        : `<span class="tok-str">${escapeHtml(str)}</span>`;
    } else if (bool) {
      out += `<span class="tok-bool">${escapeHtml(bool)}</span>`;
    } else if (num) {
      out += `<span class="tok-num">${escapeHtml(num)}</span>`;
    }
    last = offset + match.length;
    return match;
  });
  return out + escapeHtml(src.slice(last));
}

function highlightToml(src) {
  return src
    .split('\n')
    .map((line) => {
      if (/^\s*\[[^\]]+\]\s*$/.test(line)) {
        return `<span class="tok-sec">${escapeHtml(line)}</span>`;
      }
      const kv = line.match(/^(\s*)([A-Za-z0-9_.-]+)(\s*=\s*)(.*)$/);
      if (!kv) return escapeHtml(line);
      return (
        kv[1] +
        `<span class="tok-key">${escapeHtml(kv[2])}</span>` +
        kv[3] +
        highlightTomlValue(kv[4])
      );
    })
    .join('\n');
}

function highlightTomlValue(value) {
  const pattern = /("(?:[^"\\]|\\.)*")|\b(\d+(?:\.\d+)?)\b/g;
  let out = '';
  let last = 0;
  value.replace(pattern, (match, str, num, offset) => {
    out += escapeHtml(value.slice(last, offset));
    out += str
      ? `<span class="tok-str">${escapeHtml(str)}</span>`
      : `<span class="tok-num">${escapeHtml(num)}</span>`;
    last = offset + match.length;
    return match;
  });
  return out + escapeHtml(value.slice(last));
}

function highlightShell(src) {
  // Commands only count at the start of a line; flags and quoted strings
  // anywhere; `VAR=` assignments only at the start of a line.
  const token =
    /^(\s*)(\/plugin|git|uvx|claude|python3|npm|npx|cd)\b|("(?:[^"\\]|\\.)*")|(--[\w-]+)|^([A-Z_][A-Z0-9_]*(?==))/g;
  return src
    .split('\n')
    .map((line) => {
      if (/^\s*#/.test(line)) {
        return `<span class="tok-comment">${escapeHtml(line)}</span>`;
      }
      let out = '';
      let last = 0;
      line.replace(token, (match, ws, cmd, str, flag, varKey, offset) => {
        out += escapeHtml(line.slice(last, offset));
        if (cmd) {
          out += `${escapeHtml(ws)}<span class="tok-cmd">${escapeHtml(cmd)}</span>`;
        } else if (str) {
          out += `<span class="tok-str">${escapeHtml(str)}</span>`;
        } else if (flag) {
          out += `<span class="tok-flag">${escapeHtml(flag)}</span>`;
        } else if (varKey) {
          out += `<span class="tok-var">${escapeHtml(varKey)}</span>`;
        }
        last = offset + match.length;
        return match;
      });
      return out + escapeHtml(line.slice(last));
    })
    .join('\n');
}

for (const code of document.querySelectorAll('code[data-lang]')) {
  const src = code.textContent;
  let html = null;
  try {
    if (code.dataset.lang === 'json') html = highlightJson(src);
    else if (code.dataset.lang === 'toml') html = highlightToml(src);
    else if (code.dataset.lang === 'shell') html = highlightShell(src);
  } catch {
    html = null;
  }
  if (html !== null) code.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Copy buttons — hero, terminal, and per-snippet.
// ---------------------------------------------------------------------------
async function copyText(text) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy path
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

function readText(el) {
  return (el?.innerText || el?.textContent || '').trim();
}

function flash(btn, ok, okLabel = 'Copied') {
  const label = btn.querySelector('.copy-label') || btn;
  if (!btn.dataset.label) btn.dataset.label = label.textContent;
  label.textContent = ok ? okLabel : 'Select & copy';
  btn.classList.toggle('is-copied', ok);
  window.clearTimeout(btn._flashTimer);
  btn._flashTimer = window.setTimeout(() => {
    label.textContent = btn.dataset.label;
    btn.classList.remove('is-copied');
  }, 1700);
}

// Hero install tabs: Claude Code vs Other agents.
const tabBtns = document.querySelectorAll('[data-install-tab]');
const claudeCmd = document.getElementById('install-cmd');
const otherCmd = document.getElementById('install-cmd-other');
const claudePre = claudeCmd?.closest('pre');
const hintClaude = document.getElementById('install-hint-claude');
const hintOther = document.getElementById('install-hint-other');
const terminalTitle = document.getElementById('terminal-title');

function showTab(name) {
  const isClaude = name !== 'other';
  if (claudePre) claudePre.hidden = !isClaude;
  if (otherCmd) otherCmd.hidden = isClaude;
  if (hintClaude) hintClaude.hidden = !isClaude;
  if (hintOther) hintOther.hidden = isClaude;
  if (terminalTitle) {
    terminalTitle.textContent = isClaude
      ? 'claude code — install'
      : 'mcp config — other agents';
  }
  for (const btn of tabBtns) {
    const active = btn.dataset.installTab === name;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  }
}

for (const btn of tabBtns) {
  btn.addEventListener('click', () => showTab(btn.dataset.installTab));
}

function activeInstall() {
  return otherCmd && !otherCmd.hidden ? otherCmd : claudeCmd;
}

const copyBtn = document.getElementById('copy-btn');
if (copyBtn) {
  copyBtn.addEventListener('click', async () => {
    flash(copyBtn, await copyText(readText(activeInstall())));
  });
}

const heroCopy = document.getElementById('hero-copy');
if (heroCopy) {
  heroCopy.addEventListener('click', async () => {
    const ok = await copyText(readText(activeInstall()));
    flash(heroCopy, ok, 'Copied to clipboard');
  });
}

for (const btn of document.querySelectorAll('[data-copy-target]')) {
  btn.addEventListener('click', async () => {
    const target = document.getElementById(btn.dataset.copyTarget);
    flash(btn, await copyText(readText(target)));
  });
}
