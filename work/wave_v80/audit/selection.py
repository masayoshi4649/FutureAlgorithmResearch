"""前半だけで固定する代表選択と、改修条件・入力指紋の整合を独立に点検する。"""

import json

from accounts import HERE,WORK,study


def rank(packet: dict) -> tuple:
    """機能: 保存仕様から両商品の弱い側を優先する順位を再計算する。

    引数: packet(dict)。返り値: 順位tuple。
    """
    markets=[packet['periods']['前16'][s] for s in ['TOPIX','NK225']]
    sufficient=all(r['trades']>=20 and r['active_sessions']>=8 for r in markets)
    shares=[r['profit']/(r['profit']+r['loss']) if r['profit']+r['loss'] else -1. for r in markets]
    return sufficient,min(shares),sum(shares)/2,min(r['net']/max(1.,r['fees']) for r in markets),packet['config']['id']


def main() -> None:
    """機能: 初回と改修の選定を前半保存結果から独立に再現する。

    引数: なし。返り値: なし(None)。監査JSONだけ保存する。
    """
    initial=study.load(WORK/'初回事前固定.json');repair=study.load(WORK/'改修事前固定.json')
    chosen_first=study.load(WORK/'初回前半選定.json');chosen_final=study.load(WORK/'最終前半選定.json')
    fingerprint_count=0
    for fixed in [initial,repair,chosen_first,chosen_final]:
        for name,wanted in fixed['SHA256'].items():
            assert study.digest(study.ROOT/name)==wanted,name;fingerprint_count+=1
    first=[study.load(p) for p in sorted((WORK/'first/results').glob('*.json'))]
    revised=[study.load(p) for p in sorted((WORK/'repair/results').glob('*.json'))]
    assert len(first)==288 and len(revised)==42
    assert {r['config']['id'] for r in first}=={c['id'] for c in initial['条件']}
    assert {r['config']['id'] for r in revised}=={c['id'] for c in repair['条件']}
    for packet in first+revised:
        assert set(r['session'] for r in packet['rows'])==set(initial['前16'])
        assert len(packet['rows'])==32
        assert packet['periods']['後14']['TOPIX']['sessions']==0
        assert packet['periods']['後14']['NK225']['sessions']==0
    picked_first=[max((r for r in first if r['config']['entry_mode']==mode and r['config']['signal']!=7),key=rank) for mode in [0,1,2]]
    picked_repair=[max((r for r in revised if r['config']['entry_mode']==mode),key=rank) for mode in [0,1,2]]
    assert [r['config'] for r in picked_first]==chosen_first['代表']==chosen_final['初回']
    assert [r['config'] for r in picked_repair]==chosen_final['改修']
    positive=[r['config'] for r in first if all(r['periods']['前16'][s]['net']>0 for s in ['TOPIX','NK225'])]
    assert positive==repair['初回少数黒字']==chosen_final['少数黒字']
    expected={c['id']:c for c in chosen_final['初回']+chosen_final['改修']+positive+chosen_final['無方向対照']}
    assert list(expected.values())==chosen_final['確認条件']
    for control in chosen_final['無方向対照']:
        assert control['signal']==7 and control['state_mode']==0 and not control['invert'] and control['repair_mode']==0
    for packet,row in zip(picked_first,chosen_first['順位根拠']):
        assert list(rank(packet))==row['score']
    for packet,row in zip(picked_repair,chosen_final['順位根拠']):
        assert list(rank(packet))==row['score']
    result=dict(合格=True,初回条件数=len(first),改修条件数=len(revised),確認代表数=len(expected),
        固定SHA照合ファイル数=fingerprint_count,探索全結果の後14口座数=0,
        初回代表=[r['config']['id'] for r in picked_first],改修代表=[r['config']['id'] for r in picked_repair],
        初回代表の十分性=[rank(r)[0] for r in picked_first],改修代表の十分性=[rank(r)[0] for r in picked_repair],
        初回少数黒字数=len(positive),最終選定SHA256=study.digest(WORK/'最終前半選定.json'),
        注意='全30場は既知資料。保存された探索結果と順位の再現であり、過去の研究や人間の既知情報からの完全独立を証明しない。')
    (HERE/'前半選定と固定入力の独立監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
