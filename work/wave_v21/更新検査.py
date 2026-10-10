"""一時原本で増分更新・不足・実行中変更の扱いを確認する。"""

import copy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('更新検査対象', ROOT / 'M3_逆_A00_360分版/更新.py')
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
real_out = backend.OUT
real_work = backend.WORK
session = '2026-09-28_Day'
checks = {}


def row(symbol: str, amount: float) -> dict:
    """機能: 更新管理の検査用に最小の会計整合行を作る。

    引数: symbol (str)、amount (float)。返り値: 検査用損益行 (dict)。
    """
    return dict(method_id='V0800', symbol=symbol, session=session, gross_profit_yen=amount,
                gross_loss_yen=0, net_yen=amount, profit_units=1, loss_units=0, zero_units=0,
                unit_balance=1, closed_units=1, cycles=1)


with tempfile.TemporaryDirectory(dir=real_work, prefix='更新検査_') as directory:
    backend.ROOT = Path(directory)
    backend.OUT = backend.ROOT / '出力'
    backend.WORK = backend.ROOT / '作業'
    backend.OUT.mkdir()
    backend.WORK.mkdir()
    guard = dict(configuration_sha256='検査用の固定値')
    backend.fixed_settings = lambda: ({}, guard)
    for path in backend.paths_for(session):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == '.jsonl':
            times = ['08:45:01', '08:45:02', '10:00:00', '15:39:59']
            path.write_text(''.join(json.dumps(dict(CurrentPrice=100, CurrentPriceTime=f'2026-09-28T{stamp}+09:00')) + '\n' for stamp in times), encoding='utf-8')
        else:
            ending = '15:39:00' if '1min' in str(path) else '15:35:00'
            path.write_text('time,closed\n2026-09-28T08:45:00+09:00,true\n' + f'2026-09-28T{ending}+09:00,true\n', encoding='utf-8')
    paths = backend.paths_for(session)
    hashes = backend.fingerprints(paths)
    seeds = {session: dict(records=[row(symbol, 10) for symbol in backend.SYMBOLS], hashes=hashes, source='検査用')}
    backend.initial_seeds = lambda guard: copy.deepcopy(seeds)
    replay_calls = []

    def simulated_replay(name: str, fixed: dict, hashes: dict) -> tuple[list, list]:
        """機能: 会計エンジンを代行して更新分岐を検査する。

        引数: name (str)、fixed/hashes (dict)。返り値: 結果と空明細 (tuple[list, list])。
        """
        replay_calls.append(name)
        return [row(symbol, 20) for symbol in backend.SYMBOLS], []

    backend.replay = simulated_replay
    first = backend.update()
    second = backend.update()
    checks['初回２行と二回目重複なし'] = len(first['records']) == len(second['records']) == 2 and second['update_counts']['reused'] == 1
    with paths[0].open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(dict(CurrentPrice=101, CurrentPriceTime='2026-09-28T15:39:59+09:00')) + '\n')
    third = backend.update()
    checks['内容変更で既存結果を再生置換'] = replay_calls == [session] and len(third['records']) == 2 and all(item['net_yen'] == 20 for item in third['records'])
    original = paths[-1].read_bytes()
    paths[-1].unlink()
    fourth = backend.update()
    checks['片側原本不足は保留へ移動'] = not fourth['records'] and len(fourth['pending']) == 1
    paths[-1].write_bytes(original)
    original_book = paths[0].read_bytes()
    paths[0].write_text('\n'.join(original_book.decode().splitlines()[:3]) + '\n', encoding='utf-8')
    fifth = backend.update()
    checks['場末前の原本は保留'] = not fifth['records'] and '最終１分' in fifth['pending'][0]['reason']
    paths[0].write_bytes(original_book)

    def changing_replay(name: str, fixed: dict, hashes: dict) -> tuple[list, list]:
        """機能: 再生中に検査原本を変更して採用拒否を確認する。

        引数: name (str)、fixed/hashes (dict)。返り値: 結果と空明細 (tuple[list, list])。
        """
        with paths[0].open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(CurrentPrice=102, CurrentPriceTime='2026-09-28T15:39:59+09:00')) + '\n')
        return simulated_replay(name, fixed, hashes)

    backend.replay = changing_replay
    sixth = backend.update()
    checks['再生中の原本変更は不採用'] = not sixth['records'] and '処理中' in sixth['pending'][0]['reason']
    try:
        backend.check_complete(session, datetime.fromisoformat('2026-09-28T15:00:00+09:00'))
        checks['実時計がセッション終了前なら保留'] = False
    except ValueError:
        checks['実時計がセッション終了前なら保留'] = True
    checks['夜間の終了は翌日'] = backend.bounds('2026-09-28_Night')[1].isoformat() == '2026-09-29T05:55:00+09:00'
    for label, field, bad_value in [('非有限金額', 'net_yen', float('nan')), ('小数枚数', 'profit_units', 1.5), ('取引回数不一致', 'cycles', 2)]:
        pair = [row(symbol, 10) for symbol in backend.SYMBOLS]
        pair[0][field] = bad_value
        try:
            backend.validate_rows(pair, session)
            checks[label + 'を拒否'] = False
        except ValueError:
            checks[label + 'を拒否'] = True
    pair = [dict(row(symbol, 0), profit_units=0, closed_units=0, unit_balance=0, cycles=0) for symbol in backend.SYMBOLS]
    backend.validate_rows(pair, session)
    checks['取引ゼロは正常'] = True

spec2 = importlib.util.spec_from_file_location('固定条件検査対象', ROOT / 'M3_逆_A00_360分版/更新.py')
fixed_backend = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(fixed_backend)
with tempfile.TemporaryDirectory(dir=real_work, prefix='固定条件検査_') as directory:
    fixed_backend.OUT = Path(directory)
    fixed, _ = fixed_backend.fixed_settings()
    fixed['一枚でのエンジン設定']['stop_atr'] = 1.5
    fixed_backend.atomic_save(fixed_backend.OUT / '固定条件.json', fixed)
    try:
        fixed_backend.fixed_settings()
        checks['固定条件変更を拒否'] = False
    except RuntimeError:
        checks['固定条件変更を拒否'] = True

assert all(checks.values()), checks
backend.atomic_save(real_work / '増分更新の検査.json', dict(合格=True, 原本フォルダへの変更なし=True, 検査=checks))
print(json.dumps(checks, ensure_ascii=False, indent=2))
