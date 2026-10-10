"""復元方式を選ぶ価値と、全条件の金額・数量を分けて表示する。"""

from __future__ import annotations
import argparse
from html import escape
import sys
import adaptive_runner as runner
import adaptive_assessment as assessment
import assess_results

sys.path.insert(0,str(runner.HERE.parent/'wave_v35'))
import report_conditional as previous
import deterioration_signals

HERE,ROOT=runner.HERE,runner.ROOT
TITLE='復元方式の自動選択と改善8条件の反証'
OUT=ROOT/'アルゴリズム調査'/('00033_'+TITLE)
style=previous.style
CONDITIONS={r['id']:r['name'] for r in deterioration_signals.catalog()}
COMPARISONS=(('元の数量を維持','H019__A0__R1__V000'),
    ('主案：長めの逆行で使い分け',assessment.PRIMARY),
    ('常に回復待ち',assessment.SIGNAL),('常に120秒待ち',assessment.CLOCK),
    ('逆の使い分け',assessment.REVERSE),
    ('主案・実R退出なし',assessment.PRIMARY.replace('__R1__','__R0__')))


def state_note() -> str:
    """機能: 金銭の検算と未修正の状態契約不具合を分離して示す。

    引数: なし。返り値: 全ページ共通の説明HTML (str)。完全合格とは表示しない。
    """
    return '<p data-state-contract="failed"><b>実装状態の監査は未合格。</b>注文遅延15秒の1条件で、全返済予約後に取消済みの減量予約表示が12行残りました。注文・損益の検算とは分離し、現版をそのまま実運用できる完成品とは扱いません。<a href="../../work/wave_v38/状態残存の契約違反と経済影響.md">不具合と経済影響の検証</a></p>'


def description(spec: dict) -> str:
    """機能: 固定条件の分岐・数量・感度を短い日本語にする。

    引数: spec (dict)。返り値: 説明 (str)。
    """
    p=spec['policy']
    if p['kind']=='baseline':
        text='初回TOPIX5枚／NK10枚を元の返済条件まで保つ。'
    elif p['kind'] in ('static_core','static_split'):
        quantity='TOPIX4枚／NK8枚' if p['reduce_fraction']==.25 else 'TOPIX3枚／NK5枚'
        text='初回から'+quantity+'。'+('元の後半保有枠を残す。' if p['kind']=='static_core' else '実初回枚数の半分を先に利確する。')
    else:
        text=CONDITIONS[p['bad_id']]+'が保有と逆なら、生存枠の'+str(round(p['reduce_fraction']*100))+'%を返済。整数丸め、最低1枚を残す。'
        if spec['branch_mode'] in ('adverse_signal','reverse','random'):
            text+=f'減量約定時のB01（自市場{600*spec["branch_scale"]:g}秒）で復元方式を固定。'
            timer=f'{p["restore_seconds"]:g}秒待ち'
            text+=('有効な逆行なら回復待ち、それ以外は'+timer+'。' if spec['branch_mode']=='adverse_signal' else
                '有効な逆行なら'+timer+'、それ以外は回復待ち。' if spec['branch_mode']=='reverse' else '固定乱数で回復待ち／'+timer+'を選ぶ。')
        elif p['restore_mode']=='none':text+='復元しない。'
        elif p['restore_mode']=='timer':text+=f'{p["restore_seconds"]:g}秒後から、新しい有効な'+p['good_id']+'公開で復元。'
        else:text+='新しい'+CONDITIONS[p['good_id']]+'が保有方向を肯定したら復元。'
        text+=f'元組につき減量は{p["max_reductions"]}回まで。元の利確済み枠は再開しない。'
    text+=' 実損益1R退出'+('あり。' if spec['budget_enabled'] else 'なし（元の逆指値・返済は残る診断）。')
    if spec['variant_id']!='V000':
        text+=f'診断：入口×{spec["entry_scale"]:g}、悪化×{spec["bad_scale"]:g}、回復×{spec["good_scale"]:g}、分岐×{spec["branch_scale"]:g}、注文遅延{spec["min_delay_seconds"]:g}秒。'
    if spec['observed_fill']:text+='観測価格約定。'
    for field,label in (('bad_seed','減量符号'),('good_seed','回復符号'),('branch_seed','分岐')):
        if spec[field] is not None:text+=f'{label}の固定乱数seed={spec[field]}。'
    return text


