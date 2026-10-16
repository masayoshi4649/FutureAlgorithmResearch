"""数量測定の五sourceと実読取前guard及び窓終了の排他分母を接続する。"""

import ast
import copy
import difflib
import math
import hashlib
import importlib.util
import sys
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
PROOF = HERE / '完成五sourceと実読取前guard及び窓終了分母の独立接続_v3.json'
NAMES = ('plan.py', 'run.py', 'engine.py', 'artificial_engine.py', 'artificial_run.py')
checks = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 条件の成立を数え、不一致なら根拠とともに止める。
    引数: value(bool)は成立判定、detail(object)は根拠。
    返り値: None。
    """
    global checks
    checks += 1
    assert value, detail


def sha(path: Path) -> str:
    """
    機能: source又は小証跡の現在指紋を計算する。
    引数: path(Path)はsource又は小資料。
    返り値: strはSHA256。実数量本体を対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict:
    """
    機能: 現五sourceと人工への結合、実guard、JSON、窓末分母を純合成で検査する。
    引数: なし。
    返り値: dictはSOURCE_ONLY接続。正式登録やNPZ実読取ではない。
    """
    sources = {(BASE / name).relative_to(ROOT).as_posix(): sha(BASE / name) for name in NAMES}
    core_path = HERE / '完成数量coreと独立episode及び価格先着のSOURCE_ONLY接続_v2.json'
    core = json.loads(core_path.read_bytes())
    check(core['全合格'] and core['source_SHA256']['engine.py'] == sources[(BASE / 'engine.py').relative_to(ROOT).as_posix()], '独立core同値')
    owner_path = BASE / '固定BBO数量と公表活動及び価格先着の人工検査.json'
    owner = json.loads(owner_path.read_bytes())
    check(owner['全合格'] and all(sources[(BASE / name).relative_to(ROOT).as_posix()] == digest for name, digest in owner['source_SHA256'].items()), 'owner二源束縛')
    root_path = BASE / '根の分母と対応及び原始型保存の純人工_v3.json'
    root = json.loads(root_path.read_bytes())
    check(root['全合格'] and root['source_SHA256'] == sources and root['測定NPZ'] == 0, 'root130五源束縛')
    code = (BASE / 'run.py').read_text(encoding='utf-8')
    tree = ast.parse(code)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = dict(np=np, Path=Path)
    helpers = [node for node in functions if node.name in ('primitive', 'group', 'summarize', 'aggregate', 'validate')]
    exec(compile(ast.fix_missing_locations(ast.Module(body=helpers, type_ignores=[])), '私有の表示集計と資格だけ', 'exec'), namespace)
    # ----------------------------------------
    execute = next(node for node in functions if node.name == 'execute')
    guard = []
    for node in execute.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'mkdir':
            break
        guard.append(node)
    check(bool(guard) and isinstance(guard[-1], ast.Assert), 'mkdirより前のguardだけ抽出')
    guard_func = ast.FunctionDef(name='guard_only', args=copy.deepcopy(execute.args), body=guard, decorator_list=[], returns=None, type_comment=None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[guard_func], type_ignores=[])), '実本文より前のguard純合成', 'exec'), namespace)
    sessions = [f'人工{index:02d}' for index in range(33)]
    inputs = [dict(session=session, symbol=symbol) for session in sessions for symbol in ('TOPIX', 'NK225')]
    values = dict(fixed=dict(sessions=sessions, inputs=inputs),
        proposal=dict(spec=dict(implementation=sources, data=dict(inputs=inputs, sessions=sessions, input_manifests=[dict(path='入力と観測の小固定.json', sha256='fixed')]))),
        frozen=dict(全合格=True, 金融=False, source_SHA256=sources, input_fixed_SHA256='fixed', proposal_SHA256='proposal', audit_SHA256='audit'),
        audit=dict(全合格=True, 入力本文=0, source_SHA256=sources, evidence=[dict(path='合成のみ', SHA256='evidence')]))

    def guard_call(selected: dict) -> None:
        """
        機能: 実guardへ合成read/digestだけを与え、実登録と入力を一切開かず評価する。
        引数: selected(dict)は合成の正式固定・計画・監査。
        返り値: None。guard以後のmkdir/実測は抽出していない。
        """
        mapping = {'実測前の正式固定.json': selected['frozen'], '入力と観測の小固定.json': selected['fixed'],
            '試行計画.json': selected['proposal'], '本体初読前の人工と独立監査.json': selected['audit'],
            'registry': dict(trials=[dict(id='合成ID', spec=selected['proposal']['spec'])])}
        digests = {'入力と観測の小固定.json': 'fixed', '試行計画.json': 'proposal', '本体初読前の人工と独立監査.json': 'audit', '合成のみ': 'evidence'}
        namespace.update(plan=SimpleNamespace(read=lambda path: mapping[path.name], sources=lambda: sources,
            digest=lambda path: digests[path.name], TRIAL='合成ID'), HERE=HERE, ROOT=HERE,
            REGISTRY=Path('registry'), OUT=HERE / '実測しない未作成出力')
        namespace['guard_only']()

    guard_call(copy.deepcopy(values))
    check(True, '実guard正常系接続')
    for name, mutate in (
        ('入力manifest違い', lambda x: x['proposal']['spec']['data']['input_manifests'][0].update(sha256='wrong')),
        ('登録source違い', lambda x: x['proposal']['spec']['implementation'].update(偽='x')),
        ('固定source違い', lambda x: x['frozen']['source_SHA256'].update(偽='x')),
        ('監査本文未読資格なし', lambda x: x['audit'].update(入力本文=1)),
        ('入力重複', lambda x: x['fixed']['inputs'].__setitem__(1, copy.deepcopy(x['fixed']['inputs'][0]))),
        ('商品集合違い', lambda x: x['fixed']['inputs'][0].update(symbol='その他')),
        ('場数違い', lambda x: x['fixed']['sessions'].append('追加')),
        ('登録データ不一致', lambda x: x['proposal']['spec']['data'].update(inputs=[]))):
        bad = copy.deepcopy(values)
        # deepcopyは共有source dictも共有を保つので、比較対象を別dictへ明示分離する。
        bad['proposal']['spec']['implementation'] = copy.deepcopy(sources)
        bad['frozen']['source_SHA256'] = copy.deepcopy(sources)
        bad['audit']['source_SHA256'] = copy.deepcopy(sources)
        mutate(bad)
        rejected = False
        try:
            guard_call(bad)
        except AssertionError:
            rejected = True
        check(rejected, name)
    # ----------------------------------------
    fields = ['type', 'episode', 'd', 'bid', 'ask', 'opposite_q0', 'quantity_ratio', 'minimum_quantity_ratio', 'total_volume', 'npositive']
    events, outcomes = [], []
    settings = [(1, 1., 1., 1), (-1, .5, .5, -1), (1, 1.5, .75, 3), (-1, 2., 1.5, 0), (1, .75, .5, 2)]
    for episode, (side, ratio, minimum, code_) in enumerate(settings):
        for type_ in ((0,) if episode == 4 else (0, 1)):
            events.append([type_, episode, side, 100, 101, 10, ratio, minimum, 10, 1])
            outcomes.append([code_, 30 + episode])
    events, outcomes = np.array(events, float), np.array(outcomes, float)
    summary = namespace['summarize'](events, outcomes, fields, 1)
    for name, indices in dict(type0_all=[0, 2, 4, 6, 8], type0_reached=[0, 2, 4, 6], type1_all=[1, 3, 5, 7],
                              type1_decreased=[3], type1_maintained=[1, 5, 7], type1_never_below=[1, 7], type1_recovered=[5]).items():
        codes = [outcomes[index, 0] for index in indices]
        group = summary[name]
        check(group['n'] == len(indices), (name, '全分母'))
        for key, code_ in (('plus', 1), ('minus', -1), ('unknown', 0), ('eof', 2), ('window_end', 3)):
            check(group[key] == codes.count(code_), (name, key))
        denom = codes.count(1) + codes.count(-1)
        check(group['rate'] == (codes.count(1) / denom if denom else None), (name, '先着だけ分母'))
    primitive = namespace['primitive'](dict(型=[np.bool_(True), np.int64(1), np.float64(.5), None, np.array([1, 2])]))
    check(json.loads(json.dumps(primitive, allow_nan=False)) == {'型': [True, 1, .5, None, [1, 2]]}, '全payload保存型')
    for nonfinite in (float('nan'), np.float64(float('inf'))):
        rejected = False
        try:
            namespace['primitive'](dict(値=nonfinite))
        except AssertionError:
            rejected = True
        check(rejected, '非有限原始型を拒否')
    # ----------------------------------------
    before_load = code.index('raw = source.read_bytes()')
    for phrase in ("proposal['spec']['implementation'] == frozen['source_SHA256']", "len(fixed['sessions']) == 33", "(session, symbol) for session in fixed['sessions'] for symbol in ('TOPIX', 'NK225')"):
        check(code.index(phrase) < before_load, ('実読取より前のguard', phrase))
    for phrase in ('analysis_outcomes = outcomes.copy()', 'analysis_outcomes[scope_end, 0] = 3',
        'outcomes=outcomes, analysis_outcomes=analysis_outcomes', "terminal_price_reason=result['price_reason_mask'][terminal]",
        "他原因が併存し得る。3と残り0は排他的内訳。", "item['bounds'][1] - 1 <= final_clock < item['bounds'][1]"):
        check(phrase in code, ('窓末内訳と元code保存', phrase))
    plan_code = (BASE / 'plan.py').read_text(encoding='utf-8')
    for phrase in ("'engine.py', 'artificial_engine.py', 'artificial_run.py'", "audit['入力本文'] == 0", "audit['source_SHA256'] == sources()", "digest(ROOT / evidence['path']) == evidence['SHA256']"):
        check(phrase in plan_code, ('formal前監査指紋guard', phrase))
    archived = BASE / 'archive/正式初版登録不適合'
    old_proof = json.loads((HERE / '完成五sourceと実読取前guard及び窓終了分母の独立接続_v2.json').read_bytes())
    diffs = {}
    for name in ('plan.py', 'run.py', 'artificial_run.py'):
        relative = (BASE / name).relative_to(ROOT).as_posix()
        check(sha(archived / name) == old_proof['source_SHA256'][relative], ('修正前保全', name))
        previous = (archived / name).read_text(encoding='utf-8')
        current = (BASE / name).read_text(encoding='utf-8')
        diffs[name] = '\n'.join(difflib.unified_diff(previous.splitlines(), current.splitlines(), n=3))
    old_run_ast = ast.parse((archived / 'run.py').read_text(encoding='utf-8'))
    for name in ('primitive', 'validate', 'group', 'summarize', 'aggregate'):
        prior = next(node for node in old_run_ast.body if isinstance(node, ast.FunctionDef) and node.name == name)
        current = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        check(ast.dump(prior, include_attributes=False) == ast.dump(current, include_attributes=False), ('観測分母と資格は不変更', name))
    manager_path = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
    manager_tree = ast.parse(manager_path.read_text(encoding='utf-8'))
    validators = [node for node in manager_tree.body if isinstance(node, ast.FunctionDef) and node.name in ('local_path', 'validate')]
    formal_namespace = dict(ROOT=ROOT, Path=Path, math=math)
    exec(compile(ast.fix_missing_locations(ast.Module(body=validators, type_ignores=[])), '正式manageの実schema検査だけ', 'exec'), formal_namespace)
    small_path = BASE / '入力と観測の小固定.json'
    prospective = dict(id='独立合成schema', name='独立合成schema', spec=dict(
        data=dict(sessions=sessions, input_manifests=[dict(path=small_path.relative_to(ROOT).as_posix(), sha256=sha(small_path))]), implementation=sources))
    bank = dict(rules=dict(rules=[]), knowledge=dict(findings=[]), trials=dict(trials=[prospective], repetition_audit=[]), studies=dict(studies=[]))
    formal_namespace['validate'](bank, deep=False)
    check(True, '正式manageの現schemaへflat source5とinput_manifestが接続可能')
    duplicate_path = manager_path.with_name('duplicate_check.py')
    duplicate_spec = importlib.util.spec_from_file_location('数量測定の独立八部品完全性', duplicate_path)
    duplicate = importlib.util.module_from_spec(duplicate_spec)
    duplicate_spec.loader.exec_module(duplicate)
    current_fixed = json.loads((BASE / '入力と観測の小固定.json').read_bytes())
    generated = {}
    audit_value = dict(全合格=True, 入力本文=0, source_SHA256=sources, evidence=[dict(path=core_path.relative_to(ROOT).as_posix(), SHA256=sha(core_path))])
    def synthetic_read(path: Path) -> dict:
        """
        機能: 実freezeへ実入力目録と合成監査だけを渡す。
        引数: path(Path)は要求された小metadata。
        返り値: dictは小目録又は合成のSOURCE_ONLY監査。
        """
        return current_fixed if path.name == '入力と観測の小固定.json' else audit_value
    def synthetic_write(path: Path, value: dict) -> None:
        """
        機能: 実freezeの出力をメモリだけへ捕捉する。
        引数: path(Path)、value(dict)は予定出力。
        返り値: None。正式ファイルを書かない。
        """
        check(path.name not in generated, '同名合成出力の重複なし')
        generated[path.name] = copy.deepcopy(value)
    def synthetic_digest(path: Path) -> str:
        """
        機能: メモリ捕捉済みの提案又は実在小metadataの指紋を返す。
        引数: path(Path)は予定小資料。
        返り値: strは保存形式と同じSHA256。
        """
        return hashlib.sha256((json.dumps(generated[path.name], ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')).hexdigest() if path.name in generated else (sha(path) if path.exists() else '合成監査指紋')
    plan_tree = ast.parse(plan_code)
    freeze_function = next(node for node in plan_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'freeze')
    freeze_ns = dict(read=synthetic_read, write=synthetic_write, digest=synthetic_digest, sources=lambda: sources,
        HERE=BASE, ROOT=ROOT, TRIAL='独立SOURCE_ONLY合成', json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[freeze_function], type_ignores=[])), '実freezeのメモリだけへの捕捉', 'exec'), freeze_ns)
    freeze_ns['freeze']()
    built = generated['試行計画.json']
    complete = duplicate.analyze(built, [])
    check(complete['proposal_complete'] is True and complete['提案不完全理由'] == [], '実八部品checkerの提案完全true')
    for part in ('allocation', 'costs', 'execution'):
        check(isinstance(built['spec'][part], dict) and bool(built['spec'][part]), ('三部品非空dict', part))
        broken = copy.deepcopy(built)
        broken['spec'][part] = '売買なしの記述だけ'
        check(duplicate.analyze(broken, [])['proposal_complete'] is False, ('旧文字列部品を拒否', part))
    formal_namespace['validate'](dict(rules=dict(rules=[]), knowledge=dict(findings=[]), trials=dict(trials=[built], repetition_audit=[]), studies=dict(studies=[])), deep=False)
    check(True, '実freeze生成物をmanage実validatorでも受理')
    register_path = BASE / 'register.py'
    register_code = register_path.read_text(encoding='utf-8')
    register_tree = ast.parse(register_code)
    register_main = next(node for node in register_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    fake_here = HERE / '登録helperの合成固定だけ'
    fake_here.mkdir(exist_ok=False)
    (fake_here / '実測前の正式固定.json').write_text('{}', encoding='utf-8')
    for mode, expected_calls in (('complete_false', 1), ('complete_true', 2), ('check_failure', 1), ('register_failure', 2)):
        calls = []
        def fake_subprocess(command: list, **kwargs: object) -> object:
            """
            機能: 登録helperの外部processを純合成の終了コードへ置換する。
            引数: command(list)とkwargs(dict)は予定process指定。
            返り値: objectは合成stdout/終了コード。実manageを起動しない。
            """
            stage = command[5]
            calls.append(stage)
            failure = mode == 'check_failure' and stage == 'check' or mode == 'register_failure' and stage == 'register'
            return SimpleNamespace(returncode=1 if failure else 0, stdout=json.dumps(dict(proposal_complete=mode != 'complete_false')), stderr='')
        reg_ns = dict(json=json, sys=sys, subprocess=SimpleNamespace(run=fake_subprocess),
            plan=SimpleNamespace(HERE=fake_here, ROOT=ROOT, write=lambda path, value: None))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[register_main], type_ignores=[])), '登録helperの完全性gateだけ', 'exec'), reg_ns)
        rejected = False
        try:
            reg_ns['main']()
        except AssertionError:
            rejected = True
        check(len(calls) == expected_calls, ('実registerへ進む条件', mode, calls))
        check(rejected == (mode != 'complete_true'), ('終了コードと完全性の拒否', mode))
    check({(BASE / name).relative_to(ROOT).as_posix(): sha(BASE / name) for name in NAMES} == sources, '現五source不変更')
    return dict(全合格=True, 検査数=checks, source_SHA256=sources,
        登録形式訂正='実register前の提案不完全を保持。allocation/costs/executionの3記述を非空dictへし、実checker完全性trueと登録helperのfalse停止を追加検査。core/runner観測は不変更。',
        修正差分=diffs, 正式validator_SHA256=sha(manager_path),
        提案完全性checker_SHA256=sha(duplicate_path), 実freezeの提案完全=True, 登録helper_SHA256=sha(register_path),
        実登録成功='未確認。根がこれから正式freezeとcheck/registerの終端を回収する。',
        evidence=[dict(path=core_path.relative_to(ROOT).as_posix(), SHA256=sha(core_path)),
                  dict(path=owner_path.relative_to(ROOT).as_posix(), SHA256=sha(owner_path)),
                  dict(path=root_path.relative_to(ROOT).as_posix(), SHA256=sha(root_path))],
        scope='SOURCE_ONLY最終接続。rootの正式freeze/実登録/66NPZ本文初読はまだ次の操作。',
        留保=['観測窓末は取引場末完備ではない。code3は元code0の排他的な窓終了を含む内訳で他理由が併存し得る。',
              '条件付き純価格先着だけ。1T順行は約定可能利益や心理、真の補充を証明しない。',
              'type1達成集合のtype0/type1同値は同BBOの数学的対照であり二重の独立成功標本ではない。'],
        入力本文=0, NPZ=0, cache=0, 原板=0, 元金融=0, API=0, 新金融=0,
        監査sourceSHA256=sha(Path(__file__)))


def main() -> None:
    """
    機能: source最終接続を保存し、Falseがあれば上書きしない。
    引数: なし。
    返り値: None。
    """
    assert not PROOF.exists()
    try:
        result = run()
    except Exception as error:
        result = dict(全合格=False, 検査数=checks, 理由=str(error), traceback=traceback.format_exc(), 入力本文=0, NPZ=0, API=0, 新金融=0)
        PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        raise
    PROOF.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査数=checks, SHA256=sha(PROOF)), ensure_ascii=False))


if __name__ == '__main__':
    main()
