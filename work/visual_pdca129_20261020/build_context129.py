"""画像で見た短期と長期の違いを、実装可能な比較へ限定する。"""

from common129 import HERE, PREV, read, save, reference


def main():
    """
    機能: 基準出口を変えず、一時間の方向又は既知境界までの余地を比較する計画を作る。
    引数: なし。
    返り値: None。金融再生は行わない。
    """
    base = next(c for c in read(PREV/"第五巡条件.json") if c["id"] == "N36")
    configs = []
    for i, (source, mode, title) in enumerate((
        ("last", 1, "現在値・一時間と逆の新規を見送る"),
        ("last", 2, "現在値・両市場一時間と逆の新規を見送る"),
        ("last", 3, "現在値・既知一時間境界まで利益保護幅の余地"),
        ("mid", 1, "気配中値・一時間と逆の新規を見送る"),
        ("mid", 2, "気配中値・両市場一時間と逆の新規を見送る"),
        ("mid", 3, "気配中値・既知一時間境界まで利益保護幅の余地"),
    ), 4):
        configs.append(dict(base, id=f"NV{i:02d}", name=title, price_source=source,
                            peer_delay=0., context_mode=mode))
    save(HERE/"第二巡条件.json", configs)
    save(HERE/"第二巡の変更根拠.json", dict(
        question="20分の進行を一時間の押し戻りと取り違えた入口を、既知の方向・価格帯で減らせるか",
        change="N36と第一巡の出口を保ち、発注時に一時間文脈を追加。自己方向だけ、両市場方向、既知境界まで保護起動幅の余地を分ける。Lastと中値で同じ機構を比較する。",
        repeat_reason="00128の自己5/20分支持追加は日経を悪化。今回は9/29夜間の二市場画像で見えた一時間上昇の押しと帯下抜けの区別を検証し、単なる中期条件追加と同一視しない。",
        evidence=[reference(HERE/"night/利確後の同方向再参加と一時間文脈の全親分類.json")],
        classification="既存N36の一時間逆方向は日経9親3勝6敗−40980円、TOPIX8親4勝4敗−30844円。分類は旧注文固定の参考であり、新条件の収支ではない。新機構は遅延公開の確定一分終値から60分差を作る。",
        counterexamples="一時間逆向きでも日経9/30買い+4780円、TOPIX10/7買い+9582円。無取引増加、遅れて入り直す損失も全運転で測る。",
        rejected="利確後20分以内の再参加8親は全て以前の最高順行気配を更新済み。未更新帯を単に再消費したという画像仮説は棄却。",
        compares_to=["129_round1_チャートと板の失敗機構改善"],
        limitation="既知21夜間の開発比較。過去一時間の方向が次も続くと断定しない。"))


if __name__ == "__main__":
    main()
