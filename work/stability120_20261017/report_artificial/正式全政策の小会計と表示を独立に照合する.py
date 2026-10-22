"""120bの自己保全copyだけで、公開小会計・全表・参考順位を独立足算する。"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics

from bs4 import BeautifulSoup


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
PUBLIC=BASE/'private/public'
EXPECTED='c99743d739c9d24a08088f1b5ebdc78af8285b19e9704773965ea05f13890ce1'
NAME='段階トレーリングと利益玉返済の説明と全セッション損益.html'
SYMBOLS=('TOPIX','NK225')
FAMILIES=('HEDGE','NET','FLIP','RECYCLE','HARD','FIXED','ONCE','ALLSIDE')
COUNTS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 正式小会計の一致を記録し、不一致を停止する。
    引数: value(bool)は期待、label(str)は検査名。
    返り値: None。経済源・公開ファイルは変更しない。
    """
    assert value,label
    COUNTS[label]+=1


def near(a: float|None,b: float|None) -> bool:
    """
    機能: 未評価nullを零へ変換せず、保存金額の微小集計差だけを許す。
    引数: a/b(float|None)は比較値。
    返り値: boolは同値。実金額を丸める操作ではない。
    """
    return a is b if a is None or b is None else math.isclose(a,b,rel_tol=0,abs_tol=1e-5)


