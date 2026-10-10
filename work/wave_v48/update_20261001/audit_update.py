"""追加1セッションの会計と、更新した全16場の表示を独立式で照合する。"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OLD = WORK.parent / 'wave_v47'
PRIOR = WORK / 'update_20260930'
BACKUP = WORK / 'before_update_20261001'
HTML = ROOT / 'アルゴリズム調査/00042_有望4手法の説明とセッション損益/有望4手法の説明と損益.html'
IDS = ('F50_NONE__E11', 'F50_NONE__E10', 'C01__E10', 'A0__E10')
SYMBOLS = {'TOPIX': (5, 10, 1000.), 'NK225': (10, 20, 10.)}
FIELDS = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units')
SESSION = '2026-09-30_Night'


def read(path: Path) -> object:
    """機能: JSON又は圧縮JSONを読む。

    引数: path(Path)。返り値: 展開した内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def sha(path: Path) -> str:
    """機能: ファイル内容の指紋を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            h.update(block)
    return h.hexdigest()


def close(left: float, right: float, name: str) -> None:
    """機能: 会計数値を許容誤差付きで照合する。

    引数: left/right(float)、name(str)。返り値: なし(None)。
    """
    assert np.isfinite(left) and np.isfinite(right) and abs(left-right) <= 1e-6, (name, left, right)


def independent_atr(ready: dict) -> dict:
    """機能: CSVから逐次TRとATRを別式で作り、全観測の利用可能値を検算する。

    引数: ready(dict)。返り値: 公開時刻検査の証跡(dict)。
    """
    path = ROOT / 'candle_5min' / ready['symbol'] / (SESSION+'.csv')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = sorted((r for r in csv.DictReader(stream) if r['closed'].lower() == 'true'), key=lambda r:r['time'])
    times, values = [], []
    previous = None
    running = None
    for number, row in enumerate(rows):
        high, low, last = (float(row[k]) for k in ('high', 'low', 'close'))
        tr = high-low if previous is None else max(high-low, abs(high-previous), abs(low-previous))
        running = tr if running is None else (11*running+tr)/12
        times.append(datetime.fromisoformat(row['time']).timestamp()+360)
        values.append(np.nan if number < 2 else max(running, 2*ready['tick']))
        previous = last
    indexes = np.searchsorted(times, ready['time_s'], side='right')-1
    expected = np.full(len(indexes), np.nan)
    valid = indexes >= 0
    expected[valid] = np.asarray(values)[indexes[valid]]
    np.testing.assert_allclose(ready['atr'], expected, rtol=1e-12, atol=1e-9, equal_nan=True)
    return dict(銘柄=ready['symbol'], 行数=len(indexes), 確定足数=len(rows),
                足開始から360秒待機=True, 別式ATR全行一致=True, 原本SHA256=sha(path))


def account(ledger: dict, row: dict, ready: dict | None) -> dict:
    """機能: 全返済脚と注文から金額・数量・時価を別式で再構成する。

    引数: ledger/row(dict)、ready(dict|None)。返り値: 独立会計結果(dict)。
    """
    symbol = row['symbol']
    initial, cap, multiplier = SYMBOLS[symbol]
    config = ledger['config']
    assert config['initial_qty'] == initial and config['audit_cap'] == cap
    assert config['point_value'] == multiplier and config['add_mode'] == config['add_qty'] == 0
    totals = {key: 0. for key in FIELDS}
    expected_open, expected_close = Counter(), Counter()
    cycles = Counter()
    for trade in ledger['trades']:
        campaign, _, side, qty, entry, exit_price, entry_row, exit_row, _, _, stored = trade
        assert side in (-1, 1) and qty >= 1 and qty == int(qty)
        assert 0 <= entry_row <= exit_row
        points = (exit_price-entry)*side*qty
        close(points, stored, '返済脚の価格数量')
        pnl = points*multiplier
        totals['gross_profit_yen'] += max(pnl, 0)
        totals['gross_loss_yen'] += max(-pnl, 0)
        totals['net_yen'] += pnl
        totals['profit_units' if pnl > 0 else 'loss_units' if pnl < 0 else 'zero_units'] += qty
        expected_open[(entry_row, side, entry)] += qty
        expected_close[(exit_row, -side, exit_price)] += qty
        cycles[campaign] += pnl
    for key in FIELDS:
        close(totals[key], row[key], key)
    assert len(cycles) == row['cycles']
    assert sum(x > 0 for x in cycles.values()) == row['cycle_wins']
    assert sum(x < 0 for x in cycles.values()) == row['cycle_losses']
    assert sum(totals[k] for k in FIELDS[3:]) == row['closed_units']
    actual_open, actual_close = Counter(), Counter()
    holdings, maxima = {-1:0., 1:0.}, {-1:0., 1:0.}
    earlier = -1
    for order in ledger['orders']:
        execution, decision, _, side, qty, price, reason, kind = order
        assert 0 <= decision < execution and earlier <= execution
        earlier = execution
        assert qty >= 1 and qty == int(qty) and side in (-1, 1)
        if kind == 1:
            actual_open[(execution, side, price)] += qty
            holdings[side] += qty
            if reason == 20:
                assert qty == initial
        else:
            assert kind == 0
            actual_close[(execution, side, price)] += qty
            holdings[-side] -= qty
        for direction in (-1, 1):
            assert 0 <= holdings[direction] <= initial <= cap
            maxima[direction] = max(maxima[direction], holdings[direction])
    assert actual_open == expected_open and actual_close == expected_close
    assert holdings == {-1:0., 1:0.}
    assert maxima[1] == row['max_long'] and maxima[-1] == row['max_short']
    result = dict(方式=row['id'], セッション=row['session'], 銘柄=symbol, **totals,
                  返済脚数=len(ledger['trades']), 注文数=len(ledger['orders']),
                  価格数量会計一致=True, 注文と返済脚数量一致=True, 最終保有ゼロ=True,
                  全注文が判断行より後=True, 最大買い枚数=maxima[1], 最大売り枚数=maxima[-1])
    if ready is not None:
        count = len(ready['time_s'])
        cash_changes = np.zeros(count)
        position_changes = np.zeros(count)
        for order in ledger['orders']:
            execution, _, _, side, qty, price, _, _ = order
            index = int(execution)
            assert 0 <= index < count
            assert ready['start'] <= ready['time_s'][index] <= ready['limit']+600
            cash_changes[index] -= side*qty*price
            position_changes[index] += side*qty
        curve = (np.cumsum(cash_changes)+np.cumsum(position_changes)*ready['last'])*multiplier
        close(curve[-1], row['net_yen'], '期末時価')
        close(np.max(np.maximum.accumulate(curve)-curve), row['drawdown_yen'], '注文から時価下落')
        close(curve.min(), row['min_equity_yen'], '注文から時価最小')
        close(curve.max(), row['max_equity_yen'], '注文から時価最大')
        for preparation in ledger['prepare_events']:
            source = int(preparation[1])
            close(preparation[4], max(ready['atr'][source], 2*ready['tick']), '準備時にATR固定')
        result.update(全行時価を独立再構成=True, 場内注文と完済=True,
                      準備行の利用可能ATR一致=True,
                      最終返済時刻=datetime.fromtimestamp(ready['time_s'][int(ledger['orders'][-1][0])]).isoformat())
    return result


def combined(rows: list[dict]) -> dict:
    """機能: セッション統計から合計と連結最大下落を独立に集計する。

    引数: rows(list[dict])。返り値: 概要(dict)。
    """
    result = {key: sum(r[key] for r in rows) for key in FIELDS}
    net, peak, drawdown = 0., 0., 0.
    for row in sorted(rows, key=lambda r:r['session']):
        drawdown = max(drawdown, row['drawdown_yen'], peak-(net+row['min_equity_yen']))
        peak = max(peak, net+row['max_equity_yen'])
        net += row['net_yen']
    result.update(win_sessions=sum(r['net_yen'] > 0 for r in rows), session_count=len(rows),
                  average_unit_payoff=(result['gross_profit_yen']/result['profit_units'])/(result['gross_loss_yen']/result['loss_units']),
                  drawdown_yen=drawdown, cycle_win_rate=sum(r['cycle_wins'] for r in rows)/sum(r['cycles'] for r in rows))
    for name, selected in [('first_week',[r for r in rows if r['session'][:10] <= '2026-09-25']),
                           ('second_week',[r for r in rows if r['session'][:10] >= '2026-09-28'])]:
        result[name] = {key: sum(r[key] for r in selected) for key in FIELDS}
    return result


def check_display(data: dict, expected: dict) -> dict:
    """機能: 報告JSONとHTML全セルを会計元の16場・週・総計へ照合する。

    引数: data/expected(dict)。返り値: 表示照合証跡(dict)。
    """
    assert data['対象セッション数'] == 16 and data['会計入力数'] == 128
    assert read(WORK/'追加結果一覧.json') == read(BACKUP/'追加結果一覧.json')+[HERE.name]
    assert data['数量前提'] == read(BACKUP/'報告データ.json')['数量前提']
    assert data['HTML_SHA256'] == sha(HTML)
    assert [m['spec']['id'] for m in data['候補']] == list(IDS)
    soup = BeautifulSoup(HTML.read_text(encoding='utf-8'), 'html.parser')
    assert len(soup.select('.panel')) == len(soup.select('[data-tab]')) == 4
    rows_checked = cells_checked = 0
    for candidate in data['候補']:
        identifier = candidate['spec']['id']
        rows = expected[identifier]
        assert sorted(candidate['sessions'], key=lambda r:(r['session'],r['symbol'])) == sorted(rows, key=lambda r:(r['session'],r['symbol']))
        names = sorted({r['session'] for r in rows})
        assert len(names) == 16 and names[-1] == SESSION
        overview = {s:combined([r for r in rows if r['symbol'] == s]) for s in SYMBOLS}
        for symbol in SYMBOLS:
            for key, value in overview[symbol].items():
                if isinstance(value, dict):
                    for inner in value:
                        close(candidate['overview'][symbol][key][inner], value[inner], key+'/'+inner)
                else:
                    close(candidate['overview'][symbol][key], value, key)
        periods = [{s:next(r for r in rows if r['session'] == n and r['symbol'] == s) for s in SYMBOLS} for n in names]
        periods += [{s:overview[s][week] for s in SYMBOLS} for week in ('first_week','second_week')]
        periods.append(overview)
        for kind, fields in [('money',FIELDS[:3]),('units',FIELDS[3:])]:
            table = soup.select_one(f'table[data-method="{identifier}"][data-kind="{kind}"]')
            actual_rows = table.select('tbody tr')
            assert len(actual_rows) == len(periods) == 19
            for index, (tr, values) in enumerate(zip(actual_rows, periods)):
                assert int(tr['data-row']) == index
                cells = tr.select('td[data-value]')
                assert len(cells) == 6
                for cell in cells:
                    symbol, field = cell['data-symbol'], cell['data-field']
                    assert symbol in SYMBOLS and field in fields
                    value = values[symbol][field]
                    close(float(cell['data-value']), value, 'HTML原値')
                    visible = float(cell.get_text(strip=True).replace(',','').replace('−','-'))
                    close(visible, value, 'HTML表示文字')
                    cells_checked += 1
                rows_checked += 1
    return dict(報告JSON全128口座一致=True, HTML数値全一致=True,
                HTML対象行数=rows_checked, HTML数値セル数=cells_checked,
                週別と全期間の利益損失収支と枚数一致=True, 全期間の勝率比率最大下落一致=True)


def inspect_basis(inputs: dict) -> tuple[dict, dict]:
    """機能: 固定コード・入力公開順・既存因果検査の完備を照合する。

    引数: inputs(dict)。返り値: 基礎監査と参照指紋(tuple[dict,dict])。
    """
    fixed = read(HERE/'固定.json')
    complete = read(HERE/'complete.json')
    extraction = read(HERE/'入力監査.json')
    signals = read(HERE/'信号監査.json')
    assert complete['全合格'] and extraction['全合格'] and signals['全合格']
    assert complete['固定SHA256'] == sha(HERE/'固定.json')
    assert complete['対象'] == SESSION and complete['新口座数'] == 8 and complete['旧再現口座数'] == 8
    assert not fixed['条件変更'] and not complete['条件変更']
    assert [s['id'] for s in fixed['条件']] == list(IDS)
    references = dict(complete['出力SHA256']) | extraction['出力SHA256'] | fixed['実装SHA256']
    references.update(read(BACKUP/'報告データ.json')['参照SHA256'])
    references.update({name:value for name,value in fixed['原本SHA256'].items() if SESSION in name})
    references.update({p.relative_to(ROOT).as_posix():sha(p) for p in
                       (HERE/'固定.json',HERE/'complete.json',Path(__file__),BACKUP/'報告データ.json')})
    references.update(fixed.get('既存追加参照SHA256', {}))
    references = {Path(name).as_posix(): value for name, value in references.items()}
    for name in list(references):
        if ROOT/name == WORK/'追加結果一覧.json':
            references[(BACKUP/'追加結果一覧.json').relative_to(ROOT).as_posix()] = references.pop(name)
    for name, fingerprint in references.items():
        assert sha(ROOT/name) == fingerprint, name
    frames = pickle.loads((HERE/'new_features_depth.pkl').read_bytes())
    assert set(frames) == set(inputs)
    source_count = 0
    for key, frame in frames.items():
        ready = inputs[key]
        assert np.all(np.diff(ready['seq']) > 0) and np.all(np.diff(ready['time_s']) >= 0)
        assert (frame.source_time_s < frame.time_s).all()
        assert (frame.source_first_seq <= frame.source_last_seq).all()
        assert (frame.source_last_seq < frame.seq).all()
        rows = np.searchsorted(ready['seq'], frame.seq.to_numpy(), side='left')
        np.testing.assert_array_equal(ready['seq'][rows],frame.seq.to_numpy())
        np.testing.assert_array_equal(ready['time_s'][rows],frame.time_s.to_numpy())
        source_count += len(frame)
    assert len(signals['検査']) == 2
    for proof in signals['検査']:
        assert proof['session'] == SESSION and proof['信号数'] == 3
        assert all(proof[k] for k in ('切断一致','未来変更一致','上下反射一致','同秒順一致'))
    causal_count = 0
    for identifier in IDS:
        done = read(HERE/'completed'/(identifier+'.json'))
        assert done['全合格'] and done['新因果監査数'] == done['新監査数'] == 2
        assert len(done['旧再現照合']) == 2
        for prior in done['旧再現照合']:
            assert prior['全実口座指紋一致'] and prior['両仮想運転指紋一致']
        proofs = read(HERE/'audits'/(identifier+'.json.gz'))
        assert {(r['session'],r['symbol']) for r in proofs} == set(inputs)
        for proof in proofs:
            assert all(proof[k] for k in ('全分岐独立一致','全伝達遅延一致','全枠会計一致','全予約と新根拠一致',
                                         '元終了以前','同約定両建て全行一致','全予算予約一致','全初回同値',
                                         '実退出が短縮影以前','短縮影が通常影以前'))
            causal = proof['因果']
            assert all(causal[k] for k in ('先頭切断一致','未来変更一致','上下反射一致','元影と短縮影と許可を再生成'))
            assert 0 < causal['切断行'] < causal['未来変更行'] < len(inputs[proof['session'],proof['symbol']]['last'])
            causal_count += 1
    quality = [{'symbol':r['symbol'], '保存足と生板再集計':r['足一致']} for r in extraction['原本監査']]
    return dict(固定方式と実装指紋一致=True, 公開特徴の全源が公開前=True,
                公開特徴確認数=source_count, 入口途中素材因果証跡数=6,
                旧8口座の実口座と二影の完全再現証跡=True, 新8口座の統合因果証跡数=causal_count,
                保存足と原本の診断=quality,
                診断の限界='保存足と生板からの足再集計の一致数は上記診断を参照。旧仕様どおり保存1分足と保存5分足を信号へ使い、原本CurrentPriceを売買価格へ使う。'), references


def main() -> None:
    """機能: 追加口座、旧会計不変、更新表示を順に確認して独立証跡を書く。

    引数: --results/--inputs(Path)、--account-only(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, default=HERE)
    parser.add_argument('--inputs', type=Path, default=HERE/'new_inputs.pkl')
    parser.add_argument('--account-only', action='store_true')
    args = parser.parse_args()
    inputs = pickle.loads(args.inputs.read_bytes())
    inputs = {k:v for k,v in inputs.items() if k[0] == SESSION}
    assert set(inputs) == {(SESSION,s) for s in SYMBOLS}
    atr_proofs = [independent_atr(inputs[SESSION,s]) for s in SYMBOLS]
    basis, references = inspect_basis(inputs)
    old_data = read(BACKUP/'報告データ.json')
    for name, expected_sha in old_data['参照SHA256'].items():
        original = ROOT/name
        if original == WORK/'追加結果一覧.json':
            original = BACKUP/'追加結果一覧.json'
        assert sha(original) == expected_sha, name
    all_rows, accounting = {}, []
    for identifier in IDS:
        old_rows, old_ledgers = [], []
        for stage in ('exit_integration','integration_followup/new'):
            old_rows += read(OLD/stage/'sessions'/(identifier+'.json.gz'))
            old_ledgers += read(OLD/stage/'ledgers'/(identifier+'.json.gz'))
        old_rows += read(PRIOR/'sessions'/(identifier+'.json.gz'))
        old_ledgers += read(PRIOR/'ledgers'/(identifier+'.json.gz'))
        baseline = next(m for m in old_data['候補'] if m['spec']['id'] == identifier)
        assert baseline['sessions'] == old_rows
        new_rows = read(args.results/'sessions'/(identifier+'.json.gz'))
        new_ledgers = read(args.results/'ledgers'/(identifier+'.json.gz'))
        assert len(new_rows) == len(new_ledgers) == 2
        assert {(r['session'],r['symbol']) for r in new_rows} == set(inputs)
        for row in old_rows+new_rows:
            ledger = next(l for l in old_ledgers+new_ledgers if l['session'] == row['session'] and l['symbol'] == row['symbol'])
            previous = next(l for l in old_ledgers if l['symbol'] == row['symbol'])
            assert ledger['config'] == previous['config'], '固定条件からの変更を検出'
            accounting.append(account(ledger,row,inputs.get((row['session'],row['symbol']))))
        all_rows[identifier] = old_rows+new_rows
    assert len(accounting) == 128
    latest = [r for r in accounting if r['セッション'] == SESSION]
    proof = dict(全合格=True, 追加セッション=SESSION, 固定4方式順序=list(IDS),
                 旧15場120口座不変=True, 旧参照24資料SHA256一致=True,
                 新会計入力数=len(latest), 会計再計算数=len(accounting),
                 全返済脚数=sum(r['返済脚数'] for r in accounting),
                 固定設定全一致=True, 利用可能ATRの別式監査=atr_proofs,
                 新セッション独立会計=latest, 原本API取得数=0,
                 入力と固定再生の独立点検=basis, 参照SHA256=references,
                 監査コードSHA256=sha(Path(__file__)), 入力SHA256=sha(args.inputs))
    if not args.account_only:
        data = read(WORK/'報告データ.json')
        proof.update(check_display(data,all_rows), HTML_SHA256=sha(HTML), 報告データSHA256=sha(WORK/'報告データ.json'))
    name = '独立会計確認' if args.account_only else '独立確認'
    (HERE/(name+'.json')).write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 追加ナイトとレポート更新の独立確認', '',
             '固定4方式を2026年9月30日ナイトへ適用した結果を確認しました。条件・初回枚数・上限・倍率は旧台帳と全項目一致です。', '',
             '- 旧15セッションの120口座と元24資料の指紋は不変。',
             '- 全返済脚を「返済価格－新規価格」×方向×枚数×倍率で再計算し、利益・損失・収支・延べ返済枚数が一致。',
             '- 注文と返済脚の数量を別集計し、すべての注文は判断行より後。TOPIX初回5枚／上限10枚、NK初回10枚／上限20枚以内で、最後の建玉はゼロ。',
             '- 追加8口座は注文の現金出入りと保有枚数から全行の時価を独立復元。期末収支・最大下落・時価最小／最大も一致。全注文と返済は当該セッション内。',
             '- 保存5分足からTRとATRを逐次計算し直し、足開始360秒後に利用可能とした全観測ATRが一致。注文準備時に固定したATRも一致。']
    if not args.account_only:
        lines += ['- 更新JSONの全128口座と、HTMLの16場・第1週・第2週・全期間、全152行912数値セルが一致。勝つセッション数・平均勝ち枚利益／平均負け枚損失・連結最大下落も別集計で一致。']
    lines += ['- 公開板特徴の元時刻・元行はすべて公開時刻・公開行より前。旧8口座の完全再現、入口／途中素材の切断・未来改変・反射・同秒順、追加8口座の二つの影を含む統合因果検査について、実装・結果・指紋の接続を確認。',
              '', '原本診断の保存足と生板再集計の一致状況は独立確認JSONに収録しています。旧仕様どおり入口は保存1分足、ATRは保存5分足、売買価格は生板CurrentPriceを使用しており、今回だけ異なる系列へ置換していません。']
    lines += ['', '| 手法 | TOPIXミニ収支 | NK225マイクロ収支 |', '|---|---:|---:|']
    for identifier in IDS:
        values = {r['銘柄']:r['net_yen'] for r in latest if r['方式'] == identifier}
        lines.append(f"| {identifier} | {values['TOPIX']:+,.0f}円 | {values['NK225']:+,.0f}円 |")
    lines += ['', '費用0・指定価格約定を用いた保存データの再現です。現在セッションAPI取得、条件探索、旧資料の上書きは行っていません。', '',
              '確認スクリプト：[audit_update.py](audit_update.py)。詳細証跡：['+name+'.json]('+name+'.json)。']
    (HERE/(name+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({k:proof[k] for k in ('全合格','新会計入力数','会計再計算数','全返済脚数')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
