"""公開された非金融集計を一読し、場別件数・率と表示を独立再加算する。"""

import argparse
from fractions import Fraction
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00114_公表活動と表示数量の維持後の価格応答'
JSON_PATH=PUBLIC/'数量後の価格応答の公開集計.json'
HTML_PATH=PUBLIC/'表示数量を観測した後の方向応答.html'
EXPECTED='aad49e1186468c8bf069a902126c2f70d6f74a311bfe8ae03ef0978d99325d05'
PLAN=HERE/'公開非金融集計と表示の一読監査計画.json'
KEYS=('n','plus','minus','unknown','eof','window_end','resolved')
GROUPS=('type0_all','type0_reached','type1_all','type1_decreased','type1_maintained','type1_never_below','type1_recovered')
CHECKS=0


def sha(path: Path) -> str:
    """
    機能: 源又は私有小証跡を指紋へ束縛する。
    引数: path(Path)は源又は私有生成物。公開本文の別hashには使わない。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict:
    """
    機能: 修正版の計測五源をsourceだけで固定する。
    引数: なし。
    返り値: dictは五つの相対path/SHA。
    """
    return {(BASE/n).relative_to(ROOT).as_posix():sha(BASE/n) for n in ('plan.py','run.py','engine.py','artificial_engine.py','artificial_run.py')}


def save(path: Path,value: dict) -> None:
    """
    機能: 自所有の成功/False/計画を上書きせず保存する。
    引数: path(Path)、value(dict)は新保存先と内容。
    返り値: None。金融や公開を書き換えない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def equal(value: object,expected: object) -> None:
    """
    機能: 率を独立分数で照合し、None/bool/整数の取り違えを拒否する。
    引数: value/expected(object)は同じ意味の保存値と期待値。
    返り値: None。検査葉の数を記録する。
    """
    global CHECKS
    if isinstance(expected,dict):
        assert set(value)==set(expected)
        for k,v in expected.items():equal(value[k],v)
    elif isinstance(expected,list):
        assert len(value)==len(expected)
        for a,b in zip(value,expected):equal(a,b)
    elif expected is None or isinstance(expected,bool):assert value is expected;CHECKS+=1
    elif isinstance(expected,(int,Fraction,float)):
        assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
        assert abs(float(value)-float(expected))<=max(1e-12,abs(float(expected))*1e-12),(value,expected)
        CHECKS+=1
    else:assert value==expected;CHECKS+=1


def check_group(g: dict) -> None:
    """
    機能: 一群の全分母と先着/打切の排他内訳を確認する。
    引数: g(dict)は保存された一群。
    返り値: None。未解決を勝ち負けへ補完しない。
    """
    for key in KEYS:assert type(g[key]) is int and g[key]>=0
    equal(g['n'],sum(g[k] for k in ('plus','minus','unknown','eof','window_end')))
    equal(g['resolved'],g['plus']+g['minus'])
    equal(g['rate'],Fraction(g['plus'],g['resolved']) if g['resolved'] else None)
    for key in ('median_opposite_q0','median_quantity_ratio','median_minimum_quantity_ratio','median_total_volume','median_npositive'):
        if g['n']==0:equal(g[key],None)
        else:assert isinstance(g[key],(int,float)) and math.isfinite(g[key]) and g[key]>=0


def groups(g: dict) -> None:
    """
    機能: 主七群と方向/幅の排他分解・同episode同値を確認する。
    引数: g(dict)は一口座のgroups。
    返り値: None。中央値はこのphaseでは再加算しない。
    """
    for name in GROUPS:
        check_group(g[name])
        for side in ('buy','sell'):check_group(g['by_side'][side][name])
        for spread in ('one','wider','narrower'):check_group(g['by_spread'][spread][name])
        for k in KEYS:
            equal(g[name][k],sum(g['by_side'][s][name][k] for s in ('buy','sell')))
            equal(g[name][k],sum(g['by_spread'][s][name][k] for s in ('one','wider','narrower')))
    for k in KEYS:
        equal(g['type1_all'][k],g['type1_decreased'][k]+g['type1_maintained'][k])
        equal(g['type1_maintained'][k],g['type1_never_below'][k]+g['type1_recovered'][k])
    for scope in (g,*g['by_side'].values(),*g['by_spread'].values()):
        for k in (*KEYS,'rate'):equal(scope['type0_reached'][k],scope['type1_all'][k])
    equal(g['paired_same_bbo_equal'],True)


