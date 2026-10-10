"""既存の公表検査を974条件の数表と156図へ接続する。"""

from pathlib import Path

HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 公表資料の指紋・全図・全リンクの検査を準備する。

    引数: なし。返り値: なし (None)。売買・経済判定は変更しない。
    """
    source=(HERE.parent/'wave_v37/publication_audit.py').read_text(encoding='utf-8')
    source=source.replace('partial_runner','adaptive_runner').replace('00032_悪化時の部分減量と回復後の数量復元','00033_復元方式の自動選択と改善8条件の反証')
    source=source.replace('悪化時の部分減量と回復後の数量復元.html','復元方式の自動選択と改善8条件の反証.html')
    source=source.replace('14518','33116').replace('427','974').replace('chart_slot_fixed','chart_fixed')
    start=source.index("    slots=runner.read(HERE/'slot_difference_audit.json')")
    end=source.index("    visual=runner.read(HERE/'chart_visual_check.json')",start)
    source=source[:start]+source[end:]
    source=source.replace("'全台帳一致','全数量asof一致'", "'全台帳一致','全数量asof一致','全分岐一致'")
    source=source.replace("'全原本足一致','全リンク一致'", "'全原本足一致','全リンク一致','全分岐根拠一致'")
    source=source.replace("'slot_difference_audit.json','slot_risk_description_revision.json','html_visual_check.json',", "'chart_backlink_revision.json','chart_format_revision.json','html_visual_check.json',")
    source=source.replace("'report_partial.py'", "'report_adaptive.py'")
    source=source.replace("    for name,sha in table['HTML_SHA256'].items():", "    assert table['合否表示数']==3 and table['候補表行数']==8 and table['全比較ラベル一致']\n    for name,sha in table['HTML_SHA256'].items():")
    (HERE/'publication_audit.py').write_text(source,encoding='utf-8')
    print('公表検査を974条件と156図へ接続。')


if __name__=='__main__':main()
