"""機能: 保存済み実運転台帳と固定E01の同日注文を読み取り専用で照合する。

引数: なし。返り値: なし。照合JSONを同じ監査フォルダへ保存する。
"""
from pathlib import Path
import csv
import gzip
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / 'アルゴリズム調査/00045_E01リアルタイム仮想トレード/運転記録'
REPLAY = ROOT / 'work/wave_v50/update_20261002_two'
SESSION = '2026-10-02_Day'
JST = ZoneInfo('Asia/Tokyo')
REASONS = {20: '追跡新規', 1: '組の損切り', 30: '順行後の悪化で半減', 2: '追跡返済'}


def timestamp(value: float) -> str:
    """機能: 秒の時計を日本時間の文字列へ変換する。

    引数: value(float) はUNIX秒。返り値: 日本時間のISO文字列(str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def audit() -> dict:
    """機能: 2台帳の注文内容、時計、初期ATR、収支を照合する。

    引数: なし。返り値: 注文照合と保存限界を含む監査結果(dict)。
    """
    with (LIVE / '売買記録.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = [row for row in csv.DictReader(handle) if row['セッション'] == SESSION]
    with gzip.open(REPLAY / 'ledgers/E01.json.gz', 'rt', encoding='utf-8') as handle:
        old = [row for row in json.load(handle) if row['session'] == SESSION]
    result = {'対象': SESSION, '注文照合': [], '銘柄別収支': {}, '初期ATR': []}
    for account in old:
        symbol = account['symbol']
        live = [row for row in rows if row['参照銘柄'] == symbol]
        source = REPLAY / f'prepared/{SESSION}/features/約定系列_{symbol}_{SESSION}.npz'
        times = np.load(source)['time_s']
        assert len(live) == len(account['orders'])
        for actual, expected in zip(live, account['orders']):
            item = {'銘柄': symbol, '実台帳ID': int(actual['記録ID']),
                    '区分': actual['区分'], '売買': actual['売買'], '枚数': int(actual['枚数']),
                    '実受信時刻': actual['記録時刻'], '実市場時刻': actual['市場価格時刻'],
                    '歴史市場時刻': timestamp(times[int(expected[0])]),
                    '実価格': float(actual['約定価格']), '歴史価格': expected[5],
                    '理由': actual['理由']}
            item['方向枚数理由一致'] = (int(actual['枚数']) == int(expected[4])
                and actual['売買'] == ('買い' if expected[3] > 0 else '売り')
                and actual['区分'] == ('新規' if expected[7] else '返済')
                and actual['理由'] == REASONS[int(expected[6])])
            item['価格一致'] = item['実価格'] == item['歴史価格']
            item['市場時刻差秒'] = (datetime.fromisoformat(actual['市場価格時刻']).timestamp()
                                  - float(times[int(expected[0])]))
            result['注文照合'].append(item)
        result['銘柄別収支'][symbol] = {
            '実運転円': sum(float(row['確定損益円']) for row in live),
            '歴史検証円': sum(row[10] * account['config']['point_value'] for row in account['trades'])}
        entries = [row for row in live if row['区分'] == '新規']
        for actual, cycle in zip(entries, account['cycles']):
            result['初期ATR'].append({'銘柄': symbol, '組番号': int(actual['組番号']),
                '実運転': float(actual['初期ATR']), '歴史検証': cycle[5],
                '完全一致': float(actual['初期ATR']) == cycle[5]})
    # ----------------------------------------
    # 正本は読み取り専用で開き、保存している情報の範囲を確認する。
    uri = (LIVE / '状態と売買.sqlite3').resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        result['正本イベント種類'] = db.execute('SELECT kind,count(*) FROM events GROUP BY kind').fetchall()
        state = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
        result['正本の最新状態セッション'] = state['session']['id']
        db_rows = [json.loads(row[0]) for row in db.execute("SELECT body FROM events WHERE kind='trade' ORDER BY id")]
        db_rows = [row for row in db_rows if row['セッション'] == SESSION]
        result['CSVと正本の当日全取引一致'] = (len(rows) == len(db_rows) and all(
            all(str(value) == actual.get(key) for key, value in expected.items())
            for actual, expected in zip(rows, db_rows)))
    result['差の根拠'] = {
        '銘柄': 'NK225', '組番号': 2,
        '歴史準備時刻': '2026-10-02T11:45:34+09:00',
        '歴史初期ATR': 108.5895973080024,
        '歴史ATRに含む最終5分足': '2026-10-02T11:35:00+09:00',
        '実運転初期ATR': 102.04046419900219,
        '実ATRに含む最終5分足': '2026-10-02T11:40:00+09:00',
        '確定した原因': '初期ATRが異なるため0.75ATR損切り価格が1呼値異なる',
        '未確定の原因': '実運転が1本新しいATRを固定した時点の準備判断過程。全受信・準備履歴は残らず断定できない',
        '保存仕様': 'eventsは売買/稼働記録のみ。stateは最新1行を上書き。Dayの全特徴量履歴は残っていない'}
    result['集計'] = {
        '照合注文数': len(result['注文照合']),
        '方向枚数理由一致数': sum(row['方向枚数理由一致'] for row in result['注文照合']),
        '価格一致数': sum(row['価格一致'] for row in result['注文照合']),
        '市場時刻一致数': sum(row['市場時刻差秒'] == 0 for row in result['注文照合']),
        '初期ATR一致組数': sum(row['完全一致'] for row in result['初期ATR'])}
    return result


if __name__ == '__main__':
    output = audit()
    Path(__file__).with_suffix('.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output['集計'], ensure_ascii=False))
    print(json.dumps(output['銘柄別収支'], ensure_ascii=False))
    print('CSVと正本一致:', output['CSVと正本の当日全取引一致'])