class Tables(HTMLParser):
    """HTMLの四つの表からtd文字列だけを抽出する。JavaScript/通信は実行しない。"""
    def __init__(self):
        """
        機能: 表抽出の初期状態を作る。
        引数: なし。
        返り値: None。
        """
        super().__init__();self.tables=[];self.rows=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        """
        機能: table/tr/tdの構造を追う。
        引数: tag(str)、attrs(list[tuple])はHTML開始タグ。
        返り値: None。
        """
        if tag=='table':self.rows=[]
        elif tag=='tr' and self.rows is not None:self.row=[]
        elif tag=='td' and self.row is not None:self.cell=[]
    def handle_data(self,data):
        """
        機能: セルの可視文字を収集する。
        引数: data(str)はHTMLテキスト。
        返り値: None。
        """
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        """
        機能: 完成セル/行/表を格納する。
        引数: tag(str)は終了タグ。
        返り値: None。
        """
        if tag=='td' and self.cell is not None:self.row.append(''.join(self.cell).strip());self.cell=None
        elif tag=='tr' and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None
        elif tag=='table' and self.rows is not None:self.tables.append(self.rows);self.rows=None


def cell(g: dict) -> str:
    """
    機能: 独立再計算した分子/分母と先着率から期待表示を作る。
    引数: g(dict)は件数検算済み群。
    返り値: strは期待td文字列。対象reportの関数を呼ばない。
    """
    rate=Fraction(g['plus'],g['resolved']) if g['resolved'] else None
    percent='未定義' if rate is None else f'{float(rate)*100:.1f}%'
    return f"{percent} {g['plus']:,}/{g['resolved']:,}全{g['n']:,}・価格不明{g['unknown']:,}・窓終了{g['window_end']:,}・保存末尾{g['eof']:,}"


