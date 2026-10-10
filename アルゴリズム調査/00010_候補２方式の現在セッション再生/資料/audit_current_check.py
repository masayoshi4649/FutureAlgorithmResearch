"""人工の応答だけで今回ラッパーの境界・保存先・一回制限を検査する。"""

from datetime import datetime
import json
import pickle
import socket
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import current_check as current


def write(path, value):
    """機能: 試験領域へ日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def reject(function):
    """機能: 拒否するべき操作が例外になることを確認する。

    引数: function (callable)。返り値: なし (None)。
    """
    try:
        function()
    except (ValueError, RuntimeError, FileExistsError):
        return
    raise AssertionError('拒否が必要な操作が成功しました')


def source_row(symbol, stamp, value):
    """機能: 生板形式の人工データ１行を作る。

    引数: symbol/stamp (str)、value (float)。返り値: 原本形式 (dict)。
    """
    return dict(SymbolName='日経225先物' if symbol == 'NK225' else 'TOPIX先物', Symbol='人工限月',
        CurrentPrice=value, CurrentPriceTime=stamp, TradingVolume=10.,
        Buy1=dict(Price=value-10, Qty=1), Sell1=dict(Price=value+10, Qty=1))


def main():
    """機能: 人工環境で取得処理を代替し、通信を禁止したまま一連の接続を検査する。

    引数: なし。返り値: なし (None)。本番の凍結・通信・原本変更は行わない。
    """
    actual_out, actual_old = current.OUT, current.OLD
    base = actual_out / '通信なし試験' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out, old = base / '新作業', base / '前回'
    out.mkdir(parents=True)
    for name in current.LOCAL_FILES:
        (out / name).write_text('人工の固定対象\n', encoding='utf-8')
    write(old / '全条件一覧.json', current.selected_configs())
    write(old / 'live/取得記録.json', dict(session=current.SESSION, cutoff=current.KNOWN_CUTOFF, status='取得と検査完了'))
    for symbol in current.SYMBOLS:
        path = old / 'live/book' / symbol / f'{current.SESSION}.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(source_row(symbol, '2026-09-24T17:00:00+09:00', 100.), ensure_ascii=False)+'\n', encoding='utf-8')
    clock = datetime.fromisoformat('2026-09-25T03:01:25+09:00')
    session, start, end = current.LEGACY.current_session(clock)
    cutoff = clock.replace(second=0, microsecond=0)
    live, frozen_path = out / 'live', out / '現在照合_凍結記録.json'
    helper = current.source_module(current.ROOT / 'work/wave_v7/fetch_once.py', 'v15_offline_fetch_helper')
    calls, tests = [], []

    def fake_fetch(name, url, path):
        """機能: 六要求の代わりに人工の原本・足応答を一度保存する。

        引数: name/url (str)、path (Path)。返り値: 人工の取得記録 (dict)。
        """
        calls.append(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        symbol = name.split('_')[0]
        if name.endswith('_book'):
            original = old / 'live/book' / symbol / f'{session}.jsonl'
            suffix = json.dumps(source_row(symbol, '2026-09-25T03:00:00+09:00', 110.), ensure_ascii=False)+'\n'
            path.write_bytes(original.read_bytes()+suffix.encode('utf-8'))
        else:
            write(path, dict(snapshot=dict(code=symbol, sessionId=session, asOf=cutoff.isoformat(),
                session=dict(startsAt=start.isoformat(), endsAt=end.isoformat())),
                data=[dict(time=start.isoformat(), open=100., high=110., low=90., close=100., volume=10., closed=True, volumeComplete=True)]))
        return dict(name=name, url=url, path=path.relative_to(current.ROOT).as_posix(), attempts=1,
                    ok=True, http_status=200, sha256=current.sha256(path))

    helper.fetch_one = fake_fetch
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('試験中の実通信は禁止')):
        with patch.multiple(current, OUT=out, OLD=old, LIVE=live, FROZEN=frozen_path, DEPENDENCIES=[]), \
             patch.object(current, 'now_jst', return_value=clock):
            frozen = current.freeze()
            assert frozen['known_cutoff'] == current.KNOWN_CUTOFF
            assert frozen['selected_by_symbol'] == current.EXPECTED
            assert current.freeze_check() == frozen
            reject(current.freeze)
            tests.append('指定２条件と00:53境界の固定、再凍結拒否')
            code = out / 'run.py'
            contents = code.read_bytes()
            code.write_text('改変', encoding='utf-8')
            reject(current.freeze_check)
            code.write_bytes(contents)
            tests.append('実行コードの固定後変更拒否')
            catalog = old / '全条件一覧.json'
            original_catalog = catalog.read_bytes()
            changed = json.loads(original_catalog)
            changed[0]['entry_atr'] = 999
            write(catalog, changed)
            reject(current.freeze_check)
            catalog.write_bytes(original_catalog)
            tests.append('前回条件の数値変更拒否')
            with patch.object(current.reference.previous.data, 'import_module', return_value=helper):
                receipt = current.fetch()
                assert receipt['known_cutoff'] == current.KNOWN_CUTOFF
                assert len(calls) == 6 and len(set(calls)) == 6
                assert current.receipt_check(frozen) == receipt
                assert all(row['先頭バイト完全一致'] for row in current.known_prefix_check(frozen))
                reject(current.fetch)
                assert len(calls) == 6
                tests.append('人工６応答を各一回、再取得禁止、前回原本の先頭一致')
            file = live / 'book/NK225' / f'{session}.jsonl'
            contents = file.read_bytes()
            file.write_bytes(b' '+contents)
            reject(lambda: current.known_prefix_check(frozen))
            reject(lambda: current.receipt_check(frozen))
            file.write_bytes(contents)
            tests.append('先頭改変と保存応答のハッシュ不一致を拒否')

            def extract(path, symbol, target_session, quotes):
                """機能: 特徴処理の人工結果を返す。

                引数: 原本path (Path)、symbol/target_session (str)、quotes (list)。返り値: tuple。
                """
                return None, dict(銘柄=symbol, セッション=target_session)

            def write_features(frame, audit, directory, quotes):
                """機能: 原本行対応の確認に用いる人工特徴ファイルを保存する。

                引数: frame (object)、audit (dict)、directory (Path)、quotes (list)。返り値: なし (None)。
                """
                stem = f'{audit["銘柄"]}_{audit["セッション"]}'
                np.savez_compressed(directory / f'約定系列_{stem}.npz', seq=np.array([0, 1]), time_s=np.array([0., 1.]))
                write(directory / f'{stem}_audit.json', dict(約定系列NPZ_SHA256='人工'))

            def build_inputs(sessions, roots):
                """機能: 準備済み入力と監査の保存先が新作業であることを確かめる。

                引数: sessions (list)、roots (dict)。返り値: 人工入力 (dict)。
                """
                assert sessions == [session] and roots == {session:(live, live / 'features')}
                assert current.reference.previous.OUT == out
                write(current.reference.previous.OUT / '人工信号監査.json', dict(保存先='新作業'))
                return {(session, symbol):dict(seq=np.array([0, 1]), last=np.array([100., 110.])) for symbol in current.SYMBOLS}

            extractor = SimpleNamespace(extract_features=extract, write_features=write_features)
            with patch.object(current.reference.previous.data, 'import_module', return_value=extractor), \
                 patch.object(current.reference.previous, 'build_inputs', side_effect=build_inputs):
                record = current.prepare()
                assert record['今回準備中の要求数'] == 0 and record['損益評価'] is False
                assert len(calls) == 6
                for symbol in current.SYMBOLS:
                    tape = np.load(live / 'features' / f'約定系列_{symbol}_{session}.npz')
                    np.testing.assert_array_equal(tape['last'], [100., 110.])
                    np.testing.assert_array_equal(tape['current_price'], tape['last'])
                assert not (old / '人工信号監査.json').exists()
                with (out / '現在入力.pkl').open('rb') as stream:
                    assert set(pickle.load(stream)) == {(session, symbol) for symbol in current.SYMBOLS}
                reject(current.prepare)
                tests.append('CurrentPrice行対応・新作業だけへ監査と入力保存・準備重複拒否')
            with patch.object(current, 'now_jst', return_value=datetime.fromisoformat('2026-09-25T09:30:00+09:00')):
                other = out / '別セッション.json'
                with patch.multiple(current, FROZEN=other, LIVE=out / '別セッションlive'):
                    reject(current.freeze)
                assert not other.exists()
                tests.append('対象外セッションの凍結を拒否')
    current.configure()
    assert current.OUT == actual_out and current.OLD == actual_old and current.reference.previous.OUT == actual_out
    report = dict(合格=True, 検査数=len(tests), 検査=tests, 実通信回数=0, 人工要求数=len(calls),
        本番凍結=False, 本番取得=False, 実装SHA256=current.sha256(actual_out / 'current_check.py'),
        仮環境=str(base.relative_to(current.ROOT)))
    write(actual_out / '現在取得器_通信なし監査.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
