"""E01とR01の負け組を、既存台帳と当時の公開済み信号で分解する。"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import gzip
import json
from pathlib import Path
import pickle

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'wave_v67'
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """機能: 既存圧縮台帳を読み取る。

    引数: path(Path)。返り値: 台帳(dict)。
    """
    return json.loads(gzip.decompress(path.read_bytes()))


def save(path: Path, value: object) -> None:
    """機能: 今回診断内に有限JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')


def iso(stamp: float) -> str:
    """機能: 原本秒を日本時間で表示する。

    引数: stamp(float)。返り値: 日時(str)。
    """
    return datetime.fromtimestamp(stamp, JST).isoformat()


def first(indices: np.ndarray, clock: np.ndarray, entry: int) -> float | None:
    """機能: 初回条件成立までの経過分を返す。

    引数: indices/clock(ndarray)、entry(int)。返り値: 経過分(float)又は不成立(None)。
    """
    return float((clock[int(indices[0])] - clock[entry]) / 60) if len(indices) else None


def campaign(ledger: dict, cycle: list, ready: dict, signals: dict) -> dict:
    """機能: 一組の因果的な途中値と、診断専用の保有中最大値を記録する。

    引数: ledger/ready/signals(dict)、cycle(list)。返り値: 組診断(dict)。
    """
    cid, entry, exit_row = map(int, cycle[:3])
    trades = [t for t in ledger['trades'] if t['組'] == cid]
    assert trades and len({t['新規行'] for t in trades}) == 1
    d, anchor = trades[0]['方向'], trades[0]['建値']
    atr = float(cycle[5])
    clock, price = ready['time_s'], ready['last']
    rows = np.arange(entry, exit_row + 1)
    gain = d * (price[rows] - anchor) / atr
    mfe, mae = np.maximum.accumulate(np.maximum(gain, 0)), np.maximum.accumulate(np.maximum(-gain, 0))
    state = signals['entry']
    bad = signals['B00']
    raw_bad = (bad['direction'][rows] == -d) & (bad['source_row'][rows] > entry)
    raw_bad &= bad['source_row'][rows] <= rows
    elapsed = (clock[rows] - clock[entry]) / 60
    result = dict(セッション=ledger['session'], 銘柄=ledger['symbol'], 組=cid,
        方向=d, 新規時刻=iso(float(clock[entry])), 返済時刻=iso(float(clock[exit_row])),
        新規行=entry, 返済行=exit_row, 保有分=float(elapsed[-1]), 初回ATR=atr,
        枚数=int(sum(t['枚数'] for t in trades)),
        損益=float(sum(t['収支'] for t in trades)), 総損益=float(sum(t['利益損失前'] for t in trades)),
        手数料=float(sum(t['手数料'] for t in trades)), 返済理由=int(cycle[9]),
        最大順行ATR=float(mfe[-1]), 最大逆行ATR=float(mae[-1]),
        返済時順行ATR=float(gain[-1]),
        初回逆方向状態分=first(rows[state[rows] == -d], clock, entry),
        初回状態不一致分=first(rows[state[rows] != d], clock, entry),
        初回新公開逆行分=first(rows[raw_bad], clock, entry),
        初回弱い逆行根拠分=first(rows[raw_bad & (gain < 0) & (mfe < .5) & (elapsed >= 5)], clock, entry),
        初回05ATR順行分=first(rows[gain >= .5], clock, entry),
        初回05ATR逆行分=first(rows[gain <= -.5], clock, entry),
        初回15ATR順行分=first(rows[gain >= 1.5], clock, entry),
        部分返済回数=len(trades),
        悪化減量回数=sum(t['理由'] == 30 for t in trades),
        途中=[])
    # ----------------------------------------
    # 各時点では、その時点以前の最後の原本行とそれ以前の最大値だけを使う。
    for minutes in (3, 5, 10, 15, 30, 60):
        row = int(np.searchsorted(clock, clock[entry] + minutes * 60, side='right') - 1)
        if row < entry or row >= exit_row:
            result['途中'].append(dict(分=minutes, 生存=False))
            continue
        local = row - entry
        result['途中'].append(dict(分=minutes, 生存=True, 原本行=row,
            順行ATR=float(gain[local]), 過去最大順行ATR=float(mfe[local]), 過去最大逆行ATR=float(mae[local]),
            保持状態=int(state[row]), 新公開逆行=bool(raw_bad[local])))
    return result


