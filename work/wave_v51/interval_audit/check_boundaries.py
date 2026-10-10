"""区間境界・同時刻行順・実現と含みの二重計上を小さい人工例で反証する。"""
from datetime import datetime
import json

from replay_intervals import Fill, HERE, IntervalAccount


def time_of(value: str) -> float:
    """機能: 監査用の日本時刻をUnix秒へ変換する。

    引数: value(str) は時分秒。返り値: float はUnix秒。
    """
    return datetime.fromisoformat('2026-10-05T' + value + '+09:00').timestamp()


def main() -> None:
    """機能: 価格を未来補間せず、同時刻後続行を順に扱うことを検査する。

    引数: なし。返り値: なし(None)。監査結果を同フォルダへ保存する。
    """
    account = IntervalAccount(time_of('08:45:00'), time_of('10:00:00'), 1, 10)
    account.on_event(0, 10, time_of('08:45:01'), 100)
    account.on_event(1, 11, time_of('08:50:00'), 100, (Fill(1, 0, 0, 1, 2, 100, True),))
    account.on_event(2, 12, time_of('08:59:59'), 110)
    account.on_event(3, 13, time_of('09:00:00'), 90, (Fill(3, 2, 0, -1, 1, 90, False),))
    assert account.rows[0]['時価収支円'] == 20
    assert account.rows[0]['評価価格'] == 110
    assert account.rows[0]['確定収支円'] == 0
    account.on_event(4, 14, time_of('09:00:00'), 91)
    assert account.snapshot()['含み'] == -9
    assert account.snapshot()['現金'] == -10
    account.on_event(5, 15, time_of('09:20:00'), 105)
    account.on_event(6, 16, time_of('09:30:00'), 110, (Fill(6, 5, 0, -1, 1, 110, False),))
    rows = account.finish()
    assert [row['時価収支円'] for row in rows] == [20, -25, 5]
    assert [row['確定収支円'] for row in rows] == [0, -10, 10]
    assert [row['終了含み円'] for row in rows] == [20, 5, 0]
    assert [row['返済枚数'] for row in rows] == [0, 1, 1]
    assert account.balance == 0
    # ----------------------------------------
    # 同時両建ての利益玉だけを収益扱いせず、逆玉と含みを同時に会計する。
    hedge = IntervalAccount(time_of('08:45:00'), time_of('10:00:00'), 1, 2)
    hedge.on_event(0, 10, time_of('08:45:01'), 100)
    hedge.on_event(1, 11, time_of('08:50:00'), 100,
                   (Fill(1, 0, 0, 1, 2, 100, True), Fill(1, 0, 1, -1, 2, 100, True)))
    hedge.on_event(2, 12, time_of('08:59:59'), 95)
    assert hedge.unrealized() == 0
    hedge.on_event(3, 13, time_of('09:00:00'), 95, (Fill(3, 2, 0, -1, 2, 95, False),))
    assert hedge.balance == -10 and hedge.unrealized() == 10
    hedge.on_event(4, 14, time_of('09:10:00'), 90, (Fill(4, 3, 1, 1, 2, 90, False),))
    hedge_rows = hedge.finish()
    assert hedge.balance == 10 and sum(row['時価収支円'] for row in hedge_rows) == 10
    assert sum(row['確定利益円'] for row in hedge_rows) == 20
    assert sum(row['確定損失円'] for row in hedge_rows) == 10
    assert hedge.max_long == hedge.max_short == 2
    result = dict(全合格=True, 境界時計の約定は次区間=True, 端点未来価格不使用=True,
                  同時刻後続行反映=True, 確定と含みの二重計上なし=True, 両建て両脚合算=True,
                  区間=rows, 両建て区間=hedge_rows)
    (HERE / '境界監査.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print('区間境界・同時刻原本順・時価会計の人工反証に合格')


if __name__ == '__main__':
    main()
