# 采配スコア (saihai-score)

NPB全試合の「監督の采配」(バント・スクイズ・強攻・代打・代走・継投・申告敬遠)を、
指示を出した瞬間の期待値変化で毎晩自動採点するエンジン。
結果論は使わない——ヒットでも分の悪い賭けならマイナス、失敗しても正しい指示ならプラス。

毎晩のカードは 𝕏 [@saihaiscore_lab](https://x.com/saihaiscore_lab) で公開(試験運用中β)。

## 仕組み
- データ: NPB公式の公開記録より自動集計。当季実測RE表・得点確率表・選手個人の減衰成績・
  投手文脈(巡目劣化・連投・盗塁許容)・走者の走力を使用。7回以降の接戦は得点確率でも判定
- `data/events/` は試合の解析済み派生データ(打席の状態遷移等)。ページ原文は収録しない
- 毎晩GitHub Actionsが試合終了を検知してカードを生成・配達する

## 主要スクリプト
| 役割 | ファイル |
|---|---|
| 采配の期待値評価 | `src/phase1.py` |
| 打席ログDB / RE表 / 投手文脈 / 走力 | `src/palog.py` `src/retab.py` `src/pitcher_ctx.py` `src/runpower.py` |
| カード画像生成 | `src/build_card2.py` |
| 見張り→配達 | `src/cloud_plan.py` `src/cloud_watch.py` `src/discord_send.py` |

計算方法の詳細解説はnoteで順次公開予定。
