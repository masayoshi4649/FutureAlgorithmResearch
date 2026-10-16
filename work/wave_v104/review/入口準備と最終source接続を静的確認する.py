"""104入口準備の静的契約を確認し、旧独立証跡を最終sourceへ追記接続する。"""

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = ROOT.parents[1]


def sha(path: Path) -> str:
    """
    機能: 小さい直接source又は独立証跡の内容指紋を読む。
    引数: path(Path)は対象資料。
    返り値: strはSHA256。原本及び金融台帳は対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 静的定義と既人工のJSONだけを読む。
    引数: path(Path)は小さい定義又は人工証跡。
    返り値: dictは読取内容。新旧の金融結果は読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def module(name: str, path: Path) -> object:
    """
    機能: 入口人工の既存fixtureを再利用するため小さいソースを接続する。
    引数: name(str)、path(Path)は固有名と人工又は入口部品。
    返り値: objectはモジュール。main、正式準備、金融を実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def definition(path: Path, name: str) -> ast.FunctionDef:
    """
    機能: 静的sourceから名前指定の関数だけを選ぶ。
    引数: path(Path)、name(str)は対象sourceと関数名。
    返り値: ast.FunctionDefは関数の構文。関数を実行しない。
    """
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(nodes) == 1
    return nodes[0]


def calls(node: ast.AST) -> set[str]:
    """
    機能: 静的関数の呼出名を抽出し、金融又はNPZ経路の混入を確認する。
    引数: node(ast.AST)は対象関数の構文。
    返り値: set[str]は末尾の呼出名。参照先の内容は別に静的確認する。
    """
    values = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Call):
            if isinstance(item.func, ast.Attribute):
                values.add(item.func.attr)
            elif isinstance(item.func, ast.Name):
                values.add(item.func.id)
    return values


# ----------------------------------------


