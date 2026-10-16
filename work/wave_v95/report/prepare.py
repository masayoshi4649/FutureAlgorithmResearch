"""旧表示資材を新38条件の説明と検査へ合わせる。損益は読み取らない。"""

from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 新作業の表示コードと検査だけを38条件へ更新する。
    引数: なし。
    返り値: None。旧成果や売買条件は変更せず、正式結果も参照しない。
    """
    path = HERE / 'main.js'
    text = path.read_text(encoding='utf-8')
    start = text.index('function rule(config){')
    end = text.index('\n/**', start)
    text = text[:start] + '''function rule(config){
 const source={P0:'両市場の旧中値',P1:'候補は旧中値、許可は原本の約定価格',P2:'両市場の約定価格。ただし旧板の観測資格を保持',P3:'両市場の約定価格を板フローの欠測から独立'}[config.trend_source];
 const entrance=`${source}で同じ方向への進行を確認。5分で各0.03%以上、直近15秒の自己の買い・売り気配も各1呼値以上進む時に参加。TOPIX${config.trend_budget}枚、日経${config.trend_budget*2}枚。`;
 let middle='追加の再参加制限なし。';
 if(config.loss_reentry_kind!=='none'){
  const trigger=config.loss_reentry_trigger==='any_net_negative'?'直前取引の料金後損失':'直前の初期／追尾ストップによる料金後損失';
  const check={ban_opposite:'逆方向への新規を見送る',fresh_quotes:'両市場の新しい価格・気配を受信し、買い・売り気配が逆方向へ各1呼値以上進むまで待つ',fresh_price_quotes:'両市場の新しい価格・気配を受信し、約定価格と買い・売り気配が逆方向へ各1呼値以上進むまで待つ',sustained_price_quotes:'両市場の新しい価格・気配が逆方向へ各1呼値以上進んだ状態を10秒確認する'}[config.loss_reentry_kind];
  middle=`${trigger}の後、逆方向の候補だけ${check}。同方向への再参加は許す。損失は実返済後に判定し、見送った候補を後から復活させない。`;
 }
 const exit=`始値の${(config.trend_width_fraction*100).toFixed(1)}%幅で損切り・利益追尾。今回は入口効果を分けるため旧30分期限を保持。全建玉をセッション内で返済。`;
 return [['入口',entrance],['途中',middle],['出口',exit]].map(([name,text])=>`<p><b>${name}：</b>${escapeHtml(text)}</p>`).join('');
}
''' + text[end:]
    path.write_text(text, encoding='utf-8')
    # ----------------------------------------
    # 表示検査は全条件・全場を保持し、旧作業固有の名前だけを置換する。
    path = HERE / 'verify.py'
    text = path.read_text(encoding='utf-8')
    pairs = {
        '53条件': '38条件', '00090_独立価格と現在確認によるセッション安定化': '00091_両市場追従と損失後の反転確認',
        '独立価格と現在確認の説明と全セッション損益.html': '両市場追従と反転確認の説明と全セッション損益.html',
        'I3_G1_S0_T1': 'P3_R3_N', '== 53': '== 38', '数=53': '数=38', '数=3286': '数=2356',
        "WORK/'data_r1.py'": "WORK/'data.py'", 'input_module.previous.load_inputs(verify=False)': 'input_module.load_inputs(verify=False)',
        '隔離描画94': '隔離描画95', '表示名独立94': '表示名独立95', '表示正規化94': '表示正規化95',
    }
    for old, new in pairs.items():
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
