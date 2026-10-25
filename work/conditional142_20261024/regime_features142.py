"""短期の往復と、公開済み中期の支持水準を区別する特徴。"""

import numpy as np


def prepare(packet,patrol,history):
    """
    機能: 36列へ自己相手の公開MA5/MA20/高20/安20/標準偏差20/効率20を付加する。
    引数: packet/patrol/history(dict)は原資料・第二巡特徴・公開済み履歴。
    返り値: dictは48列の新しい市場資料。旧特徴は変更しない。

    相手は価格時計が厳密に古く15秒以内の原行だけを接続する。
    各平均は既存の確定一分足終端60秒後公開を維持する。
    """
    out={}
    for symbol,item in patrol.items():
        h=history[packet['session'],symbol]
        own=h[:,[0,1,3,4,2,5]]
        out[symbol]=dict(item,features=np.column_stack((item['features'],own,np.full_like(own,np.nan))))
    for symbol,item in out.items():
        peer=out['TOPIX' if symbol=='NK225' else 'NK225'];t=item['ready']['time_s'];pt=peer['ready']['time_s']
        index=np.searchsorted(pt,t,side='left')-1;safe=np.maximum(index,0)
        valid=(index>=0)&(t-pt[safe]<=15.)
        item['features'][valid,42:48]=peer['features'][safe[valid],36:42]
    return out
