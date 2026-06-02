#!/usr/bin/env python3
"""
Парсер trigger_multiple, связанных с player_speedmod.
Выводит:
- targetname триггера
- все outputs (связи)
- классификацию (nobhop/noflash/…)
- центры всех брашей (через пробел, удобно для setpos)
"""

import sys
import os
import subprocess
import tempfile
import srctools

BSPSRC_JAR = "bspsrc.jar"

# ---------- Функции нормализации и классификации (из вашего старого скрипта) ----------
def normalize_modify_output(key, val):
    """Нормализует выход ModifySpeed в каноническую строку."""
    parts = val.split(',')
    if len(parts) < 3:
        return None
    target = parts[0].strip()
    if parts[1].strip() != 'ModifySpeed':
        return None
    param = parts[2].strip() if len(parts) > 2 else ''
    try:
        p = float(param)
        param = f"{p:.4f}".rstrip('0').rstrip('.') or '0'
    except ValueError:
        pass
    delay_str = parts[3].strip() if len(parts) > 3 else '0'
    try:
        d = float(delay_str)
        d = round(d, 2)
        if abs(d) < 0.02:
            d = 0.0
        delay_str = f"{d:.2f}".rstrip('0').rstrip('.')
    except ValueError:
        pass
    fire_once = parts[4].strip() if len(parts) > 4 else '-1'
    return f"{key} = {target},{parts[1].strip()},{param},{delay_str},{fire_once}"

def classify_trigger(normalized_outputs, flag_mask):
    """Определяет тип триггера (nobhop, noflash и т.д.) по нормализованным выходам и маске флагов speedmod."""
    entries = []
    for out in normalized_outputs:
        left, right = out.split('=', 1)
        event = left.strip()
        parts = right.strip().split(',')
        if len(parts) < 4:
            continue
        param = float(parts[2])
        delay = float(parts[3])
        entries.append({'event': event, 'param': param, 'delay': delay})

    flags_present = [bit for bit in [1, 2, 4, 8, 16, 32, 64, 128] if flag_mask & bit]
    if not flags_present:
        return ['other']

    has_jump_flag = (flag_mask & 4) != 0
    nobhop = False
    if has_jump_flag:
        has_non_one = any(e['param'] != 1.0 for e in entries)
        has_reset_delay = any(e['param'] == 1.0 and e['delay'] > 0 for e in entries)
        if has_non_one and has_reset_delay:
            nobhop = True

    other_delays = [e['delay'] for e in entries if not (nobhop and e['param'] == 1.0 and e['delay'] > 0)]
    if other_delays and max(other_delays) >= 0.2:
        return ['other']
    events = set(e['event'] for e in entries)
    if 'OnTrigger' in events and not ('OnStartTouch' in events or 'OnEndTouch' in events):
        return ['other']
    for e in entries:
        if e['event'] == 'OnEndTouch' and e['param'] != 1.0:
            return ['other']
    if not nobhop:
        start_params = [(e['param'], e['delay']) for e in entries if e['event'] in ('OnStartTouch', 'OnTrigger')]
        if len(start_params) > 1:
            unique_params = set(p for p, d in start_params)
            if len(unique_params) > 1 and not (1.0 in unique_params and len(unique_params) == 2):
                return ['other']

    labels = []
    for bit in flags_present:
        if bit == 4:
            labels.append('nobhop' if nobhop else 'nojump')
        else:
            label = {1: 'noweapons', 2: 'nohud', 8: 'noduck', 16: 'nouse', 32: 'nosprint', 64: 'noflash', 128: 'nozoom'}.get(bit)
            if label:
                labels.append(label)
    return labels if labels else ['other']

