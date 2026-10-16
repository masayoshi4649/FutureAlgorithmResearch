"""二系統の人工と独立接続を現在ソースへ照合し、本文の初読前に固定する。"""

import json

import plan


def main() -> None:
    """
    機能: 人工・独立source監査の合格と指紋を確認して正式計画を保存する。
    引数: なし。
    返り値: None。実登録・NPZ本文・金融・APIを開始しない。
    """
    source = plan.sources()
    evidence = [
        plan.ROOT / 'work/quantity_response_20261015/固定BBO数量と公表活動及び価格先着の人工検査.json',
        plan.HERE / '正常行逆写像と分母及び原始型保存の純人工.json',
        plan.ROOT / 'work/quantity_response_20261015/audit/owned/完成数量coreと独立episode及び価格先着のSOURCE_ONLY接続_v2.json',
        plan.HERE / 'audit/正常行逆写像の修正と完成五sourceの独立接続.json',
    ]
    for path in evidence:
        value = plan.read(path)
        assert value['全合格']
        for relative, expected in value['source_SHA256'].items():
            target = plan.ROOT / relative if relative.startswith('work/') else plan.HERE / relative
            assert plan.digest(target) == expected
    for path in (evidence[1], evidence[3]):
        assert plan.read(path)['source_SHA256'] == source
    plan.write(plan.HERE / '本体初読前の人工と独立監査.json', dict(
        全合格=True, 入力本文=0, 新金融=0, API=0, source_SHA256=source,
        読取履歴='初版はNPZ1読で資格検査停止・測定0。この修正版は本体未読。以後66読で、累計67読と分離する。',
        evidence=[dict(path=path.relative_to(plan.ROOT).as_posix(), SHA256=plan.digest(path)) for path in evidence],
        説明='旧33場の数量応答だけを一回測る。追加2場・売買・費用・テクニカル・相手板は対象外。',
        修正='正式試行登録のflat実装指紋とinput_manifests形式に合わせた。観測条件は不変。'))
    plan.freeze()
    print(json.dumps(dict(全合格=True, source数=len(source), 入力本文=0, 新金融=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
