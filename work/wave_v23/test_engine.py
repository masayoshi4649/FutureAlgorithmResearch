"""注文管理の因果性、会計、損失抑制を合成経路で確認する。"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from engine import run
from managers import manager_catalog, make_config


def fixture(prices: list[float], states: list[int] | None = None, step: float = 1.) -> tuple[dict, np.ndarray]:
    """機能: ATR を固定した合成観測を生成する。

    引数: prices (list[float])、states (list[int]|None)、step (float)。
    返り値: 再生入力と方向信号 (tuple[dict,ndarray])。
    """
    price = np.array(prices, dtype=float)
    ready = {'time_s': np.arange(len(price)) * step, 'last': price,
             'atr': np.ones(len(price)), 'tick': .1, 'start': 0.,
             'limit': (len(price)-3)*step, 'us_open': np.inf}
    state = np.array(states if states is not None else [1]*len(price), dtype=np.int8)
    return ready, state


def configuration(number: int, ready: dict, symbol: str = 'TOPIX') -> dict:
    """機能: 短い合成経路用に待機時間だけを除いた管理条件を返す。

    引数: number (int)、ready (dict)、symbol (str)。返り値: 設定 (dict)。
    """
    config = make_config(manager_catalog()[number], symbol, ready)
    config.update(warmup_min=0., entry_cutoff_min=0., cooldown_min=0.)
    return config


def accounting(result: dict, cap: int) -> None:
    """機能: 全注文が次行以降、数量上限内、損益帳簿が整合することを確認する。

    引数: result (dict)、cap (int)。返り値: なし (None)。
    """
    assert np.all(result['orders'][:, 0] > result['orders'][:, 1])
    assert max(result['stats'][2:4]) <= cap
    assert result['stats'][6] < 1e-7
    assert abs(result['trades'][:, 10].sum()-result['stats'][0]) < 1e-7
    assert result['stats'][9] == 0


def main() -> None:
    """機能: 未来執行、連敗、円予算、上限、反転を独立した合成例で確認する。

    引数: なし。返り値: なし (None)。検証記録を JSON に保存する。
    """
    checks = []
    ready, state = fixture([100, 100, 98, 98, 98, 96, 96, 96, 94, 94, 92, 92, 90, 90])
    config = configuration(7, ready)
    config['entry_atr'] = 0.
    result = run(ready, state, config, True)
    accounting(result, 10)
    assert len(result['cycles']) == 2, result['cycles']
    assert result['stats'][0] == -2.
    checks.append('継続下落中の買いは２連敗で停止し、無限に再注文しない')

    # ----------------------------------------
    # 連敗後も反対信号または出口から１ATR進んだ時だけ再開する。
    ready2, state2 = fixture([100,100,98,98,98,96,96,96,97.1,98,99,99,99,99])
    config2 = configuration(7, ready2); config2['entry_atr'] = 0.
    result2 = run(ready2, state2, config2, True)
    accounting(result2, 10)
    assert len(result2['cycles']) == 3
    assert result2['trades'][-1, 6] >= 9
    checks.append('同方向の明確な１ATR回復後には再開できる')

    # ----------------------------------------
    # ゼロ幅注文も観測した行で約定させず、次の観測価格を用いる。
    ready3, state3 = fixture([100,103,104,105,106,107,108,109])
    config3 = configuration(0, ready3); config3['entry_atr'] = 0.
    result3 = run(ready3, state3, config3, True)
    accounting(result3, 10)
    assert result3['trades'][0, 6] == 1 and result3['trades'][0, 4] == 103
    assert result3['trades'][-1, 7] == len(ready3['last'])-2
    checks.append('成立済み新規は次行価格、場末返済も次行で執行する')

    # ----------------------------------------
    # 同額リスクはエントリーごとの固定ATRで切り捨て、上限も守る。
    ready4, state4 = fixture(list(np.linspace(100,110,30)))
    ready4['atr'][:] = 3.
    config4 = configuration(9, ready4); config4['entry_atr'] = 0.
    result4 = run(ready4, state4, config4, True)
    accounting(result4, 10)
    assert result4['orders'][0, 4] == 6
    assert result4['cycles'][0, 4]*1000 <= 20000
    checks.append('ATR３のTOPIXでは２万円予算から６枚となる')
    ready4['atr'][:] = 3.333
    rounded_result = run(ready4, state4, config4, True)
    accounting(rounded_result, 10)
    assert rounded_result['orders'][0, 4] == 5
    checks.append('呼値丸め後に予算を超える６枚を避け５枚へ切り捨てる')

    # ----------------------------------------
    # セッション損失予算は確定損益と全玉含み損を合算して停止する。
    ready5, state5 = fixture([100,100,98,98,98,96,96,96,94,94,92,92,90,90])
    config5 = configuration(0, ready5)
    config5.update(entry_atr=0., session_budget_r=1.5)
    result5 = run(ready5, state5, config5, True)
    accounting(result5, 10)
    assert len(result5['cycles']) == 2 and result5['stats'][0] == -2.
    checks.append('損失予算到達後は当該セッションで再開しない')

    # ----------------------------------------
    # 方向撤回と反転・分割・増玉・カバーを含め、全条件で会計と上限を照合。
    path = np.concatenate([np.linspace(100,112,50),np.linspace(112,95,55),np.linspace(95,118,70),np.repeat(118.,6)])
    signs = np.where(np.arange(len(path))<55,1,np.where(np.arange(len(path))<112,-1,1)).tolist()
    ready6, state6 = fixture(path.tolist(), signs, 60.)
    for symbol in ('TOPIX','NK225'):
        for index in range(len(manager_catalog())):
            config6 = configuration(index, ready6, symbol)
            result6 = run(ready6, state6, config6, True)
            accounting(result6, 10 if symbol=='TOPIX' else 20)
            for cut in (20,73,120):
                prefix = dict(ready6)
                for key in ('time_s','last','atr'):
                    prefix[key] = ready6[key][:cut]
                short = run(prefix,state6[:cut],config6,True)
                np.testing.assert_allclose(short['curve'],result6['curve'][:cut],atol=1e-7)
                np.testing.assert_allclose(short['orders'],result6['orders'][result6['orders'][:,0]<cut],atol=1e-7)
    checks.append('２０管理×２銘柄で会計・保有上限・場内返済・未来切断３点が一致')
    output = {'合格': True, '確認': checks, '管理条件数': len(manager_catalog()),
              '数量条件': 'TOPIXミニ片方向１０枚、NK225マイクロ片方向２０枚'}
    target = Path(__file__).with_name('engine_test.json')
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False))


if __name__ == '__main__':
    main()
