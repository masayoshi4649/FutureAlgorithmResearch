"""初版の保存失敗を保全し、型変換だけの修正版をSOURCE_ONLYで確認する。"""

import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT/'work/e01_opportunity_trace_20261015/prepare'
NEW = ROOT/'work/e01_opportunity_trace_20261015/prepare_v2'
OUTPUT = HERE/'保存原始型だけの修正と初回読取履歴の独立SOURCE_ONLY接続.json'
EXPECTED = {
    '厳密joinと公開符号及び当時窓接頭の純人工.json': 'df3e254648ef9ef9fbbea0565dc21c644d24bff3cac70d4416a9c3439d70f4c8',
    '元公開と紙上継続窓の非金融一読診断計画.json': 'd3ca5faf579bfca1460e14c9845999f126e18260e985afe7d9abdeefc9a21b4a',
    '二cacheの小目録固定.json': '57ad4fa098f7a04d425f308070e4d89d5c9004998e66c7e9c172174318a89825',
    '初回全33の保存Falseと原23源の保全.json': '08463da03f564dba4a375e9be2df23e6b32590ec1ed5dcfac08bc121749ed973',
}
CHECKS = []


def digest(saved: bytes) -> str:
    """
    機能: 読取済みの小資料又はsourceの指紋を作る。
    引数: saved(bytes) は許可範囲の内容。
    返り値: str はSHA256。大型本文は受け取らない。
    """
    return hashlib.sha256(saved).hexdigest()


def check(ok: bool, label: str) -> None:
    """
    機能: 型変換・署名・継承の独立判断を分類付きで残す。
    引数: ok(bool)、label(str) は判断と分類。
    返り値: None。不一致は停止する。
    """
    assert bool(ok), label
    CHECKS.append(label)


