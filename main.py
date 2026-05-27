import json
import webbrowser
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from sourcepp import bsppp as bsp

# ---------- Импорт graphviz ----------
try:
    import graphviz as gv
    HAS_GV = True
except ImportError:
    gv = None
    HAS_GV = False

# ---------- Импорт networkx ----------
try:
    import networkx as nx
    HAS_NX = True
except ImportError:
    nx = None
    HAS_NX = False

# ---------- Импорт matplotlib для 3D ----------
try:
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    HAS_MPL = True
except ImportError:
    plt = None
    Poly3DCollection = None
    HAS_MPL = False

# ================== НАСТРОЙКИ ==================
MAP_PATH = "trikz_uproar.bsp"   # <-- укажите свою карту
# =================================================

current_map = bsp.BSP(MAP_PATH)

# Кэш люмпов
models         = current_map.get_lump_data_for_models()
faces_lump     = current_map.get_lump_data_for_faces()
surfedges_lump = current_map.get_lump_data_for_surfedges()
edges_lump     = current_map.get_lump_data_for_edges()
vertices_lump  = current_map.get_lump_data_for_vertexes()

# ---------- Типы ----------
Vec3 = Tuple[float, float, float]
Face = List[Vec3]

# ---------- Вспомогательные функции ----------
def parse_vec3(s: Optional[str]) -> Optional[Vec3]:
    if not s:
        return None
    try:
        parts = list(map(float, s.split()))
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
    except ValueError:
        pass
    return None

def get_model_faces(model_index: int) -> Tuple[List[Face], Vec3]:
    if model_index < 0 or model_index >= len(models):
        return [], (0.0, 0.0, 0.0)

    model = models[model_index]
    local_faces: List[Face] = []
    for face_idx in range(model.first_face, model.first_face + model.num_faces):
        face = faces_lump[face_idx]
        poly: Face = []
        for edge_idx in range(face.first_edge, face.first_edge + face.num_edges):
            se = surfedges_lump[edge_idx].surf_edge
            e_idx = abs(se)
            if e_idx >= len(edges_lump):
                continue
            edge = edges_lump[e_idx]
            v_idx = edge.v0 if se >= 0 else edge.v1
            if v_idx >= len(vertices_lump):
                continue
            v = vertices_lump[v_idx]
            poly.append((v.position[0], v.position[1], v.position[2]))
        if poly:
            local_faces.append(poly)

    origin = model.origin[0], model.origin[1], model.origin[2]
    return local_faces, origin

def get_point_bounds(origin: Vec3, mins: Optional[Vec3], maxs: Optional[Vec3]) -> Tuple[Vec3, Vec3]:
    if mins is not None and maxs is not None:
        min_point = origin[0] + mins[0], origin[1] + mins[1], origin[2] + mins[2]
        max_point = origin[0] + maxs[0], origin[1] + maxs[1], origin[2] + maxs[2]
    else:
        half = 16.0
        min_point = origin[0] - half, origin[1] - half, origin[2] - half
        max_point = origin[0] + half, origin[1] + half, origin[2] + half
    return min_point, max_point

def get_target_name(key: str, value: str) -> Optional[str]:
    if key in ("target", "targetname", "parentname"):
        return value
    if key.startswith("On"):
        parts = value.split(",")
        if parts:
            return parts[0].strip()
    return None

def parse_on_output_params(value: str) -> List[str]:
    parts = [p.strip() for p in value.split(",")]
    while len(parts) < 5:
        parts.append("")
    return parts

def explain_connection(key: str, val: str) -> str:
    parts = parse_on_output_params(val)
    if key in ("target", "targetname", "parentname"):
        return f"{key} → {val}"
    if key.startswith("On"):
        target_name = parts[0]
        action = parts[1] if len(parts) > 1 else "?"
        action_ru = {
            "Enable": "Включить",
            "Disable": "Выключить",
            "Toggle": "Переключить",
            "Trigger": "Активировать",
            "AddOutput": "Изменить параметр",
            "SetParent": "Привязать",
            "Kill": "Удалить",
        }.get(action, action)
        if action == "AddOutput":
            param = parts[2] if len(parts) > 2 else "?"
            return f"{key}: {action_ru} у '{target_name}' ({param})"
        return f"{key}: {action_ru} '{target_name}'"
    return f"{key}: {val}"

