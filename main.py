#!/usr/bin/env python3
"""
Найти trigger_multiple, связанные с player_speedmod через outputs.
Поддерживает множественные одинаковые ключи (например, несколько OnStartTouch).
Группирует триггеры с идентичным набором outputs.
При флаге --coords выводит геометрию каждого solid'а.
"""

import argparse
import struct
import sys
from collections import defaultdict

EPSILON = 1e-4

# ---------- BSP lump indices (Source engine) ----------
LUMP_ENTITIES    = 0
LUMP_PLANES      = 1
LUMP_NODES       = 5
LUMP_LEAFS       = 10
LUMP_MODELS      = 14
LUMP_LEAFBRUSHES = 17
LUMP_BRUSHES     = 18
LUMP_BRUSHSIDES  = 19

# ---------- Binary structures ----------
HEADER_FORMAT   = "<4s i"
LUMP_FORMAT     = "<i i i i"
DPLANE_FORMAT   = "<f f f f i"
DNODE_FORMAT    = "<i i i 3h 3h H H h H"
DLEAF_FORMAT    = "<i h H 3h 3h H H H H"
DMODEL_FORMAT   = "<f f f f f f f f f i i i"
DBRUSH_FORMAT   = "<i i i"
DBRUSHSIDE_FORMAT = "<H h h h"

# ---------- BSP reader ----------
class BSPFile:
    def __init__(self, path):
        self.file = open(path, 'rb')
        self._read_header()

    def _read_header(self):
        self.file.seek(0)
        ident, version = struct.unpack(HEADER_FORMAT, self.file.read(8))
        if ident != b'VBSP':
            raise ValueError("Not a valid Valve BSP file (missing VBSP magic).")
        self.version = version
        self.lumps = {}
        for i in range(64):
            data = self.file.read(16)
            off, length, ver, fourcc = struct.unpack(LUMP_FORMAT, data)
            self.lumps[i] = (off, length)
        self.file.read(4)  # skip maprevision

    def read_lump(self, lump_index):
        off, length = self.lumps.get(lump_index, (0, 0))
        if length == 0:
            return b''
        self.file.seek(off)
        return self.file.read(length)

    def close(self):
        self.file.close()

# ---------- Entity parser (supports duplicate keys) ----------
def parse_entities(data: bytes):
    """
    Возвращает список сущностей. Каждая сущность — список кортежей (key, value)
    в порядке появления. Это сохраняет все дубликаты ключей (например, несколько OnStartTouch).
    """
    text = data.decode('latin-1', errors='replace').split('\x00', 1)[0]
    entities = []
    current = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('//'):
            continue
        if line == '{':
            current = []          # список кортежей
        elif line == '}':
            if current is not None:
                entities.append(current)
                current = None
        else:
            parts = line.split('"')
            if len(parts) >= 5:
                k, v = parts[1], parts[3]
                if current is not None:
                    current.append((k, v))
    return entities

def get_first(entity, key):
    """Вернуть первое значение для ключа key, или None."""
    for k, v in entity:
        if k == key:
            return v
    return None

def get_all(entity, key=None, prefix=None):
    """
    Вернуть список значений для ключа key (если задан) или для всех ключей,
    начинающихся с prefix (если задан). Возвращает список кортежей (key, value).
    """
    result = []
    for k, v in entity:
        if key is not None and k == key:
            result.append((k, v))
        elif prefix is not None and k.startswith(prefix):
            result.append((k, v))
    return result

# ---------- Geometry helpers ----------
def solve_3x3(a, b, c):
    m = [list(a[0]) + [a[1]], list(b[0]) + [b[1]], list(c[0]) + [c[1]]]
    n = 3
    for col in range(n):
        pivot = None
        for row in range(col, n):
            if abs(m[row][col]) > 1e-10:
                pivot = row
                break
        if pivot is None:
            return None
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        div = m[col][col]
        for j in range(col, n+1):
            m[col][j] /= div
        for row in range(n):
            if row != col:
                factor = m[row][col]
                for j in range(col, n+1):
                    m[row][j] -= factor * m[col][j]
    return (m[0][3], m[1][3], m[2][3])

