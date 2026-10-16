"""完成済み保存結果の一読だけで、新九条件の会計を独立分数算術で監査する。"""

import argparse
from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction
import hashlib
import importlib.util
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
RESULT=BASE/'root_review/公開用の同bytes結果.json'
PUBLIC=ROOT/'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加/現在の活動と再進行の公開会計.json'
RESULT_SHA='ad0df26bb40ae4bc1b37700decec1d1dbabc60efc4419871665b0d23208cb31b'
PUBLIC_SHA='3df4d3ff4c4f78fa260a88cf8fcea02568b832d15b7ee3aae342fae2f8eed8be'
PLAN=HERE/'九条件594会計の目的別読取固定.json'
CHECKS=0


def sha(path: Path) -> str:
    """
    機能: source又は保存小証跡のSHAを計算する。
    引数: path(Path)は源又は自所有小資料。金融結果へは呼ばない。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path,value: dict) -> None:
    """
    機能: 自所有の新証跡だけを非有限JSON禁止で保存する。
    引数: path(Path)、value(dict)は新保存先と内容。
    返り値: None。旧成功/Falseは上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: 凍結17源を経済入力とは別に同bytes指紋へ束縛する。
    引数: なし。
    返り値: dictは17源の相対pathとSHA。源は編集しない。
    """
    paths=sorted((BASE/'engine').glob('*.py'))+[BASE/'root_review'/s for s in ('finance.py','plan.py','financial_metrics.py')]
    assert len(paths)==17
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}


def prepare() -> None:
    """
    機能: 結果本文を読む前に目的・各一読・対象bytes/SHA・監査sourceを固定する。
    引数: なし。
    返り値: None。stat/sourceだけ読み、結果/公開本文はまだ0。
    """
    targets=[dict(role=role,path=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,SHA256=s,予定本文読取=1)
             for role,p,s in (('完成保存結果',RESULT,RESULT_SHA),('公開小会計',PUBLIC,PUBLIC_SHA))]
    assert targets[0]['bytes']==40610706 and targets[1]['bytes']==324688
    write(PLAN,dict(目的='完成保存結果の594 summary、完結親と手数料、全33場P/L/net、全期間/方向を独立Fraction/Decimalで検算し、入口③を①②の各新実運転と比較する。',
        対象='既知33場×2商品×9新条件。保存旧基準は掲載同値だけ、追加効能標本に数えない。',targets=targets,
        監査source_SHA256=sha(Path(__file__)),金融source_SHA256=sources(),
        方式='許可されたroot保存写しと公開会計を各1読、同読取bytesでSHA検算してparse前に自所有へ保全。以後原コピー再読0。',
        禁止=['実台帳本文','入力cache','原板','NPZ','現在API','新金融再生','親削除による仮想損益'],
        未測='全normal曲線/実受信順/真攻撃量/新2場/未来成績は検算対象外。',追加金融=0))
    print(json.dumps(dict(prepared=True,計画SHA256=sha(PLAN),監査source_SHA256=sha(Path(__file__)),金融結果本文=0),ensure_ascii=False))


def load_once(meta: dict,private: Path) -> dict:
    """
    機能: 一指定pathの同bytes一読を検算し、parseより先に私有写しへ保全する。
    引数: meta(dict)は事前固定、private(Path)は自所有の未保存先。
    返り値: dictは完成済みJSON。実金融を開始しない。
    """
    path=ROOT/meta['path'];assert path in (RESULT,PUBLIC) and not private.exists()
    raw=path.read_bytes()
    assert len(raw)==meta['bytes'] and hashlib.sha256(raw).hexdigest()==meta['SHA256']
    private.write_bytes(raw)
    return json.loads(raw.decode('utf-8'))


def number(value: object) -> Fraction:
    """
    機能: 有限で真偽値でない保存金額を独立分数へ変換する。
    引数: value(object)は保存された数値。
    返り値: Fractionは十進表現の厳密値。未知やNaNを零へ変えない。
    """
    assert isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    return Fraction(str(value))


def equal(actual: object,expected: object) -> None:
    """
    機能: 独立期待値と保存値を型/未知を保って再帰照合する。
    引数: actual/expected(object)は同構造の比較対象。
    返り値: None。不一致なら直ちに停止し件数を保存する。
    """
    global CHECKS
    if isinstance(expected,dict):
        assert set(actual)==set(expected),(set(actual),set(expected))
        for k,v in expected.items():equal(actual[k],v)
    elif isinstance(expected,list):
        assert len(actual)==len(expected)
        for a,e in zip(actual,expected):equal(a,e)
    elif expected is None or isinstance(expected,bool):
        assert actual is expected,(actual,expected);CHECKS+=1
    elif isinstance(expected,(Fraction,int,float)):
        value=number(actual);expected=Fraction(str(expected)) if not isinstance(expected,Fraction) else expected
        assert abs(value-expected)<=max(Fraction(1,100000),abs(expected)*Fraction(1,10**12)),(actual,str(expected))
        CHECKS+=1
    else:
        assert actual==expected,(actual,expected);CHECKS+=1


def helper() -> object:
    """
    機能: 実金融/入力を読まない既独立Fraction oracleの関数だけを利用する。
    引数: なし。
    返り値: moduleはoracle_amounts/oracle_scope。対象のfinancial_metricsは呼ばない。
    """
    path=BASE/'audit_accounting/metrics_artificial.py'
    spec=importlib.util.spec_from_file_location('独立金額分数oracle再利用',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def charge(q: int,symbol: str) -> int:
    """
    機能: 実注文の片道料を独立Decimalで切り捨てる。
    引数: q(int)、symbol(str)は実枚数/商品。
    返り値: intは円料。Native料金関数を使わない。
    """
    return int((Decimal(q)*Decimal('41.8' if symbol=='TOPIX' else '11')).to_integral_value(rounding=ROUND_FLOOR))


def parent_check(parent: dict,profile: dict,symbol: str) -> None:
    """
    機能: 保存完結親を実新規/実返済価格・方向・枚数・個別料から独立再計算する。
    引数: parent/profile(dict)、symbol(str)は同実CIDの保存小射影。
    返り値: None。原台帳や未来極値を損益へ使わない。
    """
    cap=10 if symbol=='TOPIX' else 20;mult=1000 if symbol=='TOPIX' else 10
    assert parent['枚数']==profile['entry_quantity']==cap and parent['方向']==profile['side'] in (-1,1)
    assert len(profile['exits'])==1
    entry,exit=profile['entry'],profile['exits'][0];side=parent['方向']
    assert entry['quantity']==exit['quantity']==cap
    assert entry['source_row']<entry['row']<=exit['source_row']<exit['row']
    equal(entry['price'],entry['約定']['ask' if side>0 else 'bid'])
    equal(exit['price'],exit['約定']['bid' if side>0 else 'ask'])
    fee=charge(cap,symbol);equal(entry['fee_yen'],fee);equal(exit['fee_yen'],fee)
    gross=side*cap*(number(exit['price'])-number(entry['price']))*mult
    equal(parent['粗損益'],gross);equal(parent['費用'],2*fee);equal(parent['収支'],gross-2*fee)
    equal(profile['net_yen'],gross-2*fee);equal(profile['fees_yen'],2*fee)


def normalized_metrics(z: dict) -> dict:
    """
    機能: 独立計算した期間定義を公開小会計の保存項目へ対応させる。
    引数: z(dict)は独立scopeの返り値。
    返り値: dictは公開metricsの同一列。
    """
    return dict(profit=z['aggregate']['利益'],loss=z['aggregate']['損失'],net=z['aggregate']['収支'],
        profit_share=z['aggregate']['利益割合'],sessions=z['session_count'],positive=z['positive_sessions'],negative=z['losing_sessions'],
        active=z['active_sessions'],no_trade=z['no_trade_sessions'],mean_session_net=z['mean_session_net_yen'],
        mean_positive_session_net=z['mean_positive_session_net_yen'],worst_session_loss=z['worst_negative_session_abs_yen'],
        pass_all=z['all_stability_targets'],primary_pass=z['all_main_targets'],
        tests=dict(share65=z['target65'],red20=z['target_red20'],coverage=z['target_worst_mean']))


def audit(value: dict,public: dict) -> dict:
    """
    機能: 全594 summary/全完結親/全期間/全33場公開会計を独立算術で検算する。
    引数: value/public(dict)は各一読した完成済み保存。
    返り値: dictは全場射影と三入口の各新運転比較。親削除仮説は使わない。
    """
    oracle=helper();sessions=value['sessions'];configs=value['configs'];results=value['results']
    assert len(sessions)==len(set(sessions))==33 and len(configs)==len(results)==9
    assert value['全合格'] and value['counts']==dict(TradeGatecache=33,TradeExitcache=33,現在特徴商品=66,新金融口座=594)
    equal(value['source_SHA256'],sources());equal(value['source開始終端一致'],True)
    equal(public['金融出典']['SHA256'],RESULT_SHA);equal(public['sessions'],sessions)
    equal(public['新金融口座'],594);equal(public['保存基準再金融'],0)
    assert set(results)=={c['id'] for c in configs}
    count_parents=0;rows_out=[];comparison={};all_pass=0;period_count=0
    for config in configs:
        cid=config['id'];case=results[cid];rows=case['rows'];parents=case['parents'];profiles=case['parent_diagnostics'];pc=public['cases'][cid]
        assert len(rows)==66 and len({(r['session'],r['symbol']) for r in rows})==66
        assert pc['new_financial'] is True;equal(case['config'],config);equal(pc['config'],config)
        pmap={(p['session'],p['symbol'],p['親']):p for p in parents}
        dmap={(p['session'],p['symbol'],p['parent']):p for p in profiles}
        assert len(pmap)==len(parents)==len(dmap)==len(profiles) and set(pmap)==set(dmap)
        for key,p in pmap.items():parent_check(p,dmap[key],key[1])
        count_parents+=len(parents)
        for row in rows:
            pp=[p for p in parents if p['session']==row['session'] and p['symbol']==row['symbol']]
            a=oracle.oracle_amounts([p['収支'] for p in pp])
            for key in a:equal(row[key],a[key])
            expected_ratio=a['平均利益']/a['平均損失'] if a['平均利益'] is not None and a['平均損失'] else None
            equal(row['平均損益比'],expected_ratio);equal(row['費用'],sum(p['費用'] for p in pp))
            cap=10 if row['symbol']=='TOPIX' else 20
            equal(row['新規枚数'],len(pp)*cap);equal(row['注文件数'],len(pp)*2);equal(row['全会計合格'],True)
            for key,sign in (('勝ち枚数',1),('負け枚数',-1),('零枚数',0)):
                equal(row[key],sum(p['枚数'] for p in pp if (1 if p['収支']>0 else -1 if p['収支']<0 else 0)==sign))
            expected=dict(session=row['session'],symbol=row['symbol'],profit=a['利益'],loss=a['損失'],net=a['収支'],campaigns=len(pp),
                winning_lots=row['勝ち枚数'],losing_lots=row['負け枚数'],fees=sum(p['費用'] for p in pp))
            actual=[r for r in pc['rows'] if (r['session'],r['symbol'])==(row['session'],row['symbol'])];assert len(actual)==1
            equal(actual[0],expected)
            rows_out.append(dict(id=cid,**{k:float(v) if isinstance(v,Fraction) else v for k,v in expected.items()}))
        both=[]
        for symbol in ('TOPIX','NK225'):
            own=[r for r in rows if r['symbol']==symbol];pp=[p for p in parents if p['symbol']==symbol]
            assert {r['session'] for r in own}==set(sessions)
            top=sorted((r for r in own if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]
            excluded=[r['session'] for r in top];equal(case['periods'][symbol]['除外場'],excluded)
            groups={'全場':sessions,'前半':sessions[:16],'後半':sessions[16:],'デイ':[s for s in sessions if s.endswith('_Day')],
                'ナイト':[s for s in sessions if s.endswith('_Night')],'上位3黒字場除外':[s for s in sessions if s not in excluded]}
            for label,ids in groups.items():
                rr=[r for r in own if r['session'] in ids];ps=[p for p in pp if p['session'] in ids]
                z=oracle.oracle_scope(rr,ps,symbol);actual=dict(case['periods'][symbol][label]);equal(actual.pop('sessions'),ids);equal(actual,z)
                pubkey={'全場':'full','前半':'first','後半':'last','デイ':'day','ナイト':'night','上位3黒字場除外':'top3'}[label]
                equal(pc['metrics'][symbol][pubkey],normalized_metrics(z));period_count+=1
            for label,side in (('買い',1),('売り',-1)):
                a=oracle.oracle_amounts([p['収支'] for p in pp if p['方向']==side])
                equal(case['periods'][symbol]['方向'][label],a);equal(pc['metrics'][symbol]['directions'][label],a)
            z=oracle.oracle_scope(own,pp,symbol);both.append(z['all_main_targets'])
            comparison.setdefault(config['exit_id'],{}).setdefault(symbol,{})[config['entry_id']]=dict(id=cid,
                利益=float(z['aggregate']['利益']),損失=float(z['aggregate']['損失']),収支=float(z['aggregate']['収支']),親数=len(pp),
                料金=sum(p['費用'] for p in pp),金額利益割合=float(z['aggregate']['利益割合']) if z['aggregate']['利益割合'] is not None else None,
                場平均=float(z['mean_session_net_yen']),黒字=z['positive_sessions'],赤字=z['losing_sessions'],無取引=z['no_trade_sessions'],主達成=z['all_main_targets'])
        all_pass+=all(both)
    assert len(rows_out)==594 and all_pass==0
    differences=[]
    for exit_id,symbols in comparison.items():
        for symbol,entries in symbols.items():
            third=entries['CURRENT_VOL_PRICE_RESPONSE']
            for base in ('CURRENT_VOL_SEL','CURRENT_VOL_PRICE'):
                first=entries[base]
                differences.append(dict(出口=exit_id,商品=symbol,比較='③−'+('①' if base=='CURRENT_VOL_SEL' else '②'),
                    利益差=third['利益']-first['利益'],損失差=third['損失']-first['損失'],収支差=third['収支']-first['収支'],
                    親数差=third['親数']-first['親数'],料金差=third['料金']-first['料金'],
                    定義='各新実運転の全後続結果の差。共通親削除/救済PLや因果を仮定しない。'))
    return dict(全合格=True,全場=sessions,新会計=594,完結実親=count_parents,実注文射影=count_parents*2,
        期間商品条件=period_count,算術項目=CHECKS,主達成両商品=all_pass,各入口の実結果=comparison,入口三段階差=differences,rows=rows_out)


def main() -> None:
    """
    機能: 事前固定後の指定二資料一読を監査し、成功/Falseを自所有へ保存する。
    引数: CLI --prepare/--run(bool)は固定又は一回監査。
    返り値: None。源17/公開/実台帳/金融を変更しない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--run',action='store_true');args=parser.parse_args()
    if args.prepare:prepare();return
    plan=json.loads(PLAN.read_text(encoding='utf-8'))
    assert plan['監査source_SHA256']==sha(Path(__file__)) and plan['金融source_SHA256']==sources()
    try:
        result=load_once(plan['targets'][0],HERE/'同bytes金融結果の私有保存.json')
        public=load_once(plan['targets'][1],HERE/'同bytes公開小会計の私有保存.json')
        projection=audit(result,public);assert sources()==plan['金融source_SHA256']
        write(HERE/'入口三段階と全33場の独立損益射影.json',projection)
        proof=dict(全合格=True,計画SHA256=sha(PLAN),監査source_SHA256=sha(Path(__file__)),金融source_SHA256=sources(),
            金融保存写し一読=1,公開会計一読=1,金融SHA256=RESULT_SHA,公開SHA256=PUBLIC_SHA,
            新会計=projection['新会計'],完結実親=projection['完結実親'],実注文射影=projection['実注文射影'],
            期間商品条件=projection['期間商品条件'],算術項目=CHECKS,主両商品達成=projection['主達成両商品'],
            射影SHA256=sha(HERE/'入口三段階と全33場の独立損益射影.json'),
            未測='実台帳本文/全normalcurveは読まない。親netは完成保存の実新規/全量返済射影から独立再計算した。',
            実台帳=0,入力cache=0,原板=0,NPZ=0,API=0,新金融=0,新2場=0)
        out=HERE/'九条件594会計と全完結親及び全期間の独立監査.json';write(out,proof)
        print(json.dumps(dict(全合格=True,proof_SHA256=sha(out),新会計=projection['新会計'],完結親=projection['完結実親'],
            算術項目=CHECKS,各入口の実結果=projection['各入口の実結果'],入口三段階差=projection['入口三段階差']),ensure_ascii=False))
    except BaseException:
        write(HERE/'金融小監査_初回False.json',dict(全合格=False,原因=traceback.format_exc(),金融保存写し再読禁止=True,入力cache=0,新金融=0))
        raise


if __name__=='__main__':main()
