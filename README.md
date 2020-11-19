# SmilePlayer
ニコニコ動画に特化したDiscord向け音楽再生Botです。
導入は[こちら](https://discord.com/api/oauth2/authorize?client_id=773723833387319309&permissions=8&scope=bot)から

# コマンド一覧

|コマンド名  |内容  |
|---|---|
|p  |指定されたurl, キーワードから曲を再生します。 [対応サイト](https://ytdl-org.github.io/youtube-dl/supportedsites.html)(youtube, ニコニコ動画, SoundCloud...)|
|q  |キューを表示します。|
|np  |現在再生中の曲情報を表示します。ニコニコ動画だった場合タグも表示されます。|
|s  |現在再生中の曲をスキップします。|
|clear  |キューを空にします。|
|seek  |指定した時間まで曲をシークします。|
|rewind  |指定した時間分曲を戻します。|
|join  |ボットを音声チャネルに呼び出します。|
|leave  |ボットが入っている音声チャネルからボットを切断します。|
|set_volume  |ボリュームを設定します。デフォルトは「1」です。|
|set_prefix  |prefixを設定します。デフォルトは「?」です。|
|loop  |現在再生している曲をループします。|
|shuffle  |キューをシャッフルします。|
|skipto  |指定された番号の曲までスキップします。|
|remove  |指定された番号の曲をキューから削除します。|
|help  |ヘルプメッセージを表示します。|
