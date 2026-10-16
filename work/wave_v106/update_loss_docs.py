"""比例損失停止の実測と二例の気配費用を、知見と公開導線へ記録する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
DIRECTORY = PUBLIC.name
TITLE = '枚数に合わせた損失停止の修正と全セッション損益'
DETAIL = '損失停止を狭めて失った回復勝ちの具体例.md'
NEW_ID = 'E01_LOSS_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'
OLD_ID = 'E01_ANCHOR_W60_CONFIRM_D0_P1_L2_A1'


def read(path: Path) -> dict:
    """
    機能: 保存済みの小診断又は公開小会計を読む。
    引数: path(Path)は金融再生を必要としない完成JSON。
    返り値: dictはUTF-8で保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_example() -> None:
    """
    機能: 事前の条件IDと保存診断を結び、二実例と停止線の算術を短く記録する。
    引数: なし。完成小会計、診断計画、小診断、独立小算術だけ使用する。
    返り値: None。原板・台帳・金融・APIへ接続しない。
    """
    plan_path = HERE/'loss_stop_diagnosis/二例の初回同数量回復勝ちを調べる固定計画.json'
    diagnosis_path = HERE/'loss_stop_diagnosis/同一初回の比例損切りと旧回復実利確の二例.json'
    plan, data = read(plan_path), read(diagnosis_path)
    assert plan['全合格'] and data['全合格']
    assert plan['条件'] == NEW_ID and plan['比較元'] == OLD_ID
    assert hashlib.sha256(diagnosis_path.read_bytes()).hexdigest() == '6cc4f5569713938282e01d8ffb0d3ca39743d4c177b5ec259330d704af0e9139'
    selected = {(p['session'], p['symbol'], p['parent']): p for p in plan['selected']}
    for case in data['results']:
        key = case['session'], case['symbol'], case['parent']
        reference = selected[key]
        assert case['旧利益'] == reference['old_net'] and case['新損失'] == reference['new_net']
        assert case['初回実新規']['normal_row'] == reference['first']['row']
        assert case['公開']['normal_row'] == reference['first']['source_row']
    content = f'''# 損失停止を狭めて失った回復勝ち

**結論：損切りだけを狭める修正は改善になりませんでした。** 日経の同方向確認P1は、最大赤字が1,444円から666円へ減った一方、赤字2場→17場、収支+3,386円→−5,214円です。TOPIXも全4条件が赤字でした。

比較は `{OLD_ID}` → `{NEW_ID}`。同じ初回の方向・数量・入口・利益目標で、場の損失停止線だけを初回枚数に比例させました。次の2例は「旧版で黒字・新版で赤字になった、初回同数量の親」の商品別最大悪化例であり、全取引の代表確率ではありません。

| 商品・場 | 同じ新規 | 狭い損失線による返済 | 旧版の実返済 | 差額 |
| --- | --- | --- | --- | ---: |
| TOPIXミニ・10/12デイ | 14:36:17 売り2枚 @4,145.5 | 14:36:25 買い @4,146.5、−2,166円 | 14:41:56 買い @4,145.0、+834円 | −3,000円 |
| 日経マイクロ・9/21ナイト | 19:09:34 買い3枚 @65,720 | 19:09:50 売り @65,700、−666円 | 19:33:25 売り @65,740、+534円 | −1,200円 |

新規直後の清算額はTOPIX−1,166円、日経−366円。気配差と往復料だけで、損失線2,000円・600円の**58.3%・61.0%**を消費しました。

| 初期の返済側気配から | TOPIXミニ2枚 | 日経マイクロ3枚 |
| --- | ---: | ---: |
| 往復手数料 | 166円 | 66円 |
| 損失線へ届く逆行幅 | 0.417pt、観測1呼値 | 7.8円、観測1呼値 |
| 利益線へ届く順行幅 | 1.083pt、観測3呼値 | 22.2円、観測3呼値 |

名目の利益目標P1・損失線L2が1対2でも、実際に許容する価格変化が1対2になるとは限りません。入口の気配差と手数料を含めた判定では、この2例は小さな1呼値の揺れで停止し、利益には3呼値必要でした。

TOPIX旧版は利確判断時+1,834円から、次正常気配の返済で+834円へ1,000円悪化しています。利確判断自体は成立しており、利益目標未達で待ち続けた例ではありません。

**次の検証で分けること：** 気配差・費用を踏まえた許容価格幅と、反対側の継続的な進行による方向判断の撤回。単に停止線を狭くする修正は採用しません。入口の費用負担を拒否する方法や、反対側の進行を確認して降りる方法を組み合わせた救済収支は、この2例から推定しません。

時刻は価格時計の代理で、同秒でも原行が違います。返済は判断後の次正常気配。観測1呼値はラージTOPIX0.5pt・日経10円で、実ミニ/マイクロ各2呼値。実商品の板・待ち順位、厚さ・補充、心理、真の方向反転はこの診断では測定していません。

出典：[00103_往復帯の回避と損失後再参加の統合検証](README.md)、[全33場・4条件](枚数に合わせた損失停止の修正と全セッション損益.html)、[比較元](枚数に合わせた利確修正と全セッション損益.html)、[条件ID付き診断計画](../../work/wave_v106/loss_stop_diagnosis/二例の初回同数量回復勝ちを調べる固定計画.json)、[原seqと両気配を含む小診断](../../work/wave_v106/loss_stop_diagnosis/同一初回の比例損切りと旧回復実利確の二例.json)、[独立算術](../../work/wave_v106/price_review/loss_anchor_二実例気配損益と必要呼値の独立算術.json)。条件IDは計画へ束縛し、診断JSONだけから推測していません。旧版の後の利益は比較結果であり、新版の収支へ足していません。
'''
    (PUBLIC/DETAIL).write_text(content, encoding='utf-8', newline='\n')


