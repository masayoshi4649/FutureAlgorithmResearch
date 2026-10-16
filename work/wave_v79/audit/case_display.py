"""公開用六ケースの時刻・参照板・OFIと会計を独立入口記録へ照合する。"""

from __future__ import annotations

from datetime import datetime
import json

from full_accounts import HERE, study
from independent_account import save


def same_time(left: str | None, right: str) -> None:
    """機能: 表示精度が異なる日本時間文字列を同一時刻として照合する。

    引数: left(str|None)、right(str)。返り値: なし(None)。
    """
    assert left is not None and datetime.fromisoformat(left)==datetime.fromisoformat(right),(left,right)


def main() -> None:
    """機能: 六ケース全18取引の生板表示点と損益を独立の注文・参照記録へ照合する。

    引数: なし。返り値: なし(None)。元資料にない数量や時刻は推測して補完しない。
    """
    path=HERE.parent/'report/6ケース.json';packet=study.load(path)
    proof=study.load(HERE/'最悪6口座の入口時計とOFI証拠監査.json')
    known={(r['商品'],r['セッション'],r['組']):r for r in proof['全新規']}
    base=study.load(HERE.parent/'results/E0_X0.json');rows={(r['symbol'],r['session']):r for r in base['rows']}
    assert packet['ケース数']==6 and packet['取引数']==18
    checked=markets=0
    for case in packet['ケース']:
        key=case['商品'],case['セッション'];row=rows[key]
        assert case['会計']['利益円']==row['profit'] and case['会計']['損失円']==row['loss'] and case['会計']['収支円']==row['net']
        for trade in case['取引']:
            cid=trade['元組番号']-trade['元組番号の起点'];old=known[(*key,cid)]
            assert trade['方向']==old['方向'] and trade['損益']['収支円']==old['確定損益']
            assert trade['時点']['新規約定']['価格']==old['新規気配']
            for name,source in (('発注判断','新規判断時計'),('新規約定','新規約定時計'),('返済判断','返済判断時計'),('返済約定','返済約定時計')):
                same_time(trade['時点'][name]['時刻'],old[source])
            same_time(trade['判断格子時刻'],old['従来価格入口の15秒格子時計'])
            same_time(trade['J2追加判断格子時刻'],old['共通格子時計'])
            for symbol,display in trade['二市場'].items():
                previous=display['旧入口']['参照'];expected=old['従来価格入口の参照市場'][symbol]
                assert previous['準備行']==expected['参照行'] and previous['原本seq']==expected['原本seq']
                assert previous['原本表示行']==expected['原本seq']+1
                assert previous['bid']==expected['bid'] and previous['ask']==expected['ask']
                same_time(previous['時刻'],expected['参照時計'])
                added=display['追加J2'];point=added['参照'];expected=old['参照市場'][symbol]
                assert point['準備行']==expected['参照行']
                if point['時刻'] is not None:same_time(point['時刻'],expected['参照時計'])
                if point['原本seq'] is not None:assert point['原本seq']==expected['原本seq']
                assert added['OFI15']['同方向支持']==(expected['OFI証拠']=='支持')
                assert added['OFI15']['明確な逆向き']==(expected['OFI証拠']=='明確逆行')
                markets+=1
            checked+=1
    assert checked==18 and markets==36
    result=dict(合格=True,ケース数=6,取引数=checked,二市場表示点数=markets,
        旧15秒入口と追加5秒条件を分離=True,日本時間と原本seq照合=True,
        ケース資料SHA256=study.digest(path),入口監査SHA256=study.digest(HERE/'最悪6口座の入口時計とOFI証拠監査.json'),
        限界='元診断にない追加点の時刻・数量は欠測のまま。補充原因や実受信時計を証明しない。')
    save(HERE/'公開六ケースの時計と参照板と損益照合.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
