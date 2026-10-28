"""保存原板だけから五局面の図と短い監査説明を作る。"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
import hashlib
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
plt.rcParams.update({'font.family': 'Yu Gothic', 'font.size': 10,
                     'axes.facecolor': '#152237', 'figure.facecolor': '#0c1727',
                     'text.color': '#e3ebf6', 'axes.labelcolor': '#e3ebf6',
                     'xtick.color': '#bccce1', 'ytick.color': '#bccce1',
                     'axes.edgecolor': '#607086', 'grid.color': '#34455c',
                     'legend.facecolor': '#152237', 'legend.edgecolor': '#607086',
                     'savefig.facecolor': '#0c1727'})


def hash_file(p: Path) -> str:
    """図と根拠の内容指紋を返す。

    引数: p(Path)。返り値: SHA256(str)。
    """
    return hashlib.sha256(p.read_bytes()).hexdigest()


def money(value: float) -> str:
    """会計金額を符号付き円表示へ整える。

    引数: value(float)。返り値: 表示(str)。
    """
    return f'{value:+,.0f}円'


def draw(data: dict) -> Path:
    """原行順と価格時計を分けた4段診断図を保存する。

    引数: data(dict)。返り値: PNG保存先(Path)。
    """
    lot = data['lot']; rows = data['initial_rows']; events = data['events']; full = data['chart_rows']
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [2.1, 1.3, 1.1, 2.1]})
    side = '買い' if lot['Side'] == 1 else '売り'
    fig.suptitle(f"{data['session']}｜{side} {lot['Quantity']} micro・確定 {money(lot['Gross'])}\n"
                 f"原板の事後診断：最大逆行 {lot['Worst']:.0f}円 ／ 最大順行 {lot['Best']:.0f}円", fontsize=16, y=.99)
    x = np.array([r['index'] for r in rows]); b = np.array([r['bid'] for r in rows]); a = np.array([r['ask'] for r in rows])
    axes[0].step(x, b, where='post', color='#5fcbff', lw=1.0, label='Buy1：Bid')
    axes[0].step(x, a, where='post', color='#ffa06a', lw=1.0, label='Sell1：Ask')
    axes[0].axhline(lot['Entry'], color='#f4df83', ls='--', label=f"保存新規価格 {lot['Entry']:.0f}")
    axes[0].scatter([lot['EntryIndex']], [lot['Entry']], color='#f4df83', marker='v' if side == '売り' else '^', s=100, zorder=5)
    axes[0].set_ylabel('日経ラージ価格（円）'); axes[0].legend(loc='best', ncol=3, fontsize=9)
    for p in data['points']:
        q = p['anchor']
        if p['kind'] != 'entry' and x[0] <= q['index'] <= x[-1]:
            axes[0].axvline(q['index'], color='#fd7fa4' if p['kind'] == 'worst' else '#87e3ac', ls=':', lw=1.3)
    axes[1].step(x, [r['bid_qty'] for r in rows], where='post', color='#5fcbff', lw=.8, label='Bid表示数量')
    axes[1].step(x, [r['ask_qty'] for r in rows], where='post', color='#ffa06a', lw=.8, label='Ask表示数量')
    axes[1].set_yscale('symlog', linthresh=10); axes[1].set_ylabel('表示枚数\n10超は対数目盛'); axes[1].legend(loc='upper right', ncol=2, fontsize=9)
    volumes = np.array([r['volume'] for r in rows], dtype=float); dv = np.r_[np.nan, np.diff(volumes)]
    vt = [r['volume_time'] for r in rows]
    same = np.r_[False, np.array(vt[1:]) == np.array(vt[:-1])]
    axes[2].vlines(x[(dv>0)&~same], 0, dv[(dv>0)&~same], color='#c7b5ff', label='量更新（量時計も更新）')
    axes[2].vlines(x[(dv>0)&same], 0, dv[(dv>0)&same], color='#ffdc75', label='量更新（量時計は同じ）')
    axes[2].set_ylabel('累計量の増分'); axes[2].legend(loc='upper right', ncol=2, fontsize=9)
    ticks = np.linspace(0, len(rows)-1, 7).astype(int)
    labels = [f"{rows[i]['index']}\n{rows[i]['jst'][11:19]}" for i in ticks]
    for ax in axes[:3]:
        ax.set_xlim(x[0], x[-1]); ax.set_xticks(x[ticks]); ax.set_xticklabels(labels); ax.grid(alpha=.5)
    axes[2].set_xlabel('上3段：採用原行 index ／下段ラベルは CurrentPriceTime（受信時刻ではない）')
    # ----------------------------------------
    # 全保有経路は時計の最初・末尾を別点で示し、空白を補間しない。
    final_index = events[-1]['FillIndex']
    for kind, color, label in [('first','#90d5ff','各価格時計の最初の正常板'),
                               ('last','#fbab79','同時計の末尾（最初の判断には未確定）')]:
        selected = [r[kind] for r in full if lot['EntryIndex'] <= r[kind]['index'] <= final_index]
        times = [datetime.fromtimestamp(r['time'], JST) for r in selected]
        gains = [lot['Side']*((r['bid'] if lot['Side']==1 else r['ask'])-lot['Entry']) for r in selected]
        axes[3].scatter(times, gains, s=5, color=color, alpha=.7, label=label)
    axes[3].axhline(0, color='#a5b1bf', ls='--')
    for e in events:
        t = datetime.fromtimestamp(e['FillTime'], JST)
        gain = lot['Side']*(e['Price']-lot['Entry'])
        axes[3].scatter([t], [gain], color='#f4df83', marker='x' if e['Order'].get('Targets') else 'o', s=55, zorder=5)
    axes[3].set_ylabel('当初建値から返済側気配差（円）'); axes[3].set_xlabel('下段：価格時計 JST ／ 点表示のみ、空白補間なし')
    axes[3].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S', tz=JST))
    axes[3].legend(loc='best', ncol=2, fontsize=9); axes[3].grid(alpha=.5)
    fig.text(.02, .012, '数量減少＝約定消費、数量増加＝同一注文の補充とは断定不可。最大順行・逆行は事後の説明点。'
             '\n原行順は保存順を示す。CurrentPriceTime が同じ多数行を「実時間で同じ秒」とは解釈しない。新しい売買の検証なし。',
             fontsize=10, color='#cbd6e6')
    fig.tight_layout(rect=[0, .055, 1, .945]); p = OUT / (data['session']+'_価格段階と数量.png')
    fig.savefig(p, dpi=145); plt.close(fig); return p


def main() -> None:
    """5図と根拠付き日本語要約を作成する。

    引数: なし。返り値: None。
    """
    audit = json.loads((OUT/'五夜の原板と時計の監査165.json').read_text(encoding='utf-8'))
    acc = json.loads((OUT/'U00の損失と回復の保存会計165.json').read_text(encoding='utf-8'))
    images = []
    for r in audit['rows']:
        p = Path(r['chart']['path']); data = json.loads(p.read_text(encoding='utf-8'))
        image = draw(data); images.append({'path': str(image), 'sha256': hash_file(image)})
    lines = ['# 米国開始後のU00：調べる5局面と原板の限界', '',
             '既存27完了Nightを固定。新条件の売買再生0、API取得0、米国外部データ0。金額はmicro100枚上限（mini10枚相当）、手数料0の保存模型。', '',
             '## 入力と会計', '',
             '- 保存先は両市場ともDay28・Night27。追加は10/28Dayのみで、今回の金融対象に含めない。既存54場324資料はsize/mtimeが登録記録と一致。抽出した5夜のNK225原板は全読SHAも一致。',
             '- 基準 NK225_U164_00 は全27夜 +1,100,000円、赤字9夜。返済気配の含み益が一度正になってから最終赤字の玉49件、計−878,000円。玉の最大益を全て同時実現できたという意味ではない。',
             '- 23時の返済損失は495,000円だが、返済利益も971,000円ある。時間別帰属だけでその時間を避ける根拠にしない。', '',
             '## 赤字3夜と、逆行から回復した対照', '',
             '|夜|対象玉（価格時計JST）|当初数量|最大逆行 / 最大順行|当該玉の確定損益|',
             '|---|---|---:|---:|---:|']
    for r in audit['rows']:
        l = r['selected_lot']; side = '買' if l['Side']==1 else '売'
        lines.append(f"|{r['session']}|{datetime.fromtimestamp(l['At'],JST):%H:%M:%S} {side} {l['Entry']:,.0f}|{l['Quantity']} micro|{l['Worst']:+.0f} / {l['Best']:+.0f}円|{money(l['Gross'])}|")
    lines += ['', '選択は事後の原因診断用。10/2の買いは28秒後の価格時計で−80円まで逆行した後に回復し、10/14の売りも2分後の価格時計で−50円から回復した。単純な逆行幅だけの退出では、救う損失と消す利益の両方を測る必要がある。', '',
              '10/26は当該core売り−46,000円の後、他担当を含む全実玉時価が23:20:39に+70,000円へ回復し、翌05:49:55には−51,000円。単一玉の利益返しと、別の親の新たな損失を混同しない。', '',
              '黒字夜の利益返しもある。10/2は翌00:25:02の全実玉時価+418,000円から04:35:20に+256,000円、10/21は翌00:37:40の+107,000円から01:35:56に−24,000円となった。', '',
              '## 当時の板から観測できる範囲', '',
              'Buy1〜Buy10とSell1〜Sell10の価格・表示数量、Last、累計TradingVolumeとTradingVolumeTimeは保存されている。通常のBBOはBuy1がBid、Sell1がAskとして使う。最良価格が動いた回数と、同じ価格で数量が増減した回数は別々に数えられる。', '',
              'ただし注文ID、取消識別、約定の買売方向、個々の約定ID・枚数、アプリ受信時計はない。表示数量の消失を約定消費、再出現を同じ参加者による補充と断定できない。累計量の増加と板移動が併存することまでは観測できるが、その全量がその価格で約定したとはいえない。', '',
              '|夜|米国後保存原行|正常BBO|異なる正常価格時計|前行と同時計|同時計内の最大中値幅|同量時計のまま量増加|',
              '|---|---:|---:|---:|---:|---:|---:|']
    for r in audit['rows']:
        c=r['counts']; ratio=100*c['same_price_clock_row']/(c['post_rows']-1)
        lines.append(f"|{r['session']}|{c['post_rows']:,}|{c['post_normal_bbo']:,}|{c['distinct_normal_price_clocks']:,}|{ratio:.2f}%|{c['same_clock_mid_range_max']:.0f}円|{c['volume_increased_same_volume_clock']:,}回|")
    lines += ['', '抽出5夜では米国後のTradingVolumeTimeが全てCurrentPriceTimeと等しい。これは受信時計が得られたことを意味しない。約定価格時計が進まない間にも保存板は変化するため、「同価格時計」は実際の同一秒の保証ではない。量時計不変の累計量増加は同秒の複数約定や保存更新を含み得る。', '',
              '時計が15秒超飛ぶ箇所は各夜367〜425回、60秒超は21〜90回。これを通信途絶と断定せず、価格時計の空白として記録する。同時計末尾の板を、その時計最初の判断へ遡って使わない。', '',
              '## 具体的な読み方と反証', '',
              '- 10/13の売り返済直前15秒の観測窓ではBid/Askの上方向移動が9/9回、下方向が6/5回、中値は+35円。同価格Ask数量減少25回に対し増加18回。売り側が薄くなったことだけでなく、両価格が上へ移ったという順序を観測できる。ただしこの極値は事後選択で、同条件の予測力は未測定。',
              '- 10/26の売り返済直前15秒窓は中値+55円、Bid上12/下7・Ask上10/下4、同価格Ask増14/減31回。上値の表示回復があっても価格上昇を止めていない局面だった。',
              '- 回復した10/2の買いも、逆行極値直前5秒は中値−30円でBid下5回・Ask下6回だった。その時点の逆行圧力だけでは敗者と区別できない。',
              '- 9/21の利益極値23:01:05は、その直前5秒窓内に39正常原行があるが価格時計は1種類・経過0秒。10/14の逆行極値でも43原行が同一時計。「多く更新されたから数秒の確認が済んだ」と解釈しない。', '',
              '次の検証では、価格だけの移動条件と、数量の回復→それを越えた/止められた価格の順序を使う条件を分ける。イベント数と時計経過を別に扱い、未知を逆圧力の成立としない。米国側の方向や原因を観測したと呼ばず、日本の板の再価格付けに対する耐性として測る。', '',
              '## 根拠と画像', '',
              '- [保存入力棚卸し](保存資料の増分と同一性165.json)',
              '- [全27夜の保存会計](U00の損失と回復の保存会計165.json)',
              '- [5夜の原板監査・全70約定一致](五夜の原板と時計の監査165.json)',
              '- 各 `*_選定時刻の原行.jsonl` は入口・返済・MFE/MAE時計の前後2秒にある原行を物理行番号と採番付きで保存。同時計後続は最初の判断時には未知。', '']
    for image in images:
        name=Path(image['path']).name;lines.append(f'- [{name}]({name})')
    (OUT/'米国後の損失と原板可用性165.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (OUT/'図の作成記録165.json').write_text(json.dumps({'financial_replays':0,'images':images,'visual_checked':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print('5 figures and note saved')


if __name__ == '__main__':
    main()
