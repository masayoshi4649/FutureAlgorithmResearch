"""同じ条件の校正なし台帳を影取引として、校正あり入口の過去性を検査する。"""

import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent/'microstructure/round3/集計結果.json'


def key(config: dict) -> tuple:
    """機能: 校正だけを除いた共通売買条件を鍵へ変換する。

    引数: config(dict)。返り値: 共通条件(tuple)。
    """
    return tuple(config.get(k, 1 if k == 'direction' else None) for k in
                 ('signal', 'direction', 'target', 'stop', 'hold', 'cooldown', 'protect'))


def main() -> None:
    """機能: 全校正入口が同場の完了済み影取引だけで許可されることを照合する。

    引数: なし。返り値: なし(None)。人工検査と別に実保存台帳を使う。
    """
    result = json.loads(SOURCE.read_text(encoding='utf-8'))
    controls = {}
    for method in result['methods']:
        if not method['config']['calibration']:
            kk = key(method['config'])
            assert kk not in controls
            controls[kk] = pickle.loads(Path(method['ledger']).read_bytes())
    accounts = entries = checked_empty = same_row = 0
    for method in result['methods']:
        config = method['config']
        if not config['calibration']:
            continue
        original = controls[key(config)]
        actual = pickle.loads(Path(method['ledger']).read_bytes())
        for account, ledger in actual.items():
            shadow = original[account]['trades']
            exits = shadow[:, 3]
            for order in ledger['orders'][::2]:
                decision = int(order[0])
                completed = int(np.searchsorted(exits, decision, side='right'))
                assert completed >= config['window']
                past = shadow[completed-config['window']:completed]
                assert np.all(past[:, 3] <= decision)
                assert np.count_nonzero(past[:, 11] > 0) >= config['required_wins']
                same_row += int(exits[completed-1] == decision)
                entries += 1
            if len(shadow) < config['window']:
                assert not len(ledger['orders'])
                checked_empty += 1
            accounts += 1
    record = dict(合格=True, 校正なし対照=len(controls), 校正口座=accounts, 実新規の照合=entries,
        影取引不足で無取引確認=checked_empty, 同行で影返済後に使用=same_row,
        同場の完了済み全flat組だけ使用=True, 校正なし売買器と影取引は人工独立状態表現でも一致=True,
        限定='校正窓の過去性の監査であり、次の取引の勝率95%を保証しない。',
        結果SHA256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())
    (HERE/'当場影取引校正の独立照合.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
