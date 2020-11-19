# SmilePlayer
ニコニコ動画に特化したDiscord向け音楽再生Botです。導入は[こちら](https://discord.com/api/oauth2/authorize?client_id=773723833387319309&permissions=8&scope=bot)から
## gif
![smile_player](https://j.gifs.com/910gW8.gif)

# コマンド一覧
各コマンド名の埋め込みurlから詳しい説明に飛べます。

|コマンド名  |内容  |
|---|---|
|[p](#p)  |指定されたurl, キーワードから曲を再生します。 [対応サイト](https://ytdl-org.github.io/youtube-dl/supportedsites.html)(youtube, ニコニコ動画, SoundCloud...)|
|q  |キューを表示します。|
|np  |現在再生中の曲情報を表示します。ニコニコ動画だった場合タグも表示されます。|
|s  |現在再生中の曲をスキップします。|
|clear  |キューを空にします。|
|seek  |指定した時間まで曲をシークします。|
|rewind  |指定した時間分曲を戻します。|
|join  |ボットを音声チャネルに呼び出します。|
|leave  |ボットが入っている音声チャネルからボットを切断します。|
|set_volume  |ボリュームを設定します。デフォルトは「1」です。(注意: 次の曲から適用されます)|
|set_prefix  |prefixを設定します。デフォルトは「?」です。|
|loop  |現在再生している曲をループします。|
|shuffle  |キューをシャッフルします。|
|skipto  |指定された番号の曲までスキップします。|
|remove  |指定された番号の曲をキューから削除します。|
|help  |ヘルプメッセージを表示します。|

# p
## p \<url\>
指定されたurlから再生を行います。[対応サイト](https://ytdl-org.github.io/youtube-dl/supportedsites.html)(youtube, ニコニコ動画, SoundCloud...)
ニコニコ動画の場合、検索結果とマイリストから動画を再生することができます。  
### 例
ニコニコ動画を再生  
```
?p https://www.nicovideo.jp/watch/sm8628149
```
yoububeを再生  
```
?p https://www.youtube.com/watch?v=LIlZCmETvsY&list=RDEMURaO_BWBOWTU6emDAwhI3g&start_radio=1&ab_channel=NFRecordssakanaction
```
ニコニコ動画の検索結果から再生  
```
?p https://www.nicovideo.jp/search/%E9%9F%B3MAD
```
ニコニコ動画のマイリストから再生
```
?p https://www.nicovideo.jp/user/7858782/mylist/20012500
```
## p <キーワード>
指定されたキーワードから検索し、再生を行います。デフォルトはニコニコ動画のキーワード検索ですが、後述している[オプション](#オプション)でタグ検索、youtubeからの検索を行えます。
### 例
音MADでキーワード検索
```
?p 音MAD
```
## オプション
pコマンドのみオプションを指定することができます。関係ないオプションは無視されます
### オプション一覧
|オプション名  |内容  |
|---|---|
|y  |指定されたキーワードからyoutube検索を行います。|
|t  |指定されたキーワードからタグ検索を行います。|
|v  |再生回数が多い順に並べ替え(デフォルト) |
|h  |人気が高い順に並べ替え |
|f  |投稿日時が新しい順に並べ替え|
|m  |マイリストが多い順に並べ替え|
|n  |コメントが新しい順に並べ替え|
### 例
タグ検索で音MADを検索し、人気が高い順に並べ替え
```
?p -th 音MAD
```
or
```
?p -t -h 音MAD
```
## 検索結果の整形
デフォルトだと検索結果の1番目を再生しますが、カスタマイズすることができます。
### 例
音MADで検索し、3番目を再生
```
?p 3 音MAD
```
音MADで検索し、1~5番目を再生
```
?p 1 5 音MAD
```
タグ検索で音MADを検索し、人気が高い順に並べ替へ1~5番目を再生
```
?p -th 1 5 音MAD
```

