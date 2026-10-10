"""外部通信を禁止して一回照合器の凍結・取得記録・検査拒否を点検する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
from unittest.mock import patch

import current_check as current
import data

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def write(path: Path, value: object) -> None:
    """機能: 試験領域へJSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def reject(function, exceptions: tuple[type, ...] = (ValueError, RuntimeError, FileExistsError)) -> None:
    """機能: 異常入力が確実に拒否されることを確認する。

    引数: function (callable)、exceptions (tuple[type,...])。返り値: なし (None)。
    """
    try:
        function()
    except exceptions:
        return
    raise AssertionError('異常入力が拒否されませんでした')


def candle(symbol: str, minutes: int, session: str, start: datetime, end: datetime,
           cutoff: datetime) -> dict:
    """機能: 所属検査に使う足APIの人工応答を作る。

    引数: symbol/session (str)、minutes (int)、start/end/cutoff (datetime)。
    返り値: 人工JSON応答 (dict)。
    """
    return dict(snapshot=dict(code=symbol, sessionId=session, asOf=cutoff.isoformat(),
                             session=dict(startsAt=start.isoformat(), endsAt=end.isoformat())),
                data=[dict(time=start.isoformat(), open=100., high=110., low=90., close=100.,
                           volume=1, closed=True, volumeComplete=True)])


def setup_trial(path: Path) -> dict:
    """機能: 本番の選択や原本を使わない凍結用の仮環境を作る。

    引数: path (Path)。返り値: 人工設定 (dict)。
    """
    path.mkdir(parents=True, exist_ok=True)
    for name in current.LOCAL_FILES:
        (path / name).write_text('通信なし試験用の固定対象\n', encoding='utf-8')
    config = dict(id='試験条件', family='試験', max_legs=1, entry_mode='market',
                  initial_stop_atr=1., trail_atr=None)
    write(path / '条件一覧.json', [config])
    write(path / '最終選択.json', dict(照合ID=['試験条件'], 主候補={symbol: dict(採用=dict(方式='試験条件'))
                                                                       for symbol in current.SYMBOLS}))
    write(path / '信号条件一覧.json', [])
    rows = []
    for symbol in current.SYMBOLS:
        item = dict(セッション=data.HOLDOUT, 銘柄=symbol)
        for key in ('生板', '1分足', '5分足'):
            source = path / '仮保留原本' / f'{symbol}_{key}.txt'
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('保留原本の人工内容', encoding='utf-8')
            item[key] = dict(原本=source.relative_to(ROOT).as_posix(), SHA256=current.sha256(source))
        rows.append(item)
    write(path / '原本メタ監査.json', rows)
    return config


