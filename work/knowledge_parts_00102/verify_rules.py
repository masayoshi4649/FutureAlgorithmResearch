"""知見正本の数値の型、根拠の位置、旧履歴の保持を検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMON = ROOT/'アルゴリズム調査/共通/知見台帳'


def resolve(value: object, pointer: str) -> object:
    """
    機能: 出典JSON内の指定位置を辿る。
    引数: value(object)はJSON内容、pointer(str)はJSONポインター。
    返り値: objectは指定位置の値。存在しなければ例外。
    """
    if not pointer:
        return value
    assert pointer.startswith('/'), pointer
    for component in pointer.split('/')[1:]:
        component = component.replace('~1', '/').replace('~0', '~')
        value = value[int(component)] if isinstance(value, list) else value[component]
    return value


def main() -> None:
    """
    機能: 全出典の位置と明記された分子分母、異常値拒否を検証する。
    引数: なし。
    返り値: None。金融計算や板の読取を行わず、検査記録だけを保存する。
    """
    spec = importlib.util.spec_from_file_location('台帳管理', COMMON/'manage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.load(deep=True)
    sources, pointers, counts = {}, 0, 0
    for row in data['rules']['rules']:
        evidence = row['evidence'] + [item['source'] for item in row['measurements']]
        for reference in evidence:
            path = ROOT/reference['path']
            if path.suffix != '.json' or reference.get('pointer') is None:
                continue
            if path not in sources:
                assert path.stat().st_size < 30_000_000, '検査対象の保存集計の範囲を確認してください'
                sources[path] = json.loads(path.read_text(encoding='utf-8'))
            resolve(sources[path], reference['pointer'])
            pointers += 1
        for item in row['measurements']:
            for key, field in (('numerator_pointer', 'successes'), ('denominator_pointer', 'total')):
                if item.get(key):
                    assert resolve(sources[ROOT/item['source']['path']], item[key]) == item[field]
                    counts += 1
    # ----------------------------------------
    # 不正な確率や根拠不足を、金融実行なしで保存前に拒否できることを確認する。
    rejected = []
    for label, field, value in [('割合不一致', 'value', -1), ('分母なし', 'total', None),
                                ('分子が分母超過', 'successes', 999999), ('未来範囲の記載なし', 'horizon', ''),
                                ('出典なし', 'source', None)]:
        candidate = deepcopy(data)
        candidate['rules']['rules'][0]['measurements'][0][field] = value
        try:
            module.validate(candidate)
        except (AssertionError, TypeError):
            rejected.append(label)
        else:
            raise AssertionError(label)
    assert len(data['knowledge']['findings']) == 14
    assert len(data['trials']['trials']) == 188
    assert len(data['studies']['studies']) == 100
    result = dict(全合格=True, 出典位置照合=pointers, 明示分子分母照合=counts, 保存前の拒否=rejected,
                  旧メモ14件と試行188件と資料100件を保持=True, 金融再生=0, 原板読取=0,
                  正本SHA256=data['source_sha256'])
    (HERE/'数値と出典の検証.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
