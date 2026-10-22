"""遅い追従の逆行を、確認済み復帰と事前価格保護に分けて再検証する。"""

from datetime import datetime, timezone, timedelta
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(BASE))
import engine119
import engine_v2
import catalog_v2


def read(path: Path) -> dict:
    """
    機能: 固定済みのJSONを読み込む。
    引数: path(Path) はUTF-8 JSON。
    返り値: dict。市場APIを呼ばない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value):
    """
    機能: NumPyの集計型を標準型へ変換して保存停止を防ぐ。
    引数: value(任意型) は保存する会計や配列の射影。
    返り値: JSON互換値。非有限数は不明のNoneとする。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 私有の新規成果をUTF-8で保存する。
    引数: path(Path)、value(dict) は保存先と内容。
    返り値: None。旧結果の上書きは禁止する。
    """
    assert not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def settings(symbol: str, scene: str, mode: int, exit_mode: int, guard: int) -> dict:
    """
    機能: 実契約の倍率と既存比較時刻を設定する。
    引数: symbol/scene(str)、mode/exit_mode/guard(int) は固定設定。
    返り値: dict。経済条件を場の成績から変更しない。
    """
    start = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    night = scene.endswith('Night')
    close = start + (timedelta(days=1, hours=5, minutes=40) if night else timedelta(hours=15, minutes=20))
    top = symbol == 'TOPIX'
    return dict(quantity=10 if top else 20, multiplier=1000. if top else 10.,
                fee=41.8 if top else 11., order_tick=.25 if top else 5.,
                observed_tick=.5 if top else 10., execution_mode=mode,
                entry_mode=0, exit_mode=exit_mode, guard=guard,
                entry_end=close.timestamp() - 1200, close_time=close.timestamp())


def variants(base: dict) -> dict:
    """
    機能: 八入口へ対称出口又は追尾出口と、保護無し又は両保護を接続する。
    引数: base(dict) は時系列だけで計算した入口・撤回・幅。
    返り値: dict は32固定政策。入口の閾値探索は追加しない。
    """
    specs, indexes = [], []
    for k, spec in enumerate(base['specs']):
        for xm in (5, 4):
            for em in (0, 3):
                specs.append(dict(spec, id=spec['id'] + f'_X{xm}_P{em}', exit_mode=xm,
                                  execution_mode=em, guard=2))
                indexes.append(k)
    return dict(specs=specs, **{key: base[key][indexes].copy() for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')})


def episodes(ledger: np.ndarray, quotes: dict, bars: dict, multiplier: float) -> list:
    """
    機能: 全親の実約定・気配経路と同時点Lastの差分を実行中に保存する。
    引数: ledger(ndarray[N,16])、quotes/bars(dict)、multiplier(float)。
    返り値: list[dict]。事後順行極値を約定益と呼ばない。
    """
    out = []
    for parent in np.unique(ledger[:, 0]):
        rows = ledger[ledger[:, 0] == parent]
        first, final = rows[0], rows[-1]
        a = int(np.searchsorted(quotes['row'], int(first[1])))
        z = int(np.searchsorted(quotes['row'], int(final[2])))
        assert quotes['row'][a] == first[1] and quotes['row'][z] == final[2]
        direction, price, qty = int(first[5]), first[7], rows[:, 6].sum()
        liquidation = quotes['bid'][a:z + 1] if direction == 1 else quotes['ask'][a:z + 1]
        movement = direction * (liquidation - price)
        gross_last, entry_adverse, exit_adverse = 0., 0., 0.
        legs = []
        for row in rows:
            qi = int(np.searchsorted(quotes['row'], int(row[2])))
            q = row[6]
            gl = direction * (quotes['last'][qi] - quotes['last'][a]) * q * multiplier
            ea = direction * (row[7] - quotes['last'][a]) * q * multiplier
            xa = direction * (quotes['last'][qi] - row[8]) * q * multiplier
            assert abs(gl - ea - xa - row[10] - row[11] - row[12]) < 1e-5
            gross_last += gl
            entry_adverse += ea
            exit_adverse += xa
            legs.append(dict(exit_raw=int(row[2]), exit_time=row[4], quantity=q, exit=row[8],
                             bid=quotes['bid'][qi], ask=quotes['ask'][qi], last=quotes['last'][qi],
                             reason=int(row[13]), net=row[12], decision_to_fill=row[15]))
        b = int(first[14])
        past20 = bars['close'][b] - bars['close'][b - 20] if b >= 20 else None
        out.append(dict(parent=int(parent), direction=direction, quantity=qty,
                        entry_raw=int(first[1]), entry_time=first[3], entry=price,
                        entry_last=quotes['last'][a], entry_bid=quotes['bid'][a], entry_ask=quotes['ask'][a],
                        signal_bar=b, prior20_change=past20, final_time=final[4],
                        MFE_observed=movement.max(), MAE_observed=movement.min(),
                        gross_last_same_times=gross_last, entry_adverse=entry_adverse,
                        exit_adverse=exit_adverse, fees=rows[:, 10:12].sum(),
                        net=rows[:, 12].sum(), legs=legs))
    return out


def main() -> None:
    """
    機能: 事前照合と人工検査の後、保存済み80入力から原因対照を一回だけ実行する。
    引数: なし。初回の固定源・市場原本・実運用プログラムは変更しない。
    返り値: None。全場会計・各親・明細・読取証跡を保存する。
    """
    fixed = read(HERE / '固定計画.json')
    assert read(HERE / '正式登録の全出力.json')['終了コード'] == 0
    manifest = fixed['input_manifest']
    assert (ROOT / manifest['path']).resolve() == (HERE / '入力目録.json').resolve()
    assert hashlib.sha256((ROOT / manifest['path']).read_bytes()).hexdigest() == manifest['sha256']
    for path, sha in fixed['sources'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    out = HERE / 'measurement'
    assert not out.exists()
    out.mkdir()
    meta = read(HERE / '入力目録.json')
    lookup = {(i['session'], i['symbol']): i for i in meta['inputs']}
    old_specs = meta['old_specs']
    old_primary = meta['old_primary']
    old_nets = {(i['symbol'], i['session']): i['net'] for i in meta['old_main_runs']}
    all_rows, all_specs, all_episodes, reads, caches = [], None, [], [], []
    clock = time.monotonic()
    for scene_number, scene in enumerate(meta['sessions']):
        data = {}
        for symbol in ('TOPIX', 'NK225'):
            item = lookup[scene, symbol]
            payload = (ROOT / item['owned_path']).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == item['SHA256']
            with np.load(BytesIO(payload), allow_pickle=False) as source:
                bars = {k[6:]: source[k].copy() for k in source.files if k.startswith('bars__')}
                quotes = {k[8:]: source[k].copy() for k in source.files if k.startswith('quotes__')}
                k = next(i for i, spec in enumerate(old_specs) if spec['id'] == old_primary[symbol])
                policy = {name: source['policies__' + name][k].copy() for name in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
            data[symbol] = dict(bars=bars, quotes=quotes, primary=policy)
            reads.append(dict(session=scene, symbol=symbol, source=item['owned_path'], SHA256=item['SHA256'],
                              original_market_reads=0, original_cache_reads=0))
            with (out / '保存入力読取.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(reads[-1], ensure_ascii=False) + '\n')
        for symbol in ('TOPIX', 'NK225'):
            bars, quotes = data[symbol]['bars'], data[symbol]['quotes']
            other = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            model = variants(catalog_v2.build(bars, data[other]['bars'], symbol))
            # ----------------------------------------
            # 旧入口を保ち、新規保護・返済保護・両方の寄与を四条件で分離する。
            primary = data[symbol]['primary']
            controls = [dict(id=f'BASELINE_P{p}', family='旧固定候補', name='初回固定入口の執行対照',
                             description='当商品で当時選んだ入口を保持し、執行保護だけを変更する。',
                             exit_mode=0, execution_mode=p, guard=1) for p in range(4)]
            specs = model['specs'] + controls
            if all_specs is None:
                all_specs = specs
            assert [s['id'] for s in all_specs] == [s['id'] for s in specs]
            policies = {key: np.concatenate((model[key], np.tile(primary[key], (4, 1))), axis=0)
                        for key in ('entry', 'exit_long', 'exit_short', 'width', 'valid')}
            events = engine119.market_events(bars, quotes)
            ledgers, traces, positions = [], [], []
            for k, spec in enumerate(specs):
                policy = {key: value[k] for key, value in policies.items()}
                setting = settings(symbol, scene, spec['execution_mode'], spec['exit_mode'], spec['guard'])
                answer = engine_v2.run_policy(bars, quotes, policy, setting, events)
                summary = clean(answer['summary'])
                if spec['id'] == 'BASELINE_P0':
                    assert abs(summary['net'] - old_nets[symbol, scene]) < 1e-6, (symbol, scene)
                row = dict(symbol=symbol, session=scene, method=spec['id'],
                           signals=int(np.count_nonzero(policy['entry'])), **summary)
                all_rows.append(row)
                trades = episodes(answer['ledger'], quotes, bars, setting['multiplier'])
                all_episodes.append(dict(symbol=symbol, session=scene, method=spec['id'], parents=trades))
                if len(answer['ledger']):
                    ledgers.append(np.column_stack((np.full(len(answer['ledger']), k), answer['ledger'])))
                traces.append(answer['equity'])
                positions.append(answer['position'])
            path = out / symbol / (scene + '.npz')
            assert not path.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            memory = BytesIO()
            np.savez_compressed(memory, ledger=np.concatenate(ledgers) if ledgers else np.empty((0, 17)),
                                equity=np.asarray(traces), position=np.asarray(positions),
                                **{'policies__' + key: value for key, value in policies.items()})
            payload = memory.getvalue()
            path.write_bytes(payload)
            caches.append(dict(path=path.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(payload).hexdigest()))
            save(out / symbol / (scene + '.json'), dict(rows=all_rows[-len(specs):], episodes=all_episodes[-len(specs):]))
        print(f'{scene_number + 1}/40 {scene} / 保存入力{len(reads)} / {time.monotonic() - clock:.1f}秒', flush=True)
    assert len(reads) == 80 and len(all_specs) == 36
    for path, sha in fixed['sources'].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    save(out / '復帰確認と執行保護の全四十場.json', dict(sessions=meta['sessions'], splits=meta['splits'],
         specs=all_specs, runs=all_rows, episodes=all_episodes, cache=caches, source_SHA256=fixed['sources'],
         原市場追加読取=0, API=0, 実注文=0, 留保='全40場を知った後の原因対照。未知標本での成功とはしない。',
         old_primary=old_primary, reads=reads))
    print('原因対照36政策・両商品40場を保存しました。', flush=True)


if __name__ == '__main__':
    main()
