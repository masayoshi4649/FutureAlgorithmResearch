"""入口の現在証拠と、共同方向が崩れた時の返済条件を過去情報だけで計算する。"""

import numpy as np
import signals


def session_state(session: dict) -> dict:
    """機能: 板支持、往復度、板の矛盾と二種類の価格逆行確認を作る。

    引数: session(dict) は厳密過去の共通格子と既存特徴。
    返り値: 銘柄別の入口許可と保有方向別の返済旗(dict)。将来損益は参照しない。
    """
    grid=session['grid'];markets=session['markets'];symbols=('TOPIX','NK225')
    valid=np.ones(len(grid),dtype=bool);valid30=valid.copy();efficient=valid.copy();depth_valid=valid.copy()
    source=[markets[s]['current']['index'] for s in symbols]
    for m in markets.values():
        valid &= m['current']['valid'];w=m['windows'][30]
        valid30 &= m['current']['valid']&w['source_valid']&np.isfinite(w['ret_bp'])&np.isfinite(w['bid_change_ticks'])&np.isfinite(w['ask_change_ticks'])
        w=m['windows'][300];efficient &= w['source_valid']&np.isfinite(w['efficiency'])&(w['efficiency']>=.2)
        depth_valid &= m['current']['q_valid']&np.isfinite(m['current']['depth_imbalance'])
    output={s:dict(bid=m['current']['bid'],ask=m['current']['ask'],source=m['current']['index']) for s,m in markets.items()}
    for d,name in ((1,'long'),(-1,'short')):
        support=valid.copy();depth=depth_valid&valid
        for m in markets.values():
            f=m['flow'][15]
            sufficient=f['source_valid']&f['valid']&~f['missing_ofi']&(f['nonzero_ofi_count']>=3)&np.isfinite(f['ofi_ratio'])
            support &= sufficient&(d*f['ofi_ratio']>=.1)
            depth &= d*m['current']['depth_imbalance']>=0.
        # ----------------------------------------
        # 返済は価格の反対進行を15秒確認する。板の静的偏りを必須にしない。
        reverse={}
        for s,m in markets.items():
            w=m['windows'][30]
            reverse[s]=(-d*w['bid_change_ticks']>=1.-1e-8)&(-d*w['ask_change_ticks']>=1.-1e-8)
        common=reverse['TOPIX']&reverse['NK225']
        confirmed=signals.confirmation(grid,common,valid30,source[0],source[1],15.)
        for s in symbols:
            peer='NK225' if s=='TOPIX' else 'TOPIX'
            own_reverse=reverse[s]&(d*markets[peer]['windows'][30]['ret_bp']<=0.)
            output[s][f'support_{name}']=support.copy()
            output[s][f'efficient_{name}']=(valid&efficient).copy()
            output[s][f'depth_{name}']=depth.copy()
            output[s][f'x1_{name}']=confirmed.copy()
            output[s][f'x2_{name}']=signals.confirmation(grid,own_reverse,valid30,source[0],source[1],15.)
    return dict(grid=grid,markets=output)


def build(grids: dict) -> dict:
    """機能: 全セッションの因果的な防止条件を一括生成する。

    引数: grids(dict)。返り値: 場別の防止条件(dict)。
    """
    return {session:session_state(value) for session,value in grids.items()}
