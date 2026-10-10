"""全974条件の表示を独立明細から検査する実装を作る。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 既存の数値検算と表示操作を今回の固定集合へ接続する。

    引数: なし。返り値: なし (None)。売買結果を生成しない。
    """
    text=(HERE.parent/'wave_v37/report_contract_audit.py').read_text(encoding='utf-8')
    text=text.replace('partial_design','adaptive_design').replace('00032_悪化時の部分減量と回復後の数量復元','00033_復元方式の自動選択と改善8条件の反証').replace('悪化時の部分減量と回復後の数量復元','復元方式の自動選択と改善8条件の反証').replace('427','974')
    text=text.replace('    count = 0','    tables_by_key={(t["data-id"],t["data-symbol"]):t for t in soup.select("table[data-id][data-symbol]")}\n    assert len(tables_by_key)==1948\n    count = 0')
    text=text.replace("            tables = soup.select(f'table[data-id=\"{spec[\"id\"]}\"][data-symbol=\"{symbol}\"]')\n            assert len(tables) == 1\n            count += numeric.check_money(tables[0],", "            table=tables_by_key[(spec['id'],symbol)]\n            count += numeric.check_money(table,")
    text=text.replace("hash_targets=[r['id'] for r in numeric.read(HERE/'全格子の機序診断.json')['全格子'] if r['A0比較']['同時改善']]","hash_targets=['H019__'+p+'__R1__V000' for p in design.SELECTED]")
    text=text.replace("policies = ('A0', 'CORE50', 'SMALL50', 'B06_NONE_F50', 'B06_T120_F50_N1', design.PRIMARY_POLICY)",
        "identifiers=('H019__A0__R1__V000',design.PRIMARY_ID,'H019__B06_RB01_F50_N1__R1__V000',\n        'H019__'+design.CLOCK_POLICY+'__R1__V000','H019__'+design.REVERSE_POLICY+'__R1__V000',\n        design.PRIMARY_ID.replace('__R1__','__R0__'))")
    text=text.replace('for line, (symbol, policy) in zip(printed, [(s,p) for s in (\'TOPIX\',\'NK225\') for p in policies]):\n            identifier = \'H019__\'+policy+\'__V000\'',
        "for line, (symbol, identifier) in zip(printed, [(s,p) for s in ('TOPIX','NK225') for p in identifiers]):")
    (HERE/'report_contract_audit.py').write_text(text,encoding='utf-8')
    print('974条件の数表・比較・表示操作検査を用意。')


if __name__=='__main__':main()
