"""金融実行部のガードと可逆保存を、実ファイルを開かず人工値へ接続する。"""

from __future__ import annotations

import ast
import copy
from fractions import Fraction
from io import BytesIO
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import traceback

import numpy as np

from check_contract_plan_v2 import make_source_fixture

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
CHECKS = 0
REJECTS = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 独立の判定を数える。
    引数: value(bool)、detail(object)。
    返り値: None。不一致時は停止する。
    """
    global CHECKS
    CHECKS += 1
    assert value, detail


def sha(path: Path) -> str:
    """
    機能: 小さなsourceだけを指紋化する。
    引数: path(Path) 源。
    返り値: str SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def functions(names: tuple[str, ...], namespace: dict) -> dict:
    """
    機能: finance源から指定純関数だけを取り出す。
    引数: names(tuple[str,...])、namespace(dict) 人工の依存。
    返り値: dict 関数定義。module本体とmainは自動実行しない。
    """
    tree = ast.parse((BASE / 'finance.py').read_text(encoding='utf-8'))
    selected = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name in names]
    assert {x.name for x in selected} == set(names)
    exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), str(BASE / 'finance.py'), 'exec'), namespace)
    return namespace


def refused(call, name: str) -> None:
    """
    機能: 不一致の合成metadataが拒否されることを確かめる。
    引数: call(callable)、name(str)。
    返り値: None。
    """
    global REJECTS
    failed = False
    try:
        call()
    except (AssertionError, ValueError, KeyError, TypeError):
        failed = True
    check(failed, name)
    REJECTS += 1


def pure_pack_and_reader() -> dict:
    """
    機能: RLE全行復元と、bytes一回のNPZ読取をメモリだけで照合する。
    引数: なし。
    返り値: dict 合成読取の境界。実NPZの本文は読まない。
    """
    ns = functions(('primitive', 'curve_pack', 'curve_unpack', 'load_once'), dict(np=np, hashlib=hashlib, BytesIO=BytesIO))
    for size in (0, 1, 2, 19):
        for width in (1, 16):
            curve = np.arange(size * width, dtype=float).reshape(size, width)
            if size > 2:
                curve[1:4] = curve[0]
                curve[-1, 0] = np.nan
            packed = ns['curve_pack'](curve)
            np.testing.assert_array_equal(ns['curve_unpack'](packed), curve)
            expected = [i for i in range(size) if i == 0 or not np.array_equal(curve[i], curve[i-1], equal_nan=True)]
            check(packed['starts'].tolist() == expected, '独立したRLEの開始行')
            check(tuple(packed['shape']) == (size, width), '全原行と全列のshape保持')
    x = ns['primitive'](dict(未知=np.float64(np.nan), 無限=np.float64(np.inf), 零=np.float64(-0.), 件数=np.int64(4), 真偽=np.bool_(True)))
    check(x == dict(未知=None, 無限=None, 零=-0., 件数=4, 真偽=True), '未知を0へ変えず原始型化')
    json.dumps(x, ensure_ascii=False, allow_nan=False)
    check(True, 'JSONへ非有限値を渡さない')
    stream = BytesIO()
    events = np.zeros((2, 31), dtype=np.float64)
    np.savez_compressed(stream, events=events, outcomes=np.array([{'読むとallow_pickleで失敗': True}], dtype=object))
    raw = stream.getvalue()
    calls = dict(stat=0, read=0)
    class MemoryPath:
        """実ファイルを持たない、純NPZ bytesの一回読取用の位置。"""
        def __truediv__(self, value: str):
            """
            機能: 合成パスへ連結する。
            引数: value(str) 合成名。
            返り値: MemoryPath 自分自身。
            """
            return self
        def stat(self):
            """
            機能: メモリbytesの固定属性を返す。
            引数: self(MemoryPath)。
            返り値: SimpleNamespace 長さと疑似mtime。
            """
            calls['stat'] += 1
            return SimpleNamespace(st_size=len(raw), st_mtime_ns=7)
        def read_bytes(self) -> bytes:
            """
            機能: 合成bytesを一回数えて返す。
            引数: self(MemoryPath)。
            返り値: bytes 合成NPZ。
            """
            calls['read'] += 1
            return raw
    ns['plan'] = SimpleNamespace(ROOT=MemoryPath())
    info = dict(path='合成.npz', bytes=len(raw), mtime_ns=7, SHA256=hashlib.sha256(raw).hexdigest())
    counter = dict(合成=0)
    out = ns['load_once'](info, counter, '合成', ('events',))
    check(set(out) == {'events'} and not out['events'].flags.writeable, '未来配列をdecodeせずeventsだけ返す')
    check(calls == dict(stat=2, read=1) and counter == dict(合成=1), '同bytes一回で指紋とdecode')
    np.testing.assert_array_equal(out['events'], events)
    refused(lambda: ns['load_once'](dict(info, bytes=len(raw)+1), dict(合成=0), '合成', ('events',)), 'bytes違い')
    refused(lambda: ns['load_once'](dict(info, mtime_ns=8), dict(合成=0), '合成', ('events',)), 'mtime違い')
    refused(lambda: ns['load_once'](dict(info, SHA256='0'*64), dict(合成=0), '合成', ('events',)), '同bytesのSHA違い')
    refused(lambda: ns['load_once'](info, dict(合成=0), '合成', None), '全列decodeなら禁止object列を拒否')
    return {'RLE': '行を計算し直さず全列・NaN・元shapeを復元', '保存event': '一回読んだNPZ bytesに未来配列が含まれても、eventsだけをdecodeしengineへ渡す。物理bytes未読とは表現しない。'}


