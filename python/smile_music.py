import asyncio
import json
import re
import os
from re import match
import bs4
import discord
# import youtubedl.youtube_dl as youtube_dl
import youtube_dl
import requests
from urllib import request as req
from urllib import parse
from threading import Timer
import datetime
import logging
import shlex
import subprocess
import random
import psycopg2
# from niconico_dl_async import NicoNico as niconico_dl
from niconicodl.niconico_dl_async import NicoNico as niconico_dl
import ssl
import re
import traceback
from discord.opus import Encoder as OpusEncoder
from io import BufferedReader

log = logging.getLogger(__name__)
# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_ctx = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address':
    '0.0.0.0',  # bind to ipv4 since ipv6 addresses cause issues sometimes
    'user-agent':
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:47.0) Gecko/20100101 Firefox/47.0"
}

ffmpeg_options = {
    'before_options':
    '-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

niconico_headers = {
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ja",
    "Connection": "keep-alive",
    "Host": "nvapi.nicovideo.jp",
    "Origin": "https://www.nicovideo.jp",
    "Referer": "https://www.nicovideo.jp/",
    "sec-ch-ua-mobile": "?0",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
    "X-Frontend-Id": "6",
    "X-Frontend-Version": "0",
    "X-Niconico-Language": "ja-jp"
}

headers = {
    "User-Agent":
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:47.0) Gecko/20100101 Firefox/47.0",
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

client = discord.Client()


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.1):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False, volume=0.1):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        source = OriginalFFmpegPCMAudio(filename, **ffmpeg_options)
        return cls(source, data=data, volume=volume)


class NicoNicoDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, url, volume=0.1):
        super().__init__(source, volume)

        self.url = url

    @classmethod
    async def from_url(cls, url, *, log=False, volume=0.1):
        nico_id = url.split("/")[-1]
        niconico = niconico_dl(nico_id, log=log)
        stream_url = await niconico.get_download_link()

        source = OriginalFFmpegPCMAudio(stream_url, **ffmpeg_options)
        return (cls(source, url=stream_url, volume=volume), niconico)


class OriginalFFmpegPCMAudio(discord.FFmpegPCMAudio):
    def __init__(self,
                 source,
                 *,
                 executable='ffmpeg',
                 pipe=False,
                 stderr=None,
                 before_options=None,
                 options=None):
        self.total_milliseconds = 0
        self.source = source

        super().__init__(source,
                         executable=executable,
                         pipe=pipe,
                         stderr=stderr,
                         before_options=before_options,
                         options=options)

    def wait_buffer(self):
        self._stdout.peek(OpusEncoder.FRAME_SIZE)

    def read(self):
        ret = super().read()

        if ret:
            self.total_milliseconds += 20
        return ret

    def get_tootal_millisecond(self, seek_time):
        if seek_time:
            list = reversed([int(x) for x in seek_time.split(":")])
            total = 0
            for i, x in enumerate(list):
                total += x * 3600 if i == 2 else x * 60 if i == 1 else x
            return max(1000 * total, 0)
        else:
            raise Exception()

    def rewind(self,
               rewind_time,
               *,
               executable='ffmpeg',
               pipe=False,
               stderr=None,
               before_options=None,
               options=None):
        seek_time = str(
            int((self.total_milliseconds -
                 self.get_tootal_millisecond(rewind_time)) / 1000))

        self.seek(seek_time=seek_time,
                  executable=executable,
                  pipe=pipe,
                  stderr=stderr,
                  before_options=before_options,
                  options=options)

    def seek(self,
             seek_time,
             *,
             executable='ffmpeg',
             pipe=False,
             stderr=None,
             before_options=None,
             options=None):
        self.total_milliseconds = self.get_tootal_millisecond(seek_time)
        proc = self._process
        before_options = f"-ss {seek_time} " + before_options
        args = []
        subprocess_kwargs = {
            'stdin': self.source if pipe else subprocess.DEVNULL,
            'stderr': stderr
        }

        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))

        args.append('-i')
        args.append('-' if pipe else self.source)
        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel',
                     'warning'))

        if isinstance(options, str):
            args.extend(shlex.split(options))

        args.append('pipe:1')

        args = [executable, *args]
        kwargs = {'stdout': subprocess.PIPE}
        kwargs.update(subprocess_kwargs)

        self._process = self._spawn_process(args, **kwargs)
        self._stdout = self._process.stdout
        self.kill(proc)

    def kill(self, proc):
        if proc is None:
            return

        log.info('Preparing to terminate ffmpeg process %s.', proc.pid)

        try:
            proc.kill()
        except Exception:
            log.exception(
                "Ignoring error attempting to kill ffmpeg process %s",
                proc.pid)

        if proc.poll() is None:
            log.info(
                'ffmpeg process %s has not terminated. Waiting to terminate...',
                proc.pid)
            proc.communicate()
            log.info(
                'ffmpeg process %s should have terminated with a return code of %s.',
                proc.pid, proc.returncode)
        else:
            log.info(
                'ffmpeg process %s successfully terminated with return code of %s.',
                proc.pid, proc.returncode)


