"""新規損益を計算せず、事前16対照の変数差を独立に照合する。"""

import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def read_module(name: str, path: Path) -> object:
    """
    機能: 損益の実行を伴わない条件定義モジュールを読み取る。
    引数: name (str) は固有モジュール名、path (Path) は条件定義。
    返り値: object は読取済みモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def difference(base: dict, target: dict) -> dict:
    """
    機能: 条件IDを除いた実パラメータ差を表示可能な形で返す。
    引数: base/target (dict[str,object]) は基準と比較先の条件。
    返り値: dict[str,list[object]] は変更前と変更後の値。
    """
    return {key: [base.get(key), target.get(key)] for key in sorted(base.keys() | target.keys())
            if key != 'id' and base.get(key) != target.get(key)}


def main() -> None:
    """
    機能: 原設計の変更軸が16条件へそのまま接続されたか、損益前に独立確認する。
    引数: なし。旧92と新93のcatalogのみ読み取る。
    返り値: None。変更軸照合JSONを新93のtheoryへ保存する。
    """
    old = read_module('条件差独立照合92', WORK.parent / 'wave_v92/catalog.py')
    new = read_module('条件差独立照合93', WORK / 'catalog.py')
    old_values = {v['id']: v for v in old.catalog()}
    values = {v['id']: v for v in new.catalog()}
    assert len(values) == 16 and new.PRIMARY == 'C11'
    defaults = {'range_entry_max_risk_widths': 0., 'range_entry_min_center_ratio': 0.,
                'range_target_kind': 'widths', 'range_center_target_offset': 0.,
                'range_failure_reentry_kind': 'legacy', 'failure_center_fraction': .25}
    controls = []
    for ident, old_id in [('C00', 'R_B25_C'), ('C01', 'R_B25_C_ESTOP'), ('S00', 'J8'), ('S01', 'J10')]:
        expected = dict(old_values[old_id], **defaults)
        assert difference(expected, values[ident]) == {}
        controls.append({'条件': ident, '旧対照': old_id, '追加キー': defaults, '経済条件差': {}})
    pairs = [
        ('C01', 'C02', {'range_stop_kind': ['witness_extreme', 'width_or_witness']}),
        ('C01', 'C03', {'range_entry_max_risk_widths': [0., .5]}),
        ('C01', 'C04', {'range_entry_max_risk_widths': [0., 1.]}),
        ('C02', 'C05', {'range_entry_min_center_ratio': [0., 2.]}),
        ('C05', 'C06', {'range_target_kind': ['widths', 'center']}),
        ('C05', 'C07', {'range_target_kind': ['widths', 'center_plus'], 'range_center_target_offset': [0., .5]}),
        ('C02', 'C08', {'range_failure_reentry_kind': ['legacy', 'return_self']}),
        ('C02', 'C09', {'range_failure_reentry_kind': ['legacy', 'return_both']}),
        ('C02', 'C10', {'range_failure_reentry_kind': ['legacy', 'prepare_reset']}),
        ('C06', 'C11', {'range_failure_reentry_kind': ['legacy', 'return_both']}),
        ('C11', 'S02', {'range_budget': [10, 2]}),
        ('S02', 'S03', {'trend_budget': [0, 8], 'ungated_trend': [False, True]}),
    ]
    observed = []
    for base, target, expected in pairs:
        actual = difference(values[base], values[target])
        assert actual == expected, (base, target, actual, expected)
        observed.append({'基準': base, '変更先': target, '変更': actual})
    assert all(v['trend_budget'] + v['range_budget'] <= 10 for v in values.values())
    for ident in ['C00', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09', 'C10', 'C11', 'S02', 'S03']:
        assert values[ident]['range_width_fraction'] == .001
        assert values[ident]['recovery_confirmation'] == 'both'
        assert values[ident]['recovery_fraction'] == .25
    path = HERE / '全16条件の損益前変更軸の独立照合.json'
    result = {'全合格': True, '段階': '条件定義の読取だけ。新93の損益閲覧・売買実行なし。',
              'catalogSHA256': hashlib.sha256((WORK / 'catalog.py').read_bytes()).hexdigest(),
              'コードSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              '主': new.PRIMARY, '条件数': len(values), '旧経済対照': controls,
              '独立軸比較': observed, '共通幅': .001, '双方回復量': .25,
              '源別経路の認定': '条件定義として独立固定枠を指定済み。S03のS00/S02全注文及び全行清算一致はまだ未実行。',
              '新93損益閲覧': 0, '新売買実行': 0, 'API取得': 0, '実注文': 0}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'保存先': str(path), 'SHA256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      '全合格': True, '条件数': len(values)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
