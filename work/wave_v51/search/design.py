"""新しい独立口座方式の比較条件を損益計算前に固定する。"""
from pathlib import Path
import json

HERE = Path(__file__).resolve().parent


def catalog() -> list[dict]:
    """機能: 6系統96条件を一定順で生成する。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    names = ['新鮮両市場追従', '押し戻り再開', '過去高安突破', '低効率往復', '追従往復自動切替', '板フロー確認追従']
    exits = [dict(name='均衡', stop=1., activation=1.25, width=1.25, max_minutes=120, cooldown=5),
             dict(name='早期保護', stop=.65, activation=.75, width=.65, max_minutes=90, cooldown=5),
             dict(name='時間減衰', stop=.9, activation=1., width=1.5, max_minutes=120, cooldown=20),
             dict(name='半数利確', stop=.75, activation=1.5, width=1., max_minutes=180, cooldown=10)]
    return [dict(id=f'R{family+1:02d}_W{window}_C{confirmation}_X{exit_id}', family=family, name=names[family],
                 window=window, confirmation=confirmation, exit_id=exit_id, exit=exits[exit_id])
            for family in range(6) for window in (15,30) for confirmation in (0,1) for exit_id in range(4)]


def freeze() -> dict:
    """機能: 比較設計を初回だけ保存し、その後の条件不変を検査する。

    引数: なし。返り値: 設計(dict)。
    """
    value = dict(候補数=96, 条件=catalog(), 初回枚数={'TOPIX':5,'NK225':10},
                 片方向上限={'TOPIX':10,'NK225':20}, 円倍率={'TOPIX':1000,'NK225':10},
                 費用=0, セッション跨ぎ=False, 前提='ラージ実観測価格をmini/microへ換算。注文判断後の次の有効原本行価格で約定。',
                 過去分割='先頭10場だけで候補選択、次9場は期間外比較、末尾4場は原因閲覧後の参考。全期間は既読で真正未見ではない。',
                 選択='先頭10場: 両銘柄損益/総損失の小さい側 + 平均黒字場率 + 最良場除外損益/総損失の小さい側の0.5倍。各銘柄6場以上活動かつ15決済以上を要求。系統毎1位と全体1位。',
                 足公開遅延秒=120, 注記='足開始+120秒=完了から60秒。ATRは従来の確定5分足公開列をasof参照。板フローは保存済み解放特徴のみ。',
                 新方式='E01の影口座を廃止した独立方式。売買過程の影口座反転とは異なる。')
    path = HERE/'事前固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8')) == value
    else:
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    return value


if __name__ == '__main__':
    freeze()
