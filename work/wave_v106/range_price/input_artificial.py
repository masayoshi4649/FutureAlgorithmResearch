"""新R_PRICEの六点共有・尾部資格・境界反発と料込RRを純人工で検査する。"""

from copy import deepcopy

import numpy as np

import catalog
import common
import features
import selection


def fixture() -> tuple[dict,dict,dict]:
    """
    機能: 両市場の六点往復と、同時計内で下端から1tick反発する私有素材を作る。
    引数: なし。
    返り値: tuple[dict,dict,dict]はraws、normalrecords、旧C候補。
    """
    times=np.array([0.,60.,120.,180.,240.,300.,300.,300.,300.,310.])
    mids=np.array([101.,111.,101.,111.,105.,102.,100.,101.,102.,102.])
    raws,records,cases={},{},{}
    for symbol in ('TOPIX','NK225'):
        n=len(times);seq=np.arange(200,200+n,dtype=np.int64);bid=mids-.5;ask=mids+.5
        mapping=np.arange(n,dtype=np.int64)
        raws[symbol]=dict(raw_seq=seq,price_time_s=times.copy(),bid=bid.copy(),ask=ask.copy(),execution_to_raw_index=mapping)
        records[symbol]=dict(symbol=symbol,seq=seq,time_s=times.copy(),bid=bid.copy(),ask=ask.copy(),price=mids.copy(),
            quote_valid=np.ones(n,bool),price_valid=np.ones(n,bool),tick=1.,start=0.,end=1000.,limit=900.)
        cases[symbol]=dict(event=np.zeros(n,np.int8),support_price=np.full(n,np.nan),entry_quality=np.zeros(n,bool),
            entry_reset=np.ones(n,bool),execution_to_raw_index=mapping,decisions=[])
    # 相手は自己300秒に対してstrictpastの終点を持つよう最後の新最大を299へずらす。
    raws['NK225']['price_time_s'][5:9]=299.;records['NK225']['time_s'][5:9]=299.
    return raws,records,cases


