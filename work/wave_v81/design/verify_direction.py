"""価格反転、イベント準備、同時計の二市場参照を損益に依存しない例で確認する。"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(BASE))
from signals import market_features,project


def frames(prices, times=None, quantities=None, validity=None, seqs=None, spreads=None):
    """
    機能: 方向検査専用の最良気配系列を構成する。
    引数: prices (list)、times/quantities/validity/seqs/spreads (list又はNone)。
    返り値: dict の市場特徴。原本や損益は参照しない。
    """
    prices=np.asarray(prices,dtype=float);n=len(prices)
    times=np.asarray(times if times is not None else np.arange(n),dtype=float)
    quantity=np.asarray(quantities if quantities is not None else np.full(n,100.),dtype=float)
    valid=np.asarray(validity if validity is not None else np.ones(n),dtype=bool)
    seq=np.asarray(seqs if seqs is not None else np.arange(n),dtype=np.int64)
    r=dict(time_s=times,seq=seq,tick=1.)
    spreads=np.asarray(spreads if spreads is not None else np.ones(n),dtype=float)
    b=dict(time_s=times,seq=seq,bid=prices,ask=prices+spreads,bid_qty=np.where(valid,quantity,0.),ask_qty=np.full(n,100.),
           valid=np.zeros(n,dtype=bool),reset=np.ones(n,dtype=bool))
    return market_features(r,b)


# ----------------------------------------
def main():
    """
    機能: 具体経路に対する期待状態と時計の禁止条件を検査して保存する。
    引数: なし。
    返り値: None。design内だけに結果を保存する。
    """
    checks=[]
    turn=frames(np.array([0,1,2,4,3,2,1,-1,0,1])+100)
    assert np.array_equal(turn['states'][1],[0,0,1,1,1,-1,-1,-1,-1,1])
    assert np.array_equal(turn['last_price_turn'][1],[-1,-1,2,2,2,5,5,5,5,9])
    checks.append('k2の確定方向、最高安値更新、2呼値逆行反転、反転行が期待値と一致')
    same_clock=frames([100,102,100],[0,0,0])
    assert np.array_equal(same_clock['states'][1],[0,1,-1])
    checks.append('自己は同時計でも既読の現在行更新を即反映する')
    flow=frames([100]*12,quantities=[100,101,102,103,104,105,106,107,108,108,108,108])
    assert not np.any(flow['valid'][4,:8]) and np.all(flow['valid'][4,8:])
    assert np.all(flow['flow'][0,1:]==1) and np.all(flow['flow_count'][8:]==8)
    assert np.all(flow['last_flow_update'][8:]==8)
    checks.append('EMA8は非ゼロ8更新目から有効、変化なしの行では減衰せず最後の更新行を保持')
    broken=frames([100]*11,quantities=np.arange(100,111),validity=[True]*9+[False,True])
    assert not broken['valid'][4,9] and not broken['valid'][4,10] and broken['flow_count'][10]==8
    assert broken['states'][4,9]==0
    checks.append('最良不正を反対方向にせず、回復時は比較元だけ置き直して既存EMAと8件の準備数を保持')
    checks.append('検査入力の旧10段validは全False・旧resetは全Trueだが最良状態に流用しない')
    wide=frames([100,102,104,103,102],spreads=[1,1,2,2,1])
    assert np.array_equal(wide['states'][1],[0,1,1,1,-1])
    assert np.all(wide['valid'][1]) and np.array_equal(wide['price_valid'],[True,True,False,False,True])
    checks.append('正常なspread拡大中も極値と方向を追い、新規品質だけを無効にする')
    skipped=frames([100,102,104,101],seqs=[0,1,2,8])
    assert np.array_equal(skipped['states'][1],[0,1,1,-1])
    assert skipped['flow_count'][3]==2 and not skipped['flow_comparable'][3]
    assert np.isnan(skipped['raw_ofi'][3]) and skipped['flow_rebase'][3]
    checks.append('原本seqが飛べばOFI比較元だけ再開し、D1は最後有効極値から反転を判定する')
    missing=frames([100,102,999,101,100],validity=[True,True,False,True,True])
    assert np.array_equal(missing['states'][1],[0,1,0,1,-1])
    assert not missing['valid'][1,2] and missing['turn_extreme'][1,2]==102.5
    checks.append('無効行の極端な価格を使わず最後の観測極値を保ち、復帰後に方向を再判定する')
    gap=frames([100]*10,times=list(range(9))+[30],quantities=np.arange(100,110))
    assert gap['flow_count'][9]==9 and gap['valid'][4,9]
    checks.append('時計差だけでは方向履歴を消さず、次の有効イベントを継続して数える')
    peer=frames([100,102,101,104,102,106],times=[10,10,11,11,12,12])
    own=frames([100,101,102],times=[11,12,13])
    combined=project(own,peer)
    assert np.array_equal(combined['source_peer'],[0,2,4])
    assert np.array_equal(combined['states_peer'][1],[0,1,-1])
    assert combined['states_peer'][1,1]!=peer['states'][1,3] or combined['source_peer'][1]!=3
    checks.append('相手はstrictpastの時計先頭行だけへ対応し、同時計後続の強い更新を先取りしない')
    absent=project(frames([100],times=[10]),peer)
    stale=project(frames([100],times=[30]),peer)
    assert absent['source_peer'][0]==-1 and not absent['valid_peer'].any()
    assert not stale['valid_peer'].any() and stale['age_peer'][0]>10
    checks.append('同時刻しかない相手と10秒超の相手は無効で、方向を捏造しない')
    result=dict(全合格=True,検査件数=len(checks),検査内容=checks,損益参照=False,
                signals_SHA256=hashlib.sha256((BASE/'signals.py').read_bytes()).hexdigest())
    (HERE/'方向状態の具体例照合.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
