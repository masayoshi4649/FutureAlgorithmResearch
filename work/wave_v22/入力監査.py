"""追加２セッションの読取専用原本と固定条件の損益会計を独立に照合する。"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SESSIONS = ['2026-09-28_Night', '2026-09-29_Day']
SYMBOLS = ['TOPIX', 'NK225']
JST = ZoneInfo('Asia/Tokyo')
MULTIPLIERS = {'TOPIX': 1000., 'NK225': 10.}
sys.dont_write_bytecode = True


def save(name: str, value: dict) -> None:
    """機能: 監査結果を新しい作業フォルダへ保存する。

    引数: name (str): ファイル名。value (dict): 監査結果。
    返り値: None。
    """
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def bounds(session: str) -> tuple[datetime, datetime]:
    """機能: 既存評価と同じ監視区間の開始・排他的終了を定義する。

    引数: session (str): セッション識別子。
    返り値: tuple[datetime, datetime]: 開始日時・終了日時。
    """
    date = datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    if session.endswith('Day'):
        return date + timedelta(hours=8, minutes=45), date + timedelta(hours=15, minutes=40)
    return date + timedelta(hours=17), date + timedelta(days=1, hours=5, minutes=55)


def input_audit() -> None:
    """機能: 原本の時刻範囲、足の欠落・混入、生板から再構成した足との差異を確認する。

    引数: なし。
    返り値: None。結果を入力監査.jsonへ保存する。
    """
    specification = importlib.util.spec_from_file_location('read_only_v13_data_audit', ROOT / 'work/wave_v13/data.py')
    source = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(source)
    rows = []
    for session in SESSIONS:
        start, end = bounds(session)
        for symbol in SYMBOLS:
            book, raw = source.scan_book(ROOT / 'book' / symbol / f'{session}.jsonl', collect_prices=True)
            stamps = pd.DatetimeIndex(pd.to_datetime(raw['stamps']))
            valid = stamps.notna() & np.isfinite(raw['last'])
            inside = valid & (stamps >= start) & (stamps < end)
            actual = stamps[inside]
            differences = np.diff(actual.as_unit('ns').asi8) / 1e9
            pre = valid & (stamps < start)
            post = valid & (stamps >= end)
            row = dict(セッション=session, 銘柄=symbol, 生板=book,
                       有効価格行数=int(inside.sum()), 評価区間最初=str(actual.min()), 評価区間最後=str(actual.max()),
                       評価区間最大時刻空白秒=float(differences.max(initial=0)),
                       開始前価格行数=int(pre.sum()), 終了以降価格行数=int(post.sum()),
                       開始前価格時刻例=sorted(set(stamps[pre].astype(str)))[:5],
                       終了以降価格時刻例=sorted(set(stamps[post].astype(str)))[:5],
                       原本開始終了充足=bool(actual.min() < start + timedelta(minutes=1) and actual.max() >= end - timedelta(minutes=1)))
            series = pd.Series(raw['last'][inside], index=actual)
            for interval in (1, 5):
                path = ROOT / f'candle_{interval}min' / symbol / f'{session}.csv'
                frame = pd.read_csv(path)
                frame.index = pd.to_datetime(frame.time)
                expected = pd.date_range(start, end - timedelta(minutes=interval), freq=f'{interval}min')
                current = frame[(frame.index >= start) & (frame.index < end)]
                rebuilt = series.resample(f'{interval}min').ohlc().dropna()
                common = current.index.intersection(rebuilt.index)
                diff = current.loc[common, ['open', 'high', 'low', 'close']] - rebuilt.loc[common, ['open', 'high', 'low', 'close']]
                mismatch = ~np.isclose(diff, 0, atol=1e-8).all(axis=1)
                row[f'{interval}分足'] = dict(source.candle_metadata(path), 期待足数=len(expected),
                    評価区間足数=len(current), 欠落時刻=expected.difference(current.index).astype(str).tolist(),
                    評価区間外時刻=frame.index.difference(expected).astype(str).tolist(),
                    生板再集計に存在して保存足にない時刻=rebuilt.index.difference(current.index).astype(str).tolist(),
                    保存足に存在して生板再集計にない時刻=current.index.difference(rebuilt.index).astype(str).tolist(),
                    共通足数=len(common), OHLC不一致足数=int(mismatch.sum()),
                    差異=[dict(時刻=str(stamp), 差={key: float(value) for key, value in diff.loc[stamp].items() if abs(value) > 1e-8}) for stamp in common[mismatch]])
            rows.append(row)
            print(session, symbol, row['有効価格行数'], flush=True)
    passed = all(row['原本開始終了充足'] and row['生板']['時刻逆行数'] == 0 and
                 all(not row[f'{interval}分足']['欠落時刻'] and row[f'{interval}分足']['足時刻昇順'] and
                     row[f'{interval}分足']['足時刻重複数'] == 0 for interval in (1, 5)) for row in rows)
    supported = all(row['原本開始終了充足'] and row['生板']['時刻逆行数'] == 0 and
                    all(not row[f'{interval}分足']['生板再集計に存在して保存足にない時刻'] and
                        not row[f'{interval}分足']['保存足に存在して生板再集計にない時刻'] and
                        row[f'{interval}分足']['足時刻昇順'] and row[f'{interval}分足']['足時刻重複数'] == 0
                        for interval in (1, 5)) for row in rows)
    save('入力監査.json', dict(監査日時=datetime.now(JST).isoformat(), 全分に連続した保存足あり=passed,
        セッション両端と原本価格がある足の網羅合格=supported,
        原本変更=False, API取得回数=0, 注記='生板のCurrentPriceTimeを用いた足の再集計は配信時刻・足確定処理との差異を含み得る。差異は記録し、そのまま一致扱いにはしない。保存足のない時刻は原本の有効な価格時刻にも存在しない。この確認だけで無約定と配信欠損を識別することはできない。開始前の前セッション価格は評価から除外する。', 行=rows))


def pnl_audit() -> None:
    """機能: 売買方向・建値・返済値から金額と枚数を再計算し公開台帳と突合する。

    引数: なし。
    返り値: None。結果を損益監査.jsonへ保存する。
    """
    ledger = json.loads((ROOT / 'M3_逆_A00_360分版/セッション損益.json').read_text(encoding='utf-8'))
    inputs = json.loads((OUT / '入力監査.json').read_text(encoding='utf-8'))
    rows = []
    for session in SESSIONS:
        start, end = bounds(session)
        replay = json.loads((ROOT / 'work/wave_v21' / session / '再生記録.json').read_text(encoding='utf-8'))
        independent_hashes = {}
        for source in inputs['行']:
            if source['セッション'] == session:
                for kind in ('生板', '1分足', '5分足'):
                    item = source[kind]
                    independent_hashes[Path(item['原本']).as_posix()] = item['SHA256']
        assert replay['source_hashes'] == independent_hashes
        for symbol in SYMBOLS:
            trades = [trade for trade in replay['trades'] if trade['symbol'] == symbol]
            amounts = []
            quantities = []
            for trade in trades:
                assert trade['side'] in ('買い', '売り')
                side = 1 if trade['side'] == '買い' else -1
                net = (trade['exit_price'] - trade['entry_price']) * side * trade['quantity'] * MULTIPLIERS[symbol]
                assert abs(net - trade['net_yen']) < .01
                assert trade['quantity'] == 1
                assert start <= datetime.fromisoformat(trade['entry_time']) < datetime.fromisoformat(trade['exit_time']) < end
                amounts.append(net)
                quantities.append(trade['quantity'])
            recomputed = dict(gross_profit_yen=sum(max(value, 0) for value in amounts),
                gross_loss_yen=-sum(min(value, 0) for value in amounts), net_yen=sum(amounts),
                profit_units=sum(q for p, q in zip(amounts, quantities) if p > 0),
                loss_units=sum(q for p, q in zip(amounts, quantities) if p < 0),
                zero_units=sum(q for p, q in zip(amounts, quantities) if p == 0), closed_units=sum(quantities), cycles=len(trades))
            recomputed['unit_balance'] = recomputed['profit_units'] - recomputed['loss_units']
            matches = [row for row in ledger['records'] if row['session'] == session and row['symbol'] == symbol]
            assert len(matches) == 1
            persisted = next(row for row in replay['records'] if row['symbol'] == symbol)
            assert all(abs(value - matches[0][name]) < .01 and abs(value - persisted[name]) < .01 for name, value in recomputed.items())
            assert replay['source_hashes'] == matches[0]['source_hashes']
            for before, after in zip(trades, trades[1:]):
                assert datetime.fromisoformat(before['exit_time']) < datetime.fromisoformat(after['entry_time'])
            rows.append(dict(セッション=session, 銘柄=symbol, 独立再計算=recomputed, 取引明細一致=True,
                             公開台帳一致=True, 監査原本SHA256一致=True, 場またぎなし=True, 固定一枚と非重複保有=True,
                             保有上限での収支=recomputed['net_yen'] * (10 if symbol == 'TOPIX' else 20)))
    save('損益監査.json', dict(監査日時=datetime.now(JST).isoformat(), 合格=True, 行=rows,
         注記='取引明細から独立に損益会計を照合した。シグナルと注文成立の全再実装ではない。'))
    print(json.dumps(rows, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    if '--損益' in sys.argv:
        pnl_audit()
    else:
        input_audit()
