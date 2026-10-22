"""固定した単体政策・全玉清算教師・三つの独立枠を、同じ80入力で比較する。"""

from io import BytesIO
import importlib.util
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np

import plan119 as plan
import input119
import catalog119
import engine119

selector_spec = importlib.util.spec_from_file_location('_selector119', plan.HERE / 'design/selector119.py')
selector = importlib.util.module_from_spec(selector_spec)
selector_spec.loader.exec_module(selector)
OUT = plan.HERE / 'measurement'
SYMBOLS = ('TOPIX', 'NK225')
CONTRACTS = {'TOPIX': dict(quantity=10, multiplier=1000., fee=41.8, order_tick=.25),
             'NK225': dict(quantity=20, multiplier=10., fee=11., order_tick=5.)}


def metrics(rows: list[dict]) -> dict:
    """
    機能: 無取引を勝ちへ含めず、場収支と親損益を別々に集計する。
    引数: rows(list[dict]) は一政策・一商品・指定期間の場集計。
    返り値: dict。金額は円、profit_shareは親単位の正損益合計の割合。
    """
    net = np.asarray([r['net'] for r in rows], float)
    positive = net[net > 1e-7]
    negative = net[net < -1e-7]
    p, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    parents, wins = sum(r['parents'] for r in rows), sum(r['wins'] for r in rows)
    return dict(sessions=len(rows), black=len(positive), red=len(negative), flat=int(np.count_nonzero(np.abs(net) <= 1e-7)),
        active=sum(r['fills'] > 0 for r in rows), net=float(net.sum()), profit=float(p), loss=float(loss),
        profit_share=float(p / (p + loss)) if p + loss else None,
        mean=float(net.mean()) if len(net) else None, median=float(np.median(net)) if len(net) else None,
        q25=float(np.quantile(net, .25)) if len(net) else None,
        worst=float(net.min()) if len(net) else None,
        mean_black=float(positive.mean()) if len(positive) else None,
        worst_to_mean_black=float(-negative.min() / positive.mean()) if len(negative) and len(positive) else (0. if len(positive) else None),
        without_top3_net=float(net.sum() - np.sort(positive)[-3:].sum()),
        parents=int(parents), wins=int(wins), trade_win_rate=float(wins / parents) if parents else None,
        fees=float(sum(r['fees'] for r in rows)), unclosed=sum(r['unclosed'] for r in rows))


def select(rows: list[dict], specs: list[dict], scenes: list[str]) -> dict:
    """
    機能: 事前の選択6場だけで、活動資格を満たす異なる家族を最大三つ選ぶ。
    引数: rows(list[dict])、specs(list[dict])、scenes(list[str]) は当商品結果・固定仕様・選択場。
    返り値: dict。後13場や全40の収支を選択へ戻さない。
    """
    grouped = {s['id']: [] for s in specs}
    for r in rows:
        if r['session'] in scenes:
            grouped[r['method']].append(r)
    ranking = []
    for s in specs:
        m = metrics(grouped[s['id']])
        assert m['sessions'] == len(scenes)
        eligible = m['active'] >= 3 and m['parents'] >= 5 and m['net'] > 0 and m['unclosed'] == 0
        ranking.append(dict(id=s['id'], family=s['family'], eligible=eligible, metrics=m))
    ranking.sort(key=lambda r: (r['eligible'], r['metrics']['black'], r['metrics']['q25'],
        r['metrics']['median'], -(r['metrics']['worst_to_mean_black'] if r['metrics']['worst_to_mean_black'] is not None else 1e20),
        r['metrics']['net'], r['id']), reverse=True)
    chosen, families = [], set()
    for r in ranking:
        if r['eligible'] and r['family'] not in families:
            chosen.append(r['id'])
            families.add(r['family'])
            if len(chosen) == 3:
                break
    return dict(chosen=chosen, qualified=bool(chosen), eligible_ids=[r['id'] for r in ranking if r['eligible']], ranking=ranking)


