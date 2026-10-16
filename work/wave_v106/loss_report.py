"""保存済みの具体的損失と、対策で失った利益を短い資料にまとめる。売買再生はしない。"""

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def read(path: Path) -> dict:
    """
    機能: 保存された合格済み診断資料を読み込む。
    引数: path(Path)はUTF-8の既存JSON。
    返り値: dictは保存資料。未合格なら例外を発生させる。
    """
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    assert value['全合格'] is True
    return value


def amount(value: float) -> str:
    """
    機能: 日本語資料の円額を整形する。
    引数: value(float)は保存会計の金額。
    返り値: strは三桁区切りの整数円。
    """
    return f'{value:+,.0f}円'


def main() -> None:
    """
    機能: 元の赤字上位3場と対策の反証を公開Markdownへまとめる。
    引数: なし。第一段階の固定診断と完成150条件を参照する。
    返り値: None。既存の取引を再利用し、新規売買・API取得は行わない。
    """
    diagnosis = read(HERE/'diagnosis/赤字上位場の具体原因.json')
    data = read(HERE/'finance/stage150/final_results.json')
    lines = ['# 損失箇所と改善の記録', '',
        '基準はC_N30_B4。以下の赤字上位3場は改善前に固定し、結果を見て選び直していません。TOPIXミニ10枚・日経マイクロ20枚、両側手数料後。', '',
        '## どこで損失が発生したか', '',
        '| 商品・場 | 場全体の収支 | 新規→返済（日本時間） | 建値→返済値 | 取引収支 | 確認した原因 |',
        '| --- | ---: | --- | --- | ---: | --- |']
    for symbol, groups in diagnosis['具体例'].items():
        for group in groups:
            for parent in group['最大損失2親']:
                clock = parent['JST']
                mfe = parent['max_favorable_ticks'] * (.5 if symbol=='TOPIX' else 5.)
                cause = '、'.join(parent['分類'])
                if mfe > 0:
                    cause += f'。途中の清算気配は最大{mfe:g}pt順行したが残せなかった'
                else:
                    cause += '。清算気配では順行なし'
                label = symbol+' '+group['session'].replace('_Day',' デイ').replace('_Night',' ナイト')
                lines.append(f'| {label} | {amount(group["session_net_yen"])} | '
                    f'{clock["entry"][11:19]} {parent["direction_name"]}→{clock["exit"][11:19]} | '
                    f'{parent["entry_price"]:g}→{parent["exit_price"]:g} | {amount(parent["net"])} | {cause} |')
    # ----------------------------------------
    # 対策は悪い場だけの印象ではなく、同じ全33場の実会計で比較する。
    lines += ['', '## 対策を試すと何が起きたか', '',
        '| 対策 | TOPIXの全33場収支 | 日経の全33場収支 | 残った問題 |',
        '| --- | ---: | ---: | --- |']
    checks = [
        ('変更なし','C_N30_B4','13/33・10/33場だけ黒字。利益を伸ばす一方、入口失敗と利益の返上が残る'),
        ('小利益後に狭く追尾','C_N30_T2','追尾を発動する前の逆行は防げず、伸びる利益も小さくなる'),
        ('支持破れ＋相手逆行を5秒確認して返済','C_N30_B4_THESIS_W10_C5','TOPIXは改善したが日経が悪化。相手も反対でも一時的な押し戻しがある'),
        ('デイ09:15までは静観','C_N30_B4_TIME_J','早朝の損失を減らしたが、日経の赤字場は14/33のまま'),
        ('追従と反転へ8:2の固定配分','P_N30_B4','逆張り追加部分が両銘柄で赤字。違う思想でも補完するとは限らない'),
    ]
    for label, ident, limitation in checks:
        case = data['cases'][ident]['summary']
        lines.append(f'| {label} | {amount(case["TOPIX"]["net"])} | '
                     f'{amount(case["NK225"]["net"])} | {limitation} |')
    lines += ['',
        '小利益でその場を終了する固定配分案は、TOPIX29/33・日経27/33場で黒字になった。しかし全体は−49,734円・−53,080円。**利益になるまで待てる場の多さと、待つ途中の損失額は別問題**だった。', '',
        '反例：10月6日の日経12:35:15買い70,500は、13:00:28の支持破れ・相手逆行で70,470へ返済すると−6,440円。元の15:34返済70,980なら+95,560円で、早い撤回は102,000円を失った。赤字場での早期撤回だけを見ると、この代償を見落とす。', '',
        '## 次に分けて確かめること', '',
        '- 入口：同じ方向判定でも、即時に追い掛けるより有利な指値で入れるか。約定しなかった利益も集計する。',
        '- 途中：往復相場では反転、共同方向が出る相場では追従を選ぶ。両方を常時混ぜる方法とは分ける。',
        '- 出口：一度清算利益が出た場は守れるか。利益前に一方へ逆行する場は、出口だけでは救えない。', '',
        '参照：[全条件・全セッション損益](改善手法と全セッション損益.html)、'
        '[時刻・当時情報・出典seqの原診断](../../work/wave_v106/diagnosis/赤字上位場の具体原因.json)、'
        '[途中撤回の全親対応](../../work/wave_v106/thesis/理由9と三赤字場の出口及び追加入口.json)。', '',
        '全33場は既知の探索対象。資料の未来部分は失敗原因を分析するために表示しており、売買条件に混ぜていません。']
    (PUBLIC/'損失箇所と改善の記録.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    print('保存診断から12取引と5対策を表示。追加金融再生0。')


if __name__=='__main__':
    main()
