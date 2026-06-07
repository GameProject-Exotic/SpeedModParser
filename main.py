#!/usr/bin/env python3
"""
Парсер trigger_multiple, связанных с player_speedmod.
Параметры:
  --outputs     показать все outputs триггера
  --origins     показать origin триггера
  --coords      показать min/max брашей (вместо центров)
  --no-centers  не показывать центры брашей
  --hammerid, --hammerID   показать HammerID триггера
  --verbose     включить все расширенные выводы
"""

import sys, os, subprocess, tempfile, argparse, srctools

BSPSRC_JAR = "bspsrc.jar"

def normalize_modify_output(key, val):
    parts = val.split(',')
    if len(parts) < 3: return None
    target = parts[0].strip()
    if parts[1].strip() != 'ModifySpeed': return None
    param = parts[2].strip() if len(parts) > 2 else ''
    try:
        p = float(param); param = f"{p:.4f}".rstrip('0').rstrip('.') or '0'
    except: pass
    delay_str = parts[3].strip() if len(parts) > 3 else '0'
    try:
        d = float(delay_str); d = round(d, 2)
        if abs(d) < 0.02: d = 0.0
        delay_str = f"{d:.2f}".rstrip('0').rstrip('.')
    except: pass
    fire_once = parts[4].strip() if len(parts) > 4 else '-1'
    return f"{key} = {target},{parts[1].strip()},{param},{delay_str},{fire_once}"

def classify_trigger(normalized_outputs, flag_mask):
    entries = []
    for out in normalized_outputs:
        left, right = out.split('=', 1)
        event = left.strip()
        parts = right.strip().split(',')
        if len(parts) < 4: continue
        param = float(parts[2]); delay = float(parts[3])
        entries.append({'event': event, 'param': param, 'delay': delay})
    flags_present = [b for b in (1,2,4,8,16,32,64,128) if flag_mask & b]
    if not flags_present: return ['other']
    has_jump_flag = (flag_mask & 4) != 0
    nobhop = False
    if has_jump_flag:
        has_non_one = any(e['param'] != 1.0 for e in entries)
        has_reset_delay = any(e['param'] == 1.0 and e['delay'] > 0 for e in entries)
        if has_non_one and has_reset_delay: nobhop = True
    other_delays = [e['delay'] for e in entries if not (nobhop and e['param'] == 1.0 and e['delay'] > 0)]
    if other_delays and max(other_delays) >= 0.2: return ['other']
    events = set(e['event'] for e in entries)
    if 'OnTrigger' in events and not ('OnStartTouch' in events or 'OnEndTouch' in events): return ['other']
    for e in entries:
        if e['event'] == 'OnEndTouch' and e['param'] != 1.0: return ['other']
    if not nobhop:
        start_params = [(e['param'], e['delay']) for e in entries if e['event'] in ('OnStartTouch', 'OnTrigger')]
        if len(start_params) > 1:
            unique_params = set(p for p,d in start_params)
            if len(unique_params) > 1 and not (1.0 in unique_params and len(unique_params) == 2):
                return ['other']
    labels = []
    for bit in flags_present:
        if bit == 4:
            labels.append('nobhop' if nobhop else 'nojump')
        else:
            label = {1:'noweapons',2:'nohud',8:'noduck',16:'nouse',32:'nosprint',64:'noflash',128:'nozoom'}.get(bit)
            if label: labels.append(label)
    return labels if labels else ['other']

def print_brushes(trig, args):
    for j, brush in enumerate(trig.solids, 1):
        try:
            bmin, bmax = brush.get_bbox()
            if args.coords:
                sys.stdout.write(f"  Brush {j}: min ({bmin.x:.2f}, {bmin.y:.2f}, {bmin.z:.2f})  max ({bmax.x:.2f}, {bmax.y:.2f}, {bmax.z:.2f})\n")
            else:
                cx = (bmin.x + bmax.x) / 2.0
                cy = (bmin.y + bmax.y) / 2.0
                cz = (bmin.z + bmax.z) / 2.0
                sys.stdout.write(f"{cx:.2f} {cy:.2f} {cz:.2f}\n")
        except Exception as e:
            sys.stdout.write(f"  Brush {j}: error - {e}\n")

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
    parser = argparse.ArgumentParser()
    parser.add_argument('bspfile')
    parser.add_argument('--outputs', action='store_true')
    parser.add_argument('--origins', action='store_true')
    parser.add_argument('--coords', action='store_true')
    parser.add_argument('--no-centers', action='store_true')
    parser.add_argument('--hammerid', '--hammerID', action='store_true', help='Show HammerID')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if args.verbose:
        args.outputs = args.origins = args.coords = args.hammerid = True
    if not os.path.exists(args.bspfile):
        print(f"Файл {args.bspfile} не найден"); sys.exit(1)
    if not os.path.exists(BSPSRC_JAR):
        print(f"bspsrc.jar не найден по пути {BSPSRC_JAR}"); sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="bspsrc_") as tmpdir:
        vmf_path = run_bspsrc(args.bspfile, tmpdir)
        vmf = srctools.VMF.parse(vmf_path)

        speedmod_info = {}
        for ent in vmf.entities:
            if ent['classname'] == 'player_speedmod':
                tn = ent.get('targetname')
                if tn: speedmod_info[tn] = int(ent.get('spawnflags', 0))
        if not speedmod_info:
            print("player_speedmod не найдены."); return

        triggers = []
        for ent in vmf.entities:
            if ent['classname'] != 'trigger_multiple': continue
            for out in ent.outputs:
                if out.input == 'ModifySpeed' and out.target in speedmod_info:
                    triggers.append(ent); break
        if not triggers:
            print("Нет trigger_multiple, связанных с player_speedmod через ModifySpeed."); return

        print(f"Найдено {len(triggers)} trigger_multiple, связанных с player_speedmod:\n")
        for idx, trig in enumerate(triggers, 1):
            tname = trig.get('targetname', '<без имени>')
            header = [f"{idx}. {tname}"]

            norm_outputs = []
            involved = set()
            for out in trig.outputs:
                if out.input == 'ModifySpeed' and out.target in speedmod_info:
                    norm = normalize_modify_output(out.output, f"{out.target},{out.input},{out.params},{out.delay},{out.times}")
                    if norm: norm_outputs.append(norm)
                    involved.add(out.target)
            flag_mask = 0
            for tn in involved: flag_mask |= speedmod_info.get(tn, 0)
            labels = classify_trigger(norm_outputs, flag_mask)
            header.append(f"[{', '.join(labels)}]")

            if args.hammerid:
                # Получаем id (HammerID) – может быть атрибутом .id или в словаре ['id']
                hammer_id = getattr(trig, 'id', None)
                if hammer_id is None:
                    hammer_id = trig.get('id', '?')
                header.append(f"hammerID={hammer_id}")
            if args.origins:
                origin = trig.get('origin', '')
                if origin: header.append(f"origin={origin}")
            sys.stdout.write(' '.join(header) + '\n')
            if args.outputs:
                for out in trig.outputs:
                    sys.stdout.write(f"  {out.output} -> {out.target},{out.input},{out.params},{out.delay},{out.times}\n")
            if not args.no_centers:
                print_brushes(trig, args)
            sys.stdout.write("\n")

if __name__ == '__main__':
    main()