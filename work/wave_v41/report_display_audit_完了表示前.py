"""固定10候補の表示を、元注文・全返済と独立に照合する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import gzip
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import pickle
import re
from urllib.parse import unquote, urlsplit

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'wave_v38'
HTML = ROOT / 'アルゴリズム調査/00036_黒字候補の再評価と状態修正/黒字候補の再評価と状態修正.html'
POLICIES = (
    'A0', 'B00_RB00_F25_N1', 'B00_T120_F25_N1', 'B00_T120_F25_N3',
    'B06_RB01_F25_N1', 'B06_RB01_F50_N1', 'B06_T120_F50_N3',
    'B07_T120_F25_N1', 'B07_T120_F50_N1', 'B06_CHOICE_B01_F50_N1',
)
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen',
          'profit_units', 'loss_units', 'zero_units')
PENDING = {'README.md', '../../work/wave_v41/状態修正の全再生.json'}


def read(path: Path) -> object:
    """機能: 通常又は圧縮された保存資料を読む。

    引数: path (Path)。返り値: 保存された内容 (object)。
    """
    content = path.read_bytes()
    return json.loads(gzip.decompress(content) if path.suffix == '.gz' else content)


def sha(path: Path) -> str:
    """機能: 読取り資料の内容指紋を得る。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            h.update(block)
    return h.hexdigest()


def equal(a: float, b: float, label: str) -> None:
    """機能: 有限数値の一致を円未満の丸め誤差だけ許して確認する。

    引数: a/b (float)、label (str)。返り値: なし (None)。
    """
    assert math.isfinite(a) and math.isfinite(b), label
    assert abs(a - b) <= 1e-5, (label, a, b)


class Display(HTMLParser):
    """機能: 表示セル・章・リンクをHTMLから読み取る。

    引数: なし。返り値: 解析状態を持つDisplayインスタンス (Display)。
    """

    def __init__(self) -> None:
        """機能: 独立解析器の状態を初期化する。

        引数: なし。返り値: なし (None)。
        """
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.links = []
        self.ids = []
        self.sections = {}
        self.text = []
        self.section = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag: str, attrs: list[tuple]) -> None:
        """機能: 表の行・セル・章と参照先の開始を記録する。

        引数: tag (str)、attrs (list[tuple])。返り値: なし (None)。
        """
        a = dict(attrs)
        if a.get('id'):
            self.ids.append(a['id'])
        if tag == 'a' and 'href' in a:
            self.links.append(a['href'])
        if tag == 'section':
            self.section = a.get('id')
            assert self.section and self.section not in self.sections
            self.sections[self.section] = []
        if tag == 'tr':
            assert self.row is None
            self.row = {'key': a.get('data-key'), 'cells': []}
        if tag in ('td', 'th') and self.row is not None:
            assert self.cell is None
            self.cell = []

    def handle_data(self, value: str) -> None:
        """機能: 実際のセル文字と章本文を収集する。

        引数: value (str)。返り値: なし (None)。
        """
        self.text.append(value)
        if self.section:
            self.sections[self.section].append(value)
        if self.cell is not None:
            self.cell.append(value)

    def handle_endtag(self, tag: str) -> None:
        """機能: セルの表示文字列を確定する。

        引数: tag (str)。返り値: なし (None)。
        """
        if tag in ('td', 'th') and self.cell is not None:
            self.row['cells'].append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == 'section':
            self.section = None


