"""間隔だけと初回距離も変える二系統を、損益閲覧前に固定する。"""


def specifications() -> list[dict]:
    """
    機能: 十間隔を二系統へ展開し、同じ3pt/3ptだけを統合する。
    引数: なし。
    返り値: list[dict]は十九条件。保存基準一つを再実行対象から除く。
    """
    result=[]
    gaps=(1,2,3,4,5,6,8,10,12,15)
    for family in ('初回3pt固定','初回も間隔と同じ'):
        for gap in gaps:
            initial=3 if family=='初回3pt固定' else gap
            if initial==3 and gap==3 and family!='初回3pt固定':
                continue
            result.append(dict(id=f'I{initial}_G{gap}',name=f'初回{initial}pt・間隔{gap}pt',
                family=family,initial=float(initial),spacing=float(gap),reused=initial==gap==3))
    assert len(result)==19 and len({(s['initial'],s['spacing']) for s in result})==19
    return result
