import os
import time
import math
import logging
from typing import Optional, Dict, Any, Tuple
import numpy as np
from PIL import Image, ImageDraw

from nlc.storage.paths import RESAMPLE_NEAREST

logger = logging.getLogger(__name__)

# Fast Shading Table (LUT) Cache
_LUT_CACHE: Dict[int, list] = {}
_ALPHA_LUT = list(range(256))


def _get_shading_lut(shade: float) -> list:
    key = int(shade * 256)
    lut = _LUT_CACHE.get(key)
    if lut is None:
        rgb_lut = [int(i * shade) for i in range(256)]
        lut = rgb_lut * 3 + _ALPHA_LUT
        _LUT_CACHE[key] = lut
    return lut


_LIGHT_DIR = np.array([0.3, 0.8, -0.5], dtype=float)
_LIGHT_DIR /= np.linalg.norm(_LIGHT_DIR)


def _pad_edge_1px(img: Image.Image) -> Image.Image:
    w, h = img.size
    p = Image.new('RGBA', (w + 2, h + 2))
    p.paste(img, (1, 1))
    p.paste(img.crop((0, 0, w, 1)), (1, 0))
    p.paste(img.crop((0, h - 1, w, h)), (1, h + 1))
    p.paste(img.crop((0, 0, 1, h)), (0, 1))
    p.paste(img.crop((w - 1, 0, w, h)), (w + 1, 1))
    p.paste(img.crop((0, 0, 1, 1)), (0, 0))
    p.paste(img.crop((w - 1, 0, w, 1)), (w + 1, 0))
    p.paste(img.crop((0, h - 1, 1, h)), (0, h + 1))
    p.paste(img.crop((w - 1, h - 1, w, h)), (w + 1, h + 1))
    return p


_BOX_CORNERS_CACHE: Dict[Tuple[float, ...], np.ndarray] = {}


def _get_box_corners(size: Tuple[float, ...]) -> np.ndarray:
    corners = _BOX_CORNERS_CACHE.get(size)
    if corners is None:
        corners = _UNIT_CORNERS * np.array(size, dtype=float)
        _BOX_CORNERS_CACHE[size] = corners
    return corners


def _heal_pinhole_voids(canvas: Image.Image, max_iter: int = 6) -> Image.Image:
    bbox = canvas.getbbox()
    if not bbox:
        return canvas
    bx0, by0, bx1, by1 = bbox
    x0, y0 = max(0, bx0 - 1), max(0, by0 - 1)
    x1, y1 = min(canvas.width, bx1 + 1), min(canvas.height, by1 + 1)

    alpha_sub = np.array(canvas.crop((x0, y0, x1, y1)).getchannel('A'))
    is_solid = (alpha_sub > 128).view(np.uint8)
    h_shape, w_shape = is_solid.shape
    if h_shape < 3 or w_shape < 3:
        return canvas

    row_sum = is_solid[:, :-2] + is_solid[:, 1:-1] + is_solid[:, 2:]
    n = (row_sum[:-2, :] + row_sum[1:-1, :] + row_sum[2:, :]) - is_solid[1:-1, 1:-1]
    holes = (is_solid[1:-1, 1:-1] == 0) & (n >= 7)
    if not np.any(holes):
        return canvas

    py, px = np.nonzero(holes)
    py = py + 1
    px = px + 1
    is_solid[py, px] = 1

    all_filled = list(zip(py, px))
    newly_filled = list(all_filled)

    for _ in range(max_iter - 1):
        if not newly_filled:
            break
        candidates = set()
        for y, x in newly_filled:
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 1 <= ny < h_shape - 1 and 1 <= nx < w_shape - 1 and is_solid[ny, nx] == 0:
                        candidates.add((ny, nx))
        newly_filled = []
        for cy, cx in candidates:
            if np.count_nonzero(is_solid[cy - 1:cy + 2, cx - 1:cx + 2]) >= 7:
                is_solid[cy, cx] = 1
                newly_filled.append((cy, cx))
                all_filled.append((cy, cx))

    pix = canvas.load()
    for y, x in all_filled:
        cy, cx = y + y0, x + x0
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h_shape and 0 <= nx < w_shape and is_solid[ny, nx]:
                p_val = pix[cx + dx, cy + dy]
                if p_val[3] > 128:
                    pix[cx, cy] = p_val
                    break
    return canvas



