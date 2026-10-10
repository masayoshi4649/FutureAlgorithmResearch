"""固定26入口の先行価格だけを同じ発火標本で診断し、口座損益と分離する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import pickle
from datetime import datetime, timezone, timedelta

import numpy as np
from numba import njit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE/'forward'
HORIZONS = (5, 15, 30, 60)
JST = timezone(timedelta(hours=9))
CENTRAL = 'M100_S100_P1_C1_D100'


def sha(path: Path) -> str:
    """機能: 固定された実装・信号・旧入力の内容指紋を返す。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8388608):
            result.update(block)
    return result.hexdigest()


def save_json(path: Path, value: dict) -> None:
    """機能: 非有限値を拒否して日本語JSONを新作業へ保存する。

    引数: path (Path)、value (dict)。返り値: なし (None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


def save_csv(path: Path, rows: list[dict]) -> None:
    """機能: 同じ列を持つ診断値をUTF-8 CSVへ保存する。

    引数: path (Path)、rows (list[dict])。返り値: なし (None)。
    """
    assert rows
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read(path: Path) -> dict:
    """機能: 保存された日本語JSONを読み込む。

    引数: path (Path)。返り値: 記録 (dict)。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def fire_rows(state: np.ndarray) -> np.ndarray:
    """機能: 中立から非ゼロ又は反対方向へ変わった行を列挙する。

    引数: state (ndarray[int8])。返り値: 発火原本行の昇順列 (ndarray[int64])。
    同方向の保持・更新は重ねて発火と数えない。
    """
    previous=np.zeros_like(state)
    previous[1:]=state[:-1]
    return np.flatnonzero((state!=0)&(state!=previous)).astype(np.int64)


@njit(cache=True)
def label_arrays(time: np.ndarray, price: np.ndarray, atr: np.ndarray,
                 state: np.ndarray, fires: np.ndarray, deadline: float) -> np.ndarray:
    """機能: 発火後の評価用値動きを厳密な次行価格から計算する。

    引数: time/price/atr/state/fires (ndarray)、deadline (float)。
    返り値: 発火×4期間×8列の評価配列 (ndarray[float64])。
    列は状態、基準行、評価行、基準ATR、符号付変化ATR、最大順行ATR、最大逆行ATR、到達遅れ秒。
    状態0は有効、1は次行なし、2は基準価格又はATR無効、3は期限不足。
    """
    result=np.full((len(fires),4,8),np.nan)
    horizons=np.array([5.,15.,30.,60.])
    n=len(time)
    for f in range(len(fires)):
        row=fires[f]
        entry=row+1
        for h in range(4):
            result[f,h,1]=entry
            if entry>=n:
                result[f,h,0]=1
                continue
            a=atr[row]
            result[f,h,3]=a
            if not np.isfinite(a) or a<=0 or not np.isfinite(price[entry]) or price[entry]<=0:
                result[f,h,0]=2
                continue
            target=time[entry]+horizons[h]*60.
            end=np.searchsorted(time,target)
            if time[entry]>deadline or target>deadline or end>=n or time[end]>deadline:
                result[f,h,0]=3
                continue
            high=price[entry]
            low=price[entry]
            valid=True
            for index in range(entry,end+1):
                p=price[index]
                if not np.isfinite(p) or p<=0:
                    valid=False
                    break
                high=max(high,p)
                low=min(low,p)
            if not valid:
                result[f,h,0]=2
                continue
            d=state[row]
            result[f,h,0]=0
            result[f,h,2]=end
            result[f,h,4]=d*(price[end]-price[entry])/a
            result[f,h,5]=(high-price[entry])/a if d==1 else (price[entry]-low)/a
            result[f,h,6]=(price[entry]-low)/a if d==1 else (high-price[entry])/a
            result[f,h,7]=time[end]-target
    return result


