import * as THREE from "three";
import { keeperKits } from "../model/kits";
import type { Match } from "../model/match";
import type { Trail } from "../model/trails";
import type { Pose } from "./cameras";
import { blobTexture, boardTexture, crowdTexture, discTexture, netTexture, pitchTexture, ringTexture } from "./textures";

const L = 105;
const W = 68;

/** Pitch frame (x along, y across from the near touchline, z up) to three.js world. */
export function world(x: number, y: number, z: number, out = new THREE.Vector3()): THREE.Vector3 {
  return out.set(x - L / 2, z, W / 2 - y);
}

/** Lens-specific 3D graphics. The lens sweep renders two of these side by side. */
export interface LensGraphics {
  highlight: { playerId: string; color: string } | null;
  trail: { slotId: string; playerId: string } | null;
  clubGlow: { teamId: string; color: string } | null;
  ballTrail: { slotId: string } | null;
}

export const NO_GRAPHICS: LensGraphics = { highlight: null, trail: null, clubGlow: null, ballTrail: null };

interface PlayerMesh {
  group: THREE.Group;
  disc: THREE.Mesh;
  glow: THREE.Mesh;
  teamId: string;
}

const TRAIL_VERT = /* glsl */ `
  attribute float aT;
  attribute float aSide;
  varying float vT;
  varying float vSide;
  void main() {
    vT = aT;
    vSide = aSide;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const TRAIL_FRAG = /* glsl */ `
  uniform float uHead;
  uniform float uFade;
  uniform vec3 uColor;
  uniform float uOpacity;
  varying float vT;
  varying float vSide;
  void main() {
    if (vT > uHead) discard;
    float age = uHead - vT;
    float recent = clamp(1.0 - age / uFade, 0.0, 1.0);
    float a = 0.16 + 0.7 * recent * recent;
    float edge = 1.0 - smoothstep(0.55, 1.0, abs(vSide));
    gl_FragColor = vec4(uColor, a * edge * uOpacity);
  }
