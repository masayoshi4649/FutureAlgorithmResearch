"""初回代表と102改修から選ぶ最終代表・単独対照・入力固定を独立照合する。"""

import json

from accounts import HERE,WORK,study
from selection import rank


def main() -> None:
    """機能: 改修選定の候補範囲・前半限定・順位・対照仕様を検査する。

    引数: なし。返り値: なし(None)。監査JSONだけ保存する。
    """
    first=study.load(WORK/'初回前半選定.json')
    fixed=study.load(WORK/'改修前固定.json')
    chosen=study.load(WORK/'前半選定.json')
    revised=[study.load(p) for p in sorted((WORK/'improved/results').glob('*.json'))]
    initial=[study.load(WORK/'first/results'/f'{c["id"]}.json') for c in first['代表']]
    assert len(revised)==len(fixed['条件'])==102
    assert {c['id'] for c in fixed['条件']}=={p['config']['id'] for p in revised}
    hashes=0
    for block in [fixed,chosen]:
        for name,wanted in block['SHA256'].items():
            assert study.digest(study.ROOT/name)==wanted,name
            hashes+=1
    for packet in revised+initial:
        assert len(packet['rows'])==32
        assert {r['session'] for r in packet['rows']}==set(fixed['前16'])
        for symbol in ['TOPIX','NK225']:assert packet['periods']['後14'][symbol]['sessions']==0
    picked=[max((p for p in initial+revised if p['config']['family']==f),key=rank) for f in ['D1','D2','D3']]
    assert [p['config'] for p in picked]==chosen['改修']
    assert chosen['初回']==first['代表']
    for packet,proof in zip(picked,chosen['選定理由']):assert list(rank(packet))==proof['score']
    expected_solo=[dict(c,id=c['id']+'_自己のみ',solo=1,family='単独対照') for c in chosen['改修']]
    assert chosen['単独対照']==expected_solo
    expected=list({c['id']:c for c in first['代表']+chosen['改修']+expected_solo}.values())
    assert chosen['確認条件']==expected
    result=dict(合格=True,追加条件数=len(revised),初回残候補数=len(initial),最終代表数=3,確認条件数=len(expected),
        前半限定口座数=len(initial+revised)*32,探索結果の後14口座数=0,SHA一致数=hashes,
        代表=[c['id'] for c in chosen['改修']],両商品20取引8活動場充足=[rank(p)[0] for p in picked],
        単独対照は入口共通価格品質と出口中立扱いを保持=True,
        改修固定SHA256=study.digest(WORK/'改修前固定.json'),最終選定SHA256=study.digest(WORK/'前半選定.json'),
        限界='全30場は既知。前半への適合と多重探索の危険は消えない。')
    (HERE/'最終前半選定と単独対照の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