def primitive(value: object) -> object:
    """
    機能: 独立比較用に初版出力のNumPy scalarだけをPython原始型へ正規化する。
    引数: value(object) は合成の辞書・リスト又は値。
    返り値: object は意味を保った比較値。欠測や非有限値を零にしない。
    """
    if isinstance(value, dict):
        return {key: primitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [primitive(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    assert isinstance(value, (str, bool, int, float, type(None))), type(value)
    return value


def native(value: object) -> bool:
    """
    機能: 出力の全末端がJSON原始型であることを再帰的に確認する。
    引数: value(object) は合成出力。
    返り値: bool はNumPy値を含まないか。JSON encoderへ暗黙変換を任せない。
    """
    if isinstance(value, dict):
        return all(isinstance(key, str) and native(item) for key, item in value.items())
    if isinstance(value, list):
        return all(native(item) for item in value)
    return type(value) in (str, bool, int, float, type(None))


def module(name: str, path: Path) -> object:
    """
    機能: 所有域に保全した純sourceだけを別namespaceで読み込む。
    引数: name(str)、path(Path) は私有複製の名前とsource位置。
    返り値: module は純計算部品。reader/run/mainは実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def main() -> None:
    """
    機能: 保存型だけの差分と同33入力、初回失敗履歴、全payload保存を確認する。
    引数: なし。
    返り値: None。旧6638監査を新金融又は独立有効性標本として再実行しない。
    """
    assert not OUTPUT.exists()
    values = {}
    for name, expected in EXPECTED.items():
        saved = (NEW/name).read_bytes()
        check(digest(saved) == expected, '完成v2小metadata指紋')
        values[name] = json.loads(saved)
    art = values['厳密joinと公開符号及び当時窓接頭の純人工.json']
    plan = values['元公開と紙上継続窓の非金融一読診断計画.json']
    fixed = values['二cacheの小目録固定.json']
    preserved = values['初回全33の保存Falseと原23源の保全.json']
    old_proof = json.loads((HERE/'当時窓と厳密結合及び分母の独立SOURCE_ONLY監査.json').read_bytes())
    old_fixed_saved = (OLD/'二cacheの小目録固定.json').read_bytes()
    old_fixed = json.loads(old_fixed_saved)
    signatures = art['source_SHA256']
    check(len(signatures) == 23 and signatures == plan['source_SHA256'] == fixed['source_SHA256'], '私有九参照十四のv2最終署名')
    source_bytes = {}
    for relative, expected in signatures.items():
        path = ROOT/relative
        check(path.suffix == '.py' and path.resolve().is_relative_to(ROOT/'work'), 'pysource以外は読まない')
        saved = path.read_bytes()
        check(digest(saved) == expected, 'v2完成二十三源の現在指紋')
        ast.parse(saved.decode('utf-8-sig'))
        source_bytes[relative] = saved
    old_signatures = {key: val['SHA256'] for key, val in preserved['原23source'].items()}
    check(old_signatures == old_proof['source_SHA256'], '初版独立監査と保存原二十三源一致')
    for relative, item in preserved['原23source'].items():
        check(digest((ROOT/relative).read_bytes()) == item['SHA256'] == digest((ROOT/item['archive_path']).read_bytes()), '初版全源と同bytesarchive保持')
    for name, item in preserved['小資料'].items():
        check(digest((OLD/name).read_bytes()) == item['SHA256'] == digest((ROOT/item['archive_path']).read_bytes()), '初版小資料guardFalseの同bytes保持')
    check(fixed['人工SHA256'] == plan['人工SHA256'] == EXPECTED['厳密joinと公開符号及び当時窓接頭の純人工.json'], 'v2人工計画fixed相互束縛')
    check(fixed['計画SHA256'] == EXPECTED['元公開と紙上継続窓の非金融一読診断計画.json'], 'v2計画fixed相互束縛')
    check(fixed['初版保全SHA256'] == EXPECTED['初回全33の保存Falseと原23源の保全.json'], '保全とv2固定接続')
    check(fixed['初版入力固定SHA256'] == digest(old_fixed_saved) == old_proof['metadata_SHA256']['二cacheの小目録固定.json'], '初版fixedの出典一致')
    for key in ('sessions', 'inputs', 'input_manifests'):
        check(fixed[key] == old_fixed[key], '全33組pathSHAstatと補完目録の完全継承')
    check(len(fixed['sessions']) == len(fixed['inputs']) == 33 and sum(len(x) for x in fixed['inputs'].values()) == 66, '同じ六十六cache固定')
    expected_counts = {'処理中場順': 33, 'TradeGate本文読取試行': 33, 'TradeGate本文一読': 33,
                       'TradeExit本文読取試行': 33, 'TradeExit本文一読': 33, '完了場': 33}
    check(preserved['元読取計数'] == fixed['元本文読取履歴'] == plan['初版保全']['元読取計数'] == expected_counts, '初回六十六本文と全33処理を隠さない')
    failed = json.loads((OLD/'診断False.json').read_bytes())
    check(not failed['全合格'] and failed['読取計数'] == expected_counts and 'JSON serializable' in failed['原因'], '初回保存失敗と処理済読取計数')
    check(plan['初版保全']['FalseSHA256'] == preserved['小資料']['診断False.json']['SHA256'] == art['保存不具合初版保全']['FalseSHA256'], '初回False出典の一致')
    check(fixed['小目録追加読取数'] == fixed['修正後大型本文読取'] == fixed['金融'] == fixed['API'] == 0, '継承固定の原小目録大cache追加本文ゼロ')
    check('保存不具合修正' in plan['再読理由'] and '新効能証拠0' in plan['再読理由'], '修正目的を新効能証拠としない')
    before = (OLD/'analysis.py').read_text(encoding='utf-8')
    after = (NEW/'analysis.py').read_text(encoding='utf-8')
    restored = after.replace(
        "count=None if scalar['direction_votes'] is None else int(scalar['direction_votes']),\n                signed_balance=None if scalar['balance'] is None else float(scalar['balance']))",
        "count=scalar['direction_votes'],signed_balance=scalar['balance'])").replace(
        'completed_paper_direction=bool(end<len(t))', 'completed_paper_direction=end<len(t)')
    check(restored == before, 'analysis差分は三保存fieldの原始型castだけ')
    for name in ('equal', 'validate_public', 'strict_join', 'paper_state', 'observe', 'point'):
        old_function = next(n for n in ast.parse(before).body if isinstance(n, ast.FunctionDef) and n.name == name)
        new_function = next(n for n in ast.parse(after).body if isinstance(n, ast.FunctionDef) and n.name == name)
        check(ast.dump(old_function, include_attributes=False) == ast.dump(new_function, include_attributes=False), '結合票資格順序機能はAST不変更')
    for name in ('inspect_sources.py', 'normal_reference.py', 'price_features.py', 'volume_reference.py'):
        check((OLD/name).read_bytes() == (NEW/name).read_bytes(), '代理量価格三部品とsource契約不変更')
    for relative, expected in old_signatures.items():
        if not relative.startswith('work/e01_opportunity_trace_20261015/prepare/'):
            check(signatures[relative] == expected, '参照十四源不変更')
    old_runner = ast.parse((OLD/'run.py').read_text(encoding='utf-8'))
    new_runner = ast.parse((NEW/'run.py').read_text(encoding='utf-8'))
    for name in ('load', 'main'):
        old_function = next(n for n in old_runner.body if isinstance(n, ast.FunctionDef) and n.name == name)
        new_function = next(n for n in new_runner.body if isinstance(n, ast.FunctionDef) and n.name == name)
        check(ast.dump(old_function, include_attributes=False) == ast.dump(new_function, include_attributes=False), 'reader一読SHAと別授権CLIguardは不変更')
    runner_text = (NEW/'run.py').read_text(encoding='utf-8')
    check('元本文読取履歴=fixed' in runner_text and '初版保存FalseSHA256=' in runner_text and 'common.verify_preservation()' in runner_text, '修正後結果も初回Falseと読取歴を併記')
    snapshot = HERE/'source_snapshot_v2'
    snapshot.mkdir(exist_ok=False)
    for relative, saved in source_bytes.items():
        if relative.startswith('work/e01_opportunity_trace_20261015/prepare_v2/'):
            (snapshot/Path(relative).name).write_bytes(saved)
    sys.path.insert(0, str(snapshot))
    source_reference = module('independent_fixture_v2', HERE/'opportunity_source_audit.py')
    old_analysis = module('serialization_old_analysis', HERE/'source_snapshot/analysis.py')
    new_analysis = module('serialization_new_analysis', snapshot/'analysis.py')
    payloads = 0
    initial_failures = 0
    for zero in (False, True):
        for typed in (False, True):
            g, e, _ = source_reference.fixture(zero)
            if typed:
                for account in g['accounts'].values():
                    for table in account['trade_features'].values():
                        for value in table.values():
                            for key, item in tuple(value.items()):
                                if isinstance(item, bool):
                                    value[key] = np.bool_(item)
                                elif isinstance(item, int):
                                    value[key] = np.int64(item)
                                elif isinstance(item, float):
                                    value[key] = np.float64(item)
            for length in (1, 18, 31, 33, 37, 41, 46, 53, 56, 59, 66, 79, 80):
                gate, packet = source_reference.cut(g, e, length)
                old_result = old_analysis.analyze(gate, packet)
                new_result = new_analysis.analyze(gate, packet)
                check(new_result == primitive(old_result), '独立合成全payload資格票count欠測意味同値')
                check(native(new_result), '全末端がPythonJSON原始型')
                saved = json.dumps(new_result, ensure_ascii=False, allow_nan=False)
                check(json.loads(saved) == new_result, '全payload厳格JSON保存roundtrip')
                payloads += 1
                if length == 80:
                    try:
                        json.dumps(old_result, ensure_ascii=False, allow_nan=False)
                    except TypeError:
                        initial_failures += 1
                    else:
                        raise AssertionError('初版の保存失敗が再現しない')
    check(payloads == 52 and initial_failures == 4, '四素材十三接頭全出力と初版失敗再現')
    for relative, expected in signatures.items():
        check(digest((ROOT/relative).read_bytes()) == expected, 'v2全23源開始終端不変')
    for relative, expected in plan['source111不変の確認対象'].items():
        check(digest((ROOT/relative).read_bytes()) == expected, '旧金融111十七源不変更')
    proof = dict(全合格=True,状態='SOURCE_ONLYの保存型修正接続。実cache再診断は未実行。',
        検査数=len(CHECKS),検査=CHECKS,合成payload数=payloads,初版合成保存失敗再現数=initial_failures,
        source_SHA256=signatures,metadata_SHA256=EXPECTED,監査source_SHA256=digest(Path(__file__).read_bytes()),
        初版独立計算監査SHA256='c4fe2280ab519a869db84b2b6f3e41ae6267bd062fc368c04ed7d168e32cf335',
        初版監査の対象外='全analyze出力のJSON原始型検査が漏れた。前6638合格は保存成功を保証しない。原証拠を保持。',
        差分='completed_paper_directionのbool、原公開count/balanceのint/float保存castだけ。計算/資格/方向/閾値/分母変更0。',
        元本文読取履歴=expected_counts,監査での追加読取=dict(元小目録=0,cache=0,NPZ=0,金融本文=0,金融=0,実台帳=0,原board=0,API=0,共有編集=0),
        評価='同33入力を保存不具合修正の別目的で次に診断する根の判断を妨げる問題なし。新しい金融有効性標本ではない。',
        未測=['修正診断の実cache結合結果','実busy/FAK/場停止の交差','独立新根拠/物理受信因果','新参加や指標の金融効果'])
    OUTPUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('保存型の独立接続 '+str(len(CHECKS))+'合格 / '+str(payloads)+'合成payload。SHA '+digest(OUTPUT.read_bytes()), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        failed = HERE/'保存型の独立接続初版False.json'
        assert not failed.exists()
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査=CHECKS,
            監査source_SHA256=digest(Path(__file__).read_bytes()),cache=0,金融=0,API=0), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        raise
