"""新価格の定着と進行失敗を部品ごとに比べる、結果前の19条件草案。"""

from copy import deepcopy


PRIMARY = 'U_C1R1'
SYMBOLS = ('TOPIX', 'NK225')
STRENGTHS = (('05', 0.5), ('1', 1.0), ('2', 2.0))


def catalog() -> list[dict]:
    """
    機能: 定着と進行失敗の完全条件、部品対照、自動選択、固定配分を定義する。
    引数: なし。
    返り値: list[dict]。金融結果による変更をまだ行っていない19条件草案。
    """
    values = []
    for family in ('C', 'R'):
        for suffix, strength in STRENGTHS:
            values.append(dict(id=family + suffix, kind='single', family=family,
                               strength=strength, use_volume=True, use_supply=True,
                               use_peer=True, quantity=dict(TOPIX=1, NK225=1)))
        for suffix, volume, supply, peer in (
                ('PRICE', False, False, True),
                ('VOLUME', True, False, True),
                ('SUPPLY', False, True, True),
                ('OWN', True, True, False)):
            values.append(dict(id=family + '_' + suffix, kind='single', family=family,
                               strength=1.0, use_volume=volume, use_supply=supply,
                               use_peer=peer, quantity=dict(TOPIX=1, NK225=1)))
    # ----------------------------------------
    # 旧固定1枚の実検算済み会計、自動選択、異質な二入口の固定配分を加える。
    values.append(dict(id='OLD_G0', kind='previous', previous_id='G0_Q1_X1',
                       quantity=dict(TOPIX=1, NK225=1)))
    values.append(dict(id=PRIMARY, kind='union', components=('C1', 'R1'),
                       quantity=dict(TOPIX=1, NK225=1), conflict='opposite_abstain'))
    for quantity in (2, 5, 8):
        values.append(dict(id=f'P{quantity * 10}', kind='portfolio', components=('C1', 'R1'),
                           allocations=dict(TOPIX=(quantity, 10 - quantity),
                                            NK225=(2 * quantity, 20 - 2 * quantity)),
                           per_direction_caps=dict(TOPIX=10, NK225=20)))
    assert len(values) == 19 and len({value['id'] for value in values}) == 19
    return deepcopy(values)


def labels() -> dict[str, str]:
    """
    機能: 入口思想と部品対照又は配分を短い日本語へ対応させる。
    引数: なし。
    返り値: dict[str,str]。説明名。黒字や安定性の達成を意味しない。
    """
    result = {}
    meanings = dict(PRICE='価格のみ', VOLUME='価格と出来高',
                    SUPPLY='価格と表示量', OWN='自己市場だけ')
    for value in catalog():
        ident = value['id']
        if value['kind'] == 'single':
            name = '新価格の定着' if value['family'] == 'C' else '進行失敗から反転'
            detail = meanings.get(ident.split('_')[-1], f"活動強度{value['strength']:g}倍・両市場確認")
            result[ident] = name + '／' + detail + '／各商品1枚'
        elif value['kind'] == 'previous':
            result[ident] = '旧の両市場進行／固定1枚・増玉なし'
        elif value['kind'] == 'union':
            result[ident] = '定着と進行失敗を自動選択／反対判断は保留／各商品1枚'
        else:
            top, nk = value['allocations']['TOPIX'], value['allocations']['NK225']
            result[ident] = f'定着と進行失敗を併用／TOPIX {top[0]}:{top[1]}枚・日経 {nk[0]}:{nk[1]}枚'
    return result
