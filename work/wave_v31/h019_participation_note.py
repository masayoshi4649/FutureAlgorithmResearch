"""H019価格管理の参加量を、事後の説明用として保存済み台帳からまとめる。"""

from __future__ import annotations

import episode_audit as audit


def summarize(rows: list[dict]) -> dict:
    """機能: 同一銘柄・同一条件の金額・延べ枚数・参加時間を合計する。

    引数: rows (list[dict])。返り値: 説明用の合計値 (dict)。銘柄を混ぜない。
    """
    fields = ('long_unit_minutes', 'short_unit_minutes', 'opening_orders', '買い保有分', '売り保有分',
              '保有分', '無建玉分', '初回新規待ち分', '返済後再開待ち分', '最終返済後待ち分', '新規枚数', '返済枚数')
    money = ('gross_profit_yen', 'gross_loss_yen', 'net_yen', 'profit_units', 'loss_units', 'zero_units', 'closed_units')
    return {**{field: sum(row[field] for row in rows) for field in fields},
            **{field: sum(row['損益'][field] for row in rows) for field in money}}


def main() -> None:
    """機能: 全5変形と親が指定した3区間を、新しい再生なしで記述する。

    引数: なし。返り値: なし (None)。この区間選択は結果後の説明であり、採用規則ではない。
    """
    audit.deny_network()
    source = audit.HERE / 'episode_participation_details' / 'H019.json.gz'
    data = audit.runner.read(source)
    rows = [row for row in data['参加'] if row['manager_id'] == 'L000']
    totals, comparisons = [], []
    for symbol in ('TOPIX', 'NK225'):
        for variant in audit.VARIANTS:
            subset = [row for row in rows if row['symbol'] == symbol and row['variant_id'] == variant]
            assert len(subset) == 13
            totals.append({'variant': variant, 'symbol': symbol, **summarize(subset)})
    for session in ('2026-09-22_Night', '2026-09-29_Day', '2026-09-23_Day'):
        base = next(row for row in rows if row['symbol'] == 'TOPIX' and row['session'] == session and row['variant_id'] == 'V000')
        waited = next(row for row in rows if row['symbol'] == 'TOPIX' and row['session'] == session and row['variant_id'] == 'W060')
        a, b = summarize([waited]), summarize([base])
        comparisons.append({'session': session, 'symbol': 'TOPIX', 'V000': b, 'W060': a,
                            'W060-V000': {field: a[field] - b[field] for field in a}})
    output = {'用途': '親が主結果で指摘したH019B0の経路差を説明する事後資料。追加検証・採否・事前の事例選択ではない。',
              '全5変形': totals, '親指定3区間': comparisons,
              '解釈': 'Wは初期の取引を削除するだけではない。最初の新規が変わると、その後の建玉・返済・休止・再新規も変わる。後続の組番号を対応させず、戦略全体の差を示す。',
              '一般化の限界': 'このH019とTOPIXの3区間を全入口・両銘柄の法則へ拡張しない。全12等重み及び5思想の対照はparticipation.jsonで別集計する。',
              '台帳元SHA256': audit.runner.digest(source), 'API取得数': 0, '現在保存物使用': False}
    audit.runner.save(audit.HERE / 'h019_participation_note.json', output)
    lines = ['# H019の開始待ちと後続取引', '', output['用途'], '',
             '|銘柄|変形|利益円|損失円|収支円|新規回数|買い枚数分|売り枚数分|無建玉分|初回待ち分|再開待ち分|',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in totals:
        lines.append(f"|{row['symbol']}|{row['variant']}|{row['gross_profit_yen']:,.0f}|{row['gross_loss_yen']:,.0f}|{row['net_yen']:+,.0f}|{row['opening_orders']}|{row['long_unit_minutes']:,.1f}|{row['short_unit_minutes']:,.1f}|{row['無建玉分']:,.1f}|{row['初回新規待ち分']:,.1f}|{row['返済後再開待ち分']:,.1f}|")
    lines += ['', '|TOPIX区間|収支差円|新規回数差|買い枚数分差|売り枚数分差|初回待ち分差|再開待ち分差|', '|---|---:|---:|---:|---:|---:|---:|']
    for item in comparisons:
        row = item['W060-V000']
        lines.append(f"|{item['session']}|{row['net_yen']:+,.0f}|{row['opening_orders']:+}|{row['long_unit_minutes']:+,.1f}|{row['short_unit_minutes']:+,.1f}|{row['初回新規待ち分']:+,.1f}|{row['返済後再開待ち分']:+,.1f}|")
    lines += ['', output['解釈'], '', output['一般化の限界'], '']
    (audit.HERE / 'h019_participation_note.md').write_text('\n'.join(lines), encoding='utf-8')
    print('H019全5変形と指定3区間の参加説明を保存', flush=True)


if __name__ == '__main__':
    main()
