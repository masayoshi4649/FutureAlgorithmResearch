"""今回の代表11方式の時間区間監査とE01赤字時間帯比較を再実行する。"""
import json
from pathlib import Path
import sys

import check_boundaries
import compare_windows
import replay_intervals


def main() -> None:
    """機能: 今回代表方式の台帳を選び、共通逐次会計を実行する。

    引数: なし。返り値: なし(None)。現在APIは使わない。
    """
    base = Path(__file__).resolve().parent.parent
    selected = json.loads((base / 'combined/結果.json').read_text(encoding='utf8'))['選択']['id']
    names = [('clock_search', n) for n in ('K20', 'K04', 'K24')]
    names += [('search', 'R04_W30_C0_X2'), ('rearm', 'A04_D000_T30')]
    names += [('order_methods', n) for n in ('O01_P025_C30_T120_X0', 'O02_P000_C30_T60_X1', 'O03_P000_C05_T60_X0')]
    names += [('combined', selected)]
    sys.argv = [str(Path(__file__))]
    for folder, name in names:
        sys.argv.extend(['--include', name + '=' + str(base / folder / 'ledgers' / (name + '.json.gz'))])
    check_boundaries.main()
    replay_intervals.main()
    compare_windows.main()


if __name__ == '__main__':
    main()