class perpetualTimer():
    def __init__(self, t, hFunction, *args):
        self.t = t
        self.args = args
        self.hFunction = hFunction
        self.thread = Timer(self.t, self.handle_function)

    def handle_function(self):
        self.hFunction(*self.args)
        self.thread = Timer(self.t, self.handle_function)
        self.thread.start()

    def start(self):
        self.thread.start()

    def cancel(self):
        self.thread.cancel()


def get_prefix_sql(key):
    with conn.cursor() as cur:
        cur.execute(f'SELECT id, prefix prefix FROM {table_name} WHERE id=%s',
                    (key, ))
        d = cur.fetchone()
        return d[1] if d and d[1] else defalut_prefix


def get_volume_sql(key):
    with conn.cursor() as cur:
        cur.execute(f'SELECT id, volume FROM {table_name} WHERE id=%s',
                    (key, ))
        d = cur.fetchone()
        return d[1] * defalut_volume if d and d[1] else defalut_volume


def set_prefix_sql(key, value):
    with conn.cursor() as cur:
        cur.execute(
            f'INSERT INTO {table_name} (id, prefix) VALUES (%s,%s) ON CONFLICT ON CONSTRAINT guilds_pkey DO UPDATE SET prefix=%s',
            (key, value, value))
    conn.commit()


def set_volume_sql(key, value):
    with conn.cursor() as cur:
        cur.execute(
            f'INSERT INTO {table_name} (id, volume) VALUES (%s,%s) ON CONFLICT ON CONSTRAINT guilds_pkey DO UPDATE SET volume=%s',
            (key, value, value))
    conn.commit()


def delete_setting_sql(key):
    with conn.cursor() as cur:
        cur.execute(f'DELETE FROM {table_name} WHERE id=%s', (key, ))
    conn.commit()


def heartbeat(*args):
    r = requests.post(url=args[0], json=args[1], headers=args[2])


def get_timestr(t):
    d = t.day - 1
    if d != 0:
        return f"{d}days " + t.strftime('%H:%M:%S')
    if t.hour != 0:
        return t.strftime('%H:%M:%S')
    else:
        return t.strftime('%M:%S')


async def join(ctx):
    if ctx.author.voice is None:
        await ctx.channel.send("あなたはボイスチャンネルに接続していません。")
        return

    await ctx.author.voice.channel.connect()
    await ctx.channel.send("接続しました。")


