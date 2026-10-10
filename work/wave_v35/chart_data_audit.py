"""104表示参照と固有図の売買・原本asof・条件付き追跡線を注文器なしで検算する。"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import pickle

import numpy as np

import chart_report as chart


class Extractor(HTMLParser):
    """機能: 埋込みJSONとリンク・IDを収集する。

    引数: feed(str)へHTML全文。返り値: data/links/ids属性 (str/list/set)。
    """
    def __init__(self) -> None:
        """機能: 検査対象の保持先を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__(); self.data = ''; self.active = False; self.links = []; self.ids = set()

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 重複IDを拒否し、図JSONとローカルリンクを抽出する。

        引数: tag (str)、attrs (list)。返り値: なし (None)。
        """
        values = dict(attrs)
        if values.get('id'):
            assert values['id'] not in self.ids; self.ids.add(values['id'])
        if tag == 'script' and values.get('id') == 'chart-data':
            self.active = True
        if tag == 'a' and values.get('href'):
            self.links.append(values['href'])

    def handle_endtag(self, tag: str) -> None:
        """機能: JSON範囲の終端を認識する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag == 'script': self.active = False

    def handle_data(self, data: str) -> None:
        """機能: 図JSONの本文だけを追加する。

        引数: data (str)。返り値: なし (None)。
        """
        if self.active: self.data += data


def independent_lines(ready: dict, ledger: dict, mode: int, bad: np.ndarray, sources: np.ndarray) -> tuple:
    """機能: 原価格・公開ATR・悪化列と全返済から候補・累積線・進行イベントを別式で復元する。

    引数: ready/ledger (dict)、mode (int)、bad/sources (ndarray)。
    返り値: 組別の配列と全進行イベント (tuple[dict,list])。注文器や保存曲線は使わない。
    """
    prices, atr, tick = ready['last'], ready['atr'], ready['tick']
    trades = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
    output, events = {}, []
    for cycle in np.asarray(ledger['cycles'], dtype=float).reshape(-1, 10):
        campaign, begin, end = map(int, cycle[:3]); side = int(cycle[8]); a0, risk = cycle[5], cycle[4]
        legs = trades[trades[:, 0] == campaign]; anchor = legs[0, 4]; n = end - begin
        local = np.arange(n); history = atr[begin:end]
        pointers = np.maximum.accumulate(np.where(np.isfinite(history) & (history > 0), local, -1))
        at = np.full(n, a0); valid = pointers >= 0
        at[valid] = np.maximum(history[pointers[valid]], 2 * tick)
        price = prices[begin:end]; finite = np.isfinite(price) & (price > 0)
        extrema = np.where(finite, price, -np.inf if side > 0 else np.inf)
        extreme = (np.maximum.accumulate(np.r_[anchor, extrema]) if side > 0 else np.minimum.accumulate(np.r_[anchor, extrema]))[1:]
        enabled = np.ones(n, dtype=bool) if mode == 1 else ((bad[begin:end] == -side) if mode == 2 else np.zeros(n, dtype=bool))
        used = np.where(enabled, np.minimum(a0, at), a0)
        fixed = extreme - side * 3 * a0; extra = extreme - side * 3 * used
        if side > 0:
            fixed = np.floor(fixed / tick + 1e-9) * tick; extra = np.floor(extra / tick + 1e-9) * tick
        else:
            fixed = np.ceil(fixed / tick - 1e-9) * tick; extra = np.ceil(extra / tick - 1e-9) * tick
        active = finite & (side * (extreme - anchor) >= 1.5 * a0)
        fixed[~active] = np.nan
        proposed = np.where(active, extra, -np.inf if side > 0 else np.inf)
        trail = np.maximum.accumulate(proposed) if side > 0 else np.minimum.accumulate(proposed)
        previous = np.r_[-np.inf if side > 0 else np.inf, trail[:-1]]
        advanced = active & (side * (proposed - previous) > 0)
        evidence = np.full(n, -1, dtype=np.int64); last_source = -1
        for offset in local:
            if advanced[offset]:
                row = begin + int(offset)
                kind = (2 if mode == 1 else 3) if side * (extra[offset] - fixed[offset]) > 0 else 1
                last_source = int(sources[row]) if kind == 3 else -1
                values = [row, campaign, side, previous[offset], fixed[offset],
                    extra[offset] if enabled[offset] else np.nan, trail[offset], kind, a0, at[offset], used[offset],
                    begin + int(pointers[offset]) if pointers[offset] >= 0 else -1,
                    row if kind == 3 else -1, last_source, int(bad[row]) if kind == 3 else 0]
                events.append([float(ready['time_s'][row]), *[float(v) if np.isfinite(v) else None for v in values]])
            evidence[offset] = last_source
        gains, closed = np.zeros(n), np.zeros(n)
        for trade in legs:
            offset = int(trade[7]) - begin
            if offset < n:
                gains[offset] += trade[2] * trade[3] * (trade[5] - trade[4]); closed[offset] += trade[3]
        quantity = ledger['config']['initial_qty'] - np.cumsum(closed)
        stop = anchor + side * (-risk - np.cumsum(gains)) / quantity
        stop = np.floor(stop / tick + 1e-9) * tick if side > 0 else np.ceil(stop / tick - 1e-9) * tick
        output[campaign] = {'begin': begin, 'end': end, 'direction': side, 'A0': a0, 'At': at,
            'used_atr': used, 'stop': stop, 'trail': trail, 'fixed_candidate': fixed,
            'bad_direction': bad[begin:end], 'evidence_source_row': evidence}
    return output, events


