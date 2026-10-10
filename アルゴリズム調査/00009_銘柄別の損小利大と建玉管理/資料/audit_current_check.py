"""通信を禁止した仮環境で現在取得器と既知境界の保存を検査する。"""

from datetime import datetime
import json
from pathlib import Path
import pickle
import socket
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import current_check as current
import reference

OUT, ROOT = reference.OUT, reference.ROOT


def write(path: Path, value: object) -> None:
    """機能: 人工環境へ日本語JSONを保存する。

    引数: path (Path)、value (object)。返り値: なし (None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def reject(function) -> None:
    """機能: 異常操作が例外で拒否されることを確かめる。

    引数: function (callable)。返り値: なし (None)。
    """
    try:
        function()
    except (ValueError, RuntimeError, FileExistsError):
        return
    raise AssertionError('拒否されるべき操作が成功しました')


def source_row(symbol: str, stamp: str, value: float) -> dict:
    """機能: 通信を使わず、生板形式の人工行を返す。

    引数: symbol/stamp (str)、value (float)。返り値: 生板行 (dict)。
    """
    return dict(SymbolName='日経225先物' if symbol == 'NK225' else 'TOPIX先物',
        Symbol='人工限月', CurrentPrice=value, CurrentPriceTime=stamp, TradingVolume=10.,
        Buy1=dict(Price=value-10, Qty=1), Sell1=dict(Price=value+10, Qty=1))


def setup(path: Path) -> tuple[Path, Path]:
    """機能: 本番条件・原本を使わない凍結と旧原本の仮環境を用意する。

    引数: path (Path)。返り値: 仮出力と仮旧作業のパス (tuple[Path, Path])。
    """
    out, old = path / '新作業', path / '旧作業'
    out.mkdir(parents=True, exist_ok=True)
    for name in current.LOCAL_FILES:
        (out / name).write_text('固定対象の人工内容\n', encoding='utf-8')
    write(out / '全条件一覧.json', [dict(id='人工条件', engine='grid')])
    write(out / '最終選択.json', dict(照合ID=['人工条件'],
        主候補={symbol: dict(採用=dict(method='人工条件')) for symbol in current.SYMBOLS}))
    write(old / 'live/取得記録.json', dict(session='2026-09-24_Night', cutoff='2026-09-24T23:19:00+09:00'))
    for symbol in current.SYMBOLS:
        file = old / 'live/book' / symbol / '2026-09-24_Night.jsonl'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(source_row(symbol, '2026-09-24T17:00:00+09:00', 100.), ensure_ascii=False) + '\n', encoding='utf-8')
    return out, old


def main() -> None:
    """機能: 凍結・一回取得・既知原本照合・保存入力準備を通信なしで検査する。

    引数: なし。返り値: なし (None)。本番APIは呼ばない。
    """
    base = OUT / '現在照合器_通信なし試験' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    assert base.resolve().is_relative_to(OUT.resolve())
    out, old = setup(base / '正常')
    fixed = datetime.fromisoformat('2026-09-25T00:40:00+09:00')
    clock = datetime.fromisoformat('2026-09-25T00:41:25+09:00')
    live, frozen_path = out / 'live', out / '現在照合_凍結記録.json'
    helper = reference.previous.data.import_module(ROOT / 'work/wave_v7/fetch_once.py', 'v14_offline_transport')
    calls, tests = [], []
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('外部通信は禁止')):
        with patch.multiple(current, OUT=out, OLD=old, LIVE=live, FROZEN=frozen_path), patch.object(current, 'now_jst', return_value=fixed):
            frozen = current.freeze()
            assert frozen['known_cutoff'] == '2026-09-24T23:19:00+09:00'
            assert frozen['known_session'] is True and len(frozen['known_books']) == 2
            assert current.freeze_check() == frozen
            reject(current.freeze)
            tests.append('既知23:19境界の凍結と再凍結拒否')
            source = out / 'metrics.py'
            contents = source.read_bytes()
            source.write_text('改変', encoding='utf-8')
            reject(current.freeze_check)
            source.write_bytes(contents)
            tests.append('会計コードの凍結後変更拒否')
            prior = old / 'live/book/NK225/2026-09-24_Night.jsonl'
            contents = prior.read_bytes()
            prior.write_bytes(contents + b'\n')
            reject(current.freeze_check)
            prior.write_bytes(contents)
            tests.append('旧原本の凍結後変更拒否')
        session, start, end = current.LEGACY.current_session(clock)
        cutoff = clock.replace(second=0, microsecond=0)

        def fake_fetch(name: str, url: str, path: Path) -> dict:
            """機能: 本番接続の代わりに人工の六応答を一度保存する。

            引数: name/url (str)、path (Path)。返り値: 一回要求記録 (dict)。
            """
            calls.append(name)
            symbol = name.split('_')[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith('_book'):
                old_file = old / 'live/book' / symbol / f'{session}.jsonl'
                suffix = json.dumps(source_row(symbol, '2026-09-25T00:40:00+09:00', 110.), ensure_ascii=False) + '\n'
                path.write_bytes(old_file.read_bytes() + suffix.encode('utf-8'))
            else:
                write(path, dict(snapshot=dict(code=symbol, sessionId=session, asOf=cutoff.isoformat(),
                    session=dict(startsAt=start.isoformat(), endsAt=end.isoformat())),
                    data=[dict(time=start.isoformat(), open=100., high=110., low=90., close=100.,
                               volume=10., closed=True, volumeComplete=True)]))
            return dict(name=name, url=url, path=path.relative_to(ROOT).as_posix(), attempts=1,
                        ok=True, http_status=200, sha256=current.sha256(path))

        helper.fetch_one = fake_fetch
        with patch.multiple(current, OUT=out, OLD=old, LIVE=live, FROZEN=frozen_path), \
             patch.object(current, 'now_jst', return_value=clock), \
             patch.object(reference.previous.data, 'import_module', return_value=helper):
            receipt = current.fetch()
            assert receipt['known_cutoff'] == frozen['known_cutoff']
            assert len(calls) == 6 and len(set(calls)) == 6
            assert current.receipt_check(frozen) == receipt
            assert all(row['先頭バイト完全一致'] for row in current.known_prefix_check(frozen))
            reject(current.fetch)
            assert len(calls) == 6
            tests.extend(['六要求各一回・再取得禁止', '取得記録の既知境界保持', '旧原本の先頭完全一致'])
            file = live / 'book/NK225/2026-09-24_Night.jsonl'
            contents = file.read_bytes()
            file.write_bytes(b' ' + contents)
            reject(lambda: current.known_prefix_check(frozen))
            reject(lambda: current.receipt_check(frozen))
            file.write_bytes(contents)
            tests.append('先頭原本不一致と保存応答改変の拒否')

        def extract(path, symbol, target_session, quotes):
            """機能: 特徴抽出の人工結果を返し、原本価格対応の試験へ渡す。

            引数: path (Path)、symbol/target_session (str)、quotes (list)。返り値: 人工特徴と監査 (tuple)。
            """
            return None, dict(銘柄=symbol, セッション=target_session)

        def write_features(frame, audit, directory, quotes):
            """機能: 真CurrentPrice追加前の人工原本行対応だけを保存する。

            引数: frame (object)、audit (dict)、directory (Path)、quotes (list)。返り値: なし (None)。
            """
            stem = f'{audit["銘柄"]}_{audit["セッション"]}'
            np.savez_compressed(directory / f'約定系列_{stem}.npz', seq=np.array([0, 1]), time_s=np.array([0., 1.]))
            write(directory / f'{stem}_audit.json', dict(約定系列NPZ_SHA256='人工追加前'))

        extractor = SimpleNamespace(extract_features=extract, write_features=write_features)
        fake_input = {(session, symbol): dict(seq=np.array([0, 1]), last=np.array([100., 110.])) for symbol in current.SYMBOLS}
        with patch.multiple(current, OUT=out, OLD=old, LIVE=live, FROZEN=frozen_path), \
             patch.object(current, 'now_jst', return_value=clock), \
             patch.object(reference.previous.data, 'import_module', return_value=extractor), \
             patch.object(reference.previous, 'build_inputs', return_value=fake_input):
            record = current.prepare()
            assert record['今回準備中の要求数'] == 0 and not record['損益評価']
            assert len(calls) == 6
            for symbol in current.SYMBOLS:
                tape = np.load(live / 'features' / f'約定系列_{symbol}_{session}.npz')
                np.testing.assert_array_equal(tape['last'], [100., 110.])
                np.testing.assert_array_equal(tape['current_price'], tape['last'])
            with (out / '現在入力.pkl').open('rb') as stream:
                stored = pickle.load(stream)
            assert set(stored) == set(fake_input)
            tests.append('保存応答だけから原本行対応価格と入力を準備')
        # ----------------------------------------
        # セッションが変われば開始を境界にし、以前の建玉や既知原本を継承しない。
        other_out, other_old = setup(base / '別セッション')
        with patch.multiple(current, OUT=other_out, OLD=other_old, LIVE=other_out / 'live',
                            FROZEN=other_out / '現在照合_凍結記録.json'), \
             patch.object(current, 'now_jst', return_value=datetime.fromisoformat('2026-09-25T09:30:00+09:00')):
            record = current.freeze()
            assert record['known_session'] is False and not record['known_books']
            assert record['known_cutoff'] == '2026-09-25T08:45:00+09:00'
            tests.append('別セッションは開始境界・旧建玉引継ぎなし')
    current.configure_legacy()
    report = dict(合格=True, 検査数=len(tests), 検査=tests, 実通信回数=0,
        実装SHA256=current.sha256(OUT / 'current_check.py'),
        旧取得器SHA256=current.sha256(reference.OLD / 'current_check.py'),
        仮環境=str(base.relative_to(ROOT)), 本番凍結=False, 本番現在取得=False)
    write(OUT / '現在照合器_通信なし監査.json', report)
    print(json.dumps(dict(合格=True, 検査数=len(tests), 実通信回数=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
