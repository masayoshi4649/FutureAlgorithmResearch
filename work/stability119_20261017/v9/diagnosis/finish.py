"""保存済みの限定診断だけから、対照の結論と読取証跡を閉じる。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def main() -> None:
    """
    機能: 全八条件の即停止差と改善・悪化各一例を日本語で保存する。
    引数: なし。
    返り値: None。既診断以外の結果・原入力・金融へ接続しない。
    """
    source = HERE / '気配差予算の即停止差と改善悪化二親の限定診断.json'
    value = json.loads(source.read_text(encoding='utf8'))
    assert value['全合格'] and len(value['summary']) == 8 and len(value['examples']) == 2
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in value['source_SHA256'].items())
    lines = [
        '# 初期気配差を予算へ含めた最終対照',
        '',
        '両脚の約定直後に現金枠で止まる件数は全8条件で減った。しかし4条件で総損失が改善し、4条件で悪化した。全8条件は実BBOの手数料前grossでも赤字で、初期spreadを含めるだけでは安定黒字にならなかった。',
        '',
        '変更は予約時の既知両spreadを現金損失枠へ加える一部品のみ。元の二確認・固定極値・入口費用審査・各脚別の次価格秒約定を維持した。会計不正を直した対照ではなく、初期費用を払えない予算設計を切り分けた対照である。',
        '',
        '| 条件 | 旧net円 | 新net円 | 差円 | 旧即停止／両脚親 | 新即停止／両脚親 | 新gross円 | 新料円 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in value['summary']:
        name = row['old_method'].replace('_MR_CONF_', ' ').replace('_', ' ')
        lines.append(f"|{name}|{row['old_net']:,.0f}|{row['new_net']:,.0f}|{row['change']:+,.0f}|{row['old_immediate']}/{row['old_paired']}|{row['new_immediate']}/{row['new_paired']}|{row['new_gross']:,.0f}|{row['new_fees']:,.0f}|")
    lines.extend([
        '',
        '即停止は、両脚fill完了時計とcash返済判断時計が同じ親に限定した。実返済はさらに後の各脚の正常quoteである。X0とX1の共通入口は重なるので、件数や損失を独立標本として合算しない。手数料前grossにはspreadが残り、方向予測だけの収益源を採点した値ではない。',
        '',
        'OLS60 X0は57予約が旧新で完全に対応し、総額は90,930円改善した。OLS30 X0も96予約が完全対応したが7,178円悪化した。親連番だけで結ばず、予約時計・準備時計・方向・モデル・極値・数量・参照価格で照合した。RATIO60 X0だけは旧側に追加の1親−2,614円があり、共通52予約の改善16,286円と合わせて全体改善18,900円になる。',
    ])
    for example in value['examples']:
        old, new = example['old'], example['new']
        before, after = example['old_initial'], example['new_initial']
        ot, nt = example['old_times'], example['new_times']
        side = '日経買い／TOP売り' if old['side_nk'] > 0 else '日経売り／TOP買い'
        lines.extend([
            '',
            f"## {example['label']}例：{old['session']}・{old['method'].replace('_MR_CONF_', ' ')}",
            '',
            f"{ot['decision_time']}に同じモデルで予約。{side}、日経{old['target_quantity_nk']:.0f}枚@{old['entry_nk']:,.1f}、TOP{old['target_quantity_top']:.0f}枚@{old['entry_top']:,.1f}を旧新とも同じ正常quoteで約定した。初期共同清算netは両方{before['net']:,.0f}円。予約時既知spread {after['reserved_spread_cash']:,.0f}円を追加し、枠を{before['budget']:,.2f}円から{after['budget']:,.2f}円へ変えた。",
            '',
            f"旧は{ot['exit_decision_time']}に理由{old['reason']:.0f}で返済判断し、日経{old['exit_nk']:,.1f}／TOP{old['exit_top']:,.1f}で完結、net {old['net']:,.0f}円。新は{nt['exit_decision_time']}に理由{new['reason']:.0f}で判断し、日経{new['exit_nk']:,.1f}／TOP{new['exit_top']:,.1f}で完結、net {new['net']:,.0f}円。差は{example['change']:+,.0f}円だった。",
        ])
        if example['label'] == '改善':
            lines.append('旧の現金停止を越えて保有でき、新では中心到達の理由1で終了した。単に負け親を削った利益ではなく、実際に返済時計と両脚の返済価格が変わった結果である。')
        else:
            lines.append(f"新は一度、費用後の清算可能MFE {new['mfe_liquidation_net']:,.0f}円になったが、その後cash停止で損失になった。予算拡大は損失を大きくする場合もあり、この事後MFEを取れた利益へ置き換えない。理由3は現金枠の停止で、中心到達とは異なる。")
    lines.extend([
        '',
        '## 今回の結論と読取範囲',
        '',
        '初期spreadを入れない枠が作る早過ぎる停止は減った。一方、戻りの継続・利幅・再逆行まで保証する規則ではなく、残る損失を費用だけのせいにはできない。4条件の改善を採用成功とせず、追加の条件選択や金融を行わずに今回の比較を区切る。',
        '',
        '根指定のj完成結果を一回だけ、解析前に同bytes保全した。旧i結果は既所有コピーのみ、必要quoteはi診断が保全した4 NPZだけを再利用した。原市場・原cache・元i結果追加読取・金融再生は0。価格時計の共同snapshot模型であり、真受信順や実同時約定は証明していない。',
    ])
    md = HERE / '初期気配差を予算へ含めても残った損失の対照.md'
    proof = HERE / '初期気配差予算の損失原因診断の完了証跡.json'
    assert not md.exists() and not proof.exists()
    md.write_text('\n'.join(lines) + '\n', encoding='utf8')
    files = [HERE / name for name in ('read_once.py', 'compare.py', 'finish.py',
             '初期気配差予算の即停止と改善悪化を読む計画.json', '完成結果の一読保全記録.json',
             '改善悪化二親の所有quoteだけを読む計画.json',
             '気配差予算の即停止差と改善悪化二親の限定診断.json', md.name)]
    outputs = [{'path':p.relative_to(ROOT).as_posix(), 'SHA256':hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes':p.stat().st_size} for p in files]
    complete = dict(全合格=True, 金融=False, 結果SHA256=value['結果SHA256'], source_SHA256=value['source_SHA256'],
                    新旧条件数=8, 各条件場数=40, 改善条件数=sum(r['change']>0 for r in value['summary']),
                    悪化条件数=sum(r['change']<0 for r in value['summary']), 即停止減少条件数=sum(r['new_immediate']<r['old_immediate'] for r in value['summary']),
                    結果原本読取=1,parse前同bytes保全=True,元結果追加読取=0,元i結果追加読取=0,
                    i既所有quote_NPZ読取=4,原市場読取=0,原cache読取=0,金融再生=0,outputs=outputs,
                    留保='親番号単独で対応せず予約と固定モデルを照合。共通予約と片側のみ親の寄与を分離。全8は手数料前grossも赤、安定黒字未成立。',
                    報告転記の訂正='初回根向けメッセージの例net絶対額を直後に訂正。保存JSONは当初から旧−6702→新20798、旧−5190→新−12190で正しい。差額と政策総額は不変。')
    proof.write_text(json.dumps(complete,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True, 'outputs':outputs[-2:], 'proof':{'path':proof.relative_to(ROOT).as_posix(),'SHA256':hashlib.sha256(proof.read_bytes()).hexdigest()}},ensure_ascii=False))


if __name__ == '__main__':
    main()
