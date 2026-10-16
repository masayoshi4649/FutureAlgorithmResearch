"""新しい売買や金融入力を使わず、20条件の有限案と旧固定部品だけを検算する。"""

import hashlib
import json
from pathlib import Path

import catalog

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """
    機能: 有限条件数、初回絶対数量、旧部品固定と対照参照だけを確認する。
    引数: なし。
    返り値: None。金融入力読取、売買本体実装、正式損益計算は行わない。
    """
    values = catalog.catalog()
    ids = {value['id'] for value in values}
    assert len(ids) == 20 and catalog.PRIMARY in ids and catalog.CONTROL in ids
    plan_path = HERE / '結果前の設計案.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    assert plan['予定条件数'] == 20 and plan['理論主'] == catalog.PRIMARY
    assert plan['売買実装'] == plan['正式新条件売買実行'] == 0
    new_names = {'id', 'previous_price_cap_id', 'trend_initial_quantity', 'trend_growth_mode',
                 'trend_growth_cushion_ticks', 'trend_growth_risk_budget'}
    for value in values:
        previous = catalog.PREVIOUS[value['previous_price_cap_id']]
        assert {key: item for key, item in value.items() if key not in new_names} == {
            key: item for key, item in previous.items() if key != 'id'}
        assert set(catalog.references(value['id'])).issubset(ids)
        initial = value['trend_initial_quantity']
        assert initial is None or type(initial) is int and initial in (1, 2, 4)
    paths = [Path(__file__), HERE / 'catalog.py', plan_path]
    value = dict(全合格=True, 条件数=20, 主=catalog.PRIMARY,
                 初回は両商品とも絶対数量=True, 旧初回入口と出口条件保持=True,
                 金融入力読取=0, 売買実装=0, 新正式損益=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in paths})
    (HERE / '有限案の純条件確認.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('101の20条件の有限案だけを確認。売買実装0、金融入力読取0、新正式損益0。', flush=True)


if __name__ == '__main__':
    main()
