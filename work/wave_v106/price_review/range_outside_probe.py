"""範囲外の反発がquarter候補に入った旧草案を、金融前の小人工で記録する。"""

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/range_price'


def main() -> None:
    """
    機能: 同時計の当時midがsample L未満の時、候補と料金RRの扱いを確認する。
    引数: なし。人工factoryだけを使用し正式素材を読まない。
    返り値: Noneは当時source指紋と修正要否を私有領域に保存する。
    """
    path = SOURCE/'features.py'; before = hashlib.sha256(path.read_bytes()).hexdigest()
    sys.path.insert(0,str(SOURCE))
    import features
    import input_artificial
    import catalog
    import selection
    raws,records,cases = input_artificial.fixture()
    for row,mid in [(6,99.),(7,100.)]:
        for symbol in ('TOPIX','NK225'):
            for item in (raws[symbol],records[symbol]):
                item['bid'][row] = mid-.5; item['ask'][row] = mid+.5
    measured = features.build(raws,records,'TOPIX')
    config = next(c for c in catalog.catalog() if c['mode']=='R_ONLY' and c['range_er']==.2 and c['margin_ticks']==4 and c['range_entry']=='LIMIT')
    result = selection.range_arrays({'record':records['TOPIX']},measured,config)
    sample = int(measured['normal_sample_index'][7]); low = measured['sample_tables']['own']['low'][sample]
    accepted = bool(result['allowed'][7]); actual_mid = .5*(records['TOPIX']['bid'][7]+records['TOPIX']['ask'][7])
    assert actual_mid < low
    after = hashlib.sha256(path.read_bytes()).hexdigest(); assert before == after
    output = {'全合格':not accepted,'scope':'旧草案の範囲外候補・人工だけ','金融再生':0,'金融結果読取':0,'原本NPZAPI':0,
        '観測':{'normal行':7,'sample_L':float(low),'current_mid':float(actual_mid),
            '候補方向':int(measured['boundary_events']['0.2'][7]),'停止余裕tick':float(result['stop_clearance_ticks'][7]),
            '料金後予定利益':float(result['planned_net_profit'][7]),'料金込み予定損失':float(result['planned_net_loss'][7]),
            '許可':accepted},'必要仕様':'L<=currentmid<=H。範囲外回復は今回は別仮説として含めない。',
        'source_SHA256':{'features.py':before,'selection.py':hashlib.sha256((SOURCE/'selection.py').read_bytes()).hexdigest()},
        '開始終端source一致':True}
    destination = HERE/('range_旧草案の範囲外候補False.json' if accepted else 'range_範囲外候補の局所拒否.json')
    assert not destination.exists()
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('範囲外候補',accepted,'診断保存',flush=True)


if __name__ == '__main__':
    main()
