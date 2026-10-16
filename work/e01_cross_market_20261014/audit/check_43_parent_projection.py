"""43実親の小射影だけから、会計・二起点尺度・時計・事後分類を独立確認する。"""

from collections import Counter
from datetime import datetime
from pathlib import Path
import ast
import hashlib
import json
import math

import numpy as np

from cash_distance_oracle import distances, fee


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
DIAG=HERE.parent/'diagnosis'


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 固定診断計画・完成小射影・自所有保存監査だけを読む。
    引数: path(Path)は小JSON。
    返り値: tuple[dict,str]は保存値と同読取SHA256。packet・台帳は読まない。
    """
    assert path.suffix=='.json' and '/finance/' not in path.as_posix()
    saved=path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')),hashlib.sha256(saved).hexdigest()


def near(actual: float, expected: float) -> None:
    """
    機能: 小保存値の独立算術を小さい浮動誤差内で照合する。
    引数: actual/expected(float)は保存値と独立期待。
    返り値: None。不一致は直ちに中止する。
    """
    assert math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-6),(actual,expected)


def clock(value: dict) -> None:
    """
    機能: 価格代理時計・原seq・通常行・保存BBOの型と時刻整合を確認する。
    引数: value(dict)は当時又は事後ピークの小時計。
    返り値: None。未保存受信時刻を追加しない。
    """
    for key in ('normal_row','raw_seq'):assert type(value[key]) is int and value[key]>=0
    parsed=datetime.fromisoformat(value['JST'])
    assert parsed.utcoffset().total_seconds()==9*3600 and parsed.timestamp()==value['price_time_s']
    if 'raw_row' in value:assert type(value['raw_row']) is int and value['raw_row']>=0
    if 'quote_valid' in value:
        assert value['quote_valid'] and 0<value['bid']<value['ask']


def summary(rows: list[dict], fields: tuple[str,...]) -> dict:
    """
    機能: 実親の会計・分類・尺度分布を独立に全数集計する。
    引数: rows(list[dict])、fields(tuple[str,...])は対象親と既定連続尺度。
    返り値: dictは再集計値。新しい有望閾値を選ばない。
    """
    metrics={}
    for field in fields:
        values=np.asarray([r[field] for r in rows],float)
        metrics[field]=dict(件数=len(values)) if not len(values) else dict(件数=len(values),最小=float(np.min(values)),
            第1四分位=float(np.quantile(values,.25)),中央=float(np.median(values)),第3四分位=float(np.quantile(values,.75)),最大=float(np.max(values)))
    return dict(親数=len(rows),勝ち=sum(r['実親']['収支']>0 for r in rows),負け=sum(r['実親']['収支']<0 for r in rows),
        粗損益=sum(r['実親']['粗損益'] for r in rows),費用=sum(r['実親']['費用'] for r in rows),収支=sum(r['実親']['収支'] for r in rows),
        出口理由=dict(Counter(e['理由'] for r in rows for e in r['返済'])),部分返済親数=sum(r['部分返済あり'] for r in rows),
        診断分類={k:sum(r['診断分類'][k] for r in rows) for k in ('一度も費用後黒字なし','費用後黒字を経て最終赤字','粗利が黒字で料により赤字','前親赤字後の再参加')},尺度=metrics)


# ----------------------------------------
def main() -> None:
    """
    機能: 43親・二商品全33場・尺度・事後ピーク用途を小保存値と源だけで敵対監査する。
    引数: なし。完成通知のSHAを事前期待とする。
    返り値: Noneは自所有新証跡。原市場資料・台帳・金融へ進まない。
    """
    scope=HERE/'43親小射影とreaderだけの監査目的固定.json'
    target=HERE/'全43親の会計二起点尺度及び事後用途の独立監査.json'
    assert not scope.exists() and not target.exists()
    scope.write_text(json.dumps(dict(対象='同母CONFIRM_P1の43親小射影・固定計画・reader/helper源だけ。',
        予定小射影SHA256='e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73',
        事後最大順逆行='点の算術と静的argmax区間を確認。原経路を再走査しない。',
        packet=0,ledger=0,原板=0,NPZ=0,金融=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    data,data_sha=read(DIAG/'同母二商品43実親の原因射影.json')
    plan,plan_sha=read(DIAG/'同母二商品差の診断固定計画.json')
    saved,saved_sha=read(HERE/'同一E01の両商品差と再利用及び事後選択の敵対監査.json')
    assert data_sha=='e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'
    assert data['全合格'] and plan['全合格'] and saved['全合格']
    assert data['計画SHA256']==plan_sha and data['条件ID']==plan['条件ID']==saved['条件']
    assert data['source_SHA256']==plan['source_SHA256'] and data['金融source_SHA256']==plan['金融source_SHA256']
    for group in ('source_SHA256','金融source_SHA256'):
        for path,sha in data[group].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    assert data['source開始終端一致']
    assert data['一読記録']['因果packet']==33 and data['一読記録']['対象goal活動台帳']==42
    paths={k:v for k,v in data['一読記録'].items() if k.startswith('path:')}
    assert len(paths)==75 and all(v==1 for v in paths.values())
    expected_paths={v['path'] for v in plan['input_cache'].values()}|{v['path'] for v in plan['active_ledgers'].values()}
    assert {k[5:] for k in paths}==expected_paths
    for key in ('新金融','原板','NPZ','API','公開変更','共通知見変更'):assert data[key]==0
    reader=(DIAG/'reader.py').read_text(encoding='utf-8');tree=ast.parse(reader)
    obs=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observation')
    assert 'first:last + 1' in ast.unparse(obs) and 'argmax' in ast.unparse(obs) and 'argmin' in ast.unparse(obs)
    assert not any(isinstance(n,ast.Call) and any(word in ast.unparse(n.func) for word in ('simulate','execute','urlopen','requests')) for n in ast.walk(tree))
    assert '実policy後のGU suffixは未実施' in reader and '公開固定ATRで正規化し未来ATRを再計算しない' in plan['分析定義']['経路']
    observations=data['実親'];assert len(observations)==43
    index={(r['session'],r['symbol'],r['paper_parent']):r for r in observations};assert len(index)==43
    ratios=0;points=0;parents=[]
    for row in observations:
        symbol=row['symbol'];side=row['side'];q=row['実初回q'];full=5 if symbol=='TOPIX' else 10
        value=1000 if symbol=='TOPIX' else 10;tick=.5 if symbol=='TOPIX' else 10.;budget=5000 if symbol=='TOPIX' else 2000.
        atr=row['公開ATR'];risk=q*atr*value;published=row['公開'];entry=row['新規'];parent=row['実親'];exits=row['返済']
        assert atr>0 and math.isfinite(atr) and side in (1,-1) and 0<q<=full and not row['部分返済あり'] and len(exits)==1
        assert row['通常全量']==full and row['観測呼値']==tick and row['実q全量比']==q/full
        assert row['アンカーq全量比']==row['初回受理アンカーq']/full
        near(row['ATR呼値数'],atr/tick);near(row['R円'],risk)
        clock(published);clock(entry)
        assert published['normal_row']<entry['normal_row'] and published['raw_seq']<entry['raw_seq']
        assert published['raw_row']<entry['raw_row'] and published['price_time_s']<=entry['price_time_s']
        price=row['実新規価格'];assert price==entry['ask' if side==1 else 'bid']
        exit_quote=entry['bid' if side==1 else 'ask'];assert row['実fill時の返済側気配価格']==exit_quote
        pub_spread=published['ask']-published['bid'];spread=entry['ask']-entry['bid']
        near(row['公開spread'],pub_spread);near(row['実fillspread'],spread)
        one_fee=fee(q,symbol);round_fee=2*one_fee
        assert row['公開予定往復料']==round_fee
        e=exits[0];clock(e['判断']);clock(e['約定'])
        assert e['q']==q and e['floor料']==one_fee
        assert entry['normal_row']<=e['判断']['normal_row']<e['約定']['normal_row']
        assert entry['raw_seq']<=e['判断']['raw_seq']<e['約定']['raw_seq']
        assert e['price']==e['約定']['bid' if side==1 else 'ask']
        gross=side*q*(e['price']-price)*value
        near(parent['粗損益'],gross);near(parent['収支'],gross-round_fee)
        assert parent['費用']==round_fee==row['実往復料'] and parent['枚数']==q and parent['方向']==side
        assert parent['新規行']==entry['normal_row'] and parent['最終返済行']==e['約定']['normal_row']
        if e['reason'] in (94,95):
            control=data['場別'][row['session']+'|'+symbol]['保存停止']
            assert e['判断']['normal_row']==control['判断行'] and e['約定']['normal_row']==control['返済行']
            assert e['判断']['raw_seq']==control['判断原seq'] and e['約定']['raw_seq']==control['返済原seq']
        prior=row['公開時前親清算'];goal=row['保存利益線円'];loss=row['保存損失予算円']
        assert loss==budget and goal==(500 if symbol=='TOPIX' else 100)*row['初回受理アンカーq']
        distances_expected=distances(symbol,q,goal,loss,prior,spread)
        mapping={'新規約定価格起点_全量一往復の必要利益値幅':'新規価格から利益方向幅',
            '初期返済側気配起点_必要利益値幅':'初期返済気配から利益方向幅',
            '新規約定価格起点_全量一往復の損失許容逆行値幅':'新規価格から許容逆行幅',
            '初期返済側気配起点_損失許容逆行値幅':'初期返済気配から許容逆行幅',
            '新規約定価格起点_必要利益呼値切上げ':'新規価格から利益呼値',
            '初期返済側気配起点_必要利益呼値切上げ':'初期返済気配から利益呼値'}
        for field,key in mapping.items():near(row[field],distances_expected[key]);ratios+=1
        for field,expected in (('公開spread_ATR比',pub_spread/atr),('実fillspread_ATR比',spread/atr),
            ('公開予定往復料_R比',round_fee/risk),('実往復料_R比',round_fee/risk),
            ('公開予定初期清算費用',q*pub_spread*value+round_fee),('公開予定初期清算費用_R比',(q*pub_spread*value+round_fee)/risk),
            ('実fill初期清算費用',q*spread*value+round_fee),('実fill初期清算費用_R比',(q*spread*value+round_fee)/risk),
            ('名目利益線_R比',goal/risk),('名目損失線_R比',loss/risk),('残利益線_R比',(goal-prior)/risk),('残損失線_R比',(loss+prior)/risk),
            ('新規約定価格起点_必要利益呼値数',distances_expected['新規価格から利益方向幅']/tick),
            ('初期返済側気配起点_必要利益呼値数',distances_expected['初期返済気配から利益方向幅']/tick),
            ('新規約定価格起点_必要利益_ATR比',distances_expected['新規価格から利益方向幅']/atr),
            ('初期返済側気配起点_必要利益_ATR比',distances_expected['初期返済気配から利益方向幅']/atr),
            ('新規約定価格起点_損失許容_ATR比',distances_expected['新規価格から許容逆行幅']/atr),
            ('初期返済側気配起点_損失許容_ATR比',distances_expected['初期返済気配から許容逆行幅']/atr),
            ('公開からfillの新規側不利移動呼値',side*(price-published['ask' if side==1 else 'bid'])/tick)):
            near(row[field],expected);ratios+=1
        sizing=row['当時数量判断'];assert sizing['actual_pending']==sizing['gate_accepted']==1 and sizing['size_reason']==0
        assert sizing['row']==published['normal_row'] and sizing['paper_parent']==row['paper_parent'] and sizing['side']==side
        assert sizing['selected_actual_quantity']==q and sizing['virtual_initial']==full
        near(sizing['published_ATR'],atr);near(sizing['published_spread'],pub_spread);near(sizing['published_liquidation_yen'],prior)
        margin=max(0.,budget+prior);near(sizing['remaining_budget_yen'],margin)
        planned=q*(atr+pub_spread)*value+round_fee;near(sizing['planned_risk_yen'],planned)
        allowed=[candidate for candidate in range(1,full+1) if candidate*(atr+pub_spread)*value+2*fee(candidate,symbol)<=margin]
        assert q==max(allowed)
        vote=row['公開W60'];assert vote['known'] and vote['accepted'] and vote['direction_votes']>=2 and vote['balance']>=.25
        assert vote['candidate_raw_seq']==published['raw_seq'] and vote['candidate_raw_row']==published['raw_row']
        assert vote['candidate_price_time_s']==published['price_time_s'] and vote['cutoff_price_time_s']==published['price_time_s']-60
        assert row['初回方向票数']==vote['direction_votes']==vote['up_votes']+vote['down_votes']
        near(row['候補方向釣合い'],side*(vote['up_votes']-vote['down_votes'])/vote['direction_votes'])
        for prefix,quote_field in (('事後Last','Last'),('事後清算側','bid' if side==1 else 'ask')):
            for extreme,sign in (('最大順行',1),('最大逆行',-1)):
                point=row[prefix+extreme+'時刻'];clock(point)
                assert entry['normal_row']<=point['normal_row']<=e['約定']['normal_row']
                assert entry['raw_seq']<=point['raw_seq']<=e['約定']['raw_seq']
                expected=sign*side*(point[quote_field]-price)
                near(row[prefix+extreme+'値幅'],expected);near(row[prefix+extreme+'_ATR比'],expected/atr);points+=1
        peak=row['実親清算経路'];max_net=q*row['事後清算側最大順行値幅']*value-round_fee
        min_net=-q*row['事後清算側最大逆行値幅']*value-round_fee
        near(peak['事後の最大清算利益'],max_net);near(peak['事後の最大清算損失'],min_net)
        near(peak['最大利益から返した金額'],max_net-parent['収支'])
        assert peak['実現可能な別出口利益ではない'] and max_net>=parent['収支']>=min_net
        for name in ('最大利益時刻','最大損失時刻'):
            point=peak[name];clock(point);assert entry['normal_row']<=point['normal_row']<=e['約定']['normal_row']
        classification=dict(一度も費用後黒字なし=max_net<=0,費用後黒字を経て最終赤字=max_net>0 and parent['収支']<0,
            粗利が黒字で料により赤字=gross>0 and parent['収支']<0,前親赤字後の再参加=prior<0)
        assert row['診断分類']==classification
        parents.append(dict(session=row['session'],symbol=symbol,親=row['paper_parent'],gross=gross,fee=round_fee,net=gross-round_fee,
            入口=row['新規']['JST'],出口=e['約定']['JST'],最大清算=max_net,最大清算損失=min_net,
            診断分類=classification,最大順逆行は事後=True))
    # ----------------------------------------
    groups={}
    for symbol in ('TOPIX','NK225'):
        own=[r for r in observations if r['symbol']==symbol];groups[symbol]={}
        choices=dict(全親=own,勝親=[r for r in own if r['実親']['収支']>0],負親=[r for r in own if r['実親']['収支']<0],
            買い=[r for r in own if r['side']==1],売り=[r for r in own if r['side']==-1],
            Day=[r for r in own if r['session'].endswith('_Day')],Night=[r for r in own if r['session'].endswith('_Night')])
        for name,rows in choices.items():
            fields=tuple(data['集計'][symbol][name]['尺度']);calculated=summary(rows,fields)
            for key,value in calculated.items():assert value==data['集計'][symbol][name][key],(symbol,name,key)
            groups[symbol][name]=calculated
        actual=groups[symbol]['全親'];assert actual['親数']==(19 if symbol=='TOPIX' else 24)
        assert actual['収支']==saved['商品別'][symbol]['全33']['収支'] and actual['費用']==saved['商品別'][symbol]['支払手数料']
        assert actual['粗損益']==saved['商品別'][symbol]['手数料前価格差収支']
    assert len(data['場別'])==66
    for key,scene in data['場別'].items():
        session,symbol=key.split('|');own=[r for r in observations if r['session']==session and r['symbol']==symbol]
        row=scene['row'];assert row['親数']==len(own)
        assert sum(r['実親']['収支'] for r in own)==row['収支'] and sum(r['実親']['費用'] for r in own)==row['費用']
        assert sum(max(0,r['実親']['収支']) for r in own)==row['利益'] and sum(max(0,-r['実親']['収支']) for r in own)==row['損失']
    worst={}
    for symbol in ('TOPIX','NK225'):
        expected=sorted([scene['row'] for key,scene in data['場別'].items() if key.endswith('|'+symbol) and scene['row']['収支']<0],key=lambda r:(r['収支'],r['session']))[:3]
        got=data['赤字上位最大三場'][symbol];assert [r['row'] for r in got]==expected
        assert len(got)==(3 if symbol=='TOPIX' else 2)
        for scene in got:
            assert scene['実親']==[r for r in observations if r['session']==scene['row']['session'] and r['symbol']==symbol]
        worst[symbol]=[dict(session=r['row']['session'],net=r['row']['収支'],親=[dict(親=p['paper_parent'],新規=p['新規']['JST'],返済=p['返済'][-1]['約定']['JST']) for p in r['実親']]) for r in got]
    output=dict(全合格=True,小射影SHA256=data_sha,診断計画SHA256=plan_sha,既独立監査SHA256=saved_sha,
        reader及びhelper_SHA256=data['source_SHA256'],金融source_SHA256=data['金融source_SHA256'],
        独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),全親=43,会計親=parents,
        尺度照合数=ratios,最大順逆行点照合=points,両商品集計=groups,赤字上位の具体時計=worst,
        留保=['事後最大値は保存点の算術とreaderが固定実保有区間でargmax/argminする源を確認。全raw経路を独立に再走査したとは呼ばない。',
              '全43親はpartial0。今親一括往復の必要幅の整合を確認した範囲で、partial後を保証しない。',
              '最大利益から返した金額は最大清算値が負でも正になり得る。費用後黒字を経た利益返しとは別に分類。',
              '入口票の真の方向精度、板厚み/補充、未知期間の汎用性は今回未測定。',
              '新規価格起点と初期返済気配起点は実fill spread分だけ異なる。公開spreadへ置換しない。'],
        原板=0,NPZ=0,packet=0,ledger=0,金融=0,API=0,source及び共有docs変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,親=43,尺度=ratios,事後点=points,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