def synthetic() -> dict:
    """機能: 同秒次行、評価期間、不足標本、上下対称を手計算で検査する。

    引数: なし。返り値: 合格数と破損検知記録 (dict)。
    """
    np.testing.assert_array_equal(fire_rows(np.array([0,1,1,0,-1,1,1,0],np.int8)),[1,4,5])
    time=np.array([0.,0.,300.,900.,1800.,3600.,3601.])
    price=np.array([500.,100.,110.,90.,120.,80.,200.])
    atr=np.full(7,10.)
    state=np.ones(7,np.int8)
    result=label_arrays(time,price,atr,state,np.array([0]),3600.)[0]
    np.testing.assert_array_equal(result[:,0],np.zeros(4))
    np.testing.assert_array_equal(result[:,1],np.ones(4))
    np.testing.assert_array_equal(result[:,2],[2,3,4,5])
    np.testing.assert_allclose(result[:,4],[1,-1,2,-2])
    np.testing.assert_allclose(result[:,5],[1,1,2,2])
    np.testing.assert_allclose(result[:,6],[0,1,1,2])
    inverse=label_arrays(time,price,atr,-state,np.array([0]),3600.)[0]
    np.testing.assert_array_equal(inverse[:,4],-result[:,4])
    np.testing.assert_array_equal(inverse[:,5],result[:,6])
    np.testing.assert_array_equal(inverse[:,6],result[:,5])
    reflected=label_arrays(time,1000-price,atr,-state,np.array([0]),3600.)[0]
    np.testing.assert_allclose(reflected,result)
    no_time=label_arrays(time,price,atr,state,np.array([0]),3599.)[0]
    assert no_time[-1,0]==3 and np.all(no_time[:-1,0]==0)
    no_next=label_arrays(time,price,atr,state,np.array([6]),3601.)
    assert np.all(no_next[:,:,0]==1)
    missing=atr.copy()
    missing[0]=np.nan
    invalid=label_arrays(time,price,missing,state,np.array([0]),3600.)
    assert np.all(invalid[:,:,0]==2)
    # ----------------------------------------
    # 未来を参照する箇所をラベルに閉じ、発火列は未来価格へ依存しない。
    changed=price.copy()
    changed[-1]=99999.
    np.testing.assert_array_equal(label_arrays(time,changed,atr,state,np.array([0]),3600.),
                                  label_arrays(time,price,atr,state,np.array([0]),3600.))
    return dict(全合格=True,発火定義=True,発火行価格を使わず同秒次行価格=True,
        四期間の変化順行逆行手計算=True,逆方向対照=True,価格方向反射=True,
        期限不足をゼロ損益としない=True,次行欠損=True,ATR欠損=True,期限後価格の不使用=True)


def freeze() -> dict:
    """機能: 新しい評価値を読む前に仕様と全入力指紋を固定する。

    引数: なし。返り値: 固定規則 (dict)。既存固定がある場合は完全一致を要求する。
    """
    OUT.mkdir(exist_ok=True)
    fixed=read(HERE/'component_signals_fixed.json')
    proof=synthetic()
    refs={str((HERE/'component_signals_fixed.json').relative_to(ROOT)).replace('\\','/'):sha(HERE/'component_signals_fixed.json'),
          str(Path(__file__).relative_to(ROOT)).replace('\\','/'):sha(Path(__file__)),
          'work/wave_v23/inputs.pkl':sha(HERE.parent/'wave_v23/inputs.pkl'),
          **fixed['入口保存列SHA256']}
    for path,digest in fixed['入口保存列SHA256'].items():
        assert sha(ROOT/path)==digest
    value=dict(規則='入口の先行価格診断。口座利益・注文損益ではない。',条件=fixed['条件'],
        対象='9/21デイ～9/29デイの旧13セッション、両銘柄26入力だけ。追加9/29ナイトは除外。',
        発火='中立から非ゼロ又は反対方向への遷移。前回方向保持は発火に数えない。',
        基準='発火原本行の厳密な次の行のlast。ATRは発火行の公開値。数量・費用・約定注文は扱わない。',
        期間分=list(HORIZONS),期限='ready.limitの返済要求期限と観測最終時刻の早い方。',
        評価='次行時刻から期間経過後の最初の原本行。期限を超えれば不足。最大順行・逆行は次行から評価行まで。',
        主標本='60分まで評価可能な共通発火集合を全4期間へ使用。',
        補助標本='各期間で評価可能な全発火。主標本と混同しない。',
        集計='各セッション・銘柄別に平均し、活動セッションの平均値を等重み集計。欠測セッション数を残す。',
        注意='発火が重なり、銘柄も相関する。発火数は独立標本数ではない。期間・設定の最良値を選び直さない。',
        新ナイト読取=False,新売買損益読取=False,売買再生=False,API取得数=0,人工=proof,参照SHA256=refs)
    path=OUT/'先行価格診断の事前固定.json'
    if path.exists():
        assert read(path)==value,'固定仕様は上書きしません'
    else:
        save_json(path,value)
    return value


