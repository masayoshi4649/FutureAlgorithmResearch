"""固定10候補の表示を、元注文・全返済と独立に照合する。"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
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


def same_saved(actual: object, expected: object) -> None:
    """機能: 状態修正証跡と旧統計の必須項目・数値を省略せず比較する。

    引数: actual/expected (object)。返り値: なし (None)。旧原監査と同じ絶対誤差1e-6。
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and actual.keys() == expected.keys()
        for key in expected:
            same_saved(actual[key], expected[key])
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected)
        for left, right in zip(actual, expected):
            same_saved(left, right)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)
        assert math.isfinite(actual) and math.isfinite(expected) and abs(actual - expected) <= 1e-6
    else:
        assert actual == expected


def state_completion(inputs: dict, references: dict) -> dict:
    """機能: 全974実体と旧資料を照合し、既知12行だけの修正完了を確認する。

    引数: inputs (dict)、references (dict)。返り値: 独立した完了証拠 (dict)。
    保存した成功フラグだけを信用せず、集合・内訳・全原監査の明細・旧指紋を確認する。
    """
    full_path = HERE / '状態修正の全再生.json'
    fixed_path = HERE / '状態修正の固定.json'
    old_fixed_path = OLD / '探索条件の固定.json'
    old_audit_path = OLD / 'adaptive_accounting_fixed.json'

    def bind(name: str, digest: str) -> None:
        """機能: 出所が指定した指紋を、既登録値と衝突させず結合する。

        引数: name/digest (str)。返り値: なし (None)。
        """
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and len(digest) == 64
        assert name not in references or references[name] == digest, name
        references[name] = digest

    for path in (full_path, fixed_path, old_fixed_path, old_audit_path,
                 HERE / '状態修正の差分.json', HERE / 'report_display_audit_完了表示前.py',
                 HERE / 'report_display_audit_完了表示前.json'):
        bind(path.relative_to(ROOT).as_posix(), sha(path))
    full, fixed = read(full_path), read(fixed_path)
    source, original_audit = read(old_fixed_path), read(old_audit_path)
    assert full['固定SHA256'] == sha(fixed_path)
    assert full['参照資料SHA256'] == fixed['参照資料SHA256']
    assert source['conditions'] == original_audit['主対象']
    assert source['supplementary_conditions'] == original_audit['補助対象']
    assert len(source['conditions']) == 206 and len(source['supplementary_conditions']) == 768
    assert fixed['条件'] == source['conditions'] + source['supplementary_conditions']
    specs = {s['id']: s for s in fixed['条件']}
    supplemental = {s['id'] for s in source['supplementary_conditions']}
    assert len(specs) == len(fixed['条件']) == 974 and len(supplemental) == 768
    for flag in ('全合格', '修正後実装状態契約合格', '経済全配列完全一致',
                 '全保存統計一致', '原版監査を無変更で使用', '既知12行だけ修正'):
        assert full[flag] is True, flag
    for field in ('採否変更', '旧成果変更', '新条件探索', '現在保存物使用'):
        assert full[field] is False
    assert full['API取得数'] == 0
    assert fixed['一行修正のみ'] is True and fixed['採否条件変更'] is False and fixed['影注文器変更'] is False
    for name, digest in fixed['参照資料SHA256'].items():
        bind(name, digest)
    for group in (source['SHA256'], original_audit['参照SHA256'], original_audit['原本78SHA256']):
        for name, digest in group.items():
            assert fixed['参照資料SHA256'][name] == digest
    assert len(original_audit['原本78SHA256']) == 78
    # ----------------------------------------
    # 旧実装の一行差分以外に変更がないことを、保存済み宣言とは別に確認する。
    old_engine = (OLD / 'engine_partial_restore.py').read_bytes()
    corrected_engine = (HERE / 'engine_partial_restore_corrected.py').read_bytes()
    newline = b'\r\n' if b'\r\n' in old_engine else b'\n'
    addition = b'                    phase = 2 if np.any(restorable) else 0' + newline
    assert corrected_engine.count(addition) == 1
    assert corrected_engine.replace(addition, b'', 1) == old_engine
    change = read(HERE / '状態修正の差分.json')
    assert change['元SHA256'] == sha(OLD / 'engine_partial_restore.py')
    assert change['修正版SHA256'] == sha(HERE / 'engine_partial_restore_corrected.py')
    known = dict(id='H019__B00_T120_F25_N3__R1__L015', session='2026-09-24_Night',
                 symbol='NK225', rows=list(range(46748, 46760)), old=1, new=0)
    assert fixed['既知状態差'] == known
    records = full['結果']
    assert len(records) == len({r['id'] for r in records}) == 974
    assert {r['id'] for r in records} == set(specs)
    total_inputs, total_raw, changed_conditions, changed_rows = 0, 0, 0, []
    condition_records = []
    required_flags = ('全枠会計一致', '全予約と新根拠一致', '元終了以前', '同約定両建て全行一致',
                      '全予算予約一致', '全分岐独立一致', '全伝達遅延一致', '旧保存全指紋一致',
                      '修正後状態契約合格', 'phase以外全配列完全一致')
    shadow_flags = ('影全会計一致', '独立公開計画一致', '独立準備一致', '最新成熟計画一致', '全行注文成立不成立一致')
    expected_result_fields = {'trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve',
                              'prepare_events', 'entry_preparations', 'control_curve', 'slot_curve',
                              'slot_events', 'adjustment_events', 'budget_events', 'branch_events', 'branch_curve'}
    expected_shadow_fields = {'trades', 'cycles', 'curve', 'orders', 'stats', 'atr_curve',
                             'plans', 'execution_plans', 'prepare_events', 'entry_preparations'}
    one_raw_count = sum(len(ready['last']) for ready in inputs.values())
    for record in records:
        identifier = record['id']
        is_supp = identifier in supplemental
        assert record['補助条件'] is is_supp and record['全合格'] is True
        path = HERE / 'state_fix_details' / (identifier + '.json.gz')
        assert record['実体'] == path.relative_to(ROOT).as_posix()
        bind(record['実体'], record['実体SHA256'])
        assert sha(path) == record['実体SHA256']
        detail = read(path)
        assert detail['id'] == identifier and detail['spec'] == specs[identifier]
        assert detail['補助条件'] is is_supp and detail['固定SHA256'] == full['固定SHA256']
        for flag in ('全合格', '原版状態監査合格', '経済全配列完全一致', '全保存統計一致', '影不変'):
            assert detail[flag] is True, (identifier, flag)
        for flag in ('旧成果変更', '新条件探索', '現在保存物使用'):
            assert detail[flag] is False
        assert detail['API取得数'] == 0
        assert record['全入力数'] == detail['全入力数'] == 26
        assert record['全原本行会計数'] == detail['全原本行会計数'] == one_raw_count
        destination = OLD / ('supplementary' if is_supp else '')
        source_paths = {name: destination / name / (identifier + suffix) for name, suffix in
                        (('ledgers', '.json.gz'), ('sessions', '.json.gz'),
                         ('accounting', '.json.gz'), ('summaries', '.json'))}
        assert set(detail['旧成果SHA256']) == {p.relative_to(ROOT).as_posix() for p in source_paths.values()}
        for name, digest in detail['旧成果SHA256'].items():
            bind(name, digest)
        saved_ledger = read(source_paths['ledgers'])
        saved_sessions = read(source_paths['sessions'])
        saved_summary = read(source_paths['summaries'])
        for rows in (detail['検査'], detail['sessions'], saved_ledger, saved_sessions):
            assert len(rows) == 26 and {(r['session'], r['symbol']) for r in rows} == set(inputs)
        old_by_key = {(r['session'], r['symbol']): r for r in saved_ledger}
        saved_by_key = {(r['session'], r['symbol']): r for r in saved_sessions}
        for row in detail['sessions']:
            same_saved(row, saved_by_key[row['session'], row['symbol']])
        for period in ('all_symbols', 'symbols'):
            same_saved(detail[period], saved_summary[period])
        for proof in detail['検査']:
            key = proof['session'], proof['symbol']
            for flag in required_flags:
                assert proof[flag] is True, (identifier, key, flag)
            assert proof['原本行数'] == len(inputs[key]['last'])
            shadow_proof = proof['影の独立公開と執行']
            for flag in shadow_flags:
                assert shadow_proof[flag] is True, (identifier, key, flag)
            assert shadow_proof['原本行数'] == len(inputs[key]['last'])
            fresh_fingerprints = proof['修正版全指紋']
            previous_fingerprints = old_by_key[key]['result_fingerprints']
            assert set(fresh_fingerprints) == set(previous_fingerprints) == expected_result_fields
            assert set(proof['影全指紋']) == expected_shadow_fields
            assert proof['影全指紋'] == old_by_key[key]['shadow_fingerprints']
            expected_change = identifier == known['id'] and key == (known['session'], known['symbol'])
            assert proof['状態変更行数'] == (12 if expected_change else 0)
            for field, fingerprint in fresh_fingerprints.items():
                assert set(fingerprint) == {'shape', 'dtype', 'SHA256'}
                assert re.fullmatch('[0-9a-f]{64}', fingerprint['SHA256'])
                assert fingerprint['shape'] == previous_fingerprints[field]['shape']
                assert fingerprint['dtype'] == previous_fingerprints[field]['dtype']
                if field == 'control_curve' and expected_change:
                    assert fingerprint['SHA256'] != previous_fingerprints[field]['SHA256']
                else:
                    assert fingerprint == previous_fingerprints[field], (identifier, key, field)
        differences = detail['状態変更全行']
        expected_rows = known['rows'] if identifier == known['id'] else []
        assert len(differences) == record['状態変更行数'] == detail['状態変更行数'] == len(expected_rows)
        assert [r['row'] for r in differences] == expected_rows
        for row in differences:
            assert row['session'] == known['session'] and row['symbol'] == known['symbol']
            assert row['old'] == 1 and row['new'] == 0
            ready = inputs[row['session'], row['symbol']]
            assert row['seq'] == int(ready['seq'][row['row']])
            assert row['time_s'] == float(ready['time_s'][row['row']])
            changed_rows.append(dict(id=identifier, **row))
        total_inputs += 26
        total_raw += one_raw_count
        changed_conditions += bool(differences)
        condition_records.append(dict(id=identifier, 補助条件=is_supp, 全26明細一致=True,
                                      状態変更行数=len(differences), 実体SHA256=record['実体SHA256']))
    for key, expected in dict(全条件数=974, 主条件数=206, 補助条件数=768,
                              全入力数=total_inputs, 全原本行会計数=total_raw,
                              状態変更条件数=changed_conditions, 状態変更行数=len(changed_rows)).items():
        assert full[key] == expected, key
    assert total_inputs == 25324 and total_raw == 2855617030 and changed_conditions == 1 and len(changed_rows) == 12
    return dict(全再生証拠の独立照合=True, 全条件数=974, 全入力数=total_inputs,
                全原本行会計数=total_raw, 原版監査全明細合格=True,
                旧全保存統計と経済指紋一致=True, 既知12行以外の差なし=True,
                一行修正以外の旧実装不変=True, 旧原本78と全成果指紋を照合=True,
                全再生SHA256=sha(full_path), 固定SHA256=sha(fixed_path),
                条件=condition_records, 状態変更全行=changed_rows)


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
    # 状態修正の完了証拠を全件へ接続した上で、公表リンクを確認する。
    state_proof = state_completion(inputs, refs)
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
    assert '974' in joined_text and '25,324' in joined_text and '12行' in joined_text
    assert '注文・全行の損益・数量・保存統計は旧結果と完全一致' in joined_text
    assert not any(word in joined_text for word in ('未知相場での利益を保証', '必ず利益が出る', '将来利益を保証'))
    assert not missing, ('最終公表リンクの欠落', missing)
    own = read(HERE / 'report_data_audit.json')
    assert own['全返済再計算一致'] and own['候補数'] == 10 and own['銘柄セッション数'] == 260
    assert own['返済明細数'] == trade_count and own['損益表示行数'] == 320 and own['比較表示行数'] == 20
    assert own['HTML_SHA256'] == sha(HTML) and own['報告実装SHA256'] == sha(HERE / 'report.py')
    assert own['修正版実装の完備をこの集計だけで主張'] is False
    assert own['状態修正再生SHA256'] == state_proof['全再生SHA256']

    def check_reference(item: tuple[str, str]) -> None:
        """機能: 原本・旧成果・今回の証跡が読取り中に変わっていないか確認する。

        引数: item (tuple[str,str])。返り値: なし (None)。
        """
        name, value = item
        assert sha(ROOT / name) == value, ('参照指紋不一致', name)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check_reference, refs.items()))
    result = dict(数値説明照合合格=True, 全候補数=10, 全銘柄セッション数=260,
                  全比較行数=20, 全金額枚数行数=320, 全返済件数=trade_count,
                  全注文全返済数量接続=True, 全終端保有ゼロ=True, 含み込み最大下落の独立復元=True,
                  Night開始日所属=True, 週別セッション数={'2026-09-21': 10, '2026-09-28': 3},
                  別名と旧ID=aliases, 最大2勝ち元組の独立除外=top_two,
                  表示変造拒否=negatives, 表示変造拒否数=len(negatives),
                  全リンク存在=not missing, 未完成予定リンク=sorted(set(missing)), リンク=links,
                  金額ゼロの負符号表示=[r['key'] for r in parsed.rows if r['key']
                                      and any(v == '-0' for v in r['cells'][1:3])],
                  状態修正完了の説明を全974実体へ接続=True, 状態修正の完了証拠=state_proof,
                  状態修正の実再生を本監査で実行=False,
                  公表リンク完備=not missing,
                  監査の改訂=dict(理由='未完成表示から、完了済み974条件の実体に基づく説明へ移行。数表と3破損拒否は不変。',
                               初版実装='work/wave_v41/report_display_audit_完了表示前.py',
                               初版結果='work/wave_v41/report_display_audit_完了表示前.json'),
                  台帳独立再計算=evidence, 参照SHA256=refs,
                  新損益再生=False, 原本変更=False, API取得数=0, 現在保存物使用=False)
    (HERE / 'report_display_audit.json').write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('数値説明照合合格', '全候補数', '全銘柄セッション数',
          '全比較行数', '全金額枚数行数', '全返済件数', '表示変造拒否数', '未完成予定リンク')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