def fmt(value: float|None,signed: bool=False) -> str:
    """
    機能: 表の期待文字列を生成器と独立に作る。
    引数: value(float|None)、signed(bool)は値と符号指定。
    返り値: strは表示円額又は—。
    """
    if value is None:return '—'
    if abs(value)<=1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 元小会計の完結玉損益と全玉時価を独立に集計する。
    引数: rows(list[dict])は一政策・一商品の四十場。
    返り値: dictは比較に使用する全指標。約定やNPZの再計算ではない。
    """
    gains=[r['net'] for r in rows if not r['unclosed'] and r['entries'] and r['net']>1e-7]
    losses=[-r['net'] for r in rows if not r['unclosed'] and r['entries'] and r['net']<-1e-7]
    unfinished=sum(r['unclosed']>0 for r in rows);inactive=sum(not r['entries'] and not r['unclosed'] for r in rows)
    flat=sum(not r['unclosed'] and r['entries'] and abs(r['net'])<=1e-7 for r in rows)
    nets=[r['net'] for r in rows];median=statistics.median(nets);meanabs=statistics.mean(abs(v) for v in nets)
    m={k:sum(r[k] for r in rows) for k in ('profit','loss','net','realized_net','fees','closed_lots','wins','losses','entries','forced_loss','forced_profit','trail_net','long_net','short_net')}
    m.update(sessions=len(rows),black=len(gains),red=len(losses),inactive=inactive,flat=flat,unclosed_sessions=unfinished,
        terminal_unclosed_lots=sum(r['unclosed'] for r in rows),mean=statistics.mean(nets),median=median,worst=min(nets),
        top3_removed=None if unfinished else sum(nets)-sum(sorted(gains,reverse=True)[:3]),share=m['profit']/(m['profit']+m['loss']) if m['profit']+m['loss']>1e-7 else None,
        normalized_median=median/meanabs if meanabs>1e-7 else None,mean_black=statistics.mean(gains) if gains else None,
        worst_to_mean_black=max(losses,default=0)/statistics.mean(gains) if gains else None,min_session_equity=min(r['min_equity'] for r in rows),max_session_drawdown=max(r['max_drawdown'] for r in rows),
        max_long=max(r['max_long'] for r in rows),max_short=max(r['max_short'] for r in rows),all_positive=len(gains)==len(rows) and not unfinished)
    check(len(gains)+len(losses)+inactive+flat+unfinished==40,'全場は黒赤無零未返済に分離')
    return m


def cells(m: dict) -> list[str]:
    """
    機能: 主比較表の期待セルを独立集計から作る。
    引数: m(dict)は一商品指標。
    返り値: list[str]は金額・場数等の表示文字列。
    """
    return [fmt(m['net'],True),f"{m['black']}/{m['red']}/{m['inactive']}",fmt(m['mean'],True),fmt(m['median'],True),fmt(m['worst'],True),fmt(m['top3_removed'],True),fmt(m['fees']),fmt(m['min_session_equity'],True),str(m['unclosed_sessions'])]


def main() -> None:
    """
    機能: 正式3840小会計・1920場行・全合計と固定順位を照合する。
    引数: なし。原結果は再読せず、同bytes私有copy一読だけを用いる。
    返り値: None。私有証跡と小集計を新規保存する。
    """
    target=HERE/'正式3840商品場の玉会計と全表示及び順位の独立照合.json';smallpath=BASE/'private/全四十八政策の商品別小集計.json'
    assert not target.exists() and not smallpath.exists()
    copy=BASE/'private/received/段階トレーリングと利益玉部分返済の全四十場.json';payload=copy.read_bytes()
    check(hashlib.sha256(payload).hexdigest()==EXPECTED,'自身保全copyは120b完成指定SHA')
    source=json.loads(payload);names=(NAME,'data.json','README.md','生成証跡.json');publicraw={k:(PUBLIC/k).read_bytes() for k in names}
    data=json.loads(publicraw['data.json']);generated=json.loads(publicraw['生成証跡.json']);page=BeautifulSoup(publicraw[NAME].decode('utf8'),'html.parser')
    check(generated['passed'] and generated['fixture'] is False and data['fixture'] is False and generated['result_sha256']==data['source_SHA256']==EXPECTED,'合成と途中停止版を完成結果へ混ぜない')
    check(source['financial_accounts']==generated['symbol_sessions']==3840 and source['reused_input_reads']==80,'120b完成の3840新会計だけを掲載')
    check(source['source_SHA256']==data['economic_source_SHA256'] and any('engine120b.py' in k for k in source['source_SHA256']) and any('run120b.py' in k for k in source['source_SHA256']),'修正版bの源を公開会計へ結合')
    check(source['cache']==data['cache'] and len(data['cache'])==80 and all('/recovery_b/measurement/' in c['path'] for c in data['cache']),'完成bの80台帳参照だけを保存')
    for name,value in generated['artifacts'].items():check(hashlib.sha256(publicraw[name]).hexdigest()==value,'正式生成物のSHA一致')
    for key in ('order_columns','lot_columns','curve_columns'):check(data['artifact_columns'][key]==source[key],'保存列名の結合と原台帳未読')
    specs={s['id']:s for s in source['specs']};scenes=source['sessions'];cases=data['cases']
    check(len(specs)==len(cases)==generated['policies']==48 and len(scenes)==40 and scenes==data['sessions'],'全48条件と40場を保持')
    rows={(r['method'],r['session'],r['symbol']):r for r in source['runs']};check(len(rows)==len(source['runs'])==3840,'元商品場キーの一意性')
    metrics={};ranking=[]
    for index,(ident,spec) in enumerate(specs.items()):
        case=cases[ident];check(case['spec']==spec and case['policy_index']==index,'元仕様とNPZ政策indexを保存')
        check(case['rows']==[rows[ident,s,symbol] for s in scenes for symbol in SYMBOLS],'全3840商品場の元小会計を同値転載')
        metrics[ident]={}
        for symbol in SYMBOLS:
            rr=[rows[ident,s,symbol] for s in scenes];m=aggregate(rr);metrics[ident][symbol]=m
            for k,v in m.items():check(near(case['metrics'][symbol][k],v),'商品別の金額と安定性を独立足算')
            check(near(m['profit']-m['loss'],m['realized_net']) and near(m['long_net']+m['short_net'],m['realized_net']),'完結1枚玉のP/Lと方向別和は確定損益')
            if not m['unclosed_sessions']:check(near(m['net'],m['realized_net']),'終端フラットだけ確定と時価が一致')
        values=list(metrics[ident].values());norm=[m['normalized_median'] for m in values];risk=[m['worst_to_mean_black'] for m in values]
        qualified=all(m['net']>1e-7 and m['median']>1e-7 and m['top3_removed'] is not None and m['top3_removed']>1e-7 and not m['unclosed_sessions'] for m in values)
        ranking.append(dict(id=ident,family=FAMILIES[spec['mode']],qualified=qualified,min_black=min(m['black'] for m in values),min_normalized_median=min(norm) if all(v is not None for v in norm) else None,max_worst_to_mean_black=max(risk) if all(v is not None for v in risk) else None))
    ranking.sort(key=lambda r:(not r['qualified'],-r['min_black'],-r['min_normalized_median'] if r['min_normalized_median'] is not None else math.inf,r['max_worst_to_mean_black'] if r['max_worst_to_mean_black'] is not None else math.inf,r['id']))
    check(ranking==data['common_ranking'],'結果を変える選別なしの両商品共通順位')
    main=[];seen=set()
    for r in ranking:
        if r['family'] not in seen:main.append(r['id']);seen.add(r['family'])
        if len(main)==3:break
    check(main==data['main_ids']==generated['main_ids'],'上位は異なる系統最大3の固定算式')
    check(data['qualification_count']==sum(r['qualified'] for r in ranking),'参考比較資格の独立判定')
    check(data['all40_positive_count']==sum(all(metrics[r['id']][s]['all_positive'] for s in SYMBOLS) for r in ranking),'無取引を毎場黒字へ数えない')
    tables=page.select('table.sessions');check(len(tables)==48 and len(page.select('#policy option'))==48,'全政策選択肢と全48表')
    for table in tables:
        ident=table['data-method'];trs=table.select('tbody tr');check(len(trs)==40,'全40場の表示省略なし')
        for tr,scene in zip(trs,scenes):
            expected=[]
            for symbol in SYMBOLS:
                r=rows[ident,scene,symbol];expected.extend([fmt(r['profit']),fmt(r['loss']),fmt(r['realized_net'],True),fmt(r['net'],True),fmt(r['fees']),str(int(r['closed_lots'])),str(int(r['unclosed'])),f"{int(r['max_long'])}/{int(r['max_short'])}"])
            check(tr['data-session']==scene and [td.get_text(strip=True) for td in tr.select('td')]==expected,'正式3840商品場の全16セルを表示')
        expected=[]
        for symbol in SYMBOLS:
            m=metrics[ident][symbol];expected.extend([fmt(m['profit']),fmt(m['loss']),fmt(m['realized_net'],True),fmt(m['net'],True),fmt(m['fees']),str(int(m['closed_lots'])),str(int(m['terminal_unclosed_lots'])),f"{int(m['max_long'])}/{int(m['max_short'])}"])
        check([td.get_text(strip=True) for td in table.select('tfoot td')]==expected,'全場合計は損益足算と実最大保有を区別')
    metrics_tables=page.select('table.metrics');check(len(metrics_tables)==2,'主候補と全政策比較表を分離')
    for table,ids in zip(metrics_tables,(main,[r['id'] for r in ranking])):
        trs=table.select('tbody tr');check(len(trs)==len(ids)*2,'比較表の両商品を省略しない')
        for tr,(ident,symbol) in zip(trs,[(i,s) for i in ids for s in SYMBOLS]):
            state='比較資格あり' if next(r['qualified'] for r in ranking if r['id']==ident) else '未達・参考'
            check([td.get_text(strip=True) for td in tr.select('td')]==[state,symbol,*cells(metrics[ident][symbol])],'主表と全政策表の安定指標を独立表示')
    text=page.get_text(' ',strip=True)
    check('完結1枚玉' in text and '確定収支＝利益−損失' in text and '次正常原行のBBOで損失になれば実損失' in text,'玉母集団と返済悪化の説明')
    check('未知検証の成功ではありません' in text and '実小型板・待ち順位・真受信時刻は未取得' in text,'既知開発と実小型約定未証明の説明')
    for element in page.select('[href],[src]'):
        link=element.get('href',element.get('src'));check(':' not in link,'外部通信なし')
        check(page.find(id=link[1:]) is not None if link.startswith('#') else (PUBLIC/link).exists(),'全案内と政策アンカーが実在')
    small=dict(source_SHA256=EXPECTED,scope='120b全48政策×両商品×既知40場の小会計再集計。金融の再実行や原NPZ監査ではない。',main_ids=main,qualification_count=data['qualification_count'],cases=[dict(id=r['id'],family=r['family'],qualified=r['qualified'],metrics=metrics[r['id']]) for r in ranking])
    smallpath.write_text(json.dumps(small,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    proof=dict(passed=True,scope='120b保存小会計とHTMLの全数表示照合。注文約定・原NPZ・金融核心の再監査ではない。',counts=dict(COUNTS),total_checks=sum(COUNTS.values()),result_sha256=EXPECTED,
        artifacts={k:hashlib.sha256(v).hexdigest() for k,v in publicraw.items()},source_SHA256=source['source_SHA256'],stats_path=smallpath.relative_to(ROOT).as_posix(),stats_sha256=hashlib.sha256(smallpath.read_bytes()).hexdigest(),original_result_additional_reads=0,own_copy_reads=1,NPZ_reads=0,market_reads=0,financial_replay=0,API=0)
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),proof_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),stats_sha256=proof['stats_sha256'],main=[dict(id=i,metrics=metrics[i]) for i in main]),ensure_ascii=False))


if __name__=='__main__':
    main()
