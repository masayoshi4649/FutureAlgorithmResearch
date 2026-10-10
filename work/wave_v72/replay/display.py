"""追加一場の台帳と五分足を、旧レポートと同じ図解用JSONへ接続する。"""

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ID = 'T1L1_R01'


def digest(path: Path) -> str:
    """機能: 表示に使う資料と出力の内容指紋を計算する。

    引数: path(Path)。
    返り値: SHA256の16進表記(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 追加台帳九列に約定時計を添付し、五分足と共に保存する。

    引数: なし。
    返り値: なし(None)。原本CSVへの書込み、新しいCSV生成、API取得は行わない。
    """
    source = HERE / (ID + '_追加台帳.pkl')
    input_path = ROOT / 'work/wave_v71/prepared/extra_inputs.pkl'
    ledger = pickle.loads(source.read_bytes())
    ready = pickle.loads(input_path.read_bytes())
    target = HERE / (ID + '_追加表示データ.json')
    assert not target.exists(), '既存の表示資料は上書きしない'
    orders, bars, fingerprints = {}, {}, {}
    for key, account in sorted(ledger.items()):
        name = '|'.join(key)
        orders[name] = [list(o) + [float(ready[key]['time_s'][int(o[0])])] for o in account['orders']]
        path = ROOT / 'candle_5min' / key[1] / (key[0] + '.csv')
        with path.open(encoding='utf-8-sig', newline='') as stream:
            bars[name] = [[datetime.fromisoformat(r['time']).timestamp(),
                          *[float(r[field]) for field in ('open', 'high', 'low', 'close')]]
                         for r in csv.DictReader(stream)]
        fingerprints[str(path.relative_to(ROOT))] = digest(path)
        assert all(len(o) == 10 for o in orders[name])
        assert all(len(b) == 5 for b in bars[name])
    target.write_text(json.dumps(dict(orders=orders, bars=bars), ensure_ascii=False, allow_nan=False), encoding='utf8')
    proof = dict(合格=True, 対象=list(orders), 台帳SHA256=digest(source), 入力SHA256=digest(input_path),
                 五分足SHA256=fingerprints, 表示JSON_SHA256=digest(target),
                 注文形式='元台帳9列＋約定行CurrentPriceTimeのUNIX秒。旧公開レポートと同じ形式。',
                 五分足形式='原本timeのUNIX秒、open、high、low、close。', API取得=0, 実注文=0)
    (HERE / '追加表示データの照合.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf8')
    print('追加2口座の約定時刻付き注文と五分足を保存しました。', flush=True)


if __name__ == '__main__':
    main()
