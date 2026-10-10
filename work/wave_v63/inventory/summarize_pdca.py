"""三つの改善ラウンドを上書きせず統合し、改善と反証を同じ基準で記録する。"""

import json
from pathlib import Path
import pickle

import numpy as np

from run import save,digest


HERE=Path(__file__).resolve().parent


def compare(left: str,right: str,symbol: str) -> dict:
    """機能: 同一入口の返済差と、管理変更で増減した入口集合を分ける。

    引数: left/right/symbol(str)。返り値: 同一入口での勝敗変化と集計差(dict)。
    同一入口の比較も事後診断であり、未来を入口選別へ戻さない。
    """
    a=pickle.loads((HERE/'ledger'/f'{left}.pkl').read_bytes())
    b=pickle.loads((HERE/'ledger'/f'{right}.pkl').read_bytes())
    aa={(key[0],int(g[3])):g for key,v in a.items() if key[1]==symbol for g in v['groups']}
    bb={(key[0],int(g[3])):g for key,v in b.items() if key[1]==symbol for g in v['groups']}
    common=aa.keys()&bb.keys()
    gain=sum(bb[k][11]-aa[k][11] for k in common)
    added=sum(bb[k][11] for k in bb.keys()-aa.keys())
    removed=-sum(aa[k][11] for k in aa.keys()-bb.keys())
    return dict(before=left,after=right,symbol=symbol,common_entries=len(common),added_entries=len(bb.keys()-aa.keys()),
        removed_entries=len(aa.keys()-bb.keys()),common_delta=gain,added_net=added,removed_net_difference=removed,
        net_difference=gain+added+removed,
        loss_to_profit=sum(aa[k][11]<0 and bb[k][11]>0 for k in common),
        profit_to_loss=sum(aa[k][11]>0 and bb[k][11]<0 for k in common),
        smaller_winner_count=sum(aa[k][11]>0 and 0<bb[k][11]<aa[k][11] for k in common),
        smaller_winner_difference=sum(bb[k][11]-aa[k][11] for k in common if aa[k][11]>0 and 0<bb[k][11]<aa[k][11]))


