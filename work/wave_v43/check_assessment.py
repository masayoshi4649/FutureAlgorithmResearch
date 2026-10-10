"""人工台帳だけで時間窓合議32条件の判定境界と資料破損拒否を検査する。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('window_assessment_check_target', HERE / 'assessment.py')
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)


def refresh(data: tuple, selected: str | None = None) -> None:
    """機能: 人工元組の変更から場・期間の財務値を一貫して再構成する。

    引数: data(tuple)、selected(str|None)。返り値: なし(None)。
    """
    index, sessions, names, ledgers = data
    for key in ([selected] if selected else index):
        for row, book in zip(sessions[key], ledgers[key]):
            factor = book['config']['point_value']
            quantity = 5 if row['symbol'] == 'TOPIX' else 10
            profits = [c[3] * factor for c in book['cycles']]
            gains = [p for p in profits if p > 0]
            losses = [-p for p in profits if p < 0]
            row.update(net_yen=sum(profits), gross_profit_yen=sum(gains), gross_loss_yen=sum(losses),
                profit_units=len(gains)*quantity, loss_units=len(losses)*quantity,
                zero_units=sum(p == 0 for p in profits)*quantity, cycles=len(profits),
                cycle_wins=len(gains), cycle_losses=len(losses), cycle_profit_yen=sum(gains),
                cycle_loss_yen=sum(losses), reductions=0, restorations=0,
                maximum_trade_profit=max([0.] + gains), drawdown_yen=2*factor,
                net_r=sum(c[3]/c[4] for c in book['cycles']),
                two_largest_cycle_profits=sorted(gains, reverse=True)[:2])
        for period in audit.PERIODS:
            wanted = audit.names_for(period, names)
            for symbol in audit.SYMBOLS:
                rows = [r for r in sessions[key] if r['symbol'] == symbol and r['session'] in wanted]
                value = {field: sum(r[field] for r in rows) for field in audit.SUM_FIELDS}
                value['net_r'] = sum(r['net_r'] for r in rows)
                value['drawdown_yen'] = max(r['drawdown_yen'] for r in rows)
                value['average_cycle_payoff'] = ((value['cycle_profit_yen']/value['cycle_wins']) /
                    (value['cycle_loss_yen']/value['cycle_losses'])) if value['cycle_wins'] and value['cycle_losses'] else None
                index[key][period][symbol] = value


def fixture() -> tuple:
    """機能: 全32条件・832口座の人工台帳と集計を作る。

    引数: なし。返り値: index、場別集計、13場名、台帳(tuple)。実価格は使わない。
    """
    names = [f'人工{i:02d}' for i in range(13)]
    index, sessions, ledgers = {}, {}, {}
    for spec in audit.design.catalog():
        key = spec['id']
        index[key] = dict(id=key, spec=spec, all_symbols={s:{} for s in audit.SYMBOLS},
                         symbols={s:{} for s in audit.SYMBOLS}, wave_passes=8)
        sessions[key], ledgers[key] = [], []
        for name in names:
            for symbol in audit.SYMBOLS:
                profits = [4., 3., -1., -1.] if spec['window_id'].startswith('M2') else [3., 2., -1., -1.]
                quantity = 5. if symbol == 'TOPIX' else 10.
                cycles = [[i, i*10+1, i*10+8, p, 10., 2., quantity, quantity, 1 if i % 2 == 0 else -1, 2.]
                          for i, p in enumerate(profits)]
                sessions[key].append(dict(id=key, session=name, symbol=symbol))
                ledgers[key].append(dict(session=name, symbol=symbol,
                    config=dict(point_value=1000. if symbol == 'TOPIX' else 10.), cycles=cycles))
    result = index, sessions, names, ledgers
    refresh(result)
    return result


def set_profits(data: tuple, key: str, values: list[float], chosen: list[str] | None = None) -> None:
    """機能: 指定した人工場の元組損益を変更して期間値を再構成する。

    引数: data(tuple)、key(str)、values(list[float])、chosen(list[str]|None)。返り値: なし(None)。
    """
    for book in data[3][key]:
        if chosen is None or book['session'] in chosen:
            quantity = 5. if book['symbol'] == 'TOPIX' else 10.
            book['cycles'] = [[i, i*10+1, i*10+8, p, 10., 2., quantity, quantity, 1 if i % 2 == 0 else -1, 2.]
                              for i, p in enumerate(values)]
    refresh(data, key)


def rejected(function: object) -> bool:
    """機能: 不正資料が検査例外で停止することを確認する。

    引数: function(Callable)。返り値: 拒否された場合True(bool)。
    """
    try:
        function()
    except (AssertionError, KeyError, TypeError, ValueError):
        return True
    return False


def main() -> None:
    """機能: 採否と完全性を人工で攻撃し、全件成功時だけ証拠を保存する。

    引数: なし。返り値: なし(None)。新実相場の売買は実行しない。
    """
    original = fixture()
    records = []
    rejection_count = 0

    def check(name: str, condition: bool) -> None:
        """機能: 日本語の検査名と成功を記録する。

        引数: name(str)、condition(bool)。返り値: なし(None)。
        """
        assert condition, name
        records.append(dict(検査=name, 一致=True))

    manager = audit.design.MANAGERS[0]
    other = audit.design.MANAGERS[1]
    primary = audit.identifier('M2_100', manager)
    baseline = audit.identifier('S100', manager)
    result = audit.assess(*original)
    check('全32条件832口座を保持', len(result['全条件']) == 32 and result['全入力数'] == 832)
    check('二出口の主案を別々に判定', set(result['出口別']) == set(audit.design.MANAGERS))
    check('基礎集中買売時計の正常例', all(r['経済目安合格'] for r in result['出口別'].values()))
    check('監査前は研究候補へ昇格しない', not any(r['既知比較の研究候補'] for r in result['出口別'].values()))
    verified = audit.assess(*original, verification=True)
    check('監査後にだけ固定主案を研究候補へ', all(r['既知比較の研究候補'] for r in verified['出口別'].values()))
    restored = deepcopy(verified)
    restored['監査完了'] = False
    for cell in restored['出口別'].values():
        cell['監査完了'] = False
        cell['既知比較の研究候補'] = False
    check('監査の有無で経済判定を変更しない', restored == result)
    check('主比較は改善でも全体達成と未知有効を宣言しない', not verified['全体目標達成'] and not verified['未知での有効性確認'])
    check('見送り対照未実施を保つ', not verified['見送り量対照実施'] and verified['合議固有の予測付加価値'] == '未判定')
    check('元組ID0を正常に受理', original[3][primary][0]['cycles'][0][0] == 0)

    data = deepcopy(original)
    for period in audit.PERIODS:
        for symbol in audit.SYMBOLS:
            data[0][primary][period][symbol]['drawdown_yen'] += 1
    value = audit.assess(*data, verification=True)['出口別'][manager]
    check('DD増を隠さず収益候補と分ける', value['既知比較の研究候補'] and value['中央の収益DD関係']['関係'] == '交換又は混在')
    data = deepcopy(original)
    set_profits(data, primary, [3., 2., -1., -1.])
    value = audit.assess(*data)['出口別'][manager]
    check('単一中央同値を追加改善へしない', not value['中央の収益追加改善'] and value['中央の収益DD関係']['完全同値'])
    check('同値でも基礎候補を消さない', value['中央の基礎候補'])
    data = deepcopy(original)
    set_profits(data, primary, [2., 2., -1., -1.], data[2][:6])
    set_profits(data, primary, [3.1, 2., -1., -1.], data[2][6:])
    value = audit.assess(*data)['出口別'][manager]
    check('後7増益でも全13減益なら中央改善不成立', not value['中央の収益追加改善'])
    data = deepcopy(original)
    data[0][primary]['wave_passes'] = 0
    value = audit.assess(*data, verification=True)['出口別'][manager]
    check('8波不足と経済判定を分離', value['既知比較の研究候補'] and not value['指定八波'])

    data = deepcopy(original)
    set_profits(data, primary, [], None)
    value = audit.assess(*data)['出口別'][manager]
    check('無取引を優秀と判定しない', not value['中央の基礎候補'])
    data = deepcopy(original)
    for book in data[3][primary]:
        for cycle in book['cycles']:
            cycle[8] = 1
    value = audit.assess(*data)['全条件'][primary]
    check('片方向だけの取引を買売活動合格にしない', value['元組基礎と大勝ち除外'] and not value['実取引と買売双方'])
    data = deepcopy(original)
    set_profits(data, primary, [4., 3., 1., 1.])
    value = audit.assess(*data)['全条件'][primary]
    check('無損失の未定義PFを無限大へしない', not value['基礎候補'] and value['期間別']['symbols']['TOPIX']['比率']['元組PF'] is None)
    data = deepcopy(original)
    set_profits(data, primary, [1., 1., -1., -1.])
    check('収支0とPF1は不合格', not audit.assess(*data)['全条件'][primary]['基礎候補'])
    data = deepcopy(original)
    set_profits(data, primary, [1., 1., 1., -1.])
    value = audit.assess(*data)['全条件'][primary]['期間別']['symbols']['TOPIX']
    check('PF良好でも平均元組比1は不合格', value['基礎検査']['元組PF1超'] and not value['基礎検査']['平均元組勝敗比1超'])

    data = deepcopy(original)
    set_profits(data, primary, [-1., -1.])
    set_profits(data, primary, [100., -1.], [data[2][-1]])
    value = audit.assess(*data)['全条件'][primary]['期間別']['symbols']['TOPIX']
    check('一勝依存を全取引の黒字で救済しない', value['基礎検査']['収支正'] and not value['最大勝ち除外検査']['最大勝ち元組除外非負'])
    data = deepcopy(original)
    set_profits(data, primary, [-1., -1.])
    set_profits(data, primary, [30., 30., -1., -1.], [data[2][-1]])
    value = audit.assess(*data)['全条件'][primary]['期間別']['all_symbols']['TOPIX']
    check('最大組除外と最大場除外を別々に判定', value['最大勝ち除外検査']['最大勝ち元組除外非負'] and not value['最大勝ち除外検査']['最大黒字場除外非負'])
    data = deepcopy(original)
    set_profits(data, primary, [1., -1.])
    set_profits(data, primary, [30., 30., -1., -1.], [data[2][-1]])
    value = audit.assess(*data)['全条件'][primary]
    check('上位二勝ち同時除外は表示で基礎へ後付けしない', value['基礎候補'] and value['期間別']['symbols']['TOPIX']['上位二勝ち元組同時除外収支円'] < 0)
    check('最大黒字場除外0は非負として許可', value['期間別']['symbols']['TOPIX']['最大黒字場除外収支円'] == 0)

    data = deepcopy(original)
    neighbor = audit.identifier('M2_080', manager)
    set_profits(data, neighbor, [-1., -1.])
    set_profits(data, neighbor, [100., -1.], [data[2][-1]])
    value = audit.assess(*data)['出口別']
    check('中心の一勝依存が時計耐性を落とす', not value[manager]['三中心耐性'] and value[manager]['中央の基礎候補'])
    check('他出口で失敗した出口を救済しない', value[other]['経済目安合格'] and not value[manager]['経済目安合格'])
    data = deepcopy(original)
    last = audit.identifier('M2_100', manager, 'L015')
    set_profits(data, last, [-1., -1.])
    value = audit.assess(*data)['出口別'][manager]
    check('執行基礎不成立を中央の経済判定と分離', not value['四執行基礎'] and value['経済目安合格'])
    data = deepcopy(original)
    set_profits(data, audit.identifier('U3_100', manager), [1000., 900., -1., -1.])
    value = audit.assess(*data)['出口別'][manager]
    check('最良の全一致へ主案を差替えない', value['主案ID'] == primary)

    # ----------------------------------------
    # 合否境界と異なり、資料が欠けた場合は採否を返さず例外とする。
    changes = []
    changes.append(('条件欠落', lambda d: d[0].pop(primary)))
    changes.append(('条件追加', lambda d: d[0].update(未知条件=deepcopy(d[0][primary]))))
    changes.append(('仕様差替え', lambda d: d[0][primary]['spec'].update(window_id='U3_100')))
    changes.append(('保存ID差替え', lambda d: d[0][primary].update(id=baseline)))
    changes.append(('場行欠落', lambda d: d[1][primary].pop()))
    changes.append(('場行重複', lambda d: d[1][primary].__setitem__(0, deepcopy(d[1][primary][1]))))
    changes.append(('場ID誤り', lambda d: d[1][primary][0].update(id=baseline)))
    changes.append(('台帳欠落', lambda d: d[3][primary].pop()))
    changes.append(('台帳重複', lambda d: d[3][primary].__setitem__(0, deepcopy(d[3][primary][1]))))
    changes.append(('負の元組ID', lambda d: d[3][primary][0]['cycles'][0].__setitem__(0, -1)))
    changes.append(('重複元組ID', lambda d: d[3][primary][0]['cycles'][1].__setitem__(0, 0)))
    changes.append(('無効売買方向', lambda d: d[3][primary][0]['cycles'][0].__setitem__(8, 0)))
    changes.append(('初期R0', lambda d: d[3][primary][0]['cycles'][0].__setitem__(4, 0)))
    changes.append(('元組損益改竄', lambda d: d[3][primary][0]['cycles'][0].__setitem__(3, 99)))
    changes.append(('小口倍率改竄', lambda d: d[3][primary][0]['config'].update(point_value=999)))
    changes.append(('非有限', lambda d: d[0][primary]['symbols']['TOPIX'].update(net_yen=float('nan'))))
    changes.append(('無限DD', lambda d: d[0][primary]['symbols']['TOPIX'].update(drawdown_yen=float('inf'))))
    changes.append(('数値真偽値', lambda d: d[0][primary]['symbols']['TOPIX'].update(net_yen=True)))
    changes.append(('最大勝ち欠落', lambda d: d[1][primary][0].pop('maximum_trade_profit')))
    changes.append(('上位二勝ち改竄', lambda d: d[1][primary][0].update(two_largest_cycle_profits=[])))
    changes.append(('期間総R改竄', lambda d: d[0][primary]['symbols']['TOPIX'].update(net_r=999)))
    changes.append(('平均元組比改竄', lambda d: d[0][primary]['symbols']['TOPIX'].update(average_cycle_payoff=999)))
    changes.append(('整数枚数でない', lambda d: d[1][primary][0].update(profit_units=1.5)))
    changes.append(('波数範囲外', lambda d: d[0][primary].update(wave_passes=9)))
    changes.append(('13場重複', lambda d: d[2].__setitem__(0, d[2][1])))
    changes.append(('場順序逆転', lambda d: d[2].reverse()))
    for name, change in changes:
        data = deepcopy(original)
        change(data)
        check(name + 'を拒否', rejected(lambda: audit.assess(*data)))
        rejection_count += 1
    check('元人工材料を変更しない', audit.assess(*original) == result)
    paths = [HERE/'assessment.py', Path(__file__), HERE/'design.py', audit.SOURCE,
             HERE/'反証計画.md', HERE.parent/'wave_v38/探索条件の固定.json']
    refs = {p.relative_to(audit.ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    payload = dict(全合格=True, 合成検査数=len(records), 不正資料拒否数=rejection_count,
        全条件数=32, 全人工入力数=832, 検査=records, 新実相場損益=False, 現在API取得数=0,
        採否実装SHA256=refs[(HERE/'assessment.py').relative_to(audit.ROOT).as_posix()],
        参照資料SHA256=refs)
    (HERE/'check_assessment.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in payload.items() if k not in ('検査','参照資料SHA256')},ensure_ascii=False))


if __name__ == '__main__':
    main()
