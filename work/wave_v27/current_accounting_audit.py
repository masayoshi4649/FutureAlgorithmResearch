"""一回保存した現在セッションを、条件変更・再取得なしで独立検算する。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import pickle
import socket
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import selected_accounting_audit as accounting
import current_validation as current

HERE = Path(__file__).resolve().parent
LIVE = HERE / 'live'
JST = ZoneInfo('Asia/Tokyo')


def stamp(value: float) -> str:
    """機能: 保存済みの観測秒を日本時間で表示する。

    引数: value (float) は UNIX 秒。返り値: 時刻文字列 (str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def file_hashes() -> dict:
    """機能: 保存領域の全ファイルについて実行前後の同一性を確認する準備をする。

    引数: なし。返り値: 相対パスと SHA256 (dict)。
    """
    return {p.relative_to(LIVE).as_posix(): accounting.runner.digest(p)
            for p in LIVE.rglob('*') if p.is_file()}


def describe_trades(ready: dict, replay: dict, symbol: str) -> tuple[list, list]:
    """機能: 元の返済明細と未返済玉の価格事実だけを整理する。

    引数: ready/replay (dict)、symbol (str)。返り値: 返済明細と残玉 (tuple[list,list])。
    事後の価格は原因説明にだけ使用し、売買条件の変更・別条件の実行は行わない。
    """
    result, remaining = [], []
    orders, trades = replay['orders'], replay['trades']
    for t in trades:
        entry_row, exit_row = int(t[6]), int(t[7])
        prices = ready['last'][entry_row:exit_row + 1]
        future = ready['last'][exit_row + 1:]
        favorable = int(t[2]) * (prices - t[4])
        at_or_better = np.flatnonzero(t[2] * (future - t[4]) >= 0)
        result.append({'新規時刻': stamp(ready['time_s'][entry_row]), '返済時刻': stamp(ready['time_s'][exit_row]),
                       '方向': '買い' if t[2] > 0 else '売り', '枚数': int(t[3]),
                       '新規価格': float(t[4]), '返済価格': float(t[5]),
                       '利益損失円': float(t[2] * t[3] * (t[5] - t[4]) * accounting.MULT[symbol]),
                       '理由': accounting.runner.engine.REASONS[int(t[9])],
                       '保有中最大順行pt': float(max(0., max(favorable))),
                       '保有中最大逆行pt': float(-min(0., min(favorable))),
                       '返済後の建値到達時刻': stamp(ready['time_s'][exit_row + 1 + at_or_better[0]]) if len(at_or_better) else None})
    for leg_id, order in enumerate(orders[orders[:, 7] == 1]):
        closed = int(sum(t[3] for t in trades if int(t[1]) == leg_id))
        qty = int(order[4]) - closed
        assert qty >= 0
        if qty:
            remaining.append({'元建玉': leg_id, '新規時刻': stamp(ready['time_s'][int(order[0])]),
                              '方向': '買い' if order[3] > 0 else '売り', '枚数': qty,
                              '新規価格': float(order[5]), '時価': float(ready['last'][-1]),
                              '含み損益円': float(order[3] * qty * (ready['last'][-1] - order[5]) * accounting.MULT[symbol])})
    return result, remaining


def main() -> None:
    """機能: 保存された全比較条件を再計算せず、約定・現金・残玉の整合を調べる。

    引数: なし。返り値: なし (None)。新規の監査 JSON・日本語 MD だけを保存する。
    """
    socket.socket.connect = accounting.reject_network
    socket.create_connection = accounting.reject_network
    urllib.request.OpenerDirector.open = accounting.reject_network
    before = file_hashes()
    record, frozen = current.verify_saved()
    saved = json.loads((LIVE / 'current_result.json').read_text(encoding='utf-8'))
    inputs = pickle.loads((LIVE / 'inputs.pkl').read_bytes())
    replay = pickle.loads((LIVE / 'replay.pkl').read_bytes())
    boundary = datetime.fromisoformat('2026-09-29T17:25:00+09:00').timestamp()
    cutoff = datetime.fromisoformat(saved['共通締切']).timestamp()
    expected_ids = {x['id'] for x in frozen['最終候補']}
    assert {key[0] for key in replay} == expected_ids
    assert len(replay) == len(expected_ids) * 2
    candles, rows = {}, []
    for symbol in accounting.MULT:
        candles[symbol] = {}
        for minutes in (1, 5):
            frame = pd.read_csv(LIVE / f'candle_{minutes}min' / symbol / (saved['セッション'] + '.csv'))
            assert frame.closed.dtype == bool and frame.closed.all()
            timestamps = pd.to_datetime(frame.time).map(lambda value: value.timestamp()).to_numpy()
            assert np.all(timestamps + minutes * 60 <= cutoff)
            candles[symbol][str(minutes)] = frame.to_dict(orient='records')
    # ----------------------------------------
    # 最終玉は返済扱いにせず、現金と時価で毎観測行を独立に復元する。
    for (identifier, symbol), result in replay.items():
        ready = inputs[(saved['セッション'], symbol)]
        assert ready['time_s'][-1] < cutoff < ready['limit']
        summary, independent = accounting.reconstruct(ready, result, symbol, closed=False)
        multiplier = accounting.MULT[symbol]
        trades, holdings = describe_trades(ready, result, symbol)
        realized = summary['net_yen']
        equity = float(independent['equity'][-1] * multiplier)
        floating = sum(x['含み損益円'] for x in holdings)
        accounting.close(realized + floating, equity, '確定と未決済の全玉合算')
        earlier = np.flatnonzero(ready['time_s'] < boundary)
        earlier_equity = float(independent['equity'][earlier[-1]] * multiplier) if len(earlier) else 0.
        expected = next(x for x in saved['結果'] if x['手法ID'] == identifier and x['銘柄'] == symbol)
        numbers = {'実現利益円': summary['gross_profit_yen'], '実現損失円': summary['gross_loss_yen'],
                   '実現収支円': realized, '含み損益円': floating, '合算損益円': equity,
                   '保有買い枚数': int(independent['long'][-1]), '保有売り枚数': int(independent['short'][-1]),
                   '利益決済枚数': summary['profit_units'], '損失決済枚数': summary['loss_units'],
                   '最大片方向保有枚数': max(summary['max_long'], summary['max_short']),
                   '新規約定件数': summary['新規注文数']}
        for name, value in numbers.items():
            accounting.close(value, expected[name], '保存済み現在表の' + name)
        suffix = next(x for x in saved['前回未読部分の増減'] if x['手法ID'] == identifier and x['銘柄'] == symbol)
        accounting.close([earlier_equity, equity - earlier_equity],
                         [suffix['17時25分時価損益円'], suffix['17時25分以降増減円']], '既読境界の時価増減')
        assert int(result['stats'][9]) == sum(x['枚数'] for x in holdings)
        assert not any(int(t[9]) == 9 for t in result['trades']), '21時の途中末尾を場末返済にしている'
        row = {'手法ID': identifier, '銘柄': symbol, **numbers,
               '決済合計枚数': summary['closed_units'], 'ゼロ損益決済枚数': summary['zero_units'],
               '17時25分時価損益円': earlier_equity, '17時25分以降増減円': equity - earlier_equity,
               '17時25分直前参照時刻': stamp(ready['time_s'][earlier[-1]]) if len(earlier) else None,
               '最終現金円': float(independent['cash'][-1] * multiplier),
               '原本最終時刻': stamp(ready['time_s'][-1]), '検算した観測行数': len(ready['last']),
               '返済明細': trades, '残玉': holdings, '全行会計一致': True, '架空返済なし': True}
        rows.append(row)
    for symbol in accounting.MULT:
        for name in ('orders', 'trades', 'cycles', 'curve', 'stats'):
            accounting.close(replay[('H019__D273', symbol)][name], replay[('H011__D273', symbol)][name],
                             '今回の主候補と副候補の売買結果')
    current.verify_saved()
    assert before == file_hashes(), '保存スナップショットが変わった'
    output = {'対象': '2026-09-29 ナイトの21:00締切・保存スナップショットのみ',
              '現在API取得': 0, '通信拒否': True, '候補条件変更': False, '売買再実行': False,
              '読み取った元の取得回数': len(record['requests']), '各URL一回': all(x['attempts'] == 1 for x in record['requests']),
              '全保存ファイルSHA256不変': before, '現在コード凍結SHA一致': True,
              '主副の注文返済曲線同一': True, '監査済み銘柄条件数': len(rows), '結果': rows,
              '価格事実の参照確定足': candles,
              '説明上の限界': '建値再到達など返済後の事実は事後説明のみ。損切りを避ける条件として検証・提案していない。',
              '監査コードSHA256': accounting.runner.digest(Path(__file__))}
    accounting.runner.save(HERE / 'current_accounting_audit.json', output)
    lines = ['# 現在保存データの独立会計監査', '',
             '主候補 H019__D273 と副候補 H011__D273 は、今回の全注文・返済・時価曲線が同一でした。',
             '2026年9月29日ナイト、21:00締切の途中結果です。現在APIの追加取得・候補変更・売買の再実行は行っていません。', '',
             '| 銘柄 | 確定利益 | 確定損失 | 確定収支 | 含み損益 | 合算 | 利益／損失決済枚数 | 残玉 |',
             '|---|---:|---:|---:|---:|---:|---:|---|']
    for symbol in accounting.MULT:
        row = next(x for x in rows if x['手法ID'] == 'H019__D273' and x['銘柄'] == symbol)
        lines.append(f"| {symbol} | {row['実現利益円']:,.0f}円 | {row['実現損失円']:,.0f}円 | {row['実現収支円']:,.0f}円 | {row['含み損益円']:+,.0f}円 | {row['合算損益円']:,.0f}円 | {row['利益決済枚数']}／{row['損失決済枚数']}枚 | 買い{row['保有買い枚数']}枚 |")
    lines += ['', '損失の中心は、18:46〜19:04台に入った売りが、短い反発で２回損切りになったことです。TOPIXは売り２回で−35,000円、NKは−15,000円でした。',
              '', 'TOPIXはさらに19:21の買い4066.5を、19:42に4063.0で損切りし−17,500円。５分足では19:25足の高値4068.5から19:50足の安値4060.5まで往復しており、この買いは20時台の回復前に離脱しました。20:11に4064.0で買い直し、２枚の部分利確＋13,000円と残り３枚の含み＋16,500円を得ましたが、先の３敗を埋め切っていません。',
              '', 'NKは19:22に65770で買った10枚を維持し、20:49に５枚を65910で部分利確して＋7,000円。残り５枚は65850の時価で＋4,000円ですが、先の売り２敗−15,000円を埋め切っていません。',
              '', '最初の売りは両銘柄とも18:47台の上振れで約１分で損切り。その後の18:55足にはTOPIX4061.5／NK65670まで下落したため、局所的な往復に振られたケースです。２回目の売りは19:10台の上昇で損切りしています。いずれも「長期下落が続いて損失」ではなく、方向保持と短期の上下動が噛み合わなかった事例です。',
              '', '17:25直前は両銘柄とも残玉・時価損益が０。したがって17:25以降の増減は合算損益と同じです。',
              '保存された比較条件も含む10区間すべてで、注文から復元した現金＋保有時価、全返済の枚数と損益、既読境界差額、片方向上限が一致しました。残玉を21:00に架空返済していません。',
              '事後の回復は原因説明であり、損切りを避ければよかったという条件変更や最適化は行っていません。保存領域全ファイルと凍結コードのSHA256は不変です。']
    (HERE / 'current_accounting_audit.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'独立会計通過': len(rows), '追加API取得': 0,
                      '主候補': [{k: v for k, v in row.items() if k in ('銘柄', '実現収支円', '含み損益円', '合算損益円', '決済合計枚数')}
                              for row in rows if row['手法ID'] == 'H019__D273']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
