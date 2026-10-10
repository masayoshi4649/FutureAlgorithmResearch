"""既知保存場で部分再生の同値性と途中切断の会計を独立に確認する。"""

from pathlib import Path
import pickle
import sys

import numpy as np

import partial_replay
import prepare_live


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
sys.path.insert(0, str(WORK.parent / 'wave_v65'))
import replay as reference


def main() -> None:
    """機能: 固定した分足主案6条件を旧全再生器と照合して途中切断を検査する。

    引数: なし。返り値: なし(None)。現在API・現在取得原本は参照しない。
    損益は条件の変更や選別には使用せず、実装同値性だけを判定する。
    """
    inputs = pickle.loads((WORK.parent / 'wave_v60/inputs.pkl').read_bytes())
    quotes = pickle.loads((WORK.parent / 'wave_v60/quotes.pkl').read_bytes())
    signals = pickle.loads((WORK / '入口候補.pkl').read_bytes())
    keys = [min(key for key in inputs if key[1] == symbol) for symbol in ('TOPIX', 'NK225')]
    checks = []
    for config in prepare_live.candidates()[:6]:
        for key in keys:
            ready, quote, candidates = inputs[key], quotes[key], signals[key][config['entry']]
            count = len(ready['seq']) // 2
            actual = partial_replay.simulate(ready, quote, candidates, config, count)
            expected, gates = reference.replay(ready, quote, candidates, config['exit_config'])
            assert len(actual['rows']) == len(expected)
            for left, right in zip(actual['rows'], expected):
                for name in ('entry_i', 'exit_i', 'exit_decision_i', 'entry_price', 'exit_price', 'gross', 'fees', 'net', 'reason'):
                    assert left[name] == right[name], (config['id'], key, name)
            for name, number in gates.items():
                assert actual['gates'][name] == number, (config['id'], key, name)
            clipped = dict(ready)
            for name in ('seq', 'time_s'):
                clipped[name] = ready[name][:count]
            clipped_quote = {name: value[:count] for name, value in quote.items()}
            prefix = partial_replay.simulate(clipped, clipped_quote, candidates[candidates[:, 0] < count], config, 0)
            assert prefix['現在末尾'] == actual['既知境界'], (config['id'], key, '途中切断で状態が変わっています')
            checks.append(dict(条件=config['id'], セッション=key[0], 銘柄=key[1],
                               次行約定同値=True, 途中切断不変=True, 合格=True))
    prepare_live.save('保存場との同値監査.json', dict(全合格=True, 件数=len(checks), 検査=checks,
        現在API取得=0, 現在取得原本参照=0, 結果で条件を変更しない=True))
    print('固定6条件×2銘柄で次行約定と途中切断の会計が一致しました。')


if __name__ == '__main__':
    main()