def brush_vertices(planes):
    verts = []
    n = len(planes)
    for i in range(n):
        for j in range(i+1, n):
            for k in range(j+1, n):
                pt = solve_3x3(planes[i], planes[j], planes[k])
                if pt is None:
                    continue
                inside = True
                for p_idx, (normal, dist) in enumerate(planes):
                    if p_idx in (i, j, k):
                        continue
                    dot = normal[0]*pt[0] + normal[1]*pt[1] + normal[2]*pt[2]
                    if dot > dist + EPSILON:
                        inside = False
                        break
                if inside:
                    rpt = tuple(round(v, 4) for v in pt)
                    if rpt not in verts:
                        verts.append(rpt)
    return verts

# ---------- BSP geometry loading ----------
class BSPGeometry:
    def __init__(self, bsp):
        self.bsp = bsp
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        bsp = self.bsp
        self.models_data     = bsp.read_lump(LUMP_MODELS)
        self.nodes_data      = bsp.read_lump(LUMP_NODES)
        self.leafs_data      = bsp.read_lump(LUMP_LEAFS)
        self.leafbrushes_data= bsp.read_lump(LUMP_LEAFBRUSHES)
        self.brushes_data    = bsp.read_lump(LUMP_BRUSHES)
        self.brushsides_data = bsp.read_lump(LUMP_BRUSHSIDES)
        self.planes_data     = bsp.read_lump(LUMP_PLANES)

        model_size = struct.calcsize(DMODEL_FORMAT)
        self.num_models = len(self.models_data) // model_size
        self.models = []
        for i in range(self.num_models):
            chunk = self.models_data[i*model_size:(i+1)*model_size]
            mins = struct.unpack_from("<3f", chunk, 0)
            maxs = struct.unpack_from("<3f", chunk, 12)
            origin = struct.unpack_from("<3f", chunk, 24)
            headnode = struct.unpack_from("<i", chunk, 36)[0]
            self.models.append({'mins': mins, 'maxs': maxs, 'origin': origin, 'headnode': headnode})

        leaf_size = struct.calcsize(DLEAF_FORMAT)
        self.num_leafs = len(self.leafs_data) // leaf_size
        self.leafs = [None] * self.num_leafs
        for i in range(self.num_leafs):
            vals = struct.unpack(DLEAF_FORMAT, self.leafs_data[i*leaf_size:(i+1)*leaf_size])
            self.leafs[i] = {'contents': vals[0], 'firstleafbrush': vals[7], 'numleafbrushes': vals[8]}

        num_lb = len(self.leafbrushes_data) // 2
        self.leafbrushes = list(struct.unpack(f"<{num_lb}H", self.leafbrushes_data))

        brush_size = struct.calcsize(DBRUSH_FORMAT)
        self.num_brushes = len(self.brushes_data) // brush_size
        self.brushes = []
        for i in range(self.num_brushes):
            firstside, numsides, contents = struct.unpack_from(DBRUSH_FORMAT, self.brushes_data, i*brush_size)
            self.brushes.append((firstside, numsides, contents))

        side_size = struct.calcsize(DBRUSHSIDE_FORMAT)
        self.num_sides = len(self.brushsides_data) // side_size
        self.brushsides = []
        for i in range(self.num_sides):
            planenum = struct.unpack_from("<H", self.brushsides_data, i*side_size)[0]
            self.brushsides.append(planenum)

        plane_size = struct.calcsize(DPLANE_FORMAT)
        self.num_planes = len(self.planes_data) // plane_size
        self.planes = []
        for i in range(self.num_planes):
            nx, ny, nz, dist, ptype = struct.unpack(DPLANE_FORMAT, self.planes_data[i*plane_size:(i+1)*plane_size])
            self.planes.append(((nx, ny, nz), dist))

        self._loaded = True

    def get_solids_vertices(self, model_idx):
        if not self._loaded:
            self.load()
        if model_idx < 0 or model_idx >= self.num_models:
            return []
        headnode = self.models[model_idx]['headnode']
        leafs_to_check = set()
        if headnode < 0:
            leafs_to_check.add(-1 - headnode)
        else:
            stack = [headnode]
            visited = set()
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                if node < 0:
                    leafs_to_check.add(-1 - node)
                    continue
                node_chunk = self.nodes_data[node*struct.calcsize(DNODE_FORMAT):(node+1)*struct.calcsize(DNODE_FORMAT)]
                _, child0, child1 = struct.unpack("<i i i", node_chunk[:12])
                stack.append(child0)
                stack.append(child1)

        brush_indices = set()
        for leaf_idx in leafs_to_check:
            if leaf_idx >= self.num_leafs:
                continue
            leaf = self.leafs[leaf_idx]
            for j in range(leaf['firstleafbrush'], leaf['firstleafbrush'] + leaf['numleafbrushes']):
                if j < len(self.leafbrushes):
                    brush_indices.add(self.leafbrushes[j])

        solids = []
        for b_idx in sorted(brush_indices):
            if b_idx >= self.num_brushes:
                continue
            firstside, numsides, _ = self.brushes[b_idx]
            brush_planes = []
            for s in range(firstside, firstside + numsides):
                if s >= self.num_sides:
                    break
                plane_idx = self.brushsides[s]
                if plane_idx < self.num_planes:
                    brush_planes.append(self.planes[plane_idx])
            if brush_planes:
                verts = brush_vertices(brush_planes)
                if verts:
                    solids.append(verts)
        return solids