def guard_checks(catalog, sources: dict) -> tuple[dict, dict, dict]:
    """
    機能: 正式ガードを人工の固定・照合・登録と接続する。
    引数: catalog(module)、sources(dict) 現source指紋。
    返り値: tuple[dict,dict,dict] 合成namespace・固定・正式固定。実登録ではない。
    """
    sessions = [f'合成{i:02d}_Day' for i in range(33)]
    fixed = dict(全合格=True, sessions=sessions, inputs=[{'raw': {'session': s, 'symbol': y}} for s in sessions for y in catalog.CAP])
    proposal = dict(spec=dict(entry=dict(conditions=catalog.configs()), data=dict(inputs=fixed['inputs'], sessions=sessions), implementation=sources))
    audit = dict(全合格=True, 新金融=0, source_SHA256=sources, evidence=[dict(path='合成証跡.json', SHA256='c'*64)])
    table = {'入力と保存公開の固定.json': fixed, '試行計画.json': proposal, '金融初読前の人工と独立監査.json': audit,
             '正式照合の全出力.json': dict(終了コード=0, stdout=json.dumps({'proposal_complete': True})),
             '正式登録の全出力.json': dict(終了コード=0),
             'trials.json': dict(trials=[dict(id=catalog.TRIAL_ID, spec=copy.deepcopy(proposal['spec']))])}
    def digest(path: Path) -> str:
        """
        機能: 合成表の内容をJSON経由で指紋化する。
        引数: path(Path) 合成metadata名。
        返り値: str 合成SHA256。実ファイルを読まない。
        """
        if path.name == '合成証跡.json':
            return 'c'*64
        return hashlib.sha256(json.dumps(table[path.name], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    frozen = dict(全合格=True, source_SHA256=sources, source_configs=catalog.configs(),
                  input_SHA256=digest(BASE/'入力と保存公開の固定.json'), proposal_SHA256=digest(BASE/'試行計画.json'),
                  audit_SHA256=digest(BASE/'金融初読前の人工と独立監査.json'),
                  実行予定=dict(原NPZ=66, 保存eventNPZ=66, 新金融口座=792, 原板=0, API=0))
    table['金融前の正式固定.json'] = frozen
    plan = SimpleNamespace(HERE=BASE, ROOT=ROOT, read=lambda p: table[p.name], digest=digest, sources=lambda: sources)
    ns = functions(('guard',), dict(OUT=SimpleNamespace(exists=lambda: False), plan=plan, catalog=catalog, json=json))
    a, f = ns['guard']()
    check(a is fixed and f is frozen, '合成固定と正式固定の同一接続')
    original = copy.deepcopy(table)
    changes = (
        ('未完備照合を拒否', lambda: table['正式照合の全出力.json'].update(stdout=json.dumps({'proposal_complete': False}))),
        ('登録終了1拒否', lambda: table['正式登録の全出力.json'].update(終了コード=1)),
        ('registry spec違い', lambda: table['trials.json']['trials'][0]['spec'].update(implementation={})),
        ('registry重複ID', lambda: table['trials.json']['trials'].append(copy.deepcopy(table['trials.json']['trials'][0]))),
        ('凍結12条件不一致', lambda: table['金融前の正式固定.json'].update(source_configs=[])),
        ('金融済み監査拒否', lambda: table['金融初読前の人工と独立監査.json'].update(新金融=1)),
        ('source不一致', lambda: table['金融前の正式固定.json'].update(source_SHA256={})),
        ('固定目録SHA違い', lambda: table['金融前の正式固定.json'].update(input_SHA256='0'*64)),
        ('監査根拠SHA違い', lambda: table['金融初読前の人工と独立監査.json']['evidence'][0].update(SHA256='0'*64)),
        ('33場重複', lambda: table['入力と保存公開の固定.json']['sessions'].__setitem__(1, table['入力と保存公開の固定.json']['sessions'][0])),
        ('66組重複', lambda: table['入力と保存公開の固定.json']['inputs'].__setitem__(1, copy.deepcopy(table['入力と保存公開の固定.json']['inputs'][0]))),
        ('予定口座数の不一致', lambda: table['金融前の正式固定.json']['実行予定'].update(新金融口座=793)),
    )
    for label, mutate in changes:
        table.clear(); table.update(copy.deepcopy(original))
        mutate()
        refused(ns['guard'], label)
    table.clear(); table.update(copy.deepcopy(original))
    ns['OUT'] = SimpleNamespace(exists=lambda: True)
    refused(ns['guard'], '出力既存の自動再金融を拒否')
    return ns, original, sources


def dispatch_checks(catalog, contract, producer, sources: dict) -> dict:
    """
    機能: 実mainの66×12配線だけをメモリへ置き換え、未来結果の不使用を確かめる。
    引数: catalog/contract/producer(module)、sources(dict)。
    返り値: dict 合成dispatch数。実口座の運転や有効性検査ではない。
    """
    schema, raw, fields, events, start, end = make_source_fixture(producer)
    sessions = [f'合成{i:02d}_Day' for i in range(33)]
    items = []
    for s in sessions:
        for y in catalog.CAP:
            label = s + '_' + y
            items.append(dict(raw=dict(path=label, session=s, symbol=y, bounds=[start, end]), events=dict(path=label+'_events', n=2),
                              fields=fields, raw_rows=6, time_policy=dict(entry_start_s=start, entry_end_s=end-600, force_start_s=end-300, quiet_windows=[])))
    fixed = dict(inputs=items, schema=schema, sessions=sessions, 観測T=dict(TOPIX=.5, NK225=10.))
    expected = dict(原NPZ=66, 保存eventNPZ=66, 新金融口座=792, 原板=0, API=0)
    frozen = dict(実行予定=expected, source_SHA256=sources)
    reads, simulations, saves, captured = [], [], [], {}
    class MemoryOut:
        """合成mainで一切ファイルを作らない出力位置。"""
        def __init__(self, name='合成出力'):
            """
            機能: 合成名だけを保持する。
            引数: name(str)。
            返り値: None。
            """
            self.name = name
        def __truediv__(self, name):
            """
            機能: 合成の下位位置を作る。
            引数: name(str)。
            返り値: MemoryOut 下位位置。
            """
            return MemoryOut(self.name + '/' + name)
        def mkdir(self):
            """
            機能: 作成予定を受けるだけで実際には作らない。
            引数: self(MemoryOut)。
            返り値: None。
            """
            return None
    def loader(info: dict, counter: dict, label: str, only=None) -> dict:
        """
        機能: mainの入力呼出を数えて人工配列を返す。
        引数: info/counter(dict)、label(str)、only(tuple|None)。
        返り値: dict 人工配列。実ファイルは開かない。
        """
        check(only is None if label == '原NPZ' else only == ('events',), 'eventを列限定decodeする呼出')
        reads.append((info['path'], label)); counter[label] += 1
        return {k: v.copy() for k, v in raw.items()} if label == '原NPZ' else dict(events=events.copy())
    def simulator(arrays, signal, symbol, low, high, tick, policy, config, finish):
        """
        機能: 売買を実行せず、実mainから渡る引数だけを検査する。
        引数: sourceと同じ記憶内引数。
        返り値: dict 完了済みの空の代替値。金融会計検査に数えない。
        """
        check(set(signal) == {'events', 'fields', 'price_valid_mask'} and signal['fields'] == fields, '未来ラベルのないengine引数')
        check(finish is True and config in catalog.configs() and symbol in catalog.CAP, '正式固定と12条件')
        simulations.append((symbol, config['id']))
        return dict(completed=True, parent=[], actual_legs=[], counts={})
    def save(daily: dict, path) -> dict:
        """
        機能: 台帳保存の配線だけを数える。
        引数: daily(dict)、path(MemoryOut)。
        返り値: dict 合成目録。
        """
        saves.append(path.name)
        return dict(path=path.name, SHA256='b'*64, bytes=1)
    def account(symbol, session, daily):
        """
        機能: 本検査では配線だけの空rowを返す。
        引数: symbol/session(str)、daily(dict)。
        返り値: dict 空の合成会計row。
        """
        return dict(symbol=symbol, session=session)
    def periods(rows, parents, names, symbol, legs):
        """
        機能: 同条件66場から商品33場を渡す配線を検査する。
        引数: rows/parents/names/legs(list)、symbol(str)。
        返り値: dict 空の合成集計。
        """
        check(len(rows) == 66 and len([r for r in rows if r['symbol'] == symbol]) == 33, '集計の33場母数')
        check(names == sessions and not parents and not legs, '配線用の空親を有効性としない')
        return {}
    namespace = functions(('primitive', 'main'), dict(np=np, json=json, catalog=catalog, input_contract=contract,
        engine=SimpleNamespace(simulate=simulator), metrics=SimpleNamespace(account=account, periods=periods),
        plan=SimpleNamespace(sources=lambda: sources, write=lambda p,v: captured.update({p.name:v})),
        guard=lambda: (fixed, frozen), OUT=MemoryOut(), load_once=loader, save_ledger=save, diagnose=lambda *a: {}, print=lambda *a,**k: None))
    namespace['main']()
    check(len(reads) == len(set(reads)) == 132, '66原+66eventの一意dispatch')
    check(len(simulations) == len(saves) == len(set(saves)) == 792, '12×66の一意dispatch')
    value = captured['合成出力/結果.json']
    check(value['counts'] == expected and len(value['rows']) == 792, '金融前固定の予定個数')
    check(len(value['aggregate']) == 12, '全12条件を集計')
    return {'合成原列dispatch': 66, '合成eventdispatch': 66, '代替simulate呼出': 792, '原入力実読取': 0,
            '留保': 'main配線だけの検査。simulate/会計/台帳保存を代替し、新しい経済口座の試験へ数えない。'}


def main() -> None:
    """
    機能: SOURCE_ONLYの金融前配線だけを検査し小証跡を保存する。
    引数: なし。
    返り値: None。
    """
    proof = dict(全合格=False, 原入力=0, 原NPZ=0, 保存114事象=0, 過去金融=0, API=0)
    output = HERE / '金融ガードと一回decode及び可逆保存のSOURCE_ONLY独立接続.json'
    try:
        private = HERE / '指定二源と生成元の私有複製'
        def load(name: str, path: Path):
            """
            機能: 純関数だけの小moduleを読む。
            引数: name(str)、path(Path)。
            返り値: module。
            """
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            return module
        plan = load('金融前計画の定義', BASE / 'plan.py')
        sources = plan.sources()
        catalog = load('金融前catalogの定義', BASE / 'catalog.py')
        contract = load('金融前入力契約の定義', BASE / 'input_contract.py')
        producer = load('金融前人工生成元', private / 'producer.py')
        proof['読取と保存'] = pure_pack_and_reader()
        guard_checks(catalog, sources)
        proof['合成dispatch'] = dispatch_checks(catalog, contract, producer, sources)
        check(sources == plan.sources(), '検査中の完成九source不変更')
        proof.update(全合格=True, 確認数=CHECKS, 不整合拒否数=REJECTS, source_SHA256=sources,
                     独立checker_SHA256=sha(Path(__file__)), 正式登録='この検査では実施0。正式固定・registryとの現物一致は後で別監査。')
    except BaseException:
        proof.update(確認数=CHECKS, 不整合拒否数=REJECTS, 失敗=traceback.format_exc())
        raise
    finally:
        output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print(json.dumps({k: proof.get(k) for k in ('全合格','確認数','不整合拒否数','失敗')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