def brief(records: list) -> dict:
    """機能: 組診断を利益と損失に分け、仮説に必要な分布をまとめる。

    引数: records(list[dict])。返り値: 分布(dict)。
    """
    output = {}
    for label, group in (('全組', records), ('利益組', [r for r in records if r['損益'] > 0]),
        ('損失組', [r for r in records if r['損益'] < 0])):
        nets = np.asarray([r['損益'] for r in group], float)
        value = dict(組数=len(group), 利益=float(nets[nets > 0].sum()), 損失=float(-nets[nets < 0].sum()),
            収支=float(nets.sum()), 保有中央値分=float(np.median([r['保有分'] for r in group])) if group else None,
            順行中央値ATR=float(np.median([r['最大順行ATR'] for r in group])) if group else None,
            最大順行05ATR未満=sum(r['最大順行ATR'] < .5 for r in group),
            最大順行1ATR未満=sum(r['最大順行ATR'] < 1 for r in group),
            最大順行15ATR未満=sum(r['最大順行ATR'] < 1.5 for r in group),
            最大順行2ATR以上=sum(r['最大順行ATR'] >= 2 for r in group),
            悪化減量あり=sum(r['悪化減量回数'] > 0 for r in group),
            同場直前損失=sum(r.get('直前組損失', False) for r in group),
            同方向直前損失=sum(r.get('同方向直前組損失', False) for r in group),
            二連敗後=sum(r.get('同場連敗数', 0) >= 2 for r in group),
            最大単組損失=float(-nets.min(initial=0)),
            返済理由={str(reason):sum(r['返済理由'] == reason for r in group) for reason in (1,2,7,8,9,30,32)},
            途中={})
        for minutes in (3, 5, 10, 15, 30, 60):
            alive = [(r, next(v for v in r['途中'] if v['分'] == minutes)) for r in group]
            alive = [(r,v) for r,v in alive if v['生存']]
            weak = [(r,v) for r,v in alive if v['過去最大順行ATR'] < .5]
            value['途中'][str(minutes)] = dict(生存組数=len(alive), 最大順行05ATR未満=len(weak),
                弱く含み損=sum(v['順行ATR'] < 0 for _,v in weak),
                含み損=sum(v['順行ATR'] < 0 for _,v in alive),
                状態不一致=sum(v['保持状態'] != r['方向'] for r,v in alive),
                新公開逆行=sum(v['新公開逆行'] for _,v in alive),
                分前に返済=sum(r['保有分'] <= minutes for r in group),
                分前に新公開逆行=sum(r['初回新公開逆行分'] is not None and r['初回新公開逆行分'] <= minutes for r in group))
        output[label] = value
    return output


def main() -> None:
    """機能: 過去台帳を変えず、全28場の原因診断を生成する。

    引数: なし。返り値: なし(None)。
    """
    ledgers = {code:{(l['session'],l['symbol']):l for l in read(SOURCE / f'observed/{code}.json.gz')['ledgers']}
        for code in ('E01','R01')}
    fixed = json.loads((SOURCE / '事前固定.json').read_text(encoding='utf8'))
    records = defaultdict(list)
    for folder in sorted((SOURCE / 'prepared').iterdir()):
        if not (folder / 'new_inputs.pkl').exists():
            continue
        inputs = pickle.loads((folder / 'new_inputs.pkl').read_bytes())
        signals = pickle.loads((folder / 'signals.pkl').read_bytes())
        for key,ready in sorted(inputs.items()):
            current = {name:signals[name][key] for name in ('entry','B00')}
            for code in ('E01','R01'):
                ledger = ledgers[code][key]
                previous, streak, by_direction = None, 0, {}
                for cycle in ledger['cycles']:
                    value = campaign(ledger, cycle, ready, current)
                    value['直前組損失'] = bool(previous is not None and previous['損益'] < 0)
                    value['同方向直前組損失'] = bool(by_direction.get(value['方向'], 0) < 0)
                    value['同場連敗数'] = streak
                    records[code].append(value)
                    streak = streak + 1 if value['損益'] < 0 else 0
                    previous = value
                    by_direction[value['方向']] = value['損益']
        del inputs,signals
    # ----------------------------------------
    # 結果による入口削除や改修選択はせず、前16と後12の診断を同じ形式で保存する。
    aggregate = {}
    for code, values in records.items():
        aggregate[code] = {period:{symbol:brief([r for r in values if r['セッション'] in names and r['銘柄'] == symbol])
            for symbol in ('TOPIX','NK225')} for period,names in (
                ('前16',fixed['前16']),('後12',fixed['後12']),('全28',fixed['全セッション']))}
        save(HERE / f'{code}_組別診断.json',values)
    save(HERE / '損失機序の集計.json', aggregate)
    print('E01/R01の全組診断完了', {code:len(values) for code,values in records.items()}, flush=True)


if __name__ == '__main__':
    main()
