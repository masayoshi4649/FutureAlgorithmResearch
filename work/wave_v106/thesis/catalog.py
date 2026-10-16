"""未確認だった支持破れと相手逆進行の途中判断を12対照で固定する。"""

from copy import deepcopy


def catalog(base_configs: list[dict]) -> list[dict]:
    """
    機能: 三つの既存B4へ相手窓10/30秒と確認0/5秒を加える。
    引数: base_configs(list[dict])は結果前固定された第一51の条件。
    返り値: list[dict]は12条件。入口・数量・費用・従来停止を変えない。
    """
    lookup = {value['id']: value for value in base_configs}
    result = []
    for entry in ('C_OWN', 'C_N30', 'U_P10'):
        base = entry + '_B4'
        for window in (10, 30):
            for seconds in (0., 5.):
                value = deepcopy(lookup[base])
                assert value['support_ticks'] == 4 and not any(value.get(key, False)
                    for key in ('profit_trail', 'r_profit', 'reentry_band', 'session_brake'))
                value.update(id=base+f'_THESIS_W{window}_C{int(seconds)}', base_id=base,
                    thesis_enabled=True, thesis_window=window, thesis_confirm_seconds=seconds,
                    name='支持破れと相手逆進行の途中返済',
                    explanation=f'初期支持を1呼値以上破り、相手の{window}秒両気配も逆1呼値以上で{int(seconds)}秒確認したら次正常気配で返済する。')
                result.append(value)
    assert len(result) == 12 and len({value['id'] for value in result}) == 12
    return result
