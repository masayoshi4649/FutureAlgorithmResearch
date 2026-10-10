"""固定した時間窓の合議を、同じ二つの注文管理方式で比較する。"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANAGERS = ('A0', 'B00_RB00_F25_N1')
SIGNALS = ('S080', 'S100', 'S120', 'M2_080', 'M2_100', 'M2_120',
           'V2_080', 'V2_100', 'V2_120', 'U3_080', 'U3_100', 'U3_120')


def catalog() -> list[dict]:
    """機能: 入口12種と出口2種、主案の執行診断8種を列挙する。

    引数: なし。返り値: 結果で変更しない全条件(list[dict])。
    """
    prior = json.loads((HERE.parent/'wave_v38/探索条件の固定.json').read_text(encoding='utf-8'))
    templates = {m: next(s for s in prior['conditions'] if s['id'] == f'H019__{m}__R1__V000')
                 for m in MANAGERS}
    output = []
    for manager in MANAGERS:
        for signal in SIGNALS:
            spec = deepcopy(templates[manager])
            spec.update(id=f'{signal}__{manager}__V000', window_id=signal,
                        signal_id=signal, role='primary' if signal == 'M2_100' else 'comparison',
                        primary=signal == 'M2_100', prior_manager=manager)
            output.append(spec)
        for variant, delay, observed in (('L001', 1., False), ('L005', 5., False),
                                         ('L015', 15., False), ('O000', 0., True)):
            spec = deepcopy(templates[manager])
            spec.update(id=f'M2_100__{manager}__{variant}', window_id='M2_100', signal_id='M2_100',
                        variant_id=variant, role='execution', primary=False, prior_manager=manager,
                        min_delay_seconds=delay, observed_fill=observed)
            output.append(spec)
    assert len(output) == len({s['id'] for s in output}) == 32
    return output


def rules() -> dict:
    """機能: 主案、対照、出口不変更と解釈の範囲を明示する。

    引数: なし。返り値: 共通設計(dict)。
    """
    return dict(主案='M2_100。出口A0とC01を分けて判定し、良かった出口だけへ統合しない。',
        入口='既存H019完全入口の近接3窓。2票多数決、反対拒否、全一致を機構比較。',
        元単一='S080/S100/S120は旧入口.8/1/1.2と全行一致を要求する。',
        合議中心=[.8, 1., 1.2], 構成倍率=[.8, 1., 1.2],
        新規性='合議原理は既試行。H019の時計感度を同じ入口構造の窓束で直接比較する追試。',
        数量={'TOPIX':5, 'NK225':10}, 片方向上限={'TOPIX':10, 'NK225':20},
        注文管理='v41状態修正版とv38元監査を無変更で使用。D273、固定初期ATR、場内返済。',
        出口='入口合議を保有中の方向撤回・反転条件には加えない。',
        公平性='単一窓も合議も一本の口座。同じ初回枚数・リスク幅・追加返済方式。',
        費用=0, 現在API取得数=0, 保存ライブ使用=False,
        限界='全13セッションは既知。今回の固定は結果の事後変更を防ぐが、未知検証ではない。',
        全体目標達成=False)
