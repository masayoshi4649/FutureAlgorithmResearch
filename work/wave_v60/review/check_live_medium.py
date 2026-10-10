"""一度だけ取得済みの現在原本と、中期の途中会計を再取得せず照合する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
LIVE=WORK/'live'
sys.path.insert(0,str(WORK/'medium'))
import features
import signals
from check_medium_accounts import account_audit


def main() -> None:
    """機能: 取得記録・固定候補・原本SHAと四口座の発生済費用を検査する。

    引数: なし。返り値: なし(None)。外部ネットワークへ接続しない。
    """
    manifest=json.loads((LIVE/'取得記録.json').read_text(encoding='utf-8'))
    selected=json.loads((LIVE/'確認候補固定.json').read_text(encoding='utf-8'))
    parsed=json.loads((LIVE/'現在原本の照合.json').read_text(encoding='utf-8'))
    result=json.loads((LIVE/'現在中期の途中損益.json').read_text(encoding='utf-8'))
    inputs=pickle.loads((LIVE/'inputs.pkl').read_bytes());quotes=pickle.loads((LIVE/'quotes.pkl').read_bytes())
    assert manifest['全応答成功'] and len(manifest['requests'])==3 and manifest['実注文']==0
    assert len({r['url'] for r in manifest['requests']})==3
    assert datetime.fromisoformat(selected['frozen_at'])<datetime.fromisoformat(manifest['共通to'].replace('Z','+00:00'))
    for request in manifest['requests']:
        assert request['成功'] and request['status']==200
        path=LIVE/request['file'];assert path.stat().st_size==request['bytes']
        if request['file'].endswith('.jsonl'):
            completion=[v for k,v in request['trailers'].items() if k.lower()=='x-history-complete']
            assert completion==[['true']]
            code=request['file'].split('.')[0]
            record=next(r for r in parsed['口座別'] if r['銘柄']==code)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==record['原本SHA256']
    assert result['config']['id']==selected['selected']['medium']['id']
    cfg=result['config'];setting=next(s for s in features.SETTINGS if s['id']==cfg['setting_id'])
    records=[]
    for account in result['accounts']:
        key=(account['session'],account['symbol']);r=inputs[key];q=quotes[key]
        frame=features.build(r,q,setting)
        candidate=signals.candidates(frame,float(q['mid'][0]),r['tick'],cfg['fraction'])[cfg['family']]
        orders=np.asarray(account['orders'],float).reshape(-1,15);trades=np.asarray(account['trades'],float).reshape(-1,22)
        position=int((orders[:,5]*orders[:,6]).sum())
        assert position==account['position']
        value=1000 if key[1]=='TOPIX' else 10
        incurred=orders[:,9].sum();realized=trades[:,6].sum()
        floating=0.
        if position:
            op=orders[orders[:,4]==1][-1]
            mark=q['mid'][-1] if account['price_mode']=='mid' else q['bid'][-1] if position>0 else q['ask'][-1]
            floating=position*(mark-op[7])*value
        np.testing.assert_allclose([account['fees_incurred'],account['realized_gross_pnl'],account['unrealized_end'],account['economic_net']],
                                   [incurred,realized,floating,realized-incurred+floating],atol=1e-5)
        if not position:account_audit(account,r,q,candidate,cfg)
        records.append(dict(銘柄=key[1],約定=account['price_mode'],返済組=len(trades),残建玉=position,
                            実現粗損益=float(realized),発生済手数料=float(incurred),含み=float(floating),時価純収支=float(realized-incurred+floating)))
    evidence=dict(合格=True,追加API取得=0,実注文=0,取得済み3応答の完全性照合=True,取得前選定不変=True,
                  セッション=parsed['セッション'],共通to=manifest['共通to'],口座=records,
                  結果SHA256=hashlib.sha256((LIVE/'現在中期の途中損益.json').read_bytes()).hexdigest())
    (HERE/'現在中期の独立監査.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
