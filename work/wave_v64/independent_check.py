"""既存台帳と価格列から入口方向の採点を別式で独立確認する。"""

from collections import Counter
from decimal import Decimal, ROUND_CEILING
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / 'アルゴリズム調査/00060_決済勝率95パーセントの探索とPDCA'
PUBLIC = ROOT / 'アルゴリズム調査/00061_入口の方向予測精度を出口と分離'


class TableRows(HTMLParser):
    """HTMLの表行を文字列のセル配列として収集する。"""

    def __init__(self):
        """機能: 表行収集の状態を初期化する。

        引数: なし。返り値: なし(None)。
        """
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        """機能: 表行と表セルの開始を記録する。

        引数: tag(str)、attrs(list)。返り値: なし(None)。
        """
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        """機能: 現在のセルの可視文字列を記録する。

        引数: data(str)。返り値: なし(None)。
        """
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        """機能: 閉じられたセルと行を保存する。

        引数: tag(str)。返り値: なし(None)。
        """
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    """機能: 元台帳、全281判断、全1686採点、集計とHTML表値を独立検算する。

    引数: なし。返り値: なし(None)。元スクリプトは読込実行せず、原本/APIも変更しない。
    """
    packet = json.loads((PREVIOUS / '比較3候補.json').read_text(encoding='utf-8'))
    scored = json.loads((HERE / '方向採点.json').read_text(encoding='utf-8'))
    frozen = json.loads((HERE / '採点前固定.json').read_text(encoding='utf-8'))
    ready = pickle.loads((HERE.parent / 'wave_v60/inputs.pkl').read_bytes())
    quotes = pickle.loads((HERE.parent / 'wave_v60/quotes.pkl').read_bytes())
    errors, sources, expected_entries = [], [], Counter()
    score_checked, origin_checked, boundary60, beyond_end = 0, 0, 0, 0
    for key, account in ready.items():
        assert (np.diff(account['time_s']) >= 0).all()
        assert (np.diff(account['seq']) > 0).all()
        np.testing.assert_array_equal(quotes[key]['mid'], (quotes[key]['bid'] + quotes[key]['ask']) / 2)
    for number, method in enumerate(packet['methods'], 1):
        path = PREVIOUS / '台帳' / f'候補{number}_原簿.pkl'
        ledgers = pickle.loads(path.read_bytes())
        source = ROOT / method['source']
        if source.is_file() and source.suffix == '.json':
            original = json.loads(source.read_text(encoding='utf-8'))
            original_method = next(m for m in original['methods'] if m['id'] == method['id'])
            original_path = source.parent / original_method['ledger']
            original_ledgers = pickle.loads(original_path.read_bytes())
            for key, value in ledgers.items():
                np.testing.assert_array_equal(value['orders'], original_ledgers[key]['orders'])
                np.testing.assert_array_equal(value['trades'], original_ledgers[key]['trades'])
        for key, value in ledgers.items():
            orders = value['orders']
            account = ready[key[:2]]
            for order in orders:
                if orders.shape[1] == 9:
                    if order[2] != 1:
                        continue
                    index, side = int(order[0]), int(order[3])
                    assert order[1] == index + 1
                else:
                    if order[4] != 1:
                        continue
                    matches = np.flatnonzero(account['seq'] == order[2])
                    assert len(matches) == 1
                    index, side = int(matches[0]), int(order[5])
                    assert order[0] == account['time_s'][index]
                    assert order[3] > order[2]
                assert side in (-1, 1)
                expected_entries[(method['id'], *key[:2], index, side)] += 1
        sources.append(dict(候補=number,原簿=str(path.relative_to(ROOT)),SHA256=hashlib.sha256(path.read_bytes()).hexdigest()))
    seen = Counter()
    independent = {}
    for row in scored['rows']:
        key = (row['session'], row['symbol'])
        account, quote = ready[key], quotes[key]
        t, mid, seq = account['time_s'], quote['mid'], account['seq']
        index, side = row['decision_i'], row['side']
        seen[(row['method'], *key, index, side)] += 1
        assert row['decision_seq'] == int(seq[index])
        assert row['decision_time'] == t[index]
        assert row['decision_mid'] == mid[index]
        origin_checked += 1
        labels = {}
        for minutes in (5, 15, 30, 60):
            target = t[index] + 60 * minutes
            later = np.flatnonzero(t >= target)
            j = int(later[0]) if len(later) else None
            valid = target < account['limit'] + 300 and j is not None and t[j] <= target + 60
            observed = row['scores'][str(minutes)]
            assert observed['有効'] == valid
            if valid:
                displacement = side * mid[j] - side * mid[index]
                verdict = int(displacement > 0) - int(displacement < 0)
                assert observed['判定'] == verdict
                assert observed['方向変位'] == displacement
                assert observed['評価行'] == j
                assert observed['時計超過秒'] == t[j] - target
                boundary60 += int(t[j] - target == 60)
                beyond_end += int(t[j] >= account['limit'] + 300)
                labels[str(minutes)] = (True, verdict)
            else:
                labels[str(minutes)] = (False, None)
            score_checked += 1
        for fraction in ('0.0005', '0.001'):
            label = '先着0.05' if fraction == '0.0005' else '先着0.10'
            observed = row['scores'][label]
            valid = labels['30'][0]
            assert observed['有効'] == valid
            if valid:
                width = float((Decimal(str(mid[index])) * Decimal(fraction) / Decimal(str(account['tick']))).to_integral_value(rounding=ROUND_CEILING) * Decimal(str(account['tick'])))
                end = index + 1800
                indexes = np.flatnonzero((np.arange(len(t)) > index) & (t <= t[index] + 1800))
                changes = side * mid[indexes] - side * mid[index]
                plus, minus = indexes[changes >= width], indexes[changes <= -width]
                positive = int(plus[0]) if len(plus) else len(t)
                negative = int(minus[0]) if len(minus) else len(t)
                verdict = 1 if positive < negative else -1 if negative < positive else 0
                first = min(positive, negative) if verdict else None
                assert observed['判定'] == verdict
                assert observed['幅'] == width
                assert observed['評価行'] == first
                labels[label] = (True, verdict)
            else:
                labels[label] = (False, None)
            score_checked += 1
        independent[(row['method'], *key, index, side)] = labels
    assert seen == expected_entries
    assert len(scored['rows']) == 281 == sum(expected_entries.values())
    summaries = []
    for method in scored['methods']:
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in scored['rows'] if r['method'] == method['id'] and r['symbol'] == symbol]
            for label, original in method['summary'][symbol].items():
                values = [(r, independent[(r['method'], r['session'], r['symbol'], r['decision_i'], r['side'])][label]) for r in rows]
                valid = [(r, verdict) for r, (ok, verdict) in values if ok]
                good, bad = sum(v == 1 for r, v in valid), sum(v == -1 for r, v in valid)
                neutral, count = len(valid) - good - bad, len(valid)
                long_count = sum(v * r['side'] == 1 for r, v in valid)
                short_count = sum(v * r['side'] == -1 for r, v in valid)
                computed = dict(新規数=len(rows),評価数=count,正答=good,逆行=bad,横ばい又は未到達=neutral,除外=len(rows)-count,
                    正答率=good/count if count else None,到達又は変化内正答率=good/(good+bad) if good+bad else None,
                    同時点常時買い正答率=long_count/count if count else None,同時点常時売り正答率=short_count/count if count else None,
                    同時点コイントス期待正答率=(good+bad)/(2*count) if count else None)
                assert computed == original, (method['number'], symbol, label, computed, original)
            summaries.append(dict(候補=method['number'],銘柄=symbol,固定30分=method['summary'][symbol]['30'],先着0_05=method['summary'][symbol]['先着0.05']))
    # ----------------------------------------
    # 公開HTMLの表示値と保存JSONの主・補助表を照合する。
    parser = TableRows()
    parser.feed((PUBLIC / '入口の方向予測精度.html').read_text(encoding='utf-8'))
    cells = [r for r in parser.rows if r and r[0].startswith('候補')]
    assert len(cells) == 12
    expected_cells = []
    for method in scored['methods']:
        for symbol in ('TOPIX', 'NK225'):
            a, b = method['summary'][symbol]['30'], method['summary'][symbol]['先着0.05']
            expected_cells.append([f'候補{method["number"]}', symbol, f'{a["正答"]}/{a["評価数"]}', f'{100*a["正答率"]:.1f}%', str(a['横ばい又は未到達']), str(a['除外']), f'{b["正答"]}/{b["評価数"]} ({100*b["正答率"]:.1f}%)', str(b['横ばい又は未到達'])])
    for method in scored['methods']:
        for symbol in ('TOPIX', 'NK225'):
            a = method['summary'][symbol]['30']
            expected_cells.append([f'候補{method["number"]} {symbol}'] + [f'{100*method["summary"][symbol][str(h)]["正答率"]:.1f}% ({method["summary"][symbol][str(h)]["評価数"]})' for h in (5, 15, 30, 60)] + [f'{100*a["同時点常時買い正答率"]:.1f}%', f'{100*a["同時点常時売り正答率"]:.1f}%'])
    assert cells == expected_cells
    assert json.loads((PUBLIC / '方向採点.json').read_text(encoding='utf-8')) == scored
    assert hashlib.sha256((HERE / 'entry_accuracy.py').read_bytes()).hexdigest() == frozen['コードSHA']
    report = dict(結論='元新規281件・全1686採点・36集計・HTML12表行が独立別式と一致',原簿照合=sources,
        新規起点照合=origin_checked,採点照合=score_checked,主30分評価数=sum(x['固定30分']['評価数'] for x in summaries),
        主30分除外数=sum(x['固定30分']['除外'] for x in summaries),評価時計60秒ちょうど=boundary60,
        評価時点が場末を越えた件数=beyond_end,主表=summaries,
        留意点=['価格起点は発注判断行の中値で、実約定行ではない。出口条件・手数料・気配差は方向ラベルへ混ぜていない。',
        '既存実取引の判断だけを対象とし、入口候補すべての精度ではない。実取引の選別と過去の出口条件は母集団を決めている。',
        '先着と固定時点は別の問い。候補1のNKは先着29/41=70.7%でも30分後22/41=53.7%。',
        '25セッションは既知、モデルを選定した同じデータ。未見の将来精度とは呼べない。取引時点が重なるため単純な独立二項確率推定も適さない。',
        'CurrentPriceTimeは受信時刻ではないため、方向ラベルの30分は保存された約定時計基準。',
        '採点前固定.jsonの「60秒以上」は実装・HTMLの「60秒超過」と文言が1箇所異なる。該当境界の件数を別記し、主表への影響を確認した。'],
        スクリプトSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE / '独立検査.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('結論','新規起点照合','採点照合','主30分評価数','主30分除外数','評価時計60秒ちょうど','評価時点が場末を越えた件数')},ensure_ascii=False))


if __name__ == '__main__':
    main()
