"""凍結後の保存日中と一回取得した現在夜間を原本全行から会計監査する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import urllib.parse

import numpy as np
import pandas as pd

from audit_exact import close_equal, independent_accounting
import exact_engine

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def load(path: Path):
    """機能: 監査対象のJSONを読み込む。

    引数: path (Path)。返り値: object: 保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """機能: 読取専用でファイル全体のハッシュを返す。

    引数: path (Path)。返り値: str: SHA256。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_tape(source: Path, tape: dict) -> dict:
    """機能: キャッシュ現在価格を元JSONLの同じ行と全件照合する。

    引数: source (Path)、tape (dict)。返り値: dict: 価格・行番号検査の件数。
    """
    pointer, count = 0, 0
    for index, line in enumerate(source.open('rb')):
        count += 1
        if pointer >= len(tape['seq']) or index != tape['seq'][pointer]:
            continue
        row = json.loads(line)
        close_equal(float(row['CurrentPrice']), tape['last'][pointer])
        close_equal(datetime.fromisoformat(row['CurrentPriceTime']).timestamp(), tape['time_s'][pointer])
        pointer += 1
    assert pointer == len(tape['seq'])
    return dict(元原本行数=count, 現在価格と時刻の全行一致数=pointer)


def check_receipt(frozen: dict) -> dict:
    """機能: 保存された６要求の回数・共通締切・応答ハッシュを独立検査する。

    引数: frozen (dict)。返り値: dict: 成功した要求・ファイルの数。
    """
    receipt = load(OUT/'現在照合_取得記録.json')
    assert receipt['status'] == '取得と検査完了'
    assert receipt['manifest_sha256'] == digest(OUT/'現在照合_凍結記録.json')
    assert datetime.fromisoformat(receipt['started_at']) > datetime.fromisoformat(frozen['fixed_at'])
    assert receipt['selected_ids'] == frozen['selected_ids']
    assert len(receipt['requests']) == 6
    names = set()
    for request in receipt['requests']:
        assert request['ok'] and request['attempts'] == 1
        assert request['name'] not in names
        names.add(request['name'])
        url = urllib.parse.urlparse(request['url'])
        query = urllib.parse.parse_qs(url.query)
        assert query['from'] == [receipt['starts_at']] and query['to'] == [receipt['cutoff']]
        assert digest(ROOT/request['path']) == request['sha256']
    assert names == {f'{symbol}_{kind}' for symbol in ['NK225', 'TOPIX'] for kind in ['book', '1min', '5min']}
    for candle in receipt['candles']:
        assert digest(ROOT/candle['path']) == candle['sha256']
    assert len(receipt['candles']) == 4 and len(receipt['books']) == 2
    return dict(要求数=6, 各要求回数=1, 足CSV一致数=4, 共通排他的締切=receipt['cutoff'])


def check(prefix: str, frozen: dict) -> dict:
    """機能: 固定32セルの全脚を全原本価格へ再展開し、保存集計・曲線と照合する。

    引数: prefix (str): 保留日中または現在照合。frozen (dict): 凍結記録。
    返り値: dict: 全数会計・セッション境界の検査概要。
    """
    current = prefix == '現在照合'
    session = frozen['session'] if current else frozen['holdout_session']
    base = OUT/'live' if current else ROOT
    features = OUT/'live/features' if current else OUT/'features'
    summary = pd.read_csv(OUT/f'{prefix}_セッション集計.csv')
    trades = load(OUT/f'{prefix}_全取引.json')
    curves = load(OUT/f'{prefix}_資産曲線.json')
    record = load(OUT/f'{prefix}_評価記録.json')
    assert record['selected_ids'] == frozen['selected_ids']
    assert record['manifest_sha256'] == digest(OUT/'現在照合_凍結記録.json')
    assert record['session'] == session and set(summary['セッション']) == {session}
    assert set(summary['方式']) == set(frozen['selected_ids']) and len(summary) == 2*len(frozen['selected_ids'])
    if current:
        receipt = load(OUT/'現在照合_取得記録.json')
        cutoff = datetime.fromisoformat(receipt['cutoff']).timestamp()
        assert record['今回評価中の要求数'] == 0
    else:
        assert record['status'] == '固定条件の評価完了' and record['再選択'] is False
        assert datetime.fromisoformat(record['opened_at']) > datetime.fromisoformat(frozen['fixed_at'])
        cutoff = np.inf
    grouped = defaultdict(list)
    for trade in trades:
        grouped[(trade['方式'], trade['銘柄'])].append(trade)
    prepared, source_checks = {}, []
    for symbol in ['NK225', 'TOPIX']:
        tape = dict(np.load(features/f'約定系列_{symbol}_{session}.npz', allow_pickle=False))
        tape['symbol'] = symbol
        prepared[symbol] = tape
        assert tape['time_s'][-1] < cutoff
        assert np.all(np.diff(tape['seq']) > 0) and np.all(np.diff(tape['time_s']) >= 0)
        source_checks.append(dict(銘柄=symbol, **validate_tape(base/'book'/symbol/f'{session}.jsonl', tape)))
    configs = {cfg['id']: cfg for cfg in frozen['selected_configs']}
    attribute_checks = 0
    for row in summary.to_dict('records'):
        method, symbol = row['方式'], row['銘柄']
        records = grouped[(method, symbol)]
        raw = np.asarray([[t[name] for name in exact_engine.RAW_COLUMNS] for t in records], dtype=float).reshape((-1, len(exact_engine.RAW_COLUMNS)))
        ready = prepared[symbol]
        result = dict(raw=raw, summary=row, equity=np.asarray(curves[f'{method}|{session}|{symbol}']))
        attribute_checks += independent_accounting(ready, result)
        close_equal(row['cap_net_yen'], row['net_yen']/configs[method]['max_legs'])
        assert row['gross_peak'] <= configs[method]['max_legs']
        start, end = exact_engine.bounds(session)
        for t in records:
            assert start <= t['条件設定時刻'] <= t['新規時刻'] <= t['返済評価時刻'] < cutoff
            assert t['新規時刻'] < end-60*configs[method].get('entry_deadline_min', 30.)
            assert t['新規時刻'] >= start+60*configs[method].get('warmup_min', 20.)
            if t['返済済み']:
                assert t['返済評価時刻'] < end+300
                assert t['理由番号'] != 0
            else:
                assert current, '完全保留日中の末尾に未返済が残っている'
                close_equal(t['返済評価時刻'], ready['time_s'][-1])
                close_equal(t['返済評価価格'], ready['last'][-1])
                assert t['理由番号'] == 0
            close_equal(t['収支円'], t['方向']*(t['返済評価価格']-t['新規価格'])*exact_engine.MULTIPLIERS[symbol])
            if t['理由番号'] == 4:
                assert t['返済評価時刻'] >= end
    primary = []
    for symbol, method in frozen['selected_by_symbol'].items():
        row = summary[summary['銘柄'].eq(symbol) & summary['方式'].eq(method)].iloc[0]
        primary.append(dict(銘柄=symbol, 方式=method, 利益円=float(row.profit_yen), 損失円=float(row.loss_yen),
                            確定収支円=float(row.closed_net_yen), 含み損益円=float(row.open_yen),
                            含み込み収支円=float(row.net_yen), 未返済枚数=int(row.open_count)))
    return dict(区間=prefix, セッション=session, セル数=len(summary), 脚数=len(trades),
                全行会計照合項目数=attribute_checks, 原本価格監査=source_checks,
                未返済脚数=int(summary.open_count.sum()), 主候補=primary)


def main() -> None:
    """機能: 許可された凍結後データだけを監査し、コードと選択の不変も記録する。

    引数: CLIの--holdout-only (bool)。返り値: None: 独立監査JSONを保存する。
    """
    parser = argparse.ArgumentParser(description='凍結後の会計を通信せず独立照合')
    parser.add_argument('--holdout-only', action='store_true')
    args = parser.parse_args()
    frozen = load(OUT/'現在照合_凍結記録.json')
    for name, expected in frozen['files_sha256'].items():
        assert digest(ROOT/name) == expected
    for name, expected in frozen['holdout_inputs_sha256'].items():
        assert digest(ROOT/name) == expected
    helper = load(OUT/'現在照合器_通信なし監査.json')
    assert helper['合格'] and helper['検査数'] == 27 and helper['実通信回数'] == 0
    assert helper['ソースSHA256'] == digest(OUT/'current_check.py')
    results = [check('保留日中', frozen)]
    receipt = None
    if not args.holdout_only:
        receipt = check_receipt(frozen)
        results.append(check('現在照合', frozen))
    result = dict(成功=True, 凍結ファイル不変数=len(frozen['files_sha256']), 保留原本不変数=6,
                  照合器事前試験数=27, 固定条件数=len(frozen['selected_ids']),
                  固定時刻=frozen['fixed_at'], 会計=results, 一回取得記録=receipt,
                  監査中API取得数=0, 再選択=False)
    output = OUT/('保留日中_会計独立監査.json' if args.holdout_only else '固定照合_会計独立監査.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
