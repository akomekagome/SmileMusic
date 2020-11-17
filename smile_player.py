import asyncio
import json
import re
import os
from re import match
import bs4
import discord
import youtubedl.youtube_dl as youtube_dl
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
	'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
	'before_options': '-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):

	def __init__(self, source, *, data, volume=0.1):
		super().__init__(source, volume)

		self.data = data

		self.title = data.get('title')
		self.url = data.get('url')

	@classmethod
	async def from_url(cls, url, *, loop=None, stream=False, volume = 0.1):
		loop = loop or asyncio.get_event_loop()
		data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

		if 'entries' in data:
			data = data['entries'][0]

		filename = data['url'] if stream else ytdl.prepare_filename(data)
		id = data.get('session_id')
		t = None
		if id:
			url = f"https://api.dmc.nico/api/sessions/{id}?_format=json&_method=PUT"
			requests.options(url)
			json = data['session']
			headers = {'Content-Type': 'application/json'}
			t = perpetualTimer(40, heartbeat, url, json, headers)
			t.start()
		source = OriginalFFmpegPCMAudio(filename, **ffmpeg_options)
		return (cls(source, data=data, volume=volume), t)

class OriginalFFmpegPCMAudio(discord.FFmpegPCMAudio):

	def __init__(self, source, *, executable='ffmpeg', pipe=False, stderr=None, before_options=None, options=None):
		self.total_milliseconds = 0
		self.source = source

		super().__init__(source, executable=executable, pipe=pipe, stderr=stderr, before_options=before_options, options=options)

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

	def rewind(self, rewind_time, *, executable='ffmpeg', pipe=False, stderr=None, before_options=None, options=None):
		seek_time = str(int((self.total_milliseconds - self.get_tootal_millisecond(rewind_time)) / 1000))

		self.seek(seek_time=seek_time, executable=executable, pipe=pipe, stderr=stderr, before_options=before_options, options=options)

	def seek(self, seek_time, *, executable='ffmpeg', pipe=False, stderr=None, before_options=None, options=None):
		print(seek_time)
		self.total_milliseconds = self.get_tootal_millisecond(seek_time)
		proc = self._process
		before_options = f"-ss {seek_time} " + before_options
		args = []
		subprocess_kwargs = {'stdin': self.source if pipe else subprocess.DEVNULL, 'stderr': stderr}

		if isinstance(before_options, str):
			args.extend(shlex.split(before_options))

		args.append('-i')
		args.append('-' if pipe else self.source)
		args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'warning'))

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
			log.exception("Ignoring error attempting to kill ffmpeg process %s", proc.pid)

		if proc.poll() is None:
			log.info('ffmpeg process %s has not terminated. Waiting to terminate...', proc.pid)
			proc.communicate()
			log.info('ffmpeg process %s should have terminated with a return code of %s.', proc.pid, proc.returncode)
		else:
			log.info('ffmpeg process %s successfully terminated with return code of %s.', proc.pid, proc.returncode)

class perpetualTimer():

	def __init__(self,t,hFunction, *args):
		self.t=t
		self.args = args
		self.hFunction = hFunction
		self.thread = Timer(self.t,self.handle_function)

	def handle_function(self):
		self.hFunction(*self.args)
		self.thread = Timer(self.t,self.handle_function)
		self.thread.start()

	def start(self):
		self.thread.start()

	def cancel(self):
		self.thread.cancel()

defalut_prefix = '?'
table_name = 'guilds'
defalut_volume = 0.1
guild_table = {}
client = discord.Client()
db_url = os.environ['SMILEPLAYER_DATABASE_URL']
conn = psycopg2.connect(db_url)

def get_prefix_sql(key):
	with conn.cursor() as cur:
		cur.execute(f'SELECT id, prefix prefix FROM {table_name} WHERE id=%s', (key, ))
		d = cur.fetchone()
		return d[1] if d and d[1] else defalut_prefix

