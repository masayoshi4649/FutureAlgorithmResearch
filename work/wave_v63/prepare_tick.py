"""修正済みの原本行OFI・出来高代理・価格別補充を追加保存場へ拡張する。"""

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import pickle
import sys

import numpy as np

from prepare_board import digest, HERE, ROOT, BASE


OLD=HERE.parent/'wave_v57'


def extract_one(args: tuple) -> tuple:
    """機能: 追加場を監査済み修正抽出器で原本順に処理する。

    引数: args(tuple:場キー、価格入力dict)。返り値: キー・特徴・補充・監査(tuple)。
    """
    key,ready=args
    spec=importlib.util.spec_from_file_location('fixed_tick_extract',OLD/'features.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    data,events,audit=module.extract_one(key,ready)
    return key,data,events,audit


def main() -> None:
    """機能: 全50口座の修正板特徴を共通原本順序と照合して保存する。

    引数: なし。返り値: なし(None)。APIアクセスや原本編集はしない。
    """
    target=HERE/'tick_features.pkl'
    assert not target.exists(),'既に作成済みです'
    inputs=pickle.loads((BASE/'inputs.pkl').read_bytes())
    quotes=pickle.loads((BASE/'quotes.pkl').read_bytes())
    prices=pickle.loads((HERE.parent/'wave_v59'/'inputs.pkl').read_bytes())
    prices.update(pickle.loads((HERE.parent/'wave_v59'/'holdout'/'inputs.pkl').read_bytes()))
    features=pickle.loads((OLD/'features.pkl').read_bytes())
    events=pickle.loads((OLD/'events.pkl').read_bytes())
    audits=[]
    missing=sorted(set(inputs)-set(features))
    print(f'修正済み原板{len(features)}口座・追加{len(missing)}口座',flush=True)
    with ProcessPoolExecutor(max_workers=4) as pool:
        for key,data,ev,audit in pool.map(extract_one,[(k,prices[k]) for k in missing]):
            features[key],events[key]=data,ev
            audits.append(audit)
            print(f'{key}: {len(data["seq"]):,}原本行・補充{len(ev):,}件',flush=True)
    assert len(features)==len(events)==50
    for key in sorted(inputs):
        data,ready,q=features[key],inputs[key],quotes[key]
        assert np.array_equal(data['seq'],ready['seq'])
        assert np.array_equal(data['time_s'],ready['time_s'])
        for name in ('bid','ask','mid'):
            assert np.array_equal(data[name],q[name])
    target.write_bytes(pickle.dumps(features,protocol=pickle.HIGHEST_PROTOCOL))
    (HERE/'tick_events.pkl').write_bytes(pickle.dumps(events,protocol=pickle.HIGHEST_PROTOCOL))
    manifest=dict(合格=True,口座数=50,現在取得=0,時刻=datetime.now(timezone.utc).isoformat(),
        入力照合='seq/time/bid/ask/midはv60共通入力と全行一致。旧46原本のSHAは板特徴の照合.jsonで確認。',
        観測='最良OFIは価格変更で消失した最良表示量を含む。補充は既知減少残高に80%以上が表示回復した完了イベント。出来高側は売買代金増分の平均執行価格による代理。真の個別注文/取消/成行識別ではない。',
        ファイルSHA={str(p):digest(p) for p in (OLD/'features.py',OLD/'features.pkl',OLD/'events.pkl',target,HERE/'tick_events.pkl')},
        追加抽出=audits)
    (HERE/'修正板特徴の照合.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('修正板全50口座の原本行・気配一致',flush=True)


if __name__=='__main__':
    main()