def get_speedmod_binary(spawnflags_str: Optional[str]) -> str:
    if not spawnflags_str:
        return "00000000"
    try:
        flags_int = int(spawnflags_str)
        return format(flags_int, '08b')
    except ValueError:
        return "00000000"

# ---------- Загрузка всех сущностей карты ----------
def load_all_entities() -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    all_entities: List[Dict[str, Any]] = []
    targetname_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for entity in current_map.get_lump_data_for_entities():
        kv = {item.key: item.value for item in entity.keyvalues}
        classname = kv.get("classname", "")
        if not classname:
            continue
        hammerid = kv.get("hammerid", None)
        info: Dict[str, Any] = {
            "classname": classname,
            "hammerid": hammerid,
            "params": {},
            "connections": [],
            "model_str": None,
            "origin_str": kv.get("origin", ""),
            "type": None,
        }
        for k, v in kv.items():
            if k not in ("classname", "origin", "model", "hammerid"):
                info["params"][k] = v
        for k, v in kv.items():
            if k in ("target", "targetname", "parentname") or k.startswith("On"):
                info["connections"].append((k, v))
        tname = info["params"].get("targetname")
        if tname:
            targetname_index[tname].append(info)
        model_str = kv.get("model", "")
        if model_str.startswith("*"):
            info["model_str"] = model_str
            info["type"] = "brush"
        elif kv.get("origin"):
            info["type"] = "point"
        all_entities.append(info)

    return all_entities, targetname_index

# ---------- Поиск влияния на player_speedmod ----------
def find_speedmod_influence(
    all_entities: List[Dict[str, Any]],
    targetname_index: Dict[str, List[Dict[str, Any]]]
) -> Tuple[Set[int], Dict[int, Dict[str, Any]], List[Tuple[int, int, str]]]:
    core_ids: Set[int] = set()
    for ent in all_entities:
        if ent["classname"] == "player_speedmod":
            core_ids.add(id(ent))

    if not core_ids:
        return set(), {}, []

    related_ids: Set[int] = set(core_ids)
    related_map: Dict[int, Dict[str, Any]] = {id(e): e for e in all_entities}
    edges: List[Tuple[int, int, str]] = []

    changed = True
    while changed:
        changed = False
        current_ents = [related_map[eid] for eid in list(related_ids) if eid in related_map]
        for ent in current_ents:
            ent_tname = ent["params"].get("targetname")
            if not ent_tname:
                continue

            # Входящие связи
            for other in all_entities:
                if id(other) in related_ids:
                    continue
                added = False
                for key, val in other["connections"]:
                    target = get_target_name(key, val)
                    if target == ent_tname:
                        related_ids.add(id(other))
                        changed = True
                        edges.append((id(other), id(ent), explain_connection(key, val)))
                        added = True
                        break
                if added:
                    continue

                # AddOutput динамика
                for key, val in other["connections"]:
                    if not key.startswith("On"):
                        continue
                    parts = parse_on_output_params(val)
                    cmd_target = parts[0]
                    cmd_input = parts[1]
                    if cmd_input == "AddOutput" and len(parts) >= 3:
                        addoutput_param = parts[2]
                        if addoutput_param.startswith("targetname"):
                            spl = addoutput_param.split(None, 1)
                            if len(spl) == 2 and spl[1] == ent_tname:
                                related_ids.add(id(other))
                                changed = True
                                edges.append((id(other), id(ent), explain_connection(key, val)))
                                added = True
                                break
                    if cmd_target == ent_tname:
                        related_ids.add(id(other))
                        changed = True
                        edges.append((id(other), id(ent), explain_connection(key, val)))
                        added = True
                        break
                if added:
                    break

    return related_ids, related_map, list(set(edges))

