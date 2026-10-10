"""方向予測なし注文管理の結果を組単位で補足し、使い方を記録する。"""
from collections import defaultdict
import json
import research as r


def main() -> None:
    """機能: 組単位集計と再現手順を今回領域へ出力する。

    引数: なし。返り値: なし(None)。
    """
    selected=r.read('過去10場選択.json');names=r.read('完了.json')['対象'];result=r.read('結果一覧.json')
    identifiers=selected['系統代表']+['O03_P100_C05_T60_X0','O03_P100_C05_T120_X0']
    output={}
    for identifier in identifiers:
        rows=[]
        for ledger in r.read('ledgers/'+identifier+'.json.gz'):
            groups=defaultdict(float)
            for trade in ledger['trades']:groups[str(trade[11])]+=trade[6]
            amounts=list(groups.values())
            rows.append(dict(session=ledger['session'],symbol=ledger['symbol'],組数=len(amounts),勝組数=sum(x>0 for x in amounts),
                             負組数=sum(x<0 for x in amounts),引分組数=sum(x==0 for x in amounts),
                             勝組利益=sum(x for x in amounts if x>0),負組損失=-sum(x for x in amounts if x<0),収支=sum(amounts)))
        output[identifier]=dict(各場=rows,期間={})
        for label,chosen in [('開発10',names[:10]),('期間外9',names[10:19]),('原因既読4',names[19:]),('全23',names)]:
            output[identifier]['期間'][label]={}
            for symbol in ('TOPIX','NK225'):
                chosen_rows=[v for v in rows if v['session'] in chosen and v['symbol']==symbol]
                fields=['組数','勝組数','負組数','引分組数','勝組利益','負組損失','収支'];row={f:sum(v[f] for v in chosen_rows) for f in fields}
                row['組勝率']=row['勝組数']/max(1,row['組数'])
                row['平均勝組利益']=row['勝組利益']/max(1,row['勝組数']);row['平均負組損失']=row['負組損失']/max(1,row['負組数'])
                row['平均組勝敗比']=row['平均勝組利益']/row['平均負組損失'] if row['平均負組損失'] else None
                output[identifier]['期間'][label][symbol]=row
    r.save('代表の組単位勝敗.json',output)
    r.save('要点.json',dict(候補数=60,選択=selected,事前第一候補採用=False,
                           理由='先頭10場の1位は、その後9場のTOPIXで407500円損失。直近4場の改善を採用根拠にできない。',
                           両銘柄全期間黒字=[i for i,v in result.items() if all(v['全23'][s]['net']>0 for s in ('TOPIX','NK225'))],
                           約定='判断後次有効観測価格。指定価格理想約定E01との比較は前提差あり。',
                           両建て='両脚合算。初期同量同値の両建ては含みが相殺され、片脚決済後の合算価格損益はその時点から残った側へ新規した損益と等しい。',
                           真正未見=False))
    schema=json.loads((r.SEARCH/'台帳形式.json').read_text(encoding='utf8'));schema['trades'][9]='方式番号1:OCO/2:両建て/3:予測なし方向'
    r.save('台帳形式.json',schema)
    (r.HERE/'README.md').write_text('''# 方向予測を使わない60条件

最初は `要点.json`、次に `結果一覧.json`。実行可能な逐次ポリシーは `policy.py`、固定条件は `事前固定.json`、セッション別金額・枚数は `sessions/<ID>.json`、全注文は `ledgers/<ID>.json.gz`、両建ての組全体は `代表の組単位勝敗.json`。

先頭10場の結果だけで選んだ `O03_P000_C05_T60_X0`（固定seedの方向・5分休止・60分上限）は、全23場でTOPIX −127,500円、NK225 +36,000円。その後9場のTOPIXは −407,500円であり、採用できる根拠にならなかった。直近4場だけでは +182,500円／+21,000円なので、直近だけを救う方向選びは危険だと分かる。

|系統と先頭10場の代表|TOPIX全23場|NK225全23場|
|---|---:|---:|
|OCO：O01_P025_C30_T120_X0|+130,000円|−41,000円|
|両建て：O02_P000_C30_T60_X1|−545,000円|−110,000円|
|固定seed方向：O03_P000_C05_T60_X0|−127,500円|+36,000円|

60条件のうち全23場で両銘柄黒字は交互方向の2条件だけ。ただし `O03_P100_C05_T60_X0` の全収支 +80,000円／+109,000円は各銘柄の最大勝ち場を1つ除くと −155,000円／−52,000円。`O03_P100_C05_T120_X0` は +142,500円／+197,000円、最大勝ち場を除くと −165,000円／+44,000円。後付参考であり、安定した解とは呼ばない。

## 何をしたか

方向予測の入力は使わない。現在価格・現在時刻・原本行番号・その時点で公開済みのATRだけを、原本順に一件ずつ渡す。TOPIXは片側5枚、NK225は片側10枚。上限は片側10枚・20枚を超えない。費用0、次の有効観測価格で約定。mini/micro自身の板ではなくラージの保存価格をmini/micro倍率に換算した研究である。

1. **OCO**：現在価格の上下0.25又は0.5ATRへ逆指値を準備。準備行では成立させず、後続行で片側を抜けたら注文判断し、反対側を取消。約定はさらに次の有効観測。
2. **同時両建て**：同じ数量を同時に買い・売り。各脚を固定損切りと利益追跡で処理し、両脚の合計を評価する。利益側だけを集計しない。
3. **予測なし方向**：事前固定したseedの疑似乱数、又は買い・売り交互で方向を決定。価格を見て方向を選ばない。seedは結果を見て変更していない。

各系統で組終了後の休止を5/15/30分、組の最長時間を60/120分、出口を2種類比較した。均衡出口は損切り0.75ATR、利益1.5ATRから1ATR幅の追跡。早期保護出口は損切り0.5ATR、利益0.75ATRから0.75ATR幅で追跡し、60分で1ATRの速さで幅を狭め、最小0.25ATRとする。15分経って最大順行0.25ATR未満なら不発撤退。組の時計は注文準備から数え、未成立OCOも時間上限で取消す。

ATRは判断時の公開済み値を新規組に固定し、将来のATRで書き換えない。新規はセッション返済期限の300秒前まで。保有は返済期限到達で返済判断し、後続行で閉じる。期末の架空価格で返済しない。

両建ては、両方を同量・同値で保有している間は含み損益が完全に相殺される。負け側を閉じた後は、閉じた損失と残り玉の含み益を合計すると「その決済時点の価格から残った方向へ新規した損益」に等しい。両建てそのものが無料で利益を作るわけではなく、その後の方向継続と出口に依存する。今回の12両建て条件では安定改善は確認できなかった。

## 逐次API

```python
from policy import StreamingPolicy
policy = StreamingPolicy(spec, session_start, close_limit, 'TOPIX')
event = policy.on_tick(now, seq, current_price, published_atr)
```

`now` はUTC秒、`seq` は増加する原本行番号。返り値の `orders` / `trades` は今回の観測で約定した注文・決済、`equity` は両脚合算の実現＋含み、`net_positions` は買い・売り枚数、`cycle` は準備した組番号。未約定の判断は内部状態に保持する。全未来配列はこのクラスの引数にも状態にもない。原本配列を持つ高速driverも、同じ `on_tick_step` へ現在の四つの値だけを渡す。

## 再現と検査

`python work/wave_v51/order_methods/research.py`、`python work/wave_v51/order_methods/audit.py`、`python work/wave_v51/order_methods/describe.py` の順。ネットワークは使わない。先頭10場のみ選択、次9場比較、最後4場は原因既読の参考。全期間は過去研究で閲覧済みで真正未見ではない。

全2,760口座・121,142注文を独立会計。全60条件×2銘柄×2箇所で未来削除と未来価格/ATR変更を行い、過去注文が完全一致した。代表3方式×2銘柄では、公開 `on_tick` と高速driverの全注文・決済・最終状態が完全一致。同量同価格の両建て8,903組を確認。無変動市場では60条件すべて収支0、両建て相殺恒等式も確認済み。

返済脚の勝率と両建て1組の勝率は違う。`結果一覧.json` の `trades` は返済脚数、組単位勝率は `代表の組単位勝敗.json` を参照する。既存E01の指定価格約定とは約定前提も異なるため、金額差を戦略の優劣だけに帰属させない。
''',encoding='utf8')


if __name__=='__main__':main()
