"""同bytesの旧E01エンジンへ既定無効の三部品だけを追加する。"""

import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'legacy_root/work/wave_v85/engine.py'
TARGET = HERE / 'last_core126.py'


def replace_once(text: str, before: str, after: str) -> str:
    """
    機能: 旧源の指定境界だけを一回置換する。
    引数: text/before/after(str)は旧全源と一致必須の境界と新源。
    返り値: strは追加後の源。不一致なら生成を拒否する。
    """
    assert text.count(before) == 1, before[:160]
    return text.replace(before, after)


def build() -> dict:
    """
    機能: 原版分岐を保持し、利益床・損失後再成立・場損失停止を増設する。
    引数: なし。
    返り値: dictは旧源と新源の指紋。市場読取と金融再生は行わない。
    """
    assert TARGET.resolve().is_relative_to(HERE)
    text = SOURCE.read_text(encoding='utf-8-sig')
    original = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    text = replace_once(text,
        'quiet=None, quiet_force=None, quiet_not_before=None):',
        'quiet=None, quiet_force=None, quiet_not_before=None, policy126=None, market126=None):')
    text = replace_once(text,
        '    n = len(price)\n    if quiet is None:',
        '''    n = len(price)
    # ----------------------------------------
    # 新部品は明示設定時だけ有効。原版の価格・影・注文分岐は保持する。
    if policy126 is None: policy126 = np.zeros(4)
    if market126 is None: market126 = np.full((n, 12), np.nan)
    policy_events126 = np.zeros((24000, 14)); pc126 = 0
    policy_curve126 = np.zeros((n, 12)) if detail else np.zeros((1, 12))
    session_r126 = 0.; session_stop126 = False
    session_pending126 = False; session_source126 = -1
    rearm_block126 = np.zeros(2, np.bool_)
    rearm_close126 = np.full(2, -np.inf)
    anchor_ready126 = np.zeros(2, np.bool_)
    anchor_row126 = np.full(2, -1, np.int64)
    anchor_time126 = np.full(2, np.nan)
    anchor_peer_time126 = np.full(2, np.nan)
    anchor_own126 = np.full(2, np.nan); anchor_peer126 = np.full(2, np.nan)
    anchor_own_atr126 = np.full(2, np.nan); anchor_peer_atr126 = np.full(2, np.nan)
    if quiet is None:''')
    text = replace_once(text,
        'and t >= pause_until and not blocked[0 if plan[21]>0 else 1] and not quiet[i]',
        'and t >= pause_until and not session_stop126 and not rearm_block126[0 if plan[21]>0 else 1] and not blocked[0 if plan[21]>0 else 1] and not quiet[i]')
    text = replace_once(text,
        '                    campaign = int(plan[1])+1; shadow_campaign = campaign; base = realized; entry_row = i',
        '''                    campaign = int(plan[1])+1; shadow_campaign = campaign; base = realized; entry_row = i
                    if session_r126 == 0.: session_r126 = risk''')
    text = replace_once(text,
        '        elif not is_entry and not closed and budget and i>budget_row',
        '''        elif not is_entry and not closed and session_pending126 and i > session_source126:
            fill = p; reason = 73; source = session_source126; selected[:] = True
            for slot in range(q0):
                if alive[slot]:
                    slot_events[sc] = np.array([i,source,campaign,slot+1,5.,slot_leg[slot],d,fill,1. if slot_leg[slot]>=0 else 0.,reason,plan_row]); sc += 1
            tc, oc, gain, move, done = close_slots(pos,used,slot_leg,selected,fill,i,source,reason,campaign,trades,tc,orders,oc)
            realized += gain; cash += move; acted = True; closed_now = True
            session_pending126 = False
            policy_events126[pc126] = np.array([i,campaign,5.,d,source,realized,session_r126,policy126[3],done,0.,0.,0.,0.,0.]); pc126 += 1
        elif not is_entry and not closed and budget and i>budget_row''')
    text = replace_once(text,
        '            net_campaign = realized-base-campaign_fees\n            ix = 0 if d > 0 else 1',
        '''            net_campaign = realized-base-campaign_fees
            ix = 0 if d > 0 else 1
            if policy126[2] > 0. and net_campaign < 0.:
                rearm_block126[ix] = True; rearm_close126[ix] = t
                anchor_ready126[ix] = False; anchor_row126[ix] = -1
                policy_events126[pc126] = np.array([i,campaign,1.,d,i,net_campaign,risk,t,0.,0.,0.,0.,0.,0.]); pc126 += 1''')
    text = replace_once(text,
        '        # ここから現在観測による次行予約。復元でも損益・R・期限は初期化しない。\n        if not closed:',
        '''        # ここから現在観測による次行予約。復元でも損益・R・期限は初期化しない。
        # ----------------------------------------
        # 場損失は初回実新規のRへ固定し、部分利確込みの全場時価で判定する。
        if policy126[3] > 0. and session_r126 > 0. and not session_stop126 and equity <= -policy126[3]*session_r126:
            session_stop126 = True
            session_pending126 = not closed
            session_source126 = i
            policy_events126[pc126] = np.array([i,campaign,4.,d,i,equity,session_r126,policy126[3],inv[0],0.,0.,0.,0.,0.]); pc126 += 1
        # ----------------------------------------
        # 再成立は現在行の処理後にのみ公開し、同じ行の新規を許可しない。
        if policy126[2] > 0. and market126[i,11] == 1.:
            for ix126 in range(2):
                if not rearm_block126[ix126]: continue
                sd126 = 1. if ix126 == 0 else -1.
                if not anchor_ready126[ix126] and t > rearm_close126[ix126] and market126[i,8] > rearm_close126[ix126]:
                    anchor_ready126[ix126] = True; anchor_row126[ix126] = i; anchor_time126[ix126] = t
                    anchor_own126[ix126] = market126[i,0]; anchor_peer126[ix126] = market126[i,1]
                    anchor_peer_time126[ix126] = market126[i,8]
                    anchor_own_atr126[ix126] = market126[i,2]; anchor_peer_atr126[ix126] = market126[i,3]
                    policy_events126[pc126] = np.array([i,campaign,2.,sd126,i,anchor_own126[ix126],anchor_peer126[ix126],anchor_own_atr126[ix126],anchor_peer_atr126[ix126],market126[i,8],0.,0.,0.,0.]); pc126 += 1
                if anchor_ready126[ix126]:
                    own126 = sd126*(market126[i,0]-anchor_own126[ix126])/anchor_own_atr126[ix126]
                    peer126 = sd126*(market126[i,1]-anchor_peer126[ix126])/anchor_peer_atr126[ix126]
                    window126 = market126[i,9] >= anchor_time126[ix126] and market126[i,10] >= anchor_peer_time126[ix126]
                    direction126 = sd126*market126[i,4] > .05 and sd126*market126[i,6] > .05
                    if window126 and direction126 and own126 >= policy126[2] and peer126 >= policy126[2]:
                        rearm_block126[ix126] = False
                        policy_events126[pc126] = np.array([i,campaign,3.,sd126,anchor_row126[ix126],own126,peer126,policy126[2],market126[i,4],market126[i,6],market126[i,9],market126[i,10],0.,0.]); pc126 += 1
        if not closed:''')
    text = replace_once(text,
        '            guard_peak = max(guard_peak,net_liquidation)\n            if losspar[15] > 0',
        '''            guard_peak = max(guard_peak,net_liquidation)
            # ----------------------------------------
            # 十分な順行と両市場の新しい反対進行が同時成立した行だけ床を引き上げる。
            opposition126 = i > entry_row and market126[i,8] > time[entry_row] and market126[i,11] == 1. and d*market126[i,4] < -.05 and d*market126[i,5] < -.1 and d*market126[i,6] < -.05 and d*market126[i,7] < -.1
            if policy126[0] > 0. and guard_peak >= policy126[0]*risk and opposition126:
                next_floor126 = max(guard_floor, policy126[1]*guard_peak)
                if next_floor126 > guard_floor:
                    guard_floor = next_floor126
                    policy_events126[pc126] = np.array([i,campaign,6.,d,i,net_liquidation,guard_peak,guard_floor,market126[i,4],market126[i,5],market126[i,6],market126[i,7],risk,0.]); pc126 += 1
            if policy126[0] > 0. and np.isfinite(guard_floor) and net_liquidation <= guard_floor and not guard_pending and not budget:
                guard_pending = True; guard_row = i
                policy_events126[pc126] = np.array([i,campaign,7.,d,i,net_liquidation,guard_peak,guard_floor,inv[0],0.,0.,0.,0.,0.]); pc126 += 1
            if losspar[15] > 0''')
    text = replace_once(text,
        '    stats = np.array([realized, dd, maxlong, maxshort, maxgross, maxnet, max_error, min_equity, max_equity, inv[0], 0.])',
        '''        if detail:
            policy_curve126[i] = np.array([session_r126,int(session_stop126),int(session_pending126),int(rearm_block126[0]),int(rearm_block126[1]),anchor_row126[0],anchor_row126[1],guard_peak,guard_floor,market126[i,8],pc126,i])
        if pc126 >= len(policy_events126)-8:
            raise ValueError('追加政策の証跡上限です')
    stats = np.array([realized, dd, maxlong, maxshort, maxgross, maxnet, max_error, min_equity, max_equity, inv[0], 0.])''')
    text = replace_once(text,
        'block_events[:xc], time_events[:qc])',
        'block_events[:xc], time_events[:qc], policy_curve126, policy_events126[:pc126])')
    TARGET.write_text(text, encoding='utf-8', newline='\n')
    compile(text, str(TARGET), 'exec')
    return dict(passed=True, source_sha256=original,
                generated_sha256=hashlib.sha256(TARGET.read_bytes()).hexdigest(),
                原版分岐削除=0, 新部品既定無効=True, 市場読取=0, 金融再生=0)


if __name__ == '__main__':
    import json
    proof = build()
    (HERE / '原版保持の三部品生成.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(proof, ensure_ascii=False))
