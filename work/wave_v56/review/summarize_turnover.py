"""代金差分の保存配列から、一枚更新と複数枚更新の整合性を追加確認する。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 平均価格と最後価格の差を枚数別に分解する。

    引数: なし。返り値: なし(None)。原本を再度読み込まず監査配列を利用する。
    """
    output={}
    for symbol in ('TOPIX','NK225'):
        counts=dict(正増分対=0,一枚更新=0,一枚で平均と最後価格不一致=0,複数枚更新=0,
                    複数枚で平均と最後価格不一致=0,分類不一致の出来高=0.,全出来高=0.)
        for path in sorted((HERE/'代金差分').glob(f'*_{symbol}.npz')):
            with np.load(path) as data:
                good=data['delta_good'];volume=data['volume_delta']
                different=~np.isclose(data['average_price'],data['last'],rtol=0,atol=1e-7)
                one=good&(volume==1);many=good&(volume>1)
                counts['正増分対']+=int(good.sum());counts['一枚更新']+=int(one.sum())
                counts['一枚で平均と最後価格不一致']+=int((one&different).sum())
                counts['複数枚更新']+=int(many.sum())
                counts['複数枚で平均と最後価格不一致']+=int((many&different).sum())
                counts['分類不一致の出来高']+=float(volume[good&(data['old_class']!=data['average_class'])].sum())
                counts['全出来高']+=float(volume[good].sum())
        counts['分類不一致の出来高割合']=counts['分類不一致の出来高']/counts['全出来高']
        output[symbol]=counts
    result=dict(銘柄別=output,説明='一枚の増分では平均価格と最後価格が一致するかを確認。複数枚の平均と最後価格の差は複数価格の約定が含まれれば正常で、代理分類差を誤判定率と呼ばない。')
    (HERE/'一枚更新と複数枚更新の監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