def variants(base: dict, adaptive: bool = False) -> dict:
    """
    機能: 同じ入口へ、三出口・二新規・場予算有無の予定対照を接続する。
    引数: base(dict) は18又は6入口、adaptive(bool) は選択器側の成行限定。
    返り値: dict。重複した尺度を別家族にせず、実験総数を隠さない。
    """
    specs, ix = [], []
    for k, original in enumerate(base['specs']):
        for xm, em, guard in itertools.product(range(3), (0,) if adaptive else range(2), range(2)):
            s = dict(original)
            s.update(id=original['id'] + f'_X{xm}_E{em}_G{guard}',
                family='ADAPT' if adaptive else original['family'],
                name=original.get('name', '全玉清算教師の自動選択'),
                description=original.get('description', original.get('rule', '当時までの全玉清算資産から選択する。')),
                exit_mode=xm, entry_mode=em, guard=guard, is_adaptive=adaptive)
            specs.append(s)
            ix.append(k)
    return dict(specs=specs, **{key: base[key][ix].copy() for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')})


def settings(symbol: str, scene: str, spec: dict, quantity: int | None = None) -> dict:
    """
    機能: 契約倍率と、場内での固定新規・返済時刻を作る。
    引数: symbol/scene(str)、spec(dict)、quantity(int|None) は実行数量の任意上書き。
    返り値: dict。Day15:00/Night05:20新規停止、20分後に返済判断。
    """
    start, _ = input119.SOURCE.bounds(scene)
    cut = start + (6 * 3600 + 35 * 60 if scene.endswith('_Day') else 12 * 3600 + 40 * 60)
    result = dict(CONTRACTS[symbol], entry_end=cut - 1200, close_time=cut,
        exit_mode=spec['exit_mode'], entry_mode=spec['entry_mode'], guard=spec['guard'])
    if quantity is not None:
        result['quantity'] = quantity
    return result


def save_cache(path: Path, arrays: dict) -> dict:
    """
    機能: 同じ市場入力から生成した配列を、非pickleの所有cacheへ保存する。
    引数: path(Path)、arrays(dict[str,ndarray])。
    返り値: dict。保存path・サイズ・指紋。元の市場フォルダへ書かない。
    """
    assert not path.exists()
    assert all(isinstance(a, np.ndarray) and a.dtype != object for a in arrays.values())
    memory = BytesIO()
    np.savez_compressed(memory, **arrays)
    payload = memory.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    import hashlib
    return dict(path=path.relative_to(plan.ROOT).as_posix(), bytes=len(payload), SHA256=hashlib.sha256(payload).hexdigest())


def evaluate(bars: dict, quotes: dict, models: dict, symbol: str, scene: str) -> tuple:
    """
    機能: 一場一商品で予定政策を実行し、全親台帳と公開時資産を保持する。
    引数: bars/quotes/models(dict)、symbol/scene(str)。
    返り値: tuple は場行list、資産/方向配列、政策ID列を付けた返済明細。
    """
    rows, ledgers, traces, positions = [], [], [], []
    events = engine119.market_events(bars, quotes)
    for k, spec in enumerate(models['specs']):
        policy = {key: models[key][k] for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
        result = engine119.run_policy(bars, quotes, policy, settings(symbol, scene, spec), events)
        rows.append(dict(session=scene, symbol=symbol, method=spec['id'], **result['summary']))
        traces.append(result['equity'])
        positions.append(result['position'])
        if len(result['ledger']):
            ledgers.append(np.column_stack((np.full(len(result['ledger']), k), result['ledger'])))
    return rows, np.asarray(traces), np.asarray(positions), np.concatenate(ledgers) if ledgers else np.empty((0, 17))


def main() -> None:
    """
    機能: 正式登録と人工検査の後だけ市場を読み、固定政策と数量分割を一回実行する。
    引数: なし。入力目録とsource固定の一致を要求する。
    返り値: None。結果JSONと各場cacheを保存し、選択を後期収支で変更しない。
    """
    assert plan.sources() == plan.read(plan.HERE / '正式固定.json')['source_SHA256']
    assert plan.read(plan.HERE / '正式登録の全出力.json')['終了コード'] == 0
    assert not OUT.exists()
    OUT.mkdir()
    inventory = plan.read(plan.HERE / '入力と時系列分割.json')
    lookup = {(i['session'], i['symbol']): i for i in inventory['inputs']}
    all_rows, cached, read_log = [], [], []
    selections = None
    global_specs = None
    previous = {s: None for s in SYMBOLS}
    start_clock = time.monotonic()

    for scene_index, scene in enumerate(inventory['sessions']):
        data = {}
        for symbol in SYMBOLS:
            made = input119.load(lookup[scene, symbol], symbol)
            data[symbol] = made
            read_log.append(made['read_metadata'])
            with (OUT / '入力読取.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(made['read_metadata'], ensure_ascii=False) + '\n')
        for symbol in SYMBOLS:
            peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            bars, quotes = data[symbol]['bars'], data[symbol]['quotes']
            base = variants(catalog119.build(bars, data[peer]['bars'], symbol, previous[symbol]))
            base_rows, base_eq, base_pos, base_ledger = evaluate(bars, quotes, base, symbol, scene)
            teacher = [i for i, s in enumerate(base['specs']) if s['entry_mode'] == 0 and s['guard'] == 0]
            assert len(teacher) == 54
            w20 = base['width'][next(i for i, s in enumerate(base['specs']) if s.get('scale') == 20)]
            roundtrip = 2 * math.floor(CONTRACTS[symbol]['quantity'] * CONTRACTS[symbol]['fee'] + 1e-9)
            adaptive = variants(selector.build_selectors(base_eq[teacher], base_pos[teacher], w20,
                [base['specs'][i]['family'] for i in teacher], roundtrip), adaptive=True)
            auto_rows, auto_eq, auto_pos, auto_ledger = evaluate(bars, quotes, adaptive, symbol, scene)
            specs = base['specs'] + adaptive['specs']
            if global_specs is None:
                global_specs = specs
            assert [s['id'] for s in specs] == [s['id'] for s in global_specs]
            if len(auto_ledger):
                auto_ledger[:, 0] += len(base['specs'])
            ledger = np.concatenate((base_ledger, auto_ledger))
            policies = {key: np.concatenate((base[key], adaptive[key]), axis=0)
                        for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
            arrays = {**{'bars__' + k: v for k, v in bars.items()},
                      **{'quotes__' + k: v for k, v in quotes.items()},
                      **{'policies__' + k: v for k, v in policies.items()},
                      'equity': np.concatenate((base_eq, auto_eq)),
                      'position': np.concatenate((base_pos, auto_pos)), 'ledger': ledger}
            meta = save_cache(OUT / 'prepared' / symbol / (scene + '.npz'), arrays)
            meta.update(session=scene, symbol=symbol, diagnostics=data[symbol]['diagnostics'])
            cached.append(meta)
            all_rows.extend(base_rows + auto_rows)
            value = data[symbol]['last_observed_price']
            previous[symbol] = float(value) if math.isfinite(value) and value > 0 else None
        if scene_index == 26:
            selections = {s: select([r for r in all_rows if r['symbol'] == s], global_specs,
                inventory['splits']['選択6']) for s in SYMBOLS}
            plan.write(OUT / '後十三場前の選択.json', dict(selection=selections,
                実測済み場数=27, 後十三場入力未読=True, 追加三場入力未読=True))
        print(f'{scene_index + 1}/40 {scene} / 原入力{len(read_log)} / 経過{time.monotonic() - start_clock:.1f}秒', flush=True)

    # ----------------------------------------
    # 固定した最大三家族を実数量で再実行する。元の全量損益の比例割算で済ませない。
    portfolios, portfolio_cache = [], []
    for item in cached:
        symbol, scene = item['symbol'], item['session']
        payload = (plan.ROOT / item['path']).read_bytes()
        import hashlib
        assert hashlib.sha256(payload).hexdigest() == item['SHA256']
        with np.load(BytesIO(payload), allow_pickle=False) as saved:
            bars = {key[6:]: saved[key].copy() for key in saved.files if key.startswith('bars__')}
            quotes = {key[8:]: saved[key].copy() for key in saved.files if key.startswith('quotes__')}
            policies = {key[10:]: saved[key].copy() for key in saved.files if key.startswith('policies__')}
        chosen = selections[symbol]['chosen']
        events = engine119.market_events(bars, quotes)
        sleeve_rows, sleeve_ledgers, traces = [], [], []
        quantities = (4, 3, 3) if symbol == 'TOPIX' else (8, 6, 6)
        for slot, mid in enumerate(chosen):
            k = next(i for i, s in enumerate(global_specs) if s['id'] == mid)
            policy = {key: policies[key][k] for key in policies}
            result = engine119.run_policy(bars, quotes, policy, settings(symbol, scene, global_specs[k], quantities[slot]), events)
            sleeve_rows.append(result['summary'])
            if len(result['ledger']):
                sleeve_ledgers.append(np.column_stack((np.full(len(result['ledger']), slot), result['ledger'])))
            traces.append(result['equity'])
        total = {key: sum(r[key] for r in sleeve_rows) for key in ('net', 'realized', 'profit', 'loss', 'parents',
            'wins', 'losses', 'closed_quantity', 'fees', 'unclosed', 'canceled', 'fills')}
        total['max_drawdown'] = float(sum(r['max_drawdown'] for r in sleeve_rows))
        total['max_drawdown_is_upper_bound'] = True
        total['halted'] = 0
        portfolios.append(dict(session=scene, symbol=symbol, method='PORT', **total))
        pc = save_cache(OUT / 'portfolio' / symbol / (scene + '.npz'), dict(
            ledger=np.concatenate(sleeve_ledgers) if sleeve_ledgers else np.empty((0, 17)),
            sleeve_equity=np.asarray(traces) if traces else np.empty((0, len(bars['valid'])))))
        pc.update(symbol=symbol, session=scene)
        portfolio_cache.append(pc)
    assert len(read_log) == 80 and len({i['path'] for i in read_log}) == 80
    assert plan.sources() == plan.read(plan.HERE / '正式固定.json')['source_SHA256']
    result = dict(sessions=inventory['sessions'], splits=inventory['splits'], specs=global_specs,
        runs=all_rows, portfolios=portfolios, selection=selections, cache=cached, portfolio_cache=portfolio_cache,
        source_SHA256=plan.sources(), read_log=read_log, API=0, 実注文=0,
        留保='ラージBBOと価格時計を用いた小型契約の代理約定。待ち順位と真受信順は未観測。追加3は設定選択に未使用。')
    plan.write(OUT / '戦略自動選択と全四十場の結果.json', result)
    print('全40場と固定三枠の実数量再実行が完了しました。', flush=True)


if __name__ == '__main__':
    main()
