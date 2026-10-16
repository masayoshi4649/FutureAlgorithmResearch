"""旧正常執行と対応する32場の全原行入力を、明示通知後だけ一回原本読取で作る。"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sys
import traceback

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
sys.path.insert(0, str(HERE))
import core
import data

REGISTRATION = HERE / '原本抽出前の32場登録.json'
SCHEMA = HERE / '入力schema.json'
ARTIFICIAL = HERE / '人工抽出と時計及び欠測と執行対応の検査.json'
SOURCE_NAMES = ('core.py', 'data.py', 'prepare.py', 'artificial.py')
DIRECT_INPUT_NAMES = ('work/wave_v102/data.py', 'work/wave_v102/holdout_input/data.py',
    'work/wave_v94/prepared_r1/metadata.json', 'work/wave_v95/prepared/metadata.json',
    'work/wave_v91/inputs/metadata.json', 'work/wave_v102/holdout_input/metadata.json')


def module(name: str, path: Path) -> object:
    """
    機能: 保存入力の読取だけを固有名で接続する。
    引数: name(str)、path(Path)は名前と位置。
    返り値: objectは読取モジュール。旧コード及びcacheを変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def read(path: Path) -> dict:
    """
    機能: 入力仕様又は入力指紋を読む。
    引数: path(Path)は対象JSON。
    返り値: dictは保存内容。金融結果領域を読まない。
    """
    assert not any(part in ('results', 'ledgers', 'front', 'back', 'analysis', 'review') for part in path.parts)
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: dict) -> None:
    """
    機能: 担当する新103入力領域だけへJSONを新規保存する。
    引数: path(Path)、value(dict)は位置と内容。
    返り値: None。完成資料及び旧素材の上書きを拒絶する。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 保存入力の準備からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)は呼出し引数。
    返り値: None。常にRuntimeErrorを送出する。
    """
    raise RuntimeError('103入力準備では現在API及び注文へ接続しません')


def source_sha() -> dict:
    """
    機能: 小さい直接コード及び入力仕様だけを指紋化する。
    引数: なし。
    返り値: dict[str,str]は内容指紋。生原本及び大型旧cacheの二重hashは行わない。
    """
    paths = [HERE/name for name in SOURCE_NAMES] + [ROOT/name for name in DIRECT_INPUT_NAMES]
    return {str(path.relative_to(ROOT)): data.digest(path) for path in paths}


def record_sha(record: dict) -> dict:
    """
    機能: 全原行抽出へ渡す旧正常執行列だけの内容と期間値を固定する。
    引数: record(dict)は旧の価格・気配・源行入力。
    返り値: dictは全件照合する5配列の型形状SHA及び固定スカラー。
    """
    arrays = {name: dict(dtype=str(record[name].dtype), shape=list(record[name].shape),
                         SHA256=hashlib.sha256(record[name].tobytes()).hexdigest())
              for name in ('seq', 'time_s', 'price', 'bid', 'ask')}
    return dict(arrays=arrays, start=record['start'], end=record['end'], limit=record['limit'], tick=record['tick'])


def load_existing_records() -> tuple[dict, list[str]]:
    """
    機能: 元31と追加Nightの不変素材から、旧正常執行の64口座だけを読取接続する。
    引数: なし。
    返り値: tuple[dict,list[str]]は正常執行recordと32場の明示対象。
    全旧cacheのhash再走査はせず、今回の正常列指紋と原本全件照合で対応を確認する。
    """
    original = module('103入力の旧31正常執行読取', ROOT/'work/wave_v102/data.py').load_inputs(verify=False)
    additional = module('103入力の追加Night正常執行読取', ROOT/'work/wave_v102/holdout_input/data.py').load_inputs(verify=False)
    assert len(original['metadata']['sessions']) == 31 and len(original['prices']) == 62
    assert additional['metadata']['sessions'] == ['2026-10-12_Night'] and len(additional['prices']) == 2
    assert not set(original['prices']) & set(additional['prices'])
    records = dict(original['prices'])
    records.update(additional['prices'])
    sessions = sorted([*original['metadata']['sessions'], *additional['metadata']['sessions']])
    assert len(sessions) == len(set(sessions)) == 32 and len(records) == 64
    assert set(records) == {(session, symbol) for session in sessions for symbol in SYMBOLS}
    assert sessions[0] == '2026-09-21_Day' and sessions[-1] == '2026-10-12_Night'
    return records, sessions