def audit(value: dict,html: str) -> dict:
    """
    機能: 33×2小集計と全期間を独立再加算し、HTML表と非金融表示を照合する。
    引数: value(dict)、html(str)は一読済み公開同bytes。
    返り値: dictは独立再集計の要約。
    """
    equal(value['全合格'],True);equal(value['金融'],False);equal(value['source開始終端一致'],True);equal(value['source_SHA256'],sources())
    sessions=value['sessions'];rows=value['rows'];assert len(sessions)==len(set(sessions))==33 and len(rows)==66
    assert {(r['session'],r['symbol']) for r in rows}=={(s,p) for s in sessions for p in ('TOPIX','NK225')}
    for k in ('NPZ本文','同bytesSHA検算','測定口座'):equal(value['counts'][k],66)
    for k in ('原板','足','旧金融','新金融','API','追加二場本文'):equal(value['counts'][k],0)
    equal(value['前版の資格検査停止']['NPZ本文'],1);equal(value['前版の資格検査停止']['測定口座'],0)
    for row in rows:
        groups(row['groups']);c=row['counts'];equal(c['raw_rows'],row['raw_rows'])
        equal(c['price_known_rows']+c['price_unknown_rows'],c['raw_rows'])
        equal(c['positive_episodes'],sum(c[k] for k in ('direction_buy_episodes','direction_sell_episodes','direction_zero_inside_episodes','direction_zero_last_unknown_episodes')))
        equal(c['episodes'],c['positive_episodes']+c['no_positive_episodes'])
        equal(c['episodes'],sum(c[k] for k in ('episode_end_price_unknown','episode_end_quantity_unknown','episode_end_volume_unknown','episode_end_bbo_change','episode_end_eof')))
        equal(c['type0_events'],c['direction_buy_episodes']+c['direction_sell_episodes'])
        equal(c['type0_events'],row['groups']['type0_all']['n']);equal(c['type1_events'],row['groups']['type1_all']['n'])
        equal(row['events']['n'],c['type0_events']+c['type1_events'])
        union=c['volume_unknown_rows'];a=c['volume_flag_unknown_rows'];b=c['volume_observed_invalid_rows']
        assert max(a,b)<=union<=a+b
        for code,label in (('1','plus'),('-1','minus'),('2','eof')):
            equal(c['outcome_counts'][code],sum(row['groups'][g][label] for g in ('type0_all','type1_all')))
        equal(c['outcome_counts']['0'],sum(row['groups'][g]['unknown']+row['groups'][g]['window_end'] for g in ('type0_all','type1_all')))
    computed={};comparison={}
    for symbol in ('TOPIX','NK225'):
        computed[symbol]={}
        own=[r for r in rows if r['symbol']==symbol]
        for period in ('all','Day','Night'):
            selected=[r for r in own if period=='all' or r['session'].endswith('_'+period)]
            agg={}
            for name in GROUPS:
                gs=[r['groups'][name] for r in selected];a={k:sum(g[k] for g in gs) for k in KEYS}
                rates=[Fraction(g['plus'],g['resolved']) for g in gs if g['resolved']]
                a.update(rate=Fraction(a['plus'],a['resolved']) if a['resolved'] else None,
                    active_sessions=sum(g['n']>0 for g in gs),mean_session_rate=sum(rates,Fraction())/len(rates) if rates else None,
                    min_session_rate=min(rates) if rates else None,max_session_rate=max(rates) if rates else None)
                equal(value['totals'][symbol][period]['groups'][name],a)
                agg[name]={k:float(v) if isinstance(v,Fraction) else v for k,v in a.items()}
            equal(value['totals'][symbol][period]['sessions'],len(selected));computed[symbol][period]=dict(sessions=len(selected),groups=agg)
        pairs=[(Fraction(r['groups']['type1_decreased']['plus'],r['groups']['type1_decreased']['resolved']),
                Fraction(r['groups']['type1_maintained']['plus'],r['groups']['type1_maintained']['resolved']))
               for r in own if r['groups']['type1_decreased']['resolved'] and r['groups']['type1_maintained']['resolved']]
        comparison[symbol]=dict(比較可能=len(pairs),減少が高い=sum(a>b for a,b in pairs),維持が高い=sum(a<b for a,b in pairs),同率=sum(a==b for a,b in pairs))
    parser=Tables();parser.feed(html);tables=parser.tables;assert [len(t) for t in tables]==[6,6,33,4]
    names=('type0_all','type1_all','type1_decreased','type1_maintained','type1_never_below','type1_recovered')
    for i,symbol in enumerate(('TOPIX','NK225')):
        for j,name in enumerate(names):equal(tables[i][j][1],cell(computed[symbol]['all']['groups'][name]))
    lookup={(r['session'],r['symbol']):r for r in rows}
    for i,s in enumerate(sessions):
        equal(tables[2][i][0],s.replace('_Day',' デイ').replace('_Night',' ナイト'))
        for j,(symbol,name) in enumerate((s,g) for s in ('TOPIX','NK225') for g in ('type1_decreased','type1_maintained')):
            equal(tables[2][i][j+1],cell(lookup[s,symbol]['groups'][name]))
    for i,(symbol,period) in enumerate((s,p) for s in ('TOPIX','NK225') for p in ('Day','Night')):
        equal(tables[3][i][0],symbol+' '+period)
        for j,name in enumerate(('type1_decreased','type1_maintained')):equal(tables[3][i][j+1],cell(computed[symbol][period]['groups'][name]))
    for text in ('これは売買成績ではありません','利益・費用回収・真の補充は未測定','公表出来高は全価格の合計','独立ではありません','ミニ／マイクロの実気配・手数料後黒字とは別','追加2場、テクニカル水準、相手市場の板は今回未測定'):
        assert text in html
    return dict(全合格=True,集計口座=66,全場=33,算術表示項目=CHECKS,再集計=computed,場別二群比較=comparison,
        scope='保存群を独立再加算したphase1。events分類/中央値/terminalの追加確認は別目的の出力66一読phase2。')


