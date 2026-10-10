"""新候補の報告数値を保存台帳・生価格から独立集計して照合する。"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import gzip
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import pickle
import re

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'work/wave_v49/early'
REPORT = ROOT / 'アルゴリズム調査/00044_新候補2手法と基準の説明と損益'
IDS = ('E00', 'E01', 'E08')
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen',
          'profit_units', 'loss_units', 'zero_units')


def read(path: Path) -> object:
    """機能: 保存済みJSONを読み込む。

    引数: path(Path)。返り値: 保存値(object)。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def same(actual: float, expected: float, label: object) -> None:
    """機能: 数値を丸め誤差の範囲で比較する。

    引数: actual/expected(float)、label(object)。返り値: なし(None)。
    """
    assert abs(float(actual) - float(expected)) <= 1e-6, (label, actual, expected)


class TableReader(HTMLParser):
    """機能: HTML表の数値セルを属性と表示文字の両方で収集する。"""

    def __init__(self) -> None:
        """機能: 表と行の解析状態を初期化する。

        引数: なし。返り値: なし(None)。
        """
        super().__init__()
        self.table = {}
        self.row = {}
        self.cell = None
        self.records = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """機能: 表・行・数値セルの開始属性を保存する。

        引数: tag(str)、attrs(list)。返り値: なし(None)。
        """
        values = dict(attrs)
        if tag == 'table':
            self.table = values
        elif tag == 'tr':
            self.row = values
        elif tag == 'td' and 'data-value' in values:
            self.cell = dict(table=self.table.copy(), row=self.row.copy(),
                             attrs=values, text='')

    def handle_data(self, data: str) -> None:
        """機能: 数値セルの表示文字を収集する。

        引数: data(str)。返り値: なし(None)。
        """
        if self.cell is not None:
            self.cell['text'] += data

    def handle_endtag(self, tag: str) -> None:
        """機能: 数値セル終了時に検査対象へ追加する。

        引数: tag(str)。返り値: なし(None)。
        """
        if tag == 'td' and self.cell is not None:
            self.records.append(self.cell)
            self.cell = None
        elif tag == 'table':
            self.table = {}


def reconstruct(ledger: dict, ready: dict) -> tuple[dict, np.ndarray]:
    """機能: 約定価格・枚数から損益、原本全行から時価曲線を再計算する。

    引数: ledger/ready(dict)。返り値: 会計値と時価曲線(tuple[dict,ndarray])。
    """
    multiplier = 1000 if ledger['symbol'] == 'TOPIX' else 10
    cap = 10 if ledger['symbol'] == 'TOPIX' else 20
    initial = cap // 2
    trades = np.asarray(ledger['trades'], float).reshape((-1, 11))
    profits = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4])
    np.testing.assert_allclose(profits, trades[:, 10], rtol=0, atol=1e-8)
    wins, losses, flat = profits > 1e-8, profits < -1e-8, abs(profits) <= 1e-8
    result = dict(gross_profit_yen=float(profits[wins].sum() * multiplier),
                  gross_loss_yen=float(-profits[losses].sum() * multiplier),
                  net_yen=float(profits.sum() * multiplier),
                  profit_units=int(trades[wins, 3].sum()),
                  loss_units=int(trades[losses, 3].sum()),
                  zero_units=int(trades[flat, 3].sum()))
    orders = np.asarray(ledger['orders'], float).reshape((-1, 8))
    raw_price = np.asarray(ready['last'])
    raw_time = np.asarray(ready['time_s'])
    raw_seq = np.asarray(ready['seq'])
    assert np.isfinite(raw_price).all() and (raw_price > 0).all()
    assert (np.diff(raw_time) >= 0).all() and (np.diff(raw_seq) > 0).all()
    delta_cash = np.zeros(len(raw_price))
    delta_position = np.zeros(len(raw_price))
    opened, closed = Counter(), Counter()
    expected_open, expected_close = Counter(), Counter()
    for trade in trades:
        assert trade[2] in (-1, 1) and trade[3] >= 1 and trade[3] == int(trade[3])
        assert 0 <= trade[6] <= trade[7] < len(raw_price)
        expected_open[(int(trade[6]), trade[2], trade[4])] += trade[3]
        expected_close[(int(trade[7]), -trade[2], trade[5])] += trade[3]
    prior_fill = -1
    for order in orders:
        fill, source = int(order[0]), int(order[1])
        assert 0 <= source < fill < len(raw_price)
        assert fill >= prior_fill and order[4] >= 1 and order[4] == int(order[4])
        assert order[3] in (-1, 1) and order[7] in (0, 1)
        prior_fill = fill
        quantity = order[3] * order[4]
        delta_cash[fill] -= quantity * order[5]
        delta_position[fill] += quantity
        if order[7] == 1:
            opened[(fill, order[3], order[5])] += order[4]
            assert raw_time[fill] < ready['limit']
            if order[6] == 20:
                assert order[4] == initial
        else:
            closed[(fill, order[3], order[5])] += order[4]
    assert opened == expected_open and closed == expected_close
    cash = np.cumsum(delta_cash)
    position = np.cumsum(delta_position)
    curve = (cash + position * raw_price) * multiplier
    assert position[-1] == 0
    assert max(abs(position), default=0) <= initial <= cap
    same(curve[-1], result['net_yen'], '売買現金と決済損益')
    high = np.maximum.accumulate(np.maximum(curve, 0))
    result['drawdown_yen'] = float((high - curve).max(initial=0))
    result['max_long'] = int(position.max(initial=0))
    result['max_short'] = int((-position).max(initial=0))
    cycles = np.asarray(ledger['cycles'], float).reshape((-1, 10))
    same(cycles[:, 3].sum() * multiplier, result['net_yen'], '組合計')
    for cycle in cycles:
        group = trades[trades[:, 0] == cycle[0]]
        same(group[:, 10].sum(), cycle[3], '組内約定合計')
        same(group[:, 3].sum(), initial, '組の返済枚数')
    return result, curve


