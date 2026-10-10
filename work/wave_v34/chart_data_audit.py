"""HTMLの全売買と、原本から独立計算した5分asofのATR・価格線を照合する。"""

from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import pickle

import numpy as np

import chart_report as chart


class Extractor(HTMLParser):
    """機能: HTMLの図データとローカルリンクを取り出す。

    引数: feed(str)でHTMLを指定。返り値: data/links属性 (str/list[str])。
    """

    def __init__(self) -> None:
        """機能: 収集先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__()
        self.data, self.active, self.links, self.ids = '', False, [], set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 図データ開始・要素ID・リンクを抽出する。

        引数: tag (str)、attrs (list)。返り値: なし (None)。
        """
        values = dict(attrs)
        if values.get('id'):
            assert values['id'] not in self.ids
            self.ids.add(values['id'])
        if tag == 'script' and values.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: 図データの終端を検出する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script':
            self.active = False

    def handle_data(self, value: str) -> None:
        """機能: 図データ内のJSON文字列を保存する。

        引数: value (str)。返り値: なし (None)。
        """
        if self.active:
            self.data += value


def independent_lines(ready: dict, ledger: dict, dynamic: bool) -> dict:
    """機能: 組の建値・全返済・原本価格ATRから固定予算と累積追跡線を別式で計算する。

    引数: ready/ledger (dict)、dynamic (bool)。返り値: 組番号ごとの価格線等 (dict)。
    本番エンジン・atr_curveの値を使用しない。
    """
    prices, atr, tick = ready['last'], ready['atr'], ready['tick']
    trades = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
    result = {}
    for cycle in np.asarray(ledger['cycles'], dtype=float).reshape(-1, 10):
        campaign, begin, end = map(int, cycle[:3])
        selected = trades[trades[:, 0] == campaign]
        anchor, direction, a0, risk = selected[0, 4], int(cycle[8]), cycle[5], cycle[4]
        n = end - begin
        history = atr[begin:end]
        pointers = np.maximum.accumulate(np.where(np.isfinite(history) & (history > 0), np.arange(n), -1))
        at = np.full(n, a0)
        valid = pointers >= 0
        at[valid] = np.maximum(history[pointers[valid]], tick * 2)
        extreme = (np.maximum.accumulate(np.r_[anchor, prices[begin:end]]) if direction > 0
                   else np.minimum.accumulate(np.r_[anchor, prices[begin:end]]))[1:]
        width_atr = at if dynamic else np.full(n, a0)
        proposed = extreme - direction * 3 * width_atr
        if direction > 0:
            proposed = np.floor(proposed / tick + 1e-9) * tick
            proposed[direction * (extreme - anchor) < 1.5 * a0] = -np.inf
            trail = np.maximum.accumulate(proposed)
        else:
            proposed = np.ceil(proposed / tick - 1e-9) * tick
            proposed[direction * (extreme - anchor) < 1.5 * a0] = np.inf
            trail = np.minimum.accumulate(proposed)
        gains, closed = np.zeros(n), np.zeros(n)
        for trade in selected:
            index = int(trade[7]) - begin
            if index < n:
                gains[index] += trade[2] * trade[3] * (trade[5] - trade[4])
                closed[index] += trade[3]
        quantities = ledger['config']['initial_qty'] - np.cumsum(closed)
        stop = anchor + direction * (-risk - np.cumsum(gains)) / quantities
        stop = np.floor(stop / tick + 1e-9) * tick if direction > 0 else np.ceil(stop / tick - 1e-9) * tick
        result[campaign] = {'begin': begin, 'end': end, 'direction': direction, 'A0': a0, 'At': at,
                            'used_atr': width_atr, 'stop': stop, 'trail': trail}
    return result


