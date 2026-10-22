"""最新評価条件、全場結果、具体損失と未測定改善を案内・法則別知見へ残す。"""

from pathlib import Path
from datetime import datetime,timezone,timedelta
import json
import hashlib
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
NAME="00125_毎日参加と両銘柄の利益率改善";PUBLIC=ROOT/"アルゴリズム調査"/NAME
TITLE="毎日参加する三系統と全セッション損益.html"
TRIAL="125_通常数量で毎場参加する三家族と純方向の持替え"


def read(path: Path) -> dict:
    """
    機能: 保存済み資料を読む。
    引数: path(Path)はJSON。
    返り値: dictは資料。
    """
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    """
    機能: 指定資料の指紋を求める。
    引数: path(Path)は対象。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append(path: Path,marker: str,text: str) -> None:
    """
    機能: 出典を持つ法則を重複なしで追記する。
    引数: path(Path)は共通Markdown、marker/text(str)は識別と内容。
    返り値: None。
    """
    value=path.read_text(encoding="utf-8");assert marker not in value
    path.write_text(value+"\n\n"+text,encoding="utf-8")


def main() -> None:
    """
    機能: 完成会計を変えず、資料・試行終了と整合性確認を保存する。
    引数: なし。
    返り値: None。金融再生・原本・API・注文を行わない。
    """
    result=HERE/"十二条件と二商品全四十一場の会計.json"
    assert sha(result)=="2ef627501c50359baadc6bbfa343d372c882f2b0f39fdbb1de8019fb02fdf19b"
    fixed=read(HERE/"固定計画_確定条件.json")
    for rel,h in fixed["sources"].items():assert sha(ROOT/rel)==h
    html=PUBLIC/TITLE;assert sha(html)=="14af259d4870381ff2b3c0af649735d6c5f428d4a5dcdb955fdcd8494073d2d2"
    visual=read(HERE/"visual/実描画確認.json");assert visual["passed"] and visual["root_viewed"] and visual["checked_rows"]==984
    audit=HERE/"audit_result125/十二条件と全九百八十四会計の費用なし独立保存監査.json"
    assert read(audit)["passed"] and sha(audit)=="2b97b3805b4266c19be470370c7f283af4e9e40a5cf7f156dcb75ab2265907b5"
    source=f"**出典：** [{NAME}](../../{NAME}/README.md)。"
    knowledge=ROOT/"アルゴリズム調査/共通/知見台帳"
    append(knowledge/"入口.md","00125_期限参加だけが損失原因ではない",f'''<a id="00125_期限参加だけが損失原因ではない"></a>

## 通常数量を毎場建てても、進行確認後の入口は黒字にならなかった

{source}

**当時条件・終点：** 正常BBOを持つ価格の確定15分ER・尺度wを使う三家族12条件。相手は一分厳密先行の確定足。30分未参加なら通常半容量で期限参加。TOPIX5mini／日経10micro、全玉場内返済、手数料0・売買気配差あり。

**実測・分母：** 全12×両商品が41/41場で実参加し、24商品条件すべて合計赤字。C00はTOPIX−1,497,500円の内訳が根拠参加−1,210,000／期限参加−287,500円、日経−730,000円が−478,000／−252,000円。B00は期限参加が3／5群だけでも合計−3,192,500／−716,000円。

**使い方・限界：** 最低参加を強制したことだけで全損を説明しない。進行が既に確認できることと新規後の継続利益は異なる。既知41場を12条件反復しており独立984市場標本ではない。根拠参加だけを削除する改善の成績は未測定。[全場損益](../../{NAME}/{TITLE})。
''')
    append(knowledge/"出口.md","00125_起動幅未満の利益返しと未順行",f'''<a id="00125_起動幅未満の利益返しと未順行"></a>

## 起動幅未満の利益返しは多いが、全ての負けを出口だけで救えない

{source}

**当時条件：** C00は初期stop1w、追尾開始1w、追尾幅0.75w。w=max(観測呼値8個,過去15個の絶対一分差75%点×3)、準備時に固定。保有時間固定なし。

**実測・分母：** 負け群TOPIX187中120、日経203中129が途中で一度費用なし清算時価の黒字を記録。そのうち119／128群は追尾開始1wに届かなかった。残り67／74群は一度も黒字でない。C02のstop0.75w・開始0.75w・追尾0.5wは、C00より両商品で悪化（合計TOPIX−2,010,000／日経−995,000円）。複数部品変更のため単一の幅の効果とはしない。

**具体例：** TOPIX9/28ナイト、23:52売4074・5枚は途中＋25,000円だがw9.75に未到達、翌01:20買4084で−50,000円。10/14ナイト21:07買4123・5枚はstop4119を置いても21:30の次原行bid4100で−115,000円。後者は支持撤回判断原行のLast4100とbid4127.5の差、直後bid4100への変化を伴う。停止線どおりの架空約定を使わない。

**限界・次の検証：** 条件付きの利益確保は未測定。一律狭幅化の成功とは言わず、初期損切りを保った単部品対照と失った勝ちを調べる。[保存全負け分類](../../../work/stability125_20261019/audit_diagnosis125/全十二条件の入口出口と順行返し及び実撤回距離.json)。
''')
    append(knowledge/"継続.md","00125_順行追加は初回予算維持でも悪化",f'''<a id="00125_順行追加は初回予算維持でも悪化"></a>

## 初回予算内の予定損切りへ近づけても、順行追加は全対照で悪化した

{source}

**当時条件：** 00→01は一単位順行で残半分を一度追加する点だけの政策対照。追加後に平均建値・全料と初回予算からstopを有利側へ移し、予定円損失を初回以内へ保つ。上下とも同じ式、反対は先に全返済。

**実測：** A/B/C×二商品の6対照すべてで合計収支が悪化。AはTOPIX−1,097,500→−1,255,000円、日経−530,000→−591,000円。Cは−1,497,500→−1,525,000円、−730,000→−891,000円。

**使い方・限界：** 初回予定リスクを増やさない設計でも、追加後の平均建値・停止線・実退出と後続参加が変わる。全差額を追加玉だけの直接損失とせず、次気配の飛び越しも予算保証と混同しない。全41既知場の開発比較。[全群分類と00/01対照](../../../work/stability125_20261019/audit_diagnosis125/全十二条件の入口出口と順行返し及び実撤回距離.json)。
''')
    append(knowledge/"売買の工夫.md","00125_費用零でも反対気配負担は残る",f'''<a id="00125_費用零でも反対気配負担は残る"></a>

## 手数料0でも、売買反転が気配差の負担まで利益へ変えるわけではない

{source} 先行の[00116_全赤字手法の売買反転を同条件で検証](../../00116_全赤字手法の売買反転を同条件で検証/README.md)とは入力・値幅・手数料条件が異なる再分析。

**対照：** 元注文と同じ時刻・枚数で反対BBOを使う事後参考会計。反転参考=−元gross−全新規/返済のspread×枚数×倍率、全984保存会計で反対BBO実算と一致。元の退出時刻を借りているため実行可能な反転アルゴリズムの成績ではない。

**実測・分母：** 12条件×両商品が全41場合計赤字のまま。A00は元TOPIX−1,097,500→反転参考−590,000円、日経−530,000→−102,000円。元の中値方向成分−253,750／−214,000円は反転へ有利だが、片方向分の半気配差負担843,750／316,000円が上回った。

**使い方・限界：** 手数料を除いても成行の売買気配差は残る。反転参考が全赤という結果を、全ての逆張り戦略の否定や将来の証明へ広げない。新金融再生0。[参考会計と気配差分解](../../../work/stability125_20261019/audit_reverse125/同時刻同枚数の逆売買参考会計と気配差分解.json)。
''')
    # ----------------------------------------
    # 最初に読む案内を揃え、古い成果を変更せず新しい結果へ導く。
    link=f"[{NAME}：全12条件と両商品41場](アルゴリズム調査/{NAME}/{TITLE})"
    for path,prefix in ((ROOT/"README.md","アルゴリズム調査/"),(ROOT/"アルゴリズム調査/README.md","")):
        value=path.read_text(encoding="utf-8");assert "<!--00125案内-->" not in value
        at=value.index("\n")+1
        note=f"\n<!--00125案内-->\n最新：[00125：各場参加と価格0.5%幅]({prefix}{NAME}/{TITLE})。手数料0で12条件・両商品41場を検証。全場通常数量参加は達成、平均0.5%は全条件未達。具体損失と逆売買参考を記録。\n<!--00125案内終了-->\n"
        path.write_text(value[:at]+note+value[at:],encoding="utf-8")
    index=ROOT/"アルゴリズム調査/index.html";value=index.read_text(encoding="utf-8");assert "<!--00125開始-->" not in value
    card=f'''<!--00125開始--><article class="task latest"><div class="number">作業00125・毎場参加と価格0.5%幅</div><h2>手数料0で三家族12条件を検証</h2><p>両商品41場で通常数量参加。全24商品条件が累計赤字で目標未達。損失の具体時刻と起動前の利益返しを確認。</p><a class="button" href="{NAME}/{TITLE}">全12条件と全41場</a> <a href="{NAME}/README.md">読む順序</a></article><!--00125終了-->\n'''
    assert "<!--00124開始-->" in value;value=value.replace("<!--00124開始-->",card+"<!--00124開始-->",1)
    value=value.replace("最新00124では追加一場と日経オプションを検証。既存E01・19間隔と、前場IVによる12条件の全41場を掲載しています。","最新00125は各場参加・価格0.5%幅を手数料0で検証。全12条件と両商品41場、具体的損失を掲載しています。")
    index.write_text(value,encoding="utf-8")
    kp=knowledge/"README.md";value=kp.read_text(encoding="utf-8");at=value.index("\n")+1
    kp.write_text(value[:at]+f"\n<!--00125案内-->\n最新は[00125：各場参加と価格0.5%幅](../../{NAME}/README.md)。参加と予測力、起動前の利益返し、追加の悪化、手数料0と気配差を法則別に記録。\n<!--00125案内終了-->\n"+value[at:],encoding="utf-8")
    rp=PUBLIC/"README.md";value=rp.read_text(encoding="utf-8").replace("検証後に作成する「毎日参加する三系統と全セッション損益.html」です。現在は事前設計・人工検証の段階です。未測定を達成とは扱いません。",f"[全12条件と両商品41場の損益]({TITLE})です。手数料0・全41場参加は達成しましたが、平均価格幅0.5%は全条件で未達です。")
    value=value.replace("比較設計は、より厳しい各セッションでの通常数量参加を扱い、利益率の分母に依存しない入口・継続・出口を検証します。","比較設計は、確定した各セッションでの通常数量参加を扱い、入口・継続・出口を検証します。")
    value=value.replace("全セッションの損益と具体的損失診断：検証後に追加。",f"[全セッションの損益と具体的損失診断]({TITLE})：方法・商品を選んで各41場を表示。")
    value+="\n## 測定と確認\n\n三家族×四条件×二商品×41場＝984会計。全注文・全tick時価・料金0・数量・全玉返済を独立監査し、Chromeで全24選択・984行を保存会計へ照合しました。金融再実行0、原本追加読取0、現在API0、実注文0。初回の未登録停止は登録JSONの形式誤りであり、市場損失や無取引へ置換していません。正式接続はrun125b/register125b。\n"
    rp.write_text(value,encoding="utf-8")
    # ----------------------------------------
    # この試行だけを終了し、他の試行を同値に保つ。研究の終了と目標達成を分ける。
    data=ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data"
    table=read(data/"trials.json");before=[r for r in table["trials"] if r["id"]!=TRIAL]
    history=data/"history/00125_終了前の試行台帳.json";assert not history.exists();history.write_bytes((data/"trials.json").read_bytes())
    trial=next(r for r in table["trials"] if r["id"]==TRIAL);trial.update(status="検証完了・目標未達",readme=f"アルゴリズム調査/{NAME}/README.md",report=html.relative_to(ROOT).as_posix(),financial_accounts=984,result_summary="手数料0、全12条件が両商品全41場で通常数量参加。全24商品条件が累計赤字、平均価格幅0.5%の合格0。未知確認0。")
    trial["evidence"] += [dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in (result,audit,HERE/"visual/実描画確認.json",HERE/"audit_reverse125/同時刻同枚数の逆売買参考会計と気配差分解.json")]
    assert before==[r for r in table["trials"] if r["id"]!=TRIAL]
    table["updated_at"]=datetime.now(timezone(timedelta(hours=9))).isoformat();(data/"trials.json").write_text(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    manager=data.parent/"manage.py"
    outputs=[]
    for command,args in (("build",[]),("verify",["--deep"])):
        proc=subprocess.run([sys.executable,"-B","-X","utf8",str(manager),command]+args,cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        outputs.append(dict(command=command,returncode=proc.returncode,stdout=proc.stdout,stderr=proc.stderr));print(command,proc.returncode,flush=True)
        assert proc.returncode==0,proc.stderr[-1500:]
    assert sha(html)=="14af259d4870381ff2b3c0af649735d6c5f428d4a5dcdb955fdcd8494073d2d2"
    proof=dict(passed=True,financial_accounts=984,financial_replays=0,original_market_reads=0,goal_met=False,all_session_participation=True,fees=0,html_sha256=sha(html),result_sha256=sha(result),old_trials_unchanged=True,outputs=outputs)
    (HERE/"案内と法則別知見及び試行終了.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
    print("各場参加・手数料0の全41場検証と未達及び具体損失を保存しました。",flush=True)


if __name__=="__main__":main()
