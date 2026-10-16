"""診断と固定18条件の再生結果だけから、暗色の板検証レポートを生成する。"""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(WORK))
import experiment

OUT=ROOT/'アルゴリズム調査/00075_J2赤字上位セッションの板検証と防止策'
MAIN='赤字上位3セッションの板と防止策.html'


def load(path: Path) -> object:
    """機能: 保存済みのJSON又は配列を読み込む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return experiment.load(path)


def charts(cases: list) -> dict:
    """機能: 元建玉の全原本清算評価から、5秒ごと両極値を残す描画を作る。

    引数: cases(list)。返り値: 取引IDと描画点列(dict)。
    全原本の極値を診断値へ照合する。表示用間引きを売買判断には使わない。
    """
    ready,book,*_=experiment.material(5);ledgers=load(WORK/'ledgers/E0_X0.pkl');output={}
    for c in cases:
        key=(c['セッション'],c['商品']);r,f=ready[key],book[key]
        for t in c['取引']:
            trade=ledgers[key]['trades'][t['組番号']-1];start,end=int(trade[1]),int(trade[2])
            times=r['time_s'][start:end+1];quotes=(f['bid'] if trade[3]==1 else f['ask'])[start:end+1]
            value=1000 if key[1]=='TOPIX' else 10
            nets=trade[3]*(quotes-trade[5])*trade[4]*value-trade[7]-trade[8]
            assert np.isfinite(nets).all()
            assert abs(float(nets.max())-t['事後']['MFE円'])<1e-6
            assert abs(float(nets.min())-t['事後']['MAE円'])<1e-6
            bins=np.floor((times-times[0])/5).astype(int);boundaries=np.r_[0,np.flatnonzero(np.diff(bins))+1,len(times)]
            indices={0,len(times)-1}
            for a,b in zip(boundaries[:-1],boundaries[1:]):
                indices.update((a+int(np.argmin(nets[a:b])),a+int(np.argmax(nets[a:b]))))
            output[t['ID']]=dict(start=float(times[0]),end=float(times[-1]),points=[[float(times[i]),float(nets[i])] for i in sorted(indices)])
    return output


def main() -> None:
    """機能: 会計・板・事後経路を一つの通信不要HTMLにまとめる。

    引数: なし。返り値: なし(None)。
    """
    fixed=load(WORK/'事前固定.json');case=load(HERE/'6ケース.json');effects=load(WORK/'analysis/全条件の効果.json')
    results={c['id']:load(WORK/'results'/f'{c["id"]}.json') for c in fixed['条件']}
    data=dict(cases=case['ケース'],worst=fixed['商品別赤字上位3'],days=fixed['開始日合計の赤字上位3'],sessions=fixed['全30'],
        effects=effects,results=results,replay=load(WORK/'analysis/赤字上位6口座の再生時刻.json'),charts=charts(case['ケース']))
    OUT.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
    html=(HERE/'template.html').read_text(encoding='utf8').replace('__STYLE__',(HERE/'style.css').read_text(encoding='utf8')).replace('__SCRIPT__',(HERE/'main.js').read_text(encoding='utf8')).replace('__DATA__',payload)
    assert not any(token in html for token in ('__STYLE__','__SCRIPT__','__DATA__'))
    (OUT/MAIN).write_text(html,encoding='utf8')
    public=dict(説明='基準J2と防止18条件。主条件情報遅延5秒。判断後の次有効ラージ気配約定、手数料後。',全30=fixed['全30'],条件=results,比較=effects,赤字上位の板と注文=case)
    (OUT/'公開会計.json').write_text(json.dumps(public,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    (HERE/'描画資料.json').write_text(json.dumps(data['charts'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(dict(HTML=str(OUT/MAIN),SHA256=hashlib.sha256((OUT/MAIN).read_bytes()).hexdigest(),ケース=len(case['ケース']),取引=len(case['全取引']),条件=len(results)),ensure_ascii=False))


if __name__=='__main__':
    main()
