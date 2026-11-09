"""從指定的 pCloud 共用資料夾查詢原始檔案。"""

import json
import re
import unicodedata
from pathlib import PurePosixPath
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen


def file_key(value):
    return unicodedata.normalize("NFKC", value).strip().casefold().replace("\\", "/")


def model_key(value):
    return re.sub(r"[\s‐‑–−-]+", "", file_key(value))


class PublicFiles:
    def __init__(self, link):
        url = urlsplit(link)
        code = ""
        host = "api.pcloud.com"
        if url.scheme == "https":
            if url.netloc in ("my.pcloud.com", "e.pcloud.link", "u.pcloud.link", "eapi.pcloud.com"):
                params = parse_qs(url.fragment or url.query)
                code = params.get("code", [""])[0]
                if url.netloc.startswith(("e.", "eapi.")):
                    host = "eapi.pcloud.com"
            elif url.netloc == "pc.cd":
                code = url.path.strip("/")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", code):
            raise ValueError("需要 pCloud 資料夾的 HTTPS 共用連結")
        self.code = code
        self.host = host
        self._files = ()
        self._refresh_at = 0
        self._lock = Lock()

    def _request(self, method, **params):
        query = urlencode({"code": self.code, **params})
        with urlopen(f"https://{self.host}/{method}?{query}", timeout=8) as response:
            result = json.load(response)
        if result.get("result") != 0:
            raise ValueError(f"pCloud API {method} failed: {result.get('result')}")
        return result

    def _catalog(self):
        with self._lock:
            if monotonic() >= self._refresh_at:
                metadata = self._request("showpublink")["metadata"]
                if not metadata["isfolder"]:
                    raise ValueError("共用連結必須指向資料夾")
                files = []
                pending = [("", metadata)]
                while pending:
                    prefix, folder = pending.pop()
                    for child in folder["contents"]:
                        path = prefix + child["name"]
                        if child["isfolder"]:
                            pending.append((path + "/", child))
                        else:
                            files.append((int(child["fileid"]), path))
                self._files = tuple(files)
                self._refresh_at = monotonic() + 300
            return self._files

    def search(self, query, *, manual=False):
        query_key = file_key(query)
        if not query_key:
            return []
        matches = []
        for file_id, path in self._catalog():
            name = PurePosixPath(path).name
            stem = PurePosixPath(path).stem
            if query_key in (file_key(path), file_key(name), file_key(stem)):
                rank = 0
            elif manual:
                if not re.match(rf"{re.escape(model_key(query))}(?![a-z0-9])", model_key(stem)):
                    continue
                rank = 1 if name.casefold().endswith(".pdf") else 2
            elif query_key in file_key(name):
                rank = 1
            else:
                continue
            matches.append((rank, path, file_id))
        matches.sort(key=lambda entry: (entry[0], file_key(entry[1]), entry[2]))
        if matches:
            best = matches[0][0]
            return [(file_id, path) for rank, path, file_id in matches if rank == best]
        return []

    def download_url(self, file_id):
        result = self._request("getpublinkdownload", fileid=file_id, forcedownload=1)
        path = result["path"]
        if not path.startswith("/") or path.startswith("//") or any(c in path for c in "\r\n\\"):
            raise ValueError("pCloud 回傳無效的下載路徑")
        host = next((host for host in result["hosts"]
                     if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.pcloud\.com", host)), None)
        if host is None:
            raise ValueError("pCloud 回傳無效的下載主機")
        return f"https://{host}{path}"