def recompute(ledger: dict, ready: dict) -> tuple[dict, np.ndarray, list[float], int]:
    """機能: 全返済を元値・数量から計算し、全新規と全返済の対応を検査する。

    引数: ledger/ready (dict)。返り値: 損益6項目、独立時価、元組損益、返済数 (tuple)。
    含み込み最大下落は、保存された最大下落値を使用せず全注文から再構築する。
    """
    factor = {'TOPIX': 1000., 'NK225': 10.}[ledger['symbol']]
    n = len(ready['last'])
    sums = dict.fromkeys(FIELDS, 0.)
    opening, closing, used_opening, used_closing = (defaultdict(float) for _ in range(4))
    campaigns = defaultdict(float)
    cash_step, net_step = np.zeros(n), np.zeros(n)
    side_opened, side_closed = defaultdict(float), defaultdict(float)
    for order in ledger['orders']:
        row, source, campaign, side, qty, price, reason, is_open = order
        assert all(math.isfinite(v) for v in order)
        assert row == int(row) and source == int(source) and 0 <= source < row < n
        assert campaign == int(campaign) and campaign >= 0 and side in (-1, 1)
        assert qty > 0 and qty == int(qty) and price > 0 and is_open in (0, 1)
        cash_step[int(row)] -= side * qty * price
        net_step[int(row)] += side * qty
        if is_open:
            opening[(campaign, side, price, row)] += qty
            side_opened[(campaign, side)] += qty
        else:
            closing[(campaign, -side, price, row)] += qty
            side_closed[(campaign, -side)] += qty
            assert side_closed[(campaign, -side)] <= side_opened[(campaign, -side)]
        assert ready['time_s'][int(row)] < ready['limit'] + 600
    assert dict(side_opened) == dict(side_closed), '未決済の新規玉を表から除外してはならない'
    for trade in ledger['trades']:
        campaign, leg, side, qty, entry, exit_price, entry_row, exit_row, role, reason, saved_pnl = trade
        assert all(math.isfinite(v) for v in trade)
        assert side in (-1, 1) and qty > 0 and qty == int(qty) and entry > 0 and exit_price > 0
        assert 0 <= entry_row <= exit_row < n and entry_row == int(entry_row) and exit_row == int(exit_row)
        value = side * qty * (exit_price - entry) * factor
        equal(value, saved_pnl * factor, '返済の元価格数量')
        used_opening[(campaign, side, entry, entry_row)] += qty
        used_closing[(campaign, side, exit_price, exit_row)] += qty
        campaigns[campaign] += value
        sums['net_yen'] += value
        if value > 0:
            sums['gross_profit_yen'] += value
            sums['profit_units'] += qty
        elif value < 0:
            sums['gross_loss_yen'] -= value
            sums['loss_units'] += qty
        else:
            sums['zero_units'] += qty
    assert dict(opening) == dict(used_opening), '全新規と返済明細の数量不一致'
    assert dict(closing) == dict(used_closing), '全返済注文と返済明細の数量不一致'
    assert set(campaigns) == {c[0] for c in ledger['cycles']}
    for cycle in ledger['cycles']:
        equal(campaigns[cycle[0]], cycle[3] * factor, '損失を含む全元組')
    inventory = np.cumsum(net_step)
    assert inventory[-1] == 0, '終端の保有残'
    equity = (np.cumsum(cash_step) + inventory * np.asarray(ready['last'])) * factor
    equal(float(equity[-1]), sums['net_yen'], '現金と全決済損益')
    return sums, equity, list(campaigns.values()), len(ledger['trades'])


def add(rows: list[dict]) -> dict:
    """機能: 独立計算済みの全行を除外せず合算する。

    引数: rows (list[dict])。返り値: 6項目合計 (dict)。
    """
    return {field: sum(r[field] for r in rows) for field in FIELDS}


def financial_cells(label: str, value: dict) -> list[str]:
    """機能: 表示仕様の金額・枚数・差を独立に文字列化する。

    引数: label (str)、value (dict)。返り値: 8列 (list[str])。
    """
    return [label, f'{value["gross_profit_yen"]:,.0f}', f'{value["gross_loss_yen"]:,.0f}',
            f'{value["net_yen"]:+,.0f}', str(int(value['profit_units'])),
            str(int(value['loss_units'])), str(int(value['zero_units'])),
            f'{int(value["profit_units"] - value["loss_units"]):+d}']


