"""固定2場の実原行状態に対し、金融を再生せず接頭因果不変だけを検査する。"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time
import traceback

import numpy as np

import adapter
import states


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSIONS = ('2026-09-21_Day', '2026-10-12_Night')
SYMBOLS = ('TOPIX', 'NK225')
FUTURES = ('最終価格不明', '気配不明', '出来高不明', '完全板不明', '時計不明', '未来活動の売買反射')
PLAN = HERE / '固定2場の実状態接頭検査計画.json'
RESULT = HERE / '固定2場の実状態と二市場pulseの接頭不変.json'


def hashes() -> dict:
    """
    機能: 現状態・入力v2・草案の小さい直接資料だけへ指紋を結ぶ。
    引数: なし。
    返り値: dict[str,str]。巨大原本の反復読取又は金融再生はしない。
    """
    refs = [Path(__file__), HERE / 'states.py', HERE / 'adapter.py', HERE / 'state_artificial.py',
        HERE / '独立状態と厳密過去接続及び実配分の人工検査_補足06.json',
        ROOT / 'work/wave_v103/catalog.py', ROOT / 'work/wave_v103/input_v2/data.py',
        ROOT / 'work/wave_v103/input_v2/correction.py', ROOT / 'work/wave_v103/input_v2/metadata.json',
        ROOT / 'work/wave_v103/input_v2/入力schema.json']
    refs += [ROOT / 'work/wave_v103' / name for name in ('数値設計草案.json', '数値設計補足01.json',
        '数値設計補足02.json', '数値設計補足03.json', '数値設計補足04.json', '数値設計補足05.json', '数値設計補足06.json')]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}


def prepare() -> None:
    """
    機能: 固定場・境界・未来改変範囲を損益前の計画へ登録する。
    引数: なし。
    返り値: None。入力配列をロードしない。既存計画は上書きしない。
    """
    assert not PLAN.exists()
    proof = json.loads((HERE / '独立状態と厳密過去接続及び実配分の人工検査_補足06.json').read_text(encoding='utf-8'))
    assert proof['全合格'] and proof['人工専用'] and proof['正式金融再生'] == 0
    plan = dict(状態='rootの別指示後に一回だけ実行', 場一覧=SESSIONS, 商品一覧=SYMBOLS,
        条件一覧=['C1', 'R1'], 自動単一='U_C1R1の同条件合成も比較', 金融再生=0, API取得=0,
        境界='各口座・条件の初回準備、価格移動通過、移動後確認、初回paired pulse。それぞれ存在しなければ保存開始60/300/900秒の固定接頭を使用。存在しない段階は未成立として記録。',
        未来変更=FUTURES, 未来追加原行数=512,
        検査範囲='全原行の基準状態を一度計算し、選定接頭の切断及び次512原行への6改変と比較。相手も接頭最大時計の厳密過去公表源まで保存し、その後512原行を未来改変。後方全場の改変実行を称しない。',
        SHA256=hashes())
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(計画保存=True, 配列ロード=0, 正式金融再生=0, 計画SHA256=hashlib.sha256(PLAN.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


def prefix(raw: dict, length: int, writable: bool = False) -> dict:
    """
    機能: 原行配列だけを切断し、旧執行map等の異なる軸は状態判断へ混入させない。
    引数: raw(dict)、length(int)は保持行数、writable(bool)は未来編集copy。
    返り値: dict。N軸以外の配列は状態で使わず、元のreadonlyを保持する。
    """
    n = len(raw['raw_seq'])
    return {name: (value[:length].copy() if writable else value[:length]) if value.ndim and len(value) == n else value
            for name, value in raw.items()}


def mutate(raw: dict, start: int, kind: int) -> dict:
    """
    機能: 指定接頭後の512原行だけの観測を変更し、既知接頭を保存する。
    引数: raw(dict)は接頭と次512行、start/kind(int)は未来開始と改変種別。
    返り値: dict。過去原行・原seqを編集しないcopy。
    """
    changed = prefix(raw, len(raw['raw_seq']), True)
    later = slice(start, None)
    if kind == 0:
        changed['last'][later] = np.nan
        changed['lp_reset_reason'][later] = 1
    elif kind == 1:
        changed['bid'][later] = np.nan
        changed['best_price_valid'][later] = False
        changed['depth_transition_valid'][later] = False
    elif kind == 2:
        changed['volume_delta'][later] = np.nan
        changed['volume_delta_usable'][later] = False
        changed['volume_reset_reason'][later] = 1
    elif kind == 3:
        changed['bid_quantities'][later] = np.nan
        changed['depth_valid'][later] = False
        changed['depth_transition_valid'][later] = False
        changed['depth_reset_reason'][later] = 1
    elif kind == 4:
        changed['price_time_s'][later] = np.nan
        changed['price_time_valid'][later] = False
        changed['price_reset_reason'][later] = 1
    else:
        center = float(raw['bid'][max(0, start - 1)] + raw['ask'][max(0, start - 1)])
        if not np.isfinite(center):
            center = 1e6
        changed['bid'][later], changed['ask'][later] = center - raw['ask'][later], center - raw['bid'][later]
        changed['last'][later] = center - raw['last'][later]
        changed['bid_qty'][later], changed['ask_qty'][later] = raw['ask_qty'][later], raw['bid_qty'][later]
        changed['bid_prices'][later], changed['ask_prices'][later] = center - raw['ask_prices'][later], center - raw['bid_prices'][later]
        changed['bid_quantities'][later], changed['ask_quantities'][later] = raw['ask_quantities'][later], raw['bid_quantities'][later]
    return changed


def assert_state(reference: dict, candidate: dict, length: int) -> None:
    """
    機能: 原行接頭の全準備状態・固定ID・段階・代理と疎なログを比較する。
    引数: reference/candidate(dict)、length(int)は過去行数。
    返り値: None。不一致ならAssertionError。末尾金融成果を使用しない。
    """
    for name in ('qualified', 'volume_direction_proxy', 'ready', 'anchor_raw_seq', 'phases'):
        np.testing.assert_array_equal(reference[name][:length], candidate[name][:length], err_msg=name)
    for name in ('events', 'event_raw_seq', 'event_anchor_raw_seq'):
        left = reference[name][reference['events'][:, 0] < length]
        right = candidate[name][candidate['events'][:, 0] < length]
        np.testing.assert_array_equal(left, right, err_msg=name)


def assert_pulse(reference: dict, candidate: dict, length: int) -> None:
    """
    機能: 原行接頭のpulseと判断台帳を比較し、過去消費の変更を検出する。
    引数: reference/candidate(dict)、length(int)は自己の過去行数。
    返り値: None。同時計公表源を後の行へ置換した差も拒否する。
    """
    np.testing.assert_array_equal(reference['event'][:length], candidate['event'][:length])
    if 'peer_rows' in reference:
        np.testing.assert_array_equal(reference['peer_rows'][:length], candidate['peer_rows'][:length])
    assert [row for row in reference['decisions'] if row['row'] < length] == [row for row in candidate['decisions'] if row['row'] < length]


def cut_points(packet: dict, pulse: dict, raw: dict, item: dict) -> tuple[list[dict], dict]:
    """
    機能: 既定段階の初回原行を採用し、不存在なら固定時計接頭へ置き換える。
    引数: packet/pulse/raw/item(dict)は状態と保存時間。
    返り値: tuple[list[dict],dict]。段階不存在は勝手に成立扱いしない。
    """
    cuts, scope = {}, {}
    for name, code in (('初期準備', 2), ('価格移動', 4), ('移動後確認', 5)):
        found = packet['events'][packet['events'][:, 3] == code]
        row = int(found[0, 0]) if len(found) else None
        scope[name] = dict(成立=row is not None, 最初原行=row)
        if row is not None:
            cuts.setdefault(row + 1, []).append(name)
    row = pulse['decisions'][0]['row'] if pulse['decisions'] else None
    scope['初回paired pulse'] = dict(成立=row is not None, 最初原行=row)
    if row is not None:
        cuts.setdefault(row + 1, []).append('初回paired pulse')
    if any(not value['成立'] for value in scope.values()):
        for seconds in (60., 300., 900.):
            found = np.flatnonzero(raw['price_time_valid'] & np.isfinite(raw['price_time_s']) & (raw['price_time_s'] >= item['start'] + seconds))
            if len(found):
                cuts.setdefault(int(found[0]) + 1, []).append(f'固定{seconds:g}秒')
    assert cuts, '固定接頭にも使用できる原行がありません'
    return [dict(length=length, 境界=names) for length, names in sorted(cuts.items())], scope


def execute() -> None:
    """
    機能: rootが許可した固定2場4口座について、一回だけ実状態接頭を検査する。
    引数: なし。
    返り値: None。全条件金融・旧出口・手数料損益は再生しない。
    """
    assert PLAN.exists() and not RESULT.exists()
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    beginning = hashes()
    assert plan['SHA256'] == beginning, '計画後のsource変更を検出しました'
    loader = adapter.module('103実状態接頭だけのv2入力', ROOT / 'work/wave_v103/input_v2/data.py')
    catalog = adapter.module('103実状態接頭だけの条件', ROOT / 'work/wave_v103/catalog.py')
    configurations = {value['id']: value for value in catalog.catalog() if value['id'] in ('C1', 'R1')}
    counts = dict(口座=0, 単一状態=0, 境界接頭=0, 切断局所比較=0, 切断pair比較=0, 切断union比較=0,
                  未来改変局所比較=0, 未来改変pair比較=0, 未来改変union比較=0)
    cover, inputs = {}, {}
    for session in SESSIONS:
        raw, items, packets = {}, {}, {}
        for symbol in SYMBOLS:
            raw[symbol], items[symbol] = loader.load_account(session, symbol, verify=True)
            item = items[symbol]
            inputs[session + '|' + symbol] = dict(位置=item['出力位置'], SHA256=item['出力SHA256'])
            packets[symbol] = {family: states.run(raw[symbol], item, configurations[family + '1']) for family in ('C', 'R')}
            counts['口座'] += 1
            counts['単一状態'] += 2
        for symbol in SYMBOLS:
            other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            own_raw, peer_raw = raw[symbol], raw[other]
            components = {family: dict(own=packets[symbol][family], peer=packets[other][family], peer_raw=peer_raw) for family in ('C', 'R')}
            full_union = states.union_pulses(components, own_raw)
            for family in ('C', 'R'):
                full = states.pulses(packets[symbol][family], packets[other][family], own_raw, peer_raw)
                cuts, scope = cut_points(packets[symbol][family], full, own_raw, items[symbol])
                rows = []
                for cutoff in cuts:
                    length = cutoff['length']
                    stamps = own_raw['price_time_s'][:length]
                    finite = stamps[np.isfinite(stamps)]
                    maximum = float(finite.max())
                    public = states.publication(peer_raw)
                    before = public['rows'][public['times'] < maximum]
                    peer_length = int(before[-1]) + 1 if len(before) else 0
                    local = prefix(own_raw, length)
                    past_peer = prefix(peer_raw, peer_length)
                    short_own = {f: states.run(local, items[symbol], configurations[f + '1']) for f in ('C', 'R')}
                    short_peer = {f: states.run(past_peer, items[other], configurations[f + '1']) for f in ('C', 'R')}
                    assert_state(packets[symbol][family], short_own[family], length)
                    assert_pulse(full, states.pulses(short_own[family], short_peer[family], local, past_peer), length)
                    short_components = {f: dict(own=short_own[f], peer=short_peer[f], peer_raw=past_peer) for f in ('C', 'R')}
                    assert_pulse(full_union, states.union_pulses(short_components, local), length)
                    counts['境界接頭'] += 1
                    counts['切断局所比較'] += 1
                    counts['切断pair比較'] += 1
                    counts['切断union比較'] += 1
                    own_extended = prefix(own_raw, min(len(own_raw['raw_seq']), length + 512))
                    peer_extended = prefix(peer_raw, min(len(peer_raw['raw_seq']), peer_length + 512))
                    for kind in range(6):
                        changed_own, changed_peer = mutate(own_extended, length, kind), mutate(peer_extended, peer_length, kind)
                        altered_own = {f: states.run(changed_own, items[symbol], configurations[f + '1']) for f in ('C', 'R')}
                        altered_peer = {f: states.run(changed_peer, items[other], configurations[f + '1']) for f in ('C', 'R')}
                        assert_state(packets[symbol][family], altered_own[family], length)
                        assert_pulse(full, states.pulses(altered_own[family], altered_peer[family], changed_own, changed_peer), length)
                        altered_components = {f: dict(own=altered_own[f], peer=altered_peer[f], peer_raw=changed_peer) for f in ('C', 'R')}
                        assert_pulse(full_union, states.union_pulses(altered_components, changed_own), length)
                        counts['未来改変局所比較'] += 1
                        counts['未来改変pair比較'] += 1
                        counts['未来改変union比較'] += 1
                    rows.append(dict(cutoff, 最終保持raw_seq=int(own_raw['raw_seq'][length - 1]), 相手保持行数=peer_length,
                        自己未来原行数=len(own_extended['raw_seq']) - length, 相手未来原行数=len(peer_extended['raw_seq']) - peer_length))
                cover[session + '|' + symbol + '|' + family] = dict(成立範囲=scope, 接頭=rows,
                    全場準備完了行数=int(packets[symbol][family]['ready'].sum()), 全場paired pulse数=len(full['decisions']))
                print(json.dumps(dict(完了=session + '|' + symbol + '|' + family, 接頭数=len(rows), 金融再生=0), ensure_ascii=False), flush=True)
    ending = hashes()
    assert beginning == ending
    result = dict(全合格=True, 対象場=SESSIONS, 条件=['C1', 'R1'], 検査件数=counts, 実成立範囲=cover,
        開始終端ソース一致=True, 開始SHA256=beginning, SHA256=ending, 入力NPZ=inputs,
        計画SHA256=hashlib.sha256(PLAN.read_bytes()).hexdigest(), 正式金融再生=0, API取得=0, 実注文=0,
        限界='固定2場のC1/R1と自動単一接続だけ。各接頭の次512行を6方式変更する検査で、後方全場の改変検査ではない。準備/pulse不存在は未成立として保持。収益性又は実受信先後の検査ではない。')
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=counts, 証跡SHA256=hashlib.sha256(RESULT.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


def main() -> None:
    """
    機能: 計画だけの保存とroot許可後の一回検査を、明示引数で分離する。
    引数: CLIの--prepare-plan又は--root-v2-prefix-authorized。
    返り値: None。無引数では実入力をロードしない。
    """
    parser = argparse.ArgumentParser(description='金融を使わない固定2場の接頭検査')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-plan', action='store_true')
    group.add_argument('--root-v2-prefix-authorized', action='store_true')
    args = parser.parse_args()
    if args.prepare_plan:
        prepare()
    else:
        execute()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        folder = HERE / ('接頭False_' + time.strftime('%Y%m%d_%H%M%S'))
        folder.mkdir(exist_ok=False)
        sources = {}
        for name in ('prefix_preflight.py', 'states.py', 'adapter.py'):
            content = (HERE / name).read_bytes()
            (folder / name).write_bytes(content)
            sources[name] = hashlib.sha256(content).hexdigest()
        if PLAN.exists():
            (folder / PLAN.name).write_bytes(PLAN.read_bytes())
        (folder / 'False.json').write_text(json.dumps(dict(全合格=False, 例外=str(error), traceback=traceback.format_exc(),
            原sourceSHA256=sources, 正式金融再生=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
