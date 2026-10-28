"""日中第二巡の保存結果を数量・出口・追加確認へ分解する。金融再生はしない。"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict
import importlib.util
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
FIRST=BASE.parent
_spec=importlib.util.spec_from_file_location('fixed_day164',FIRST/'day_design/diagnose_day164.py')
source=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(source)


def main()->None:
    """保存会計の比較、原行照合、図、短い解釈を保存する。

    引数: なし。返り値: None。実取引・金融再生・条件再選択は行わない。
    """
    out=HERE/'diagnosis';diagpath=out/'日中数量上限と防御の比較164r2.json';d=source.read(diagpath)
    assert source.read(BASE/'再生全完了164r2.json')['completed'] is True
    reportpath=FIRST/'report_data164_all.json';report=source.read(reportpath);methods={m['id']:m for m in report['methods']}
    pairs=defaultdict(list)
    for r in d['parent_changes']:pairs[(r['method'],r['reference'])].append(r)
    contrasts=[]
    for (method,reference),rows in pairs.items():
        contrasts.append(dict(method=method,reference=reference,changed=sum(r['delta']!=0 for r in rows),improved=sum(r['delta']>0 for r in rows),worsened=sum(r['delta']<0 for r in rows),saved=sum(max(0,r['delta']) for r in rows),lost=sum(min(0,r['delta']) for r in rows),net_difference=sum(r['delta'] for r in rows)))
    caps=d['quantity_cap_pairs'];same=sum(len(x['initial_new'])==len(x['initial_old']) and all(a['entry']==b['entry'] and a['entry_time']==b['entry_time'] for a,b in zip(x['initial_new'],x['initial_old'])) for x in caps)
    assert len(caps)==61 and same==61
    cap_qty=dict(new=sum(r['quantity'] for x in caps for r in x['initial_new']),old=sum(r['quantity'] for x in caps for r in x['initial_old']))

    # ----------------------------------------
    # 発注判断と次原行約定を、保存済みの原板へ再照合する。
    cfg=[('2026-10-13_Day','episode/1',['NK225_D164_07','NK225_D164_13'],'09:49:20','09:53:00','同じ買値の88枚を25枚へ抑制。方向の誤りは残る'),
         ('2026-10-26_Day','addon/0',['NK225_D164_13','NK225_D164_14'],'09:30:00','15:36:00','建値保護後の再下落を取れず、追加玉は小さく損切り')]
    fonts={f.name for f in fm.fontManager.ttflist}
    for name in ('Yu Gothic','Meiryo','MS Gothic'):
        if name in fonts:plt.rcParams['font.family']=name;break
    plt.style.use('dark_background');fig,axes=plt.subplots(2,1,figsize=(13,8));examples=[]
    colors=['#69c9ff','#ffc76b']
    for ax,(session,parent,ids,start,end,title) in zip(axes,cfg):
        firstpath=next((FIRST/'results').glob('*/'+session+'.json'));newpath=next((BASE/'results').glob('*/'+session+'.json'))
        original=source.read(firstpath);changed=source.read(newpath);scene=original['scene'];raw=source.raw_rows(scene)
        caseby={c['config']['id']:c for c in original['cases']+changed['cases']}
        a=datetime.fromisoformat(session[:10]+'T'+start+'+09:00').timestamp();b=datetime.fromisoformat(session[:10]+'T'+end+'+09:00').timestamp()
        use=np.flatnonzero((raw['time']>=a)&(raw['time']<=b)&raw['valid']);display=use[::max(1,len(use)//12000)]
        ax.plot([datetime.fromtimestamp(float(t),source.JST) for t in raw['time'][display]],(raw['bid'][display]+raw['ask'][display])/2,lw=.7,c='#c1cbd4',label='原板の中値')
        orderproof=[]
        for j,method in enumerate(ids):
            case=caseby[method]
            for e in case['actual']['Events'] or []:
                if e['Order']['Parent']!=parent:continue
                ix=e['FillIndex'];di=e['Order']['DecisionIndex'];side=e['Order']['Side'];price=raw['ask'][ix] if side>0 else raw['bid'][ix]
                assert e['Price']==price and abs(e['FillTime']-raw['time'][ix])<1e-5
                orderproof.append(dict(method=method,kind=e['Order']['Kind'],reason=e['Order']['Reason'],quantity=e['Order']['Quantity'],gross=e['Gross'],decision_index=di,decision_line=int(raw['line'][di]),decision_time=source.stamp(float(raw['time'][di])),fill_index=ix,fill_line=int(raw['line'][ix]),fill_time=source.stamp(float(raw['time'][ix])),bid=float(raw['bid'][ix]),ask=float(raw['ask'][ix]),price=e['Price']))
                if a<=e['FillTime']<=b:
                    isnew=not e['Order'].get('Targets');t=datetime.fromtimestamp(e['FillTime'],source.JST)
                    ax.scatter([t],[e['Price']],marker='^' if isnew else 'v',c=colors[j],s=35,zorder=5)
                    ax.annotate(method[-2:]+(' 新' if isnew else ' 返')+str(e['Order']['Quantity']),xy=(t,e['Price']),xytext=(3,12 if j==0 else -19),textcoords='offset points',fontsize=8,color=colors[j])
        examples.append(dict(session=session,parent=parent,methods=ids,result_fingerprints=[dict(path=str(p),sha256=source.digest(p)) for p in (firstpath,newpath)],raw_sha256=raw['sha256'],orders=orderproof))
        ax.set_title(session+' / '+title,fontsize=11);ax.set_ylabel('日経ラージ価格');ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S',tz=source.JST));ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.suptitle('数量増幅の抑制と、そのまま残る入口・利益保護の限界（枚数はmicro）',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.96]);imagepath=out/'日中第二巡の数量と保護164r2.png';fig.savefig(imagepath,dpi=150);plt.close(fig)
    summaryids=['NK225_D164_'+x for x in ('00','01','07','09','12','13','14','15')]
    payload=dict(passed=True,new_financial_replays=0,known_development=True,source_fingerprints=[dict(path=str(p),sha256=source.digest(p)) for p in (diagpath,reportpath)],summary={m:methods[m]['summary'] for m in summaryids},contrasts=contrasts,delay_parents=len(caps),same_initial_time_and_price=same,delayed_initial_quantity=cap_qty,raw_examples=examples,image_sha256=source.digest(imagepath))
    (out/'日中部品の効果と原行照合164r2.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 日中第二巡：数量増幅は抑えたが、元J02を全面的には上回らない','',
           '27デイ、片側micro100枚（mini10枚相当）、手数料なし。第二巡は全54場の第一巡結果を見た後の追加開発であり、未見検証ではない。以下は保存結果の再集計で、新しい金融再生は0回。','',
           '|手法|全27場収支|赤字場|場内最悪|前20デイ|後7デイ|','|---|---:|---:|---:|---:|---:|']
    for method in summaryids:
        m=methods[method]['summary'];s=m['全場'];lines.append(f"|{method}|{s['net']:,.0f}円|{s['negative_sessions']}/27|{s['minimum_equity']:,.0f}円|{m['前40内']['net']:,.0f}円|{m['確認14内']['net']:,.0f}円|")
    lines += ['', '## 何が直り、何が残ったか','',
      '- **待機後の増量**：D13はD07の延期61親すべてで初回の約定時刻・価格が同じ。実約定した56初回玉の枚数合計を1,980→1,284microへ制限した。10/13 09:49:40の買67,810は88→25枚、損失193,600→55,000円。方向を当てた改善ではなく、短い再加速だけで量を膨らませない改善。',
      '- **増量の直後に逆行**：D15はD14に「5秒・15秒の両方が順方向の時だけ元Sourceの追撃」を加えた。追加玉53→41件。変化した11親は全て改善し合計76,300円改善した。ただし元J02へ同条件だけを加えたD08は全体で悪化しているため、追撃−50円と併用した今回の範囲の結果である。',
      '- **少量の利益を失う**：D12/14/15の建値保護は、元Sourceの利益部分返済後に残った玉だけが対象。初回から即保護するものではない。D15の初回実玉161玉（延期56＋即時105）のうち「一度正益になってから最終赤字」は49玉、計1,147,400円残る。この不満は解決していない。',
      '- **利益保護が勝ちを削る**：10/26のD14は57枚売62,840のうち28枚を10:07:21に62,490で利確。残29枚を10:56:21に62,840で同値返済した。D13ならその残玉で後に159,300円を得た。追加28枚も−50円判定で11,200円損切りし、D13の100,800円利益を失った。同親は358,100→86,800円。守った価格へ戻った後の再下落まで消している。',
      '- **頂上買い・分内反応**：失速判定・保護は原板ごとに動き、1分確定を待たない。しかし10/13では3秒の再加速でも買い判断が外れ、8秒後には−50円。時間解像度を上げただけでは頂上を識別できない。D13の数量制限はこの損失を縮めるが、負ける入口自体は残す。','',
      '## 結論','',
      'D15は前半の固定順位で選ばれた比較候補。元D00に対し赤字は10→9場、場内最悪は−189,200→−177,600円と改善した一方、収支は423,100円減った。利益返し・頂上買い・追加直後損のすべてを解決したとは言えない。',
      '部品としては、待機中の希望量上限D13と、追撃に短期の同方向確認を足したD15対D14に意味がある。全玉の浅い保護や、保護後に増量して同じ波へ入り直す第一巡D04～06は採用根拠にならない。','',
      '原板図： [日中第二巡の数量と保護](日中第二巡の数量と保護164r2.png)。全原行・判断/約定時刻・数量・返済価格は `日中部品の効果と原行照合164r2.json`。']
    (out/'日中第二巡の結論164r2.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,raw_orders=sum(len(x['orders']) for x in examples),new_financial_replays=0),ensure_ascii=False))


if __name__=='__main__':main()