# ----------------------------------------
def write_knowledge() -> None:
    """
    機能: 出口の法則を部品単位で記録し、枚数と利確の旧知見へ後続結果を結ぶ。
    引数: なし。実測範囲・分母・条件・未測定を明記する。
    返り値: None。共通知見Markdown以外へ知見本文を二重管理しない。
    """
    path = ROOT/'アルゴリズム調査/共通/知見台帳/出口.md'
    text = path.read_text(encoding='utf-8')
    anchor = '名目の損益幅は気配差と費用後の許容値幅とは違う'
    law = '''
<a id="名目の損益幅は気配差と費用後の許容値幅とは違う"></a>

## 名目の損益幅は気配差と費用後の許容値幅とは違う

**出典：** [00103_往復帯の回避と損失後再参加の統合検証](../../00103_往復帯の回避と損失後再参加の統合検証/README.md)。2026年10月14日、正式4条件264口座・各商品33場。対照は利確だけ初回受理qへ比例した版。今回は損失停止線も初回q/通常全量へ比例し、新規数量選択B・入口・利益線・実料・部分返済・次正常執行を維持。

**当時の判断：** 最初の受理公開qで場の利益・損失線を一度固定。未約定取消でも保持、以後の数量へ選び直さない。費用後の場清算額が線へ達した後、次正常気配で残玉を返済して場停止。線は実約定損失の保証ではない。

**測定結果：** 両商品黒字0/4、最新三基準合格0/4。日経CONFIRM_P1は最大赤字1,444円→666円、平均黒字270.5円→149.4円、黒字/赤字/無取引22/2/9→7/17/9、金額利益69.9%→14.3%、収支+3,386円→−5,214円。赤字の深さは減ったが頻度が増えた。TOPIX同条件も12/6/15→6/12/15、収支−10,642円→−8,060円で黒字化しなかった。

**仕組みを確かめた二例：** 同条件の初回同数量・同sourceで旧黒字→新赤字となった保存済みの親から、商品別最大差の各1例を読み取り診断の前に選んだ。金融再生の前に選んだ事例ではない。TOPIX10/12デイ14:36:17売り2枚は14:36:25に−2,166円で停止、旧版14:41:56は+834円。日経9/21ナイト19:09:34買い3枚は19:09:50に−666円、旧版19:33:25は+534円。気配差と往復料が損失線の58.3%・61.0%を新規直後に消費。初期返済側気配からは損切りまで観測1呼値、利益まで3呼値だった。TOPIX旧版は利確判断+1,834円から次正常返済+834円へ悪化したので、判断時と実損益を区別する。

**算術の適用条件：** 初回実親・過去PL0・判断前部分返済なし・初回受理qと実q一致。初期返済側気配から損失線へ必要逆行幅は(L−q×気配差×円倍率−往復料)/(q×円倍率)、利益線へ必要順行幅は(P＋q×気配差×円倍率＋往復料)/(q×円倍率)。観測呼値へ切上げ。部分返済や過去損益がある場へこの単純式をそのまま使わない。

**使える場面と限界：** 狭い費用後停止線を設計する前に、当時気配差と料が価格変化の余裕をどれだけ消費するかを点検する。二例の算術は全取引の勝率・先着確率ではない。小さな逆行を全て方向転換と扱うと回復勝ちを失う。正常価格変化の後に回復したという比較であり、厚み・補充・心理・真の受信時計は未測定。入口の費用拒否や反対進行を使った新たな救済PLは未測定。

根拠：[全場4条件](../../00103_往復帯の回避と損失後再参加の統合検証/枚数に合わせた損失停止の修正と全セッション損益.html)、[具体時刻と算術](../../00103_往復帯の回避と損失後再参加の統合検証/損失停止を狭めて失った回復勝ちの具体例.md)、[8部品と正式計画](../../../work/wave_v106/e01_size_loss_anchor/試行計画.json)、[全264会計・境界・寄与の独立監査](../../../work/wave_v106/price_review/loss_anchor_全264小会計と比例境界及び最新三基準の独立確認.json)、[二例選定と条件ID](../../../work/wave_v106/loss_stop_diagnosis/二例の初回同数量回復勝ちを調べる固定計画.json)、[小診断独立算術](../../../work/wave_v106/price_review/loss_anchor_二実例気配損益と必要呼値の独立算術.json)。金融段階は保存GU132再利用・新GU0、既33input各一読、旧goal264台帳各一読。別目的の二例診断は4台帳・2input各一読で、新金融/原板/NPZ/API0。独立小算術はpacketと台帳を再読していない。
'''
    if '<a id="'+anchor+'"></a>' not in text:
        path.write_text(text.rstrip()+'\n\n'+law.lstrip(), encoding='utf-8', newline='\n')
    path = ROOT/'アルゴリズム調査/共通/知見台帳/売買の工夫.md'
    text = path.read_text(encoding='utf-8')
    addition = '**後続の損失線対照：** 受理qに損失線も比例する4条件は両商品とも合計赤字。日経P1は赤字2場→17場に増え、単に損切りを狭める方法では補填条件を改善できなかった。[気配差・費用と停止余裕の法則](出口.md#名目の損益幅は気配差と費用後の許容値幅とは違う)へ、全場結果と二実例を分けて記録した。'
    if addition not in text:
        path.write_text(text.rstrip()+'\n\n'+addition+'\n', encoding='utf-8', newline='\n')


