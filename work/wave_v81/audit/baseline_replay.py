"""最終の拡張方向素材でも、初回3代表の前半経路が変わらないことを確認する。"""

import json
import numpy as np

from accounts import HERE,WORK,study


def main() -> None:
    """機能: 初回と最終5秒の同じ32口座を全台帳・時価指紋まで比較する。

    引数: なし。返り値: なし(None)。監査JSONだけ保存する。
    """
    selected=study.load(WORK/'初回前半選定.json')['代表'];accounts=arrays=0
    for config in selected:
        identifier=config['id']
        before=study.load(WORK/'first/ledgers'/f'{identifier}.pkl')
        after=study.load(WORK/'final/delay5/ledgers'/f'{identifier}.pkl')
        assert len(before)==32 and len(after)==60
        for key,old in before.items():
            current=after[key]
            assert old['curve_hash']==current['curve_hash']
            for field in ['orders','trades','stats','events']:
                np.testing.assert_array_equal(old[field],current[field],err_msg=f'{identifier} {key} {field}')
                arrays+=1
            accounts+=1
    result=dict(合格=True,基準条件数=len(selected),前半口座数=accounts,台帳配列照合数=arrays,
        全行清算時価SHA一致数=accounts,初回3代表を後から変更していない=True)
    (HERE/'初回基準3代表の最終完全一致.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