def verify_html(text: str, expected: dict, overview: dict, aliases: dict) -> Display:
    """機能: HTMLセルの値・件数・重複・旧IDへの対応を照合する。

    引数: text (str)、expected/overview/aliases (dict)。返り値: 解析済みHTML (Display)。
    """
    parsed = Display()
    parsed.feed(text)
    assert len(parsed.ids) == len(set(parsed.ids))
    financial = [r for r in parsed.rows if r['key']]
    assert len(financial) == len({r['key'] for r in financial}) == 320
    assert {r['key'] for r in financial} == set(expected)
    for row in financial:
        cells = ['0' if i in (1, 2) and value == '-0' else value
                 for i, value in enumerate(row['cells'])]
        assert cells == expected[row['key']], ('金額枚数表示', row)
    compared = [r['cells'] for r in parsed.rows if not r['key'] and len(r['cells']) == 6
                and re.match(r'^C\d{2} ', r['cells'][0])]
    assert len(compared) == 20
    keys = [(r[0].split()[0], r[1]) for r in compared]
    assert len(set(keys)) == 20 and set(keys) == set(overview)
    for key, row in zip(keys, compared):
        assert row[2:] == overview[key], ('比較表示', key, row)
    assert set(parsed.sections) == set(aliases)
    for alias, identifier in aliases.items():
        found = [value.removeprefix('旧ID：') for value in parsed.sections[alias]
                 if value.startswith('旧ID：')]
        assert found == [identifier], ('表示別名と旧ID', alias, found)
    return parsed


