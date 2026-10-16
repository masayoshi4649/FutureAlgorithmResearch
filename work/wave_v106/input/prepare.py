"""事前登録済み33packetを各一回読み、同一入口の当時Q1数値を保存する。"""

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REGISTER = HERE/'正式33読取前の入力接続固定.json'
OUTPUT = HERE/'全33場の因果特徴準備.json'
ARTIFICIAL = HERE/'Q1当時経路と既存執行接続の人工検査.json'
OLD_METADATA = ROOT/'work/wave_v104/入口準備の全32結果.json'
DAY_METADATA = ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json'
REF_METADATA = (ROOT/'work/wave_v91/inputs/metadata.json', ROOT/'work/wave_v102/holdout_input/metadata.json')
DAY = '2026-10-13_Day'
for _name in ('core', 'data'):
    _identifier = '106入力準備専用'+_name
    _specification = importlib.util.spec_from_file_location(_identifier, HERE/(_name+'.py'))
    _module = importlib.util.module_from_spec(_specification)
    sys.modules[_identifier] = _module
    _specification.loader.exec_module(_module)
    globals()[_name] = _module


def write_json(path: Path, value: dict) -> None:
    """
    機能: 所有105input内へUTF-8の証跡を書き込む。
    引数: path(Path)、value(dict)は書込先と内容。
    返り値: None。旧source/cache/原本には書き込まない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source_paths() -> list[Path]:
    """
    機能: 入力定義・既存入力由来と人工の小依存だけを列挙する。
    引数: なし。
    返り値: list[Path]は計画固定対象。金融結果又は巨大packetは含めない。
    """
    paths = [HERE/name for name in ('features.py', 'core.py', 'data.py', 'prepare.py', 'artificial.py',
        'baseline_oracle.py', '入力schema.json', 'APIとQ1因果特徴の草案.json', '105からの複製由来.json',
        '正常基準非対応の局所修正.json')]
    paths += [ARTIFICIAL, OLD_METADATA, DAY_METADATA, *REF_METADATA,
        ROOT/'work/wave_v90/strategy.py', ROOT/'work/wave_v104/peer/prices.py',
        ROOT/'work/wave_v104/peer/core.py', ROOT/'work/wave_v104/peer/api.py']
    paths += [ROOT/f'work/wave_v{number}/catalog.py' for number in range(91, 103)]
    paths += [ROOT/'work/wave_v105/catalog.py']
    for path in (OLD_METADATA, DAY_METADATA):
        paths += [ROOT/name for name in data.read_json(path)['source_SHA256']]
    return sorted(set(paths))


def references() -> dict:
    """
    機能: 旧31と追加Nightの保存済みref_openだけを小metadataから接続する。
    引数: なし。
    返り値: dictは場→商品→ref_open。原板・旧prepared64・利益を参照しない。
    """
    result = {}
    for path in REF_METADATA:
        saved = data.read_json(path)
        for key, value in saved['references'].items():
            session, symbol = key.split('|')
            assert symbol in core.SYMBOLS and symbol not in result.setdefault(session, {})
            assert value['ref_open']['known_from_i'] == 0
            result[session][symbol] = value['ref_open']
    assert len(result) == 32 and all(set(value) == set(core.SYMBOLS) for value in result.values())
    return result


def register() -> dict:
    """
    機能: 33場の既存cacheのstatと保存指紋を本文未読で事前登録する。
    引数: なし。
    返り値: dictはsource固定と読取対象。元packet本文・新金融・利益ラベルの読取は0。
    """
    assert not REGISTER.exists(), '既登録を上書きしない'
    artificial = data.read_json(ARTIFICIAL)
    assert artificial['全合格'] and artificial['正式packet読取'] == artificial['新金融再生'] == 0
    old, additional = data.read_json(OLD_METADATA), data.read_json(DAY_METADATA)
    assert old['全合格'] and old['対象場数'] == 32 and old['入口数'] == 19
    assert additional['全合格'] and additional['session'] == DAY
    refs = references()
    assert set(old['sessions']) == set(old['cache']) == set(refs)
    for metadata in (old, additional):
        for name, wanted in metadata['source_SHA256'].items():
            assert data.digest(ROOT/name) == wanted, name
    files = {}
    for session in [DAY]+old['sessions']:
        value = additional if session == DAY else old['cache'][session]
        path = (ROOT/value['path']).resolve()
        allowed = ROOT/'work/wave_v104/holdout_input/activity_peer' if session == DAY else ROOT/'work/wave_v104/prepared'
        assert path.is_relative_to(allowed.resolve())
        stat = path.stat()
        files[session] = dict(path=str(path.relative_to(ROOT)), SHA256=value['SHA256'],
            size=stat.st_size, mtime_ns=stat.st_mtime_ns, kind='追加Day完全packet' if session == DAY else '旧32peerpacket')
    result = dict(全合格=True, sessions=[DAY]+old['sessions'], 対象場数=33, 口座数=66,
        入口=list(core.ENTRIES), 窓=list(core.features.WINDOWS), cache=files,
        source_SHA256={str(path.relative_to(ROOT)): data.digest(path) for path in source_paths()},
        正式packet読取=0, 原本再読取=0, NPZ再読取=0, 旧103活動cache再読取=0, 旧64base再prepare=0, 新金融再生=0,
        利益ラベル読取=0, 現在API=0, 実注文=0, 旧source変更=0,
        幅の実値対照='正式許可後の追加Day2商品を先に読む。同prepared実幅との一致まで入力終端合格にしない。',
        限界='完全旧signalは再構成しない。record/reference_open/signal.trend_widthの閉じた入力契約。')
    write_json(REGISTER, result)
    return result


def verify_fixed(fixed: dict) -> None:
    """
    機能: 小sourceの現在指紋が読取前固定と一致することを確認する。
    引数: fixed(dict)は事前固定証跡。
    返り値: None。不一致で原packetを読まず停止する。
    """
    for name, expected in fixed['source_SHA256'].items():
        assert data.digest(ROOT/name) == expected, name


def run() -> dict:
    """
    機能: 根の明示許可後、各保存packetを一度読み当時数値だけを新cacheへ保存する。
    引数: なし。
    返り値: dictは正式終端。Falseを保持し、自動再試行・原本再抽出をしない。
    """
    assert not OUTPUT.exists(), '既終端を上書き又は自動再実行しない'
    fixed = data.read_json(REGISTER)
    verify_fixed(fixed)
    refs, cache, counts = references(), {}, {}
    result = dict(全合格=False, 対象場数=33, 口座数=66, 入口=list(core.ENTRIES),
        sessions=sorted(fixed['sessions']), cache=cache, counts=counts, 入力packet読取=0,
        原本再読取=0, NPZ再読取=0, 旧103活動cache再読取=0, 旧64base再prepare=0, 新金融再生=0, 利益ラベル読取=0,
        現在API=0, 実注文=0, 旧source変更=0,
        事前固定SHA256=data.digest(REGISTER), source_SHA256=fixed['source_SHA256'],
        loader_source_SHA256={str(HERE.joinpath(name).relative_to(ROOT)): data.digest(HERE/name)
            for name in ('data.py', 'core.py', 'features.py')},
        追加Day実幅一致口座=0, 旧正常列と入口の保持口座=0)
    try:
        for session in fixed['sessions']:
            item = fixed['cache'][session]
            path = ROOT/item['path']
            before = path.stat()
            assert before.st_size == item['size'] and before.st_mtime_ns == item['mtime_ns']
            saved = path.read_bytes()
            result['入力packet読取'] += 1
            assert hashlib.sha256(saved).hexdigest() == item['SHA256']
            after = path.stat()
            assert before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns
            loaded = pickle.loads(gzip.decompress(saved))
            del saved
            if session == DAY:
                assert loaded['schema_version'] == 1 and loaded['session'] == session
                value = core.build_session(loaded['peer'], saved_prepared=loaded['prepared'])
                result['追加Day実幅一致口座'] += 2
            else:
                assert result['追加Day実幅一致口座'] == 2
                value = core.build_session(loaded, references=refs[session])
            result['旧正常列と入口の保持口座'] += 2
            output = HERE/'cache'/f'{session}.pkl.gz'
            assert not output.exists()
            output.parent.mkdir(parents=True, exist_ok=True)
            serialized = gzip.compress(pickle.dumps(value, protocol=5), compresslevel=3, mtime=0)
            output.write_bytes(serialized)
            cache[session] = dict(path=str(output.relative_to(ROOT)), SHA256=hashlib.sha256(serialized).hexdigest(), size=len(serialized))
            counts[session] = {entry: {symbol: dict(
                candidates=len(value['features'][entry][symbol]), raw_candidates=len(value['raw_features'][entry][symbol]),
                original_events=int(np.count_nonzero(value['cases'][entry][symbol]['event'])),
                q1={role: {str(window): dict(known=sum(measured[role][str(window)]['known'] for measured in value['features'][entry][symbol].values()),
                    unknown=sum(not measured[role][str(window)]['observed_known'] for measured in value['features'][entry][symbol].values()),
                    ambiguous=sum(measured[role][str(window)]['ambiguous'] for measured in value['features'][entry][symbol].values()))
                    for window in core.features.WINDOWS} for role in ('own', 'own_normal', 'peer')})
                for symbol in core.SYMBOLS} for entry in core.ENTRIES}
            del value, loaded, serialized
            print(session+' 入力完了', flush=True)
        verify_fixed(fixed)
        assert len(cache) == result['入力packet読取'] == 33
        assert result['旧正常列と入口の保持口座'] == 66 and result['追加Day実幅一致口座'] == 2
        result.update(全合格=True, 開始終端source一致=True,
            閾値適用=0, 入口条件変更=0, 無取引を勝ちと認定=0)
    except Exception as error:
        result.update(失敗=str(error), traceback=traceback.format_exc(), 開始終端source一致=False)
        write_json(OUTPUT, result)
        raise
    write_json(OUTPUT, result)
    return result


def main() -> None:
    """
    機能: 本文未読の登録と、根レビュー後の正式一回読取を明確に分ける。
    引数: CLIの--register-only又は--root-input-reviewed(bool)。
    返り値: None。無指定又は両指定で拒否し金融を実行しない。
    """
    parser = argparse.ArgumentParser(description='105の既存入力とQ1特徴だけを保存する')
    parser.add_argument('--register-only', action='store_true')
    parser.add_argument('--root-input-reviewed', action='store_true')
    arguments = parser.parse_args()
    if arguments.register_only == arguments.root_input_reviewed:
        parser.error('登録又は根レビュー済み正式読取を一つだけ明示してください')
    result = register() if arguments.register_only else run()
    print(json.dumps(dict(全合格=result['全合格'], 対象場数=result['対象場数']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