def summarize(values: np.ndarray) -> dict:
    """機能: 有効標本だけの値動きと順行・逆行を集計する。

    引数: values (ndarray[n,8]) は同一期間のラベル。返り値: 件数と平均・中央値 (dict)。
    標本なしを収益ゼロとして代入しない。
    """
    if not len(values):
        return dict(評価数=0,順方向数=0,逆方向数=0,同値数=0,順方向率=None,
                    平均変化ATR=None,中央値変化ATR=None,平均最大順行ATR=None,平均最大逆行ATR=None,
                    平均到達遅れ秒=None,最大到達遅れ秒=None)
    ret=values[:,4]
    return dict(評価数=len(values),順方向数=int((ret>0).sum()),逆方向数=int((ret<0).sum()),
        同値数=int((ret==0).sum()),順方向率=float((ret>0).mean()),平均変化ATR=float(ret.mean()),
        中央値変化ATR=float(np.median(ret)),平均最大順行ATR=float(values[:,5].mean()),
        平均最大逆行ATR=float(values[:,6].mean()),平均到達遅れ秒=float(values[:,7].mean()),
        最大到達遅れ秒=float(values[:,7].max()))


def calculate(protocol: dict) -> tuple[list, list, list]:
    """機能: 旧入力と固定方向列だけから全発火・期間・セッションを集計する。

    引数: protocol (dict)。返り値: 発火別評価・セッション集計・層別集計 (tuple[list,list,list])。
    """
    inputs=pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    assert len(inputs)==26 and not any(key[0]=='2026-09-29_Night' for key in inputs)
    specs=protocol['条件']
    events=[]
    sessions=[]
    for spec in specs:
        identifier=spec['id']
        with np.load(HERE/'component_entries'/(identifier+'.npz')) as archive:
            assert set(archive.files)=={'|'.join(key) for key in inputs}
            for key,ready in sorted(inputs.items()):
                state=archive['|'.join(key)]
                assert len(state)==len(ready['last']) and np.isin(state,[-1,0,1]).all()
                assert np.all(np.diff(ready['time_s'])>=0)
                fires=fire_rows(state)
                deadline=min(float(ready['limit']),float(ready['time_s'][-1]))
                labels=label_arrays(ready['time_s'],ready['last'],ready['atr'],state,fires,deadline)
                common=labels[:,3,0]==0
                market='デイ' if key[0].endswith('_Day') else 'ナイト'
                for f,row in enumerate(fires):
                    entry=int(row)+1
                    entry_ok=entry<len(state)
                    for h,minutes in enumerate(HORIZONS):
                        values=labels[f,h]
                        code=int(values[0])
                        end=int(values[2]) if code==0 else None
                        events.append(dict(手法ID=identifier,セッション=key[0],銘柄=key[1],場=market,
                            発火行=int(row),発火seq=int(ready['seq'][row]),方向=int(state[row]),
                            発火時刻=datetime.fromtimestamp(ready['time_s'][row],JST).isoformat(),
                            基準行=entry if entry_ok else None,
                            基準時刻=datetime.fromtimestamp(ready['time_s'][entry],JST).isoformat() if entry_ok else None,
                            基準価格=float(ready['last'][entry]) if entry_ok else None,
                            当時ATR=float(ready['atr'][row]) if np.isfinite(ready['atr'][row]) else None,
                            期間分=minutes,状態=('有効','次行なし','価格又はATR無効','期限不足')[code],
                            共通60分標本=bool(common[f]),評価行=end,
                            評価時刻=datetime.fromtimestamp(ready['time_s'][end],JST).isoformat() if end is not None else None,
                            評価価格=float(ready['last'][end]) if end is not None else None,
                            符号付変化ATR=float(values[4]) if code==0 else None,
                            最大順行ATR=float(values[5]) if code==0 else None,
                            最大逆行ATR=float(values[6]) if code==0 else None,
                            到達遅れ秒=float(values[7]) if code==0 else None))
                for side,label in ((0,'両方向'),(1,'買い'),(-1,'売り')):
                    side_mask=np.ones(len(fires),bool) if side==0 else state[fires]==side
                    for h,minutes in enumerate(HORIZONS):
                        status=labels[:,h,0]
                        for cohort in ('共通60分','期間別全有効'):
                            eligible=side_mask&(common if cohort=='共通60分' else status==0)
                            summary=summarize(labels[eligible,h,:])
                            sessions.append(dict(手法ID=identifier,セッション=key[0],銘柄=key[1],場=market,
                                方向区分=label,期間分=minutes,標本=cohort,発火数=int(side_mask.sum()),
                                次行なし数=int((side_mask&(status==1)).sum()),
                                無効価格ATR数=int((side_mask&(status==2)).sum()),
                                期限不足数=int((side_mask&(status==3)).sum()),
                                共通60分除外数=int((side_mask&~common&(status==0)).sum()),**summary))
        print(identifier+'：先行価格ラベル完了',flush=True)
    # ----------------------------------------
    # 発火数で重み付けせず、活動セッションの平均を等重みにする。
    grouped=[]
    for spec in specs:
        for symbol in ('TOPIX','NK225'):
            for market in ('全場','デイ','ナイト'):
                for side in ('両方向','買い','売り'):
                    for minutes in HORIZONS:
                        for cohort in ('共通60分','期間別全有効'):
                            selected=[row for row in sessions if row['手法ID']==spec['id'] and row['銘柄']==symbol
                                and (market=='全場' or row['場']==market) and row['方向区分']==side
                                and row['期間分']==minutes and row['標本']==cohort]
                            active=[row for row in selected if row['評価数']]
                            result=dict(手法ID=spec['id'],銘柄=symbol,場=market,方向区分=side,
                                期間分=minutes,標本=cohort,全セッション数=len(selected),
                                評価セッション数=len(active),欠測セッション数=len(selected)-len(active),
                                発火数=sum(row['発火数'] for row in selected),評価数=sum(row['評価数'] for row in selected),
                                次行なし数=sum(row['次行なし数'] for row in selected),
                                無効価格ATR数=sum(row['無効価格ATR数'] for row in selected),
                                期限不足数=sum(row['期限不足数'] for row in selected),
                                共通60分除外数=sum(row['共通60分除外数'] for row in selected),
                                正平均セッション数=sum(row['平均変化ATR']>0 for row in active),
                                負平均セッション数=sum(row['平均変化ATR']<0 for row in active))
                            for column in ('平均変化ATR','平均最大順行ATR','平均最大逆行ATR','順方向率'):
                                result['場等重み'+column]=float(np.mean([row[column] for row in active])) if active else None
                            result['最悪場平均変化ATR']=min(row['平均変化ATR'] for row in active) if active else None
                            result['最良場平均変化ATR']=max(row['平均変化ATR'] for row in active) if active else None
                            result['最大到達遅れ秒']=max(row['最大到達遅れ秒'] for row in active) if active else None
                            grouped.append(result)
    return events,sessions,grouped


