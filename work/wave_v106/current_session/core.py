"""同じ旧原板入力から、二固定価格反発と旧C対照を途中終端まで準備する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

import common


SESSION='2026-10-13_Night'
SYMBOLS=('TOPIX','NK225')
INPUT_PATH=common.ROOT/'work/wave_v104/holdout_input/core.py'
STATE_PATH=common.HERE/'states_snapshot.py'
holdout=common.module('106現ナイトの不変追加一場collector',INPUT_PATH)
holdout.CACHE=str(common.HERE/'jit')


def range_parts() -> tuple:
    """
    機能: 新R_PRICEの価格特徴/選択/固定設定を通常名衝突なく接続する。
    引数: なし。
    返り値: tuple[object,object,object]は不変features/selection/catalog。
    """
    base=common.ROOT/'work/wave_v106/range_price'
    features=common.module('106現ナイトの不変価格六点',base/'features.py')
    previous=sys.modules.get('features');sys.modules['features']=features
    try:selection=common.module('106現ナイトの不変価格反発選択',base/'selection.py')
    finally:
        if previous is None:sys.modules.pop('features',None)
        else:sys.modules['features']=previous
    catalog=common.module('106現ナイトの結果前24設定',base/'catalog.py')
    return features,selection,catalog


def configs() -> list[dict]:
    """
    機能: 未取得場に対する事前2条件と旧C_ONLY相当だけを返す。
    引数: なし。
    返り値: list[dict]は3対照。歴史結果から任意条件を追加選択しない。
    """
    _,_,catalog=range_parts();values={v['id']:v for v in catalog.catalog()}
    selected=[deepcopy(values[n]) for n in ('AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT')]
    old=deepcopy(selected[0]);old.update(id='C_ONLY_B2_ER40_B4',mode='C_ONLY')
    return selected+[old]


def extract_stream(stream: object, session: str, symbol: str) -> dict:
    """
    機能: NDJSONの一バイト走査をhashし、旧normal/独立LP/44原行v2へ分配する。
    引数: stream(BinaryIO)、session/symbol(str)は場と商品。人工ではBytesIOを渡す。
    返り値: dictは元数学の抽出と本文指紋/行数。場完了は仮定しない。
    """
    hasher=hashlib.sha256();count=0;size=0
    def rows() -> object:
        """
        機能: 同じNDJSON行を一度hashして保存順原seqと共に公開する。
        引数: なし。
        返り値: Iterator[tuple[int,dict]]。空行/非辞書/エラーJSONは推測救済しない。
        """
        nonlocal count,size
        for seq,line in enumerate(stream):
            assert line.strip(),'空NDJSON行'
            hasher.update(line);size+=len(line);value=json.loads(line)
            assert isinstance(value,dict) and 'CurrentPriceTime' in value,'原板JSON以外の本文'
            count+=1;yield seq,value
    value=holdout.extract_rows(rows(),session,symbol)
    value['diagnosis'].update(本文SHA256=hasher.hexdigest(),本文bytes=size,本文行数=count)
    return value


def activity_parts() -> tuple:
    """
    機能: 不変103活動へ同一bytesの私有stateを供給し、旧JITへの書込を避ける。
    引数: なし。
    返り値: tuple[object,object,list]は旧活動/104peer/旧19route。金融は呼ばない。
    """
    original=common.ROOT/'work/wave_v103/activity/states_snapshot.py'
    assert common.digest(STATE_PATH)==common.digest(original)
    with holdout.owned_cache():
        state=common.module('106現ナイト不変103state私有複製',STATE_PATH)
        canonical='103活動の不変状態複製'
        if canonical in sys.modules:
            assert common.digest(Path(sys.modules[canonical].__file__))==common.digest(STATE_PATH)
        else:sys.modules[canonical]=state
        activity=common.module('106現ナイト不変103活動',common.ROOT/'work/wave_v103/activity/core.py')
        def state_provider() -> object:
            """
            機能: 活動関数のstate取得だけを私有同一数学へ置き換える。
            引数: なし。
            返り値: objectは旧103と同一bytesのstate。資格と数値は変更しない。
            """
            return state
        activity.states=state_provider
        catalog=common.module('106現ナイト不変103route',common.ROOT/'work/wave_v103/catalog.py')
        peer=common.module('106現ナイト不変104peer',common.ROOT/'work/wave_v104/peer/api.py')
    return activity,peer,catalog.catalog()


def build(extracted: dict, python: bool=False) -> dict:
    """
    機能: 新2抽出だけを旧完全prepare/C_OWN/純価格sixへ接続し、金融前の入力を作る。
    引数: extracted(dict[symbol,dict])、python(bool)は純人工で状態Pythonを指定する。
    返り値: dictはprepared/cases/measured/quietと対応由来。終了時刻を途中へ変更しない。
    """
    assert set(extracted)==set(SYMBOLS);sessions={v['session'] for v in extracted.values()};assert len(sessions)==1
    session=sessions.pop()
    with holdout.owned_cache():
        material,prepared=holdout.build_material(extracted)
        activity,peer,values=activity_parts()
        raw={s:extracted[s]['raw'] for s in SYMBOLS}
        records={s:prepared[session,s]['record'] for s in SYMBOLS}
        items={s:dict(symbol=s,session=session,raw_rows=len(raw[s]['raw_seq']),normal_execution_rows=len(records[s]['seq']),
            **{n:records[s][n] for n in ('start','end','limit','tick')}) for s in SYMBOLS}
        activity_packet=activity.build_session(session,raw,items,values,python=python)
        peer_packet=peer.prepared_session(activity_packet,records)
    F,_,_=range_parts()
    TIME=common.module('106現ナイトの同一Jtimer',common.ROOT/'work/wave_v106/time_guard/time_windows.py')
    result=dict(schema_version=1,session=session,prepared={s:prepared[session,s] for s in SYMBOLS},cases={},measured={},quiet={},
        raw=raw,activity=activity_packet,peer=peer_packet,references=material['metadata']['references'],途中終端=True)
    for symbol in SYMBOLS:
        assert peer_packet['normal'][symbol]['record'] is records[symbol]
        result['cases'][symbol]={entry:peer_packet['cases'][entry][symbol]['normal'] for entry in ('C_OWN','R_OWN')}
        result['measured'][symbol]=F.build(raw,records,symbol)
        q=TIME.features(records[symbol],'J');result['quiet'][symbol]=dict(active=q['quiet'],start_s=q['quiet_start_s'],windows=q['windows'])
        assert records[symbol]['limit']==records[symbol]['end']-300.
        assert result['references'][session+'|'+symbol]['ref_open']['known_from_i']==0
    return result


def normal(packet: dict, symbol: str, config: dict) -> dict:
    """
    機能: 二つのR_PRICE固定条件又は同状態C_ONLYの元C正常列を選ぶ。
    引数: packet(dict)、symbol(str)、config(dict)は準備入力と3条件。
    返り値: dictは固定R_PRICEengineのnormalケース。元Cの非event資格も保持する。
    """
    _,selection,_=range_parts()
    if config['mode']!='C_ONLY':return selection.build(packet,symbol,config)
    value=selection.build(packet,symbol,dict(config,mode='AUTO'))
    c=packet['cases'][symbol]['C_OWN'];keep=value['entry_families']==1
    value['event'][~keep]=0;value['support_price'][~keep]=np.nan
    value['entry_quality']=c['entry_quality'].copy();value['entry_reset']=c['entry_reset'].copy()
    value['entry_families'][~keep]=0;value['entry_modes'][~keep]=0
    for field in ('target_prices','entry_stop_prices','entry_limit_prices'):value[field][:]=np.nan
    value['decisions']=[v for v in value['decisions'] if keep[int(v['row'])]]
    value['entry_id']=config['id'];return value
