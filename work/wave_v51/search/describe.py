"""独立探索の選抜位置と不採用理由を、数値から短く記録する。"""
from collections import defaultdict
import json
import research as r


def main() -> None:
    """機能: 組単位勝敗・参考候補・再現手順を保存する。

    引数: なし。返り値: なし(None)。
    """
    results=r.read('結果一覧.json');choice=r.read('過去10場選択.json');names=r.read('入力構成.json')['対象']
    identifiers=choice['系統代表']+[f'R04_W30_C0_X{x}' for x in range(4)]
    campaign_stats={}
    for identifier in identifiers:
        rows=[]
        for ledger in r.read('ledgers/'+identifier+'.json.gz'):
            groups=defaultdict(float)
            for trade in ledger['trades']:groups[str(trade[11])]+=trade[6]
            values=list(groups.values());profit=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
            wins=sum(v>0 for v in values);losses=sum(v<0 for v in values)
            rows.append(dict(session=ledger['session'],symbol=ledger['symbol'],新規組数=len(values),勝組数=wins,負組数=losses,
                             引分組数=sum(v==0 for v in values),勝組利益=profit,負組損失=loss))
        campaign_stats[identifier]=dict(各場=rows,期間={})
        for label,chosen in (('開発10',names[:10]),('期間外9',names[10:19]),('原因既読4',names[19:]),('全23',names)):
            campaign_stats[identifier]['期間'][label]={}
            for symbol in ('TOPIX','NK225'):
                subset=[v for v in rows if v['session'] in chosen and v['symbol']==symbol]
                fields=['新規組数','勝組数','負組数','引分組数','勝組利益','負組損失']
                row={f:sum(v[f] for v in subset) for f in fields}
                row['組勝率']=row['勝組数']/max(1,row['新規組数'])
                row['平均勝組利益']=row['勝組利益']/max(1,row['勝組数'])
                row['平均負組損失']=row['負組損失']/max(1,row['負組数'])
                row['平均組損益比']=row['平均勝組利益']/row['平均負組損失'] if row['平均負組損失'] else None
                campaign_stats[identifier]['期間'][label][symbol]=row
    r.save('代表の組単位勝敗.json',campaign_stats)
    r.save('要点.json',dict(第一候補=choice['第一候補'],第一候補採用=False,
                           理由='先頭10場による選抜でも両銘柄赤字で、その後9場も両銘柄赤字。',
                           参考候補='R04_W30_C0_X2',参考候補の後付選択=True,
                           参考理由='30本低効率の回帰は出口4種類すべて両銘柄の全期間黒字。ただし先頭10場のTOPIX決済数不足で事前選抜条件外。',
                           全期間両銘柄黒字数=sum(all(v['全23'][s]['net']>0 for s in ('TOPIX','NK225')) for v in results.values()),
                           活動と重複=r.read('活動と重複.json'),真正未見=False))
    text='''# 独立96条件の探索

最初に `要点.json`、次に `結果一覧.json`、機械的な条件は `事前固定.json` と `research.py` を参照する。

新しい方式は実装できたが、E01を置き換える根拠は得られていない。先頭10場だけで選んだ第一候補 `R02_W15_C1_X1` は全23場でTOPIX −167,500円、NK225 −67,000円。前9場でなく後9場だけでも −120,000円、−37,000円だった。直近4場だけの改善を選抜根拠にしていない。

参考として `R04_W30_C0_X2` は、TOPIX +72,500円、NK225 +28,000円。最大の勝ち場を1つ除いても +35,000円、+16,000円。ただし活動は14/23場・15/23場、新規は24組・28組に留まり、先頭10場のTOPIX決済数が事前条件を満たさなかった。全23場を見た後の参考候補で、事前選抜の成功例ではない。出口4種類すべて同じ入口で全期間両銘柄黒字という結果はあるが、8割の場で勝てる証拠ではない。

## 何を機械的に行うか

全96条件に共通して、TOPIXは5枚、NK225は10枚で新規建てし、保有中の追加はしない。片方向上限は10枚・20枚を超えない。判断に使うのは同じセッションの1分確定足、公開済みの5分ATR、ラージ2銘柄の保存板。足は開始から120秒後（完了から60秒後）に使用し、相手はその時点以前に公開された最後の値だけを使う。判断後の次の有効原本行の価格で約定する。大きな約定遅延・費用は加算していない。mini/micro自身の約定板ではなく、ラージ価格をmini/micro倍率へ換算した検証である。

6系統は、新鮮な両市場方向への追従、平均線からの乖離を制限した追従、過去高安突破、低効率での平均回帰、追従と回帰の自動切替、公開板フローの確認付き追従。各15/30本窓、通常/厳格確認、4出口で96条件。名称『押し戻り再開』の実装は平均線付近への距離制限であり、押しが発生して再開する状態遷移を個別追跡してはいない。3/15/30本は1分足の本数であり、欠損足があると実時間はその分だけ伸びる。

### 参考R04の入口

直前30本の純価格変化÷総移動距離（効率比）が0.20以下。価格がEMA30から0.8ATR以上離れ、その乖離を戻す向きに直近3本の価格変化が0.1ATRを超える。相手市場が強い一方向相場（効率比0.30以上かつ30本変化0.5ATR超）で逆らっているときは見送る。注文判断時点で平均線まで0.25ATR以上の余地があるときだけ、平均へ戻る向きに注文する。約定時点の有利不利で注文を取り消さない。

### 参考R04の途中と出口（X2）

新規時のATRを固定。逆行0.9ATRで損切り。1ATR以上順行した後は、最高益から1.5ATRの後退で返済し、その幅を時間とともに30分で1ATRずつ狭め、最小0.5ATRとする。平均線への回帰目標は判断時点に固定する。15分経っても最大順行0.5ATR未満なら不発として返済。両市場の直近3本が反対へ0.25ATR超動いたら、追跡幅を0.5ATR以下へ縮め、5分以上保有かつ利益0.2ATR未満なら返済。最長120分。損切りした組は20分、その他は5分休止する。セッション返済期限になれば返済を判断し、後続の原本価格で閉じる。期限時刻に架空の約定を作らない。

## 検査と再現

`python work/wave_v51/search/research.py` で96条件を再生、`python work/wave_v51/search/audit.py` で因果性・会計・対称性を検査する。外部APIは使用しない。`describe.py` で説明用の組単位勝敗を再集計する。

`sessions/<ID>.json` がセッション別利益・損失・収支と勝ち/負け/引分枚数、`ledgers/<ID>.json.gz` が全注文と決済。`結果一覧.json` は先頭10場・次9場・最後4場・全23場。最後4場は原因調査後であり、ほかの期間も過去研究で閲覧済み。真正未見ではない。96条件のうち売買結果が完全同一なものを除くと89結果である。

全4,416口座の98,246注文を独立会計した。接頭辞切断と未来の足/板/価格/ATR変更で過去の判断・注文が完全一致すること、両市場の価格と板を上下反転すると売買方向のみ反転して損益と注文時刻が一致することを検査した。整数/時刻/行/注文列は完全一致、反射時の浮動値だけ絶対誤差1e-7以内とする。ATRそのものの抽出は既存の因果監査済み配列を引き継いでおり、今回、生原本からATR抽出器までを独立に再実装してはいない。

新方式の約定は次観測価格、既存E01レポートは指定価格約定なので、金額差には注文前提の差も含む。優位性を保証する比較としては扱わない。決済分割を行うX3では、`trades` と `payoff` は返済脚ごとの数値。組全体の勝率・平均勝敗比は `代表の組単位勝敗.json`、枚数あたりの損小利大は `per_contract_payoff` を見る。

板確認系は120秒内に公開されたOFIを参照する。ただし、前の約定時刻ブロックが次の時刻で公開されるデータ構造であり、公開が新しくても元ブロックの `source_time_s` は古い場合がある。今回は元ブロックの経過時間で追加除外していない。この点は既存E01の古さ判定と異なり、板確認系の成績を実際の受信時刻を使った板読みに一般化できない。
'''
    (r.HERE/'README.md').write_text(text,encoding='utf8')
    r.save('台帳形式.json',dict(orders=['判断時刻UTC秒','約定時刻UTC秒','判断原本seq','約定原本seq','1新規又は2返済','買い+1売り-1','枚数','約定価格','実現損益円','返済理由コード'],
                               trades=['新規時刻UTC秒','返済時刻UTC秒','建玉方向±1','返済枚数','新規価格','返済価格','実現損益円','返済理由コード','新規ATR','1追従2回帰','返済判断時刻UTC秒','新規約定seq','返済約定seq','返済判断seq','最大順行ATR','保有分'],返済理由=r.REASONS))


if __name__=='__main__':main()
