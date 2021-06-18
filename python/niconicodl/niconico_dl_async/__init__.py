# niconico_dl_async by tasuren

from bs4 import BeautifulSoup as bs
from asyncio import get_event_loop
from aiohttp import ClientSession
from aiofile import async_open
from json import loads, dumps
from time import time
from requests import post
from threading import Thread, Timer

version = "1.1.0"


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


def par(max_num, now):
    return now / max_num * 100


class NicoNico():
    def __init__(self, nicoid, log=False):
        self._print = lambda content, end="\n": print(content, end=end
                                                      ) if log else lambda: ""
        self.now_status = "..."
        self.url = None
        self.stop = True
        self.nicoid = nicoid
        self.now_downloading = False
        self.heartbeat_first_data = None
        self.tasks = []

    def wrap_heartbeat(self, *args):
        self.heartbeat(args[0])

    async def get_info(self):
        # 情報を取る。
        url = f"https://www.nicovideo.jp/watch/{self.nicoid}"
        self.headers = {
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Origin": "https://www.nicovideo.jp",
            'Connection': 'keep-alive',
            "Content-Type": "application/json",
            'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.72 Safari/537.36 Edg/89.0.774.45',
            'Accept': '*/*',
            "Accept-Encoding": "gzip, deflate, br",
            'Origin': 'https://www.nicovideo.jp',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            "Origin": "https://www.nicovideo.jp",
            "Referer": "https://www.nicovideo.jp/",
            "Sec-Fetch-Dest": "empty",
            'Accept-Language': 'ja,en;q=0.9,en-GB;q=0.8,en-US;q=0.7'
        }

        self._print(f"Getting niconico webpage ... : {url}")

        async with ClientSession() as session:
            async with session.get(url, headers=self.headers) as res:
                html = await res.text()
        soup = bs(html, "html.parser")

        data = soup.find("div", {
            "id": "js-initial-watch-data"
        }).get("data-api-data")
        self.data = loads(data)
        movie = self.data["media"]["delivery"]["movie"]

        # heartbeat用のdataを作る。
        session = movie["session"]
        data = {}
        data["content_type"] = "movie"
        data["content_src_id_sets"] = [{
            "content_src_ids": [{
                "src_id_to_mux": {
                    "video_src_ids": [session["videos"][0]],
                    "audio_src_ids": [session["audios"][0]]
                }
            }]
        }]
        data["timing_constraint"] = "unlimited"
        data["keep_method"] = {
            "heartbeat": {
                "lifetime": session["heartbeatLifetime"]
            }
        }
        data["recipe_id"] = session["recipeId"]
        data["priority"] = session["priority"]
        data["protocol"] = {
            "name": "http",
            "parameters": {
                "http_parameters": {
                    "parameters": {
                        "http_output_download_parameters": {
                            "use_well_known_port":
                            "yes"
                            if session["urls"][0]["isWellKnownPort"] else "no",
                            "use_ssl":
                            "yes" if session["urls"][0]["isSsl"] else "no",
                            "transfer_preset":
                            ""
                        }
                    }
                }
            }
        }
        data["content_uri"] = ""
        data["session_operation_auth"] = {
            "session_operation_auth_by_signature": {
                "token": session["token"],
                "signature": session["signature"]
            }
        }
        data["content_id"] = session["contentId"]
        data["content_auth"] = {
            "auth_type": session["authTypes"]["http"],
            "content_key_timeout": session["contentKeyTimeout"],
            "service_id": "nicovideo",
            "service_user_id": str(session["serviceUserId"])
        }
        data["client_info"] = {"player_id": session["playerId"]}

        self.heartbeat_first_data = {"session": data}

        return self.data

    def start_stream(self):
        # 定期的に生きていることをニコニコに伝えるためのもの。
        self.get = False
        c = 0

        self._print(
            "Starting heartbeat ... : https://api.dmc.nico/api/sessions?_format=json"
        )
        res = post(f"https://api.dmc.nico/api/sessions?_format=json",
                   headers=self.headers,
                   data=dumps(self.heartbeat_first_data))

        self.result_data = loads(res.text)["data"]["session"]
        session_id = self.result_data["id"]

        self.get = True

        return session_id

    def heartbeat(self, session_id):

        res = post(
            f"https://api.dmc.nico/api/sessions/{session_id}?_format=json&_method=PUT",
            headers=self.headers,
            data=dumps({"session": self.result_data}))

        if res.status_code == 201 or res.status_code == 200:
            self.result_data = loads(res.text)["data"]["session"]
        else:
            raise

    async def get_download_link(self):
        if self.stop:
            self.stop = False
            await self.get_info()
            session_id = self.start_stream()
            self.heartbeat_task = perpetualTimer(30, self.wrap_heartbeat,
                                                 session_id)
            self.heartbeat_task.start()
            self.now_downloading = True

            # 心臓が動くまで待機。
            while not self.get:
                pass

            return self.result_data["content_uri"]
        else:
            return self.result_data["content_uri"]

    async def download(self, path, chunk=1024):
        self.url = url = await self.get_download_link()

        params = (
            ("ht2_nicovideo",
             self.result_data["content_auth"]["content_auth_info"]["value"]), )
        headers = self.headers
        headers["Content-Type"] = "video/mp4"

        self._print(f"Getting file size ...")
        async with ClientSession(raise_for_status=True) as session:
            self._print(f"Starting download ... : {url}")
            async with session.get(
                    url,
                    headers=self.headers,
                    params=params,
            ) as res:

                size = res.content_length

                now_size = 0
                async with async_open(path, "wb") as f:
                    await f.write(b"")
                async with async_open(path, "ab") as f:
                    async for chunk in res.content.iter_chunked(chunk):
                        if chunk:
                            now_size += len(chunk)
                            await f.write(chunk)
                            self._print(
                                f"\rDownloading now ... : {int(now_size/size*100)}% ({now_size}/{size}) | Response status : {self.now_status}",
                                end="")
        self._print("\nDownload was finished.")
        self.now_downloading = False

    def close(self):
        self.stop = True
        self.heartbeat_task.cancel()

    def __del__(self):
        self.close()


if __name__ == "__main__":

    async def test():
        niconico = NicoNico("sm20780163", log=True)
        data = await niconico.get_info()
        print(await niconico.get_download_link())
        input()
        niconico.close()

    get_event_loop().run_until_complete(test())
