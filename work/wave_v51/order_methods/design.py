"""方向予測を使わない60種類の注文管理条件を事前固定する。"""
from pathlib import Path
import json

HERE=Path(__file__).resolve().parent


def catalog() -> list[dict]:
    """機能: 3系統60条件を損益に触れず生成する。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    output=[]
    exits=[dict(name='均衡',stop=.75,activation=1.5,width=1.),dict(name='早期保護時間減衰',stop=.5,activation=.75,width=.75)]
    for family,options in [(0,(.25,.5)),(1,(0.,)),(2,(0.,1.))]:
        for option in options:
            for cooldown in (5,15,30):
                for cycle in (60,120):
                    for exit_id in (0,1):
                        identifier=f'O{family+1:02d}_P{round(option*100):03d}_C{cooldown:02d}_T{cycle}_X{exit_id}'
                        output.append(dict(id=identifier,family=family,name=['両方向逆指値OCO突破','両建て片脚損切り追跡','予測なし方向'][family],
                                           option=option,cooldown=cooldown,cycle=cycle,exit_id=exit_id,exit=exits[exit_id]))
    assert len(output)==60
    return output


def freeze() -> dict:
    """機能: カタログと選抜規則を初回だけ固定し、その後不変を検査する。

    引数: なし。返り値: 固定仕様(dict)。
    """
    value=dict(条件=catalog(),候補数=60,初回片側枚数={'TOPIX':5,'NK225':10},片方向上限={'TOPIX':10,'NK225':20},
               円倍率={'TOPIX':1000,'NK225':10},費用=0,方向予測入力=False,
               注文仕様='判断後次の有効原本行で観測価格約定。準備したOCOは次の原本行から成立判定。片側成立時点で他方を取消。',
               公開API='StreamingPolicy(spec, start, limit, symbol).on_tick(now, seq, price, atr)。未来配列を渡さない。',
               足='既存ready.atrの当該行だけ。確定5分足の公開遅延を継承。',セッション準備秒=1200,新規終了='返済期限300秒前',
               組の期限='OCOを準備又は同時両建て/コイントスを判断した時点から60又は120分。未成立OCOも期限で取消・休止。',
               選抜='先頭10場のみ。両銘柄損益/総損失の小さい側+黒字場率平均+最大勝ち場除外損益/総損失の小さい側×0.5。各銘柄6場活動かつ15決済脚以上。',
               分割='先頭10場選抜、次9場比較、原因を既読の最後4場参考。すべて過去研究既読で真正未見ではない。',
               seed='セッションstartの整数と商品名ASCII和から固定。同じ履歴・条件なら同一列。',
               注意='両建ては両脚実現・含みを合算し、片脚だけの見かけの利益を採用しない。mini/micro価格はラージ保存価格の倍率換算。')
    path=HERE/'事前固定.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf8'))==value
    else:path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    return value


if __name__=='__main__':freeze()
