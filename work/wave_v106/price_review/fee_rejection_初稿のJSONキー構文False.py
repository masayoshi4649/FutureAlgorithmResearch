"""取り下げた費用だけの損失後停止案と、根拠経路の事実訂正を保存する。"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def run() -> None:
    """
    機能: 既小診断から確定した二損失の粗損益を検算し、未実施の取り下げ理由を記録する。
    引数: なし。保存小診断と既往 catalog の source だけを参照する。
    返り値: None。新入力、大型台帳、金融、原板、APIを読み実行しない。
    """
    path = ROOT/'work/wave_v106/e01_trade_gate/diagnosis/全24の5寄与と赤字上位場及びW60成行P1L8の具体原因.json'
    saved = path.read_bytes(); source_sha = hashlib.sha256(saved).hexdigest(); diagnosis = json.loads(saved)
    cid = 'E01_TRADE_W60_CONFIRM_D0_P1L8'; session = '2026-09-29_Night'
    pointer = '/results/'+cid+'/NK225/最悪3場/'+session
    value = diagnosis['results'][cid]['NK225']['最悪3場'][session]
    observed = sorted(value['最大損失2親'],key=lambda p:p['新規']['normal_row'])
    assert len(observed) == value['変更']['親数'] == 2
    parents = []
    for p in observed:
        gross = sum(Decimal(str(int(p['実枚数'])))*Decimal(10)*Decimal(str(e['価格']-p['実新規価格']))
                    *(1 if p['方向']=='買い' else -1) for e in p['返済注文'])
        assert len(p['返済注文']) == 1 and p['返済注文'][0]['枚数'] == p['実枚数']
        assert gross == Decimal(str(p['収支']))+Decimal(str(p['実往復料金']))
        parents.append(dict(親=p['親'],公開=p['公開'],新規=p['新規'],新規価格=p['実新規価格'],方向=p['方向'],
            枚数=p['実枚数'],返済=p['返済注文'],純損益=p['収支'],注文別実料=p['実往復料金'],
            粗損益=float(gross),粗利益0条件に該当=gross==0,実親の最大事後清算利益=p['事後親清算経路']['事後の最大清算利益']))
    assert [p['純損益'] for p in parents] == [-7220.,-1220.]
    assert [p['粗損益'] for p in parents] == [-7000.,-1000.]
    assert sum(p['純損益'] for p in parents) == value['変更']['収支'] == -8440.
    # ----------------------------------------
    # 誤認の混入元は、既小診断の全24条件で保存された当該最悪場だけを調べる。
    # 全GU台帳を追加読取しないため、旧資料全体を否定したと扱わない。
    matched = []
    for candidate, case in diagnosis['results'].items():
        scene = case['NK225']['最悪3場'].get(session)
        if scene and any(p['収支']==-220. for p in scene['最大損失2親']): matched.append(candidate)
    veto = diagnosis['重点条件の全赤字場と黒字反証']['NK225']['赤字全場'][session]['実親の時系列']
    catalog = ROOT/'work/wave_v89/catalog.py'
    proof = dict(全合格=True,状態='仮説の診断前提が誤りだったため取り下げ。未実装・未金融。',
        提案だった条件='paper GU が終了し、実親も全返済済みで、実純損益＋注文別実料＝粗損益0となった場合、その場の次新規を停止する。',
        誤認だった前提='NK W60_CONFIRM D0 P1L8 の9/29ナイトが費用だけの−220円後に−8220円となった。',
        確認済み実経路=parents,合計純損益=-8440.,
        発火可否='両親とも粗損益が負で0ではない。この自然基準の停止はどちらにも発火しない。',
        最大損失予防の根拠ではない=True,
        混入元の小資料探索=dict(対象='旧24の当該場が保存された最悪3場の最大損失2親。',
            費用だけの負け親を含む条件=matched,出典特定='この保存範囲では−220円親なし。混入元は特定できない。',
            旧W60VETOの実親=[dict(親=p['親'],新規=p['新規'],収支=p['収支'],実料=p['実往復料金']) for p in veto]),
        静的留保=['粗損益0は最終損益の性質であり、保有中に一度も手数料を覆うほど順行しなかったことを意味しない。MFEとは別。',
            '将来の完結親配列の損益を途中で参照してはいけない。実約定接頭とUID残0、過去に公開されたpaper終了から判断する必要がある。',
            '同行ですでに約定した別UIDを巻き戻せない。新規取消と残玉の次正常気配返済が必要になる。',
            'TOPIX9/21ナイトの最初−12918円は費用418円を戻しても粗−12500円で、費用だけの条件に該当しない。',
            '停止後の勝ち喪失・後参加・料金まで全後続運転しなければ改善額を計算できない。この取り下げ案では計算しない。'],
        既往との相違='00085は実採否と独立した完了仮想親の料金後net<0連敗又は金額割合で新規停止し、仮想回復で再開する。'
            '今回案は完成した実親のgross==0だけを自然基準に永久場停止するため同じ機械条件ではないが、取り下げにより正式重複照合はしていない。',
        source=[dict(path=path.relative_to(ROOT).as_posix(),pointer=pointer,sha256=source_sha),
            dict(path=catalog.relative_to(ROOT).as_posix(),pointer='specification()の連敗/公開/履歴/親採否',sha256=hashlib.sha256(catalog.read_bytes()).hexdigest())],
        財務合計の訂正なし=True,57_1と67_5の割合の訂正なし=True,
        原板読取=0,原NPZ読取=0,大型input読取=0,大型台帳読取=0,実装変更=0,新金融再生=0,API=0,
        公開編集=0,共通知見編集=0,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out = HERE/'fee_rejection_費用だけの終了後停止案の前提訂正と未実施.json';assert not out.exists()
    payload = (json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8');out.write_bytes(payload)
    note = HERE/'fee_rejection_取り下げた停止案の事実訂正.md';assert not note.exists()
    note.write_text('''# 費用だけの損失後に場を止める案は取り下げ

根拠にした日経の2026年9月29日ナイトは、**−220円後に−8,220円ではありません**。旧W60_CONFIRM・成行・P1L8は、19:12:57の買い65,850を19:15:13に65,780で返済して−7,220円、その後23:25:13の買い66,180を66,170で返済して−1,220円、合計−8,440円でした。時刻は保存された価格代理時計です。

各親の実料は220円なので、粗損益は−7,000円と−1,000円。どちらも粗損益0ではなく、「費用だけの負けで次新規を停止する」条件は発火しません。この場を避けられる根拠にならないため、実装・新金融へ進めません。

旧24の小診断に保存された当該場の最大損失親には−220円親を見つけられず、誤認の混入元は未特定です。全旧台帳を追加読取した調査ではありません。旧00085の仮想連敗停止とは条件が違いますが、今回は正式重複照合前に取り下げました。

財務合計と上位3場除外後の57.1%・67.5%は訂正不要です。[根拠と系譜](fee_rejection_費用だけの終了後停止案の前提訂正と未実施.json)に確認範囲を残しました。追加金融・原板・原NPZ・API・公開編集は0です。
''',encoding='utf-8',newline='\n')
    print(hashlib.sha256(payload).hexdigest(),flush=True)


if __name__ == '__main__': run()