# ---------- Расшифровка флагов player_speedmod ----------
def decode_speedmod_flags(spawnflags_str: Optional[str]) -> List[str]:
    flags = []
    if not spawnflags_str:
        return flags
    try:
        val = int(spawnflags_str)
    except ValueError:
        return flags
    bit_descriptions = {
        1: "Suppress weapons",
        2: "Suppress HUD",
        4: "Suppress jump",
        8: "Suppress duck",
        16: "Suppress use",
        32: "Suppress sprint",
        64: "Suppress attack",
        128: "Suppress zoom",
    }
    for bit, desc in bit_descriptions.items():
        if val & bit:
            flags.append(f"{desc} ({bit})")
    return flags

# ---------- Получение фигур сущности ----------
def get_world_figures(info: Dict[str, Any]) -> List[List[Vec3]]:
    """Возвращает список фигур (каждая – список уникальных мировых вершин)."""
    if info.get("type") == "brush" and info.get("model_str"):
        model_id = int(info["model_str"][1:])
        local_faces, model_origin = get_model_faces(model_id)
        if not local_faces:
            return []
        entity_origin = parse_vec3(info.get("origin_str", "")) or (0.0, 0.0, 0.0)
        world_faces = []
        for poly in local_faces:
            world_poly = [(v[0] + entity_origin[0], v[1] + entity_origin[1], v[2] + entity_origin[2]) for v in poly]
            world_faces.append(world_poly)

        # Группировка граней по связности (общие рёбра)
        n = len(world_faces)
        adj = [[] for _ in range(n)]
        edge_to_faces = defaultdict(list)
        for i, face in enumerate(world_faces):
            m = len(face)
            for j in range(m):
                v1 = face[j]
                v2 = face[(j+1) % m]
                edge = tuple(sorted((v1, v2)))
                edge_to_faces[edge].append(i)
        for edge, face_indices in edge_to_faces.items():
            if len(face_indices) == 2:
                a, b = face_indices
                adj[a].append(b)
                adj[b].append(a)
        visited = [False] * n
        figures = []
        for i in range(n):
            if not visited[i]:
                comp = []
                stack = [i]
                visited[i] = True
                while stack:
                    node = stack.pop()
                    comp.append(node)
                    for nb in adj[node]:
                        if not visited[nb]:
                            visited[nb] = True
                            stack.append(nb)
                verts_set = set()
                for idx in comp:
                    for v in world_faces[idx]:
                        verts_set.add(v)
                if verts_set:
                    figures.append(sorted(verts_set))
        return figures
    elif info.get("type") == "point" and info.get("origin_str"):
        origin = parse_vec3(info["origin_str"])
        if origin:
            return [[origin]]
    return []

