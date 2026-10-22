"""実結果を読まず、公開生成と少数候補の固定・期間集計を合成小会計で検査する。"""

from copy import deepcopy
from datetime import date,timedelta
import importlib.util
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'report119.py'
spec=importlib.util.spec_from_file_location('_report119_fixture_only',SOURCE)
R=importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
COUNT={}


def check(value: bool,label: str) -> None:
    """
    機能: 合成期待値との照合を種類別に記録し、不一致で停止する。
    引数: value(bool)は期待条件、label(str)は検査名。
    返り値: None。
    """
    assert value,label
    COUNT[label]=COUNT.get(label,0)+1


def fixture() -> dict:
    """
    機能: 日付も損益も完全合成の四十場・六手法・PORTを作る。
    引数: なし。
    返り値: dictは公開予定schema。実市場や実結果から転記しない。
    """
    sessions=[str(date(2030,1,1)+timedelta(days=i//2))+('_Day' if i%2==0 else '_Night') for i in range(40)]
    ids=['T0','T1','A0','A1','T2','T3']
    specs=[dict(id=v,family='ADAPT' if v.startswith('A') else '家族'+str(k),name='合成候補'+v,
        description='完全合成の方向条件を満たしたときに入ります。',is_adaptive=v.startswith('A'),
        horizon_minutes=20 if v=='A0' else 60,method='single' if v=='A0' else 'distinct_family_consensus',
        exit_mode=k%3,entry_mode=k%2,guard=k%2) for k,v in enumerate(ids)]
    runs=[];ports=[]
    for k,ident in enumerate(ids+['PORT']):
        for i,scene in enumerate(sessions):
            for j,symbol in enumerate(R.SYMBOLS):
                residue=(i+k+j)%7;inactive=residue==0
                p,l=(0.,0.) if inactive else ((120.,20.) if residue>2 else ((20.,120.) if residue==1 else (30.,30.)))
                row=dict(session=scene,symbol=symbol,method=ident,net=p-l,realized=p-l,profit=p,loss=l,
                    parents=0 if inactive else 2,wins=0 if inactive else 1,losses=0 if inactive else 1,
                    closed_quantity=0 if inactive else (20 if symbol=='TOPIX' else 40),fees=0. if inactive else 4.,
                    unclosed=0,max_drawdown=0. if inactive else 130.,canceled=0,fills=0 if inactive else 4,halted=0)
                if ident=='PORT':row['max_drawdown_is_upper_bound']=True;ports.append(row)
                else:runs.append(row)
    selections={}
    for symbol,order,chosen in [('TOPIX',['T0','A0','T1','A1','T2','T3'],['T0','T1','A0']),('NK225',['T1','A1','T0','A0','T2','T3'],['T1','A1'])]:
        selections[symbol]=dict(chosen=chosen,qualified=True,eligible_ids=chosen,
            ranking=[dict(id=v,eligible=v in chosen,metrics=dict(net=100. if v in chosen else -1.)) for v in order])
    return dict(sessions=sessions,splits={'設計参照21':sessions[:21],'選択6':sessions[21:27],
        '既知確認10':sessions[27:37],'追加確認3':sessions[37:],'確認13':sessions[27:],'全40':sessions},
        specs=specs,runs=runs,portfolios=ports,selection=selections,cache=[],read_log=[],source_SHA256={'合成のみ':'f'*64})


def rejected(call: object,label: str) -> None:
    """
    機能: 欠けた小会計や不正な期間がゼロへ補完されず拒否されることを確認する。
    引数: call(Callable[[],object])は合成検査、label(str)は内容。
    返り値: None。
    """
    try:call()
    except (AssertionError,ValueError,KeyError):check(True,label)
    else:raise AssertionError(label)


def inspect_public(data: dict,output: Path) -> None:
    """
    機能: 合成HTMLの全場表・上下合計・期間表を元合成数値へ照合する。
    引数: data(dict)は合成値、output(Path)は生成した人工専用フォルダ。
    返り値: None。実市場成果物を読まない。
    """
    page=BeautifulSoup((output/R.HTML_NAME).read_text(encoding='utf8'),'html.parser')
    public=json.loads((output/'公開会計.json').read_text(encoding='utf8'))
    check(public['candidate_ids']==['T0','A0','T1','A1','PORT'],'五候補を選択期だけから決める')
    for table in page.select('table.sessions'):
        ident=table['data-method'];body=table.select('tbody tr');check(len(body)==40,'各候補の四十場を省略しない')
        source={(r['session'],r['symbol']):r for r in data['runs']+data['portfolios'] if r['method']==ident}
        for tr,scene in zip(body,data['sessions']):
            check(tr['data-session']==scene,'原セッション順')
            values=[c.get_text(strip=True) for c in tr.select('td')]
            expected=[]
            for symbol in R.SYMBOLS:
                row=source[scene,symbol]
                expected.extend([f"{row['profit']:,.0f}",f"{row['loss']:,.0f}",f"{row['net']:+,.0f}" if row['net'] else '0',str(row['parents']),'—'])
            check(values==expected,'全利益損失収支取引数表示')
        footer=[c.get_text(strip=True) for c in table.select('tfoot td')];wanted=[]
        for symbol in R.SYMBOLS:
            rr=[source[s,symbol] for s in data['sessions']];net=sum(r['net'] for r in rr)
            wanted.extend([f"{sum(r['profit'] for r in rr):,.0f}",f"{sum(r['loss'] for r in rr):,.0f}",f"{net:+,.0f}" if net else '0',str(sum(r['parents'] for r in rr)),'—'])
        check(footer==wanted,'四十場footerの独立和')
    check(len(page.select('.period-panel'))==3 and len(page.select('.period-panel:not([hidden])'))==1,'三期間の既定表示')
    for ident,case in public['cases'].items():
        check(len(case['rows'])==80,'公開JSONは商品場八十行')
        for symbol in R.SYMBOLS:
            for label,scenes in data['splits'].items():
                if label not in R.PERIODS:continue
                rr=[r for r in case['rows'] if r['symbol']==symbol and r['session'] in scenes];v=case['periods'][symbol][label]
                pos=[r['net'] for r in rr if r['fills'] and r['net']>0];neg=[r['net'] for r in rr if r['fills'] and r['net']<0]
                check(v['positive']==len(pos) and v['negative']==len(neg),'場正負と親正負を混同しない')
                check(v['inactive']==sum(r['fills']==0 for r in rr),'無取引を勝ちにしない')
                check(v['net']==sum(r['net'] for r in rr) and v['top3_positive_excluded']==sum(r['net'] for r in rr)-sum(sorted(pos,reverse=True)[:3]),'期間と上位三黒字除外の独立和')
    check('max_drawdown_is_upper_bound' in (output/'公開会計.json').read_text(encoding='utf8'),'PORTの下落上界注記を保持')
    check('同時資産の実最大下落ではありません' in (output/'README.md').read_text(encoding='utf8'),'READMEで下落上界を明示')
    check(not page.select('script[src]') and not page.select('img[src]'),'外部資産取得なし')


def main() -> None:
    """
    機能: 結果未読の公開生成人工を一度実行し、sourceと証跡を保存する。
    引数: なし。
    返り値: None。金融再生・原入力・実結果・APIの読取は0。
    """
    target=HERE/'公開生成器の四十場と固定候補の合成検査_v4.json';check(not target.exists(),'人工証跡上書きなし')
    data=fixture();raw=R.json_bytes(data);out=HERE/'report_fixture_v4_合成四十場'
    proof=R.generate(data,out,R.digest(raw),fixture=True);inspect_public(data,out)
    specs,_=R.validate(data);picks,_=R.candidates(data,specs)
    changed=deepcopy(data)
    for r in changed['runs']:
        if r['session'] in changed['splits']['確認13']:
            r['profit']+=1000000.;r['net']+=1000000.;r['realized']+=1000000.
    check(R.candidates(changed,specs)[0]==picks,'確認十三と追加三の数値で候補を変更しない')
    empty=deepcopy(data)
    for symbol in R.SYMBOLS:
        empty['selection'][symbol]['chosen']=[];empty['selection'][symbol]['eligible_ids']=[];empty['selection'][symbol]['qualified']=False
    for r in empty['portfolios']:
        for key in R.SUMMARY_FIELDS:r[key]=0
    emptyout=HERE/'report_fixture_v4_無資格と未清算'
    a=empty['runs'][next(i for i,r in enumerate(empty['runs']) if r['method']=='T0' and r['symbol']=='TOPIX' and r['fills'])]
    a['unclosed']=2;a['net']+=50000.
    R.generate(empty,emptyout,R.digest(R.json_bytes(empty)),fixture=True)
    u=json.loads((emptyout/'公開会計.json').read_text(encoding='utf8'))
    for symbol in R.SYMBOLS:
        v=u['cases']['PORT']['periods'][symbol]['全40'];check(v['positive']==0 and v['inactive']==40 and v['profit_share'] is None,'無資格PORT零を成功にしない')
    v=u['cases']['T0']['periods']['TOPIX']['全40'];check(v['unclosed_sessions']==1 and v['top3_positive_excluded'] is None and not v['all_sessions_positive'],'未清算評価益を成功にしない')
    check('資格を満たす候補はありません' in (emptyout/R.HTML_NAME).read_text(encoding='utf8'),'無資格の代表を推奨しない')
    nullable=deepcopy(data)
    for row in nullable['runs']+nullable['portfolios']:
        for key in R.NULLABLE_FIELDS:row[key]=None
    nullout=HERE/'report_fixture_v4_未保存メタnull'
    R.generate(nullable,nullout,R.digest(R.json_bytes(nullable)),fixture=True,source_result=HERE/'合成の復元結果.json')
    n=json.loads((nullout/'公開会計.json').read_text(encoding='utf8'))
    original=json.loads((out/'公開会計.json').read_text(encoding='utf8'))
    for ident,case in n['cases'].items():
        check(all(row['fills'] is None and row['canceled'] is None and row['halted'] is None for row in case['rows']),'未保存メタをゼロへ補完しない')
        check(case['periods']==original['cases'][ident]['periods'],'nullでも場正負と無取引の会計判定が一致')
    check('design/合成の復元結果.json' in (nullout/'README.md').read_text(encoding='utf8'),'指定した復元結果へのリンク')
    bad=deepcopy(data);bad['runs'].pop();rejected(lambda:R.validate(bad),'欠場をゼロ補完しない')
    bad=deepcopy(data);bad['splits']['確認13'][0]=bad['splits']['選択6'][0];rejected(lambda:R.validate(bad),'選択確認の重複を拒否')
    bad=deepcopy(data);bad['portfolios'][0]['max_drawdown_is_upper_bound']=False;rejected(lambda:R.validate(bad),'PORT下落上界の欠落を拒否')
    bad=deepcopy(data);bad['runs'][1]['net']+=1;rejected(lambda:R.validate(bad),'完結場の親P/L不整合を拒否')
    rejected(lambda:R.generate(data,out,R.digest(raw),fixture=True),'既存公開物の上書き拒否')
    # ----------------------------------------
    # CLIの一目的読取はPath.read_bytesを局所計測し、実ファイルは合成JSONだけにする。
    fixturepath=HERE/'report_fixture_v4_入力合成.json';fixturepath.write_bytes(raw)
    cliout=HERE/'report_fixture_v4_CLI一読';oldargv=list(sys.argv);original=Path.read_bytes;reads=[]
    def tracked(path: Path) -> bytes:
        """
        機能: 人工CLIの入力ファイルだけ読取回数を記録する。
        引数: path(Path)はPythonが読むファイル位置。
        返り値: bytesは元の読取結果。
        """
        if path.resolve()==fixturepath.resolve():reads.append(path)
        return original(path)
    try:
        Path.read_bytes=tracked
        sys.argv=[str(SOURCE),'--result',str(fixturepath),'--expected-sha256','0'*64,'--output',str(cliout)]
        rejected(R.main,'完成SHA不一致は生成前に拒否')
        check(len(reads)==1 and not cliout.exists(),'SHA不一致でも入力一読だけ')
        reads.clear();sys.argv=[str(SOURCE),'--result',str(fixturepath),'--expected-sha256',R.digest(raw),'--output',str(cliout),'--fixture']
        R.main();check(len(reads)==1,'CLI結果本文は一目的一読')
    finally:
        Path.read_bytes=original;sys.argv=oldargv
    source={p.name:R.digest(p.read_bytes()) for p in (SOURCE,Path(__file__))}
    result=dict(全合格=True,scope='完全合成の四十場・固定五候補。実結果未読の表示/集計/一読SHAガード検査。',検査数=COUNT,検査合計=sum(COUNT.values()),
        source_SHA256=source,生成人工=proof,実結果本文読取=0,市場読取=0,原入力=0,大型台帳=0,新金融再生=0,API=0,
        制約=['実際のランキングの選択期分離、約定、親P/Lの正当性は根の金融監査へ委譲。','計画/全結果リンクは正式00119配置に合わせ、公開後に実在確認する。','合成検査の成功を収益性の成功へ数えない。'])
    target.write_bytes(R.json_bytes(result));print('公開生成人工合格',sum(COUNT.values()),R.digest(target.read_bytes()),flush=True)


if __name__=='__main__':
    main()
