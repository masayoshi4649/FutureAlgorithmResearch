"""新正式損益を開かず、読取門番と会計差の人工反証だけを行う。"""

import ast
import hashlib
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.dont_write_bytecode = True
import 共通独立読取 as R
import 元候補対応と独立会計分解 as P


def toy(origin: int, entry: float, exit_price: float, side: int = 1, quantity: int = 8,
        fee: float = 334., decision: int | None = None) -> dict:
    """
    機能: 売買エンジンと無関係な、元候補と実発注を分けた人工親を作る。
    引数: origin/side/quantity(int)、entry/exit_price/fee(float)、decision(int|None)。
    返り値: dict。料金差例は純代数境界であり正式料金設定の変更ではない。
    """
    trade = np.zeros(16, float)
    trade[0] = origin; trade[1] = 0; trade[2] = origin + 1; trade[3] = origin + 2
    trade[4] = side; trade[5] = quantity; trade[6] = entry; trade[7] = exit_price
    trade[8] = fee; trade[9] = fee
    trade[10] = side * (exit_price - entry) * quantity * 1000.
    trade[11] = trade[10] - 2. * fee
    trade[15] = origin if decision is None else decision
    entry_d = dict(candidate_row=origin, candidate_seq=origin + 100, candidate_time=1000. + origin,
        candidate_quote=100., trigger_time=1000. + origin, trigger_quote=entry,
        fill_time=1001. + origin, kind=7, width=5., phase_row=origin,
        favorable_peak=103., opposite_extreme=101., fallback_used=0)
    return dict(trade=trade, entry=entry_d)


def main() -> None:
    """
    機能: 構文、未許可の正式結果読取拒否、独立恒等式の必要境界を人工確認する。
    引数: なし。正式結果の許可フラグを受け付けず、新97損益を読まない。
    返り値: None。自担当review内だけへ証跡を保存する。
    """
    assert not R.AUTHORIZED
    files = list(R.HERE.glob('*.py'))
    for path in files:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    old = {('例', 'TOPIX'): {1: toy(1, 100., 110.), 2: toy(2, 100., 105., -1),
        3: toy(3, 100., 112.), 4: toy(4, 100., 99.)}}
    new = {('例', 'TOPIX'): {1: toy(1, 101., 110., decision=20),
        2: toy(2, 102., 101., -1), 5: toy(5, 100., 98.)}}
    value = P.decompose(old, new, 'TOPIX', ['例'], True)
    assert value['同候補親'] == 2 and value['有利建値親'] == 1 and value['不利建値親'] == 1
    assert value['建値改善円'] == 8000. and value['返済差円'] == 32000.
    assert value['逃した元固有利益円'] == 95332. and value['避けた元固有損失円'] == 8668.
    assert value['新固有損失円'] == 16668.
    assert value['全経路差円'] == value['同候補収支差円'] - value['元固有収支円'] + value['新固有収支円']
    first = {('例', 'TOPIX'): {1: toy(1, 100., 110.)}}
    second = {('例', 'TOPIX'): {1: toy(1, 100., 108.)}}
    exit_only = P.decompose(first, second, 'TOPIX', ['例'], True)
    assert exit_only['厳密同一実新規親'] == 1 and exit_only['厳密同一実新規管理差円'] == -16000.
    changed_fee = {('例', 'TOPIX'): {1: toy(1, 100., 110., fee=350.)}}
    fee_only = P.decompose(first, changed_fee, 'TOPIX', ['例'], True)
    assert fee_only['料金差円'] == -32. and fee_only['同候補収支差円'] == -32.
    try:
        R.read(R.WORK / 'analysis/比較結果.json')
    except AssertionError:
        gate = True
    else:
        raise AssertionError('未許可で正式結果を読み得ました')
    clis = ['全36親会計と安定性の独立照合.py',
        '待機の同候補建値差と勝ち刈り及び固有経路の独立分解.py',
        '最悪3場の待機原板と救済及び勝ち刈りの独立反証.py']
    for name in clis:
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(R.HERE / name)],
            capture_output=True, text=True, encoding='utf-8')
        assert result.returncode != 0 and '根の全31正式完了許可が必要' in result.stderr, (name, result.stdout, result.stderr)
    R.save('正式後3CLIの準備と許可門番及び独立恒等式の人工確認.json', dict(
        全合格=True, 状態='コード準備のみ・正式97損益未読', 正式結果閲覧=0,
        正式策略再生=0, API取得=0, 実注文=0, 構文検査=len(files), 根未許可直接読取拒否=gate,
        根未許可CLI停止=clis, 人工反証={'元候補と発注行を別鍵とする': True, 'longshort建値差': True,
            '旧固有勝負と新固有を全経路へ含める': True, '厳密同一実新規管理差': True, '料金差を省略しない': True},
        人工同候補差=value, 人工純出口差=exit_only, 人工料金差=fee_only,
        コードSHA256={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}))
    print('新reviewの構文・未許可3CLI停止・独立会計恒等式を人工だけで確認。正式損益未読。', flush=True)


if __name__ == '__main__':
    main()
