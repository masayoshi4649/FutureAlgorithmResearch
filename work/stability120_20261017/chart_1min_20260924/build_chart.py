"""保存済み一分足と完結玉を重ね、新しい売買計算を行わず表示する。"""

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転'
NAME = '2026-09-24_Dayの1分足と売買.html'
SOURCE = ROOT / 'work/stability120_20261017/session_20260924_day/表示用の全玉と同時約定集約.json'


def digest(path: Path) -> str:
    """
    機能: 読み取り元と公開物の保存内容を識別する。
    引数: path(Path)は存在するファイル。
    返り値: strはSHA256の十六進表記。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 当日二銘柄の一分足と保存済み全約定を自己完結HTMLへ埋め込む。
    引数: なし。ローカルCSV二本と既存表示JSONだけを使用する。
    返り値: None。金融再生・元板読み取り・実注文は行わない。
    """
    original = json.loads(SOURCE.read_text(encoding='utf-8'))
    data = {'session': original['session'], 'method': original['method'], 'symbols': {}}
    evidence = {'passed': True, 'financial_replay': 0, 'book_reads': 0, 'API': 0,
                'source': {'path': str(SOURCE.relative_to(ROOT)), 'sha256': digest(SOURCE)}, 'symbols': {}}
    for symbol in ('TOPIX', 'NK225'):
        saved = original['symbols'][symbol]
        path = ROOT / 'candle_1min' / symbol / '2026-09-24_Day.csv'
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
        candles = []
        for row in rows:
            stamp = datetime.fromisoformat(row['time'])
            assert stamp.strftime('%Y-%m-%d') == '2026-09-24'
            assert stamp.utcoffset().total_seconds() == 9 * 3600
            values = [float(row[key]) for key in ('open', 'high', 'low', 'close')]
            assert values[2] <= min(values[0], values[3]) <= max(values[0], values[3]) <= values[1]
            candles.append([stamp.timestamp(), *values, float(row['volume']), row['volume_complete'] == 'true'])
        assert all(b[0] > a[0] for a, b in zip(candles, candles[1:]))
        groups = saved['groups']
        events = []
        for lot in saved['lots']:
            events.append((lot['entry_row'], lot['entry_epoch'], lot['side'], 1))
            events.append((lot['exit_row'], lot['exit_epoch'], lot['side'], -1))
        events.sort()
        inventory = [[candles[0][0], 0, 0]]
        counts = {1: 0, -1: 0}
        for raw, stamp, side, delta in events:
            counts[side] += delta
            assert counts[side] >= 0
            inventory.append([stamp, counts[1], counts[-1]])
        assert counts == {1: 0, -1: 0}
        assert all(candles[0][0] <= r['entry_epoch'] < candles[-1][0] + 60 and
                   candles[0][0] <= r['exit_epoch'] < candles[-1][0] + 60 for r in groups)
        assert sum(r['quantity'] for r in groups) == saved['lot_count']
        assert sum(r['net'] for r in groups) == saved['expected']['net']
        data['symbols'][symbol] = {
            'label': 'TOPIX' if symbol == 'TOPIX' else '日経225',
            'product': saved['label'], 'unit': saved['unit'], 'candles': candles,
            'groups': groups, 'inventory': inventory, 'summary': saved['expected'],
            'lot_count': saved['lot_count'], 'group_count': len(groups),
        }
        evidence['symbols'][symbol] = {
            'csv': str(path.relative_to(ROOT)), 'sha256': digest(path), 'candles': len(candles),
            'first': rows[0]['time'], 'last': rows[-1]['time'],
            'closed_lots': saved['lot_count'], 'filled_orders': len(events),
            'grouped_markers': 2 * len(groups), 'net': saved['expected']['net'],
            'max_long': max(r[1] for r in inventory), 'max_short': max(r[2] for r in inventory),
        }
    template = (HERE / 'chart_template.html').read_text(encoding='utf-8')
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/')
    assert template.count('__CHART_DATA__') == 1
    target = PUBLIC / NAME
    target.write_bytes(template.replace('__CHART_DATA__', payload).encode('utf-8'))
    evidence['html'] = {'path': str(target.relative_to(ROOT)), 'sha256': digest(target)}
    (HERE / '生成と入力照合.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
