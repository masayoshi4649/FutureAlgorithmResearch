"""確定した板判断の知見を分類別台帳と索引へ反映する。"""
from __future__ import annotations

import shutil
from pathlib import Path

from control165 import ROOT, HERE, read, record, save

STUDY = "00165_米国開始後の板追随と損失安定化"
COMMON = ROOT/"アルゴリズム調査/共通/知見台帳"
SOURCE = f"**出典：** [{STUDY}](../../{STUDY}/README.md)。[具体売買と限界](../../{STUDY}/損失を減らせた場面と残る課題.md)。"


def append(path: Path, text: str) -> None:
    """同研究の重複追記を拒否し、旧本文を残して知見を追加する。

    引数: path(Path)、text(str)。返り値: None。
    """
    old=path.read_text(encoding="utf-8-sig")
    assert STUDY not in old, str(path)
    path.write_text(old.rstrip()+"\n\n"+text.strip()+"\n",encoding="utf-8",newline="")


def main() -> None:
    """独立会計を確認し、知見・案内・公開時点の不変コピーを作る。

    引数: なし。返り値: None。金融再生とアプリ更新は行わない。
    """
    assert read(HERE/"audit/audit165.json")["passed"]
    sections={
      "入口.md":f'''<a id="{STUDY}_板と逆向きの入口を待つ"></a>

## 反対価格帯を見た入口待機には小幅改善があったが、損失の深さは残った

{SOURCE}

当時条件：NK225の米国開始15分後以降、元U164_00初回と逆方向へ両気配が20円以上移り、方向側更新幅比0.625以上、その後2価格更新でも維持し、先行する同価格数量回復が既知なら待機。価格時計30秒内に元方向の新価格帯維持が成立した時だけ初回希望量・Source残量以内で新規。未回復は取消。U165_03、micro100枚/片方向、次正常ラージAsk/Bid、手数料0。

全27夜の元初回107件中17件待機、13件再開、4件取消。取消4件の元損失108,000円と再開13件の差−27,000円で累計差+81,000円。収支+1,100,000→+1,181,000円、赤字9→8夜。赤字平均30,889→31,375円・中央値29,000→34,000円・最悪時価−85,000→−88,000円で、損失の深さは改善していない。

取消4件は既知資料内では全て旧損失だったが、将来の成功率100%ではない。前20夜では第一候補04、基準、03の順に固定。後7夜を見た選び直しはしていない。米国価格・ニュースは使用せず、外因そのものの推定成功とも称さない。
''',
      "継続.md":f'''<a id="{STUDY}_追撃確認と通常の押戻り"></a>

## 短い価格帯確認は追撃の選別を少し変えたが、反転ごとの半減は通常の押戻りも削った

{SOURCE}

当時条件：米国後U165_04は元Sourceの同親追加だけを、E08の同方向価格帯維持が既知の場合に採用。初回・別担当初回は保持。27夜で追加40件の17件を抑止し、消失利益80,000円・回避損失74,000円、差−6,000円。赤字9夜は同じ、最大場内下落162,000→145,000円。原板で10/08の追加損16,000円回避と、10/02の追加益20,000円消失を確認。

U165_06は初回実約定後の新しい反対価格帯維持で親残量を一度半減。106回の半減で+383,000円・赤字10夜・平均赤字22,400円・最悪時価−53,000円。一律半量01は+550,000円・赤字9夜・平均赤字15,444円・最悪時価−42,500円だった。短い反対状態を観測しただけでは、数量判断の優位を示せない。費用0・既知27夜の比較であり、他の幅・持続条件は未測定。
''',
      "出口.md":f'''<a id="{STUDY}_利益残玉と反対価格帯"></a>

## 利益残玉を短い反対価格帯で返しても、利益消失問題はほぼ残った

{SOURCE}

当時条件：U165_05はSourceの黒字部分返済が実際に約定した後、当時存在する残玉だけを資格付与。資格後に正益を観測し、その後新たな反対価格帯維持が成立した時に次正常板で返済。資格前MFEや古い反対状態は使わない。

元と同じ147所有玉で、正益後に最終赤字となった玉は49→48、当該赤字玉の純損益−878,000→−875,000円。一度も正益にならない赤字16玉・−300,000円は不変。全27夜の累計は+1,100,000→+1,052,000円、赤字夜9は同じ、平均赤字30,889→33,444円。観測34独自返済という作動回数と、利益消失の解消率を混同しない。今回の条件は改善未確認。
''',
      "売買の工夫.md":f'''<a id="{STUDY}_同じ価格帯への重ね新規と気配差"></a>

## 小さな押戻りIDを別の機会と数えると、同じ波への重ね建てで気配差を払う

{SOURCE}

当時条件：独立U165_10は両気配の価格帯維持後、新しい逆向き価格更新と2更新後の回復で20microを新規。別の押戻りIDなら同じ基礎価格帯へも入れ、全方向最大5親。−50円/+100円/新たな反対価格帯/場末で返済。米国後、手数料0。

前20夜13,682玉のうち、同じ基礎価格帯で保有中の重ね新規8,364玉。全玉ゼロ後の同帯への再参加は3玉だった。反対価格帯で11,979玉を返済。保有中央値40価格時計秒で、924玉は新規と返済の価格時計が同じ。2更新は実時間2秒ではない。

収支−41,450,000円は、同じ約定時刻・数量を固定した中値変化成分−3,645,000円と往復気配差−37,805,000円に一致。中値で執行できる別戦略の成績ではない。数量回復条件を加えた11も3,348玉・−9,892,000円（中値−638,000・気配差−9,254,000）。気配差が大半だが、中値方向の予測優位も未確認。9/22夜の翌00:06:52〜00:07:01に同帯へ20micro×5を重ね、00:07:25に−52,000円の具体例を原行で確認した。

同帯の重複上限、気配差に対して十分な進行、長短状態の一致は次の仮説。本結果を修正済みの成績と称さない。基礎価格帯と押戻りIDは機械的状態で、統計的に独立した波ではない。
'''}
    changed=[]
    for name,text in sections.items():
        path=COMMON/name; append(path,text);changed.append(path)
    # ----------------------------------------
    # 案内は既存の記録を残して先頭に追加する。
    for path,prefix in ((ROOT/"README.md","アルゴリズム調査/"),(ROOT/"アルゴリズム調査/README.md",""),(COMMON/"README.md","../../")):
        old=path.read_text(encoding="utf-8-sig")
        assert STUDY not in old
        text=f"最新：[{STUDY}]({prefix}{STUDY}/README.md)。米国データを使わず国内板の14条件を27夜で比較。入口待機03は赤字9→8夜だが、通常損失の深さは未改善。前半固定第一候補04はほぼ横ばい。[手法別損益xlsx]({prefix}{STUDY}/米国開始後の板判断と全セッション損益.xlsx)。\n\n"
        path.write_text(text+old,encoding="utf-8",newline="");changed.append(path)
    path=ROOT/"アルゴリズム調査/index.html"
    old=path.read_text(encoding="utf-8-sig"); assert STUDY not in old
    lead="作業00164は日中J02の改修と、米国開始前後の独立手法を比較した資料です。"
    assert lead in old
    old=old.replace(lead,"作業00165は米国データを使わず、国内板から米国開始後の追随と失速を読む14条件を比較した資料です。",1)
    marker='<article class="task latest"><div class="number">作業00164'
    assert marker in old
    card=f'''<!-- 00165は既知27夜の研究成果への案内です。損益本文はExcelへ分離しています。 -->
<article class="task latest"><div class="number">作業00165・米国開始後の板判断</div><h2>入口の待機は小幅改善。損失の深さは残る</h2><p>国内板14条件を27夜で比較。前半固定第一候補04はほぼ横ばい。候補03は赤字9→8夜、累計110万→118.1万円ですが、平均赤字は減っていません。</p><a class="button" href="{STUDY}/米国開始後の板判断と全セッション損益.xlsx">全27夜の損益（Excel）</a> <a href="{STUDY}/README.md">短い結論</a> <a href="{STUDY}/損失を減らせた場面と残る課題.md">具体的な売買と原因</a></article>

'''
    old=old.replace(marker,card+marker.replace('task latest','task'),1)
    path.write_text(old,encoding="utf-8",newline="");changed.append(path)
    # ----------------------------------------
    # 将来の索引更新で過去証跡の内容指紋が変わらないよう、公開時点を別保存する。
    snapshot=HERE/"公開時点の共通文書"
    records=[]
    for path in changed:
        dest=snapshot/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True)
        assert not dest.exists();shutil.copyfile(path,dest);records.append(record(dest))
    save(HERE/"知見更新165.json",dict(passed=True,financial_replays=0,study=STUDY,
        changed=[p.relative_to(ROOT).as_posix() for p in changed],snapshots=records))
    print("4分類の知見と索引を更新し、公開時点を保存しました。")


if __name__ == "__main__":
    main()