_UNIT_CORNERS = np.array([
    [-0.5,  0.5, -0.5], [ 0.5,  0.5, -0.5],
    [ 0.5, -0.5, -0.5], [-0.5, -0.5, -0.5],
    [-0.5,  0.5,  0.5], [ 0.5,  0.5,  0.5],
    [ 0.5, -0.5,  0.5], [-0.5, -0.5,  0.5],
], dtype=float)

_FACE_DEFS = [
    ('front',  (0, 1, 2, 3)),
    ('back',   (5, 4, 7, 6)),
    ('top',    (4, 5, 1, 0)),
    ('bottom', (3, 2, 6, 7)),
    ('right',  (4, 0, 3, 7)),
    ('left',   (1, 5, 6, 2)),
]


class Model3DRenderer:
    def __init__(self, skin_path: str, cape_path: Optional[str] = None, model: str = "classic"):
        self.skin_path = os.path.abspath(skin_path) if skin_path else ""
        self.cape_path = os.path.abspath(cape_path) if cape_path else None
        self.model = "slim" if str(model).lower() == "slim" else "classic"

        self._skin_mtime = 0.0
        self._cape_mtime = 0.0
        self._last_stat_check = 0.0

        self.head_base: Dict[str, Image.Image] = {}
        self.head_overlay: Dict[str, Image.Image] = {}
        self.torso_base: Dict[str, Image.Image] = {}
        self.torso_overlay: Dict[str, Image.Image] = {}
        self.ra_base: Dict[str, Image.Image] = {}
        self.ra_overlay: Dict[str, Image.Image] = {}
        self.la_base: Dict[str, Image.Image] = {}
        self.la_overlay: Dict[str, Image.Image] = {}
        self.rl_base: Dict[str, Image.Image] = {}
        self.rl_overlay: Dict[str, Image.Image] = {}
        self.ll_base: Dict[str, Image.Image] = {}
        self.ll_overlay: Dict[str, Image.Image] = {}
        self.cape_tex: Optional[Dict[str, Image.Image]] = None

        self._opaque_textures: set = set()
        self._padded_cache: Dict[int, Image.Image] = {}
        self._shaded_cache: Dict[Tuple[int, int], Image.Image] = {}

        self.reload_textures()

    def _init_caches(self) -> None:
        self._opaque_textures = set()
        self._padded_cache = {}
        self._shaded_cache = {}
        all_tex_dicts = [
            self.head_base, self.head_overlay,
            self.torso_base, self.torso_overlay,
            self.ra_base, self.ra_overlay,
            self.la_base, self.la_overlay,
            self.rl_base, self.rl_overlay,
            self.ll_base, self.ll_overlay,
        ]
        if self.cape_tex:
            all_tex_dicts.append(self.cape_tex)
        for td in all_tex_dicts:
            for t in td.values():
                tid = id(t)
                try:
                    ext = t.getchannel('A').getextrema()
                    if ext[0] == 255:
                        self._opaque_textures.add(tid)
                except Exception:
                    pass
                padded = _pad_edge_1px(t)
                self._padded_cache[tid] = padded
                for s_level in range(25):
                    shade_val = s_level / 24.0
                    if shade_val < 0.98:
                        lut = _get_shading_lut(shade_val)
                        if hasattr(padded, '_new') and hasattr(padded, 'im'):
                            self._shaded_cache[(tid, s_level)] = padded._new(padded.im.point(lut, None))
                        else:
                            self._shaded_cache[(tid, s_level)] = padded.point(lut)
                    else:
                        self._shaded_cache[(tid, s_level)] = padded

    def reload_textures(self) -> bool:
        if not self.skin_path or not os.path.exists(self.skin_path):
            return False

        try:
            skin_raw = Image.open(self.skin_path).convert("RGBA")
            self._skin_mtime = os.path.getmtime(self.skin_path)

            if skin_raw.size == (64, 32):
                skin = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                skin.paste(skin_raw, (0, 0))
                skin.paste(skin_raw.crop((0, 16, 16, 32)), (16, 48))
                skin.paste(skin_raw.crop((40, 16, 56, 32)), (32, 48))
            elif skin_raw.size[0] != 64 or skin_raw.size[1] != 64:
                skin = skin_raw.resize((64, 64), RESAMPLE_NEAREST)
            else:
                skin = skin_raw

            def cp(b: Tuple[int, int, int, int]) -> Image.Image:
                return skin.crop(b)

            # Head (8x8x8)
            self.head_base = {
                'front': cp((8, 8, 16, 16)), 'back': cp((24, 8, 32, 16)),
                'right': cp((0, 8, 8, 16)), 'left': cp((16, 8, 24, 16)),
                'top': cp((8, 0, 16, 8)), 'bottom': cp((16, 0, 24, 8))
            }
            self.head_overlay = {
                'front': cp((40, 8, 48, 16)), 'back': cp((56, 8, 64, 16)),
                'right': cp((32, 8, 40, 16)), 'left': cp((48, 8, 56, 16)),
                'top': cp((40, 0, 48, 8)), 'bottom': cp((48, 0, 56, 8))
            }

            # Torso (8x12x4) - torso top permanently omitted under head
            self.torso_base = {
                'front': cp((20, 20, 28, 32)), 'back': cp((32, 20, 40, 32)),
                'right': cp((16, 20, 20, 32)), 'left': cp((28, 20, 32, 32)),
                'bottom': cp((28, 16, 36, 20))
            }
            self.torso_overlay = {
                'front': cp((20, 36, 28, 48)), 'back': cp((32, 36, 40, 48)),
                'right': cp((16, 36, 20, 48)), 'left': cp((28, 36, 32, 48)),
                'bottom': cp((28, 32, 36, 36))
            }

            # Arms
            aw = 3 if self.model == "slim" else 4
            self.ra_base = {
                'front': cp((44, 20, 44+aw, 32)), 'back': cp((48+aw, 20, 48+2*aw, 32)),
                'right': cp((40, 20, 44, 32)), 'left': cp((44+aw, 20, 48+aw, 32)),
                'top': cp((44, 16, 44+aw, 20)), 'bottom': cp((44+aw, 16, 44+2*aw, 20))
            }
            self.ra_overlay = {
                'front': cp((44, 36, 44+aw, 48)), 'back': cp((48+aw, 36, 48+2*aw, 48)),
                'right': cp((40, 36, 44, 48)), 'left': cp((44+aw, 36, 48+aw, 48)),
                'top': cp((44, 32, 44+aw, 36)), 'bottom': cp((44+aw, 32, 44+2*aw, 36))
            }

            self.la_base = {
                'front': cp((36, 52, 36+aw, 64)), 'back': cp((40+aw, 52, 40+2*aw, 64)),
                'right': cp((32, 52, 36, 64)), 'left': cp((36+aw, 52, 40+aw, 64)),
                'top': cp((36, 48, 36+aw, 52)), 'bottom': cp((36+aw, 48, 36+2*aw, 52))
            }
            self.la_overlay = {
                'front': cp((52, 52, 52+aw, 64)), 'back': cp((56+aw, 52, 56+2*aw, 64)),
                'right': cp((48, 52, 52, 64)), 'left': cp((52+aw, 52, 56+aw, 64)),
                'top': cp((52, 48, 52+aw, 52)), 'bottom': cp((52+aw, 48, 52+2*aw, 52))
            }

            # Legs (4x12x4)
            self.rl_base = {
                'front': cp((4, 20, 8, 32)), 'back': cp((12, 20, 16, 32)),
                'right': cp((0, 20, 4, 32)), 'left': cp((8, 20, 12, 32)),
                'top': cp((4, 16, 8, 20)), 'bottom': cp((8, 16, 12, 20))
            }
            self.rl_overlay = {
                'front': cp((4, 36, 8, 48)), 'back': cp((12, 36, 16, 48)),
                'right': cp((0, 36, 4, 48)), 'left': cp((8, 36, 12, 48)),
                'top': cp((4, 32, 8, 36)), 'bottom': cp((8, 32, 12, 36))
            }

            self.ll_base = {
                'front': cp((20, 52, 24, 64)), 'back': cp((28, 52, 32, 64)),
                'right': cp((16, 52, 20, 64)), 'left': cp((24, 52, 28, 64)),
                'top': cp((20, 48, 24, 52)), 'bottom': cp((24, 48, 28, 52))
            }
            self.ll_overlay = {
                'front': cp((4, 52, 8, 64)), 'back': cp((12, 52, 16, 64)),
                'right': cp((0, 52, 4, 64)), 'left': cp((8, 52, 12, 64)),
                'top': cp((4, 48, 8, 52)), 'bottom': cp((8, 48, 12, 52))
            }

            # Cape (10x16x1) - front flush against back omitted
            self.cape_tex = None
            if self.cape_path and os.path.exists(self.cape_path):
                c_img = Image.open(self.cape_path).convert("RGBA")
                self._cape_mtime = os.path.getmtime(self.cape_path)
                self.cape_tex = {
                    'back': c_img.crop((1, 1, 11, 17)),
                    'top': c_img.crop((1, 0, 11, 1)),
                    'bottom': c_img.crop((11, 0, 21, 1)),
                    'right': c_img.crop((0, 1, 1, 17)),
                    'left': c_img.crop((11, 1, 12, 17))
                }

            def _filter_visible_overlay(tex_dict: Dict[str, Image.Image]) -> Dict[str, Image.Image]:
                return {k: v for k, v in tex_dict.items() if v.getbbox() is not None}

            self.head_overlay = _filter_visible_overlay(self.head_overlay)
            self.torso_overlay = _filter_visible_overlay(self.torso_overlay)
            self.ra_overlay = _filter_visible_overlay(self.ra_overlay)
            self.la_overlay = _filter_visible_overlay(self.la_overlay)
            self.rl_overlay = _filter_visible_overlay(self.rl_overlay)
            self.ll_overlay = _filter_visible_overlay(self.ll_overlay)

            self._init_caches()
            return True
        except Exception as e:
            logger.error("Failed loading skin/cape textures: %s", e)
            return False

    def update_cape(self, cape_path: Optional[str]) -> None:
        new_cape = os.path.abspath(cape_path) if cape_path else None
        if new_cape != self.cape_path:
            self.cape_path = new_cape
            self.reload_textures()

    def update_model(self, model: str) -> None:
        new_model = "slim" if str(model).lower() == "slim" else "classic"
        if new_model != self.model:
            self.model = new_model
            self.reload_textures()

    def render_frame(
        self,
        yaw_deg: float = 30.0,
        pitch_deg: float = 10.0,
        walk_phase: float = 0.0,
        width: int = 360,
        height: int = 400,
        scale: Optional[float] = None,
        is_walking: Optional[bool] = None
    ) -> Optional[Image.Image]:
        now = time.monotonic()
        if now - self._last_stat_check > 1.0:
            self._last_stat_check = now
            if self.skin_path and os.path.exists(self.skin_path):
                try:
                    if os.path.getmtime(self.skin_path) > self._skin_mtime:
                        self.reload_textures()
                except OSError:
                    pass

        yaw = math.radians(yaw_deg)
        pitch = math.radians(pitch_deg)

        cy_rot, sy_rot = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)

        R_cam = np.array([
            [cy_rot, 0.0, -sy_rot],
            [sp * sy_rot, cp, sp * cy_rot],
            [cp * sy_rot, -sp, cp * cy_rot]
        ], dtype=float)

        moving = is_walking if is_walking is not None else (walk_phase != 0.0)

        max_limb = math.radians(26)
        leg_angle = (max_limb * math.sin(walk_phase)) if moving else 0.0
        arm_angle = -leg_angle * 0.9

        sin_p = math.sin(walk_phase)
        cape_pitch = math.radians(10.0 + 18.0 * (sin_p ** 2)) if moving else math.radians(8.0)
        cape_roll = math.radians(2.5 * sin_p) if moving else 0.0
        bob_y = -0.35 * (sin_p ** 2) if moving else 0.0

        cam_light_dir = R_cam @ _LIGHT_DIR

        faces = []

        def add_box(
            center,
            size,
            tex_dict,
            pivot=None,
            local_pitch=0.0,
            local_roll=0.0,
            is_overlay=False,
            omit_faces=None,
            occluder_dict=None
        ):
            if not tex_dict:
                return

            corners = _get_box_corners(tuple(size))
            c_pos = np.array([center[0], center[1] + bob_y, center[2]], dtype=float)
            piv = np.array([pivot[0], pivot[1] + bob_y, pivot[2]], dtype=float) if pivot is not None else c_pos

            if local_pitch != 0.0 and local_roll == 0.0:
                c_p, s_p = math.cos(local_pitch), math.sin(local_pitch)
                R_local = np.array([
                    [1.0, 0.0, 0.0],
                    [0.0, c_p, -s_p],
                    [0.0, s_p, c_p]
                ], dtype=float)
                corners = (corners + (c_pos - piv)) @ R_local.T + (piv - c_pos)
            elif local_pitch != 0.0 or local_roll != 0.0:
                c_p, s_p = math.cos(local_pitch), math.sin(local_pitch)
                c_r, s_r = math.cos(local_roll), math.sin(local_roll)
                R_local = np.array([
                    [c_r, -s_r, 0.0],
                    [s_r, c_r, 0.0],
                    [0.0, 0.0, 1.0]
                ], dtype=float) @ np.array([
                    [1.0, 0.0, 0.0],
                    [0.0, c_p, -s_p],
                    [0.0, s_p, c_p]
                ], dtype=float)
                corners = (corners + (c_pos - piv)) @ R_local.T + (piv - c_pos)

            world_corners = corners + c_pos
            cam_corners = world_corners @ R_cam.T

            for name, idxs in _FACE_DEFS:
                if omit_faces and name in omit_faces:
                    continue
                if occluder_dict:
                    occ_t = occluder_dict.get(name)
                    if occ_t is not None and id(occ_t) in self._opaque_textures:
                        continue
                t = tex_dict.get(name)
                if not t:
                    continue
                v0 = cam_corners[idxs[0]]
                v1 = cam_corners[idxs[1]]
                v2 = cam_corners[idxs[2]]
                v3 = cam_corners[idxs[3]]
                d1 = v1 - v0
                d3 = v3 - v0

                # Backface culling: discard polygons facing away from camera early
                nz = d1[0] * d3[1] - d1[1] * d3[0]
                if nz >= 0:
                    continue

                nx = d1[1] * d3[2] - d1[2] * d3[1]
                ny = d1[2] * d3[0] - d1[0] * d3[2]
                norm_len = math.sqrt(nx * nx + ny * ny + nz * nz)
                if norm_len > 1e-6:
                    inv_len = 1.0 / norm_len
                    nx *= inv_len
                    ny *= inv_len
                    nz *= inv_len

                dot = nx * cam_light_dir[0] + ny * cam_light_dir[1] + nz * cam_light_dir[2]
                shade = max(0.58, min(1.0, 0.78 + 0.22 * dot))
                avg_z = (v0[2] + v1[2] + v2[2] + v3[2]) * 0.25

                faces.append({
                    'tex': t,
                    'pts_cam': (v0, v1, v2, v3),
                    'avg_z': avg_z,
                    'shade': shade,
                    'is_overlay': is_overlay
                })

        aw = 3 if self.model == "slim" else 4

        # Head (8x8x8), center y=18
        add_box([0, 18, 0], [8, 8, 8], self.head_base, occluder_dict=self.head_overlay)
        add_box([0, 18, 0], [8.5, 8.5, 8.5], self.head_overlay, is_overlay=True)

        # Torso (8x12x4), center y=8 (omit occluded top)
        add_box([0, 8, 0], [8, 12, 4], self.torso_base, occluder_dict=self.torso_overlay, omit_faces={'top'})
        add_box([0, 8, 0], [8.5, 12.5, 4.5], self.torso_overlay, is_overlay=True, omit_faces={'top'})

        # Right Arm (MC right = -X), shoulder pivot y=12.0 flush with torso side (X = -4.0)
        ra_x = -4 - (aw / 2.0)
        add_box([ra_x, 8, 0], [aw, 12, 4], self.ra_base, pivot=[ra_x, 12.0, 0], local_pitch=arm_angle, occluder_dict=self.ra_overlay)
        add_box([ra_x, 8, 0], [aw + 0.5, 12.5, 4.5], self.ra_overlay, pivot=[ra_x, 12.0, 0], local_pitch=arm_angle, is_overlay=True)

        # Left Arm (MC left = +X), shoulder pivot y=12.0 flush with torso side (X = +4.0)
        la_x = 4 + (aw / 2.0)
        add_box([la_x, 8, 0], [aw, 12, 4], self.la_base, pivot=[la_x, 12.0, 0], local_pitch=-arm_angle, occluder_dict=self.la_overlay)
        add_box([la_x, 8, 0], [aw + 0.5, 12.5, 4.5], self.la_overlay, pivot=[la_x, 12.0, 0], local_pitch=-arm_angle, is_overlay=True)

        # Right Leg (MC right = -X), pelvis extension top Y=2.85, height 12.85, hip pivot y=2.0
        # Pants overlay inner face clamped at X=0.0 (X in [-4.25, 0.0], center X=-2.125, width=4.25)
        add_box([-2, -3.575, 0], [4, 12.85, 4], self.rl_base, pivot=[-2, 2.0, 0], local_pitch=leg_angle, occluder_dict=self.rl_overlay)
        add_box([-2.125, -3.575, 0], [4.25, 12.85, 4.5], self.rl_overlay, pivot=[-2, 2.0, 0], local_pitch=leg_angle, is_overlay=True)

        # Left Leg (MC left = +X), pelvis extension top Y=2.85, height 12.85, hip pivot y=2.0
        # Pants overlay inner face clamped at X=0.0 (X in [0.0, 4.25], center X=+2.125, width=4.25)
        add_box([2, -3.575, 0], [4, 12.85, 4], self.ll_base, pivot=[2, 2.0, 0], local_pitch=-leg_angle, occluder_dict=self.ll_overlay)
        add_box([2.125, -3.575, 0], [4.25, 12.85, 4.5], self.ll_overlay, pivot=[2, 2.0, 0], local_pitch=-leg_angle, is_overlay=True)

        # Cape attached to upper back of torso (z=2.8, pivot y=14, z=2.4) (omit occluded front)
        if self.cape_tex:
            add_box([0, 6, 2.8], [10, 16, 1], self.cape_tex, pivot=[0, 14, 2.4], local_pitch=-cape_pitch, local_roll=cape_roll, omit_faces={'front'})

        # Sort faces back to front, ensuring overlay draws above base on equal depth
        faces.sort(key=lambda f: (f['avg_z'], 0 if f['is_overlay'] else 1), reverse=True)

        if scale is None:
            scale = min(width / 34.0, height / 39.0)
        pedestal_y = int(height * 0.86)
        cy = (pedestal_y - 2) - (cp * 10.0 * scale)
        cx = width / 2.0

        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))

        for f in faces:
            tex = f['tex']
            pts_cam = f['pts_cam']
            p0 = (cx + pts_cam[0][0] * scale, cy - pts_cam[0][1] * scale)
            p1 = (cx + pts_cam[1][0] * scale, cy - pts_cam[1][1] * scale)
            p2 = (cx + pts_cam[2][0] * scale, cy - pts_cam[2][1] * scale)
            p3 = (cx + pts_cam[3][0] * scale, cy - pts_cam[3][1] * scale)

            # Subpixel crack prevention: conservative 0.35px expansion outward from 2D centroid
            c_qx = (p0[0] + p1[0] + p2[0] + p3[0]) * 0.25
            c_qy = (p0[1] + p1[1] + p2[1] + p3[1]) * 0.25

            dx0, dy0 = p0[0] - c_qx, p0[1] - c_qy
            dx1, dy1 = p1[0] - c_qx, p1[1] - c_qy
            d0 = math.hypot(dx0, dy0)
            d1 = math.hypot(dx1, dy1)
            inv0 = 0.35 / d0 if d0 > 1e-4 else 0.0
            inv1 = 0.35 / d1 if d1 > 1e-4 else 0.0

            # 2D parallelogram symmetry: opposite vertices have equal distance to centroid
            p0_e = (p0[0] + dx0 * inv0, p0[1] + dy0 * inv0)
            p1_e = (p1[0] + dx1 * inv1, p1[1] + dy1 * inv1)
            p2_e = (p2[0] - dx0 * inv0, p2[1] - dy0 * inv0)
            p3_e = (p3[0] - dx1 * inv1, p3[1] - dy1 * inv1)

            W, H = float(tex.width), float(tex.height)
            vx0 = (p1_e[0] - p0_e[0]) / W
            vx1 = (p1_e[1] - p0_e[1]) / W
            vy0 = (p3_e[0] - p0_e[0]) / H
            vy1 = (p3_e[1] - p0_e[1]) / H
            det = vx0 * vy1 - vx1 * vy0
            if abs(det) < 1e-4:
                continue

            inv_det = 1.0 / det
            a = vy1 * inv_det
            b = -vy0 * inv_det
            d = -vx1 * inv_det
            e = vx0 * inv_det

            min_x = int(math.floor(min(p0_e[0], p1_e[0], p2_e[0], p3_e[0])))
            min_y = int(math.floor(min(p0_e[1], p1_e[1], p2_e[1], p3_e[1])))
            max_x = int(math.ceil(max(p0_e[0], p1_e[0], p2_e[0], p3_e[0])))
            max_y = int(math.ceil(max(p0_e[1], p1_e[1], p2_e[1], p3_e[1])))
            bw = max(1, max_x - min_x)
            bh = max(1, max_y - min_y)
            if max_x < 0 or min_x >= width or max_y < 0 or min_y >= height:
                continue

            dx = min_x - p0_e[0]
            dy = min_y - p0_e[1]
            c_val = a * dx + b * dy + 1.0
            f_val = d * dx + e * dy + 1.0

            tid = id(tex)
            tex_padded = self._padded_cache.get(tid)
            if tex_padded is None:
                tex_padded = _pad_edge_1px(tex)
                self._padded_cache[tid] = tex_padded

            shade_key = (tid, int(f['shade'] * 24))
            tex_shaded = self._shaded_cache.get(shade_key)
            if tex_shaded is None:
                if f['shade'] < 0.98:
                    lut = _get_shading_lut(f['shade'])
                    if hasattr(tex_padded, '_new') and hasattr(tex_padded, 'im'):
                        tex_shaded = tex_padded._new(tex_padded.im.point(lut, None))
                    else:
                        tex_shaded = tex_padded.point(lut)
                else:
                    tex_shaded = tex_padded
                self._shaded_cache[shade_key] = tex_shaded

            warped = tex_shaded.transform(
                (bw, bh),
                Image.Transform.AFFINE,
                (a, b, c_val, d, e, f_val),
                resample=RESAMPLE_NEAREST
            )

            mask = Image.new('L', (bw, bh), 0)
            draw = ImageDraw.Draw(mask)
            poly_pts = [(p0_e[0] - min_x, p0_e[1] - min_y), (p1_e[0] - min_x, p1_e[1] - min_y), (p2_e[0] - min_x, p2_e[1] - min_y), (p3_e[0] - min_x, p3_e[1] - min_y)]
            draw.polygon(poly_pts, fill=255)

            is_opaque = tid in self._opaque_textures
            if is_opaque and not f['is_overlay']:
                canvas.paste(warped, (min_x, min_y), mask)
            elif is_opaque and f['is_overlay']:
                canvas.paste(warped, (min_x, min_y), mask)
            else:
                warped.putalpha(Image.composite(warped.getchannel('A'), mask, mask))
                canvas.alpha_composite(warped, (min_x, min_y))

        canvas = _heal_pinhole_voids(canvas)
        return canvas


