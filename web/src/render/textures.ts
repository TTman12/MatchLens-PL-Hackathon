import * as THREE from "three";

/** Pitch markings and mowing stripes, drawn once on a canvas. */
export function pitchTexture(margin: number, pxPerM: number): THREE.CanvasTexture {
  const L = 105;
  const W = 68;
  const cw = Math.round((L + margin * 2) * pxPerM);
  const ch = Math.round((W + margin * 2) * pxPerM);
  const c = document.createElement("canvas");
  c.width = cw;
  c.height = ch;
  const g = c.getContext("2d")!;
  // Stripes run across the pitch, 12 bands per half like a real mow.
  const band = L / 18;
  for (let i = -2; i * band < L + margin * 2; i++) {
    g.fillStyle = i % 2 === 0 ? "#2f7a3a" : "#357f40";
    g.fillRect((margin + i * band) * pxPerM, 0, band * pxPerM + 1, ch);
  }
  // Subtle grain so the grass doesn't look flat under a moving camera.
  const img = g.getImageData(0, 0, cw, ch);
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < img.data.length; i += 4) {
    const n = (rnd() - 0.5) * 10;
    img.data[i] = img.data[i]! + n;
    img.data[i + 1] = img.data[i + 1]! + n;
    img.data[i + 2] = img.data[i + 2]! + n;
  }
  g.putImageData(img, 0, 0);

  // Pitch frame: x right, y up from the near touchline. Canvas y runs down, so flip.
  const X = (x: number) => (margin + x) * pxPerM;
  const Y = (y: number) => (margin + W - y) * pxPerM;
  const R = (r: number) => r * pxPerM;
  g.strokeStyle = "rgba(255,255,255,0.92)";
  g.fillStyle = "rgba(255,255,255,0.92)";
  g.lineWidth = Math.max(2, 0.12 * pxPerM);
  g.lineJoin = "round";
  const rect = (x: number, y: number, w: number, h: number) => g.strokeRect(X(x), Y(y + h), R(w), R(h));
  const dot = (x: number, y: number) => {
    g.beginPath();
    g.arc(X(x), Y(y), R(0.22), 0, Math.PI * 2);
    g.fill();
  };
  rect(0, 0, L, W);
  g.beginPath();
  g.moveTo(X(L / 2), Y(0));
  g.lineTo(X(L / 2), Y(W));
  g.stroke();
  g.beginPath();
  g.arc(X(L / 2), Y(W / 2), R(9.15), 0, Math.PI * 2);
  g.stroke();
  dot(L / 2, W / 2);
  for (const side of [0, 1] as const) {
    const gx = side === 0 ? 0 : L;
    const s = side === 0 ? 1 : -1;
    const box = (depth: number, width: number) => rect(side === 0 ? 0 : L - depth, W / 2 - width / 2, depth, width);
    box(16.5, 40.32);
    box(5.5, 18.32);
    dot(gx + s * 11, W / 2);
    // The D: the part of the 9.15 m circle round the spot outside the box.
    const a = Math.acos(5.5 / 9.15);
    g.beginPath();
    if (side === 0) g.arc(X(11), Y(W / 2), R(9.15), -a, a);
    else g.arc(X(L - 11), Y(W / 2), R(9.15), Math.PI - a, Math.PI + a);
    g.stroke();
    for (const cy of [0, W]) {
      g.beginPath();
      const start = side === 0 ? (cy === 0 ? -Math.PI / 2 : 0) : cy === 0 ? Math.PI : Math.PI / 2;
      g.arc(X(gx), Y(cy), R(1), start, start + Math.PI / 2);
      g.stroke();
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** Soft round shadow. */
export function blobTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, "rgba(0,0,0,0.55)");
  grad.addColorStop(0.6, "rgba(0,0,0,0.25)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

/** Glow ring for highlights. */
export function ringTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 20, 64, 64, 64);
  grad.addColorStop(0, "rgba(255,255,255,0)");
  grad.addColorStop(0.55, "rgba(255,255,255,0.0)");
  grad.addColorStop(0.72, "rgba(255,255,255,1)");
  grad.addColorStop(0.82, "rgba(255,255,255,0.5)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

/** Top face of a player disc: club colour with the shirt number. */
export function discTexture(primary: string, secondary: string, text: string, shirt: number): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  g.fillStyle = primary;
  g.beginPath();
  g.arc(64, 64, 64, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = secondary;
  g.lineWidth = 10;
  g.beginPath();
  g.arc(64, 64, 58, 0, Math.PI * 2);
  g.stroke();
  g.fillStyle = text;
  g.font = "700 64px 'Barlow Condensed', 'Arial Narrow', sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText(String(shirt), 64, 68);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

/** Advertising board strip: our own marks only. */
export function boardTexture(): THREE.CanvasTexture {
  const words = ["MATCHLENS", "THE FICTIONAL LEAGUE", "EVERY MOMENT EXPLAINED"];
  const font = "700 40px 'Barlow Condensed', 'Arial Narrow', sans-serif";
  const gap = 70;
  const probe = document.createElement("canvas").getContext("2d")!;
  probe.font = font;
  // One full cycle of words per tile, so the repeat never cuts a word.
  const width = Math.ceil(words.reduce((w, s) => w + probe.measureText(s).width + gap, 0));
  const c = document.createElement("canvas");
  c.width = width;
  c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "#0c1f2b";
  g.fillRect(0, 0, width, 64);
  g.font = font;
  g.textBaseline = "middle";
  let x = gap / 2;
  words.forEach((w, i) => {
    g.fillStyle = i === 0 ? "#33e1a1" : "#e8eef2";
    g.fillText(w, x, 34);
    x += g.measureText(w).width + gap;
  });
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  return tex;
}

/** Crowd: dense speckle in muted colours with both clubs' colours mixed in. */
export function crowdTexture(colours: string[]): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 256;
  const g = c.getContext("2d")!;
  g.fillStyle = "#11151c";
  g.fillRect(0, 0, 1024, 256);
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const palette = [...colours, ...colours, "#2a2f38", "#3a3f48", "#5a5048", "#1e2430", "#6b6f78"];
  for (let row = 0; row < 32; row++) {
    // A tier gap every 8 rows.
    if (row % 8 === 7) continue;
    for (let i = 0; i < 180; i++) {
      g.fillStyle = palette[Math.floor(rnd() * palette.length)]!;
      g.globalAlpha = 0.55 + rnd() * 0.45;
      g.fillRect(i * 5.7 + rnd() * 2, row * 8 + rnd() * 2, 3.2, 4.5);
    }
  }
  g.globalAlpha = 1;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  return tex;
}

/** Goal net mesh pattern. */
export function netTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.strokeStyle = "rgba(255,255,255,0.55)";
  g.lineWidth = 2;
  g.strokeRect(0, 0, 64, 64);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}
