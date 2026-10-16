"""方向判定と保有管理を分離し、時間出口のない売買を前半選定・後半確認する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

sys.dont_write_bytecode = True
import numpy as np
import numba
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
numba.config.CACHE_DIR = str(HERE / 'numba_cache')
import engine
import accounting
from signals import MODELS

SYMBOLS = ('TOPIX', 'NK225')


def load(path: Path) -> object:
    """機能: 固定したローカル素材を読む。

    引数: path(Path)。返り値: 内容(object)。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(path: Path, value: object) -> None:
    """機能: 今回の作業範囲へだけ結果を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    assert path.resolve().is_relative_to(HERE)
    if path.suffix == '.pkl':
        path.write_bytes(pickle.dumps(value, protocol=5))
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 固定内容を分割読取で照合する。

    引数: path(Path)。返り値: SHA-256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def deny(*args, **kwargs) -> None:
    """機能: 売買再生からのネットワーク利用を禁止する。

    引数: 任意。返り値: なし(None)、例外で停止する。
    """
    raise RuntimeError('保存資料のみを使用する')


def material() -> tuple:
    """機能: 原板気配と、各行までに確定した13方向状態を接続する。

    引数: なし。返り値: 原価格・板・信号・行番号の組(tuple)。
    """
    meta = load(ROOT / 'work/wave_v77/inputs/metadata.json')
    ready, books = {}, {}
    for kind, dest in (('ready', ready), ('features', books)):
        for path in meta['input_paths'][kind]:
            dest.update(load(ROOT / path))
    ready.update(load(ROOT / 'work/wave_v77/inputs/extra_inputs.pkl'))
    books.update(load(ROOT / 'work/wave_v77/inputs/extra_features.pkl'))
    signals = load(HERE / 'prepared/signals.pkl')
    maps = {key: np.arange(len(r['time_s']), dtype=np.int32) for key, r in ready.items()}
    assert set(ready) == set(books) == set(signals)
    return ready, books, signals, maps


def catalog() -> list:
    """機能: 同じ方向定義で入口・継続・出口を行う78条件と単独対照8条件を作る。

    引数: なし。返り値: 固定条件一覧(list)。
    """
    out = []
    for m, model in enumerate(MODELS):
        for x in range(3):
            for entry in range(2):
                out.append(dict(id=f'{model["id"]}_X{x}_M{entry}', model=m, exit_model=m,
                    family=model['id'][:2], entry_mode=entry, exit_mode=x, solo=0, repair=0, freshness=10))
    for m in range(4):
        for entry in range(2):
            out.append(dict(id=f'{MODELS[m]["id"]}_単独_M{entry}', model=m, exit_model=m,
                family='単独対照', entry_mode=entry, exit_mode=0, solo=1, repair=0, freshness=10))
    assert len(out) == 86
    return out


def arguments(c: dict, key: tuple, data: tuple, delay: int) -> tuple:
    """機能: 固定条件を方向追従エンジンへ渡す。

    引数: c(dict)、key/data(tuple)、delay(int)。返り値: エンジン引数(tuple)。
    """
    ready, books, signals, maps = data
    r, f, s = ready[key], books[key], signals[key]
    m, x = c['model'], c['exit_model']
    own_valid = s['valid_self'][m]; peer_valid = s['valid_peer'][m]
    exit_own_valid = s['valid_self'][x]; exit_peer_valid = s['valid_peer'][x]
    if c.get('freshness', 10) < 10:
        young = s['age_peer'] <= c['freshness']
        peer_valid = peer_valid & young; exit_peer_valid = exit_peer_valid & young
    quantity, value, fee = (10, 1000., 41.8) if key[1] == 'TOPIX' else (20, 10., 11.)
    return (r['time_s'], f['bid'], f['ask'], s['price_valid'], f['reset'], maps[key], r['time_s'],
        s['states_self'][m], s['source_self'], s['source_peer'], s['bid'], s['ask'],
        r['tick'], r['start'], r['limit'], quantity, value, fee, float(delay), c['entry_mode'],
        0., 0., 0., 0, 0., 0, s['states_peer'][m], own_valid, peer_valid,
        c['exit_mode'], c['solo'], c.get('repair', 0), s['states_self'][x], s['states_peer'][x], exit_own_valid, exit_peer_valid)


def run_one(c: dict, data: tuple, sessions: list, base: Path, delay: int, fixed: dict) -> str:
    """機能: 一条件の全決済と全行時価を再生し、保有時間は結果として集計する。

    引数: c/fixed(dict)、data(tuple)、sessions(list)、base(Path)、delay(int)。返り値: 条件ID(str)。
    """
    target = base / 'results' / (c['id'] + '.json')
    if target.exists():
        return c['id']
    rows, ledgers, durations = [], {}, {}
    for key in sorted(data[0]):
        if key[0] not in sessions:
            continue
        args = arguments(c, key, data, delay)
        out = engine.simulate(*args)
        rows.append(accounting.account(key, args, out))
        durations[key] = args[0][out[1][:, 2].astype(np.int64)] - args[0][out[1][:, 1].astype(np.int64)]
        ledgers[key] = dict(orders=out[0], trades=out[1], curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest(), stats=out[3], events=out[4])
    periods = {}
    for name, subset in (('対象', sessions), ('前16', fixed['前16']), ('後14', fixed['後14'])):
        periods[name] = {}
        for symbol in SYMBOLS:
            a = accounting.aggregate(rows, symbol, subset)
            parts = [v for k, v in durations.items() if k[0] in subset and k[1] == symbol]
            holds = np.concatenate(parts) if parts else np.zeros(0)
            a['hold_median'] = float(np.median(holds)) if len(holds) else None
            a['hold_p95'] = float(np.percentile(holds, 95)) if len(holds) else None
            a['hold_max'] = float(holds.max()) if len(holds) else None
            a['hold_bins'] = np.histogram(holds, bins=[-1., 5.000001, 30.000001, 60.000001, 300.000001, 1800.000001, np.inf])[0].tolist()
            periods[name][symbol] = a
    path = base / 'ledgers' / (c['id'] + '.pkl')
    save(path, ledgers)
    save(target, dict(config=dict(c, latency=delay), rows=rows, periods=periods, ledger_SHA256=digest(path)))
    return c['id']


def score(result: dict) -> tuple:
    """機能: 前16で双方の活動数と金額利益割合を優先して順位付けする。

    引数: result(dict)。返り値: 大きい順の順位キー(tuple)。
    """
    a = [result['periods']['前16'][s] for s in SYMBOLS]
    sufficient = all(v['trades'] >= 20 and v['active_sessions'] >= 8 for v in a)
    shares = [v['profit_share'] if v['profit_share'] is not None else -1. for v in a]
    return (sufficient, min(shares), sum(shares) / 2,
        min(v['without_best_session'] / max(1., v['fees']) for v in a), result['config']['id'])


def freeze() -> None:
    """機能: 初回の新損益を見る前に、条件・順位・既知の前後分割を固定する。

    引数: なし。返り値: なし(None)。既存の固定記録は上書きしない。
    """
    assert not (HERE / '初回事前固定.json').exists()
    old = load(ROOT / 'work/wave_v80/初回事前固定.json')
    files = [ROOT / n for n in old['SHA256'] if not str(n).replace('\\', '/').startswith('work/wave_v80/')]
    files += [HERE / n for n in ('engine.py', 'accounting.py', 'study.py', 'signals.py', 'prepare.py', 'prepared/signals.pkl', 'design/方向仕様.json')]
    save(HERE / '初回事前固定.json', dict(条件=catalog(), モデル=MODELS, 全30=old['全30'], 前16=old['前16'], 後14=old['後14'],
        思想='時間や利益幅で取引を切らず、価格反転と板更新イベントから方向を逐次判断する。自己は現原板、相手は厳密過去。固定利確・損切り・保有期限・待機秒数は設けない。',
        通常出口={'X0':'両方有効で共同支持が消失（中立・不一致含む）', 'X1':'どちらか有効な一市場が反対', 'X2':'両方有効で反対一致'},
        欠測='欠測を中立や反対へ変換しない。新規不可、既存は有効根拠の出口か場内清算まで保持。この危険も全行時価で計上。',
        場内運用='終了120秒前から新規判断を停止し、60秒前に全返済を判断する。通常の保有期限とは区別。到達後有効気配待ちと残状態を監査。',
        発注='判断時に新規/返済を送り指定0/1/5秒後の最初の有効原本行で約定。既発注成行は未来の信号で消さない。新規約定時も最新方向で返済判断し、ドテンは返済成立後の新しい同方向支持で再判定。',
        初回='86条件を前16・注文5秒で再生。方向家族D1/D2/D3ごとに1代表。単独対照8は代表にしない。',
        選択='双方20決済・8活動場以上を優先し、低い方の金額利益割合→両平均→低い方の最大勝ち場除外収支/手数料→IDで固定。',
        改修='前半の損失原因を調べて、時間出口を使わない少数改修だけを固定し再生。入口と出口の方向定義を分ける対照、方向状態の再準備を候補とする。',
        最終='代表確定後、同じ条件で後14を含む全30、注文0/1/5秒、相手鮮度3秒で確認。後14も既知データ。後半結果で代表を選び直さない。',
        費用='TOPIXミニ10枚・1000円/pt・片道41.8円/枚、NK225マイクロ20枚・10円/pt・片道11円/枚。注文単位で円未満切捨て。ラージ気配代用。',
        制約='板受信時計なし、代理時計の同時性、ミニ/マイクロ板、待ち順位と部分約定は未実証。金額利益80%や毎場安定を保証しない。',
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in files}, 現在API取得=0, 実注文=0))


def select_initial() -> None:
    """機能: 前半の各思想から代表を固定する。

    引数: なし。返り値: なし(None)。後半の新損益は参照しない。
    """
    assert not (HERE / '初回前半選定.json').exists()
    rs = [load(p) for p in (HERE / 'first/results').glob('*.json')]
    assert len(rs) == 86
    selected = [max([r for r in rs if r['config']['family'] == family], key=score) for family in ('D1', 'D2', 'D3')]
    save(HERE / '初回前半選定.json', dict(代表=[r['config'] for r in selected],
        順位根拠=[dict(id=r['config']['id'], score=score(r), 前16=r['periods']['前16']) for r in selected], 後半新損益未参照=True,
        SHA256={str(p.relative_to(ROOT)):digest(p) for p in sorted((HERE / 'first/results').glob('*.json'))}))


def main() -> None:
    """機能: 固定記録作成、初回探索、前半選定を実行する。

    引数: CLI --freeze/--select(bool)、--workers(int)。返り値: なし(None)。
    """
    p = argparse.ArgumentParser(); p.add_argument('--freeze', action='store_true'); p.add_argument('--select', action='store_true'); p.add_argument('--workers', type=int, default=3)
    a = p.parse_args(); socket.socket.connect = deny; socket.create_connection = deny
    if a.freeze:
        freeze(); print('保有期限のない初回86条件を損益前に固定しました。'); return
    fixed = load(HERE / '初回事前固定.json')
    assert all(digest(ROOT / name) == value for name, value in fixed['SHA256'].items())
    if a.select:
        select_initial(); print('前半の3代表を固定しました。'); return
    data = material(); sessions = fixed['前16']; base = HERE / 'first'
    for n in ('results', 'ledgers'): (base / n).mkdir(parents=True, exist_ok=True)
    engine.simulate(*arguments(fixed['条件'][0], (sessions[0], 'TOPIX'), data, 5))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks = [pool.submit(run_one, c, data, sessions, base, 5, fixed) for c in fixed['条件']]
        for i, task in enumerate(as_completed(tasks), 1):
            identifier = task.result()
            if i % 6 == 0 or i == len(tasks): print(f'方向追従 前16 {i}/{len(tasks)} {identifier}', flush=True)


if __name__ == '__main__':
    main()