def main() -> None:
    """
    機能: 新入口準備の静的契約と最終sourceの小人工接続だけを確認する。
    引数: なし。
    返り値: None。新しい追記証跡を一件保存し、旧独立出力は変更しない。
    """
    target = HERE/'入口準備と最終source接続の追記確認.json'
    assert not target.exists()
    refs = [ROOT/name for name in ('prepare.py', 'prepared_data.py', 'base.py', 'catalog.py',
        '数値設計案.json', '安定性の採用基準補足.json', 'peer/core.py', 'peer/api.py', 'peer/prices.py',
        'engine/core.py', 'engine/interface.py', 'engine/adapter.py', 'engine/old_finance_snapshot.py')]
    refs += [HERE/name for name in ('相手窓と支持追尾の独立人工.py', '入口競合消費と相手採否の独立人工.py',
        '旧気配資格と同出口接続の独立人工.py', '停止予約と注文経済の独立人工.py')]
    refs += [Path(__file__)]
    before = {str(path.relative_to(PROJECT)): sha(path) for path in refs}
    old_names = ('相手窓と支持追尾の独立人工.json', '入口競合消費と相手採否の独立人工.json',
        '停止予約と注文経済の独立人工.json', '旧気配資格と同出口接続の独立人工.json')
    old_proofs = {name: read(HERE/name) for name in old_names}
    old_hashes = {name: sha(HERE/name) for name in old_names}
    assert all(value['全合格'] for value in old_proofs.values())
    count = dict(静的金融非実行経路=0, 最終自己候補=0, 四reset_ORと時計診断分離=0,
        旧quote資格と相手窓=0, 全19normal接口の採否とmap=0, 最終出口接口接続=0,
        不変金融本体依存=0, 継承小source照合=0)
    for path, name in ((ROOT/'prepare.py', 'formal'), (ROOT/'base.py', 'load_prepared'),
                       (PROJECT/'work/wave_v103/base.py', 'load'),
                       (PROJECT/'work/wave_v103/activity/data.py', 'load_session')):
        actual = calls(definition(path, name))
        assert not actual & {'execute', 'play', 'simulate', 'read_npz_once', 'load_npz', 'loadtxt'}
        count['静的金融非実行経路'] += 1
    assert calls(definition(ROOT/'prepare.py', 'formal')) >= {'load_prepared', 'load_session', 'prepared_session'}
    loader = (ROOT/'prepared_data.py').read_text(encoding='utf-8')
    assert loader.index('hashlib.sha256(saved)') < loader.index('pickle.loads')
    assert 'base.immutable(value)' in loader and "metadata['新金融再生']" in loader
    # 旧103の完了freezeが既に固定した小sourceだけを再照合する。旧巨大全数入力は読まない。
    inherited = read(PROJECT/'work/wave_v103/金融事前固定.json')['source_SHA256']
    inherited_selected = {}
    for name in ('work\\wave_v103\\base.py', 'work\\wave_v103\\engine\\adapter.py',
                 'work\\wave_v102\\strategy.py', 'work\\wave_v102\\catalog.py',
                 'work\\wave_v102\\accounting.py'):
        wanted = inherited[name]
        assert sha(PROJECT/name) == wanted
        inherited_selected[name] = wanted
        count['継承小source照合'] += 1
    api = module('104最終静的入口API', ROOT/'peer/api.py')
    fixtures = module('104最終静的入口fixture', HERE/'入口競合消費と相手採否の独立人工.py')
    quotes = module('104最終静的quote_fixture', HERE/'旧気配資格と同出口接続の独立人工.py')
    widths = module('104最終静的窓_fixture', HERE/'相手窓と支持追尾の独立人工.py')
    for symbol, center in (('TOPIX', 4000.), ('NK225', 60000.)):
        for reflected in (False, True):
            account, raw = fixtures.competition_fixture(center, reflected)
            union = api.core.union_candidates(account, raw)
            assert [value['row'] for value in union] == [0, 1, 4, 6, 7, 8]
            assert len(union[1]['episodes']) == 1 and len(union[1]['competition_ready_episodes']) == 2
            expected = [center+5, center-5, center, center+3, center+4, center-3]
            if reflected:
                expected = [2*center-value for value in expected]
            assert [value['support_price'] for value in union] == expected
            count['最終自己候補'] += len(union)
        for case in ('正常', '旧quote資格だけ不正', '量だけの欠測', '数値BBO不正', '非normal'):
            account, execution = quotes.quote_fixture(symbol, case)
            actual = api.core.restore_account(account, execution)
            raw = actual['raw']
            np.testing.assert_array_equal(raw['entry_reset'], np.logical_or.reduce([raw[name] != 0 for name in
                ('price_reset_reason', 'depth_reset_reason', 'lp_reset_reason', 'volume_reset_reason')]))
            feature = api.prices.build(raw, account['item'], api.core.publications(raw), api.POLICY)
            assert feature['windows']['10']['direction_t1'][-1] == (1 if case in ('正常', '量だけの欠測') else 3)
            count['旧quote資格と相手窓'] += 1
        for fault in ('clock', 'seq'):
            account, execution = quotes.quote_fixture(symbol, '正常')
            if fault == 'clock':
                account['source']['price_time_s'][1] = execution['time_s'][1] = 0.
                account['source']['price_time_s'][0] = execution['time_s'][0] = 1.
            else:
                account['source']['raw_seq'][1:] += 1
                execution['seq'][1:] += 1
            # 元103 commonqualifiedが不正原行を拒否する契約を維持する。
            account['source']['qualified'][1] = False
            account['normal_record']['time_s'] = execution['time_s'].copy()
            account['normal_record']['seq'] = execution['seq'].copy()
            restored = api.core.restore_account(account, execution)
            assert restored['raw']['clock_or_sequence_invalid'][1] and not restored['raw']['entry_reset'][1]
            assert not restored['raw']['entry_quality'][1]
            count['四reset_ORと時計診断分離'] += 1
    for config in api.core.entries():
        for side in (1, -1):
            for state in (1, -1, 0, 2, 3):
                own, peer, feature, selection = fixtures.peer_fixture(state, True)
                own.update(raw_seq=np.array([100], np.int64), qualified=np.ones(1, bool), entry_reset=np.zeros(1, bool),
                    entry_quality=np.ones(1, bool), execution_to_raw_index=np.array([0], np.int64),
                    normal_execution_row=np.array([0], np.int64))
                candidate = dict(row=0, raw_seq=100, price_time_s=100., side=side, support_price=1000.,
                    self_lineages=[dict(family='C', anchor_raw_seq=100, support_price=1000.)])
                normal = dict(entry_quality=np.ones(1, bool), entry_reset=np.zeros(1, bool))
                value = api.filter_case(config, [candidate], own, peer, feature, selection, normal)
                expected = config['gate'] == 'OWN' or state == side or (config['gate'].startswith('N') and state == 0)
                assert value['normal']['entry_id'] == config['id'] and bool(value['normal']['event'][0]) == expected
                np.testing.assert_array_equal(value['normal']['execution_to_raw_index'], own['execution_to_raw_index'])
                count['全19normal接口の採否とmap'] += 1
    interface = module('104最終静的出口接口', ROOT/'engine/interface.py')
    for symbol in ('TOPIX', 'NK225'):
        prepared, case = quotes.capture_fixture(symbol)
        for ident in ('O', 'B1', 'B2', 'B4', 'T2', 'T4'):
            signal, config = interface.connect(prepared, case, ident)
            np.testing.assert_array_equal(signal['event'], case['event'])
            np.testing.assert_array_equal(signal['entry_quality'], case['entry_quality'])
            np.testing.assert_array_equal(signal['entry_reset'], case['entry_reset'])
            count['最終出口接口接続'] += 1
    # 600金融人工を再実行せず、実際に呼んだ金融本体と数値依存のexact指紋不変を使う。
    financial = old_proofs['停止予約と注文経済の独立人工.json']['SHA256']
    for name in ('engine/core.py', 'catalog.py', '数値設計案.json'):
        assert sha(ROOT/name) == financial[str(Path(name))]
        count['不変金融本体依存'] += 1
    assert all(sha(HERE/name) == wanted for name, wanted in old_hashes.items())
    after = {str(path.relative_to(PROJECT)): sha(path) for path in refs}
    assert before == after, '静的確認中に対象sourceが変更されました。'
    proof = dict(全合格=True, scope='最終104入口準備と接口の静的確認及び小人工接続。正式32準備/新金融は実行していない。',
        検査件数=count, SHA256=before, 旧独立四資料_SHA256=old_hashes,
        source更新の意味=dict(peer='四reset ORは不変、価格時計/seq派生診断を別欄へ分離。実103 qualified=Falseを救済しない。',
            interface='同normal三列の直接接続と既存cacheのcanonical alias。金融core及び数値式はexact不変。'),
        継承sourceの旧103固定一致=inherited_selected,
        静的結論=dict(入口='19条件は同自己候補、同normal id/map/資格を保持し、未知を中立へ救済しない。',
            準備='103活動gzip pickleと旧共通pickleだけを読む。原jsonl/103v2NPZの再読、金融body実行はない。',
            会計='researchは114単一、12追加実腿、6配分、旧参照1を商品別accountingへ接続。未完成assessment実装の合格は含まない。',
            採用='両商品活動16場/20親、損小利大/80割合、3安定性非悪化、最大勝ち除外黒字を結果前の条件とする。無活動は勝ちでない。'),
        要補足='入口準備の旧共通信号依存はこの旧103小source一致へ委譲。formal freezeでこの追記JSONを直接含める。',
        実行=dict(正式32準備=0, 新104金融=0, 金融body実行=0, 原本読取=0, NPZ読取=0, 保存cache読取=0,
                  API=0, 実注文=0, goalツール=0))
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=count, 証跡=str(target), SHA256=sha(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
