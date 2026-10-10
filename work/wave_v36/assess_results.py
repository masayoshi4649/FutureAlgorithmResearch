"""売買再生の全集合を固定採否へ渡し、独立検査前の判定を別保存する。"""

from __future__ import annotations

import band_runner as runner
import band_assessment as assessment


def collect() -> tuple[dict, dict, list[str], dict]:
    """機能: 全主364・補助65を欠落なく読み、方向対照を組み立てる。

    引数: なし。返り値: 要約、各場、場一覧、方向対照 (tuple[dict,dict,list[str],dict])。
    """
    fixed = runner.prepare()
    items = runner.read(runner.HERE / '全条件の期間集計.json.gz')
    extras = runner.read(runner.HERE / 'supplementary/全条件の期間集計.json.gz')
    assert len(items) == len({r['id'] for r in items}) == 364
    assert len(extras) == len({r['id'] for r in extras}) == 65
    assert {r['id'] for r in items} == {r['id'] for r in fixed['conditions']}
    assert {r['id'] for r in extras} == {r['id'] for r in fixed['supplementary_conditions']}
    index = {r['id']: r for r in items + extras}
    sessions = {}
    for extra, values in ((False, items), (True, extras)):
        folder = runner.HERE / ('supplementary' if extra else '')
        assert runner.read(folder / '主再生の完了.json')['全条件数'] == len(values)
        for item in values:
            identifier = item['id']
            assert runner.read(folder / 'summaries' / (identifier + '.json')) == item
            rows = runner.read(folder / 'sessions' / (identifier + '.json.gz'))
            assert len(rows) == len({(r['session'], r['symbol']) for r in rows}) == 26
            assert {(r['session'], r['symbol']) for r in rows} == {
                (name, symbol) for name in fixed['全セッション'] for symbol in runner.SYMBOLS}
            assert all(r['id'] == identifier for r in rows)
            sessions[identifier] = rows
    randoms = [index[f'Q034__R{seed:03d}'] for seed in range(64)]
    comparison = assessment.random_comparison(index[assessment.PRIMARY], randoms, index['Q034__REV'])
    return index, sessions, fixed['全セッション'], comparison


def main() -> None:
    """機能: 未監査を明示して暫定判定を保存する。正式な採用判断は完備監査が行う。

    引数: なし。返り値: なし (None)。
    """
    index, sessions, names, comparison = collect()
    value = assessment.assess(index, sessions, names, False, comparison)
    assert value['監査完了'] is False and value['既知比較の採用候補'] is False
    runner.save(runner.HERE / '暫定判定.json', value)
    print('全364＋補助65を固定式で暫定判定。独立監査完了とは扱いません。', flush=True)


if __name__ == '__main__':
    main()