# ---------- Вывод списка speedmod и влияющих сущностей ----------
def print_speedmod_list(related_ids: Set[int], related_map: Dict[int, Dict[str, Any]],
                        edges: List[Tuple[int, int, str]]) -> List[Dict[str, Any]]:
    if not related_ids:
        print("player_speedmod не найдены.")
        return []

    speedmods = []
    others = []
    for eid in related_ids:
        ent = related_map[eid]
        if ent["classname"] == "player_speedmod":
            speedmods.append(ent)
        else:
            others.append(ent)

    speedmod_influencers = defaultdict(list)
    for from_id, to_id, desc in edges:
        to_ent = related_map.get(to_id)
        from_ent = related_map.get(from_id)
        if to_ent and to_ent["classname"] == "player_speedmod":
            speedmod_influencers[to_id].append((from_ent, desc))

    print("\n" + "=" * 60)
    print(f"Всего player_speedmod: {len(speedmods)}")
    for i, sm in enumerate(speedmods):
        sm_id = id(sm)
        print(f"\n--- player_speedmod #{i} ---")
        print(f"  classname: {sm['classname']}")
        print(f"  hammerid: {sm.get('hammerid', '—')}")
        targetname = sm["params"].get("targetname", "—")
        print(f"  targetname: {targetname}")
        speedmod_val = sm["params"].get("speedmod", "не задан")
        print(f"  speedmod: {speedmod_val}")
        spawnflags_str = sm["params"].get("spawnflags", "0")
        binary_str = get_speedmod_binary(spawnflags_str)
        print(f"  spawnflags: {spawnflags_str} (binary: {binary_str})")
        flags = decode_speedmod_flags(spawnflags_str)
        if flags:
            print("  Флаги подавления:")
            for flag in flags:
                print(f"    - {flag}")
        else:
            print("  Флаги подавления: (нет)")
        extra_keys = {k: v for k, v in sm["params"].items()
                      if k not in ("targetname", "speedmod", "spawnflags")}
        if extra_keys:
            print("  Прочие параметры:")
            for k, v in extra_keys.items():
                print(f"    {k}: {v}")
        influencers = speedmod_influencers.get(sm_id, [])
        if influencers:
            print(f"  Влияющие сущности ({len(influencers)}):")
            for inf_ent, desc in influencers:
                print(f"    - {inf_ent['classname']} (hammerid: {inf_ent.get('hammerid', '—')})")
                print(f"      связь: {desc}")
        else:
            print("  Влияющие сущности: не найдены")

    all_list = speedmods + others
    print("\n=== Влияющие сущности ===")
    for i, ent in enumerate(others, start=len(speedmods)):
        model_str = ent.get("model_str", "")
        print(f"[{i}] {ent['classname']} (hammerid: {ent.get('hammerid', '—')}) {model_str}")
        target_ids = set()
        for key, val in ent["connections"]:
            target = get_target_name(key, val)
            if target:
                for sm in speedmods:
                    if sm["params"].get("targetname") == target:
                        target_ids.add(id(sm))
        if target_ids:
            target_descs = []
            for sm_id in target_ids:
                for sm in speedmods:
                    if id(sm) == sm_id:
                        target_descs.append(sm['classname'] + ' (id:' + sm.get('hammerid', '?') + ')')
                        break
            print(f"    влияет на: {', '.join(target_descs)}")

    return all_list

# ---------- Вывод геометрии сущностей ----------
def print_entities_geometry(entities: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 60)
    print("ГЕОМЕТРИЯ СУЩНОСТЕЙ")
    for ent in entities:
        print(f"\n{ent['classname']} (hammerid: {ent.get('hammerid', '—')}) {ent.get('model_str','')}")
        figures = get_world_figures(ent)
        if not figures:
            print("  Геометрия отсутствует")
            continue
        for i, fig in enumerate(figures):
            print(f"  [Фигура {i+1}]:")
            for v in fig:
                print(f"    ({v[0]:.2f}, {v[1]:.2f}, {v[2]:.2f})")

# ---------- Сборка словаря геометрии по флагам ----------
def build_geometry_dict(related_ids: Set[int], related_map: Dict[int, Dict[str, Any]],
                        edges: List[Tuple[int, int, str]]) -> Dict[str, List[List[Vec3]]]:
    speedmods = []
    for eid in related_ids:
        ent = related_map[eid]
        if ent["classname"] == "player_speedmod":
            speedmods.append(ent)

    if not speedmods:
        return {}

    influencers = defaultdict(list)
    for from_id, to_id, desc in edges:
        to_ent = related_map.get(to_id)
        from_ent = related_map.get(from_id)
        if to_ent and to_ent["classname"] == "player_speedmod":
            influencers[to_id].append(from_ent)

    flag_to_speedmods = defaultdict(list)
    for sm in speedmods:
        binary = get_speedmod_binary(sm["params"].get("spawnflags"))
        flag_to_speedmods[binary].append(sm)

    result: Dict[str, List[List[Vec3]]] = {}
    for binary, sm_list in flag_to_speedmods.items():
        all_figures: List[List[Vec3]] = []
        seen_ids = set()
        for sm in sm_list:
            for inf_ent in influencers.get(id(sm), []):
                if id(inf_ent) in seen_ids:
                    continue
                seen_ids.add(id(inf_ent))
                figures = get_world_figures(inf_ent)
                all_figures.extend(figures)
        if all_figures:
            result[binary] = all_figures
    return result

