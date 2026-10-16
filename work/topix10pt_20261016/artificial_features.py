"""一分足特徴と32仮説の欠測・因果・尺度を、実入力なしの合成例で検査する。"""

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent


def load_features():
    """
    機能: 同じ所有域の純特徴計算だけを読み込む。
    引数: なし。
    返り値: module はfeatures.py。実入力・他経済源を読み込まない。
    """
    spec=importlib.util.spec_from_file_location('検査対象の純特徴',HERE/'features.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def source_hashes() -> dict:
    """
    機能: この人工と純特徴源の開始終端指紋を取得する。
    引数: なし。
    返り値: dict[str,str] は2源のSHA256。
    """
    return {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('features.py','artificial_features.py')}


def fixture(n: int=420,kind: str='mixed') -> tuple[dict,dict]:
    """
    機能: 価格・出来高・板・先行相手値を全て人工生成する。
    引数: n(int) は足数、kind(str) はmixed/trend/flatの経路。
    返り値: tuple[dict,dict] はbarsとother。外部ファイルを参照しない。
    """
    i=np.arange(n,dtype=float)
    if kind=='trend':close=4000.+i*.5
    elif kind=='flat':close=np.full(n,4000.)
    else:
        close=4000.+i*.015+4*np.sin(i*.08)+1.7*np.sin(i*.31)
        close+=np.where((i%160)>=80,(i%160-80)*.11,0.)
    opening=np.r_[close[:1],close[:-1]] if n else np.empty(0)
    wiggle=.25+.15*(np.sin(i*.17)+1)
    bars=dict(t_s=i*60,open=opening,high=np.maximum(opening,close)+wiggle,
        low=np.minimum(opening,close)-wiggle,close=close,volume=100.+(i%13)*11,
        volume_known=np.ones(n,bool),valid=np.ones(n,bool),book_imbalance=np.sin(i*.08)*.8,
        book_depth=np.sin(i*.08+.1)*.8,book_ofi=np.sin(i*.31)*.8,
        book_quote_valid=np.ones(n,bool),anchor=close+.1*np.sign(np.sin(i*.31)),
        pub_raw_row=np.arange(n,dtype=np.int64)*3+1)
    other=dict(matchedNKclose=60000.+i*2,return3=np.sin(i*.08)*.001,
        return10=np.sin(i*.04)*.002,efficiency10=np.full(n,.7),matchedNKt_s=i*60-60,
        matchedNKknown=np.ones(n,bool))
    return bars,other


def copy_arrays(data: dict) -> dict:
    """
    機能: 人工配列を変更用に複製する。
    引数: data(dict[str,ndarray]) は合成契約。
    返り値: dict[str,ndarray] は独立配列。
    """
    return {name:value.copy() for name,value in data.items()}


def oracle_ma(values: np.ndarray,period: int,exponential: bool) -> np.ndarray:
    """
    機能: Fractionで欠測リセット付きSMA/EMAを別計算する。
    引数: values(ndarray)、period(int)、exponential(bool) は系列と計算種別。
    返り値: ndarray[float] は独立期待値。初回p本SMAから開始する。
    """
    result=np.full(len(values),np.nan);history=[];previous=None;alpha=Fraction(2,period+1)
    for row,value in enumerate(values):
        if not np.isfinite(value):history=[];previous=None;continue
        history.append(Fraction(str(float(value))))
        if len(history)<period:continue
        if not exponential or previous is None:previous=sum(history[-period:],Fraction())/period
        else:previous=alpha*history[-1]+(1-alpha)*previous
        result[row]=float(previous)
    return result


def json_value(value):
    """
    機能: 診断配列を未知Noneを保つJSON原始型へ変換する。
    引数: value(any) は合成計算結果。
    返り値: JSON互換値。NaNを観測0へ補完しない。
    """
    if isinstance(value,dict):return {str(k):json_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [json_value(v) for v in value]
    if isinstance(value,np.ndarray):return json_value(value.tolist())
    if isinstance(value,np.generic):return json_value(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    return value


def run() -> dict:
    """
    機能: 未観測入力だけで特徴算術・全出力保存・接頭因果を確認する。
    引数: なし。
    返り値: dict は検査数、仕様、合成だけの観測件数、開始終端SHA。
    """
    initial=source_hashes();f=load_features();checks=0;cases=0;prefixes=0

    def check(name: str,condition: bool) -> None:
        """
        機能: 名前付きの独立期待を検査する。
        引数: name(str)、condition(bool) は検査名と成否。
        返り値: None。不一致はその場で停止する。
        """
        nonlocal checks
        checks+=1
        if not bool(condition):raise AssertionError(name)

    def equal(name: str,actual: np.ndarray,expected: np.ndarray,tolerance: float=1e-9) -> None:
        """
        機能: NaN位置を含めた配列同値を検査する。
        引数: name(str)、actual/expected(ndarray)、tolerance(float) は期待精度。
        返り値: None。shape又は値が違えば停止する。
        """
        nonlocal checks
        checks+=int(np.size(expected))+1
        np.testing.assert_allclose(actual,expected,rtol=1e-11,atol=tolerance,equal_nan=True,err_msg=name)

    def evaluate(bars: dict,other: dict) -> dict:
        """
        機能: 合成入力不変と全出力JSON保存を含めて実装を接続する。
        引数: bars/other(dict) は合成契約。
        返り値: dict は純特徴計算結果。入力編集があれば停止する。
        """
        nonlocal cases
        cases+=1;before={k:v.tobytes() for k,v in {**bars,**other}.items()}
        result=f.prepare(bars,other)
        check('入力配列不変',before=={k:v.tobytes() for k,v in {**bars,**other}.items()})
        check('有限X',result['X'].shape[0]==len(bars['t_s']) and np.isfinite(result['X']).all())
        check('32符号',result['signals'].shape==(len(bars['t_s']),32) and np.isin(result['signals'],[-1,0,1]).all())
        check('仕様32固定',result['specifications']==f.specifications())
        check('名前と群の全域',len(result['names'])==result['X'].shape[1]==len(set(result['names'])) and set(result['names'])==set(result['feature_groups']))
        check('群5種',set(result['feature_groups'].values())=={'price','ma','volume','book','peer'})
        for col,name in enumerate(result['names']):
            if name.endswith('_known'):
                check('既知flag二値',np.isin(result['X'][:,col],[0.,1.]).all())
                check('未知値0符号化',np.all(result['X'][result['X'][:,col]==0,col-1]==0))
        payload=json.dumps(json_value(result),ensure_ascii=False,allow_nan=False)
        restored=json.loads(payload);check('全出力保存統合',len(restored['specifications'])==32 and len(restored['X'])==len(bars['t_s']))
        return result

    # ----------------------------------------
    # 16期間の算術と欠測後の再seedを、別Fraction計算へ照合する。
    bars,other=fixture(280,'trend');bars['valid'][105]=False
    for key in ('open','high','low','close'):bars[key][105]=np.nan
    base=evaluate(bars,other);close=np.where(bars['valid'],bars['close'],np.nan)
    for col,period in enumerate(f.PERIODS):
        equal('SMA Fraction全16',base['sma'][:,col],oracle_ma(close,period,False))
        equal('EMA Fraction全16',base['ema'][:,col],oracle_ma(close,period,True))
        check('初回warmup',np.isnan(base['ema'][:period-1,col]).all() and np.isfinite(base['ema'][period-1,col]))
        check('欠分後warmup',np.isnan(base['ema'][106:106+period-1,col]).all() and np.isfinite(base['ema'][106+period-1,col]))
    check('最長90候補個別warmup',not base['candidate_known'][:92,3].any() and base['candidate_known'][92,3])
    check('短期を90分まで一律停止しない',base['candidate_known'][:89,0].any())

    # ----------------------------------------
    # 未知の種類を分離し、観測0・分母なし・不足足を混同しない。
    bars,other=fixture(220,'trend');standard=evaluate(bars,other)
    for kind in ('volume','book','peer','anchor'):
        b=copy_arrays(bars);p=copy_arrays(other)
        if kind=='volume':b['volume_known'][70:80]=False;b['volume'][70:80]=np.nan
        elif kind=='book':
            b['book_quote_valid'][70:80]=False
            for key in ('book_imbalance','book_depth','book_ofi'):b[key][70:80]=np.nan
        elif kind=='peer':
            p['matchedNKknown'][70:80]=False
            for key in ('matchedNKclose','return3','return10','efficiency10','matchedNKt_s'):p[key][70:80]=np.nan
        else:b['anchor'][70:80]=np.nan;b['pub_raw_row'][70:80]=-1
        changed=evaluate(b,p);equal('補助欠測は価格MA非変更',changed['ema'],standard['ema'],0)
        equal('補助欠測はSMA非変更',changed['sma'],standard['sma'],0)
        if kind=='anchor':check('公開不能は全候補0',not changed['signals'][70:80].any())
        elif kind=='peer':check('未知peerで二市場0',not changed['signals'][70:80,24:28].any())
        elif kind=='book':check('未知板で板候補0',not changed['signals'][70:80,28:].any())
    b=copy_arrays(bars);b['book_ofi'][100]=np.nan;partial=evaluate(b,other)
    col=partial['names'].index('book_ofi_known');check('正常板だがOFI分母0は未知',partial['X'][100,col]==0)
    col=partial['names'].index('book_depth_known');check('OFI未知でも深さ既知',partial['X'][100,col]==1)
    b=copy_arrays(bars);b['book_depth'][100]=0.;partial=evaluate(b,other)
    col=partial['names'].index('book_depth');check('深さratio実測0既知',partial['X'][100,col]==0 and partial['X'][100,col+1]==1)
    b=copy_arrays(bars);b['volume'][:]=0.;zero=evaluate(b,other)
    col=zero['names'].index('volume_ratio5_known');check('出来高分母0は未知',not zero['X'][:,col].any())
    b=copy_arrays(bars);b['volume'][100]=0.;zero=evaluate(b,other)
    col=zero['names'].index('volume_ratio5');check('正の前平均に実測0は既知0',zero['X'][100,col]==0 and zero['X'][100,col+1]==1)
    b,p=fixture(100,'flat');flat=evaluate(b,p)
    col=flat['names'].index('efficiency10');check('静止の完備効率は既知0',flat['X'][30,col]==0 and flat['X'][30,col+1]==1)
    check('静止MAに偽整列なし',not flat['signals'][:,:4].any())

    # ----------------------------------------
    # 厳密先行peer・当時公開anchor・イベント化の判定順を固定する。
    p=copy_arrays(other);p['matchedNKt_s'][100]=bars['t_s'][100]-59
    rejected=False
    try:f.prepare(bars,p)
    except AssertionError:rejected=True
    check('先行一足不足を拒否',rejected)
    p=copy_arrays(other);p['matchedNKclose']+=900000.;rescaled=evaluate(bars,p)
    equal('NK絶対水準はX不採用',rescaled['X'],standard['X'],0)
    equal('NK絶対水準は採否不採用',rescaled['signals'],standard['signals'],0)
    pattern=np.array([1,1,1,1,0,1,1,1,-1,-1,-1,-1,0,1,1,1])
    known=np.ones(len(pattern),bool);expected=np.zeros(len(pattern),np.int8);expected[[2,7,10,15]]=[1,1,-1,1]
    equal('継続三分の初認定だけ',f._publish(pattern>0,pattern<0,known,3),expected,0)
    known[6]=False;expected[:]=0;expected[[2,10,15]]=[1,-1,1]
    equal('未知跨ぎで確認継続不可',f._publish(pattern>0,pattern<0,known,3),expected,0)
    b,p=fixture(120,'trend');b['valid'][3]=False
    for key in ('open','high','low','close'):b[key][3]=np.nan
    opening=evaluate(b,p);check('欠けた開始15分帯を再作成しない',not opening['candidate_known'][:,14].any())

    # ----------------------------------------
    # 自身の絶対価格・時刻・原row番号を学習値へ持ち込まない。
    bars,other=fixture();original=evaluate(bars,other);translated=copy_arrays(bars)
    for key in ('open','high','low','close','anchor'):translated[key]+=10000.
    shifted=evaluate(translated,other)
    equal('自己の絶対水準をX不採用',shifted['X'],original['X'],2e-8)
    b=copy_arrays(bars);p=copy_arrays(other);b['t_s']+=123456000.;p['matchedNKt_s']+=123456000.;b['pub_raw_row']+=1234567
    reindexed=evaluate(b,p);equal('時刻日付行番号はX不採用',reindexed['X'],original['X'],0)
    equal('時刻日付行番号は採否不採用',reindexed['signals'],original['signals'],0)
    forbidden=('peer_matchedNKclose','peer_age_seconds','close','t_s','pub_raw_row')
    check('生価格と日時特徴なし',not set(forbidden)&set(original['names']))
    check('全MA距離列あり',all(f'{kind}{period}_10pt' in original['names'] for kind in ('ema','sma') for period in f.PERIODS))
    col=original['names'].index('ema20_10pt');equal('MA距離10pt定義',original['X'][19:,col],(original['ema'][19:,f.PERIODS.index(20)]-bars['close'][19:])/10)

    # ----------------------------------------
    # 接頭・未来の全面変更・未知を入れた接頭で現在以前が不変。
    for end in (0,1,14,15,20,45,89,90,95,121,250,419):
        prefixes+=1;b={k:v[:end].copy() for k,v in bars.items()};p={k:v[:end].copy() for k,v in other.items()};prefix=evaluate(b,p)
        for name in ('X','signals','candidate_known','ema','sma','decision_valid'):
            equal('接頭 '+name,prefix[name],original[name][:end],0)
    b=copy_arrays(bars);p=copy_arrays(other);cut=240
    for key in ('open','high','low','close','anchor'):b[key][cut:]+=500000.
    b['volume'][cut:]*=1000;b['book_imbalance'][cut:]*=-1;b['book_depth'][cut:]*=-1;b['book_ofi'][cut:]*=-1
    p['return3'][cut:]*=-1;p['return10'][cut:]*=-1
    future=evaluate(b,p)
    for name in ('X','signals','candidate_known','ema','sma'):equal('未来改変 '+name,future[name][:cut],original[name][:cut],0)
    for data in (bars,other):
        for value in data.values():value.setflags(write=False)
    readonly=evaluate(bars,other);equal('readonly入力',readonly['X'],original['X'],0)
    # ----------------------------------------
    # 定義の安定性と代表的な非同値条件を、人工経路だけで検査する。
    specs=f.specifications();family=Counter(v['family'] for v in specs)
    check('八family四候補',len(family)==8 and set(family.values())=={4})
    check('32定義が全て別',len({v['condition'] for v in specs})==32)
    check('未来語を効果として確定しない',all('未測仮説' in v['limitations'] for v in specs))
    check('異なる条件が人工で実際に異なる',len({original['signals'][:,i].tobytes() for i in range(32)})>=16)
    check('始終source一致',initial==source_hashes())
    return dict(全合格=True,検査数=checks,合成計算数=cases,接頭数=prefixes,source_SHA256=initial,
        期間=list(f.PERIODS),候補数=32,family=dict(family),X列数=len(original['names']),feature_groups=dict(Counter(original['feature_groups'].values())),
        人工経路で事象を出した条件数=int(np.count_nonzero(np.any(original['signals']!=0,axis=0))),
        scope='SOURCE_ONLY。合成配列のみ。実入力/金融/到達結果/学習/採点/API読取0。合格は有効性の実績ではない。',
        保存定義='学習Xは未知0とknown0を組にし、raw MA診断のNaNはJSONのみNoneへ型変換。観測値の補完ではない。',
        定義取得='specifications()は空足から結果前に32条件を取得。')


def main() -> None:
    """
    機能: 人工を一度実行して成功又はFalseを別証跡へ保存する。
    引数: CLI --output(str) は未存在の証跡パス。
    返り値: None。失敗は保存して例外を再送出し、過去成功を上書きしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(HERE/'特徴量32条件とMA欠測因果及び保存統合の人工検査.json'));args=parser.parse_args()
    path=Path(args.output);assert not path.exists(),str(path)
    try:result=run()
    except Exception as exc:
        failure=path.with_name(path.stem+'_False.json');assert not failure.exists()
        failure.write_text(json.dumps(dict(全合格=False,error=repr(exc),source_SHA256=source_hashes(),実入力読取0=True),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');raise
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(全合格=result['全合格'],検査数=result['検査数'],合成計算数=result['合成計算数'],X列数=result['X列数'],証跡=str(path),SHA256=hashlib.sha256(path.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
