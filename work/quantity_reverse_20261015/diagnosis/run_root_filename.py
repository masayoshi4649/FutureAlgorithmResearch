"""根が指定した診断保存名だけを接続し、固定済み診断を一回実行する。"""

import reader


def main() -> None:
    """
    機能: 判定式や読取対象を変えずに、完成診断のファイル名だけ根指定へ接続する。
    引数: なし。
    返り値: None。金融の再実行や原入力読取は行わない。
    """
    previous=reader.OUTPUT
    assert previous.name=='新反転十二条件の金額分解と指定二例の小診断.json' and not previous.exists()
    target=reader.HERE/'反転の実運転と二例の注文及び費用の小診断.json'
    assert not target.exists()
    reader.write(reader.HERE/'根指定の診断保存名への接続.json',dict(目的='root complete_trialが接続する指定ファイル名へ変更。数式/対象/予算は不変更。',
        旧予定名=previous.name,新保存名=target.name,固定計画SHA256=reader.sha(reader.PLAN.read_bytes()),
        wrapper_SHA256=reader.sha(__import__('pathlib').Path(__file__).read_bytes()),実結果読取前=True))
    reader.OUTPUT=target
    reader.run('7c0bcadbaaf933669c989cdce5517009b7b4adeec6c58fb27c2a379b2dab8b65')


if __name__=='__main__':main()
