配信サイトの配信を簡単に録画できるソフトウェアです。

## 対応プラットフォーム
- Twitch
- YouTube
- ツイキャス
- ニコニコ生放送
#### 以下のプラットフォームは順次開放予定
- TikTok
- Kick
- AbemaTV　
- radiko
- OPENREC
- BiliBili
- 17LIVE
- ふわっち

### 必要なツール

https://www.ffmpeg.org/download.html
からWindows用のffmpegをダウンロードし、インストールしてください。インストール後、ffmpegのパスをシステム環境変数に追加してください。
非対応サイト向けのフォールバック録画を使う場合は、yt-dlp もインストールしてください。

### 注意事項
YouTube Data APIの使用制限された場合、APIからAPI無しでの録画に自動的に切り替わります。
ただし、複数の配信枠を同時に録画する場合、APIは必須です。