def aggregate(rows: list[dict]) -> dict:
    """機能: 独立計算済みの複数セッションを加算する。

    引数: rows(list[dict])。返り値: 利益・損失・収支・枚数(dict)。
    """
    result = {field: sum(row[field] for row in rows) for field in FIELDS}
    result['net_units'] = result['profit_units'] - result['loss_units']
    return result


def plain(source: str) -> str:
    """機能: HTML断片から表示文字だけを取り出す。

    引数: source(str)。返り値: 文字列(str)。
    """
    return unescape(re.sub('<[^>]*>', '', source)).strip()


def run() -> dict:
    """機能: 三方式の全口座・週・全期間とHTML表示を独立照合する。

    引数: なし。返り値: 検証記録(dict)。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    for update in ('update_20260930', 'update_20261001'):
        inputs.update(pickle.loads((ROOT / 'work/wave_v48' / update / 'new_inputs.pkl').read_bytes()))
    assert len(inputs) == 32
    registration = HERE / '追加結果一覧.json'
    registered = read(registration) if registration.exists() else []
    assert isinstance(registered, list) and len(set(registered)) == len(registered)
    updates = []
    update_keys = {}
    for name in registered:
        directory = (HERE / name).resolve()
        assert directory.parent == HERE.resolve(), ('追加フォルダ範囲', name)
        complete = read(directory / 'complete.json')
        assert complete['全合格'] and not complete['条件変更'] and complete['API追加取得数'] == 0
        new_inputs = pickle.loads((directory / 'new_inputs.pkl').read_bytes())
        assert not set(new_inputs).intersection(inputs), ('入力重複', name)
        inputs.update(new_inputs)
        updates.append((directory, complete))
        update_keys[directory] = set(new_inputs)
    session_names = sorted({key[0] for key in inputs})
    count = len(session_names)
    assert len(inputs) == count * 2
    # 表示部品とは独立に、ナイトの開始日を含む月曜起点の週へ分けます。
    weeks = {}
    for name in session_names:
        day = date.fromisoformat(name[:10])
        monday = day - timedelta(days=day.weekday())
        weeks.setdefault(monday, []).append(name)
    periods = [[name] for name in session_names] + list(weeks.values()) + [session_names]
    total_index = len(periods) - 1
    report_data = read(HERE / '報告データ.json')
    assert report_data['対象セッション数'] == count
    report_methods = {item['spec']['id']: item for item in report_data['候補']}
    expected, proofs, totals, sources = {}, [], {}, {}
    baseline_entries = {}
    for identifier in IDS:
        paths = {kind: SOURCE / kind / (identifier + ('.json' if kind == 'summaries' else '.json.gz'))
                 for kind in ('ledgers', 'sessions', 'summaries')}
        ledgers, sessions, summary = (read(paths[kind]) for kind in ('ledgers', 'sessions', 'summaries'))
        summaries = [(summary, '全16', set((row['session'], row['symbol']) for row in sessions))]
        for directory, complete in updates:
            new_paths = {kind: directory / kind / (identifier + ('.json' if kind == 'summaries' else '.json.gz'))
                         for kind in ('ledgers', 'sessions', 'summaries')}
            for path in new_paths.values():
                relative = path.relative_to(ROOT).as_posix()
                actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
                assert complete['出力SHA256'][relative] == actual_sha
                sources[relative] = actual_sha
            new_ledgers, new_sessions, new_summary = (read(new_paths[kind]) for kind in ('ledgers', 'sessions', 'summaries'))
            assert not {(row['session'], row['symbol']) for row in sessions}.intersection(
                {(row['session'], row['symbol']) for row in new_sessions})
            ledgers += new_ledgers
            sessions += new_sessions
            summaries.append((new_summary, f'全{len(sessions) // 2}', set((row['session'], row['symbol']) for row in sessions)))
        stored = {(row['session'], row['symbol']): row for row in sessions}
        assert len(stored) == len(sessions) == len(ledgers) == count * 2
        report_stored = {(row['session'], row['symbol']): row for row in report_methods[identifier]['sessions']}
        assert set(report_stored) == set(stored)
        calculated, curves = {}, {}
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            actual, curve = reconstruct(ledger, inputs[key])
            for field in (*FIELDS, 'drawdown_yen', 'max_long', 'max_short'):
                same(stored[key][field], actual[field], (identifier, key, field))
                same(report_stored[key][field], actual[field], (identifier, key, field, '表示元'))
            for directory, _ in updates:
                curve_path = directory / 'curves' / f'{identifier}_{key[0]}_{key[1]}.npz'
                if not curve_path.exists():
                    curve_path = directory / 'curves' / f'{identifier}_{key[1]}.npz'
                if key in update_keys[directory]:
                    with np.load(curve_path) as curve_file:
                        np.testing.assert_allclose(curve_file['equity'] * ledger['config']['point_value'], curve, rtol=0, atol=1e-6)
            orders = np.asarray(ledger['orders']).reshape((-1, 8))
            initial = orders[(orders[:, 7] == 1) & (orders[:, 6] == 20)]
            if identifier == 'E00':
                baseline_entries[key] = initial
            else:
                np.testing.assert_array_equal(initial, baseline_entries[key])
            config = ledger['config']
            stop, activation, trail = {'E00': (1, 1.5, 3), 'E01': (.75, 1.5, 3), 'E08': (.5, .5, .5)}[identifier]
            assert (config['stop_atr'], config['activation_atr'], config['main_trail']) == (stop, activation, trail)
            calculated[key], curves[key] = actual, curve
            proofs.append(dict(方式=identifier, セッション=key[0], 銘柄=key[1], 独立会計=True,
                               時価最大下落=True, 片方向上限=True, 初回固定=True, 場内完済=True))
        names = sorted({key[0] for key in calculated})
        assert names == session_names and len(calculated) == count * 2
        for index, selected in enumerate(periods):
            for symbol in ('TOPIX', 'NK225'):
                expected[(identifier, index, symbol)] = aggregate([calculated[name, symbol] for name in selected])
        totals[identifier] = {}
        for symbol in ('TOPIX', 'NK225'):
            values = expected[identifier, total_index, symbol].copy()
            total = high = dd = 0.
            for name in names:
                curve = curves[name, symbol] + total
                peak = np.maximum.accumulate(np.maximum(curve, high))
                dd = max(dd, float((peak - curve).max(initial=0)))
                high = max(high, float(curve.max(initial=0)))
                total = float(curve[-1])
            values['drawdown_yen'] = dd
            values['win_sessions'] = sum(calculated[name, symbol]['net_yen'] > 0 for name in names)
            values['average_unit_payoff'] = ((values['gross_profit_yen'] / values['profit_units']) /
                                               (values['gross_loss_yen'] / values['loss_units']))
            for field, value in values.items():
                if field != 'net_units':
                    same(summaries[-1][0]['periods'][f'全{count}'][symbol][field], value, (identifier, symbol, field))
                    same(report_methods[identifier]['overview'][symbol][field], value, (identifier, symbol, field, '表示元'))
            totals[identifier][symbol] = values
        # ----------------------------------------
        # 過去期間の集計も継続検査し、追加による既存結果の置換を検出する。
        for stored_summary, period_name, covered in summaries:
            for symbol in ('TOPIX', 'NK225'):
                keys = sorted(key for key in covered if key[1] == symbol)
                reference = aggregate([calculated[key] for key in keys])
                total = high = dd = 0.
                for key in keys:
                    curve = curves[key] + total
                    peak = np.maximum.accumulate(np.maximum(curve, high))
                    dd = max(dd, float((peak - curve).max(initial=0)))
                    high = max(high, float(curve.max(initial=0)))
                    total = float(curve[-1])
                reference['drawdown_yen'] = dd
                for field, value in reference.items():
                    if field != 'net_units':
                        same(stored_summary['periods'][period_name][symbol][field], value,
                             (identifier, period_name, symbol, field))
        for path in paths.values():
            sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    # ----------------------------------------
    # 表示属性と表示文字を別々に検算し、欠けた方式・週・枚数表も検出する。
    html_paths = list(REPORT.glob('*.html'))
    assert len(html_paths) == 1, html_paths
    html = html_paths[0]
    source_html = html.read_text(encoding='utf-8')
    parser = TableReader()
    parser.feed(source_html)
    seen = set()
    for cell in parser.records:
        identifier = cell['table'].get('data-method', '').split('__')[-1]
        if identifier not in IDS or 'data-row' not in cell['row']:
            continue
        row = int(cell['row']['data-row'])
        symbol, field = cell['attrs']['data-symbol'], cell['attrs']['data-field']
        target = expected[identifier, row, symbol][field]
        same(float(cell['attrs']['data-value']), target, (identifier, row, symbol, field, '属性'))
        text = cell['text'].strip().replace(',', '').replace('円', '').replace('枚', '').replace('−', '-')
        same(float(text), target, (identifier, row, symbol, field, '表示'))
        identity = identifier, row, symbol, field
        assert identity not in seen, ('数値セル重複', identity)
        seen.add(identity)
    required = {(identifier, row, symbol, field) for identifier in IDS for row in range(len(periods))
                for symbol in ('TOPIX', 'NK225') for field in FIELDS}
    assert required == seen, ('表示セルの過不足', sorted(required - seen), sorted(seen - required))
    # ----------------------------------------
    # 比較一覧と各章の主要数値も独立計算値と表示文字で照合する。
    overview = re.search(r'<table class="overview">(.*?)</table>', source_html, re.S).group(1)
    body = re.search(r'<tbody>(.*?)</tbody>', overview, re.S).group(1)
    overview_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', body, re.S)
    assert len(overview_rows) == 3
    kpi_count = 0
    for identifier, row in zip(('E01', 'E08', 'E00'), overview_rows):
        texts = [plain(cell) for cell in re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)]
        assert len(texts) == 7
        assert identifier in texts[0] or identifier == 'E00'
        for offset, symbol in ((1, 'TOPIX'), (4, 'NK225')):
            values = totals[identifier][symbol]
            assert texts[offset] == f"{values['net_yen']:+,.0f}円"
            assert texts[offset+1] == f"{values['win_sessions']}/{count}場"
            assert texts[offset+2] == f"{values['drawdown_yen']:,.0f}円"
            kpi_count += 3
        panel = re.search(r'<section[^>]*data-id="' + identifier + r'">(.*?)</section>', source_html, re.S).group(1)
        kpis = re.search(r'<div class="kpis">(.*?)<h3>', panel, re.S).group(1)
        text = plain(kpis)
        for symbol, label in (('TOPIX', 'TOPIXミニ'), ('NK225', 'NK225マイクロ')):
            values = totals[identifier][symbol]
            expected_text = (f"{label}：{values['win_sessions']}/{count}場が黒字 ／ 1枚平均利益÷平均損失 "
                             f"{values['average_unit_payoff']:.2f}倍 ／ 最大途中下落 {values['drawdown_yen']:,.0f}円")
            assert expected_text in text, (identifier, symbol, text, expected_text)
            kpi_count += 3
    result = dict(全合格=True, 方式数=3, 口座数=len(proofs), 表数値セル=len(seen),
                  比較一覧と主要数値=kpi_count,
                  原本価格による時価全行照合=True, 台帳から再計算=True,
                  各セッション週合計全期間合計=True, 表示文字と属性の一致=True,
                  全期間=totals, 口座確認=proofs, 元データSHA256=sources,
                  HTML=str(html.relative_to(ROOT)), HTML_SHA256=hashlib.sha256(html.read_bytes()).hexdigest(),
                  対象セッション数=count, 対象週数=len(weeks), 各表行数=len(periods), 登録追加フォルダ=registered,
                  新規市場データ取得数=0, 再バックテスト実行数=0)
    (HERE / '独立確認.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (HERE / '独立確認.md').write_text(
        '# 新候補レポートの独立確認\n\n'
        f'- 3方式・{len(proofs)}口座を保存約定台帳から再集計し、利益・損失・収支・勝ち負け同値枚数が一致。\n'
        f'- 保存生価格の全行で時価最大下落と保有上限を独立照合。\n'
        f'- 各{count}セッション・{len(weeks)}週・全期間のHTML数値{len(seen)}セルは、属性値と表示文字が一致。\n'
        f'- 比較一覧と各章の主要指標{ kpi_count }項目も、独立計算した収支・黒字場数・平均勝敗比・最大途中下落に一致。\n'
        '- 新規市場データ取得および新規バックテストは実施していない。\n'
        '- 将来の収益性を確認する検査ではなく、保存結果と報告の整合性を確認する検査。\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps({key: result[key] for key in ('全合格', '方式数', '口座数', '表数値セル')}, ensure_ascii=False))
