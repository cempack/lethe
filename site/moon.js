// The Lethe moon over still water, live: the same model as lethe/moon.py in the app.
//
// Nothing here is an image. A sphere is ray-cast on a coarse grid of cells and lit from the
// upper left; each cell takes one of a handful of inks, and the shades between them are made
// by ordered dithering. The surface (seas and highlands) turns slowly about a tilted axis, and
// the water mirrors it in rows that drift and thin out with depth. Drag the moon to turn it.
//
// The sky, the glow and the light never change, so they are worked out once per size. A frame
// only looks up which part of the surface faces each cell, slides the rows of the reflection,
// and lets a few stars flicker.
(() => {
  const canvas = document.querySelector(".sky");
  const hero = document.querySelector(".hero");
  if (!canvas || !hero) return;
  const ctx = canvas.getContext("2d");

  const TAU = Math.PI * 2, TW = 512, TH = 128, TILT = 0.36, IDLE = 0.11;
  const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);
  const SEA = [[30, 34, 45], [64, 72, 94], [126, 137, 166]];
  const LAND = [[52, 58, 76], [108, 118, 146], [198, 207, 227]];
  const BRIGHT = [[108, 118, 146], [198, 207, 227], [242, 245, 251]];
  const DUSK = [[30, 34, 45], [52, 58, 76], [64, 72, 94]];
  const NIGHT = [[13, 14, 17], [17, 18, 23], [20, 22, 28], [25, 27, 34]];
  const AIR = [104, 118, 152];
  const GLINT = [[198, 207, 227], [126, 137, 166], [72, 80, 104]];
  const WATER = [[34, 39, 52], [70, 79, 102], [132, 143, 172]];
  const SKY = [[7, 8, 11], [10, 11, 15], [14, 16, 22], [20, 23, 31], [29, 33, 45]];
  const DEEP = [[7, 8, 11], [9, 10, 14], [12, 14, 19], [17, 19, 26]];
  const STARS = [[70, 79, 102], [126, 137, 166], [198, 207, 227]];
  // INKS[q][ground]: q 0..2 in the light, 3 the terminator, 4 and 5 the dark side.
  const INKS = [0, 1, 2].map((q) => [SEA[q], LAND[q], BRIGHT[q]]);
  INKS.push(DUSK, [NIGHT[0], NIGHT[2], NIGHT[2]], [NIGHT[1], NIGHT[3], NIGHT[3]]);

  const random = (seed) => () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  // The ground as a map (0 sea, 1 land, 2 bright): smooth noise on the sphere itself, so the
  // map has no seam and no pinching at the poles.
  const surface = (() => {
    const n = 16, rnd = random(7), lattice = Float32Array.from({ length: n * n * n }, rnd);
    const noise = (x, y, z) => {
      const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
      let fx = x - xi, fy = y - yi, fz = z - zi;
      fx *= fx * (3 - 2 * fx); fy *= fy * (3 - 2 * fy); fz *= fz * (3 - 2 * fz);
      const x0 = ((xi % n) + n) % n, y0 = ((yi % n) + n) % n, z0 = ((zi % n) + n) % n;
      const x1 = (x0 + 1) % n, y1 = (y0 + 1) % n, z1 = (z0 + 1) % n;
      const at = (a, b, c) => lattice[(c * n + b) * n + a];
      const a = at(x0, y0, z0) * (1 - fx) + at(x1, y0, z0) * fx, b = at(x0, y1, z0) * (1 - fx) + at(x1, y1, z0) * fx;
      const c = at(x0, y0, z1) * (1 - fx) + at(x1, y0, z1) * fx, d = at(x0, y1, z1) * (1 - fx) + at(x1, y1, z1) * fx;
      return (a * (1 - fy) + b * fy) * (1 - fz) + (c * (1 - fy) + d * fy) * fz;
    };
    const out = new Uint8Array(TW * TH);
    for (let row = 0; row < TH; row++) {
      const lat = (0.5 - (row + 0.5) / TH) * Math.PI, cl = Math.cos(lat), y = Math.sin(lat);
      for (let col = 0; col < TW; col++) {
        const lon = (col / TW) * TAU, x = cl * Math.cos(lon), z = cl * Math.sin(lon);
        const v = 0.62 * noise(x * 1.7 + 3, y * 1.7 + 5, z * 1.7 + 7) + 0.38 * noise(x * 4.3 + 11, y * 4.3 + 13, z * 4.3 + 17);
        const fine = noise(x * 13 + 23, y * 13 + 29, z * 13 + 31);
        out[row * TW + col] = v < 0.47 ? 0 : fine > 0.84 && v > 0.58 ? 2 : 1;
      }
    }
    return out;
  })();

  const still = matchMedia("(prefers-reduced-motion: reduce)");
  let scene = null, lon = 0.6, omega = IDLE, time = 0, last = 0, visible = true, held = null;

  function build() {
    const cell = hero.clientWidth < 720 ? 3 : 4;
    const W = Math.ceil(hero.clientWidth / cell), H = Math.ceil(hero.clientHeight / cell);
    if (W < 40 || H < 40) return;
    const cx = W / 2, hy = Math.round(H * 0.79);
    const R = Math.max(24, Math.min(H * 0.2, W * 0.27, 58));
    const len = Math.hypot(-0.66, 0.56, 0.4), lx = -0.66 / len, ly = 0.56 / len, lz = 0.4 / len;
    const cp = Math.cos(TILT), sp = Math.sin(TILT);
    const bg = new Uint8ClampedArray(W * H * 4);
    const put = (i, j, c) => { const k = (j * W + i) * 4; bg[k] = c[0]; bg[k + 1] = c[1]; bg[k + 2] = c[2]; bg[k + 3] = 255; };
    const dither = (inks, level, th) => {
      level = Math.max(0, Math.min(inks.length - 1, level));
      const q = Math.floor(level);
      return inks[Math.min(inks.length - 1, q + (level - q > th ? 1 : 0))];
    };
    // Sky and water: dark, with a glow around the moon and along the horizon.
    for (let j = 0; j < H; j++) {
      for (let i = 0; i < W; i++) {
        const th = BAYER[(j & 3) * 4 + (i & 3)], dx = (i + 0.5 - cx) / R, dy = (hy - j - 0.5) / R;
        if (j < hy) {
          const r = Math.hypot(dx, dy);
          put(i, j, dither(SKY, 2.9 * Math.exp(-Math.max(0, r - 1) * 0.95) + 1.5 * Math.exp(-dy * 0.42) * Math.exp(-Math.abs(dx) * 0.1) - 0.15, th));
        } else {
          const r = Math.hypot(dx, dy * 2.4);
          put(i, j, dither(DEEP, 2.1 * Math.exp(-Math.max(0, r - 0.6) * 0.75) + 0.9 * Math.exp(dy * 0.5) * Math.exp(-Math.abs(dx) * 0.12) - 0.1, th));
        }
      }
    }
    const rnd = random(11), stars = [];
    for (let n = Math.floor((W * hy) / 420); n > 0; n--) {
      const i = Math.floor(rnd() * W), j = Math.floor(rnd() * Math.max(1, hy - 12));
      if (Math.hypot((i - cx) / R, (hy - j) / R) < 1.9) continue;
      const weight = rnd() * rnd(), ink = STARS[weight > 0.55 ? 2 : weight > 0.22 ? 1 : 0];
      const k = (j * W + i) * 4;
      if (rnd() < 0.3) stars.push({ k, ink, under: [bg[k], bg[k + 1], bg[k + 2]], speed: 0.6 + rnd() * 1.8, phase: rnd() * TAU });
      put(i, j, ink);
    }
    // The moon: which map cell each grid cell looks at, and how the light falls on it.
    const cells = [], level = new Map();
    for (let j = Math.max(0, Math.floor(hy - R * 1.1)); j < hy; j++) {
      const y = (hy - j - 0.5) / R;
      for (let i = Math.max(0, Math.floor(cx - R * 1.1)); i < Math.min(W, cx + R * 1.1 + 1); i++) {
        const x = (i + 0.5 - cx) / R, r2 = x * x + y * y, th = BAYER[(j & 3) * 4 + (i & 3)];
        if (r2 > 1) {
          const r = Math.sqrt(r2);
          if (r < 1.08) {                      // the thin ring of atmosphere
            const g = (1.08 - r) / 0.08;
            if (g * g * Math.max(0.15, ((x * lx + y * ly) / r) * 0.7 + 0.45) > th) {
              const k = (j * W + i) * 4, a = 0.5 * g;
              put(i, j, [bg[k] + (AIR[0] - bg[k]) * a, bg[k + 1] + (AIR[1] - bg[k + 1]) * a, bg[k + 2] + (AIR[2] - bg[k + 2]) * a]);
            }
          }
          continue;
        }
        const z = Math.sqrt(1 - r2), yw = y * cp + z * sp, zw = -y * sp + z * cp;
        const row = Math.min(TH - 1, Math.floor((0.5 - Math.asin(Math.max(-1, Math.min(1, yw))) / Math.PI) * TH));
        const col = Math.floor((((Math.atan2(x, zw) / TAU) % 1) + 1) % 1 * TW);
        const lam = x * lx + y * ly + z * lz;
        let q;
        if (lam > 0) {
          const s = Math.max(0, Math.min(1, lam * 1.3) * 2 - (r2 > 0.88 ? 0.7 : 0));
          q = Math.min(2, Math.floor(s) + (s - Math.floor(s) > th ? 1 : 0));
          level.set(j * W + i, q);
        } else if (lam > -0.12 && (lam + 0.12) / 0.12 > th) q = 3;
        else q = 4 + (th > 0.55 ? 1 : 0);
        cells.push((j * W + i) * 4, row * TW, col, q);
      }
    }
    // The horizon: a line of light from edge to edge, brightest under the moon.
    for (let i = 0; i < W; i++) {
      const d = Math.abs(i + 0.5 - cx) / (W * 0.5);
      if (1 - Math.pow(d, 1.5) > BAYER[(hy & 3) * 4 + (i & 3)] * 0.98) put(i, hy, d < 0.5 ? GLINT[d < 0.1 ? 0 : d < 0.24 ? 1 : 2] : SKY[4]);
    }
    // Glints on the water, thinning out with distance.
    for (let n = W * 3; n > 0; n--) {
      const gauss = () => Math.sqrt(-2 * Math.log(1 - rnd())) * Math.cos(TAU * rnd());
      const d = 2 + Math.floor(Math.abs(gauss()) * R * 0.75), i = Math.floor(cx + gauss() * R * (1.6 + d * 0.05)), j = hy + d;
      if (j >= H || i < 0 || i >= W - 3 || rnd() > Math.exp(-d / (R * 0.9))) continue;
      for (let m = 1 + Math.floor(rnd() * 3); m > 0; m--) put(i + m - 1, j, WATER[d > R * 0.5 ? 0 : Math.floor(rnd() * 2)]);
    }
    // The reflection: each row of water mirrors a row of the moon, squeezed, thinner with depth.
    const rows = [], depth = Math.floor(R * 0.74), x0 = Math.max(0, Math.floor(cx - R - 8)), x1 = Math.min(W, Math.ceil(cx + R + 8));
    for (let d = 1; d <= depth && hy + d < H; d++) {
      const j = hy + d, src = hy - 1 - Math.floor((d - 1) / 0.74), fade = Math.pow(1 - d / (depth + 1), 1.25);
      const line = new Int8Array(W).fill(-1);
      for (let i = x0; i < x1; i++) {
        const q = level.get(src * W + i);
        if (q !== undefined && fade * (0.55 + 0.2 * q) > BAYER[(j & 3) * 4 + (i & 3)]) line[i] = q;
      }
      rows.push({ j, d, line });
    }
    canvas.width = W;
    canvas.height = H;
    canvas.style.width = `${W * cell}px`;
    canvas.style.height = `${H * cell}px`;
    const image = ctx.createImageData(W, H);
    image.data.set(bg);
    scene = { W, H, cell, cx, hy, R, bg, image, cells: Int32Array.from(cells), rows, stars, x0, x1 };
    draw();
  }

  function draw() {
    const { W, bg, image, cells, rows, stars, x0, x1 } = scene, d = image.data;
    const shift = ((Math.floor((lon / TAU) * TW) % TW) + TW) % TW;
    for (let n = 0; n < cells.length; n += 4) {
      const k = cells[n], c = INKS[cells[n + 3]][surface[cells[n + 1] + ((cells[n + 2] + shift) % TW)]];
      d[k] = c[0]; d[k + 1] = c[1]; d[k + 2] = c[2];
    }
    const flow = Math.floor(time * 2.6);
    for (const { j, d: depth, line } of rows) {
      const gap = (depth + flow) % (depth < 9 ? 3 : depth < 16 ? 4 : 5) === 0;
      const slide = Math.round(Math.sin(time * 1.25 + depth * 0.85) * (0.5 + depth * 0.085));
      for (let i = x0; i < x1; i++) {
        const k = (j * W + i) * 4, src = i - slide, q = gap || src < 0 || src >= W ? -1 : line[src];
        if (q < 0) { d[k] = bg[k]; d[k + 1] = bg[k + 1]; d[k + 2] = bg[k + 2]; }
        else { const c = WATER[q]; d[k] = c[0]; d[k + 1] = c[1]; d[k + 2] = c[2]; }
      }
    }
    for (const s of stars) {
      const c = Math.sin(time * s.speed + s.phase) > -0.55 ? s.ink : s.under;
      d[s.k] = c[0]; d[s.k + 1] = c[1]; d[s.k + 2] = c[2];
    }
    ctx.putImageData(image, 0, 0);
  }

  function tick(now) {
    requestAnimationFrame(tick);
    if (!scene || !visible || now - last < 1000 / 30) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (still.matches && !held) return;
    time += dt;
    if (!held) {
      omega += (IDLE - omega) * Math.min(1, dt * 1.6);
      lon += omega * dt;
    }
    draw();
  }

  // Drag the moon to turn it; let go and it settles back to its own pace.
  const onMoon = (event) => {
    if (!scene) return false;
    const box = canvas.getBoundingClientRect();
    const x = (event.clientX - box.left) / scene.cell, y = (event.clientY - box.top) / scene.cell;
    return y < scene.hy + 2 && Math.hypot(x - scene.cx, y - scene.hy) < scene.R * 1.1;
  };
  hero.addEventListener("pointerdown", (event) => {
    if (event.target.closest("a, button, .command") || !onMoon(event)) return;
    held = { x: event.clientX, lon, at: performance.now() };
    hero.setPointerCapture(event.pointerId);
    hero.classList.add("turning");
  });
  hero.addEventListener("pointermove", (event) => {
    if (!held) return hero.classList.toggle("on-moon", onMoon(event));
    const next = held.lon - (event.clientX - held.x) * 0.011, now = performance.now();
    omega = Math.max(-5, Math.min(5, ((next - lon) / Math.max(8, now - held.at)) * 1000));
    lon = next;
    held.at = now;
    if (still.matches) draw();
  });
  const release = () => { held = null; hero.classList.remove("turning"); };
  hero.addEventListener("pointerup", release);
  hero.addEventListener("pointercancel", release);

  new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }).observe(hero);
  let pending;
  addEventListener("resize", () => { clearTimeout(pending); pending = setTimeout(build, 120); });
  build();
  requestAnimationFrame(tick);
})();
