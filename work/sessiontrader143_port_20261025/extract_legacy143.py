"""主担当源の照合用に、既存E01方向とLast系/中値系履歴を保存入力から追加抽出する。"""

from pathlib import Path
import argparse
import ast
import pandas as pd
import numpy as np
from extract_fixture143 import HERE, ROOT, SCENES, shared, matrix, write_json, digest


def rebuild_gates(packet):
    """
    機能: 凍結済み三関数をそのまま読み、既存ATRと公開済み一分足からG許可だけを再準備する。
    引数: packet(dict) は保存原行・方向・ATR。
    返り値: tuple[dict,dict] は市場別許可と読取元指紋。売買関数を読み込まない。
    """
    source=ROOT/'work/stability126_20261019/engine/legacy_root/work/wave_v49/gates/gate_replay.py'
    selected=('model_from_bars','expanded','gate_mask')
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in selected]
    assert len(nodes)==3
    namespace=dict(np=np,pd=pd)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source),'exec'),namespace)
    refs={str(source.relative_to(ROOT)):digest(source)};models={}
    for key,r in packet['inputs'].items():
        scene,symbol=key
        path=ROOT.parent/f'JP_OSE_Data/future/{symbol}/{scene}/candle_1min.csv'
        refs['../'+str(path.relative_to(ROOT.parent)).replace('\\','/')]=digest(path)
        frame=pd.read_csv(path)
        available=pd.to_datetime(frame.time).dt.as_unit('ns').astype('int64').to_numpy(float)/1e9+120
        valid=frame.closed.astype(str).str.lower().eq('true').to_numpy(copy=True)
        valid&=(available>=r['start']+120)&(available<=r['time_s'][-1])
        times=available[valid];close=frame.loc[valid,'close'].astype(float).to_numpy()
        assert np.all(np.diff(times)>0)
        index=np.searchsorted(r['time_s'],times,side='right')-1
        atr=np.full(len(times),np.nan);ok=index>=0;atr[ok]=r['atr'][index[ok]]
        models[key]=namespace['model_from_bars'](dict(time_s=times,close=close,atr=atr))
    result={}
    for key,r in packet['inputs'].items():
        own,peer=namespace['expanded'](key,models,r['time_s'])
        result[key]=namespace['gate_mask'](dict(kind='rearm'),packet['features'][key]['columns'][0],own,peer)
    return result,refs


def main():
    """
    機能: 元packetの当時方向・退出材料・二市場履歴だけを別フォルダへ抽出する。
    引数: --all は50場、--rebuild-gates は公開足から不足Gを再準備、--output は出力位置。
    返り値: None。E01の売買核・新しい金融再生は呼ばない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--all',action='store_true');parser.add_argument('--rebuild-gates',action='store_true')
    parser.add_argument('--output',type=Path,default=HERE/'fixtures/legacy');args=parser.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    packets,_,_=shared.material();packets={p['session']:p for p in packets}
    all_cases=[]
    for scene in list(packets) if args.all else SCENES:
        packet=shared.packet_from(packets[scene])
        feature_module=shared.prior.common.features129
        _,lastmarket,lasthistory,_=feature_module.build(packet,'last',0.)
        _,midmarket,_,_=feature_module.build(packet,'mid',0.)
        fields={}; gate_available={}; refs={packets[scene]['path']:packets[scene]['sha256']}
        permissions_path=ROOT/'work/stability126_20261019/rearm126/追加十一場のＧ入口許可.npz'
        with np.load(permissions_path) as z: permissions={name:z[name] for name in z.files}
        rebuilt={};gate_checks={}
        if args.rebuild_gates:
            rebuilt,source_refs=rebuild_gates(packet);refs.update(source_refs)
        for symbol in ('NK225','TOPIX'):
            key=scene,symbol;p=packet['features'][key];col=p['columns'];valid=p['valid']
            gate=packet.get('gates',{}).get(key)
            if gate is None and symbol+'_'+scene in permissions:
                gate=permissions[symbol+'_'+scene];refs[str(permissions_path.relative_to(ROOT))]=digest(permissions_path)
            if gate is not None and key in rebuilt:
                np.testing.assert_array_equal(gate,rebuilt[key],err_msg=scene+'/'+symbol+'保存G許可との不一致')
                gate_checks[symbol]='保存Gと全行一致'
            if gate is None and key in rebuilt:
                gate=rebuilt[key];gate_checks[symbol]='元凍結三関数で非金融再準備'
            gate_available[symbol]=gate is not None
            direction=np.where(gate,col[0],0) if gate is not None else np.full(len(col[0]),np.nan)
            state=np.column_stack((col[0],direction,np.where(valid,col[1],0),col[2]))
            stem=f'{symbol}_{scene}'
            market_columns=['自己価格','相手価格','自己ATR','相手ATR','自己30秒','自己120秒','相手30秒','相手120秒','相手時計','自己30秒基準時計','相手30秒基準時計','正常']
            fields[symbol]=dict(
                e01=matrix(out/(stem+'_e01.f64.gz'),state,['元方向','開始再許可方向','悪化方向','悪化元行']),
                day_market=matrix(out/(stem+'_daymarket.f64.gz'),packet['markets'][key],market_columns),
                last_market=matrix(out/(stem+'_lastmarket.f64.gz'),lastmarket[key],market_columns),
                mid_market=matrix(out/(stem+'_midmarket.f64.gz'),midmarket[key],market_columns),
                last_history=matrix(out/(stem+'_lasthistory.f64.gz'),lasthistory[key],feature_module.features128.NAMES))
        path=out/(scene+'_legacy.json.gz')
        write_json(path,dict(session=scene,matrices=fields,
            references=refs,e01_gate_available=gate_available,gate_checks=gate_checks,
            explanation='E01.Direction と GateDirection は開始再許可方向、Adverse は悪化方向。元方向を開始許可なしで新規へ使わない。G未知の場は主担当入口再生成に使わない。'),True)
        all_cases.append(dict(session=scene,file=path.name,sha256=digest(path),e01_gate_available=gate_available,gate_checks=gate_checks))
        print(scene,'既存主担当向け特徴の抽出完了',flush=True)
    write_json(out/'manifest.json',dict(cases=all_cases,new_financial_replays=0,source_sha256=digest(Path(__file__))))


if __name__=='__main__':main()