# ---------- Main ----------
def process(bsp_path, show_coords):
    bsp = BSPFile(bsp_path)

    ent_data = bsp.read_lump(LUMP_ENTITIES)
    if not ent_data:
        print("Entity lump empty.")
        bsp.close()
        return
    entities = parse_entities(ent_data)

    # Собираем targetname всех player_speedmod
    speedmod_names = set()
    for ent in entities:
        if get_first(ent, 'classname') == 'player_speedmod':
            tn = get_first(ent, 'targetname')
            if tn:
                speedmod_names.add(tn)
    if not speedmod_names:
        print("No player_speedmod entities found.")
        bsp.close()
        return

    # Фильтруем trigger_multiple с выходами на speedmod
    triggers = []
    for ent in entities:
        if get_first(ent, 'classname') != 'trigger_multiple':
            continue
        outputs = get_all(ent, prefix='On')
        for key, val in outputs:
            target = val.split(',', 1)[0].strip()
            if target in speedmod_names:
                triggers.append(ent)
                break

    if not triggers:
        print("No trigger_multiple linked to player_speedmod.")
        bsp.close()
        return

    # Группировка по полному набору outputs (сортированный кортеж всех (key,val) с On*)
    groups = defaultdict(list)
    for trig in triggers:
        outputs = tuple(sorted(get_all(trig, prefix='On')))
        groups[outputs].append(trig)

    # Геометрия только если нужно
    geom = None
    if show_coords:
        geom = BSPGeometry(bsp)
        geom.load()

    first_group = True
    for out_set, trigs in groups.items():
        if not first_group:
            print("\n" + "-"*40)
        first_group = False
        print("\nOutputs:")
        for key, val in out_set:
            print(f"  {key} = {val}")
        print("Triggers:")
        for trig in trigs:
            model = get_first(trig, 'model') or '?'
            tname = get_first(trig, 'targetname') or ''
            print(f"  {model}{' (' + tname + ')' if tname else ''}")
            if show_coords and model.startswith('*'):
                try:
                    model_idx = int(model[1:])
                except ValueError:
                    continue
                solids = geom.get_solids_vertices(model_idx)
                for solid_idx, verts in enumerate(solids, start=1):
                    print(f"    Solid {solid_idx}: {len(verts)} vertices")
                    for v in verts:
                        print(f"      ({v[0]:.3f}, {v[1]:.3f}, {v[2]:.3f})")

    bsp.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Find trigger_multiple entities linked to player_speedmod")
    parser.add_argument('bspfile', help='path to .bsp file')
    parser.add_argument('--coords', action='store_true', help='show detailed geometry (solids and vertices)')
    args = parser.parse_args()
    process(args.bspfile, args.coords)