def expected_raw_sha() -> dict:
    """
    機能: 旧の全原行検査及び追加Night入力検査が保存した原本指紋を参照する。
    引数: なし。
    返り値: dict[str,str]は対象64原本の既保存SHA。原本をここで再読取しない。
    """
    old = read(ROOT/'work/wave_v94/prepared_r1/metadata.json')
    extra = read(ROOT/'work/wave_v102/holdout_input/metadata.json')
    result = {item['原本相対位置']: item['原本SHA256'] for item in old['素材取得診断']}
    for name, wanted in extra['原本SHA256'].items():
        if Path(name).parts[0] == 'book':
            assert name not in result
            result[name] = wanted
    assert len(result) == 64
    return result


def artificial_complete() -> dict:
    """
    機能: 現sourceと結び付く人工抽出の合格を正式原本読取より前に要求する。
    引数: なし。
    返り値: dictは人工証跡。人工合格を実入力合格と呼ばない。
    """
    proof = read(ARTIFICIAL)
    assert proof['全合格'] and proof['正式全64原本抽出'] == 0 and proof['金融再生'] == 0
    for name, wanted in proof['コードSHA256'].items():
        assert data.digest(ROOT/name) == wanted, name
    return proof


def register_only() -> None:
    """
    機能: 32場と64原本を明記し、旧正常列と既保存原本SHAを正式抽出前に登録する。
    引数: なし。
    返り値: None。原本はstatだけ確認し、原本の読取抽出及び新hashは行わない。
    """
    artificial_complete()
    assert not REGISTRATION.exists() and not (HERE/'metadata.json').exists()
    before = source_sha()
    records, sessions = load_existing_records()
    expected = expected_raw_sha()
    originals = {}
    for (session, symbol), record in sorted(records.items()):
        path = ROOT/'book'/symbol/(session+'.jsonl')
        name = str(path.relative_to(ROOT))
        assert name in expected and path.exists()
        originals[session+'|'+symbol] = dict(session=session, symbol=symbol, 原本位置=name,
            既保存原本SHA256=expected[name], 原本バイト数=path.stat().st_size,
            原本最終保存epoch=path.stat().st_mtime, 旧正常列=record_sha(record))
    assert set(expected) == {value['原本位置'] for value in originals.values()}
    assert source_sha() == before
    assert read(SCHEMA) == core.schema()
    save(REGISTRATION, dict(全合格=True, 状態='対象及び抽出sourceの登録。正式原本抽出は未実行。',
        sessions=sessions, 対象場数=32, 口座数=64, accounts=originals, 直接コードSHA256=before,
        入力schemaSHA256=data.digest(SCHEMA), 人工検査SHA256=data.digest(ARTIFICIAL),
        原本hash方式='各原本を正式抽出する一回読取の中でhash。登録時は既保存原本SHAの参照だけ。',
        元31素材変更=0, 追加Night素材変更=0, 正式全64原本抽出=0, 金融再生=0, 現在API取得=0, 実注文=0))
    print('32場64原本と旧正常列を登録しました。正式原本読取・金融再生は0です', flush=True)


def extract_one(job: tuple[str, str, dict, dict]) -> tuple[str, dict]:
    """
    機能: 根確認後の一口座を一回原本読取で抽出し、npzへ新規保存する。
    引数: job(tuple[str,str,dict,dict])は場、商品、旧正常列及び事前登録。
    返り値: tuple[str,dict]は口座キーと全件対応・原本指紋・出力指紋の診断。
    """
    session, symbol, record, registered = job
    assert record_sha(record) == registered['旧正常列']
    path = ROOT/registered['原本位置']
    arrays, diagnosis = core.extract_jsonl(path, record['start'], record['end'], record)
    assert diagnosis['raw_SHA256'] == registered['既保存原本SHA256'], '既保存検査後の原本変更'
    assert diagnosis['raw_bytes'] == registered['原本バイト数']
    assert np.array_equal(arrays['raw_seq'], np.arange(diagnosis['raw_rows'], dtype=np.int64))
    destination = HERE/'raw'/symbol/(session+'.npz')
    assert destination.resolve().is_relative_to(HERE.resolve()) and not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    diagnosis.update(session=session, symbol=symbol, start=record['start'], end=record['end'],
        limit=record['limit'], tick=record['tick'], 原本位置=registered['原本位置'],
        出力位置=str(destination.relative_to(ROOT)), 出力SHA256=data.digest(destination),
        旧正常列=registered['旧正常列'])
    return session+'|'+symbol, diagnosis