def main() -> None:
    """機能: 全表示枠の参照と固有図を、保存台帳・原価格による独立式へ照合する。

    引数: なし。返り値: なし (None)。売買再生を追加しない。
    """
    chart.wave_order_audit.deny_network()
    htmlpath = chart.OUT / '５分足と売買.html'; parser = Extractor(); parser.feed(htmlpath.read_text(encoding='utf-8'))
    payload = json.loads(parser.data); frozen = chart.freeze()
    assert payload['methods'] == chart.design.SLOTS and payload['trace_columns'] == chart.TRACE_COLUMNS
    assert payload['preparation_columns'] == chart.PREPARATION_COLUMNS
    selection = chart.runner.read(chart.HERE / '選択固定.json')['選択']['selected_exit_mode_id']
    assert payload['selected_mode'] == selection
    inputs = pickle.loads((chart.HERE.parent / 'wave_v23/inputs.pkl').read_bytes()); chart.runner.input_api.initialize(inputs)
    expected_views = {slot + '|' + session + '|' + symbol: chart.design.source_method(slot, session, selection) + '|' + session + '|' + symbol
                      for slot in chart.design.SLOTS for session, symbol in inputs}
    assert len(expected_views) == 104 and payload['views'] == expected_views
    assert set(payload['cases']) == set(expected_views.values())
    count = 78 if selection.startswith('B') else 52
    assert len(payload['cases']) == count
    details = chart.runner.read(chart.HERE / 'chart_details.json.gz')
    assert details['表示参照'] == expected_views and len(details['図']) == count
    assert details['選択固定SHA256'] == chart.runner.digest(chart.HERE / '選択固定.json')
    methods = {k.split('|')[0] for k in payload['cases']}
    ledgers = {name: {(r['session'], r['symbol']): r for r in chart.runner.read(chart.HERE / 'ledgers' / (name + '.json.gz'))} for name in methods}
    specs = {r['id']: r for r in chart.runner.read(chart.HERE / '探索条件の固定.json')['conditions']}
    entries = exits = samples = prepares = progresses = 0
    for detail in details['図']:
        plotkey = detail['key']; shown = payload['cases'][plotkey]
        assert shown == {name: detail[name] for name in shown}
        name, session, symbol = plotkey.split('|'); key = session, symbol
        ready, ledger = inputs[key], ledgers[name][key]
        raw = np.asarray(ledger['trades'], dtype=float).reshape(-1, 11)
        orders = np.asarray(ledger['orders'], dtype=float).reshape(-1, 8)
        assert detail['全注文'] == ledger['orders'] and len(raw) == len(shown['trades'])
        for actual, trade in zip(shown['trades'], raw):
            begin, end = int(trade[6]), int(trade[7])
            expected = [ready['time_s'][begin], ready['time_s'][end], trade[2], trade[3], trade[4], trade[5],
                        trade[2] * trade[3] * (trade[5] - trade[4]) * ledger['config']['point_value']]
            np.testing.assert_allclose(actual[:7], expected, atol=1e-6, rtol=0)
            assert actual[7] == chart.runner.engine.REASONS[int(trade[9])] and actual[9:] == [begin, end]
        assert {int(row[0]) for row in orders if row[7] == 1} == {int(t[9]) for t in shown['trades']}
        assert np.isclose(sum(t[6] for t in shown['trades']), shown['net_yen'], atol=1e-6, rtol=0)
        state, bad, sources = chart.runner.columns(specs[name], key, ready)
        lines, events = independent_lines(ready, ledger, specs[name]['width_mode'], bad, sources)
        actual_events = np.array([[np.nan if v is None else v for v in row] for row in shown['events']], dtype=float).reshape(-1, 16)
        expected_events = np.array([[np.nan if v is None else v for v in row] for row in events], dtype=float).reshape(-1, 16)
        np.testing.assert_allclose(actual_events, expected_events, atol=1e-7, rtol=0, equal_nan=True)
        assert len(events) == len(ledger['trail_events'])
        extra = sum(e[8] >= 2 for e in events)
        assert extra == shown['control']['additional_advance_events']
        for label, source in (('shadow', ledger['shadow']), ('actual', ledger)):
            markers = shown['preparations'][label]; assert len(markers) == len(source['prepare_events'])
            links = {int(r[2]): int(r[1]) for r in source['entry_preparations']}
            for marker, event in zip(markers, source['prepare_events']):
                identity, row, side = map(int, event[:3]); filled = links.get(identity, -1)
                np.testing.assert_array_equal(marker[:8], [ready['time_s'][row], row, identity, side, *event[3:]])
                assert marker[8:11] == [True, identity, filled]
                assert marker[11] == (float(ready['time_s'][filled]) if filled >= 0 else None)
                if filled >= 0: assert filled > row
        assert shown['preparations']['shadow'] == shown['preparations']['actual']
        pointer = -1
        for sample in shown['tracking']:
            stamp, ref, campaign, side = sample[:4]
            while pointer + 1 < len(ready['time_s']) and ready['time_s'][pointer + 1] <= stamp:
                pointer += 1
            assert ref == pointer
            if side:
                line = lines[campaign]; offset = pointer - line['begin']
                assert line['begin'] <= pointer < line['end'] and side == line['direction']
                values = [line['A0'], line['At'][offset], line['used_atr'][offset], line['stop'][offset],
                          line['trail'][offset], line['fixed_candidate'][offset], line['bad_direction'][offset],
                          line['evidence_source_row'][offset]]
                expected = [float(v) if np.isfinite(v) else None for v in values]
                np.testing.assert_allclose(np.array(sample[4:], dtype=float), np.array(expected, dtype=float),
                                           atol=1e-7, rtol=0, equal_nan=True)
            else:
                assert sample[4:] == [None] * 8
            samples += 1
        entries += sum(row[7] == 1 for row in orders); exits += len(raw)
        prepares += len(shown['preparations']['actual']); progresses += len(events)
    for link in parser.links:
        assert not link.startswith(('http:', 'https:', '//'))
        if link.startswith('#'): assert link[1:] in parser.ids
        else: assert (chart.OUT / link.split('#')[0]).exists(), link
    assert chart.freeze() == frozen
    chart.runner.save(chart.HERE / 'chart_data_audit.json', {'全図示数': 104, '固有再生数': count,
        '表示参照全一致': True, '全返済一致': True, '全新規一致': True, '全仮想準備一致': True,
        '全実準備一致': True, '全準備起点一致': True, '原本asof列一致': True,
        'ATR価格線の別式計算一致': True, '全追跡根拠一致': True, 'ローカルリンク全有効': True,
        '固有新規件数': int(entries), '固有返済件数': exits, '原本asof標本数': samples,
        '固有準備件数': prepares, '固有追跡進行件数': progresses,
        '固定SHA256': chart.runner.digest(chart.HERE / 'chart_fixed.json'), 'HTML_SHA256': chart.runner.digest(htmlpath),
        'API取得数': 0, '現在保存物使用': False, '追加売買再生': False})
    print('104表示と固有', count, '図の売買・ATR・固定候補・有利側累積線が一致。', flush=True)


if __name__ == '__main__':
    main()
