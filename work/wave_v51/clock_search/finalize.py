"""時計探索の監査ラベルを明確にし、保存数値から短い比較表を作成する。"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    """機能: 比較表と証跡一覧を生成する。

    引数: なし。返り値: なし(None)。損益・注文は変更しない。
    """
    result = json.loads((HERE / '結果.json').read_bytes())
    for path in (HERE / 'audits').glob('*.json.gz'):
        proofs = json.loads(gzip.decompress(path.read_bytes()))
        for proof in proofs:
            if '全初回一致' in proof:
                proof['指定時計と全初回一致'] = proof.pop('全初回一致')
            if '元影時計一致' in proof:
                proof['指定時計から再生成一致'] = proof.pop('元影時計一致')
            if '通常影から再生成' in proof['因果']:
                proof['因果']['指定時計から再生成'] = proof['因果'].pop('通常影から再生成')
        path.write_bytes(gzip.compress(json.dumps(proofs, ensure_ascii=False, indent=2).encode('utf8'), mtime=0))
    lines = ['# 再参加時計の探索', '', '最初にこのファイルを読み、次に「事前固定.json」「選択.json」「結果.json」の順で確認する。詳細台帳はledgers、場別集計はsessions、時価曲線はcurves、監査はaudits。', '',
        '**時計変更単独は採用できない。** 先頭10場で選んだ上位3条件が、追加4場では全て従来E01より悪化した。損切り後の再参加を可能にするだけで安定性が上がる仮説は支持されなかった。', '',
        'K20は10月6日TOPIXの後半回復へ13:11に買い直して+24,500円を取り、場収支を−75,000円から−50,500円へ改善した。一方、10月1日ナイトはTOPIXの組数が7→13、NKが11→19に増え、収支がそれぞれ+187,500→−3,000円、+58,000→−83,200円に悪化した。待機には機会を失う面と追加試行を抑える面がある。', '',
        'ただしK20は休止5→15分も同時変更している。同じ15分休止で時計だけを変えたK04→K20の全期間差はTOPIX−52,500円、NK−27,100円。休止だけを延ばすK00→K04の差は−446,500円、−140,500円だった。K20の大幅悪化を時計変更だけに帰してはいけない。注文時刻が変わった結果のため、単なる件数制限とも異なる。', '',
        '48条件を先頭10場だけで選び、上位3条件と既存E01を次9場・直近4場で再検証した。次9・直近4は既知データであり、将来の未見成績ではない。', '',
        '|ID|再参加時計|休止分|入口ATR|時間失敗保護|', '|---|---|---:|---:|---|']
    for identifier, summary in result['集計'].items():
        spec = summary['条件']
        lines.append(f"|{identifier}|{spec['clock']}|{spec['cooldown']:g}|{spec['entry']:g}|{spec['failure']}|")
    lines += ['', 'normalは従来どおり損切り1ATRの通常影、riskは影の損切りを実口座の0.75ATRに統一、actualは利益追跡の短縮も出口影に統一。actualも途中の減量まで一致する実口座完全フラット時計とは異なる。休止は指定時計の終了から計測する。', '',
        '|ID|期間|銘柄|利益円|損失円|収支円|勝ち場/全場|PF|平均1枚勝敗比|時価DD円|最良場除外円|組数|',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for identifier, summary in result['集計'].items():
        for label, symbols in summary['periods'].items():
            for symbol, p in symbols.items():
                lines.append(f"|{identifier}|{label}|{symbol}|{p['gross_profit_yen']:,.0f}|{p['gross_loss_yen']:,.0f}|{p['net_yen']:+,.0f}|{p['win_sessions']}/{p['session_count']}|{p['money_ratio']:.2f}|{p['average_unit_payoff']:.2f}|{p['drawdown_yen']:,.0f}|{p['best_removed_net']:+,.0f}|{p['cycles']}|")
    lines += ['', '全詳細対象で独立会計、片方向上限、初回数量、場内完済、原本次行以降の注文、切断・未来変更・上下反射の因果監査が合格。K00は旧E01の全46口座で注文・実口座・出口影・準備時計の指紋が完全一致した。', '',
        '再現: プロジェクトルートで `python -X utf8 work/wave_v51/clock_search/research.py` を実行する。保存済み先頭10場の比較はtrainingから再利用する。', '']
    (HERE / '結果の要点.md').write_text('\n'.join(lines), encoding='utf8')


if __name__ == '__main__':
    main()
