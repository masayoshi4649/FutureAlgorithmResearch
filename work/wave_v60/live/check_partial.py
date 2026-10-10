"""途中会計の合成検査。入口はテスト内だけで固定し、実相場・API・売買規則を変更しない。"""

import json
from pathlib import Path

import numpy as np

import medium_replay as replay


HERE = Path(__file__).resolve().parent


def example(size: int) -> tuple[dict, dict]:
    """機能: 一秒刻み・固定中値・スプレッド2の合成価格を作る。

    引数: size(int) は有効行数。
    返り値: 共通入力と気配(tuple[dict,dict])。
    """
    ready = {'session': '合成_Day', 'symbol': 'TOPIX', 'start': 0., 'limit': 7200., 'tick': 1.,
             'time_s': np.arange(size, dtype=float), 'seq': np.arange(size, dtype=np.int64)}
    quotes = {'time_s': ready['time_s'], 'seq': ready['seq'], 'bid': np.full(size, 99.),
              'ask': np.full(size, 101.), 'mid': np.full(size, 100.)}
    return ready, quotes


def forced_candidates(frame: object, opening: float, tick: float, fraction: float) -> dict:
    """機能: テストプロセス内だけで一回の入口を指定する。

    引数: frame(object)、opening/tick/fraction(float) は本物と同じ呼出契約。
    返り値: MT1入口のNx3配列を持つ辞書(dict)。本番ファイルには変更を加えない。
    """
    return {'MT1': np.asarray([[10., 1., 10.]])}


def main() -> None:
    """機能: 未決済の発生費用・含み、完結組、未実行判断を独立な期待値で照合する。

    引数: なし。
    返り値: なし(None)。ネットワークを使用せず合成証跡を保存する。
    """
    original = replay.signals.candidates
    replay.signals.candidates = forced_candidates
    config = next(value for value in replay.signals.methods() if value['id'] == 'MT1_P3_9_W10_X1_T30')
    checks = []
    try:
        ready, quotes = example(1000)
        opened = replay.partial_account(ready, quotes, config, True)
        assert opened['cycles'] == 0 and opened['position'] == 5
        assert opened['fees_incurred'] == opened['open_entry_fees'] == 209.
        assert opened['realized_gross_pnl'] == opened['closed_trade_net'] == 0.
        assert opened['unrealized_end'] == -10000. and opened['economic_net'] == -10209.
        checks.append('未決済玉を清算せず、入口料金209円と返済側含みを両方計上')
        middle = replay.partial_account(ready, quotes, config, False)
        assert middle['unrealized_end'] == 0. and middle['economic_net'] == -209.
        checks.append('中値参考も発生した入口費用を失わない')
        ready, quotes = example(2500)
        closed = replay.partial_account(ready, quotes, config, True)
        assert closed['cycles'] == 1 and closed['position'] == 0
        assert closed['fees_incurred'] == 418. and closed['open_entry_fees'] == 0.
        assert closed['economic_net'] == closed['closed_trade_net'] == -10418.
        checks.append('完結取引は入口返済両道費用と純損益が一致')
        ready, quotes = example(11)
        pending = replay.partial_account(ready, quotes, config, True)
        assert pending['position'] == 0 and pending['fees_incurred'] == 0.
        assert pending['未実行の新規判断数'] == 1
        checks.append('末尾で判断した未約定注文へ費用や建玉を先取りしない')
        ready, quotes = example(0)
        empty = replay.partial_account(ready, quotes, config, True)
        assert empty['economic_net'] == 0. and empty['position'] == 0
        checks.append('開始前の空データは準備待ちのまま')
    finally:
        replay.signals.candidates = original
    result = {'合格': True, '検査数': len(checks), '検査': checks, 'ネットワーク回数': 0,
              '本番候補と売買コード変更': False}
    (HERE / '途中会計の合成監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
