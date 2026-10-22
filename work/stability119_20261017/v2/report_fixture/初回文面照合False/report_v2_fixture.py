"""原因対照レポートの共通順位と全場表示を、実結果未読の合成会計だけで検査する。"""

from copy import deepcopy
from datetime import date,timedelta
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup

import report_v2 as R

HERE=Path(__file__).resolve().parent
COUNTS={}


def check(value: bool,label: str) -> None:
    """
    機能: 合成上の独立期待値を照合して件数を残す。
    引数: value(bool)は期待条件、label(str)は検査名。
    返り値: None。不一致時にAssertionErrorを送出する。
    """
    assert value,label
    COUNTS[label]=COUNTS.get(label,0)+1


def fixture() -> dict:
    """
    機能: 日付・損益とも実市場と無関係な三十六条件・四十場を作る。
    引数: なし。
    返り値: dictは完成予定schema。金融エンジンを呼ばない。
    """
    sessions=[str(date(2031,1,1)+timedelta(days=i//2))+('_Day' if i%2==0 else '_Night') for i in range(40)]
    specs=[]
    for f in range(4):
        for length in (20,40):
            for xm in (5,4):
                for pm in (0,3):
                    ident=f'F{f}_L{length}_X{xm}_P{pm}'
                    specs.append(dict(id=ident,family='F'+str(f),name='合成の復帰確認'+str(f),
                        description='過去の進行後に停止と復帰を別の観測で確認して入ります。',
                        exit_mode=xm,execution_mode=pm,guard=2))
    specs.extend(dict(id=v,family='商品別旧候補',name='合成の旧入口対照',description='商品別の旧入口を保持します。',
                      exit_mode=0,execution_mode=i,guard=1) for i,v in enumerate(R.BASELINES))
    runs=[]
    for k,spec in enumerate(specs):
        for i,scene in enumerate(sessions):
            for s,symbol in enumerate(R.SYMBOLS):
                if k>=32:net=1000000.
                elif i<22+k%8:net=100.+k
                else:net=-40.-s*10
                gain=max(net,0);loss=max(-net,0)
                runs.append(dict(method=spec['id'],session=scene,symbol=symbol,
                    net=net,realized=net,profit=gain,loss=loss,parents=1,wins=int(net>0),losses=int(net<0),
                    closed_quantity=10 if symbol=='TOPIX' else 20,fees=836. if symbol=='TOPIX' else 440.,
                    unclosed=0,max_drawdown=100.,canceled=0,fills=2,halted=0,
                    protected_fallbacks=0,protected_wait_rows=0,rejected_entries=0))
    return dict(sessions=sessions,splits={'全40':sessions,'確認13':sessions[27:],'追加確認3':sessions[37:]},
        specs=specs,runs=runs,episodes=[],cache=[],source_SHA256={'合成源':'a'*64},
        old_primary={'TOPIX':'合成TOP旧入口','NK225':'合成NK旧入口'},reads=[])


def reject(call: object,label: str) -> None:
    """
    機能: 不完全な結果がゼロ補完又は成功に変換されず拒否されることを確認する。
    引数: call(Callable[[],object])は合成呼出、label(str)は検査名。
    返り値: None。
    """
    try:call()
    except (AssertionError,KeyError,ValueError):check(True,label)
    else:raise AssertionError(label)


def inspect(data: dict,folder: Path) -> dict:
    """
    機能: 生成HTMLの全表を合成会計の金額・場数・未返済へ直接照合する。
    引数: data(dict)は合成元、folder(Path)は人工専用生成先。
    返り値: dictは生成した全三十六公開小会計。
    """
    p=json.loads((folder/'data.json').read_text(encoding='utf8'))
    page=BeautifulSoup((folder/R.HTML_NAME).read_text(encoding='utf8'),'html.parser')
    check(len(p['common_ranking'])==32 and all(not r['id'].startswith('BASELINE') for r in p['common_ranking']),'旧商品別入口は共通順位対象外')
    check(len(p['main_ids'])<=3 and len({p['cases'][i]['spec']['family'] for i in p['main_ids']})==len(p['main_ids']),'主は最大三つの異家族')
    check(len(p['cases'])==36,'全三十六の小会計を残す')
    source={(v['method'],v['session'],v['symbol']):v for v in data['runs']}
    for table in page.select('table.sessions'):
        ident=table['data-method'];rows=table.select('tbody tr');check(len(rows)==40,'全条件の四十行掲載')
        for tr,scene in zip(rows,data['sessions']):
            values=[v.get_text(strip=True) for v in tr.select('td')];expected=[]
            for symbol in R.SYMBOLS:
                r=source[ident,scene,symbol]
                expected.extend([f"{r['profit']:,.0f}",f"{r['loss']:,.0f}",f"{r['net']:+,.0f}" if r['net'] else '0',str(r['parents']),f"{r['fees']:,.0f}",str(r['unclosed'])])
            check(values==expected,'全掲載金額親数料金未返済')
        expected=[]
        for symbol in R.SYMBOLS:
            rr=[source[ident,scene,symbol] for scene in data['sessions']];net=sum(r['net'] for r in rr)
            expected.extend([f"{sum(r['profit'] for r in rr):,.0f}",f"{sum(r['loss'] for r in rr):,.0f}",f"{net:+,.0f}" if net else '0',str(sum(r['parents'] for r in rr)),f"{sum(r['fees'] for r in rr):,.0f}",str(sum(r['unclosed']!=0 for r in rr))+'場'])
        check([v.get_text(strip=True) for v in table.select('tfoot td')]==expected,'全場合計の独立足算')
    for ident,case in p['cases'].items():
        check(len(case['rows'])==80,'各条件両商品八十行')
        for symbol in R.SYMBOLS:
            rr=[source[ident,s,symbol] for s in data['sessions']];net=[v['net'] for v in rr];m=case['metrics'][symbol]
            positive=[v for v in net if v>0]
            check(m['net']==sum(net) and m['top3_removed']==sum(net)-sum(sorted(positive,reverse=True)[:3]),'上位三黒字除外の独立計算')
            check(m['mean_abs_net']==sum(abs(v) for v in net)/40,'正規化分母は全四十平均絶対net')
    check('未知検証ではありません' in page.get_text(' ',strip=True),'既知開発と未知成功の分離')
    check('共通順位に入れません' in page.get_text(' ',strip=True),'BASELINE除外理由の表示')
    check('実小型板' in (folder/'README.md').read_text(encoding='utf8'),'実約定の留保')
    check(not page.select('script[src]') and not page.select('img[src]'),'外部通信資産なし')
    return p


def main() -> None:
    """
    機能: 実結果未読で、順位・全表示・同bytes保全の合成検査を一回実行する。
    引数: なし。
    返り値: Noneは人工証跡。新金融・原市場・大型台帳を読まない。
    """
    target=HERE/'report_fixture/共通規則順位と全三十六条件の純表示検査.json';check(not target.exists(),'純人工の上書き禁止')
    data=fixture();raw=R.encoded(data);folder=HERE/'report_fixture/public'
    proof=R.generate(data,folder,R.sha(raw),'合成だけ/原因対照.json',fixture=True);public=inspect(data,folder)
    # ----------------------------------------
    # 日経の円額だけを倍率変更しても、順位と主規則は変わらない。
    changed=deepcopy(data)
    for row in changed['runs']:
        if row['symbol']=='NK225':
            for key in R.MONEY:row[key]*=1000000
    _,scaled,_=R.render(changed,'b'*64,'完全合成')
    check([v['id'] for v in scaled['common_ranking']]==[v['id'] for v in public['common_ranking']],'円倍率の違いで共通順位を変えない')
    check(scaled['main_ids']==public['main_ids'],'円倍率の違いで主家族を変えない')
    # 未達・未清算・無取引を全て別に扱う。
    failed=deepcopy(data)
    for row in failed['runs']:
        row.update(net=0.,realized=0.,profit=0.,loss=0.,parents=0,wins=0,losses=0,closed_quantity=0,fees=0.,fills=0)
    last=failed['runs'][0];last.update(net=100000.,unclosed=10,fills=1,fees=41.)
    doc,f,_=R.render(failed,'c'*64,'完全合成')
    check(f['qualification_count']==0 and '<strong>毎セッションの安定黒字は未達です。</strong>' in doc,'資格なしの太字未達表示')
    v=f['cases'][last['method']]['metrics']['TOPIX'];check(v['unclosed_sessions']==1 and v['black']==0 and v['inactive']==39 and v['top3_removed'] is None,'無取引と未清算評価益を勝ちにしない')
    bad=deepcopy(data);bad['runs'].pop();reject(lambda:R.validate(bad),'欠場をゼロ補完しない')
    bad=deepcopy(data);bad['runs'][0]['net']+=1;reject(lambda:R.validate(bad),'親P/Lと場netの不一致を拒否')
    reject(lambda:R.generate(data,folder,R.sha(raw),'合成',True),'既存公開フォルダを上書きしない')
    # ----------------------------------------
    # 指定SHAの一読と自分copyをCLIだけで確認する。
    source=HERE/'report_fixture/入力は完全合成.json';source.write_bytes(raw)
    received=HERE/'report_fixture/received';out=HERE/'report_fixture/cli_public'
    original=Path.read_bytes;argv=list(sys.argv);reads=[]
    def tracked(path: Path) -> bytes:
        """
        機能: 合成の原結果位置だけ一読を計数する。
        引数: path(Path)は読取対象。
        返り値: bytesは元の読取結果。
        """
        if path.resolve()==source.resolve():reads.append(path)
        return original(path)
    try:
        Path.read_bytes=tracked
        sys.argv=[str(HERE/'report_v2.py'),'--result',str(source),'--expected-sha256','0'*64,'--output',str(out),'--received',str(received),'--fixture']
        reject(R.main,'原結果SHA不一致で生成しない')
        check(len(reads)==1 and not out.exists() and not received.exists(),'SHA不一致で保全先も作らない')
        reads.clear();sys.argv[4]=R.sha(raw);R.main()
        check(len(reads)==1,'指定原結果の一目的一読')
    finally:Path.read_bytes=original;sys.argv=argv
    check((received/source.name).read_bytes()==raw,'自身copyは完全同bytes')
    receipt=json.loads((received/'一読と同bytes保全.json').read_text(encoding='utf8'));check(receipt['source_reads']==1 and receipt['fixture'],'一読保全証跡')
    result=dict(passed=True,scope='実結果未読。三十六条件四十場の完全合成会計、共通順位、未達表示、全掲載、一読とcopy。',
        counts=COUNTS,total_checks=sum(COUNTS.values()),fixture_generation=proof,
        source_SHA256={p.name:R.sha(p.read_bytes()) for p in (HERE/'report_v2.py',Path(__file__))},
        actual_result_reads=0,market_reads=0,financial_replay=0,large_ledger_reads=0,API=0)
    target.write_bytes(R.encoded(result));print('v2公開純人工合格',sum(COUNTS.values()),R.sha(target.read_bytes()),flush=True)


if __name__=='__main__':main()
