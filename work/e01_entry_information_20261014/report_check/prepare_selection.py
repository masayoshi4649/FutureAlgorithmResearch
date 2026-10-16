"""00110の十二比較と九新金融を分け、結果前の表示選定を固定する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能: 109と同順位で、十二入口比較から商品別に一組固定する方針を保存する。
    引数: なし。コピー元は金融前109の小選定JSONのみ。
    返り値: None。新金融・旧金融・入力・台帳・API・公開の実行は0。
    """
    source = ROOT/'work/e01_price_exit_ablation_20261014/報告書選定の事前固定_v2.json'
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '54dd2e7f3f0f8f7b5791246c10a2f9a391895ea3bc8564755d0be3017fefd344'
    target = HERE/'報告書選定の事前固定_v1.json'
    assert not target.exists()
    value = json.loads(raw.decode('utf-8'))
    value['段階'] = '00110新出来高代理九条件の金融本文閲覧前'
    value['選定対象'] = '全十二比較。新VOL九条件と保存PRICE_BOTH三条件から商品ごとに一組を選び、全三十三場へ固定する。保存三条件を新金融又は独立標本へ算入しない。'
    value['標本'] = '同じ保存三十三場の既知内探索。新金融594会計と保存198会計で792比較、新九条件と保存三条件を混同しない。'
    value['旧評価訂正'] = dict(旧00109全十二主条件合格数=0,
        解釈='価格票のみの原新規三条件は保存再利用。新金融0で、その旧結果も全商品net赤字。')
    value['改訂理由'] = '全ORIGINで入口情報だけを四条件に分離。数量・FAK価格票0.75許容・三出口・親場停止・静観・paper退出は固定。評価基準・順位は109と同じ。'
    value['旧選定SHA256'] = hashlib.sha256(raw).hexdigest()
    value['コピー元選定SHA256'] = hashlib.sha256(raw).hexdigest()
    value['比較未測'] = '保存PRICE三条件の旧実親経路は再コピーしない。保存集計のMAEなどは値がある範囲だけ引用し、欠測を0にしない。'
    value['禁止'] = [s for s in value['禁止'] if '旧ON' not in s]
    value['入口定義'] = [
        'PRICE_BOTHは両市場の正常Last隣接非零変化各一票。各2票・自己方向balance0.25以上。',
        '出来高代理は公表出来高正増を伴うLast対直前raw BBOの一更新一票。保存paper方向signed釣合いを再signしない。真の攻撃注文方向・攻撃量ではない。',
        'VOL_SELECTEDの釣合いはTOPIX0.5・NK0.25、VOL25は両0.25、ANDはVOL25とPRICE_BOTHを共に必要とする。',
        'proxyの未知を反票や零へ補完しない。価格時計proxyの物理先後は未証明。'
    ]
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 選定SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        新金融条件=9, 保存比較条件=3, 全比較=12, 金融=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
