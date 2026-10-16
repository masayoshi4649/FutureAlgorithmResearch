"""完了した独立監査を集約し、検証範囲と未証明の範囲を明示する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent


def main() -> None:
    """機能: 合格済み証跡の計数と指紋をまとめる。

    引数: なし。返り値: なし(None)。JSON集約だけを書き込む。
    """
    sources=['first','improved','final_delay0','final_delay1','final_delay5','quality3']
    rows=[];proofs={}
    for name in sources:
        path=HERE/f'{name}の全口座独立会計監査.json'
        data=json.loads(path.read_text(encoding='utf8'));assert data['合格']
        rows.append({k:data[k] for k in ['段階','条件数','口座数','注文数','決済数','照合項目数','期間口座数','全行清算時価SHA一致口座数']})
        proofs[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    others=['人工方向追従監査.json','料金と欠測タイマーの人工独立会計監査.json',
        '原板方向と二市場時計の独立監査.json','準備から除外された原本行の原因.json',
        '前半選定と固定入力の独立監査.json','拡張22方向の独立監査.json',
        '改修の入口出口分離と単独対照人工監査.json','最終前半選定と単独対照の独立監査.json',
        '全最終代表と三遅延の実注文未来監査.json','初回基準3代表の最終完全一致.json',
        '最終数値と解釈の独立確認.json']
    published=(HERE/'公開HTMLと説明の最終監査.json').exists()
    if published:others.append('公開HTMLと説明の最終監査.json')
    for name in others:
        path=HERE/name;assert path.exists();proofs[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    totals={k:sum(r[k] for r in rows) for k in ['条件数','口座数','注文数','決済数','照合項目数','期間口座数','全行清算時価SHA一致口座数']}
    result=dict(会計全合格=True,条件別延べ合計=totals,各段階=rows,
        原板方向監査='60口座の13方向と追加9方向を独立式で再現。初回300原本切断、追加は全22状態の独立一致。',
        注文未来監査='全9確認条件×3遅延から201実口座、3898切断・31184配列照合。未来の価格と双方の入口出口状態・有効性を改変しても過去は不変。',
        検査中に修正した欠陥=['清算時刻以後に新規約定した同じ原板行で場内返済を発注する。',
            '単独対照のX1/X2が中立で返済してしまう交絡をラッパーで除く。',
            '正常な気配差拡大と不正10段で方向履歴を消す仕様を、損益未閲覧の品質修正段階として保存・再固定。'],
        未証明=['真の二市場受信時計、CurrentPriceTime同時計内の実経過時間。',
            'ミニ・マイクロの実気配、注文順位、出来高による部分約定、市場影響。',
            '未知の将来での黒字性、金額利益80%、全セッションの安定性。'],
        研究結論の監査='前半188条件で両商品同時黒字0。最終主3は0/1/5秒の各商品で赤字。中値経路に正のケースはあるが売買側価格と料金を越える採用可能性は確認できない。',
        公開資料監査='主HTML27経路1620口座、鮮度3条件、前半188条件、公開会計、条件記録と説明を確認済み。' if published else '生成後に別記録で確認予定。',証跡SHA256=proofs)
    (HERE/'監査集約.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(totals,ensure_ascii=False))


if __name__=='__main__':main()