def save_geometry_dict(geom_dict: Dict[str, List[List[Vec3]]],
                       filename_json: str = "speedmod_triggers.json",
                       filename_txt: str = "speedmod_triggers.txt") -> None:
    json_ready: Dict[str, List[List[List[float]]]] = {}
    for flags, figures in geom_dict.items():
        json_figures: List[List[List[float]]] = []
        for figure in figures:
            json_figure = [[round(v[0], 2), round(v[1], 2), round(v[2], 2)] for v in figure]
            json_figures.append(json_figure)
        json_ready[flags] = json_figures

    with open(filename_json, 'w', encoding='utf-8') as f:
        json.dump(json_ready, f, indent=2, ensure_ascii=False)
    print(f"Геометрия сохранена в {filename_json}")

    with open(filename_txt, 'w', encoding='utf-8') as f:
        for flags, figures in json_ready.items():
            f.write(f"Флаги: {flags}\n")
            for i, figure in enumerate(figures, 1):
                f.write(f"  Фигура {i}: [")
                f.write(", ".join(f"({v[0]}, {v[1]}, {v[2]})" for v in figure))
                f.write("]\n")
            f.write("\n")
    print(f"Читаемый вариант сохранён в {filename_txt}")

# ---------- Глобальный граф влияния (graphviz) ----------
def build_speedmod_graph(related_ids: Set[int], related_map: Dict[int, Dict[str, Any]],
                         edges: List[Tuple[int, int, str]]) -> None:
    if not HAS_GV or gv is None:
        print("graphviz не установлен — граф не будет построен.")
        return

    dot = gv.Digraph(name="speedmod_influence", engine="dot", format="png")
    dot.attr(
        rankdir="LR",
        splines="polyline",
        nodesep="0.5",
        ranksep="0.8",
        fontname="Arial",
        fontsize="12",
        label="Влияние на player_speedmod",
        labelloc="t",
        dpi="150",
        size="60,45!",
        ratio="compress",
    )
    dot.attr("node",
        shape="box", style="filled,rounded",
        fontname="Arial", fontsize="9",
        margin="0.15,0.1", penwidth="1.5",
    )
    dot.attr("edge",
        fontname="Arial", fontsize="8",
        color="#555555", arrowhead="open",
    )

    def color(cls: str) -> str:
        if cls == "player_speedmod":
            return "#F9CA24"
        elif cls.startswith("trigger_"):
            return "#FF6B6B"
        elif cls.startswith("func_"):
            return "#4ECDC4"
        elif cls.startswith("filter_"):
            return "#45B7D1"
        else:
            return "#E0E0E0"

    for eid in related_ids:
        ent = related_map[eid]
        label = ent["classname"]
        if ent.get("hammerid"):
            label += f"\n(id:{ent['hammerid']})"
        tname = ent["params"].get("targetname")
        if tname:
            label += f"\ntn:{tname}"
        dot.node(str(eid), label, fillcolor=color(ent["classname"]), fontcolor="black")

    for from_id, to_id, desc in edges:
        edge_label = desc if len(desc) <= 70 else desc[:67] + "..."
        dot.edge(str(from_id), str(to_id), label=edge_label)

    with dot.subgraph(name="cluster_legend") as legend:
        legend.attr(label="Типы", fontsize="10", style="dashed")
        items = [
            ("player_speedmod", "#F9CA24"),
            ("trigger_*", "#FF6B6B"),
            ("func_*", "#4ECDC4"),
            ("filter_*", "#45B7D1"),
            ("прочее", "#E0E0E0"),
        ]
        for i, (name, clr) in enumerate(items):
            legend.node(f"leg{i}", name, fillcolor=clr, fontsize="8", shape="box", style="filled,rounded")
        for i in range(len(items)-1):
            legend.edge(f"leg{i}", f"leg{i+1}", style="invis")

    dot.attr(size="60,45!", ratio="compress", dpi="150")
    out = "speedmod_influence"
    try:
        dot.render(out, format="png", cleanup=False)
        print(f"✅ Глобальный граф сохранён в {out}.png")
        webbrowser.open(f"{out}.png")
    except Exception as e:
        print(f"❌ Ошибка рендеринга: {e}")