# ----------------------------------------
def write_navigation() -> None:
    """
    機能: 最新369IDの判定と損失原因へ導線を更新し、過去時点の報告を保存する。
    引数: なし。READMEと一覧の最新説明だけを更新する。
    返り値: None。357時点のHTMLや完成金融sourceは変更しない。
    """
    path = PUBLIC/'README.md'
    text = path.read_text(encoding='utf-8')
    text = text.replace('両商品の三基準同時達成は追加後の365条件IDでも0件です。', '両商品の三基準同時達成は、数量・利確・損失線の12条件追加後の369条件IDでも0件です。', 1)
    text = text.replace('数量4条件と利確修正4条件を含む[365条件IDの判定](../../work/wave_v106/new_goal/初回受理目標四条件追加後の65基準と全候補判定.json)', '追加12条件を含む[369条件IDの判定](../../work/wave_v106/new_goal/初回受理損失四条件追加後の65基準と全候補判定.json)', 1)
    marker = '**損失線を狭めた次の対照：**'
    if marker not in text:
        paragraphs = text.split('\n\n')
        paragraphs.insert(4, marker+' ['+TITLE+']('+TITLE+'.html)に全4条件・全33場を掲載。日経の同方向確認P1は最大赤字1,444円→666円と浅くなりましたが、赤字2場→17場・収支+3,386円→−5,214円で悪化しました。['+DETAIL.removesuffix('.md')+']('+DETAIL+')で、小さな気配変化で停止した時刻と、入口費用が停止余地を消費する算術を確認できます。')
        text = '\n\n'.join(paragraphs)
    path.write_text(text, encoding='utf-8', newline='\n')
    for path in (ROOT/'README.md', ROOT/'アルゴリズム調査/README.md'):
        lines = path.read_text(encoding='utf-8').splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith('最新の結論：'):
                prefix = 'アルゴリズム調査/' if path == ROOT/'README.md' else ''
                directory = prefix+DIRECTORY+'/'
                lines[i] = '最新の結論：[利確修正と全33場]('+directory+'枚数に合わせた利確修正と全セッション損益.html)。日経は金額利益69.9%・赤字2/33場ですが、最大赤字1,444円を平均黒字270.5円で補えません。[損失線だけ狭めた4比較]('+directory+TITLE+'.html)は赤字が増え、両商品とも全4条件赤字。[具体時刻と気配差・手数料の原因]('+directory+DETAIL+')を記録しました。追加12条件を含む369主評価IDで両商品三基準合格0件。[現在一回照合]('+directory+'現在ナイト一回照合の入力検査.html)は入力時計の逆行で金融未測定です。'
                found = True
                break
        assert found, path
        path.write_text('\n'.join(lines)+'\n', encoding='utf-8', newline='\n')
    path = ROOT/'アルゴリズム調査/index.html'
    text = path.read_text(encoding='utf-8')
    old = '数量と利確の8条件を追加し365主評価IDを判定。日経は金額利益69.9%・赤字2/33場へ改善しましたが、平均黒字約271円より最大赤字1,444円が大きく補填不足。TOPIXは新4条件とも赤字で、両銘柄共通の三基準達成は未発見です。'
    new = '数量・利確・損失線の12条件を追加し369主評価IDを判定。日経の利確修正は金額利益69.9%・赤字2/33場ですが平均黒字約271円で最大赤字1,444円を補えません。損失線だけ狭めると赤字17場へ悪化。気配差・費用が停止余地を先に消費した具体時刻を記録しました。両銘柄共通の三基準達成は未発見です。'
    assert old in text
    text = text.replace(old, new, 1)
    target = '<a href="'+DIRECTORY+'/予定リスクで枚数を変える4比較と全セッション損益.html">前段の数量4比較</a>'
    addition = ' <a href="'+DIRECTORY+'/'+TITLE+'.html">損失線4比較</a> <a href="'+DIRECTORY+'/'+DETAIL+'">損失の具体時刻</a>'
    assert target in text
    if addition not in text:
        text = text.replace(target, target+addition, 1)
    path.write_text(text, encoding='utf-8', newline='\n')


def main() -> None:
    """
    機能: 最新小会計を確認して知見・原因・導線を一度更新する。
    引数: なし。
    返り値: None。金融再生と入力再読を行わない。
    """
    data = read(PUBLIC/'枚数に合わせた損失停止4比較の公開会計.json')
    assert data['全合格'] and data['both_goal_pass'] == data['both_net_positive'] == 0
    n = data['cases'][NEW_ID]['summary']['NK225']
    o = data['cases'][NEW_ID]['comparison']['summary']['NK225']
    assert (n['negative'], n['net'], n['worst_session_loss']) == (17, -5214, 666)
    assert (o['negative'], o['net'], o['worst_session_loss']) == (2, 3386, 1444)
    write_example()
    write_knowledge()
    write_navigation()
    print('369ID・損失停止の失敗・二例の気配費用を知見と最新導線へ記録。新金融0。')


if __name__ == '__main__':
    main()
