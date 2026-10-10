"""既存の確定会計だけを再集計し、最近の知見を比較する。新しい損益再生は行わない。"""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCES = {}


def read(relative):
    """
    機能: 保存された資料を読取り、出典の指紋を記録する。
    引数: relative (str) はプロジェクトルートからの相対パス。
    返り値: dict は既存資料の内容。
    """
    path = ROOT / relative
    content = path.read_bytes()
    SOURCES[relative] = hashlib.sha256(content).hexdigest()
    return json.loads(content.decode('utf-8'))


def summarize(rows, sessions, symbol):
    """
    機能: 共通期間と単一商品で、部分決済明細の金額と活動を集計する。
    引数: rows (list[dict])、sessions (list[str])、symbol (str)。
    返り値: dict は費用後の利益、損失、収支及び比較指標。
    """
    selected = [r for r in rows if r['session'] in sessions and r['symbol'] == symbol]
    if len(selected) != len(sessions):
        return {'未計算': True, '必要場数': len(sessions), '保存場数': len(selected)}
    profit = sum(r['profit'] for r in selected)
    loss = sum(r['loss'] for r in selected)
    wins = sum(r.get('winning_legs', r['wins']) for r in selected)
    losses = sum(r.get('losing_legs', r['losses']) for r in selected)
    best = max(selected, key=lambda r: r['net'])
    return {
        '利益': profit, '損失': loss, '収支': profit-loss,
        '金額利益割合': profit/(profit+loss) if profit+loss else None,
        '総利益総損失比': profit/loss if loss else None,
        '平均勝ち平均負け比': (profit/wins)/(loss/losses) if wins and losses and loss else None,
        '組数': sum(r.get('campaigns', r['trades']) for r in selected),
        '活動場数': sum(r['trades'] > 0 for r in selected),
        '黒字場数': sum(r['net'] > 0 for r in selected),
        '赤字場数': sum(r['net'] < 0 for r in selected),
        '手数料': sum(r['fees'] for r in selected),
        '最大黒字場除外収支': profit-loss-best['net'],
        '最悪場収支': min(r['net'] for r in selected),
    }


