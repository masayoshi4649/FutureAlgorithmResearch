"""利益順行後の減量許可を、既存数量管理のまま固定比較する。"""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIMARY = 'G150_F25_N1__V000'
CONTROL = 'G000_F25_N1__V000'
BASELINE = 'A0__V000'


@lru_cache(maxsize=None)
def read(path: Path) -> object:
    """機能: 変更しない過去の固定設計を読む。

    引数: path(Path)。返り値: 読取専用として扱うJSON内容(object)。仕様へは深い複写を使う。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def specification(threshold: float = 1.5, fraction: int = 25, maximum: int = 1,
                  *, baseline: bool = False, variant: str = 'V000',
                  role: str = 'mechanism', **changes) -> dict:
    """機能: 旧注文規則へ価格順行の許可条件だけを追加する。

    引数: threshold(float)、fraction/maximum(int)、baseline(bool)、variant/role(str)、changes(dict)。
    返り値: 一つの固定条件(dict)。gate閾値は価格の初期ATR倍で、金額Rではない。
    """
    old = read(HERE.parent/'wave_v38/探索条件の固定.json')
    policy_name = 'A0' if baseline else f'B00_RB00_F{fraction}_N{maximum}'
    template_id = 'H019__A0__R1__V000' if baseline else 'H019__B00_RB00_F25_N1__R1__V000'
    row = deepcopy(next(r for r in old['conditions'] if r['id'] == template_id))
    if not baseline:
        policies = read(HERE.parent/'wave_v37/partial_design_fixed.json')['conditions']
        row['policy'] = deepcopy(next(r['policy'] for r in policies if r['policy']['id'] == policy_name))
        row['policy']['branch_mode'] = 'fixed'
    name = 'A0' if baseline else f'G{round(threshold*100):03d}_F{fraction}_N{maximum}'
    row.update(id=f'{name}__{variant}', signal_id='H019', variant_id=variant, role=role,
               gate_threshold_atr=0. if baseline else threshold, gate_mode='direction',
               baseline_policy=policy_name, gate_reference='G000_F25_N1__V000')
    row.update(changes)
    row['primary'] = row['id'] == PRIMARY
    assert row['gate_threshold_atr'] in (0., 1., 1.2, 1.5, 1.8, 2.)
    assert row['gate_mode'] in ('direction', 'inverse', 'any_valid')
    return row


def catalog() -> list[dict]:
    """機能: 主案を差し替えず、35個の主比較を列挙する。

    引数: なし。返り値: 全主条件(list[dict])。
    """
    rows = [specification(baseline=True, role='reference')]
    rows.extend(specification(0., f, n, role='reference') for f in (25, 50) for n in (1, 3))
    rows.extend(specification(a, f, n) for a in (1., 1.5, 2.) for f in (25, 50) for n in (1, 3))
    # ----------------------------------------
    # 元A0と元C01の入口時計対照は過去台帳の完全再現を要求する。
    for baseline in (True, False):
        for suffix, scale in (('080', .8), ('120', 1.2)):
            rows.append(specification(0., baseline=baseline, variant='E'+suffix,
                                      role='reference_clock', entry_scale=scale))
    # ----------------------------------------
    # 主案の順行距離・入口・悪化・回復・執行を一軸ずつ変える。
    for suffix, value in (('120', 1.2), ('180', 1.8)):
        rows.append(specification(variant='A'+suffix, role='sensitivity', gate_threshold_atr=value))
    for prefix, field in (('E', 'entry_scale'), ('D', 'bad_scale'), ('G', 'good_scale')):
        for suffix, scale in (('080', .8), ('120', 1.2)):
            rows.append(specification(variant=prefix+suffix, role='sensitivity', **{field:scale}))
    for seconds in (1., 5., 15.):
        rows.append(specification(variant=f'L{int(seconds):03d}', role='execution', min_delay_seconds=seconds))
    rows.append(specification(variant='O000', role='execution', observed_fill=True))
    rows.append(specification(variant='INV', role='mechanism', gate_mode='inverse'))
    rows.append(specification(variant='AV_ALL', role='mechanism', gate_mode='any_valid'))
    assert len(rows) == len({r['id'] for r in rows}) == 35
    assert sum(r['primary'] for r in rows) == 1
    return rows


def supplementary() -> list[dict]:
    """機能: 悪化と回復の符号だけを別々に乱数化した128対照を返す。

    引数: なし。返り値: 全補助条件(list[dict])。最良seedを選ばない。
    """
    rows = []
    for seed in range(64):
        rows.append(specification(variant=f'UB{seed:03d}', role='supplementary', bad_seed=seed))
        rows.append(specification(variant=f'UG{seed:03d}', role='supplementary', good_seed=seed))
    assert len(rows) == len({r['id'] for r in rows}) == 128
    return rows


def rules() -> dict:
    """機能: 機械的な許可規則と比較範囲を結果前に定義する。

    引数: なし。返り値: 共通規則(dict)。
    """
    return dict(主案=PRIMARY, 無ゲートC01=CONTROL, 元価格管理=BASELINE,
        主条件数=35, 補助条件数=128, 全条件数=163,
        許可='同じ影A0組の当行までの d*(extreme-anchor)/初期ATR が閾値以上となった初回行を保存。後の新しいB00公開source_row>到達行のみ許可。',
        初回到達='同じ組では一度だけ。値が戻っても解除しない。次の影組でリセット。',
        根拠='sourceはrawseqでなくready行。到達行と同じ公開は使わず、同時刻の後続行は使用できる。',
        通常='元B00方向だけを許可。source列は全行で元値を維持する。',
        恒等='閾値0＋directionは完全bypass。A0と無ゲートC01の中央・入口時計変更6条件は旧全配列同値を検査する。',
        方向除去='AV_ALLは到達後の全ての新しい有効B00公開へ、影保有と逆方向を渡す。最初の1公開だけへ限定しない。旧N1注文器が受理できる機会で最大1回減量。',
        乱数='旧v38の同source固定符号をbad/good別に使用。ゲートや元入口の情報は保持し、ゲート全体の純粋な無情報対照とは呼ばない。',
        数量={'TOPIX':5, 'NK225':10}, 片方向上限={'TOPIX':10, 'NK225':20},
        原則='初期1R組予算・元部分利確・トレーリング・360分期限・場末返済を維持。順行到達や復元で予算と期限をリセットしない。',
        単位='許可の距離は価格の初期ATR倍。実現＋含みの金額Rや、最大利益額の比率ではない。',
        不成立組='順行閾値へ届かない損失組も全て集計。未発火を成功とはしない。',
        同じ元組='影A0が共通の中央同士で対応。入口時計・執行が違う組番号を相互に同じ取引として扱わない。',
        費用=0, 現在API取得数=0, 保存ライブ使用=False,
        限界='全13セッションは既知。次の調査案は今回の売買結果へ混ぜない。', 全体目標達成=False)


if __name__ == '__main__':
    print(f'主{len(catalog())}、補助{len(supplementary())}。新損益なし。')