def run() -> None:
    """機能: 固定を照合して旧入力の先行価格診断と全明細を保存する。

    引数: なし。返り値: なし (None)。採用手法の変更や口座収益の再計算を行わない。
    """
    protocol=freeze()
    for path,digest in protocol['参照SHA256'].items():
        assert sha(ROOT/path)==digest,path
    events,sessions,groups=calculate(protocol)
    assert len(sessions)==26*26*3*4*2 and len(groups)==26*2*3*3*4*2
    assert len(events)%4==0
    save_csv(OUT/'全発火と先行価格.csv',events)
    save_csv(OUT/'セッション別先行価格.csv',sessions)
    save_csv(OUT/'場別銘柄別先行価格.csv',groups)
    save_json(OUT/'先行価格診断.json',dict(全合格=True,口座利益ではない=True,
        事前固定SHA256=sha(OUT/'先行価格診断の事前固定.json'),入力数=26,手法数=26,
        延べ発火数=len(events)//4,評価行数=len(events),セッション集計数=len(sessions),層別集計数=len(groups),
        セッション別=sessions,層別=groups,新ナイト読取=False,新売買損益読取=False,売買再生=False,API取得数=0))
    for path,digest in protocol['参照SHA256'].items():
        assert sha(ROOT/path)==digest,path
    save_json(OUT/'実行検査.json',dict(全合格=True,入力指紋不変=True,
        発火数=len(events)//4,全発火記録SHA256=sha(OUT/'全発火と先行価格.csv'),
        セッションCSV_SHA256=sha(OUT/'セッション別先行価格.csv'),層別CSV_SHA256=sha(OUT/'場別銘柄別先行価格.csv'),
        JSON_SHA256=sha(OUT/'先行価格診断.json')))
    print(json.dumps(dict(全合格=True,発火数=len(events)//4,評価行数=len(events)),ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true')
    args=parser.parse_args()
    if args.freeze:
        freeze()
        print('旧26入力・入口26条件の先行価格診断を損益前に固定しました',flush=True)
    else:
        run()
