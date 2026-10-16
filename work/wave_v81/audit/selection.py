"""事前固定した商品共通順位と、前半だけによる代表選択を独立に照合する。"""

import json

from accounts import HERE,WORK,study


def rank(packet: dict) -> tuple:
    """機能: 両商品の弱い側を優先する順位を、金額の分子分母から別計算する。

    引数: packet(dict)。返り値: 独立順位キー(tuple)。
    """
    markets=[packet['periods']['前16'][symbol] for symbol in ['TOPIX','NK225']]
    sufficient=all(row['trades']>=20 and row['active_sessions']>=8 for row in markets)
    shares=[row['profit']/(row['profit']+row['loss']) if row['profit']+row['loss'] else -1. for row in markets]
    best_removed=[]
    for symbol,row in zip(['TOPIX','NK225'],markets):
        sessions=[r['net'] for r in packet['rows'] if r['symbol']==symbol]
        without=sum(sessions)-max(sessions)
        best_removed.append(without/max(1.,row['fees']))
    return sufficient,min(shares),sum(shares)/2,min(best_removed),packet['config']['id']


def main() -> None:
    """機能: 初回86条件・前半3代表・指紋・後半未混入を照合する。

    引数: なし。返り値: なし(None)。監査結果をJSONへ保存する。
    """
    fixed=study.load(WORK/'初回事前固定.json')
    chosen=study.load(WORK/'初回前半選定.json')
    hashes=0
    for block in [fixed,chosen]:
        for name,wanted in block['SHA256'].items():
            assert study.digest(study.ROOT/name)==wanted,name
            hashes+=1
    direction=study.load(WORK/'design/方向仕様.json')
    raw_hashes=0
    for section in ['入力SHA256','原本SHA256']:
        for name,wanted in direction[section].items():
            assert study.digest(study.ROOT/name)==wanted,name
            hashes+=1
            raw_hashes+=int(section=='原本SHA256')
    for name,wanted in direction['コードSHA256'].items():
        assert study.digest(WORK/name)==wanted,name
        hashes+=1
    packets=[study.load(p) for p in sorted((WORK/'first/results').glob('*.json'))]
    assert len(packets)==len(fixed['条件'])==86
    assert {p['config']['id'] for p in packets}=={c['id'] for c in fixed['条件']}
    for packet in packets:
        assert len(packet['rows'])==32
        assert set(r['session'] for r in packet['rows'])==set(fixed['前16'])
        for symbol in ['TOPIX','NK225']:
            assert packet['periods']['後14'][symbol]['sessions']==0
    picked=[max((p for p in packets if p['config']['family']==family),key=rank) for family in ['D1','D2','D3']]
    assert [p['config'] for p in picked]==chosen['代表']
    for packet,proof in zip(picked,chosen['順位根拠']):
        assert list(rank(packet))==proof['score']
    result=dict(合格=True,初回条件数=len(packets),代表数=3,探索結果の後14口座数=0,
        固定SHA一致数=hashes,内原本一致数=raw_hashes,初回代表=[p['config']['id'] for p in picked],
        両商品20取引8活動場充足=[rank(p)[0] for p in picked],
        初回固定SHA256=study.digest(WORK/'初回事前固定.json'),選定SHA256=study.digest(WORK/'初回前半選定.json'),
        注意='全30場自体は既知資料。前半固定の再現であり、未知期間の性能証明ではない。')
    (HERE/'前半選定と固定入力の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
