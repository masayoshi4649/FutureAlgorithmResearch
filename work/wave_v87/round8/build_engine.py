"""凍結した独立玉の管理を保持し、逆行時の保険入口だけを生成する。"""
from pathlib import Path

HERE=Path(__file__).resolve().parent


def replace_once(text,before,after):
    """
    機能: 想定した旧断片だけを一度置換する。
    引数: text/before/after(str)。
    返り値: str。重複又は元実装変更は拒否する。
    """
    assert text.count(before)==1,before[:100]
    return text.replace(before,after)


def build():
    """
    機能: 第七段階の出口・注文順から、保険の追跡入口版を生成する。
    引数: なし。
    返り値: None。元ファイルは変更しない。
    """
    source=(HERE.parent/'round7/engine.py').read_text(encoding='utf-8')
    source=replace_once(source,'"""当行までの元注文だけを読む独立追加玉。元玉の状態へ書き戻さない。"""',
        '"""順行極値からの逆行と公開済み反対支持で、独立保険を一度だけ建てる。"""')
    source=replace_once(source,'start_atr,stop_atr,activation_atr,trail_atr,observed):',
        'start_atr,stop_atr,activation_atr,trail_atr,observed,prepare_atr,pullback_atr,confirm,\n             seq,own_value,own_valid,peer_value,peer_valid,own_release_seq,peer_release_time):')
    source=replace_once(source,'end/cutoff/tick/各幅(float)、relation(int)、observed(bool)。',
        'end/cutoff/tick/各幅(float)、relation/confirm(int)、observed(bool)、\n          seq/支持値/有効性/公開行/公開時刻(ndarray)。最新公開イベントの当時ATR正規化値を受け取る。')
    source=replace_once(source,'時価8列、証跡12列、状態5列。',
        '時価8列、証跡12列、状態5列、保険入口根拠7列。')
    source=replace_once(source,'oc=tc=ec=pointer=0',
        'oc=tc=ec=pointer=0\n    insurance=np.zeros((capacity,7));ic=0\n    core_extreme=0.;extreme_row=-1;prepared=False;gate_row=-1;published_permission=False')
    source=replace_once(source,'if pending_market or core_side*(p-level)>=-1e-9:',
        'if pending_market or -core_side*(p-level)>=-1e-9:')
    source=replace_once(source,'sat_side=core_side*relation;sat_qty=initial',
        'assert published_permission and 0<=gate_row<i\n                insurance[ic]=np.array([i,cid,pending_row,gate_row,core_extreme,extreme_row,level]);ic+=1\n                sat_side=core_side*relation;sat_qty=initial')
    source=replace_once(source,'pending=False;used=False;core_closed=-1;force_row=-1',
        'pending=False;used=False;core_closed=-1;force_row=-1\n                core_extreme=anchor;extreme_row=i;prepared=False;gate_row=-1;published_permission=False')
    before='''        if core_qty and not used and not pending and relation and not no_entry:
            pending=True;pending_row=i
            level=rounded(anchor+core_side*start_atr*atr,tick,core_side)
            pending_market=core_side*(p-level)>=-1e-9
            events[ec]=np.array([i,cid,1.,i,core_side*relation,initial,level,core_qty,atr,80.,core_closed,0.]);ec+=1'''
    after='''        if core_qty and not used and relation:
            if core_side*(p-core_extreme)>1e-9:
                core_extreme=p;extreme_row=i
                events[ec]=np.array([i,cid,9.,i,core_side,initial,core_extreme,core_qty,atr,80.,core_closed,int(prepared)]);ec+=1
            if not prepared and core_side*(core_extreme-anchor)>=prepare_atr*atr-1e-9:
                prepared=True
                events[ec]=np.array([i,cid,8.,extreme_row,core_side,initial,core_extreme,core_qty,atr,80.,core_closed,1.]);ec+=1
            permit=prepared and not no_entry
            if confirm:
                permit=permit and own_valid[i] and peer_valid[i] and own_release_seq[i]<=seq[i] and peer_release_time[i]<t
                permit=permit and np.isfinite(own_value[i]) and np.isfinite(peer_value[i])
                permit=permit and -core_side*own_value[i]>.05 and -core_side*peer_value[i]>.05
            if pending and not permit:
                events[ec]=np.array([i,cid,5.,i,core_side*relation,initial,level,core_qty,atr,86.,core_closed,int(prepared)]);ec+=1
                pending=False
            if permit:
                nextlevel=rounded(core_extreme-core_side*max(tick,pullback_atr*atr),tick,-core_side)
                if not pending or core_side*(nextlevel-level)>1e-9:
                    pending=True;pending_row=i;level=nextlevel
                    pending_market=-core_side*(p-level)>=-1e-9
                    events[ec]=np.array([i,cid,1.,i,core_side*relation,initial,level,core_qty,atr,80.,core_closed,int(prepared)]);ec+=1
            gate_row=i;published_permission=permit'''
    source=replace_once(source,before,after)
    source=replace_once(source,'np.array([sat_qty,core_qty,int(pending),maxlong,maxshort])',
        'np.array([sat_qty,core_qty,int(pending),maxlong,maxshort]),insurance[:ic]')
    (HERE/'engine.py').write_text(source,encoding='utf-8')


if __name__=='__main__':build()
