"""保存生成元の逆写像を純合成で再現し、別試行R2のvalidateだけの訂正を監査する。"""

import ast
import copy
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import traceback

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]
OLD = ROOT / 'work/quantity_response_20261015'
PROOF = BASE / 'audit/正常行逆写像の修正と完成五sourceの独立接続.json'
NAMES = ('plan.py', 'run.py', 'engine.py', 'artificial_engine.py', 'artificial_run.py')
checks = 0


def check(value: bool, detail: object) -> None:
    """
    機能: 独立確認を数え、不成立なら停止する。
    引数: value(bool)は判定、detail(object)は根拠。
    返り値: None。
    """
    global checks
    checks += 1
    assert value, detail


def sha(path: Path) -> str:
    """
    機能: 小source又は小metadataだけを指紋化する。
    引数: path(Path)はsource又はJSON目録。
    返り値: strはSHA256。NPZを対象にしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source: Path, name: str) -> ast.FunctionDef:
    """
    機能: sourceから指定関数のASTだけを取得する。
    引数: source(Path)、name(str)は定義位置と関数名。
    返り値: FunctionDefは純検査対象。moduleの実行部は起動しない。
    """
    return next(node for node in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef) and node.name == name)


def validator(path: Path) -> object:
    """
    機能: 実runnerのvalidateだけを外部IOなしで接続する。
    引数: path(Path)はrunner source。
    返り値: objectは合成配列を検査する関数。
    """
    namespace = dict(np=np)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function(path, 'validate')], type_ignores=[])), str(path), 'exec'), namespace)
    return namespace['validate']


def run() -> dict:
    """
    機能: producer実関数の合成出力から正逆mapを検証し、R2の不変範囲を結ぶ。
    引数: なし。
    返り値: dictはSOURCE_ONLY監査。入力本文や測定結果を開かない。
    """
    sources = {(BASE / name).relative_to(ROOT).as_posix(): sha(BASE / name) for name in NAMES}
    owner_path = BASE / '正常行逆写像と分母及び原始型保存の純人工.json'
    owner = json.loads(owner_path.read_bytes())
    check(owner['全合格'] and owner['source_SHA256'] == sources and owner['測定NPZ'] == 0, '根131人工と現五源')
    old_false_path = OLD / 'measurement/False.json'
    old_false = json.loads(old_false_path.read_bytes())
    check(not old_false['全合格'] and old_false['counts']['NPZ本文'] == 1 and old_false['counts']['測定口座'] == 0, '初版1読測定0の履歴')
    check(all(sha(ROOT / name) == digest for name, digest in old_false['source_SHA256'].items()), '初版失敗時五源を保持')
    check(sha(BASE / '入力と観測の小固定.json') == sha(OLD / '入力と観測の小固定.json'), '同66入力目録を無変更継承')
    fixed = json.loads((BASE / '入力と観測の小固定.json').read_bytes())
    schema = fixed['schema']
    check(schema['normal_execution_row'] == dict(dtype='int32', shape=['N']), '逆mapはint32でboolではない')
    check(schema['execution_to_raw_index'] == dict(dtype='int64', shape=['M']), '順mapはint64')
    for name in ('engine.py', 'artificial_engine.py'):
        check(sha(BASE / name) == sha(OLD / name), ('観測core再利用同bytes', name))
    for name in ('primitive', 'group', 'summarize', 'aggregate'):
        check(ast.dump(function(BASE / 'run.py', name), include_attributes=False) == ast.dump(function(OLD / 'run.py', name), include_attributes=False), ('集計と保存の不変更', name))
    # ----------------------------------------
    producer_path = ROOT / 'work/wave_v103/input/core.py'
    raw = producer_path.read_bytes()
    snapshot = HERE / 'producer実関数の私有複製'
    snapshot.mkdir(exist_ok=False)
    copied = snapshot / 'producer103.py'
    copied.write_bytes(raw)
    spec = importlib.util.spec_from_file_location('逆写像の生成元を純合成で呼ぶ', copied)
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    check(producer.schema()['columns'] == schema, 'producer44列型形状の同値')
    begin = datetime(2026, 1, 5, 9, tzinfo=timezone(timedelta(hours=9)))
    start, end = begin.timestamp() - 60, begin.timestamp() + 60
    rows = []
    for index in range(6):
        raw_row = dict(Symbol='合成', SymbolName='合成', Exchange=23, CurrentPrice=100 + index,
            CurrentPriceTime=(begin + timedelta(seconds=index)).isoformat(), TradingVolume=1000 + index,
            TradingVolumeTime=(begin + timedelta(seconds=index)).isoformat())
        for level in range(1, 11):
            raw_row['Buy' + str(level)] = dict(Price=100 + index - level, Qty=10 + level)
            raw_row['Sell' + str(level)] = dict(Price=99 + index + level, Qty=20 + level)
        rows.append((index, raw_row))
    base, _ = producer.extract_rows(rows, start, end)
    validate, old_validate = validator(BASE / 'run.py'), validator(OLD / 'run.py')
    fixtures = []
    for selected in ([], [0], [1], [0, 2, 5], [1, 3, 4], list(range(6))):
        selected_array = np.array(selected, np.int64)
        record = {old: base[name][selected_array].copy() for name, old in (
            ('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask'))}
        arrays, _ = producer.extract_rows(rows, start, end, record)
        expected = np.full(6, -1, np.int32)
        expected[selected_array] = np.arange(len(selected), dtype=np.int32)
        check(np.array_equal(arrays['normal_execution_row'], expected), ('生成元の逆map意味', selected))
        check(np.array_equal(arrays['execution_to_raw_index'], selected_array), ('生成元の順map意味', selected))
        validate(arrays, schema)
        check(not any(value.flags.writeable for value in arrays.values()), ('44列readonly', selected))
        if selected == [0, 2, 5]:
            old_refused = False
            try:
                old_validate({key: value.copy() for key, value in arrays.items()}, schema)
            except AssertionError:
                old_refused = True
            check(old_refused, '旧flatnonzero誤仮定をproducer合成で再現')
            fixtures.append(arrays)
    sample = fixtures[0]
    for label, mutate in (
        ('未対応-2拒否', lambda a: a['normal_execution_row'].__setitem__(1, -2)),
        ('正常ID順序違い拒否', lambda a: a['normal_execution_row'].__setitem__([0, 2], [1, 0])),
        ('余計な正常ID拒否', lambda a: a['normal_execution_row'].__setitem__(1, 3)),
        ('正常ID欠落拒否', lambda a: a['normal_execution_row'].__setitem__(0, -1)),
        ('順map重複拒否', lambda a: a['execution_to_raw_index'].__setitem__(1, 0)),
        ('順map範囲外拒否', lambda a: a['execution_to_raw_index'].__setitem__(2, 6)),
        ('逆mapをboolへ変更拒否', lambda a: a.update(normal_execution_row=a['normal_execution_row'].astype(bool)))):
        broken = {key: value.copy() for key, value in sample.items()}
        mutate(broken)
        refused = False
        try:
            validate(broken, schema)
        except AssertionError:
            refused = True
        check(refused, label)
    # ----------------------------------------
    correction_path = ROOT / 'work/wave_v103/input_v2/correction.py'
    namespace = dict(np=np, CHANGED=('volume_delta_usable', 'volume_delta'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function(correction_path, 'correct_arrays')], type_ignores=[])), str(correction_path), 'exec'), namespace)
    corrected, diagnosis = namespace['correct_arrays'](sample)
    check(diagnosis['不変配列数'] == 42, 'v2は42列を保持')
    for key in ('normal_execution_row', 'execution_to_raw_index'):
        check(np.array_equal(corrected[key], sample[key]), ('v2でもmap同一', key))
    held_path = ROOT / 'work/wave_v104/holdout_input/core.py'
    held_source = held_path.read_text(encoding='utf-8')
    check("raw['normal_execution_row'][indexes] = np.arange(len(indexes), dtype=np.int32)" in held_source, '104も逆ID構築')
    check("raw['execution_to_raw_index'] = indexes.astype(np.int64)" in held_source, '104も順map構築')
    check("functions['source'].extract_rows" in held_source and "functions['correction'].correct_arrays(raw)" in held_source, '104は103の未対応-1とv2不変を継承')
    # ----------------------------------------
    old_plan = json.loads((OLD / '試行計画.json').read_bytes())
    generated = {}
    def fake_read(path: Path) -> dict:
        """
        機能: R2freezeへ小固定又は合成監査だけを渡す。
        引数: path(Path)はmetadata指定。
        返り値: dictはSOURCE_ONLYの値。
        """
        return fixed if path.name == '入力と観測の小固定.json' else dict(全合格=True, 入力本文=0, source_SHA256=sources, evidence=[])
    def fake_write(path: Path, value: dict) -> None:
        """
        機能: 正式builderの予定JSONをメモリ捕捉する。
        引数: path(Path)、value(dict)は出力予定。
        返り値: None。正式freezeファイルを書かない。
        """
        generated[path.name] = copy.deepcopy(value)
    namespace = dict(HERE=BASE, ROOT=ROOT, TRIAL='114R2_正常行逆写像を訂正した公表活動と数量後の純先着',
        read=fake_read, write=fake_write, sources=lambda: sources, digest=lambda path: sha(path) if path.exists() else '合成', json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function(BASE / 'plan.py', 'freeze')], type_ignores=[])), 'R2仕様のメモリ捕捉だけ', 'exec'), namespace)
    namespace['freeze']()
    proposal = generated['試行計画.json']
    check(proposal['purpose'] == '不具合修正' and proposal['compares_to'] == [old_plan['id']], '修正試行の系譜')
    for part in ('entry', 'management', 'exit', 'allocation', 'costs', 'execution'):
        check(proposal['spec'][part] == old_plan['spec'][part], ('観測条件の不変更', part))
    for key in ('sessions', 'inputs', 'schema'):
        check(proposal['spec']['data'][key] == old_plan['spec']['data'][key], ('入力定義不変更', key))
    checker_path = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    checker_spec = importlib.util.spec_from_file_location('R2の八部品完全性だけ', checker_path)
    checker = importlib.util.module_from_spec(checker_spec)
    checker_spec.loader.exec_module(checker)
    check(checker.analyze(proposal, [])['proposal_complete'], 'R2八部品の実checker完全性')
    diffs = {name: '\n'.join(difflib.unified_diff((OLD / name).read_text(encoding='utf-8').splitlines(),
        (BASE / name).read_text(encoding='utf-8').splitlines(), n=3)) for name in ('plan.py', 'run.py', 'artificial_run.py')}
    check({(BASE / name).relative_to(ROOT).as_posix(): sha(BASE / name) for name in NAMES} == sources, '修正五源不変更')
    check(all(sha(ROOT / name) == digest for name, digest in old_false['source_SHA256'].items()), '初版五源も不変更')
    return dict(全合格=True, 検査数=checks, source_SHA256=sources,
        producer_source_SHA256={path.relative_to(ROOT).as_posix(): sha(path) for path in (producer_path, correction_path, held_path)},
        観測条件不変=True, map契約='normal_execution_rowはint32逆map。未対応−1、対応は正常ID0..M−1。boolflagではない。',
        修正差分=diffs, 根人工SHA256=sha(owner_path), 初版False_SHA256=sha(old_false_path),
        読取履歴=dict(根初版NPZ=1, 根初版測定口座=0, 根初版engine呼出=0, R2現時点本文=0,
                       R2予定NPZ=66, 完走時の累計予定=67, 再読を独立追加標本としない=True),
        監査不足の是正='初版の独立監査はbool代入の人工mapを受理し、producer逆IDの−1/0契約を追わなかった。今回はproducer実関数の合成出力を起点に訂正。',
        再利用='旧core/owner人工2源同bytesの監査を再利用。新しい有効性証拠として追加しない。',
        正式登録成功='修正版は未確認。根が次にfreeze/check/registerの終端を回収する。',
        入力本文=0, NPZ=0, cache=0, 原板=0, 元金融=0, API=0, 新金融=0,
        監査sourceSHA256=sha(Path(__file__)))


def main() -> None:
    """
    機能: 生成元の純合成とR2のsource接続を新規保存する。
    引数: なし。
    返り値: None。失敗は上書きせず残す。
    """
    PROOF.parent.mkdir(parents=True, exist_ok=True)
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