def main() -> None:
    """機能: 全78図の売買・asof参照・独立計算したATRと価格線・リンクを確認する。

    引数: なし。返り値: なし (None)。注文器の追加再生は行わない。
    """
    chart.wave_order_audit.deny_network()
    path = chart.OUT / '５分足と売買.html'
    parser = Extractor()
    parser.feed(path.read_text(encoding='utf-8'))
    payload = json.loads(parser.data)
    frozen = chart.runner.read(chart.HERE / 'chart_fixed.json')
    details = chart.runner.read(chart.HERE / 'chart_details.json.gz')
    inputs = pickle.loads((chart.HERE.parent / 'wave_v23/inputs.pkl').read_bytes())
    assert sorted(payload['methods']) == frozen['手法']
    ledgers = {identifier: {(row['session'], row['symbol']): row for row in chart.runner.read(chart.HERE / 'ledgers' / (identifier + '.json.gz'))}
               for identifier in frozen['手法']}
    assert payload['preparation_columns'] == frozen['PREPARATION_COLUMNS']
    count = samples = entries = exits = shadow_count = actual_count = 0
    for row in details['図']:
        identifier, key = row['method'], (row['session'], row['symbol'])
        plotkey = identifier + '|' + key[0] + '|' + key[1]
        records = payload['trades'][plotkey]
        assert len(records) == len(row['全返済'])
        for actual, expected in zip(records, row['全返済']):
            np.testing.assert_array_equal(actual[:7], [datetime.fromisoformat(expected['新規時刻']).timestamp(), datetime.fromisoformat(expected['返済時刻']).timestamp(),
                expected['direction'], expected['枚数'], expected['新規価格'], expected['返済価格'], expected['損益円']])
            assert actual[7] == chart.runner.engine.REASONS[expected['返済理由番号']]
            assert actual[9:] == [expected['新規行'], expected['返済行']]
        orders = np.asarray(row['全注文'], dtype=float).reshape(-1, 8)
        assert set(orders[orders[:, 7] == 1, 0].astype(int)) == {value[9] for value in records}
        assert len(orders[orders[:, 7] == 0]) == len(records)
        ready = inputs[key]
        ledger = ledgers[identifier][key]
        lines = independent_lines(ready, ledger, '__AT__' in identifier)
        assert payload['preparations'][plotkey] == row['準備']
        shadow_prepared = {int(event[1]): event for event in ledger['shadow']['prepare_events']}
        actual_prepared = {int(event[1]): event for event in ledger['prepare_events']}
        shared = {number for number in shadow_prepared.keys() & actual_prepared.keys()
                  if np.array_equal(shadow_prepared[number][1:], actual_prepared[number][1:])}
        for label, source in (('shadow', ledger['shadow']), ('actual', ledger)):
            shown = payload['preparations'][plotkey][label]
            assert len(shown) == len(source['prepare_events'])
            fills = {int(event[2]): int(event[1]) for event in source['entry_preparations']}
            for marker, original in zip(shown, source['prepare_events']):
                local, number, side = map(int, original[:3])
                filled = fills.get(local, -1)
                np.testing.assert_array_equal(marker[:8], [ready['time_s'][number], number, local, side,
                    original[3], original[4], original[5], original[6]])
                assert marker[8] is (number in shared)
                assert marker[9] == (int(shadow_prepared[number][0]) if number in shared or label == 'shadow' else -1)
                assert marker[10] == filled
                assert marker[11] == (float(ready['time_s'][filled]) if filled >= 0 else None)
                if filled >= 0:
                    assert filled > number
            if label == 'shadow':
                shadow_count += len(shown)
            else:
                actual_count += len(shown)
                if '__SHADOW__' in identifier:
                    assert all(marker[8] for marker in shown)
        assert payload['tracking'][plotkey] == row['asof']
        pointer = -1
        for value in row['asof']:
            stamp, reference, campaign, side = value[:4]
            while pointer + 1 < len(ready['time_s']) and ready['time_s'][pointer + 1] <= stamp:
                pointer += 1
            assert reference == pointer
            if side:
                actual = lines[campaign]
                assert actual['begin'] <= pointer < actual['end'] and side == actual['direction']
                offset = pointer - actual['begin']
                expected = [actual['A0'], actual['At'][offset], actual['used_atr'][offset], actual['stop'][offset], actual['trail'][offset]]
                for observed, target in zip(value[4:], expected):
                    if np.isfinite(target):
                        np.testing.assert_allclose(observed, target, atol=1e-7, rtol=0)
                    else:
                        assert observed is None
            else:
                assert value[4:] == [None] * 5
            samples += 1
        count += 1
        entries += int(np.count_nonzero(orders[:, 7] == 1))
        exits += len(records)
    assert count == len(payload['tracking']) == len(payload['trades']) == len(payload['preparations']) == 78
    for href in parser.links:
        assert not href.startswith(('http:', 'https:'))
        target = href.split('#', 1)[0]
        assert not target or (path.parent / target).exists(), href
    chart.runner.save(chart.HERE / 'chart_data_audit.json', {'全図示数': count, '全新規件数': entries, '全返済件数': exits,
        '原本asof標本数': samples, '全返済一致': True, '全新規一致': True, '原本asof列一致': True,
        'ATR価格線の別式計算一致': True, '全仮想準備件数': shadow_count, '全実準備件数': actual_count,
        '全仮想準備一致': True, '全実準備一致': True, '全準備起点一致': True,
        'ローカルリンク全有効': True, 'API取得数': 0, '現在保存物使用': False,
        'HTML_SHA256': chart.runner.digest(path), '固定SHA256': chart.runner.digest(chart.HERE / 'chart_fixed.json')})
    print('全78図の売買と原本asof、ATRと価格線の別式計算が一致。', flush=True)


if __name__ == '__main__':
    main()
