# Onsets and Frames Research Viewer

MAESTRO v3 test、アップロードしたWAV、学習済みCheckpointを比較する単一ユーザー向けViewerです。既存の `runs/` とデータセットは読み取り専用で扱い、推論結果は `outputs/viewer/` に保存します。

## Docker内で起動

既存の `onset-and-frames_rin` コンテナ内で次を実行します。

```bash
cd /home/rin/onset-and-frames
scripts/viewer/org.sh
```

既定ポートはコンテナ内の `8765` です。既存Composeでは公開していません。GPU推論はWebサーバーとは別プロセスで、ジョブごとに逐次実行されます。使用GPUを変える場合は起動前に `CUDA_VISIBLE_DEVICES=2` などを設定します。

## SSHで手元のブラウザへ転送

SSH先ホストで、コンテナのDockerブリッジIPを確認します。

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' onset-and-frames_rin
```

Windows PowerShellから、確認したコンテナIPを指定してSSHトンネルを張ります。以下はコンテナIPが `172.21.0.4` の場合に接続できた例です。`mic_ext` はWindows側で設定済みのSSH接続先名です。

```powershell
ssh -N -L 127.0.0.1:8766:172.21.0.4:8765 mic_ext
```

ブラウザで `http://localhost:8766` を開きます。`8766` はWindows側の待受ポート、`8765` はDockerコンテナ内のViewerのポートです。コンテナのIPは再作成時に変わる場合があるため、上の `docker inspect` で確認した値に置き換えてください。ViewerはlocalhostのHost/Originだけを受け付けます。既存Composeや公開ポートは変更しません。

`192.168.0.34` はSSH先ホストのLAN内IPです。Windows PCが別ネットワークにいる場合は直接接続できないことがあるため、接続できた `mic_ext` を使用します。Windows側のローカルポート `8765` では `bind [127.0.0.1]:8765: Permission denied` が発生したため、上の例では `8766` を使用しています。接続の詳細を調べるときだけ、`ssh` に `-v` を追加してください。

## 画面の使い方

1. Checkpointを2個選びます。別のCheckpointを追加・削除できます。学習条件はカードに表示されます。
2. MAESTRO v3 testの曲を選ぶか、WAVと任意のGT MIDIをアップロードします。WAVは512 MB以下、30分以下です。
3. 「推論・比較を開始」を押します。進捗、エラー、キャッシュ再利用が表示されます。
4. 曲別指標、評価済みtest曲の平均、ピアノロール、予測MIDIを確認します。重ね合わせ表示ではGTと各モデルのチェックボックスで表示対象を選べます。音声再生位置はピアノロール上の赤線と同期します。

GT MIDIがないアップロードは推論とMIDI表示だけを行います。MAESTRO v3の44.1 kHz/stereo音声は既存データセットと同じffmpeg設定で16 kHz/monoに変換します。

## 全177曲のバッチ評価

次のコマンドを**明示的に実行した場合だけ**全test曲を評価します。

```bash
scripts/viewer/eval_all.sh --model transcriber-261023-112532:190000
```

同じコマンドを再実行すると、結果JSONがある曲を飛ばして未評価分だけ処理します。複数Checkpointは `--model` を繰り返して指定します。単曲確認には `--track-id`、少数曲での確認には `--limit` が使えます。

```bash
scripts/viewer/eval_all.sh --model transcriber-261023-112532:190000 --track-id 6
```

`outputs/viewer/cache/<結果ID>/result.json` に曲別指標とピアノロール用音符列、同じ場所に予測MIDIを保存します。全体指標は、評価済み曲の各指標の算術平均です。画面には完了曲数も表示します。学習中のTensorBoard検証値は20秒程度の切り出しによる別条件です。

## 動作確認

次は小さな入力検証テストです。続くコマンドは実Checkpointで単曲を処理します。`smoke_http.sh` はViewer起動中に別ターミナルから実行してください。全177曲の評価は行いません。

```bash
scripts/viewer/check.sh
scripts/viewer/eval_all.sh --model transcriber-261023-112532:190000 --track-id 92
scripts/viewer/verify_f1.sh --model transcriber-261023-112532:190000 --track-id 92
scripts/viewer/smoke_http.sh --model transcriber-261023-112532:190000 --track-id 92
scripts/viewer/smoke_http.sh --model transcriber-261023-112532:190000 --track-id 92 --without-gt
```

2モデルのWebジョブを確認する場合は `smoke_http.sh` に `--model` を2回渡します。`smoke_http.sh` はテスト用にMAESTROの実WAVをアップロードするため、`outputs/viewer/uploads/` に新しいファイルが残ります。

## 制約

- モデル読み込みに `weights_only=False` を使うため、Checkpointは `runs/` 内の信頼済みファイルだけを選択できます。アップロードしたCheckpointは扱いません。
- GTは元MIDIを表示します。評価値の計算では既存コードと同じ32 msのラベル化と `evaluate()` を使います。
- データセットに `.pt` キャッシュがあれば読み取りだけに使い、なければメモリ内でラベルを作ります。元データへの書き込みは行いません。
- 曲全体の推論は長い曲ほど時間とGPUメモリを使います。Webジョブは一つずつ実行します。