class SkinRenderer3D:
    _cached_renderers: Dict[Tuple[str, Optional[str], str], Model3DRenderer] = {}

    @classmethod
    def get_renderer(
        cls,
        skin_path: str,
        cape_path: Optional[str] = None,
        model: str = "classic"
    ) -> Model3DRenderer:
        key = (os.path.abspath(skin_path) if skin_path else "",
               os.path.abspath(cape_path) if cape_path else None,
               model)
        if key not in cls._cached_renderers:
            cls._cached_renderers[key] = Model3DRenderer(skin_path, cape_path, model)
        return cls._cached_renderers[key]

    @classmethod
    def render(
        cls,
        skin_path: str,
        model: str = "classic",
        height: int = 360,
        cape_path: Optional[str] = None
    ) -> Optional[Image.Image]:
        try:
            renderer = cls.get_renderer(skin_path, cape_path, model)
            img = renderer.render_frame(yaw_deg=30.0, pitch_deg=10.0, walk_phase=0.0, width=int(height * 0.84), height=height)
            return img
        except Exception as e:
            logger.error("SkinRenderer3D.render failed: %s", e)
            return None

    @classmethod
    def render_frame(
        cls,
        skin_path: str,
        cape_path: Optional[str] = None,
        yaw_deg: float = 30.0,
        pitch_deg: float = 10.0,
        walk_phase: float = 0.0,
        width: int = 360,
        height: int = 400,
        model: str = "classic",
        scale: Optional[float] = None,
        is_walking: Optional[bool] = None
    ) -> Optional[Image.Image]:
        renderer = cls.get_renderer(skin_path, cape_path, model)
        return renderer.render_frame(
            yaw_deg=yaw_deg,
            pitch_deg=pitch_deg,
            walk_phase=walk_phase,
            width=width,
            height=height,
            scale=scale,
            is_walking=is_walking
        )

    @classmethod
    def render_cape_thumbnail(
        cls,
        cape_path: str,
        width: int = 128,
        height: int = 160
    ) -> Optional[Image.Image]:
        if not cape_path or not os.path.exists(cape_path):
            return None
        try:
            with Image.open(cape_path) as img:
                img = img.convert("RGBA")
                w, h = img.size
                if w == 64 and h == 32:
                    face = img.crop((1, 1, 11, 17))
                elif w == 22 and h == 17:
                    face = img.crop((1, 1, 11, 17))
                else:
                    scale = w / 64.0 if w >= 64 else w / 22.0
                    face = img.crop((int(1 * scale), int(1 * scale), int(11 * scale), int(17 * scale)))
                return face.resize((width, height), RESAMPLE_NEAREST)
        except Exception as e:
            logger.error("render_cape_thumbnail failed for %s: %s", cape_path, e)
            return None


__all__ = ["Model3DRenderer", "SkinRenderer3D", "_get_shading_lut"]