def extract_all(workers: int) -> None:
    """
    機能: 根によるschema確認後だけ、32場64口座を正式抽出して終端manifestを保存する。
    引数: workers(int)は並列原本読取数。1又は2。
    返り値: None。入力のみを作り、金融再生及びAPI取得は行わない。
    """
    assert workers in (1, 2)
    artificial_complete()
    registered = read(REGISTRATION)
    assert registered['全合格'] and registered['正式全64原本抽出'] == 0
    assert data.digest(SCHEMA) == registered['入力schemaSHA256']
    assert data.digest(ARTIFICIAL) == registered['人工検査SHA256']
    assert source_sha() == registered['直接コードSHA256']
    assert not (HERE/'metadata.json').exists()
    assert not list((HERE/'raw').rglob('*.npz')), '部分抽出を黙って再開又は上書きしません'
    records, sessions = load_existing_records()
    assert sessions == registered['sessions']
    jobs = [(session, symbol, record, registered['accounts'][session+'|'+symbol])
            for (session, symbol), record in sorted(records.items())]
    accounts = {}
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(extract_one, job) for job in jobs]
        for future in as_completed(futures):
            key, diagnosis = future.result()
            accounts[key] = diagnosis
            print(key + f" 原本{diagnosis['raw_rows']:,}行/旧執行{diagnosis['normal_execution_rows']:,}行が一致", flush=True)
    assert len(accounts) == 64 and set(accounts) == set(registered['accounts'])
    assert source_sha() == registered['直接コードSHA256']
    output = dict(全合格=True, sessions=sessions, 対象場数=32, 口座数=64, schema=core.schema(),
        accounts=dict(sorted(accounts.items())), 直接コードSHA256=registered['直接コードSHA256'],
        事前登録SHA256=data.digest(REGISTRATION), 入力schemaSHA256=data.digest(SCHEMA),
        人工検査SHA256=data.digest(ARTIFICIAL), 元31素材変更=0, 追加Night素材変更=0,
        全旧正常執行seq時刻LP両気配一致=True, 原本各1回読取hash=True,
        実受信時計を利用した=False, 約定取消又は注文主体の同定=False,
        累計売買代金から方向別約定量を再構成した=False,
        正式全64原本抽出=64, 金融再生=0, 現在API取得=0, 実注文=0)
    save(HERE/'metadata.json', output)
    first = sessions[0]
    arrays, item = data.load_account(first, 'TOPIX')
    assert len(arrays['raw_seq']) == item['raw_rows']
    print('全32場64口座の原行・時計・表示板・旧正常執行対応が完成。金融再生は0です', flush=True)


def main() -> None:
    """
    機能: 事前登録と根確認後の正式原本抽出を明示フラグで分ける。
    引数: CLI --register-only(bool)、--root-schema-reviewed(bool)、--workers(int)。
    返り値: None。無指定又は同時指定は原本読取前に拒否する。
    """
    parser = argparse.ArgumentParser(description='103保存原板の入力準備だけを行う')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--register-only', action='store_true')
    mode.add_argument('--root-schema-reviewed', action='store_true')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    if args.register_only:
        register_only()
    else:
        extract_all(args.workers)


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        index = 1
        while (HERE/f'入力準備不合格_{index:05d}.json').exists():
            index += 1
        save(HERE/f'入力準備不合格_{index:05d}.json', dict(全合格=False,
            例外型=type(error).__name__, 内容=str(error), 診断=traceback.format_exc(),
            抽出コードSHA256={name: data.digest(HERE/name) for name in SOURCE_NAMES if (HERE/name).exists()},
            正式入力完成=(HERE/'metadata.json').exists(), 金融再生=0, 現在API取得=0, 実注文=0))
        raise
