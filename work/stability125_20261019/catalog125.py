"""通常数量の最低参加と三家族の固定十二条件を定義する。"""


def specifications() -> list[dict]:
    """
    機能: 新金融の結果を見る前に三家族各四条件を列挙する。
    引数: なし。
    返り値: list[dict]は家族・損切り・利益追尾・追加・相手確認の固定仕様。
    """
    families=[('A',0,'共通進行後の押し戻り再進行'),('B',1,'極値から反発反落し純建玉を持替え'),('C',2,'往復回帰と方向追従をERで切替')]
    variants=[
        (0,1.,1.,.75,False,True,'標準・初回半容量だけ'),
        (1,1.,1.,.75,True,True,'標準・一単位順行で残半分追加'),
        (2,.75,.75,.5,False,True,'撤回と利益追尾を狭くする'),
        (3,1.5,1.,1.,True,False,'広めの撤回・相手確認なし対照'),
    ]
    result=[]
    for tag,mode,name in families:
        for number,stop,start,trail,add,peer,description in variants:
            result.append(dict(id=f'{tag}{number:02}',family=tag,mode=mode,name=name+'／'+description,
                stop_w=stop,trail_start_w=start,trail_w=trail,add_enabled=add,peer_required=peer,
                initial_quantity='cap//2',add_quantity='残り上限まで一回。予定撤回損失の初回予算を維持',
                deadline_seconds=1800,force_direction='現在対初回Last→直近確定一分方向→買い',
                entry_cost_gate='判断と実新規の両方でspread＋2×片道一枚料÷倍率≤0.5×準備幅。期限参加も迂回せず、次行拡大は取消',
                session_exit='引け六分前から通常返済予約。次原行がなければ六分窓内BBO代理を区別',
                fees='一注文ごとfloor(数量×片道料)。通常及び代理返済の両道を含む'))
    assert len(result)==12
    return result