# ---------- 3D-визуализация сущности ----------
def visualize_entity_3d(info: Dict[str, Any]) -> None:
    if not HAS_MPL or plt is None or Poly3DCollection is None:
        print("matplotlib не установлен — 3D-визуализация недоступна.")
        return

    world_faces = None
    origin = None
    mins, maxs = None, None

    if info.get("type") == "brush" and info.get("model_str"):
        try:
            model_id = int(info["model_str"][1:])
            local_faces, model_origin = get_model_faces(model_id)
            if local_faces:
                entity_origin = parse_vec3(info.get("origin_str", "")) or (0.0, 0.0, 0.0)
                world_faces = []
                for poly in local_faces:
                    world_poly = [(v[0] + entity_origin[0], v[1] + entity_origin[1], v[2] + entity_origin[2]) for v in poly]
                    world_faces.append(world_poly)
                origin = entity_origin
        except (ValueError, IndexError) as e:
            print(f"Не удалось получить геометрию модели: {e}")

    if world_faces is None and info.get("origin_str"):
        origin = parse_vec3(info["origin_str"])
        if origin:
            mins_str = info["params"].get("mins")
            maxs_str = info["params"].get("maxs")
            mins = parse_vec3(mins_str) if mins_str else None
            maxs = parse_vec3(maxs_str) if maxs_str else None
        else:
            print("Сущность не имеет допустимых координат origin.")
            return
    elif world_faces is None:
        print("Сущность не имеет геометрии (ни brush, ни point).")
        return

    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_subplot(111, projection='3d')
    title = info["classname"]
    if info.get("hammerid"):
        title += f" (id:{info['hammerid']})"
    ax.set_title(title)

    if world_faces is not None:
        poly3d = Poly3DCollection(world_faces, alpha=0.6, edgecolor='k', facecolor='cyan')
        ax.add_collection3d(poly3d)
        all_verts = [v for poly in world_faces for v in poly]
        xs, ys, zs = zip(*all_verts)
        ax.set_xlim(min(xs)-10, max(xs)+10)
        ax.set_ylim(min(ys)-10, max(ys)+10)
        ax.set_zlim(min(zs)-10, max(zs)+10)
    else:
        min_point, max_point = get_point_bounds(origin, mins, maxs)
        corners = [
            (min_point[0], min_point[1], min_point[2]),
            (min_point[0], min_point[1], max_point[2]),
            (min_point[0], max_point[1], min_point[2]),
            (min_point[0], max_point[1], max_point[2]),
            (max_point[0], min_point[1], min_point[2]),
            (max_point[0], min_point[1], max_point[2]),
            (max_point[0], max_point[1], min_point[2]),
            (max_point[0], max_point[1], max_point[2]),
        ]
        edges_cube = [(0,1),(0,2),(0,4),(1,3),(1,5),(2,3),(2,6),(3,7),(4,5),(4,6),(5,7),(6,7)]
        for e in edges_cube:
            xs_line = [corners[e[0]][0], corners[e[1]][0]]
            ys_line = [corners[e[0]][1], corners[e[1]][1]]
            zs_line = [corners[e[0]][2], corners[e[1]][2]]
            ax.plot(xs_line, ys_line, zs_line, color='blue')
        ax.scatter(*origin, color='red', s=50)
        ax.set_xlim(min_point[0]-10, max_point[0]+10)
        ax.set_ylim(min_point[1]-10, max_point[1]+10)
        ax.set_zlim(min_point[2]-10, max_point[2]+10)

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    ax.set_zlabel('Z')
    plt.show()