`;

function ribbon(points: Float32Array, width: number, height: number, sampleZ?: Float32Array): THREE.BufferGeometry {
  const n = points.length / 3;
  const pos = new Float32Array(n * 2 * 3);
  const aT = new Float32Array(n * 2);
  const aSide = new Float32Array(n * 2);
  const idx: number[] = [];
  const v = new THREE.Vector3();
  let nx = 0;
  let ny = 1;
  for (let i = 0; i < n; i++) {
    const x = points[i * 3]!;
    const y = points[i * 3 + 1]!;
    const a = Math.max(0, i - 1);
    const b = Math.min(n - 1, i + 1);
    const dx = points[b * 3]! - points[a * 3]!;
    const dy = points[b * 3 + 1]! - points[a * 3 + 1]!;
    const len = Math.hypot(dx, dy);
    // Keep the last good normal while the player stands still.
    if (len > 1e-3) {
      nx = -dy / len;
      ny = dx / len;
    }
    const z = height + (sampleZ ? sampleZ[i]! : 0);
    for (const side of [-1, 1]) {
      const k = i * 2 + (side < 0 ? 0 : 1);
      world(x + (nx * width * side) / 2, y + (ny * width * side) / 2, z, v);
      pos.set([v.x, v.y, v.z], k * 3);
      aT[k] = points[i * 3 + 2]!;
      aSide[k] = side;
    }
    if (i < n - 1) {
      const k = i * 2;
      idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aT", new THREE.BufferAttribute(aT, 1));
  g.setAttribute("aSide", new THREE.BufferAttribute(aSide, 1));
  g.setIndex(idx);
  return g;
}

export class Stage {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(26, 16 / 9, 0.5, 600);
  private players = new Map<string, PlayerMesh>();
  private ball: THREE.Mesh;
  private ballShadow: THREE.Mesh;
  private highlight: THREE.Mesh;
  private playerTrails = new Map<string, THREE.Mesh>(); // key slotId|playerId
  private ballTrails = new Map<string, THREE.Mesh>();
  private playerTrailMat: THREE.ShaderMaterial;
  private ballTrailMat: THREE.ShaderMaterial;
  private width = 1;
  private height = 1;
  private pose: Pose | null = null;
  private tmp = new THREE.Vector3();
  private tmpPos: [number, number] = [0, 0];
  private tmpBall: [number, number, number] = [0, 0, 0];
  private clock = 0;

  constructor(
    canvas: HTMLCanvasElement,
    private match: Match,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    const bg = new THREE.Color("#0a0e14");
    this.scene.background = bg;
    this.scene.fog = new THREE.Fog(bg, 140, 260);

    this.scene.add(new THREE.HemisphereLight("#dfeaff", "#1b2a1c", 1.6));
    const sun = new THREE.DirectionalLight("#ffffff", 1.6);
    sun.position.set(-30, 80, 40);
    this.scene.add(sun);

    this.buildGround();
    this.buildGoals();
    this.buildStands();

    const blob = blobTexture();
    const shadowGeo = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
    const shadowMat = new THREE.MeshBasicMaterial({ map: blob, transparent: true, depthWrite: false });
    const ring = ringTexture();
    const glowGeo = new THREE.PlaneGeometry(3.4, 3.4).rotateX(-Math.PI / 2);
    const discGeo = new THREE.CylinderGeometry(0.8, 0.8, 0.3, 40);

    // Keepers wear their own colours, as on a real pitch, so they stand out from both teams.
    const keepers = keeperKits(match.home, match.away);
    for (const p of match.players.values()) {
      const col = p.position === "GK" ? keepers[p.teamId === match.home.team_id ? 0 : 1] : p.club.colours;
      const side = new THREE.MeshStandardMaterial({ color: col.secondary, roughness: 0.6 });
      const top = new THREE.MeshStandardMaterial({
        map: discTexture(col.primary, col.secondary, col.text, p.shirt),
        roughness: 0.55,
      });
      const disc = new THREE.Mesh(discGeo, [side, top, side]);
      disc.position.y = 0.2;
      const shadow = new THREE.Mesh(shadowGeo, shadowMat);
      shadow.scale.setScalar(2.8);
      shadow.position.set(0.25, 0.02, 0.2);
      const glow = new THREE.Mesh(
        glowGeo,
        new THREE.MeshBasicMaterial({ map: ring, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }),
      );
      glow.position.y = 0.04;
      glow.visible = false;
      const group = new THREE.Group();
      group.add(shadow, glow, disc);
      group.visible = false;
      this.scene.add(group);
      this.players.set(p.player_id, { group, disc, glow, teamId: p.teamId });
    }

    this.ball = new THREE.Mesh(
      new THREE.SphereGeometry(0.34, 24, 16),
      new THREE.MeshStandardMaterial({ color: "#ffffff", emissive: "#ffffff", emissiveIntensity: 0.35, roughness: 0.4 }),
    );
    this.ballShadow = new THREE.Mesh(shadowGeo, shadowMat);
    this.ballShadow.scale.setScalar(1.3);
    this.scene.add(this.ball, this.ballShadow);

    this.highlight = new THREE.Mesh(
      new THREE.PlaneGeometry(4.6, 4.6).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: ring, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }),
    );
    this.highlight.renderOrder = 2;
    this.highlight.visible = false;
    this.scene.add(this.highlight);

    const trailMat = (color: string, fade: number) =>
      new THREE.ShaderMaterial({
        vertexShader: TRAIL_VERT,
        fragmentShader: TRAIL_FRAG,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        uniforms: {
          uHead: { value: 0 },
          uFade: { value: fade },
          uColor: { value: new THREE.Color(color) },
          uOpacity: { value: 1 },
        },
      });
    this.playerTrailMat = trailMat("#ffffff", 3.5);
    this.ballTrailMat = trailMat("#ffc94d", 6);
    this.buildTrails();
  }

  private buildGround() {
    const margin = 6;
    const tex = pitchTexture(margin, 26);
    const pitch = new THREE.Mesh(
      new THREE.PlaneGeometry(L + margin * 2, W + margin * 2).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }),
    );
    this.scene.add(pitch);
    const surround = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 300).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: "#1d4a26", roughness: 1 }),
    );
    surround.position.y = -0.02;
    this.scene.add(surround);
  }

  private buildGoals() {
    const post = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.3, emissive: "#ffffff", emissiveIntensity: 0.25 });
    const net = netTexture();
    for (const gx of [0, L]) {
      const s = gx === 0 ? -1 : 1; // net depth goes outward
      const g = new THREE.Group();
      const r = 0.07;
      const h = 2.44;
      const w = 7.32;
      const depth = 2.0;
      for (const py of [W / 2 - w / 2, W / 2 + w / 2]) {
        const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 10), post);
        m.position.copy(world(gx, py, h / 2));
        g.add(m);
      }
      const bar = new THREE.Mesh(new THREE.CylinderGeometry(r, r, w, 10), post);
      bar.rotation.x = Math.PI / 2;
      bar.position.copy(world(gx, W / 2, h));
      g.add(bar);
      const netMat = (rx: number, ry: number) => {
        const t = net.clone();
        t.repeat.set(rx, ry);
        t.needsUpdate = true;
        return new THREE.MeshBasicMaterial({ map: t, transparent: true, side: THREE.DoubleSide, depthWrite: false });
      };
      const back = new THREE.Mesh(new THREE.PlaneGeometry(w, h), netMat(w * 4, h * 4));
      back.rotation.y = Math.PI / 2;
      back.position.copy(world(gx + s * depth, W / 2, h / 2));
      const top = new THREE.Mesh(new THREE.PlaneGeometry(depth, w), netMat(depth * 4, w * 4));
      top.rotation.x = -Math.PI / 2;
      top.position.copy(world(gx + (s * depth) / 2, W / 2, h));
      g.add(back, top);
      for (const py of [W / 2 - w / 2, W / 2 + w / 2]) {
        const side = new THREE.Mesh(new THREE.PlaneGeometry(depth, h), netMat(depth * 4, h * 4));
        side.position.copy(world(gx + (s * depth) / 2, py, h / 2));
        g.add(side);
      }
      this.scene.add(g);
    }
  }

  private buildStands() {
    const boardTex = boardTexture();
    const boardMat = (len: number) => {
      const t = boardTex.clone();
      t.repeat.set(len / ((boardTex.image as HTMLCanvasElement).width / 64) / 0.9, 1);
      t.needsUpdate = true;
      return new THREE.MeshBasicMaterial({ map: t });
    };
    const crowd = crowdTexture([this.match.home.colours.primary, this.match.away.colours.primary]);
    const crowdMat = (len: number) => {
      const t = crowd.clone();
      t.repeat.set(len / 60, 1);
      t.needsUpdate = true;
      return new THREE.MeshStandardMaterial({ map: t, roughness: 1 });
    };
    // Far side: boards then a raked stand.
    const farLen = L + 30;
    const board = new THREE.Mesh(new THREE.PlaneGeometry(farLen, 0.9), boardMat(farLen));
    board.position.copy(world(L / 2, W + 4.5, 0.45));
    this.scene.add(board);
    const rake = (len: number, depth: number, rise: number) => new THREE.PlaneGeometry(len, Math.hypot(depth, rise));
    const far = new THREE.Mesh(rake(farLen + 20, 30, 22), crowdMat(farLen + 20));
    far.rotation.x = -Math.atan2(30, 22); // tilt back from vertical, top away from the pitch
    far.position.copy(world(L / 2, W + 8 + 15, 1.5 + 11));
    this.scene.add(far);
    // Ends: boards and stands behind each goal.
    for (const gx of [0, L]) {
      const s = gx === 0 ? -1 : 1;
      const endLen = W + 24;
      const b = new THREE.Mesh(new THREE.PlaneGeometry(endLen, 0.9), boardMat(endLen));
      b.rotation.y = (s * -Math.PI) / 2;
      b.position.copy(world(gx + s * 4.5, W / 2, 0.45));
      this.scene.add(b);
      const stand = new THREE.Mesh(rake(endLen + 20, 26, 18), crowdMat(endLen + 20));
      stand.rotation.order = "YXZ";
      stand.rotation.y = (s * -Math.PI) / 2;
      stand.rotation.x = -Math.atan2(26, 18);
      stand.position.copy(world(gx + s * (8 + 13), W / 2, 1.5 + 9));
      this.scene.add(stand);
    }
    // Near side boards, seen from reverse angles.
    const near = new THREE.Mesh(new THREE.PlaneGeometry(farLen, 0.9), boardMat(farLen));
    near.rotation.y = Math.PI;
    near.position.copy(world(L / 2, -4.5, 0.45));
    this.scene.add(near);
  }

  /** Builds meshes for replay windows a live feed has added since the last call. */
  syncTrails() {
    this.buildTrails();
  }

  private buildTrails() {
    for (const [slotId, trails] of this.match.trails) {
      if (this.ballTrails.has(slotId)) continue;
      for (const [pid, trail] of trails) {
        const mesh = new THREE.Mesh(ribbon(trail.points, 0.55, 0.05), this.playerTrailMat);
        mesh.visible = false;
        mesh.renderOrder = 1;
        mesh.frustumCulled = false;
        this.scene.add(mesh);
        this.playerTrails.set(`${slotId}|${pid}`, mesh);
      }
      // Ball track on the ground, for the Pundit lens.
      const slot = this.match.slots.find((s) => s.id === slotId)!;
      const [w0, w1] = slot.window;
      const n = Math.max(2, Math.round((w1 - w0) / this.match.tracks.dt) + 1);
      const pts = new Float32Array(n * 3);
      const zs = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        const t = w0 + ((w1 - w0) * i) / (n - 1);
        this.match.tracks.ballAt(t, this.tmpBall);
        pts.set([this.tmpBall[0], this.tmpBall[1], t], i * 3);
        zs[i] = this.tmpBall[2];
      }
      const mesh = new THREE.Mesh(ribbon(pts, 0.7, 0.06, zs), this.ballTrailMat);
      mesh.visible = false;
      mesh.renderOrder = 1;
      mesh.frustumCulled = false;
      this.scene.add(mesh);
      this.ballTrails.set(slotId, mesh);
    }
  }

  trail(slotId: string, playerId: string): Trail | undefined {
    return this.match.trails.get(slotId)?.get(playerId);
  }

  resize(w: number, h: number) {
    this.width = Math.max(1, w);
    this.height = Math.max(1, h);
    this.renderer.setSize(this.width, this.height, false);
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
  }

  /** Puts players and ball where they are at match time `t`. */
  setFrame(t: number, wallTime: number) {
    this.clock = wallTime;
    const tracks = this.match.tracks;
    for (const [id, pm] of this.players) {
      const on = tracks.playerAt(id, t, this.tmpPos);
      pm.group.visible = on;
      if (on) world(this.tmpPos[0], this.tmpPos[1], 0, pm.group.position);
    }
    const b = tracks.ballAt(t, this.tmpBall);
    world(b[0], b[1], b[2] + 0.34, this.ball.position);
    world(b[0], b[1], 0.03, this.ballShadow.position);
    const lift = Math.min(1, b[2] / 6);
    this.ballShadow.scale.setScalar(1.3 + lift);
    (this.ballShadow.material as THREE.MeshBasicMaterial).opacity = 1 - lift * 0.6;
    this.playerTrailMat.uniforms.uHead!.value = t;
    this.ballTrailMat.uniforms.uHead!.value = t;
  }

  /** Moves the camera toward `pose`; `snap` cuts straight to it. */
  setPose(target: Pose, dt: number, snap: boolean) {
    if (!this.pose || snap) {
      this.pose = { pos: [...target.pos], look: [...target.look], fov: target.fov };
    } else {
      const k = 1 - Math.exp(-dt * 5);
      for (let i = 0; i < 3; i++) {
        this.pose.pos[i] = this.pose.pos[i]! + (target.pos[i]! - this.pose.pos[i]!) * k;
        this.pose.look[i] = this.pose.look[i]! + (target.look[i]! - this.pose.look[i]!) * k;
      }
      this.pose.fov += (target.fov - this.pose.fov) * k;
    }
    const p = this.pose;
    world(p.pos[0], p.pos[1], p.pos[2], this.camera.position);
    this.camera.lookAt(world(p.look[0], p.look[1], p.look[2], this.tmp));
    if (Math.abs(this.camera.fov - p.fov) > 1e-3) {
      this.camera.fov = p.fov;
      this.camera.updateProjectionMatrix();
    }
    // Turn the shirt numbers to face the camera, whatever the angle.
    const yaw = Math.atan2(this.camera.position.x - this.tmp.x, this.camera.position.z - this.tmp.z);
    // The cap's texture runs up along local +x, so a quarter turn puts its top away from the camera.
    for (const pm of this.players.values()) pm.disc.rotation.y = yaw + Math.PI / 2;
  }

  private applyLens(g: LensGraphics) {
    for (const m of this.playerTrails.values()) m.visible = false;
    for (const m of this.ballTrails.values()) m.visible = false;
    for (const pm of this.players.values()) pm.glow.visible = false;
    this.highlight.visible = false;

    if (g.trail) {
      const m = this.playerTrails.get(`${g.trail.slotId}|${g.trail.playerId}`);
      if (m) m.visible = true;
    }
    if (g.ballTrail) {
      const m = this.ballTrails.get(g.ballTrail.slotId);
      if (m) m.visible = true;
    }
    if (g.clubGlow) {
      for (const pm of this.players.values()) {
        if (pm.teamId !== g.clubGlow.teamId || !pm.group.visible) continue;
        pm.glow.visible = true;
        (pm.glow.material as THREE.MeshBasicMaterial).color.set(g.clubGlow.color);
      }
    }
    if (g.highlight) {
      const pm = this.players.get(g.highlight.playerId);
      if (pm?.group.visible) {
        this.highlight.visible = true;
        this.highlight.position.set(pm.group.position.x, 0.06, pm.group.position.z);
        const pulse = 1 + 0.08 * Math.sin(this.clock * 5);
        this.highlight.scale.setScalar(pulse);
        (this.highlight.material as THREE.MeshBasicMaterial).color.set(g.highlight.color);
      }
    }
  }

  /**
   * Draws the frame. With `sweep`, the screen is split at `sweep.at` (0 to 1 from the
   * left): the new lens's graphics to the left of the bar, the old lens's to the right.
   */
  render(graphics: LensGraphics, sweep?: { at: number; previous: LensGraphics }) {
    const r = this.renderer;
    if (!sweep) {
      r.setScissorTest(false);
      this.applyLens(graphics);
      r.render(this.scene, this.camera);
      return;
    }
    const split = Math.round(this.width * sweep.at);
    r.setScissorTest(true);
    if (split > 0) {
      r.setScissor(0, 0, split, this.height);
      this.applyLens(graphics);
      r.render(this.scene, this.camera);
    }
    if (split < this.width) {
      r.setScissor(split, 0, this.width - split, this.height);
      this.applyLens(sweep.previous);
      r.render(this.scene, this.camera);
    }
    r.setScissorTest(false);
  }

  /** Screen position (CSS pixels) of a pitch-frame point, or null if behind the camera. */
  project(x: number, y: number, z: number): { x: number; y: number } | null {
    const v = world(x, y, z, this.tmp).project(this.camera);
    if (v.z > 1 || v.z < -1) return null;
    return { x: ((v.x + 1) / 2) * this.width, y: ((1 - v.y) / 2) * this.height };
  }

  /** Screen position of a player's head, or null if off the pitch or off screen. */
  projectPlayer(id: string, z = 2.2) {
    const pm = this.players.get(id);
    if (!pm?.group.visible) return null;
    const p = pm.group.position;
    const v = this.tmp.set(p.x, z, p.z).project(this.camera);
    if (v.z > 1 || v.z < -1) return null;
    return { x: ((v.x + 1) / 2) * this.width, y: ((1 - v.y) / 2) * this.height };
  }

  dispose() {
    this.renderer.dispose();
  }
}
