"""追加Dayの入力だけを、人工・事前固定・根確認の後に一回原本走査で生成する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys
import traceback

import numpy as np

import core
import data


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE/'追加Day未読入力の固定計画.json'
ARTIFICIAL = HERE/'旧normal独立LPと完全prepareの人工検査.json'
FIXED = HERE/'追加入力sourceと人工確認の固定.json'
OWN_SOURCES = ('core.py', 'data.py', 'prepare.py', 'artificial.py')


def read(path: Path) -> dict:
    """
    機能: 所有域の計画、人工証跡、入力固定だけを読む。
    引数: path(Path)は日本語JSON。
    返り値: dictは内容。金融結果、旧32cache、生原本の読取には使わない。
    """
    assert path.resolve().is_relative_to(HERE.resolve())
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域の未存在JSONへ固定又は正式入力の終端を保存する。
    引数: path(Path)は位置、value(dict)は資料。
    返り値: None。旧領域と完成資料を上書きしない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 入力処理中のAPI取得と実注文への通信を拒否する。
    引数: args(tuple)、kwargs(dict)は接続指定。
    返り値: None。常にRuntimeError。
    """
    raise RuntimeError('追加Dayは保存済み新2原本だけを一回読み、API、金融及び注文を行いません')


def stat_check(plan: dict) -> dict:
    """
    機能: 未読登録済み2原本のstatだけを確認する。
    引数: plan(dict)は値読取前の計画。
    返り値: dictはサイズ/mtime_ns。価格、板、原行、原本hashは読まない。
    """
    answer = {}
    for symbol in core.SYMBOLS:
        item = plan['原本stat'][symbol]
        path = ROOT/item['path']
        expected = (ROOT/'book'/symbol/(core.SESSION+'.jsonl')).resolve()
        assert path.resolve() == expected
        stat = path.stat()
        assert stat.st_size == item['bytes']
        stamp = datetime.fromisoformat(item['last_write_utc']).timestamp()
        assert abs(stat.st_mtime-stamp) < 1e-5
        answer[symbol] = dict(path=item['path'], bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return answer


def verified_artificial() -> tuple[dict, dict]:
    """
    機能: 人工の完全旧prepare合格と、参照ソースの不変を要求する。
    引数: なし。
    返り値: tuple[dict,dict]は人工証跡と小直接依存指紋。原本hashは含めない。
    """
    proof = read(ARTIFICIAL)
    assert proof['全合格'] and proof['人工専用']
    for key in ('正式追加原本読取', '旧32原本再読取', '金融結果読取', '金融再生', '現在API取得', '実注文', 'goal操作'):
        assert proof[key] == 0
    source_sha = dict(proof['コードSHA256'])
    for name in OWN_SOURCES:
        path = HERE/name
        relative = str(path.relative_to(ROOT))
        assert relative in source_sha and data.digest(path) == source_sha[relative]
    for name, wanted in source_sha.items():
        assert data.digest(ROOT/name) == wanted, name
    for path in (PLAN, HERE.parent/'catalog.py', HERE.parent/'数値設計案.json',
                 HERE.parent/'安定性の採用基準補足.json', HERE.parent/'evaluation/assessment.py'):
        source_sha[str(path.relative_to(ROOT))] = data.digest(path)
    schema_path = HERE/'入力schema.json'
    assert read(schema_path) == core.schema()
    source_sha[str(schema_path.relative_to(ROOT))] = data.digest(schema_path)
    return proof, source_sha


def register_only() -> None:
    """
    機能: 人工合格後に対象新一場、2原本stat、条件及びsourceを値未読で固定する。
    引数: なし。
    返り値: None。原本の内容/hash、正式新入力、金融を実行しない。
    """
    assert not FIXED.exists() and not (HERE/'metadata.json').exists()
    plan = read(PLAN)
    assert plan['session'] == core.SESSION and plan['条件数'] == 121 and plan['事前指定主'] == 'U_P10_T2'
    proof, fingerprints = verified_artificial()
    save(FIXED, dict(全合格=True, 状態='値未読の入力事前固定。正式走査は未実行。',
        session=core.SESSION, 口座数=2, 原本stat=stat_check(plan), 小直接依存SHA256=fingerprints,
        計画SHA256=data.digest(PLAN), 人工SHA256=data.digest(ARTIFICIAL),
        正式新原本読取=0, 旧32原本再読=0, 旧32大型cache読取=0,
        金融再生=0, 金融結果閲覧=0, 現在API取得=0, 実注文=0, goal操作=0))
    print('追加Day入力をstatとsourceで固定。原本内容読取は0です', flush=True)


def formal(workers: int) -> None:
    """
    機能: 根の明示許可後だけ、新2原本を各一回抽出し完全旧prepareを別保存する。
    引数: workers(int)は1又は2の同時商品数。
    返り値: None。旧32を再読せず、新場金融・選定・API・注文も行わない。
    """
    assert workers in (1, 2)
    assert not (HERE/'metadata.json').exists() and not list((HERE/'raw').glob('*/*.npz'))
    fixed, plan = read(FIXED), read(PLAN)
    assert fixed['全合格'] and fixed['session'] == core.SESSION
    proof, fingerprints = verified_artificial()
    assert fingerprints == fixed['小直接依存SHA256']
    assert data.digest(ARTIFICIAL) == fixed['人工SHA256']
    assert stat_check(plan) == fixed['原本stat']
    with core.owned_cache():
        core.modules()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {symbol: executor.submit(core.extract_jsonl, ROOT/'book'/symbol/(core.SESSION+'.jsonl'), core.SESSION, symbol)
                       for symbol in core.SYMBOLS}
            extracted = {symbol: future.result() for symbol, future in futures.items()}
    accounts = {}
    for symbol, item in extracted.items():
        record, probe = item['normal']['record'], item['normal']['probe']
        assert probe['latest']['time'] >= record['limit'] and np.any(record['time_s'] >= record['limit']), '通常終端前の未完成入力'
        original_stat = fixed['原本stat'][symbol]
        assert item['diagnosis']['raw_stat_size'] == original_stat['bytes']
        assert item['diagnosis']['raw_stat_mtime_ns'] == original_stat['mtime_ns']
        target = HERE/'raw'/symbol/(core.SESSION+'.npz')
        assert not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, **item['raw'])
        diagnostic = deepcopy(item['diagnosis'])
        diagnostic.update(session=core.SESSION, symbol=symbol, start=record['start'], end=record['end'],
            limit=record['limit'], tick=record['tick'], 原本位置=original_stat['path'],
            出力位置=str(target.relative_to(ROOT)), 出力SHA256=data.digest(target),
            通常終端用normal行数=int(np.sum(record['time_s'] >= record['limit'])),
            通常終端までの不足秒=record['end']-record['time_s'][-1])
        diagnostic['qualifications']['volume_delta_usable'] = int(item['raw']['volume_delta_usable'].sum())
        accounts[core.SESSION+'|'+symbol] = diagnostic
    material, prepared = core.build_material(extracted)
    bundle = HERE/'materialと完全旧prepare.pkl'
    assert not bundle.exists()
    with bundle.open('wb') as stream:
        pickle.dump(dict(material=material, prepared=prepared), stream, protocol=5)
    schema = core.schema()
    assert schema['version'] == 2 and len(schema['columns']) == 44
    assert stat_check(plan) == fixed['原本stat']
    assert verified_artificial()[1] == fingerprints
    save(HERE/'metadata.json', dict(全合格=True, sessions=[core.SESSION], 口座数=2, accounts=accounts,
        schema=schema, 小直接依存SHA256=fingerprints,
        事前固定SHA256=data.digest(FIXED), 人工SHA256=data.digest(ARTIFICIAL),
        入力SHA256={str(bundle.relative_to(ROOT)): data.digest(bundle)},
        完全旧prepare=True, 簡易signal代用=False, 始値当時from_i0=True,
        原本各一回hash=True, 正式原本各一回読取=2, 旧32原本再読=0, 旧32大型cache読取=0,
        前場参照読取=0, 条件変更=0, 主変更=0, 金融結果読取=0, 金融再生=0,
        現在API取得=0, 実注文=0, goal操作=0))
    print('追加Dayの2原本一回抽出、旧normal/独立LP、完全102.prepareが完成。金融0', flush=True)


def main() -> None:
    """
    機能: 値未読の事前固定と、根確認後の正式一回抽出をCLIフラグで分離する。
    引数: CLI --register-only(bool)、--root-additional-input-reviewed(bool)、--workers(int)。
    返り値: None。無フラグや同時指定は原本内容読取前に拒否する。
    """
    parser = argparse.ArgumentParser(description='追加Day一場だけの不変入力を準備する')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--register-only', action='store_true')
    modes.add_argument('--root-additional-input-reviewed', action='store_true')
    parser.add_argument('--workers', type=int, default=1)
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    if args.register_only:
        register_only()
    else:
        formal(args.workers)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        index = 1
        while (HERE/f'追加入力不合格_{index:05d}.json').exists():
            index += 1
        save(HERE/f'追加入力不合格_{index:05d}.json', dict(全合格=False,
            例外型=type(error).__name__, 内容=str(error), 診断=traceback.format_exc(),
            出力完成=(HERE/'metadata.json').exists(), 自動再抽出=False,
            金融再生=0, 金融結果読取=0, 現在API取得=0, 実注文=0, goal操作=0))
        raise