def get_volume_sql(key):
	with conn.cursor() as cur:
		cur.execute(f'SELECT id, volume FROM {table_name} WHERE id=%s', (key, ))
		d = cur.fetchone()
		return d[1] * defalut_volume if d and d[1] else defalut_volume

def set_prefix_sql(key, value):
	with conn.cursor() as cur:
		cur.execute(f'INSERT INTO {table_name} (id, prefix) VALUES (%s,%s) ON CONFLICT ON CONSTRAINT guilds_pkey DO UPDATE SET prefix=%s', (key, value, value))
	conn.commit()

def set_volume_sql(key, value):
	with conn.cursor() as cur:
		cur.execute(f'INSERT INTO {table_name} (id, volume) VALUES (%s,%s) ON CONFLICT ON CONSTRAINT guilds_pkey DO UPDATE SET volume=%s', (key, value, value))
	conn.commit()

def heartbeat(*args):
	r = requests.post(url = args[0], json = args[1], headers=args[2])

def get_timestr(t):
	return t.strftime('%M:%S') if t.hour == 0 else t.strftime('%H:%M:%S')

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

	await ctx.guild.voice_client.disconnect()

	await ctx.channel.send("切断しました。")

def awaitable_voice_client_play(func, player, loop):
	f = asyncio.Future()
	after = lambda e: loop.call_soon_threadsafe(lambda: f.set_result(e))
	func(player, after = after)
	return f

async def play_music(ctx, url):
	try:
		volume = get_volume_sql(str(ctx.guild.id))
		player, t = await YTDLSource.from_url(url, loop=client.loop, stream=True, volume=volume)
		guild_table[ctx.guild.id]["player"] = player
		e = await awaitable_voice_client_play(ctx.guild.voice_client.play, player, client.loop)
		if t:
			t.cancel()
	except:
		await ctx.channel.send("再生に失敗しました")

async def play_queue(ctx, movie_infos):
	if(not movie_infos):
		await ctx.channel.send("検索に失敗しました")
		return
	if ctx.guild.voice_client is None:
		await join(ctx)

	for info in movie_infos:
		title = info["title"]
		url = info["url"]
		t = info["time"]
		author = info["author"]
		movie_embed = discord.Embed(title="\u200b",description = f"[{title}]({url})")
		movie_embed.set_thumbnail(url= info["image_url"])
		movie_embed.add_field(name="再生時間", value=f"{get_timestr(t)}")
		movie_embed.set_author(name=f"{author.display_name} added", icon_url=author.avatar_url)
		await ctx.channel.send(embed = movie_embed)

	queue = guild_table.get(ctx.guild.id, {}).get('music_queue')
	if queue:
		queue.extend(movie_infos)
	else:
		guild_table[ctx.guild.id] = {"has_loop": False, "has_loop_queue": False, "player": None, "music_queue": movie_infos}
		while(True):
			data = guild_table.get(ctx.guild.id, {})
			if not data['music_queue']:
				return
			await play_music(ctx, data['music_queue'][0]["url"])
			has_loop = guild_table.get(ctx.guild.id, {}).get('has_loop')
			has_loop_queue = guild_table.get(ctx.guild.id, {}).get('has_loop_queue')
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
		queue_embed.set_thumbnail(url= queue[0]["image_url"])
		for i, x in enumerate(queue):
			title = x["title"]
			url = x["url"]
			t = x["time"]
			author = x["author"]
			name = "__Now Playing:__" if i == 0 else "__Up Next:__" if i == 1 else "\u200b"
			queue_embed.add_field(name=name, value=f"`{i + 1}.`[{title}]({url})|`{get_timestr(t)}` Requested by: {author.display_name}",inline=False)
		await ctx.channel.send(embed = queue_embed)
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
		movie_embed = discord.Embed(title="\u200b",description = f"[{title}]({url})")
		movie_embed.set_thumbnail(url= queue[0]["image_url"])
		current_pos = int(to_total_second(current_time) / to_total_second(t) * 20)
		bar = ''
		for i in range(20):
			bar += '🔘' if current_pos == i else '▬'
		movie_embed.add_field(name=bar, value=f"`{current_time_str}/{end_time_str}`",inline=False)
		movie_embed.set_author(name=f"{author.display_name} added", icon_url=author.avatar_url)
		if(url.startswith("https://www.nicovideo.jp/")):
			movie_embed.add_field(name="\u200b", value = ",".join([f"`[{tag}]`" for tag in get_tags(url)]),inline=False)
		await ctx.channel.send(embed = movie_embed)
	else:
		await ctx.channel.send("現在再生していません。")

