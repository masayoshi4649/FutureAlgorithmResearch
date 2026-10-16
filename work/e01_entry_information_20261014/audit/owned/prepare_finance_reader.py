"""旧独立checkerの純会計機能だけを新所有域へ写す一回の準備。"""

from pathlib import Path


def main() -> None:
    """
    機能: source本文だけから旧親算術の部品を新checkerへ保存する。
    引数: なし。
    返り値: None。金融JSON又は旧台帳を読まない。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[3]
    source = root / 'work/e01_price_exit_ablation_20261014/audit/owned/price_exit_finance_small_check.py'
    text = source.read_text(encoding='utf-8').split('# ----------------------------------------\ndef compare_on')[0]
    text = text.replace('反票OFF新792会計と保存ON集計/各場net差を一読の小資料だけで検算する。',
                        '495唯一と99同値及び198PRICE保存を分け、入口代理の署名と全場会計を検算する。')
    text = text.replace('e01_price_exit_ablation_20261014/engine', 'e01_entry_information_20261014/engine')
    text = text.replace("EXPECTED_SHA='6bc96e20d9ea72af1df51ed73d4595be5cadc1e9ac8760c9a69a1a501cd8886d'",
                        "EXPECTED_SHA='9c4ec0cb94e09f27a98c6c9462a5de1cc4b6532e5c447f7fa3fc94202a647000'")
    destination = here / 'entry_information_finance_small_check.py'
    assert not destination.exists()
    destination.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