def main() -> None:
    """機能: 通信経路を禁止し、正常・異常・再実行拒否を検査して結果を保存する。

    引数: なし。返り値: なし (None)。
    """
    original_import = data.import_module
    helper = original_import(ROOT / 'work/wave_v7/fetch_once.py', 'v13_offline_fetch_helper')
    base = OUT / '照合器_通信なし試験' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    assert base.resolve().is_relative_to(OUT.resolve())
    clock = datetime.fromisoformat('2026-09-24T23:10:25+09:00')
    fixed = datetime.fromisoformat('2026-09-24T23:09:00+09:00')
    results = []
    calls = []
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('通信は禁止されています')):
        # ----------------------------------------
        # 日付またぎ、休止時間、境界はAPIなしで時計から確定する。
        valid = [('2026-09-24T08:45:00+09:00', '2026-09-24_Day'),
                 ('2026-09-24T15:44:59+09:00', '2026-09-24_Day'),
                 ('2026-09-24T17:00:00+09:00', '2026-09-24_Night'),
                 ('2026-09-25T05:59:59+09:00', '2026-09-24_Night')]
        for stamp, expected in valid:
            assert current.current_session(datetime.fromisoformat(stamp))[0] == expected
            results.append('時計所属:' + stamp)
        for stamp in ('2026-09-24T06:00:00+09:00', '2026-09-24T08:44:59+09:00',
                      '2026-09-24T15:45:00+09:00', '2026-09-24T16:59:59+09:00', '2026-09-24T23:10:00'):
            reject(lambda: current.current_session(datetime.fromisoformat(stamp)))
            results.append('時計拒否:' + stamp)
        trial = base / '正常取得'
        setup_trial(trial)
        live = trial / 'live'
        frozen_path = trial / '現在照合_凍結記録.json'
        with patch.multiple(current, OUT=trial, LIVE=live, FROZEN=frozen_path), patch.object(current, 'now_jst', return_value=fixed):
            frozen = current.freeze()
            assert current.freeze_check() == frozen
            reject(current.freeze)
            results.append('凍結と再凍結拒否')
            source = trial / 'catalog.py'
            saved = source.read_bytes()
            source.write_text('変更', encoding='utf-8')
            reject(current.freeze_check)
            source.write_bytes(saved)
            assert current.freeze_check() == frozen
            results.append('凍結コード改変拒否')
        session, start, end = current.current_session(clock)
        cutoff = clock.replace(second=0, microsecond=0)

        def fake_fetch(name: str, url: str, destination: Path) -> dict:
            """機能: 実通信の代わりに人工の板または足応答を保存する。

            引数: name/url (str)、destination (Path)。返り値: 一回要求記録 (dict)。
            """
            calls.append(name)
            symbol = name.split('_')[0]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith('_book'):
                row = dict(SymbolName='日経225先物' if symbol == 'NK225' else 'TOPIX先物',
                           Symbol='人工限月', CurrentPrice=100., CurrentPriceTime=start.isoformat(),
                           Buy1=dict(Price=90., Qty=1), Sell1=dict(Price=110., Qty=1))
                destination.write_text(json.dumps(row, ensure_ascii=False) + '\n', encoding='utf-8')
            else:
                minutes = int(name.rsplit('_', 1)[1].replace('min', ''))
                write(destination, candle(symbol, minutes, session, start, end, cutoff))
            return dict(name=name, url=url, path=destination.relative_to(ROOT).as_posix(), attempts=1,
                        ok=True, sha256=current.sha256(destination), http_status=200)

        helper.fetch_one = fake_fetch
        with patch.multiple(current, OUT=trial, LIVE=live, FROZEN=frozen_path), \
             patch.object(current, 'now_jst', return_value=clock), patch.object(data, 'import_module', return_value=helper):
            receipt = current.fetch()
            assert receipt['status'] == '取得と検査完了'
            assert len(calls) == 6 and len(set(calls)) == 6
            assert current.receipt_check(frozen) == receipt
            reject(current.fetch)
            assert len(calls) == 6
            results.append('六要求各一回と再取得拒否')
            destination = live / '応答' / 'NK225_1min.json'
            saved = destination.read_bytes()
            destination.write_text('{}', encoding='utf-8')
            reject(lambda: current.receipt_check(frozen))
            destination.write_bytes(saved)
            results.append('取得応答改変拒否')
        # ----------------------------------------
        # 変換器の所属・時刻検査を不正応答で直接点検する。
        for number, kind in enumerate(['銘柄', 'セッション', '開始', '終了', '古いasOf', '未確定だけ', '締切以降']):
            folder = base / f'異常足_{number}'
            response = candle('NK225', 1, session, start, end, cutoff)
            if kind == '銘柄':
                response['snapshot']['code'] = 'TOPIX'
            elif kind == 'セッション':
                response['snapshot']['sessionId'] = '2026-09-23_Night'
            elif kind == '開始':
                response['snapshot']['session']['startsAt'] = end.isoformat()
            elif kind == '終了':
                response['snapshot']['session']['endsAt'] = start.isoformat()
            elif kind == '古いasOf':
                response['snapshot']['asOf'] = start.isoformat()
            elif kind == '未確定だけ':
                response['data'][0]['closed'] = False
            else:
                response['data'][0]['time'] = cutoff.isoformat()
            path = folder / '足応答.json'
            write(path, response)
            helper.LIVE = folder
            reject(lambda: helper.convert_candles(path, 'NK225', 1, session, start, end, cutoff))
            results.append('足応答拒否:' + kind)
        for number, kind in enumerate(['銘柄', '締切以降', '逆行', '時差なし', '限月不一致', '価格列なし']):
            row = dict(SymbolName='日経225先物', Symbol='人工限月', CurrentPrice=100.,
                       CurrentPriceTime=start.isoformat(), Buy1={}, Sell1={})
            rows = [row.copy()]
            if kind == '銘柄':
                rows[0]['SymbolName'] = 'TOPIX先物'
            elif kind == '締切以降':
                rows[0]['CurrentPriceTime'] = cutoff.isoformat()
            elif kind == '逆行':
                rows = [dict(row, CurrentPriceTime='2026-09-24T18:00:00+09:00'), row.copy()]
            elif kind == '時差なし':
                rows[0]['CurrentPriceTime'] = '2026-09-24T18:00:00'
            elif kind == '限月不一致':
                rows.append(dict(row, Symbol='別限月'))
            else:
                del rows[0]['CurrentPrice']
            path = base / f'異常板_{number}.jsonl'
            path.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in rows), encoding='utf-8')
            reject(lambda: current.validate_book(path, 'NK225', start, cutoff))
            results.append('生板拒否:' + kind)
        # ----------------------------------------
        # 一つ失敗した場合も取得ロックが残り、二度目に六要求を出さない。
        trial = base / '一部失敗'
        setup_trial(trial)
        live = trial / 'live'
        frozen_path = trial / '現在照合_凍結記録.json'
        with patch.multiple(current, OUT=trial, LIVE=live, FROZEN=frozen_path), patch.object(current, 'now_jst', return_value=fixed):
            current.freeze()
        previous_count = len(calls)

        def failure_fetch(name: str, url: str, destination: Path) -> dict:
            """機能: 六件中の一要求が失敗する人工取得を作る。

            引数: name/url (str)、destination (Path)。返り値: 要求結果 (dict)。
            """
            calls.append(name)
            return dict(name=name, url=url, attempts=1, ok=False, error='人工障害')

        helper.fetch_one = failure_fetch
        with patch.multiple(current, OUT=trial, LIVE=live, FROZEN=frozen_path), \
             patch.object(current, 'now_jst', return_value=clock), patch.object(data, 'import_module', return_value=helper):
            reject(current.fetch)
            assert len(calls) == previous_count + 6
            reject(current.fetch)
            assert len(calls) == previous_count + 6
            record = json.loads((live / '取得記録.json').read_text(encoding='utf-8'))
            assert record['status'] == '失敗・再試行禁止'
            results.append('一部失敗後の再取得拒否')
    report = dict(合格=True, 検査数=len(results), 検査=results, 実通信回数=0,
                  ソースSHA256=hashlib.sha256((OUT / 'current_check.py').read_bytes()).hexdigest(),
                  人工環境=str(base.relative_to(ROOT)),
                  本番凍結=False, 保存保留原本価格読み込み=False, 現在API取得=False)
    write(OUT / '現在照合器_通信なし監査.json', report)
    print(json.dumps(dict(合格=True, 検査数=len(results), 実通信回数=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