def prepare() -> None:
    """
    機能: 本文前に公開JSON/HTMLの目的・stat・同bytesSHA照合を固定する。
    引数: なし。
    返り値: None。結果本文は0。
    """
    assert JSON_PATH.stat().st_size==1632263 and HTML_PATH.stat().st_size==21097
    save(PLAN,dict(目的='33×2数量群/方向/幅/昼夜/各終点を独立Integer/Fractionで加算し、1Tを利益にしないHTML表を確認する。',
        JSON=dict(path=JSON_PATH.relative_to(ROOT).as_posix(),bytes=1632263,SHA256=EXPECTED,本文一読=1),
        HTML=dict(path=HTML_PATH.relative_to(ROOT).as_posix(),bytes=21097,root指定SHA接頭='3c568',本文一読=1),
        source_SHA256=sources(),監査source_SHA256=sha(Path(__file__)),原NPZ=0,新金融=0,API=0))
    print(json.dumps(dict(prepared=True,plan_SHA256=sha(PLAN),結果本文=0),ensure_ascii=False))


def main() -> None:
    """
    機能: 指定公開2資料を各一読して先に私有保存し、成功/Falseと次読取目録を保存する。
    引数: CLI --prepare/--run(bool)は事前固定と一回監査。
    返り値: None。元測定結果/原NPZ/金融は読まない。
    """
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.prepare:prepare();return
    plan=json.loads(PLAN.read_text(encoding='utf-8'));assert plan['source_SHA256']==sources() and plan['監査source_SHA256']==sha(Path(__file__))
    try:
        raw=JSON_PATH.read_bytes();assert len(raw)==plan['JSON']['bytes'] and hashlib.sha256(raw).hexdigest()==EXPECTED
        copy=HERE/'公開結果の同bytes私有コピー.json';assert not copy.exists();copy.write_bytes(raw);value=json.loads(raw.decode('utf-8'))
        html_raw=HTML_PATH.read_bytes();html_sha=hashlib.sha256(html_raw).hexdigest();assert len(html_raw)==plan['HTML']['bytes'] and html_sha.startswith('3c568')
        html_copy=HERE/'公開HTMLの同bytes私有コピー.html';assert not html_copy.exists();html_copy.write_bytes(html_raw)
        result=audit(value,html_raw.decode('utf-8'));assert plan['source_SHA256']==sources()
        save(HERE/'六十六小集計と全場率及び非金融表示の独立再加算.json',result)
        # ----------------------------------------
        # 新出力だけの分類audit用に目録を保存。原入力NPZは対象に含めない。
        targets=[dict(session=r['session'],symbol=r['symbol'],events=r['events'],fields=r['fields'],outcome_fields=r['outcome_fields'],raw_rows=r['raw_rows'],expected_groups=r['groups']) for r in value['rows']]
        save(HERE/'新出力66だけの後続監査用目録.json',dict(公開SHA256=EXPECTED,targets=targets,追加欄=['quantity_ratio/minimum_quantity_ratioの1境界と回復内訳','fresh_price_time','first_positive_fresh_price_time','volume_after_price','npositive','type0_all/type0_reached'],原NPZ=0,出力本文未読=True))
        proof=dict(全合格=True,plan_SHA256=sha(PLAN),source_SHA256=sources(),公開結果一読=1,公開HTML一読=1,公開SHA256=EXPECTED,HTML_SHA256=html_sha,
            集計口座=66,算術表示項目=CHECKS,親旧測定1読=1,旧測定口座0=True,修正版測定口座=66,
            結果='数量非金融率。金融予算/費用/約定/利益は未測。',原入力NPZ=0,出力eventsNPZ=0,金融=0,API=0)
        out=HERE/'数量公開六十六集計と先着分母及び表示の独立監査.json';save(out,proof)
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(out),算術表示項目=CHECKS,場別二群比較=result['場別二群比較'],二群={s:{n:result['再集計'][s]['all']['groups'][n] for n in ('type0_all','type0_reached','type1_decreased','type1_maintained')} for s in ('TOPIX','NK225')}),ensure_ascii=False))
    except BaseException:
        save(HERE/'公開小集計監査_初回False.json',dict(全合格=False,原因=traceback.format_exc(),公開原本文再読禁止=True,原NPZ=0,金融=0));raise


if __name__=='__main__':main()
