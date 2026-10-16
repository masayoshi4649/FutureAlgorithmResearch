"""反転保有で出口を再判定した新116と、元115・固定時刻参考を区別して診断する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from fractions import Fraction
import gzip
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import pickle


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
RESULT=WORK/'finance/結果.json'
MIRROR=WORK/'mirror/固定時刻で買売を反転した十二条件の参考会計.json'
MIRROR_SHA='3285da706460752211c1583d1219c2098816a86e2236e88cc7a8f5434ae0765a'
MAIN='QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1'
PLAN=HERE/'出口再判定の診断目的と読取予算の固定.json'
OUTPUT=HERE/'新反転十二条件の金額分解と指定二例の小診断.json'
SOURCE_NAMES=('catalog.py','engine.py','artificial.py','input_contract.py','plan.py','finance.py',
              'artificial_root.py','metrics/metrics.py','metrics/artificial_metrics.py')
EXAMPLES=(('TOPIX','2026-09-24_Night',2446),('NK225','2026-10-01_Night',3513))


def sha(raw: bytes) -> str:
    """
    機能: 同じbytesの指紋を計算する。
    引数: raw(bytes)。
    返り値: SHA256文字列(str)。
    """
    return hashlib.sha256(raw).hexdigest()


def number(value: object) -> Fraction:
    """
    機能: 有限実数を厳密な算術へ写し、未知を拒否する。
    引数: value(object)。
    返り値: Fraction。真偽を数値に含めない。
    """
    assert isinstance(value,Real) and not isinstance(value,bool) and math.isfinite(value)
    return Fraction(str(value))


def primitive(value: object) -> object:
    """
    機能: 記憶内の小抽出をJSON原始型に移す。
    引数: value(object)。
    返り値: object。観測の非有限だけNoneを保持する。
    """
    if isinstance(value,dict):return {str(k):primitive(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [primitive(v) for v in value]
    if hasattr(value,'tolist'):return primitive(value.tolist())
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def write(path: Path, value: dict) -> None:
    """
    機能: 自所有域へ小資料を上書きせず保存する。
    引数: path(Path)、value(dict)。
    返り値: None。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(primitive(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def sources() -> dict:
    """
    機能: 準備済み新金融九源の指紋だけを確認する。
    引数: なし。
    返り値: dict[str,str]。金融結果や入力を読まない。
    """
    return {(WORK/name).relative_to(ROOT).as_posix():sha((WORK/name).read_bytes()) for name in SOURCE_NAMES}


def clock(value: object) -> str | None:
    """
    機能: 保存価格時計を日本時刻へ表示変換する。
    引数: value(object) はepoch秒又はNone。
    返り値: str|None。受信時刻や応答遅延へ読み替えない。
    """
    return None if value is None else datetime.fromtimestamp(float(number(value)),timezone(timedelta(hours=9))).isoformat()


def sums(rows: list[dict], parents: list[dict]) -> dict:
    """
    機能: 完結親のP/Lと場の黒赤・無取引を、期間ごと同じ定義で再加算する。
    引数: rows/parents(list[dict])。
    返り値: dict。勝ち親率と場の赤字率を混同しない。
    """
    nets=[number(p['net_yen']) for p in parents]
    profit=sum((x for x in nets if x>0),Fraction())
    loss=-sum((x for x in nets if x<0),Fraction())
    assert profit==sum((number(row['利益']) for row in rows),Fraction())
    assert loss==sum((number(row['損失']) for row in rows),Fraction())
    assert profit-loss==sum((number(row['収支']) for row in rows),Fraction())
    assert len(parents)==sum(int(row['親数']) for row in rows)
    return dict(利益=float(profit),損失=float(loss),収支=float(profit-loss),親数=len(parents),
        勝ち親=sum(x>0 for x in nets),負け親=sum(x<0 for x in nets),零親=sum(x==0 for x in nets),
        場数=len(rows),黒字場=sum(number(r['収支'])>0 for r in rows),赤字場=sum(number(r['収支'])<0 for r in rows),
        無取引場=sum(int(r['親数'])==0 for r in rows),
        利益割合=float(profit/(profit+loss)) if profit+loss else None)


def check_breakdown(parent: dict, legs: list[dict], breakdown: dict, symbol: str) -> dict:
    """
    機能: 全返済脚の両BBOから中値・交差・料を直接検算する。
    引数: parent/breakdown(dict)、legs(list[dict])、symbol(str)。
    返り値: dict は親の金額分解と、各実脚の新規・返済点。
    """
    own=[leg for leg in legs if int(leg['parent'])==parent['parent'] and int(leg['uid'])==parent['uid']]
    remaining=list(breakdown['legs'])
    assert own and sum(int(leg['q']) for leg in own)==parent['quantity']
    mid,cross,cost,net=Fraction(),Fraction(),Fraction(),Fraction()
    mult=1000 if symbol=='TOPIX' else 10
    for leg in own:
        matches=[i for i,p in enumerate(remaining) if
            all(int(p[k])==int(leg[k]) for k in ('q','side','entry_row','exit_row'))]
        assert matches
        endpoints=remaining.pop(matches[0])
        a,b=endpoints['新規'],endpoints['返済']
        assert 0<number(a['bid'])<number(a['ask']) and 0<number(b['bid'])<number(b['ask'])
        side,q=int(leg['side']),int(leg['q'])
        assert side in (-1,1) and side==parent['side'] and q>0
        assert number(a['ask' if side>0 else 'bid'])==number(leg['entry_price'])
        assert number(b['bid' if side>0 else 'ask'])==number(leg['exit_price'])
        gain=side*q*mult*(number(b['bid'])+number(b['ask'])-number(a['bid'])-number(a['ask']))/2
        burden=q*mult*(number(a['ask'])-number(a['bid'])+number(b['ask'])-number(b['bid']))/2
        fees=number(leg['entry_fee_allocated'])+number(leg['exit_fee'])
        assert gain-burden==number(leg['gross_yen'])
        assert gain-burden-fees==number(leg['net_yen'])
        mid+=gain;cross+=burden;cost+=fees;net+=number(leg['net_yen'])
    assert not remaining
    assert mid==number(breakdown['中値差粗損益']) and cross==number(breakdown['気配差負担'])
    assert cost==number(breakdown['手数料'])==number(parent['fee_yen'])
    assert net==number(breakdown['収支'])==number(parent['net_yen'])==mid-cross-cost
    return dict(中値差粗損益=float(mid),気配差負担=float(cross),手数料=float(cost),収支=float(net),legs=breakdown['legs'])


def calculate(result: dict, mirror: dict) -> dict:
    """
    機能: 十二実反転運転を元115・固定時刻参考と比較し、主候補の期間差と二例を抽出する。
    引数: result/mirror(dict) は保存済み新結果と既集計参考。
    返り値: dict。同じ親を削除した改善額や新たな反実仮想PLを作らない。
    """
    assert result['全合格'] is True and result['金融'] is True and result['主候補']==MAIN
    configs=[c['id'] for c in result['configs']]
    sessions=result['sessions']
    assert len(configs)==len(set(configs))==12 and len(sessions)==len(set(sessions))==33
    assert len(result['rows'])==len(result['diagnostics'])==792
    diag={(d['case'],d['symbol'],d['session']):d for d in result['diagnostics']}
    assert len(diag)==792
    comparisons,periods={},{}
    for cid in configs:
        old=cid.replace('QREVERSE_','QEXEC_',1)
        assert old in mirror['aggregate']
        comparison={}
        for symbol in ('TOPIX','NK225'):
            rr=[r for r in result['rows'] if r['case']==cid and r['symbol']==symbol]
            pp=[p for p in result['parents'] if p['case']==cid and p['symbol']==symbol]
            assert len(rr)==33 and {r['session'] for r in rr}==set(sessions)
            account=sums(rr,pp)
            dd=[diag[cid,symbol,s] for s in sessions]
            components={k:float(sum((number(d[k]) for d in dd),Fraction())) for k in ('中値差粗損益','気配差負担','手数料','収支')}
            assert number(components['中値差粗損益'])-number(components['気配差負担'])-number(components['手数料'])==number(components['収支'])==number(account['収支'])
            for row in rr:
                d=diag[cid,symbol,row['session']]
                assert number(d['中値差粗損益'])-number(d['気配差負担'])-number(d['手数料'])==number(row['収支'])
            baseline=mirror['aggregate'][old]['symbols'][symbol]
            comparison[symbol]=dict(新反転実運転=account,金額分解=components,
                元115=baseline['元会計'],固定時刻参考=baseline['固定時刻反転'],
                元115からのnet差=account['収支']-baseline['元会計']['収支'],
                固定時刻参考からのnet差=account['収支']-baseline['固定時刻反転']['収支'])
            if cid==MAIN:
                middle=len(sessions)//2
                groups={'全33':sessions,'前16':sessions[:middle],'後17':sessions[middle:],
                    'デイ':[s for s in sessions if s.endswith('_Day')],
                    'ナイト':[s for s in sessions if s.endswith('_Night')]}
                periods[symbol]={label:dict(**sums([r for r in rr if r['session'] in ids],[p for p in pp if p['session'] in ids]),sessions=ids)
                    for label,ids in groups.items() if ids}
        comparisons[cid]=comparison
    examples=[]
    for symbol,session,seq in EXAMPLES:
        d=diag[MAIN,symbol,session]
        found=[s for s in d['snapshots'] if int(s['公開']['raw_seq'])==seq]
        assert len(found)<=1
        record=dict(symbol=symbol,session=session,元の第一公開raw_seq=seq,実親保存有無=bool(found))
        if found:
            s=found[0]
            p=[p for p in result['parents'] if p['case']==MAIN and p['symbol']==symbol and p['session']==session and p['parent']==s['parent'] and p['uid']==s['uid']]
            bd=[b for b in d['parent_breakdown'] if b['parent']==s['parent'] and b['uid']==s['uid']]
            assert len(p)==len(bd)==1
            assert p[0]['side']==(-1 if symbol=='TOPIX' else 1)
            assert int(s['新規']['raw_seq'])==seq+1
            legs=[leg for leg in result['actual_legs'] if leg['case']==MAIN and leg['symbol']==symbol and leg['session']==session]
            record.update(parent=p[0],snapshots=s,価格時計={label:clock(s[label]['price_time_s']) for label in ('公開','新規','最終返済')},
                金額分解=check_breakdown(p[0],legs,bd[0],symbol))
        examples.append(record)
    return dict(全合格=True,十二条件の比較=comparisons,主候補の期間=periods,第一公開二例=examples,
        留保='元115と固定時刻参考から新反転運転への差は、別々に完了した政策全体の差。後続時刻/親/場停止も変わるので親対応の因果額ではない。')


def trace(daily: dict, example: dict) -> dict:
    """
    機能: 指定二場だけで公開seqの受理と実親の返済理由を照合する。
    引数: daily/example(dict)。
    返り値: dict は選定事象・親の公開・注文・制御だけ。曲線を展開しない。
    """
    assert daily['config']['id']==MAIN and daily['completed'] is True
    target=example.get('parent',{}).get('parent')
    out={}
    for name,fields in (('publication_events','publication_fields'),('orders','order_fields'),('control_events','control_fields')):
        data=daily[name].tolist() if hasattr(daily[name],'tolist') else daily[name]
        keys=daily[fields]
        assert len(keys)==len(set(keys)) and all(len(row)==len(keys) for row in data)
        rows=[dict(zip(keys,row)) for row in data]
        out[name]=[row for row in rows if (name=='publication_events' and int(row['raw_seq'])==example['元の第一公開raw_seq']) or
                   (name!='publication_events' and target is not None and int(row['parent'])==target)]
    out['reason_labels']=daily['reason_labels']
    return out


def prepare() -> None:
    """
    機能: 金融完了前に対象・源・参考SHA・一読予算を固定する。
    引数: なし。
    返り値: None。新結果は読まず、statも不要。
    """
    write(PLAN,dict(状態='SOURCE_ONLY準備。根の金融終了とSHA通知後にだけ新結果一読。',
        source_SHA256=sources(),reader_SHA256=sha(Path(__file__).read_bytes()),
        金融結果=RESULT.relative_to(ROOT).as_posix(),結果最大bytes=64*1024*1024,
        既参考=dict(path=MIRROR.relative_to(ROOT).as_posix(),SHA256=MIRROR_SHA),
        対象='新十二条件×両商品×全三十三。主C_E4前16/後17/Day/Night。第一原公開seq2446/3513の二例。',
        読取予算=dict(新116完成結果=1,既mirror参考=1,指定二場の新台帳='各一回・最大2',原NPZ=0,eventNPZ=0,旧115金融=0,API=0,金融再実行=0),
        保存='結果と選定台帳はSHA/bytes照合し同bytes私有copyをparseより先に保存。',
        区別='新反転の保有/場損益に従い出口を再判定した実運転、旧政策時刻を固定した逆BBO参考、元115の三つを区別する。'))


def run(expected_sha: str) -> None:
    """
    機能: 根の通知後に完成結果一読と指定台帳最大二読で診断を完了する。
    引数: expected_sha(str) は根指定の新結果SHA256。
    返り値: None。新しい金融を走らせない。
    """
    assert len(expected_sha)==64 and all(c in '0123456789abcdef' for c in expected_sha)
    assert not OUTPUT.exists()
    fixed=json.loads(PLAN.read_text(encoding='utf-8'))
    assert fixed['source_SHA256']==sources() and fixed['reader_SHA256']==sha(Path(__file__).read_bytes())
    assert RESULT.stat().st_size<=fixed['結果最大bytes']
    raw=RESULT.read_bytes()
    assert sha(raw)==expected_sha
    copy=HERE/'新116完成結果の同bytes私有コピー.json'
    assert not copy.exists()
    copy.write_bytes(raw)
    result=json.loads(raw.decode('utf-8'))
    assert result['source_SHA256']==fixed['source_SHA256']
    mirror_raw=MIRROR.read_bytes()
    assert sha(mirror_raw)==MIRROR_SHA
    mirror=json.loads(mirror_raw.decode('utf-8'))
    completed=calculate(result,mirror)
    read_count=0
    for example in completed['第一公開二例']:
        infos=[item for item in result['ledgers'] if item['case']==MAIN and item['symbol']==example['symbol'] and item['session']==example['session']]
        assert len(infos)==1
        info=infos[0]
        path=(ROOT/info['path']).resolve()
        assert path.is_relative_to((WORK/'finance/ledgers').resolve()) and path.stat().st_size==info['bytes']
        body=path.read_bytes();read_count+=1
        assert len(body)==info['bytes'] and sha(body)==info['SHA256']
        destination=HERE/'ledger_copies'/(example['session']+'_'+example['symbol']+'.pkl.gz')
        destination.parent.mkdir(exist_ok=True)
        assert not destination.exists()
        destination.write_bytes(body)
        daily=pickle.loads(gzip.decompress(body))
        example['実台帳の理由と受理']=trace(daily,example)
        example['台帳目録']=info
        del daily,body
    assert read_count==2 and sources()==fixed['source_SHA256']
    completed.update(新結果SHA256=expected_sha,既参考SHA256=MIRROR_SHA,目的固定SHA256=sha(PLAN.read_bytes()),
        読取=dict(新結果=1,既mirror参考=1,指定新台帳=read_count,原NPZ=0,eventNPZ=0,旧115金融=0,API=0,金融再実行=0))
    write(OUTPUT,completed)
    print(json.dumps(dict(全合格=True,SHA256=sha(OUTPUT.read_bytes()),主候補=completed['十二条件の比較'][MAIN]),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--root-result-sha')
    args=parser.parse_args()
    assert args.prepare_only != bool(args.root_result_sha)
    prepare() if args.prepare_only else run(args.root_result_sha)
