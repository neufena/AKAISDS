"""A small client for the s2k-send server (`s2kserver.py`, HTTP API version 1), which sends and receives Akai S2000 samples over SCSI from a
Raspberry Pi with a PiSCSI board. Written from the server's API.md, standard library only.

Audio over this API is raw 16-bit signed little-endian MONO PCM. s2k-send 0.7 takes only 44100 or 22050 Hz (anything else: `bad_rate`).
Names are up to 12 characters of `NAME_CHARS`.
Every call blocks: run them off the GUI thread."""

import json
import urllib.error
import urllib.request

API = "/v1"
DEFAULT_URL = "http://piscsi.local:8420"
DEFAULT_PORT = 8420
NAME_CHARS = frozenset("0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-.")
TERMINAL_STATES = ("done", "failed", "cancelled")
# the server reads a whole sample over SCSI before it sends the first byte back (no progress, no streaming in s2k-send 0.7); the
# S2000's 32 MB of RAM at an assumed ~100 KB/s read would be ~5 minutes, so a download gets far longer than an ordinary request
AUDIO_TIMEOUT_S = 900.0


class S2kError(Exception):
    """An error reply from the server (`status` is the HTTP status), or the server couldn't be reached (`status` 0)."""

    def __init__(self, status, code, message, details=None):
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def normalize_url(url):
    """What the user typed as a server address: `http://` is added when there is no scheme, the default port when there is none."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    if "://" not in url:
        url = "http://" + url
    scheme, rest = url.split("://", 1)
    host = rest.split("/", 1)[0]
    if ":" not in host.rsplit("]", 1)[-1]:
        url = f"{scheme}://{host}:{DEFAULT_PORT}" + rest[len(host):]
    return url


def akai_name(name):
    """`name` as the server accepts it: upper case, characters it can't take become spaces, at most 12, no trailing spaces."""
    upper = name.upper()[:12]
    return "".join(ch if ch in NAME_CHARS else " " for ch in upper).rstrip() or "SAMPLE"


def pcm_from_samples(samples):
    return b"".join(max(-32768, min(32767, int(s))).to_bytes(2, "little", signed=True) for s in samples)


def samples_from_pcm(pcm):
    return [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm) - 1, 2)]


class S2kClient:
    def __init__(self, base_url, timeout=120.0, opener=None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _request(self, method, path, body=None, content_type=None, timeout=None):
        request = urllib.request.Request(self.base + API + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with self._open(request, timeout=timeout or self.timeout) as reply:
                return reply.headers, reply.read()
        except urllib.error.HTTPError as e:
            data = e.read()
            try:
                error = json.loads(data)["error"]
            except (ValueError, KeyError, TypeError):
                raise S2kError(e.code, "http_error", data[:200].decode("utf-8", "replace")) from None
            raise S2kError(e.code, error.get("code", "error"), error.get("message", ""), error) from None
        except (urllib.error.URLError, OSError) as e:
            raise S2kError(0, "unreachable", f"can't reach {self.base}: {getattr(e, 'reason', e)}") from None

    def _json(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        return json.loads(self._request(method, path, body, "application/json" if body else None)[1])

    def status(self):
        return self._json("GET", "/status")

    def samples(self):
        return self._json("GET", "/samples")

    def sample(self, slot):
        return self._json("GET", f"/samples/{int(slot)}")

    def sample_audio(self, slot):
        """(info, pcm): info has name, rate, frames and root from the reply's headers; pcm is the raw audio."""
        headers, data = self._request("GET", f"/samples/{int(slot)}/audio?format=pcm", timeout=max(self.timeout, AUDIO_TIMEOUT_S))
        info = {
            "name": headers.get("X-S2K-Name"),
            "rate": int(headers.get("X-S2K-Rate", 0)),
            "frames": int(headers.get("X-S2K-Frames", 0)),
            "root": int(headers.get("X-S2K-Root", 60)),
        }
        return info, data

    def create_job(self, specs, verify=True, block=16384):
        """specs: [{name, rate, frames, optional root}]. Returns the job (state `awaiting_audio`)."""
        return self._json("POST", "/jobs", {"samples": specs, "verify": verify, "block": block})

    def upload(self, job_id, index, pcm):
        return json.loads(self._request("PUT", f"/jobs/{job_id}/samples/{index}", bytes(pcm), "application/octet-stream")[1])

    def start(self, job_id):
        return self._json("POST", f"/jobs/{job_id}/start")

    def job(self, job_id, since=0):
        return self._json("GET", f"/jobs/{job_id}?since={int(since)}")

    def cancel(self, job_id):
        """Cancels a job that isn't running yet (a running transfer can't be stopped safely)."""
        return self._json("DELETE", f"/jobs/{job_id}")
