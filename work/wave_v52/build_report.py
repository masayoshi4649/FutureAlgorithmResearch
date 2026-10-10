"""観測・固定規則・全口座損益を短い暗色HTMLへまとめる。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'アルゴリズム調査/00049_価格形成の観測から新手法を構築'
sys.path.insert(0, str(HERE / 'theory'))
from analyze import load_ready


def read(path: Path) -> dict:
    """機能: 日本語JSONを読む。

    引数: path(Path)。返り値: 内容(dict)。
    """
    return json.loads(path.read_text(encoding='utf8'))


def main() -> None:
    """機能: 再計算済みの観測と損益だけから報告書を生成する。

    引数: なし。返り値: なし(None)。条件選択や新規データ取得はしない。
    """
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = read(HERE / '売買結果.json')
    fixed = read(HERE / '売買仕様固定.json')
    measurement = read(HERE / 'theory/観測結果.json')
    ready = load_ready()
    prices = {'TOPIX': {}, 'NK225': {}}
    for (session, symbol), a in ready.items():
        grid = np.arange(a['time_s'][0], a['time_s'][-1], 60.)
        ix = np.unique(np.r_[np.searchsorted(a['time_s'], grid, side='right') - 1, len(a['time_s']) - 1])
        prices[symbol][session] = np.c_[a['time_s'][ix], a['last'][ix]].tolist()
    rows = []
    for symbol in ('TOPIX', 'NK225'):
        for feature, title in (('execution', '執行側'), ('withdrawal', '表示減少'), ('addition', '表示追加'),
                               ('recovery', '同価格回復'), ('supply', '近接供給'), ('repricing', '両気配の値直し')):
            values = [r for r in measurement['指標別'] if r['symbol'] == symbol and r['feature'] == feature
                      and r['horizon'] == 300 and r['sampling'] == '60秒']
            rows.append([symbol + '・' + title, *[f'{v["partial_corr"]:+.3f}' for v in values]])
    # ----------------------------------------
    # 本文は主試験を中心にし、比較の最高利益へ置換しない。
    data = dict(headline='価格形成の違いは測れた。共通して安定する利益は、まだ確認できない。',
        findings=[
            '<b>観測：</b>執行と注文追加の偏りは、その時の値動きと関係しました。ところが5分先の追加情報は小さく、TOPIXとNK225で符号も異なりました。「どちらが焦っているか」まで特定できたわけではありません。',
            '<b>新案P01：</b>執行方向の強い偏りと同方向の値動きを観測した後、偏りの消失と価格反転を待つ方法を作り、12入口＋2出口の14条件で検証。23場合計はTOPIXミニ5枚で <b>+57,500円</b>、NK225マイクロ10枚で <b>−90,000円</b>。平均勝ちは平均負けの1.26／1.20倍でも、負ける回数が多く、安定性は不足しました。',
            '<b>反証：</b>TOPIXでは価格だけの反転確認C03（+607,500円）、NK225では即逆張りC02（+326,000円）が主案を上回りました。ただし銘柄別に結果を見て選んだ組合せは、検証済みの自動選択アルゴリズムではありません。'],
        observationNote='<p>先頭10場で比較尺度・調整係数を固定し、次9場と最後4場へ適用。表はその固定係数で調整した残差同士の相関です。14,770の有効な1分起点を使用しました。全23場は過去の調査で既に見たデータなので、真の未見テストとは呼びません。</p>',
        observations=rows, methods=fixed['手法'], mainMethod='P01',
        assumptions='TOPIXミニは1回5枚（上限10枚）、NK225マイクロは1回10枚（上限20枚）。増玉なし。費用0、判断後の次の有効原本行の最終価格で約定。ラージ価格を各商品の倍率で換算。全玉を場内で返済。',
        results=results, prices=prices, sessions=sorted({key[0] for key in ready}),
        auditText='''<p><b>検証済み：</b>約595万原本行、23場×2銘柄、14条件・644口座。29,638注文の判断後約定、枚数制限、全玉返済、13,048区間の含み込み会計を独立検算。未来を切断・改変しても、それ以前の特徴・判断・約定は変わりませんでした。</p>
<p><b>識別できない：</b>真の取消／約定内訳、隠れ数量、同じ発注者の補充、新規建玉と返済の区別、参加者の心理。受信時計がないため、約定時計を使った時間順再生です。</p>
<p><b>まだ証明していない：</b>異なる週への再現、8割の取引勝率、長い継続波の捕捉、ミニ／マイクロでの実約定。今回の観測は1・5・15分の応答が対象です。板の価値全般を否定した結果ではありません。</p>
<details><summary>約定価格だけを変えた参考感度</summary><p>主表の費用0条件とは別に、約定時刻と枚数を固定し、同行の中値、買いは売気配・売りは買気配へ置換しました。P01はTOPIX +57,500 → +225,000 → −1,337,500円、NK −90,000 → −72,000 → −662,000円。中値では改善するので、古い最終価格だけが主因とは言えません。小幅頻回売買の収益に対し、提示気配差の影響が大きい比較です。</p><p>損切り・判断の再計算を伴わず、ラージの気配を使用した感度試験です。ミニ／マイクロの実際の約定結果ではありません。<a href="../../work/wave_v52/measurement/約定価格感度.json">全14条件の価格感度</a></p></details>
<p>現在セッションのAPI取得：0回。実注文：0回。既存のApp/E01は変更していません。</p>''')
    for method in data['methods']:
        if method['id'] == 'P01':
            method['description'] = '執行偏りと同方向の値動きを観測した後、その偏りと値動きが反転してから戻りを狙う。'
            method['entry'] += '強さの閾値はTOPIX 0.500、NK 0.588。最初に記憶してから5分で失効し、同方向の継続で延長しない。'
    for syms in results.values():
        for group in syms.values():
            for account in group['accounts']:
                account.pop('trades', None)
    template = (HERE / 'report_template.html').read_text(encoding='utf8')
    # 関数説明を複数行スタイルへ統一する。
    template = re.sub(r'/\*\* ([^\n]*?) \*/', lambda m: '/**\n * ' + m[1].replace('@param', '\n * @param').replace('@returns', '\n * @returns') + '\n */', template)
    (HERE / 'report_template.html').write_text(template, encoding='utf8')
    content = template.replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    path = OUTPUT / '価格形成から組んだ新手法の検証.html'
    path.write_text(content, encoding='utf8')
    meta = dict(主HTML=str(path), バイト数=path.stat().st_size, SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                セッション数=len(data['sessions']), 手法数=len(data['methods']), 銘柄数=2)
    (OUTPUT / '生成記録.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main()
