"""時間出口を使わず、損失診断に基づく方向幅と入口・出口の分離を検証する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import socket
import numpy as np
import study

HERE = study.HERE


def material() -> tuple:
    """機能: 固定済み原価格と22方向モデルを接続する。

    引数: なし。返り値: 原価格・板・方向・対応行(tuple)。
    """
    ready, books, _, maps = study.material()
    return ready, books, study.load(HERE / 'extended/signals.pkl'), maps


def arguments(c: dict, key: tuple, data: tuple, delay: int) -> tuple:
    """機能: 強い入口の方向と現在の価格出口が矛盾する新規を止める。

    引数: c(dict)、key/data(tuple)、delay(int)。返り値: エンジン引数(tuple)。
    同時点以前の方向だけで判定し、方向不明を逆方向に変換しない。
    """
    a = list(study.arguments(c, key, data, delay))
    if c.get('entry_gate', 0):
        # ----------------------------------------
        # 自市場・相手市場それぞれの入口と価格方向の一致だけを許可する。
        a[7] = np.where(a[34] & (a[7] == a[32]), a[7], 0).astype(np.int8)
        a[26] = np.where(a[35] & (a[26] == a[33]), a[26], 0).astype(np.int8)
        a[27] = a[27] & a[34]
        a[28] = a[28] & a[35]
    if c.get('solo', 0) and c['exit_mode'] != 0:
        # ----------------------------------------
        # 単独対照でも反対を出口とする条件は中立で降りない。入口品質は変えない。
        a[34] = a[34] & (a[32] != 0)
    return tuple(a)


def run_one(c: dict, data: tuple, sessions: list, base, delay: int, fixed: dict) -> str:
    """機能: 改修条件を全原板で再生し、利益も失われた損失も実会計する。

    引数: c/fixed(dict)、data(tuple)、sessions(list)、base(Path)、delay(int)。
    返り値: 条件ID(str)。後続注文まで再生し、単純な損益符号反転はしない。
    """
    target = base / 'results' / (c['id'] + '.json')
    if target.exists():
        return c['id']
    rows, ledgers, durations = [], {}, {}
    for key in sorted(data[0]):
        if key[0] not in sessions:
            continue
        args = arguments(c, key, data, delay)
        out = study.engine.simulate(*args)
        rows.append(study.accounting.account(key, args, out))
        durations[key] = args[0][out[1][:, 2].astype(np.int64)] - args[0][out[1][:, 1].astype(np.int64)]
        ledgers[key] = dict(orders=out[0].copy(), trades=out[1].copy(),
            curve_hash=hashlib.sha256(out[2].tobytes()).hexdigest(), stats=out[3].copy(), events=out[4].copy())
    periods = {}
    for name, subset in (('対象', sessions), ('前16', fixed['前16']), ('後14', fixed['後14'])):
        periods[name] = {}
        for symbol in study.SYMBOLS:
            a = study.accounting.aggregate(rows, symbol, subset)
            parts = [v for k, v in durations.items() if k[0] in subset and k[1] == symbol]
            holds = np.concatenate(parts) if parts else np.zeros(0)
            a['hold_median'] = float(np.median(holds)) if len(holds) else None
            a['hold_p95'] = float(np.percentile(holds, 95)) if len(holds) else None
            a['hold_max'] = float(holds.max()) if len(holds) else None
            a['hold_bins'] = np.histogram(holds, bins=[-1., 5.000001, 30.000001, 60.000001, 300.000001, 1800.000001, np.inf])[0].tolist()
            periods[name][symbol] = a
    path = base / 'ledgers' / (c['id'] + '.pkl')
    study.save(path, ledgers)
    study.save(target, dict(config=dict(c, latency=delay), rows=rows, periods=periods, ledger_SHA256=study.digest(path)))
    return c['id']


def catalog() -> list:
    """機能: 診断から限定した102比較を作る。

    引数: なし。返り値: 粗い方向54条件と入口・価格出口分離48条件(list)。
    """
    models = study.load(HERE / 'extended/metadata.json')['モデル']
    initial = study.load(HERE / '初回前半選定.json')['代表']
    out = []
    for m in range(13, 22):
        for x in range(3):
            for entry in range(2):
                out.append(dict(id=f'{models[m]["id"]}_X{x}_M{entry}', model=m, exit_model=m,
                    family=models[m]['id'][:2], entry_mode=entry, exit_mode=x, solo=0, repair=0,
                    freshness=10, entry_gate=0, change='方向の価格幅又は板イベント数を拡大'))
    price_index = {v['ticks']: i for i, v in enumerate(models) if v['id'].startswith('D1')}
    for m in [v['model'] for v in initial] + list(range(13, 22)):
        model = models[m]
        family = model['id'][:2]
        if family == 'D1':
            width = model['ticks'] // 2
        elif family == 'D2':
            width = {128: 8, 512: 16, 2048: 32}[model['span']]
        else:
            width = model['ticks']
        exit_m = price_index[width]
        for repair in range(2):
            for entry in range(2):
                out.append(dict(id=f'{model["id"]}_価格出口K{width:02}_再準備{repair}_M{entry}',
                    model=m, exit_model=exit_m, family=family, entry_mode=entry, exit_mode=1,
                    solo=0, repair=repair, freshness=10, entry_gate=1,
                    change='入口と価格出口を整合し、片方の価格反対で返済' + ('・再準備あり' if repair else '・再準備なし')))
    assert len(out) == 102 and len({c['id'] for c in out}) == 102
    return out


def freeze() -> None:
    """機能: 改修損益を見る前に根因・条件・選択基準を保存する。

    引数: なし。返り値: なし(None)。既存の固定記録は上書きしない。
    """
    path = HERE / '改修前固定.json'
    assert not path.exists()
    initial = study.load(HERE / '初回事前固定.json')
    study.save(path, dict(条件=catalog(),
        理由=['細かい方向反転では取引回数が多く、約定気配差と手数料が中値損益をさらに悪化させる。価格幅と非ゼロ板イベント数を拡大して比較する。',
            '強い板方向と二市場反対一致まで待つ出口では、中立・片側反対でも保持する。価格の反対を別に定義し、その時点で返済を判断する。',
            '古い入口が残り、短い出口に既に反対する新規を防ぐため、入口時にも価格出口と整合させる。',
            '同方向の取引を繰り返す場合を、秒数待機ではなく一度有効な支持解消を観測する再準備で比較する。初回の主因だったとは断定しない。'],
        再準備='価格方向との整合条件を加えた後の入口状態を使用する。欠測では再準備せず、有効な支持解消で再準備する。',
        単独対照='同じ価格品質条件を残し、売買方向は自己だけを見る。X0は自己支持消失、X1/X2は自己が明確に反対した時だけ通常返済。二市場版との出口意味を揃える。',
        禁止='通常の固定利確・固定損切り・最大保有時間・確認秒数・固定休止を使用しない。',
        選択='初回代表3と追加102だけを候補に、study.scoreと同じ双方の活動条件・金額利益割合で家族別に選ぶ。改善しなければ初回を残す。',
        後半='代表・自己のみ対照を固定してから全30の0/1/5秒と相手鮮度3秒を再生。後14も過去調査済みで未知試験ではない。',
        前16=initial['前16'], 後14=initial['後14'], 全30=initial['全30'],
        SHA256={str(p.relative_to(study.ROOT)):study.digest(p) for p in
            [HERE / n for n in ('pdca.py', 'engine.py', 'study.py', 'accounting.py', 'extensions.py',
             'extended/signals.pkl', 'extended/metadata.json', '初回前半選定.json', 'diagnosis/初回3代表の方向継続と損失原因.json')]},
        現在API取得=0, 実注文=0))


def select() -> None:
    """機能: 前半のみで最終3条件と銘柄単独対照を固定する。

    引数: なし。返り値: なし(None)。全30や後14はここで読まない。
    """
    path = HERE / '前半選定.json'
    assert not path.exists()
    first = study.load(HERE / '初回前半選定.json')['代表']
    rs = [study.load(HERE / 'first/results' / (c['id'] + '.json')) for c in first]
    extra = sorted((HERE / 'improved/results').glob('*.json'))
    assert len(extra) == 102
    rs += [study.load(p) for p in extra]
    selected = [max([r for r in rs if r['config']['family'] == family], key=study.score) for family in ('D1', 'D2', 'D3')]
    revised = [r['config'] for r in selected]
    solo = [dict(c, id=c['id'] + '_自己のみ', solo=1, family='単独対照') for c in revised]
    unique = list({c['id']: c for c in first + revised + solo}.values())
    study.save(path, dict(初回=first, 改修=revised, 単独対照=solo, 確認条件=unique,
        選定理由=[dict(id=r['config']['id'], score=study.score(r), 前16=r['periods']['前16']) for r in selected],
        後半の新損益未参照=True, SHA256={str(p.relative_to(study.ROOT)):study.digest(p) for p in extra}))


def main() -> None:
    """機能: 前半改修から代表固定、全セッション再確認まで実行する。

    引数: --freeze/--select/--final/--quality(bool)、--workers(int)。返り値: なし(None)。
    """
    p = argparse.ArgumentParser()
    for flag in ('freeze', 'select', 'final', 'quality'):
        p.add_argument('--' + flag, action='store_true')
    p.add_argument('--workers', type=int, default=3)
    a = p.parse_args()
    socket.socket.connect = study.deny; socket.create_connection = study.deny
    if a.freeze:
        freeze(); print('改修102条件を損益参照前に固定しました。'); return
    fixed = study.load(HERE / '改修前固定.json')
    assert all(study.digest(study.ROOT / n) == h for n, h in fixed['SHA256'].items())
    if a.select:
        select(); print('前半のみで代表と単独対照を固定しました。'); return
    data = material()
    if a.final or a.quality:
        selected = study.load(HERE / '前半選定.json')
        if a.quality:
            jobs = [(dict(c, freshness=3), 5, HERE / 'quality3') for c in selected['改修']]
        else:
            jobs = [(c, delay, HERE / 'final' / f'delay{delay}') for delay in (0, 1, 5) for c in selected['確認条件']]
        sessions = fixed['全30']
    else:
        jobs = [(c, 5, HERE / 'improved') for c in fixed['条件']]
        sessions = fixed['前16']
    study.engine.simulate(*arguments(jobs[0][0], (sessions[0], 'TOPIX'), data, jobs[0][1]))
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks = [pool.submit(run_one, c, data, sessions, base, delay, fixed) for c, delay, base in jobs]
        for i, task in enumerate(as_completed(tasks), 1):
            identifier = task.result()
            if i % 6 == 0 or i == len(tasks):
                print(f'方向による売買 {i}/{len(tasks)} {identifier}', flush=True)


if __name__ == '__main__':
    main()
