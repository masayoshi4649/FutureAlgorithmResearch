"""I2の旧源点及び資格の固定を、旧生行の資格と独立厳密過去索引から照合する。"""

import json
from pathlib import Path
import socket
import sys

import numpy as np

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
sys.path.insert(0,str(HERE))
import check_inputs as A


def main() -> None:
    """
    機能: 全62の旧現在源・各窓旧源・断裂資格を独立再構成し、I2固定対照を確認する。
    引数: なし。
    返り値: None、新JSON一つ。売買・損益計算及び元素材書込みは行わない。
    """
    socket.socket.connect=A.deny;socket.create_connection=A.deny
    material=A.module('旧源索引の独立素材93',ROOT/'work/wave_v93/data.py').load_inputs()
    metadata=A.load(WORK/'prepared_r1/metadata.json')
    lanes=A.load(WORK/'prepared_r1/price_lanes.pkl')
    sources={**metadata['旧入力SHA256'],**metadata['新コードSHA256'],**metadata['新入力SHA256']}
    for path in (WORK/'prepared_r1/metadata.json',Path(A.__file__),Path(__file__)):
        sources[str(path.relative_to(ROOT))]=A.digest(path)
    for relative,expected in sources.items():assert A.digest(ROOT/relative)==expected,relative
    rows=[]
    for key,record in sorted(material['prices'].items()):
        grid=material['grids'][key[0]]['grid'];old=material['grids'][key[0]]['markets'][key[1]]
        coupled=lanes['I2'][key[0]]['markets'][key[1]]
        quality=material['features'][key]['quality'];reset=material['features'][key]['reset'];times=record['time_s']
        now,age=A.source(grid-1.,times,quality,reset)
        A.equal(old['current']['index'],now,'独立旧現在源/'+str(key))
        A.equal(coupled['current']['index'],now,'I2旧現在源維持/'+str(key))
        A.equal(coupled['current']['age'],age,'I2旧現在鮮度/'+str(key))
        broken=np.r_[0,np.cumsum(reset)]
        for seconds in A.WINDOWS:
            old_source,old_age=A.source(grid-1.-seconds,times,quality,reset)
            available=(now>=0)&(old_source>=0)
            crossed=available&((broken[np.maximum(now,0)+1]-broken[np.maximum(old_source,0)+1])>0)
            usable=available&(old_source<now)&~crossed
            expected=dict(old=old_source,now=now,old_age=old_age,source_valid=usable,
                          same_row=available&(old_source==now),reset_or_invalid_cross=crossed)
            for field,value in expected.items():
                A.equal(old['windows'][seconds][field],value,'独立旧窓/'+str(key)+'/'+str(seconds)+'/'+field)
                A.equal(coupled['windows'][seconds][field],value,'I2旧窓維持/'+str(key)+'/'+str(seconds)+'/'+field)
        rows.append(dict(場=key[0],商品=key[1],全現在源及び5窓の源と資格独立一致=True,格子数=len(grid)))
    for relative,expected in sources.items():assert A.digest(ROOT/relative)==expected,('監査途中変更',relative)
    result=dict(全検査合格=True,全31既知=True,口座数=62,独立検算=dict(A.COUNTS),場別検算=rows,
                旧現在源から期待値をコピー=0,旧窓源から期待値をコピー=0,
                旧resetの意味='旧v57は完全10段invalid時に必ずreset bit4を立てるため、旧brokenのinvalid包含と同じ。',
                新損益計算=0,現在API取得=0,実注文=0,SHA256=sources)
    path=HERE/'I2全62の旧源と窓資格の独立厳密過去再構成.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('全62 I2の旧源と資格を独立厳密過去索引で再構成。売買損益0。',flush=True)


if __name__=='__main__':main()
