"""ネット接続なしで候補を固定し、親のGO後にだけ現在原本を一回取得する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import subprocess

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
OLD = WORK.parent / 'wave_v60'
PREVIOUS = (OLD / 'live', WORK.parent / 'wave_v61/live')
MINUTE = ('ACCEL_H03_V020', 'STRAIGHT_H05_V020', 'BREAK_H03_V020')
RAW = ('RAW_ACCEL_S060_V050', 'RAW_STRAIGHT_S060_V050')
EXITS = (
    dict(id='狭幅', stop=.001, arm=.0011, trail=.0001, floor=.001),
    dict(id='広幅', stop=.001, arm=.0015, trail=.0005, floor=.001),
    dict(id='短期幅', stop=.0003, arm=.0005, trail=.0002, floor=.0003),
)


def digest(path: Path, count: int | None = None) -> str:
    """機能: 原本又は指定した前半のSHA256を読み取りだけで求める。

    引数: path(Path)、count(int|None)は読み取る最大バイト数。
    返り値: SHA256文字列(str)。前半が不足した場合は例外とする。
    """
    result, remaining = hashlib.sha256(), count
    with path.open('rb') as stream:
        while remaining is None or remaining > 0:
            part = stream.read(4 * 1024 * 1024 if remaining is None else min(remaining, 4 * 1024 * 1024))
            if not part:
                break
            result.update(part)
            if remaining is not None:
                remaining -= len(part)
    assert remaining in (None, 0), '比較する原本前半が不足しています'
    return result.hexdigest()


def save(name: str, value: object) -> None:
    """機能: 非有限値を拒否して今回フォルダ内だけにJSONを保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def load_module(name: str, path: Path):
    """機能: 指定したローカル実装を実行開始なしで読み込む。

    引数: name(str)、path(Path)。返り値: 読み込んだモジュール(ModuleType)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parser_module():
    """機能: 既存パーサーの出力先だけを今回フォルダに分離する。

    引数: なし。返り値: 既存パーサーモジュール(ModuleType)。旧成果を書き換えない。
    """
    module = load_module('旧現在原本パーサー', OLD / 'live/parse_snapshot.py')
    module.HERE, module.WORK, module.ROOT = HERE, OLD, ROOT
    return module


def candidates() -> list[dict]:
    """機能: 今回API参照前に決めた12主案の組合せを返す。

    引数: なし。返り値: 入口ID・系統・出口と方向の一覧(list[dict])。
    順方向だけを確認し、現在結果による条件再調整は行わない。
    """
    return [dict(id=f'{entry}_{exit_config["id"]}', entry=entry, source=source, mirror=False,
                 exit_config=dict(exit_config))
            for source, entries, exit_configs in (('minute', MINUTE, EXITS[:2]), ('raw', RAW, EXITS))
            for entry in entries for exit_config in exit_configs]


def prepare() -> None:
    """機能: ネットワーク未使用で契約・12候補・既知前半の参照先を固定する。

    引数: なし。返り値: なし(None)。固定済み又は取得開始済みなら拒否する。
    """
    HERE.mkdir(exist_ok=True)
    assert not (HERE / '取得準備固定.json').exists() and not (HERE / '取得開始.json').exists()
    assert json.loads((HERE / '途中会計の合成監査.json').read_text(encoding='utf-8'))['全合格']
    parser_module().save_baseline()
    selection = dict(時刻=datetime.now(timezone.utc).isoformat(), selected=candidates(), 条件数=12,
                     枚数=dict(TOPIXmini=10, NK225micro=20), 方向='検知方向のみ',
                     禁止='今回取得した原本を使って入口・出口・数量・休止を再調整しない',
                     未決済='原本末尾で仮想清算しない。実現損益・発生手数料・全残玉の返済気配評価を分ける。',
                     休止秒=600, 実注文=0, 現在API取得=0)
    save('候補固定.json', selection)
    paths = [Path(__file__), HERE / 'partial_replay.py', HERE / '途中会計の合成監査.json',
             HERE / '契約照合基準.json', HERE / '候補固定.json',
             OLD / 'inputs.pkl', OLD / 'quotes.pkl', OLD / 'live/fetch_once.exe',
             OLD / 'live/fetch_once.go', OLD / 'live/parse_snapshot.py']
    for previous in PREVIOUS:
        paths.extend(previous / name for name in ('inputs.pkl', 'quotes.pkl', '取得記録.json', 'TOPIX.jsonl', 'NK225.jsonl'))
    save('取得準備固定.json', dict(時刻=datetime.now(timezone.utc).isoformat(), 外部取得=0,
         ファイル={str(path): digest(path) for path in paths},
         注意='入口実装の最終SHA固定はsealで行う。sealはネット接続せず、fetchは親GO後だけ。',
         前半参照先=[str(path) for path in PREVIOUS]))
    print('12候補・契約・既知前半を固定しました。現在APIは未使用です。')


def verify_prepare() -> dict:
    """機能: 候補・取得器・旧原本が事前固定から変更されていないことを照合する。

    引数: なし。返り値: 準備固定情報(dict)。ネットワークは使用しない。
    """
    frozen = json.loads((HERE / '取得準備固定.json').read_text(encoding='utf-8'))
    for name, sha in frozen['ファイル'].items():
        assert digest(Path(name)) == sha, (name, '取得前の固定と不一致')
    selection = json.loads((HERE / '候補固定.json').read_text(encoding='utf-8'))
    assert selection['selected'] == candidates() and selection['条件数'] == 12
    return frozen


def seal() -> None:
    """機能: 完成した入口実装のSHAと候補IDの存在を取得前に封印する。

    引数: なし。返り値: なし(None)。ネットワーク取得も再選定も行わない。
    """
    verify_prepare()
    assert not (HERE / '取得開始.json').exists() and not (HERE / '取得前最終固定.json').exists()
    minute = load_module('今回分足入口', WORK / 'steep_signals.py')
    raw = load_module('今回短期入口', WORK / 'round2/raw_signals.py')
    definitions = {'minute': {value['id']: value for value in minute.definitions()},
                   'raw': {value['id']: value for value in raw.definitions()}}
    assert all(value['entry'] in definitions[value['source']] for value in candidates())
    paths = (WORK / 'steep_signals.py', WORK / 'round2/raw_signals.py')
    save('取得前最終固定.json', dict(時刻=datetime.now(timezone.utc).isoformat(), 外部取得=0,
         候補SHA=digest(HERE / '候補固定.json'), 実装={str(path): digest(path) for path in paths},
         入口定義={value['entry']: definitions[value['source']][value['entry']] for value in candidates()},
         現在データを参照していない=True))
    print('入口実装を最終封印しました。現在APIは未使用です。')


def verify_seal() -> dict:
    """機能: 取得又は再生に先立ち候補と入口コードの最終封印を照合する。

    引数: なし。返り値: 最終封印(dict)。現在原本は判断基準に使わない。
    """
    verify_prepare()
    frozen = json.loads((HERE / '取得前最終固定.json').read_text(encoding='utf-8'))
    assert digest(HERE / '候補固定.json') == frozen['候補SHA']
    for name, sha in frozen['実装'].items():
        assert digest(Path(name)) == sha, (name, '封印済みの入口が変更されています')
    return frozen


def boundaries() -> dict:
    """機能: 同場の旧取得前半を原本バイト・全気配・連番で照合する。

    引数: なし。返り値: 各銘柄の既知境界と追加有効行数(dict)。追加HTTP取得はしない。
    """
    fresh = pickle.loads((HERE / 'inputs.pkl').read_bytes())
    fresh_quotes = pickle.loads((HERE / 'quotes.pkl').read_bytes())
    reports = []
    sources = [(OLD, pickle.loads((OLD / 'inputs.pkl').read_bytes()),
                pickle.loads((OLD / 'quotes.pkl').read_bytes()))]
    sources.extend((previous, pickle.loads((previous / 'inputs.pkl').read_bytes()),
                    pickle.loads((previous / 'quotes.pkl').read_bytes())) for previous in PREVIOUS)
    for key, ready in fresh.items():
        checks, count = [], 0
        for source, known, known_quotes in sources:
            if key not in known:
                continue
            previous = known[key]
            old_path = (ROOT / 'book' / key[1] / f'{key[0]}.jsonl' if source == OLD else source / f'{key[1]}.jsonl')
            prefix_sha = digest(HERE / f'{key[1]}.jsonl', old_path.stat().st_size)
            assert prefix_sha == digest(old_path), '現在原本の既知前半が一致しません'
            n = len(previous['seq'])
            assert len(ready['seq']) >= n
            for name in ('seq', 'time_s'):
                np.testing.assert_array_equal(ready[name][:n], previous[name])
            for name in ('bid', 'ask', 'mid'):
                np.testing.assert_array_equal(fresh_quotes[key][name][:n], known_quotes[key][name])
            count = max(count, n)
            checks.append(dict(参照先=str(source), 既知有効行数=n, 原本前半完全一致=True))
        reports.append(dict(セッション=key[0], 銘柄=key[1], 同場の既知前半あり=bool(checks),
                       既知有効行数=count, 追加有効行数=len(ready['seq']) - count,
                       既知最終時計=float(ready['time_s'][count - 1]) if count else None, 照合元=checks))
    report = dict(照合=reports, 追加取得=0,
                  解釈='同場の既知前半は未知成績と呼ばない。同時計でも有効原本行境界で追加資産変化を分ける。')
    save('既知前半と追加区間.json', report)
    manifest = json.loads((HERE / '現在原本の照合.json').read_text(encoding='utf-8'))
    manifest['同場の既知前半あり'] = any(row['同場の既知前半あり'] for row in reports)
    if manifest['同場の既知前半あり']:
        manifest['未見検証と呼べるか'] = False
        manifest['注記'] = '原本全体には以前の取得済み前半を含む。新しい追加区間を別表示する。'
    save('現在原本の照合.json', manifest)
    return report


def fetch(authorized: bool) -> None:
    """機能: 親のGO後だけ状態一回・二銘柄の板各一回を取得して照合する。

    引数: authorized(bool)は親のGOを受けた明示指定。
    返り値: なし(None)。失敗時も再取得せず、実注文はしない。
    """
    assert authorized, '親GOがありません。ネットワーク未使用です'
    verify_seal()
    assert not (HERE / '取得開始.json').exists(), '二度目の取得を拒否します'
    save('取得直前照合.json', dict(時刻=datetime.now(timezone.utc).isoformat(),
         候補SHA=digest(HERE / '候補固定.json'), 最終封印SHA=digest(HERE / '取得前最終固定.json'), 親GO=True, 実注文=0))
    try:
        subprocess.run([str(OLD / 'live/fetch_once.exe'), '-authorized', '-directory', str(HERE)], check=True)
        parser_module().main()
        boundaries()
    except Exception as error:
        save('現在確認停止.json', dict(理由=str(error), 再取得=False, 条件を変更しない=True))
        raise


def main() -> None:
    """機能: 準備・最終封印・親GO後取得を明示的に分けて実行する。

    引数: コマンド引数stage(str)、authorized(bool)。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='急傾斜手法の一回現在確認を準備する。')
    parser.add_argument('stage', choices=('prepare', 'seal', 'fetch'))
    parser.add_argument('--authorized', action='store_true')
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare()
    elif args.stage == 'seal':
        seal()
    else:
        fetch(args.authorized)


if __name__ == '__main__':
    main()