def main() -> None:
    """機能: 42モデルの全場会計と事前主条件を統合し、95%達成の有無を保存する。

    引数: なし。返り値: なし(None)。結果による条件追加・変更は行わない。
    """
    rounds=[json.loads((HERE/f'R{n}_集計結果.json').read_text(encoding='utf8')) for n in (1,2,3)]
    methods=[m for r in rounds for m in r['methods']]
    result=dict(meta=dict(rounds=3,models=len(methods),accounts=sum(len(m['accounts']) for m in methods),
        primary_ids=[m['id'] for m in methods if m['primary']],api_calls=0,
        group_definition='全玉が0へ戻るまでの入口・返済費用後往復。単一在庫・追加部分返済なし、各組2注文。',
        price_modes={'Q':'次原本行気配','E':'新規のみ待機指値','P':'新規と利確が待機指値','M':'独立中値参考'},
        source_sha256={f'R{n}_集計結果.json':digest(HERE/f'R{n}_集計結果.json') for n in (1,2,3)},
        passed_95=[dict(id=m['id'],symbol=s) for m in methods for s in ('TOPIX','NK225') if m['summary'][s]['raw_95_pass']],
        note='全25場既読。各ラウンドの条件は当該ラウンド損益前固定。事後改善研究であり未知汎化は未検証。'),methods=methods)
    save(HERE/'集計結果.json',result)
    comparisons=[compare(f'R2_G{g}_Q',f'R3_G{g}_J1_Q',s) for g in (2,3) for s in ('TOPIX','NK225')]
    save(HERE/'利益保護の同一入口比較.json',comparisons)
    # ----------------------------------------
    # 公開報告は主三案の失敗も残す。最高利益への主案差し替えをしない。
    lines=['# 在庫・執行の原因分析と三段階の改善','',
        '費用後の決済取引95%を達成した条件はありません。42モデルを25場・2銘柄で評価しました。全場は既読であり、未知データへの合格ではありません。','',
        '## 何が赤字を生んでいたか','',
        '旧在庫の平均回帰型は、同じ注文を中値へ付け替えると黒字になる例がありました。気配を跨ぐ価格差がその小さい優位を上回ります。一方、利益方向への追加型は同注文中値でも赤字で、すべてを費用だけのせいにはできません。',
        '旧I1の全flat組勝率はTOPIX69.8%・NK67.1%でも、平均勝ち/平均負けは0.313・0.274でした。途中利確だけを数えると、この逆行玉の損失を見落とします。','',
        '## R1：追加玉を止め、待機指値の効果を分ける','',
        '過去5分の平均から離れた側で一度だけ入り、1幅で損切り・1.5幅で利確・15分で返済します。次行気配、新規だけ指値、新規と利確が指値、中値参考を比較しました。',
        '待機指値だけでは黒字化しませんでした。保守的な1呼値通過を要求すると、狭い幅では約定した瞬間に損切り位置へ接近します。これは実際の小型商品の指値約定を保証した結果ではなく、通過約定仮定の感度です。','',
        '## R2：補充と価格の戻りを確認する','',
        '幅が気配差に対して小さすぎる場合を除き、低い方向効率、最良価格での数量回復、OFI・執行代理・直近価格の同意を個別に追加しました。',
        'TOPIXでは選別が改善しましたが、主条件は31組・勝率41.9%・収支4,542円に留まります。最大利益場を除くと−54,204円、最大資産減少70,643円です。NKは78組・23.1%・−149,160円で、共通の95%手法ではありません。','',
        '## R3：順行した利益と場の利益を守る','',
        '1幅順行したら費用を超える位置と半幅のトレールで保護します。別対照では場の時価利益が3幅分へ到達した後、1幅分の減少で終了します。元の損切り幅を広げません。',
        '主条件の勝率はTOPIX48.4%・NK30.8%へ上がりましたが、収支は−12,958円・−143,160円でした。勝率を上げる管理が平均利益も削るため、利益改善とは一致しません。','',
        '## 解釈の限界','',
        '指値は事前待機があり、実際に価格が1ラージ呼値通過した場合だけ約定とします。注文順番・小型板・個別約定内訳は不明です。CurrentPriceTimeは最終約定の時計であり、実受信時刻や注文遅延を直接示しません。',
        '補充は表示量の回復であり、同じ主体の補充や心理を識別しません。OFIには既に起きた価格変化を含みます。保有時間の変更は次の採用入口も変えるため、運用全体の差と同一入口の差を分けて保存しました。','',
        '補充価格の条件は、現在の最良価格と回復を観測した価格の比較です。間の全行で一度も割れなかった条件ではありません。','',
        '待機注文の前に並んだ数量を約定出来高で消費する別の指値仮定は未検証です。ラージの板数量からmini/microの待ち順を識別できないため、今回の95%達成証拠には加えていません。','',
        '利益を95%の確率で得ながら平均勝ちを平均負けより大きくするには、観測上PFが19を超える必要があります。今回は未達を明示し、少額勝ち・稀な大損や勝ち玉だけの集計を成功に数えません。','',
        '参照：`集計結果.json`、各 `R*_仕様.json`・`R*_実行前固定.json`、`利益保護の同一入口比較.json`、`ledger/*.pkl`。']
    (HERE/'原因と改善結果.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(clean_print(result['meta']),ensure_ascii=False))


def clean_print(meta: dict) -> dict:
    """機能: 実行結果の件数だけを表示する。

    引数: meta(dict)。返り値: 短い表示用辞書(dict)。
    """
    return {k:meta[k] for k in ('models','accounts','primary_ids','passed_95')}


if __name__=='__main__':
    main()
