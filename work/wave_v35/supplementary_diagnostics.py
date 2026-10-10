"""選ばれた悪化条件だけを対象に、固定乱数と符号反転の補助比較を行う。"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import argparse

import numpy as np

import conditional_runner as runner

HERE = runner.HERE


def catalog(mode: str) -> list[dict]:
    """機能: 選択済みB条件の乱数63本と単純反転1本を生成する。

    引数: mode (str)。返り値: 追加64条件又は不適用の空列 (list[dict])。
    """
    assert mode in {r['id'] for r in runner.design.exit_modes()}
    if not mode.startswith('B'):
        return []
    base = next(s for s in runner.design.catalog() if s['id'] == f'H019__{mode}__V000')
    rows = []
    for seed in [*range(1, 64), None]:
        spec = deepcopy(base)
        variant = f'R{seed:03d}' if seed is not None else 'REV0'
        spec.update(id=f'H019__{mode}__{variant}', variant_id=variant, role='supplemental',
            random_seed=seed, reverse_deterioration=seed is None, adoption_scope=False,
            reference_id='H019__A0__V000', always_reference_id='H019__MIN__V000',
            name=base['name'] + (f'／固定乱数seed{seed}' if seed is not None else '／方向の単純反転'))
        rows.append(spec)
    assert len(rows) == len({r['id'] for r in rows}) == 64
    return rows


def prepare() -> dict:
    """機能: 実相場を使わず全分岐・非採用規則・符号反転を事前固定する。

    引数: なし。返り値: 固定記録 (dict)。
    """
    branches = {mode['id']: catalog(mode['id']) for mode in runner.design.exit_modes()}
    assert len(branches['A0']) == len(branches['MIN']) == 0
    assert sum(len(v) for v in branches.values()) == 768
    values = np.array([0, 1, -1, 0, -1], dtype=np.int8)
    assert np.array_equal(values == 0, (-values) == 0)
    assert np.array_equal(-(-values), values)
    payload = {'新損益参照': False, '条件': '初期6で選択されたB条件だけ。A0/MINなら不適用。',
        '全分岐': branches, '追加条件数': 'B選択時64、その他0。768分岐を全て実行する意味ではない。',
        'seed0': '主840内R000を再利用。重複して新手法数へ加えない。',
        '採用変更': False, '正式p値': False, '選択工程全体の乱数化': False,
        '比較': '各銘柄の全13と後7で元条件を上回る収支の本数、中央値、最小最大と活動量を表示。',
        '留保': '活動時刻は同じだが、逆方向時間と実短縮回数は異なる。最良seedを採用しない。',
        '実装SHA256': runner.digest(HERE / 'supplementary_diagnostics.py'),
        '設計固定SHA256': runner.digest(HERE / 'conditional_design_fixed.json'),
        '合成検査': {'全14分岐': True, '乱数63と反転1': True, '非ゼロ時刻の反転保存': True}}
    path = HERE / 'supplementary_design_fixed.json'
    if path.exists():
        assert runner.read(path) == payload
    else:
        runner.save(path, payload)
    return payload


def main() -> None:
    """機能: 主再生の選択を変えず、必要な場合だけ補助64条件を別保存する。

    引数: --prepare (bool)、--workers (int)。返り値: なし (None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    prepare()
    if args.prepare:
        print('補助乱数の全分岐を結果前固定。', flush=True)
        return
    runner.previous.prior.deny_network()
    fixed = runner.prepare()
    selected = runner.read(HERE / '選択固定.json')
    selected_hash = runner.digest(HERE / '選択固定.json')
    finished = runner.read(HERE / '主再生の完了.json')
    assert finished['選択固定SHA256'] == selected_hash
    mode = selected['選択']['selected_exit_mode_id']
    specs = catalog(mode)
    record = {'適用': bool(specs), '理由': '選択Bの方向だけを変える補助比較。' if specs else '選択はA0又はMINで、悪化方向を使用しない。',
        '条件数': len(specs), '全入力数': len(specs) * 26, '全波数': len(specs) * 8,
        '条件IDs': [s['id'] for s in specs], '選択固定SHA256': selected_hash,
        '探索固定SHA256': runner.digest(HERE / '探索条件の固定.json'),
        '基準seed0 ID': f'H019__{mode}__R000' if specs else None,
        '採用変更': False, '正式p値': False, '集計': {}}
    if specs:
        for phase in ('training', 'evaluation', ''):
            for folder in ('sessions', 'ledgers', 'waves', 'summaries'):
                (HERE / 'supplementary' / phase / folder).mkdir(parents=True, exist_ok=True)
        for phase in ('training', 'evaluation'):
            with ProcessPoolExecutor(max_workers=args.workers, initializer=runner.worker_init, initargs=(phase,)) as pool:
                futures = [pool.submit(runner.evaluate, spec, 'supplementary') for spec in specs]
                for count, future in enumerate(as_completed(futures), 1):
                    result = future.result()
                    print(f"補助 {phase} {count}/64 {result['id']}", flush=True)
        summaries = [runner.combine(spec, fixed, 'supplementary') for spec in specs]
        seed0 = runner.read(HERE / 'summaries' / f'H019__{mode}__R000.json')
        original = runner.read(HERE / 'summaries' / f'H019__{mode}__V000.json')
        randoms = [seed0] + [r for r in summaries if r['spec']['random_seed'] is not None]
        assert len(randoms) == 64
        reversed_value = next(r for r in summaries if r['spec']['reverse_deterioration'])
        for period in ('all_symbols', 'symbols'):
            record['集計'][period] = {}
            for symbol in runner.SYMBOLS:
                source = original[period][symbol]
                nets = [r[period][symbol]['net_yen'] for r in randoms]
                record['集計'][period][symbol] = {'元条件': source,
                    '乱数64収支中央値円': float(np.median(nets)), '乱数64収支最小円': min(nets),
                    '乱数64収支最大円': max(nets), '元条件より黒字額が大きい本数': sum(v > source['net_yen'] + 1e-6 for v in nets),
                    '元条件と同じ収支本数': sum(abs(v - source['net_yen']) <= 1e-6 for v in nets),
                    '反転条件': reversed_value[period][symbol],
                    '乱数全64': [{'id': r['id'], '成績': r[period][symbol]} for r in randoms]}
        runner.save(HERE / 'supplementary/全条件の期間集計.json.gz', summaries)
    assert runner.digest(HERE / '選択固定.json') == selected_hash
    runner.prepare()
    runner.save(HERE / '補助乱数診断.json', record)
    print(f'補助診断 {len(specs)}条件を保存。', flush=True)


if __name__ == '__main__':
    main()