def main():
    """
    機能: 既存結果を同じ期間へ揃え、再利用する部品と未確認案を保存する。
    引数: なし。
    返り値: None。担当領域の比較JSONを出力する。
    """
    sources = {
        'T1L1_R01': 'アルゴリズム調査/00069_T1L1_R01の全セッションと金額評価/銘柄別の全セッション会計.json',
        'R01P_G2_W4_D': 'work/wave_v71/results/R01P_G2_W4_D.json',
        'T3L1_G0_W4_D': 'work/wave_v71/results/T3L1_G0_W4_D.json',
        '始値制限と休止': 'work/wave_v74/extension/results/K0_E0_B1_W40_P2.json',
        'J1': 'work/wave_v77/results/J0_P0_R40_T40_H30_A0.json',
        'J2': 'work/wave_v77/results/J2_P0_R40_T40_H30_A0.json',
        'J1とFD反対撤退': 'work/wave_v76/results/B_FD15_E0_M1_C15_T40_H30.json',
        'Q板厚とドテン': 'work/wave_v76/results/Q25_E10_M2_C30_T40_HS.json',
    }
    accounts = {name: read(path) for name, path in sources.items()}
    sessions = sorted({r['session'] for r in accounts['J2']['rows']})
    assert len(sessions) == 29
    periods = {'前16': sessions[:16], '後13': sessions[16:], '全29': sessions}
    compared = {}
    for name, account in accounts.items():
        compared[name] = {'出典': sources[name], '会計': {
            period: {symbol: summarize(account['rows'], selected, symbol) for symbol in ['TOPIX', 'NK225']}
            for period, selected in periods.items()}}

    # ----------------------------------------
    losses = read('work/wave_v77/diagnostics/既存3候補の前16損失構造.json')
    management = read('work/wave_v77/diagnostics/改善機構の対照分析.json')
    old_management = read('work/wave_v76/analysis/板支持による途中判断の効果と限界.json')
    new_result = read('work/wave_v77/analysis/改善と反証の整理.json')
    reference = read('work/wave_v74/analysis/第二段階の保有継続と休止の分析.json')
    monetary = read('work/wave_v73/audit/全明細金額による全28と全29の独立再選定.json')
    structure = {}
    for symbol, values in losses['候補']['B_F15_E0_M0_C0_T40_H30']['商品別'].items():
        values = values['全体']
        structure[symbol] = values | {
            '含み益後赤字損失の割合': values['含み益後赤字返済の損失']/values['損失'],
            '10bp以上順行後赤字損失の割合': values['最大順行10bp以上後の赤字返済損失']/values['損失'],
        }
    compact = {}
    for symbol, values in management['代表']['J2_P1_R20_T40_H30_A0']['期間']['全29'].items():
        compact[symbol] = values['管理対照']
    result = {
        '範囲': '00066〜00073の既存確定結果を再確認。原本再生、新条件の損益探索、現在API取得は行わない。',
        '新損益再生': False, '現在API取得': 0, '実注文': 0,
        '比較条件': 'ラージ売買気配での次行約定、立会手数料後、TOPIXミニ上限10枚・NK225マイクロ上限20枚。利益玉と損失玉は個別計上。',
        '限界': '過去の探索で全期間既知。時間分割は未知検証ではない。全30があるのは00073の固定22条件のみ。他方式の30場目を0円で埋めない。',
        '同じ前16と後13の比較': compared,
        'J1とJ2の全30': {'J1': new_result['基準']['全30'], 'J2': new_result['代表'][0]['会計']['全30']},
        '損失源': {
            'J1前16': structure,
            '解釈': '含み益後の赤字は多数だが、TOPIXでは10bp以上伸びてからの赤字は総損失の約1%。わずかな揺れを利益として全保護しようとすると、勝ちの途中の揺れも切る。含み益経験だけでは早期保護の根拠にならない。',
            'J2管理対照': compact,
            '管理対照の限界': management['比較の限界'],
        },
        '再利用できる部品': [
            {'部品': '両市場の実価格が同方向に進む入口', '判断': '最有力の中核', '証拠': 'J1/J2は前16・後13の両商品で黒字。各期間の最大黒字場を除いても黒字。Q板厚だけ、単独ティック反転より比較根拠が多い。'},
            {'部品': '明確に逆向きのOFIを入口で除外し、進行量の足並みを確認', '判断': 'J2の入口を共通基準に使う', '証拠': 'NKの損失が減り、後13の平均勝ち平均負け比も1を超える。TOPは利益割合ほぼ不変、利益金額が減り全29のDDはJ1より大きい。両商品同時改善とはいえない。'},
            {'部品': '強い反対合意が成立した場合だけ途中撤退', '判断': '単独追加で検証する価値', '証拠': 'J1+FD15の全29は両商品改善。後13TOPは悪化したため改善確定ではない。弱い支持消失M3への拡張は悪化。'},
            {'部品': '一定の余白を残すトレーリングと保有期限', '判断': '従来J1/J2の出口を対照として保持', '証拠': '早期保護P2は損失と同時に利益も削った。P2は保護と幅縮小を同時変更しており、保護単独を全否定しない。'},
            {'部品': '逆行保険と元玉縮小の経済的等価性', '判断': '新しい予測優位には数えない', '証拠': '同じネット枚数なら両建ては余分な気配差と手数料を支払う。必要なら純枚数を減らし、保険利確だけの勝率を採点しない。'},
        ],
        '再導入を急がない部品': [
            {'部品': 'T1L1_R01の段階利益固定', '理由': '全29でTOP勝率73.2%・NK75.7%でも両商品赤字。平均勝ち平均負けは約0.25/0.23。高勝率と損小利大を区別する。'},
            {'部品': 'R01P_G2_W4_Dの金額首位', '理由': 'TOPの全29利益割合57.25%は18組のみ、前16赤字、追加デイ-90,836円。共通の安定最良とは認められない。'},
            {'部品': 'T3補充反転と広幅', '理由': '全29両黒字でもNK14組、前16NK赤字、後13TOP赤字、TOPは最大黒字場除外赤字。観測上の補充であり真の補充発注者は不明。'},
            {'部品': '始値・前終値の片方向制限＋連敗休止', '理由': '保有継続に仕様を切り分けた追加240でも全29両商品黒字なし。基準より上か下かは、その後の限界注文の優劣を示さない。'},
            {'部品': '数量を小さく開始して順行追加', '理由': '00073のQ/P代表では追加0回、損失だけでなく利益も約1/5。予測精度改善ではない。追加した場合は遅い玉の負けを隠さない。'},
            {'部品': 'Q板厚主導の早い入口・ドテン', '理由': '主5秒では全29黒字でもNKは情報遅延1/15秒で赤字。共通受信時計が無いデータで秒単位優位を採用根拠にしない。'},
        ],
        '理論からの統合案': [
            {'案': 'J2＋FD強反対撤退', '入口': 'J2の条件を固定して使用。', '途中': '両市場でOFIと距離加重板が逆向きに揃い、新しい両市場観測で15秒確認した時だけ撤退。', '出口': '従来0.4%トレール、30分、場内返済。', '理由': '入口に継続する共通価格圧力を使い、保有仮説を壊す明確な反対圧力に反応する。中立は反転とみなさない。', '未確認': 'J2入口とFD撤退の相互作用。過去の別々の改善を足し算しない。'},
            {'案': 'J2＋実価格を伴う仮説失効撤退', '入口': 'J2を固定。', '途中': 'FD強反対合意に加え、両市場の短期売買気配が元方向と逆に進んでいる時に撤退。', '出口': '従来トレールと期限を保険として維持。', '理由': '数量だけの取消や一時偏りを、実際に気配を動かした反対圧力と区別する。', '未確認': '追加確認による撤退の遅れ。価格窓・持続秒数は損益前に少数固定する。'},
            {'案': '上記に一組損失枠又は当場損失枠を独立追加', '入口': '既存と同じ。', '途中': '同じ始値割合等で決めた予算を超えたら縮小又は停止。', '出口': '損失枠達成時の次有効気配返済。', '理由': '予測精度ではなく悪い日の損失尾部を制限する。', '未確認': '損切り後の回復利益を消す可能性。最初の損失を防ぐものではなく、全日黒字の解決策と扱わない。'},
        ],
        '閾値の由来を混同しない': {
            '結果選定済み': 'J1の300秒0.03%、出口0.4%と30分は過去条件群の前16選定。J2のOFI-0.1、進行量比1/4は00073固定範囲から前16選定。理論だけから一意に導いた定数ではない。',
            '結果閲覧前に固定した理論': '共通価格進行を確認し、中立と反対成立を区別し、損失玉・手数料を含めて判定するという機構。理論が正しくても係数や収益性を保証しない。',
            '今回の新案': '上記の統合は既知結果から着想した新条件。既知30場で良くなっても独立未知データの証明ではない。',
        },
        '結論': '直近で最も共通性があるのはJ1/J2の共同価格進行＋余白のあるトレーリング。全日安定の達成は未確認。板は早く入る主予測器より、矛盾した入口の除外と強い仮説失効の補助に置く。',
        '出典SHA256': SOURCES,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / '最近の候補と再利用できる部品.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'保存': str(target), '候補数': len(compared), '新損益再生': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