# ---------- Основная логика ----------
def run_bspsrc(bsp_path, out_dir):
    vmf_name = os.path.basename(bsp_path).replace('.bsp', '.vmf')
    vmf_path = os.path.join(out_dir, vmf_name)
    subprocess.run(["java", "-jar", BSPSRC_JAR, bsp_path, "--output", vmf_path,
                    "--no_sprp", "--no_overlays", "--no_cubemaps", "--no_details",
                    "--no_areaportals", "--no_occluders", "--no_ladders", "--no_visclusters",
                    "--no_disps", "--no_cubemaptexfix", "--no_ttfix", "--no_lumpfiles",
                    "--appid=240", "--format=NEW"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return vmf_path

def main():
    if len(sys.argv) < 2:
        print("Использование: python script.py map.bsp")
        sys.exit(1)
    bsp_file = sys.argv[1]

    if not os.path.exists(bsp_file):
        print(f"Файл {bsp_file} не найден")
        sys.exit(1)
    if not os.path.exists(BSPSRC_JAR):
        print(f"bspsrc.jar не найден по пути {BSPSRC_JAR}")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="bspsrc_") as tmpdir:
        vmf_path = run_bspsrc(bsp_file, tmpdir)
        vmf = srctools.VMF.parse(vmf_path)

        # ---- 1. Все player_speedmod и их spawnflags ----
        speedmod_info = {}  # targetname -> spawnflags
        for ent in vmf.entities:
            if ent['classname'] == 'player_speedmod':
                tn = ent.get('targetname')
                if tn:
                    speedmod_info[tn] = int(ent.get('spawnflags', 0))

        if not speedmod_info:
            print("player_speedmod не найдены.")
            return

        # ---- 2. Найти trigger_multiple, связанные со speedmod через ModifySpeed ----
        triggers = []
        for ent in vmf.entities:
            if ent['classname'] != 'trigger_multiple':
                continue
            # Проверим outputs на наличие ModifySpeed, ссылающегося на speedmod
            for out in ent.outputs:
                if out.input == 'ModifySpeed' and out.target in speedmod_info:
                    triggers.append(ent)
                    break

        if not triggers:
            print("Нет trigger_multiple, связанных с player_speedmod через ModifySpeed.")
            return

        print(f"Найдено {len(triggers)} trigger_multiple, связанных с player_speedmod:\n")

        for idx, trig in enumerate(triggers, 1):
            tname = trig.get('targetname', '<без имени>')
            print(f"{idx}. trigger_multiple '{tname}'")

            # ---- Вывод всех outputs ----
            print("   Outputs:")
            for out in trig.outputs:
                print(f"      {out.output} -> {out.target},{out.input},{out.params},{out.delay},{out.times}")

            # ---- Классификация ----
            # Собираем нормализованные выходы ModifySpeed
            norm_outputs = []
            involved_speedmods = set()
            for out in trig.outputs:
                if out.input == 'ModifySpeed' and out.target in speedmod_info:
                    # Формируем строку как в старом скрипте
                    fake_key = out.output
                    fake_val = f"{out.target},{out.input},{out.params},{out.delay},{out.times}"
                    norm = normalize_modify_output(fake_key, fake_val)
                    if norm:
                        norm_outputs.append(norm)
                    involved_speedmods.add(out.target)
            # Маска флагов от всех задействованных speedmod
            flag_mask = 0
            for tn in involved_speedmods:
                flag_mask |= speedmod_info.get(tn, 0)
            labels = classify_trigger(norm_outputs, flag_mask)
            print(f"   Classification: {', '.join(labels)}")

            # ---- Геометрия (центры брашей) ----
            print("   Brush centers (for setpos):")
            for j, brush in enumerate(trig.solids, 1):
                try:
                    bmin, bmax = brush.get_bbox()
                    cx = (bmin.x + bmax.x) / 2.0
                    cy = (bmin.y + bmax.y) / 2.0
                    cz = (bmin.z + bmax.z) / 2.0
                    print(f"      {cx:.2f} {cy:.2f} {cz:.2f}")
                except Exception as e:
                    print(f"      Ошибка браша {j}: {e}")
            print()

if __name__ == "__main__":
    main()