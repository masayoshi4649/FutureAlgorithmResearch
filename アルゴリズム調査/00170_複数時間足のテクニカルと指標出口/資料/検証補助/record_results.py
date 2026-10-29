"""検証済みの新知見と結果参照だけを共通領域へ追記する。"""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


def digest(path):
    """
    機能: 正本資料の指紋を計算する。
    引数: path(Path)は小容量の資料。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_fact(path, anchor, text):
    """
    機能: 同じ出典アンカーの二重追記を防ぐ。
    引数: path(Path),anchor(str),text(str)。
    返り値: None。既存の知見を削除・置換しない。
    """
    if anchor in path.read_text(encoding='utf-8'):return
    with path.open('a',encoding='utf-8',newline='\n') as f:f.write('\n\n'+text.strip()+'\n')


def main():
    """
    機能: 実測法則の範囲を明記し、台帳は小さな参照行だけ追記する。
    引数: なし。
    返り値: None。
    """
    here=Path(__file__).resolve().parent;root=here.parents[1]
    study=root/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    common=root/'アルゴリズム調査/共通/知見台帳'
    append_fact(common/'入口.md','00170_複数時間足のテクニカル_確認率','''<a id="00170_複数時間足のテクニカル_確認率"></a>

## 多指標の一致と、入口の的中率を混同しない

**出典：** [00170_複数時間足のテクニカルと指標出口](../../00170_複数時間足のテクニカルと指標出口/指標仮説の確認結果.md)。

MA・RSI・MACD・BB・DMIから過去手法非参照で12仮説を固定。A/B時間足・I/F出口・2銘柄・昼夜の192区分のうち、検討前34場で黒字18区分、確認後23場でも黒字は2区分。これは条件区分の再現率であり、個々の入口の成功確率ではない。各mini10枚・手数料0・ラージBBOの次正常原行約定。

固定選定のTOPIX日中F09B_Fは確認＋1万円だが新規1回/12場、無取引11場。低頻度で損失が少ないことを高確度・安定収益としない。複数指標は同じ価格を変換したもので、票数の多さを独立証拠の数へ読み替えない。テクニカル一般の不可能性を証明した検証でもない。''')
    append_fact(common/'継続.md','00170_指標支持と継続の対照','''<a id="00170_指標支持と継続の対照"></a>

## 指標の支持失効で降りる効果は、入口仮説に依存する

**出典：** [00170_同初回入口の出口対照](../../00170_複数時間足のテクニカルと指標出口/損失経路の確認.md)。

日経夜間F10B_I（DMI交差＋ADX上昇）は全52決済、途中の正益消失34件、正益を見てから最終赤字13件。初回入口の原行・方向が一致する25場の最初の1取引ずつを比較した合計でIは−39万円、指標失効を無効にしたTは−28万円。支持失効が必ず損失を減らすとは言えなかった。

一方TOPIX夜間F03Bの同初回11場の最初の1取引ずつを比較した合計はF＋1万円、I−8.5万円、T−15万円。I/F/Tは同じ入口式でも途中の保有時間が違い、2回目以降の入口は一致しない。選択は前半で固定、ここは全既知場の部品診断であり、未知期間の一般法則ではない。''')
    append_fact(common/'出口.md','00170_利益床と原行約定','''<a id="00170_利益床と原行約定"></a>

## 早期利益床が防ぐ赤字と、約定までの戻りを分ける

**出典：** [00170_原板の具体例](../../00170_複数時間足のテクニカルと指標出口/原板で確認した具体例.md)。

日経2026-10-16日中のF09A_Iは15:00:01に65730買い10mini、最高含み＋5万円から15:15:00に65530返済で−20万円。I/Tは同結果だが、事前固定F（＋0.04%で＋0.01%利益床）は同日0円へ改善した。最良高値での利確という未来情報は使っていない。

この一場の改善を全体の完成としない。TOPIX夜間F03Bの床理由3決済は合計0円で、床を置いた価格の利益は保証されなかった。約定は条件成立の次正常原行の返済側BBO。床到達・返済判断・実約定を分け、気配の飛びや商品差を隠さない。''')
    append_fact(common/'売買の工夫.md','00170_最小約定記録と独立照合','''<a id="00170_最小約定記録と独立照合"></a>

## 約定だけを保存し、原板から損益経路を復元する

**出典：** [00170_表示資料監査](../../00170_複数時間足のテクニカルと指標出口/表示資料監査.json)。

固定4枠と出口対照の285場資料は、所有ID付き350約定片・JSONL合計115,594バイトで保存できた。原板・全tick保有・含みのコピーは不要。独立再計算で全リソースの利益/損失と残玉ゼロが一致し、3区間のViewer画像と数値は同じデータ指紋で照合した。

mini10枚とラージ板10枚は別の数量。ラージ1枚はmini10枚相当であり、そのまま枚数を比較しない。今回の約定価格は参照ラージBBOを使う共通モデルで、実際のmini板の約定可能量を検証した結果ではない。''')
    # ----------------------------------------
    # 結果の正本を小さな参照だけで辿り、旧巨大台帳を複製しません。
    files=['README.md','全候補と損益.md','比較.resources.json','結果監査.json','表示資料監査.json','選定固定.json','確認集計.json','損失経路の確認.md','原板で確認した具体例.md','指標仮説の確認結果.md']
    refs=[{'path':(study/name).relative_to(root).as_posix(),'sha256':digest(study/name)} for name in files]
    obj={'trial_id':'R170_001','status':'検証完了','at':datetime.now().astimezone().isoformat(),'plan_sha256':digest(study/'計画.json'),'results':refs,'finding':'固定4枠は確認3赤字、残る黒字も新規1回。安定収益の達成とは扱わない。','historical_comparison':'方式設計時の過去資料非参照を優先し、旧台帳との類似照合は未実施。'}
    registry=root/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials_v3.jsonl'
    existing=[json.loads(line) for line in registry.read_text(encoding='utf-8').splitlines() if line.strip()]
    if any(x['trial_id']=='R170_001' and x['status']=='検証完了' for x in existing):raise RuntimeError('完了記録は既に存在します')
    with registry.open('a',encoding='utf-8',newline='\n') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n')
    shutil.copyfile(here/'record_results.py',study/'資料/検証補助/record_results.py')
    print(json.dumps({'試行':'R170_001','知見追記':4,'結果参照':len(refs)},ensure_ascii=False))


if __name__=='__main__':main()
