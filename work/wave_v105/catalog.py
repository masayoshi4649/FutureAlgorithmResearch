"""損失原因に対応した部品を単独・統合で比較する候補定義。金融前に固定する。"""

from copy import deepcopy


ENTRIES = ('C_OWN', 'C_N30', 'U_P10')
SYMBOLS = ('TOPIX', 'NK225')
PRIMARY = 'C_N30_R21_EN30_ZONE_STOP'
COMMON = dict(initial_stop_fraction=.001, cooldown_seconds=30., start_offset=300.,
              cut_offset=300., force_offset=60.)


def variants() -> list[dict]:
    """
    機能: 何を変更した効果かを切り分ける17対照を定義する。
    引数: なし。
    返り値: list[dict]は候補仕様。金融結果による数値変更は行わない。
    """
    return [
        dict(name='B4', explanation='元の支持4呼値と広い利益追尾。比較基準。'),
        dict(name='T2', support_ticks=2, profit_trail=True,
             explanation='元の支持2呼値と狭い利益追尾。再参加が増える対照。'),
        dict(name='B4_E30', filter_mode='E', window=30,
             explanation='自己の直近30秒が往復より片道進行を優勢にした場合だけ入る。'),
        dict(name='B4_EP30', filter_mode='EP', window=30,
             explanation='自己と相手の直近30秒の片道進行が両方優勢な場合だけ入る。'),
        dict(name='B4_N30', filter_mode='N', window=30,
             explanation='自己の直近30秒の逆行幅より停止余裕が小さい入口を見送る。'),
        dict(name='B4_EN30', filter_mode='EN', window=30,
             explanation='自己の片道進行と停止余裕の両方を確認する。'),
        dict(name='B4_ZONE', reentry_band=True,
             explanation='損切りした同方向の支持帯へ、新しい帯外の根拠が出るまで再参加しない。'),
        dict(name='B4_STOP', session_brake=True,
             explanation='当時の清算損失が開始時のリスク予算を超えたら、その場の新規を停止する。'),
        dict(name='R21', r_profit=True, alpha=2., beta=1.,
             explanation='料込み初期リスクの2倍まで順行したら、1倍幅で利益を追う。'),
        dict(name='R32', r_profit=True, alpha=3., beta=2.,
             explanation='料込み初期リスクの3倍まで順行したら、2倍幅で利益を追う。'),
        dict(name='R21_ZONE', r_profit=True, alpha=2., beta=1., reentry_band=True,
             explanation='初期リスクに応じた利益追尾に、損失帯への再参加抑制を加える。'),
        dict(name='R21_EN30', r_profit=True, alpha=2., beta=1., filter_mode='EN', window=30,
             explanation='自己の進行と停止余裕を確認し、初期リスクに応じて利益を追う。'),
        dict(name='R21_EN30_ZONE', r_profit=True, alpha=2., beta=1., filter_mode='EN', window=30, reentry_band=True,
             explanation='入口の進行・余裕、初期リスクによる利益追尾、損失帯への再参加抑制を組み合わせる。'),
        dict(name='R21_EN30_ZONE_STOP', r_profit=True, alpha=2., beta=1., filter_mode='EN', window=30,
             reentry_band=True, session_brake=True,
             explanation='入口の進行・余裕と損失帯を確認し、利益追尾と場ごとの損失停止を併用する。'),
        dict(name='R21_EN10_ZONE_STOP', r_profit=True, alpha=2., beta=1., filter_mode='EN', window=10,
             reentry_band=True, session_brake=True,
             explanation='統合案の入口を見る範囲だけ10秒へ短縮し、30秒に依存しないかを比較する。'),
        dict(name='B4_EN30_ZONE_STOP', filter_mode='EN', window=30, reentry_band=True, session_brake=True,
             explanation='統合案で利益追尾だけ元の広い幅へ戻し、利益を伸ばす効果を分離する。'),
        dict(name='R21_EN30_ZONE_STOP_PUBLIC', r_profit=True, alpha=2., beta=1., filter_mode='EN', window=30,
             reentry_band=True, session_brake=True, own_path='PUBLIC',
             explanation='統合案の自己経路だけ価格時計ごとの先頭観測へ圧縮し、同時計内の往復を落とす影響を比べる。'),
    ]


def catalog() -> list[dict]:
    """
    機能: 三つの既存入口に同じ17対照を適用する。
    引数: なし。
    返り値: list[dict]は51条件。正式枚数はTOPIX10枚・日経20枚。
    """
    result = []
    for entry in ENTRIES:
        for variant in variants():
            value = dict(id=entry+'_'+variant['name'], entry_id=entry, support_ticks=4,
                profit_trail=False, r_profit=False, alpha=2., beta=1., reentry_band=False,
                session_brake=False, session_budget_multiple=1., filter_mode='NONE', window=30, own_path='NORMAL',
                quantity={'TOPIX': 10, 'NK225': 20}, **COMMON)
            value.update(deepcopy(variant))
            result.append(value)
    assert len(result) == 51 and len({value['id'] for value in result}) == 51
    assert PRIMARY in {value['id'] for value in result}
    return result
