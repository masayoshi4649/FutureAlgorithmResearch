"""保存した読取診断を七商品場の短い確認用表示へ整理する。"""

import json
from pathlib import Path


def main() -> None:
    """
    機能: 診断結果の実親と時刻だけを表示し、金融再生や大台帳読取を行わない。
    引数: なし。保存済み診断JSONを参照する。
    返り値: None。確認用の小さいJSONを標準出力に表示する。
    """
    path = Path(__file__).resolve().parent/'price_review/size_loss_diagnosis/最悪六場と旧勝ち赤字化二例の具体診断.json'
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    rows = []
    for key, account in value['場別'].items():
        parents = []
        for parent in account['新実親']:
            parents.append({k:parent[k] for k in (
                '親','side','実初回q','公開','実新規価格','返済','保存完結親',
                '公開W60','全量保持と一往復だけの場合の目標必要順行値幅','実親清算ピーク')})
        rows.append(dict(商品場=key,収支=account['新']['収支'],実親=parents,
            勝ち赤字化=account.get('旧勝ち赤字化の事後参考')))
    print(json.dumps(dict(全合格=value['全合格'],場別=rows),ensure_ascii=False))


if __name__ == '__main__':
    main()