def run() -> None:
    """
    機能: 同時計の尾部逆行/seq・同時計未来・RR丸め・量分離とAUTOを人工検証する。
    引数: なし。
    返り値: None。原本と金融結果を読まず所有域に証跡を保存する。
    """
    raws,records,cases=fixture();measured={s:features.build(raws,records,s) for s in ('TOPIX','NK225')};checks=[]
    own=measured['TOPIX'];assert own['boundary_events']['0.2'][7]==1
    assert own['states']['0.2'][7]==1 and own['sample_tables']['own']['rows'][own['normal_sample_index'][7],-1]==5
    checks.append('量/resetなしの両市場six RANGEと、実当行BBOの下端反発を独立に測る')
    for symbol in ('TOPIX','NK225'):
        record=records[symbol];raw=raws[symbol];other='NK225' if symbol=='TOPIX' else 'TOPIX'
        ctx={s:features.legacy.context(raws[s],start=0.,limit=900.) for s in (symbol,other)}
        for row in range(len(record['seq'])):
            index=int(measured[symbol]['normal_sample_index'][row]);stamp=float(record['time_s'][row])
            oracle=features.legacy.sample(raw,ctx[symbol],stamp,record['tick'],row,False)
            observed=features.at_row(measured[symbol]['sample_tables']['own'],index,
                bool(measured[symbol]['own_known'][row]),int(measured[symbol]['own_reason'][row]))
            assert oracle==observed,(symbol,row,oracle,observed)
            oracle_peer=features.legacy.sample(raws[other],ctx[other],stamp,records[other]['tick'],None,True)
            assert oracle_peer==features.at_row(measured[symbol]['sample_tables']['peer'],index)
    checks.append('全人工normalの共有six値と旧第二版sampleが自己/peerで完全同値')
    broken={s:{k:(v.copy() if isinstance(v,np.ndarray) else v) for k,v in raw.items()} for s,raw in raws.items()}
    broken['TOPIX']['raw_seq'][7:]+=1
    broken_records={s:dict(record) for s,record in records.items()};broken_records['TOPIX']=dict(records['TOPIX'],seq=broken['TOPIX']['raw_seq'])
    invalid=features.build(broken,broken_records,'TOPIX')
    assert own['own_known'][7] and not invalid['own_known'][7] and invalid['own_reason'][7]&8
    checks.append('同PriceTimeの後半seq断裂は各候補尾部へ反映し、先頭knownを使い回さない')
    prepared={s:dict(record=records[s],reference_open=100.,signal=dict(trend_width=2.)) for s in records}
    packet=dict(prepared=prepared,cases={s:dict(C_OWN=cases[s]) for s in records},measured=measured)
    config=next(c for c in catalog.catalog() if c['mode']=='R_ONLY' and c['range_er']==.2 and c['margin_ticks']==4 and c['range_entry']=='LIMIT')
    R=selection.range_arrays(prepared['TOPIX'],own,config)
    assert R['allowed'][7] and R['target'][7]==106. and R['stop'][7]==97.
    assert R['planned_entry'][7]==100.5 and R['stop_clearance_ticks'][7]==3.5
    shallow=selection.range_arrays(prepared['TOPIX'],own,dict(config,margin_ticks=1))
    assert not shallow['allowed'][7] and shallow['rejection'][7]==2
    checks.append('停止余裕2tick未満は固定停止を捏造して延長せず入口拒否')
    market=selection.range_arrays(prepared['TOPIX'],own,dict(config,range_entry='MARKET'))
    assert not market['allowed'][7] and market['rejection'][7]==5
    checks.append('同じ反発でも成行予定askの費用RRが不足すれば拒否、指値有利さを混ぜない')
    checks.append('丸めたtarget/stopと当時指値から料込RRを測る')
    normal=selection.build(packet,'TOPIX',config)
    assert normal['event'][7]==1 and normal['entry_quality'][7] and not normal['entry_reset'][7]
    assert normal['entry_families'][7]==2 and normal['decisions'][0]['selected_support_roots']==[]
    checks.append('純価格反発は旧C量不明/resetに救済を足さず別資格、架空板rootsなし')
    outside_raw=deepcopy(raws);outside_records=deepcopy(records)
    for key in ('bid','ask'):
        outside_raw['TOPIX'][key][6:8]-=.5;outside_records['TOPIX'][key][6:8]-=.5
    outside=features.build(outside_raw,outside_records,'TOPIX')
    assert outside['states']['0.2'][7]==1 and outside['boundary_events']['0.2'][7]==0
    checks.append('まだ固定sampleLow未満の反発は範囲内回復ではなく入口候補から除外')
    reflected_raw=deepcopy(raws);reflected_records=deepcopy(records)
    for s in records:
        b,a=raws[s]['bid'],raws[s]['ask']
        reflected_raw[s]['bid']=212.-a;reflected_raw[s]['ask']=212.-b
        reflected_records[s]['bid']=212.-a;reflected_records[s]['ask']=212.-b
    reflected=features.build(reflected_raw,reflected_records,'TOPIX')
    sell=selection.range_arrays(dict(prepared['TOPIX'],record=reflected_records['TOPIX']),reflected,config)
    assert reflected['boundary_events']['0.2'][7]==-1 and sell['allowed'][7]
    assert sell['target'][7]==106. and sell['stop'][7]==115. and sell['planned_entry'][7]==111.5
    checks.append('価格反射でも上端売りと停止上側が対称。利確丸めは買floor/売ceil')
    fractional=deepcopy(own)
    fractional['sample_tables']['own']['centre']+=.2
    fractional_sell=deepcopy(reflected);fractional_sell['sample_tables']['own']['centre']+=.2
    assert selection.range_arrays(prepared['TOPIX'],fractional,config)['target'][7]==106.
    assert selection.range_arrays(dict(prepared['TOPIX'],record=reflected_records['TOPIX']),fractional_sell,config)['target'][7]==107.
    checks.append('中心非整数でも保守的な買floor/売ceilを予定RRそのものへ使用')
    short_raw={s:{k:v[:9].copy() for k,v in r.items()} for s,r in raws.items()}
    short_records={s:{k:(v[:9].copy() if isinstance(v,np.ndarray) else v) for k,v in r.items()} for s,r in records.items()}
    prefix=features.build(short_raw,short_records,'TOPIX')
    for key in ('own_known','own_reason','peer_known','qok','previous_normal_row'):
        np.testing.assert_array_equal(prefix[key],own[key][:9])
    for key in ('states','boundary_events'):
        for er in ('.2','.4'):
            value='0'+er;np.testing.assert_array_equal(prefix[key][value],own[key][value][:9])
    checks.append('後の時計/気配を追加しても先行原rowの観測と反発は完全不変')
    reversed_raw=deepcopy(raws);reversed_records=deepcopy(records)
    reversed_raw['TOPIX']['price_time_s'][7]=299.5;reversed_records['TOPIX']['time_s'][7]=299.5
    reversed_value=features.build(reversed_raw,reversed_records,'TOPIX')
    assert not reversed_value['own_known'][7] and not reversed_value['own_known'][8]
    checks.append('同時計後半のhighwater価格逆行は次行で時計が戻っても窓を未知にする')
    auto_packet=deepcopy(packet);old=auto_packet['cases']['TOPIX']['C_OWN'];old['event'][9]=1
    old['support_price'][9]=100.;old['entry_quality'][9]=True;old['entry_reset'][9]=False
    old['decisions']=[dict(row=9,normal_row=9,raw_row=9,raw_seq=209,side=1,support_price=100.,
        selected_support_roots=[dict(anchor_raw_seq=201,support_price=100.)],episode=('旧C',201))]
    auto_packet['measured']['TOPIX']['states']['0.2'][9]=2
    auto=selection.build(auto_packet,'TOPIX',dict(config,mode='AUTO'))
    assert auto['entry_families'][7]==2 and auto['entry_families'][9]==1
    assert auto['decisions'][-1]==old['decisions'][0]
    assert auto['entry_quality'][9]==old['entry_quality'][9] and auto['entry_reset'][9]==old['entry_reset'][9]
    checks.append('AUTOのRANGEはRを先、その他TRENDは旧C当時pulseと支持roots/資格をexact保持')
    common.write(common.HERE/'範囲内反発とAUTO接頭及び料込RRの人工検査.json',dict(全合格=True,検査数=len(checks),検査=checks,
        source_SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in
            [common.HERE/n for n in ('common.py','catalog.py','features.py','selection.py','input_artificial.py')]
            +[common.ROOT/'work/wave_v106/regime_price/features.py']},新金融=0,原板=0,API=0))
    print('six境界反発の入力人工合格',flush=True)


if __name__=='__main__':
    run()
