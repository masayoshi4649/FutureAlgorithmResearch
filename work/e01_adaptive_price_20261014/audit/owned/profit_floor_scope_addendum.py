"""固定全量の平均値幅と可変数量の容量換算を混同しないための純算術補足。"""

from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 旧容量監査の対象範囲に、固定10mini条件と可変数量の反例を追記証跡として束縛する。
    引数: なし。実会計や価格は読まず、保存済み先行証跡の指紋と純算術だけを使う。
    返り値: None。原証跡は上書きせず新補足を所有域へ保存する。
    """
    prior=HERE/'旧00106の実容量使用と一取引10万円床の独立算術.json'
    target=HERE/'経済床の固定全量値幅と可変数量容量換算の範囲補足.json'
    assert not target.exists()
    prior_sha=hashlib.sha256(prior.read_bytes()).hexdigest()
    assert prior_sha=='74bdcae31ce9f0693876aa3b9c42d97d9eecca5a333030ca6c12fd26f5e4bada'
    gain=10*25.5*1000-836
    loss=-1*50*1000-82
    mean=(gain+loss)/2
    assert mean==102041 and (25.5-50)/2==-12.25
    output=dict(全合格=True,先行証跡SHA256=prior_sha,
        表現の限定='平均方向値幅10.0836ptは各完結親が10miniで新規・一括返済を行う条件の算術。可変qで生価格値幅の単純平均の必要条件とは呼ばない。',
        一般的な経済床='平均net100000円は10mini容量換算の平均net10pt。実現価格値幅ではなく円損益を容量10000円/ptで除す。',
        純算術反例=dict(一親目q=10,一親目方向値幅pt=25.5,一親目net円=gain,二親目q=1,二親目方向値幅pt=-50,
            二親目net円=loss,全親平均net円=mean,生値幅単純平均pt=-12.25,
            説明='数量が異なる二つの純算術例。全親平均netは100000円以上でも生価格値幅平均は負で、後者を一般条件へ置換できない。実アルゴの成績や三基準合格例ではない。'),
        予約最低額の限定='5836円は観測ラージの正spread下限0.5pt・10mini・往復注文料836円・ATR0仮定の旧モデル算術。初回q上限5とは別制約。',
        未変更='旧容量監査・金融source・完成会計は変更していない。',
        独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        実価格読取=0,金融result再読=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,新金融=0,共有変更=0)
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