# ---------- Локальный граф связей (networkx) ----------
def build_local_graph(entity: Dict[str, Any], all_entities: List[Dict[str, Any]],
                      targetname_index: Dict[str, List[Dict[str, Any]]]) -> None:
    if not HAS_NX or nx is None:
        print("networkx не установлен — локальный граф недоступен.")
        return

    related = {id(entity): entity}
    edges = []

    ent_tname = entity["params"].get("targetname")
    if ent_tname:
        for other in all_entities:
            for key, val in other["connections"]:
                if get_target_name(key, val) == ent_tname:
                    if id(other) not in related:
                        related[id(other)] = other
                    edges.append((id(other), id(entity), explain_connection(key, val)))

    for key, val in entity["connections"]:
        target = get_target_name(key, val)
        if target:
            for tgt in targetname_index.get(target, []):
                if id(tgt) not in related:
                    related[id(tgt)] = tgt
                edges.append((id(entity), id(tgt), explain_connection(key, val)))

    for other in all_entities:
        if id(other) in related:
            continue
        for key, val in other["connections"]:
            if not key.startswith("On"):
                continue
            parts = parse_on_output_params(val)
            if parts[0] == ent_tname or (parts[1] == "AddOutput" and parts[2].startswith("targetname") and parts[2].split(None,1)[-1] == ent_tname):
                if id(other) not in related:
                    related[id(other)] = other
                edges.append((id(other), id(entity), explain_connection(key, val)))
                break

    edges = list(set(edges))
    if len(related) <= 1:
        print("Нет связей для локального графа.")
        return

    G = nx.DiGraph()
    for ent in related.values():
        label = f"{ent['classname']}"
        if ent.get("hammerid"):
            label += f"\n({ent['hammerid']})"
        G.add_node(id(ent), label=label)

    for from_id, to_id, desc in edges:
        if from_id in related and to_id in related:
            G.add_edge(from_id, to_id, label=desc)

    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(G, seed=42, k=2.0, iterations=50)
    labels = {n: G.nodes[n]["label"] for n in G.nodes()}
    nx.draw_networkx_nodes(G, pos, node_color='lightblue', node_size=2000)
    nx.draw_networkx_edges(G, pos, arrowstyle='->', arrowsize=20, edge_color='gray')
    nx.draw_networkx_labels(G, pos, labels, font_size=8)
    edge_labels = {(u,v): d["label"] for u,v,d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=6, label_pos=0.3)
    plt.title(f"Связи сущности {entity['classname']}")
    plt.axis('off')
    plt.tight_layout()
    plt.show()

# ================== ГЛАВНАЯ ЛОГИКА ==================
def main() -> None:
    all_entities, targetname_index = load_all_entities()
    print(f"Загружено {len(all_entities)} сущностей.")

    related_ids, related_map, edges = find_speedmod_influence(all_entities, targetname_index)
    if not related_ids:
        print("player_speedmod не найдены.")
        return

    flat_list = print_speedmod_list(related_ids, related_map, edges)
    print_entities_geometry(flat_list)

    # Сохранение структурированной геометрии
    geom_dict = build_geometry_dict(related_ids, related_map, edges)
    if geom_dict:
        save_geometry_dict(geom_dict)
    else:
        print("Нет геометрии влияющих сущностей для сохранения.")

    print("\nИнтерактивный режим:")
    print("  Введите индекс, hammerid, classname или model (*число) для просмотра 3D-геометрии.")
    print("  :g — глобальный граф влияния")
    print("  :l — локальный граф для последней выбранной сущности")
    print("  Пустая строка — выход.")
    last_selected = None

    while True:
        sel = input("> ").strip()
        if not sel:
            break
        if sel == ":g":
            build_speedmod_graph(related_ids, related_map, edges)
            continue
        if sel == ":l":
            if last_selected:
                build_local_graph(last_selected, all_entities, targetname_index)
            else:
                print("Сначала выберите сущность.")
            continue

        # Поиск сущности
        found = None
        try:
            idx = int(sel)
            if 0 <= idx < len(flat_list):
                found = flat_list[idx]
        except ValueError:
            pass
        if not found:
            for ent in flat_list:
                if ent.get("hammerid") == sel:
                    found = ent
                    break
        if not found:
            for ent in flat_list:
                if sel.lower() in ent["classname"].lower():
                    found = ent
                    break
        if not found:
            for ent in flat_list:
                if ent.get("model_str") == sel:
                    found = ent
                    break
        if not found:
            print("Не найдено.")
            continue

        last_selected = found
        print(f"Выбрано: {found['classname']} (hammerid: {found.get('hammerid')}) {found.get('model_str','')}")
        visualize_entity_3d(found)

if __name__ == "__main__":
    main()