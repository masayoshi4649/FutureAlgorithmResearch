"""表示回復周期を、その間の観測出来高の有無だけで分類する。"""

from pathlib import Path
import hashlib
import json
import pickle

import numpy as np


HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent.parent/'wave_v57'


def main() -> None:
    """機能: 全完了周期内の市場全体出来高と、表示回復の意味を照合する。

    引数: なし。返り値: なし(None)。売買成績・未来ラベルは使用しない。
    """
    frames=pickle.loads((SOURCE/'features.pkl').read_bytes())
    events=pickle.loads((SOURCE/'events.pkl').read_bytes())
    records=[]
    for key in sorted(frames):
        data,ev=frames[key],events[key]
        start=np.searchsorted(data['seq'],ev['start_seq']);end=ev['i']
        np.testing.assert_array_equal(data['seq'][start],ev['start_seq'])
        assert np.all(start<end)
        delta=data['volume_delta']
        cumulative=np.r_[0.,np.cumsum(np.nan_to_num(delta,nan=0.))]
        missing=np.r_[0,np.cumsum(~np.isfinite(delta))]
        resets=np.r_[0,np.cumsum(data['reset'])]
        assert not np.any(resets[end+1]-resets[start])
        volume=cumulative[end+1]-cumulative[start]
        unknown=(missing[end+1]-missing[start])>0
        known=~unknown
        assert not np.any(volume<0)
        record=dict(セッション=key[0],銘柄=key[1],表示回復完了数=len(ev),周期中出来高既知数=int(known.sum()),
                    周期中出来高ゼロ数=int((known&(volume==0)).sum()),周期中出来高正数=int((known&(volume>0)).sum()),
                    周期中出来高欠測数=int(unknown.sum()),完了行出来高ゼロ数=int((delta[end]==0).sum()))
        records.append(record)
    summary={}
    fields=[k for k in records[0] if k not in ('セッション','銘柄')]
    for symbol in ('TOPIX','NK225'):
        summary[symbol]={k:sum(r[k] for r in records if r['銘柄']==symbol) for k in fields}
        summary[symbol]['周期中出来高既知でゼロの割合']=summary[symbol]['周期中出来高ゼロ数']/summary[symbol]['周期中出来高既知数']
    report=dict(合格=True,対象='売買に採用された入口に限定しない、10段全価格の表示回復完了周期',
                計算='減少開始行から回復完了行までのvolume_deltaを両端含め加算。市場全体の出来高であり、その壁での出来高ではない。',
                解釈='周期中出来高ゼロなら、保存された累積値からは周期中の約定を確認できない。表示回復を、約定を吸収したことと同一視できない。正なら吸収と判定できるという逆の主張もできない。',
                制約='スナップショット間の内訳・主体・遅延配信は識別しない。周期は重複し、出来高を周期ごと加算した値は市場出来高と比較しない。',
                銘柄別=summary,原本別=records,
                入力SHA256={name:hashlib.sha256((SOURCE/name).read_bytes()).hexdigest() for name in ('features.pkl','events.pkl')})
    (HERE/'表示回復と出来高の独立照合.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
