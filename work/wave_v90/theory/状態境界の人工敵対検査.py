"""現在状態の境界と反例を、損益エンジンを実行せず独立に確かめる。"""

import ast
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent


def read_state_functions():
    """
    機能: 正式strategyから状態分類関数だけを取り出し、損益計算への接続を除く。
    引数: なし。
    返り値: dict[str, object] は状態分類と確認関数。
    """
    path = BASE / 'strategy.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ('confirmation', 'state', 'mapping'):
            keep.append(node)
    assert len(keep) == 3
    namespace = {'np': np, 'SYMBOLS': ('TOPIX', 'NK225')}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def material(efficiency=.2, common=0, changing_sources=True):
    """
    機能: 将来損益やラベルを含まない最小の二市場状態を作る。
    引数: efficiency(float)、common(int)、changing_sources(bool)。
    返り値: tuple[dict, dict] は格子素材とJ2許可。
    """
    grid = np.array([300., 305., 310., 315., 320.])
    source = np.arange(5, dtype=np.int32) if changing_sources else np.zeros(5, np.int32)
    markets = {}
    for symbol in ('TOPIX', 'NK225'):
        markets[symbol] = {
            'current': {'valid': np.ones(5, bool), 'index': source.copy(), 'mid': np.full(5, 100.)},
            'windows': {300: {'source_valid': np.ones(5, bool), 'efficiency': np.full(5, efficiency),
                              'total_variation': np.full(5, 10.)}},
            'ranges': {180: {'source_valid': np.ones(5, bool), 'position_valid': np.ones(5, bool),
                            'width': np.full(5, 2.), 'low': np.full(5, 99.), 'high': np.full(5, 101.)}}
        }
    entry = {'common': np.full(5, common, np.int8), 'entries': {'J2': {
        'long_allowed': np.ones(5, bool), 'short_allowed': np.ones(5, bool)}}}
    return {'grid': grid, 'markets': markets}, entry


def run():
    """
    機能: ER境界、欠測、逆選択例と分類確認の人工経路を検査して証拠を保存する。
    引数: なし。
    返り値: dict は検査名と件数及び全合格。
    """
    functions = read_state_functions()
    config = {'high_er': .4, 'low_er': .2, 'confirm_seconds': 10.}
    checks = []

    # ----------------------------------------
    for sign in (-1, 1):
        source, entry = material(.4, sign)
        actual = functions['state'](source, entry, config)
        assert np.array_equal(actual['raw_mode'], np.full(5, sign))
        assert np.array_equal(actual['mode'], [0, 0, sign, sign, sign])
        checks.append(f'高ER境界と共同方向{sign}の10秒確認')
    source, entry = material(.2)
    actual = functions['state'](source, entry, config)
    assert np.array_equal(actual['raw_mode'], np.full(5, 2))
    assert np.array_equal(actual['mode'], [0, 0, 2, 2, 2])
    checks.append('低ER境界と範囲内の10秒確認')

    # ----------------------------------------
    for name, efficiency, common, change in [
        ('高ERでも二市場共同方向がない', .4, 0, None),
        ('低ERでも現在共同進行がある', .2, 1, None),
        ('中間ERを往復へ代用しない', .3, 0, None),
        ('窓総変動ゼロを往復へ代用しない', .2, 0, 'zero'),
        ('欠測を往復へ代用しない', .2, 0, 'missing'),
        ('低ERでも直前範囲を脱した端点', .2, 0, 'outside'),
        ('範囲幅ゼロを往復へ代用しない', .2, 0, 'flat'),
        ('片市場ERだけ高い不一致', .2, 0, 'discord')
    ]:
        source, entry = material(efficiency, common)
        market = source['markets']['NK225']
        if change == 'zero':
            market['windows'][300]['total_variation'][:] = 0
        elif change == 'missing':
            market['current']['valid'][:] = False
        elif change == 'outside':
            market['current']['mid'][:] = 102
        elif change == 'flat':
            market['ranges'][180]['width'][:] = 0
        elif change == 'discord':
            market['windows'][300]['efficiency'][:] = .4
        actual = functions['state'](source, entry, config)
        assert not np.any(actual['mode'])
        checks.append(name)

    # ----------------------------------------
    source, entry = material(.2, changing_sources=False)
    assert not functions['state'](source, entry, config)['mode'].any()
    checks.append('同一源を古いまま保持しても状態確認が完了しない')
    fast = dict(config, confirm_seconds=0.)
    assert np.array_equal(functions['state'](source, entry, fast)['mode'], np.full(5, 2))
    checks.append('0秒対照は更新確認を明示して省く')
    source, entry = material(.2)
    source['markets']['NK225']['current']['valid'][2] = False
    actual = functions['state'](source, entry, config)
    assert np.array_equal(actual['mode'], np.zeros(5))
    checks.append('欠測を挟むと10秒確認の時計を再開始する')

    # ----------------------------------------
    grid = np.array([300., 305., 310.])
    record = {'time_s': np.array([299., 300., 300., 305., 322.])}
    mapped = functions['mapping'](grid, record)
    assert np.array_equal(mapped, [-1, 0, -1, 1, -1])
    checks.append('格子は最初の自市場行へ一度だけ公開し10秒超過を使わない')
    answer = {'全合格': True, '検査数': len(checks), '検査': checks,
              '位置付け': '状態分類だけを人工検査。注文執行や損益の完全検証ではない。',
              '新条件損益計算': 0, '新条件損益閲覧': 0,
              'strategy_SHA256': hashlib.sha256((BASE / 'strategy.py').read_bytes()).hexdigest(),
              '検査コード_SHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = HERE / '状態境界の人工敵対検査.json'
    target.write_text(json.dumps(answer, ensure_ascii=False, indent=2), encoding='utf-8')
    return answer


if __name__ == '__main__':
    proof = run()
    print(f"状態境界の人工敵対検査 {proof['検査数']}件 全合格。新条件損益計算・閲覧なし")