def money_tables(rows: list[dict], identifier: str, sessions: list[str]) -> str:
    """機能: 全期間・各週・各セッションの金額と延べ返済枚数を示す。

    引数: rows (list[dict])、identifier (str)、sessions (list[str])。返り値: HTML (str)。
    """
    body = []
    for symbol in runner.SYMBOLS:
        part = sorted((r for r in rows if r['symbol'] == symbol), key=lambda r: r['session'])
        assert len(part) == 13
        output = [style.money_row(label, style.totals([r for r in part if r['session'] in names]))
            for label, names in (('全13', sessions), ('共通後半7', sessions[6:]),
                ('9/21開始週', [s for s in sessions if s < '2026-09-28']),
                ('9/28開始週・途中', [s for s in sessions if s >= '2026-09-28']))]
        output += [style.money_row(r['session'], r) for r in part]
        body += ['<h3>'+symbol+'</h3>', style.table(
            ['区間', '利益 円', '損失 円', '収支 円', '利益枚数', '損失枚数', '同値枚数', '勝ち−負け枚数'],
            output, f'data-id="{identifier}" data-symbol="{symbol}"')]
    return ''.join(body)


def all_results(items: list[dict], sessions: list[str], preview: bool) -> None:
    """機能: 全974条件を個別選択できる章として出力する。

    引数: items (list[dict])、sessions (list[str])、preview (bool)。返り値: なし (None)。
    """
    primary = runner.design.PRIMARY_ID
    body = [f'<p><a href="{TITLE}.html">比較へ</a></p><h1>全条件の損益</h1>',
        '<p>主206・補助768。数量は延べ返済枚数です。勝ち−負け枚数は数量差であり、損益額でも現在の保有数でもありません。</p>',
        '<label>手法<select id="method-filter">'+''.join(f'<option value="{r["id"]}"'+
            (' selected' if r['id'] == primary else '')+'>'+escape(r['id'])+'</option>' for r in items)+'</select></label>']
    body.insert(1, state_note())
    for item in items:
        identifier, spec = item['id'], item['spec']
        destination = 'supplementary' if spec['role'] == 'supplementary' else ''
        rows = runner.read(HERE/destination/'sessions'/(identifier+'.json.gz'))
        body += [f'<section class="method" id="{identifier}"'+(' hidden' if identifier != primary else '')+'>',
            '<h2>'+escape(identifier)+'</h2><p>'+escape(description(spec))+'</p>',
            money_tables(rows, identifier, sessions), '</section>']
    if preview: body.insert(1, '<p><strong>独立監査中の暫定表示。</strong></p>')
    script = '''/**
 * 選択した固定手法の表示だけを切り替える。
 * @param {Event|undefined} event - 選択操作。
 * @returns {undefined} 返り値なし。売買条件には触れない。
 */
function filter(event){const value=document.getElementById('method-filter').value;document.querySelectorAll('.method').forEach(e=>e.hidden=e.id!==value)}const choice=document.getElementById('method-filter');const requested=decodeURIComponent(location.hash.slice(1));if(Array.from(choice.options).some(o=>o.value===requested))choice.value=requested;choice.addEventListener('change',filter);filter();'''
    (OUT/'全条件損益.html').write_text(style.page('全条件の損益', body, script), encoding='utf-8')