async def leave(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    guild_table.pop(ctx.guild.id, None)
    await ctx.guild.voice_client.disconnect()
    await ctx.channel.send("切断しました。")


def awaitable_voice_client_play(func, player, loop):
    f = asyncio.Future()
    after = lambda e: loop.call_soon_threadsafe(lambda: f.set_result(e))
    func(player, after=after)
    return f


async def play_music(ctx, url, first_seek=None):
    try:
        volume = get_volume_sql(str(ctx.guild.id))
        is_niconico = url.startswith("https://www.nicovideo.jp/")
        if is_niconico:
            player, niconico = await NicoNicoDLSource.from_url(
                url, log=env=="dev", volume=volume)
        else:
            player = await YTDLSource.from_url(url,
                                               loop=client.loop,
                                               stream=True,
                                               volume=volume)
        guild_table[ctx.guild.id]["player"] = player

        if first_seek:
            player.original.seek(**ffmpeg_options, seek_time=first_seek)
        player.original.wait_buffer()
        await awaitable_voice_client_play(ctx.guild.voice_client.play, player,
                                          client.loop)
        if is_niconico:
            niconico.close()
    except BaseException as error:
        traceback.print_exc()
        print(url)
        await ctx.channel.send("再生に失敗しました")


async def play_queue(ctx, movie_infos):
    if (not movie_infos):
        await ctx.channel.send("検索に失敗しました")
        return
    if ctx.guild.voice_client is None:
        await join(ctx)

    queue = guild_table.get(ctx.guild.id, {}).get('music_queue')
    start_index = len(queue) if queue else 0

    info = movie_infos[0]
    author = info["author"]
    movie_embed = discord.Embed()
    movie_embed.set_thumbnail(url=info["image_url"])
    infos_len = len(movie_infos)
    if infos_len <= 1:
        title = info["title"]
        url = info["url"]
        t = info["time"]
        movie_embed.add_field(name="\u200b",
                              value=f"[{title}]({url})",
                              inline=False)
        movie_embed.add_field(name="再生時間", value=f"{get_timestr(t)}")
        movie_embed.add_field(name="キューの順番", value=f"{start_index + 1}")
    else:
        for x in movie_infos[:min(3, infos_len - 1)]:
            title = x["title"]
            url = x["url"]
            movie_embed.add_field(name="\u200b",
                                  value=f"[{title}]({url})",
                                  inline=False)
        movie_embed.add_field(name="\u200b", value=f"・・・", inline=False)
        last_info = movie_infos[-1]
        title = last_info["title"]
        url = last_info["url"]
        movie_embed.add_field(name="\u200b",
                              value=f"[{title}]({url})",
                              inline=False)
        total_datetime = get_timestr(
            to_time(sum([to_total_second(x["time"]) for x in movie_infos])))
        movie_embed.add_field(name="再生時間", value=f"{total_datetime}")
        movie_embed.add_field(
            name="キューの順番",
            value=f"{start_index + 1}...{start_index + infos_len}")
        movie_embed.add_field(name="曲数", value=f"{infos_len}")
    movie_embed.set_author(name=f"{author.display_name} added",
                           icon_url=author.avatar_url)
    await ctx.channel.send(embed=movie_embed)

    if queue:
        queue.extend(movie_infos)
    else:
        guild_table[ctx.guild.id] = {
            "has_loop": False,
            "has_loop_queue": False,
            "player": None,
            "music_queue": movie_infos
        }
        while (True):
            data = guild_table.get(ctx.guild.id, {})
            if not ctx.guild.voice_client:
                guild_table.pop(ctx.guild.id, None)
                await ctx.channel.send("切断しました。")
                return
            if not data or not data['music_queue']:
                return
            current_info = data['music_queue'][0]
            await play_music(ctx,
                             current_info.get('url'),
                             first_seek=current_info.get('first_seek'))
            has_loop = guild_table.get(ctx.guild.id, {}).get('has_loop')
            has_loop_queue = guild_table.get(ctx.guild.id,
                                             {}).get('has_loop_queue')
            if not has_loop:
                x = data['music_queue'].pop(0)
                if has_loop_queue:
                    data['music_queue'].append(x)


async def stop(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    if not ctx.guild.voice_client.is_playing():
        await ctx.channel.send("再生していません。")
        return

    ctx.guild.voice_client.stop()

    await ctx.channel.send("スキップしました。")


async def show_queue(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    queue = guild_table.get(ctx.guild.id, {}).get('music_queue')
    if queue:
        queue_embed = discord.Embed()
        queue_embed.set_thumbnail(url=queue[0]["image_url"])
        total_time = sum([to_total_second(x["time"]) for x in queue])
        for i, x in enumerate(queue[:20]):
            title = x["title"]
            url = x["url"]
            t = x["time"]
            author = x["author"]
            name = "__Now Playing:__" if i == 0 else "__Up Next:__" if i == 1 else "\u200b"
            queue_embed.add_field(
                name=name,
                value=
                f"`{i + 1}.`[{title}]({url})|`{get_timestr(t)} Requested by: {author.display_name}`",
                inline=False)
        player = guild_table.get(ctx.guild.id, {}).get('player')
        current_total_time = int(player.original.total_milliseconds / 1000)
        total_time -= current_total_time
        queue_embed.add_field(
            name="\u200b", value=f"残り時間: `{get_timestr(to_time(total_time))}`")
        await ctx.channel.send(embed=queue_embed)

    else:
        await ctx.channel.send("キューは空です。")


async def show_now_playing(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    player = guild_table.get(ctx.guild.id, {}).get('player')
    queue = guild_table.get(ctx.guild.id, {}).get('music_queue')
    if player and queue:
        title = queue[0]["title"]
        url = queue[0]["url"]
        t = queue[0]["time"]
        author = queue[0]["author"]
        current_time = to_time(player.original.total_milliseconds / 1000)
        current_time_str = get_timestr(current_time)
        end_time_str = get_timestr(t)
        movie_embed = discord.Embed()
        movie_embed.set_thumbnail(url=queue[0]["image_url"])
        movie_embed.add_field(name="\u200b",
                              value=f"[{title}]({url})",
                              inline=False)
        current_pos = int(
            to_total_second(current_time) / to_total_second(t) * 18)
        bar = ''
        for i in range(18):
            bar += '🔘' if current_pos == i else '▬'
        movie_embed.add_field(name="\u200b", value=bar, inline=False)
        movie_embed.add_field(name="\u200b",
                              value=f"`{current_time_str}/{end_time_str}`",
                              inline=False)
        movie_embed.set_author(name=f"{author.display_name} added",
                               icon_url=author.avatar_url)
        if (url.startswith("https://www.nicovideo.jp/")):
            movie_embed.add_field(name="\u200b",
                                  value=",".join(
                                      [f"`[{tag}]`" for tag in get_tags(url)]),
                                  inline=False)
        await ctx.channel.send(embed=movie_embed)
    else:
        await ctx.channel.send("現在再生していません。")


async def seek(ctx, t):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    player = guild_table.get(ctx.guild.id, {}).get('player')
    if player:
        ctx.guild.voice_client.pause()
        try:
            player.original.seek(**ffmpeg_options, seek_time=t)
            player.original.wait_buffer()
        except:
            await ctx.channel.send("無効な形式です。")
        finally:
            ctx.guild.voice_client.resume()
    else:
        await ctx.channel.send("現在再生していません。")


async def rewind(ctx, t):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    player = guild_table.get(ctx.guild.id, {}).get('player')
    if player:
        try:
            player.original.rewind(**ffmpeg_options, rewind_time=t)
        except:
            await ctx.channel.send("無効な形式です。")
    else:
        await ctx.channel.send("現在再生していません。")


async def loop(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        value = not data.get("has_loop")
        data["has_loop"] = value
        if (value):
            await ctx.channel.send("ループが有効になりました。")
        else:
            await ctx.channel.send("ループが無効になりました。")
    else:
        await ctx.channel.send("現在再生していません。")


async def loopqueue(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        value = not data.get("has_loop_queue")
        data["has_loop_queue"] = value
        if (value):
            await ctx.channel.send("キューループが有効になりました。")
        else:
            await ctx.channel.send("キューループが無効になりました。")
    else:
        await ctx.channel.send("現在再生していません。")


async def clear(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        data['music_queue'] = data['music_queue'][:1]
        await ctx.channel.send("キューを空にしました。")
    else:
        await ctx.channel.send("キューは空です。")


async def shuffle(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        data['music_queue'] = data['music_queue'][:1] + random.sample(
            data['music_queue'][1:],
            len(data['music_queue']) - 1)
        await ctx.channel.send("キューをシャッフルしました。")
    else:
        await ctx.channel.send("キューは空です。")


async def skipto(ctx, index):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        if index < 2 or index > len(data['music_queue']):
            await ctx.channel.send("キューの範囲外です。")
            return
        data['music_queue'] = data['music_queue'][:1] + data['music_queue'][
            index - 1:]
        await stop(ctx)
        await ctx.channel.send(f"キューを{index}番目まで飛ばしました。")
    else:
        await ctx.channel.send("キューは空です。")


async def remove(ctx, index):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    data = guild_table.get(ctx.guild.id)
    if data:
        if index < 2 or index > len(data['music_queue']):
            await ctx.channel.send("キューの範囲外です。")
            return
        data['music_queue'].pop(index - 1)
        await ctx.channel.send(f"キューの{index}番目を削除しました")
    else:
        await ctx.channel.send("キューは空です。")


async def pause(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    if ctx.guild.voice_client.is_paused():
        await resume(ctx)
        return

    if not ctx.guild.voice_client.is_playing():
        await ctx.channel.send("再生していません。")
        return

    ctx.guild.voice_client.pause()

    await ctx.channel.send("一時停止しました、resumeまたはpauseコマンドで解除できます")


async def resume(ctx):
    if ctx.guild.voice_client is None:
        await ctx.channel.send("接続していません。")
        return

    ctx.guild.voice_client.resume()

    await ctx.channel.send("再生を再開しました。")


async def play(ctx, args, add_infos={}):
    optionbases = [x for x in args if x.startswith('-')]
    args = [i for i in args if i not in optionbases]
    options = ''.join([x[1:] for x in optionbases])

    sort = next((x for x in ['h', 'f', 'm', 'n'] if x in options), 'v')

    slice_dict = {}
    if len(args) >= 4 and args[1].isdecimal() and args[2].isdecimal():
        slice_dict = {"start": int(args[1]) - 1, "stop": int(args[2])}
        del (args[1:3])
    elif len(args) >= 3 and args[1].isdecimal():
        slice_dict = {"start": int(args[1]) - 1, "stop": int(args[1])}
        del (args[1])

    keyword = ' '.join(args[1:])

    if niconico_id_pattern.match(args[1]):
        args[1] = f"https://www.nicovideo.jp/watch/{args[1]}"

    result = niconico_pattern.subn('https://www.nicovideo.jp', args[1])
    args[1] = result[0]
    result = niconico_ms_pattern.subn('https://www.nicovideo.jp/watch',
                                      args[1])
    args[1] = result[0]

    movie_infos = None

    try:
        if args[1].startswith("https://www.nicovideo.jp/search"):
            movie_infos = niconico_infos_from_search(args[1], **slice_dict)
        elif args[1].startswith("https://www.nicovideo.jp/tag"):
            movie_infos = niconico_infos_from_search(args[1], **slice_dict)
        elif args[1].startswith("https://www.nicovideo.jp/series"):
            movie_infos = niconico_infos_from_series(args[1], **slice_dict)
        elif re.match("https://www.nicovideo.jp/.*/mylist/.*", args[1]):
            movie_infos = niconico_infos_from_mylist(args[1], **slice_dict)
        elif args[1].startswith("https://www.nicovideo.jp/watch"):
            movie_infos = niconico_infos_from_video_url(args[1])
        elif re.match("https?://.*", args[1]):
            movie_infos = await infos_from_ytdl(args[1], client.loop)
        elif "y" in options:
            movie_infos = await infos_from_ytdl(keyword, client.loop)
        elif "t" in options:
            movie_infos = niconico_infos_from_search(
                get_tag_url(keyword, sort), **slice_dict)
        else:
            movie_infos = niconico_infos_from_search(
                get_keyword_url(keyword, sort), **slice_dict)
        for info in movie_infos:
            info["author"] = ctx.author
            info.update(add_infos)
    except:
        traceback.print_exc()
        print(args)
        await ctx.channel.send("検索に失敗しました。")
        return

    await play_queue(ctx, movie_infos)


async def set_prefix(ctx, key, value):
    try:
        set_prefix_sql(key, value)
        client_id = client.user.id
        bot_name = client.user.name
        await set_nick(ctx.guild, client_id, bot_name, force=True)
        await ctx.channel.send("prefixを変更しました。")
    except:
        traceback.print_exc()
        await ctx.channel.send("prefixの変更に失敗しました")


async def set_volume(ctx, key, value):
    try:
        volume = float(value)
        set_volume_sql(key, volume)
        client_id = client.user.id
        bot_name = client.user.name
        await set_nick(ctx.guild, client_id, bot_name, force=True)
        await ctx.channel.send("音量を変更しました。")
    except:
        traceback.print_exc()
        await ctx.channel.send("音量の変更に失敗しました")


async def delete_setting(ctx, key):
    try:
        delete_setting_sql(key)
        client_id = client.user.id
        bot_name = client.user.name
        await set_nick(ctx.guild, client_id, bot_name, force=True)
        await ctx.channel.send("全ての設定を削除しました。")
    except:
        traceback.print_exc()
        await ctx.channel.send("設定の削除に失敗しました")


async def set_nick(guild, client_id, bot_name, force=False):
    try:
        member = guild.get_member(client_id)
        if not member or (not force and member.nick
                          and member.nick != bot_name):
            return
        key = str(guild.id)
        nick = '-'.join([
            get_prefix_sql(key),
            '{:.1f}'.format(get_volume_sql(key) / defalut_volume), bot_name
        ])
        await member.edit(nick=nick)
    except:
        pass


async def help(ctx):
    help_embed = discord.Embed(title="SmilePlayer")
    help_embed.add_field(
        name="\u200b",
        value=
        ":white_check_mark:コマンド一覧は[こちら](https://github.com/akomekagome/SmilePlayer/blob/main/README.md)"
    )
    help_embed.add_field(
        name="\u200b",
        value=
        ":computer: 質問, 要望などは、[こちら](https://discord.gg/uVp6Aajqd7)のdiscordサーバーからお願いします！",
        inline=False)
    await ctx.channel.send(embed=help_embed)


def get_keyword_url(keyword, sort='v'):
    urlKeyword = parse.quote(keyword)
    url = f"https://www.nicovideo.jp/search/{urlKeyword}?sort={sort}"
    return url


def get_tag_url(keyword, sort='v'):
    urlKeyword = parse.quote(keyword)
    url = f"https://www.nicovideo.jp/tag/{urlKeyword}?sort={sort}"
    return url


def to_time(total_second):
    total_second = int(total_second)
    day = total_second / 86400
    total_second %= 86400
    hour = total_second / 3600
    total_second %= 3600
    minute = total_second / 60
    total_second %= 60
    second = total_second

    return datetime.datetime(year=datetime.MINYEAR,
                             month=1,
                             day=int(day) + 1,
                             hour=int(hour),
                             minute=int(minute),
                             second=second)


def to_total_second(t):

    return (t.day - 1) * 86400 + t.hour * 3600 + t.minute * 60 + t.second


def get_tags(url):
    r = requests.get(url)
    html = r.text
    soup = bs4.BeautifulSoup(html, "html.parser")
    soup = soup.select_one('meta[name="keywords"]')
    return soup.get("content").split(",")


def niconico_infos_from_search(url, start=0, stop=1):
    movie_infos = []
    r = requests.get(url)
    html = r.text
    soup = bs4.BeautifulSoup(html, "html.parser")
    soup = soup.select('li[data-video-id^="sm"]')
    for s in soup[start:stop]:
        item_thumb_box = s.select_one(".itemThumbBox")
        item_thumb = item_thumb_box.select_one(".itemThumb")
        id = item_thumb.get("data-id")
        url = "https://www.nicovideo.jp/watch/" + id
        thumb = item_thumb.select_one('.thumb')
        image_url = thumb.get("data-original")
        title = thumb.get("alt")
        time_str = item_thumb_box.select_one(".videoLength").contents[0].split(
            ':')
        total_second = int(time_str[0]) * 60 + int(time_str[1])
        t = to_time(total_second)
        info = {"url": url, "title": title, "image_url": image_url, "time": t}
        movie_infos.append(info)

    return movie_infos


def niconico_infos_from_mylist(url, start=None, stop=None):
    movie_infos = []
    parse_url = parse.urlparse(url)
    mylist_id = parse_url[2].split('/')[-1]
    r = requests.get(
        f"https://nvapi.nicovideo.jp/v2/mylists/{mylist_id}?pageSize=25000&page=1",
        headers=niconico_headers)
    response = r.text
    j = json.loads(response)
    items = j["data"]["mylist"]["items"]
    for item in items[start:stop]:
        video = item["video"]
        id = video["id"]
        url = "https://www.nicovideo.jp/watch/" + id
        title = video["title"]
        image_url = video["thumbnail"]["listingUrl"]
        if not image_url:
            print(video["thumbnail"])
        total_second = video["duration"]
        t = to_time(total_second)
        info = {"url": url, "title": title, "image_url": image_url, "time": t}
        movie_infos.append(info)

    return movie_infos


def niconico_infos_from_series(url, start=None, stop=None):
    movie_infos = []
    r = requests.get(url)
    html = r.text
    soup = bs4.BeautifulSoup(html, "html.parser")
    soup = soup.select('.NC-MediaObject')
    for s in soup[start:stop]:
        link = s.select_one(".NC-Link")
        thumbnail = s.select_one(".NC-Thumbnail")
        thumbnail_image = thumbnail.select_one(".NC-Thumbnail-image")
        url = "https://www.nicovideo.jp/" + link.get("href")
        image_url = thumbnail_image.get("data-background-image")
        title = thumbnail_image.get("aria-label")
        time_str = thumbnail.select_one(".NC-VideoLength").contents[0].split(':')
        total_second = int(time_str[0]) * 60 + int(time_str[1])
        t = to_time(total_second)
        info = {"url": url, "title": title, "image_url": image_url, "time": t}
        movie_infos.append(info)

    return movie_infos


def niconico_infos_from_video_url(url):
    movie_infos = []
    r = req.Request(url=url, headers=headers)
    page = req.urlopen(r)
    html = page.read()
    page.close()
    soup = bs4.BeautifulSoup(html, "html.parser")
    soup = soup.select_one('script[type="application/ld+json"]')
    j = json.loads(soup.contents[0])
    url = j["url"]
    title = j["name"]
    image_url = j["thumbnailUrl"][0]
    total_second = int(j["duration"][2:-1])
    t = to_time(total_second)
    info = {"url": url, "title": title, "image_url": image_url, "time": t}
    movie_infos.append(info)

    return movie_infos


async def infos_from_ytdl(url, loop=None):
    movie_infos = []
    loop = loop or asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, lambda: ytdl.extract_info(url, download=False))

    if 'entries' in data:
        data = data['entries'][0]

    thumbnails = data.get("thumbnails")
    image_url = thumbnails[0].get("url") if thumbnails else None

    info = {
        "url": url,
        "title": data["title"],
        "image_url": image_url,
        "time": to_time(int(data["duration"]))
    }
    movie_infos.append(info)

    return movie_infos


@client.event
async def on_ready():
    await client.change_presence(activity=discord.Game(
        f'{defalut_prefix}help {str(len(client.guilds))}サーバー'))
    print("ready!")


@client.event
async def on_guild_join(guild):
    await client.change_presence(activity=discord.Game(
        f'{defalut_prefix}help {str(len(client.guilds))}サーバー'))
    client_id = client.user.id
    bot_name = client.user.name
    await set_nick(guild, client_id, bot_name)

@client.event
async def on_guild_remove(guild):
    key = str(guild.id)
    delete_setting_sql(key)


@client.event
async def on_message(ctx):
    if ctx.author.bot:
        return

    key = str(ctx.guild.id)
    prefix = get_prefix_sql(key)
    args = re.split('[\u3000 \t]+', ctx.content)
    if ((not args) | (not args[0].startswith(prefix))):
        return
    args[0] = args[0][len(prefix):].lower()

    if args[0] == "join":
        await join(ctx)
    elif any([x == args[0] for x in ["leave", "disconnect"]]):
        await leave(ctx)
    elif any([x == args[0] for x in ["p"]]) and len(args) >= 2:
        await play(ctx, args)
    elif args[0] == "py" and len(args) >= 2:
        args.insert(1, "-y")

        await play(ctx, args)
    elif args[0] == "pseek" and len(args) >= 3:
        first_seek = args[1]
        del (args[1])

        await play(ctx, args, add_infos={"first_seek": first_seek})
    elif args[0] == "q":
        await show_queue(ctx)
    elif any([x == args[0] for x in ["s", "fs"]]):
        await stop(ctx)
    elif args[0] == "np":
        await show_now_playing(ctx)
    elif args[0] == "pause":
        await pause(ctx)
    elif args[0] == "resume":
        await resume(ctx)
    elif args[0] == "seek" and len(args) >= 2:
        await seek(ctx, args[1])
    elif args[0] == "rewind" and len(args) >= 2:
        await rewind(ctx, args[1])
    elif args[0] == "loop":
        await loop(ctx)
    elif args[0] == "loopqueue":
        await loopqueue(ctx)
    elif args[0] == "set_volume" and len(args) >= 2:
        await set_volume(ctx, key, args[1])
    elif args[0] == "set_prefix" and len(args) >= 2:
        await set_prefix(ctx, key, args[1])
    elif args[0] == "delete_setting":
        await delete_setting(ctx, key)
    elif args[0] == "clear":
        await clear(ctx)
    elif args[0] == "shuffle":
        await shuffle(ctx)
    elif args[0] == "skipto" and len(args) >= 2 and args[1].isdecimal():
        await skipto(ctx, int(args[1]))
    elif args[0] == "remove" and len(args) >= 2 and args[1].isdecimal():
        await remove(ctx, int(args[1]))
    elif args[0] == "help":
        await help(ctx)
    elif args[0] == "debug":
        if env != "dev":
            return

        pass


table_name = 'guilds'
defalut_volume = 0.1
guild_table = {}
ssl._create_default_https_context = ssl._create_unverified_context
conn = psycopg2.connect(host=os.environ.get('POSTGRES_HOST'), user=os.environ.get('POSTGRES_USER'), password=os.environ.get('POSTGRES_PASSWORD'), database=os.environ.get('POSTGRES_DB'), port=int(os.environ.get('POSTGRES_PORT')))
niconico_pattern = re.compile(r'https://(www.nicovideo.jp|sp.nicovideo.jp)')
niconico_ms_pattern = re.compile(r'https://nico.ms')
niconico_id_pattern = re.compile(r'^[a-z]{2}[0-9]+$')

token = os.environ['SMILEMUSIC_DISCORD_TOKEN']
defalut_prefix = os.environ['SMILEMUSIC_PREFIX']
env = os.environ['SMILEMUSIC_ENV']
client.run(token)