"""確認済みの知見と未検証の仮説を、根拠付きの読みやすい台帳へ残す。"""

from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

import common


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 104完了時点の数値を再計算せず読み、105で引き継ぐ知見を保存する。
    引数: なし。
    返り値: None。事実と推論を分けたJSON及びダークHTMLを新規保存する。
    """
    previous = common.PREVIOUS
    loss_path = previous/'支持幅と再参加及び利益保険の損失診断.json'
    boundary_path = previous/'旧自己入口の支持破れと順行の診断.json'
    assessment_path = previous/'安定性の全121判定.json'
    loss = common.read(loss_path)
    boundary = common.read(boundary_path)
    assessment = common.read(assessment_path)
    assert loss['全合格'] and boundary['全合格'] and not assessment['adoption_candidates']
    rows = []
    rows.append(dict(ID='K01', 区分='確認済み', 知見='121条件では両銘柄の安定性・金額利益80%を満たす採用手法はなかった。',
        範囲='従来32場の比較。追加10月13日デイも別確認済み。全手法の不可能性を証明したわけではない。',
        判断='最大収益だけで選ばず、赤字頻度・損失規模・最大勝ち除外後の収支を各銘柄で評価する。',
        根拠=[str(assessment_path.relative_to(common.ROOT))]))
    values = loss['summary']['C_OWN_T2']
    parts = []
    for symbol, label in (('TOPIX', 'TOPIX'), ('NK225', '日経')):
        value = values[symbol]['損失取引']
        parts.append(f'{label} {value["count"]}件中{value["net_loss_before_activation"]}件')
    rows.append(dict(ID='K02', 区分='確認済み', 知見='狭い利益追尾T2の損失は、利益保護の発動前が大部分。'+ '、'.join(parts)+'。',
        範囲='C_OWN_T2・従来32場・各1枚。原因の事後分類で、当時の予測条件ではない。',
        判断='発動後の利確幅だけを変えても、同じ入口・同じ初期停止線の発動前損失は救えない。', 根拠=[str(loss_path.relative_to(common.ROOT))]))
    rows.append(dict(ID='K03', 区分='確認済み', 知見='名目の利益追尾2呼値に対し、入口から初期停止線までの距離の中央値は両銘柄4呼値。',
        範囲='C_OWN_T2・従来32場。初期停止線で確実に約定するとは仮定していない。',
        判断='初期リスクと利益追尾幅を別変数として評価する。リスクを広げれば有利になるとは未確認。', 根拠=[str(loss_path.relative_to(common.ROOT))]))
    rows.append(dict(ID='K04', 区分='否定された条件', 知見='この入口で利益追尾だけを狭め、再参加を増やす変更は安定性を改善しなかった。',
        範囲='C_OWNのB2→T2。TOPIXは取引243→436回、平均利益18,501→1,177円、平均損失1,938→1,896円。',
        判断='失う利益と増える再参加損失を必ず別集計する。狭い追尾という技法全体の否定ではない。', 根拠=[str(loss_path.relative_to(common.ROOT))]))
    parts = []
    for symbol, label in (('TOPIX', 'TOPIX'), ('NK225', '日経')):
        value = boundary['totals']['C_OWN'][symbol]['利益']
        parts.append(f'{label} {value["count"]}件中{value["boundaries"]["2"]["crossed"]}件')
    rows.append(dict(ID='K05', 区分='確認済み', 知見='旧出口で最終的に勝った取引にも、固定支持から2呼値外へ一度逆行する例がある。'+'、'.join(parts)+'。',
        範囲='旧C_OWN_Oの事後経路診断。これから戻るかどうかは当時には未確定。',
        判断='支持線を割ったら必ず方向を誤った、とは扱えない。損切りを厳しくする変更で失う勝ちも計算する。', 根拠=[str(boundary_path.relative_to(common.ROOT))]))
    rows.append(dict(ID='H01', 区分='未検証の仮説', 知見='直前の往復が大きく、停止余裕が足りない入口を見送る。',
        範囲='自己・相手市場の過去10/30秒の気配経路だけで測る。', 判断='入口直後の逆行を減らすか、勝ちだけを減らしていないかを部品対照で確認する。',
        根拠=['work/wave_v104/peer/次反復案/105_入口品質の3候補_未検証.json']))
    rows.append(dict(ID='H02', 区分='未検証の仮説', 知見='損切りした同方向・同じ支持帯への再参加を、新しい根拠が生まれるまで抑える。',
        範囲='当時の支持価格と初期リスクで帯を固定する。未来の往復幅は使わない。', 判断='防げた連敗と、失った回復利益を両方記録する。',
        根拠=['work/wave_v104/engine/初期リスクと利益追尾及び価格帯再参加の最小案.json']))
    rows.append(dict(ID='H03', 区分='未検証の仮説', 知見='初期リスクに応じた利益追尾と、セッション損失停止を独立に試す。',
        範囲='利益追尾と損失停止の効果を混ぜない。次の正常気配で返済するため予算超過はあり得る。',
        判断='赤字の減少だけで採用せず、活動場数・残る利益・大勝ちへの依存も判定する。',
        根拠=['work/wave_v104/engine/初期リスクと利益追尾及び価格帯再参加の最小案.json']))
    paths = sorted({name for row in rows for name in row['根拠']})
    value = dict(更新日時=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        対象='104完了時点から105へ引き継ぐ知見。全過去研究を網羅した台帳ではない。',
        成功条件='各銘柄の手数料後の安定収益・損小利大。無取引を勝ちに数えない。',
        状態='105の個別損失診断と改修検証を進行中。新しい改善効果はまだ未確認。',
        知見=rows, 根拠SHA256={name: common.digest(common.ROOT/name) for name in paths})
    common.save(HERE/'知見台帳.json', value)
    body = []
    for row in rows:
        links = ' ／ '.join('<a href="../../'+escape(name.replace('\\', '/'))+'">根拠'+str(i+1)+'</a>' for i,name in enumerate(row['根拠']))
        body.append('<tr><th>'+escape(row['ID'])+'<br>'+escape(row['区分'])+'</th><td><b>'+escape(row['知見'])+'</b><p>'+escape(row['範囲'])+'</p></td><td>'+escape(row['判断'])+'<p>'+links+'</p></td></tr>')
    document = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>検証の知見台帳</title><style>
body{background:#101723;color:#e4edf8;font-family:Meiryo,sans-serif;line-height:1.7;margin:24px auto;padding:0 16px;max-width:1250px}a{color:#96c9ff}table{border-collapse:collapse;width:100%}th,td{border:1px solid #39485b;padding:14px;vertical-align:top}th{min-width:120px;background:#203049}td p{color:#bdcce0}h1{font-size:26px}.scroll{overflow:auto}footer{margin-top:20px}
</style><!--
[コンポーネント概要]
.scroll は知見、検証範囲、次の判断を並べる表の横閲覧領域です。
確認済みと未検証の仮説を文字で分け、各行から根拠へ移動できます。
この資料は保存済みの知見を表示し、外部通信や注文は行いません。
--><h1>検証の知見台帳</h1>'''
    document += '<p>'+escape(value['対象'])+'</p><p><b>'+escape(value['状態'])+'</b></p><div class="scroll"><table><thead><tr><th>分類</th><th>わかったこと・範囲</th><th>今後の扱い</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div><footer><a href="知見台帳.json">根拠指紋を含む全台帳</a></footer></html>'
    (HERE/'知見台帳.html').write_text(document, encoding='utf-8')
    print('根拠付きの知見8件を保存しました。', flush=True)


if __name__ == '__main__':
    main()