def main() -> None:
    """機能: 凍結された主仮説の判定と全974条件を表示する。

    引数: --preview (bool)。返り値: なし (None)。正式版は経済完備監査必須。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true')
    preview=parser.parse_args().preview
    index,sessions,fixed=assess_results.collect()
    if not preview:
        proof=runner.read(HERE/'経済完備監査.json')
        assert proof['経済検証完了'] and proof['実装状態契約合格'] is False
        assert (proof['全条件数'],proof['補助条件数'])==(206,768)
        for path,sha in proof['参照資料SHA256'].items():assert runner.digest(ROOT/path)==sha,path
    verdict=runner.read(HERE/('暫定判定.json' if preview else '独立判定.json'))
    primary=index[assessment.PRIMARY]
    chosen=[(label,index[identifier]) for label,identifier in COMPARISONS]
    status=lambda value:'通過' if value else '未通過'
    overview=('主案は黒字・損小利大の基礎候補です。' if verdict['基礎候補'] else '主案は基礎候補の条件を満たしません。')
    overview+=('使い分けによる利益改善も支持されました。' if verdict['分岐の利益付加価値'] else '使い分けが固定方式を上回る証拠は不足しました。')
    body=[f'<p><a href="../index.html">調査一覧</a> ／ <a href="全条件損益.html">全974条件の週・セッション損益</a> ／ <a href="５分足と売買.html">5分足と売買</a></p><h1>{TITLE}</h1>',
        '<p class="lead">'+overview+'</p>',
        state_note(),
        '<p>主案：両市場が短期で逆行したら半量を減らす。その時点で自市場も長めに逆行していれば回復を待ち、それ以外は120秒後から新しい有効情報を確認して数量を戻す。</p>',
        '<p>基礎候補：<b data-verdict="基礎候補">'+status(verdict['基礎候補'])+'</b> ／ 14感度：<b data-verdict="十四感度頑健性">'+status(verdict['十四感度頑健性'])+'</b> ／ 使い分けの価値：<b data-verdict="分岐の利益付加価値">'+status(verdict['分岐の利益付加価値'])+'</b></p>',
        '<h2>同じ入口での全13セッション比較</h2>',previous.main_table(chosen,'all_symbols'),
        '<p class="muted">TOPIXミニ／NKマイクロ換算。初回5／10枚、片方向上限10／20枚。費用0・指定価格約定・場内全返済。最大下落は含み損益込み。枚数は延べ決済数です。</p>',
        '<details><summary>後半7セッションの比較</summary>',previous.main_table(chosen,'symbols'),'</details>',
        '<details><summary>使い分けはなぜ合格／不合格か</summary>',
        style.table(['検査','結果'],[[name,status(value)] for name,value in verdict['分岐価値']['検査'].items()]),
        '<p>減量時点が同じ取引同士を比較。主案の選択が、常に回復待ち・常に時計待ち・逆選択・分岐だけ乱数の64対照を上回るか確認しました。黒字と選択情報の価値は別判定です。</p>',
        '<p>後半7セッションでは、乱数分岐64本のうちTOPIX56本・NK35本が主案以上の円収支でした。14感度は基礎収益条件の通過であり、収益額が一定という意味ではありません。</p>',
        '<p>例：TOPIXの9/25ナイトでは時計復元で損失が7,000円から13,000円へ増加。NKの9/24ナイトでは回復待ちで復元機会を失い、利益が16,500円から7,500円へ減少しました。<a href="../../work/wave_v38/分岐の反例と読み方.md">対応する注文と原因</a>。</p>',
        '<p><a href="../../work/wave_v38/独立判定.json">全層別差・全感度・全対照の判定資料</a></p></details>',
        '<details><summary>前回改善した8条件はどうだったか</summary>',
        style.table(['条件ID','基礎候補','TOP収支 円','TOP最大下落 円','NK収支 円','NK最大下落 円'],
            [[f'<a href="全条件損益.html#H019__{policy}__R1__V000">{policy}</a>',status(verdict['既選抜八条件'][policy]['基礎候補'])]+
                [style.yen(index['H019__'+policy+'__R1__V000']['all_symbols'][symbol][field]) for symbol in runner.SYMBOLS for field in ('net_yen','drawdown_yen')]
                for policy in runner.design.SELECTED], 'id="main-eight"'),
        '<p>同じ入口を使う8条件です。8件の独立した成功とは数えません。感度・減量符号・回復符号の対照も全条件損益に掲載しています。</p></details>',
        '<details><summary>エントリーとイグジット</summary><p>公開済み1分足のEMA15/60、60秒遅れの他市場方向、直近30秒の気配変化が一致したら、0.25ATRの新規トレーリングを準備。</p>',
        '<p>初回ATRを固定し、組全体で1ATR相当の損失予算、2ATRで元枠の半分利確、1.5ATR順行後に3ATR追跡、最長360分。減量・復元の損益も同じ組へ加算し、場末には全返済します。</p>',
        '<p>追加の実R退出を外した比較でも、元の損切りと場末返済は残します。保有増減と予算返済の効果を分けるための診断です。</p></details>',
        '<details><summary>検証範囲</summary><p>主206＋補助768条件。全25,324入力の独立会計、3,918入力の過去部分一致・未来改変・価格反射、指定7,792波区間を照合。注文遅延1/5/15秒、窓±20%、観測価格約定も比較しています。</p>',
        '<p>全13セッションは既知で、後半7も未知データではありません。先物価格をミニ／マイクロに換算しています。遅延診断は約定通知の即時認識と注文組の一括管理を前提にし、別々の取消通知が前後する通信障害までは再現していません。</p>',
        '<p>乱数対照は公開機会を保持する成分検査です。正式な有意確率や市場情報を完全に除いたコイントスとは扱いません。現在APIの追加取得は0回です。</p></details>',
        '<p><a href="README.md">資料案内・再現手順</a></p>']
    if preview:body.insert(1,'<p><strong>独立監査中の暫定表示。</strong></p>')
    OUT.mkdir(exist_ok=True)
    (OUT/(TITLE+'.html')).write_text(style.page(TITLE,body),encoding='utf-8')
    all_results([index[s['id']] for s in fixed['conditions']+fixed['supplementary_conditions']],fixed['全セッション'],preview)
    print('全974条件の比較と損益を出力。')


if __name__=='__main__':main()