async def seek(ctx, t):
	if ctx.guild.voice_client is None:
		await ctx.channel.send("接続していません。")
		return

	player = guild_table.get(ctx.guild.id, {}).get('player')
	if player:
		try:
			player.original.seek(**ffmpeg_options, seek_time =t)
		except:
			await ctx.channel.send("無効な形式です。")
	else:
		await ctx.channel.send("現在再生していません。")

async def rewind(ctx, t):
	if ctx.guild.voice_client is None:
		await ctx.channel.send("接続していません。")
		return

	player = guild_table.get(ctx.guild.id, {}).get('player')
	if player:
		try:
			player.original.rewind(**ffmpeg_options, rewind_time =t)
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
		if(value):
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
		if(value):
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
		data['music_queue'] = data['music_queue'][:1] + random.sample(data['music_queue'][1:], len(data['music_queue']) - 1)
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
		data['music_queue'] = data['music_queue'][:1] + data['music_queue'][index - 1:]
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

async def set_prefix(ctx, key, value):
	try:
		set_prefix_sql(key, value)
		await ctx.channel.send("prefixを変更しました。")
	except:
		await ctx.channel.send("prefixの変更に失敗しました")

async def set_volume(ctx, key, value):
	try:
		volume = float(value)
		set_volume_sql(key, volume)
		await ctx.channel.send("音量を変更しました。")
	except:
		await ctx.channel.send("音量の変更に失敗しました")

def search_keyword_url(keyword, sort = 'v'):
	urlKeyword = parse.quote(keyword)
	url = f"https://www.nicovideo.jp/search/{urlKeyword}?sort={sort}"
	return url

def search_tag_url(keyword, sort = 'v'):
	urlKeyword = parse.quote(keyword)
	url = f"https://www.nicovideo.jp/tag/{urlKeyword}?sort={sort}"
	return url

def to_time(total_second):
	total_second = int(total_second)
	hour = total_second / 3600
	total_second %= 3600
	minute = total_second / 60
	total_second %= 60
	second = total_second

	return datetime.time(hour = int(hour), minute = int(minute), second = second)

def to_total_second(t):

	return t.hour * 3600 + t.minute * 60 + t.second

def get_tags(url):
	r = requests.get(url)
	html = r.text
	soup = bs4.BeautifulSoup(html, "html.parser")
	soup = soup.select_one('meta[name="keywords"]')
	return soup.get("content").split(",")

def infos_from_html(url, start = 0, stop = 1):
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
		time_str = item_thumb_box.select_one(".videoLength").contents[0].split(':')
		total_second = int(time_str[0]) * 60 + int(time_str[1])
		t = to_time(total_second)
		info = {"url": url, "title": title, "image_url": image_url, "time": t}
		movie_infos.append(info)

	return movie_infos

def infos_from_json(url, start = 0, stop = 1):
	movie_infos = []
	headers = {"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:47.0) Gecko/20100101 Firefox/47.0",}
	r = req.Request(url=url, headers=headers)
	page = req.urlopen(r)
	html = page.read()
	page.close()
	soup = bs4.BeautifulSoup(html, "html.parser")
	soup = soup.select_one('script[type="application/ld+json"]')
	j = json.loads(soup.contents[0])
	elements = j['itemListElement']
	for elem in elements[start:stop]:
		url = elem["url"]
		title = elem["name"]
		image_url = elem["thumbnailUrl"][2]
		total_second = int(elem["duration"][2:-1])
		t = to_time(total_second)
		info = {"url": url, "title": title, "image_url": image_url, "time": t}
		movie_infos.append(info)

	return movie_infos