def main() -> None:
    """機能: 保存台帳から表示を独立検算し、変造拒否と参照指紋を保存する。

    引数: なし。返り値: なし (None)。戦略再生・現在データ取得は行わない。
    """
    refs = {}

    def register(path: Path) -> None:
        """機能: 検査に用いる資料の前指紋を登録する。

        引数: path (Path)。返り値: なし (None)。
        """
        refs[path.relative_to(ROOT).as_posix()] = sha(path)

    input_path = HERE.parent / 'wave_v23/inputs.pkl'
    fixed_path = OLD / '探索条件の固定.json'
    for path in (Path(__file__), HERE / 'report.py', HTML, input_path, fixed_path,
                 OLD / 'adaptive_design_fixed.json', OLD / '独立判定.json',
                 OLD / '経済完備監査.json', HERE / 'report_data_audit.json',
                 HERE / '板観測の欠落診断.json'):
        register(path)
    fixed = read(fixed_path)
    names = sorted(fixed['全セッション'])
    assert len(names) == len(set(names)) == 13
    inputs = pickle.loads(input_path.read_bytes())
    keys = {(s, sym) for s in names for sym in ('TOPIX', 'NK225')}
    assert set(inputs) == keys
    design = read(OLD / 'adaptive_design_fixed.json')
    assert set(design['rules']['対象8条件']) == set(POLICIES[1:9])
    expected, overview, aliases, evidence, top_two = {}, {}, {}, [], {}
    trade_count = 0
    for index, policy in enumerate(POLICIES):
        alias = f'C{index:02d}'
        identifier = f'H019__{policy}__R1__V000'
        aliases[alias] = identifier
        paths = {folder: OLD / folder / (identifier + suffix) for folder, suffix in
                 (('sessions', '.json.gz'), ('ledgers', '.json.gz'), ('summaries', '.json'))}
        for path in paths.values():
            register(path)
        sessions, ledgers, summary = (read(paths[x]) for x in ('sessions', 'ledgers', 'summaries'))
        assert summary['id'] == identifier and summary['spec']['policy']['id'] == policy
        assert summary['spec']['variant_id'] == 'V000' and summary['spec']['budget_enabled'] is True
        for rows in (sessions, ledgers):
            assert len(rows) == 26 and {(r['session'], r['symbol']) for r in rows} == keys
        saved = {(r['session'], r['symbol']): r for r in sessions}
        recomputed, curves, campaign_values = {}, {}, defaultdict(list)
        for ledger in ledgers:
            key = ledger['session'], ledger['symbol']
            assert saved[key]['id'] == identifier
            values, curve, profits, count = recompute(ledger, inputs[key])
            trade_count += count
            for field in FIELDS:
                equal(values[field], saved[key][field], '保存セッションとの一致')
            recomputed[key], curves[key] = values, curve
            campaign_values[key[1]].extend(profits)
            evidence.append(dict(id=identifier, session=key[0], symbol=key[1],
                                 返済件数=count, 全新規全返済対応=True, 終端保有ゼロ=True, **values))
        for symbol in ('TOPIX', 'NK225'):
            total = add([recomputed[s, symbol] for s in names])
            for field in FIELDS:
                equal(total[field], summary['all_symbols'][symbol][field], '保存全13との一致')
            joined, offset = [np.zeros(1)], 0.
            for session in names:
                joined.append(curves[session, symbol] + offset)
                offset += curves[session, symbol][-1]
            path = np.concatenate(joined)
            dd = float(np.max(np.maximum.accumulate(path) - path))
            equal(dd, summary['all_symbols'][symbol]['drawdown_yen'], '独立注文時価のDD')
            money_ratio = total['gross_profit_yen'] / total['gross_loss_yen']
            unit_ratio = (total['gross_profit_yen'] / total['profit_units']) / (total['gross_loss_yen'] / total['loss_units'])
            overview[alias, symbol] = [f'{total["net_yen"]:+,.0f}', f'{dd:,.0f}',
                                      f'{money_ratio:.2f}', f'{unit_ratio:.2f}']
            expected[f'{alias}|{symbol}|全期間'] = financial_cells('全13セッション', total)
            weeks = defaultdict(list)
            for session in names:
                stamp = date.fromisoformat(session[:10])
                monday = (stamp - timedelta(days=stamp.weekday())).isoformat()
                weeks[monday].append(recomputed[session, symbol])
                label = session[:10] + (' 日中' if session.endswith('_Day') else ' 夜間')
                expected[f'{alias}|{symbol}|{session}'] = financial_cells(label, recomputed[session, symbol])
            assert set(weeks) == {'2026-09-21', '2026-09-28'}
            assert len(weeks['2026-09-21']) == 10 and len(weeks['2026-09-28']) == 3
            for monday, rows in weeks.items():
                expected[f'{alias}|{symbol}|{monday}'] = financial_cells(monday + '開始週', add(rows))
            if policy == 'A0':
                winners = sorted((v for v in campaign_values[symbol] if v > 0), reverse=True)
                top_two[symbol] = dict(全収支円=total['net_yen'], 最大勝ち元組円=winners[:2],
                                     上位2勝ち元組を同時除外した収支円=total['net_yen'] - sum(winners[:2]))
                assert top_two[symbol]['上位2勝ち元組を同時除外した収支円'] > 0
    # ----------------------------------------
    # 表示済み文字列を直接変更し、保存値の検算だけで終わらないことを確認する。
    content = HTML.read_text(encoding='utf-8')
    parsed = verify_html(content, expected, overview, aliases)
    negatives = []
    first_key = 'C00|TOPIX|全期間'
    row_pattern = r'(<tr data-key="' + re.escape(first_key) + r'">)(.*?)(</tr>)'
    match = re.search(row_pattern, content, re.S)
    assert match
    cells = re.findall(r'<td>(.*?)</td>', match.group(2), re.S)
    for label, cell_index in (('金額1箇所', 0), ('決済枚数1箇所', 3)):
        changed_cells = list(cells)
        changed_cells[cell_index] = str(int(cells[cell_index].replace(',', '')) + 1)
        part = match.group(2)
        positions = list(re.finditer(r'<td>(.*?)</td>', part, re.S))
        hit = positions[cell_index]
        changed_part = part[:hit.start(1)] + changed_cells[cell_index] + part[hit.end(1):]
        changed = content[:match.start(2)] + changed_part + content[match.end(2):]
        try:
            verify_html(changed, expected, overview, aliases)
        except AssertionError:
            negatives.append(label)
        else:
            raise AssertionError('表示変造を検知しなかった: ' + label)
    original = '旧ID：' + aliases['C00']
    assert content.count(original) == 1
    changed = content.replace(original, '旧ID：' + aliases['C01'], 1)
    try:
        verify_html(changed, expected, overview, aliases)
    except AssertionError:
        negatives.append('旧ID1箇所')
    else:
        raise AssertionError('旧IDの誤対応を検知しなかった')
    # ----------------------------------------
    # 未完成リンクだけを限定記録し、状態修正の完了判定とは混同しない。
    missing, links = [], []
    for href in parsed.links:
        value = urlsplit(href)
        if value.scheme:
            assert value.scheme in ('https', 'http')
            continue
        target = (HTML.parent / unquote(value.path)).resolve() if value.path else HTML
        exists = target.is_file()
        if not exists:
            assert href in PENDING, ('予定外のリンク欠落', href)
            missing.append(href)
        if value.fragment and not value.path:
            assert unquote(value.fragment) in parsed.ids
        links.append(dict(href=href, 存在=exists, 未完成予定=href in PENDING and not exists))
    joined_text = ''.join(parsed.text)
    assert '未知検証ではありません' in joined_text
    assert '収益改善はまだ示していません' in joined_text
    assert '夜間は開始日の所属週' in joined_text
    false_completion = ('状態修正が完了', '状態修正は完了', '修正版の全検査に合格', '実運用可能', '完全実装合格')
    assert not any(word in joined_text for word in false_completion)
    own = read(HERE / 'report_data_audit.json')
    assert own['全返済再計算一致'] and own['候補数'] == 10 and own['銘柄セッション数'] == 260
    assert own['返済明細数'] == trade_count and own['損益表示行数'] == 320 and own['比較表示行数'] == 20
    assert own['HTML_SHA256'] == sha(HTML) and own['報告実装SHA256'] == sha(HERE / 'report.py')
    assert own['修正版実装の完備をこの集計だけで主張'] is False
    for name, value in refs.items():
        assert sha(ROOT / name) == value, ('読取中の資料変更', name)
    result = dict(数値説明照合合格=True, 全候補数=10, 全銘柄セッション数=260,
                  全比較行数=20, 全金額枚数行数=320, 全返済件数=trade_count,
                  全注文全返済数量接続=True, 全終端保有ゼロ=True, 含み込み最大下落の独立復元=True,
                  Night開始日所属=True, 週別セッション数={'2026-09-21': 10, '2026-09-28': 3},
                  別名と旧ID=aliases, 最大2勝ち元組の独立除外=top_two,
                  表示変造拒否=negatives, 表示変造拒否数=len(negatives),
                  全リンク存在=not missing, 未完成予定リンク=sorted(set(missing)), リンク=links,
                  金額ゼロの負符号表示=[r['key'] for r in parsed.rows if r['key']
                                      and any(v == '-0' for v in r['cells'][1:3])],
                  状態修正完了を主張していない=True, 状態修正の実再生完了を本監査で判定=False,
                  公表リンク完備=not missing,
                  説明上の留意点=['上位2勝ち組は同時除外でも黒字。「個別に除く」は同時除外と明記すると明瞭。',
                                 '未完成予定リンクには準備中表示を添えるか、対象生成後に公表する。'],
                  台帳独立再計算=evidence, 参照SHA256=refs,
                  新損益再生=False, 原本変更=False, API取得数=0, 現在保存物使用=False)
    (HERE / 'report_display_audit.json').write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('数値説明照合合格', '全候補数', '全銘柄セッション数',
          '全比較行数', '全金額枚数行数', '全返済件数', '表示変造拒否数', '未完成予定リンク')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
