"""旧両影へ、前行の注文を評価した後だけ働く短期支持の公開制御を加える。"""
from pathlib import Path

HERE=Path(__file__).resolve().parent
OLD=HERE.parents[1]/'wave_v86'
ARGS='short_mode, raw_seq, self_value, self_valid, self_source, peer_value, peer_valid, peer_source_time'


def once(text,before,after):
    """
    機能: 既知の接続箇所だけを置換する。
    引数: text/before/after(str)。
    返り値: str。
    """
    assert text.count(before)==1,(before,text.count(before))
    return text.replace(before,after,1)


def publishing(prefix,indent):
    """
    機能: 内部の待機と極値は保持し、外へ出す注文の有効性だけを記述する。
    引数: prefix/indent(str)。
    返り値: str の共通生成コード。
    """
    p=prefix
    lines=f'''{p}publish=False
if {p}pending_d:
    {p}publish=supported(short_mode,{p}pending_d,{p}pending_extreme_row,i,raw_seq,time,self_value,self_valid,self_source,peer_value,peer_valid,peer_source_time)
    if short_mode>0 and {p}publish:
        if not {p}was_published: {p}pending_row=i
        {p}pending_market=int({p}par[28])==2 or {p}pending_d*(price[i]-{p}pending_level)>=-1e-8
{p}support_curve[i,:]=np.array([{p}pending_d,{p}pending_extreme_row,int({p}publish),{p}pending_level,self_source[i],peer_source_time[i]])
{p}was_published={p}publish
'''
    return ''.join(indent+line+'\n' for line in lines.rstrip().splitlines())


def build_shadow():
    """
    機能: GUの独立通常影・出口影で使う支持制御版を生成する。
    引数: なし。
    返り値: str の生成先。
    """
    text=(OLD/'shadow_engine.py').read_text(encoding='utf-8')
    text=once(text,'from numba import njit','from numba import njit\nfrom wave87_round3_core import supported')
    text=once(text,'quiet, quiet_force, quiet_not_before):','quiet, quiet_force, quiet_not_before, '+ARGS+'):')
    text=once(text,'    effective_qty=int(par[0]);pending_qty=int(par[0]);pending_market=False',
        '    pending_extreme_row=-1;was_published=False\n    support_curve=np.zeros((n,6))\n    effective_qty=int(par[0]);pending_qty=int(par[0]);pending_market=False')
    text=once(text,'            if i>0: plans[i,:]=plans[i-1,:]',
        '            if i>0: plans[i,:]=plans[i-1,:]\n            if short_mode>0:\n                plans[i,21]=0.;was_published=False')
    text=once(text,'                pending_extreme=min(pending_extreme,p) if pending_d>0 else max(pending_extreme,p)',
        '                changed_extreme=min(pending_extreme,p) if pending_d>0 else max(pending_extreme,p)\n                if changed_extreme!=pending_extreme: pending_extreme_row=i\n                pending_extreme=changed_extreme')
    text=once(text,'                    pending_until=t+par[27];pending_row=i;pending_extreme=p',
        '                    pending_until=t+par[27];pending_row=i;pending_extreme=p;pending_extreme_row=i;was_published=False')
    text=once(text,'        plans[i,:]=np.array([d,campaign,a,anchor,risk,entry_row,entry_t,inv[0],realized,base,',
        publishing('','        ')+'        plans[i,:]=np.array([d,campaign,a,anchor,risk,entry_row,entry_t,inv[0],realized,base,')
    text=once(text,'            pending_d,pending_level,pending_until,pending_atr,pending_qty,int(pending_market),',
        '            pending_d if publish else 0,pending_level,pending_until,pending_atr,pending_qty,int(pending_market),')
    text=once(text,'plans,execution_plans,dynamic_events[:dynamic_count]',
        'plans,execution_plans,dynamic_events[:dynamic_count],support_curve')
    target=HERE/'shadow_engine.py';target.write_text(text,encoding='utf-8')
    return str(target)


def build_combined():
    """
    機能: 利確後再参加の統合器へ、同じ次観測有効の支持条件を追加する。
    引数: なし。
    返り値: str の生成先。
    """
    text=(OLD/'phase2/engine.py').read_text(encoding='utf-8')
    text=once(text,'from numba import njit','from numba import njit\nfrom wave87_round3_core import supported')
    text=once(text,'cooldown_seconds, profit_fast_enabled):','cooldown_seconds, profit_fast_enabled, '+ARGS+'):')
    text=once(text,'    ns_ready_after=-np.inf','    ns_pending_extreme_row=-1;xs_pending_extreme_row=-1\n    ns_was_published=False;xs_was_published=False\n    ns_support_curve=np.zeros((n,6));xs_support_curve=np.zeros((n,6))\n    ns_ready_after=-np.inf')
    for p in ('ns_','xs_'):
        text=once(text,f'                    {p}plans[i, :] = {p}plans[i - 1, :]',
            f'                    {p}plans[i, :] = {p}plans[i - 1, :]\n                if short_mode>0:\n                    {p}plans[i,21]=0.;{p}was_published=False')
        before=f'                    {p}pending_extreme = min({p}pending_extreme, {p}p) if {p}pending_d > 0 else max({p}pending_extreme, {p}p)'
        after=f'''                    {p}changed_extreme = min({p}pending_extreme, {p}p) if {p}pending_d > 0 else max({p}pending_extreme, {p}p)
                    if {p}changed_extreme!={p}pending_extreme: {p}pending_extreme_row=i
                    {p}pending_extreme={p}changed_extreme'''
        text=once(text,before,after)
        text=once(text,f'                        {p}pending_extreme = {p}p',
            f'                        {p}pending_extreme = {p}p\n                        {p}pending_extreme_row=i;{p}was_published=False')
        # 更新済み計画だけを公開する。現行の約定評価より前へ移動しない。
        before=f'            {p}plans[i, :] = np.array([{p}d, {p}campaign,'
        text=once(text,before,publishing(p,'            ')+before)
        text=once(text,f'{p}stop_reason, {p}pending_d, {p}pending_level,',
            f'{p}stop_reason, {p}pending_d if {p}publish else 0, {p}pending_level,')
    text=once(text,'profit_reentry_events[:profit_reentry_count])',
        'profit_reentry_events[:profit_reentry_count], ns_support_curve, xs_support_curve)')
    target=HERE/'engine.py';target.write_text(text,encoding='utf-8')
    return str(target)


if __name__=='__main__':
    print(build_shadow())
    print(build_combined())