async def infos_from_ytdl(url, loop = None):
	movie_infos = []
	loop = loop or asyncio.get_event_loop()
	data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

	if 'entries' in data:
		data = data['entries'][0]

	thumbnails = data.get("thumbnails")
	image_url = thumbnails[0].get("url") if thumbnails else None

	info = {"url": url, "title": data["title"], "image_url": image_url, "time": to_time(int(data["duration"]))}
	movie_infos.append(info)

	return movie_infos

@client.event
async def on_ready():
	print('導入サーバー数: ' + str(len(client.guilds)))

@client.event
async def on_message(ctx):
	if ctx.author.bot:
		return

	key = str(ctx.guild.id)
	prefix = get_prefix_sql(key)
	args = re.split('[\u3000 \t]+', ctx.content)
	if((not args) | (not args[0].startswith(prefix))):
		return
	args[0] = args[0][len(prefix):].lower()

	if args[0] == "join":
		await join(ctx)
	elif args[0] == "leave" or args[0] == "disconnect":
		await leave(ctx)
	elif any([x == args[0] for x in ["p"]]) and len(args) >= 2:
		optionbases = [x for x in args if x.startswith('-')]
		args = [i for i in args if i not in optionbases]
		options = ''.join([x[1:] for x in optionbases])

		if len(args) >= 4 and args[1].isdecimal() and args[2].isdecimal():
			slice_dict = {"start": int(args[1]) - 1, "stop": int(args[2])}
			args = args[2:]
		elif len(args) >= 3 and args[1].isdecimal():
			slice_dict = {"start": int(args[1]) - 1, "stop": int(args[1])}
			args = args[1:]
		else:
			slice_dict = {}

		keyword = ' '.join(args[1:])
		sort = next((x for x in ['h', 'f', 'm', 'n'] if x in options), 'v')
		try:
			if args[1].startswith("https://www.nicovideo.jp/search"):
				movie_infos = infos_from_html(args[1], **slice_dict)
			elif args[1].startswith("https://www.nicovideo.jp/tag"):
				movie_infos = infos_from_json(args[1], **slice_dict)
			elif re.match("https://www.nicovideo.jp/(.*)/mylist", args[1]):
				movie_infos = infos_from_json(args[1], **slice_dict if slice_dict else {"start": 0, "stop": 100})
			elif re.match("https?://", args[1]):
				movie_infos = await infos_from_ytdl(args[1], client.loop)
			elif "t" in options:
				movie_infos = infos_from_json(search_tag_url(keyword, sort), **slice_dict)
			else:
				movie_infos = infos_from_html(search_keyword_url(keyword, sort), **slice_dict)
			for info in movie_infos:
				info["author"] = ctx.author
			await play_queue(ctx, movie_infos)
		except Exception as e:
			print(e)
			await ctx.channel.send("検索に失敗しました。")
	elif args[0] == "py" and len(args) >= 2:
		url = args[1] if re.match("https?://", args[1]) else ' '.join(args[1:])
		try:
			infos = await infos_from_ytdl(url, client.loop)
			for info in infos:
				info["author"] = ctx.author
			await play_queue(ctx, infos)
		except Exception as e:
			print(e)
			await ctx.channel.send("検索に失敗しました。")
	elif args[0] == "q":
		await show_queue(ctx)
	elif args[0] == "s":
		await stop(ctx)
	elif args[0] == "np":
		await show_now_playing(ctx)
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
	elif args[0] == "clear":
		await clear(ctx)
	elif args[0] == "shuffle":
		await shuffle(ctx)
	elif args[0] == "skipto" and len(args) >= 2 and args[1].isdecimal():
		await skipto(ctx, int(args[1]))
	elif args[0] == "remove" and len(args) >= 2 and args[1].isdecimal():
		await remove(ctx, int(args[1]))

token = os.environ['SMILEPLAYER_DISCORD_TOKEN']
client.run(token)