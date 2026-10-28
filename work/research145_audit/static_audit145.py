"""保存コードの系譜と手数料経路を検査する。金融再生は行わない。"""

import ast
import hashlib
import inspect
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/research145_engine'))
import source145 as source


def fingerprint(path):
    """
    機能: 読み取った実装の内容指紋を記録する。
    引数: path(Path)は既存コード。
    返り値: strはSHA256文字列。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ast_equal(first, second):
    """
    機能: 関数の構文木を比較し、数値処理と公開時刻が同一か確認する。
    引数: first/second(callable)は比較する既存関数。
    返り値: boolは構文木の一致。
    """
    return ast.dump(ast.parse(inspect.getsource(first))) == ast.dump(ast.parse(inspect.getsource(second)))


def main():
    """
    機能: 新しい元通知の設定系譜と公開済み履歴の意味を独立確認する。
    引数: なし。
    返り値: None。実データの特徴生成・金融再生を呼ばずJSONを保存する。
    """
    old = source.OLD
    first = json.loads((old / '第一巡計画143.json').read_text(encoding='utf-8'))
    restored = json.loads((old / 'episode_restore_configs143.json').read_text(encoding='utf-8'))
    declared_day = first['configs']['episode'][0]
    day_old = dict(declared_day, maximum=2, initial=min(declared_day['initial'], 2))
    day_new = dict(source.episode.configurations()[0], maximum=2, initial=2)
    assert day_old == day_new
    original = source.shared.previous.first.original
    selected = original.configurations()[33]
    keys = set(selected) - {'id', 'name'}
    night_old = dict(restored[0], initial=1, maximum=2)
    night_new = dict(selected, initial=1, maximum=2)
    assert {key: night_old[key] for key in keys} == {key: night_new[key] for key in keys}
    assert ast_equal(original.history, source.active.history)
    feature_module = source.shared.previous.prior.common.features129.features128
    assert feature_module.NAMES[1] == '平均20'
    # ----------------------------------------
    # 参照したコードを凍結記録し、後の実装修正を監査結果へ混ぜない。
    paths = [Path(source.__file__), Path(original.__file__), Path(source.active.__file__),
             Path(feature_module.__file__), old / 'episode143.py', old / 'core_overlay_v2_143.py',
             ROOT / 'work/research145_engine/trader145.py',
             ROOT / 'work/research145_residual/residual145.py']
    report = dict(金融再生=False, 昼別入口='S01と設定完全一致', 夜別入口='L00と数値設定完全一致',
                  公開履歴='旧historyとAST完全一致', 第31列='遅延公開済み平均20',
                  費用経路='基本源は費用列のみ0。他源・追加・H04予算はfee10=0で再生成するコード。',
                  指紋={str(p.relative_to(ROOT)): fingerprint(p) for p in paths})
    (HERE / 'コード系譜監査145.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
